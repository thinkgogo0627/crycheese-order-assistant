# scripts/

로컬에서만 돌리는 코드 (모델 학습, 사전 계산). Vercel 배포에서는 제외됨(.vercelignore).

- 결과물은 `data/processed/` 에 저장하고 **git 커밋** → 서버는 `app.core.data.processed("파일명")` 으로 읽기만 함
- 학습 전용 패키지(lightgbm 등)는 `requirements.txt` 에 넣지 않는다 (서버 용량 절약). 대신 `scripts/requirements.txt`
- 실행은 레포 루트에서: `python -m scripts.train_forecast`
