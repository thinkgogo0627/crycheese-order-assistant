"""Time-safe, store-specific menu forecasts and source validation."""
from pathlib import Path
import argparse, hashlib, json
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from threadpoolctl import threadpool_limits
import joblib

ROOT=Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT=Path(__file__).resolve().parent/"artifacts"
H=14
STORES=['S01','S02','S03']
MENUS=[f'M{i:03d}' for i in range(1,17)]
REQUIRED_FILES=(1,2,7,8,9,15)

class Dataset:
    def __init__(self, data_dir=None):
        candidates=[Path(data_dir)] if data_dir is not None else [ROOT/'data',ROOT/'data'/'raw']
        self.data_dir=next((p for p in candidates if all(len(list(p.glob(f'{i:02d}_*.csv')))==1 for i in REQUIRED_FILES)),None)
        if self.data_dir is None:
            raise FileNotFoundError('Need exactly one CSV each for 01,02,07,08,09,15; pass --data-dir PATH.')
        self.paths={i:next(self.data_dir.glob(f'{i:02d}_*.csv')) for i in REQUIRED_FILES}
        self.hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in self.paths.values()}
        self.frames={i:pd.read_csv(p) for i,p in self.paths.items()}
        self.start=pd.Timestamp('2026-01-01'); self.N=273
        self.stores=self.frames[1].set_index('store_id').loc[STORES]
        self.menus=self.frames[2].set_index('menu_id').loc[MENUS]
        self.active=np.zeros((self.N,3,16),bool)
        for r in self.frames[15].itertuples():
            if r.status=='취급':
                a=self.day(r.start_date); b=self.day(r.end_date)
                self.active[a:b+1,STORES.index(r.store_id),MENUS.index(r.menu_id)]=True
        sales=self.frames[9].copy(); sales['d']=sales.date.map(self.day)
        sales['s']=sales.store_id.map(dict(zip(STORES,range(3))))
        sales['m']=sales.menu_id.map(dict(zip(MENUS,range(16))))
        assert not sales.duplicated(['date','hour','store_id','menu_id','channel']).any()
        assert sales.qty.eq(sales.demand_qty-sales.lost_qty).all()
        assert sales.cancel_qty.le(sales.qty).all()
        self.demand=np.zeros((self.N,3,16)); self.cancel=np.zeros_like(self.demand)
        for r in sales.itertuples():
            self.demand[r.d,r.s,r.m]+=r.demand_qty
            self.cancel[r.d,r.s,r.m]+=r.cancel_qty
        self.net=self.demand-self.cancel
        assert not (self.demand[~self.active]>0).any()
        self.holiday=np.zeros(self.N+H)
        for r in self.frames[7].itertuples(): self.holiday[self.day(r.date)]=r.is_holiday
        self.promo=np.zeros((self.N+H,3,16))
        for r in self.frames[8].itertuples():
            for m in r.target_menu.split(','):
                self.promo[self.day(r.start_date):self.day(r.end_date)+1,STORES.index(r.store_id),MENUS.index(m)]=1
        self.categories=pd.Categorical(self.menus.category).codes
        self.sales=sales

    def day(self,date): return int((pd.Timestamp(date)-self.start).days)
    def date(self,d): return self.start+pd.Timedelta(days=int(d))
    def offered(self,d,s): return self.active[min(d,self.N-1),s]
    def check_hashes(self):
        assert all(hashlib.sha256((self.data_dir/n).read_bytes()).hexdigest()==h for n,h in self.hashes.items())

    def features(self,o,s,h):
        """Origin o is before sales. All demand features end at o-1."""
        t=o+h; hist=self.demand[max(0,o-28):o,s]; act=self.active[max(0,o-28):o,s]
        def mean(k):
            x=hist[-k:]; a=act[-k:]
            return np.divide(x.sum(0),a.sum(0),out=np.zeros(16),where=a.sum(0)>0)
        m7,m28=mean(7),mean(28)
        w=(self.date(t).dayofweek)
        histdays=np.arange(max(0,o-28),o)
        match=np.array([self.date(d).dayofweek==w for d in histdays])
        aa=act[match]; xx=hist[match]
        weekday=np.divide(xx.sum(0),aa.sum(0),out=m7.copy(),where=aa.sum(0)>0)
        lag=hist[-1]; std=hist[-7:].std(0)
        # A cold start has no own observations. Use past observed category level as a visible fallback.
        for m in range(16):
            if not act[-7:,m].any():
                members=self.categories==self.categories[m]
                vals=m28[members]; m7[m]=np.mean(vals[vals>0]) if (vals>0).any() else 0
            if not aa[:,m].any(): weekday[m]=m7[m]
        own=np.column_stack([np.arange(16),self.categories,np.full(16,w),np.full(16,h),
             np.full(16,self.holiday[t]),self.promo[t,s],np.full(16,t/273),
             m7,m28,weekday,lag,std,np.divide(m7,m28,out=np.ones(16),where=m28>0),act[-7:].sum(0)])
        cross=np.tile(np.r_[hist[-1],hist[-7:].mean(0)],(16,1))
        return own,np.column_stack([own,cross]),m7,weekday


def metrics(y,p):
    return {'wape_pct':100*np.abs(y-p).sum()/y.sum() if y.sum() else np.nan,
            'mae':np.abs(y-p).mean(),'bias_pct':100*(p-y).sum()/y.sum() if y.sum() else np.nan}

def train_forecasts(data, output_dir=DEFAULT_OUTPUT):
    """Fit Jan-Jun for July selection, then refit Jan-Jul for fixed Aug-Sep evaluation."""
    out=Path(output_dir)
    (out/'models').mkdir(exist_ok=True,parents=True)
    variants=['mean7','weekday4','blend','hgb_own','hgb_cross']
    validation_end=data.day('2026-08-01'); first=data.day('2026-07-01')
    all_scores=[]; predictions=[]; selected={}; caches={}
    # Build once. Training labels are explicitly censored at each fit cutoff.
    blocks={s:[] for s in range(3)}
    for s in range(3):
        for o in range(28,validation_end):
            for h in range(H):
                t=o+h
                if t>=validation_end: continue
                a,b,m7,w=data.features(o,s,h); mask=data.active[t,s]
                blocks[s].append((t,a[mask],b[mask],data.demand[t,s,mask]))
    for phase,cutoff,end in [('validation',first,validation_end),('test',validation_end,data.N)]:
        cache={v:np.zeros((data.N,H,3,16)) for v in variants}
        for s in range(3):
            rows=[b for b in blocks[s] if b[0]<cutoff]
            X=np.vstack([b[2] for b in rows]); y=np.concatenate([b[3] for b in rows])
            models={}
            for name,ncols in [('hgb_own',14),('hgb_cross',46)]:
                model=HistGradientBoostingRegressor(loss='poisson',learning_rate=.06,max_iter=120,
                    max_leaf_nodes=15,min_samples_leaf=35,l2_regularization=2,
                    categorical_features=[0,1,2],early_stopping=False,random_state=42)
                with threadpool_limits(limits=2): model.fit(X[:,:ncols],y)
                models[name]=model
                joblib.dump(model,out/'models'/f'{phase}_{STORES[s]}_{name}.joblib')
            xs=[]; bases=[]; positions=[]
            for o in range(cutoff,end):
                for h in range(H):
                    a,b,m7,w=data.features(o,s,h)
                    xs.append(b); bases.append((m7,w)); positions.append((o,h))
            XX=np.vstack(xs)
            with threadpool_limits(limits=2):
                pp={n:models[n].predict(XX[:,:14 if n=='hgb_own' else 46]).reshape(-1,16) for n in models}
            for k,(o,h) in enumerate(positions):
                active=data.offered(o+h,s); m7,w=bases[k]
                vals={'mean7':m7,'weekday4':w,'blend':.5*m7+.5*w,'hgb_own':pp['hgb_own'][k],'hgb_cross':pp['hgb_cross'][k]}
                for name,v in vals.items(): cache[name][o,h,s]=np.maximum(v,0)*active
            # Score one-step and operational h=0..3 separately; model selection uses h=0..3.
            for name in variants:
                for band,hs in [('day0',[0]),('days0to3',range(4))]:
                    truth=[]; pred=[]
                    for o in range(cutoff,end):
                        for h in hs:
                            if o+h>=end: continue
                            mask=data.active[o+h,s]
                            truth.extend(data.demand[o+h,s,mask]); pred.extend(cache[name][o,h,s,mask])
                    result={'phase':phase,'store_id':STORES[s],'model':name,'horizons':band,
                            **metrics(np.array(truth),np.array(pred))}
                    all_scores.append(result)
            if phase=='validation':
                ss=[r for r in all_scores if r['phase']==phase and r['store_id']==STORES[s] and r['horizons']=='days0to3']
                selected[STORES[s]]=min(ss,key=lambda r:r['wape_pct'])['model']
            print(phase,STORES[s],'selected',selected[STORES[s]],flush=True)
        cache['selected']=np.zeros_like(cache['mean7'])
        for s,store in enumerate(STORES): cache['selected'][:,:,s]=cache[selected[store]][:,:,s]
        for o in range(cutoff,end):
            for s,store in enumerate(STORES):
                for m,menu in enumerate(MENUS):
                    predictions.append({'phase':phase,'date':str(data.date(o).date()),'store_id':store,'menu_id':menu,
                        'offered':bool(data.active[o,s,m]),'actual_demand':data.demand[o,s,m],
                        **{v:cache[v][o,0,s,m] for v in variants+['selected']}})
        caches[phase]=cache
    scores=pd.DataFrame(all_scores); scores.to_csv(out/'forecast_scores.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(predictions).to_csv(out/'daily_menu_predictions.csv',index=False,encoding='utf-8-sig')
    (out/'model_selection.json').write_text(json.dumps(selected,ensure_ascii=False,indent=2),encoding='utf-8')
    manifest={'fit_periods':{'validation':'training labels <= 2026-06-30','test':'training labels <= 2026-07-31'},
        'selection_period':'2026-07-01..2026-07-31; target dates inside July only',
        'selection_metric':'store-specific WAPE over horizons 0..3; offered menu-days',
        'feature_history':'all demand-derived inputs end at origin-1',
        'features_own':['menu','category','target_weekday','horizon','holiday','target_menu_promotion','time_index',
            'active_day_mean7','active_day_mean28','same_weekday4','lag1','std7','mean7_over_mean28','active_days7'],
        'features_cross':['all 16 menus lag1','all 16 menus prior7 calendar-day means'],
        'assumed_known':['menu availability schedule','promotion schedule','calendar'],
        'source_hashes':data.hashes,'selected':selected,
        'hgb_parameters':{'loss':'poisson','learning_rate':.06,'max_iter':120,'max_leaf_nodes':15,
            'min_samples_leaf':35,'l2_regularization':2,'early_stopping':False,'random_state':42},
        'api_reference':'https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.HistGradientBoostingRegressor.html'}
    (out/'model_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    # Persist full origin/horizon predictions so simulations and notebook are reproducible.
    for phase,c in caches.items(): np.savez_compressed(out/f'forecasts_{phase}.npz',**c)
    return caches,selected,scores

def main(argv=None):
    parser=argparse.ArgumentParser(description='Train the shared store-specific baseline demand forecast.')
    parser.add_argument('--data-dir',type=Path,help='Directory containing the provided source CSVs; default: data/, then data/raw/.')
    parser.add_argument('--output-dir',type=Path,default=DEFAULT_OUTPUT,help='Local generated models and predictions.')
    args=parser.parse_args(argv)
    data=Dataset(args.data_dir)
    _,selected,scores=train_forecasts(data,args.output_dir)
    data.check_hashes()
    print('Selected models:',selected)
    print(scores.loc[(scores.phase=='test') & (scores.horizons=='day0')].to_string(index=False))
    print('Output:',args.output_dir.resolve())

if __name__=='__main__':
    main()
