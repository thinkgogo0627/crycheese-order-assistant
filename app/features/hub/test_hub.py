"""Contract, causality and inventory conservation checks for this feature only."""
from datetime import date, timedelta
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.core.scenario import Scenario
from .planner import Planner, clean_config, take, expire, take_whole_packs
from .service import common_data, CommonForecastData, source_frames, compute

client = TestClient(app)


def test_registered_feature_and_row_contract():
    assert any(x['name']=='hub' for x in client.get('/api/features').json())
    r=client.post('/api/hub',json={})
    assert r.status_code==200,r.text
    p=r.json()
    assert p['scenario']['store_id']=='S01' and p['forecast_model']=='ewma'
    assert p['alternatives'][0]['hub_count']==0
    ids=[s for g in p['groups'] for s in g['members']]
    assert sorted(ids)==['S01','S02','S03'] and len(set(ids))==len(ids)
    for name in ('groups','alternatives','store_orders','hub_orders','transfers','shortages','emergency_orders'):
        assert all(x['basis'] for x in p[name])
    assert all(t['hub_id'].startswith('H') for t in p['transfers'])
    assert 0 <= p['fill_rate'] <= 1
    assert p['assumptions']


def test_fefo_conservation_last_day_and_whole_pack():
    d=date(2026,9,1)
    lots=[[500,d],[1500,d+timedelta(days=1)]]
    pieces,missing=take(lots,1000)
    assert sum(x[0] for x in pieces)+sum(x[0] for x in lots)==2000
    assert missing==0 and pieces[0]==[500,d]
    assert expire(lots,d+timedelta(days=1))==0
    assert expire(lots,d+timedelta(days=2))==1000
    lots=[[600,d],[400,d+timedelta(days=1)]]
    assert take_whole_packs(lots,1000,1000)==([],1000)


def test_morning_receipts_and_common_forecast():
    ds=common_data();origin=date(2026,10,1)
    receipts=ds.committed_receipts(origin)
    assert sum(r['qty'] for r in receipts if r['source']=='S01' and r['item']=='I020')==24
    for store,index in ds.si.items():
        f=ds.ingredient_forecast(origin,origin,store)
        for i,item in enumerate(ds.F.items):
            assert f[item]==ds.F.item(origin)[index,i,0]


def test_route_specific_cover_and_capacity():
    ds=common_data()
    cfg=clean_config(ds,dict(as_of='2026-09-01',max_hubs=1,scenarios=8,travel_minutes=0,
        preparation_minutes=0,receiving_minutes=0,matrix={'H01':{'S01':30}},
        capacity_liters={'chilled':0,'frozen':200,'ambient':150},
        hub_stock={'H01':{'I016':[{'qty':1000,'last_use_date':'2026-09-05'}]}}))
    p=Planner(ds,cfg)
    assert p.local_cover('S01','I016','H01')>0
    assert p.local_cover('S01','I016','H02')==0
    r=p.evaluate([0,1,2],'H01',.5)
    assert r['peak_liters']['chilled']>0 and not r['capacity_ok'] and not r['feasible']


def shortage_planner():
    ds=common_data()
    p=Planner(ds,clean_config(ds,dict(as_of='2026-09-07',store_count=1,max_hubs=0,scenarios=8)))
    key='S01','I001'  # supplier B: Monday order unavailable, Wednesday receipt
    p.initial[key]=[];p.firm[key]={};p.raw_safety[key]=0
    values=[1000. if d<=date(2026,9,8) else 0. for d in p.days]
    p.forecasts[key]=values;p.scenario_demand[key]=[list(values) for _ in p.origins]
    return p


def test_lost_today_demand_not_reordered_or_in_emergency():
    p=shortage_planner()
    line=next(x for x in p.make_store_plan('S01',0,False) if x['item']=='I001')
    assert line['needed_qty']==0  # regular receipt Wed cannot recover Mon/Tue sales
    r=p.solve()
    em=next(x for x in r['emergency_drafts'] if x['item']=='I001')
    assert em['arrival']=='2026-09-08' and em['net_future_shortage_qty']==1000
    assert em['qty']==1008 and not em['current_day_shortage_resolved']


def test_future_sales_and_future_orders_do_not_change_inputs():
    origin=date(2026,9,1);frames=source_frames()
    sales=frames['09_sales'];mask=sales['date']>=str(origin)
    sales.loc[mask,'demand_qty']+=10000;sales.loc[mask,'qty']+=10000
    ds=CommonForecastData(frames)
    a=Planner(common_data(),clean_config(common_data(),dict(as_of=str(origin),max_hubs=0,scenarios=8)))
    b=Planner(ds,clean_config(ds,dict(as_of=str(origin),max_hubs=0,scenarios=8)))
    assert a.forecasts==b.forecasts and a.scenario_demand==b.scenario_demand
    assert a.firm==b.firm
    assert all(o+timedelta(days=a.length-1)<origin for o in a.origins)


def test_existing_scenario_contract_and_horizon():
    r=client.post('/api/hub',json={'as_of':'2026-12-01'})
    assert r.status_code==422 and 'error' in r.json()
    for target in (.1,.8,.98):
        p=compute(Scenario(service_level=target,horizon_days=1))
        assert p.service_target==target
        assert p.evaluation_end_exclusive<=date(2026,10,2)
        assert all(x.date<date(2026,10,2) for x in p.transfers+p.shortages)
    delayed=compute(Scenario(delay_days=14,horizon_days=14))
    assert delayed.evaluation_end_exclusive<=date(2026,10,15)


def test_minimum_amount_review_is_not_received():
    p=shortage_planner()
    line=dict(units=1,cost=100,supplier='SUP_A',order_date='2026-09-07',
              status='DRAFT',qty=1000,arrival='2026-09-08')
    p.minimum_check([line],False)
    assert line['status']=='MIN_AMOUNT_REVIEW'
    assert p.confirmed_qty(line,date(2026,9,8))==0
