"""Hourly as-of POS replay and 30-minute inventory reallocation recommendations.

Never reads after-decision sales. Historical replay uses *fulfilled* sales
(qty - cancel_qty); demand_qty and lost_qty are retrospective labels, not
live POS fields. Lots are reconstructed from prior EOD and assumed 08:00
receipts, and must NOT be represented as verified real-time inventory.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import date, timedelta
from math import floor

from app.core.errors import AppError

def HTTPException(status_code, detail):
    return AppError("invalid_hourly_input", detail, status_code)
from pydantic import BaseModel, Field

from .runtime import Scenario
from .rolling import CumulativeHourlyForecaster
from .calibration import rolling_params
from typing import Literal


class LiveSale(BaseModel):
    """A POS-confirmed count for one *completed* clock hour."""
    store_id: str
    menu_id: str
    hour: int = Field(ge=0, le=23)
    sold_qty: float = Field(ge=0, allow_inf_nan=False)


class IntradayScenario(BaseModel):
    forecast_profile: Literal['original','balanced','protective'] = 'protective'
    as_of: date = date(2026, 9, 10)
    store_id: str = 'S01'
    decision_time: str = Field('11:00', pattern=r'^([01][0-9]|2[0-3]):00$')
    horizon_hours: int = Field(4, ge=1, le=10)
    demand_multiplier: float = Field(1., gt=0, le=5, allow_inf_nan=False)
    delay_days: int = Field(0, ge=0, le=14)
    transfer_cost: float = Field(0, ge=0, le=100000, allow_inf_nan=False)
    promotion_multiplier: float = Field(1., ge=.5, le=2.5)
    adjustment_strength: float | None = Field(None, ge=0, le=1)
    minimum_avoided_menu_qty: float = Field(1., ge=0, le=20)
    # If provided, this is the ENTIRE confirmed sales snapshot up to decision_time;
    # never mix it with or silently fall back to historical sales for that day.
    live_sales: list[LiveSale] | None = None


def _minute(x: int) -> str:
    return f'{x//60:02d}:{x%60:02d}'


def _cap(x, low, high):
    return min(high,max(low,x))


class HourlyPlanner:
    def __init__(self, engine):
        self.e=engine
        # Read once; row-level held-out demand_qty/lost_qty must NEVER be used
        # as contemporaneously observable signals.
        self.sales=engine.data['09_sales']

    def _actual_sales(self,sc,now):
        e=self.e; out=defaultdict(float)
        if sc.live_sales is not None:
            seen=set()
            for x in sc.live_sales:
                key=(x.store_id,x.menu_id,x.hour)
                if key in seen: raise HTTPException(422,"POS 스냅샷에 중복 매장·메뉴·시간이 있습니다.")
                seen.add(key)
                if x.store_id not in e.stores or x.menu_id not in e.menus:
                    raise HTTPException(422,'실시간 매장 또는 메뉴 ID가 올바르지 않습니다.')
                if x.hour>=now//60 or x.hour<int(e.stores[x.store_id]['open_hour']) or x.hour>=int(e.stores[x.store_id]['close_hour']):
                    raise HTTPException(422,'완전히 종료된 영업 시간대의 POS 판매량만 입력할 수 있습니다.')
                out[x.store_id,x.menu_id,x.hour]+=x.sold_qty
            return out,'live_pos_snapshot'
        if sc.as_of>e.last_history_day:
            raise HTTPException(422,'이 날짜의 시간별 실판매 기록은 없습니다. live_sales로 해당 시점의 확정 실판매 데이터를 제공하세요.')
        rows=self.sales[(self.sales['date']==sc.as_of.isoformat()) &
                        (self.sales['hour']<now//60)]
        for r in rows.itertuples(index=False):
            # qty is fulfilled before cancellations, not latent demand_qty.
            out[r.store_id,r.menu_id,int(r.hour)]+=max(0.,float(r.qty)-float(r.cancel_qty))
        return out,'historical_pos_replay'

    def _make_forecaster(self, sc, fhour, store):
        e=self.e;day=sc.as_of
        baseline={(m,h):fhour.get((day,store,m,h),0.)
                  for m in e.menus for h in range(int(e.stores[store]['open_hour']),
                                                 int(e.stores[store]['close_hour']))}
        cfg=rolling_params(sc.forecast_profile)
        if sc.adjustment_strength is not None:
            cfg['strength']=sc.adjustment_strength
        return CumulativeHourlyForecaster(
            store_id=store, day=day.isoformat(), menus=list(e.menus), baseline=baseline,
            open_hour=int(e.stores[store]['open_hour']),
            close_hour=int(e.stores[store]['close_hour']),
            **cfg,
        )

    def _adjust(self, sc, now, fhour, actual):
        """Share one cumulative same-day forecaster with the rolling UI/API."""
        e=self.e;day=sc.as_of
        updated=dict(fhour);snapshots=[]
        for store in e.stores:
            model=self._make_forecaster(sc,fhour,store)
            for h in range(model.open_hour,min(now//60,model.close_hour)):
                model.observe_completed_hour(
                    h, {m:actual.get((store,m,h),0.) for m in e.menus})
            # All hours beyond the decision time share today's cumulative signal;
            # the hourly baseline already captures the usual lunch/dinner shape.
            for h in range(max(now//60,model.open_hour),model.close_hour):
                values=model.forecast_hour(h)['predicted_by_menu']
                for m,val in values.items():
                    key=(day,store,m,h)
                    if key in updated:updated[key]=val
            snapshots.append({**model.observed_summary(),
                              'trade_area':e.stores[store]['trade_area']})
        return updated,snapshots

    def rolling(self,sc:IntradayScenario):
        """Replay one POS hour at a time, returning only causal next-hour forecasts.

        At 11:00 S01 sees 10:00-10:59 confirmed sales; at 12:00 it sees
        10:00-11:59; at 13:00 it sees 10:00-12:59. At no stage is a later
        observation fed to an earlier prediction.
        """
        e=self.e;day=sc.as_of
        if sc.store_id not in e.stores:
            raise HTTPException(422,'알 수 없는 매장입니다.')
        if not date(2026,7,1)<=day<=date(2026,10,1):
            raise HTTPException(422,'현재 데모는 2026-07-01~2026-10-01 범위만 지원합니다.')
        now=int(sc.decision_time[:2])
        base=Scenario(as_of=day,store_id=sc.store_id,horizon_days=2,
                      demand_multiplier=sc.demand_multiplier,
                      promotion_multiplier=sc.promotion_multiplier,transfer_cost=0,
                      forecast_profile=sc.forecast_profile)
        _,_,fhour,_=e.forecast_bundle(base)
        actual,source=self._actual_sales(sc,now*60)
        model=self._make_forecaster(sc,fhour,sc.store_id)
        timeline=[]
        if now>=model.open_hour:
            for h in range(model.open_hour,min(now,model.close_hour-1)+1):
                if h>model.open_hour:
                    prev=h-1
                    model.observe_completed_hour(prev,{m:actual.get((sc.store_id,m,prev),0.)
                                                       for m in e.menus})
                pred=model.forecast_hour(h)
                # The predicted menu mix has its own ingredient footprint.
                required=defaultdict(float)
                for m,q in pred['predicted_by_menu'].items():
                    for item,per in e.bom[m].items():required[item]+=q*per
                timeline.append({
                    'hour':pred['predicted_hour'],
                    'observed_hours':pred['based_on_completed_hours'],
                    'observed_sold_cumulative':pred['observed_sold_cumulative'],
                    'baseline_completed_hours':pred['baseline_completed_hours'],
                    'adjustment_factor':pred['adjustment_factor'],
                    'baseline_next_hour':pred['baseline_next_hour'],
                    'predicted_next_hour':pred['predicted_next_hour'],
                    'top_menus':sorted([
                        {'menu_id':m,'menu':e.menus[m]['menu_name'],
                         'baseline':round(pred['baseline_by_menu'][m],3),
                         'predicted':round(q,3)}
                        for m,q in pred['predicted_by_menu'].items()],
                        key=lambda r:r['predicted'],reverse=True)[:5],
                    'ingredient_requirements':sorted([
                        {'ingredient_id':i,'ingredient':e.items[i]['ingredient_name'],
                         'qty':round(q,2),'unit':e.items[i]['use_unit']}
                        for i,q in required.items() if q>0],
                        key=lambda r:r['qty'],reverse=True),
                })
        return {
            'as_of':day.isoformat(),
            'store_id':sc.store_id,
            'decision_time':sc.decision_time,
            'data_source':source,
            'trade_area':e.stores[sc.store_id]['trade_area'],
            'timeline':timeline,
            'note':('시간 구간은 시작 시각으로 표기: 10:00 = 10:00~10:59. '
                    '11:00 예측에는 종료된 10시 실적까지만, 12:00 예측에는 10~11시 실적까지만 사용. '
                    '현재 예측은 확정 실판매 관측값 기반의 수요 보정이며, 품절로 판매 못 한 수요는 실시간 관측되지 않음.'),
        }

    def _reconstruct_lots(self,sc,now,actual):
        e=self.e; day=sc.as_of
        # We start from *yesterday* EOD, never from today's closing inventory.
        base=Scenario(as_of=day,store_id=sc.store_id,horizon_days=1,
                      demand_multiplier=sc.demand_multiplier,transfer_cost=0,delay_days=sc.delay_days)
        lots,arrivals,issues=e.initial(base)
        lots=deepcopy(lots)
        for (s,i),rows in lots.items():
            lots[(s,i)]=[r for r in rows if r['expiry']>=day]
        for row in arrivals.get(day,[]):
            i=row['item'];life=int(e.items[i]['shelf_life_days'])
            lots[(row['store'],i)].append({'qty':row['qty'],
                'expiry':day+timedelta(days=life-1),'lot':'scheduled_08:00'})
        discrepancies=[]
        for h in range(now//60):
            for s in e.stores:
                if not(int(e.stores[s]['open_hour'])<=h<int(e.stores[s]['close_hour'])):continue
                for m in e.menus:
                    fulfilled=actual.get((s,m,h),0.)
                    if fulfilled<=0:continue
                    for i,per in e.bom[m].items():
                        consumed=e.burn(lots,(s,i),fulfilled*per)
                        if fulfilled*per-consumed>1e-5 and len(discrepancies)<20:
                            discrepancies.append({'store_id':s,'ingredient_id':i,
                                'hour':_minute(h*60),'unreconciled_qty':round(fulfilled*per-consumed,2)})
        return lots,issues,discrepancies

    def _required(self,fhour,day,s,i,start,end):
        e=self.e
        total=0.
        for tick in range(start,end,30):
            if not(int(e.stores[s]['open_hour'])*60<=tick<int(e.stores[s]['close_hour'])*60):continue
            h=tick//60
            total+=.5*sum(fhour.get((day,s,m,h),0.)*e.bom[m].get(i,0.) for m in e.menus)
        return total

    def _future_sim(self,day,now,end,fhour,lots,transfers=None):
        e=self.e
        inventory=deepcopy(lots)
        arrivals=defaultdict(list)
        for trip in transfers or []:
            for piece in trip['_moves']:
                # Deduct source immediately; this is a planning simulation.
                source=(trip['from_store'],piece['item'])
                leftover=piece['qty']
                for row in sorted(inventory[source],key=lambda l:l['expiry']):
                    if row['lot']==piece['lot'] and row['expiry']==piece['expiry']:
                        use=min(leftover,row['qty']);row['qty']-=use;leftover-=use
                        if leftover<1e-8:break
                if leftover>1e-6:raise RuntimeError('시뮬레이션 이동량이 현재 가용 lot을 초과')
                arrivals[trip['_arrive']].append({'to':trip['to_store'],**piece})
        lost=0.;potential=0.;sold=0.
        for tick in range(now,end,30):
            for move in arrivals.pop(tick,[]):
                if move['expiry']>=day:
                    inventory[move['to'],move['item']].append({
                        'qty':move['qty'],'expiry':move['expiry'],'lot':move['lot']})
            for s in e.stores:
                if not(int(e.stores[s]['open_hour'])*60<=tick<int(e.stores[s]['close_hour'])*60):continue
                available={i:e.count(inventory,(s,i),day) for i in e.items}
                pri=[]
                for m in e.menus:
                    req=.5*fhour.get((day,s,m,tick//60),0.)
                    if req<=0:continue
                    food=sum(q*e.unit_cost(i,day) for i,q in e.bom[m].items())
                    pri.append((float(e.menus[m]['virtual_price'])-food,m,req))
                for _,m,req in sorted(pri,reverse=True):
                    feasible=min([req]+[available[i]/q for i,q in e.bom[m].items() if q>0])
                    take=max(0.,min(req,feasible));lost+=req-take;sold+=take;potential+=req
                    for i,q in e.bom[m].items():
                        e.burn(inventory,(s,i),take*q)
                        available[i]-=take*q
        return {'unmet_menu_qty':round(lost,4),'fulfilled_menu_qty':round(sold,4),
                'forecast_menu_qty':round(potential,4)}

    def plan(self,sc:IntradayScenario):
        e=self.e;day=sc.as_of
        if sc.store_id not in e.stores:raise HTTPException(422,'알 수 없는 매장입니다.')
        if not(date(2026,7,1)<=day<=date(2026,10,1)):
            raise HTTPException(422,'현재 데모는 2026-07-01~2026-10-01 범위만 지원합니다.')
        now=int(sc.decision_time[:2])*60
        end=min(now+60*sc.horizon_hours,24*60)
        base=Scenario(as_of=day,store_id=sc.store_id,horizon_days=2,
                      demand_multiplier=sc.demand_multiplier,
                      promotion_multiplier=sc.promotion_multiplier,transfer_cost=0,
                      forecast_profile=sc.forecast_profile)
        _,fitem,fhour,_=e.forecast_bundle(base)
        observed,source=self._actual_sales(sc,now)
        adjusted,signals=self._adjust(sc,now,fhour,observed)
        inventory,issues,discrepancies=self._reconstruct_lots(sc,now,observed)
        no_transfer=self._future_sim(day,now,end,adjusted,inventory)
        # Identify first insufficient half-hour for every ingredient from now.
        risks=[];proposals=[]
        for i in e.items:
            for s in e.stores:
                opening=int(e.stores[s]['open_hour'])*60
                closing=int(e.stores[s]['close_hour'])*60
                if now>=closing:continue
                start=max(now,opening)
                available=e.count(inventory,(s,i),day)
                first=None
                rolling=available
                for tick in range(start,min(end,closing),30):
                    rolling-=self._required(adjusted,day,s,i,tick,tick+30)
                    if rolling<-1e-6:
                        first=tick
                        break
                need=max(0.,self._required(adjusted,day,s,i,start,min(end,closing))-available)
                if first is not None:
                    risks.append({'store_id':s,'ingredient_id':i,'ingredient':e.items[i]['ingredient_name'],
                                  'first_at':_minute(first),'shortfall_use_qty':round(need,2),
                                  'unit':e.items[i]['use_unit']})
                arrive=now+30
                if arrive>=min(end,closing):continue
                # Only shortage *from arrival onwards* can be prevented.
                before=self._required(adjusted,day,s,i,start,max(start,arrive))
                after=self._required(adjusted,day,s,i,max(start,arrive),min(end,closing))
                need_after=max(0.,after-max(0.,available-before))
                if need_after>1e-6:proposals.append((s,i,need_after,first))
        # A donor must cover its own rest-of-day *plus* an explicit next-day
        # buffer. This does not assume all current stock is transferable.
        donors=defaultdict(float)
        next_day=day+timedelta(days=1)
        for s in e.stores:
            for i in e.items:
                current=e.count(inventory,(s,i),day)
                rest=self._required(adjusted,day,s,i,now,24*60)
                buffer=.4*fitem.get((next_day,s,i),0.)
                donors[s,i]=max(0.,current-rest-buffer)
        # Earliest risks first, bundled by route. Proposed amounts will be
        # checked against donor lot availability and prospective menu fill-rate.
        proposals.sort(key=lambda x:(x[3] if x[3] is not None else 10000,-x[2]))
        planned=deepcopy(inventory)
        route=defaultdict(list)
        for dest,i,need,first in proposals:
            for origin in e.stores:
                if origin==dest or need<=1e-6:continue
                give=min(need,donors[origin,i])
                if give<=1e-6:continue
                removed=[];left=give
                for lot in sorted(planned[origin,i],key=lambda r:r['expiry']):
                    if lot['expiry']<day:continue
                    take=min(left,lot['qty'])
                    if take>1e-8:
                        removed.append({'item':i,'qty':take,'expiry':lot['expiry'],'lot':lot['lot']})
                        lot['qty']-=take;left-=take
                    if left<1e-8:break
                actual=give-left
                if actual<=1e-8:continue
                planned[origin,i]=[lot for lot in planned[origin,i] if lot['qty']>1e-8]
                donors[origin,i]-=actual;need-=actual
                route[origin,dest].extend(removed)
        trips=[]
        for (origin,dest),parts in route.items():
            if not parts:continue
            # The simulation runs from now, and only this arrival is usable.
            trips.append({'from_store':origin,'to_store':dest,'_arrive':now+30,
                          '_moves':parts})
        # Remove individually ineffective routes. Zero explicit transport fees
        # are NOT a reason to generate pointless handling work.
        for trip in trips.copy():
            full=self._future_sim(day,now,end,adjusted,inventory,trips)
            reduced=[x for x in trips if x is not trip]
            minus=self._future_sim(day,now,end,adjusted,inventory,reduced)
            if full['unmet_menu_qty'] >= minus['unmet_menu_qty']-1e-6:
                trips=reduced
        with_transfer=self._future_sim(day,now,end,adjusted,inventory,trips)
        avoided=no_transfer['unmet_menu_qty']-with_transfer['unmet_menu_qty']
        # An explicit per-recommendation threshold prevents meaningless 0.08
        # menu movements, even when additional monetary transfer cost is zero.
        if avoided+1e-6<sc.minimum_avoided_menu_qty:
            trips=[];with_transfer=no_transfer;avoided=0.
        display=[]
        for trip in trips:
            agg=defaultdict(float)
            for piece in trip['_moves']:agg[piece['item']]+=piece['qty']
            display.append({'from_store':trip['from_store'],'to_store':trip['to_store'],
                            'depart':_minute(now),'arrive':_minute(now+30),'minutes':30,
                            'trip_cost':sc.transfer_cost,
                            'items':[{'ingredient_id':i,'ingredient':e.items[i]['ingredient_name'],
                                      'qty':round(v,2),'unit':e.items[i]['use_unit']} for i,v in agg.items()]})
        hours=[]
        for h in range(now//60,min(24,(end+59)//60)):
            if not(int(e.stores[sc.store_id]['open_hour'])<=h<int(e.stores[sc.store_id]['close_hour'])):continue
            before=sum(fhour.get((day,sc.store_id,m,h),0.) for m in e.menus)
            after=sum(adjusted.get((day,sc.store_id,m,h),0.) for m in e.menus)
            hours.append({'hour':_minute(h*60),'baseline':round(before,2),'updated':round(after,2)})
        return {'as_of':day.isoformat(),'decision_time':sc.decision_time,'store_id':sc.store_id,
                'data_source':source,'observed_sales_period':'당일 영업 시작~판단시각 직전의 완료된 시간',
                'observed':signals,'hourly_forecast':hours,
                'risks':sorted(risks,key=lambda x:x['first_at']),
                'transfers':display,'without_transfer':no_transfer,'with_transfer':with_transfer,
                'predicted_avoided_lost_menu_qty':round(max(0.,avoided),3),
                'remaining_lost_menu_qty':with_transfer['unmet_menu_qty'],
                'data_issues':issues[:6],'snapshot_discrepancies':discrepancies,
                'assumptions':[
                    '과거 데이터 재생은 현재 시점 이전 완료된 시간의 qty-cancel_qty만 관측. demand_qty/lost_qty는 POS 관측 입력으로 사용하지 않음',
                    'S01/S03는 10시, S02는 11시 개점. 10:00에는 당일 완료 시간 판매 기록이 없어 기본예측 유지',
                    '30분 도착 후에만 재고 사용 가능. 이동비는 입력한 가상 운임이며 실제 계약 조건은 미확인',
                    '실측 현재고가 없으므로 전날 lot 마감재고+08시 입고 가정-확정 판매 BOM 소진으로 재구성. 실물 조정/당일 폐기는 미확인',
                    '판매 데이터는 시간별이므로 앞으로 30분별 수요는 시간당 예측량을 반으로 나눈 근사',
                    f'수요 보정 프로필 {sc.forecast_profile}: 7월 검증 선정, 8~9월 탐색 평가(반복 열람된 기간). 경제적 품절·폐기 비용 최적화는 아직 수행하지 않음',
                    '이동은 권고안만 생성하고 주문/재고/차량을 실제 변경하지 않음. 직원 시간, 냉장 운송/보관 가능성은 추가 검증 필요',
                    '공급사 직배송·기존 발주 등 당일 입고는 오전 8시 도착 가정. 30분 이동은 입고확정 처리가 아님',
                    '운송비의 경제적 최적화는 미구현. 조치 남발을 피하도록 기본값은 예상 미판매 메뉴 1개 이상 개선되는 이동만 추천',
                ]}
