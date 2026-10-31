"""[조원 C] 발주 추천.

STUB(호진): 부족예상 품목을 리드타임 동안 소요량만큼 박스 올림. α·SS·EOQ·만료 상한 미반영. 담당자가 교체.
"""
import math
from datetime import timedelta

from app.core import data
from app.core.scenario import Scenario
from app.features import registry

from .schemas import OrderLine, OrdersResponse, SupplierOrder


def recommend(sc: Scenario) -> OrdersResponse:
    inv = registry.run("inventory", sc)               # B 결과
    fc = registry.run("forecast", sc)                 # A 결과 (캐시에서 나옴)
    ing = data.ingredients().set_index("ingredient_id")
    price = data.prices(sc.as_of).set_index("ingredient_id")["unit_price"]
    daily = {}
    for r in fc.rows:
        daily[r.ingredient_id] = daily.get(r.ingredient_id, 0) + r.qty / sc.horizon_days

    by_sup: dict[str, list[OrderLine]] = {}
    for a in inv.alerts:
        i = ing.loc[a.ingredient_id]
        need = daily[a.ingredient_id] * sc.horizon_days
        qty = max(math.ceil(need / i.use_qty_per_order_unit), int(i.min_order_qty))
        p = float(price[a.ingredient_id])
        by_sup.setdefault(i.supplier_id, []).append(OrderLine(
            ingredient_id=a.ingredient_id, ingredient_name=i.ingredient_name, order_unit=i.order_unit,
            order_qty=qty, use_qty=qty * float(i.use_qty_per_order_unit), unit_price=p, amount=qty * p,
            basis=f"[STUB] {sc.horizon_days}일 소요 {need:.0f}{i.use_unit} ÷ {i.use_qty_per_order_unit:g} → {qty}{i.order_unit}",
        ))

    orders = []
    for sup_id, lines in by_sup.items():
        s = ing[ing.supplier_id == sup_id].iloc[0]
        total = sum(l.amount for l in lines)
        orders.append(SupplierOrder(
            supplier_id=sup_id, supplier_name=s.supplier_name, order_cutoff=s.order_cutoff,
            expected_date=sc.as_of + timedelta(days=int(s.lead_time_days)),
            lines=lines, total_amount=total, meets_min_amount=total >= s.min_order_amount,
        ))
    return OrdersResponse(orders=orders, assumptions=["[STUB] 부족예상 품목만 발주, 안전재고·만료 상한 미반영"])
