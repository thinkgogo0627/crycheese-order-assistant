"""Immutable snapshot adapter for the existing causal hourly forecaster."""
from datetime import datetime
from .rolling import CumulativeHourlyForecaster


def build_trend(*, store_id, day, menus, baseline, open_hour, close_hour,
                decision_time, completed_sales, band_fraction=0.10, **model_options):
    """Rebuild from complete hourly snapshots; corrections replace prior snapshots.

    completed_sales: {hour: {menu_id: net_fulfilled_qty}}. All closed hours
    are mandatory, including explicit zero-sale hours. Partial hours rejected.
    Decision time is local store time, on day. No persistent shared state.
    """
    import math
    if not math.isfinite(band_fraction) or not 0 <= band_fraction <= 1:
        raise ValueError('band_fraction must be finite and between 0 and 1')
    clock = datetime.strptime(decision_time, '%H:%M')
    cutoff = max(open_hour, min(clock.hour, close_hour))
    if set(completed_sales) != set(range(open_hour, cutoff)):
        raise ValueError('Provide every completed hour exactly once; no current/future hours')
    model = CumulativeHourlyForecaster(store_id=store_id, day=day, menus=menus,
        baseline=baseline, open_hour=open_hour, close_hour=close_hour, **model_options)
    rows = []
    for hour in range(open_hour, close_hour):
        base = sum(model.baseline[m, hour] for m in menus)
        actual = forecast = lower = upper = prior = error = None
        if hour < cutoff:
            prior = sum(model.forecast_hour(hour)['predicted_by_menu'].values())
            snapshot = completed_sales[hour]
            if set(snapshot) != set(menus):
                raise ValueError('Each completed hour must contain all menus, including zero sales')
            model.observe_completed_hour(hour, snapshot)
            actual = sum(float(v) for v in snapshot.values())
            error = abs(prior - actual) / actual * 100 if actual > 0 else None
        else:
            forecast = sum(model.forecast_hour(hour)['predicted_by_menu'].values())
            lower, upper = forecast * (1-band_fraction), forecast * (1+band_fraction)
        rows.append(dict(hour=hour, label=f'{hour:02d}:00', baseline=base,
                         actual=actual, forecast=forecast, lower=lower, upper=upper,
                         prior_forecast=prior, absolute_percentage_error=error))
    return dict(store_id=store_id, day=day, decision_time=decision_time,
                band_fraction=band_fraction,
                band_note='예측값 ±10% 표시 범위(기본값). 검증된 오차율·신뢰구간이 아닙니다.',
                rows=rows)
