from app.features.base import Feature
from . import service
from .schemas import HourlyResponse, IntradayResponse

class HourlyForecast(Feature):
    name = "hourly_forecast"
    label = "시간별 누적 수요 예측"
    description = "종료된 시간의 POS 실판매로 다음 시간 수요를 보정합니다."
    Response = HourlyResponse
    def run(self, sc):
        return service.forecast(sc)

class IntradayPlan(Feature):
    name = "intraday_plan"
    label = "시간별 재계획 실험"
    description = "30분 이동·소분 허용 가정하의 검토용 초안. 실제 실행 없음."
    Response = IntradayResponse
    def run(self, sc):
        return service.plan(sc)
