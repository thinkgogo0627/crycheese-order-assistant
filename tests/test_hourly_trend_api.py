from app.features import registry
from app.core.scenario import Scenario

def test_trend_api_recalculates_and_has_no_future_actuals():
    def call(payload):
        return registry.run("hourly_forecast", Scenario(**payload)).model_dump(mode="json")
    payload = dict(as_of='2026-09-10', store_id='S01', decision_time='12:00', horizon_hours=4)
    a = call(payload)
    rows = a['trend']['rows']
    assert all(r['actual'] is not None and r['forecast'] is None for r in rows if r['hour'] < 12)
    assert all(r['actual'] is None and r['lower'] == r['forecast'] * .9 and r['upper'] == r['forecast'] * 1.1 for r in rows if r['hour'] >= 12)
    assert max(r['hour'] for r in rows) == 15
    b = call({**payload, 'live_sales': []})
    assert b['trend']['rows'] != rows
    assert all(r['actual'] == 0 for r in b['trend']['rows'] if r['hour'] < 12)
