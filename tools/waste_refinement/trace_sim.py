"""Team simulator instrumented with lot provenance and causal forecast transfers.

The sales/quality/order chronology matches tools/backtest/sim.py. Oracle mode
exists only to reconcile old reported numbers; experiments use forecast mode.
"""
import numpy as np, math
from sim import World, kpi, DATES, STORES, QUALITY_RATE

def simulate(W, policy, audit, start=0, end=None, verbose=False):
    T = len(DATES) if end is None else end
    S, I = 3, len(W.INGS)
    lots = [[[] for _ in range(I)] for _ in range(S)]     # [expiry_day, qty]
    for s in range(S):
        for i in range(I):
            if W.init[s,i]>0: lots[s][i].append(audit.initial(s,i,int(W.shelf[i])-2,W.init[s,i]))
    pipe = [[{} for _ in range(I)] for _ in range(S)]       # arrival_day -> qty(use)
    cons = np.zeros((S,I,T)); log = dict(exp_waste=np.zeros((S,I,T)), q_waste=np.zeros((S,I,T)),
        stockout=np.zeros((S,I,T),bool), lost_rev=np.zeros((S,T)), lost_margin=np.zeros((S,T)), lost_qty=np.zeros((S,T)),
        purchase=np.zeros((S,T)), emerg=np.zeros((S,I,T)), close_val=np.zeros((S,T)), close_qty=np.zeros((S,I,T)), pos=0, orders=[], transfers=[])
    policy.attach(W)
    log['lost_menu']=np.zeros((S,len(W.MENUS),T))
    for d in range(start, T):
        for s in range(S):
            for i in range(I):
                q = pipe[s][i].pop(d, 0)
                if q>0: lots[s][i].extend(audit.receive(d,s,i,q)); lots[s][i].sort()
        audit.before_day(d,lots,pipe,log)
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
                        audit.queue(d,s,i,u,arr,policy)
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
                if audit.transfer_mode != 'none':
                    for i in np.where(need>av+1e-9)[0]:
                        rest = (audit.remaining(d,h,s,observed=dem)*(~blocked[s])) @ W.B[:,i]
                        deficit = math.ceil(rest - av[i])
                        best=None
                        for o in range(S):
                            if o==s: continue
                            ro = (audit.remaining(d,h,o)*(~blocked[o])) @ W.B[:,i]
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
                                    lots[s][i].append(audit.move(l,t,d,h,o,s,i))
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
                        audit.consume(l,t,d,s,i,"used")
                        if rem<=1e-9: break
                    cons[s,i,d]+=use[i]
                for i in np.where(short)[0]:
                    blocked[s] |= W.B[:,i]>0
                    if i not in out_today[s]:
                        out_today[s].add(i); log["stockout"][s,i,d]=True
                        u = policy.emergency(d, s, i, cons[s,:, :d])
                        pipe[s][i][d+1] = pipe[s][i].get(d+1,0)+u*W.pack[i]
                        log["purchase"][s,d]+=u*W.price[d,i]; log["emerg"][s,i,d]=u
                        audit.queue(d,s,i,u,d+1,policy,kind="emergency")
        for s in range(S):
            lost=lost_acc[s]
            log['lost_menu'][s,:,d]=lost
            log["lost_rev"][s,d] += lost @ W.mprice; log["lost_margin"][s,d] += lost @ W.margin; log["lost_qty"][s,d]+=lost.sum()
        for s in range(S):
            # 마감: 사용기한 폐기 → 품질 폐기
            for i in range(I):
                keep=[]
                for l in lots[s][i]:
                    if l[0] <= d:
                        log["exp_waste"][s,i,d]+=l[1]
                        audit.consume(l,l[1],d,s,i,"expired")
                    elif l[1]>1e-9: keep.append(l)
                lots[s][i]=keep
                if W.storage[i]=="냉장":
                    tot=sum(l[1] for l in keep); q=tot*QUALITY_RATE; log["q_waste"][s,i,d]=q
                    for l in keep:
                        t=min(l[1],q); l[1]-=t; q-=t
                        audit.consume(l,t,d,s,i,"quality")
                        if q<=0: break
                log["close_qty"][s,i,d]=sum(l[1] for l in lots[s][i])
            log["close_val"][s,d]=(log["close_qty"][s,:,d]*W.unit_cost_t[d]).sum()
    audit.finish(lots,pipe)
    log["cons"]=cons; return log
