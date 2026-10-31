"""재고·발주 시뮬레이터 (일 단위 의사결정, 시간대별 판매)
하루 순서: 07시 입고 → 정기발주 판단 → 시간대별 판매(부족 시 품절, 해당 메뉴 당일 판매중단, 긴급발주) → 마감 후 사용기한 폐기·냉장 품질폐기
가정: 매장 간 이동 없음(모든 정책 동일), 실사조정 없음, 냉장 품질폐기는 기대값(잔량의 0.3%/일)으로 결정적 처리"""
import numpy as np, pandas as pd, math
from common import *

WD = ["월","화","수","목","금","토","일"]
QUALITY_RATE = 0.003
TRANSFER = True

class World:
    def __init__(self):
        P = load_panel(); self.P = P
        self.MENUS, self.INGS = P["MENUS"], P["INGS"]
        ing = r("03_ingredients").set_index("ingredient_id"); self.ing = ing
        self.pack = ing.use_qty_per_order_unit.values.astype(float)
        self.shelf = ing.shelf_life_days.values.astype(int)
        self.storage = ing.storage.values; self.supplier = ing.supplier_id.values
        self.moq_units = ing.min_order_qty.values
        sup = r("05_suppliers").set_index("supplier_id")
        self.sup = {s: dict(order_days=set(x.order_days.split(",")), deliv=set(x.delivery_days.split(",")),
                            lead=int(x.lead_time_days), moq=float(x.min_order_amount)) for s,x in sup.iterrows()}
        ph = r("06_ingredient_price_history"); ph["vf"]=pd.to_datetime(ph.valid_from)
        self.price = np.zeros((len(DATES)+10, len(self.INGS)))   # 발주단위당 단가
        for j,iid in enumerate(self.INGS):
            p = ph[ph.ingredient_id==iid].sort_values("vf")
            for x in p.itertuples(): self.price[max(0,(x.vf-DATES[0]).days):, j] = x.unit_price
        self.B = P["B"]; self.mprice = P["menus"].virtual_price.values.astype(float)
        # 시간대별 순수요 [store, menu, day, hour]
        s = r("09_sales"); s["net"]=s.demand_qty-s.cancel_qty; s["di"]=(pd.to_datetime(s.date)-DATES[0]).dt.days
        self.H = np.zeros((3, len(self.MENUS), len(DATES), 24))
        si={x:i for i,x in enumerate(STORES)}; mi={x:i for i,x in enumerate(self.MENUS)}
        g = s.groupby(["store_id","menu_id","di","hour"]).net.sum()
        for (st,m,d,h),v in g.items(): self.H[si[st],mi[m],d,h]=v
        inv = r("10_inventory_daily"); first = inv[inv.date=="2026-01-01"].set_index(["store_id","ingredient_id"])
        self.init = np.array([[first.loc[(st,i)].opening_qty for i in self.INGS] for st in STORES], float)
        self.wd = [WD[d.dayofweek] for d in DATES] + [WD[(DATES[-1]+pd.Timedelta(days=k)).dayofweek] for k in range(1,11)]
        # 메뉴 공헌이익 = 판매가 − BOM 원가(연평균 단가)
        unit_cost = self.price[:len(DATES)].mean(0)/self.pack
        self.margin = self.mprice - self.B @ unit_cost
        self.unit_cost_t = self.price/self.pack[None,:]

    def arrival(self, sid, d):
        s=self.sup[sid]; t=d+s["lead"]
        while self.wd[t] not in s["deliv"]: t+=1
        return t
    def next_order_day(self, sid, d):
        for k in range(1,8):
            if self.wd[d+k] in self.sup[sid]["order_days"]: return d+k

def simulate(W, policy, start=0, end=None, verbose=False):
    T = len(DATES) if end is None else end
    S, I = 3, len(W.INGS)
    lots = [[[] for _ in range(I)] for _ in range(S)]     # [expiry_day, qty]
    for s in range(S):
        for i in range(I):
            if W.init[s,i]>0: lots[s][i].append([-1 + W.shelf[i] - 1, W.init[s,i]])
    pipe = [[{} for _ in range(I)] for _ in range(S)]       # arrival_day -> qty(use)
    cons = np.zeros((S,I,T)); log = dict(exp_waste=np.zeros((S,I,T)), q_waste=np.zeros((S,I,T)),
        stockout=np.zeros((S,I,T),bool), lost_rev=np.zeros((S,T)), lost_margin=np.zeros((S,T)), lost_qty=np.zeros((S,T)),
        purchase=np.zeros((S,T)), emerg=np.zeros((S,I,T)), close_val=np.zeros((S,T)), close_qty=np.zeros((S,I,T)), pos=0, orders=[], transfers=[])
    policy.attach(W)
    for d in range(start, T):
        for s in range(S):
            for i in range(I):
                q = pipe[s][i].pop(d, 0)
                if q>0: lots[s][i].append([d + W.shelf[i] - 1, q]); lots[s][i].sort()
        # 정기발주
        for s in range(S):
            for sid in W.sup:
                if W.wd[d] not in W.sup[sid]["order_days"]: continue
                items = np.where(W.supplier==sid)[0]
                q = policy.order(d, s, sid, items, lots[s], pipe[s], cons[s,:, :d])
                arr = W.arrival(sid, d); amt=0
                for i,u in q.items():
                    if u>0:
                        pipe[s][i][arr] = pipe[s][i].get(arr,0) + u*W.pack[i]; amt += u*W.price[d,i]
                        log["orders"].append((d,s,sid,i,u))
                log["purchase"][s,d]+=amt; log["pos"] += amt>0
        # 판매 (시간대 바깥 루프 → 매장 간 이동 가능)
        blocked=[np.zeros(len(W.MENUS),bool) for _ in range(S)]; out_today=[set() for _ in range(S)]
        lost_acc=[np.zeros(len(W.MENUS)) for _ in range(S)]
        def avail(s,i): return sum(l[1] for l in lots[s][i] if l[0]>=d)
        for h in range(24):
            for s in range(S):
                dem = W.H[s,:,d,h]
                if dem.sum()==0: continue
                lost_acc[s] += dem*blocked[s]; dem = dem*(~blocked[s])
                need = dem @ W.B
                av = np.array([avail(s,i) for i in range(I)])
                if TRANSFER:
                    for i in np.where(need>av+1e-9)[0]:
                        rest = (W.H[s,:,d,h:].sum(1)*(~blocked[s])) @ W.B[:,i]
                        deficit = math.ceil(rest - av[i])
                        best=None
                        for o in range(S):
                            if o==s: continue
                            ro = (W.H[o,:,d,h:].sum(1)*(~blocked[o])) @ W.B[:,i]
                            a7 = cons[o,i,max(0,d-7):d].mean() if d>0 else 0
                            sur = avail(o,i) - ro - 2*a7
                            if sur>0 and (best is None or sur>best[1]): best=(o,sur)
                        if best:
                            o,sur=best; q=min(deficit, math.floor(sur))
                            if q>0:
                                rem=q
                                for l in lots[o][i]:
                                    if l[0]<d or l[1]<=0: continue
                                    t=min(l[1],rem); l[1]-=t; rem-=t
                                    lots[s][i].append([l[0],t])
                                    if rem<=0: break
                                lots[s][i].sort(); log["transfers"].append((d,h,o,s,i,q)); av[i]=avail(s,i)
                ratio = np.where(need>0, np.minimum(1, av/np.maximum(need,1e-9)), 1)
                short = ratio < 1 - 1e-12
                fill = np.ones(len(W.MENUS))
                if short.any():
                    for m in range(len(W.MENUS)):
                        used = W.B[m]>0
                        fill[m] = ratio[used].min() if used.any() else 1
                sold = dem*fill; lost_acc[s] += dem - sold
                use = sold @ W.B
                for i in np.where(use>0)[0]:
                    rem = use[i]
                    for l in lots[s][i]:
                        if l[0] < d or l[1]<=0: continue
                        t = min(l[1], rem); l[1]-=t; rem-=t
                        if rem<=1e-9: break
                    cons[s,i,d]+=use[i]
                for i in np.where(short)[0]:
                    blocked[s] |= W.B[:,i]>0
                    if i not in out_today[s]:
                        out_today[s].add(i); log["stockout"][s,i,d]=True
                        u = policy.emergency(d, s, i, cons[s,:, :d])
                        pipe[s][i][d+1] = pipe[s][i].get(d+1,0)+u*W.pack[i]
                        log["purchase"][s,d]+=u*W.price[d,i]; log["emerg"][s,i,d]=u
        for s in range(S):
            lost=lost_acc[s]
            log["lost_rev"][s,d] += lost @ W.mprice; log["lost_margin"][s,d] += lost @ W.margin; log["lost_qty"][s,d]+=lost.sum()
        for s in range(S):
            # 마감: 사용기한 폐기 → 품질 폐기
            for i in range(I):
                keep=[]
                for l in lots[s][i]:
                    if l[0] <= d: log["exp_waste"][s,i,d]+=l[1]
                    elif l[1]>1e-9: keep.append(l)
                lots[s][i]=keep
                if W.storage[i]=="냉장":
                    tot=sum(l[1] for l in keep); q=tot*QUALITY_RATE; log["q_waste"][s,i,d]=q
                    for l in keep:
                        t=min(l[1],q); l[1]-=t; q-=t
                        if q<=0: break
                log["close_qty"][s,i,d]=sum(l[1] for l in lots[s][i])
            log["close_val"][s,d]=(log["close_qty"][s,:,d]*W.unit_cost_t[d]).sum()
    log["cons"]=cons; return log

def kpi(W, log, t0, t1):
    a=(DATES.get_loc(pd.Timestamp(t0))); b=DATES.get_loc(pd.Timestamp(t1))+1
    uc=W.unit_cost_t[a:b].T[None,:,:]
    ew=(log["exp_waste"][:,:,a:b]*uc).sum(); qw=(log["q_waste"][:,:,a:b]*uc).sum()
    lm=log["lost_margin"][:,a:b].sum()
    return {"품절(매장×식자재×일)":int(log["stockout"][:,:,a:b].sum()), "판매손실(개)":round(log["lost_qty"][:,a:b].sum()),
            "판매손실 매출":round(log["lost_rev"][:,a:b].sum()), "판매손실 공헌이익":round(lm),
            "기한폐기":round(ew), "품질폐기":round(qw), "폐기합계":round(ew+qw),
            "총손실(폐기+공헌이익손실)":round(ew+qw+lm),
            "평균재고금액(3매장)":round(log["close_val"][:,a:b].sum(0).mean()),
            "구매금액":round(log["purchase"][:,a:b].sum()),
            "긴급발주":int((log["emerg"][:,:,a:b]>0).sum()), "매장간이동":sum(1 for x in log["transfers"] if a<=x[0]<b)}
