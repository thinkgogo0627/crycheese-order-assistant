"""[조원 B] 재고 투영(FEFO) + 알림.

STUB(호진): 현재 재고 + 미입고 - 예측 소요를 단순 누적. lot·만료·SS 미반영. 담당자가 교체.
"""
from datetime import timedelta

from app.core import data
from app.core.scenario import Scenario
from app.features import registry

from .schemas import Alert, InventoryResponse, ProjectionPoint


def project(sc: Scenario) -> InventoryResponse:
    fc = registry.run("forecast", sc)                 # A 결과
    on_hand = data.lots(sc.store_id, sc.as_of).groupby("ingredient_id")["remaining_qty"].sum()
    po = data.open_orders(sc.store_id, sc.as_of)
    po["arrive"] = (po.expected_date + timedelta(days=sc.delay_days)).dt.date
    incoming = po.groupby(["arrive", "ingredient_id"])["use_qty"].sum()

    level = on_hand.to_dict()
    projection, alerts, alerted = [], [], set()
    for r in fc.rows:
        inc = float(incoming.get((r.date, r.ingredient_id), 0))
        level[r.ingredient_id] = level.get(r.ingredient_id, 0) + inc - r.qty
        lv = level[r.ingredient_id]
        projection.append(ProjectionPoint(
            date=r.date, ingredient_id=r.ingredient_id, on_hand=round(lv, 2), incoming=inc,
            basis=f"[STUB] 전일 재고 + 입고 {inc:g} - 예측 {r.qty:g}",
        ))
        if lv < 0 and r.ingredient_id not in alerted:
            alerted.add(r.ingredient_id)
            alerts.append(Alert(
                ingredient_id=r.ingredient_id, ingredient_name=r.ingredient_name,
                level="부족예상", stockout_date=r.date,
                basis=f"[STUB] {r.date} 예상 재고 {lv:.0f}{r.use_unit}",
            ))
    return InventoryResponse(alerts=alerts, projection=projection,
                             assumptions=["[STUB] 만료·FEFO·안전재고 미반영", "입고 예정일에 전량 도착 (+지연 일수)"])
