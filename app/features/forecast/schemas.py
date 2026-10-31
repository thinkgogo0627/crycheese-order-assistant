"""[조원 A] 수요 예측 응답. 초안(호진) — 담당자가 자유롭게 수정, 수정 시 호진에게 공유."""
from datetime import date

from app.features.base import BaseResponse, Row


class IngredientDemand(Row):
    date: date
    ingredient_id: str
    ingredient_name: str
    use_unit: str
    qty: float                    # 예측 소요량 d (사용 단위)


class ForecastResponse(BaseResponse):
    rows: list[IngredientDemand]  # 식자재 × 일
    wape: float | None = None     # 검증기간 WAPE (모델 채택 근거)
