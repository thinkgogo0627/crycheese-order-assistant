import pandas as pd, numpy as np
import os
D = os.environ.get("CRY_DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "data", "raw"))
r = lambda n: pd.read_csv(f"{D}/{n}.csv", encoding="utf-8-sig")
STORES = ["S01","S02","S03"]
DATES = pd.date_range("2026-01-01","2026-09-30")
END = pd.Timestamp("2026-09-30")

def load_panel():
    s = r("09_sales"); menus = r("02_menus"); ing = r("03_ingredients"); bom = r("04_bom")
    MENUS = menus.menu_id.tolist(); INGS = ing.ingredient_id.tolist()
    s["net"] = s.demand_qty - s.cancel_qty
    s["d"] = pd.to_datetime(s.date)
    g = s.groupby(["store_id","menu_id","d"]).net.sum()
    Y = np.zeros((3, len(MENUS), len(DATES)))
    si = {x:i for i,x in enumerate(STORES)}; mi = {x:i for i,x in enumerate(MENUS)}; di = {x:i for i,x in enumerate(DATES)}
    for (st,m,d),v in g.items(): Y[si[st],mi[m],di[d]] = v
    av = r("15_menu_availability"); A = np.zeros_like(Y, dtype=bool)
    for x in av[av.status=="취급"].itertuples():
        a, b = pd.Timestamp(x.start_date), pd.Timestamp(x.end_date)
        A[si[x.store_id], mi[x.menu_id], (DATES>=a)&(DATES<=b)] = True
    B = np.zeros((len(MENUS), len(INGS)))
    ii = {x:i for i,x in enumerate(INGS)}
    for x in bom.itertuples(): B[mi[x.menu_id], ii[x.ingredient_id]] = x.qty_per_menu
    cal = r("07_calendar"); hol = cal.is_holiday.values.astype(bool)
    promo = np.zeros_like(Y, dtype=bool)
    for p in r("08_promotions").itertuples():
        for m in p.target_menu.split(","):
            promo[si[p.store_id], mi[m], (DATES>=p.start_date)&(DATES<=p.end_date)] = True
    return dict(Y=Y, A=A, B=B, MENUS=MENUS, INGS=INGS, hol=hol, promo=promo, ing=ing, menus=menus)
