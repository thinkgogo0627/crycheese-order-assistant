"""
데이터 접근은 전부 여기를 거친다. (기능 코드에서 pd.read_csv 금지)

- raw/ CSV 17개: import 시 1회 로드 (Vercel cold start마다 1회, ~10MB라 문제 없음)
- processed/ 결과물: 처음 요청될 때 1회 로드 (scripts/ 가 만들고 git에 커밋한 파일)
- 날짜 컬럼은 전부 datetime64 로 변환해 둠 → Scenario의 date와 비교할 때 _ts() 사용

시점 규약: 아래 함수들은 as_of(판단일 아침) 기준으로 "그 시점에 알 수 있는 것"만 돌려준다.
새 접근 함수가 필요하면 호진에게 요청.
"""
import os
from datetime import date
from functools import lru_cache
from pathlib import Path

import pandas as pd

from app.core.errors import AppError

ROOT = Path(__file__).resolve().parents[2]
RAW = Path(os.environ.get("CRY_DATA_DIR", str(ROOT / "data" / "raw")))
PROCESSED = ROOT / "data" / "processed"

DATE_COLS = {"date", "valid_from", "start_date", "end_date", "order_date",
             "expected_date", "receipt_date", "last_use_date"}


def _load(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="utf-8-sig")  # 첫 줄 BOM 제거
    for c in DATE_COLS & set(df.columns):
        df[c] = pd.to_datetime(df[c])
    return df


# "09_sales" → "sales" 처럼 번호 뗀 이름으로 접근
RAW_TABLES: dict[str, pd.DataFrame] = {
    p.stem.split("_", 1)[1]: _load(p) for p in sorted(RAW.glob("*.csv"))
}


def _ts(d: date) -> pd.Timestamp:
    return pd.Timestamp(d)


def table(name: str) -> pd.DataFrame:
    """원본 테이블 그대로 (복사본). 예: table("sales"), table("inventory_lots_daily")"""
    if name not in RAW_TABLES:
        raise AppError("no_table", f"없는 테이블: {name} (가능: {', '.join(RAW_TABLES)})", 500)
    return RAW_TABLES[name].copy()


@lru_cache(maxsize=None)
def _processed(name: str) -> pd.DataFrame:
    path = PROCESSED / name
    if not path.exists():
        raise AppError("no_artifact", f"data/processed/{name} 가 없습니다 (scripts 실행·커밋 필요)", 500)
    if path.suffix == ".csv":
        return _load(path)
    if path.suffix in (".pkl", ".pickle"):
        return pd.read_pickle(path)
    raise AppError("bad_artifact", f"지원하지 않는 형식: {name}", 500)


def processed(name: str) -> pd.DataFrame:
    """scripts/ 결과물. 예: processed("forecast.csv")"""
    return _processed(name).copy()


# ---------- 마스터 ----------
def ingredients() -> pd.DataFrame:
    """식자재 마스터 + 공급사 조건 (발주 요일, 리드타임, 최소 발주금액)."""
    return table("ingredients").merge(table("suppliers"), on="supplier_id", how="left")


def bom() -> pd.DataFrame:
    """menu_id, ingredient_id, qty_per_menu, use_unit"""
    return table("bom")


def menus_available(store_id: str, on: date) -> pd.DataFrame:
    """해당 매장에서 on 날짜에 '취급' 중인 메뉴."""
    a = table("menu_availability")
    t = _ts(on)
    a = a[(a.store_id == store_id) & (a.status == "취급") & (a.start_date <= t) & (a.end_date >= t)]
    return table("menus").merge(a[["menu_id"]], on="menu_id")


def prices(on: date) -> pd.DataFrame:
    """on 날짜에 유효한 식자재 단가 (ingredient_id, unit_price). 단가는 발주 단위 기준."""
    p = table("ingredient_price_history")
    p = p[p.valid_from <= _ts(on)].sort_values("valid_from")
    return p.groupby("ingredient_id", as_index=False).last()[["ingredient_id", "unit_price"]]


# ---------- 과거 실적 (as_of 전날까지만) ----------
def sales(store_id: str, as_of: date) -> pd.DataFrame:
    """as_of 전날까지의 시간대별 판매 원본."""
    s = table("sales")
    return s[(s.store_id == store_id) & (s.date < _ts(as_of))]


def daily_menu_demand(store_id: str, as_of: date) -> pd.DataFrame:
    """date × menu_id 일별 수요(demand_qty = 품절 전 수요) 합계."""
    s = sales(store_id, as_of)
    return s.groupby(["date", "menu_id"], as_index=False)["demand_qty"].sum()


def inventory_daily(store_id: str, as_of: date) -> pd.DataFrame:
    """as_of 전날까지의 일별 재고 기록 (10_inventory_daily)."""
    i = table("inventory_daily")
    return i[(i.store_id == store_id) & (i.date < _ts(as_of))]


# ---------- as_of 시점 상태 ----------
def lots(store_id: str, as_of: date) -> pd.DataFrame:
    """as_of 전날 영업 종료 시점의 lot별 잔량 (FEFO용, last_use_date 오름차순).
    재고가 0인 품목은 행이 없음. 잔량 합 = 10_inventory_daily.closing_qty (검증 완료)."""
    l = table("inventory_lots_daily")
    l = l[(l.store_id == store_id) & (l.date == _ts(as_of) - pd.Timedelta(days=1))]
    return l.sort_values(["ingredient_id", "last_use_date"]).reset_index(drop=True)


def open_orders(store_id: str, as_of: date) -> pd.DataFrame:
    """as_of 아침 기준 미입고 발주 = as_of 전에 발주했고, as_of 전에 입고 기록이 없는 줄.
    use_qty 컬럼 = order_qty × use_qty_per_order_unit (사용 단위 환산).
    가정: 부분·지연 입고 없음(명세서), 입고 예정일(expected_date)에 전량 도착."""
    po = table("purchase_orders")
    rc = table("receipts")
    t = _ts(as_of)
    received = set(rc.loc[rc.receipt_date < t, "po_line_id"])
    po = po[(po.store_id == store_id) & (po.order_date < t) & ~po.po_line_id.isin(received)]
    conv = table("ingredients")[["ingredient_id", "use_qty_per_order_unit"]]
    po = po.merge(conv, on="ingredient_id", how="left")
    po["use_qty"] = po.order_qty * po.use_qty_per_order_unit
    return po.drop(columns="use_qty_per_order_unit").reset_index(drop=True)


def summary() -> dict[str, int]:
    """/health 용: 테이블별 행 수."""
    return {k: len(v) for k, v in RAW_TABLES.items()}
