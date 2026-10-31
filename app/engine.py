"""재고·발주 의사결정 엔진. 기준일 아침에 알 수 있는 정보만 사용한다.

- 수요 예측: app/forecast.py (EWMA × 요일지수 × 공휴일 × 행사)
- 발주: 다음 정기입고 전날까지 FEFO로 재고를 투영해 부족분 + 품목별 안전재고를 포장단위로 발주.
  안전재고 = z_i × (입고주기 합계 예측오차 RMSE). z_i는 '부족 1단위당 막히는 공헌이익'과
  '초과 1단위 보유비용'의 임계비율로 정하고 전체 강도 α로 조정한다 (1~9월 백테스트 기본값 α=1.6).
- 최소 발주금액 미달: 급한 품목이 없으면 다음 발주일로 이월, 있으면 사용기한 위험이 낮은 품목을 앞당겨 채운다.
- 매장 간 이동: 개점 전 09:00 출발 가정. 오늘 품절 예상분(회피 공헌이익)과 기한 내 못 쓸 재고(회피 폐기원가)만
  옮기고, 경로별 회피손실 합계가 운송비보다 클 때만 실행한다.
- 결과는 읽기 전용 추천이며 실제 주문·이동을 실행하지 않는다.
"""
from __future__ import annotations

import json
from collections import defaultdict
from copy import deepcopy
from datetime import date, timedelta
from math import ceil, floor
from pathlib import Path
from statistics import NormalDist
from typing import Any

import numpy as np
import pandas as pd
from fastapi import HTTPException
from pydantic import BaseModel, Field

from app.forecast import Forecaster, EXTRA_HOLIDAYS
from app.lot_projection import project_lot_usage

DAYS = list('월화수목금토일')
QUALITY_RATE = {'냉장': 0.003}          # 냉장 품목 품질 폐기: 잔량의 일 0.3% (1~9월 실적 기대값)
HOLD_RATE = {'냉장': 0.003, '냉동': 0.0005, '상온': 0.0005}
BACKTEST_FILE = Path(__file__).resolve().parent / 'static' / 'backtest.json'

MODE_NAMES = {
    'independent': 'M0 · 매장별 발주',
    'independent_transfer': 'M0+ · 매장별 발주 + 매장 간 이동',
    'pooled': 'M1 · 통합발주 (가정)',
    'shared': 'M2 · 통합발주 + 이동 (가정)',
}
COMPLIANT = ('independent', 'independent_transfer')   # 제공 데이터의 발주 규칙(매장·공급사·일자별 발주서)과 일치


class Scenario(BaseModel):
    as_of: date = date(2026, 10, 1)
    store_id: str = 'S01'
    horizon_days: int = Field(7, ge=1, le=14)
    demand_multiplier: float = Field(1, ge=.5, le=2)
    delay_days: int = Field(0, ge=0, le=3)
    safety_alpha: float = Field(1.6, ge=.5, le=2.5)
    service_level: float | None = Field(None, ge=.5, le=.999)   # 이전 버전 호환용. 사용하지 않음
    transfer_minutes: int = Field(30, ge=0, le=180)
    transfer_cost: float = Field(0, ge=0, le=1000000)  # task baseline excludes transport expense
    can_split_pack: bool = False


def fmt(x: float) -> str:
    return f'{x:,.0f}'


class Engine:
    def __init__(self, data: dict[str, pd.DataFrame]):
        self.data = data
        self.stores = {r['store_id']: r for r in data['01_stores'].to_dict('records')}
        self.items = {r['ingredient_id']: r for r in data['03_ingredients'].to_dict('records')}
        self.menus = {r['menu_id']: r for r in data['02_menus'].to_dict('records')}
        self.suppliers = {r['supplier_id']: r for r in data['05_suppliers'].to_dict('records')}
        self.bom = defaultdict(dict)
        for r in data['04_bom'].to_dict('records'):
            self.bom[r['menu_id']][r['ingredient_id']] = float(r['qty_per_menu'])
        self.prices = defaultdict(list)
        for r in data['06_ingredient_price_history'].to_dict('records'):
            self.prices[r['ingredient_id']].append((date.fromisoformat(r['valid_from']), float(r['unit_price'])))
        for xs in self.prices.values():
            xs.sort()
        self.lots = data['16_inventory_lots_daily']
        self.pos = data['11_purchase_orders']
        self.receipts = data['12_receipts']
        self.F = Forecaster(data)
        self.last_history_day = self.F.last
        self.si = {s: k for k, s in enumerate(self.F.stores)}
        self.mi = {m: k for k, m in enumerate(self.F.menus)}
        self.ii = {i: k for k, i in enumerate(self.F.items)}
        # 메뉴 공헌이익 (가상 판매가 − BOM 원가, 기간 평균 단가)
        mean_uc = {i: np.mean([p for _, p in self.prices[i]]) / float(self.items[i]['use_qty_per_order_unit']) for i in self.items}
        self.margin = {m: float(r['virtual_price']) - sum(q * mean_uc[i] for i, q in self.bom[m].items()) for m, r in self.menus.items()}
        self.mean_uc = mean_uc
        self._z, self._cu = {}, {}
        bt = BACKTEST_FILE
        self.backtest = json.loads(bt.read_text(encoding='utf-8')) if bt.exists() else None

    # ------------------------------------------------------------------ 기본 조회
    def price(self, i: str, day: date) -> float:
        rows = self.prices[i]
        return next((p for d, p in reversed(rows) if d <= day), rows[0][1])

    def unit_cost(self, i: str, day: date) -> float:
        return self.price(i, day) / float(self.items[i]['use_qty_per_order_unit'])

    def z(self, i: str, alpha: float, as_of: date) -> float:
        """품목별 안전재고 계수: 임계비율 cu/(cu+co)의 정규분위수 × α (0.5~4.5로 제한).
        cu = 이 식자재 1단위 부족 시 막히는 공헌이익 (기준일 전 메뉴 판매 비중으로 가중)
        co = 1단위 초과 보유 비용 (보관 손실 + 사용기한이 짧으면 만료 위험)"""
        key = (i, round(alpha, 3), as_of)
        if key not in self._z:
            if as_of not in self._cu:
                dem = self.F.Y[:, :, :max(1, self.F.idx(as_of))].sum((0, 2))
                cu = {}
                for it in self.items:
                    ms = [m for m in self.menus if it in self.bom[m]]
                    w = sum(dem[self.mi[m]] * self.bom[m][it] for m in ms)
                    cu[it] = sum(dem[self.mi[m]] * self.margin[m] for m in ms) / max(w, 1e-9)
                self._cu[as_of] = cu
            cu = self._cu[as_of][i]
            ir = self.items[i]; shelf = int(ir['shelf_life_days'])
            co = self.mean_uc[i] * (HOLD_RATE[ir['storage']] * 2 + (2.0 / shelf if shelf <= 14 else 0))
            cr = cu / (cu + co)
            self._z[key] = float(np.clip(alpha * NormalDist().inv_cdf(min(cr, 0.99997)), 0.5, 4.5))
        return self._z[key]

    def cu(self, i: str, as_of: date) -> float:
        self.z(i, 1.0, as_of)
        return self._cu[as_of][i]

    def active(self, s: str, m: str, day: date) -> bool:
        t = self.F.idx(day)
        return 0 <= t < self.F.A.shape[2] and bool(self.F.A[self.si[s], self.mi[m], t])

    def forecasts(self, sc: Scenario) -> tuple[dict, dict]:
        """기준일 아침 예측 (전날까지 판매만 사용) × 수요 배율"""
        fm = self.F.menu(sc.as_of) * sc.demand_multiplier
        fi = self.F.item(sc.as_of) * sc.demand_multiplier
        bymenu, byitem = {}, {}
        n = min(sc.horizon_days + 9, self.F.K)
        for k in range(n):
            day = sc.as_of + timedelta(days=k)
            for s, si in self.si.items():
                for m, mi in self.mi.items():
                    if fm[si, mi, k] > 0:
                        bymenu[(day, s, m)] = float(fm[si, mi, k])
                for i, ii in self.ii.items():
                    byitem[(day, s, i)] = float(fi[si, ii, k])
        return bymenu, byitem

    def initial(self, sc: Scenario) -> tuple[dict, dict, list[str]]:
        prev = sc.as_of - timedelta(days=1)
        if prev < date(2026, 1, 1) or prev > self.last_history_day:
            raise HTTPException(status_code=422, detail='기준일 이전 영업 종료 재고가 없습니다. 2026-01-02~2026-10-01 범위에서 선택하세요.')
        filtered = self.lots[self.lots['date'] == prev.isoformat()]
        if filtered.empty:
            raise HTTPException(422, '입고 묶음별 재고가 없는 기준일입니다.')
        lots = defaultdict(list)
        for r in filtered.itertuples(index=False):
            qty = float(r.remaining_qty)
            if qty > 0:
                lots[(r.store_id, r.ingredient_id)].append({'qty': qty, 'expiry': date.fromisoformat(r.last_use_date),
                    'receipt_date': date.fromisoformat(r.receipt_date), 'lot': str(r.lot_id)})
        issues = []
        inv = self.data['10_inventory_daily']
        last = inv[inv['date'] == prev.isoformat()]
        lot_sums = {k: sum(x['qty'] for x in xs) for k, xs in lots.items()}
        for r in last.itertuples(index=False):
            if abs(lot_sums.get((r.store_id, r.ingredient_id), 0) - float(r.closing_qty)) > 0.01:
                issues.append(f'{r.store_id}/{r.ingredient_id} lot 잔량·마감재고 불일치')
        # 기준일 전에 넣었지만 아직 입고되지 않은 발주 (예: 9/30 발주 → 10/1 입고, 입고 파일에는 없음)
        prevpo = self.pos[self.pos['order_date'] < sc.as_of.isoformat()]
        rec = self.receipts[self.receipts['receipt_date'] < sc.as_of.isoformat()].groupby('po_line_id')['received_qty'].sum().to_dict()
        arrivals = defaultdict(list)
        for r in prevpo.itertuples(index=False):
            qty = float(r.order_qty) - float(rec.get(r.po_line_id, 0))
            if qty <= 0:
                continue
            scheduled = max(sc.as_of, date.fromisoformat(r.expected_date) + timedelta(days=sc.delay_days))
            amount = qty * float(self.items[r.ingredient_id]['use_qty_per_order_unit'])
            arrivals[scheduled].append({'store': r.store_id, 'item': r.ingredient_id, 'qty': amount, 'pending': True})
        return lots, arrivals, issues

    # ------------------------------------------------------------------ 재고 도구
    @staticmethod
    def burn(lots: dict, key: tuple, qty: float, *, consume: bool = True) -> float:
        xs = sorted(lots[key], key=lambda x: x['expiry'])
        remaining = qty
        for lot in xs:
            take = min(remaining, lot['qty'])
            if consume:
                lot['qty'] -= take
            remaining -= take
            if remaining <= 1e-8:
                break
        if consume:
            lots[key] = [l for l in xs if l['qty'] > 1e-8]
        return qty - max(0, remaining)

    @staticmethod
    def count(lots: dict, key: tuple, day: date) -> float:
        return sum(x['qty'] for x in lots[key] if x['expiry'] >= day)

    def orders_day(self, sup: dict, d: date) -> bool:
        return DAYS[d.weekday()] in sup['order_days'].split(',')

    def receipt_day(self, sup: dict, d: date) -> bool:
        return DAYS[d.weekday()] in sup['delivery_days'].split(',')

    def delivery(self, sup: dict, order: date, delay: int) -> date:
        d = order + timedelta(days=int(sup['lead_time_days']) + delay)
        for _ in range(14):
            if self.receipt_day(sup, d):
                return d
            d += timedelta(days=1)
        raise ValueError('납품 요일을 찾지 못했습니다')

    def next_order(self, sup: dict, from_day: date) -> date:
        for n in range(15):
            d = from_day + timedelta(days=n)
            if self.orders_day(sup, d):
                return d
        raise ValueError('발주일을 찾지 못했습니다')

    def project(self, lots: dict, arrivals: dict, s: str, i: str, day: date, H: int, f: list[float]):
        """FEFO 투영: 오늘부터 H일 동안 예측 소요를 쓸 때 (부족량, 기간 끝 잔량, 기한경과 예상량)"""
        shelf = int(self.items[i]['shelf_life_days'])
        L = [[x['expiry'], x['qty'], day] for x in lots[(s, i)] if x['qty'] > 0]
        for t in range(H):
            d = day + timedelta(days=t)
            for r in arrivals.get(d, []):
                if r['store'] == s and r['item'] == i:
                    L.append([d + timedelta(days=shelf - 1), r['qty'], d])
        L.sort(key=lambda x: x[0])
        short = exp = 0.0
        for t in range(H):
            d = day + timedelta(days=t)
            need = f[t]
            for l in L:
                if need <= 0:
                    break
                if l[2] <= d <= l[0] and l[1] > 0:
                    take = min(l[1], need); l[1] -= take; need -= take
            short += need
            for l in L:
                if l[0] == d and l[1] > 0:
                    exp += l[1]; l[1] = 0
        left = sum(l[1] for l in L if l[0] >= day + timedelta(days=H))
        return short, left, exp

    # ------------------------------------------------------------------ 발주
    def line_need(self, sc, s, i, day, a1, H, lots, arrivals, fitem):
        ir = self.items[i]
        pack = float(ir['use_qty_per_order_unit']); shelf = int(ir['shelf_life_days'])
        f = [fitem.get((day + timedelta(days=t), s, i), 0.) for t in range(H)]
        stock = self.count(lots, (s, i), day)
        if sum(f) <= 0:
            return dict(store=s, item=i, q=0, urgent=False, ppd=0, risk=9, doc=99, need=0, stock=stock,
                        ss=0, short=0, exp=0, z=0, pack=pack, padded=0, want=0.0, gap=0.0,
                        left=stock, base_q=0, safety_topup=0., rounding_qty=0.)
        short, left, exp = self.project(lots, arrivals, s, i, day, H, f)
        off = (day - sc.as_of).days
        rmse = self.F.horizon_rmse(self.si[s], self.ii[i], sc.as_of, off, off + H) * sc.demand_multiplier
        z = self.z(i, sc.safety_alpha, sc.as_of)
        ss = z * rmse
        gap = short + max(0.0, ss - left)
        q = ceil(round(gap / pack, 9)) if gap > 1e-9 else 0
        if q > 0:   # 새 입고분이 사용기한 안에 쓰일 수 있는 포장 수로 제한 (예측 부족분은 확보)
            a_off = (a1 - day).days
            fpost = [fitem.get((day + timedelta(days=a_off + t), s, i), 0.) for t in range(min(shelf, 14))]
            # 냉장: 보유량에 비례해 품질 폐기가 나므로 14일 소요까지만 허용
            # 냉동·상온: 품질 폐기가 없으므로 사용기한 전체(14일 이후는 예측 평균으로 연장)까지 허용
            window = min(shelf, 14) if ir['storage'] == '냉장' else shelf
            post = sum(fpost) + (sum(fpost) / len(fpost)) * max(0, window - len(fpost))
            cap = floor(max(0.0, post - left) / pack)
            qmin = ceil(round(short / pack, 9))
            q = max(qmin, min(q, cap))
        if q > 0:
            q = max(q, int(ir['min_order_qty']))
        want = min(gap, q * pack) if q > 0 else 0.0
        incoming = sum(r['qty'] for xs in arrivals.values() for r in xs if r['store'] == s and r['item'] == i)
        mean_f = max(sum(f) / len(f), 1e-9)
        return dict(store=s, item=i, q=q, urgent=(short + max(0.0, 0.5 * ss - left)) > 1e-9, ppd=mean_f / pack,
                    risk=(pack / mean_f) / shelf, doc=(stock + incoming + q * pack) / mean_f,
                    need=sum(f), stock=stock, ss=ss, short=short, exp=exp, z=z, pack=pack, padded=0, want=want, gap=gap,
                    left=left, base_q=q, safety_topup=max(0.,ss-left), rounding_qty=max(0.,q*pack-gap))

    def reason(self, ln: dict, day: date, a2: date) -> str:
        u = self.items[ln['item']]['use_unit']
        usable = ln['stock'] - ln['exp']
        end = (a2 - timedelta(days=1)).strftime('%m/%d')
        if ln['q'] > 0:
            txt = (f"{day.strftime('%m/%d')}~{end} 예상소요 {fmt(ln['need'])}{u} + 안전재고 {fmt(ln['ss'])}{u}"
                   f" − 사용가능 재고 {fmt(usable)}{u} → {ln['q']}{self.items[ln['item']]['order_unit']}")
            if ln['exp'] > 0:
                txt += f" (기한 경과 예상 {fmt(ln['exp'])}{u} 제외)"
            if ln['padded']:
                txt += f" · 최소금액 충족 위해 {ln['padded']}단위 앞당김"
            return txt
        if ln.get('gap', 0) > 1e-9:
            return (f"{end}까지 예상소요 {fmt(ln['need'])}{u}는 충당되나 안전재고 일부 부족. "
                    f"1{self.items[ln['item']]['order_unit']}({fmt(ln['pack'])}{u})를 사용기한 안에 다 쓰기 어려워 발주 보류")
        return f"사용가능 재고 {fmt(usable)}{u}로 {end}까지 예상소요 {fmt(ln['need'])}{u}와 안전재고 {fmt(ln['ss'])}{u} 충당"

    def recommend_orders(self, sc: Scenario, mode: str, day: date, lots: dict, arrivals: dict, fitem: dict, results: dict):
        for supid, sup in self.suppliers.items():
            if not self.orders_day(sup, day):
                continue
            a1 = self.delivery(sup, day, sc.delay_days)
            nxt = self.next_order(sup, day + timedelta(days=1))
            a2 = self.delivery(sup, nxt, sc.delay_days)
            H = max(1, (a2 - day).days)
            lines = [self.line_need(sc, s, i, day, a1, H, lots, arrivals, fitem)
                     for i, ir in self.items.items() if ir['supplier_id'] == supid for s in self.stores]
            groups = defaultdict(list)
            for ln in lines:
                groups[ln['store'] if mode == 'independent' else 'ALL'].append(ln)
            minimum = float(sup['min_order_amount'])
            for group, gl in groups.items():
                pooled_split = mode != 'independent' and sc.can_split_pack
                byitem = defaultdict(list)
                for ln in gl:
                    byitem[ln['item']].append(ln)

                def packs_of(i):
                    xs = byitem[i]
                    if pooled_split:   # 소분 허용 가정: 매장별 올림 대신 필요량 합계를 한 번만 올림
                        want = sum(x['want'] for x in xs)
                        return max(int(self.items[i]['min_order_qty']), ceil(round(want / xs[0]['pack'], 9))) if want > 1e-9 else 0
                    return sum(x['q'] for x in xs)

                amount = sum(packs_of(i) * self.price(i, day) for i in byitem)
                if amount <= 0:
                    continue
                if amount + 1e-8 < minimum:
                    if not any(x['urgent'] for x in gl if x['q'] > 0):
                        results['blocked'].append({'date': day.isoformat(), 'supplier': supid, 'store': group, 'amount': round(amount),
                                                   'minimum': round(minimum), 'action': '이월',
                                                   'reason': f'급한 품목이 없어 다음 발주일({nxt.strftime("%m/%d")})로 이월'})
                        continue
                    cand = [x for x in gl if x['ppd'] > 0 and x['risk'] < 0.35] or [x for x in gl if x['ppd'] > 0]
                    added = 0
                    while amount + 1e-8 < minimum and cand:
                        x = min(cand, key=lambda y: y['doc'])
                        x['q'] += 1; x['padded'] += 1; x['want'] += x['pack']; x['doc'] += x['pack'] / max(x['ppd'] * x['pack'], 1e-9)
                        amount += self.price(x['item'], day); added += 1
                    results['blocked'].append({'date': day.isoformat(), 'supplier': supid, 'store': group, 'amount': round(amount),
                                               'minimum': round(minimum), 'action': '채움',
                                               'reason': f'급한 품목이 있어 사용기한 위험이 낮은 품목 {added}단위를 앞당겨 최소금액 충족'})
                for i, xs in byitem.items():
                    packs = packs_of(i)
                    if packs <= 0:
                        continue
                    pack = xs[0]['pack']
                    if pooled_split:
                        want = [(x['store'], x['want']) for x in xs if x['want'] > 0]
                        tot = sum(w for _, w in want); got = packs * pack
                        alloc = [(st, w * min(1.0, got / tot)) for st, w in want]
                        if got > tot:
                            alloc.append(('S01', got - tot))
                    else:
                        alloc = [(x['store'], x['q'] * pack) for x in xs if x['q'] > 0]
                    for st, amt in alloc:
                        if amt > 1e-8:
                            arrivals[a1].append({'store': st, 'item': i, 'qty': amt, 'pending': False})
                    results['purchase_cost'] += packs * self.price(i, day)
                    results['ordered_packs'] += packs
                    if day == sc.as_of:
                        results['orders'].append({
                            'supplier_id': supid, 'supplier': self.suppliers[supid]['supplier_name'],
                            'store_id': group, 'ingredient_id': i, 'ingredient': self.items[i]['ingredient_name'],
                            'order_date': day.isoformat(), 'arrival_date': a1.isoformat(), 'next_arrival': a2.isoformat(),
                            'order_qty': packs, 'order_unit': self.items[i]['order_unit'], 'use_qty': round(packs * pack, 1),
                            'unit': self.items[i]['use_unit'], 'amount': round(packs * self.price(i, day)),
                            'allocated': {st: round(sum(a for d2, a in alloc if d2 == st), 1) for st, _ in alloc},
                            'forecast_need': round(sum(x['need'] for x in xs), 1),
                            'usable_stock': round(sum(x['stock'] - x['exp'] for x in xs), 1),
                            'safety_stock': round(sum(x['ss'] for x in xs), 1), 'z': round(xs[0]['z'], 2),
                            'padded': sum(x['padded'] for x in xs),
                            'need_components': [{'store_id': x['store'], 'forecast_shortage_qty': x['short'],
                                'safety_topup_qty': x['safety_topup'], 'pre_round_need_qty': x['gap'],
                                'base_order_qty': x['base_q'], 'pack_rounding_qty': x['rounding_qty'],
                                'minimum_topup_packs': x['padded'], 'minimum_topup_use_qty': x['padded']*x['pack'],
                                'projected_left_qty': x['left']} for x in xs],
                            'reason': ' / '.join(self.reason(x, day, a2) for x in xs if x['q'] > 0) or
                                      ' / '.join(self.reason(x, day, a2) for x in xs)})
                if day == sc.as_of:
                    for x in gl:
                        if x['q'] == 0 and x['need'] > 0:
                            results['no_order'].append({'supplier_id': supid, 'store_id': x['store'], 'ingredient_id': x['item'],
                                                        'ingredient': self.items[x['item']]['ingredient_name'],
                                                        'reason': self.reason(x, day, a2)})

    # ------------------------------------------------------------------ 이동
    def transfers_day(self, sc: Scenario, day: date, lots: dict, fitem: dict, results: dict):
        """개점 전 이동: (1) 오늘 품절 예상분 → 회피 공헌이익, (2) 기한 내 못 쓸 재고 → 회피 폐기원가"""
        shadow = deepcopy(lots)
        route_plans = defaultdict(list)
        arrive_min = 9 * 60 + sc.transfer_minutes
        for i, ir in self.items.items():
            uc = self.unit_cost(i, day)
            z = self.z(i, sc.safety_alpha, sc.as_of)
            off = (day - sc.as_of).days
            st = {}
            for s in self.stores:
                f = [fitem.get((day + timedelta(days=t), s, i), 0.) for t in range(14)]
                protect = f[0] + f[1] + z * self.F.horizon_rmse(self.si[s], self.ii[i], sc.as_of, off, off + 2) * sc.demand_multiplier
                cur = self.count(shadow, (s, i), day)
                # 기한 안에 못 쓸 양: 각 묶음 만료일까지 FEFO로 써도 남는 양
                # 7일 안에 만료되는 묶음, 또는 앞으로 14일 쓸 메뉴가 없는 재고(취급 종료 등)가 대상
                dead = sum(f) <= 1e-9
                rest = 0.0; used = 0.0; rest_span = 99
                for lot in sorted(shadow[(s, i)], key=lambda x: x['expiry']):
                    if lot['expiry'] < day:
                        continue
                    span = (lot['expiry'] - day).days + 1
                    cap = sum(f[:min(span, 14)]) - used
                    use = min(lot['qty'], max(0.0, cap)); used += use
                    if (span <= 7 or dead) and lot['qty'] - use > 1e-6:
                        rest += lot['qty'] - use; rest_span = min(rest_span, span, 14)
                st[s] = dict(f=f, cur=cur, need=max(0.0, f[0] - cur), excess=max(0.0, cur - protect), rest=rest, rest_span=rest_span)
            moves = []
            for recv in sorted(self.stores, key=lambda x: -st[x]['need']):
                for give in self.stores:
                    if give == recv or st[recv]['need'] <= 1e-6:
                        continue
                    take = min(st[recv]['need'], st[give]['excess'])
                    if take > 1e-6:
                        moves.append((give, recv, take, '품절 방지', self.cu(i, sc.as_of)))
                        st[recv]['need'] -= take; st[give]['excess'] -= take
                        # FEFO로 빠지는 물량은 만료가 빠른 묶음부터이므로 '기한 내 못 쓸 양'도 함께 줄어든다
                        st[recv]['cur'] += take; st[give]['cur'] -= take
                        st[give]['rest'] = max(0.0, st[give]['rest'] - take)
            for give in self.stores:
                if st[give]['rest'] <= 1e-6:
                    continue
                for recv in self.stores:
                    if recv == give:
                        continue
                    room = max(0.0, sum(st[recv]['f'][:st[give]['rest_span']]) - st[recv]['cur'])
                    take = min(st[give]['rest'], room)
                    if take > 1e-6:
                        moves.append((give, recv, take, '폐기 방지', uc))
                        st[give]['rest'] -= take; st[recv]['cur'] += take
            for give, recv, take, purpose, unit_value in moves:
                if ir['use_unit'] in ('개', '장', '캔', '매'):
                    take = floor(take + 1e-9)   # 낱개 단위는 정수로만 이동
                open_minutes = min(int(self.stores[give]['open_hour']), int(self.stores[recv]['open_hour'])) * 60
                if arrive_min > open_minutes:
                    continue
                removed = []; remaining = take
                for lot in sorted(shadow[(give, i)], key=lambda x: x['expiry']):
                    if lot['expiry'] < day:
                        continue
                    used = min(remaining, lot['qty'])
                    if used > 1e-8:
                        lot['qty'] -= used; removed.append({'qty': used, 'expiry': lot['expiry'],
                            'receipt_date': lot.get('receipt_date',day), 'lot': lot['lot']}); remaining -= used
                    if remaining <= 1e-8:
                        break
                shadow[(give, i)] = [l for l in shadow[(give, i)] if l['qty'] > 1e-8]
                for line in removed:
                    shadow[(recv, i)].append(line.copy())
                actual = take - remaining
                if actual <= 1e-8:
                    continue
                route_plans[(give, recv)].append({'ingredient_id': i, 'ingredient': ir['ingredient_name'], 'qty': round(actual, 1),
                                                  'unit': ir['use_unit'], 'purpose': purpose,
                                                  'avoided_loss': round(actual * unit_value), 'estimated_food_value': round(actual * uc, 2),
                                                  'expiry': min(x['expiry'] for x in removed).isoformat(), '_lots': removed})
        for (origin, dest), lines in route_plans.items():
            benefit = sum(x['avoided_loss'] for x in lines)
            if benefit + 1e-9 < sc.transfer_cost:
                if day == sc.as_of:
                    results.setdefault('skipped_transfers', []).append({'from_store': origin, 'to_store': dest, 'avoided_loss': round(benefit),
                                                         'trip_cost': sc.transfer_cost, 'items': [{k: v for k, v in x.items() if k != '_lots'} for x in lines]})
                continue
            committed = []
            for line in lines:
                i = line['ingredient_id']
                for move in line['_lots']:
                    remaining = move['qty']
                    for source in lots[(origin, i)]:
                        if source['lot'] == move['lot'] and source['expiry'] == move['expiry']:
                            used = min(remaining, source['qty']); source['qty'] -= used; remaining -= used
                            if remaining <= 1e-8:
                                break
                    if remaining > 1e-5:
                        raise RuntimeError('이동 중복 배정 검증 실패')
                    lots[(dest, i)].append(move.copy())
                lots[(origin, i)] = [l for l in lots[(origin, i)] if l['qty'] > 1e-8]
                committed.append({k: v for k, v in line.items() if k != '_lots'})
            results['trip_count'] += 1
            results['transport_cost'] += sc.transfer_cost
            if day == sc.as_of:
                results['transfers'].append({'from_store': origin, 'to_store': dest, 'depart': '09:00',
                                             'arrive': f'{arrive_min // 60:02d}:{arrive_min % 60:02d}', 'minutes': sc.transfer_minutes,
                                             'trip_cost': sc.transfer_cost, 'items': committed, 'avoided_loss': round(benefit),
                                             'estimated_food_value': round(sum(x['estimated_food_value'] for x in committed))})

    # ------------------------------------------------------------------ 시나리오 시뮬레이션 (예측 수요 기준)
    def simulate(self, sc: Scenario, mode: str, fmenu: dict, fitem: dict, firstlots: dict, firstarrivals: dict) -> dict:
        lots = deepcopy(firstlots); arrivals = deepcopy(firstarrivals)
        result = {'mode': mode, 'orders': [], 'no_order': [], 'transfers': [], 'skipped_transfers': [], 'alerts': [], 'blocked': [],
                  'warnings': [], 'purchase_cost': 0., 'transport_cost': 0., 'waste_cost': 0., 'quality_waste_cost': 0.,
                  'food_used_cost': 0., 'expected_revenue': 0., 'potential_revenue': 0., 'lost_qty': 0.,
                  'trip_count': 0, 'ordered_packs': 0, 'closing_value': 0.}
        order_mode = 'independent' if mode.startswith('independent') else 'pooled'
        day = sc.as_of
        for step in range(sc.horizon_days):
            d = day + timedelta(days=step)
            for (s, i), ll in lots.items():
                valid = []
                for l in ll:
                    if l['expiry'] < d:
                        result['waste_cost'] += l['qty'] * self.unit_cost(i, d)
                    else:
                        valid.append(l)
                lots[(s, i)] = valid
            for shipment in arrivals.pop(d, []):
                i = shipment['item']; s = shipment['store']
                until = d + timedelta(days=int(self.items[i]['shelf_life_days']) - 1)
                lots[(s, i)].append({'qty': shipment['qty'], 'expiry': until, 'receipt_date': d,
                                    'lot': 'committed' if shipment['pending'] else 'recommended'})
            if step == 0:
                self.alerts(sc, d, lots, fitem, result, arrivals=arrivals, fmenu=fmenu)
            if mode in ('independent_transfer', 'shared'):
                self.transfers_day(sc, d, lots, fitem, result)
            self.recommend_orders(sc, order_mode, d, lots, arrivals, fitem, result)
            for s in self.stores:
                available = {i: self.count(lots, (s, i), d) for i in self.items}
                priorities = []
                for m in self.menus:
                    demand = fmenu.get((d, s, m), 0)
                    if not demand:
                        continue
                    priorities.append((self.margin[m], m, demand))
                    result['potential_revenue'] += demand * float(self.menus[m]['virtual_price'])
                for margin, m, demand in sorted(priorities, reverse=True):
                    feasible = demand
                    for i, q in self.bom[m].items():
                        feasible = min(feasible, available[i] / q)
                    sold = max(0, min(demand, feasible))
                    result['expected_revenue'] += sold * float(self.menus[m]['virtual_price'])
                    result['lost_qty'] += demand - sold
                    for i, q in self.bom[m].items():
                        used = self.burn(lots, (s, i), sold * q)
                        available[i] -= used
                        result['food_used_cost'] += used * self.unit_cost(i, d)
                for i, ir in self.items.items():   # 마감 후 냉장 품질 폐기 (기대값)
                    rate = QUALITY_RATE.get(ir['storage'], 0)
                    if rate:
                        q = self.count(lots, (s, i), d) * rate
                        result['quality_waste_cost'] += self.burn(lots, (s, i), q) * self.unit_cost(i, d)
        end = day + timedelta(days=sc.horizon_days)
        for (s, i), ll in lots.items():
            for l in ll:
                if l['expiry'] < end:
                    result['waste_cost'] += l['qty'] * self.unit_cost(i, end)
                else:
                    result['closing_value'] += l['qty'] * self.unit_cost(i, end)
        result['waste_cost'] += result['quality_waste_cost']
        result['contribution_after_waste_and_transport'] = (result['expected_revenue'] - result['food_used_cost'] -
                                                            result['waste_cost'] - result['transport_cost'])
        total = sum(fmenu.get((day + timedelta(days=n), s, m), 0) for n in range(sc.horizon_days) for s in self.stores for m in self.menus)
        result['fill_rate'] = (1 - result['lost_qty'] / max(1e-9, total)) * 100
        for k in ['purchase_cost', 'transport_cost', 'waste_cost', 'quality_waste_cost', 'food_used_cost', 'expected_revenue',
                  'potential_revenue', 'closing_value', 'lost_qty', 'contribution_after_waste_and_transport', 'fill_rate']:
            result[k] = round(result[k], 2)
        return result

    def alerts(self, sc: Scenario, d: date, lots: dict, fitem: dict, result: dict, *, arrivals=None, fmenu=None):
        if fmenu is None:
            fmenu, _ = self.forecasts(sc)
        traces = project_lot_usage(self, d, lots, arrivals or {}, fmenu, horizon=3)
        for s in self.stores:
            for i, ir in self.items.items():
                u = ir['use_unit']
                cur = self.count(lots, (s, i), d)
                want = fitem.get((d, s, i), 0.)
                valid = [l for l in lots[(s, i)] if l['qty'] > 1e-6 and l['expiry'] >= d]
                if want > cur + 1e-6:
                    result['alerts'].append({'type': 'shortage', 'store': s, 'item': i, 'name': ir['ingredient_name'],
                                             'qty': round(want - cur, 1), 'unit': u, 'date': d.isoformat(),
                                             'detail': f'오늘 예상소요 {fmt(want)}{u} > 재고 {fmt(cur)}{u}'})
                soon = sum(l['qty'] for l in valid if l['expiry'] <= d + timedelta(days=2))
                if soon > 1e-5:
                    first = min(l['expiry'] for l in valid)
                    near = [r for r in traces[(s,i)] if r['expiry_within_horizon']]
                    use = sum(r['expected_used_qty'] for r in near)
                    expected_waste = sum(r['expected_expiry_qty'] for r in near)
                    result['alerts'].append({'type': 'expiry', 'store': s, 'item': i, 'name': ir['ingredient_name'],
                                             'qty': round(soon, 1), 'unit': u, 'date': first.isoformat(),
                                             'expiring_qty': soon, 'expected_use_before_expiry_qty': use,
                                             'expected_expiry_qty': expected_waste,
                                             'expected_expiry_cost': expected_waste*self.unit_cost(i,d),
                                             'lots': near, 'projection_basis': 'menu_coupled_committed_only_before_new_orders_or_transfers',
                                             'detail': f'3일 내 기한 임박 {fmt(soon)}{u} · 해당 로트 예상 사용 {fmt(use)}{u} · 예상 폐기 {fmt(expected_waste)}{u} (신규 발주·이동 전)'})
                horizon_need = sum(fitem.get((d + timedelta(days=n), s, i), 0.) for n in range(14))
                if cur > 0 and horizon_need <= 1e-6:
                    result['alerts'].append({'type': 'deadstock', 'store': s, 'item': i, 'name': ir['ingredient_name'],
                                             'qty': round(cur, 1), 'unit': u, 'date': d.isoformat(),
                                             'detail': '이 매장에서 향후 14일 사용할 메뉴가 없음 (취급 종료 등) → 다른 매장 이동 검토'})
                elif valid and horizon_need > 0:
                    days_cover = cur / max(horizon_need / 14, 1e-9)
                    shelf = int(ir['shelf_life_days'])
                    if days_cover > min(shelf, 21):
                        result['alerts'].append({'type': 'overstock', 'store': s, 'item': i, 'name': ir['ingredient_name'],
                                                 'qty': round(cur, 1), 'unit': u, 'date': d.isoformat(),
                                                 'detail': f'현재 재고가 약 {days_cover:.0f}일분 (사용기한 {shelf}일)'})

    # ------------------------------------------------------------------ API 응답
    def plan(self, sc: Scenario) -> dict[str, Any]:
        if sc.store_id not in self.stores:
            raise HTTPException(422, '알 수 없는 매장입니다.')
        if not (date(2026, 7, 1) <= sc.as_of <= date(2026, 10, 1)):
            raise HTTPException(422, '2026-07-01~2026-10-01 기준일만 지원합니다.')
        fmenu, fitem = self.forecasts(sc)
        lots, arrivals, issues = self.initial(sc)
        # One explicit morning book snapshot for displayed quantities, matching simulation receipts.
        display_lots = deepcopy(lots)
        received_today = defaultdict(float)
        for r in arrivals.get(sc.as_of, []):
            key=(r['store'],r['item']);received_today[key]+=r['qty']
            display_lots[key].append({'qty':r['qty'], 'expiry':sc.as_of+timedelta(days=int(self.items[r['item']]['shelf_life_days'])-1),
                                     'receipt_date':sc.as_of, 'lot':'committed'})
        results = {mode: self.simulate(sc, mode, fmenu, fitem, lots, arrivals) for mode in MODE_NAMES}
        # 이동은 회피손실이 운송비보다 클 때만 실행되므로 M0+를 기본 추천으로 사용
        chosen = results['independent_transfer']
        selected = sc.store_id
        firstday = sc.as_of
        ssi = self.si[selected]
        fm = self.F.menu(sc.as_of) * sc.demand_multiplier
        days = [firstday + timedelta(days=k) for k in range(min(7, sc.horizon_days))]
        forecast_days = [{'date': d.isoformat(), 'weekday': DAYS[d.weekday()], 'holiday': self.F.holiday(d),
                          'total': round(float(fm[ssi, :, k].sum()), 1)} for k, d in enumerate(days)]
        forecast_menu = [{'menu_id': m, 'menu': mr['menu_name'], 'price': mr['virtual_price'],
                          'qty': [round(float(fm[ssi, self.mi[m], k]), 1) for k in range(len(days))]}
                         for m, mr in self.menus.items() if any(self.active(selected, m, d) for d in days)]
        forecasts = [{'menu_id': x['menu_id'], 'menu': x['menu'], 'qty': x['qty'][0], 'price': x['price']} for x in forecast_menu]
        ingredients = [{'ingredient_id': i, 'ingredient': r['ingredient_name'], 'unit': r['use_unit'], 'storage': r['storage'],
                        'predicted_today': round(fitem.get((firstday, selected, i), 0), 1),
                        'predicted_7d': round(sum(fitem.get((d, selected, i), 0) for d in days), 1),
                        'opening_stock': round(self.count(lots, (selected,i),firstday),1),
                        'received_today': round(received_today[(selected,i)],1),
                        'current_stock': round(self.count(display_lots, (selected, i), firstday), 1),
                        'inventory_basis': 'after_07_receipts_before_inspection_and_transfers',
                        'expiry_nearest': min((x['expiry'].isoformat() for x in display_lots[(selected, i)] if x['expiry'] >= firstday), default=None),
                        'z': round(self.z(i, sc.safety_alpha, sc.as_of), 2)}
                       for i, r in self.items.items()]
        comparison = [{**{k: v for k, v in res.items() if k in ['mode', 'purchase_cost', 'transport_cost', 'waste_cost', 'quality_waste_cost',
                                                               'expected_revenue', 'lost_qty', 'fill_rate', 'ordered_packs', 'trip_count',
                                                               'closing_value', 'contribution_after_waste_and_transport']},
                       'name': MODE_NAMES[res['mode']], 'assumption': res['mode'] not in COMPLIANT}
                      for res in results.values()]
        meta = self.F.meta[self.F.idx(sc.as_of)]
        hol_list = [f'{d} {n}' for d, n in EXTRA_HOLIDAYS.items()]
        return {'as_of': sc.as_of.isoformat(), 'store_id': selected, 'forecast': forecasts,
                'forecast_days': forecast_days, 'forecast_menu': forecast_menu,
                'ingredients': ingredients, 'comparison': comparison,
                'recommended_mode': chosen['mode'], 'recommended_name': MODE_NAMES[chosen['mode']],
                'safety_alpha': sc.safety_alpha,
                'orders': [r for r in chosen['orders'] if r['store_id'] in ('ALL', selected)],
                'all_orders': chosen['orders'], 'no_order': [r for r in chosen['no_order'] if r['store_id'] == selected],
                'transfers': chosen['transfers'],
                'shared_alternative_transfers': results['independent_transfer']['transfers'],
                'skipped_transfers': results['independent_transfer']['skipped_transfers'],
                'alerts': [r for r in chosen['alerts'] if r['store'] == selected],
                'all_alerts': chosen['alerts'], 'blocked': chosen['blocked'],
                'data_issues': issues[:8],
                'model': {'store_dow_index': {DAYS[w]: round(float(meta['dow'][ssi, w]), 3) for w in range(7)},
                          'holiday_factor': round(float(meta['hol'][ssi]), 3), 'promo_lift': round(float(meta['promo']), 3)},
                'backtest': self.backtest,
                'assumptions': [
                    '기준일 07시 입고 후·실사 및 이동 전 장부재고 기준. 실사조정은 미반영. 전날까지 판매만 예측에 사용',
                    '수요 예측: 메뉴별 EWMA(α=0.1) × 매장 요일지수(최근 8주) × 공휴일 계수 × 행사 배율. 확정 수요(demand_qty−cancel_qty) 기준',
                    f'데이터 기간 밖 공휴일은 직접 추가한 가정: {", ".join(hol_list)}',
                    '행사 배율은 기준일 전에 끝난 행사(S02 7월 세트 할인)에서 측정. 10월에 예정된 행사 정보는 없음',
                    '취급 기간이 9/30에 끝나는 메뉴는 데이터 종료일로 보고 계속 취급으로 해석',
                    '안전재고 = 품목별 z × 다음 입고까지 합계 예측오차(RMSE, 최근 42개 기준일). z는 부족 1단위당 공헌이익과 보유비용의 비율로 정하고 강도 α로 조정',
                    '최소 발주금액 미달 시 급한 품목이 없으면 다음 발주일로 이월, 있으면 사용기한 위험이 낮은 품목을 앞당겨 채움',
                    '매장 간 거리·운송비는 제공되지 않음. 09:00 출발·설정한 분 뒤 도착, 경로별 1회 고정비로 가정',
                    '이동은 회피손실(품절: 공헌이익, 기한 경과: 식자재 원가)이 운송비보다 클 때만 추천',
                    'M1·M2 통합발주는 공급사가 여러 매장 주문 합산·소분을 허용한다는 가정이며 제공 데이터의 발주 규칙과 다름',
                    '화면의 정책 비교는 예측 수요 기준 시나리오이며 실적이 아님. 실제 수요 검증은 백테스트 탭 참고',
                    '냉장 품목 품질 폐기는 1~9월 실적의 기대값(잔량의 일 0.3%)으로 반영',
                    '모든 금액은 가상 가격이며 합성 데이터 결과를 실제 매장 성과로 해석하지 않음',
                ]}
