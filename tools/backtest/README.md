# 백테스트 도구

`app/static/backtest.json`(화면의 '백테스트 검증' 탭)을 만든 코드입니다.

- `sim.py`: 재고 시뮬레이터. 실제 시간대별 수요로 판매하고, 재고가 모자라면 그 식자재를 쓰는 메뉴를 그날 판매 중단한 뒤 긴급발주(다음날 07시 입고), 매장 간 이동(명세서 7절 생성 규칙), 사용기한 폐기, 냉장 품질 폐기(잔량의 일 0.3%)를 재현합니다.
  - 검증: 기존 정책(`policies.Baseline`, 명세서 7절)으로 돌리면 품절 17건(실제 15), 이동 87건(실제 81), 기한폐기 380,947원(실제 379,545원), 평균 재고금액 658.9만 원(실제 659.0만 원).
- `run_backtest.py`: `app/engine.py`의 발주 로직을 매일 호출해 2~9월, 7~9월 성과를 계산합니다.
- `run_robust.py`: 실제 시간대별 수요를 포아송 재표본한 5개 경로에서 같은 비교를 반복합니다.

```bash
pip install -r requirements.txt scipy
python tools/backtest/run_backtest.py
python tools/backtest/run_robust.py
```

데이터 위치는 `CRY_DATA_DIR` 환경변수(기본 `data/raw`)를 따릅니다.
