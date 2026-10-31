"""Read-only, menu-coupled FEFO projection of the lots present at decision time.

The input snapshot already includes today's receipts. Only committed future
receipts are added. No hypothetical later orders, moves or quality shocks.
"""
from copy import deepcopy
from collections import defaultdict
from datetime import timedelta


def project_lot_usage(engine, day, lots, arrivals, fmenu, horizon=3):
    stock=defaultdict(list); originals={}; usage={}; expiry={}; daily={}
    for (s,i), rows in lots.items():
        for n,row in enumerate(rows):
            if row['qty']<=0 or row['expiry']<day:continue
            key=(s,i,n)
            r=deepcopy(row);r['_key']=key
            stock[s,i].append(r);originals[key]=deepcopy(row)
            usage[key]=expiry[key]=0.;daily[key]=[]
    for h in range(horizon):
        d=day+timedelta(days=h)
        if h:  # the snapshot is already after07:00 on day0
            for n,r in enumerate(arrivals.get(d,[])):
                i=r['item'];s=r['store']
                stock[s,i].append(dict(qty=r['qty'],expiry=d+timedelta(days=int(engine.items[i]['shelf_life_days'])-1),
                    receipt_date=d,lot=f'planned:{d}:{n}',_key=None))
        opening={key:0. for key in originals};used={key:0. for key in originals};waste={key:0. for key in originals}
        for rows in stock.values():
            for r in rows:
                if r['_key'] is not None:opening[r['_key']]+=r['qty']
        for s in engine.stores:
            for _,m in sorted(((engine.margin[m],m) for m in engine.menus),reverse=True):
                wanted=fmenu.get((d,s,m),0.)
                if wanted<=0:continue
                recipe=engine.bom[m]
                feasible=min([wanted]+[sum(r['qty'] for r in stock[s,i] if r['expiry']>=d)/q for i,q in recipe.items()])
                for i,q in recipe.items():
                    need=feasible*q
                    for r in sorted(stock[s,i],key=lambda x:(x['expiry'],x.get('receipt_date',day),x['lot'])):
                        if r['expiry']<d:continue
                        take=min(need,r['qty']);r['qty']-=take;need-=take
                        if r['_key'] is not None:used[r['_key']]+=take
                        if need<=1e-8:break
        closing={key:0. for key in originals}
        for key,rows in stock.items():
            kept=[]
            for r in rows:
                if r['expiry']==d:
                    if r['_key'] is not None:waste[r['_key']]+=r['qty']
                    r['qty']=0.
                if r['_key'] is not None:closing[r['_key']]+=r['qty']
                if r['qty']>1e-8:kept.append(r)
            stock[key]=kept
        for key in originals:
            usage[key]+=used[key];expiry[key]+=waste[key]
            if opening[key]>1e-8:
                daily[key].append(dict(date=d.isoformat(),opening_qty=opening[key],expected_used_qty=used[key],
                    expected_expiry_qty=waste[key],closing_qty=closing[key]))
    output=defaultdict(list)
    for (s,i,n),r in originals.items():
        key=(s,i,n)
        output[s,i].append(dict(lot_id=r['lot'],receipt_date=str(r.get('receipt_date','unknown')),
            last_use_date=r['expiry'].isoformat(),current_qty=r['qty'],expected_used_qty=usage[key],
            expected_expiry_qty=expiry[key],remaining_after_horizon=max(0.,r['qty']-usage[key]-expiry[key]),
            expiry_within_horizon=r['expiry']<day+timedelta(days=horizon),daily=daily[key]))
    return output
