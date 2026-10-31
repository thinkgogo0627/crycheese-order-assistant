from datetime import date
from typing import Any
from pydantic import Field
from app.features.base import BaseResponse, Row


class HubOrder(Row):
    store_id: str
    ingredient_id: str
    ingredient_name: str
    supplier_id: str
    order_date: date
    arrival_date: date
    order_qty: int
    order_unit: str
    use_qty: float
    use_unit: str
    safety_qty: float = 0
    amount: int
    status: str
    minimum_amount: float = 0
    order_total: float = 0


class HubTransfer(Row):
    date: date
    hub_id: str
    store_id: str
    ingredient_id: str
    ingredient_name: str
    qty: float
    use_unit: str
    response_minutes: float
    last_use_date: date


class EmergencyOrder(HubOrder):
    current_day_shortage_resolved: bool = False


class Shortage(Row):
    date: date
    store_id: str
    ingredient_id: str
    ingredient_name: str
    qty: float
    use_unit: str
    status: str


class HubGroup(Row):
    hub_id: str | None
    members: list[str]
    alpha: float
    capacity_ok: bool
    fleet_ok: bool
    peak_liters: dict[str, float]
    outside_30_minutes: list[str]


class Alternative(Row):
    hub_count: int
    feasible: bool
    economic_cost: int
    fill_rate: float
    logistics_cost: int
    waste_cost: int


class HubResponse(BaseResponse):
    forecast_model: str = 'ewma'
    forecast_basis: str
    conditions: dict[str, Any]
    status: str
    recommended_hub_count: int | None
    evaluation_start: date
    evaluation_end_exclusive: date
    service_target: float
    fill_rate: float
    groups: list[HubGroup]
    alternatives: list[Alternative]
    store_orders: list[HubOrder]
    hub_orders: list[HubOrder]
    transfers: list[HubTransfer]
    emergency_orders: list[EmergencyOrder]
    shortages: list[Shortage]
    search_method: str
    warnings: list[str] = Field(default_factory=list)
