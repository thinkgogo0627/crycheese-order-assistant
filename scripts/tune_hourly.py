"""Offline, chronological calibration of the exact demand/rolling model components.

Usage (requires PRIVATE CSV data/raw, never committed):
    python scripts/tune_hourly.py

The search uses July 2026. Aug-Sep 2026 has been repeatedly inspected;
its reported assessment is exploratory, not an independent holdout. The calibrator scores latent demand
but exclusively uses fulfilled POS sales (qty-cancel_qty) as live evidence.
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from itertools import product
from pathlib import Path
from collections import defaultdict

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.features.hourly_forecast.runtime import get_engine, Scenario
ENGINE = get_engine()

OUT=ROOT/'work'/'hourly_tuning'
OUT.mkdir(parents=True,exist_ok=True)

TRAIN_START=date(2026,7,1)
VALID_END=date(2026,7,31)
TEST_END=date(2026,9,30)
RECENT=(7,14,28)
SAMEW=(2,4,8)
HOURS_LOOKBACK=(28,56,84)
PSEUDOS=(0.,4.,12.,24.)
WEIGHTS=[(i/5,j/5,(5-i-j)/5) for i in range(6) for j in range(6-i)]
# Current baseline: (7,4,56,12,0.4/0.4/0.2)
OLD=(7,4,56,12.,(0.4,0.4,0.2))


def pct(pred,actual):
    return 100*np.abs(pred-actual).sum()/max(actual.sum(),1e-9)


def capture():
    e=ENGINE
    dm=e.demand_model
    rows=[]
    actual_qty=e.data['09_sales'].copy()
    actual_qty['sold']=np.maximum(0.,actual_qty['qty'].astype(float)-actual_qty['cancel_qty'].astype(float))
    sold={(date.fromisoformat(str(r.date)),r.store_id,r.menu_id,int(r.hour)):float(r.sold)
          for r in actual_qty.groupby(['date','store_id','menu_id','hour'],as_index=False)['sold'].sum().itertuples(index=False)}
    cur=TRAIN_START
    while cur<=TEST_END:
        if (cur-TRAIN_START).days%15==0:
            print(f'[features] {cur.isoformat()}',flush=True)
        sc=Scenario(as_of=cur,horizon_days=1,forecast_profile="original")
        pred,_,hpred,_=e.forecast_bundle(sc)
        cutoff=cur-timedelta(days=1)
        for store in e.stores:
            for menu in e.menus:
                if not e.active(store,menu,cur):continue
                hist=dm._samples(store,menu,cutoff,56)
                recent=[dm._mean([v for d,v in hist if d>=cutoff-timedelta(days=n-1)]) for n in RECENT]
                same0=[v for d,v in hist if d.weekday()==cur.weekday()]
                same=[dm._mean(same0[:n]) if same0 else recent[0] for n in SAMEW]
                area=dm._mean([v for _,v in hist])*dm._weekday_profile(store,menu,hist,cur.weekday())
                oldbase=0.4*recent[0]+0.4*same[1]+0.2*area
                current_d=pred.get((cur,store,menu),0.)
                effect=current_d/oldbase if oldbase>1e-9 else 1.
                # preserve exact existing menu-correlation and promotion effects
                shares={}; openh=int(e.stores[store]['open_hour']);closeh=int(e.stores[store]['close_hour'])
                possible=list(range(openh,closeh))
                for win in HOURS_LOOKBACK:
                    ds=[cutoff-timedelta(days=k) for k in range(win) if e.active(store,menu,cutoff-timedelta(days=k))]
                    sames=[d for d in ds if d.weekday()==cur.weekday()]
                    basecounts=np.zeros(24);samecounts=np.zeros(24)
                    for d in ds:
                        for h,q in dm.hourly.get((store,menu,d),{}).items():basecounts[h]+=q
                    for d in sames:
                        for h,q in dm.hourly.get((store,menu,d),{}).items():samecounts[h]+=q
                    denom=basecounts[possible].sum()
                    prior=np.zeros(24)
                    prior[possible]=basecounts[possible]/denom if denom>0 else 1./len(possible)
                    for pseudo in PSEUDOS:
                        div=samecounts[possible].sum()+pseudo
                        # zero count & zero pseudocount requires a proper prior (avoid 0/0)
                        shares[(win,pseudo)]=(samecounts+pseudo*prior)/div if div>0 else prior.copy()
                y=np.zeros(24);pos=np.zeros(24);current_h=np.zeros(24)
                for h in possible:
                    y[h]=dm.hourly.get((store,menu,cur),{}).get(h,0.)
                    pos[h]=sold.get((cur,store,menu,h),0.)
                    current_h[h]=hpred.get((cur,store,menu,h),0.)
                assert np.isclose(current_d,current_h.sum(),atol=1e-6)
                oldshares=shares[(56,12.)]
                if current_d>0 and not np.allclose(current_h,current_d*oldshares,atol=1e-5):
                    raise AssertionError(f'Not exact: {cur} {store} {menu} {np.abs(current_h-current_d*oldshares).max()}')
                rows.append(dict(day=cur,store=store,menu=menu,rec=recent,same=same,area=area,
                                 effect=effect,y=y,pos=pos,current_daily=current_d,current_h=current_h,
                                 shares=shares,active_hours=possible))
        cur+=timedelta(days=1)
    print(f'[features] finished rows={len(rows)}',flush=True)
    return rows


def make_arrays(rows):
    d=np.array([x['day'] for x in rows]);store=np.array([x['store'] for x in rows]);menus=np.array([x['menu'] for x in rows]);
    Y=np.stack([x['y'] for x in rows]);POS=np.stack([x['pos'] for x in rows]);
    C=np.stack([x['current_h'] for x in rows]);
    R=np.stack([x['rec'] for x in rows]);W=np.stack([x['same'] for x in rows]);A=np.array([x['area'] for x in rows]);E=np.array([x['effect'] for x in rows]);
    S={k:np.stack([r['shares'][k] for r in rows]) for k in product(HOURS_LOOKBACK,PSEUDOS)}
    val=(d<=VALID_END);test=(d>VALID_END)
    assert val.sum()>0 and test.sum()>0
    return locals()


def daily_guess(D,rv,sv,weights):
    a,b,c=weights
    return np.maximum(0., (a*D['R'][:,RECENT.index(rv)]+b*D['W'][:,SAMEW.index(sv)]+c*D['A'])*D['E'])


def optimize_baseline(D):
    # Independent minimization of hourly WAPE, includes daily and hour-profile components.
    val=D['val'];y=D['Y'][val]
    prev=D['C'][val]
    records=[]
    for rv,sv,w in product(RECENT,SAMEW,WEIGHTS):
        d=daily_guess(D,rv,sv,w)[val,None]
        for hw,pseudo in product(HOURS_LOOKBACK,PSEUDOS):
            pred=d*D['S'][(hw,pseudo)][val]
            loss=np.abs(pred-y).sum()
            records.append((loss,rv,sv,w,hw,pseudo))
    records.sort(key=lambda x:x[0]);best=records[0]
    orig=pct(prev,y)
    bpred=daily_guess(D,best[1],best[2],best[3])[:,None]*D['S'][(best[4],best[5])]
    print('[baseline] July old,selected',orig,pct(bpred[val],y),flush=True)
    print('[baseline] chosen',best[1:],flush=True)
    print('[baseline] top',records[:5],flush=True)
    print('[baseline] Aug/Sep current,selected',pct(D['C'][D['test']],D['Y'][D['test']]),pct(bpred[D['test']],D['Y'][D['test']]),flush=True)
    return best,bpred,records


def rolling_fields(D,bpred):
    """Create strictly causal cumulative POS and baseline features for each store/day/hour/menu."""
    by_store_day=defaultdict(list)
    for idx in range(len(D['d'])):by_store_day[(D['d'][idx],D['store'][idx])].append(idx)
    data=[]
    for (day,store),row_ids in by_store_day.items():
        # All 16 menu rows, hour range may differ by store.
        actual=D['POS'][row_ids].sum(axis=0)
        base=bpred[row_ids].sum(axis=0)
        cumul_pos=np.cumsum(actual)-actual
        cumul_base=np.cumsum(base)-base
        for idx in row_ids:
            # store schedule from known metadata, not future observed demand
            start=int(ENGINE.stores[store]['open_hour']);end=int(ENGINE.stores[store]['close_hour'])
            for h in range(start+1,end):
                data.append((idx,h,float(D['Y'][idx,h]),float(bpred[idx,h]),
                             float(cumul_pos[h]),float(cumul_base[h]),
                             float(D['POS'][idx,:h].sum()),float(bpred[idx,:h].sum())))
    arr=np.asarray(data,dtype=float)
    return dict(idx=arr[:,0].astype(int),hour=arr[:,1].astype(int),target=arr[:,2],baseline=arr[:,3],
                pos_store=arr[:,4],base_store=arr[:,5],pos_menu=arr[:,6],base_menu=arr[:,7])


def predict_rolling(F, config):
    """Vectorized, mathematically equal to CumulativeHourlyForecaster._signals()."""
    strength=config['strength'];ss=config['store_smooth'];ms=config['menu_smooth'];gain=config['menu_gain'] if strength > 0 else 0.0
    store_ratio=(F['pos_store']+ss)/(F['base_store']+ss+1e-30)
    store_factor=np.clip(1+strength*(store_ratio-1),config['store_low'],config['store_high'])
    menu_ratio=(F['pos_menu']+ms)/(F['base_menu']+ms+1e-30)
    delta=np.clip((menu_ratio-store_ratio)*gain,-config['delta_cap'],config['delta_cap'])
    menu_factor=np.clip(store_factor+delta,config['menu_low'],config['menu_high'])
    return F['baseline']*menu_factor


def tune_rolling(F,D):
    validation=D['val'][F['idx']]
    target=F['target'][validation]
    old=dict(strength=.4,store_smooth=8.,menu_smooth=3.,menu_gain=.1,
             store_low=.75,store_high=1.3,menu_low=.70,menu_high=1.35,delta_cap=.06)
    # Prioritize physically meaningful minimal model, then modest menu correction.
    # Stage 1: store-only correction; 3,888 simple combinations.
    store_candidates=[]
    for ss,strength,lo,hi in product((2.,4.,8.,16.,32.),(0.,.1,.2,.3,.4,.5,.6,.8),(.5,.65,.75,.85,1.),(1.,1.15,1.3,1.5,2.)):
        if hi<lo:continue
        store_ratio=(F['pos_store'][validation]+ss)/(F['base_store'][validation]+ss)
        f=np.clip(1+strength*(store_ratio-1),lo,hi)
        loss=np.abs(F['baseline'][validation]*f-target).sum()
        store_candidates.append((loss,ss,strength,lo,hi))
    store_candidates.sort()
    # Keep the simplest store-only top 5, then tune optional menu-level adjustment.
    base_top=store_candidates[:5]
    trial=[]
    for _,ss,strength,lo,hi in base_top:
        for ms,gain,delta in product((1.,3.,6.,12.),(0.,.05,.1,.2),(.03,.06,.10)):
            c=dict(strength=strength,store_smooth=ss,menu_smooth=ms,
                   menu_gain=gain,store_low=lo,store_high=hi,
                   menu_low=min(.7,lo),menu_high=max(1.35,hi),delta_cap=delta)
            # If gain=0, preserve no menu adjustments.
            loss=np.abs(predict_rolling(F,c)[validation]-target).sum()
            trial.append((loss,c))
    trial.sort(key=lambda x:x[0]);best=trial[0][1]
    # Always check pre-calibration defaults against the selected same baseline;
    # and include no-adjustment to detect no useful rolling signal.
    b_old=predict_rolling(F,old)
    b_new=predict_rolling(F,best)
    before=pct(F['baseline'][validation],target)
    print('[rolling] July baseline, old, calibrated',before,pct(b_old[validation],target),pct(b_new[validation],target),flush=True)
    print('[rolling] best',json.dumps(best,ensure_ascii=False),flush=True)
    return best,old,b_new,b_old,trial


def tune_shortage_protective(F,D,under_weight=1.5):
    """Cost-illustrative policy: miss demand is weighted 1.5x overprediction.

    This is NOT a company-provided shortage/waste cost ratio; use as sensitivity
    mode, never claim it is the economically optimal service level.
    """
    val=D['val'][F['idx']]; y=F['target'][val]; b=F['baseline'][val]
    def loss(p):
        err=p-y
        return np.where(err<0,under_weight*(-err),err).sum()
    candidates=[]
    for ss,strength,lo,hi in product((2.,4.,8.,16.,32.),(0.,.1,.2,.3,.4,.5,.6,.8),(.5,.65,.75,.85,1.),(1.,1.15,1.3,1.5,2.)):
        if hi<lo:continue
        factor=np.clip(1+strength*((F['pos_store'][val]+ss)/(F['base_store'][val]+ss)-1),lo,hi)
        candidates.append((loss(b*factor),ss,strength,lo,hi))
    candidates.sort();final=[]
    for _,ss,strength,lo,hi in candidates[:8]:
        for ms,gain,delta in product((1.,3.,6.,12.),(0.,.05,.1,.2),(.03,.06,.10)):
            c=dict(strength=strength,store_smooth=ss,menu_smooth=ms,
                   menu_gain=gain,store_low=lo,store_high=hi,
                   menu_low=min(.7,lo),menu_high=max(1.35,hi),delta_cap=delta)
            final.append((loss(predict_rolling(F,c)[val]),c))
    final.sort(key=lambda x:x[0]);cfg=final[0][1]
    pred=predict_rolling(F,cfg)
    print('[PROTECTIVE]',under_weight,json.dumps(cfg), 'july_wape',pct(pred[val],y),'holdout_wape',pct(pred[D['test'][F['idx']]],F['target'][D['test'][F['idx']]]),flush=True)
    return cfg,pred


def report_metrics(D,F,F_orig,cur,bp,opt,old,selected,orig_original,protective_pred):
    t=D['test']; val=D['val'];out={}
    actual=D['Y'];
    for name,mask in [('july_validation',val),('aug_sep_holdout',t)]:
        rows={}
        for method,pred in [('original_baseline',cur),('tuned_baseline',bp)]:
            rows[method]=dict(hour_wape=pct(pred[mask],actual[mask]),
                              day_wape=pct(pred[mask].sum(axis=1),actual[mask].sum(axis=1)))
        fmask=mask[F['idx']]
        fmask0=mask[F_orig['idx']]
        rows['original_end_to_end']={'next_hour_wape':pct(orig_original[fmask0],F_orig['target'][fmask0]), 'next_hour_mae':float(np.abs(orig_original[fmask0]-F_orig['target'][fmask0]).mean())}
        for method,pred in [('original_cumulative_on_tuned_baseline',old),('tuned_cumulative',selected),
                            ('tuned_baseline_next_hour',F['baseline']),('shortage_protective',protective_pred)]:
            rows[method]=dict(next_hour_wape=pct(pred[fmask],F['target'][fmask]),
                              next_hour_mae=float(np.abs(pred[fmask]-F['target'][fmask]).mean()))
        out[name]=rows
        print(f'=={name}==',json.dumps(rows,ensure_ascii=False,indent=2),flush=True)
    # Score per store across final test: no averaging of per-store percentages in headline.
    out['per_store_holdout']={}
    for s in ENGINE.stores:
        fmask=t[F['idx']]&(D['store'][F['idx']]==s)
        out['per_store_holdout'][s]={
            'records':int(fmask.sum()),
            'no_adjust_wape':pct(F['baseline'][fmask],F['target'][fmask]),
            'original_adjust_wape':pct(old[fmask],F['target'][fmask]),
            'calibrated_adjust_wape':pct(selected[fmask],F['target'][fmask]),
        }
    for month in (8,9):
        mask=(D['d'][F['idx']]>=date(2026,month,1))&(D['d'][F['idx']]<date(2026,month+1,1) if month<12 else True)
        out[f'month_{month}']={
            'original_end_to_end_wape':pct(orig_original[mask], F_orig['target'][mask]),
            'tuned_end_to_end_wape':pct(selected[mask],F['target'][mask]),
            'protective_end_to_end_wape':pct(protective_pred[mask],F['target'][mask]),
        }
    # Block-bootstrap calendar weeks, resampling all menu/hours/stores together
    # so the confidence interval does not pretend individual orders are iid.
    mask=D['test'][F['idx']]
    dates=D['d'][F['idx']][mask]
    labels=np.array([dt.isocalendar()[:2] for dt in dates],dtype=object)
    week_ids=np.array([str(dt.isocalendar()[:2]) for dt in dates])
    unique=np.unique(week_ids)
    groups={w:np.flatnonzero(week_ids==w) for w in unique}
    y=F['target'][mask]; oldp=orig_original[mask]; newp=selected[mask]
    rng=np.random.default_rng(240731)
    diffs=[]
    for i in range(1500):
        weeks=rng.choice(unique,size=len(unique),replace=True)
        chosen=np.concatenate([groups[x] for x in weeks])
        denom=max(y[chosen].sum(),1e-10)
        diffs.append(100*(np.abs(oldp[chosen]-y[chosen]).sum()-np.abs(newp[chosen]-y[chosen]).sum())/denom)
    out['bootstrap']={'week_blocks':len(unique),'n_draws':len(diffs), 'delta_wape_old_minus_tuned_95pct_interval':list(np.quantile(diffs,[.025,.975])),
                      'positive_improvement_rate':float((np.array(diffs)>0).mean())}
    # Store-level next-hour sums, matching what the operator sees on dashboard.
    agg=pd.DataFrame({'date':[str(x) for x in D['d'][F['idx']][mask]],
                      'store':D['store'][F['idx']][mask], 'hour':F['hour'][mask],
                      'target':F['target'][mask], 'old':orig_original[mask],
                      'balanced':selected[mask], 'protective':protective_pred[mask]})
    agg=agg.groupby(['date','store','hour'],sort=False)[['target','old','balanced','protective']].sum()
    out['store_hour_holdout']={'observations':len(agg),
        **{f'{k}_wape':pct(agg[k].to_numpy(),agg['target'].to_numpy()) for k in ('old','balanced','protective')}}
    out['forecast_bias']={}
    for name,pred in [('old_original',orig_original),('tuned',selected),('protective',protective_pred)]:
        yy=F['target'][mask];p=pred[mask];
        out['forecast_bias'][name]={'mean_signed_error':float((p-yy).mean()),
                                    'total_underforecast_menu_units':float(np.maximum(yy-p,0).sum()),
                                    'total_overforecast_menu_units':float(np.maximum(p-yy,0).sum())}
    # Same block-bootstrap for the protective profile as the balanced one.
    protectp=protective_pred[mask]
    p_diffs=[]
    rng=np.random.default_rng(240731)
    for i in range(1500):
        weeks=rng.choice(unique,size=len(unique),replace=True)
        chosen=np.concatenate([groups[x] for x in weeks])
        denom=max(y[chosen].sum(),1e-10)
        p_diffs.append(100*(np.abs(oldp[chosen]-y[chosen]).sum()-np.abs(protectp[chosen]-y[chosen]).sum())/denom)
    out['bootstrap']['protective_delta_wape_old_minus_new_95pct_interval']=list(np.quantile(p_diffs,[.025,.975]))
    print('[BOOTSTRAP]',json.dumps(out['bootstrap'],ensure_ascii=False),flush=True)
    return out


def main():
    rows=capture();D=make_arrays(rows)
    best,baseline,records=optimize_baseline(D)
    F=rolling_fields(D,baseline)
    F_orig=rolling_fields(D,D['C'])
    config,old,selected,oldpred,trials=tune_rolling(F,D)
    original_rolling=dict(strength=.4,store_smooth=8.,menu_smooth=3.,menu_gain=.1,
                          store_low=.75,store_high=1.3,menu_low=.70,menu_high=1.35,delta_cap=.06)
    original_e2e=predict_rolling(F_orig,original_rolling)
    protective_cfg,protective_pred=tune_shortage_protective(F,D,under_weight=1.5)
    met=report_metrics(D,F,F_orig,D['C'],baseline,config,oldpred,selected,original_e2e,protective_pred)
    cfg={
        'description':'Chronological July 2026 validation; repeatedly inspected August–September 2026 evaluation. Forecasting latent demand using earlier fulfilled POS sales.',
        'baseline':dict(recent_days=int(best[1]),same_weekdays=int(best[2]),hour_profile_days=int(best[4]),hour_pseudo=float(best[5]),
                        weights=[float(x) for x in best[3]],area_history_days=56),
        'rolling':config,
        'shortage_protective_illustrative':{'under_prediction_weight':1.5,'parameters':protective_cfg},
        'selected_on':'2026-07-01..2026-07-31',
        'evaluated_on':'2026-08-01..2026-09-30',
        'metrics':met,
    }
    (OUT/'selected_params.json').write_text(json.dumps(cfg,ensure_ascii=False,indent=2)+'\n', encoding='utf-8')
    pd.DataFrame([dict(july_abs_error=r[0],recent_days=r[1],same_weekdays=r[2],weights=str(r[3]),
                            hourly_history_days=r[4],hourly_pseudocount=r[5]) for r in records[:30]]).to_csv(OUT/'validation_top30.csv',index=False)
    pd.DataFrame([dict(july_abs_error=r[0],**r[1]) for r in trials[:30]]).to_csv(OUT/'rolling_top30.csv',index=False)
    print('WRITTEN',OUT/'selected_params.json')


if __name__=='__main__':main()
