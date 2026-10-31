"""Verifies that the shipped July-calibrated parameters reach real planning paths."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.features.hourly_forecast.calibration import baseline_params, rolling_params
from app.features.hourly_forecast.runtime import Scenario
from app.features.hourly_forecast.intraday import HourlyPlanner, IntradayScenario
from app.main import app
from app.features.hourly_forecast.runtime import get_engine
ENGINE=get_engine()
DATA=ENGINE.data


def test_calibrated_params_are_explicit_and_reproducible():
    b=baseline_params('balanced')
    assert sum(b['weights'])==pytest.approx(1.0)
    assert b['recent_days'] == 7
    assert b['hour_profile_days'] == 84
    assert b['hour_pseudo'] == 24
    assert baseline_params('protective') == b
    assert baseline_params('original')['hour_profile_days'] == 56
    assert rolling_params('original')['store_smooth'] == 8
    assert rolling_params('protective')['store_high'] > rolling_params('balanced')['store_high']


def test_tuned_daily_and_hourly_profiles_reach_production_forecast():
    d=date(2026,9,10)
    originals=ENGINE.forecast_bundle(Scenario(as_of=d,forecast_profile='original',horizon_days=1))
    tuned=ENGINE.forecast_bundle(Scenario(as_of=d,forecast_profile='protective',horizon_days=1))
    _,_,a,_=originals
    _,_,b,meta=tuned
    assert meta['calibration']['baseline']['weights']==[.6,.2,.2]
    assert sum(a.get((d,'S01',m,11),0) for m in ENGINE.menus)==pytest.approx(89.2586,abs=.03)
    assert sum(b.get((d,'S01',m,11),0) for m in ENGINE.menus)==pytest.approx(88.66,abs=.04)
    assert all(x>=0 for x in b.values())


def test_custom_strength_zero_disables_both_store_and_menu_adjustment():
    sc=IntradayScenario(as_of=date(2026,9,10),decision_time='13:00',
                        forecast_profile='protective',adjustment_strength=0)
    result=HourlyPlanner(ENGINE).rolling(sc)
    for x in result['timeline']:
        assert x['predicted_next_hour']==pytest.approx(x['baseline_next_hour'],abs=.00011)


def test_api_exports_auditable_metrics_and_switchable_profiles():
    cli=TestClient(app)
    response=cli.post('/api/hourly_forecast',json={'as_of':'2026-09-10'})
    assert response.status_code == 200
    info=response.json()['calibration']
    assert info['profile']=='protective'
    assert 'reported_metrics' in info
    req=dict(as_of='2026-09-10',store_id='S01',decision_time='11:00')
    old=cli.post('/api/hourly_forecast',json={**req,'forecast_profile':'original'})
    protect=cli.post('/api/hourly_forecast',json={**req,'forecast_profile':'protective'})
    assert old.status_code==200 and protect.status_code==200
    assert protect.json()['timeline'][-1]['predicted_next_hour'] != old.json()['timeline'][-1]['predicted_next_hour']
