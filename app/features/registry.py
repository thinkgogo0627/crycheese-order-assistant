"""
기능 목록. 여기 등록된 기능만 API로 노출된다.

[조원] 새 기능을 만들면 아래 FEATURES 에 한 줄 추가. 이 파일의 다른 곳은 건드리지 않는다.

기능끼리 호출할 때는 반드시 registry.run 을 쓴다 (캐시 공유):
    from app.features import registry        # ← 모듈째 import (순환 import 방지)
    fc = registry.run("forecast", sc)
"""
from collections import OrderedDict

from app.core.errors import AppError
from app.core.scenario import Scenario
from app.features.base import BaseResponse, Feature

from app.features.forecast.feature import Forecast
from app.features.inventory.feature import Inventory
from app.features.orders.feature import Orders

FEATURES: dict[str, Feature] = {
    f.name: f
    for f in [
        Forecast(),
        Inventory(),
        Orders(),
        # NewFeature(),   ← 여기에 한 줄 추가
    ]
}

# (기능명, 시나리오) → 결과. 같은 인스턴스 안에서만 유효 (Vercel은 인스턴스가 자주 바뀜)
_CACHE: "OrderedDict[tuple[str, Scenario], BaseResponse]" = OrderedDict()
_CACHE_MAX = 256


def get(name: str) -> Feature:
    if name not in FEATURES:
        raise AppError("no_feature", f"없는 기능: {name}", 404)
    return FEATURES[name]


def run(name: str, sc: Scenario) -> BaseResponse:
    key = (name, sc)
    if key in _CACHE:
        _CACHE.move_to_end(key)
        return _CACHE[key]
    feat = get(name)
    res = feat.run(sc)
    if not isinstance(res, feat.Response):
        raise AppError("bad_response", f"{name}.run()이 {feat.Response.__name__}를 돌려주지 않음", 500)
    res = res.model_copy(update={"scenario": sc})
    _CACHE[key] = res
    if len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)
    return res
