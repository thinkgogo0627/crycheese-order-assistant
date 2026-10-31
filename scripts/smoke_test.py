"""API 스모크 테스트 (표준 라이브러리만 사용).
- [기능] /api/features 에 등록된 모든 기능을 SPEC 규격(응답 공통 필드·basis·에러 포맷)으로 검사
- [LEGACY] 임시 엔진 /api/plan, /api/backtest, /dashboard (엔진 삭제 시 이 블록도 삭제)

사용:
    python3 scripts/smoke_test.py                                          # 로컬 http://localhost:8000
    python3 scripts/smoke_test.py https://hackathon-cry-cheese-api.vercel.app
"""
import json
import sys
import time
import urllib.error
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")
SC = {"as_of": "2026-09-15", "store_id": "S02", "horizon_days": 7,
      "demand_multiplier": 1.2, "delay_days": 1, "service_level": None}
PLAN_KEYS = ["forecast", "ingredients", "comparison", "orders", "all_orders", "transfers",
             "alerts", "blocked", "data_issues", "assumptions"]
failed = 0


def call(method, path, body=None):
    req = urllib.request.Request(
        BASE + path, method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Origin": "http://localhost:5173"},
    )
    t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw, status, headers = r.read(), r.status, r.headers
    except urllib.error.HTTPError as e:
        raw, status, headers = e.read(), e.code, e.headers
    ms = int((time.time() - t) * 1000)
    try:
        body = json.loads(raw)
    except Exception:
        body = raw[:200].decode(errors="replace")
    return status, body, {k.lower(): v for k, v in headers.items()}, ms


def check(name, ok, detail=""):
    global failed
    failed += not ok
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))


print(f"대상: {BASE}\n")

s, j, h, ms = call("GET", "/health")
n = len(j.get("tables", {})) if isinstance(j, dict) else 0
check("GET /health (데이터 17개 로드)", s == 200 and isinstance(j, dict) and j.get("ok") and n == 17,
      f"{s}, ok={j.get('ok') if isinstance(j, dict) else j}, 테이블 {n}개, {ms}ms")
check("CORS 헤더", "access-control-allow-origin" in h, h.get("access-control-allow-origin", "없음"))

# ---------------- 기능 (SPEC 규격) ----------------
s, feats, _, ms = call("GET", "/api/features")
check("GET /api/features", s == 200 and isinstance(feats, list), f"{s}, {[f.get('name') for f in feats] if isinstance(feats, list) else feats}")
for f in feats if isinstance(feats, list) else []:
    name = f["name"]
    s, j, _, ms = call("POST", f"/api/{name}", SC)
    if s != 200 or not isinstance(j, dict):
        check(f"POST /api/{name}", False, f"{s}, {json.dumps(j, ensure_ascii=False)[:300]}")
        continue
    lists = {k: v for k, v in j.items() if isinstance(v, list) and k != "assumptions"}
    rows = [r for v in lists.values() for r in v if isinstance(r, dict)]
    no_basis = sum(1 for r in rows if not r.get("basis"))
    check(f"POST /api/{name}", j.get("scenario", {}).get("store_id") == "S02",
          f"{ms}ms, " + ", ".join(f"{k} {len(v)}" for k, v in lists.items()))
    check(f"  {name}: assumptions 있음", bool(j.get("assumptions")), str(len(j.get("assumptions") or [])))
    check(f"  {name}: 모든 행에 basis", no_basis == 0, f"basis 없는 행 {no_basis}/{len(rows)}")
    check(f"  {name}: 3초 이내", ms < 3000, f"{ms}ms")
    s, j, _, _ = call("POST", f"/api/{name}", {**SC, "as_of": "2026-12-01"})
    check(f"  {name}: 범위 밖 입력 → 422 + error 포맷", s == 422 and isinstance(j, dict) and "error" in j, str(s))
if isinstance(feats, list) and not feats:
    print("       (등록된 기능 없음 — registry.py 에 추가하면 자동으로 검사됨)")

s, j, _, _ = call("POST", "/api/__nope__", SC)
check("없는 경로 → 404 + error 포맷", s == 404 and isinstance(j, dict) and "error" in j, str(s))

# ---------------- [LEGACY] 임시 엔진 ----------------
s, j, h, ms = call("POST", "/api/plan", SC)
if s == 200 and isinstance(j, dict):
    missing = [k for k in PLAN_KEYS if k not in j]
    check("POST /api/plan", not missing and j.get("store_id") == "S02",
          f"{ms}ms, 누락 키 {missing}" if missing else
          f"{ms}ms, 예측 {len(j['forecast'])} · 발주 {len(j['orders'])} · 이동 {len(j['transfers'])} · "
          f"알림 {len(j['alerts'])} · 비교 {len(j['comparison'])} · 추천 {j.get('recommended_mode')}")
    check("  plan 응답 시간 < 10초", ms < 10000, f"{ms}ms")
else:
    check("POST /api/plan", False, f"{s}, {json.dumps(j, ensure_ascii=False)[:300]}")

s2, j2, _, ms = call("POST", "/api/plan", {**SC, "demand_multiplier": 1.8})
if s == 200 and s2 == 200:
    a = sum(o.get("amount", 0) for o in j["orders"])
    b = sum(o.get("amount", 0) for o in j2["orders"])
    check("  조건 변경 → 결과 변화 (수요배율 1.2 → 1.8)", a != b, f"발주금액 {a:,.0f} → {b:,.0f}원")

s, j, _, ms = call("POST", "/api/plan", {**SC, "horizon_days": 99})
check("범위 밖 입력 → 422", s == 422, f"{s}")

s, j, _, ms = call("GET", "/api/backtest")
check("GET /api/backtest", s == 200 and isinstance(j, dict), f"{s}, 키 {list(j)[:6] if isinstance(j, dict) else j}")

s, j, _, ms = call("GET", "/dashboard")
check("GET /dashboard", s == 200, f"{s}")

print(f"\n{'전부 통과' if not failed else f'실패 {failed}개'}")
sys.exit(1 if failed else 0)
