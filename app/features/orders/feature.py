from app.core.scenario import Scenario
from app.features.base import Feature

from .schemas import OrdersResponse
from .service import recommend


class Orders(Feature):
    name = "orders"
    label = "발주 추천"
    description = "재고 투영 결과 + 공급사 조건 → 공급사별 발주서 (줄마다 근거)"
    Response = OrdersResponse

    def run(self, sc: Scenario) -> OrdersResponse:
        return recommend(sc)
