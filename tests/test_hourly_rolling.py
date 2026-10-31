"""Cumulative 10→11→12→13 one-hour-ahead forecast contract."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.features.hourly_forecast.rolling import CumulativeHourlyForecaster
from app.features.hourly_forecast.intraday import HourlyPlanner, IntradayScenario
from app.main import app
from app.features.hourly_forecast.runtime import get_engine
ENGINE=get_engine()
DATA=ENGINE.data
from app.features.hourly_forecast.runtime import Engine


def sample_model():
    baseline={(m,h):q for m in ['M1','M2'] for h,q in [(10,10.),(11,15.),(12,20.),(13,25.)]}
    return CumulativeHourlyForecaster(
        store_id='S01',day='2026-09-10',menus=['M1','M2'],baseline=baseline,
        open_hour=10,close_hour=14,strength=0.4,
    )


def test_accumulating_completed_hour_sales_instead_of_last_hour_only():
    m=sample_model()
    p10=m.forecast_hour()
    assert p10['predicted_hour']=='10:00'
    assert p10['based_on_completed_hours']==[]
    assert p10['predicted_next_hour']==20.0
    m.observe_completed_hour(10, {'M1':20,'M2':5})
    p11=m.forecast_hour()
    assert p11['predicted_hour']=='11:00'
    assert p11['based_on_completed_hours']==['10:00']
    assert p11['observed_sold_cumulative']==25
    m.observe_completed_hour(11, {'M1':35,'M2':15})
    p12=m.forecast_hour()
    assert p12['predicted_hour']=='12:00'
    assert p12['based_on_completed_hours']==['10:00','11:00']
    assert p12['observed_sold_cumulative']==75
    m.observe_completed_hour(12, {'M1':0,'M2':30})
    p13=m.forecast_hour()
    assert p13['predicted_hour']=='13:00'
    assert p13['based_on_completed_hours']==['10:00','11:00','12:00']
    assert p13['observed_sold_cumulative']==105
    # Contrasts with last-hour-only adjustment: the first two observations
    # still contribute at 13:00 despite a quieter 12 o'clock hour.
    assert p13['baseline_completed_hours']==90
    assert p13['adjustment_factor']>1
    assert p13['predicted_next_hour']>p13['baseline_next_hour']


def test_no_rewrite_no_gap_no_negative_sales_and_no_completed_hour_peek():
    model=sample_model()
    with pytest.raises(ValueError):model.observe_completed_hour(11, {'M1':3})
    with pytest.raises(ValueError):model.observe_completed_hour(10, {'M1':-1})
    with pytest.raises(ValueError):model.observe_completed_hour(10, {'WRONG':3})
    model.observe_completed_hour(10, {'M1':2})
    with pytest.raises(ValueError):model.observe_completed_hour(10, {'M1':100})
    with pytest.raises(ValueError):model.forecast_hour(10)
    with pytest.raises(ValueError):model.observe_completed_hour(12, {'M1':3})
    assert model.forecast_hour(11)['predicted_hour']=='11:00'


def test_real_data_timeline_adds_one_closed_hour_at_a_time():
    payload=HourlyPlanner(ENGINE).rolling(
        IntradayScenario(as_of=date(2026,9,10),decision_time='13:00',store_id='S01'))
    t=payload['timeline']
    assert [x['hour'] for x in t]==['10:00','11:00','12:00','13:00']
    assert [x['observed_hours'] for x in t]==[
        [],['10:00'],['10:00','11:00'],['10:00','11:00','12:00']]
    assert [len(x['observed_hours']) for x in t]==[0,1,2,3]
    assert t[0]['baseline_next_hour']==t[0]['predicted_next_hour']
    assert all(x['predicted_next_hour']>=0 for x in t)
    assert all(x['ingredient_requirements'] for x in t)


def test_s02_first_data_point_at_12_because_it_opens_at_11():
    t=HourlyPlanner(ENGINE).rolling(
        IntradayScenario(as_of=date(2026,9,10),decision_time='13:00',store_id='S02'))['timeline']
    assert [x['hour'] for x in t]==['11:00','12:00','13:00']
    assert [x['observed_hours'] for x in t]==[[],['11:00'],['11:00','12:00']]


def test_13h_forecast_ignores_real_sales_at_13h_and_later():
    scenario=IntradayScenario(as_of=date(2026,9,10),decision_time='13:00',store_id='S01')
    original=HourlyPlanner(ENGINE).rolling(scenario)
    tampered=dict(DATA)
    sales=DATA['09_sales'].copy()
    mask=(sales.date==str(scenario.as_of))&(sales.hour>=13)
    for c in ('qty','demand_qty','lost_qty'):
        sales.loc[mask,c]=999999
    tampered['09_sales']=sales
    alternative=HourlyPlanner(Engine(tampered)).rolling(scenario)
    assert original==alternative


def test_api_rolling_and_intraday_same_adjustment_logic():
    client=TestClient(app)
    req={'as_of':'2026-09-10','store_id':'S01','decision_time':'13:00'}
    rolling=client.post('/api/hourly_forecast',json=req)
    assert rolling.status_code==200,rolling.text
    p=rolling.json()
    latest=p['timeline'][-1]
    intraday=client.post('/api/intraday_plan',json=req)
    assert intraday.status_code==200,intraday.text
    signal=next(x for x in intraday.json()['observed'] if x['store_id']=='S01')
    assert latest['adjustment_factor']==pytest.approx(signal['adjustment_factor'],abs=0.00051)
    assert latest['predicted_next_hour']==pytest.approx(intraday.json()['hourly_forecast'][0]['updated'],abs=.011)
