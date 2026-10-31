"""Leakage-safe daily/hourly demand forecasting using observed sales history.

Trade area is represented by store-specific weekend/weekday and intraday
profiles; three stores each belong to a unique trade area, so a separate
causal trade-area coefficient cannot be identified from these data.
Promotions are advertised schedules; their availability at the scenario as-of
is assumed. Observed promo sales after as-of are never used.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from math import sqrt

import pandas as pd
from .calibration import baseline_params


class DemandModel:
    def __init__(self, engine):
        self.e = engine
        sales = engine.data['09_sales']
        hourly = sales.groupby(['date', 'store_id', 'menu_id', 'hour'], as_index=False)['demand_qty'].sum()
        self.hourly = defaultdict(dict)
        for r in hourly.itertuples(index=False):
            self.hourly[(r.store_id, r.menu_id, date.fromisoformat(r.date))][int(r.hour)] = float(r.demand_qty)
        self.promos = []
        for p in engine.data['08_promotions'].to_dict('records'):
            if isinstance(p['target_menu'], str):
                ids = {x.strip() for x in p['target_menu'].replace('+', ',').split(',') if x.strip()}
            else:
                ids = set()
            self.promos.append((p['store_id'], date.fromisoformat(p['start_date']),
                                date.fromisoformat(p['end_date']), ids, p['promo_type']))

    def active_promos(self, store, menu, day):
        return [p for p in self.promos if p[0] == store and p[1] <= day <= p[2] and menu in p[3]]

    def _samples(self, s, m, cutoff, n=56):
        return [(cutoff-timedelta(days=k), self.e.daily_sales.get((cutoff-timedelta(days=k),s,m),0.))
                for k in range(n) if self.e.active(s,m,cutoff-timedelta(days=k))]

    @staticmethod
    def _mean(xs):
        return sum(xs)/len(xs) if xs else 0.

    def _weekday_profile(self, s, m, samples, weekday):
        # A store + trade-area + menu specific factor, shrunk to a 1.0 baseline.
        # Cannot separately identify store and trade area with one store per area.
        all_values = [v for _,v in samples]
        current = [v for d,v in samples if d.weekday() == weekday]
        avg = self._mean(all_values)
        if avg <= 0:return 1.
        return max(.5, min(1.65, (.25 + .75 * (self._mean(current)/avg if current else 1.))))

    def _promo_factor(self, store, menu, cutoff):
        # Difference-in-ratios with non-target menu controls; only prior observations.
        campaigns=[p for p in self.promos if p[0]==store and menu in p[3] and p[1]<=cutoff]
        if not campaigns:return 1.,0
        campaign=campaigns[-1]
        begin,end=campaign[1], min(campaign[2],cutoff)
        observed = [(d,self.e.daily_sales.get((d,store,menu),0.))
                    for d in (begin+timedelta(days=k) for k in range((end-begin).days+1))
                    if self.e.active(store,menu,d)]
        if len(observed)<5:return 1.,len(observed)
        # Same-weekday pre-promo baseline, avoids using future campaign outcomes.
        pre=[]
        for d,v in observed:
            pool=[self.e.daily_sales.get((d-timedelta(days=7*k),store,menu),0.)
                  for k in range(1,5) if d-timedelta(days=7*k)<begin and self.e.active(store,menu,d-timedelta(days=7*k))]
            if pool: pre.append((d,v,self._mean(pool)))
        if len(pre)<5:return 1.,len(pre)
        target_ratio=self._mean([v for _,v,_ in pre])/max(.1,self._mean([base for _,_,base in pre]))
        controls=[]
        control_menus=[m for m in self.e.menus if m not in campaign[3] and m!=menu]
        for other in control_menus:
            before=[];after=[]
            for d,_,_ in pre:
                before_v=[self.e.daily_sales.get((d-timedelta(days=7*k),store,other),0.)
                          for k in range(1,5) if d-timedelta(days=7*k)<begin and self.e.active(store,other,d-timedelta(days=7*k))]
                if before_v and self.e.active(store,other,d):
                    before.append(self._mean(before_v))
                    after.append(self.e.daily_sales.get((d,store,other),0.))
            if before and self._mean(before)>1:
                controls.append(self._mean(after)/max(.1,self._mean(before)))
        control_factor=self._mean(controls) if controls else 1.
        raw=target_ratio/max(.5,control_factor)
        weight=min(.65,len(pre)/(len(pre)+15))
        return max(.75,min(1.5,1+weight*(raw-1))),len(pre)

    def _links(self, store, cutoff):
        # Weekday-demeaned correlations between distinct menu demand histories.
        days=[cutoff-timedelta(days=k) for k in range(56)]
        signals={}
        for m in self.e.menus:
            xs=[]
            for d in days:
                if self.e.active(store,m,d):xs.append((d,self.e.daily_sales.get((d,store,m),0.)))
            if len(xs)<21:continue
            weekdays=defaultdict(list)
            for d,v in xs:weekdays[d.weekday()].append(v)
            means={w:self._mean(q) for w,q in weekdays.items()}
            signals[m]={d:(v-means[d.weekday()])/max(1.,means[d.weekday()]) for d,v in xs}
        corr={}; links=[]
        menus=list(signals)
        for a_idx,a in enumerate(menus):
            for b in menus[a_idx+1:]:
                shared=set(signals[a]) & set(signals[b])
                if len(shared)<21:continue
                x=[signals[a][d] for d in shared];y=[signals[b][d] for d in shared]
                xm=self._mean(x);ym=self._mean(y)
                xx=sum((v-xm)**2 for v in x);yy=sum((v-ym)**2 for v in y)
                r=sum((u-xm)*(v-ym) for u,v in zip(x,y))/sqrt(xx*yy) if xx>0 and yy>0 else 0.
                corr[(a,b)]=r;corr[(b,a)]=r
                overlap=set(self.e.bom[a]) & set(self.e.bom[b])
                if abs(r)>=.2 or len(overlap)>=3:
                    links.append({'menu_a':a,'menu_b':b,'name_a':self.e.menus[a]['menu_name'],
                                  'name_b':self.e.menus[b]['menu_name'],'correlation':round(r,3),
                                  'shared_ingredients':len(overlap),'observations':len(shared)})
        return corr,sorted(links,key=lambda x:abs(x['correlation']),reverse=True)[:12]

    def _hour_share(self, store, menu, weekday, cutoff, *, window=56, pseudo=12.):
        openhour=int(self.e.stores[store]['open_hour']); closehour=int(self.e.stores[store]['close_hour'])
        possible=list(range(openhour,closehour))
        days=[cutoff-timedelta(days=k) for k in range(window)]
        same=[d for d in days if d.weekday()==weekday and self.e.active(store,menu,d)]
        all_days=[d for d in days if self.e.active(store,menu,d)]
        counts=defaultdict(float);base=defaultdict(float)
        for d in all_days:
            for h,q in self.hourly.get((store,menu,d),{}).items():base[h]+=q
        for d in same:
            for h,q in self.hourly.get((store,menu,d),{}).items():counts[h]+=q
        grand=sum(base[h] for h in possible)
        # Dirichlet shrinkage: weekday-specific hours + prior menu/hour profile.
        denominator=sum(counts[h] for h in possible)+pseudo
        if denominator<=0:
            return {h:(base[h]/grand if grand else 1/len(possible)) for h in possible}
        return {h:(counts[h]+pseudo*(base[h]/grand if grand else 1/len(possible)))/denominator for h in possible}

    def generate(self, sc):
        params=baseline_params(getattr(sc,"forecast_profile","protective"))
        cutoff=sc.as_of-timedelta(days=1)
        bymenu={};byitem={};byhour={};profiles=[];links_by_store={};uplifts=[]
        total_days=sc.horizon_days  # Hourly adapter requests exactly the needed days.
        corrmap={}
        shares_cache={}
        histories={}
        for s in self.e.stores:
            corr,links=self._links(s,cutoff)
            corrmap[s]=corr;links_by_store[s]=links
            recent=[(cutoff-timedelta(days=k),
                     sum(self.e.daily_sales.get((cutoff-timedelta(days=k),s,m),0.) for m in self.e.menus))
                    for k in range(56)]
            weekdays=[v for d,v in recent if d.weekday()<5];weekends=[v for d,v in recent if d.weekday()>=5]
            profiles.append({'store_id':s,'trade_area':self.e.stores[s]['trade_area'],
                             'weekday_mean':round(self._mean(weekdays),2),
                             'weekend_mean':round(self._mean(weekends),2),
                             'weekend_vs_weekday':round(self._mean(weekends)/max(.01,self._mean(weekdays)),3)})
            for m in self.e.menus:
                histories[(s,m)]=self._samples(s,m,cutoff,n=int(params["area_history_days"]))
        promo_effect={}
        for s in self.e.stores:
            for m in self.e.menus:
                promo_effect[(s,m)]=self._promo_factor(s,m,cutoff)
        for offset in range(total_days):
            day=sc.as_of+timedelta(days=offset)
            for s in self.e.stores:
                raw={}
                for m in self.e.menus:
                    if not self.e.active(s,m,day):continue
                    hist=histories[(s,m)]
                    vals7=[v for d,v in hist if d>=cutoff-timedelta(days=int(params["recent_days"])-1)]
                    recent7=self._mean(vals7)
                    same=[v for d,v in hist if d.weekday()==day.weekday()][:int(params["same_weekdays"])]
                    sameavg=self._mean(same) if same else recent7
                    area_factor=self._weekday_profile(s,m,hist,day.weekday())
                    area_base=self._mean([v for _,v in hist])*area_factor
                    wr,ws,wa=params["weights"]
                    base=max(0,wr*recent7+ws*sameavg+wa*area_base)
                    raw[m]=base
                # Restrained association effect from co-demand anomalies in the
                # LAST observed 7 days; no future predicted menus are used.
                for m,base in raw.items():
                    assoc=[]
                    for other in raw:
                        if other==m:continue
                        r=corrmap[s].get((m,other),0)
                        if abs(r)<.3:continue
                        vals=histories[(s,other)]
                        last7=self._mean([v for d,v in vals if d>=cutoff-timedelta(days=6)])
                        prior=self._mean([v for _,v in vals])
                        if prior<2:continue
                        shock=max(-.3,min(.3,(last7-prior)/prior))
                        assoc.append((abs(r),r*shock))
                    assoc.sort(reverse=True)
                    adjust=max(-.10,min(.10,.2*self._mean([v for _,v in assoc[:3]]))) if assoc else 0.
                    active=self.active_promos(s,m,day)
                    empirical,observations=promo_effect[(s,m)]
                    promo_factor=(empirical*sc.promotion_multiplier if active else 1.)
                    demand=max(0,base*(1+adjust)*promo_factor*sc.demand_multiplier)
                    bymenu[(day,s,m)]=demand
                    if active and offset==0:
                        uplifts.append({'store_id':s,'menu_id':m,'promo_type':active[0][4],
                                        'observed_promo_days':observations,
                                        'estimated_uplift':round(empirical,3),
                                        'scenario_multiplier':sc.promotion_multiplier,
                                        'applied_factor':round(promo_factor,3),
                                        'note':'행사 일정은 사전 공지되었다고 가정; 미래 판매 실적은 사용하지 않음'})
                    share_key=(s,m,day.weekday())
                    if share_key not in shares_cache:
                        shares_cache[share_key]=self._hour_share(s,m,day.weekday(),cutoff,
                                            window=int(params["hour_profile_days"]),
                                            pseudo=float(params["hour_pseudo"]))
                    shares=shares_cache[share_key]
                    for h,share in shares.items():
                        byhour[(day,s,m,h)] = demand*share
                    for i,q in self.e.bom[m].items():
                        byitem[(day,s,i)] = byitem.get((day,s,i),0)+demand*q
                for i in self.e.items:byitem.setdefault((day,s,i),0.)
        return bymenu,byitem,byhour,{'store_profiles':profiles,'related_menus':links_by_store,
                                     'promotion_effects':uplifts,
                                     'method':'과거정보 기반 수요 예측 + 프로모션·메뉴 연관 + 학습된 일별 가중치 및 시간별 분포',
                                     'calibration':{'profile':getattr(sc,'forecast_profile','protective'), 'baseline':params}}
