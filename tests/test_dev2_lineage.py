"""`app/lineage.py` — 계보 쓰기의 검증(422) · DB 지킴이 트리거가 422 로 올라가는 경로 · 출하 화살표(ship/unlink) · 읽기 함수.

설계도 §3 예시 10행과 양방향 추적은 `tests/test_lineage_scenario.py` 에 있다. 여기는 그 바깥의 경우다.
출하 화면은 개발3 소유라서 출하 LOT 행은 전제 데이터로 넣고 계약의 함수(`ship_roll` · `unlink_shipment`)를 직접 부른다.
"""
import psycopg
import pytest
from fastapi import HTTPException

from lcomfine.app import lineage, nav
from lcomfine.db import conn

from test_dev2_helpers import TEST_BY, World, client, err, finishing, receive, slit, splice

L = lineage


@pytest.fixture(scope="module")
def w():
    world = World()
    try:
        world.lot = world.good_lot(qty="100000")
        yield world
    finally:
        world.cleanup()
        assert world.leftovers() == 0


def _print(w) -> str:
    return w.print_roll([w.lot])


def _422(fn) -> dict:
    """`fn(cur)` 을 트랜잭션 안에서 부른다 — 422 HTTPException 이어야 하고, 그 detail 을 돌려준다."""
    with pytest.raises(HTTPException) as caught:
        with conn.tx() as cur:
            fn(cur)
    assert caught.value.status_code == 422 and caught.value.detail["code"] == "validation_error"
    return caught.value.detail


def _ship(w, shipment_id: int, roll_no: str) -> int:
    with conn.tx() as cur:
        return L.ship_roll(cur, shipment_id=shipment_id, roll_id=w.roll_id(roll_no), by=TEST_BY)


# ── link 의 검증 ────────────────────────────────────────────────────────
def test_link_rejects_self_cycle_duplicate_and_bad_shapes(w):
    a = _print(w)
    b = finishing(a)
    c1, c2 = slit(b, 2)
    d = finishing(c2)                                                             # a → b → (c1, c2) → d
    A, B, C1, C2, D = (w.roll_id(x) for x in (a, b, c1, c2, d))
    lot = w.lot_id(w.lot)
    edges = len(w.genealogy())
    assert "자기 자신을 부모로" in _422(lambda cur: L.link(cur, (L.ROLL, C1), (L.ROLL, C1), L.SLITTING, by=TEST_BY))["message"]
    assert "계보 순환" in _422(lambda cur: L.link(cur, (L.ROLL, C1), (L.ROLL, B), L.FINISHING, by=TEST_BY))["message"]
    assert "계보 순환" in _422(lambda cur: L.link(cur, (L.ROLL, D), (L.ROLL, B), L.SPLICE, by=TEST_BY))["message"]   # 두 단 아래의 자손
    assert "같은 화살표 중복" in _422(lambda cur: L.link(cur, (L.ROLL, A), (L.ROLL, B), L.FINISHING, by=TEST_BY))["message"]
    assert "같은 화살표 중복" in _422(lambda cur: L.link(cur, (L.MATERIAL_LOT, lot), (L.ROLL, A), L.INPUT, by=TEST_BY))["message"]
    assert "공정 구분" in _422(lambda cur: L.link(cur, (L.ROLL, C1), (L.ROLL, C2), L.FINISHING, by=TEST_BY))["message"]
    for parent, child, relation in (((L.MATERIAL_LOT, lot), (L.ROLL, C1), L.SLITTING),       # 원재료 LOT 은 `투입` 만
                                    ((L.ROLL, C1), (L.ROLL, C2), L.INPUT),                   # 롤 → 롤 에 `투입`
                                    ((L.ROLL, C1), (L.ROLL, C2), L.SHIPPING),                # `출하` 인데 자식이 롤
                                    ((L.SHIPMENT, 1), (L.ROLL, C1), L.FINISHING),            # 출하 LOT 은 부모가 못 된다
                                    ((L.MATERIAL_LOT, lot), (L.SHIPMENT, 1), L.SHIPPING)):   # 원재료 LOT → 출하
        assert "맞지 않습니다" in _422(lambda cur: L.link(cur, parent, child, relation, by=TEST_BY))["message"]
    assert "관계가 아닙니다" in _422(lambda cur: L.link(cur, (L.ROLL, C1), (L.ROLL, C2), "합지", by=TEST_BY))["message"]
    assert "종류가 아닙니다" in _422(lambda cur: L.link(cur, ("pallet", 1), (L.ROLL, C2), L.FINISHING, by=TEST_BY))["message"]
    assert "없는 롤" in _422(lambda cur: L.link(cur, (L.ROLL, 999999999), (L.ROLL, C2), L.SLITTING, by=TEST_BY))["message"]
    assert len(w.genealogy()) == edges                                           # 아무것도 들어가지 않았다


def test_link_rejects_uninspected_and_rejected_material_lots(w):
    """불합격/검사 대기 LOT 투입 = 422 (합격 LOT 만 — D-13)."""
    roll_id = w.roll_id(_print(w))
    waiting = receive(w)
    assert "대기" in _422(lambda cur: L.link(cur, (L.MATERIAL_LOT, w.lot_id(waiting)), (L.ROLL, roll_id), L.INPUT, by=TEST_BY))["message"]
    assert "대기" in _422(lambda cur: L.assert_usable(cur, [(L.MATERIAL_LOT, w.lot_id(waiting))]))["message"]
    conn.x("update material_lot set insp_status = '불합격', insp_at = now() where lot_no = %s", (waiting,))
    detail = _422(lambda cur: L.assert_usable(cur, [(L.MATERIAL_LOT, w.lot_id(waiting)), (L.ROLL, roll_id), (L.ROLL, 999999999)]))
    assert {f["reason"] for f in detail["fields"]} == {"입고검사 불합격", "없는 롤"}     # 무엇이 왜 안 되는지 항목별로


# ── 출하 화살표: ship_roll · unlink_shipment (개발3 이 부른다) ──────────
def test_ship_roll_rules(w):
    good, other_job_roll, failed, untested = _print(w), None, _print(w), _print(w)
    shipment_id, shipment_no = w.new_shipment("SR1")
    gid = _ship(w, shipment_id, good)
    row = conn.q1("select * from roll_genealogy where genealogy_id = %s", (gid,))
    assert (row["relation"], row["parent_roll_id"], row["child_shipment_id"], row["created_by"]) == ("출하", w.roll_id(good), shipment_id, TEST_BY)
    assert L.roll_state(w.roll_id(good)) == "출하"
    assert "이미 출하된 롤" in _422(lambda cur: L.ship_roll(cur, shipment_id=shipment_id, roll_id=w.roll_id(good), by=TEST_BY))["message"]
    second_id, _ = w.new_shipment("SR2")
    assert "이미 출하된 롤" in _422(lambda cur: L.ship_roll(cur, shipment_id=second_id, roll_id=w.roll_id(good), by=TEST_BY))["message"]   # 재출하
    used = _print(w)
    finishing(used)
    assert "소진" in _422(lambda cur: L.ship_roll(cur, shipment_id=second_id, roll_id=w.roll_id(used), by=TEST_BY))["message"]
    job2_id, job2_no = w.new_job("SHIPJOB")
    other_job_roll = w.print_roll([w.lot], job_no=job2_no)
    assert "Job 이 다른 롤" in _422(lambda cur: L.ship_roll(cur, shipment_id=second_id, roll_id=w.roll_id(other_job_roll), by=TEST_BY))["message"]   # D-16
    conn.x("insert into inspection (roll_id, job_id, result, inspected_by, inspected_at) values (%s, %s, '합격', %s, now() - interval '1 hour')",
           (w.roll_id(failed), w.job_id, TEST_BY))
    conn.x("insert into inspection (roll_id, job_id, result, inspected_by) values (%s, %s, '불합격', %s)", (w.roll_id(failed), w.job_id, TEST_BY))
    assert "불합격" in _422(lambda cur: L.ship_roll(cur, shipment_id=second_id, roll_id=w.roll_id(failed), by=TEST_BY))["message"]       # D-17 최신 검사
    _ship(w, second_id, untested)                                                # 미검사 롤은 통과 (D-17)
    approved_id, _ = w.new_shipment("SR3", status="승인")
    assert "승인 상태의 출하" in _422(lambda cur: L.ship_roll(cur, shipment_id=approved_id, roll_id=w.roll_id(_print(w)), by=TEST_BY))["message"]
    assert "없는 출하 LOT" in _422(lambda cur: L.ship_roll(cur, shipment_id=999999999, roll_id=w.roll_id(untested), by=TEST_BY))["message"]
    assert "없는 롤" in _422(lambda cur: L.ship_roll(cur, shipment_id=second_id, roll_id=999999999, by=TEST_BY))["message"]


def test_unlink_shipment_returns_rolls_to_stock(w):
    a, b = _print(w), _print(w)
    shipment_id, shipment_no = w.new_shipment("UL1")
    _ship(w, shipment_id, a)
    _ship(w, shipment_id, b)
    assert {n.no for n in L.trace_backward((L.SHIPMENT, shipment_id)).rolls()} == {a, b}
    with conn.tx() as cur:
        assert L.unlink_shipment(cur, shipment_id, by=TEST_BY) == 2
    assert (L.roll_state(w.roll_id(a)), L.roll_state(w.roll_id(b))) == ("재고", "재고")     # 롤은 다시 재고
    assert L.trace_backward((L.SHIPMENT, shipment_id)).edges == []
    with conn.tx() as cur:
        assert L.unlink_shipment(cur, shipment_id, by=TEST_BY) == 0
    finishing(a)                                                                           # 재고로 돌아왔으니 다음 공정에 쓸 수 있다
    approved_id, _ = w.new_shipment("UL2")
    _ship(w, approved_id, b)
    conn.x("update shipment set status = '승인', approved_at = now() where shipment_id = %s", (approved_id,))
    assert "승인된 출하" in _422(lambda cur: L.unlink_shipment(cur, approved_id, by=TEST_BY))["message"]
    assert L.roll_state(w.roll_id(b)) == "출하"
    assert "없는 출하 LOT" in _422(lambda cur: L.unlink_shipment(cur, 999999999, by=TEST_BY))["message"]


def test_same_roll_used_by_two_jobs_at_once_only_one_wins(w):
    """같은 롤을 두 작업이 동시에 쓰면 뒤쪽이 앞의 커밋을 기다렸다가 `소진` 으로 막힌다(`assert_usable` 의 행 잠금).

    DB 트리거는 이 경우를 못 막는다(슬리팅은 한 부모에 자식이 여럿) — `lineage` 만 막는다.
    """
    import threading
    import time

    parent_id = w.roll_id(_print(w))
    results: dict[str, object] = {}

    def first():
        with conn.tx() as cur:
            results["first"] = len(L.slit_roll(cur, parent_roll_id=parent_id, count=2, by=TEST_BY))
            time.sleep(0.6)                                    # 커밋을 늦춘다 — 그 사이 두 번째가 들어온다

    def second():
        time.sleep(0.2)
        started = time.monotonic()
        try:
            with conn.tx() as cur:
                L.make_finishing_roll(cur, parent_roll_ids=[parent_id], by=TEST_BY)
            results["second"] = "통과"
        except HTTPException as exc:
            results["second"] = exc.detail["message"]
        results["waited"] = time.monotonic() - started

    threads = [threading.Thread(target=first), threading.Thread(target=second)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)
    assert results["first"] == 2
    assert "소진" in str(results["second"]), results                # 두 번째는 422
    assert results["waited"] > 0.2, results                         # 앞의 커밋을 기다렸다
    assert conn.q1("select count(*) as n from roll_genealogy where parent_roll_id = %s", (parent_id,))["n"] == 2


# ── DB 지킴이 트리거 → IntegrityError → 422 ─────────────────────────────
def test_db_guard_integrity_error_surfaces_as_422(w, monkeypatch):
    """`lineage` 의 사전 검사를 끄면 DB 트리거가 막는다 — 그 `IntegrityError` 가 500 이 아니라 422 로 올라가는가.

    (사전 검사가 놓친 경우의 마지막 방어선: api-contract.md §3.) 실패한 요청은 롤도 계보도 남기지 않는다.
    """
    shipped = _print(w)
    shipment_id, _ = w.new_shipment("GUARD")
    _ship(w, shipment_id, shipped)
    monkeypatch.setattr(lineage, "_check_link", lambda *a, **k: None)
    monkeypatch.setattr(lineage, "assert_usable", lambda *a, **k: None)
    rolls_before, edges_before = conn.q1("select count(*) as n from roll where job_id = %s", (w.job_id,))["n"], len(w.genealogy())
    r = client("field").post(nav.path_of("RLL-02"), data={"roll_no": shipped, "count": "2"})     # 출하된 롤을 슬리팅
    assert r.status_code == 422 and r.json()["code"] == "validation_error", r.text
    assert "이미 출하된 롤은 다음 공정에 쓸 수 없다" in r.json()["fields"][0]["reason"]           # 트리거의 문장 그대로
    r = client("field").post(nav.path_of("RLL-01"), data={"roll_no": shipped})
    assert r.status_code == 422 and "이미 출하된 롤" in r.json()["fields"][0]["reason"]
    with pytest.raises(psycopg.errors.IntegrityError):                                           # 순환도 DB 가 막는다
        with conn.tx() as cur:
            a = w.roll_id(finishing(_print(w)))
            b = L.make_finishing_roll(cur, parent_roll_ids=[a], by=TEST_BY)["roll_id"]
            L.link(cur, (L.ROLL, b), (L.ROLL, a), L.FINISHING, by=TEST_BY)
    monkeypatch.undo()
    assert conn.q1("select count(*) as n from roll where job_id = %s", (w.job_id,))["n"] == rolls_before + 2   # 순환 시도의 부모 2개(인쇄·후가공)만 남았다
    assert len(w.genealogy()) == edges_before + 2                                                # 그 둘의 계보(투입 1 + 후가공 1)


# ── 읽기 함수 ───────────────────────────────────────────────────────────
def test_resolve_and_search(w):
    roll_no = _print(w)
    shipment_id, shipment_no = w.new_shipment("RSV")
    lot, roll, ship = L.resolve(w.lot), L.resolve(roll_no), L.resolve(shipment_no)
    assert (lot.kind, lot.label, lot.state, lot.job_no) == (L.MATERIAL_LOT, "원재료 LOT", "합격", None)
    assert (roll.kind, roll.label, roll.state, roll.job_no, roll.id) == (L.ROLL, "인쇄", "재고", w.job_no, w.roll_id(roll_no))
    assert (ship.kind, ship.label, ship.state, ship.job_no, ship.id) == (L.SHIPMENT, "출하 LOT", "등록", w.job_no, shipment_id)
    assert L.resolve(f"  {roll_no.lower()} ") == roll and roll.ref == (L.ROLL, roll.id)        # 공백·소문자
    assert L.resolve("R000000-0000") is None and L.resolve("") is None and L.resolve(None) is None
    found = L.search(w.tag)                                                                    # 번호 일부 — 이 묶음의 출하 LOT 들
    assert shipment_no in [n.no for n in found] and {n.kind for n in found} == {L.SHIPMENT}
    assert [n.no for n in found] == sorted(n.no for n in found)
    assert roll_no in {n.no for n in L.search(roll_no[2:])} and w.lot in {n.no for n in L.search(w.lot[:-1])}
    assert L.search("") == [] and L.search("%") == [] and L.search("_") == []                  # 와일드카드는 글자로 본다
    assert len(L.search(roll_no[:4], limit=1)) == 1
    with pytest.raises(HTTPException) as nf:
        L.roll_state(999999999)
    assert nf.value.status_code == 404
    with pytest.raises(HTTPException) as nf:
        L.trace_forward((L.ROLL, 999999999))
    assert nf.value.status_code == 404
    assert L.trace_backward(lot.ref).edges == [] and L.trace_forward(ship.ref).edges == []     # 맨 앞의 위 · 맨 끝의 아래
    assert L.parents_of(lot.ref) == [] and L.children_of(ship.ref) == []


def test_one_step_edges(w):
    a, b = _print(w), _print(w)
    mid = splice([a, b])
    kids = slit(mid, 3)
    up, down = L.parents_of((L.ROLL, w.roll_id(mid))), L.children_of((L.ROLL, w.roll_id(mid)))
    assert [(e.parent.no, e.relation, e.depth) for e in up] == [(a, "splice", 1), (b, "splice", 1)]
    assert [(e.child.no, e.child.label, e.child.state) for e in down] == [(k, "슬리팅", "재고") for k in kids]
    first = L.parents_of((L.ROLL, w.roll_id(a)))
    assert [(e.parent.kind, e.parent.no, e.relation, e.qty) for e in first] == [(L.MATERIAL_LOT, w.lot, "투입", 10.0)]
    assert a in {e.child.no for e in L.children_of((L.MATERIAL_LOT, w.lot_id(w.lot)))}


def test_read_functions_do_not_write(w, monkeypatch):
    """G-05 — 읽기 함수는 어떤 테이블에도 쓰지 않는다: 쓰기 경로(`conn.x` · `conn.tx`)를 막고, 나가는 SQL 이 전부 조회인지 본다."""
    roll_no = slit(finishing(_print(w)), 2)[0]
    shipment_id, shipment_no = w.new_shipment("RO")
    _ship(w, shipment_id, roll_no)
    roll_id = w.roll_id(roll_no)
    seen: list[str] = []
    real_q = conn.q

    def spy_q(sql, params=None):
        seen.append(sql)
        return real_q(sql, params)

    def no_write(*a, **k):
        raise AssertionError("읽기 함수가 쓰기 경로를 불렀다")

    monkeypatch.setattr(conn, "q", spy_q)
    monkeypatch.setattr(conn, "x", no_write)
    monkeypatch.setattr(conn, "tx", no_write)
    node = L.resolve(shipment_no)
    back = L.trace_backward(node.ref)
    fwd = L.trace_forward(L.resolve(w.lot).ref)
    L.search(w.tag)
    L.parents_of(L.resolve(roll_no).ref)
    L.children_of(L.resolve(roll_no).ref)
    L.roll_state(roll_id)
    monkeypatch.undo()
    assert back.material_lots() and fwd.shipments() and len(seen) == 12, len(seen)   # 조회 12번 — 그 밖의 SQL 은 없다
    for sql in seen:
        words = set(sql.lower().replace("(", " ").replace(")", " ").split())
        assert not words & {"insert", "update", "delete", "truncate", "create", "drop", "alter", "merge"}, sql
        assert sql.lstrip().lower().startswith(("select", "with")), sql
    assert sum("with recursive" in s.lower() for s in seen) == 2          # 추적 한 번 = 재귀 조회 하나


def test_api_error_helper_contract():
    """오류는 `app.util.http` 의 예외로만 올라간다 — 422 의 모양(code · message · fields)."""
    body = err(client("field").post(nav.path_of("RLL-02"), data={"roll_no": "R000000-0000", "count": "2"}))
    assert set(body) == {"code", "message", "fields"} and body["fields"] == [{"name": "부모 롤", "reason": "R000000-0000"}]
