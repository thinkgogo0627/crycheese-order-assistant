"""Replay shipped profiles through the actual forecaster, without retuning.

Run from repository root: python scripts/evaluate_hourly.py
Private CSV data is required. Output contains aggregate metrics only.
"""
import json
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.features.hourly_forecast.runtime import get_engine, Scenario
from app.features.hourly_forecast.intraday import HourlyPlanner, IntradayScenario


def main():
    engine = get_engine()
    planner = HourlyPlanner(engine)
    sales = engine.data['09_sales'].copy()
    sales['sold'] = (sales['qty'] - sales['cancel_qty']).clip(lower=0)
    grouped = sales.groupby(['date', 'store_id', 'menu_id', 'hour'])[['sold', 'demand_qty']].sum()
    records = grouped.to_dict('index')
    results = {}
    started = perf_counter()
    for profile in ('original', 'balanced', 'protective'):
        sums = defaultdict(float)
        day = date(2026, 8, 1)
        while day <= date(2026, 9, 30):
            _, _, hourly, _ = engine.forecast_bundle(Scenario(as_of=day, horizon_days=1, forecast_profile=profile))
            for store in engine.stores:
                sc = IntradayScenario(as_of=day, store_id=store, forecast_profile=profile)
                model = planner._make_forecaster(sc, hourly, store)
                menus = [m for m in engine.menus if engine.active(store, m, day)]
                for hour in range(model.open_hour, model.close_hour):
                    predictions = model.forecast_hour(hour)['predicted_by_menu']
                    # Match supplied evaluation: exclude the opening hour, before any POS evidence.
                    if hour > model.open_hour:
                        actual_total = predicted_total = 0.0
                        for menu in menus:
                            actual = records.get((day.isoformat(), store, menu, hour), {}).get('demand_qty', 0.0)
                            predicted = predictions[menu]
                            sums['absolute_error'] += abs(predicted - actual)
                            sums['actual'] += actual
                            sums['records'] += 1
                            actual_total += actual
                            predicted_total += predicted
                        sums['store_absolute_error'] += abs(predicted_total - actual_total)
                        sums['store_records'] += 1
                    model.observe_completed_hour(hour, {
                        m: records.get((day.isoformat(), store, m, hour), {}).get('sold', 0.0)
                        for m in engine.menus
                    })
            day += timedelta(days=1)
        results[profile] = {
            **sums,
            'next_hour_wape_percent': 100 * sums['absolute_error'] / sums['actual'],
            'next_hour_mae': sums['absolute_error'] / sums['records'],
            'store_hour_wape_percent': 100 * sums['store_absolute_error'] / sums['actual'],
        }
        print(profile, json.dumps(results[profile]), flush=True)
    output = ROOT / 'work' / 'hourly_evaluation.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({
        'period': '2026-08-01..2026-09-30',
        'status': 'Repeatedly inspected synthetic-data evaluation; not an independent holdout.',
        'seconds': perf_counter() - started, 'profiles': results,
    }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
