"""채번 `app/numbering.py` — 형식은 `sys_number_rule` 행에서 오고, 동시에 불러도 번호가 겹치지 않는다 (G-08 · D-05 · D-101).

카운터는 **먼 과거 날짜**(`at=`)의 범위에서만 올리고 끝나면 그 범위의 카운터 행을 지운다 — 오늘의 번호와 다른 사람의 발번을 건드리지 않는다.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytest

from lcomfine.app import numbering
from lcomfine.db import conn

# 테스트마다 다른 날짜 범위를 쓴다 (서로의 카운터를 보지 않게)
AT_FORMAT = datetime(1999, 1, 1, 9, 0)
AT_SERIAL = datetime(1999, 1, 2, 9, 0)
AT_PARALLEL = datetime(1999, 1, 3, 9, 0)
AT_ROLLBACK = datetime(1999, 1, 4, 9, 0)
AT_PEEK = datetime(1999, 1, 5, 9, 0)
AT_KINDS = datetime(1999, 1, 6, 9, 0)


def _scope(kind: str, at: datetime) -> str:
    return conn.q1("""select case when date_format = '' then '' else to_char(%s::timestamptz, date_format) end as s
                        from sys_number_rule where seq_kind = %s""", (at, kind))["s"]


def _drop(kind: str, at: datetime) -> None:
    scope = _scope(kind, at)
    assert scope != "", "날짜 형식이 빈 규칙에서는 이 테스트가 통산 카운터를 건드리게 된다 — 테스트를 고친다"
    conn.x("delete from sys_number_seq where seq_kind = %s and seq_scope = %s", (kind, scope))


@pytest.fixture
def scoped():
    """(kind, at) 를 등록해 두면 테스트 앞뒤로 그 범위의 카운터 행을 지운다."""
    used: list[tuple[str, datetime]] = []

    def use(kind: str, at: datetime) -> datetime:
        _drop(kind, at)
        used.append((kind, at))
        return at

    yield use
    for kind, at in used:
        _drop(kind, at)


def test_rule_rows_exist_for_all_kinds():
    # 설계도의 번호 6종은 그대로이고, 그 뒤에 설계도 밖 확장의 수주 번호(D-418)가 하나 더 있다
    assert numbering.KINDS[:6] == ("JOB", "JOB_LOT", "MAT_LOT", "ROLL", "SHIPMENT", "COA")
    assert numbering.KINDS[6:] == ("SALES_ORDER",)
    for kind in numbering.KINDS:
        row = numbering.rule(kind)
        assert row is not None, f"sys_number_rule 에 {kind} 행 없음 — seed_dev1"
        assert row["seq_kind"] == kind and 1 <= row["seq_digits"] <= 10


def test_format_comes_from_rule_row(scoped):
    """번호 = prefix + to_char(at, date_format) + 0 채운 일련번호 — 코드가 아니라 행이 형식이다."""
    at = scoped("JOB", AT_FORMAT)
    row = numbering.rule("JOB")
    date_part = _scope("JOB", at)
    no = numbering.next("JOB", at=at)
    assert no == f"{row['prefix']}{date_part}{'1'.zfill(row['seq_digits'])}"
    assert no.isascii() and no == no.upper() and all(ch.isalnum() or ch == "-" for ch in no), no   # 바코드에 찍히는 글자


def test_next_is_sequential_and_peek_does_not_consume(scoped):
    at = scoped("ROLL", AT_SERIAL)
    first = numbering.peek("ROLL", at=at)
    assert numbering.peek("ROLL", at=at) == first               # 미리보기는 발번하지 않는다
    a, b, c = (numbering.next("ROLL", at=at) for _ in range(3))
    assert a == first and len({a, b, c}) == 3
    width = numbering.rule("ROLL")["seq_digits"]
    assert [int(n[-width:]) for n in (a, b, c)] == [1, 2, 3]
    assert int(numbering.peek("ROLL", at=at)[-width:]) == 4


def test_concurrent_calls_never_collide(scoped):
    """8 스레드 × 25 번 = 200 번 발번 — 겹치는 번호 0, 빠진 번호 0."""
    at = scoped("MAT_LOT", AT_PARALLEL)

    def take(_):
        return [numbering.next("MAT_LOT", at=at) for _ in range(25)]

    with ThreadPoolExecutor(max_workers=8) as pool:
        numbers = [n for chunk in pool.map(take, range(8)) for n in chunk]
    assert len(numbers) == 200 and len(set(numbers)) == 200
    last = conn.q1("select last_value from sys_number_seq where seq_kind = 'MAT_LOT' and seq_scope = %s",
                   (_scope("MAT_LOT", at),))["last_value"]
    assert last == 200


def test_next_in_caller_transaction_rolls_back_with_it(scoped):
    """`cur=` 로 받은 번호는 그 트랜잭션과 함께 되돌아간다 — 업무 행이 실패하면 번호도 비지 않는다."""
    at = scoped("SHIPMENT", AT_ROLLBACK)
    first = numbering.next("SHIPMENT", at=at)
    with pytest.raises(RuntimeError, match="업무 행 실패"):
        with conn.tx() as cur:
            lost = numbering.next("SHIPMENT", cur=cur, at=at)
            assert lost != first
            raise RuntimeError("업무 행 실패")
    with conn.tx() as cur:
        again = numbering.next("SHIPMENT", cur=cur, at=at)
    assert again == lost                                        # 롤백된 번호가 다시 나온다


def test_counter_restarts_per_date_scope(scoped):
    at = scoped("COA", AT_PEEK)
    other = scoped("COA", AT_KINDS)
    width = numbering.rule("COA")["seq_digits"]
    numbering.next("COA", at=at)
    numbering.next("COA", at=at)
    n = numbering.next("COA", at=other)
    assert int(n[-width:]) == 1 and _scope("COA", other) in n


def test_kinds_do_not_share_a_counter(scoped):
    at = AT_KINDS
    for kind in ("JOB", "JOB_LOT"):
        scoped(kind, at)
    wj, wl = numbering.rule("JOB")["seq_digits"], numbering.rule("JOB_LOT")["seq_digits"]
    j1, l1, j2 = numbering.next("JOB", at=at), numbering.next("JOB_LOT", at=at), numbering.next("JOB", at=at)
    assert (int(j1[-wj:]), int(l1[-wl:]), int(j2[-wj:])) == (1, 1, 2)


def test_unknown_kind_is_value_error():
    for call in (numbering.next, numbering.peek, numbering.rule):
        with pytest.raises(ValueError):
            call("PALLET")
