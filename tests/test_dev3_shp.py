# tests/test_dev3_shp.py — SHP 출하 (개발3): 출하 지시(할당 · 행 잠금) · 확정(판정 차단 · 재고 감소 · stock_move) · 반품·정정 · 이력.
# 기준 데이터는 test_dev3_world.World 가 SQL 로 직접 만들고 지운다(다른 개발자 화면 · 시드에 기대지 않는다).
import threading
from datetime import date, timedelta
from decimal import Decimal

import psycopg
import pytest

from lcomfine.db import conn
from test_dev3_world import World, login


@pytest.fixture(scope="module")
def c():
    return {lid: login(lid) for lid in ("sl", "sh", "pr", "admin", "ac", "ex")}


@pytest.fixture
def w():
    world = World()
    yield world
    world.close()


def _order(c, w, lines, **extra):
    data = {"customer_id": str(w.customer_id), "due_date": (date.today() + timedelta(days=5)).isoformat(),
            "stock_id": [str(s) for s, _ in lines], "qty": [str(q) for _, q in lines], **extra}
    return c.post("/shp/orders", data=data)


def _notes(key):
    return conn.q("select to_role, handled_at from notification where dedupe_key = %s order by to_role", (key,))


# ── F-SHP-011 출하 지시 등록 ─────────────────────────────────────────────

@pytest.mark.fn("F-SHP-011")
def test_create_order_allocates_within_available_and_notifies(c, w):
    lot = w.lot("10")
    r = _order(c["sl"], w, [(lot["stock_id"], "4")], note="(예시)")
    assert r.status_code == 200, r.text
    no = r.json()["shipment_no"]
    o = w.order(no)
    assert o["status"] == "지시" and o["customer_id"] == w.customer_id and o["request_id"] is None
    assert w.stock(lot["stock_id"])["allocated_qty"] == Decimal("4")
    assert w.stock(lot["stock_id"])["qty"] == Decimal("10")          # 할당은 현재고를 바꾸지 않는다
    lines = conn.q("select product_lot_id, location_id, qty from shipment_line where shipment_order_id = %s", (o["id"],))
    assert lines == [{"product_lot_id": lot["id"], "location_id": w.location_id, "qty": Decimal("4")}]
    assert _notes(f"shipment_ordered:{no}") == [{"to_role": "SH", "handled_at": None}]
    assert conn.q1("select count(*) n from sys_change_log where function_id = 'F-SHP-011' and target = %s",
                   (f"shipment_order:{no}",))["n"] == 1


@pytest.mark.fn("F-SHP-011")
def test_create_order_from_request_fills_customer_and_due(c, w):
    lot = w.lot("10")
    r = c["sl"].post("/shp/orders", data={"request_no": w.request_no, "stock_id": [str(lot["stock_id"])], "qty": ["2"]})
    assert r.status_code == 200, r.text
    o = w.order(r.json()["shipment_no"])
    req = conn.q1("select customer_id, due_date from production_request where id = %s", (w.request_id,))
    assert (o["request_id"], o["customer_id"], o["due_date"]) == (w.request_id, req["customer_id"], req["due_date"])


@pytest.mark.fn("F-SHP-011")
def test_create_order_rejects_bad_input_422(c, w):
    ok = w.lot("10")
    waiting = w.lot("10", judge=None)                 # 검사대기
    stopped_item = w.item(use_yn="N")
    stopped = w.lot("10", item_id=stopped_item)
    cases = [
        ([(ok["stock_id"], "10.001")], {}, "가용 수량을 넘는 할당"),
        ([(waiting["stock_id"], "1")], {}, "할당할 수 없는 LOT"),
        ([(stopped["stock_id"], "1")], {}, "할당할 수 없는 LOT"),
        ([], {}, "할당할 LOT 가 없습니다"),
        ([(ok["stock_id"], "0")], {}, "0보다 커야"),
        ([(ok["stock_id"], "abc")], {}, "숫자"),
        ([(ok["stock_id"], "1"), (ok["stock_id"], "1")], {}, "두 줄"),
        ([(ok["stock_id"], "1")], {"request_no": "없는-번호"}, "없는 생산의뢰"),
        ([(ok["stock_id"], "1")], {"customer_id": ""}, "거래처"),
        ([(ok["stock_id"], "1")], {"due_date": ""}, "납기"),
        ([(999999999999, "1")], {}, "할당할 수 없는 LOT"),
    ]
    for lines, extra, msg in cases:
        r = _order(c["sl"], w, lines, **extra)
        assert r.status_code == 422, (lines, extra, r.text)
        assert msg in r.json()["message"], (msg, r.json())
    assert w.stock(ok["stock_id"])["allocated_qty"] == 0
    assert conn.q1("select count(*) n from shipment_order where customer_id = %s", (w.customer_id,))["n"] == 0


@pytest.mark.fn("F-SHP-011")
def test_create_order_forbidden_for_read_only_department(c, w):
    lot = w.lot("10")
    assert _order(c["pr"], w, [(lot["stock_id"], "1")]).status_code == 403     # 생산부 SHP-010 = R
    assert _order(c["ac"], w, [(lot["stock_id"], "1")]).status_code == 403     # 회계부 R
    assert w.stock(lot["stock_id"])["allocated_qty"] == 0


@pytest.mark.fn("F-SHP-011")
def test_concurrent_allocation_never_exceeds_available(w):
    """Review Focus — 스레드 2개가 같은 LOT(가용 10)에 7 씩 동시에 할당한다. 하나만 통과하고, 다른 하나는 행 잠금 뒤
    줄어든 가용으로 라우터가 판정한 422(사람이 읽는 문장 — DB CHECK 제약의 422 가 아니다)다."""
    lot = w.lot("10")
    clients = [login("sl"), login("sh")]
    barrier = threading.Barrier(2)
    results: list = [None, None]

    def go(i):
        barrier.wait()
        results[i] = _order(clients[i], w, [(lot["stock_id"], "7")])

    ts = [threading.Thread(target=go, args=(i,)) for i in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(30)
    codes = sorted(r.status_code for r in results)
    assert codes == [200, 422], [r.text for r in results]
    rejected = next(r for r in results if r.status_code == 422).json()
    assert rejected["message"] == "가용 수량을 넘는 할당입니다", rejected
    assert "가용 3" in rejected["fields"][0]["reason"]                 # 앞의 할당이 커밋된 뒤의 값으로 판정
    s = w.stock(lot["stock_id"])
    assert s["allocated_qty"] == Decimal("7") and s["allocated_qty"] <= s["qty"]
    assert conn.q1("select count(*) n from shipment_order where customer_id = %s", (w.customer_id,))["n"] == 1


@pytest.mark.fn("F-SHP-011")
def test_allocation_waits_for_row_lock(c, w):
    """할당은 `select … for update` 안에서 한다 — 다른 트랜잭션이 그 재고 행을 잡고 있으면 끝날 때까지 기다린다."""
    lot = w.lot("10")
    holder = psycopg.connect(conn.dsn())
    try:
        holder.execute("select id from lot_stock where id = %s for update", (lot["stock_id"],))
        done = threading.Event()
        out = {}

        def go():
            out["r"] = _order(c["sl"], w, [(lot["stock_id"], "6")])
            done.set()

        t = threading.Thread(target=go)
        t.start()
        assert not done.wait(1.0), "행 잠금을 기다리지 않고 지나갔다"
        holder.execute("update lot_stock set allocated_qty = 5 where id = %s", (lot["stock_id"],))
        holder.commit()
        t.join(30)
        assert out["r"].status_code == 422 and "가용 5" in out["r"].json()["fields"][0]["reason"]
    finally:
        holder.close()
    assert w.stock(lot["stock_id"])["allocated_qty"] == Decimal("5")


# ── F-SHP-012 출하 지시 수정 ─────────────────────────────────────────────

@pytest.mark.fn("F-SHP-012")
def test_update_order_moves_allocation(c, w):
    a, b = w.lot("10"), w.lot("8")
    r = _order(c["sl"], w, [(a["stock_id"], "6")])
    oid = r.json()["id"]
    # a 의 6 을 풀고 a 3 + b 8 로 다시 잡는다 (a 는 자기 할당을 푼 뒤의 가용 10 으로 판정)
    r = c["sh"].post(f"/shp/orders/{oid}", data={"stock_id": [str(a["stock_id"]), str(b["stock_id"])], "qty": ["3", "8"],
                                                  "due_date": (date.today() + timedelta(days=9)).isoformat()})
    assert r.status_code == 200, r.text
    assert w.stock(a["stock_id"])["allocated_qty"] == Decimal("3")
    assert w.stock(b["stock_id"])["allocated_qty"] == Decimal("8")
    assert conn.q1("select count(*) n from shipment_line where shipment_order_id = %s", (oid,))["n"] == 2
    # 할당 해제: b 로만
    r = c["sh"].post(f"/shp/orders/{oid}", data={"stock_id": [str(b["stock_id"])], "qty": ["1"]})
    assert r.status_code == 200
    assert (w.stock(a["stock_id"])["allocated_qty"], w.stock(b["stock_id"])["allocated_qty"]) == (0, Decimal("1"))
    # 가용 초과 · 누락 · 없는 ID · 숫자 아닌 ID · 권한
    assert c["sh"].post(f"/shp/orders/{oid}", data={"stock_id": [str(b["stock_id"])], "qty": ["9"]}).status_code == 422
    assert c["sh"].post(f"/shp/orders/{oid}", data={}).status_code == 422
    assert c["sh"].post("/shp/orders/999999999999", data={"stock_id": [str(b["stock_id"])], "qty": ["1"]}).status_code == 404
    assert c["sh"].post("/shp/orders/abc", data={"stock_id": [str(b["stock_id"])], "qty": ["1"]}).status_code == 404
    assert c["pr"].post(f"/shp/orders/{oid}", data={"stock_id": [str(b["stock_id"])], "qty": ["1"]}).status_code == 403
    assert w.stock(b["stock_id"])["allocated_qty"] == Decimal("1")


@pytest.mark.fn("F-SHP-012")
def test_update_confirmed_order_422(c, w):
    lot = w.lot("10")
    oid = _order(c["sl"], w, [(lot["stock_id"], "2")]).json()["id"]
    assert c["sh"].post(f"/shp/confirm/{oid}/confirm").status_code == 200
    r = c["sh"].post(f"/shp/orders/{oid}", data={"stock_id": [str(lot["stock_id"])], "qty": ["1"]})
    assert r.status_code == 422 and "확정된 출하" in r.json()["message"]


# ── F-SHP-013 출하 지시 조회 ─────────────────────────────────────────────

@pytest.mark.fn("F-SHP-013")
def test_orders_screen_lists_and_prefills(c, w):
    lot = w.lot("10")
    no = _order(c["sl"], w, [(lot["stock_id"], "4")]).json()["shipment_no"]
    r = c["pr"].get("/shp/orders", params={"customer": str(w.customer_id), "status": "지시"})
    assert r.status_code == 200 and no in r.text and lot["lot_no"] in r.text
    assert "출하 지시 등록" in r.text and "이 부서는 이 기능을 실행할 권한이 없습니다" in r.text   # R 부서는 폼 대신 안내
    r = c["sl"].get("/shp/orders", params={"request_no": w.request_no})
    assert r.status_code == 200 and w.request_no in r.text and "남은" in r.text and lot["lot_no"] in r.text
    assert c["sl"].get("/shp/orders", params={"request_no": "없는-번호"}).status_code == 422
    assert c["sl"].get("/shp/orders", params={"due_from": "2026-13-40"}).status_code == 422
    assert c["sl"].get("/shp/orders", params={"edit": "999999999999"}).status_code == 404
    assert c["sl"].get("/shp/orders", params={"edit": str(w.order(no)["id"])}).status_code == 200
    assert login("ds").get("/shp/orders").status_code == 403                                   # 디자인·개발실 칸 없음


# ── F-SHP-021 출하 확정 ─────────────────────────────────────────────────

@pytest.mark.fn("F-SHP-021")
def test_confirm_reduces_stock_and_writes_one_move_per_line(c, w):
    a, b = w.lot("10"), w.lot("5")
    r = _order(c["sl"], w, [(a["stock_id"], "4"), (b["stock_id"], "5")])
    oid, no = r.json()["id"], r.json()["shipment_no"]
    r = c["sh"].post(f"/shp/confirm/{oid}/confirm")
    assert r.status_code == 200, r.text
    o = w.order(no)
    assert o["status"] == "확정" and o["confirmed_at"] is not None and o["confirmed_by"] == "sh"
    sa, sb = w.stock(a["stock_id"]), w.stock(b["stock_id"])
    assert (sa["qty"], sa["allocated_qty"]) == (Decimal("6"), 0)       # 가용 = 6 − 0 = 확정 전 가용(10 − 4)과 같다
    assert (sb["qty"], sb["allocated_qty"]) == (0, 0)
    moves = conn.q("""select move_kind, lot_kind, lot_id, from_location_id, to_location_id, qty from stock_move
                       where ref_table = 'shipment_order' and ref_id = %s order by lot_id""", (oid,))
    assert moves == [
        {"move_kind": "출하", "lot_kind": "제품", "lot_id": a["id"], "from_location_id": w.location_id,
         "to_location_id": None, "qty": Decimal("4")},
        {"move_kind": "출하", "lot_kind": "제품", "lot_id": b["id"], "from_location_id": w.location_id,
         "to_location_id": None, "qty": Decimal("5")}]
    assert [n["to_role"] for n in _notes(f"shipment_confirmed:{no}")] == ["AC", "SL"]
    assert _notes(f"shipment_ordered:{no}")[0]["handled_at"] is not None   # 연 화면에서 처리하면 닫힌다
    # 두 번째 확정 · 없는 ID · 숫자 아님 · 권한(영업부 SHP-020 = R)
    assert c["sh"].post(f"/shp/confirm/{oid}/confirm").status_code == 422
    assert c["sh"].post("/shp/confirm/999999999999/confirm").status_code == 404
    assert c["sh"].post("/shp/confirm/x1/confirm").status_code == 404
    assert c["sl"].post(f"/shp/confirm/{oid}/confirm").status_code == 403


@pytest.mark.fn("F-SHP-021")
def test_confirm_blocked_by_unjudged_or_rejected_lot_422(c, w):
    good = w.lot("10")
    unjudged = w.lot("10", judge=None, status="가용")      # 재고는 가용이어도 판정 행이 없으면 미판정
    oid = _order(c["sl"], w, [(good["stock_id"], "1"), (unjudged["stock_id"], "1")]).json()["id"]
    r = c["sh"].post(f"/shp/confirm/{oid}/confirm")
    assert r.status_code == 422 and {"name": unjudged["lot_no"], "reason": "검사 미판정"} in r.json()["fields"]
    # 재판정 불합격(D-515 — 가장 최근 차수가 판정) → 여전히 422 · 할당은 그대로
    w.judge(unjudged["id"], "합격", "가용")
    w.judge(good["id"], "불합격", "보류")
    r = c["sh"].post(f"/shp/confirm/{oid}/confirm")
    assert r.status_code == 422 and r.json()["fields"][0]["name"] == good["lot_no"]
    assert "불합격" in r.json()["fields"][0]["reason"]
    assert w.stock(good["stock_id"]) == {"qty": Decimal("10"), "allocated_qty": Decimal("1"), "status": "보류"}
    assert conn.q1("select count(*) n from stock_move where ref_table = 'shipment_order' and ref_id = %s", (oid,))["n"] == 0
    assert conn.q1("select status from shipment_order where id = %s", (oid,))["status"] == "지시"
    # 재판정 합격 → 확정된다
    w.judge(good["id"], "합격", "가용")
    assert c["sh"].post(f"/shp/confirm/{oid}/confirm").status_code == 200


# ── F-SHP-022 출하 확정 대상 조회 ─────────────────────────────────────────

@pytest.mark.fn("F-SHP-022")
def test_confirm_screen_shows_pending_with_judgement(c, w):
    unjudged = w.lot("10", judge=None, status="가용")
    no = _order(c["sl"], w, [(unjudged["stock_id"], "2")]).json()["shipment_no"]
    r = c["sh"].get("/shp/confirm", params={"no": no})
    assert r.status_code == 200 and no in r.text and "미판정" in r.text and "확정 불가 1 LOT" in r.text
    r = c["sl"].get("/shp/confirm")                                  # R 부서 — 보이지만 확정 단추 없음
    assert r.status_code == 200 and "/confirm\" class=\"inline\"" not in r.text
    assert c["pr"].get("/shp/confirm").status_code == 403            # 생산부 칸 없음


# ── F-SHP-023 반품·정정 등록 ─────────────────────────────────────────────

@pytest.mark.fn("F-SHP-023")
def test_adjust_only_after_confirm_and_keeps_stock(c, w):
    lot = w.lot("10")
    oid = _order(c["sl"], w, [(lot["stock_id"], "5")]).json()["id"]
    body = {"kind": "반품", "qty": "2", "reason": "고객 반품 (예시)"}
    r = c["sh"].post(f"/shp/confirm/{oid}/adjust", data=body)
    assert r.status_code == 422 and "확정된 출하만" in r.json()["message"]
    assert c["sh"].post(f"/shp/confirm/{oid}/confirm").status_code == 200
    before = w.stock(lot["stock_id"])
    moves_before = conn.q1("select count(*) n from stock_move where lot_kind = '제품' and lot_id = %s", (lot["id"],))["n"]
    r = c["sh"].post(f"/shp/confirm/{oid}/adjust", data={**body, "lot_no": lot["lot_no"]})
    assert r.status_code == 200, r.text
    r = c["admin"].post(f"/shp/confirm/{oid}/adjust", data={"kind": "정정", "qty": "-1", "reason": "수량 정정 (예시)"})
    assert r.status_code == 200
    rows = conn.q("select kind, qty, reason, product_lot_id from shipment_adjust where shipment_order_id = %s order by id", (oid,))
    assert [(x["kind"], x["qty"], x["product_lot_id"]) for x in rows] == [("반품", Decimal("-2"), lot["id"]),
                                                                          ("정정", Decimal("-1"), None)]
    assert w.stock(lot["stock_id"]) == before                                       # 재고는 바꾸지 않는다 (D-515)
    assert conn.q1("select count(*) n from stock_move where lot_kind = '제품' and lot_id = %s", (lot["id"],))["n"] == moves_before
    # 반품 누계 초과 · 구분 · 사유 · 수량 · 없는 LOT · 없는 ID · 권한
    bad = [({"kind": "반품", "qty": "4", "reason": "x"}, "출하 수량을 넘습니다"),
           ({"kind": "교환", "qty": "1", "reason": "x"}, "구분"),
           ({"kind": "반품", "qty": "1", "reason": "  "}, "사유"),
           ({"kind": "정정", "qty": "0", "reason": "x"}, "0 일 수 없습니다"),
           ({"kind": "반품", "qty": "1", "reason": "x", "lot_no": "없는-LOT"}, "없는 LOT")]
    for data, msg in bad:
        r = c["sh"].post(f"/shp/confirm/{oid}/adjust", data=data)
        assert r.status_code == 422 and msg in r.json()["message"], (data, r.text)
    assert c["sh"].post("/shp/confirm/999999999999/adjust", data=body).status_code == 404
    assert c["sl"].post(f"/shp/confirm/{oid}/adjust", data=body).status_code == 403
    with pytest.raises(psycopg.errors.RaiseException):                              # 불변 이력
        conn.x("update shipment_adjust set qty = -9 where shipment_order_id = %s", (oid,))


# ── F-SHP-031 출하 이력 조회 ─────────────────────────────────────────────

@pytest.mark.fn("F-SHP-031")
def test_history_groups_adjust_rows_under_original(c, w):
    lot = w.lot("10")
    r = _order(c["sl"], w, [(lot["stock_id"], "5")])
    oid, no = r.json()["id"], r.json()["shipment_no"]
    pending_screen = c["ex"].get("/shp/history", params={"no": no})
    assert pending_screen.status_code == 200 and f"<code>{no}</code>" not in pending_screen.text           # 확정 전은 이력에 없다
    c["sh"].post(f"/shp/confirm/{oid}/confirm")
    c["sh"].post(f"/shp/confirm/{oid}/adjust", data={"kind": "반품", "qty": "1", "reason": "파손 반품 (예시)"})
    today = date.today().isoformat()
    r = c["ac"].get("/shp/history", params={"date_from": today, "date_to": today, "customer": str(w.customer_id),
                                            "item": str(w.item_id)})
    assert r.status_code == 200 and no in r.text
    assert f'data-adjust-of="{no}"' in r.text and "파손 반품 (예시)" in r.text
    assert r.text.index(no) < r.text.index("파손 반품 (예시)")
    r = c["ac"].get("/shp/history", params={"customer": str(w.customer_id), "date_from": "2000-01-01", "date_to": "2000-01-02"})
    assert r.status_code == 200 and f"<code>{no}</code>" not in r.text and "미수집" in r.text
    assert c["ac"].get("/shp/history", params={"date_from": "nope"}).status_code == 422
    assert login("ds").get("/shp/history").status_code == 403
    assert conn.q1("select count(*) n from stock_move where ref_table = 'shipment_order' and ref_id = %s", (oid,))["n"] == 1
