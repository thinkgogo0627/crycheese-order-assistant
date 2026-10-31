"""응답 모양. 가장 먼저 작성해서 호진에게 공유."""
from app.features.base import BaseResponse, Row


class ExampleRow(Row):           # Row 상속 → basis 필드 자동 포함
    ingredient_id: str
    value: float


class ExampleResponse(BaseResponse):   # BaseResponse 상속 → scenario, assumptions 자동 포함
    rows: list[ExampleRow]
