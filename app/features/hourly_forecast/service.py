"""Registry adapter. No FastAPI dependencies; no real orders or transfers."""
from app.core.scenario import Scenario
from .runtime import get_engine, Scenario as RuntimeScenario
from .trend import build_trend
from .intraday import HourlyPlanner, IntradayScenario
from .calibration import baseline_params, rolling_params, read_calibration
from .schemas import HourlyResponse, IntradayResponse

LIMITS = [
    "기본 수요는 전날까지 demand_qty, 당일 보정은 종료된 시간의 qty-cancel_qty만 사용합니다.",
    "live_sales는 전체 확정 스냅샷입니다. 빠진 매장·메뉴·시간은 판매 0으로 간주하며, 부분 전송에는 사용할 수 없습니다.",
    "품절로 관측 판매가 낮으면 잠재 수요를 과소 보정할 수 있습니다.",
    "첨부 7월 선정·8~9월 수치는 반복 열람된 합성 데이터의 탐색 평가입니다.",
    "기존 일별 발주 엔진은 변경하지 않습니다. 1.5배 과소예측 가중치는 위험 선호 가정입니다.",
]

def request(sc):
    return IntradayScenario(**sc.model_dump(include=set(IntradayScenario.model_fields)))

def forecast(sc: Scenario):
    result = HourlyPlanner(get_engine()).rolling(request(sc))
    for row in result['timeline']:
        row['basis'] = f"{len(row['observed_hours'])}개 종료 시간의 누적 실판매 {row['observed_sold_cumulative']}개로 메뉴별 기본예측을 보정"
    engine = get_engine()
    planner = HourlyPlanner(engine)
    request_sc = request(sc)
    _, _, hourly, _ = engine.forecast_bundle(RuntimeScenario(
        as_of=sc.as_of, store_id=sc.store_id, horizon_days=2,
        demand_multiplier=sc.demand_multiplier,
        promotion_multiplier=sc.promotion_multiplier, forecast_profile=sc.forecast_profile))
    now = int(sc.decision_time[:2])
    actual, _ = planner._actual_sales(request_sc, now * 60)
    opening = int(engine.stores[sc.store_id]['open_hour'])
    closing = int(engine.stores[sc.store_id]['close_hour'])
    options = rolling_params(sc.forecast_profile)
    if sc.adjustment_strength is not None:
        options['strength'] = sc.adjustment_strength
    trend = build_trend(
        store_id=sc.store_id, day=sc.as_of.isoformat(), menus=list(engine.menus),
        baseline={(m, h): hourly.get((sc.as_of, sc.store_id, m, h), 0.)
                  for m in engine.menus for h in range(opening, closing)},
        open_hour=opening, close_hour=closing, decision_time=sc.decision_time,
        completed_sales={h: {m: actual.get((sc.store_id, m, h), 0.) for m in engine.menus}
                         for h in range(opening, min(now, closing))}, **options)
    trend['rows'] = [row for row in trend['rows'] if row['hour'] < max(now, opening) + sc.horizon_hours]
    for row in trend['rows']:
        row['basis'] = '완료 시간의 순판매 실적' if row['actual'] is not None else '누적 POS 보정 예측 및 예측값의 ±10% 표시 범위'
    result['trend'] = trend
    result['assumptions'] = LIMITS
    result['calibration'] = {
        'profile': sc.forecast_profile,
        'baseline': baseline_params(sc.forecast_profile),
        'rolling': {**rolling_params(sc.forecast_profile), **({'strength': sc.adjustment_strength} if sc.adjustment_strength is not None else {})},
        'reported_metrics': read_calibration()['metrics'],
    }
    return HourlyResponse.model_validate(result)

def plan(sc: Scenario):
    result = HourlyPlanner(get_engine()).plan(request(sc))
    for key in ['observed', 'hourly_forecast', 'risks', 'transfers']:
        for row in result[key]:
            row['basis'] = {
                'observed': '완료된 영업시간 누적 실판매 / 동일 시간 기본예측으로 보정',
                'hourly_forecast': '전날까지 기본 수요 × 완료 시간 누적 POS 기반 메뉴별 보정배율',
                'risks': '전날 lot + 예정 입고 - 확정 판매 BOM 소진과 이후 예상 소요를 비교',
                'transfers': '발송점 잔여일 수요와 다음 날 40% 보호량을 제외하고, 30분 뒤 도착한 lot만 소비 가능',
            }[key]
    result['assumptions'] += LIMITS + [
        '이동량은 사용단위의 연속량이며 소분·동시 운송 가능을 가정합니다. 실제 실행 전 규격 검토가 필요합니다.',
        '재계획의 다음 날 40% 보호량은 고정 가정입니다. 일별 서비스 수준 입력은 이 계산에 적용되지 않습니다.',
        '기한이 지난 미입고 예정일은 판단일로 이월하는 가정이며 실제 도착 확정이 아닙니다.',
    ]
    return IntradayResponse.model_validate(result)
