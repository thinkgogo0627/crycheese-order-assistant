"""Transparent calibration choices, selected on July 2026 only.

The bundled JSON includes only aggregate model settings/metrics, not raw data.
The shortage-protective loss ratio 1.5 is an explicit sensitivity assumption,
not an observed economic penalty ratio from the restaurant.
"""
from __future__ import annotations

import json
from pathlib import Path
from functools import lru_cache
from copy import deepcopy

CALIBRATION_FILE = Path(__file__).resolve().parent / 'config' / 'selected_params.json'

ORIGINAL_BASELINE = {
    'recent_days': 7, 'same_weekdays': 4, 'hour_profile_days': 56,
    'hour_pseudo': 12., 'area_history_days': 56, 'weights': [0.4,0.4,0.2],
}
ORIGINAL_ROLLING = {
    'strength': 0.4, 'store_smooth': 8., 'menu_smooth': 3.,
    'menu_gain': .1, 'store_low': .75, 'store_high': 1.30,
    'menu_low': .7, 'menu_high': 1.35, 'delta_cap': .06,
}

@lru_cache(maxsize=1)
def _read_calibration() -> dict:
    if not CALIBRATION_FILE.exists():
        raise RuntimeError('번들 config/selected_params.json이 없습니다. 원본 파일을 복구하거나 오프라인 튜닝 결과를 검토 후 복사하세요.')
    return json.loads(CALIBRATION_FILE.read_text(encoding='utf-8'))


def baseline_params(profile: str) -> dict:
    if profile == 'original':return deepcopy(ORIGINAL_BASELINE)
    if profile not in ('balanced','protective'):raise ValueError(f'알 수 없는 모형: {profile}')
    return deepcopy(read_calibration()['baseline'])


def rolling_params(profile: str) -> dict:
    if profile == 'original':return dict(ORIGINAL_ROLLING)
    if profile == 'balanced':return dict(read_calibration()['rolling'])
    if profile == 'protective':return dict(read_calibration()['shortage_protective_illustrative']['parameters'])
    raise ValueError(f'알 수 없는 모형: {profile}')


def read_calibration() -> dict:
    """Return a defensive copy; cached metadata must not be mutated by callers."""
    return deepcopy(_read_calibration())
