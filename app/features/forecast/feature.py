from app.core.scenario import Scenario
from app.features.base import Feature

from .schemas import ForecastResponse
from .service import forecast


class Forecast(Feature):
    name = "forecast"
    label = "수요 예측"
    description = "메뉴 수요 예측 → BOM 환산 → 식자재별 일별 예측 소요량"
    Response = ForecastResponse

    def run(self, sc: Scenario) -> ForecastResponse:
        return forecast(sc)
