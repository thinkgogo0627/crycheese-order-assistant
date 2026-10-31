"""Pure daily FEFO hub planning helpers. Source frames are supplied by core.data.

No UI, HTTP server, CSV reads or order execution live in this feature.
"""
from __future__ import annotations

import csv
import hashlib
import io
import itertools
import json
import math
import statistics
from collections import defaultdict
from datetime import date, timedelta
from functools import lru_cache

VERSION = '2.0.0'
ZONES = ('chilled', 'frozen', 'ambient')
ZONE = {'냉장': 'chilled', '냉동': 'frozen', '상온': 'ambient'}
DAYS = {'월': 0, '화': 1, '수': 2, '목': 3, '금': 4, '토': 5, '일': 6}
EPS = 1e-8


def day(value):
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def dates(start, stop):
    while start < stop:
        yield start
        start += timedelta(days=1)


def quantile(values, p):
    """Conservative empirical nearest-rank quantile, no normality assumption."""
    values = sorted(values)
    if not values:
        return 0.0
    return values[max(0, min(len(values) - 1, math.ceil(p * len(values)) - 1))]


def mean(values):
    return statistics.fmean(values) if values else 0.0


def pack_round(qty, pack, minimum=1):
    if qty <= EPS:
        return 0
    return max(minimum, math.ceil((qty - EPS) / pack))


def validate_number(value, name, low, high):
    if isinstance(value, bool):
        raise ValueError(f'{name}: 숫자를 입력하세요.')
    value = float(value)
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{name}: {low}~{high} 범위가 필요합니다.')
    return value


def add_lot(lots, qty, expiry):
    if qty > EPS:
        lots.append([float(qty), expiry])


def expire(lots, today):
    waste = sum(q for q, expiry in lots if expiry < today)
    lots[:] = [[q, expiry] for q, expiry in lots if expiry >= today and q > EPS]
    return waste


def stock(lots):
    return sum(q for q, _ in lots)


def take(lots, qty):
    """Return transferred pieces (quantity, ORIGINAL expiry), preserving FEFO."""
    pieces = []
    for lot in sorted(lots, key=lambda x: x[1]):
        used = min(qty, lot[0])
        if used > EPS:
            lot[0] -= used
            qty -= used
            pieces.append([used, lot[1]])
        if qty <= EPS:
            break
    lots[:] = [x for x in lots if x[0] > EPS]
    return pieces, max(0.0, qty)


def take_whole_packs(lots, qty, pack):
    """Do not combine opened fractions from different lots into a new pack."""
    pieces=[]
    qty=math.floor((qty+EPS)/pack)*pack
    for lot in sorted(lots,key=lambda x:x[1]):
        used=min(qty,math.floor((lot[0]+EPS)/pack)*pack)
        if used>EPS:
            lot[0]-=used;qty-=used;pieces.append([used,lot[1]])
        if qty<=EPS:
            break
    lots[:]=[x for x in lots if x[0]>EPS]
    return pieces,max(0.0,qty)


def supplier_window(supplier, origin, delay=0):
    """Decision at 06:00 KST, before cutoff. Column calendars take precedence."""
    def order_after(d, strict=False):
        d += timedelta(days=int(strict))
        for _ in range(15):
            if d.weekday() in supplier['order_days']:
                return d
            d += timedelta(days=1)
        raise ValueError('발주 가능일을 찾을 수 없습니다.')

    def arrival(order):
        d = order + timedelta(days=supplier['lead'] + delay)
        for _ in range(15):
            if d.weekday() in supplier['delivery_days']:
                return d
            d += timedelta(days=1)
        raise ValueError('입고 가능일을 찾을 수 없습니다.')

    order = order_after(origin)
    return order, arrival(order), arrival(order_after(order, True))


class Dataset:
    """In-memory source panel. File access is owned by app.core.data."""
    def __init__(self, *, frames, select_models=False):
        self.rows, self.hashes = {}, {}
        required = (1, 2, 3, 4, 5, 6, 9, 11, 15, 16)
        for number in required:
            name = next(k for k in frames if k.startswith(f'{number:02d}_'))
            self._read(number, name+'.csv', frames[name].to_csv(index=False).encode('utf-8'))
        self.stores = {r['store_id']: r for r in self.rows[1]}
        self.menus = {r['menu_id']: r for r in self.rows[2]}
        self.menu_ids = sorted(self.menus)
        self.ingredients = {}
        for r in self.rows[3]:
            self.ingredients[r['ingredient_id']] = dict(
                id=r['ingredient_id'], name=r['ingredient_name'], supplier=r['supplier_id'],
                unit=r['use_unit'], pack=float(r['use_qty_per_order_unit']),
                order_unit=r['order_unit'], minimum=int(r['min_order_qty']),
                zone=ZONE[r['storage']], shelf=int(r['shelf_life_days']))
        self.bom = defaultdict(list)
        for r in self.rows[4]:
            self.bom[r['menu_id']].append((r['ingredient_id'], float(r['qty_per_menu'])))
        self.suppliers = {}
        for r in self.rows[5]:
            self.suppliers[r['supplier_id']] = dict(
                id=r['supplier_id'], order_days={DAYS[x] for x in r['order_days'].split(',')},
                delivery_days={DAYS[x] for x in r['delivery_days'].split(',')},
                lead=int(r['lead_time_days']), cutoff=r['order_cutoff'],
                minimum=float(r['min_order_amount']))
        self.prices = defaultdict(list)
        for r in self.rows[6]:
            self.prices[r['ingredient_id']].append((day(r['valid_from']), float(r['unit_price'])))
        for rows in self.prices.values():
            rows.sort()
        self.availability = defaultdict(list)
        for r in self.rows[15]:
            if r['status'] == '취급':
                self.availability[r['store_id'], r['menu_id']].append((day(r['start_date']), day(r['end_date'])))
        self.demand = defaultdict(float)
        self.cancels = defaultdict(float)
        self.hour_demand = defaultdict(float)
        seen = set()
        for r in self.rows[9]:
            key = (r['date'], r['hour'], r['store_id'], r['menu_id'], r['channel'])
            if key in seen:
                raise ValueError('판매 데이터에 중복 키가 있습니다.')
            seen.add(key)
            d, s, m = day(r['date']), r['store_id'], r['menu_id']
            demand, qty, lost, cancel = (float(r[x]) for x in ('demand_qty', 'qty', 'lost_qty', 'cancel_qty'))
            if abs(demand - lost - qty) > EPS or not 0 <= cancel <= qty:
                raise ValueError('판매 데이터 수량 관계가 맞지 않습니다.')
            self.demand[d, s, m] += demand
            self.cancels[d, s, m] += cancel
            self.hour_demand[d, s, int(r['hour'])] += max(0, demand - cancel)
        all_dates = [k[0] for k in self.demand]
        self.start, self.end = min(all_dates), max(all_dates)
        self.lots = defaultdict(list)
        for r in self.rows[16]:
            self.lots[day(r['date']), r['store_id'], r['ingredient_id']].append(
                [float(r['remaining_qty']), day(r['last_use_date'])])
        self.purchase_orders = []
        for r in self.rows[11]:
            if r['order_type'] not in ('정기', '긴급'):
                raise ValueError('지원하지 않는 발주 유형입니다.')
            self.purchase_orders.append(dict(
                source=r['store_id'], item=r['ingredient_id'], order=day(r['order_date']),
                arrival=day(r['expected_date']), units=float(r['order_qty']), kind=r['order_type']))
        self.selection, self.selection_scores = self._select() if select_models else ({}, {})
        # Free row-level sales after aggregation; no raw-data HTTP endpoint exists.
        del self.rows[9]

    def committed_receipts(self, origin, delay=0):
        return [dict(source=p['source'], item=p['item'], arrival=max(origin, p['arrival']+timedelta(days=delay)),
                     qty=p['units']*self.ingredients[p['item']]['pack'])
                for p in self.purchase_orders if p['order'] < origin <= p['arrival']]

    def _read(self, number, name, content):
        self.hashes[name] = hashlib.sha256(content).hexdigest()
        self.rows[number] = list(csv.DictReader(io.StringIO(content.decode('utf-8-sig'))))

    def offered(self, d, source, menu):
        d = min(d, self.end)
        return any(a <= d <= b for a, b in self.availability[source, menu])

    @lru_cache(maxsize=100000)
    def menu_forecast(self, origin, target, source, model):
        hist = list(dates(max(self.start, origin - timedelta(days=28)), origin))
        values = {}
        for m in self.menu_ids:
            active = [d for d in hist if self.offered(d, source, m)]
            last7 = [d for d in active if d >= origin - timedelta(days=7)]
            same = [d for d in active if d.weekday() == target.weekday()]
            m7 = mean([self.demand[d, source, m] for d in last7])
            if not last7:
                category = self.menus[m]['category']
                peers = []
                for other in self.menu_ids:
                    if self.menus[other]['category'] == category:
                        obs = [self.demand[d, source, other] for d in hist if self.offered(d, source, other)]
                        if obs and mean(obs) > 0:
                            peers.append(mean(obs))
                m7 = mean(peers)
            weekday = mean([self.demand[d, source, m] for d in same]) if same else m7
            p = m7 if model == 'mean7' else weekday if model == 'weekday4' else (m7 + weekday) / 2
            values[m] = max(0.0, p) if self.offered(target, source, m) else 0.0
        return values

    def _select(self):
        selection, results = {}, {}
        for s in sorted(self.stores):
            scores = {}
            for model in ('mean7', 'weekday4', 'blend'):
                error, total = 0.0, 0.0
                for origin in dates(date(2026, 7, 1), date(2026, 8, 1)):
                    for h in range(4):
                        target = origin + timedelta(days=h)
                        if target >= date(2026, 8, 1):
                            continue
                        pred = self.menu_forecast(origin, target, s, model)
                        for m in self.menu_ids:
                            if self.offered(target, s, m):
                                actual = self.demand[target, s, m]
                                error += abs(actual - pred[m])
                                total += actual
                scores[model] = 100 * error / total if total else 0
            selection[s] = min(scores, key=scores.get)
            results[s] = scores
        return selection, results

    @lru_cache(maxsize=100000)
    def ingredient_forecast(self, origin, target, source):
        gross = self.menu_forecast(origin, target, source, self.selection[source])
        result = {a: 0.0 for a in self.ingredients}
        hist = list(dates(max(self.start, origin - timedelta(days=28)), origin))
        for m, p in gross.items():
            demand = sum(self.demand[d, source, m] for d in hist)
            cancel = sum(self.cancels[d, source, m] for d in hist)
            net = p * (1 - min(1, cancel / demand)) if demand > 0 else p
            for a, qty in self.bom[m]:
                result[a] += net * qty
        return result

    @lru_cache(maxsize=100000)
    def actual_ingredients(self, d, source):
        result = {a: 0.0 for a in self.ingredients}
        for m in self.menu_ids:
            net = self.demand[d, source, m] - self.cancels[d, source, m]
            for a, qty in self.bom[m]:
                result[a] += net * qty
        return result

    def price(self, a, on):
        valid = [p for d, p in self.prices[a] if d <= on]
        if not valid:
            raise ValueError(f'{a}: {on} 이전 단가가 없습니다.')
        return valid[-1]

    def metadata(self):
        return dict(version=VERSION, source_files=self.hashes,
                    period=[str(self.start), str(self.end)], stores=list(self.stores.values()),
                    ingredients=list(self.ingredients.values()), forecast_models=self.selection,
                    selection_wape=self.selection_scores, real_store_count=len(self.stores),
                    decision_time='06:00 Asia/Seoul', forecast_scope='mean7/weekday4/blend only')


def defaults(data):
    return dict(as_of='2026-09-01', store_count=len(data.stores),
                demand_multiplier=1.0, service_target=.95, scenarios=24,
                alpha_grid=[0.0, .25, .5], max_hubs=2,
                hub_items=['I009', 'I016', 'I017', 'I020'],
                travel_minutes=30, preparation_minutes=10, receiving_minutes=5,
                vehicle_count=1, vehicle_minutes_per_day=360,
                hub_daily_cost=12000, trip_cost=5000,
                holding_daily_rate=.0005, shortage_penalty_multiplier=4,
                capacity_liters={'chilled': 200, 'frozen': 200, 'ambient': 150},
                pack_volume_liters={a: (item['pack'] / 1000 if item['unit'] in ('g', 'ml')
                                        else max(.5, item['pack'] * .05))
                                   for a, item in data.ingredients.items()},
                split_allowed=False, hub_order_mode='regular', delay_days=0, evaluation_days=14,
                capacity_source='assumed_net_spare_capacity',
                matrix={}, hub_stock={}, forecast_overrides={}, baseline_safety_overrides={},
                baseline_order_overrides={})


def clean_config(data, submitted):
    if not isinstance(submitted, dict):
        raise ValueError('JSON 객체가 필요합니다.')
    cfg = defaults(data)
    unknown = set(submitted) - set(cfg)
    if unknown:
        raise ValueError(f'알 수 없는 입력: {sorted(unknown)}')
    cfg.update(submitted)
    cfg['as_of'] = str(day(cfg['as_of']))
    origin = day(cfg['as_of'])
    if not date(2026, 7, 1) <= origin <= data.end+timedelta(days=1):
        raise ValueError('기준일은 2026-07-01~2026-10-01이어야 합니다.')
    if data.selection.get('S01') != 'ewma' and origin < date(2026, 8, 1):
        raise ValueError('7월 선택 평균 모델은 8월 이후에만 사용할 수 있습니다.')
    integer_limits = {'evaluation_days': (1, 14), 'delay_days': (0, 14), 'store_count': (1, 12), 'scenarios': (8, 40), 'max_hubs': (0, 3),
                      'vehicle_count': (1, 10), 'vehicle_minutes_per_day': (30, 1440)}
    for name, bounds in integer_limits.items():
        value = validate_number(cfg[name], name, *bounds)
        if value != int(value):
            raise ValueError(f'{name}: 정수가 필요합니다.')
        cfg[name] = int(value)
    for name, bounds in {
        'demand_multiplier': (0, 5), 'service_target': (0, 1), 'travel_minutes': (0, 30),
        'preparation_minutes': (0, 120), 'receiving_minutes': (0, 120),
        'hub_daily_cost': (0, 1000000), 'trip_cost': (0, 1000000),
        'holding_daily_rate': (0, .1), 'shortage_penalty_multiplier': (0, 100),
    }.items():
        cfg[name] = validate_number(cfg[name], name, *bounds)
    if not isinstance(cfg['split_allowed'], bool):
        raise ValueError('split_allowed는 true/false여야 합니다.')
    if cfg['hub_order_mode'] not in ('regular', 'emergency'):
        raise ValueError('hub_order_mode은 regular 또는 emergency입니다.')
    if not isinstance(cfg['alpha_grid'], list) or not 1 <= len(cfg['alpha_grid']) <= 5:
        raise ValueError('alpha_grid는 1~5개 감축률 배열입니다.')
    cfg['alpha_grid'] = sorted(set(validate_number(a, 'alpha', 0, .75) for a in cfg['alpha_grid']))
    if not isinstance(cfg['hub_items'], list) or set(cfg['hub_items']) - set(data.ingredients):
        raise ValueError('hub_items에 유효한 식자재 ID 배열이 필요합니다.')
    cfg['hub_items'] = sorted(set(cfg['hub_items']))
    for z in ZONES:
        cfg['capacity_liters'][z] = validate_number(cfg['capacity_liters'][z], z, 0, 100000)
    for a in data.ingredients:
        cfg['pack_volume_liters'][a] = validate_number(cfg['pack_volume_liters'][a], a + ' 포장부피', .001, 10000)
    if not isinstance(cfg['matrix'], dict) or not isinstance(cfg['hub_stock'], dict):
        raise ValueError('matrix와 hub_stock은 객체여야 합니다.')
    if any(not isinstance(cfg[f],dict) for f in ('forecast_overrides','baseline_safety_overrides','baseline_order_overrides')):
        raise ValueError('팀 예측·안전재고 입력은 객체여야 합니다.')
    for h, routes in cfg['matrix'].items():
        if not isinstance(routes, dict):
            raise ValueError('matrix[허브ID]는 매장별 분 단위 객체입니다.')
        for s, value in routes.items():
            validate_number(value, f'{h}/{s}', 0, 300)
    for h, items in cfg['hub_stock'].items():
        if not isinstance(items, dict):
            raise ValueError('hub_stock[허브ID]는 식자재별 로트 배열 객체입니다.')
        for a, lots in items.items():
            if a not in data.ingredients or not isinstance(lots, list):
                raise ValueError('허브 재고는 유효한 식자재별 로트 배열이어야 합니다.')
            for lot in lots:
                validate_number(lot['qty'], '허브 로트 수량', 0, 1e10)
                day(lot['last_use_date'])
    return cfg


class Planner:
    def __init__(self, data, cfg):
        self.data, self.cfg, self.origin = data, cfg, day(cfg['as_of'])
        sources = sorted(data.stores)
        self.stores = []
        for i in range(cfg['store_count']):
            source = sources[i % len(sources)]
            self.stores.append(dict(id=source if i < len(sources) else f'V{i+1:02d}',
                                    source=source, synthetic=i >= len(sources)))
        self.ids = [s['id'] for s in self.stores]
        self.hubs = [f'H{i+1:02d}' for i in range(min(cfg['max_hubs'], len(self.stores)))]
        valid_hubs={'H01','H02','H03'}
        for hub,routes in cfg['matrix'].items():
            if hub not in valid_hubs or set(routes)-set(self.ids):
                raise ValueError('matrix에 유효한 허브 H01~H03 / 현재 매장 ID를 사용하세요.')
        if set(cfg['hub_stock'])-valid_hubs:
            raise ValueError('hub_stock 허브 ID는 H01~H03입니다.')
        for field in ('forecast_overrides','baseline_safety_overrides','baseline_order_overrides'):
            if set(cfg[field])-set(self.ids):
                raise ValueError(f'{field}: 현재 매장 ID를 사용하세요.')
            for sid,items in cfg[field].items():
                if not isinstance(items,dict) or set(items)-set(data.ingredients):
                    raise ValueError(f'{field}: 매장별 유효한 식자재 ID 객체가 필요합니다.')
                if field=='forecast_overrides' and any(not isinstance(x,dict) for x in items.values()):
                    raise ValueError('forecast_overrides: 식자재별 날짜/수량 객체가 필요합니다.')
        self.items = list(data.ingredients)
        self.windows = {a: supplier_window(data.suppliers[item['supplier']], self.origin, cfg['delay_days'])
                        for a, item in data.ingredients.items()}
        # Same next-day emergency exception as source specification; no regular MOQ amount/calendar applied.
        self.hub_windows = {a: ((self.origin, self.origin + timedelta(days=1+cfg['delay_days']),
                                self.origin + timedelta(days=2+cfg['delay_days']))
                               if cfg['hub_order_mode'] == 'emergency' else self.windows[a]) for a in self.items}
        # Never penalize a policy for not modelling a replenishment decision that
        # occurs AFTER this one-cycle comparison. Bound each SKU identically for
        # direct/hub alternatives, even when their supplier calendars differ.
        self.evaluation_end={a:min(self.windows[a][2],self.hub_windows[a][2])
                             if a in cfg['hub_items'] else self.windows[a][2] for a in self.items}
        requested_end = self.origin + timedelta(days=cfg['evaluation_days'])
        self.evaluation_end = {a:min(end, requested_end) for a,end in self.evaluation_end.items()}
        for sid,items in cfg['baseline_order_overrides'].items():
            for a,line in items.items():
                if not isinstance(line,dict) or line.get('basis')!='NET_NEED_INCLUDES_SAFETY':
                    raise ValueError('외부 발주는 basis=NET_NEED_INCLUDES_SAFETY와 포장 전 순필요량이 필요합니다.')
                validate_number(line['net_need_before_pack_qty'],'외부 순발주 필요량',0,1e10)
                validate_number(line['safety_qty'],'외부 안전재고',0,1e10)
                if day(line['horizon_end_exclusive'])!=self.windows[a][2]:
                    raise ValueError(f'{sid}/{a}: 외부 발주 기간이 서비스의 다음 입고 경계와 다릅니다.')
        self.stop = max(self.evaluation_end.values())
        self.days = list(dates(self.origin, self.stop))
        self.length = len(self.days)
        available = list(dates(max(data.start + timedelta(days=28), self.origin - timedelta(days=90)),
                               self.origin - timedelta(days=self.length - 1)))
        if len(available) < 8:
            raise ValueError('과거 오차 재현에 필요한 이력이 부족합니다.')
        # Select evenly spaced, ALIGNED historical blocks; never shuffle store errors independently.
        count = min(cfg['scenarios'], len(available))
        self.origins = [available[round(i*(len(available)-1)/(count-1))] for i in range(count)]
        self.forecasts, self.scenario_demand, self.initial, self.firm = {}, {}, {}, {}
        self.prices = {a: data.price(a, self.origin) for a in self.items}
        self.cost_per_unit = {a: self.prices[a] / data.ingredients[a]['pack'] for a in self.items}
        self.vol_per_unit = {a: cfg['pack_volume_liters'][a] / data.ingredients[a]['pack'] for a in self.items}
        self.raw_safety = {}
        self._load()
        self.store_plan_cache, self.group_cache = {}, {}

    def route(self, hub, store):
        return float(self.cfg['matrix'].get(hub, {}).get(store, self.cfg['travel_minutes']))

    def _load(self):
        for s in self.stores:
            sid, source = s['id'], s['source']
            scale = self.cfg['demand_multiplier']
            for a, item in self.data.ingredients.items():
                forecasts = []
                override = self.cfg['forecast_overrides'].get(sid, {}).get(a)
                for d in self.days:
                    p = self.data.ingredient_forecast(self.origin, d, source)[a] * scale
                    if override is not None:
                        if str(d) not in override:
                            raise ValueError(f'forecast_overrides {sid}/{a}: {d} 예측이 누락되었습니다.')
                        p = validate_number(override[str(d)], '외부 식자재 예측', 0, 1e10)
                    forecasts.append(p)
                self.forecasts[sid, a] = forecasts
                self.initial[sid, a] = [x[:] for x in self.data.lots[self.origin-timedelta(days=1), source, a]]
                receipts = defaultdict(float)
                for po in self.data.committed_receipts(self.origin, self.cfg['delay_days']):
                    if po['source'] == source and po['item'] == a and po['arrival'] < self.evaluation_end[a]:
                        receipts[po['arrival']] += po['qty']
                self.firm[sid, a] = dict(receipts)
                scenarios, errors = [], []
                _, arrival, stop = self.windows[a]
                for old in self.origins:
                    values, residuals = [], []
                    for j, d in enumerate(self.days):
                        old_target = old + timedelta(days=j)
                        old_prediction = self.data.ingredient_forecast(old, old_target, source)[a]
                        actual = self.data.actual_ingredients(old_target, source)[a]
                        # Additive residual, preserving zero/cold-start behavior and cross-store signs.
                        residual = (actual - old_prediction) * scale
                        values.append(max(0.0, forecasts[j] + residual))
                        if arrival <= d < stop:
                            residuals.append(residual)
                    scenarios.append(values)
                    errors.append(sum(residuals))
                self.scenario_demand[sid, a] = scenarios
                safety = max(0.0, quantile(errors, self.cfg['service_target']))
                if a in self.cfg['baseline_safety_overrides'].get(sid, {}):
                    safety = validate_number(self.cfg['baseline_safety_overrides'][sid][a], '외部 안전재고', 0, 1e10)
                external=self.cfg['baseline_order_overrides'].get(sid,{}).get(a)
                if external is not None:
                    safety=float(external['safety_qty'])
                self.raw_safety[sid, a] = safety

    def local_cover(self, sid, a, hub=None):
        source = next(s['source'] for s in self.stores if s['id'] == sid)
        hist = list(dates(self.origin-timedelta(days=28), self.origin))
        shares = defaultdict(float)
        for d in hist:
            for hour in range(24):
                shares[hour] += self.data.hour_demand[d, source, hour]
        total = sum(shares.values())
        row = self.data.stores[source]
        uniform = 1 / max(1, int(row['close_hour'])-int(row['open_hour'])+1)
        peak = max(shares.values(), default=0) / total if total else uniform
        travel = self.route(hub, sid) if hub else self.cfg['travel_minutes']
        response = travel + self.cfg['preparation_minutes'] + self.cfg['receiving_minutes']
        return max(self.forecasts[sid, a], default=0) * min(1, peak * response / 60)

    def make_store_plan(self, sid, alpha, enabled, hub=None):
        key = sid, alpha, enabled, hub
        if key in self.store_plan_cache:
            return self.store_plan_cache[key]
        lines = []
        for a, item in self.data.ingredients.items():
            use_hub = enabled and a in self.cfg['hub_items']
            safety = self.raw_safety[sid, a]
            if use_hub:
                safety = max(safety * (1-alpha), self.local_cover(sid, a, hub))
            order, arrival, end = self.windows[a]
            lots = [x[:] for x in self.initial[sid, a]]
            # Net, time-phased FEFO requirements. Pre-arrival lost demand is never reordered.
            shortage_after, last_stock = 0.0, 0.0
            for j, d in enumerate(self.days):
                if d >= end:
                    break
                expire(lots, d)
                add_lot(lots, self.firm[sid, a].get(d, 0), d+timedelta(days=item['shelf']-1))
                _, unmet = take(lots, self.forecasts[sid, a][j])
                if d >= arrival:
                    shortage_after += unmet
                expire(lots, d+timedelta(days=1))
                last_stock = stock(lots)
            # Later arrivals cannot cancel an earlier stockout. First cover every
            # post-arrival deficit, then fill any remaining terminal reserve gap.
            needed = shortage_after + max(0.0, safety - last_stock)
            basis='BUILT_IN_FEFO_NET_NEED'
            external=self.cfg['baseline_order_overrides'].get(sid,{}).get(a)
            if external is not None:
                # Already net of stock/receipts. Replace only the safety component;
                # never net the same existing stock or receipts a second time.
                needed=max(0,float(external['net_need_before_pack_qty'])
                           -float(external['safety_qty'])+safety)
                basis='TEAM_NET_NEED_INCLUDES_SAFETY'
            units = pack_round(needed, item['pack'], item['minimum'])
            line = dict(store=sid, item=a, name=item['name'], use_unit=item['unit'],
                        order_unit=item['order_unit'], order_date=str(order), arrival=str(arrival),
                        end=str(end), needed_qty=needed, safety_qty=safety,
                        units=units, qty=units*item['pack'], cost=units*self.prices[a],
                        supplier=item['supplier'], basis=basis,status='DRAFT' if units else 'NOT_NEEDED')
            lines.append(line)
        self.minimum_check(lines, emergency=False)
        self.store_plan_cache[key] = lines
        return lines

    def minimum_check(self, lines, emergency):
        groups = defaultdict(list)
        for line in lines:
            if line['units']:
                groups[line['supplier'], line['order_date']].append(line)
        for (supplier, _), group in groups.items():
            amount = sum(x['cost'] for x in group)
            minimum = 0 if emergency else self.data.suppliers[supplier]['minimum']
            if amount + EPS < minimum:
                for line in group:
                    line['status'] = 'MIN_AMOUNT_REVIEW'
                    line['minimum_amount'] = minimum
                    line['order_total'] = amount

    @staticmethod
    def confirmed_qty(line, d):
        return line['qty'] if line['status'] == 'DRAFT' and line['arrival'] == str(d) else 0.0

    def store_path(self, sid, plans, sample, shadow=False):
        """Unconstrained hub requests, with no fictitious rescue before first hub receipt."""
        requests = {}
        for line in plans:
            a, item = line['item'], self.data.ingredients[line['item']]
            lots = [x[:] for x in self.initial[sid, a]]
            values = self.forecasts[sid, a] if sample is None else self.scenario_demand[sid, a][sample]
            needs = []
            hub_arrival, hub_end = self.hub_windows[a][1:]
            for j, d in enumerate(self.days):
                if d>=self.evaluation_end[a]:
                    needs.append(0.0)
                    continue
                expire(lots, d)
                add_lot(lots, self.firm[sid, a].get(d, 0), d+timedelta(days=item['shelf']-1))
                add_lot(lots, self.confirmed_qty(line, d), d+timedelta(days=item['shelf']-1))
                request = 0.0
                if a in self.cfg['hub_items'] and d < hub_end:
                    request = max(0.0, values[j] + line['safety_qty'] - stock(lots))
                    if not self.cfg['split_allowed']:
                        request = pack_round(request, item['pack']) * item['pack']
                    if shadow and d >= hub_arrival:
                        add_lot(lots, request, d+timedelta(days=item['shelf']-1))
                needs.append(request)
                take(lots, values[j])
                expire(lots, d+timedelta(days=1))
            requests[a] = needs
        return requests

    def evaluate(self, members, hub=None, alpha=0, details=False):
        key = tuple(members), hub, alpha
        if key in self.group_cache and not details:
            return self.group_cache[key]
        enabled = hub is not None
        reachability = []
        if enabled:
            reachability = [self.ids[i] for i in members if self.route(hub, self.ids[i]) > 30]
        plans = {self.ids[i]: self.make_store_plan(self.ids[i], alpha, enabled, hub) for i in members}
        hub_lines, target_rows = [], []
        if enabled:
            paths = [[self.store_path(sid, p, r, True) for sid, p in plans.items()]
                     for r in range(len(self.origins))]
            for a in self.cfg['hub_items']:
                item = self.data.ingredients[a]
                order, arrival, end = self.hub_windows[a]
                totals = [sum(sum(q for d,q in zip(self.days,path[a]) if arrival <= d < end)
                              for path in sample_paths) for sample_paths in paths]
                target = quantile(totals, self.cfg['service_target'])
                existing = sum(float(x['qty']) for x in self.cfg['hub_stock'].get(hub, {}).get(a, [])
                               if day(x['last_use_date']) >= arrival)
                # Reserve initial stock for requests BEFORE the new receipt too.
                # This bound is deliberately conservative when pre-arrival lots
                # have different expiry dates; finite replay reports the outcome.
                net_samples=[]
                for total,sample_paths in zip(totals,paths):
                    earlier=sum(sum(q for d,q in zip(self.days,path[a]) if d < arrival)
                                for path in sample_paths)
                    remaining=max(0,existing-earlier)
                    net_samples.append(max(0,total-remaining))
                needed = quantile(net_samples, self.cfg['service_target'])
                units = pack_round(needed, item['pack'], item['minimum'])
                line = dict(store=hub, item=a, name=item['name'], supplier=item['supplier'],
                            order_date=str(order), arrival=str(arrival), end=str(end),
                            target_qty=target, needed_qty=needed, existing_usable_qty=existing,
                            units=units, qty=units*item['pack'], cost=units*self.prices[a],
                            use_unit=item['unit'], order_unit=item['order_unit'],
                            status='DRAFT' if units else 'NOT_NEEDED')
                hub_lines.append(line)
                target_rows.append(dict(item=a, target_qty=target, p50=quantile(totals,.5),
                                        p95=quantile(totals,.95), samples=len(totals)))
            self.minimum_check(hub_lines, self.cfg['hub_order_mode'] == 'emergency')
        results = [self.simulate(members, plans, hub, hub_lines, r, details=False)
                   for r in range(len(self.origins))]
        total_demand = sum(x['demand_value'] for x in results)
        total_unmet = sum(x['unmet_value'] for x in results)
        fill = 1 - total_unmet/total_demand if total_demand else 1.0
        cap_peak = {z:max((r['hub_peak_liters'][z] for r in results),default=0) for z in ZONES}
        capacity_ok = all(cap_peak[z] <= self.cfg['capacity_liters'][z]+EPS for z in ZONES)
        fleet_ok = all(not r['fleet_overflow'] for r in results)
        per_store_fill = {}
        for sid in plans:
            demand = sum(r['store_demand_value'][sid] for r in results)
            unmet = sum(r['store_unmet_value'][sid] for r in results)
            per_store_fill[sid] = 1-unmet/demand if demand else 1.0
        order_review = any(x['status']=='MIN_AMOUNT_REVIEW' for x in hub_lines)
        structural = not reachability and capacity_ok and fleet_ok and not order_review
        service_ok = fill+EPS >= self.cfg['service_target'] and all(
            x+EPS >= self.cfg['service_target'] for x in per_store_fill.values())
        result = dict(hub=hub, members=list(plans), alpha=alpha, hub_count=int(enabled),
                      structural_feasible=structural, service_feasible=service_ok,
                      feasible=structural and service_ok,
                      economic_cost=mean([r['economic_cost'] for r in results]),
                      purchase_cost=sum(x['cost'] for p in plans.values() for x in p if x['status']=='DRAFT')
                                    +sum(x['cost'] for x in hub_lines if x['status']=='DRAFT'),
                      logistics_cost=mean([r['logistics_cost'] for r in results]),
                      waste_cost=mean([r['waste_cost'] for r in results]),
                      end_inventory_value=mean([r['end_value'] for r in results]),
                      unmet_value=mean([r['unmet_value'] for r in results]),
                      demand_value=mean([r['demand_value'] for r in results]),
                      fill_rate=fill, per_store_fill=per_store_fill,
                      peak_liters=cap_peak, capacity_ok=capacity_ok, fleet_ok=fleet_ok,
                      order_review=order_review, outside_30_minutes=reachability,
                      peak_daily_trips=max((r['max_trips'] for r in results),default=0),
                      store_order_review_count=sum(x['status']=='MIN_AMOUNT_REVIEW' for p in plans.values() for x in p))
        self.group_cache[key] = result
        if details:
            result = dict(result, store_orders=[x for p in plans.values() for x in p],
                          hub_orders=hub_lines, targets=target_rows,
                          forecast_scenario=self.simulate(members, plans, hub, hub_lines, None, True))
        return result

    def simulate(self, members, plans, hub, hub_lines, sample, details=False):
        cfg, enabled = self.cfg, hub is not None
        retail = {(sid,a):[x[:] for x in self.initial[sid,a]] for sid in plans for a in self.items}
        hub_lots = {a:[] for a in self.items}
        if enabled:
            for a, lots in cfg['hub_stock'].get(hub,{}).items():
                hub_lots[a] = [[float(x['qty']),day(x['last_use_date'])] for x in lots]
        purchase = sum(x['cost'] for p in plans.values() for x in p if x['status']=='DRAFT')
        purchase += sum(x['cost'] for x in hub_lines if x['status']=='DRAFT')
        opening = sum(stock(lots)*self.cost_per_unit[a] for (sid,a),lots in retail.items())
        opening += sum(stock(lots)*self.cost_per_unit[a] for a,lots in hub_lots.items())
        known_inbound = sum(sum(self.firm[sid,a].values())*self.cost_per_unit[a] for sid in plans for a in self.items)
        unmet_value = demand_value = waste = holding = logistics = 0.0
        per_demand, per_unmet = defaultdict(float), defaultdict(float)
        peak = {z:0.0 for z in ZONES}
        overflow, max_trips = False, 0
        transfers, shortages, capacity_trace = [], [], []
        prearrival = defaultdict(float)
        cover_risk = []
        for j,d in enumerate(self.days):
            hub_usage = {z:0.0 for z in ZONES}
            for a,item in self.data.ingredients.items():
                if d<self.evaluation_end[a]:
                    waste += expire(hub_lots[a],d)*self.cost_per_unit[a]
            for line in hub_lines:
                a,item=line['item'],self.data.ingredients[line['item']]
                if d<self.evaluation_end[a]:
                    add_lot(hub_lots[a],self.confirmed_qty(line,d),d+timedelta(days=item['shelf']-1))
            for a,item in self.data.ingredients.items():
                hub_usage[item['zone']] += stock(hub_lots[a])*self.vol_per_unit[a]
            for z in ZONES:
                peak[z]=max(peak[z],hub_usage[z])
            if details:
                capacity_trace.append(dict(date=str(d),**hub_usage))
            shipments = defaultdict(list)
            daily_needs = {}
            for sid,p in plans.items():
                for line in p:
                    a,item=line['item'],self.data.ingredients[line['item']]
                    if d>=self.evaluation_end[a]:
                        continue
                    lots=retail[sid,a]
                    waste += expire(lots,d)*self.cost_per_unit[a]
                    add_lot(lots,self.firm[sid,a].get(d,0),d+timedelta(days=item['shelf']-1))
                    add_lot(lots,self.confirmed_qty(line,d),d+timedelta(days=item['shelf']-1))
                    need=(self.forecasts[sid,a] if sample is None else self.scenario_demand[sid,a][sample])[j]
                    daily_needs[sid,a]=need
                    if enabled and a in cfg['hub_items']:
                        request=max(0,need+line['safety_qty']-stock(lots))
                        if not cfg['split_allowed']:
                            request=pack_round(request,item['pack'])*item['pack']
                        if request>EPS:
                            shipments[sid].append((a,request))
                        if stock(lots)+EPS < min(need,self.local_cover(sid,a,hub)):
                            cover_risk.append(dict(date=str(d),store=sid,item=a,status='INSUFFICIENT_RESPONSE_COVER'))
            # Conservative one round trip per store/day, all ingredients bundled.
            # This is a throughput constraint, NOT a minute-by-minute dispatch guarantee.
            used_minutes=0.0
            vehicle_load=[0.0]*cfg['vehicle_count']
            day_trips=0
            for sid in sorted(shipments):
                travel=self.route(hub,sid)
                cycle=2*travel+cfg['preparation_minutes']+cfg['receiving_minutes']
                vehicle=min(range(len(vehicle_load)),key=lambda i:vehicle_load[i])
                can_ship=travel<=30 and vehicle_load[vehicle]+cycle<=cfg['vehicle_minutes_per_day']+EPS
                requested_available=any((stock(hub_lots[a]) if cfg['split_allowed'] else
                                         sum(math.floor((q+EPS)/self.data.ingredients[a]['pack']) for q,e in hub_lots[a]))>EPS
                                        for a,_ in shipments[sid])
                if requested_available and not can_ship:
                    overflow=True
                did_ship=False
                for a,qty in shipments[sid]:
                    if not can_ship:
                        continue
                    if not cfg['split_allowed']:
                        pieces,left=take_whole_packs(hub_lots[a],qty,self.data.ingredients[a]['pack'])
                    else:
                        pieces,left=take(hub_lots[a],qty)
                    sent=qty-left
                    if sent>EPS:
                        retail[sid,a].extend(pieces)
                        did_ship=True
                        if details:
                            transfers.append(dict(date=str(d),hub=hub,store=sid,item=a,qty=sent,
                                                  use_unit=self.data.ingredients[a]['unit'],travel_minutes=travel,
                                                  response_minutes=travel+cfg['preparation_minutes']+cfg['receiving_minutes'],
                                                  lots=[dict(qty=q,last_use_date=str(e)) for q,e in pieces]))
                if did_ship:
                    used_minutes+=cycle
                    vehicle_load[vehicle]+=cycle
                    logistics+=cfg['trip_cost']
                    day_trips+=1
            # Count actual store-day trips, not ingredient rows.
            max_trips=max(max_trips,day_trips)
            for (sid,a),need in daily_needs.items():
                _,unmet=take(retail[sid,a],need)
                value=need*self.cost_per_unit[a]
                loss=unmet*self.cost_per_unit[a]
                demand_value+=value; unmet_value+=loss
                per_demand[sid]+=value; per_unmet[sid]+=loss
                if unmet>EPS and details:
                    arrival=self.hub_windows[a][1] if enabled else self.windows[a][1]
                    label='BEFORE_NEW_RECEIPT' if d<arrival else 'UNRESOLVED_DAILY_SHORTAGE'
                    shortages.append(dict(date=str(d),store=sid,item=a,qty=unmet,
                                          use_unit=self.data.ingredients[a]['unit'],status=label))
                if unmet>EPS and d<self.windows[a][1]:
                    prearrival[sid,a]+=unmet
            for (sid,a),lots in retail.items():
                if d>=self.evaluation_end[a]:
                    continue
                waste+=expire(lots,d+timedelta(days=1))*self.cost_per_unit[a]
                holding+=stock(lots)*self.cost_per_unit[a]*cfg['holding_daily_rate']
            for a,lots in hub_lots.items():
                if d>=self.evaluation_end[a]:
                    continue
                waste+=expire(lots,d+timedelta(days=1))*self.cost_per_unit[a]
                holding+=stock(lots)*self.cost_per_unit[a]*cfg['holding_daily_rate']
        end_value=sum(stock(lots)*self.cost_per_unit[a] for (sid,a),lots in retail.items())
        end_value+=sum(stock(lots)*self.cost_per_unit[a] for a,lots in hub_lots.items())
        pending_asset=sum(line['cost'] for p in list(plans.values())+[hub_lines] for line in p
                          if line['status']=='DRAFT' and day(line['arrival'])>=self.evaluation_end[line['item']])
        end_value+=pending_asset
        active_days=max(((self.evaluation_end[a]-self.origin).days for a in cfg['hub_items']),default=0)
        activation=cfg['hub_daily_cost']*active_days if enabled else 0
        # Inventory conservation valuation: expiry loss is already included here, never add waste twice.
        used_resource_cost=opening+known_inbound+purchase-end_value
        economic=used_resource_cost+holding+logistics+activation+unmet_value*cfg['shortage_penalty_multiplier']
        result=dict(economic_cost=economic,purchase_cost=purchase,logistics_cost=logistics,
                    waste_cost=waste,end_value=end_value,unmet_value=unmet_value,demand_value=demand_value,
                    store_demand_value=dict(per_demand),store_unmet_value=dict(per_unmet),
                    hub_peak_liters=peak,fleet_overflow=overflow,max_trips=max_trips,
                    holding_cost=holding,hub_operating_cost=activation,resource_cost=used_resource_cost)
        result['pending_receipt_asset_value']=pending_asset
        if details:
            result.update(transfers=transfers,shortages=shortages,capacity_trace=capacity_trace,
                          response_cover_risks=cover_risk,
                          retail_end=[dict(store=sid,item=a,qty=stock(lots)) for (sid,a),lots in retail.items()],
                          hub_end=[dict(hub=hub,item=a,qty=stock(lots)) for a,lots in hub_lots.items()])
        return result

    def solve(self):
        n=len(self.stores)
        baseline_parts=[self.evaluate([i]) for i in range(n)]
        baseline=self.combine(baseline_parts)
        alternatives={0:baseline}
        search_method='exact_partitions_and_hub_assignment' if n<=6 else 'bounded_greedy_grouping'
        if n<=6:
            def partitions(items):
                if not items:
                    yield []
                    return
                first,*rest=items
                for partition in partitions(rest):
                    yield [[first]]+[g[:] for g in partition]
                    for j in range(len(partition)):
                        yield [([first]+g if k==j else g[:]) for k,g in enumerate(partition)]
            # Every store is either direct-only or in one of the opened hub groups.
            for mask in range(1,1<<n):
                supported=[i for i in range(n) if mask>>i&1]
                direct=[baseline_parts[i] for i in range(n) if not mask>>i&1]
                for groups in partitions(supported):
                    if len(groups)>len(self.hubs):
                        continue
                    for hubs in itertools.permutations(self.hubs,len(groups)):
                        parts=[]
                        for group,hub in zip(groups,hubs):
                            choices=[self.evaluate(sorted(group),hub,a) for a in self.cfg['alpha_grid']]
                            viable=[c for c in choices if c['feasible']]
                            # An infeasible group is never hidden in a 'recommended' network.
                            parts.append(min(viable,key=lambda c:c['economic_cost']) if viable
                                         else min(choices,key=lambda c:(not c['structural_feasible'],-c['fill_rate'],c['economic_cost'])))
                        self.keep(alternatives,self.combine(direct+parts))
        else:
            # Explicit approximation for synthetic expansions; not advertised as a global optimum.
            for k in range(1,len(self.hubs)+1):
                for shift in range(min(n,4)):
                    groups=[[] for _ in range(k)]
                    for j,i in enumerate(sorted(range(n),key=lambda i:-(sum(self.forecasts[self.ids[i],a][0]*self.cost_per_unit[a]
                                                                                            for a in self.items)))):
                        groups[(j+shift)%k].append(i)
                    parts=[]
                    for hub,group in zip(self.hubs,groups):
                        choices=[self.evaluate(sorted(group),hub,a) for a in self.cfg['alpha_grid']]
                        parts.append(min(choices,key=lambda c:(not c['feasible'],not c['structural_feasible'],c['economic_cost'])))
                    self.keep(alternatives,self.combine(parts))
        feasible=[x for x in alternatives.values() if x['feasible']]
        chosen=min(feasible,key=lambda x:x['economic_cost']) if feasible else None
        diagnostic=min(alternatives.values(),key=lambda x:(not x['structural_feasible'],-x['fill_rate'],x['economic_cost']))
        selected=chosen or diagnostic
        detail=[]
        for part in selected['groups']:
            members=[self.ids.index(s) for s in part['members']]
            detail.append(self.evaluate(members,part['hub'],part['alpha'],True))
        emergencies=[]
        emergency_arrival=self.origin+timedelta(days=1+self.cfg['delay_days'])
        future_shortages=defaultdict(float)
        for group in detail:
            for shortage in group['forecast_scenario']['shortages']:
                if day(shortage['date'])>=emergency_arrival:
                    future_shortages[shortage['store'],shortage['item']]+=shortage['qty']
        for (sid,a),qty in future_shortages.items():
            item=self.data.ingredients[a]
            units=pack_round(qty,item['pack'],item['minimum'])
            emergencies.append(dict(store=sid,item=a,name=item['name'],net_future_shortage_qty=qty,
                                    units=units,qty=units*item['pack'],order_unit=item['order_unit'],
                                    cost=units*self.prices[a],arrival=str(emergency_arrival),
                                    status='DRAFT_EXPIRY_AND_CAPACITY_REVIEW',
                                    source_rule='긴급발주는 요일·마감·최소금액 예외 / 다음날 07시',
                                    current_day_shortage_resolved=False))
        forecast=[dict(store=sid,item=a,date=str(d),qty=self.forecasts[sid,a][j],unit=self.data.ingredients[a]['unit'])
                  for sid in self.ids for a in self.items for j,d in enumerate(self.days)]
        return dict(version=VERSION,status='DRAFT_SCENARIO_PLAN',
                    recommendation_status='FEASIBLE_SCENARIO' if chosen else 'NO_FEASIBLE_PLAN',
                    config=self.cfg,source=self.data.metadata(),
                    horizon=dict(start=str(self.origin),end_exclusive=str(self.stop),decision_time='06:00 Asia/Seoul',
                                 item_end_exclusive={a:str(d) for a,d in self.evaluation_end.items()}),
                    stores=self.stores,scenario_count=len(self.origins),
                    calibration_origins=[str(d) for d in self.origins],
                    search_method=search_method,computed_group_scenarios=len(self.group_cache),
                    recommended=chosen,diagnostic=diagnostic,
                    baseline=baseline,alternatives=[alternatives[k] for k in sorted(alternatives)],
                    selected_details=detail,forecasts=forecast,emergency_drafts=emergencies,
                    assumptions=[
                        '합성 판매·발주 데이터이며 실제 매장 성과를 뜻하지 않습니다.',
                        '확정 입고는 기준일 이전 발주만 사용합니다. 당일·미래 발주/기말재고는 의사결정에 사용하지 않습니다.',
                        '예측 모델은 7월에 선택한 평균 후보 3종입니다. HGB 학습·가중치는 포함하지 않습니다.',
                        '메뉴 취급 계획을 사전 인지한다고 가정합니다. 데이터 종료 뒤에는 마지막 취급 상태를 유지합니다.',
                        '취소율은 과거 28일로 보정해 메뉴 잠재수요를 식자재 소요량으로 변환합니다.',
                        '추가 매장은 원래 3매장 프로필·재고의 복제 시나리오이며 실제 추가 데이터가 아닙니다.',
                        '거리 기본값은 허브→각 매장 편도 30분입니다. 실측 위치·교통 데이터가 아닙니다.',
                        '보관 용량은 허브 자체 영업분을 뺀 순여유 공간이며 포장 부피는 사용자가 확인해야 하는 가정입니다.',
                        '일 단위 FEFO 수량 모형입니다. 30분 운송·일일 배송 여력은 검사하지만 동시 배차와 분 단위 품절을 보장하지 않습니다.',
                        '품목별 다음 보충 입고 경계까지만 비교합니다. 다음 발주를 모델링하지 않은 이후 날짜를 품절로 잘못 집계하지 않습니다.',
                        '원가기준 식자재 수요충족률입니다. 메뉴 판매 충족률이나 고객 서비스 수준과 다릅니다.',
                        '과거 잔차의 같은 날짜 블록을 함께 사용합니다. 희귀 수요급증·실제 서비스 수준의 통계적 보장은 아닙니다.',
                        '경제비용은 시작·입고·구매·종료 재고 수지를 반영한 가상 자원비+보유비+배송비+허브비+미충족 페널티입니다.',
                        '출력은 승인 전 추천입니다. 실제 발주·예약·정산은 실행하지 않습니다.'
                    ])

    @staticmethod
    def combine(parts):
        fields=('economic_cost','purchase_cost','logistics_cost','waste_cost','end_inventory_value','unmet_value','demand_value')
        result={f:sum(p[f] for p in parts) for f in fields}
        result.update(hub_count=sum(p['hub_count'] for p in parts),groups=parts,
                      feasible=all(p['feasible'] for p in parts),
                      structural_feasible=all(p['structural_feasible'] for p in parts),
                      service_feasible=all(p['service_feasible'] for p in parts))
        result['fill_rate']=1-result['unmet_value']/result['demand_value'] if result['demand_value'] else 1
        return result

    @staticmethod
    def keep(alternatives, candidate):
        k=candidate['hub_count']
        rank=lambda c:(not c['feasible'],not c['structural_feasible'],-c['fill_rate'] if not c['feasible'] else 0,c['economic_cost'])
        if k not in alternatives or rank(candidate)<rank(alternatives[k]):
            alternatives[k]=candidate


def plan(data, submitted=None):
    return Planner(data,clean_config(data,submitted or {})).solve()
