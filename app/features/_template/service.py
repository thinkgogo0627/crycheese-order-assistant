"""계산 로직. FastAPI import 금지. 데이터는 app.core.data 로만."""
from app.core import data
from app.core.scenario import Scenario
from app.features import registry  # noqa: F401  (다른 기능 결과가 필요할 때: registry.run("forecast", sc))

from .schemas import ExampleResponse, ExampleRow


def compute(sc: Scenario) -> ExampleResponse:
    inv = data.inventory_daily(sc.store_id, sc.as_of)
    last = inv[inv.date == inv.date.max()]
    rows = [
        ExampleRow(ingredient_id=r.ingredient_id, value=float(r.closing_qty),
                   basis=f"{sc.last_closed} 기말 재고 {r.closing_qty}{r.use_unit}")
        for r in last.itertuples()
    ]
    return ExampleResponse(rows=rows, assumptions=["예시 기능입니다"])
