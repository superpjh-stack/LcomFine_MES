"""자재 · 입고 (MAT · 기능 8) — 입고 · 입고검사 · 원재료 LOT · 자재 투입. 화면이 부르는 엔드포인트로 검증한다.

기대값은 contracts/function-list.md 의 계약 문장과 api-contract.md 의 오류 계약이다.
권한: 생산·현장 = 입력(일반) · 품질 = 입력(입고검사만) · 관리자 = 조회 (설계도 §6, D-14).
"""
import pytest

from lcomfine.app import nav

from test_dev2_helpers import (HTML, World, change_logs, client, count, decode_barcode, err, finish, inspect, ok, one,
                               receive, scan_input, start)

REC, INS, LOTS, INP = (nav.path_of(s) for s in ("MAT-01", "MAT-02", "MAT-03", "MAT-04"))


@pytest.fixture(scope="module")
def w():
    world = World()
    try:
        yield world
    finally:
        world.cleanup()
        assert world.leftovers() == 0


# ── MAT-01 입고 ─────────────────────────────────────────────────────────
@pytest.mark.fn("F-MAT-01")
def test_receipt_creates_one_material_lot_waiting_for_inspection(w):
    before = count("select count(*) as n from material_lot where item_id = %s", (w.raw_id,))
    body = ok(client("field").post(REC, data={"item_code": w.raw_code, "supplier_name": "공급처 (예시)",
                                              "supplier_lot_no": "SL-1", "received_qty": "1,250.5"}))
    lot = one("select * from material_lot where lot_no = %s", (body["lot_no"],))
    assert count("select count(*) as n from material_lot where item_id = %s", (w.raw_id,)) == before + 1   # 입고 1건 = LOT 1개
    assert lot["insp_status"] == "대기" and lot["insp_at"] is None and body["insp_status"] == "대기"
    assert float(lot["received_qty"]) == 1250.5 and lot["qty_unit"] == "m"          # 단위를 비우면 품목의 단위
    assert lot["received_by"] == "field" and lot["supplier_lot_no"] == "SL-1"
    assert body["label_url"] == f"{LOTS}/{body['lot_no']}/label"
    assert change_logs("F-MAT-01", f"material_lot:{body['lot_no']}") == 1          # G-18
    # LOT 번호는 채번 한 곳에서 나온다 — 연달아 받으면 서로 다르다
    assert receive(w) != receive(w)


@pytest.mark.fn("F-MAT-01")
@pytest.mark.parametrize("data, name", [
    ({"received_qty": "10"}, "원재료 품목"),                                   # 필수값 누락
    ({"item_code": "없는-품목", "received_qty": "10"}, "원재료 품목"),
    ({"item_code": "FG", "received_qty": "10"}, "원재료 품목"),                # 제품 품목은 입고 불가
    ({"item_code": "RM"}, "입고 수량"),
    ({"item_code": "RM", "received_qty": "0"}, "입고 수량"),
    ({"item_code": "RM", "received_qty": "-3"}, "입고 수량"),
    ({"item_code": "RM", "received_qty": "열 개"}, "입고 수량"),
])
def test_receipt_validation_is_422(w, data, name):
    data = {k: {"FG": w.item_code, "RM": w.raw_code}.get(v, v) for k, v in data.items()}
    before = count("select count(*) as n from material_lot where item_id = %s", (w.raw_id,))
    body = err(client("field").post(REC, data=data))
    assert body["fields"][0]["name"] == name
    assert count("select count(*) as n from material_lot where item_id = %s", (w.raw_id,)) == before


@pytest.mark.fn("F-MAT-02")
def test_receipt_list_and_filters(w):
    lot_no = receive(w, supplier_name="필터-공급처 (예시)")
    c = client("admin")                                                         # 관리자 = 조회
    r = c.get(REC, params={"item_code": w.raw_code})
    assert r.status_code == 200 and lot_no in r.text and "대기" in r.text
    assert lot_no in c.get(REC, params={"supplier": "필터-공급처"}).text
    r = c.get(REC, params={"item_code": w.raw_code, "date_to": "2000-01-01"})  # 0건이면 미수집 (G-11)
    assert r.status_code == 200 and lot_no not in r.text and "미수집" in r.text
    assert err(c.get(REC, params={"date_from": "어제"}))["fields"][0]["name"] == "입고일(부터)"


# ── MAT-02 입고검사 ─────────────────────────────────────────────────────
@pytest.mark.fn("F-MAT-03")
def test_inspection_result_by_quality_role(w):
    lot_no = receive(w)
    body = ok(client("qc").post(INS, data={"lot_no": lot_no, "result": "합격", "note": "외관 양호 (예시)"}))
    lot = one("select * from material_lot where lot_no = %s", (lot_no,))
    assert body["insp_status"] == "합격" and lot["insp_status"] == "합격"
    assert lot["insp_by"] == "qc" and lot["insp_at"] is not None and lot["insp_note"] == "외관 양호 (예시)"
    assert change_logs("F-MAT-03", f"material_lot:{lot_no}") == 1
    ok(client("qc").post(INS, data={"lot_no": lot_no.lower(), "result": "불합격"}))    # 투입 전에는 판정을 바꿀 수 있다
    assert one("select insp_status from material_lot where lot_no = %s", (lot_no,))["insp_status"] == "불합격"


@pytest.mark.fn("F-MAT-03")
def test_inspection_validation_and_no_change_after_input(w):
    c = client("qc")
    assert err(c.post(INS, data={"lot_no": "M000000-000", "result": "합격"}))["message"] == "없는 원재료 LOT 번호입니다"
    lot_no = receive(w)
    assert err(c.post(INS, data={"lot_no": lot_no, "result": "보류"}))["fields"][0]["name"] == "판정"
    assert err(c.post(INS, data={"lot_no": lot_no}))["fields"][0]["name"] == "판정"
    assert err(c.post(INS, data={"result": "합격"}))["fields"][0]["name"] == "LOT 번호"
    inspect(lot_no, "합격")
    work_id = start(w)
    scan_input(work_id, lot_no)
    body = err(c.post(INS, data={"lot_no": lot_no, "result": "불합격"}))               # 이미 투입된 LOT 의 판정 변경
    assert "이미 투입된 LOT" in body["message"]
    assert one("select insp_status from material_lot where lot_no = %s", (lot_no,))["insp_status"] == "합격"


@pytest.mark.fn("F-MAT-03")
@pytest.mark.parametrize("who", ["prod", "field", "admin"])
def test_inspection_result_is_quality_only(w, who):
    """괄호 권한 — 입고검사 결과 등록은 품질만(범위 `입고검사`, D-14). 생산·현장의 일반 입력도, 관리자의 조회도 403."""
    lot_no = receive(w)
    body = err(client(who).post(INS, data={"lot_no": lot_no, "result": "합격"}), 403)
    assert body["function_id"] == "F-MAT-03"
    assert one("select insp_status from material_lot where lot_no = %s", (lot_no,))["insp_status"] == "대기"


@pytest.mark.fn("F-MAT-04")
def test_inspection_list_waiting_first_and_scan_entry(w):
    done, waiting = w.good_lot(), receive(w)
    c = client("qc")
    r = c.get(INS)
    assert r.status_code == 200 and r.text.index(waiting) < r.text.index(done)           # 대기 건이 먼저
    r = c.get(INS, params={"insp_status": "합격"})
    assert done in r.text and waiting not in r.text
    r = c.get(INS, params={"no": waiting})                                                # 라벨 스캔 → 그 LOT 의 판정 칸
    assert r.status_code == 200 and f'name="lot_no" value="{waiting}"' in r.text
    assert err(c.get(INS, params={"no": "M000000-000"}))["message"] == "없는 원재료 LOT 번호입니다"


# ── MAT-03 원재료 LOT ───────────────────────────────────────────────────
@pytest.mark.fn("F-MAT-05")
def test_lot_list_shows_stock_computed_from_inputs(w):
    lot_no = w.good_lot(qty="1000")
    for qty in ("120", "30.5"):
        scan_input(start(w), lot_no, qty=qty)
    stock = one("select received_qty, input_qty, remaining_qty, input_count from v_material_lot_stock where lot_no = %s", (lot_no,))
    assert (float(stock["received_qty"]), float(stock["input_qty"]), float(stock["remaining_qty"]), stock["input_count"]) \
        == (1000.0, 150.5, 849.5, 2)
    assert float(one("select received_qty from material_lot where lot_no = %s", (lot_no,))["received_qty"]) == 1000.0   # D3 는 안 깎는다
    c = client("prod")
    r = c.get(LOTS, params={"no": lot_no})                                                # 스캔 진입 — 그 LOT 이 열린다
    assert r.status_code == 200 and "849.500" in r.text and "150.500" in r.text and 'id="opened"' in r.text
    r = c.get(LOTS, params={"lot": lot_no[-5:], "insp_status": "합격", "item_code": w.raw_code})
    assert r.status_code == 200 and lot_no in r.text
    r = c.get(LOTS, params={"item_code": w.raw_code, "lot": "없는번호"})
    assert "미수집" in r.text


@pytest.mark.fn("F-MAT-05")
def test_unknown_lot_scan_is_422_and_keeps_scan_box(w):
    """없는 LOT 스캔 = 422. 브라우저에서는 같은 화면이 422 로 다시 그려지고 스캔칸이 남는다(다음 스캔을 막지 않는다)."""
    c = client("field")
    assert err(c.get(LOTS, params={"no": "M000000-000"}))["fields"] == [{"name": "LOT 번호", "reason": "M000000-000"}]
    r = c.get(LOTS, params={"no": "M000000-000", "device": "pop"}, headers=HTML)
    assert r.status_code == 422
    assert 'class="err big"' in r.text and "없는 원재료 LOT 번호입니다" in r.text
    assert "data-scan autofocus" in r.text and 'class="ch-pop"' in r.text


@pytest.mark.fn("F-MAT-06")
def test_material_lot_label_has_scannable_barcode(w):
    lot_no = w.good_lot()
    r = client("field").get(f"{LOTS}/{lot_no}/label")
    assert r.status_code == 200
    assert 'data-label-kind="원재료 LOT 라벨"' in r.text and f'data-label-number="{lot_no}"' in r.text
    assert decode_barcode(r.text) == lot_no                                               # 바코드 → 디코드 → 원래 번호
    assert "합격" in r.text and w.raw_code in r.text and "window.print()" in r.text
    assert "cdn" not in r.text.lower() and "<img" not in r.text                           # 외부 CDN·이미지 0
    # 그 바코드 값을 스캔칸에 넣으면 그 LOT 이 열린다 (G-14)
    opened = client("field").get(LOTS, params={"no": decode_barcode(r.text)})
    assert opened.status_code == 200 and 'id="opened"' in opened.text and lot_no in opened.text
    err(client("field").get(f"{LOTS}/M000000-000/label"), 404)                            # 경로의 키가 없으면 404


# ── MAT-04 자재 투입 ────────────────────────────────────────────────────
@pytest.mark.fn("F-MAT-07")
def test_input_scan_one_scan_one_row(w):
    lot_no, work_id = w.good_lot(), start(w)
    genealogy_before = len(w.genealogy())
    body = ok(client("field").post(INP, data={"work_id": str(work_id), "lot_no": lot_no, "input_qty": "12.5"}))
    row = one("select * from material_input where material_input_id = %s", (body["input_id"],))
    assert row["work_result_id"] == work_id and float(row["input_qty"]) == 12.5 and row["scanned_by"] == "field"
    assert row["qty_unit"] == "m"
    assert count("select count(*) as n from material_input where work_result_id = %s", (work_id,)) == 1
    assert len(w.genealogy()) == genealogy_before                 # 계보 행은 작업 종료 때 생긴다 (D-13)
    assert change_logs("F-MAT-07", f"material_input:{body['input_id']}") == 1
    ok(client("prod").post(INP, data={"work_id": str(work_id), "lot_no": w.good_lot()}))    # 투입량 없이 스캔만 해도 한 건
    assert count("select count(*) as n from material_input where work_result_id = %s", (work_id,)) == 2


@pytest.mark.fn("F-MAT-07")
def test_input_scan_rejects_bad_lots_and_does_not_block_next_scan(w):
    """불합격·검사 대기·없는 LOT·중복 스캔은 422 — 그리고 그 뒤의 정상 스캔은 그대로 들어간다."""
    c = client("field")
    work_id = start(w)
    good, waiting, rejected = w.good_lot(), receive(w), receive(w)
    inspect(rejected, "불합격")

    def scan(lot_no):
        return c.post(INP, data={"work_id": str(work_id), "lot_no": lot_no})

    assert "불합격" in err(scan(rejected))["message"]                                       # 불합격 LOT 투입 스캔 = 422
    assert "대기" in err(scan(waiting))["message"]
    assert err(scan("M000000-000"))["message"] == "없는 원재료 LOT 번호입니다"
    assert err(scan(""))["fields"][0]["name"] == "LOT 번호"
    ok(scan(good))                                                                          # 오류 뒤에도 다음 스캔은 된다
    assert "이미 스캔한 LOT" in err(scan(good))["message"]                                  # 같은 실적에 중복
    assert count("select count(*) as n from material_input where work_result_id = %s", (work_id,)) == 1
    assert err(c.post(INP, data={"work_id": "999999999", "lot_no": good}))["message"] == "없는 작업 실적입니다"
    assert err(c.post(INP, data={"lot_no": good}))["fields"][0]["name"] == "작업 실적"
    assert err(c.post(INP, data={"work_id": str(work_id), "lot_no": w.good_lot(), "input_qty": "0"}))["fields"][0]["name"] == "투입량"
    finish(work_id)                                                                         # 끝난 작업에는 투입 불가
    assert "진행 중인 작업에만" in err(scan(w.good_lot()))["message"]
    assert count("select count(*) as n from material_input where work_result_id = %s", (work_id,)) == 1


@pytest.mark.fn("F-MAT-07")
def test_pop_scan_error_returns_to_scan_box(w):
    """POP(브라우저) — 422 는 스캔하던 화면으로 303, 그 화면이 큰 글씨로 사유를 보이고 스캔칸이 다시 포커스를 잡는다."""
    c = client("field")
    work_id, waiting = start(w), receive(w)
    page = f"{INP}?work_id={work_id}&device=pop"
    r = c.post(INP, data={"work_id": str(work_id), "lot_no": waiting}, headers={**HTML, "referer": page}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == page
    back = c.get(page, headers=HTML)
    assert back.status_code == 200 and 'class="ch-pop"' in back.text
    assert 'class="err big"' in back.text and "투입할 수 없습니다" in back.text              # 큰 글씨
    assert 'name="lot_no" data-scan autofocus' in back.text                                 # 스캔칸이 포커스를 잡는다
    assert 'class="err big"' not in c.get(page, headers=HTML).text                          # 알림은 한 번만
    ok_r = c.post(INP, data={"work_id": str(work_id), "lot_no": w.good_lot()}, headers={**HTML, "referer": page},
                  follow_redirects=False)
    assert ok_r.status_code == 303 and "투입했습니다" in c.get(page, headers=HTML).text


@pytest.mark.fn("F-MAT-08")
def test_input_list_by_work(w):
    lot_a, lot_b, work_id, other = w.good_lot(), w.good_lot(), start(w), start(w)
    scan_input(work_id, lot_a, qty="7")
    scan_input(other, lot_b)
    c = client("qc")                                                                        # 품질 = 조회 가능
    r = c.get(INP, params={"work_id": work_id})
    assert r.status_code == 200 and lot_a in r.text and lot_b not in r.text and "7.000" in r.text
    assert "data-scan" in r.text                                                            # 스캔칸이 포커스를 잡는다
    r = c.get(INP)
    assert lot_a in r.text and lot_b in r.text
    assert err(c.get(INP, params={"work_id": "999999999"}))["message"] == "없는 작업 실적입니다"
    empty = start(w)
    assert "미수집" in c.get(INP, params={"work_id": empty}).text


# ── 권한 (설계도 §6 · G-17) ─────────────────────────────────────────────
@pytest.mark.parametrize("who, path, data", [
    ("admin", REC, {"item_code": "x", "received_qty": "1"}),        # 관리자 × 자재·입고 = 조회 → 쓰기 403
    ("qc", REC, {"item_code": "x", "received_qty": "1"}),           # 품질 = 입고검사만 → 입고 등록 403
    ("admin", INP, {"work_id": "1", "lot_no": "x"}),
    ("qc", INP, {"work_id": "1", "lot_no": "x"}),                   # 품질 = 입고검사만 → 투입 스캔 403
])
def test_read_only_roles_cannot_write(who, path, data):
    """권한이 먼저다(401 → 403 → 422) — 입력값이 틀려도 403 이 먼저 나온다."""
    err(client(who).post(path, data=data), 403)


def test_anonymous_is_401():
    for path in (REC, INS, INP):
        err(client().post(path, data={}), 401)
    err(client().get(LOTS), 401)


@pytest.mark.parametrize("who", ["admin", "prod", "qc", "field"])
def test_all_four_roles_can_open_the_screens(who):
    for path in (REC, INS, LOTS, INP):
        assert client(who).get(path).status_code == 200
