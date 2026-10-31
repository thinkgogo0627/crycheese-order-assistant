"""[조원 C] 발주 추천 응답. 초안(호진) — 담당자가 자유롭게 수정, 수정 시 호진에게 공유."""
from datetime import date

from pydantic import BaseModel

from app.features.base import BaseResponse, Row


class OrderLine(Row):
    ingredient_id: str
    ingredient_name: str
    order_unit: str
    order_qty: int                 # 발주 단위 수량 (박스 등)
    use_qty: float                 # 사용 단위 환산량
    unit_price: float
    amount: float


class SupplierOrder(BaseModel):
    supplier_id: str
    supplier_name: str
    order_cutoff: str              # 발주 마감 시각
    expected_date: date            # 입고 예정일
    lines: list[OrderLine]
    total_amount: float
    meets_min_amount: bool         # 공급사 최소 발주금액 충족 여부


class OrdersResponse(BaseResponse):
    orders: list[SupplierOrder]
