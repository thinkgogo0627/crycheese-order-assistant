from app.core.scenario import Scenario
from app.features.base import Feature
from .schemas import HubResponse
from .service import compute


class Hub(Feature):
    name = 'hub'
    label = '허브 공급·긴급발주'
    description = '공통 EWMA 예측으로 무허브·허브 대안을 비교하고 정기발주, 허브 공급, 외부 긴급발주 초안을 계산합니다.'
    Response = HubResponse

    def run(self, sc: Scenario) -> HubResponse:
        return compute(sc)
