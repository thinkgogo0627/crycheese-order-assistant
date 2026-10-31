"""
모든 기능이 지켜야 할 계약.

기능 = Feature를 상속한 클래스 1개 + 응답 모델(Pydantic) 1개.
- name        → URL: POST /api/{name}, 다른 기능에서 registry.run(name, sc) 로 호출
- label       → 화면 표시명
- description → /docs 설명
- Response    → 응답 모양 (BaseResponse 상속)
- run(sc)     → 계산. FastAPI를 몰라도 되는 순수 함수처럼 작성
"""
from abc import ABC, abstractmethod
from typing import ClassVar

from pydantic import BaseModel, Field

from app.core.scenario import Scenario


class Row(BaseModel):
    """응답의 한 줄. 모든 행은 근거(basis)를 가진다 → 화면에 '왜 이 숫자인지' 표시."""
    basis: str = Field(description="이 숫자가 나온 근거 (수식·입력값을 사람이 읽을 수 있게)")


class BaseResponse(BaseModel):
    """모든 응답 공통. scenario는 registry가 자동으로 채움."""
    scenario: Scenario | None = None
    assumptions: list[str] = Field(default_factory=list, description="이 결과에 쓰인 가정")


class Feature(ABC):
    name: ClassVar[str]
    label: ClassVar[str]
    description: ClassVar[str] = ""
    Response: ClassVar[type[BaseResponse]]

    @abstractmethod
    def run(self, sc: Scenario) -> BaseResponse: ...
