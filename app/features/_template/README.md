# 기능 템플릿

1. 이 폴더를 복사해서 이름 변경: `cp -r app/features/_template app/features/<기능이름>`
2. `schemas.py` 응답 모양 작성 → 호진에게 공유 (프론트 화면이 이걸 보고 만들어짐)
3. `service.py` 계산 로직 작성
4. `feature.py` 의 name / label / description 수정
5. `app/features/registry.py` 의 FEATURES 에 한 줄 추가
6. 로컬 확인: `uvicorn app.main:app --reload` → http://localhost:8000/docs 에서 POST /api/<기능이름>

규칙
- FastAPI import 금지 (service.py, schemas.py)
- CSV·모델 파일을 직접 열지 않는다 → `app.core.data` 함수만 사용 (필요한 함수는 호진에게 요청)
- 다른 기능 결과는 `registry.run("forecast", sc)` 로만 받는다
- 응답 행은 `Row` 를 상속 → `basis`(근거) 필수
- 가정은 `assumptions` 리스트에 문장으로 적는다
- 에러는 `raise AppError("code", "메시지", status)` 
