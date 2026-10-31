"""[조원 A] 수요 예측.

STUB(호진): 전날 기준 avg_consumption_7d × 수요배율 을 그대로 쓴다. 담당자가 교체.
교체 방향: scripts/ 에서 LightGBM 예측 테이블을 만들어 data/processed/ 에 커밋
          → 여기서는 data.processed("forecast.csv") 를 읽어 sc 로 필터 + BOM 환산만.
"""
from app.core import data
from app.core.scenario import Scenario

from .schemas import ForecastResponse, IngredientDemand


def forecast(sc: Scenario) -> ForecastResponse:
    inv = data.inventory_daily(sc.store_id, sc.as_of)
    last = inv[inv.date == inv.date.max()]
    names = data.ingredients().set_index("ingredient_id")["ingredient_name"]
    rows = [
        IngredientDemand(
            date=d,
            ingredient_id=r.ingredient_id,
            ingredient_name=names[r.ingredient_id],
            use_unit=r.use_unit,
            qty=round(r.avg_consumption_7d * sc.demand_multiplier, 2),
            basis=f"[STUB] {sc.last_closed} 최근 7일 평균 소비 {r.avg_consumption_7d:g} × 배율 {sc.demand_multiplier:g}",
        )
        for d in sc.horizon
        for r in last.itertuples()
    ]
    return ForecastResponse(rows=rows, assumptions=["[STUB] 최근 7일 평균 소비가 유지된다고 가정"])
