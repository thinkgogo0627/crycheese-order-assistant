#!/usr/bin/env python3
"""Local, dependency-free food-inventory hub planning service. Python >= 3.10.

Run: python hub_service.py --data /path/to/data.zip
Test: python hub_service.py --self-test
Batch: python hub_service.py --data data.zip --config scenario.json --report result.json

Daily FEFO scenario planning, NOT a live dispatch/ordering system. Source data
stays outside this file. All travel, storage-volume and cost inputs are explicit
scenario assumptions. The forecasting baseline matches train.py's three moving
average candidates; its two HGB candidates are not reimplemented here.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import itertools
import json
import math
import statistics
import sys
import threading
import time
import traceback
import zipfile
from collections import defaultdict
from datetime import date, timedelta
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

VERSION = '1.0.0'
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


def supplier_window(supplier, origin):
    """Decision at 06:00 KST, before cutoff. Column calendars take precedence."""
    def order_after(d, strict=False):
        d += timedelta(days=int(strict))
        for _ in range(15):
            if d.weekday() in supplier['order_days']:
                return d
            d += timedelta(days=1)
        raise ValueError('발주 가능일을 찾을 수 없습니다.')

    def arrival(order):
        d = order + timedelta(days=supplier['lead'])
        for _ in range(15):
            if d.weekday() in supplier['delivery_days']:
                return d
            d += timedelta(days=1)
        raise ValueError('입고 가능일을 찾을 수 없습니다.')

    order = order_after(origin)
    return order, arrival(order), arrival(order_after(order, True))


class Dataset:
    """Read source ZIP directly or a CSV directory; never extract/publish originals."""
    def __init__(self, path):
        path = Path(path).expanduser().resolve()
        self.path = path
        self.rows, self.hashes = {}, {}
        required = (1, 2, 3, 4, 5, 6, 9, 11, 15, 16)
        if path.is_file() and zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as archive:
                for number in required:
                    matches = [n for n in archive.namelist()
                               if Path(n).name.startswith(f'{number:02d}_') and n.endswith('.csv')
                               and not n.startswith('__MACOSX/')]
                    if len(matches) != 1:
                        raise ValueError(f'{number:02d}_ CSV가 정확히 하나 필요합니다.')
                    self._read(number, Path(matches[0]).name, archive.read(matches[0]))
        elif path.is_dir():
            for number in required:
                matches = list(path.glob(f'{number:02d}_*.csv'))
                if len(matches) != 1:
                    raise ValueError(f'{path}: {number:02d}_ CSV가 정확히 하나 필요합니다.')
                self._read(number, matches[0].name, matches[0].read_bytes())
        else:
            raise ValueError('--data에 제공 ZIP 또는 CSV 폴더를 지정하세요.')
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
        self.selection, self.selection_scores = self._select()
        # Free row-level sales after aggregation; no raw-data HTTP endpoint exists.
        del self.rows[9]

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
                split_allowed=False, hub_order_mode='regular',
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
    if not date(2026, 8, 1) <= origin <= data.end:
        raise ValueError('기준일은 2026-08-01~2026-09-30이어야 합니다. 7월 선택의 미래 사용을 막기 위한 범위입니다.')
    integer_limits = {'store_count': (1, 12), 'scenarios': (8, 40), 'max_hubs': (0, 3),
                      'vehicle_count': (1, 10), 'vehicle_minutes_per_day': (30, 1440)}
    for name, bounds in integer_limits.items():
        value = validate_number(cfg[name], name, *bounds)
        if value != int(value):
            raise ValueError(f'{name}: 정수가 필요합니다.')
        cfg[name] = int(value)
    for name, bounds in {
        'demand_multiplier': (.1, 5), 'service_target': (.5, .999), 'travel_minutes': (0, 30),
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
        self.windows = {a: supplier_window(data.suppliers[item['supplier']], self.origin)
                        for a, item in data.ingredients.items()}
        # Same next-day emergency exception as source specification; no regular MOQ amount/calendar applied.
        self.hub_windows = {a: ((self.origin, self.origin + timedelta(days=1),
                                self.origin + timedelta(days=2))
                               if cfg['hub_order_mode'] == 'emergency' else self.windows[a]) for a in self.items}
        # Never penalize a policy for not modelling a replenishment decision that
        # occurs AFTER this one-cycle comparison. Bound each SKU identically for
        # direct/hub alternatives, even when their supplier calendars differ.
        self.evaluation_end={a:min(self.windows[a][2],self.hub_windows[a][2])
                             if a in cfg['hub_items'] else self.windows[a][2] for a in self.items}
        for sid,items in cfg['baseline_order_overrides'].items():
            for a,line in items.items():
                if not isinstance(line,dict) or line.get('basis')!='NET_NEED_INCLUDES_SAFETY':
                    raise ValueError('외부 발주는 basis=NET_NEED_INCLUDES_SAFETY와 포장 전 순필요량이 필요합니다.')
                validate_number(line['net_need_before_pack_qty'],'외부 순발주 필요량',0,1e10)
                validate_number(line['safety_qty'],'외부 안전재고',0,1e10)
                if day(line['horizon_end_exclusive'])!=self.windows[a][2]:
                    raise ValueError(f'{sid}/{a}: 외부 발주 기간이 서비스의 다음 입고 경계와 다릅니다.')
        self.stop = max(max(w[2] for w in self.windows.values()), max(w[2] for w in self.hub_windows.values()))
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
                for po in self.data.purchase_orders:
                    if po['source'] == source and po['item'] == a and po['order'] < self.origin <= po['arrival'] < self.evaluation_end[a]:
                        receipts[po['arrival']] += po['units'] * item['pack']
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

    def local_cover(self, sid, a):
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
        response = self.cfg['travel_minutes'] + self.cfg['preparation_minutes'] + self.cfg['receiving_minutes']
        return max(self.forecasts[sid, a], default=0) * min(1, peak * response / 60)

    def make_store_plan(self, sid, alpha, enabled):
        key = sid, alpha, enabled
        if key in self.store_plan_cache:
            return self.store_plan_cache[key]
        lines = []
        for a, item in self.data.ingredients.items():
            use_hub = enabled and a in self.cfg['hub_items']
            safety = self.raw_safety[sid, a]
            if use_hub:
                safety = max(safety * (1-alpha), self.local_cover(sid, a))
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
        plans = {self.ids[i]: self.make_store_plan(self.ids[i], alpha, enabled) for i in members}
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
                        if stock(lots)+EPS < min(need,self.local_cover(sid,a)):
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
        emergency_arrival=self.origin+timedelta(days=1)
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


PAGE = r'''<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>재고의 거리 · 허브 의사결정 실험실</title>
<style>
:root{--bg:#f4f2eb;--ink:#24372e;--sub:#67746a;--line:#d8ddd1;--paper:#fffef9;--green:#235942;--soft:#e5eddf;--orange:#a44a21}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
header{border-bottom:1px solid var(--line);background:var(--paper);padding:20px max(24px,calc((100vw - 1320px)/2));display:flex;justify-content:space-between;align-items:center;gap:20px}
.brand{font-weight:700;letter-spacing:-.7px;font-size:20px}.tag{font-size:12px;color:var(--sub)}main{max-width:1320px;margin:0 auto;padding:32px 24px 60px}
.intro{display:flex;justify-content:space-between;align-items:end;gap:24px;margin-bottom:26px}h1{font-size:30px;line-height:1.3;letter-spacing:-1px;margin:4px 0 12px}h2{font-size:18px;margin:0 0 16px}h3{font-size:14px;margin:18px 0 8px}p{margin:0;color:var(--sub)}.eyebrow{font-size:12px;letter-spacing:2px;color:var(--green);font-weight:700}
.layout{display:grid;grid-template-columns:320px minmax(0,1fr);gap:24px}.panel{background:var(--paper);border:1px solid var(--line);border-radius:12px;padding:22px;min-width:0}.controls{align-self:start}.field{margin-bottom:17px}label{display:block;font-size:13px;font-weight:600;margin-bottom:5px}.pair{display:grid;grid-template-columns:1fr 1fr;gap:12px}input,select,textarea{font:inherit;width:100%;padding:9px 10px;background:#fff;color:var(--ink);border:1px solid #bbc7ba;border-radius:6px}textarea{font:12px/1.5 ui-monospace,monospace;min-height:150px;resize:vertical}input[type=checkbox]{width:auto;margin-right:7px}small{font-size:12px;color:var(--sub);display:block;margin-top:5px}.check{font-size:13px;font-weight:400}.button{background:var(--green);color:white;border:0;border-radius:7px;padding:12px 18px;font:600 14px inherit;cursor:pointer}.button:disabled{opacity:.55;cursor:wait}.button.secondary{background:transparent;color:var(--green);border:1px solid var(--line);padding:8px 13px}.full{width:100%}.status{padding:14px 17px;background:var(--soft);border-radius:8px;margin-bottom:18px}.status.warn{background:#f7e9d5;color:#71452c}.muted{color:var(--sub)}.tiny{font-size:12px}.kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:20px}.kpi{padding:17px;background:var(--paper);border:1px solid var(--line);border-radius:9px}.kpi span{display:block;font-size:12px;color:var(--sub)}.kpi strong{display:block;font-size:25px;letter-spacing:-.6px;font-weight:650;margin-top:4px}.stack{display:grid;gap:18px}.scroll{overflow:auto}.table{width:100%;border-collapse:collapse;font-size:13px;white-space:nowrap}.table th{text-align:left;font-weight:500;color:var(--sub);padding:10px 12px;border-bottom:1px solid var(--line)}.table td{padding:11px 12px;border-bottom:1px solid #e9ece3}.table tr:last-child td{border-bottom:0}.table .num{text-align:right;font-variant-numeric:tabular-nums}.picked{background:#edf3e8}.pill{display:inline-block;padding:2px 8px;border-radius:20px;background:var(--soft);color:var(--green);font-size:11px}.pill.warn{background:#f6e5cf;color:#7b4425}.group{display:grid;grid-template-columns:88px minmax(0,1fr);gap:16px;padding:18px 0;border-top:1px solid var(--line)}.group:first-child{border-top:0;padding-top:0}.hub{font-weight:700;color:var(--green)}.storechips{display:flex;gap:7px;flex-wrap:wrap;margin:5px 0}.chip{padding:4px 9px;border:1px solid var(--line);border-radius:5px;font-size:12px}.bar{height:7px;background:#e5e9df;border-radius:10px;overflow:hidden;margin-top:5px}.bar i{display:block;height:100%;background:var(--green)}.bars{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:12px}.bars span{font-size:11px}.righthead{display:flex;justify-content:space-between;align-items:center;gap:12px}details{margin-top:12px}summary{cursor:pointer;font-size:13px;color:var(--green)}.blank{display:grid;place-items:center;min-height:220px;text-align:center;color:var(--sub)}.error{color:#a52f2f;margin-top:12px;white-space:pre-wrap}.note{border-left:3px solid #a1b69d;padding-left:12px;margin-top:14px;font-size:12px;color:var(--sub)}ul{padding-left:20px}.tabs{display:flex;gap:8px;margin:16px 0;flex-wrap:wrap}.tab{border:1px solid var(--line);background:transparent;padding:7px 12px;border-radius:6px;color:var(--sub);cursor:pointer}.tab.active{background:var(--green);color:white}.loading{animation:pulse 1.2s infinite}@keyframes pulse{50%{opacity:.5}}@media(prefers-reduced-motion:reduce){.loading{animation:none}}@media(max-width:900px){.layout{grid-template-columns:1fr}.intro{display:block}.controls{max-width:none}.kpis{grid-template-columns:repeat(3,1fr)}}@media(max-width:560px){main{padding:22px 14px}header{padding:14px}.tag{display:none}h1{font-size:25px}.panel{padding:16px}.kpis{grid-template-columns:1fr}.kpi strong{font-size:23px}.bars{grid-template-columns:1fr}.group{grid-template-columns:65px 1fr}}
</style></head><body>
<header><div class="brand">재고의 거리 <span class="pill">HUB LAB</span></div><div class="tag">제공 데이터 × 보관 제약 × 30분 공급권</div></header>
<main><div class="intro"><div><div class="eyebrow">INVENTORY NETWORK PLANNING</div><h1>어디에, 얼마나 보관할까요?</h1><p>같은 수요에서 허브 없는 운영과 공동 재고 운영을 비교합니다.</p></div><div id="source" class="tiny muted" aria-live="polite">데이터 확인 중…</div></div>
<div class="layout"><aside class="panel controls"><h2>운영 조건</h2><form id="form">
<div class="pair"><div class="field"><label for="asof">판단 기준일 · 06시</label><input id="asof" type="date" min="2026-08-01" max="2026-09-30" required></div><div class="field"><label for="count">일반 매장 수</label><input id="count" type="number" min="1" max="12" step="1" required></div></div>
<div class="pair"><div class="field"><label for="mult">수요 배율</label><input id="mult" type="number" min="0.1" max="5" step="0.1"></div><div class="field"><label for="hubs">허브 후보 수</label><input id="hubs" type="number" min="0" max="3" step="1"></div></div>
<div class="pair"><div class="field"><label for="service">수량 충족 목표 · %</label><input id="service" type="number" min="50" max="99.9" step="0.1"></div><div class="field"><label for="travel">허브→매장 · 분</label><input id="travel" type="number" min="0" max="30" step="1"></div></div>
<h3>공동 재고 순여유 공간 · L</h3><div class="pair"><div class="field"><label for="chilled">냉장</label><input id="chilled" type="number" min="0" max="100000"></div><div class="field"><label for="frozen">냉동</label><input id="frozen" type="number" min="0" max="100000"></div></div><div class="field"><label for="ambient">상온</label><input id="ambient" type="number" min="0" max="100000"><small>허브 자체 영업 재고 공간을 제외한 값입니다.</small></div>
<h3>배송·운영비 가정</h3><div class="pair"><div class="field"><label for="trip">배송 1회 · 원</label><input id="trip" type="number" min="0" step="500"></div><div class="field"><label for="fixed">허브 1곳/일 · 원</label><input id="fixed" type="number" min="0" step="1000"></div></div>
<div class="field"><label for="mode">허브의 공급사 발주</label><select id="mode"><option value="regular">정기 · 요일/최소금액 적용</option><option value="emergency">긴급 · 데이터상 예외 적용</option></select></div>
<label class="check"><input id="split" type="checkbox">포장 분할·이동을 운영상 허용</label><small>기본값은 분할 금지입니다. 허용 여부는 별도 확인해야 합니다.</small>
<details><summary>가정·팀 모듈 연결 입력</summary><small>추가 매장은 원본 3매장 프로필 복제입니다. 부피·경로는 실측값으로 바꾸세요.</small><label for="advanced">고급 JSON · 기본값과 병합</label><textarea id="advanced" spellcheck="false" aria-label="고급 시나리오 JSON"></textarea></details>
<button class="button full" id="run" type="submit" style="margin-top:20px">운영안 계산</button><div id="error" class="error" role="alert"></div>
</form></aside>
<section id="results" aria-live="polite"><div class="panel blank"><div>공급사 조건과 로트 재고를 읽었습니다.<br>운영 조건을 바꾸고 계산해 보세요.</div></div></section></div></main>
<script>
(()=>{'use strict';let meta=null,last=null;const $=id=>document.getElementById(id),fmt=n=>Math.round(n||0).toLocaleString('ko-KR'),pct=n=>((n||0)*100).toFixed(1)+'%',esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function input(id,v){$(id).value=v}function num(id){return Number($(id).value)}
fetch('/api/meta').then(r=>r.json()).then(r=>{meta=r;const d=r.defaults;input('asof',d.as_of);input('count',d.store_count);input('mult',d.demand_multiplier);input('hubs',d.max_hubs);input('service',d.service_target*100);input('travel',d.travel_minutes);for(const z of ['chilled','frozen','ambient'])input(z,d.capacity_liters[z]);input('trip',d.trip_cost);input('fixed',d.hub_daily_cost);input('mode',d.hub_order_mode);input('advanced',JSON.stringify({alpha_grid:d.alpha_grid,hub_items:d.hub_items,scenarios:d.scenarios,vehicle_count:d.vehicle_count,vehicle_minutes_per_day:d.vehicle_minutes_per_day,pack_volume_liters:d.pack_volume_liters,matrix:{}},null,2));$('source').innerHTML='2026.01–09 · 실제 제공 매장 3개<br>선택 모델 '+Object.entries(r.metadata.forecast_models).map(([k,v])=>esc(k+' '+v)).join(' / ');}).catch(e=>{$('error').textContent=e.message});
function table(headers,rows){return '<div class="scroll"><table class="table"><thead><tr>'+headers.map(h=>'<th>'+esc(h)+'</th>').join('')+'</tr></thead><tbody>'+rows.join('')+'</tbody></table></div>'}
function tr(values,cls=''){return '<tr class="'+cls+'">'+values.map((v,i)=>'<td'+(i?' class="num"':'')+'>'+v+'</td>').join('')+'</tr>'}
function render(r){last=r;let selected=r.recommended||r.diagnostic;const ok=!!r.recommended,delta=r.baseline.economic_cost-selected.economic_cost;
let html='<div class="status '+(ok?'':'warn')+'"><strong>'+(ok?(selected.hub_count?'허브 '+selected.hub_count+'곳을 사용하는 안':'허브 없이 운영하는 안'):'현재 조건에서는 실행 가능한 운영안이 없습니다.')+'</strong><br><span class="tiny">'+(ok?'입력한 가정과 과거 오차 시나리오에서의 비교 결과입니다.':'아래 상세는 가장 가까운 진단안입니다. 제약을 확인하고 다시 계산하세요.')+'</span></div>';
html+='<div class="kpis"><div class="kpi"><span>추정 경제비용 · '+r.horizon.start+'~'+r.horizon.end_exclusive+' 직전</span><strong>'+fmt(selected.economic_cost)+'원</strong></div><div class="kpi"><span>허브 없는 기준안 대비 차이</span><strong>'+(delta>=0?'−':'+')+fmt(Math.abs(delta))+'원</strong></div><div class="kpi"><span>원가기준 식자재 수량 충족률</span><strong>'+pct(selected.fill_rate)+'</strong></div></div>';
html+='<div class="stack"><div class="panel"><div class="righthead"><h2>허브 수별 비교</h2><button class="button secondary" id="download">결과 JSON 저장</button></div>'+table(['허브','경제비용','구매 현금','배송비','충족률','판정'],r.alternatives.map(a=>tr([a.hub_count+'곳',fmt(a.economic_cost),fmt(a.purchase_cost),fmt(a.logistics_cost),pct(a.fill_rate),'<span class="pill '+(a.feasible?'':'warn')+'">'+(a.feasible?'조건 충족':'검토 필요')+'</span>'],a.hub_count===selected.hub_count?'picked':'')))+'<div class="note">종료 재고 가치를 반영한 비용입니다. 구매액 감소를 그대로 절감액으로 계산하지 않습니다. '+(r.search_method.startsWith('exact')?'6매장 이하: 후보 허브·그룹·감축률 조합 탐색.':'7매장 이상: 근사 그룹 탐색이며 전역 최적해를 보장하지 않습니다.')+'</div></div>';
html+='<div class="panel"><h2>매장 그룹과 보관 제약</h2>'+r.selected_details.map(g=>{let label=g.hub||'직접 발주';let notes=[];if(!g.capacity_ok)notes.push('보관 한도 초과');if(!g.fleet_ok)notes.push('배송 여력 초과');if(g.order_review)notes.push('허브 최소 발주금액 미달');if(g.outside_30_minutes.length)notes.push('30분 공급권 이탈');if(!g.service_feasible)notes.push('수량 충족 목표 미달');if(g.store_order_review_count)notes.push('매장 발주 '+g.store_order_review_count+'줄 최소금액 검토');return '<div class="group"><div class="hub">'+esc(label)+'</div><div><div class="storechips">'+g.members.map(s=>'<span class="chip">'+esc(s)+'</span>').join('')+'</div><span class="tiny muted">안전재고 감축 후보 '+Math.round(g.alpha*100)+'% · 최대 '+g.peak_daily_trips+'회/일 배송 · 충족률 '+pct(g.fill_rate)+'</span>'+(notes.length?'<div class="tiny" style="color:var(--orange)">'+notes.map(esc).join(' / ')+'</div>':'')+(g.hub?'<div class="bars">'+['chilled','frozen','ambient'].map((z,i)=>{const cap=r.config.capacity_liters[z],used=g.peak_liters[z];return '<div><span>'+['냉장','냉동','상온'][i]+' '+used.toFixed(1)+' / '+fmt(cap)+'L</span><div class="bar"><i style="width:'+Math.min(100,cap?used/cap*100:used?100:0)+'%;'+(used>cap?'background:var(--orange)':'')+'"></i></div></div>'}).join('')+'</div>':'')+'</div></div>'}).join('')+'</div>';
const orders=r.selected_details.flatMap(g=>g.hub_orders||[]).filter(o=>o.units>0);html+='<div class="panel"><h2>허브 발주 초안</h2>'+(orders.length?table(['허브 / 품목','입고일','필요량 → 포장','금액','상태'],orders.map(o=>tr([esc(o.store+' · '+o.name),esc(o.arrival),fmt(o.needed_qty)+esc(o.use_unit)+' → '+fmt(o.units)+esc(o.order_unit),fmt(o.cost),esc(o.status==='MIN_AMOUNT_REVIEW'?'최소금액 검토':'승인 전 초안')]))):'<p>현재 선택안에는 허브 추가 발주가 없습니다.</p>')+'</div>';
const shortages=r.selected_details.flatMap(g=>g.forecast_scenario.shortages);html+='<div class="panel"><h2>기준 수요에서 해결되지 않는 부족</h2>'+(shortages.length?table(['매장 / 품목','날짜','부족량','원인'],shortages.slice(0,30).map(x=>tr([esc(x.store+' · '+meta.metadata.ingredients.find(a=>a.id===x.item).name),esc(x.date),fmt(x.qty)+esc(x.use_unit),esc(x.status==='BEFORE_NEW_RECEIPT'?'새 입고 전 부족':'보충 후에도 부족')]))):'<p>일 단위 기준 수요 시나리오에서 미충족 수량이 없습니다.</p>')+'<div class="note">다음날 도착하는 긴급발주로 오늘의 부족을 해결했다고 표시하지 않습니다. 긴급발주 초안 '+r.emergency_drafts.length+'건은 JSON에 포함됩니다.</div></div>';
html+='<div class="panel"><details><summary>매장 정기발주·공급 계획</summary>'+table(['매장 / 품목','입고일','포장 수','금액','상태'],r.selected_details.flatMap(g=>g.store_orders).filter(x=>x.units>0).map(o=>tr([esc(o.store+' · '+o.name),esc(o.arrival),fmt(o.units)+esc(o.order_unit),fmt(o.cost),esc(o.status==='MIN_AMOUNT_REVIEW'?'최소금액 검토':'초안')])))+'</details><details><summary>데이터·가정·해석 범위</summary><ul class="tiny muted">'+r.assumptions.map(s=>'<li>'+esc(s)+'</li>').join('')+'</ul><p class="tiny">과거 오차 블록 '+r.scenario_count+'개 · 그룹 평가 '+r.computed_group_scenarios+'개 · '+esc(r.recommendation_status)+'</p></details></div></div>';
$('results').innerHTML=html;$('download').onclick=()=>{const blob=new Blob([JSON.stringify(last,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='hub-plan-'+last.config.as_of+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};}
$('form').addEventListener('submit',async e=>{e.preventDefault();$('error').textContent='';$('run').disabled=true;$('run').textContent='재고·그룹·발주 계산 중…';try{const advanced=JSON.parse($('advanced').value||'{}');const payload={...advanced,as_of:$('asof').value,store_count:num('count'),demand_multiplier:num('mult'),max_hubs:num('hubs'),service_target:num('service')/100,travel_minutes:num('travel'),capacity_liters:{chilled:num('chilled'),frozen:num('frozen'),ambient:num('ambient')},trip_cost:num('trip'),hub_daily_cost:num('fixed'),hub_order_mode:$('mode').value,split_allowed:$('split').checked};const res=await fetch('/api/plan',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}),result=await res.json();if(!res.ok)throw Error(result.error||'계산 실패');render(result)}catch(err){$('error').textContent=err.message}finally{$('run').disabled=false;$('run').textContent='운영안 계산'}});
})();
</script></body></html>'''


def create_server(data, host='127.0.0.1', port=8765, initial_config=None):
    # One bounded calculation at a time prevents repeated UI requests from exhausting CPU.
    compute_lock=threading.Lock()
    class Handler(BaseHTTPRequestHandler):
        def reply(self,status,payload,kind='application/json; charset=utf-8'):
            raw=payload.encode('utf-8') if isinstance(payload,str) else json.dumps(payload,ensure_ascii=False,allow_nan=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type',kind)
            self.send_header('Content-Length',str(len(raw)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data:")
            self.end_headers(); self.wfile.write(raw)

        def allowed_host(self):
            return self.headers.get('Host','').split(':')[0] in ('127.0.0.1','localhost')

        def do_GET(self):
            if not self.allowed_host():
                return self.reply(403,{'error':'localhost 전용입니다.'})
            if self.path=='/':
                return self.reply(200,PAGE,'text/html; charset=utf-8')
            if self.path=='/api/meta':
                return self.reply(200,dict(metadata=data.metadata(),defaults=clean_config(data,initial_config or {})))
            if self.path=='/health':
                return self.reply(200,dict(status='ok',version=VERSION))
            return self.reply(404,{'error':'경로를 찾을 수 없습니다.'})

        def do_POST(self):
            if not self.allowed_host():
                return self.reply(403,{'error':'localhost 전용입니다.'})
            origin=self.headers.get('Origin')
            if origin and origin not in (f'http://{self.headers.get("Host")}',):
                return self.reply(403,{'error':'같은 출처의 요청만 허용합니다.'})
            if self.path!='/api/plan':
                return self.reply(404,{'error':'경로를 찾을 수 없습니다.'})
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=1000000:
                    raise ValueError('요청은 1MB 이하 JSON이어야 합니다.')
                body=json.loads(self.rfile.read(size))
                with compute_lock:
                    result=plan(data,{**(initial_config or {}),**body})
                self.reply(200,result)
            except (ValueError,KeyError,TypeError,OverflowError) as e:
                self.reply(400,{'error':str(e)})
            except Exception:
                traceback.print_exc()
                self.reply(500,{'error':'계산 중 오류가 발생했습니다. 서버 로그를 확인하세요.'})

        def log_message(self,fmt,*args):
            print('[HTTP]',fmt%args,flush=True)
    return ThreadingHTTPServer((host,port),Handler)


def self_test():
    import unittest
    class CoreTests(unittest.TestCase):
        def test_fefo(self):
            lots=[[5,date(2026,9,5)],[3,date(2026,9,2)]]
            pieces,unmet=take(lots,6)
            self.assertEqual(pieces,[[3,date(2026,9,2)],[3,date(2026,9,5)]])
            self.assertEqual(unmet,0); self.assertEqual(stock(lots),2)
        def test_conservation(self):
            lots=[[7,date(2026,9,2)]]
            moved,unmet=take(lots,12)
            self.assertEqual(sum(q for q,e in moved)+stock(lots),7)
            self.assertEqual(unmet,5)
        def test_expiry_last_day(self):
            lots=[[7,date(2026,9,2)]]
            self.assertEqual(expire(lots,date(2026,9,2)),0)
            self.assertEqual(expire(lots,date(2026,9,3)),7)
        def test_transfer_expiry_preserved(self):
            lots=[[5,date(2026,9,2)]]; receiver=[]
            pieces,_=take(lots,2);receiver.extend(pieces)
            self.assertEqual(receiver[0][1],date(2026,9,2))
        def test_quantile(self):
            self.assertEqual(quantile(list(range(1,21)),.95),19)
        def test_whole_pack(self):
            self.assertEqual(pack_round(1001,1000),2)
            self.assertEqual(pack_round(0,1000),0)
            self.assertEqual(pack_round(1,1000,3),3)
        def test_supplier_calendar(self):
            s=dict(order_days={6,1,3,4},delivery_days={0,2,4,5},lead=1)
            self.assertEqual(supplier_window(s,date(2026,9,7)),
                             (date(2026,9,8),date(2026,9,9),date(2026,9,11)))
        def test_positive_requests_do_not_cancel(self):
            errors=[-10,10]
            self.assertEqual(sum(max(0,x) for x in errors),10)
        def test_invalid_float(self):
            with self.assertRaises(ValueError):validate_number(float('nan'),'x',0,1)
        def test_no_silent_capacity_clip(self):
            required,cap=40,35
            self.assertFalse(required<=cap)
        def test_open_fractions_are_not_whole_pack(self):
            lots=[[600,date(2026,9,2)],[400,date(2026,9,3)]]
            pieces,unmet=take_whole_packs(lots,1000,1000)
            self.assertEqual(pieces,[]);self.assertEqual(unmet,1000)
            self.assertEqual(stock(lots),1000)
        def test_same_expiry_no_double_use(self):
            lots=[[4,date(2026,9,2)]]
            a,_=take(lots,3);b,left=take(lots,3)
            self.assertEqual(sum(x[0] for x in a+b),4);self.assertEqual(left,2)
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(CoreTests)
    return unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful()


def main():
    parser=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--data',type=Path,help='제공 ZIP 또는 CSV 폴더')
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--config',type=Path,help='선택: API와 같은 JSON 시나리오')
    parser.add_argument('--report',type=Path,help='선택: 서버 대신 계산 결과 JSON 저장')
    parser.add_argument('--self-test',action='store_true')
    args=parser.parse_args()
    if args.self_test:
        raise SystemExit(0 if self_test() else 1)
    if not args.data:
        parser.error('--data로 ZIP 또는 CSV 폴더를 지정하세요.')
    print('데이터를 읽고 7월 평균 후보를 비교합니다…',flush=True)
    data=Dataset(args.data)
    print('선택 모델:',data.selection,flush=True)
    cfg=json.loads(args.config.read_text(encoding='utf-8')) if args.config else {}
    if args.report:
        result=plan(data,cfg)
        args.report.parent.mkdir(exist_ok=True,parents=True)
        args.report.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        print('결과:',args.report.resolve(),flush=True)
        return
    server=create_server(data,port=args.port,initial_config=cfg)
    print(f'Local: http://127.0.0.1:{server.server_port}',flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__=='__main__':
    main()
