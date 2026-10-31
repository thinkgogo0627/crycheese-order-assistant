"""[조원 B] 재고 투영 + 알림 응답. 초안(호진) — 담당자가 자유롭게 수정, 수정 시 호진에게 공유."""
from datetime import date
from typing import Literal

from app.features.base import BaseResponse, Row

AlertLevel = Literal["긴급부족", "부족예상", "만료임박", "과잉"]


class ProjectionPoint(Row):
    date: date
    ingredient_id: str
    on_hand: float                 # 그날 영업 종료 후 예상 재고 (사용 단위)
    incoming: float = 0            # 그날 입고 예정량
    expired: float = 0             # 그날 만료 폐기량


class Alert(Row):
    ingredient_id: str
    ingredient_name: str
    level: AlertLevel
    stockout_date: date | None = None        # 평균 기준 부족일
    stockout_date_safe: date | None = None   # 보수적 기준(예측+SS) 부족일


class InventoryResponse(BaseResponse):
    alerts: list[Alert]
    projection: list[ProjectionPoint]
