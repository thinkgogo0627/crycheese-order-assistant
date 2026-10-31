# 기능 규격 (SPEC)

> Claude Code에 맡길 때: **"`app/features/SPEC.md`를 읽고, 그 규격에 맞춰 `app/features/<기능명>/`에 기능을 작성해. `_template/`을 복사해서 시작해."**

이 문서를 어기는 코드는 머지하지 않는다. 규격에 없는 게 필요하면 먼저 호진에게 묻는다.

---

## 0. 한눈에

```
화면 입력(Scenario) ──POST /api/<name>──▶ <name>/feature.py ─▶ service.py ─▶ 응답(<Name>Response)
                                                     │
                                       app.core.data (데이터) / registry.run (다른 기능)
```

- 기능 1개 = 폴더 1개 = API 1개 = 화면 1개
- 서버 입구(`app/main.py`)는 건드리지 않는다. `registry.py`에 등록하면 `POST /api/<name>`이 자동 생성된다.

---

## 1. 위치와 이름

| 항목 | 규칙 |
|---|---|
| 폴더 | `app/features/<name>/` — `_template/`을 복사해서 시작 |
| 이름 `<name>` | 영어 소문자 snake_case 한 단어~두 단어 (예: `demand_forecast`, `order_recommend`) |
| URL | `POST /api/<name>` (자동) |
| 수정 가능 범위 | **자기 폴더 안 + `registry.py` 두 줄**. 그 외 파일은 수정 금지 |

폴더 안 필수 파일:

| 파일 | 역할 | 규칙 |
|---|---|---|
| `schemas.py` | 응답 모양 | **가장 먼저 작성해서 호진에게 공유** (프론트가 이걸 보고 화면을 만든다) |
| `service.py` | 계산 로직 | FastAPI import 금지 |
| `feature.py` | 선언 (`name`, `label`, `description`, `Response`, `run`) | 5~10줄 |

필요하면 같은 폴더에 `utils.py` 등 자유롭게 추가.

---

## 2. 입력 규격

- 모든 기능의 입력은 **`app.core.scenario.Scenario` 하나**. 기능별 입력 모델을 따로 만들지 않는다.

| 필드 | 타입 | 기본값 | 의미 |
|---|---|---|---|
| `as_of` | date | 2026-10-01 | 판단일 **아침** (2026-07-01 ~ 2026-10-01) |
| `store_id` | `S01`/`S02`/`S03` | S01 | 매장 |
| `horizon_days` | int 1~14 | 7 | 예측·투영 일수 |
| `demand_multiplier` | float | 1.0 | 수요 배율 k (가상 시나리오) |
| `delay_days` | int 0~14 | 0 | 입고 지연 일수 (가상 시나리오) |
| `service_level` | float \| null | null | 목표 서비스 수준. null = 기능이 품목별로 결정 |

- 편의 속성: `sc.last_closed` (= as_of − 1일, 볼 수 있는 마지막 영업일), `sc.horizon` (as_of부터 horizon_days일 날짜 리스트)
- 새 입력이 필요하면 **호진에게 요청** → `core/scenario.py`에 **기본값과 함께** 추가 + 프론트 타입 반영. 직접 추가 금지.

---

## 3. 출력 규격

```python
from app.features.base import BaseResponse, Row

class OrderLine(Row):            # 표의 한 줄 = Row 상속 → basis(근거) 필드 자동 포함
    ingredient_id: str
    ingredient_name: str
    order_qty: int
    ...

class OrderResponse(BaseResponse):   # 응답 = BaseResponse 상속 → scenario, assumptions 자동 포함
    lines: list[OrderLine]
```

| 규칙 | 내용 |
|---|---|
| 응답 클래스 | `BaseResponse` 상속, 이름은 `<Name>Response` |
| 표 행 | `Row` 상속 → **`basis` 필수**: 이 숫자가 왜 나왔는지 사람이 읽는 문장 (예: `"7일 소요 3,550매 + 안전재고 420매 − 재고 1,200매 → 박스 120매 단위 올림 23박스"`) |
| `assumptions` | 이 결과에 쓰인 가정을 문장 리스트로 (예: `"입고 예정일에 전량 도착"`) |
| `scenario` | 쓰지 않는다. registry가 자동으로 채운다 |
| 반환 | `run()`은 반드시 `Response` 인스턴스를 반환 (dict 반환 시 500) |

### 단위·표기

| 대상 | 규칙 |
|---|---|
| 수량 | 기본은 **사용 단위(use_unit)**. 필드명 `*_qty` + 같은 행에 `use_unit` 표기 |
| 발주 수량 | **발주 단위(order_unit)** 정수. 필드명 `order_qty` + `order_unit` 표기. 환산: `⌈사용단위 수량 ÷ use_qty_per_order_unit⌉` |
| 금액 | 원, 정수 (`amount`, `*_cost`, `*_price`) |
| 날짜 | `date` 타입 (JSON에서 `"YYYY-MM-DD"`) |
| 비율 | 0~1 소수 (화면에서 %로 변환) |
| 키 이름 | snake_case 영어 |
| 식자재·메뉴 | id와 이름을 같이 (`ingredient_id` + `ingredient_name`, `menu_id` + `menu_name`) |

---

## 4. 의존성 규격

### 4-1. 데이터 — `app.core.data`로만 읽는다

`pd.read_csv` 직접 사용 금지. **CSV 수정·삭제·`git rm` 금지** (배포 데이터가 사라짐).

| 함수 | 반환 |
|---|---|
| `data.table(name)` | 원본 테이블 복사본. 번호 뗀 이름: `"sales"`, `"inventory_lots_daily"` … |
| `data.ingredients()` | 식자재 + 공급사 조건 (발주 요일, 리드타임, 최소 발주금액) |
| `data.bom()` | 메뉴별 식자재 사용량 |
| `data.menus_available(store, on)` | 그날 취급 메뉴 |
| `data.prices(on)` | 그날 유효 단가 (발주 단위 기준) |
| `data.sales(store, as_of)` | as_of 전날까지 시간대별 판매 |
| `data.daily_menu_demand(store, as_of)` | 일 × 메뉴 수요(demand_qty) 합 |
| `data.inventory_daily(store, as_of)` | as_of 전날까지 일별 재고 |
| `data.lots(store, as_of)` | 전날 영업 종료 lot 잔량 (last_use_date 순) |
| `data.open_orders(store, as_of)` | as_of 아침 기준 미입고 발주 (`use_qty` = 사용 단위 환산) |
| `data.processed(file)` | `data/processed/` 사전 계산 결과 |

필요한 함수가 없으면 **호진에게 요청** (직접 `data.py` 수정 금지).

### 4-2. 다른 기능 결과

```python
from app.features import registry        # 모듈째 import (순환 import 방지)
fc = registry.run("demand_forecast", sc)  # 같은 시나리오면 캐시에서 나옴
```

- 다른 기능 폴더의 코드를 **직접 import 금지**
- 여러 기능이 같이 쓰는 함수 → 호진에게 요청해서 `app/core/`로

### 4-3. 패키지

| 어디서 | 허용 |
|---|---|
| 서버 (`app/`) | 표준 라이브러리, **pandas, numpy, pydantic, fastapi**까지. 그 외 추가는 호진 승인 후 `requirements.txt` |
| 학습·사전 계산 (`scripts/`) | 자유 (lightgbm, sklearn 등). `scripts/requirements.txt`에 기록 |

무거운 모델은 서버에서 돌리지 않는다: `scripts/`에서 결과 테이블을 만들어 `data/processed/`에 저장·**커밋**하고, 서버는 `data.processed()`로 읽기만 한다.

---

## 5. 시점 규약 (미래 정보 누수 금지)

- `as_of` = 판단일 **아침**. 볼 수 있는 데이터는 **as_of 전날 영업 종료까지**.
- `data.py` 함수들은 이미 as_of로 잘라서 준다. `data.table()`로 원본을 직접 쓸 때는 반드시 `date < as_of`로 직접 자를 것.
- 예측·투영 구간은 `sc.horizon` (as_of부터).

---

## 6. 에러

```python
from app.core.errors import AppError
raise AppError("no_data", "해당 기준일의 재고 기록이 없습니다", status=404)
```

- 응답은 자동으로 `{"error": {"code": "no_data", "message": "..."}}`
- `HTTPException` 직접 사용 금지. 예상 못 한 예외는 500 `internal`로 나간다.

---

## 7. 성능

- 요청 1건 **3초 이내** (Vercel 서버리스, cold start 있음)
- 반복 계산은 `registry.run` 캐시를 활용, 무거운 건 사전 계산(4-3)

---

## 8. 작업 흐름 (Git)

1. `git switch main && git pull` → `git switch -c feat/<name>`
2. `cp -r app/features/_template app/features/<name>` → `schemas.py` 먼저 작성·공유
3. `service.py`, `feature.py` 작성 → `registry.py`에 두 줄 추가
4. 로컬 확인:
   ```bash
   uvicorn app.main:app --reload            # http://localhost:8000/docs 에서 POST /api/<name>
   python3 scripts/smoke_test.py            # 다른 터미널, "전부 통과" 확인
   ```
5. PR 올리기. **머지는 호진이 한다** (Vercel 무료 플랜이 조원 커밋 배포를 막음)

## 9. PR 전 체크리스트

- [ ] 내 폴더 + `registry.py` 두 줄 외에 수정한 파일이 없다
- [ ] `schemas.py`를 호진에게 공유했다
- [ ] 모든 표 행에 `basis`, 응답에 `assumptions`가 있다
- [ ] 단위 규칙(3장)을 지켰다 — 수량·발주수량·금액 구분
- [ ] `pd.read_csv`, `HTTPException`, 다른 기능 폴더 import가 없다
- [ ] as_of 당일 이후 데이터를 쓰지 않는다
- [ ] `python3 scripts/smoke_test.py` 전부 통과


## 통합 UI 확장 계약 (2026-10-31)

사용자의 전체 UI·서비스 통합 및 역할별 화면 요청으로 아래 공통 입력을 기본값과 함께 확장했습니다.
개별 기능의 임의 입력 모델은 추가하지 않았습니다. 기존 6개 필드 요청도 그대로 동작합니다.

| 필드 | 기본값 | 의미 |
|---|---|---|
| `hub_store_ids` | null | 중복 없는 실제 매장 ID 배열. null이면 기존 전체 3개 매장 |
| `hub_host_store_id` | null | 허브 역할을 하는 매장. 그룹 안에 있어야 함 |
| `hub_policy` | auto | auto=대안 탐색, assigned=H01 지정 그룹 고정, none=무허브 |
| `max_hubs` | 2 | 허브 상한 0~3 |
| `chilled_capacity_liters` | 200 | 허브 자체 영업 재고를 제외한 냉장 여유 L |
| `frozen_capacity_liters` | 200 | 냉동 여유 L |
| `ambient_capacity_liters` | 150 | 상온 여유 L |
| `hub_daily_cost` | 12000 | 허브당 가정 운영비 원/일 |
| `transfer_cost` | 0 | 배송 추가비 원/회 |
| `can_split_pack` | false | 포장 소분 허용 여부. 현재 UI는 false 고정 |

시연 ID는 프론트 화면 분류이며 인증·권한 검증 수단이 아닙니다. 서버 인증이 필요할 때는
인증 세션에서 매장 범위를 결정해야 하며, 클라이언트가 보낸 범위를 보안 근거로 사용하면 안 됩니다.
머지 담당자와 Git 작업 흐름은 기존 규칙을 유지합니다.
