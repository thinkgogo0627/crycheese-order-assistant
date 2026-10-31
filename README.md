# 식자재 관리 및 발주 자동화 (크라이치즈버거 AX 해커톤 주제 1)

백엔드: FastAPI on Vercel (`app/main.py`의 `app` 자동 인식) · 프론트: React + Vite on Vercel (`frontend/`)

## 로컬 실행

```bash
pip install -r requirements.txt uvicorn
uvicorn app.main:app --reload       # http://localhost:8000/docs
```

## 구조와 담당

```
Hackathon/
├─ app/
│  ├─ main.py                [호진] 서버 입구. 등록된 기능마다 POST /api/{name} 자동 생성
│  ├─ core/                  [호진] 공통 부품
│  │  ├─ scenario.py           화면 입력값(Scenario). 모든 기능의 유일한 입력
│  │  ├─ data.py               데이터 접근 함수. CSV는 여기서만 읽는다
│  │  └─ errors.py             AppError → {"error":{"code","message"}}
│  └─ features/
│     ├─ base.py             [호진] Feature / Row / BaseResponse 계약
│     ├─ registry.py         [호진] 기능 목록 (조원은 FEATURES에 한 줄 추가만)
│     ├─ _template/          [호진] 복사용 견본
│     ├─ forecast/           [조원 A] 수요 예측          → POST /api/forecast
│     ├─ inventory/          [조원 B] 재고 투영 + 알림    → POST /api/inventory
│     └─ orders/             [조원 C] 발주 추천          → POST /api/orders
├─ scripts/                  [조원] 로컬 전용 (학습·사전 계산). 배포 제외
├─ data/
│  ├─ raw/                   원본 CSV (수정 금지)
│  └─ processed/             scripts 결과물 → 반드시 커밋 (배포본은 이것만 읽음)
└─ frontend/                 [호진]
```

## 기능 폴더 = 파일 3개

| 파일 | 역할 | 규칙 |
|---|---|---|
| `schemas.py` | 응답 모양 (Pydantic) | **제일 먼저 작성해서 호진에게 공유.** 행은 `Row` 상속 → `basis`(근거) 필수 |
| `service.py` | 계산 로직 | FastAPI import 금지. 데이터는 `app.core.data`만 사용 |
| `feature.py` | 선언 (name, label, Response, run) | 5~10줄 |

자기 폴더 안에서는 파일을 자유롭게 추가해도 됨 (`utils.py` 등). **자기 폴더 밖은 수정 금지** (예외: `registry.py` 한 줄).

현재 forecast / inventory / orders 는 **STUB**(호진이 만든 임시 계산)이 들어 있음. 응답 모양은 초안이니 담당자가 수정하고 공유.

## 새 기능 추가 순서

1. `cp -r app/features/_template app/features/<이름>`
2. `schemas.py` 작성 → 호진에게 공유
3. `service.py` 채우기
4. `feature.py`의 `name`, `label`, `description` 수정
5. `app/features/registry.py`의 `FEATURES`에 한 줄 추가
6. `/docs`에서 `POST /api/<이름>` 확인

## 기능끼리 호출

```
forecast → inventory → orders
```

```python
from app.features import registry      # 모듈째 import (순환 import 방지)
fc = registry.run("forecast", sc)      # 같은 시나리오면 캐시에서 나옴
```

다른 기능 폴더의 코드를 직접 import 하지 않는다.

## 데이터 접근 (`app/core/data.py`)

| 함수 | 내용 |
|---|---|
| `table(name)` | 원본 테이블. 번호 뗀 이름: `table("sales")`, `table("inventory_lots_daily")` |
| `ingredients()` | 식자재 + 공급사 조건 |
| `bom()` / `menus_available(store, on)` / `prices(on)` | BOM / 취급 메뉴 / 유효 단가(발주 단위) |
| `sales(store, as_of)` / `daily_menu_demand(store, as_of)` | as_of 전날까지 판매 / 일×메뉴 수요 합 |
| `inventory_daily(store, as_of)` | as_of 전날까지 일별 재고 |
| `lots(store, as_of)` | 전날 영업 종료 lot 잔량 (last_use_date 순) |
| `open_orders(store, as_of)` | as_of 아침 기준 미입고 발주 (`use_qty` = 사용 단위 환산) |
| `processed(file)` | scripts 결과물 |

필요한 함수가 없으면 호진에게 요청.

**시점 규약**: `as_of` = 판단일 아침. as_of 당일 이후 데이터를 쓰면 미래 정보 누수.

## 조원이 가져온 것 → 넣을 위치

| 가져온 것 | 위치 |
|---|---|
| 기준일·매장 → 결과 함수 | `app/features/<기능>/service.py` |
| 결과 컬럼 구성 | `app/features/<기능>/schemas.py` |
| 노트북·학습 코드 | 학습은 `scripts/`, 서빙 계산만 `service.py` |
| 모델·사전 계산 테이블 | `data/processed/` (커밋) |
| 서버에서 쓰는 새 패키지 | `requirements.txt` (호진에게 알림) |
| 학습에만 쓰는 패키지 | `scripts/requirements.txt` |

## Vercel 제약

- 배포 후 파일 쓰기 불가 → 학습·테이블 생성은 로컬 `scripts/`에서 하고 결과를 커밋
- cold start마다 CSV 재로딩, 캐시는 인스턴스 안에서만 유효
- 패키지 용량·실행 시간 제한 → LightGBM은 서버에서 돌리지 말고 예측 테이블을 미리 만들어 읽기
