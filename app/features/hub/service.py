"""Read-only hub feature. Source access and forecast computation are shared."""
from functools import lru_cache

from .planner import Dataset, Planner, clean_config
from app.core import data
from app.forecast import Forecaster
from datetime import timedelta
from .settings import SETTINGS
from app.core.errors import AppError
from app.core.scenario import Scenario
from .schemas import (Alternative, EmergencyOrder, HubGroup, HubOrder, HubResponse,
                      HubTransfer, Shortage)


class HubForecaster(Forecaster):
    # Local horizon extension; the shared forecasting formula is unchanged.
    K = 48


class CommonForecastData(Dataset):
    def __init__(self, frames):
        super().__init__(frames=frames, select_models=False)
        self.F = HubForecaster(frames)
        self.si = {s: i for i, s in enumerate(self.F.stores)}
        self.selection = {s: 'ewma' for s in self.stores}

    def ingredient_forecast(self, origin, target, source):
        k = (target-origin).days
        if not 0 <= k < self.F.K:
            raise ValueError('공통 예측 기간을 벗어났습니다.')
        values = self.F.item(origin)[self.si[source], :, k]
        return dict(zip(self.F.items, values.tolist()))

    def actual_ingredients(self, d, source):
        values = self.F.act_item[self.si[source], :, self.F.idx(d)]
        return dict(zip(self.F.items, values.tolist()))

    @lru_cache(maxsize=64)
    def committed_receipts(self, origin, delay=0):
        return [dict(source=s, item=r.ingredient_id,
                     arrival=max(origin, r.expected_date.date()+timedelta(days=delay)), qty=float(r.use_qty))
                for s in self.stores for r in data.open_orders(s, origin).itertuples(index=False)]


def source_frames():
    # CSV IO belongs exclusively to app.core.data. Only source-format copies
    # are made here for the common Forecaster and the pure planner.
    names = {1:'stores',2:'menus',3:'ingredients',4:'bom',5:'suppliers',
             6:'ingredient_price_history',7:'calendar',8:'promotions',9:'sales',
             11:'purchase_orders',15:'menu_availability',16:'inventory_lots_daily'}
    frames = {}
    for number, name in names.items():
        frame = data.table(name)
        for col in data.DATE_COLS & set(frame.columns):
            frame[col] = frame[col].dt.strftime('%Y-%m-%d')
        frames[f'{number:02d}_{name}'] = frame
    return frames


@lru_cache(maxsize=1)
def common_data():
    return CommonForecastData(source_frames())


def order_row(line):
    return dict(store_id=line['store'], ingredient_id=line['item'], ingredient_name=line['name'],
                supplier_id=line['supplier'], order_date=line['order_date'], arrival_date=line['arrival'],
                order_qty=line['units'], order_unit=line['order_unit'], use_qty=line['qty'],
                use_unit=line['use_unit'], safety_qty=line.get('safety_qty', 0), amount=round(line['cost']),
                status=line['status'], minimum_amount=line.get('minimum_amount', 0),
                order_total=line.get('order_total', 0),
                basis=f"입고 후 부족분과 안전재고를 반영한 순필요량 {line['needed_qty']:.1f}{line['use_unit']} → 포장 올림 {line['units']}{line['order_unit']}")


def compute(sc: Scenario) -> HubResponse:
    source = common_data()
    submitted = {**SETTINGS, 'as_of': str(sc.as_of),
        'service_target': sc.service_level or .95, 'delay_days': sc.delay_days,
        'demand_multiplier': sc.demand_multiplier, 'evaluation_days':sc.horizon_days}
    try:
        cfg = clean_config(source, submitted)
        planner = Planner(source, cfg)
        result = planner.solve()
    except (ValueError, KeyError, TypeError) as e:
        raise AppError('invalid_hub_input', str(e), 422) from e
    chosen = result['recommended'] or result['diagnostic']
    groups, stores, hubs, transfers, shortages = [], [], [], [], []
    for group in result['selected_details']:
        groups.append(HubGroup(hub_id=group['hub'], members=group['members'], alpha=group['alpha'],
            capacity_ok=group['capacity_ok'], fleet_ok=group['fleet_ok'], peak_liters=group['peak_liters'],
            outside_30_minutes=group['outside_30_minutes'], basis='30분 도달·입고 직후 최대 보관량·일일 차량 여력을 검사한 그룹'))
        stores.extend(HubOrder(**order_row(line)) for line in group['store_orders'])
        hubs.extend(HubOrder(**order_row(line)) for line in group['hub_orders'])
        for row in group['forecast_scenario']['transfers']:
            transfers.append(HubTransfer(date=row['date'], hub_id=row['hub'], store_id=row['store'],
                ingredient_id=row['item'], ingredient_name=source.ingredients[row['item']]['name'],
                qty=row['qty'], use_unit=row['use_unit'], response_minutes=row['response_minutes'],
                last_use_date=min(l['last_use_date'] for l in row['lots']),
                basis='공통 예측 부족분에 허브 재고를 FEFO로 배분. 기존 소비기한을 유지하는 일 단위 공급 초안'))
        for row in group['forecast_scenario']['shortages']:
            shortages.append(Shortage(date=row['date'], store_id=row['store'], ingredient_id=row['item'],
                ingredient_name=source.ingredients[row['item']]['name'], qty=row['qty'], use_unit=row['use_unit'],
                status=row['status'], basis='정기입고와 허브 공급 후 남은 부족. 오늘 판매손실은 다음날 입고로 회복하지 않음'))
    emergency = []
    for row in result['emergency_drafts']:
        item = source.ingredients[row['item']]
        emergency.append(EmergencyOrder(store_id=row['store'], ingredient_id=row['item'], ingredient_name=row['name'],
            supplier_id=item['supplier'], order_date=sc.as_of, arrival_date=row['arrival'], order_qty=row['units'],
            order_unit=row['order_unit'], use_qty=row['qty'], use_unit=item['unit'], amount=round(row['cost']),
            status=row['status'], basis='다음날 이후 미해결 부족만 포장 올림. 소비기한·보관량 확인이 필요한 외부 긴급발주 초안'))
    warnings = ['일 단위 공급 시나리오입니다. 동시 배차 대기시간과 분 단위 품절 방지를 보장하지 않습니다.',
        '외부 긴급발주는 초안이며 재시뮬레이션 전 부족량입니다. 현재 충족률에 긴급발주 효과를 합산하지 않습니다.']
    if any(x.status == 'MIN_AMOUNT_REVIEW' for x in stores+hubs):
        warnings.append('최소 발주금액 미달 주문은 입고로 간주하지 않았습니다. 합배송·발주 조정 검토가 필요합니다.')
    if cfg['store_count'] > 3:
        warnings.append('4번째 이후 매장은 제공 3개 매장 프로필의 복제 시나리오입니다.')
    return HubResponse(status=result['recommendation_status'], forecast_basis='공통 EWMA×요일×공휴일×행사 순수요. 무허브·허브 대안에서 같은 예측과 잔차 기반 안전재고를 사용',
        conditions={k:cfg[k] for k in SETTINGS},
        recommended_hub_count=result['recommended']['hub_count'] if result['recommended'] else None,
        evaluation_start=sc.as_of, evaluation_end_exclusive=result['horizon']['end_exclusive'],
        service_target=cfg['service_target'], fill_rate=chosen['fill_rate'], groups=groups,
        alternatives=[Alternative(**{k:(round(r[k]) if k in ('economic_cost','logistics_cost','waste_cost') else r[k]) for k in ('hub_count','feasible','economic_cost','fill_rate','logistics_cost','waste_cost')},
            basis='동일한 과거 잔차 경로와 예측, 무허브 포함 비교. 식자재 원가 가중 충족률 기준') for r in result['alternatives']],
        store_orders=stores, hub_orders=hubs, transfers=transfers, emergency_orders=emergency, shortages=shortages,
        search_method=result['search_method'], warnings=warnings,
        assumptions=[a for a in result['assumptions'] if '7월' not in a and '취소율' not in a]+[
            '공통 EWMA 예측을 사용하며 대안별 안전재고 원기준을 고정하고 매장 간 직접 이동은 허용하지 않습니다.',
            '정기발주는 공급사 요일·포장·최소금액을 검사합니다. 최소금액 미달은 자동 채움 없이 검토 대상으로 남깁니다.',
            'Scenario.horizon 범위 안에서 품목별 다음 보충 입고 경계까지만 동일 기간으로 비교합니다. 이후 발주는 아직 모델링하지 않습니다.'])
