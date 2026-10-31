"""기능 선언. name / label / description 만 바꾸면 됨."""
from app.core.scenario import Scenario
from app.features.base import Feature

from .schemas import ExampleResponse
from .service import compute


class Example(Feature):
    name = "example"                 # → POST /api/example
    label = "예시 기능"
    description = "템플릿 예시: 전날 기말 재고를 그대로 돌려준다"
    Response = ExampleResponse

    def run(self, sc: Scenario) -> ExampleResponse:
        return compute(sc)
