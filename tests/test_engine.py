from copy import deepcopy
from datetime import date, timedelta

import pandas as pd
from fastapi.testclient import TestClient
from app.main import app, ENGINE, DATA
from app.engine import Engine, Scenario, MODE_NAMES

client = TestClient(app)


def plan(**kw):
    r = client.post('/api/plan', json=kw)
    assert r.status_code == 200, r.text
    return r.json()


def test_web_and_health():
    assert client.get('/').status_code == 200
    assert client.get('/dashboard').status_code == 200
    assert '원본 CSV' in client.get('/dashboard').text
    assert client.get('/health').json()['ok'] is True
    assert client.get('/api/backtest').status_code == 200


def test_plan_structure_constraints_and_reasons():
    p = plan(as_of='2026-10-01', store_id='S01')
    assert len(p['comparison']) == len(MODE_NAMES) == 4
    assert p['recommended_mode'] == 'independent_transfer'
    assert {c['mode'] for c in p['comparison'] if c['assumption']} == {'pooled', 'shared'}
    assert len(p['ingredients']) == 22 and len(p['forecast_days']) == 7
    assert p['all_orders'], '10/1은 두 공급사 모두 발주일'
    for o in p['all_orders']:
        assert o['store_id'] in ENGINE.stores                       # 매장별 발주서 (통합 아님)
        assert o['order_qty'] >= ENGINE.items[o['ingredient_id']]['min_order_qty']
        assert abs(sum(o['allocated'].values()) - o['use_qty']) <= 0.11
        assert o['reason'] and '→' in o['reason']
        assert o['arrival_date'] == '2026-10-02'
    for c in p['comparison']:
        assert 0 <= c['fill_rate'] <= 100.001 and c['purchase_cost'] >= 0


def test_supplier_minimum_is_met_or_deferred():
    for d in ['2026-07-15', '2026-08-20', '2026-09-10', '2026-10-01']:
        p = plan(as_of=d, store_id='S03', safety_alpha=1.2)
        by = {}
        for o in p['all_orders']:
            by[(o['store_id'], o['supplier_id'])] = by.get((o['store_id'], o['supplier_id']), 0) + o['amount']
        for (s, sup), amt in by.items():
            assert amt >= float(ENGINE.suppliers[sup]['min_order_amount'])


def test_holiday_and_weekday_effects_in_forecast():
    p = plan(as_of='2026-10-01', store_id='S01')
    days = {x['date']: x for x in p['forecast_days']}
    assert days['2026-10-03']['holiday'] == '개천절'
    assert days['2026-10-03']['total'] < 0.7 * days['2026-10-02']['total']   # 오피스 상권 공휴일 감소
    assert p['model']['store_dow_index']['일'] < p['model']['store_dow_index']['목']


def test_dead_stock_transfer_after_menu_discontinued():
    # S02는 치킨버거 판매를 7/31에 중단 → 남은 치킨 패티(I004)를 쓸 수 있는 S01로 이동 추천
    p = plan(as_of='2026-08-05', store_id='S02')
    assert any(a['type'] == 'deadstock' and a['item'] == 'I004' for a in p['alerts'])
    moves = [(t['from_store'], t['to_store'], i['ingredient_id'], i['purpose']) for t in p['transfers'] for i in t['items']]
    assert ('S02', 'S01', 'I004', '폐기 방지') in moves


def test_morning_transfer_preserves_lot_identity_and_conservation():
    sc = Scenario(as_of=date(2026, 9, 10), transfer_minutes=30, transfer_cost=100)
    item = 'I017'; day = sc.as_of
    lots = {(s, i): [] for s in ENGINE.stores for i in ENGINE.items}
    lots['S01', item] = [{'qty': 1000., 'expiry': day + timedelta(days=2), 'lot': 'DEMOLOT'}]
    f = {}
    for s in ENGINE.stores:
        f[(day, s, item)] = {'S01': 100., 'S02': 350., 'S03': 0.}[s]
        f[(day + timedelta(days=1), s, item)] = {'S01': 100., 'S02': 0., 'S03': 0.}[s]
    result = {'trip_count': 0, 'transport_cost': 0, 'transfers': [], 'warnings': []}
    ENGINE.transfers_day(sc, day, lots, f, result)
    assert result['trip_count'] == 1 and result['transfers'][0]['arrive'] == '09:30'
    assert all(x['lot'] == 'DEMOLOT' for x in lots['S02', item])
    assert abs(sum(l['qty'] for s in ['S01', 'S02'] for l in lots[s, item]) - 1000) < 1e-6
    assert ENGINE.count(lots, ('S01', item), day) >= 100
    assert ENGINE.count(lots, ('S02', item), day) <= 350 + 1e-6      # 필요량보다 많이 보내지 않음


def test_uneconomic_trip_not_executed_and_no_lot_mutation():
    day = date(2026, 9, 10)
    sc = Scenario(as_of=day, transfer_cost=1000000)
    lots = {(s, i): [] for s in ENGINE.stores for i in ENGINE.items}
    lots['S01', 'I017'] = [{'qty': 1000., 'expiry': day + timedelta(days=1), 'lot': 'lot1'}]
    original = deepcopy(lots)
    demand = {(day, 'S01', 'I017'): 100., (day, 'S02', 'I017'): 200.}
    r = {'trip_count': 0, 'transport_cost': 0, 'transfers': [], 'warnings': []}
    ENGINE.transfers_day(sc, day, lots, demand, r)
    assert lots == original and r['trip_count'] == 0


def test_decision_does_not_peek_future_sales():
    sc = Scenario(as_of=date(2026, 9, 10))
    alt = dict(DATA)
    sales = DATA['09_sales'].copy()
    sales.loc[sales['date'] >= sc.as_of.isoformat(), 'demand_qty'] = 9999
    alt['09_sales'] = sales
    E2 = Engine(alt)
    assert ENGINE.forecasts(sc) == E2.forecasts(sc)
    a = ENGINE.plan(sc); b = E2.plan(sc)
    assert [(o['ingredient_id'], o['order_qty']) for o in a['all_orders']] == [(o['ingredient_id'], o['order_qty']) for o in b['all_orders']]
