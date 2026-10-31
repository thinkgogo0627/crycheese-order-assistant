# 기능 템플릿

**규격은 `app/features/SPEC.md`가 기준이다. 먼저 읽을 것.**

```bash
cp -r app/features/_template app/features/<name>
```

1. `schemas.py` — 응답 모양 (`ExampleRow`, `ExampleResponse` 이름 변경) → 호진에게 공유
2. `service.py` — 계산 로직 (`compute` 교체)
3. `feature.py` — `name`(= 폴더명), `label`, `description` 수정
4. `app/features/registry.py` — import 한 줄 + FEATURES 한 줄
5. `uvicorn app.main:app --reload` → http://localhost:8000/docs 에서 `POST /api/<name>` 확인
6. `python3 scripts/smoke_test.py` 전부 통과 → PR
