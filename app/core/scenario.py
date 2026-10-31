"""
화면 입력값 모델. 프론트 frontend/src/types/api.ts 의 Scenario와 필드가 같아야 함.
모든 기능의 입력은 이거 하나.

시점 규약
- as_of = 판단일 "아침". 데이터는 as_of 전날(last_closed) 영업 종료까지만 볼 수 있음.
- 시간대별 확장만 as_of 당일 decision_time 이전에 완료된 POS를 추가 사용한다.
- 예측·투영 구간 = as_of 부터 horizon_days 일 (sc.horizon)
"""
from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

AS_OF_MIN = date(2026, 7, 1)
AS_OF_MAX = date(2026, 10, 1)


class CompletedSale(BaseModel):
    model_config = ConfigDict(frozen=True)
    store_id: Literal["S01", "S02", "S03"]
    menu_id: str
    hour: int = Field(ge=0, le=23)
    sold_qty: float = Field(ge=0, allow_inf_nan=False)


class Scenario(BaseModel):
    # frozen → 해시 가능 → registry 캐시 키로 사용
    model_config = ConfigDict(frozen=True)

    as_of: date = Field(AS_OF_MAX, description="판단일 아침 (2026-07-01 ~ 2026-10-01)")
    store_id: Literal["S01", "S02", "S03"] = "S01"
    horizon_days: int = Field(7, ge=1, le=14, description="예측·투영 일수")
    demand_multiplier: float = Field(1.0, gt=0, le=5, description="수요 배율 k")
    delay_days: int = Field(0, ge=0, le=14, description="입고 지연 일수 (가상 시나리오)")
    service_level: float | None = Field(None, gt=0, lt=1, description="null = 품목별 자동(α)")

    # Hourly-only inputs. Existing daily ordering defaults and model are unchanged.
    forecast_profile: Literal["original", "balanced", "protective"] = "protective"
    decision_time: str = Field("11:00", pattern=r"^([01][0-9]|2[0-3]):00$")
    horizon_hours: int = Field(4, ge=1, le=10)
    promotion_multiplier: float = Field(1.0, ge=0.5, le=2.5, allow_inf_nan=False)
    adjustment_strength: float | None = Field(None, ge=0, le=1, allow_inf_nan=False)
    minimum_avoided_menu_qty: float = Field(1.0, ge=0, le=20)
    transfer_cost: float = Field(0, ge=0, le=100000, allow_inf_nan=False)
    live_sales: tuple[CompletedSale, ...] | None = Field(None, max_length=2000)

    @field_validator("as_of")
    @classmethod
    def _check_as_of(cls, v: date) -> date:
        if not AS_OF_MIN <= v <= AS_OF_MAX:
            raise ValueError(f"as_of는 {AS_OF_MIN} ~ {AS_OF_MAX} 사이여야 합니다")
        return v

    @property
    def last_closed(self) -> date:
        """볼 수 있는 마지막 영업 종료일 (as_of - 1)."""
        return self.as_of - timedelta(days=1)

    @property
    def horizon(self) -> list[date]:
        """as_of 부터 horizon_days 일."""
        return [self.as_of + timedelta(days=i) for i in range(self.horizon_days)]
