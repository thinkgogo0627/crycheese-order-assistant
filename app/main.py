"""배포 스캐폴드: 데이터 로딩 + 헬스체크."""
from pathlib import Path

import pandas as pd
from fastapi import FastAPI

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"

DATA = {p.stem: pd.read_csv(p) for p in sorted(RAW.glob("*.csv"))}

app = FastAPI(title="식자재 발주 의사결정 지원")


@app.get("/")
def root():
    return {"service": "식자재 관리 및 발주 자동화", "status": "ok", "docs": "/docs"}


@app.get("/health")
def health():
    return {"ok": True, "tables": {k: len(v) for k, v in DATA.items()}}
