# 크라이치즈버거 매장 운영 UI

Vite + React + TypeScript + Tailwind. 기존 저장소와 Vercel 배포 구조를 유지합니다.

## 시연 로그인

세 ID 모두 비밀번호는 `cry2026`입니다. 계정 카드를 누르면 입력되고 로그인 버튼으로 진입합니다.

| ID | 역할 | 계산·화면 범위 |
|---|---|---|
| HUB001 | S01 허브 담당자 | S01/S02 그룹 정기발주, 허브 안전재고, 용량, 공급·대안 비교 |
| STORE002 | S02 소속 매장 | 내 재고·발주·긴급발주, 허브 보충 초안 |
| SOLO003 | S03 독립 매장 | S03 단독 정기·긴급발주. 허브 메뉴·배분 제외 |

이는 합성 데이터 시연용 로그인입니다. sessionStorage에 ID만 보관합니다.
실제 사용자 인증·서버 권한 검증·주문 전송·승인·출고·정산을 구현한 것은 아닙니다.
실서비스 전환 시 서버 인증으로 허용 매장 범위를 결정해야 합니다.

## 로컬 실행

```bash
# 저장소 루트
python -m pip install -r requirements.txt
uvicorn app.main:app --port 8000
# 별도 터미널
cd frontend
npm install
cp .env.example .env.local
# VITE_API_URL=http://localhost:8000, VITE_USE_MOCK=false 설정
npm run dev
```

새 허브 화면은 실제 `/api/hub` 응답이 필요합니다. 이전 더미 모드에는 허브 응답이 없으므로
모든 역할을 시연하려면 실제 API를 사용하세요. 원본 CSV는 저장소의 데이터 로딩 규칙을 따릅니다.

## 화면과 데이터

- 공통 로그인 → 역할별 대시보드와 메뉴. 독립 매장 `/hub` 직접 접근은 홈으로 이동합니다.
- 시간별 수요 화면은 최신 main의 `/api/hourly_forecast`를 사용합니다. 선택 매장 예측만 표시하고, 기존 매장 간 직접 이동 실험 API·소스는 보존합니다.
- 재고·예측은 기존 `/api/plan`의 선택 매장 재고·알림·예측만 사용합니다.
- 정기발주·허브·긴급발주는 `/api/hub`를 사용합니다. 기존 엔진의 매장 간 직접 이동 추천은 UI에 노출하지 않습니다.
- 조건 입력은 임시 상태이며 **조건 적용** 버튼으로 계산에 반영합니다.
- `hub_policy=assigned`는 지정 그룹 H01 운영, `auto`는 무허브 포함 비교, `none`은 독립 운영입니다.
- 발주 초안 CSV 다운로드를 제공합니다. 계산 결과가 제약 미달이면 문제 확인용으로 표시합니다.
- 재고의 lot별 소비기한과 예상 사용·폐기 분리는 기존 구현을 유지했습니다.
- 0포장인 항목은 주문 초안에서 제외합니다. 최소금액 미달은 입고로 간주하지 않습니다.

공식 사이트와 같은 **Pretendard Variable**을 로컬 제공하고 **#F8B81C**와 검정·흰색,
둥근 버튼·넉넉한 여백을 운영 화면에 적용했습니다. 공식 로고는 `public/brand/`,
폰트와 SIL OFL 라이선스는 `public/fonts/`에 있습니다.

## 배포

두 Vercel 프로젝트가 있습니다. 프론트와 `/api/hub`를 제공하는 백엔드를 모두 반영해야 합니다.
PR을 검토해 main에 머지한 뒤 각 프로젝트 배포를 확인하세요.
프론트 Root Directory는 `frontend`, `VITE_API_URL`은 실제 API 주소입니다.
로컬 `.env.local`은 Git에 올리지 않습니다. 환경변수는 빌드 시 주입되므로 변경 후 재배포가 필요합니다.

```bash
npm run build
npm run lint
# 저장소 루트에서 백엔드 테스트
python -m pytest tests app/features/hub/test_hub.py -q
python scripts/smoke_test.py http://localhost:8000
```
