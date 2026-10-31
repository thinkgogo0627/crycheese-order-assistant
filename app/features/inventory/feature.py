from app.core.scenario import Scenario
from app.features.base import Feature

from .schemas import InventoryResponse
from .service import project


class Inventory(Feature):
    name = "inventory"
    label = "재고 알림"
    description = "lot별 FEFO 재고 투영 → 긴급부족·부족예상·만료임박·과잉 알림"
    Response = InventoryResponse

    def run(self, sc: Scenario) -> InventoryResponse:
        return project(sc)
