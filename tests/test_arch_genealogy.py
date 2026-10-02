"""스키마가 계보를 감당하는가 — 설계도 §3 예시를 SQL 로 직접 넣어 본다 (contracts/db-schema.md §3).

이것은 **스키마** 검사다. 같은 예시를 API 로 만드는 것은 개발2 의 `tests/test_lineage_scenario.py`(G-06)이고,
추적 함수는 `app/lineage.py`(G-07)다. 여기서는 그 둘이 기대는 바닥 — 10행 · 재귀 조회 · 순환 금지 · 재출하 금지 — 만 본다.
모든 행은 트랜잭션 안에서 넣고 마지막에 롤백한다(DB 에 아무것도 남기지 않는다).
"""
import psycopg
import pytest

from lcomfine.db import conn


class _Rollback(Exception):
    pass


@pytest.fixture()
def cur():
    """끝나면 무조건 롤백하는 커서."""
    try:
        with conn.tx() as c:
            yield c
            raise _Rollback
    except _Rollback:
        pass


def _one(cur, sql, params=()):
    cur.execute(sql, params)
    return cur.fetchone()


def _base(cur) -> dict:
    """품목·고객·Job·원재료 LOT 2 (전부 (예시) — 실데이터 아님)."""
    item = _one(cur, "insert into item (item_code, item_name, item_type, created_by) values ('T-ITEM', '제품 (예시)', '제품', 't') returning item_id")["item_id"]
    raw = _one(cur, "insert into item (item_code, item_name, item_type, created_by) values ('T-RAW', '원재료 (예시)', '원재료', 't') returning item_id")["item_id"]
    cust = _one(cur, "insert into customer (customer_code, customer_name, created_by) values ('T-CUST', '고객 (예시)', 't') returning customer_id")["customer_id"]
    job = _one(cur, """insert into job (job_no, item_id, customer_id, order_qty, qty_unit, due_date, created_by)
                       values ('T-JOB', %s, %s, 1, 'm', current_date, 't') returning job_id""", (item, cust))["job_id"]
    lots = [_one(cur, """insert into material_lot (lot_no, item_id, received_qty, qty_unit, received_by, insp_status, insp_at)
                         values (%s, %s, 100, 'm', 't', '합격', now()) returning material_lot_id""", (f"T-LOT{i}", raw))["material_lot_id"]
            for i in (1, 2)]
    return {"item": item, "cust": cust, "job": job, "lots": lots}


def _roll(cur, job, no, process_type):
    return _one(cur, "insert into roll (roll_no, process_type, job_id, produced_by) values (%s, %s, %s, 't') returning roll_id",
                (no, process_type, job))["roll_id"]


def _edge(cur, relation, *, lot=None, parent=None, child=None, ship=None):
    cur.execute("""insert into roll_genealogy (parent_material_lot_id, parent_roll_id, child_roll_id, child_shipment_id, relation, created_by)
                   values (%s, %s, %s, %s, %s, 't')""", (lot, parent, child, ship, relation))


def _example(cur) -> dict:
    """설계도 §3 그림 그대로: LOT 2 → 인쇄 2 → 후가공 1(splice) → 슬리팅 3 → 출하 1(①② 출하, ③ 재고)."""
    b = _base(cur)
    p1, p2 = _roll(cur, b["job"], "T-P1", "인쇄"), _roll(cur, b["job"], "T-P2", "인쇄")
    f = _roll(cur, b["job"], "T-F", "후가공")
    s1, s2, s3 = (_roll(cur, b["job"], f"T-S{i}", "슬리팅") for i in (1, 2, 3))
    ship = _one(cur, """insert into shipment (shipment_no, job_id, customer_id, ship_date, registered_by)
                        values ('T-SHIP', %s, %s, current_date, 't') returning shipment_id""", (b["job"], b["cust"]))["shipment_id"]
    _edge(cur, "투입", lot=b["lots"][0], child=p1)
    _edge(cur, "투입", lot=b["lots"][0], child=p2)
    _edge(cur, "투입", lot=b["lots"][1], child=p2)
    _edge(cur, "splice", parent=p1, child=f)
    _edge(cur, "splice", parent=p2, child=f)
    for s in (s1, s2, s3):
        _edge(cur, "슬리팅", parent=f, child=s)
    _edge(cur, "출하", parent=s1, ship=ship)
    _edge(cur, "출하", parent=s2, ship=ship)
    return {**b, "p": [p1, p2], "f": f, "s": [s1, s2, s3], "ship": ship}


UP = """with recursive up as (
            select g.* from roll_genealogy g where g.child_shipment_id = %s
            union
            select g.* from roll_genealogy g join up on g.child_roll_id = up.parent_roll_id)
        select * from up"""
DOWN = """with recursive down as (
              select g.* from roll_genealogy g where g.parent_material_lot_id = %s
              union
              select g.* from roll_genealogy g join down on g.parent_roll_id = down.child_roll_id)
          select * from down"""


def test_example_is_exactly_10_rows(cur):
    e = _example(cur)
    cur.execute("""select relation, count(*) as n from roll_genealogy
                    where child_roll_id = any(%s) or child_shipment_id = %s group by relation""",
                (e["p"] + [e["f"]] + e["s"], e["ship"]))
    got = {r["relation"]: r["n"] for r in cur.fetchall()}
    assert got == {"투입": 3, "splice": 2, "슬리팅": 3, "출하": 2} and sum(got.values()) == 10


def test_backward_trace_reaches_both_material_lots(cur):
    e = _example(cur)
    cur.execute(UP, (e["ship"],))
    rows = cur.fetchall()
    assert {r["parent_material_lot_id"] for r in rows if r["parent_material_lot_id"]} == set(e["lots"])
    assert len(rows) == 9                                        # 10행 중 재고 ③ 으로 가는 슬리팅 한 줄만 빠진다
    assert e["s"][2] not in {r["child_roll_id"] for r in rows}


def test_forward_trace_reaches_shipment_and_leaves_stock(cur):
    e = _example(cur)
    cur.execute(DOWN, (e["lots"][0],))
    rows = cur.fetchall()
    assert {r["child_roll_id"] for r in rows if r["child_roll_id"]} == set(e["p"] + [e["f"]] + e["s"])
    assert {r["child_shipment_id"] for r in rows if r["child_shipment_id"]} == {e["ship"]}
    assert len(rows) == 9                                        # LOT ② 의 투입 한 줄만 빠진다
    cur.execute("select roll_no, state from v_roll_state where roll_id = any(%s)", (e["p"] + [e["f"]] + e["s"],))
    state = {r["roll_no"]: r["state"] for r in cur.fetchall()}
    assert state == {"T-P1": "소진", "T-P2": "소진", "T-F": "소진", "T-S1": "출하", "T-S2": "출하", "T-S3": "재고"}


def test_deep_chain_trace_is_recursive(cur):
    """깊이 12단 사슬 — 깊이를 가정하지 않는다."""
    b = _base(cur)
    rolls = [_roll(cur, b["job"], "T-C0", "인쇄")]
    _edge(cur, "투입", lot=b["lots"][0], child=rolls[0])
    for i in range(1, 12):
        rolls.append(_roll(cur, b["job"], f"T-C{i}", "후가공"))
        _edge(cur, "후가공", parent=rolls[-2], child=rolls[-1])
    cur.execute(DOWN, (b["lots"][0],))
    assert len(cur.fetchall()) == 12


#: 경우 → 막는 제약 이름 또는 지킴이 트리거의 메시지 조각 (다른 이유로 우연히 막힌 것을 통과로 세지 않는다)
EXPECTED = {
    "self": "자기 자신을 부모로",
    "cycle": "계보 순환",
    "reship": "roll_genealogy_ship_once_uq",
    "ship_consumed": "소진",
    "consume_shipped": "이미 출하된 롤",
    "duplicate": "roll_genealogy_roll_roll_uq",
    "lot_to_shipment": "roll_genealogy_shape_chk",
    "relation_mismatch": "공정 구분",
    "update_edge": "고칠 수 없다",
    "other_job": "Job 이 다른 롤",
}


@pytest.mark.parametrize("case", ["self", "cycle", "reship", "ship_consumed", "consume_shipped", "duplicate",
                                  "lot_to_shipment", "relation_mismatch", "update_edge", "other_job"])
def test_guard_rejects(case):
    """순환·자기 자신·재출하 등은 DB 가 막는다 (422 의 마지막 방어선). 위반은 전부 IntegrityError 다."""
    with pytest.raises(psycopg.errors.IntegrityError) as caught:
        with conn.tx() as cur:
            e = _example(cur)
            p1, p2 = e["p"]
            s1, s2, s3 = e["s"]
            if case == "self":
                _edge(cur, "슬리팅", parent=s3, child=s3)
            elif case == "cycle":
                x, y, z = (_roll(cur, e["job"], f"T-{n}", "후가공") for n in "XYZ")
                _edge(cur, "후가공", parent=s3, child=x)       # 정상: ③ → X → Y → Z
                _edge(cur, "후가공", parent=x, child=y)
                _edge(cur, "후가공", parent=y, child=z)
                _edge(cur, "후가공", parent=z, child=x)        # Z → X 는 순환
            elif case == "reship":
                ship2 = _one(cur, """insert into shipment (shipment_no, job_id, customer_id, ship_date, registered_by)
                                     values ('T-SHIP2', %s, %s, current_date, 't') returning shipment_id""", (e["job"], e["cust"]))["shipment_id"]
                _edge(cur, "출하", parent=s1, ship=ship2)
            elif case == "ship_consumed":
                _edge(cur, "출하", parent=e["f"], ship=e["ship"])
            elif case == "consume_shipped":
                x = _roll(cur, e["job"], "T-X", "후가공")
                _edge(cur, "후가공", parent=s1, child=x)
            elif case == "duplicate":
                _edge(cur, "splice", parent=p1, child=e["f"])
            elif case == "lot_to_shipment":
                _edge(cur, "출하", lot=e["lots"][0], ship=e["ship"])
            elif case == "relation_mismatch":
                x = _roll(cur, e["job"], "T-X", "인쇄")
                _edge(cur, "슬리팅", parent=s3, child=x)
            elif case == "update_edge":
                cur.execute("update roll_genealogy set parent_roll_id = %s where parent_roll_id = %s and child_shipment_id = %s",
                            (s3, s1, e["ship"]))
            elif case == "other_job":
                job2 = _one(cur, """insert into job (job_no, item_id, customer_id, order_qty, qty_unit, due_date, created_by)
                                    values ('T-JOB2', %s, %s, 1, 'm', current_date, 't') returning job_id""", (e["item"], e["cust"]))["job_id"]
                other = _roll(cur, job2, "T-O", "슬리팅")
                _edge(cur, "출하", parent=other, ship=e["ship"])
            raise AssertionError(f"{case}: DB 가 막지 않았다")   # 여기까지 오면 실패 (그리고 롤백된다)
    text = f"{caught.value.diag.constraint_name or ''} {caught.value.diag.message_primary}"
    assert EXPECTED[case] in text, f"{case}: 다른 이유로 막혔다 — {text}"


def test_nothing_left_behind():
    assert conn.q1("select count(*) as n from roll where roll_no like 'T-%'")["n"] == 0
    assert conn.q1("select count(*) as n from job where job_no like 'T-%'")["n"] == 0
