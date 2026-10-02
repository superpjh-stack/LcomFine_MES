"""출하 (F-SHP-01~07 · P8 · D8 + 계보의 `출하` 행) — 등록 → 롤 스캔 → 관리자 승인 → COA, 승인 전에만 취소.

채번(`numbering`)·계보(`lineage`)·바코드(`printing`)는 개발1·2 의 모듈을 **API 를 통해** 부른다.
필요한 품목·Job·롤·검사는 SQL 로 직접 만든다(접두 `T3S-`). 끝나면 그 접두의 Job 에 딸린 행이 하나도 남지 않는다.
"""
from decimal import Decimal

import pytest

from lcomfine.app import nav
from lcomfine.db import conn

from test_dev3_support import World, cleanup, client, count, leftovers, one

P = "T3S-"
SHIPMENTS = nav.path_of("SHP-01")
APPROVALS = nav.path_of("SHP-02")
COA = nav.path_of("SHP-03")


@pytest.fixture()
def w():
    world = World(P)
    world.item_a, world.cust, world.cust2 = world.item("P1"), world.customer("C1"), world.customer("C2")
    world.job1 = world.job("JOB1", world.item_a, world.cust)
    world.job2 = world.job("JOB2", world.item_a, world.cust)
    world.r1, world.r2, world.r3 = (world.roll(f"R{i}", world.job1) for i in (1, 2, 3))
    world.d1 = world.defect_code("D1")
    world.inspection(world.r1, world.job1, "합격", Decimal("0.8"))
    world.inspection(world.r2, world.job1, "불합격", Decimal("5.0"))        # 옛 판정
    world.inspection(world.r2, world.job1, "합격", Decimal("1.2"), defects=((world.d1, "끝단 (예시)"),))   # 최신 = 합격
    yield world
    cleanup(P)
    assert leftovers(P) == {}
    assert count("select count(*) as n from shipment s join job j on j.job_id = s.job_id where j.job_no like %s", (P + "%",)) == 0


def _register(job_no: str = P + "JOB1", login_id: str = "prod", **extra) -> str:
    r = client(login_id).post(SHIPMENTS, data={"job_no": job_no, "ship_date": "2001-03-10", **extra})
    assert r.status_code == 200, r.text
    return r.json()["shipment_no"]


def _scan(shipment_no: str, roll_no: str, login_id: str = "field"):
    return client(login_id).post(f"{SHIPMENTS}/{shipment_no}/rolls", data={"roll_no": roll_no})


def _state(roll_no: str) -> str:
    return one("select state from v_roll_state where roll_no = %s", (roll_no,))["state"]


def _edges(shipment_no: str) -> list[dict]:
    return conn.q("""select r.roll_no, g.relation, g.created_by from roll_genealogy g
                       join shipment s on s.shipment_id = g.child_shipment_id join roll r on r.roll_id = g.parent_roll_id
                      where s.shipment_no = %s order by g.genealogy_id""", (shipment_no,))


@pytest.mark.fn("F-SHP-01")
def test_register_shipment_numbers_it_and_defaults_customer(w):
    r = client("prod").post(SHIPMENTS, data={"job_no": P + "JOB1", "ship_date": "2001-03-10", "note": "(예시)"})
    assert r.status_code == 200 and r.json()["ok"] is True
    no = r.json()["shipment_no"]
    row = one("select * from shipment where shipment_no = %s", (no,))
    assert (row["job_id"], row["customer_id"], str(row["ship_date"]), row["status"], row["registered_by"]) == \
        (w.job1, w.cust, "2001-03-10", "등록", "prod")                       # 고객을 안 주면 그 Job 의 고객
    assert row["coa_no"] is None and row["approved_at"] is None
    other = _register(login_id="field", customer_code=P + "C2")
    assert other != no                                                       # 번호는 채번(numbering)에서 — 겹치지 않는다
    assert one("select customer_id from shipment where shipment_no = %s", (other,))["customer_id"] == w.cust2
    log = one("select login_id, log_type, function_id from sys_access_log where target = %s", (f"shipment:{no}",))
    assert log == {"login_id": "prod", "log_type": "변경", "function_id": "F-SHP-01"}

    conn.x("update job set status = '취소' where job_id = %s", (w.job2,))
    before = count("select count(*) as n from shipment where job_id in (%s, %s)", (w.job1, w.job2))
    for data, text in [({"ship_date": "2001-03-10"}, "필수값"), ({"job_no": P + "JOB1"}, "필수값"),
                       ({"job_no": P + "NOPE", "ship_date": "2001-03-10"}, "없는 Job"),
                       ({"job_no": P + "JOB1", "ship_date": "3월 10일"}, "날짜"),
                       ({"job_no": P + "JOB2", "ship_date": "2001-03-10"}, "취소된 Job"),
                       ({"job_no": P + "JOB1", "ship_date": "2001-03-10", "customer_code": P + "NOPE"}, "없는 고객")]:
        r = client("prod").post(SHIPMENTS, data=data)
        assert r.status_code == 422 and text in r.json()["message"], data
    assert count("select count(*) as n from shipment where job_id in (%s, %s)", (w.job1, w.job2)) == before


@pytest.mark.fn("F-SHP-02")
def test_scan_roll_writes_one_genealogy_row_through_lineage(w):
    no = _register()
    r = _scan(no, P + "R1")
    assert r.status_code == 200 and r.json()["roll_no"] == P + "R1" and r.json()["roll_count"] == 1
    assert _edges(no) == [{"roll_no": P + "R1", "relation": "출하", "created_by": "field"}]   # 바코드 한 번 = 계보 한 줄
    assert _state(P + "R1") == "출하"
    assert _scan(no, P + "R3").status_code == 200                           # 미검사 롤은 담긴다 (D-17)
    assert [e["roll_no"] for e in _edges(no)] == [P + "R1", P + "R3"]
    assert one("select function_id from sys_access_log where target = %s", (f"shipment:{no} roll:{P}R1",))["function_id"] == "F-SHP-02"


@pytest.mark.fn("F-SHP-02")
def test_scan_rejections_are_422_and_do_not_block_next_scan(w):
    """없는 롤 · 이미 출하된 롤 · 소진된 롤 · 다른 Job 의 롤 · 불합격 롤 · 롤이 아닌 번호 → 422. 그 뒤의 정상 스캔은 된다."""
    no, other = _register(), _register()
    assert _scan(no, P + "R1").status_code == 200
    parent = w.roll("PARENT", w.job1, "후가공")                             # R3 의 부모 → 소진
    w.edge("슬리팅", parent=parent, child=w.r3)
    foreign = w.roll("FOREIGN", w.job2)                                     # 다른 Job 의 롤
    failed = w.roll("FAILED", w.job1)
    w.inspection(failed, w.job1, "합격")
    w.inspection(failed, w.job1, "불합격")                                  # 최신 검사가 불합격
    w.material_lot("LOT1", w.item("RAW", "원재료"))

    cases = [(no, P + "NOPE", "없는 롤"), (no, "", "롤 번호"),
             (no, P + "R1", "이미 출하된 롤"),                               # 같은 출하에 다시
             (other, P + "R1", "이미 출하된 롤"),                            # 다른 출하에 재출하
             (no, P + "PARENT", "소진"), (no, P + "FOREIGN", "Job"), (no, P + "FAILED", "불합격"),
             (no, P + "LOT1", "롤 번호가 아닙니다")]
    for shipment_no, roll_no, text in cases:
        r = _scan(shipment_no, roll_no)
        assert r.status_code == 422 and r.json()["code"] == "validation_error", (roll_no, r.status_code, r.text)
        assert text in r.json()["message"], (roll_no, r.json())
    assert [e["roll_no"] for e in _edges(no)] == [P + "R1"] and _edges(other) == []
    assert _scan(no, P + "R2").status_code == 200                           # 오류 뒤에도 다음 스캔은 된다 (옛 불합격 + 최신 합격 = 합격)
    assert [e["roll_no"] for e in _edges(no)] == [P + "R1", P + "R2"]

    r = _scan(P + "NOSHIP", P + "R3")                                       # 경로의 출하 LOT 이 없다 → 404
    assert r.status_code == 404 and r.json()["code"] == "not_found"
    assert client("admin").post(f"{APPROVALS}/{no}/approve").status_code == 200
    r = _scan(no, P + "FOREIGN")
    assert r.status_code == 422 and "승인된 출하" in r.json()["message"]     # 승인된 출하에는 못 담는다


@pytest.mark.fn("F-SHP-03")
def test_cancel_before_approval_returns_rolls_to_stock(w):
    no = _register()
    assert _scan(no, P + "R1").status_code == 200 and _scan(no, P + "R2").status_code == 200
    r = client("field").post(f"{SHIPMENTS}/{no}/cancel")
    assert r.status_code == 200 and r.json()["removed_rolls"] == 2
    assert one("select status, updated_by from shipment where shipment_no = %s", (no,)) == {"status": "취소", "updated_by": "field"}
    assert _edges(no) == [] and _state(P + "R1") == "재고" and _state(P + "R2") == "재고"    # 계보 행이 지워졌다
    r = client("field").post(f"{SHIPMENTS}/{no}/cancel")
    assert r.status_code == 422 and "이미 취소" in r.json()["message"]
    assert _scan(no, P + "R1").status_code == 422                           # 취소된 출하에는 못 담는다

    again = _register()                                                     # 재고로 돌아온 롤은 다른 출하에 담긴다
    assert _scan(again, P + "R1").status_code == 200
    assert client("admin").post(f"{APPROVALS}/{again}/approve").status_code == 200
    r = client("prod").post(f"{SHIPMENTS}/{again}/cancel")
    assert r.status_code == 422 and "승인된 출하는 취소할 수 없습니다" in r.json()["message"]
    assert _state(P + "R1") == "출하" and one("select status from shipment where shipment_no = %s", (again,))["status"] == "승인"
    assert client("prod").post(f"{SHIPMENTS}/{P}NOSHIP/cancel").status_code == 404


@pytest.mark.fn("F-SHP-04")
def test_list_search_and_open_one_shipment(w):
    no = _register()
    _scan(no, P + "R2"), _scan(no, P + "R3")
    cancelled = _register()
    client("prod").post(f"{SHIPMENTS}/{cancelled}/cancel")
    c = client("qc")                                                        # 품질 = 조회

    def listing(**params) -> str:
        r = c.get(SHIPMENTS, params=params)
        assert r.status_code == 200, r.text[:300]
        return r.text[r.text.index("<h2>출하 목록"):r.text.index("</main>")]

    text = listing(job_no=P + "JOB1")
    assert "2건" in text and f"<code>{no}</code>" in text and f"<code>{cancelled}</code>" in text and "미발행" in text
    assert "1건" in listing(job_no=P + "JOB1", status="등록") and "1건" in listing(job_no=P + "JOB1", status="취소")
    assert "2건" in listing(customer=P + "C1", date_from="2001-03-10", date_to="2001-03-10")
    assert "1건" in listing(shipment_no=no)
    empty = listing(job_no=P + "JOB1", date_from="2001-03-11")
    assert "0건" in empty and "미수집" in empty

    r = c.get(SHIPMENTS, params={"no": no})                                 # 한 건 열기 — 담긴 롤과 그 검사 판정
    opened = r.text[r.text.index('id="opened"'):r.text.index('id="form"')]
    assert "롤 2개 (합격 1 · 불합격 0 · 미검사 1)" in opened
    row_r2 = opened[opened.index(f"<code>{P}R2</code>"):opened.index(f"<code>{P}R3</code>")]
    assert "합격" in row_r2 and "1.20" in row_r2 and "끝단 (예시)" in row_r2 and "5.00" not in row_r2   # 최신 검사
    assert "검사 결과 미수집" in opened[opened.index(f"<code>{P}R3</code>"):]
    assert 'name="roll_no"' not in r.text                                   # 조회 역할에게는 롤 스캔칸이 없다
    scan_page = client("field").get(SHIPMENTS, params={"no": no}).text
    assert f'action="{SHIPMENTS}/{no}/rolls"' in scan_page and 'name="roll_no" data-scan autofocus' in scan_page   # 스캔칸이 포커스를 잡는다

    r = c.get(SHIPMENTS, params={"no": P + "NOSHIP"})
    assert r.status_code == 422 and "없는 출하 LOT" in r.json()["message"]
    assert c.get(SHIPMENTS, params={"status": "보류"}).status_code == 422


@pytest.mark.fn("F-SHP-05")
def test_only_admin_approves_and_coa_number_is_issued(w):
    """출하 승인은 관리자만 (괄호 권한 `입력 (승인)`, D-14). 승인이 곧 COA 발행이다 (D-17)."""
    no = _register()
    path = f"{APPROVALS}/{no}/approve"
    r = client("admin").post(path)
    assert r.status_code == 422 and "롤이 담기지 않은" in r.json()["message"]   # 롤 0개
    assert _scan(no, P + "R1").status_code == 200
    for login_id in ("prod", "field", "qc"):                                # 일반 입력·조회 역할은 승인할 수 없다
        r = client(login_id).post(path)
        assert r.status_code == 403 and r.json()["code"] == "forbidden", login_id
    assert client().post(path).status_code == 401
    assert one("select status from shipment where shipment_no = %s", (no,))["status"] == "등록"

    r = client("admin").post(path)
    assert r.status_code == 200 and r.json()["roll_count"] == 1
    row = one("select * from shipment where shipment_no = %s", (no,))
    assert (row["status"], row["approved_by"], row["coa_no"]) == ("승인", "admin", r.json()["coa_no"])
    assert row["approved_at"] is not None and row["coa_issued_at"] is not None and row["coa_no"]
    assert one("select function_id, login_id from sys_access_log where target = %s and function_id = 'F-SHP-05'",
               (f"shipment:{no}",))["login_id"] == "admin"
    r = client("admin").post(path)
    assert r.status_code == 422 and "이미 승인" in r.json()["message"]
    assert one("select coa_no from shipment where shipment_no = %s", (no,))["coa_no"] == row["coa_no"]   # 번호가 다시 나가지 않는다
    assert client("admin").post(f"{APPROVALS}/{P}NOSHIP/approve").status_code == 404

    late = _register()                                                      # 스캔한 뒤에 불합격 판정이 들어온 롤 (D-305)
    assert _scan(late, P + "R2").status_code == 200
    w.inspection(w.r2, w.job1, "불합격")
    r = client("admin").post(f"{APPROVALS}/{late}/approve")
    assert r.status_code == 422 and "불합격" in r.json()["message"] and r.json()["fields"][0]["name"] == P + "R2"
    assert one("select status, coa_no from shipment where shipment_no = %s", (late,)) == {"status": "등록", "coa_no": None}

    page = client("admin").get(APPROVALS)                                   # 승인 화면 — 대기와 최근 승인
    assert page.status_code == 200 and f"{APPROVALS}/{late}/approve" in page.text and row["coa_no"] in page.text
    assert client("qc").get(APPROVALS).status_code == 200                   # 화면은 조회 이상이면 열린다


@pytest.mark.fn("F-SHP-01", "F-SHP-02", "F-SHP-03")
def test_read_roles_cannot_write_shipments(w):
    """권한 표: 출하 = 관리자 `입력 (승인)` · 생산·현장 `입력` · 품질 `조회`. 관리자는 승인만, 품질은 아무 쓰기도 못 한다."""
    no = _register()
    for login_id in ("qc", "admin"):
        c = client(login_id)
        assert c.get(SHIPMENTS).status_code == 200
        for path, data in [(SHIPMENTS, {"job_no": P + "JOB1", "ship_date": "2001-03-10"}),
                           (f"{SHIPMENTS}/{no}/rolls", {"roll_no": P + "R1"}), (f"{SHIPMENTS}/{no}/cancel", {})]:
            r = c.post(path, data=data)
            assert r.status_code == 403 and r.json()["code"] == "forbidden", (login_id, path)
    assert client().post(SHIPMENTS, data={"job_no": P + "JOB1", "ship_date": "2001-03-10"}).status_code == 401
    assert _edges(no) == [] and one("select status from shipment where shipment_no = %s", (no,))["status"] == "등록"


@pytest.mark.fn("F-SHP-06")
def test_coa_list_shows_issued_and_not_issued(w):
    issued, waiting, cancelled = _register(), _register(), _register()
    _scan(issued, P + "R1")
    coa_no = client("admin").post(f"{APPROVALS}/{issued}/approve").json()["coa_no"]
    client("prod").post(f"{SHIPMENTS}/{cancelled}/cancel")
    r = client("qc").get(COA, params={"job_no": P + "JOB1"})
    assert r.status_code == 200
    text = r.text[r.text.index("<h2>COA <small>"):r.text.index("</main>")]
    assert "2건" in text and cancelled not in text                           # 취소된 출하는 COA 대상이 아니다
    row_issued = text[text.index(f"<code>{coa_no}</code>"):]
    assert f"{COA}/{issued}/print" in row_issued
    row_waiting = text[:text.index(f"<code>{coa_no}</code>")]
    assert f"<code>{waiting}</code>" in row_waiting and "미발행" in row_waiting and f"{COA}/{waiting}/print" not in text
    r = client("qc").get(COA, params={"job_no": P + "없는Job"})
    assert "0건" in r.text and "미수집" in r.text[r.text.index("<h2>COA <small>"):]


@pytest.mark.fn("F-SHP-07")
def test_coa_print_is_built_from_latest_inspections(w):
    no = _register()
    for roll in ("R1", "R2", "R3"):
        assert _scan(no, P + roll).status_code == 200
    r = client("qc").get(f"{COA}/{no}/print")
    assert r.status_code == 422 and "승인되지 않은 출하" in r.json()["message"]   # 미승인 출하는 422
    coa_no = client("admin").post(f"{APPROVALS}/{no}/approve").json()["coa_no"]

    r = client("qc").get(f"{COA}/{no}/print")
    assert r.status_code == 200
    doc = r.text[r.text.index('<section class="panel coa">'):r.text.index("</main>")]
    assert f"<code>{coa_no}</code>" in doc and f"<code>{no}</code>" in doc and f"<code>{P}JOB1</code>" in doc
    assert "<svg" in doc and "window.print()" in doc                        # 바코드(printing) + 인쇄 버튼
    r1 = doc[doc.index(f"<code>{P}R1</code>"):doc.index(f"<code>{P}R2</code>")]
    r2 = doc[doc.index(f"<code>{P}R2</code>"):doc.index(f"<code>{P}R3</code>")]
    r3 = doc[doc.index(f"<code>{P}R3</code>"):doc.index("coa-foot")]
    assert "0.80" in r1 and "합격" in r1 and "없음" in r1
    assert "1.20" in r2 and "합격" in r2 and "끝단 (예시)" in r2 and "5.00" not in r2   # 옛 불합격이 아니라 최신 검사
    assert r3.count("미수집") >= 4                                           # 검사가 없는 롤 — ΔE · 판정 · 불량 · 일시
    assert "롤 3개 — 합격 2 · 불합격 0 · 검사 결과 미수집 1" in doc
    from lcomfine.app import printing
    assert str(printing.barcode_svg(no)) in doc                              # 바코드 값 = 출하 LOT 번호 글자 그대로

    r = client("admin").get(f"{COA}/{P}NOSHIP/print")
    assert r.status_code == 404
    assert client("field").get(f"{COA}/{no}/print").status_code == 200       # 현장도 조회·출력은 된다
    assert client().get(f"{COA}/{no}/print").status_code == 401


@pytest.mark.fn("F-SHP-02")
def test_pop_scan_error_returns_to_scan_box(w):
    """브라우저(POP)의 스캔 오류는 오류 화면이 아니라 **스캔하던 화면으로 303** + 알림이다 — 다음 스캔을 막지 않는다 (G-13)."""
    no = _register()
    c = client("field")
    page = f"{SHIPMENTS}?no={no}&device=pop"
    browser = {"accept": "text/html", "referer": f"http://testserver{page}"}
    r = c.post(f"{SHIPMENTS}/{no}/rolls", data={"roll_no": P + "NOPE"}, headers=browser, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith(page)
    html = c.get(page, headers={"accept": "text/html"}).text
    assert 'class="ch-pop"' in html and _flash(html)["message"] == "없는 롤입니다"                # 알림 한 번 (POP 은 큰 글씨)
    assert _flash(html)["fields"] == [{"name": "롤 번호", "reason": P + "NOPE"}]
    assert 'name="roll_no" data-scan autofocus' in html                                          # 스캔칸이 다시 포커스를 잡는다
    r = c.post(f"{SHIPMENTS}/{no}/rolls", data={"roll_no": P + "R1"}, headers=browser, follow_redirects=False)
    assert r.status_code == 303 and _edges(no)[0]["roll_no"] == P + "R1"                         # 다음 스캔은 그대로 된다
    html = c.get(page, headers={"accept": "text/html"}).text
    assert "담았습니다" in _flash(html)["message"] and f"<code>{P}R1</code>" in html
    assert _flash(c.get(page, headers={"accept": "text/html"}).text) is None                    # 알림은 한 번만 뜬다


def _flash(html: str) -> dict | None:
    import html as html_lib
    import json
    import re
    m = re.search(r'<script type="application/json" id="flash-data">(.*?)</script>', html, re.S)
    return json.loads(html_lib.unescape(m.group(1))) if m else None
