"""후가공 · 슬리팅 롤 이력 (RLL · 기능 7) — 후가공(1:1) · splice(N:1) · 슬리팅(1:N) · 롤 이력 · 롤 라벨.

화면이 부르는 엔드포인트로 검증한다. 권한: 생산·현장 = 입력 · 관리자·품질 = 조회 (설계도 §6).
이미 소진·출하된 롤은 다시 쓸 수 없다(422).
"""
import re
import threading
import time

import pytest

from lcomfine.app import lineage, nav
from lcomfine.app.routers import job as job_router
from lcomfine.db import conn

from test_dev2_helpers import (HTML, TEST_BY, World, change_logs, client, count, decode_barcode, err, finishing, ok, one,
                               pause_after,
                               slit, splice)

FIN, SLT, HIS = (nav.path_of(s) for s in ("RLL-01", "RLL-02", "RLL-03"))


@pytest.fixture(scope="module")
def w():
    world = World()
    try:
        world.lot = world.good_lot(qty="100000")          # 이 묶음의 인쇄 롤은 전부 이 LOT 에서 나온다
        yield world
    finally:
        world.cleanup()
        assert world.leftovers() == 0


def _print(w) -> str:
    return w.print_roll([w.lot])


def _state(roll_no: str) -> str:
    return one("select state from v_roll_state where roll_no = %s", (roll_no,))["state"]


def _edges_into(w, roll_no: str) -> set:
    return {(g["parent_no"], g["relation"]) for g in w.genealogy() if g["child_no"] == roll_no}


def _rolls(w) -> int:
    """이 World 의 Job 전부에 매달린 롤 수."""
    return count("select count(*) as n from roll r join job j on j.job_id = r.job_id where j.item_id = %s", (w.item_id,))


def _text(html: str) -> str:
    """화면의 글자만 (태그·스크립트·스타일을 뺀다)."""
    html = re.sub(r"<(script|style)\b.*?</\1>", " ", html, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def _work_id(roll_no: str) -> int:
    return one("select work_result_id from roll where roll_no = %s", (roll_no,))["work_result_id"]


# ── RLL-01 후가공 ───────────────────────────────────────────────────────
@pytest.mark.fn("F-RLL-01")
def test_finishing_one_parent_makes_one_roll_and_one_edge(w):
    parent = _print(w)
    before = len(w.genealogy())
    body = ok(client("field").post(FIN, data={"roll_no": parent, "equipment_code": w.eq_code, "length_m": "480", "width_mm": "1000"}))
    roll = one("select * from roll where roll_no = %s", (body["roll_no"],))
    assert roll["process_type"] == "후가공" and roll["job_id"] == w.job_id and roll["work_result_id"] is None
    assert roll["equipment_id"] == w.eq_id and float(roll["length_m"]) == 480 and roll["produced_by"] == "field"
    assert len(w.genealogy()) == before + 1 and _edges_into(w, body["roll_no"]) == {(parent, "후가공")}
    assert body["relation"] == "후가공" and body["label_url"] == f"{HIS}/{body['roll_no']}/label"
    assert (_state(parent), _state(body["roll_no"])) == ("소진", "재고")
    assert change_logs("F-RLL-01", f"roll:{body['roll_no']}") == 1


@pytest.mark.fn("F-RLL-01")
def test_finishing_rejects_unknown_consumed_and_shipped_rolls(w):
    c = client("prod")
    assert err(c.post(FIN, data={"roll_no": "R000000-0000"}))["message"] == "없는 롤 번호입니다"       # 없는 롤 스캔 422
    assert err(c.post(FIN, data={}))["fields"][0]["name"] == "부모 롤"
    assert err(c.post(FIN, data={"roll_no": w.lot}))["message"] == "없는 롤 번호입니다"                # 원재료 LOT 번호는 롤이 아니다
    used = _print(w)
    child = finishing(used)
    assert "소진" in err(c.post(FIN, data={"roll_no": used}))["message"]                              # 소진된 롤 재사용 422
    shipment_id, _ = w.new_shipment("FIN")
    with conn.tx() as cur:
        lineage.ship_roll(cur, shipment_id=shipment_id, roll_id=w.roll_id(child), by=TEST_BY)
    assert "출하" in err(c.post(FIN, data={"roll_no": child}))["message"]                             # 출하된 롤 재사용 422
    a, b = _print(w), _print(w)
    assert "splice" in err(c.post(FIN, data={"roll_no": f"{a},{b}"}))["message"]                      # 1:1 화면에 롤 2개
    assert err(c.post(FIN, data={"roll_no": a, "equipment_code": "없는설비"}))["fields"][0]["name"] == "설비"
    assert err(c.post(FIN, data={"roll_no": a, "width_mm": "-5"}))["fields"][0]["name"] == "폭"
    assert (_state(a), _state(b)) == ("재고", "재고")


@pytest.mark.fn("F-RLL-02")
def test_splice_n_parents_make_one_roll_with_n_edges(w):
    parents = [_print(w) for _ in range(3)]
    before = len(w.genealogy())
    body = ok(client("field").post(FIN + "/splice", data={"roll_no": parents, "equipment_code": w.eq_code}))
    assert body["relation"] == "splice" and body["parents"] == parents
    assert one("select process_type from roll where roll_no = %s", (body["roll_no"],))["process_type"] == "후가공"
    assert len(w.genealogy()) == before + 3                                                           # 부모 수만큼 한 줄씩
    assert _edges_into(w, body["roll_no"]) == {(p, "splice") for p in parents}
    assert [_state(p) for p in parents] == ["소진"] * 3 and _state(body["roll_no"]) == "재고"
    assert change_logs("F-RLL-02", f"roll:{body['roll_no']}") == 1
    two = [_print(w), _print(w)]
    assert ok(client("prod").post(FIN + "/splice", data={"roll_no": ", ".join(two)}))["parents"] == two   # 쉼표로 이어도 된다


@pytest.mark.fn("F-RLL-02")
def test_splice_validation_and_all_or_nothing(w):
    c = client("field")
    a, b, used = _print(w), _print(w), _print(w)
    finishing(used)
    rolls_before = count("select count(*) as n from roll where job_id = %s", (w.job_id,))
    edges_before = len(w.genealogy())
    assert "2개 이상" in err(c.post(FIN + "/splice", data={"roll_no": [a]}))["message"]
    assert "2개 이상" in err(c.post(FIN + "/splice", data={}))["message"]
    assert "두 번 스캔" in err(c.post(FIN + "/splice", data={"roll_no": [a, b, a]}))["message"]        # 같은 롤 중복
    assert err(c.post(FIN + "/splice", data={"roll_no": [a, "R000000-0000"]}))["message"] == "없는 롤 번호입니다"
    body = err(c.post(FIN + "/splice", data={"roll_no": [a, b, used]}))                               # 하나라도 소진이면 전부 안 된다
    assert "소진" in body["message"] and body["fields"][0]["name"] == used
    assert count("select count(*) as n from roll where job_id = %s", (w.job_id,)) == rolls_before
    assert len(w.genealogy()) == edges_before and (_state(a), _state(b)) == ("재고", "재고")
    other_job_id, other_job_no = w.new_job("SPL")                                                     # 부모들의 Job 이 다르면 Job 을 지정한다
    x = w.print_roll([w.lot], job_no=other_job_no)
    assert "Job 이 서로 다릅니다" in err(c.post(FIN + "/splice", data={"roll_no": [a, x]}))["message"]
    assert err(c.post(FIN + "/splice", data={"roll_no": [a, x], "job_no": "J000000-000"}))["message"] == "없는 Job 번호입니다"
    made = ok(c.post(FIN + "/splice", data={"roll_no": [a, x], "job_no": other_job_no}))["roll_no"]
    assert one("select job_id, job_lot_id from roll where roll_no = %s", (made,)) == {"job_id": other_job_id, "job_lot_id": None}


@pytest.mark.fn("F-RLL-02")
def test_splice_job_must_be_an_open_job_of_the_parents(w):
    """DEF-QA2-002 · D-208 — `job_no` 는 부모 롤들의 Job 중 하나여야 하고 취소·완료 Job 이면 422. 422 면 롤·계보·부모 상태가 그대로다."""
    c = client("field")
    a, b = _print(w), _print(w)
    _, cancelled = w.new_job("CXL", status="취소")                                                     # 롤이 없는 취소 Job (F-JOB-03)
    _, unrelated = w.new_job("UNR")                                                                    # 부모와 무관한 `등록` Job
    done_id, done = w.new_job("DONE")
    x = w.print_roll([w.lot], job_no=done)
    conn.x("update job set status = '완료' where job_id = %s", (done_id,))                             # 마감은 개발1 화면의 일 — 전제로 바꾼다
    rolls_before, edges_before = _rolls(w), len(w.genealogy())
    for job_no in (cancelled, unrelated):
        body = err(c.post(FIN + "/splice", data={"roll_no": [a, b], "job_no": job_no}))
        assert "부모 롤의 Job 이 아닙니다" in body["message"] and body["fields"][0]["name"] == job_no
        assert w.job_no in body["fields"][0]["reason"]
        assert count("select count(*) as n from roll r join job j on j.job_id = r.job_id where j.job_no = %s", (job_no,)) == 0
    body = err(c.post(FIN + "/splice", data={"roll_no": [a, x], "job_no": done}))                      # 부모의 Job 이지만 마감된 Job
    assert body["message"] == "완료 상태의 Job 에는 롤을 만들 수 없습니다" and body["fields"][0] == {"name": done, "reason": "상태 완료"}
    assert (_rolls(w), len(w.genealogy())) == (rolls_before, edges_before)
    assert [_state(r) for r in (a, b, x)] == ["재고"] * 3
    page = c.get(FIN, params={"rolls": f"{a},{x}"}, headers=HTML).text                                 # 화면은 부모의 Job 중 `등록` 인 것만 고르게 한다
    assert '<select name="job_no" required>' in page and f'<option value="{w.job_no}">' in page
    assert f'<option value="{done}">' not in page and f"Job {done} (완료)" in _text(page)
    made = ok(c.post(FIN + "/splice", data={"roll_no": [a, x], "job_no": w.job_no}))["roll_no"]         # 살아 있는 쪽 Job 으로는 된다
    assert one("select job_id from roll where roll_no = %s", (made,))["job_id"] == w.job_id
    assert [_state(r) for r in (a, x)] == ["소진"] * 2
    same = ok(c.post(FIN + "/splice", data={"roll_no": [b, _print(w)], "job_no": w.job_no.lower()}))   # 부모가 같은 Job 이어도 그 Job 을 적을 수 있다
    assert one("select job_id from roll where roll_no = %s", (same["roll_no"],))["job_id"] == w.job_id


@pytest.mark.fn("F-RLL-01", "F-RLL-02", "F-RLL-04")
def test_finishing_and_slitting_are_blocked_for_closed_jobs(w):
    """D-208 — 1:1 후가공 · Job 을 안 준 splice · 슬리팅도 롤이 붙을 Job 이 취소·완료면 422. 다시 `등록` 이면 된다."""
    c = client("prod")
    job_id, job_no = w.new_job("CLOSED")
    p, q = (w.print_roll([w.lot], job_no=job_no) for _ in range(2))
    rolls_before, edges_before = _rolls(w), len(w.genealogy())
    for status in ("완료", "취소"):                                                                    # 취소 Job 에 롤이 있는 것은 옛 데이터뿐이다 — 그래도 막는다
        conn.x("update job set status = %s where job_id = %s", (status, job_id))
        message = f"{status} 상태의 Job 에는 롤을 만들 수 없습니다"
        for path, data in ((FIN, {"roll_no": p}), (FIN + "/splice", {"roll_no": [p, q]}), (SLT, {"roll_no": p, "count": "2"})):
            body = err(c.post(path, data=data))
            assert body["message"] == message and body["fields"][0] == {"name": job_no, "reason": f"상태 {status}"}
        assert (_rolls(w), len(w.genealogy())) == (rolls_before, edges_before) and (_state(p), _state(q)) == ("재고", "재고")
        page = c.get(SLT, params={"no": p}, headers=HTML).text                                         # 화면도 폼 대신 사유를 보인다
        assert message in page and 'id="slit-form"' not in page
        page = c.get(FIN, params={"rolls": p}, headers=HTML).text
        assert f"Job {job_no} ({status})" in _text(page) and "후가공 롤을 만들 수 없다" in page
    conn.x("update job set status = '등록' where job_id = %s", (job_id,))
    assert 'id="slit-form"' in c.get(SLT, params={"no": p}, headers=HTML).text
    assert len(slit(finishing(p), 2)) == 2 and _state(q) == "재고"


@pytest.mark.fn("F-RLL-01", "F-RLL-02", "F-RLL-04")
def test_finishing_and_slitting_wait_for_a_close_in_flight_and_then_refuse(w, monkeypatch):
    """마감(F-JOB-02 `완료`)이 Job 행을 잠그고 아직 커밋하지 않은 동안 들어온 후가공·splice·슬리팅은 기다렸다가 422 (D-208 의 `for share`).

    DEF-QA2-004 와 같은 꼴인지 본 것 — 여기는 판정이 롤을 만드는 트랜잭션 **안에** 있어(`lineage._assert_job_open`) 창이 없다.
    양쪽 다 실제 API 다: 마감을 잠금 직후에 세워 두고 그 사이에 롤 등록을 보낸다. 반대 순서(롤 등록이 먼저)는 둘 다 200 이 맞다 —
    마감은 롤이 있는 것을 막지 않는다."""
    orders = nav.path_of("JOB-01")
    job_id, job_no = w.new_job("INFLIGHT")
    p, q = (w.print_roll([w.lot], job_no=job_no) for _ in range(2))
    rolls_before, edges_before = _rolls(w), len(w.genealogy())
    try:
        for path, data in ((FIN, {"roll_no": p}), (FIN + "/splice", {"roll_no": [p, q]}), (SLT, {"roll_no": p, "count": "2"})):
            got: dict = {}
            entered, release = pause_after(monkeypatch, job_router, "lock_job")
            closer = threading.Thread(target=lambda: got.update(close=client("prod").post(f"{orders}/{job_no}", data={"status": "완료"})))
            maker = threading.Thread(target=lambda path=path, data=data: got.update(make=client("field").post(path, data=data)))
            try:
                closer.start()
                assert entered.wait(10)                                                                # 마감이 Job 행을 잠갔다 (아직 커밋 전)
                maker.start()
                time.sleep(1.0)
                assert maker.is_alive(), path                                                          # 롤 등록은 그 트랜잭션이 끝나기를 기다린다
            finally:
                release.set()
                for th in (closer, maker):
                    if th.ident is not None:
                        th.join(timeout=20)
            assert not closer.is_alive() and not maker.is_alive()
            assert got["close"].status_code == 200, got["close"].text
            assert err(got["make"])["message"] == "완료 상태의 Job 에는 롤을 만들 수 없습니다", path
            assert (_rolls(w), len(w.genealogy())) == (rolls_before, edges_before) and (_state(p), _state(q)) == ("재고", "재고")
            ok(client("prod").post(f"{orders}/{job_no}", data={"status": "등록"}), "마감 되돌리기")       # 다음 경로를 위해 다시 연다
    finally:
        conn.x("delete from sys_access_log where log_type = '변경' and target = %s", (f"job:{job_no}",))


@pytest.mark.fn("F-RLL-01", "F-RLL-04")
def test_out_of_range_numbers_are_422_naming_the_field(w):
    """DEF-QA1-002 — 컬럼이 담지 못하는 숫자는 422 로, 어느 칸인지 알린다 (길이 numeric(14,3) · 폭 numeric(10,2) · 분할 수 integer)."""
    c = client("field")
    parent, other = _print(w), _print(w)
    rolls_before = _rolls(w)
    for path, data, name in (
            (FIN, {"roll_no": parent, "length_m": "1e15"}, "길이"),
            (FIN, {"roll_no": parent, "length_m": "99999999999.9995"}, "길이"),                       # 반올림하면 자릿수가 넘는다
            (FIN, {"roll_no": parent, "width_mm": "1e9"}, "폭"),
            (FIN, {"roll_no": parent, "width_mm": "100000000"}, "폭"),
            (FIN + "/splice", {"roll_no": [parent, other], "length_m": "100000000000"}, "길이"),
            (SLT, {"roll_no": parent, "count": "1", "widths_mm": "1e9"}, "폭 1"),
            (SLT, {"roll_no": parent, "count": "2", "widths_mm": "500, 99999999.995"}, "폭 2"),
            (SLT, {"roll_no": parent, "count": "2", "length_m": "1e15"}, "길이"),
            (SLT, {"roll_no": parent, "count": "99999999999"}, "분할 수")):
        body = err(c.post(path, data=data))
        assert body["fields"][0]["name"] == name and "너무 큽니다" in body["message"], (path, data, body)
    assert err(c.post(FIN, data={"roll_no": parent, "width_mm": "0.004"}))["fields"][0]["name"] == "폭"   # 담기면 0 이 되는 폭
    assert _rolls(w) == rolls_before and (_state(parent), _state(other)) == ("재고", "재고")
    made = ok(c.post(FIN, data={"roll_no": parent, "length_m": "99999999999.999", "width_mm": "99999999.99"}))["roll_no"]
    row = one("select length_m::text as l, width_mm::text as w from roll where roll_no = %s", (made,))   # 상한까지는 담긴다
    assert row == {"l": "99999999999.999", "w": "99999999.99"}
    made = ok(c.post(FIN, data={"roll_no": other, "length_m": "480.12345"}))["roll_no"]                 # 소수 자릿수를 넘으면 반올림해 담는다
    assert one("select length_m::text as l from roll where roll_no = %s", (made,))["l"] == "480.123"


@pytest.mark.fn("F-RLL-03")
def test_finishing_list_and_scan_flow(w):
    a, b = _print(w), _print(w)
    made = splice([_print(w), _print(w)])
    c = client("qc")                                                                                   # 품질 = 조회
    r = c.get(FIN)
    assert r.status_code == 200 and made in r.text and "splice" in r.text and "data-scan autofocus" in r.text
    # 스캔 흐름: 한 번 스캔 = 롤 하나가 쌓인다 (브라우저는 주소를 정리해 303)
    f = client("field")
    r = f.get(FIN, params={"add": a}, headers=HTML, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"{FIN}?rolls={a}"
    r = f.get(FIN, params={"rolls": a}, headers=HTML)
    assert f'action="{FIN}"' in r.text and f'name="roll_no" value="{a}"' in r.text and "후가공 실적 등록" in r.text
    r = f.get(FIN, params={"rolls": a, "add": b})                                                      # 둘이 되면 splice 로 보낸다
    assert r.status_code == 200 and f'action="{FIN}/splice"' in r.text and "splice 등록" in r.text
    assert f'name="roll_no" value="{a}"' in r.text and f'name="roll_no" value="{b}"' in r.text
    assert "같은 롤 중복" in str(err(f.get(FIN, params={"rolls": a, "add": a}))["fields"])              # 같은 롤을 또 스캔
    assert err(f.get(FIN, params={"rolls": a, "add": "R000000-0000"}))["message"] == "없는 롤 번호입니다"
    fresh = splice([_print(w), _print(w)])
    r = f.get(FIN, params={"rolls": a, "add": fresh}, headers=HTML)                                    # 후가공 롤도 재고면 붙는다(303 뒤 200)
    assert r.status_code == 200 and f'name="roll_no" value="{fresh}"' in r.text
    used = _print(w)
    finishing(used)
    r = f.get(FIN, params={"rolls": a, "add": used, "device": "pop"}, headers=HTML)                    # 소진 롤 스캔 — 큰 글씨, 목록은 그대로
    assert r.status_code == 422 and 'class="err big"' in r.text and "data-scan autofocus" in r.text
    assert f'name="rolls" value="{a}"' in r.text
    r = c.get(FIN, params={"made": made})
    assert 'id="made"' in r.text and decode_barcode(r.text[r.text.index('id="made"'):]) == made


# ── RLL-02 슬리팅 ───────────────────────────────────────────────────────
@pytest.mark.fn("F-RLL-04")
def test_slitting_one_parent_makes_n_rolls_n_edges_n_labels(w):
    parent = finishing(_print(w))
    before = len(w.genealogy())
    body = ok(client("field").post(SLT, data={"roll_no": parent, "count": "3", "widths_mm": "400, 400, 200",
                                              "length_m": "480", "equipment_code": w.eq_code}))
    rolls = conn.q("select roll_no, process_type, slit_seq, width_mm, job_id from roll where roll_no = any(%s) order by slit_seq",
                   (body["rolls"],))
    assert len(body["rolls"]) == 3 and [r["roll_no"] for r in rolls] == body["rolls"]
    assert [(r["process_type"], r["slit_seq"], float(r["width_mm"])) for r in rolls] == [("슬리팅", 1, 400.0), ("슬리팅", 2, 400.0), ("슬리팅", 3, 200.0)]
    assert len(w.genealogy()) == before + 3
    assert all(_edges_into(w, r) == {(parent, "슬리팅")} for r in body["rolls"])
    assert _state(parent) == "소진" and [_state(r) for r in body["rolls"]] == ["재고"] * 3
    assert body["label_urls"] == [f"{HIS}/{r}/label" for r in body["rolls"]]                           # 라벨 N장
    assert change_logs("F-RLL-04", f"roll:{parent}") == 1
    assert len(ok(client("prod").post(SLT, data={"roll_no": _print(w), "count": "1"}))["rolls"]) == 1  # 인쇄 롤도 나눌 수 있다 · N=1


@pytest.mark.fn("F-RLL-04")
def test_slitting_validation(w):
    c = client("field")
    parent = _print(w)
    for cnt in ("0", "-2", "", "셋"):
        assert err(c.post(SLT, data={"roll_no": parent, "count": cnt}))["fields"][0]["name"] == "분할 수"   # N 이 1 미만
    assert "폭의 개수" in err(c.post(SLT, data={"roll_no": parent, "count": "3", "widths_mm": "400,400"}))["message"]
    assert err(c.post(SLT, data={"roll_no": parent, "count": "2", "widths_mm": "400,0"}))["fields"][0]["name"] == "폭 2"
    assert err(c.post(SLT, data={"roll_no": "R000000-0000", "count": "2"}))["message"] == "없는 롤 번호입니다"
    assert _state(parent) == "재고"                                                                    # 실패하면 아무것도 안 생긴다
    made = slit(parent, 2)
    assert "소진" in err(c.post(SLT, data={"roll_no": parent, "count": "2"}))["message"]                # 부모가 재고가 아니면 422
    shipment_id, _ = w.new_shipment("SLT")
    with conn.tx() as cur:
        lineage.ship_roll(cur, shipment_id=shipment_id, roll_id=w.roll_id(made[0]), by=TEST_BY)
    assert "출하" in err(c.post(SLT, data={"roll_no": made[0], "count": "2"}))["message"]               # 출하된 롤 재사용 422


@pytest.mark.fn("F-RLL-05")
def test_slitting_list_and_labels_of_one_parent(w):
    parent = _print(w)
    made = slit(parent, 3, widths_mm="300,300,400")
    c = client("admin")                                                                                # 관리자 = 조회
    r = c.get(SLT)
    assert r.status_code == 200 and all(m in r.text for m in made) and parent in r.text and "300.00" in r.text
    r = c.get(SLT, params={"parent": parent})                                                          # 그 부모의 라벨 N장
    assert r.text.count('data-label-kind="롤 라벨"') == 3 and all(f'data-label-number="{m}"' in r.text for m in made)
    fresh = _print(w)
    r = c.get(SLT, params={"no": fresh})                                                               # 부모 스캔 → 분할 칸
    assert r.status_code == 200 and f'name="roll_no" value="{fresh}"' in r.text
    assert err(c.get(SLT, params={"no": "R000000-0000"}))["message"] == "없는 롤 번호입니다"
    r = c.get(SLT, params={"no": parent}, headers=HTML)                                                # 소진된 롤을 스캔하면 폼 대신 안내
    assert "다시 쓸 수 없습니다" in r.text and f'name="roll_no" value="{parent}"' not in r.text


# ── RLL-03 롤 이력 ──────────────────────────────────────────────────────
@pytest.mark.fn("F-RLL-06")
def test_history_shows_roll_job_state_and_one_step(w):
    a, b = _print(w), _print(w)
    mid = splice([a, b])
    children = slit(mid, 2)
    c = client("qc")
    r = c.get(HIS, params={"no": mid})
    assert r.status_code == 200 and 'id="roll"' in r.text
    assert w.job_no in r.text and "후가공" in r.text and "소진" in r.text                              # 공정 구분 · Job · 상태
    assert all(x in r.text for x in (a, b, *children))                                                # 부모 2 · 자식 2
    r = c.get(HIS, params={"no": a})                                                                   # 인쇄 롤: 부모는 원재료 LOT, 생산 실적이 이어진다
    assert w.lot in r.text and mid in r.text and "실적 수량" in r.text
    r = c.get(HIS, params={"no": children[0].lower()})                                                 # 재고 롤: 자식이 없다
    assert r.status_code == 200 and "재고 — 다음 공정·출하에 쓰이지 않았다" in r.text
    assert err(c.get(HIS, params={"no": "R000000-0000"}))["message"] == "없는 롤 번호입니다"           # 없는 롤 422
    assert err(c.get(HIS, params={"no": w.lot}))["message"] == "없는 롤 번호입니다"
    r = c.get(HIS, params={"no": "R000000-0000", "device": "pop"}, headers=HTML)
    assert r.status_code == 422 and 'class="err big"' in r.text and "data-scan autofocus" in r.text
    r = c.get(HIS)                                                                                     # 번호 없이 열면 최근 롤 + 스캔칸
    assert r.status_code == 200 and "data-scan autofocus" in r.text and mid in r.text


@pytest.mark.fn("F-RLL-06")
def test_history_joins_job_color_work_inspection_shipment_by_roll_number(w):
    """G-08 — 롤 번호 하나로 그 롤의 작업지시·조색 기록·생산 실적·검사 결과·출하가 조회된다."""
    roll_no = _print(w)
    ok(client("qc").post(nav.path_of("CLR-01"), data={"job_no": w.job_no, "color_name": "이력 색 (예시)"}))
    conn.x("""insert into inspection (roll_id, job_id, delta_e, result, inspected_by) values (%s, %s, 1.25, '합격', %s)""",
           (w.roll_id(roll_no), w.job_id, TEST_BY))                                                    # 검사·출하는 개발3 화면의 데이터 — 전제로 넣는다
    shipment_id, shipment_no = w.new_shipment("HIS")
    with conn.tx() as cur:
        lineage.ship_roll(cur, shipment_id=shipment_id, roll_id=w.roll_id(roll_no), by=TEST_BY)
    r = client("prod").get(HIS, params={"no": roll_no})
    assert r.status_code == 200
    assert w.job_no in r.text and w.job_lot_no not in r.text                                           # 작업지시 (생산 LOT 은 지정 안 한 실적)
    assert f"{nav.path_of('CLR-01')}?job_no={w.job_no}" in r.text                                      # 조색 기록
    assert "실적 수량 100.000" in r.text                                                               # 생산 실적
    assert "ΔE 1.25" in r.text and "합격" in r.text                                                    # 검사 결과
    assert shipment_no in r.text and "출하" in r.text                                                  # 출하


@pytest.mark.fn("F-RLL-06")
def test_history_of_finishing_and_slit_rolls_shows_the_ancestor_print_work_results(w):
    """DEF-QA2-001 — 후가공·슬리팅 롤의 생산 실적 = 계보를 거슬러 올라간 조상 인쇄 롤의 실적 (db-schema.md §6 · G-08)."""
    a, b, other = _print(w), _print(w), _print(w)
    mid = splice([a, b])
    slits = slit(finishing(mid), 2)                                                                    # 인쇄 ×2 → splice → 후가공 → 슬리팅 ×2
    lone = finishing(other)
    ok(client("field").post(nav.path_of("POP-02") + "/scrap", data={"work_id": str(_work_id(a)), "scrap_qty": "2"}))
    c = client("qc")
    for roll_no in (mid, *slits):
        r = c.get(HIS, params={"no": roll_no})
        text = _text(r.text)
        assert r.status_code == 200 and 'id="works"' in r.text and "작업 실적은 인쇄 롤에만 있다" not in r.text
        assert all(re.search(rf"실적 {_work_id(x)}\b", text) for x in (a, b)), roll_no               # 조상 인쇄 롤 2개의 실적이 둘 다
        assert not re.search(rf"실적 {_work_id(other)}\b", text)                                       # 계보 밖 인쇄 롤의 실적은 없다
        assert "조상 인쇄 롤 2개의 실적 2건" in text and "정지 0회 · 폐기 1건" in text
        assert all(f"{HIS}?no={x}" in r.text for x in (a, b))                                          # 그 인쇄 롤로 건너간다
    text = _text(c.get(HIS, params={"no": lone}).text)                                                 # 1:1 후가공 — 조상 인쇄 롤 1개
    assert re.search(rf"실적 {_work_id(other)}\b", text) and "조상 인쇄 롤 1개의 실적 1건" in text
    r = c.get(HIS, params={"no": a})                                                                   # 인쇄 롤은 자기 실적 한 건 — 표는 없다
    assert f"실적 {_work_id(a)} ·" in _text(r.text) and 'id="works"' not in r.text and "폐기 1건" in _text(r.text)
    # 실적이 없는 조상(이관으로 들어온 옛 롤 등)뿐이면 `미수집`
    orphan = f"{w.tag}-OLD"
    conn.x("insert into roll (roll_no, process_type, job_id, produced_by) values (%s, '후가공', %s, %s)", (orphan, w.job_id, TEST_BY))
    r = c.get(HIS, params={"no": orphan})
    works = r.text[r.text.index('id="works"'):]
    assert r.status_code == 200 and "미수집" in works[:works.index("</section>")]


@pytest.mark.fn("F-RLL-07")
def test_roll_label_kinds_and_barcode(w):
    printed = _print(w)
    slit_rolls = slit(finishing(_print(w)), 2, widths_mm="500,500")
    c = client("field")
    r = c.get(f"{HIS}/{slit_rolls[1]}/label")
    assert r.status_code == 200 and 'data-label-kind="롤 라벨"' in r.text                             # 후가공·슬리팅 롤 = 롤 라벨
    assert decode_barcode(r.text) == slit_rolls[1] and "슬리팅 (분할 2)" in r.text and "500.00" in r.text
    assert w.job_no in r.text and "window.print()" in r.text and "<img" not in r.text
    r = c.get(f"{HIS}/{printed}/label")                                                                # 인쇄 롤도 같은 양식으로 재출력된다
    assert r.status_code == 200 and 'data-label-kind="인쇄 롤 라벨"' in r.text and decode_barcode(r.text) == printed
    err(c.get(f"{HIS}/R000000-0000/label"), 404)
    # 그 바코드 값을 스캔칸에 넣으면 그 롤이 열린다 (G-14)
    opened = c.get(HIS, params={"no": decode_barcode(c.get(f"{HIS}/{slit_rolls[0]}/label").text)})
    assert opened.status_code == 200 and 'id="roll"' in opened.text and slit_rolls[0] in opened.text


# ── 권한 ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("who", ["admin", "qc"])
def test_read_only_roles_cannot_write(w, who):
    """관리자·품질 × 후가공·슬리팅 = 조회 → 쓰기 403. 롤은 그대로 재고."""
    a, b = _print(w), _print(w)
    c = client(who)
    err(c.post(FIN, data={"roll_no": a}), 403)
    err(c.post(FIN + "/splice", data={"roll_no": [a, b]}), 403)
    err(c.post(SLT, data={"roll_no": a, "count": "2"}), 403)
    assert (_state(a), _state(b)) == ("재고", "재고")
    for path in (FIN, SLT, HIS, f"{HIS}/{a}/label"):
        assert c.get(path).status_code == 200


def test_anonymous_is_401():
    for path in (FIN, FIN + "/splice", SLT):
        err(client().post(path, data={}), 401)
    err(client().get(HIS), 401)
