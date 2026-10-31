"""Private compatibility helpers for hourly forecasts; never replaces app.engine."""
from collections import defaultdict
from datetime import date, timedelta
from functools import lru_cache
from typing import NamedTuple
import pandas as pd
from app.core import data as source
from app.core.errors import AppError
from .demand import DemandModel

def HTTPException(status_code, detail):
    return AppError("invalid_hourly_input", detail, status_code)

class Scenario(NamedTuple):
    as_of: date
    store_id: str = 'S01'
    horizon_days: int = 2
    demand_multiplier: float = 1.0
    promotion_multiplier: float = 1.0
    forecast_profile: str = 'protective'
    transfer_cost: float = 0.0
    delay_days: int = 0

class Engine:
    def __init__(self, data: dict[str, pd.DataFrame]):
        self.data = data
        self.stores = {r['store_id']: r for r in data['01_stores'].to_dict('records')}
        self.items = {r['ingredient_id']: r for r in data['03_ingredients'].to_dict('records')}
        self.menus = {r['menu_id']: r for r in data['02_menus'].to_dict('records')}
        self.suppliers = {r['supplier_id']: r for r in data['05_suppliers'].to_dict('records')}
        self.bom = defaultdict(dict)
        for r in data['04_bom'].to_dict('records'):
            self.bom[r['menu_id']][r['ingredient_id']] = float(r['qty_per_menu'])
        self.available = defaultdict(list)
        for r in data['15_menu_availability'].to_dict('records'):
            if r['status'] == '취급' and isinstance(r['start_date'], str):
                self.available[(r['store_id'], r['menu_id'])].append((date.fromisoformat(r['start_date']), date.fromisoformat(r['end_date'])))
        d = data['09_sales'].groupby(['date', 'store_id', 'menu_id'], as_index=False)['demand_qty'].sum()
        self.daily_sales = {(date.fromisoformat(r.date), r.store_id, r.menu_id):float(r.demand_qty) for r in d.itertuples(index=False)}
        self.last_history_day = max(k[0] for k in self.daily_sales)
        self.prices = defaultdict(list)
        for r in data['06_ingredient_price_history'].to_dict('records'):
            self.prices[r['ingredient_id']].append((date.fromisoformat(r['valid_from']),float(r['unit_price'])))
        for xs in self.prices.values(): xs.sort()
        self.lots = data['16_inventory_lots_daily']
        self.pos = data['11_purchase_orders']
        self.receipts = data['12_receipts']
        self.calendar = data['07_calendar']
        self.demand_model = DemandModel(self)


    def price(self, i: str, day: date) -> float:
        rows = self.prices[i]
        return next((p for d,p in reversed(rows) if d<=day),rows[0][1])


    def unit_cost(self, i: str, day:date) -> float:
        return self.price(i,day)/float(self.items[i]['use_qty_per_order_unit'])


    def active(self, s:str, m:str, day:date)->bool:
        for a,b in self.available[(s,m)]:
            if a<=day<=b or (b==self.last_history_day and a<=day and day>b):
                return True
        return False


    @lru_cache(maxsize=24)
    def forecast_bundle(self,sc:Scenario)->tuple[dict,dict,dict,dict]:
        return self.demand_model.generate(sc)


    def initial(self, sc:Scenario)->tuple[dict,dict,list[str]]:
        prev=sc.as_of-timedelta(days=1)
        if prev < date(2026,1,1) or prev>self.last_history_day:
            raise HTTPException(status_code=422,detail='기준일 이전 영업 종료 재고가 없습니다. 2026-01-02~2026-10-01 범위에서 선택하세요.')
        filtered=self.lots[self.lots['date']==prev.isoformat()]
        if filtered.empty: raise HTTPException(422,'입고 묶음별 재고가 없는 기준일입니다.')
        lots=defaultdict(list)
        for r in filtered.itertuples(index=False):
            qty=float(r.remaining_qty)
            if qty>0:
                lots[(r.store_id,r.ingredient_id)].append({'qty':qty,'expiry':date.fromisoformat(r.last_use_date),'lot':str(r.lot_id)})
        issues=[]
        inv=self.data['10_inventory_daily']
        last=inv[inv['date']==prev.isoformat()]
        lot_sums={k:sum(x['qty'] for x in xs) for k,xs in lots.items()}
        for r in last.itertuples(index=False):
            if abs(lot_sums.get((r.store_id,r.ingredient_id),0)-float(r.closing_qty))>0.01:
                issues.append(f'{r.store_id}/{r.ingredient_id} lot 잔량·마감재고 불일치')
        prevpo=self.pos[self.pos['order_date']<sc.as_of.isoformat()].copy()
        rec=self.receipts[self.receipts['receipt_date']<sc.as_of.isoformat()].groupby('po_line_id')['received_qty'].sum().to_dict()
        arrivals=defaultdict(list)
        for r in prevpo.itertuples(index=False):
            qty=float(r.order_qty)-float(rec.get(r.po_line_id,0))
            if qty<=0:continue
            scheduled=max(sc.as_of,date.fromisoformat(r.expected_date)+timedelta(days=sc.delay_days))
            if scheduled>sc.as_of+timedelta(days=sc.horizon_days+9):continue
            amount=qty*float(self.items[r.ingredient_id]['use_qty_per_order_unit'])
            arrivals[scheduled].append({'store':r.store_id,'item':r.ingredient_id,'qty':amount,'pending':True})
        return lots,arrivals,issues


    @staticmethod
    def burn(lots:dict, key:tuple, qty:float, *, consume:bool=True)->float:
        xs=sorted(lots[key],key=lambda x:x['expiry'])
        remaining=qty
        for lot in xs:
            take=min(remaining,lot['qty'])
            if consume:lot['qty']-=take
            remaining-=take
            if remaining<=1e-8:break
        if consume:lots[key]=[l for l in xs if l['qty']>1e-8]
        return qty-max(0,remaining)


    @staticmethod
    def count(lots:dict,key:tuple,day:date)->float:
        return sum(x['qty'] for x in lots[key] if x['expiry']>=day)


TABLES = ('01_stores','02_menus','03_ingredients','04_bom','05_suppliers',
          '06_ingredient_price_history','07_calendar','08_promotions','09_sales',
          '10_inventory_daily','11_purchase_orders','12_receipts','16_inventory_lots_daily',
          '15_menu_availability')

@lru_cache(maxsize=1)
def get_engine():
    tables = {}
    for key in TABLES:
        frame = source.table(key.split('_',1)[1])
        for column in source.DATE_COLS & set(frame.columns):
            frame[column] = frame[column].dt.strftime('%Y-%m-%d')
        tables[key] = frame
    return Engine(tables)
