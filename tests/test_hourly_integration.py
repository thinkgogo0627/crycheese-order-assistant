"""Boundary checks for the common registry and supplied POS snapshots."""
from fastapi.testclient import TestClient
from app.main import app
from app.core.scenario import Scenario
from app.features.hourly_forecast.calibration import baseline_params, read_calibration
from app.features.hourly_forecast.runtime import get_engine

client = TestClient(app)
REQUEST = {'as_of': '2026-09-10', 'store_id': 'S01', 'decision_time': '11:00'}
SALE = {'store_id': 'S01', 'menu_id': next(iter(get_engine().menus)), 'hour': 10, 'sold_qty': 2}


def test_snapshot_scenario_remains_hashable_for_registry_cache():
    assert hash(Scenario(**REQUEST, live_sales=[SALE])) == hash(Scenario(**REQUEST, live_sales=[SALE]))


def test_duplicate_snapshot_is_rejected_instead_of_double_counted():
    response = client.post('/api/hourly_forecast', json={**REQUEST, 'live_sales': [SALE, SALE]})
    assert response.status_code == 422
    assert '중복' in response.json()['error']['message']


def test_unobserved_future_day_does_not_silently_replay_september():
    response = client.post('/api/hourly_forecast', json={**REQUEST, 'as_of': '2026-10-01'})
    assert response.status_code == 422
    assert 'live_sales' in response.json()['error']['message']


def test_empty_explicit_snapshot_is_zero_sales_and_does_not_fall_back():
    response = client.post('/api/hourly_forecast', json={**REQUEST, 'live_sales': []})
    assert response.status_code == 200
    result = response.json()
    assert result['data_source'] == 'live_pos_snapshot'
    assert result['timeline'][-1]['observed_sold_cumulative'] == 0
    assert all(row['basis'] for row in result['timeline'])


def test_metadata_cannot_modify_cached_configuration():
    before = baseline_params('protective')['weights'][:]
    baseline_params('protective')['weights'][0] = 999
    read_calibration()['baseline']['weights'][0] = 999
    assert baseline_params('protective')['weights'] == before
