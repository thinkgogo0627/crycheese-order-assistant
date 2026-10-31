"""Traceable local experiment; no raw data or lot exports belong in Git.

Run from repository root:
  python tools/waste_refinement/study.py --output /path/to/private/output
"""
import argparse, json, sys, math
from pathlib import Path
from collections import defaultdict
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tools/backtest'))
from app import engine as eng
from run_backtest import EnginePolicy
from sim import simulate as original_simulate, kpi, World
from common import DATES, STORES, D
from trace_sim import simulate

FOCUS={'I009','I017','I020'}


def projection(lots, pending, demand, day, shelf, addition=None):
    """Independent ingredient guard. Evaluation itself remains menu-coupled."""
    rows=[[int(l[0]),float(l[1]),getattr(l,'batch',None)] for l in lots]
    if addition:rows.append(list(addition))
    expired=defaultdict(float);short=[]
    for h,need in enumerate(demand):
        d=day+h
        if h and pending.get(d,0)>0:rows.append([d+shelf-1,pending[d],None])
        rows.sort(key=lambda x:x[0])
        for r in rows:
            if r[0]<d:continue
            take=min(need,r[1]);r[1]-=take;need-=take
        short.append(max(0.,need))
        keep=[]
        for r in rows:
            if r[0]<=d:expired[r[2]]+=r[1]
            elif r[1]>1e-8:keep.append(r)
        rows=keep
    return np.array(short),dict(expired)


class DiagnosticPolicy(EnginePolicy):
    def __init__(self,E,variant='baseline'):
        super().__init__(eng,E,'diagnostic_'+variant,safety_alpha=1.6)
        self.variant=variant;self.info={};self.decisions=[]
        self.target_items={variant.split('_',1)[1]} if variant.startswith('transfer_I') else FOCUS
        self.last_lines={};original=E.line_need
        def traced(*args,**kwargs):
            r=original(*args,**kwargs)
            self.last_lines[r['store'],r['item']]=dict(r)
            return r
        E.line_need=traced

    def ensure_forecast(self,d):
        if d not in self.cache:
            self.cache={d:self.E.forecasts(eng.Scenario(as_of=DATES[d].date(),safety_alpha=1.6))}
        return self.cache[d]

    def demand(self,d,s,i,n=14,mult=1.):
        _,fi=self.ensure_forecast(d)
        return np.array([fi.get(((DATES[d]+np.timedelta64(h,'D')).date(),STORES[s],self.W.INGS[i]),0.)*mult for h in range(n)])

    def order(self,d,s,sid,items,lots,pipe,cons_hist):
        out=super().order(d,s,sid,items,lots,pipe,cons_hist)
        W=self.W;arrival=W.arrival(sid,d);next_arrival=W.arrival(sid,W.next_order_day(sid,d))
        for i,q in out.items():
            ln=self.last_lines[STORES[s],W.INGS[i]]
            base=ln['q'];baseuse=base*W.pack[i]
            shortage=min(baseuse,ln['short']);safety=min(max(0.,baseuse-shortage),ln['safety_topup'])
            self.info[d,s,i]=dict(order_day=d,arrival_day=arrival,store=STORES[s],item=W.INGS[i],
                original_packs=float(q),final_packs=float(q),pack=float(W.pack[i]),
                forecast_need=ln['need'],forecast_shortage=ln['short'],safety_target=ln['ss'],
                projected_left=ln['left'],stock_at_order=ln['stock'],pre_round_gap=ln['gap'],base_packs=base,
                shortage_component=shortage,safety_component=safety,rounding_component=max(0.,baseuse-shortage-safety),
                minimum_component=max(0.,(q-base)*W.pack[i]),topup_packs=q-base,removed_packs=0.,
                expected_use_lifetime=float(self.demand(d,s,i,21)[arrival-d:min(21,arrival-d+int(W.shelf[i]))].sum()))
        if self.variant not in {'trim_one','trim_expiry','trim_point_guarded','trim_guarded','combined'} or STORES[s]!='S02':return out
        for i in list(out):
            if W.INGS[i] not in FOCUS:continue
            q=out[i];new=q-1
            if new<0 or (new>0 and new<W.moq_units[i]):continue
            amount=sum(v*W.price[d,j] for j,v in out.items())-W.price[d,i]
            if amount>1e-6 and amount<float(W.sup[sid]['moq']):continue
            allow=self.variant=='trim_one'
            reason='one_pack_counterfactual'
            if not allow:
                n=min(21,max(next_arrival-d+1,arrival-d+int(W.shelf[i])))
                basepipe=dict(pipe[i]);cutpipe=dict(pipe[i])
                basepipe[arrival]=basepipe.get(arrival,0)+q*W.pack[i]
                cutpipe[arrival]=cutpipe.get(arrival,0)+new*W.pack[i]
                high=self.demand(d,s,i,n,1.2);point=self.demand(d,s,i,n)
                bshort,_=projection(lots[i],basepipe,high,d,int(W.shelf[i]))
                cshort,_=projection(lots[i],cutpipe,high,d,int(W.shelf[i]))
                bp,bw=projection(lots[i],basepipe,point,d,int(W.shelf[i]))
                cp,cw=projection(lots[i],cutpipe,point,d,int(W.shelf[i]))
                expiry_reduction=sum(cw.values())<sum(bw.values())-1e-6
                guard=True if self.variant=='trim_expiry' else np.all(cp<=bp+1e-6) if self.variant=='trim_point_guarded' else np.all(cshort<=bshort+1e-6)
                allow=bool(expiry_reduction and guard)
                reason={'trim_expiry':'forecast_expiry_reduction','trim_point_guarded':'expiry_reduction_and_point_daily_shortage_guard'}.get(self.variant,'expiry_reduction_and_120pct_daily_shortage_guard')
            if allow:
                out[i]=new
                rec=self.info[d,s,i];rec['final_packs']=float(new);rec['removed_packs']=1.
                keys=('minimum_component','rounding_component','safety_component','shortage_component')
                rec['pre_trim_components']={k:rec[k] for k in keys}
                remove=float(W.pack[i])
                for k in keys:
                    removed=min(remove,rec[k]);rec[k]-=removed;remove-=removed
                assert remove<1e-6
                self.decisions.append(dict(day=d,store=STORES[s],item=W.INGS[i],action='cut_one_pack',reason=reason))
        return {i:q for i,q in out.items() if q>0}


class Lot(list):
    def __init__(self,expiry,qty,batch):
        super().__init__([expiry,qty]);self.batch=batch


class Audit:
    def __init__(self,W,policy,transfer_mode='forecast'):
        self.W=W;self.policy=policy;self.transfer_mode=transfer_mode
        self.batches={};self.pending=defaultdict(list);self.events=[];self.hour_cache={};self.actions=[]

    def new(self,s,i,expiry,qty,receipt,kind,metadata=None):
        batch=f'B{len(self.batches):06d}'
        self.batches[batch]=dict(batch=batch,origin_store=STORES[s],item=self.W.INGS[i],receipt_day=receipt,
            expiry_day=expiry,received=qty,used=0.,expired=0.,quality=0.,terminal=0.,
            expiry_cost=0.,kind=kind,order=metadata or {})
        return Lot(expiry,qty,batch)

    def initial(self,s,i,expiry,qty):return self.new(s,i,expiry,qty,-1,'initial')

    def queue(self,d,s,i,packs,arrival,policy,kind='regular'):
        self.pending[arrival,s,i].append((packs*self.W.pack[i],kind,dict(policy.info.get((d,s,i),{})) if kind=='regular' else {}))

    def receive(self,d,s,i,qty):
        rows=self.pending.pop((d,s,i),[])
        assert abs(sum(q for q,_,_ in rows)-qty)<1e-4,(d,s,i,qty,rows)
        return [self.new(s,i,d+int(self.W.shelf[i])-1,q,d,kind,info) for q,kind,info in rows]

    def focused(self,b):return b['origin_store']=='S02' and b['item'] in FOCUS

    def consume(self,lot,qty,d,s,i,kind):
        if qty<=1e-8:return
        b=self.batches[lot.batch];b[kind]+=qty
        if kind=='expired':
            b['expiry_cost']+=qty*self.W.unit_cost_t[d,i]
            b.setdefault('expiry_events',[]).append(dict(day=d,store=STORES[s],qty=qty,cost=qty*self.W.unit_cost_t[d,i]))
        if self.focused(b):self.events.append(dict(batch=lot.batch,day=d,store=STORES[s],item=b['item'],action=kind,qty=qty))

    def move(self,lot,qty,d,h,source,target,i):
        b=self.batches[lot.batch]
        if qty>1e-8 and self.focused(b):
            self.events.append(dict(batch=lot.batch,day=d,hour=h,store=STORES[source],to_store=STORES[target],item=b['item'],action='move',qty=qty))
        return Lot(lot[0],qty,lot.batch)

    def remaining(self,d,h,s,observed=None):
        if self.transfer_mode=='oracle':return self.W.H[s,:,d,h:].sum(1)
        if observed is not None:
            # Receiver's trigger-hour demand is already observed; only later hours are forecasts.
            return observed+self.remaining(d,h+1,s)
        key=(d,h,s)
        if key not in self.hour_cache:
            # Daily demand and hourly proportions use only dates strictly before d.
            fm,_=self.policy.ensure_forecast(d)
            daily=np.array([fm.get((DATES[d].date(),STORES[s],m),0.) for m in self.W.MENUS])
            past=self.W.H[s,:,max(0,d-28):d,:]
            totals=past.sum((1,2));remaining=past[:,:,h:].sum((1,2))
            share=np.divide(remaining,totals,out=np.full_like(totals,(24-h)/24),where=totals>0)
            self.hour_cache[key]=daily*share
        return self.hour_cache[key]

    def before_day(self,d,lots,pipe,log):
        if self.policy.variant not in {'transfer_guarded','combined'} and not self.policy.variant.startswith('transfer_I'):return
        W=self.W;s=STORES.index('S02')
        for i,item in enumerate(W.INGS):
            if item not in self.policy.target_items:continue
            for lot in sorted(lots[s][i]):
                if lot[1]<=1e-6 or not d<=lot[0]<=d+6:continue
                n=14;high=self.policy.demand(d,s,i,n,1.2)
                base_short,expired=projection(lots[s][i],pipe[s][i],high,d,int(W.shelf[i]))
                surplus=min(lot[1],expired.get(lot.batch,0.))
                if surplus<=1e-6:continue
                for target in range(len(STORES)):
                    if target==s or surplus<=1e-6:continue
                    low=self.policy.demand(d,target,i,n,.8)
                    before_short,bw=projection(lots[target][i],pipe[target][i],low,d,int(W.shelf[i]))
                    q=min(surplus,float(before_short[:int(lot[0])-d+1].sum()))
                    if q<=1e-6:continue
                    _,aw=projection(lots[target][i],pipe[target][i],low,d,int(W.shelf[i]),addition=(lot[0],q,lot.batch))
                    if sum(aw.values())>sum(bw.values())+1e-6:continue
                    lot[1]-=q
                    after_short,_=projection(lots[s][i],pipe[s][i],high,d,int(W.shelf[i]))
                    if np.any(after_short>base_short+1e-6):lot[1]+=q;continue
                    lots[target][i].append(self.move(lot,q,d,9,s,target,i));lots[target][i].sort()
                    surplus-=q;log['transfers'].append((d,9,s,target,i,q))
                    self.actions.append(dict(day=d,source='S02',target=STORES[target],item=item,qty=q,
                        expiry_day=int(lot[0]),cost=0.,assumed_minutes=30,can_split=True))

    def finish(self,lots,pipe):
        for store in lots:
            for rows in store:
                for lot in rows:self.batches[lot.batch]['terminal']+=lot[1]
        errors=[abs(b['received']-sum(b[k] for k in ('used','expired','quality','terminal'))) for b in self.batches.values()]
        self.max_balance_error=max(errors,default=0.)
        assert self.max_balance_error<1e-4,self.max_balance_error


def store_metrics(log,W,lo,hi):
    rows=[]
    for s,store in enumerate(STORES):
        loss=log['lost_menu'][s,:,lo:hi]
        rows.append(dict(store=store,lost_menu_qty=float(loss.sum()),stockout_item_days=int(log['stockout'][s,:,lo:hi].sum()),
            expiry_cost=float((log['exp_waste'][s,:,lo:hi]*W.unit_cost_t[lo:hi].T).sum()),
            quality_cost=float((log['q_waste'][s,:,lo:hi]*W.unit_cost_t[lo:hi].T).sum()),
            purchase=float(log['purchase'][s,lo:hi].sum())))
    return rows


def run(output,variants):
    output.mkdir(parents=True,exist_ok=True)
    data={p.stem:pd.read_csv(p,encoding='utf-8-sig') for p in Path(D).glob('*.csv')}
    W=World();summary={};baseline_log=None;T=len(DATES)
    for variant in variants:
        mode='oracle' if variant=='oracle_reference' else 'forecast'
        E=eng.Engine(data);policy=DiagnosticPolicy(E,'baseline' if variant=='oracle_reference' else variant)
        audit=Audit(W,policy,mode)
        log=simulate(W,policy,audit)
        row=dict(metrics=kpi(W,log,'2026-02-01','2026-09-30'),by_store=store_metrics(log,W,31,T),
            metrics_aug_sep=kpi(W,log,'2026-08-01','2026-09-30'),
            evaluation_aug_sep=store_metrics(log,W,212,T),max_lot_balance_error=audit.max_balance_error,
            cuts=policy.decisions,preventive_moves=audit.actions,transfer_count=len(log['transfers']))
        if variant=='oracle_reference':
            original_policy=EnginePolicy(eng,eng.Engine(data),'original',safety_alpha=1.6)
            old=original_simulate(W,original_policy)
            row['parity']={k:float(np.max(np.abs(old[k].astype(float)-log[k].astype(float)))) for k in ('lost_qty','stockout','exp_waste','q_waste','purchase','close_qty')}
            assert max(row['parity'].values())<1e-4,row['parity']
        if variant=='baseline':baseline_log=log
        if baseline_log is not None:
            delta=log['lost_menu']-baseline_log['lost_menu']
            row['nonworsening_all_store_menu_days']=bool(np.all(delta[:,:,31:]<=1e-6))
            row['worsened_store_menu_days']=int((delta[:,:,31:]>1e-6).sum())
            row['additional_lost_menu_qty_on_worse_days']=float(np.maximum(delta[:,:,31:],0).sum())
        focused=[b for b in audit.batches.values() if b['item'] in FOCUS and
                 (audit.focused(b) or any(e['store']=='S02' for e in b.get('expiry_events',[])))]
        for b in focused:
            if not b['order']:continue
            rec=b['order'];s=STORES.index(b['origin_store']);i=W.INGS.index(b['item'])
            a=b['receipt_day'];z=min(T,b['expiry_day']+1)
            rec['realized_demand_lifetime']=float((W.H[s,:,a:z,:].sum((1,2))@W.B[:,i]))
            rec['realized_use_lifetime']=float(log['cons'][s,i,a:z].sum())
            rec['lifetime_observed_completely']=b['expiry_day']<T
        (output/f'{variant}_lots.json').write_text(json.dumps(focused,ensure_ascii=False,indent=2),encoding='utf-8')
        (output/f'{variant}_events.json').write_text(json.dumps(audit.events,ensure_ascii=False),encoding='utf-8')
        summary[variant]=row
        (output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
        print(variant,json.dumps(row['metrics'],ensure_ascii=False),flush=True)
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--variants',nargs='+',default=['oracle_reference','baseline','trim_one','trim_expiry','trim_point_guarded','trim_guarded','transfer_guarded','combined','transfer_I009','transfer_I017','transfer_I020'])
    a=p.parse_args();run(a.output,a.variants)
