"""수요 예측: 메뉴별 EWMA 수준 × 매장 요일지수 × 공휴일 계수 × 행사 배율.

- 기준일(as_of) 아침에 전날까지의 판매만 사용한다. 모든 기준일의 예측을 서버 시작 시 미리 계산한다.
- 예측 대상은 품절이 없었다면 팔렸을 확정 수요(demand_qty - cancel_qty)이고, BOM으로 식자재 소요량으로 바꾼다.
- 6~9월 롤링 백테스트에서 7일 평균, 동일요일 평균, 50:50 혼합, LightGBM보다 식자재 단위 오차가 낮았던 구성이다.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

# 데이터 기간(~9/30) 밖의 공휴일. 제공 데이터가 아니라 직접 추가한 가정이다.
EXTRA_HOLIDAYS = {
    '2026-10-03': '개천절',
    '2026-10-05': '대체공휴일(개천절)',
    '2026-10-09': '한글날',
}


class Forecaster:
    K = 24            # 기준일부터 예측하는 일수 (최대 기간 14일 + 발주 계산 여유)
    ALPHA = 0.1       # EWMA 평활 계수
    WEEKS = 8         # 요일지수 계산 기간(주)
    ERR_WINDOW = 42   # 예측오차 통계에 쓰는 과거 기준일 수

    def __init__(self, data: dict[str, pd.DataFrame]):
        self.stores = data['01_stores'].store_id.tolist()
        self.menus = data['02_menus'].menu_id.tolist()
        self.items = data['03_ingredients'].ingredient_id.tolist()
        s = data['09_sales']
        self.start = date.fromisoformat(s.date.min())
        self.last = date.fromisoformat(s.date.max())
        T = (self.last - self.start).days + 1
        self.T = T
        TE = T + self.K + 8
        si = {x: i for i, x in enumerate(self.stores)}
        mi = {x: i for i, x in enumerate(self.menus)}
        S, M = len(self.stores), len(self.menus)

        g = s.assign(net=s.demand_qty - s.cancel_qty).groupby(['store_id', 'menu_id', 'date']).net.sum()
        Y = np.zeros((S, M, T))
        for (st, m, d), v in g.items():
            Y[si[st], mi[m], (date.fromisoformat(d) - self.start).days] = v
        self.Y = Y

        A = np.zeros((S, M, TE), bool)
        for r in data['15_menu_availability'].itertuples(index=False):
            if r.status != '취급' or not isinstance(r.start_date, str):
                continue
            a = (date.fromisoformat(r.start_date) - self.start).days
            b = (date.fromisoformat(r.end_date) - self.start).days
            # 데이터 마지막 날에 끝나는 취급 기간은 '계속 취급'으로 해석
            b = TE - 1 if b >= T - 1 else b
            A[si[r.store_id], mi[r.menu_id], max(a, 0):b + 1] = True
        self.A = A

        self.hol_name = {}
        cal = data['07_calendar']
        for r in cal.itertuples(index=False):
            if int(r.is_holiday) == 1:
                self.hol_name[r.date] = r.holiday_name
        self.hol_name.update(EXTRA_HOLIDAYS)
        self.hol = np.array([(self.start + timedelta(days=t)).isoformat() in self.hol_name for t in range(TE)])
        self.wd = np.array([(self.start + timedelta(days=t)).weekday() for t in range(TE)])

        self.promos = []
        P = np.zeros((S, M, TE), bool)
        for r in data['08_promotions'].itertuples(index=False):
            a = (date.fromisoformat(r.start_date) - self.start).days
            b = (date.fromisoformat(r.end_date) - self.start).days
            ms = [mi[x] for x in str(r.target_menu).split(',') if x in mi]
            for m in ms:
                P[si[r.store_id], m, max(a, 0):b + 1] = True
            self.promos.append(dict(id=r.promo_id, s=si[r.store_id], ms=ms, a=a, b=b))
        self.P = P

        bom = data['04_bom']
        B = np.zeros((M, len(self.items)))
        ii = {x: i for i, x in enumerate(self.items)}
        for r in bom.itertuples(index=False):
            B[mi[r.menu_id], ii[r.ingredient_id]] = float(r.qty_per_menu)
        self.B = B
        self.act_item = np.einsum('smt,mi->sit', Y, B)   # 실제(무제약) 식자재 소요

        self._precompute()

    # ------------------------------------------------------------------ 계수
    def _dow_index(self, L: int) -> np.ndarray:
        """[store, weekday] 최근 8주 매장 합계 기준 (공휴일 제외)"""
        tot = self.Y.sum(1)
        idx = [t for t in range(max(0, L - 7 * self.WEEKS + 1), L + 1) if not self.hol[t]]
        out = np.ones((tot.shape[0], 7))
        if len(idx) < 14:
            return out
        base = tot[:, idx].mean(1)
        for w in range(7):
            same = [t for t in idx if self.wd[t] == w]
            if len(same) >= 2:
                out[:, w] = tot[:, same].mean(1) / np.maximum(base, 1e-9)
        return out

    def _holiday_factor(self, L: int) -> np.ndarray:
        tot = self.Y.sum(1)
        rs = []
        for t in range(28, L + 1):
            if self.hol[t]:
                base = [t - 7 * j for j in range(1, 5) if not self.hol[t - 7 * j]]
                if base:
                    rs.append(tot[:, t] / np.maximum(tot[:, base].mean(1), 1e-9))
        return np.mean(rs, 0) if rs else np.ones(tot.shape[0])

    def _promo_lift(self, L: int) -> dict:
        """L 이전에 끝난 행사에서 측정한 대상 메뉴 수요 배율. 이력이 없으면 1."""
        lifts = []
        for p in self.promos:
            if p['b'] >= L or p['a'] < 28:
                continue
            during = self.Y[p['s'], p['ms'], p['a']:p['b'] + 1].mean()
            before = self.Y[p['s'], p['ms'], p['a'] - 28:p['a']].mean()
            if before > 0:
                lifts.append(float(np.clip(during / before, 1.0, 3.0)))
        return {'lift': float(np.mean(lifts)) if lifts else 1.0, 'n': len(lifts)}

    # ------------------------------------------------------------------ 사전계산
    def _precompute(self):
        S, M, T, K = self.Y.shape[0], self.Y.shape[1], self.T, self.K
        self.fc_menu = np.zeros((T + 1, S, M, K))
        self.meta = {}
        for d in range(1, T + 1):           # d = 기준일 인덱스, 마지막 관측일 L = d-1
            L = d - 1
            di = self._dow_index(L)
            hf = self._holiday_factor(L)
            pl = self._promo_lift(L)['lift']
            lvl = np.full((S, M), np.nan)
            for t in range(max(0, L - 59), L + 1):
                fac = di[:, self.wd[t]] * (hf if self.hol[t] else 1.0)
                x = self.Y[:, :, t] / fac[:, None]
                x = np.where(self.P[:, :, t], x / pl, x)
                av = self.A[:, :, t]
                init = av & np.isnan(lvl)
                lvl = np.where(init, x, lvl)
                upd = av & ~init
                lvl = np.where(upd, self.ALPHA * x + (1 - self.ALPHA) * lvl, lvl)
            lvl = np.nan_to_num(lvl)
            for k in range(K):
                t = d + k
                fac = di[:, self.wd[t]] * (hf if self.hol[t] else 1.0)
                f = lvl * fac[:, None]
                f = np.where(self.P[:, :, t], f * pl, f)
                self.fc_menu[d, :, :, k] = f * self.A[:, :, t]
            self.meta[d] = dict(dow=di, hol=hf, promo=pl)
        self.fc_item = np.einsum('dsmk,mi->dsik', self.fc_menu, self.B)

    # ------------------------------------------------------------------ 조회
    def idx(self, day: date) -> int:
        return (day - self.start).days

    def menu(self, as_of: date) -> np.ndarray:
        return self.fc_menu[self.idx(as_of)]

    def item(self, as_of: date) -> np.ndarray:
        return self.fc_item[self.idx(as_of)]

    def horizon_rmse(self, s: int, i: int, as_of: date, off: int, H: int) -> float:
        """과거 기준일들에서 [off, H) 구간 합계 예측의 RMSE. 기준일 전에 실적이 확정된 구간만 사용."""
        d = self.idx(as_of)
        errs = []
        for o in range(max(1, d - self.ERR_WINDOW), d):
            if o + H > d:          # 실적이 아직 없는 구간은 쓰지 않음
                break
            p = self.fc_item[o, s, i, off:H].sum()
            y = self.act_item[s, i, o + off:o + H].sum()
            errs.append(p - y)
        if len(errs) < 5:
            return 0.5 * float(self.fc_item[d, s, i, off:H].sum())
        return float(np.sqrt(np.mean(np.square(errs))))

    def holiday(self, day: date) -> str:
        return self.hol_name.get(day.isoformat(), '')
