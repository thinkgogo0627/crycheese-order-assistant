import sys, copy, numpy as np, pandas as pd, time
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bt_merged import *
W0 = World()
rows = []
for seed in range(5):
    rng = np.random.default_rng(seed)
    W = copy.copy(W0); W.H = rng.poisson(W0.H).astype(float)
    idx = np.argwhere(W.H > 0)
    sales = pd.DataFrame({"date": [str(DATES[d].date()) for d in idx[:,2]], "hour": idx[:,3], "store_id": [STORES[s] for s in idx[:,0]],
                          "menu_id": [W.MENUS[m] for m in idx[:,1]], "channel": "매장", "demand_qty": W.H[tuple(idx.T)].astype(int),
                          "qty": W.H[tuple(idx.T)].astype(int), "cancel_qty": 0, "lost_qty": 0, "sales_amount": 0, "promo_flag": 0})
    ne, NE = load_engine(ROOT, sales)
    pols = [Baseline()] + [EnginePolicy(ne, NE, f"통합 엔진 α={a}", safety_alpha=a) for a in [1.2, 1.4, 1.6, 1.8]]
    for p in pols:
        log = simulate(W, p); k = kpi(W, log, "2026-02-01", "2026-09-30")
        rows.append(dict(seed=seed, 정책=p.name, **k))
        print(seed, p.name, k["총손실(폐기+공헌이익손실)"], k["품절(매장×식자재×일)"], k["폐기합계"], k["평균재고금액(3매장)"], flush=True)
R = pd.DataFrame(rows); R.to_csv(os.path.join(HERE, "bt_robust.csv"), index=False, encoding="utf-8-sig")
g = R.groupby("정책")[["총손실(폐기+공헌이익손실)","품절(매장×식자재×일)","판매손실 공헌이익","폐기합계","평균재고금액(3매장)","구매금액"]].mean().round()
print(g.to_string())
base = R[R.정책=="기존 정책"].set_index("seed")["총손실(폐기+공헌이익손실)"]
for n in R.정책.unique():
    x = R[R.정책==n].set_index("seed")["총손실(폐기+공헌이익손실)"]; print(n, ((x/base-1)*100).round(1).tolist())
