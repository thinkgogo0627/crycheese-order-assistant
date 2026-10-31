from collections import defaultdict
from copy import deepcopy
from datetime import date, timedelta
from types import SimpleNamespace
from pathlib import Path
import sys
import numpy as np
import pytest
from app.lot_projection import project_lot_usage
from app.engine import Scenario
from app.main import ENGINE

D=date(2026,9,1)


def toy():
    return SimpleNamespace(stores={'S01':{}},items={'bun':{'shelf_life_days':3},'patty':{'shelf_life_days':5}},
        menus={'burger':{}},margin={'burger':5},bom={'burger':{'bun':1,'patty':1}})


def row(q,expiry,lot,receipt=D):return dict(qty=q,expiry=expiry,receipt_date=receipt,lot=lot)


def test_other_ingredient_shortage_prevents_false_lot_depletion():
    lots={('S01','bun'):[row(10,D,'bun-old')]}
    copy=deepcopy(lots)
    result=project_lot_usage(toy(),D,lots,{}, {(D,'S01','burger'):10})['S01','bun'][0]
    assert result['expected_used_qty']==0 and result['expected_expiry_qty']==10
    assert lots==copy


def test_receipts_fefo_last_use_day_and_full_lot_balance():
    lots={('S01','bun'):[row(5,D,'first'),row(7,D+timedelta(days=1),'second')],
          ('S01','patty'):[row(4,D+timedelta(days=4),'patty')]}
    arrivals={D:[dict(store='S01',item='patty',qty=100)],
              D+timedelta(days=1):[dict(store='S01',item='patty',qty=10)]}
    demand={(D,'S01','burger'):10,(D+timedelta(days=1),'S01','burger'):6}
    rows=project_lot_usage(toy(),D,lots,arrivals,demand)['S01','bun']
    assert [(r['expected_used_qty'],r['expected_expiry_qty']) for r in rows]==[(4,1),(6,1)]
    for r in rows:
        assert r['current_qty']==r['expected_used_qty']+r['expected_expiry_qty']+r['remaining_after_horizon']
        for day in r['daily']:
            assert day['opening_qty']==day['expected_used_qty']+day['expected_expiry_qty']+day['closing_qty']


def test_receipt_tie_break_and_duplicate_lot_ids_remain_separate():
    lots={('S01','bun'):[row(4,D,'same',D),row(4,D,'same',D-timedelta(days=1))],
          ('S01','patty'):[row(4,D+timedelta(days=4),'p')]}
    rows=project_lot_usage(toy(),D,lots,{}, {(D,'S01','burger'):4})['S01','bun']
    assert [r['expected_used_qty'] for r in rows]==[0,4]


def test_api_expiry_quantities_and_shared_morning_snapshot():
    assert Scenario().transfer_cost==0
    p=ENGINE.plan(Scenario(as_of=date(2026,10,1),store_id='S01',transfer_cost=0))
    assert p['all_alerts']
    for a in p['all_alerts']:
        if a['type']!='expiry':continue
        assert a['expiring_qty']==pytest.approx(a['expected_use_before_expiry_qty']+a['expected_expiry_qty'])
        assert a['expiring_qty']==pytest.approx(sum(l['current_qty'] for l in a['lots']))
        assert all(l['expected_expiry_qty']>=0 for l in a['lots'])
    ingredients={r['ingredient_id']:r for r in p['ingredients']}
    assert ingredients['I020']['current_stock']==33
    assert ingredients['I020']['opening_stock']==9
    assert ingredients['I020']['received_today']==24
    for r in ingredients.values():
        assert r['current_stock']==pytest.approx(r['opening_stock']+r['received_today'],abs=.11)


sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools/waste_refinement'))
from study import Audit, Lot, projection, DiagnosticPolicy, EnginePolicy


def test_transfer_moves_batch_identity_and_balance_without_cost():
    W=SimpleNamespace(INGS=['I009'],unit_cost_t=np.ones((3,1)))
    audit=Audit(W,None);lot=audit.new(1,0,2,10,0,'regular')
    lot[1]-=4;received=audit.move(lot,4,1,9,1,0,0)
    assert received.batch==lot.batch and received[0]==lot[0]
    audit.consume(received,4,2,0,0,'used');received[1]=0
    audit.finish([[[received]],[[lot]],[[]]],None)
    assert audit.max_balance_error==0


def test_remaining_hour_forecast_does_not_use_today_or_future_actuals():
    H=np.ones((3,1,8,24));W=SimpleNamespace(H=H,MENUS=['m'])
    policy=SimpleNamespace(ensure_forecast=lambda d:({(date(2026,1,6),'S01','m'):24},{}))
    a=Audit(W,policy);expected=a.remaining(5,12,0,observed=np.array([9.]))
    W.H[:,:,5:,:]=9999
    b=Audit(W,policy);actual=b.remaining(5,12,0,observed=np.array([9.]))
    np.testing.assert_allclose(expected,actual)
    np.testing.assert_allclose(actual,[20.]) # observed9 +11remaining hourly units


def test_guard_projection_does_not_count_pending_receipt_twice():
    shortage,waste=projection([Lot(2,5,'a')],{0:100,1:4},[4,4,2],0,3)
    np.testing.assert_allclose(shortage,[0,0,1])
    assert sum(waste.values())==0


@pytest.mark.parametrize('original,expected',[(2,2),(3,2)])
def test_one_pack_cut_respects_supplier_minimum_and_component_balance(monkeypatch,original,expected):
    monkeypatch.setattr(EnginePolicy,'order',lambda *args,**kwargs:{0:original})
    p=DiagnosticPolicy(SimpleNamespace(line_need=lambda *args:{}),'trim_one')
    p.W=SimpleNamespace(INGS=['I009'],pack=np.array([10.]),shelf=np.array([5]),moq_units=np.array([1]),
        sup={'sup':{'moq':100.}},price=np.ones((273,1))*60,
        arrival=lambda sid,d:d+1,next_order_day=lambda sid,d:d+2)
    p.demand=lambda d,s,i,n=14,mult=1.:np.zeros(n)
    p.last_lines['S02','I009']=dict(q=original,short=0.,safety_topup=original*10-3,need=10.,ss=30.,
        left=0.,stock=0.,gap=original*10-3)
    order=p.order(31,1,'sup',[0],[[]],[{}],np.zeros((1,31)))
    assert order=={0:expected}
    assert sum(order.values())*60>=100
    r=p.info[31,1,0]
    assert sum(r[k] for k in ('shortage_component','safety_component','rounding_component','minimum_component'))==expected*10
