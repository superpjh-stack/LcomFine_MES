"""공용 조회 분리 시 선택값 거부와 호출자 트랜잭션·잠금 계약을 보존한다."""
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from lcomfine.app import lookups, shipment_queries as shp


@pytest.mark.parametrize('row,reason', [
    (None, '없는 위치입니다: 7'),
    ({'use_yn': 'N', 'wh_use': 'Y', 'location_code': 'L'}, '사용 중지된 위치입니다: L'),
    ({'use_yn': 'Y', 'wh_use': 'N', 'location_code': 'L'}, '사용 중지된 위치입니다: L'),
])
def test_location_rejects_missing_or_inactive(monkeypatch, row, reason):
    monkeypatch.setattr(lookups.conn, 'q1', lambda *args: row)
    with pytest.raises(HTTPException) as error:
        lookups.location_in('7')
    assert error.value.status_code == 422
    assert error.value.detail['fields'] == [{'name': '위치', 'reason': reason}]


@pytest.mark.parametrize('status', ['취소', '완료'])
def test_work_order_rejects_closed(monkeypatch, status):
    row = {'id': 7, 'work_order_no': 'WO-TEST', 'status': status}
    monkeypatch.setattr(lookups.conn, 'q1', lambda *args: row)
    with pytest.raises(HTTPException) as error:
        lookups.work_order_in('7')
    assert error.value.status_code == 422
    assert error.value.detail['fields'][0]['reason'] == f'{status}된 지시입니다: WO-TEST'


def test_optional_location_avoids_db(monkeypatch):
    query = Mock(side_effect=AssertionError('불필요한 DB 조회'))
    monkeypatch.setattr(lookups.conn, 'q1', query)
    assert lookups.location_in(None, required=False) is None
    query.assert_not_called()


def test_item_allows_only_original_inactive_selection():
    row = {'id': 7, 'item_type': '제품', 'use_yn': 'N', 'item_code': 'ITEM'}
    cur = Mock(); cur.fetchone.return_value = row
    assert lookups.item_choice(cur, 7, allow_inactive_id=7) == row
    with pytest.raises(HTTPException) as error:
        lookups.item_choice(cur, 7)
    assert error.value.status_code == 422


def test_existing_row_uses_callers_lock():
    cur = Mock(); cur.fetchone.return_value = {'id': 7}
    assert lookups.exists_or_404(cur, 'item', 7) == {'id': 7}
    sql, args = cur.execute.call_args.args
    assert sql.endswith('for update') and args == (7,)
    cur.fetchone.return_value = None
    with pytest.raises(HTTPException) as error:
        lookups.exists_or_404(cur, 'item', 7)
    assert error.value.status_code == 404


def test_shipment_stock_locks_in_sorted_unique_order():
    cur = Mock(); cur.fetchall.return_value = [{'id': 2}, {'id': 9}]
    assert shp._lock_stock(cur, [9, 2, 9]) == {2: {'id': 2}, 9: {'id': 9}}
    sql, args = cur.execute.call_args.args
    assert args == ([2, 9],)
    assert 'order by s.id' in sql and 'for update of s' in sql


def test_judgements_use_callers_transaction(monkeypatch):
    query = Mock(side_effect=AssertionError('호출자 트랜잭션 밖 조회'))
    monkeypatch.setattr(shp.conn, 'q', query)
    cur = Mock(); cur.fetchall.return_value = [{'lot_id': 7, 'result': '합격', 'seq': 2}]
    assert shp._judgements([7, 7], cur)[7]['seq'] == 2
    sql, args = cur.execute.call_args.args
    assert args == ([7],)
    assert 'with recursive up' in sql and 'up.depth, q.seq desc' in sql
    query.assert_not_called()


def test_empty_shipment_lookups_avoid_db(monkeypatch):
    query = Mock(side_effect=AssertionError('불필요한 DB 조회'))
    monkeypatch.setattr(shp.conn, 'q', query)
    assert shp._judgements([]) == {}
    assert shp._order_lines([]) == {}
    query.assert_not_called()
