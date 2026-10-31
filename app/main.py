"""서버 입구. Vercel이 app/main.py 의 `app`을 자동 인식.

[호진 전용] 조원은 이 파일을 수정하지 않는다. 기능 추가 = app/features/registry.py 에 한 줄.
- 정식 구조: app/features/<name>/ → POST /api/<name> 자동 생성 (규격: app/features/SPEC.md)
- [LEGACY] /api/plan, /api/backtest, /dashboard 는 임시 엔진(app/engine.py).
  프론트가 아직 /api/plan 을 쓰므로 실제 기능이 화면에 붙은 뒤 한꺼번에 삭제한다.
"""
import os
from pathlib import Path

import pandas as pd
from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from app.core import errors
from app.core.scenario import Scenario
from app.features import registry

app = FastAPI(title="크라이치즈버거 발주·재고 의사결정 도우미")
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https://.*\.vercel\.app|http://localhost:5173|http://127\.0\.0\.1:5173",
    allow_methods=["*"],
    allow_headers=["*"],
)
errors.install(app)  # 모든 에러 → {"error": {"code", "message"}}


@app.get("/")
def root():
    return {"service": "발주·재고 의사결정 도우미", "status": "ok", "docs": "/docs",
            "features": [f"/api/{n}" for n in registry.FEATURES]}


# ---------------- 정식: features ----------------
@app.get("/api/features")
def list_features():
    """등록된 기능 목록 (프론트·스모크 테스트용)."""
    return [
        {"name": f.name, "label": f.label, "description": f.description, "path": f"/api/{f.name}"}
        for f in registry.FEATURES.values()
    ]


def _add_route(name: str) -> None:
    f = registry.FEATURES[name]

    def endpoint(sc: Scenario = Body(default_factory=Scenario)):
        return registry.run(name, sc)

    app.post(f"/api/{name}", response_model=f.Response, summary=f.label,
             description=f.description, name=name, tags=["features"])(endpoint)


for _name in registry.FEATURES:
    _add_route(_name)


# ---------------- [LEGACY] 임시 엔진: 실제 기능으로 교체 후 이 블록 + engine.py 삭제 ----------------
from app.engine import Engine, Scenario as EngineScenario  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW = Path(os.environ.get("CRY_DATA_DIR", str(ROOT / "data" / "raw")))
DATA = {p.stem: pd.read_csv(p, encoding="utf-8-sig") for p in sorted(RAW.glob("*.csv"))}
ENGINE = Engine(DATA) if len(DATA) >= 17 else None


@app.get("/health")
def health():
    return {"ok": ENGINE is not None, "tables": {k: len(v) for k, v in DATA.items()}}


@app.get("/dashboard", response_class=HTMLResponse, tags=["legacy"])
def dashboard():
    return (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")


@app.post("/api/plan", tags=["legacy"])
def plan(scenario: EngineScenario):
    if ENGINE is None:
        raise HTTPException(503, "서버의 CSV 데이터가 로딩되지 않았습니다. CRY_DATA_DIR를 확인해 주세요.")
    return ENGINE.plan(scenario)


@app.get("/api/backtest", tags=["legacy"])
def backtest():
    if ENGINE is None or ENGINE.backtest is None:
        raise HTTPException(503, "백테스트 결과가 없습니다.")
    return ENGINE.backtest
