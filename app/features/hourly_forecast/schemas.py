"""Typed public responses; all displayed numeric rows carry calculation basis."""
from datetime import date
from typing import Any
from pydantic import Field
from app.features.base import BaseResponse, Row

class TimelineRow(Row):
    hour: str
    observed_hours: list[str]
    observed_sold_cumulative: float
    baseline_completed_hours: float
    adjustment_factor: float
    baseline_next_hour: float
    predicted_next_hour: float
    top_menus: list[dict[str, Any]]
    ingredient_requirements: list[dict[str, Any]]

class HourlyResponse(BaseResponse):
    as_of: date
    store_id: str
    decision_time: str
    data_source: str
    trade_area: str
    timeline: list[TimelineRow]
    note: str
    calibration: dict[str, Any] = Field(default_factory=dict)

class SignalRow(Row):
    store_id: str
    trade_area: str
    observed_completed_hours: int
    observed_hour_labels: list[str]
    observed_sold: float
    baseline_same_hours: float
    adjustment_factor: float
    signal: str

class ForecastRow(Row):
    hour: str
    baseline: float
    updated: float

class RiskRow(Row):
    store_id: str
    ingredient_id: str
    ingredient: str
    first_at: str
    shortfall_use_qty: float
    unit: str

class TransferRow(Row):
    from_store: str
    to_store: str
    depart: str
    arrive: str
    minutes: int
    trip_cost: float
    items: list[dict[str, Any]]

class IntradayResponse(BaseResponse):
    as_of: date
    store_id: str
    decision_time: str
    data_source: str
    observed_sales_period: str
    observed: list[SignalRow]
    hourly_forecast: list[ForecastRow]
    risks: list[RiskRow]
    transfers: list[TransferRow]
    without_transfer: dict[str, float]
    with_transfer: dict[str, float]
    predicted_avoided_lost_menu_qty: float
    remaining_lost_menu_qty: float
    data_issues: list[str]
    snapshot_discrepancies: list[dict[str, Any]]
