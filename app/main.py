"""배포 스캐폴드: 데이터 로딩 + 헬스체크. (Vercel이 app/main.py의 `app`을 자동 인식)"""
from pathlib import Path

import pandas as pd
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"

# CSV 맨 앞에 BOM이 있어서 utf-8-sig로 읽어야 첫 컬럼명이 깨지지 않음
DATA = {p.stem: pd.read_csv(p, encoding="utf-8-sig") for p in sorted(RAW.glob("*.csv"))}

app = FastAPI(title="식자재 발주 의사결정 지원")

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https://.*\.vercel\.app|http://localhost:5173",
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"service": "식자재 관리 및 발주 자동화", "status": "ok", "docs": "/docs"}


@app.get("/health")
def health():
    return {"ok": True, "tables": {k: len(v) for k, v in DATA.items()}}
