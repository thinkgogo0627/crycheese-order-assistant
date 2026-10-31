"""FastAPI read-only planning API. No purchases or transfers are executed."""
from pathlib import Path
import os

import pandas as pd
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

from app.engine import Engine, Scenario

ROOT = Path(__file__).resolve().parent.parent
RAW = Path(os.environ.get('CRY_DATA_DIR', str(ROOT / 'data' / 'raw')))
DATA = {p.stem: pd.read_csv(p, encoding='utf-8-sig') for p in sorted(RAW.glob('*.csv'))}
ENGINE = Engine(DATA) if len(DATA) >= 17 else None

app = FastAPI(title='크라이치즈버거 발주·재고 의사결정 도우미')
app.add_middleware(CORSMiddleware,
                   allow_origin_regex=r'https://.*\.vercel\.app|http://localhost:5173|http://127\.0\.0\.1:5173',
                   allow_methods=['*'],allow_headers=['*'])

@app.get('/')
def root():
    return {'service':'발주·재고 의사결정 도우미','status':'ok','dashboard':'/dashboard','docs':'/docs','data_ready':ENGINE is not None}

@app.get('/dashboard', response_class=HTMLResponse)
def dashboard():
    return (ROOT / 'app' / 'static' / 'index.html').read_text(encoding='utf-8')

@app.get('/health')
def health():
    return {'ok':ENGINE is not None,'tables':{k:len(v) for k,v in DATA.items()}}

@app.post('/api/plan')
def plan(scenario: Scenario):
    if ENGINE is None:
        from fastapi import HTTPException
        raise HTTPException(503,'서버의 비공개 CSV 데이터가 로딩되지 않았습니다. CRY_DATA_DIR를 설정해 주세요.')
    return ENGINE.plan(scenario)

@app.get('/api/backtest')
def backtest():
    if ENGINE is None or ENGINE.backtest is None:
        from fastapi import HTTPException
        raise HTTPException(503,'백테스트 결과가 없습니다.')
    return ENGINE.backtest
