import pytest
from app.features.hourly_forecast.trend import build_trend


def make(time='11:00', sales=None):
    return build_trend(store_id='S01', day='2026-09-10', menus=['m'],
        baseline={('m', h): 100 for h in range(10, 13)}, open_hour=10,
        close_hour=13, decision_time=time,
        completed_sales={10: {'m': 150}} if sales is None else sales)


def test_update_changes_only_future_and_band_is_exact():
    before = make('10:00', {})
    after = make()
    assert after['rows'][0]['actual'] == 150
    assert after['rows'][0]['forecast'] is None
    assert after['rows'][1]['forecast'] > before['rows'][1]['forecast']
    for row in after['rows'][1:]:
        assert row['lower'] == pytest.approx(row['forecast'] * .9)
        assert row['upper'] == pytest.approx(row['forecast'] * 1.1)
        assert row['actual'] is None


def test_future_missing_and_incomplete_hours_rejected():
    for sales in ({}, {10: {}}, {10: {'m': 100}, 11: {'m': 200}}):
        with pytest.raises(ValueError): make(sales=sales)


def test_correction_rebuild_and_end_of_day_and_zero_actual():
    assert make(sales={10: {'m': 50}})['rows'][1]['forecast'] < make()['rows'][1]['forecast']
    result = make('13:00', {h: {'m': 0} for h in range(10, 13)})
    assert all(r['forecast'] is None and r['absolute_percentage_error'] is None for r in result['rows'])
    assert make('11:30')['rows'][1]['actual'] is None
