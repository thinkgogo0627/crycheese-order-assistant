"""통합 엔진의 발주 로직을 검증된 재고 시뮬레이터(실제 시간대별 수요, 품절·긴급발주·매장간 이동·품질폐기)로 백테스트"""
import sys, importlib, pickle, json, time, copy, numpy as np, pandas as pd
from datetime import date, timedelta
from collections import defaultdict
import os
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
from sim import World, simulate, kpi, DATES, STORES
from policies import Baseline

def load_engine(root, sales=None):
    for k in [k for k in sys.modules if k == "app" or k.startswith("app.")]: del sys.modules[k]
    sys.path.insert(0, root)
    eng = importlib.import_module("app.engine")
    sys.path.remove(root)
    from common import D
    names = ["01_stores","02_menus","03_ingredients","04_bom","05_suppliers","06_ingredient_price_history","07_calendar","08_promotions","09_sales","10_inventory_daily","11_purchase_orders","12_receipts","13_waste","14_transfers","15_menu_availability","16_inventory_lots_daily","17_stockouts"]
    data = {n: pd.read_csv(f"{D}/{n}.csv", encoding="utf-8-sig") for n in names}
    if sales is not None: data["09_sales"] = sales
    return eng, eng.Engine(data)

class EnginePolicy(Baseline):
    def __init__(self, eng, E, name, mode="new", **sc):
        self.eng, self.E, self.name, self.mode, self.sc = eng, E, name, mode, sc; self.cache = {}; self.blocked = 0
    def order(self, d, s, sid, items, lots, pipe, hist):
        W, E = self.W, self.E; day = (DATES[0] + pd.Timedelta(days=d)).date(); st = STORES[s]
        sc = self.eng.Scenario(as_of=day, store_id=st, horizon_days=7, **self.sc)
        if d not in self.cache: self.cache = {d: E.forecasts(sc)}
        fmenu, fitem = self.cache[d]
        L = defaultdict(list)
        for i in range(len(W.INGS)):
            for e, q in lots[i]:
                if q > 0: L[(st, W.INGS[i])].append({"qty": q, "expiry": (DATES[0] + pd.Timedelta(days=int(e))).date(), "lot": "x"})
        arr = defaultdict(list)
        for i in range(len(W.INGS)):
            for t, q in pipe[i].items():
                if t > d: arr[(DATES[0] + pd.Timedelta(days=int(t))).date()].append({"store": st, "item": W.INGS[i], "qty": q, "pending": True})
        res = {"orders": [], "no_order": [], "blocked": [], "purchase_cost": 0., "ordered_packs": 0}
        sup_save, st_save = E.suppliers, E.stores
        E.suppliers = {sid: sup_save[sid]}; E.stores = {st: st_save[st]}
        try: E.recommend_orders(sc, "independent", day, L, arr, fitem, res)
        finally: E.suppliers, E.stores = sup_save, st_save
        self.blocked += sum(1 for b in res["blocked"] if b.get("action", "보류") != "채움")
        return {W.INGS.index(o["ingredient_id"]): int(o["order_qty"]) for o in res["orders"] if o["store_id"] == st}

def run_all(W, pols, periods):
    rows = []
    for p in pols:
        t = time.time(); log = simulate(W, p)
        for a, b, lab in periods:
            rows.append(dict(정책=p.name, 기간=lab, **kpi(W, log, a, b)))
        print(f"{p.name}: {time.time()-t:.0f}s", flush=True)
    return rows

if __name__ == "__main__":
    W = World()
    new_eng, NE = load_engine(ROOT)
    periods = [("2026-02-01","2026-09-30","2~9월"), ("2026-07-01","2026-09-30","7~9월")]
    pols = [Baseline()]
    for a in [1.2, 1.4, 1.6]:
        pols.append(EnginePolicy(new_eng, NE, f"통합 엔진 α={a}", safety_alpha=a))
    rows = run_all(W, pols, periods)
    R = pd.DataFrame(rows); R.to_csv(os.path.join(HERE, "bt_main.csv"), index=False, encoding="utf-8-sig")
    pd.set_option("display.width", 300); pd.set_option("display.max_columns", 30)
    print(R.to_string())
