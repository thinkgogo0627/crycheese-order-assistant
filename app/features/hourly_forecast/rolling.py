"""Causal, cumulative next-hour sales forecasts for one burger store.

A single instance lives for one store and day.  Each `observe_completed_hour`
adds one fully closed POS hour; an earlier hour is never overwritten and a
future hour cannot be observed.  Forecast baselines are computed *as of the
previous day* by the existing model.  The current day's latent demand, lost
sales and future fulfilled sales never enter this class.

This forecasts **fulfilled POS sales-driven demand adjustment**, not actual
unconstrained demand (stockouts can bias observations downward).  The shrinkage
strength is heuristic and should be calibrated on chronological validation.
"""
from __future__ import annotations

from math import isfinite
from typing import Mapping


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


class CumulativeHourlyForecaster:
    """Next-hour prediction from *all* completed same-day hours, sequentially.

    Example for a store opening at 10:00:
      predict_next_hour()                   -> 10:00 baseline (no sales yet)
      observe_completed_hour(10, {...})     -> ingest 10:00~10:59 POS totals
      predict_next_hour()                   -> 11:00 prediction
      observe_completed_hour(11, {...})     -> ingest 11:00~11:59 POS totals
      predict_next_hour()                   -> 12:00 prediction using 10+11

    A repeated or skipped hour raises ValueError. All menus omitted from the
    completed-hour mapping are assumed to have zero fulfilled sales for that
    hour; **only pass complete POS snapshots**, not individual transactions.
    """

    def __init__(
        self,
        *,
        store_id: str,
        day: str,
        menus: list[str],
        baseline: Mapping[tuple[str, int], float],
        open_hour: int,
        close_hour: int,
        strength: float = 0.4,
        store_smooth: float = 8.,
        menu_smooth: float = 3.,
        menu_gain: float = .1,
        store_low: float = .75,
        store_high: float = 1.30,
        menu_low: float = .70,
        menu_high: float = 1.35,
        delta_cap: float = .06,
    ) -> None:
        if not (0 <= open_hour < close_hour <= 24):
            raise ValueError('매장 영업시간이 유효하지 않습니다.')
        if not (0 <= strength <= 1):
            raise ValueError('보정 강도는 0~1이어야 합니다.')
        if not menus or len(set(menus)) != len(menus):
            raise ValueError('메뉴 목록이 비어있거나 중복되었습니다.')
        self.store_id = store_id
        self.day = day
        self.menus = tuple(menus)
        self.open_hour = open_hour
        self.close_hour = close_hour
        if not all(isfinite(v) for v in (strength, store_smooth, menu_smooth, menu_gain, store_low, store_high, menu_low, menu_high, delta_cap)):
            raise ValueError('보정 파라미터는 유한한 수여야 합니다.')
        if store_smooth<=0 or menu_smooth<=0 or menu_gain<0 or delta_cap<0:
            raise ValueError('평활화 및 추가 보정 파라미터가 유효하지 않습니다.')
        if not (0<=store_low<=1<=store_high and 0<=menu_low<=1<=menu_high):
            raise ValueError('보정배율의 허용 범위가 1을 포함해야 합니다.')
        self.strength = strength
        self.store_smooth=store_smooth
        self.menu_smooth=menu_smooth
        self.menu_gain=menu_gain
        self.store_low=store_low
        self.store_high=store_high
        self.menu_low=menu_low
        self.menu_high=menu_high
        self.delta_cap=delta_cap
        self.baseline = {}
        for menu in self.menus:
            for hour in range(open_hour, close_hour):
                value = float(baseline.get((menu, hour), 0))
                if not isfinite(value) or value < 0:
                    raise ValueError('기본 예측량은 0 이상의 유한한 값이어야 합니다.')
                self.baseline[(menu, hour)] = value
        self._completed: dict[int, dict[str, float]] = {}

    @property
    def next_hour(self) -> int:
        return self.open_hour + len(self._completed)

    def observe_completed_hour(self, hour: int, sales_by_menu: Mapping[str, float]) -> None:
        """Ingest one *complete* POS hour; its sales are then fixed."""
        if hour != self.next_hour or hour >= self.close_hour:
            raise ValueError('관측은 종료된 영업시간을 순서대로 한 번씩만 등록하세요.')
        unknown = set(sales_by_menu) - set(self.menus)
        if unknown:
            raise ValueError(f'알 수 없는 메뉴: {sorted(unknown)}')
        snapshot = {m: float(sales_by_menu.get(m, 0)) for m in self.menus}
        if any(not isfinite(v) or v < 0 for v in snapshot.values()):
            raise ValueError('실판매량은 음수가 아닌 유한한 수여야 합니다.')
        self._completed[hour] = snapshot

    def _signals(self) -> dict:
        hours = list(self._completed)
        actual = sum(sum(s.values()) for s in self._completed.values())
        base = sum(self.baseline[m, h] for h in hours for m in self.menus)
        if not hours:
            return dict(hours=[], actual=0.0, baseline=0.0,
                        factor=1.0, menu_factors={m: 1.0 for m in self.menus})
        # Store-level signal is stable even when the first hour is sparse.
        ratio = (actual + self.store_smooth) / (base + self.store_smooth)
        store_factor = _clip(1 + self.strength * (ratio - 1), self.store_low, self.store_high)
        menu_factors = {}
        for m in self.menus:
            menu_actual = sum(row[m] for row in self._completed.values())
            menu_base = sum(self.baseline[m, h] for h in hours)
            menu_ratio = (menu_actual + self.menu_smooth) / (menu_base + self.menu_smooth)
            delta = _clip((menu_ratio - ratio) * (self.menu_gain if self.strength>0 else 0.),
                          -self.delta_cap, self.delta_cap)
            menu_factors[m] = _clip(store_factor + delta, self.menu_low, self.menu_high)
        return dict(hours=hours, actual=actual, baseline=base,
                    factor=store_factor, menu_factors=menu_factors)

    def observed_summary(self) -> dict:
        signal = self._signals()
        return {
            'store_id': self.store_id,
            'observed_completed_hours': len(signal['hours']),
            'observed_hour_labels': [f'{h:02d}:00' for h in signal['hours']],
            'observed_sold': round(signal['actual'], 3),
            'baseline_same_hours': round(signal['baseline'], 3),
            'adjustment_factor': round(signal['factor'], 4),
            'signal': '실측' if signal['hours'] else '관측 없음: 기본예측 유지',
        }

    def forecast_hour(self, hour: int | None = None) -> dict:
        """Predict any not-yet-completed hour, defaulting to the *next* hour."""
        h = self.next_hour if hour is None else hour
        if not self.next_hour <= h < self.close_hour:
            raise ValueError('이미 종료된 시간 또는 영업 종료 이후는 예측하지 않습니다.')
        sig = self._signals()
        menu_base = {m: self.baseline[m, h] for m in self.menus}
        menu_new = {m: menu_base[m] * sig['menu_factors'][m] for m in self.menus}
        return {
            'predicted_hour': f'{h:02d}:00',
            'based_on_completed_hours': [f'{x:02d}:00' for x in sig['hours']],
            'observed_sold_cumulative': round(sig['actual'], 3),
            'baseline_completed_hours': round(sig['baseline'], 3),
            'adjustment_factor': round(sig['factor'], 4),
            'baseline_next_hour': round(sum(menu_base.values()), 4),
            'predicted_next_hour': round(sum(menu_new.values()), 4),
            'baseline_by_menu': menu_base,
            'predicted_by_menu': menu_new,
        }
