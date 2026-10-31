"""API 스모크 테스트 (표준 라이브러리만 사용).

사용:
    python scripts/smoke_test.py                              # 로컬 http://localhost:8000
    python scripts/smoke_test.py https://<백엔드>.vercel.app   # 배포본
"""
import json
import sys
import urllib.error
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")
SC = {"as_of": "2026-09-15", "store_id": "S02", "horizon_days": 7,
      "demand_multiplier": 1.2, "delay_days": 1, "service_level": None}
failed = 0


def call(method, path, body=None):
    req = urllib.request.Request(
        BASE + path, method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Origin": "http://localhost:5173"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"null"), dict(r.headers)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw), dict(e.headers)
        except Exception:
            return e.code, raw[:200].decode(errors="replace"), dict(e.headers)


def check(name, ok, detail=""):
    global failed
    failed += not ok
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))


print(f"대상: {BASE}\n")

s, j, h = call("GET", "/health")
check("GET /health", s == 200 and isinstance(j, dict) and j.get("ok"),
      f"{s}, 테이블 {len(j.get('tables', {})) if isinstance(j, dict) else '?'}개 (17개여야 함)")
check("CORS 헤더", "access-control-allow-origin" in {k.lower() for k in h}, h.get("access-control-allow-origin", "없음"))

s, j, _ = call("GET", "/api/features")
names = [f["name"] for f in j] if s == 200 else []
check("GET /api/features", s == 200 and len(names) >= 3, f"{names}")

for n in names:
    s, j, _ = call("POST", f"/api/{n}", SC)
    ok = s == 200 and isinstance(j, dict) and j.get("scenario", {}).get("store_id") == "S02"
    sizes = {k: len(v) for k, v in j.items() if isinstance(v, list)} if isinstance(j, dict) else j
    check(f"POST /api/{n}", ok, f"{s}, {sizes}")

s, j, _ = call("POST", "/api/orders")
check("빈 body → 기본 시나리오", s == 200, str(s))

s, j, _ = call("POST", "/api/orders", {"as_of": "2026-12-01"})
check("범위 밖 입력 → 422 + error 포맷", s == 422 and isinstance(j, dict) and "error" in j,
      json.dumps(j, ensure_ascii=False)[:120])

s, j, _ = call("POST", "/api/nope", SC)
check("없는 경로 → 404 + error 포맷", s == 404 and isinstance(j, dict) and "error" in j, str(s))

print(f"\n{'전부 통과' if not failed else f'실패 {failed}개'}")
sys.exit(1 if failed else 0)
