"""생산 실적 POP (POP · 기능 8) — 작업 실적 · 정지/폐기 · 롤 라벨. 화면이 부르는 엔드포인트로 검증한다.

기대값은 contracts/function-list.md 의 계약 문장이다. 권한: 생산·현장 = 입력 · 관리자·품질 = 조회 (설계도 §6).
POP 의 시작·종료·정지는 사람이 누르는 기록이다.
"""
import threading
import time

import pytest

from lcomfine.app import nav
from lcomfine.app.routers import job as job_router
from lcomfine.app.routers import pop as pop_router
from lcomfine.db import conn

from test_dev2_helpers import (HTML, World, change_logs, client, count, decode_barcode, err, finish, ok, one,
                               pause_after, scan_input, start)

WORK, STOPS, LABELS = (nav.path_of(s) for s in ("POP-01", "POP-02", "POP-03"))


@pytest.fixture(scope="module")
def w():
    world = World()
    try:
        yield world
    finally:
        world.cleanup()
        assert world.leftovers() == 0


def _work(work_id: int) -> dict:
    return one("select * from work_result where work_result_id = %s", (work_id,))


# ── POP-01 작업 실적 ────────────────────────────────────────────────────
@pytest.mark.fn("F-POP-01")
def test_work_start_creates_running_work_and_leaves_job_alone(w):
    job_before = one("select status, updated_at from job where job_id = %s", (w.job_id,))
    body = ok(client("field").post(WORK + "/start", data={"job_no": w.job_no, "lot_no": w.job_lot_no,
                                                         "equipment_code": w.eq_code}))
    row = _work(body["work_id"])
    assert row["job_id"] == w.job_id and row["status"] == "진행" and row["started_at"] is not None and row["ended_at"] is None
    assert row["equipment_id"] == w.eq_id and row["worker"] == "field"
    assert row["job_lot_id"] == one("select job_lot_id from job_lot where lot_no = %s", (w.job_lot_no,))["job_lot_id"]
    assert one("select status, updated_at from job where job_id = %s", (w.job_id,)) == job_before    # D2 는 P2 만 쓴다
    assert change_logs("F-POP-01", f"work_result:{body['work_id']}") == 1
    ok(client("prod").post(WORK + "/start", data={"job_no": w.job_no.lower()}))                      # LOT·설비는 선택


@pytest.mark.fn("F-POP-01")
def test_work_start_validation_is_422(w):
    c = client("field")
    assert err(c.post(WORK + "/start", data={}))["fields"][0]["name"] == "Job 번호"
    assert err(c.post(WORK + "/start", data={"job_no": "J000000-000"}))["message"] == "없는 Job 번호입니다"
    for status in ("취소", "완료"):
        _, job_no = w.new_job(f"X{status}", status=status)
        assert status in err(c.post(WORK + "/start", data={"job_no": job_no}))["message"]            # 취소·완료 Job 은 422
    other_id, other_no = w.new_job("OTHER")
    conn.x("insert into job_lot (job_id, lot_no, created_by) values (%s, %s, 't2-test')", (other_id, f"{w.tag}-LX"))
    assert "이 Job 의 생산 LOT 이 아닙니다" in err(c.post(WORK + "/start", data={"job_no": w.job_no, "lot_no": f"{w.tag}-LX"}))["message"]
    assert err(c.post(WORK + "/start", data={"job_no": w.job_no, "lot_no": "L000000-000"}))["fields"][0]["name"] == "생산 LOT"
    assert err(c.post(WORK + "/start", data={"job_no": w.job_no, "equipment_code": "없는설비"}))["fields"][0]["name"] == "설비"


@pytest.mark.fn("F-POP-02")
def test_work_finish_makes_one_print_roll_with_input_edges(w):
    """작업 종료 = 실적 `완료` + 인쇄 롤 1개 + 투입 LOT 마다 계보 `투입` 한 줄. 한 트랜잭션."""
    lot_a, lot_b = w.good_lot(), w.good_lot()
    work_id = start(w, lot_no=w.job_lot_no)
    scan_input(work_id, lot_a, qty="40")
    scan_input(work_id, lot_b, qty=None)
    before = len(w.genealogy())
    body = ok(client("field").post(f"{WORK}/{work_id}/finish", data={"output_qty": "480.5", "length_m": "500", "width_mm": "1200"}))
    roll = one("select * from roll where roll_no = %s", (body["roll_no"],))
    assert roll["process_type"] == "인쇄" and roll["work_result_id"] == work_id and roll["job_id"] == w.job_id
    assert roll["equipment_id"] == w.eq_id and float(roll["length_m"]) == 500 and float(roll["width_mm"]) == 1200
    assert roll["job_lot_id"] == _work(work_id)["job_lot_id"] is not None                              # Job → 생산 LOT → Roll
    done = _work(work_id)
    assert done["status"] == "완료" and done["ended_at"] is not None and float(done["output_qty"]) == 480.5
    assert done["qty_unit"] == "m"                                                                     # 비우면 Job 의 단위
    edges = [g for g in w.genealogy() if g["child_no"] == body["roll_no"]]
    assert len(w.genealogy()) == before + 2
    assert {(g["parent_no"], g["relation"]) for g in edges} == {(lot_a, "투입"), (lot_b, "투입")}
    assert {g["parent_no"]: g["qty"] for g in edges}[lot_a] == 40 and {g["parent_no"]: g["qty"] for g in edges}[lot_b] is None
    assert body["label_url"] == f"{LABELS}/{body['roll_no']}/print"                                    # 응답에 롤 번호와 라벨 링크
    assert change_logs("F-POP-02", f"roll:{body['roll_no']}") == 1
    assert one("select state from v_roll_state where roll_no = %s", (body["roll_no"],))["state"] == "재고"
    again = err(client("field").post(f"{WORK}/{work_id}/finish", data={"output_qty": "1"}))            # 실적 1건 = 롤 1개
    assert "이미 종료" in again["message"]
    assert count("select count(*) as n from roll where work_result_id = %s", (work_id,)) == 1


@pytest.mark.fn("F-POP-02")
def test_work_finish_validation(w):
    c = client("field")
    work_id = start(w)
    body = err(c.post(f"{WORK}/{work_id}/finish", data={"output_qty": "10"}))                          # 투입 0건이면 422
    assert "자재 투입 스캔이 없습니다" in body["message"]
    assert _work(work_id)["status"] == "진행" and count("select count(*) as n from roll where work_result_id = %s", (work_id,)) == 0
    scan_input(work_id, w.good_lot())
    assert err(c.post(f"{WORK}/{work_id}/finish", data={}))["fields"][0]["name"] == "실적 수량"
    assert err(c.post(f"{WORK}/{work_id}/finish", data={"output_qty": "-1"}))["fields"][0]["name"] == "실적 수량"
    assert err(c.post(f"{WORK}/{work_id}/finish", data={"output_qty": "1", "width_mm": "0"}))["fields"][0]["name"] == "폭"
    assert _work(work_id)["status"] == "진행"                                                          # 실패하면 아무것도 안 바뀐다
    err(c.post(f"{WORK}/999999999/finish", data={"output_qty": "1"}), 404)                             # 경로의 키가 없으면 404
    err(c.post(f"{WORK}/abc/finish", data={"output_qty": "1"}), 404)
    stop_id = ok(c.post(STOPS, data={"work_id": str(work_id), "stop_reason": "판 교체 (예시)"}))["stop_id"]
    assert "재개한 뒤 종료" in err(c.post(f"{WORK}/{work_id}/finish", data={"output_qty": "1"}))["message"]
    ok(c.post(f"{STOPS}/{stop_id}/resume"))
    finish(work_id)


@pytest.mark.fn("F-POP-02", "F-POP-06")
def test_out_of_range_numbers_are_422_naming_the_field(w):
    """DEF-QA1-002 — 컬럼이 담지 못하는 숫자는 500 이 아니라 422, 어느 칸인지 알린다 (수량·길이 numeric(14,3) · 폭 numeric(10,2))."""
    c = client("field")
    work_id = start(w)
    scan_input(work_id, w.good_lot())
    for path, data, name in (
            (f"{WORK}/{work_id}/finish", {"output_qty": "1e15"}, "실적 수량"),
            (f"{WORK}/{work_id}/finish", {"output_qty": "100000000000"}, "실적 수량"),               # 정수부 12자리
            (f"{WORK}/{work_id}/finish", {"output_qty": "99999999999.9995"}, "실적 수량"),           # 반올림하면 12자리
            (f"{WORK}/{work_id}/finish", {"output_qty": "1", "length_m": "1e15"}, "길이"),
            (f"{WORK}/{work_id}/finish", {"output_qty": "1", "width_mm": "1e9"}, "폭"),
            (f"{STOPS}/scrap", {"work_id": str(work_id), "scrap_qty": "1e15"}, "폐기 수량"),
            (f"{STOPS}/scrap", {"work_id": str(work_id), "scrap_qty": "1e-9"}, "폐기 수량"),          # 담기면 0 — 0 보다 커야 한다
            (f"{STOPS}/scrap", {"work_id": "99999999999999999999", "scrap_qty": "1"}, "작업 실적"),
            (STOPS, {"work_id": "99999999999999999999", "stop_reason": "x"}, "작업 실적")):
        body = err(c.post(path, data=data))
        assert body["fields"][0]["name"] == name, (path, data, body)
    body = err(c.post(f"{WORK}/{work_id}/finish", data={"output_qty": "1e15"}))
    assert body["message"] == "실적 수량이(가) 너무 큽니다" and "정수부 11자리" in body["fields"][0]["reason"]
    assert _work(work_id)["status"] == "진행" and count("select count(*) as n from roll where work_result_id = %s", (work_id,)) == 0
    assert count("select count(*) as n from work_scrap where work_result_id = %s", (work_id,)) == 0
    ok(c.post(f"{STOPS}/scrap", data={"work_id": str(work_id), "scrap_qty": "99999999999.999"}))       # 상한까지는 담긴다
    roll_no = finish(work_id, qty="99999999999.999", length_m="99999999999.999", width_mm="99999999.99")
    assert one("select output_qty::text as q from work_result where work_result_id = %s", (work_id,))["q"] == "99999999999.999"
    assert one("select width_mm::text as w from roll where roll_no = %s", (roll_no,))["w"] == "99999999.99"
    for path, params in ((STOPS, {"work_id": "99999999999999999999"}), (nav.path_of("MAT-04"), {"work_id": "99999999999999999999"})):
        assert err(c.get(path, params=params))["fields"][0]["name"] == "작업 실적"                    # 조회의 키도 500 이 아니다


@pytest.mark.fn("F-POP-02")
def test_work_finish_is_atomic(w, monkeypatch):
    """롤 생성 뒤에 실패하면 롤·계보·실적 상태가 함께 되돌아간다 (한 트랜잭션)."""
    from lcomfine.app import lineage

    work_id = start(w)
    scan_input(work_id, w.good_lot())
    real = lineage.link

    def broken(cur, parent, child, relation, **kw):
        real(cur, parent, child, relation, **kw)
        raise lineage.http.validation_error("테스트가 낸 실패", fields=[])

    monkeypatch.setattr(lineage, "link", broken)
    before = len(w.genealogy())
    err(client("field").post(f"{WORK}/{work_id}/finish", data={"output_qty": "1"}))
    monkeypatch.undo()
    assert _work(work_id)["status"] == "진행" and _work(work_id)["ended_at"] is None
    assert count("select count(*) as n from roll where work_result_id = %s", (work_id,)) == 0
    assert len(w.genealogy()) == before
    finish(work_id)                                                                                    # 다시 하면 된다
    assert len(w.genealogy()) == before + 1


@pytest.mark.fn("F-POP-03")
def test_work_list_and_job_scan_entry(w):
    running, done = start(w), start(w)
    scan_input(done, w.good_lot())
    roll_no = finish(done)
    c = client("qc")                                                                                   # 품질 = 조회
    r = c.get(WORK)
    assert r.status_code == 200 and w.job_no in r.text and roll_no in r.text                           # 진행 중 · 오늘 완료 · 만든 롤
    assert f"{WORK}/{running}/finish" in r.text and f"{WORK}/{done}/finish" not in r.text
    assert "data-scan autofocus" in r.text                                                             # 스캔칸이 포커스를 잡는다 (G-13)
    r = c.get(WORK, params={"no": w.job_no})                                                           # 작업지시서 바코드 스캔 → 시작 칸
    assert r.status_code == 200 and 'id="start"' in r.text and f'name="job_no" value="{w.job_no}"' in r.text
    assert w.job_lot_no in r.text
    assert err(c.get(WORK, params={"no": "J000000-000"}))["message"] == "없는 Job 번호입니다"          # 없는 번호 스캔 = 422
    r = c.get(WORK, params={"no": "J000000-000", "device": "pop"}, headers=HTML)
    assert r.status_code == 422 and 'class="err big"' in r.text and "data-scan autofocus" in r.text    # 큰 글씨 + 스캔칸 유지
    r = c.get(WORK, params={"day": "2000-01-01"})                                                      # 다른 날: 그날 완료 건은 없다
    assert roll_no not in r.text
    r = c.get(WORK, params={"roll": roll_no})                                                          # 종료 직후: 방금 만든 롤의 라벨
    assert 'id="made"' in r.text and decode_barcode(r.text[r.text.index('id="made"'):]) == roll_no


# ── POP-02 정지 · 폐기 ──────────────────────────────────────────────────
@pytest.mark.fn("F-POP-04", "F-POP-05")
def test_stop_then_resume(w):
    c = client("field")
    work_id = start(w)
    stop_id = ok(c.post(STOPS, data={"work_id": str(work_id), "stop_reason": "잉크 보충 (예시)"}))["stop_id"]
    stop = one("select * from work_stop where work_stop_id = %s", (stop_id,))
    assert stop["stop_reason"] == "잉크 보충 (예시)" and stop["stopped_at"] is not None and stop["resumed_at"] is None
    assert _work(work_id)["status"] == "정지"
    assert change_logs("F-POP-04", f"work_stop:{stop_id}") == 1
    assert "진행 중인 작업만" in err(c.post(STOPS, data={"work_id": str(work_id), "stop_reason": "또 정지"}))["message"]
    assert "진행 중인 작업에만" in err(c.post(nav.path_of("MAT-04"), data={"work_id": str(work_id), "lot_no": w.good_lot()}))["message"]

    body = ok(c.post(f"{STOPS}/{stop_id}/resume"))
    assert body["work_id"] == work_id and _work(work_id)["status"] == "진행"
    assert one("select resumed_at from work_stop where work_stop_id = %s", (stop_id,))["resumed_at"] is not None
    assert change_logs("F-POP-05", f"work_stop:{stop_id}") == 1
    assert "이미 재개" in err(c.post(f"{STOPS}/{stop_id}/resume"))["message"]                           # 이미 재개한 정지는 422
    err(c.post(f"{STOPS}/999999999/resume"), 404)
    ok(c.post(STOPS, data={"work_id": str(work_id), "stop_reason": "두 번째 정지", "stopped_at": "2020-01-01T09:00"}))
    assert count("select count(*) as n from work_stop where work_result_id = %s", (work_id,)) == 2


@pytest.mark.fn("F-POP-04")
def test_stop_validation(w):
    c = client("field")
    work_id = start(w)
    assert err(c.post(STOPS, data={"work_id": str(work_id)}))["fields"][0]["name"] == "정지 사유"
    assert err(c.post(STOPS, data={"stop_reason": "x"}))["fields"][0]["name"] == "작업 실적"
    assert err(c.post(STOPS, data={"work_id": "999999999", "stop_reason": "x"}))["message"] == "없는 작업 실적입니다"
    assert err(c.post(STOPS, data={"work_id": str(work_id), "stop_reason": "x", "stopped_at": "어제"}))["fields"][0]["name"] == "정지 시각"
    assert err(c.post(STOPS, data={"work_id": str(work_id), "stop_reason": "x", "stopped_at": "2999-01-01T00:00"}))["fields"][0]["name"] == "정지 시각"
    assert _work(work_id)["status"] == "진행" and count("select count(*) as n from work_stop where work_result_id = %s", (work_id,)) == 0


@pytest.mark.fn("F-POP-06")
def test_scrap_records_quantity_only(w):
    c = client("prod")
    work_id = start(w)
    before = len(w.genealogy())
    body = ok(c.post(STOPS + "/scrap", data={"work_id": str(work_id), "scrap_qty": "12.5", "qty_unit": "m",
                                             "defect_code": w.defect_code, "reason": "초기 조정분 (예시)"}))
    row = one("select * from work_scrap where work_scrap_id = %s", (body["scrap_id"],))
    assert float(row["scrap_qty"]) == 12.5 and row["defect_code_id"] == w.defect_id and row["created_by"] == "prod"
    assert change_logs("F-POP-06", f"work_scrap:{body['scrap_id']}") == 1
    assert len(w.genealogy()) == before and count("select count(*) as n from roll where work_result_id = %s", (work_id,)) == 0
    assert _work(work_id)["status"] == "진행"                                                          # 롤·계보·상태를 건드리지 않는다
    ok(c.post(STOPS + "/scrap", data={"work_id": str(work_id), "scrap_qty": "1"}))                     # 사유는 선택
    for qty in ("0", "-1", "", "많이"):
        assert err(c.post(STOPS + "/scrap", data={"work_id": str(work_id), "scrap_qty": qty}))["fields"][0]["name"] == "폐기 수량"
    assert err(c.post(STOPS + "/scrap", data={"work_id": str(work_id), "scrap_qty": "1", "defect_code": "없는코드"}))["fields"][0]["name"] == "불량코드"
    assert err(c.post(STOPS + "/scrap", data={"work_id": "999999999", "scrap_qty": "1"}))["message"] == "없는 작업 실적입니다"
    assert count("select count(*) as n from work_scrap where work_result_id = %s", (work_id,)) == 2


@pytest.mark.fn("F-POP-07")
def test_stop_and_scrap_list(w):
    c = client("field")
    work_id, quiet = start(w), start(w)
    ok(c.post(STOPS, data={"work_id": str(work_id), "stop_reason": "조회용 정지 (예시)"}))
    ok(c.post(STOPS + "/scrap", data={"work_id": str(work_id), "scrap_qty": "3", "reason": "조회용 폐기 (예시)"}))
    r = client("admin").get(STOPS, params={"work_id": work_id})                                        # 관리자 = 조회
    assert r.status_code == 200 and "조회용 정지 (예시)" in r.text and "조회용 폐기 (예시)" in r.text and "3.000" in r.text
    r = client("admin").get(STOPS, params={"work_id": quiet})                                          # 0건이면 미수집
    assert r.status_code == 200 and r.text.count("미수집") >= 2 and "조회용 정지" not in r.text
    assert "조회용 정지 (예시)" in client("admin").get(STOPS).text


# ── POP-03 롤 라벨 ──────────────────────────────────────────────────────
@pytest.mark.fn("F-POP-08")
def test_print_roll_label_has_scannable_barcode(w):
    roll_no = w.print_roll([w.good_lot()])
    c = client("field")
    r = c.get(f"{LABELS}/{roll_no}/print")
    assert r.status_code == 200
    assert 'data-label-kind="인쇄 롤 라벨"' in r.text and f'data-label-number="{roll_no}"' in r.text
    assert decode_barcode(r.text) == roll_no                                                           # 바코드 → 디코드 → 원래 번호
    assert w.job_no in r.text and w.item_code in r.text and "500.000" in r.text                        # Job · 품목 · 길이
    assert "window.print()" in r.text and "<img" not in r.text and "cdn" not in r.text.lower()
    err(c.get(f"{LABELS}/R000000-0000/print"), 404)
    # 그 바코드 값을 스캔칸에 넣으면 그 롤이 열린다 (G-14)
    opened = c.get(nav.path_of("RLL-03"), params={"no": decode_barcode(r.text)})
    assert opened.status_code == 200 and 'id="roll"' in opened.text and roll_no in opened.text
    # 화면 /pop/roll-labels — 라벨을 뽑을 인쇄 롤 목록 · 스캔하면 미리보기
    listing = c.get(LABELS)
    assert listing.status_code == 200 and f"{LABELS}/{roll_no}/print" in listing.text and "data-scan autofocus" in listing.text
    assert decode_barcode(c.get(LABELS, params={"no": roll_no}).text) == roll_no
    assert err(c.get(LABELS, params={"no": "R000000-0000"}))["message"] == "없는 롤 번호입니다"


# ── 권한 · 채널 ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("who", ["admin", "qc"])
def test_read_only_roles_cannot_write(w, who):
    """관리자·품질 × 생산 실적 = 조회 → 쓰기 403. 화면은 열린다."""
    c = client(who)
    work_id = start(w)
    for path, data in ((WORK + "/start", {"job_no": w.job_no}),
                       (f"{WORK}/{work_id}/finish", {"output_qty": "1"}),
                       (STOPS, {"work_id": str(work_id), "stop_reason": "x"}),
                       (f"{STOPS}/1/resume", {}),
                       (STOPS + "/scrap", {"work_id": str(work_id), "scrap_qty": "1"})):
        err(c.post(path, data=data), 403)
    assert _work(work_id)["status"] == "진행"
    for path in (WORK, STOPS, LABELS):
        assert c.get(path).status_code == 200


def test_anonymous_is_401():
    for path in (WORK + "/start", STOPS, STOPS + "/scrap", WORK + "/1/finish", STOPS + "/1/resume"):
        err(client().post(path, data={}), 401)


def test_pop_channel_layout_and_disabled_buttons(w):
    """`?device=pop` — 터치용 레이아웃(body.ch-pop). 조회 역할에게 쓰기 버튼은 비활성으로 보인다."""
    start(w)
    r = client("field").get(WORK, params={"device": "pop", "no": w.job_no}, headers=HTML)
    assert r.status_code == 200 and 'class="ch-pop"' in r.text and 'name="device" value="pop"' in r.text
    assert "disabled title=" not in r.text[r.text.index('id="start"'):r.text.index("</section>", r.text.index('id="start"'))]
    r = client("qc").get(WORK, params={"no": w.job_no}, headers=HTML)
    assert "disabled title=" in r.text[r.text.index('id="start"'):r.text.index("</section>", r.text.index('id="start"'))]


@pytest.mark.fn("F-POP-02")
def test_pop_channel_survives_the_redirect_after_a_write(w):
    """`?device=pop` 으로 연 화면에서 쓰기를 하면 돌아가는 주소에도 그 채널이 붙는다 (D-19 채널 훅)."""
    c = client("field")
    work_id = start(w)
    scan_input(work_id, w.good_lot())
    r = c.post(f"{WORK}/{work_id}/finish", data={"output_qty": "1"}, headers={**HTML, "referer": f"http://testserver{WORK}?device=pop"},
               follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith(f"{WORK}?roll=R") and r.headers["location"].endswith("&device=pop")
    page = c.get(r.headers["location"], headers=HTML)
    assert page.status_code == 200 and 'class="ch-pop"' in page.text and 'id="made"' in page.text
    r = c.post(WORK + "/start", data={"job_no": w.job_no}, headers={**HTML, "referer": f"http://testserver{WORK}"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == WORK                       # 채널 없이 열었으면 그대로


# ── 작업 시작과 Job 취소·마감이 겹칠 때 (DEF-QA2-004 · D-211) ────────────
_CLOSE = {"취소": "C", "완료": "D"}       # Job 번호는 주소에 들어간다 — 접미는 영문으로


def _close(closing: str, job_no: str):
    """F-JOB-03 취소 · F-JOB-02 마감(`완료`) — 작업지시 화면이 부르는 그대로 (생산 역할)."""
    c = client("prod")
    if closing == "취소":
        return c.post(f"{nav.path_of('JOB-01')}/{job_no}/cancel")
    return c.post(f"{nav.path_of('JOB-01')}/{job_no}", data={"status": "완료"})


def _job_state(job_id: int) -> tuple:
    return (one("select status from job where job_id = %s", (job_id,))["status"],
            count("select count(*) as n from work_result where job_id = %s", (job_id,)))


def _drop_job_logs(w) -> None:
    """이 묶음의 Job 을 취소·마감하며 남긴 변경 로그 — `World.cleanup` 은 개발1 화면의 로그를 모른다."""
    conn.x("delete from sys_access_log where log_type = '변경' and target like %s", (f"job:{w.tag}%",))


@pytest.mark.fn("F-POP-01")
@pytest.mark.parametrize("closing", ["취소", "완료"])
def test_work_start_waits_for_a_cancel_or_close_in_flight_and_then_refuses(w, monkeypatch, closing):
    """취소·마감이 Job 행을 잠그고 아직 커밋하지 않은 동안 들어온 작업 시작은 **기다렸다가** 바뀐 상태를 보고 422.

    고치기 전에는 트랜잭션 밖에서 읽은 `등록` 을 믿고 실적을 넣어 200 이었다(닫힌 Job 에 열린 실적). 양쪽 다 실제 API 다 —
    취소·마감을 잠금 직후에 세워 두고(`job.lock_job` 뒤) 그 사이에 작업 시작을 보낸다."""
    job_id, job_no = w.new_job(f"WAIT{_CLOSE[closing]}")
    got: dict = {}
    entered, release = pause_after(monkeypatch, job_router, "lock_job")
    closer = threading.Thread(target=lambda: got.update(close=_close(closing, job_no)))
    starter = threading.Thread(target=lambda: got.update(start=client("field").post(
        WORK + "/start", data={"job_no": job_no, "equipment_code": w.eq_code})))
    try:
        closer.start()
        assert entered.wait(10)                                               # 취소·마감이 Job 행을 잠갔다 (아직 커밋 전)
        starter.start()
        time.sleep(1.0)
        assert starter.is_alive()                                             # 작업 시작은 그 트랜잭션이 끝나기를 기다린다
        assert _job_state(job_id) == ("등록", 0)                              # 아직 아무것도 커밋되지 않았다
    finally:
        release.set()
        for th in (closer, starter):
            if th.ident is not None:
                th.join(timeout=20)
        _drop_job_logs(w)
    assert not closer.is_alive() and not starter.is_alive()
    assert got["close"].status_code == 200, got["close"].text
    body = err(got["start"])                                                  # 둘 중 하나만 통과한다
    assert body["message"] == f"{closing} 상태의 Job 은 작업을 시작할 수 없습니다"
    assert body["fields"] == [{"name": job_no, "reason": f"상태 {closing}"}]
    assert _job_state(job_id) == (closing, 0)                                 # 닫힌 Job 에 실적이 없다


@pytest.mark.fn("F-POP-01")
@pytest.mark.parametrize("closing", ["취소", "완료"])
def test_cancel_or_close_waits_for_a_work_start_in_flight_and_then_refuses(w, monkeypatch, closing):
    """반대 순서 — 작업 시작이 Job 행을 잠그고(`for share`) 실적을 넣는 동안 들어온 취소·마감은 기다렸다가 그 실적을 세고 422."""
    job_id, job_no = w.new_job(f"HOLD{_CLOSE[closing]}")
    got: dict = {}
    entered, release = pause_after(monkeypatch, pop_router, "assert_job_open")
    starter = threading.Thread(target=lambda: got.update(start=client("field").post(
        WORK + "/start", data={"job_no": job_no, "equipment_code": w.eq_code})))
    closer = threading.Thread(target=lambda: got.update(close=_close(closing, job_no)))
    try:
        starter.start()
        assert entered.wait(10)                                               # 작업 시작이 Job 행을 잠갔다 (실적은 아직 커밋 전)
        closer.start()
        time.sleep(1.0)
        assert closer.is_alive()
    finally:
        release.set()
        for th in (starter, closer):
            if th.ident is not None:
                th.join(timeout=20)
        _drop_job_logs(w)
    assert not closer.is_alive() and not starter.is_alive()
    ok(got["start"], "작업 시작")
    body = err(got["close"])
    assert ("작업 실적" in body["message"]) and _job_state(job_id) == ("등록", 1)


@pytest.mark.fn("F-POP-01")
@pytest.mark.parametrize("closing", ["취소", "완료"])
def test_work_start_racing_with_cancel_or_close_lets_exactly_one_through(w, closing):
    """실제 동시 요청 — 화면의 시작 폼이 보내는 값(Job · 생산 LOT · 설비)과 취소·마감을 같이 출발시킨다.

    매번 **정확히 하나만** 200 이어야 한다: 시작이 이기면 Job 은 `등록` · 실적 1건, 취소·마감이 이기면 Job 은 닫히고 실적 0건.
    교착이 나면 그 요청이 503 이라 여기서 걸린다(`[200, 422]` 가 아니다)."""
    starter, closer = client("field"), client("prod")
    outcomes: dict[str, int] = {}
    try:
        for n in range(25):
            job_id, job_no = w.new_job(f"RACE{_CLOSE[closing]}{n}")
            lot_no = f"{job_no}-L"
            conn.x("insert into job_lot (job_id, lot_no, created_by) values (%s, %s, 't2-test')", (job_id, lot_no))
            got: dict[str, int] = {}
            gate = threading.Barrier(2)

            def go_start():
                gate.wait()
                got["start"] = starter.post(WORK + "/start", data={"job_no": job_no, "lot_no": lot_no,
                                                                   "equipment_code": w.eq_code}).status_code

            def go_close():
                gate.wait()
                url = f"{nav.path_of('JOB-01')}/{job_no}"
                got["close"] = (closer.post(url + "/cancel") if closing == "취소"
                                else closer.post(url, data={"status": "완료"})).status_code

            threads = [threading.Thread(target=go_start), threading.Thread(target=go_close)]
            for th in threads:
                th.start()
            for th in threads:
                th.join(timeout=30)
            assert not any(th.is_alive() for th in threads), f"시도 {n}: 30초 안에 끝나지 않았다 (교착?)"
            assert sorted(got.values()) == [200, 422], f"시도 {n}: {got} · Job {_job_state(job_id)} · 그때까지 {outcomes}"
            expected = ("등록", 1) if got["start"] == 200 else (closing, 0)
            assert _job_state(job_id) == expected, f"시도 {n}: {got}"
            key = "시작이 먼저" if got["start"] == 200 else f"{closing}가 먼저"
            outcomes[key] = outcomes.get(key, 0) + 1
    finally:
        _drop_job_logs(w)
    assert sum(outcomes.values()) == 25
