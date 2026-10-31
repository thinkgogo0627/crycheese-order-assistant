from types import SimpleNamespace

from app.features.hub.planner import Planner


def check(lines, emergency=False):
    planner = SimpleNamespace(data=SimpleNamespace(suppliers={'SUP_A': {'minimum': 100000}}))
    Planner.minimum_check(planner, lines, emergency)


def line(cost):
    return {'units': 1, 'supplier': 'SUP_A', 'order_date': '2026-10-01', 'cost': cost, 'status': 'DRAFT'}


def test_valid_recommendations_publish_minimum_for_quantity_edits():
    rows = [line(60000), line(60000)]
    check(rows)
    assert all(row['minimum_amount'] == 100000 for row in rows)
    assert all(row['order_total'] == 120000 for row in rows)
    assert all(row['status'] == 'DRAFT' for row in rows)


def test_exact_threshold_and_under_minimum_keep_existing_decision():
    exact = [line(100000)]
    check(exact)
    assert exact[0]['status'] == 'DRAFT'
    below = [line(99999)]
    check(below)
    assert below[0]['status'] == 'MIN_AMOUNT_REVIEW'


def test_emergency_orders_have_no_regular_minimum():
    rows = [line(100)]
    check(rows, emergency=True)
    assert rows[0]['minimum_amount'] == 0
    assert rows[0]['status'] == 'DRAFT'
