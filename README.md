# 크라이치즈버거 발주·재고 의사결정 도우미

크라이치즈버거 AX 해커톤 주제 1 — 식자재 관리 및 발주 자동화

### 🔗 서비스 주소: **https://hackathon-cry-cheese.vercel.app/**

| 구분 | 주소 | 비고 |
|---|---|---|
| **서비스 (웹 화면)** | https://hackathon-cry-cheese.vercel.app/ | 사용자가 접속하는 주소. 시연 계정은 [`frontend/README.md`](frontend/README.md) |
| API 서버 | https://hackathon-cry-cheese-api.vercel.app/ | 화면이 내부적으로 호출하는 백엔드. API 문서는 `/docs` |

---

## 무엇을 하나

3개 매장(S01·S02·S03), 16개 메뉴, 22개 식자재의 판매·재고·발주 이력으로 **"오늘 무엇을 얼마나 발주할지"** 를 근거와 함께 추천합니다.

| 화면 | 경로 | 내용 | API |
|---|---|---|---|
| 운영 대시보드 | `/` | 역할별 요약, 선택 매장 발주 초안 | `/api/hub` |
| 재고·소비기한 | `/inventory` | 부족 예상, 기한 임박 로트, 예상 폐기 | `/api/plan` |
| 정기발주 | `/orders` | 공급사별 발주 초안(수정 가능), 최소 발주금액 처리 | `/api/hub` |
| 허브 공급 | `/hub` | 허브 비축량, 매장 그룹 배정, 무허브 대안 비교 (허브·소속 매장만) | `/api/hub` |
| 긴급발주 | `/emergency` | 정기 입고 전 부족분 외부 긴급발주 초안 | `/api/hub` |
| 수요 예측 | `/forecast` | 7일 메뉴별 예측, 요일·공휴일·행사 보정 | `/api/plan` |
| 시간별 수요 | `/intraday` | 완료된 POS 시간으로 다음 시간 수요 보정 | `/api/hourly_forecast` |
| 데이터 연결 | `/status` | API·데이터 로딩 상태 | `/health`, `/api/features` |

로그인은 역할(허브 담당 / 허브 소속 매장 / 독립 매장)에 따라 보이는 메뉴와 계산 범위가 달라지는 **시연용** 로그인입니다. 실제 인증·주문 전송은 구현하지 않았습니다.

## 핵심 로직

- **수요 예측** (`app/forecast.py`): 메뉴별 EWMA × 매장 요일지수 × 공휴일 계수 × 행사 배율 → BOM으로 식자재 소요량 변환
- **발주** (`app/engine.py`, `app/features/hub/`): 로트 단위 FEFO 재고 전망 → 다음 입고까지 부족량 + 안전재고(품목별 품절 비용 vs 보유 비용) → 포장 단위 올림, 최소 발주금액 이월/채움
- **허브 공급** (`app/features/hub/`): 무허브·허브 대안에 같은 예측을 적용해 비축량·배송·보관 용량·비용을 비교
- **시간별 예측** (`app/features/hourly_forecast/`): 판단 시각 이전에 끝난 POS 실판매로 남은 시간 수요를 보정
- **시점 규약**: `as_of` = 판단일 아침. 전날 영업 종료까지의 데이터만 사용(미래 정보 누수 금지)

상세 근거·백테스트·한계는 아래 문서에 있습니다.

| 문서 | 내용 |
|---|---|
| [`README_SOLUTION.md`](README_SOLUTION.md) | 예측·발주 로직, 백테스트 결과, 가정과 한계 |
| [`README_CALIBRATION.md`](README_CALIBRATION.md) | 시간대별 예측 통합과 검증 |
| [`app/features/hub/README.md`](app/features/hub/README.md) | 허브 공급·긴급발주 계산 흐름 |
| [`app/features/SPEC.md`](app/features/SPEC.md) | 기능 작성 규격 (새 기능 추가 시 필독) |
| [`frontend/README.md`](frontend/README.md) | 화면 구성, 시연 계정 |
| [`tools/backtest/README.md`](tools/backtest/README.md) · [`tools/waste_refinement/README.md`](tools/waste_refinement/README.md) | 백테스트·폐기 보완 분석 |

## 기술 스택

- **백엔드**: Python 3.12, FastAPI, pandas, numpy — Vercel Python 런타임 (`app/main.py`의 `app` 자동 인식)
- **프론트엔드**: React 19, Vite, TypeScript, Tailwind CSS, TanStack Query, Recharts — Vercel 정적 배포 (`frontend/`)

## 데이터

원본 CSV(`data/raw/*.csv`, 17개 테이블)는 **실제 기업 데이터이므로 저장소에 포함하지 않습니다** (`.gitignore`). 테이블 설명은 [`data/raw/데이터명세서.md`](data/raw/데이터명세서.md)에 있습니다.

로컬에서 실행하려면 받은 CSV를 `data/raw/`에 두거나, 다른 폴더를 `CRY_DATA_DIR` 환경변수로 지정합니다.

```bash
python scripts/import_data.py "<받은 데이터 zip 경로>"   # data/raw/ 로 풀기
```

## 로컬 실행

```bash
# 백엔드
pip install -r requirements.txt
uvicorn app.main:app --reload            # http://localhost:8000/docs
```

```bash
# 프론트엔드 (별도 터미널)
cd frontend
npm install
cp .env.example .env.local               # VITE_API_URL=http://localhost:8000
npm run dev                              # http://localhost:5173
```

```bash
# 테스트
pip install -r requirements-dev.txt
python -m pytest
```

```bash
# 배포 점검 (프론트 · API · 연동)
python scripts/deploy_check.py
```

## 폴더 구조

```
├─ app/                      백엔드 (FastAPI)
│  ├─ main.py                서버 입구. 등록된 기능마다 POST /api/{name} 자동 생성
│  ├─ core/                  공통: scenario.py(입력), data.py(데이터 접근), errors.py
│  ├─ features/              기능 1개 = 폴더 1개 → POST /api/<name>
│  │  ├─ registry.py         기능 목록
│  │  ├─ SPEC.md             기능 규격
│  │  ├─ _template/          새 기능 복사용 견본
│  │  ├─ hub/                허브 공급·정기·긴급발주
│  │  └─ hourly_forecast/    시간별 수요 예측·재계획
│  ├─ engine.py, forecast.py, lot_projection.py   일별 예측·발주 엔진 (/api/plan)
│  └─ static/                정적 대시보드 (/dashboard)
├─ frontend/                 웹 화면 (React + Vite)
├─ hub-service/              허브 로직 원형 (표준 라이브러리 단독 실행본)
├─ scripts/                  로컬 전용 도구 (데이터 import, 튜닝, 배포 점검). 배포 제외
├─ tools/                    백테스트·폐기 분석
├─ outputs/baseline_forecast/  베이스라인 예측 노트북
├─ tests/                    pytest
└─ data/
   ├─ raw/                   원본 CSV (커밋 금지)
   └─ processed/             사전 계산 결과물 (커밋)
```

## 새 기능 추가

1. `cp -r app/features/_template app/features/<이름>`
2. `schemas.py`(응답 모양, 행은 `Row` 상속 → `basis` 근거 필수) → `service.py`(계산, FastAPI import 금지) → `feature.py`(name·label·description)
3. `app/features/registry.py`에 import 한 줄 + `FEATURES`에 한 줄
4. `/docs`에서 `POST /api/<이름>` 확인

데이터는 `app.core.data`의 함수(`table`, `sales`, `lots`, `open_orders` 등)로만 읽고, 다른 기능은 `registry.run("<name>", sc)`로 호출합니다. 자세한 규칙은 [`app/features/SPEC.md`](app/features/SPEC.md).

## 배포

| Vercel 프로젝트 | 루트 | 주소 |
|---|---|---|
| 프론트엔드 | `frontend/` | https://hackathon-cry-cheese.vercel.app/ |
| API | 저장소 루트 | https://hackathon-cry-cheese-api.vercel.app/ |

- `main`에 머지하면 두 프로젝트가 자동 배포됩니다.
- 프론트는 빌드 시 `VITE_API_URL`(= API 주소)을 읽습니다.
- Vercel 서버는 파일 쓰기가 불가하므로 학습·사전 계산은 로컬 `scripts/`에서 하고 결과를 `data/processed/`에 커밋합니다.
- 원본 CSV는 저장소에 없으므로 API 서버에는 별도로 데이터를 주입해야 합니다. 데이터가 없으면 `/health`가 `"ok": false`를 반환합니다.

> 모든 금액·수치는 해커톤 제공 데이터 기준이며 실제 매장 성과로 해석하지 않습니다.
