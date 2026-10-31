"""머지 후 배포 점검: 백엔드 · 프론트 · 백-프론트 연동 (표준 라이브러리만 사용).

사용:
    python3 scripts/deploy_check.py                       # production
    python3 scripts/deploy_check.py <프론트URL> <백엔드URL>  # preview 등
"""
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

FRONT = (sys.argv[1] if len(sys.argv) > 1 else "https://hackathon-cry-cheese.vercel.app").rstrip("/")
API = (sys.argv[2] if len(sys.argv) > 2 else "https://hackathon-cry-cheese-api.vercel.app").rstrip("/")
failed = 0


def req(url, method="GET", headers=None):
    r = urllib.request.Request(url, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(r, timeout=60) as res:
            return res.status, res.read(), {k.lower(): v for k, v in res.headers.items()}
    except urllib.error.HTTPError as e:
        return e.code, e.read(), {k.lower(): v for k, v in e.headers.items()}


def check(name, ok, detail=""):
    global failed
    failed += not ok
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))


# 1) 백엔드: 스모크 테스트 그대로 실행
print("=" * 60 + f"\n1) 백엔드  {API}\n" + "=" * 60)
rc = subprocess.call([sys.executable, str(Path(__file__).with_name("smoke_test.py")), API])
check("백엔드 스모크 테스트", rc == 0, "위 FAIL 항목 확인" if rc else "")

# 2) 프론트: 페이지·번들·SPA 라우팅
print("\n" + "=" * 60 + f"\n2) 프론트  {FRONT}\n" + "=" * 60)
s, html, h = req(FRONT + "/")
html = html.decode(errors="replace")
check("GET / (index.html)", s == 200 and "<div id=\"root\"" in html, f"{s}")
scripts = re.findall(r'src="(/assets/[^"]+\.js)"', html)
check("JS 번들 참조", bool(scripts), ", ".join(scripts) or "없음 — 빌드 실패 또는 이전 배포")
bundle = ""
for src in scripts:
    s, b, _ = req(FRONT + src)
    check(f"GET {src}", s == 200, f"{s}, {len(b)//1024}KB")
    bundle += b.decode(errors="replace")
s, _, _ = req(FRONT + "/status")
check("SPA 라우팅 (/status 새로고침)", s == 200, f"{s}")

# 3) 연동: 프론트 번들에 박힌 API 주소 + CORS
print("\n" + "=" * 60 + "\n3) 백-프론트 연동\n" + "=" * 60)
check("번들에 백엔드 주소 포함 (VITE_API_URL)", API in bundle,
      "OK" if API in bundle else "없음 → 프론트 환경변수 VITE_API_URL 확인 후 Redeploy")
urls = sorted(set(re.findall(r"https://[a-z0-9-]+\.(?:up\.railway\.app|vercel\.app|onrender\.com)", bundle)) - {FRONT})
if urls:
    print(f"       번들 안의 외부 주소: {urls}")
paths = sorted(set(re.findall(r"""['"`](/api/[a-z0-9_/-]+)['"`]""", bundle)))
print(f"       프론트가 호출하는 API: {paths or '없음'}")
s, b, _ = req(API + "/openapi.json")
served = set(re.findall(r'"(/api/[a-z0-9_/-]+)"', b.decode(errors="replace"))) if s == 200 else set()
missing = [p for p in paths if p not in served]
check("프론트가 호출하는 API가 백엔드에 모두 존재", not missing, f"없는 API: {missing}" if missing else f"{len(paths)}개 OK")

s, _, h = req(API + "/api/features", "OPTIONS",
              {"Origin": FRONT, "Access-Control-Request-Method": "POST",
               "Access-Control-Request-Headers": "content-type"})
check("CORS preflight (프론트 도메인 → POST)", s == 200 and h.get("access-control-allow-origin") == FRONT,
      f"{s}, allow-origin={h.get('access-control-allow-origin', '없음')}")

print("\n" + ("전부 통과" if not failed else f"실패 {failed}개"))
sys.exit(1 if failed else 0)
