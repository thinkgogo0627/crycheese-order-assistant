"""Time-consistent POS replay and 30-minute transfer checks."""
from collections import defaultdict
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from app.features.hourly_forecast.runtime import Engine
from app.features.hourly_forecast.intraday import HourlyPlanner, IntradayScenario, LiveSale
from app.main import app
from app.features.hourly_forecast.runtime import get_engine
ENGINE=get_engine()
DATA=ENGINE.data

DAY=date(2026,9,10)


def test_10am_has_no_completed_hour_sales_and_11am_has_s01_observation():
    p=HourlyPlanner(ENGINE)
    ten=p.plan(IntradayScenario(as_of=DAY,decision_time='10:00'))
    assert all(x['observed_completed_hours']==0 and x['adjustment_factor']==1
               for x in ten['observed'])
    assert not ten['transfers'] or all(t['arrive']=='10:30' for t in ten['transfers'])
    eleven=p.plan(IntradayScenario(as_of=DAY,decision_time='11:00'))
    sig={r['store_id']:r for r in eleven['observed']}
    assert sig['S01']['observed_completed_hours']==1
    assert sig['S03']['observed_completed_hours']==1
    assert sig['S02']['observed_completed_hours']==0
    assert eleven['hourly_forecast'][0]['updated'] != eleven['hourly_forecast'][0]['baseline']
    assert all(t['depart']=='11:00' and t['arrive']=='11:30' and t['trip_cost']==0
               for t in eleven['transfers'])
    assert eleven['predicted_avoided_lost_menu_qty']>=0


def test_future_actual_and_future_lost_not_used_at_11():
    sc=IntradayScenario(as_of=DAY,decision_time='11:00')
    base=HourlyPlanner(ENGINE).plan(sc)
    new=dict(DATA)
    sales=DATA['09_sales'].copy()
    future=(sales.date>=DAY.isoformat()) & ((sales.date>DAY.isoformat()) | (sales.hour>=11))
    for col in ['qty','cancel_qty','demand_qty','lost_qty']:
        sales.loc[future,col]=999999 if col in ('qty','demand_qty') else 0
    new['09_sales']=sales
    alternative=HourlyPlanner(Engine(new)).plan(sc)
    assert base==alternative


def test_completed_past_sales_changes_next_hour_prediction():
    sc=IntradayScenario(as_of=DAY,decision_time='11:00')
    base=HourlyPlanner(ENGINE).plan(sc)
    new=dict(DATA)
    sales=DATA['09_sales'].copy()
    observed=(sales.date==DAY.isoformat())&(sales.hour==10)&(sales.store_id=='S01')
    sales.loc[observed,'qty']=sales.loc[observed,'qty']*3
    sales.loc[observed,'cancel_qty']=0
    new['09_sales']=sales
    other=HourlyPlanner(Engine(new)).plan(sc)
    assert other['hourly_forecast']!=base['hourly_forecast']


def test_live_sales_override_and_completed_hour_validation():
    p=HourlyPlanner(ENGINE)
    asof=date(2026,10,1)
    with pytest.raises(Exception):
        p.plan(IntradayScenario(as_of=asof,decision_time='11:00'))
    live=p.plan(IntradayScenario(as_of=asof,decision_time='11:00',live_sales=[
        LiveSale(store_id='S01',menu_id='M001',hour=10,sold_qty=25)]))
    assert live['data_source']=='live_pos_snapshot'
    assert next(s for s in live['observed'] if s['store_id']=='S01')['observed_sold']==25
    with pytest.raises(Exception):
        p.plan(IntradayScenario(as_of=asof,decision_time='11:00',live_sales=[
            LiveSale(store_id='S01',menu_id='M001',hour=11,sold_qty=25)]))


def test_future_sim_cannot_recover_before_arrival_shortage():
    p=HourlyPlanner(ENGINE);e=ENGINE
    day=DAY;now=11*60;end=12*60
    store='S01';other='S03';menu='M001'
    ing=next(i for i,q in e.bom[menu].items() if q>0)
    lots=defaultdict(list)
    for i in e.items:
        lots[store,i]=[{'qty':1000000.,'expiry':day+timedelta(days=3),'lot':f's1-{i}'}]
    lots[store,ing]=[]
    lots[other,ing]=[{'qty':1000000.,'expiry':day+timedelta(days=3),'lot':'donor'}]
    f={(day,store,menu,11):10.}
    before=p._future_sim(day,now,end,f,lots)
    trip={'from_store':other,'to_store':store,'_arrive':now+30,
          '_moves':[{'item':ing,'qty':10*e.bom[menu][ing],
                     'expiry':day+timedelta(days=3),'lot':'donor'}]}
    after=p._future_sim(day,now,end,f,lots,[trip])
    assert before['unmet_menu_qty']==10
    assert after['unmet_menu_qty']==5   # The first 30 minutes cannot be recovered.
    assert sum(lot['qty'] for lot in lots[other,ing])==1000000  # Read-only plan.


def test_zero_cost_and_unnecessary_transfer_filtered():
    p=HourlyPlanner(ENGINE)
    base=p.plan(IntradayScenario(as_of=DAY,decision_time='11:00'))
    assert base['predicted_avoided_lost_menu_qty']>0
    strict=p.plan(IntradayScenario(as_of=DAY,decision_time='11:00',minimum_avoided_menu_qty=20))
    assert not strict['transfers']
    assert strict['with_transfer']==strict['without_transfer']


def test_api_and_dashboard():
    client=TestClient(app)
    response=client.post('/api/intraday_plan',json={'as_of':'2026-09-10','decision_time':'11:00',
                                               'store_id':'S01'})
    assert response.status_code==200,response.text
    payload=response.json()
    assert payload['data_source']=='historical_pos_replay'
    assert all(x['minutes']==30 for x in payload['transfers'])
