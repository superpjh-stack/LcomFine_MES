"""경영 읽기 모델 분리 전후의 0·미수집·방향별 목표·전기 비교 계약."""
from datetime import date
from decimal import Decimal as D

import pytest

from lcomfine.app import dashboard, management


def target(key, direction, value, low=None, high=None):
    return {'metric_key': key, 'metric_name': key, 'direction': direction,
            'target_value': value, 'range_min': low, 'range_max': high}


def test_attainment_preserves_direction_deduplication_and_rounding(monkeypatch):
    rows = [target('high', '높을수록 좋음', D(100)), target('high', '높을수록 좋음', D(200)),
            target('low', '낮을수록 좋음', D(10)), target('range', '범위 내 정상', D(5), D(4), D(6)),
            target('zero', '높을수록 좋음', D(0)), target('missing', '높을수록 좋음', D(10))]
    monkeypatch.setattr(dashboard.conn, 'q', lambda *args: rows)
    result = dashboard._target_attainment(date(2026, 1, 1), date(2026, 1, 31),
                                         {'high': D(120), 'low': D(20), 'range': D(5), 'zero': D(0)})
    assert result['value'] == D('90.0')
    assert result['available'] is True
    assert [c['attainment'] for c in result['contributors']] == [D('120.0'), D('50.0'), D('100.0')]


def test_no_measurable_targets_stays_unavailable(monkeypatch):
    monkeypatch.setattr(dashboard.conn, 'q', lambda *args: [target('low', '낮을수록 좋음', D(10))])
    assert dashboard._target_attainment(date(2026, 1, 1), date(2026, 1, 31), {'low': D(0)}) == {
        'value': None, 'available': False, 'contributors': []}


def test_executive_previous_preserves_zero_and_availability():
    current = {'executive': {'hero_kpis': [
        {'key': 'amount', 'value': D(0), 'availability': '수집'},
        {'key': 'profit', 'value': None, 'availability': '연계 전'}]}}
    previous = {'executive': {'hero_kpis': [{'key': 'amount', 'value': D(5)}, {'key': 'profit', 'value': D(4)}]}}
    assert dashboard.enrich_executive(current, previous) is current
    a, p = current['executive']['hero_kpis']
    assert a['delta'] == D(-5) and a['previous'] == D(5) and a['availability'] == '수집'
    assert p['delta'] is None and p['availability'] == '연계 전'


@pytest.mark.parametrize('op,observed,expected', [
    ('gt', 5, False), ('gte', 5, True), ('lt', 5, False), ('lte', 5, True),
    ('outside', 5, False), ('outside', 10, False), ('outside', 11, True)])
def test_threshold_boundaries(op, observed, expected):
    assert management._triggered({'compare_op': op, 'value_min': D(5), 'value_max': D(10)}, D(observed)) is expected


def test_comparison_keeps_zero_target_and_missing_distinct():
    metric = {'direction': '높을수록 좋음'}
    result = management.compare(metric, D(0), {'target_value': D(0)})
    assert result == {'actual': D(0), 'status': '정상', 'attainment': None, 'variance': D(0)}
    assert management.compare(metric, None, None)['status'] == '미수집'
    assert management.compare(metric, D(0), None)['status'] == '목표 없음'


@pytest.mark.parametrize('amount,availability', [(None, '연계 전'), (D(0), '수집')])
def test_executive_model_builds_without_db_and_preserves_financial_availability(amount, availability):
    from lcomfine.app.dashboard_models import build_executive
    data = {f'RPT-0{s}0': {'kpis': [], 'series': {}, 'tables': {}} for s in range(1, 8)}
    result = build_executive(data, {'value': None, 'available': False, 'contributors': []},
                             {'order_amount': amount, 'shipment_amount': amount, 'actual_cost': amount}, [], [])
    hero = {k['key']: k for k in result['hero_kpis']}
    assert hero['order_amount']['value'] == amount
    assert hero['order_amount']['availability'] == availability
    assert hero['profit']['value'] == amount
    assert len(result['flow']) == 7
    assert all(stage['status'] == '미수집' for stage in result['flow'])
    assert result['causes'] == {'cumulative': [], 'due_forecast': [], 'quality_pareto': []}
