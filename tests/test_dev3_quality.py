"""품질 검사 기록 (F-QUA-01~06 · P7 · D7) — 롤 참조로 검사 결과 등록·수정·삭제·조회, 불량 유형별 집계와 불량 롤.

필요한 품목·Job·롤·불량코드는 SQL 로 직접 만든다(접두 `T3Q-`). 끝나면 그 접두의 행이 하나도 남지 않는다.
"""
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal

import pytest

from lcomfine.app import nav, stats
from lcomfine.db import conn

from test_dev3_support import World, cleanup, client, count, leftovers, one

P = "T3Q-"
INSPECTIONS = nav.path_of("QUA-01")
DEFECT_STATS = nav.path_of("QUA-02")
KST = timezone(timedelta(hours=9))


@pytest.fixture()
def w():
    world = World(P)
    world.item_a, world.cust = world.item("P1"), world.customer()
    world.job1 = world.job("JOB1", world.item_a, world.cust)
    world.r1, world.r2 = world.roll("R1", world.job1), world.roll("R2", world.job1)
    world.d1, world.d2 = world.defect_code("D1"), world.defect_code("D2")
    yield world
    cleanup(P)
    assert leftovers(P) == {}


def _rows(roll_no: str) -> list[dict]:
    return conn.q("""select n.* from inspection n join roll r on r.roll_id = n.roll_id
                      where r.roll_no = %s order by n.inspection_id""", (roll_no,))


def _defects(inspection_id: int) -> list[tuple]:
    return [(r["defect_code"], r["position"]) for r in conn.q(
        """select d.defect_code, x.position from inspection_defect x join defect_code d on d.defect_code_id = x.defect_code_id
            where x.inspection_id = %s order by x.inspection_defect_id""", (inspection_id,))]


@pytest.mark.fn("F-QUA-01")
def test_create_inspection_copies_job_key_and_defect_rows(w):
    qc = client("qc")
    r = qc.post(INSPECTIONS, data={"roll_no": P + "R1", "delta_e": "1.25", "result": "불합격", "note": "(예시)",
                                   "defect_code": [P + "D1", "", P + "D2"], "position": ["좌측 10m (예시)", "", ""]})
    assert r.status_code == 200 and r.json()["ok"] is True and r.json()["result"] == "불합격"
    row = one("select * from inspection where inspection_id = %s", (r.json()["inspection_id"],))
    assert (row["roll_id"], row["job_id"], row["delta_e"], row["result"], row["inspected_by"]) == \
        (w.r1, w.job1, Decimal("1.25"), "불합격", "qc")                    # Job 키는 롤에서 복사 (D-16)
    assert _defects(row["inspection_id"]) == [(P + "D1", "좌측 10m (예시)"), (P + "D2", None)]
    log = one("""select login_id, function_id, target, log_type from sys_access_log
                  where function_id = 'F-QUA-01' and target like %s order by log_id desc limit 1""", (f"%{P}R1%",))
    assert (log["login_id"], log["log_type"]) == ("qc", "변경")            # 쓰기 성공 직후 변경 로그 (G-18)

    r = qc.post(INSPECTIONS, data={"roll_no": P + "R2", "result": "합격"})  # ΔE · 불량 없이도 된다
    assert r.status_code == 200 and _rows(P + "R2")[0]["delta_e"] is None

    bad = [
        ({"roll_no": P + "NOPE", "result": "합격"}, "없는 롤"),
        ({"roll_no": "", "result": "합격"}, "롤 번호"),
        ({"roll_no": P + "R1", "result": "보류"}, "판정"),
        ({"roll_no": P + "R1", "result": ""}, "판정"),
        ({"roll_no": P + "R1", "result": "합격", "delta_e": "-1"}, "ΔE"),
        ({"roll_no": P + "R1", "result": "합격", "delta_e": "많이"}, "ΔE"),
        ({"roll_no": P + "R1", "result": "불합격", "defect_code": [P + "D9"]}, "불량 행"),
        ({"roll_no": P + "R1", "result": "불합격", "defect_code": [""], "position": ["우측"]}, "불량 행"),
    ]
    before = count("select count(*) as n from inspection where job_id = %s", (w.job1,))
    for data, text in bad:
        r = qc.post(INSPECTIONS, data=data)
        assert r.status_code == 422 and r.json()["code"] == "validation_error" and text in r.json()["message"], data
    assert count("select count(*) as n from inspection where job_id = %s", (w.job1,)) == before   # 422 는 아무것도 남기지 않는다


@pytest.mark.fn("F-QUA-01", "F-QUA-02", "F-QUA-03")
def test_only_quality_role_can_write(w):
    """권한 표: 품질 검사 기록 = 관리자·생산·현장 `조회`, 품질 `입력`. 조회 역할의 쓰기는 403, 미로그인은 401."""
    iid = w.inspection(w.r1, w.job1)
    for login_id in ("admin", "prod", "field"):
        c = client(login_id)
        assert c.get(INSPECTIONS).status_code == 200                       # 조회는 된다
        for path, data in [(INSPECTIONS, {"roll_no": P + "R1", "result": "합격"}),
                           (f"{INSPECTIONS}/{iid}", {"result": "불합격"}), (f"{INSPECTIONS}/{iid}/delete", {})]:
            r = c.post(path, data=data)
            assert r.status_code == 403 and r.json()["code"] == "forbidden", (login_id, path)
    assert client().post(INSPECTIONS, data={"roll_no": P + "R1", "result": "합격"}).status_code == 401
    assert [r["result"] for r in _rows(P + "R1")] == ["합격"]              # 아무것도 바뀌지 않았다
    # 권한이 없으면 입력값 오류보다 403 이 먼저다
    assert client("prod").post(INSPECTIONS, data={"roll_no": "", "result": ""}).status_code == 403


@pytest.mark.fn("F-QUA-02")
def test_update_inspection_replaces_values_and_defects(w):
    iid = w.inspection(w.r1, w.job1, "합격", Decimal("0.80"), defects=((w.d1, "앞 (예시)"),))
    qc = client("qc")
    r = qc.post(f"{INSPECTIONS}/{iid}", data={"delta_e": "2.5", "result": "불합격", "note": "수정 (예시)",
                                              "defect_code": [P + "D2", P + "D2"], "position": ["가", "나"],
                                              "roll_no": P + "R2"})          # 롤은 바꿀 수 없다 — 무시된다
    assert r.status_code == 200
    row = one("select * from inspection where inspection_id = %s", (iid,))
    assert (row["roll_id"], row["delta_e"], row["result"], row["note"], row["updated_by"]) == \
        (w.r1, Decimal("2.50"), "불합격", "수정 (예시)", "qc")
    assert _defects(iid) == [(P + "D2", "가"), (P + "D2", "나")]            # 불량 행은 통째로 바뀐다
    assert qc.post(f"{INSPECTIONS}/{iid}", data={"result": "합격"}).status_code == 200
    assert _defects(iid) == [] and one("select delta_e from inspection where inspection_id = %s", (iid,))["delta_e"] is None

    assert qc.post(f"{INSPECTIONS}/{iid}", data={"result": "애매"}).status_code == 422
    r = qc.post(f"{INSPECTIONS}/999999999", data={"result": "합격"})        # 경로의 키가 없다 → 404
    assert r.status_code == 404 and r.json()["code"] == "not_found"


@pytest.mark.fn("F-QUA-03")
def test_delete_inspection_removes_defect_rows(w):
    iid = w.inspection(w.r1, w.job1, "불합격", defects=((w.d1, None), (w.d2, None)))
    keep = w.inspection(w.r1, w.job1, "합격")
    qc = client("qc")
    r = qc.post(f"{INSPECTIONS}/{iid}/delete")
    assert r.status_code == 200
    assert count("select count(*) as n from inspection where inspection_id = %s", (iid,)) == 0
    assert count("select count(*) as n from inspection_defect where inspection_id = %s", (iid,)) == 0
    assert [r["inspection_id"] for r in _rows(P + "R1")] == [keep]
    assert qc.post(f"{INSPECTIONS}/{iid}/delete").status_code == 404        # 이미 없다
    assert one("select function_id from sys_access_log where target like %s order by log_id desc limit 1",
               (f"inspection:{iid} %",))["function_id"] == "F-QUA-03"


@pytest.mark.fn("F-QUA-01", "F-QUA-02", "F-QUA-03")
def test_inspection_of_approved_shipment_roll_is_locked(w):
    """출하 승인된 롤의 검사는 등록·수정·삭제 422 — COA 는 검사 결과에서 매번 만들므로 발행 뒤에 바뀌면 안 된다 (D-304)."""
    iid = w.inspection(w.r1, w.job1, "합격", Decimal("1.0"))
    ship = w.shipment("SHIP1", w.job1, w.cust)
    w.edge("출하", parent=w.r1, ship=ship)
    qc = client("qc")
    assert qc.post(f"{INSPECTIONS}/{iid}", data={"result": "합격", "delta_e": "1.1"}).status_code == 200   # 승인 전에는 고친다
    w.approve_sql(ship)
    for path, data in [(INSPECTIONS, {"roll_no": P + "R1", "result": "불합격"}),
                       (f"{INSPECTIONS}/{iid}", {"result": "불합격"}), (f"{INSPECTIONS}/{iid}/delete", {})]:
        r = qc.post(path, data=data)
        assert r.status_code == 422 and "출하 승인된 롤" in r.json()["message"], path
        assert P + "SHIP1" in r.json()["fields"][0]["reason"]
    row = _rows(P + "R1")
    assert len(row) == 1 and (row[0]["result"], row[0]["delta_e"]) == ("합격", Decimal("1.10"))
    assert qc.post(INSPECTIONS, data={"roll_no": P + "R2", "result": "합격"}).status_code == 200            # 다른 롤은 된다


@pytest.mark.fn("F-QUA-04")
def test_list_and_search_inspections(w):
    old = w.inspection(w.r1, w.job1, "불합격", Decimal("4.2"), datetime(2001, 3, 5, 10, 0, tzinfo=KST), defects=((w.d1, "끝 (예시)"),))
    new = w.inspection(w.r1, w.job1, "합격", Decimal("0.9"), datetime(2001, 3, 6, 10, 0, tzinfo=KST))
    w.inspection(w.r2, w.job1, "합격", None, datetime(2001, 3, 7, 10, 0, tzinfo=KST))
    c = client("prod")                                                      # 조회 역할

    def body(**params) -> str:
        r = c.get(INSPECTIONS, params=params)
        assert r.status_code == 200, r.text[:300]
        return r.text[r.text.index("<h2>검사 결과 <small>"):r.text.index("</main>")]

    text = body(job_no=P + "JOB1")
    assert "3건" in text and P + "R1" in text and P + "R2" in text and "4.20" in text and "끝 (예시)" in text
    assert f"불량 {'D1'} (예시) · 끝 (예시)" in text                         # 불량 유형 · 위치
    assert "2건" in body(roll_no=P + "R1") and "1건" in body(job_no=P + "JOB1", result="불합격")
    assert "1건" in body(job_no=P + "JOB1", date_from="2001-03-06", date_to="2001-03-06")
    assert "2건" in body(job_no=P + "JOB1", date_from="2001-03-06")
    empty = body(roll_no=P + "없는롤")
    assert "0건" in empty and "미수집" in empty                             # 빈 표만 두지 않는다 (G-11)

    scan = body(no=P + "R1")                                                # 라벨 바코드로 진입 (`?no=`)
    assert "2건" in scan and P + "R2" not in scan
    rows = scan.split("<tr>")[2:]
    assert "최신" in rows[0] and "합격" in rows[0] and "최신" not in rows[1]  # 최신 검사가 그 롤의 판정이다
    assert f"?edit={new}" in rows[0] and f"?edit={old}" in rows[1]
    assert f'value="{P}R1"' in c.get(INSPECTIONS, params={"no": P + "R1"}).text    # 등록칸에 번호가 채워진다

    r = c.get(INSPECTIONS, params={"no": P + "NOPE"})                       # 없는 롤 스캔 → 422
    assert r.status_code == 422 and "없는 롤" in r.json()["message"]
    assert c.get(INSPECTIONS, params={"date_from": "3월"}).status_code == 422
    edit = client("qc").get(INSPECTIONS, params={"edit": old}).text
    assert "검사 결과 수정" in edit and f'action="{INSPECTIONS}/{old}"' in edit and 'value="4.20"' in edit


def _stats_fixture(w) -> None:
    item_b = w.item("P2")
    job2 = w.job("JOB2", item_b, w.cust)
    r3 = w.roll("R3", job2)
    at = lambda d, h=10: datetime(2001, 3, d, h, 0, tzinfo=KST)   # noqa: E731
    w.inspection(w.r1, w.job1, "불합격", at=at(5), defects=((w.d1, "가 (예시)"), (w.d1, "나 (예시)"), (w.d2, None)))
    w.inspection(w.r1, w.job1, "불합격", at=at(6), defects=((w.d1, None),))
    w.inspection(w.r2, w.job1, "불합격", at=at(6), defects=((w.d1, "다 (예시)"),))
    w.inspection(r3, job2, "불합격", at=at(7), defects=((w.d2, "라 (예시)"),))
    w.inspection(w.r2, w.job1, "불합격", at=datetime(2001, 4, 1, 0, 0, tzinfo=KST), defects=((w.d1, None),))   # 기간 밖
    w.item_b = item_b


@pytest.mark.fn("F-QUA-05")
def test_defect_stats_by_type(w):
    """불량 유형마다 불량 행 수와 서로 다른 롤 수 — 손으로 센 값과 같다."""
    _stats_fixture(w)
    mine = lambda rows: {r["defect_code"]: (r["defect_count"], r["roll_count"]) for r in rows if r["defect_code"].startswith(P)}   # noqa: E731
    d1, d2 = date(2001, 3, 1), date(2001, 3, 31)
    assert mine(stats.defect_by_type(d1, d2)) == {P + "D1": (4, 2), P + "D2": (2, 2)}
    assert mine(stats.defect_by_type(d1, d2, w.item_a)) == {P + "D1": (4, 2), P + "D2": (1, 1)}
    assert mine(stats.defect_by_type(d1, d2, w.item_b)) == {P + "D2": (1, 1)}
    assert mine(stats.defect_by_type(date(2001, 3, 6), date(2001, 3, 6))) == {P + "D1": (2, 2)}        # 양 끝 날짜 포함
    assert mine(stats.defect_by_type(date(2001, 3, 1), date(2001, 4, 1))) == {P + "D1": (5, 2), P + "D2": (2, 2)}

    c = client("admin")
    r = c.get(DEFECT_STATS, params={"date_from": "2001-03-01", "date_to": "2001-03-31", "item_id": w.item_a})
    assert r.status_code == 200
    table = r.text[r.text.index("<h2>불량 유형별 집계"):r.text.index('id="rolls"')]
    assert "불량 유형 2종 · 불량 행 5건" in table
    row_d1 = table[table.index(f"<code>{P}D1</code>"):table.index(f"<code>{P}D2</code>")]
    assert '<td class="num">4</td>' in row_d1 and '<td class="num">2</td>' in row_d1
    assert f"rolls?defect_code={P}D1" in row_d1                              # 내역(불량 롤)으로 넘어가는 링크

    r = c.get(DEFECT_STATS, params={"date_from": "1990-01-01", "date_to": "1990-01-31"})
    assert r.status_code == 200 and "미수집" in r.text[r.text.index("<h2>불량 유형별 집계"):]             # 0건 (G-11)
    assert c.get(DEFECT_STATS, params={"date_from": "2001-03-31", "date_to": "2001-03-01"}).status_code == 422
    assert c.get(DEFECT_STATS, params={"item_id": "999999999"}).status_code == 422
    assert c.get(DEFECT_STATS).status_code == 200                           # 기간을 비우면 이번 달


@pytest.mark.fn("F-QUA-06")
def test_defect_rolls_lists_roll_position_job(w):
    _stats_fixture(w)
    c = client("field")                                                     # 현장도 조회는 된다
    params = {"date_from": "2001-03-01", "date_to": "2001-03-31", "defect_code": P + "D1"}
    r = c.get(f"{DEFECT_STATS}/rolls", params=params)
    assert r.status_code == 200
    detail = r.text[r.text.index('id="rolls"'):r.text.index("</main>")]
    assert "4건" in detail and detail.count(f"<code>{P}R1</code>") == 3 and detail.count(f"<code>{P}R2</code>") == 1
    assert "가 (예시)" in detail and "다 (예시)" in detail and f"<code>{P}JOB1</code>" in detail
    assert P + "R3" not in detail and "라 (예시)" not in detail              # 다른 불량 유형의 롤
    rows = stats.defect_rolls(date(2001, 3, 1), date(2001, 3, 31), P + "D1")
    assert len(rows) == 4 == dict((r["defect_code"], r["defect_count"]) for r in stats.defect_by_type(date(2001, 3, 1), date(2001, 3, 31)))[P + "D1"]
    assert {(r["roll_no"], r["position"], r["job_no"]) for r in rows} == {
        (P + "R1", "가 (예시)", P + "JOB1"), (P + "R1", "나 (예시)", P + "JOB1"), (P + "R1", None, P + "JOB1"), (P + "R2", "다 (예시)", P + "JOB1")}

    r = c.get(f"{DEFECT_STATS}/rolls", params={**params, "defect_code": P + "D2", "item_id": w.item_b})
    detail = r.text[r.text.index('id="rolls"'):r.text.index("</main>")]
    assert "1건" in detail and f"<code>{P}R3</code>" in detail and f"<code>{P}JOB2</code>" in detail
    r = c.get(f"{DEFECT_STATS}/rolls", params={**params, "defect_code": P + "NOPE"})
    assert r.status_code == 422 and "없는 불량코드" in r.json()["message"]
    r = c.get(f"{DEFECT_STATS}/rolls", params={"date_from": "1990-01-01", "date_to": "1990-01-31"})
    assert r.status_code == 200 and "미수집" in r.text[r.text.index('id="rolls"'):]


# ── 웨이브 D (QA 결함 수정) ─────────────────────────────────────────────
HTML = {"accept": "text/html"}


@pytest.mark.fn("F-QUA-04")
def test_scan_of_unknown_roll_redraws_the_screen_with_the_scan_box(w):
    """없는 번호 스캔(GET `?no=`) — JSON 은 422, 브라우저는 **같은 화면**을 422 로 다시 그린다: 큰 글씨 사유 + 스캔칸 (D-201 · DEF-QA1-004)."""
    qc = client("qc")
    r = qc.get(INSPECTIONS, params={"no": P + "NOPE"})
    assert r.status_code == 422 and r.json()["code"] == "validation_error"
    r = qc.get(INSPECTIONS, params={"no": P + "NOPE", "device": "pop"}, headers=HTML)
    assert r.status_code == 422
    assert "data-scan" in r.text and 'id="scan-result"' in r.text and 'class="err big"' in r.text
    assert "없는 롤입니다" in r.text and P + "NOPE" in r.text and "ch-pop" in r.text
    assert 'id="inspection-form"' in r.text                               # 오류 화면이 아니라 검사 결과 화면이다
    r = qc.get(INSPECTIONS, params={"no": P + "R1"}, headers=HTML)        # 있는 번호는 그대로 200 — 배너가 없다
    assert r.status_code == 200 and 'id="scan-result"' not in r.text


@pytest.mark.fn("F-QUA-01", "F-QUA-04")
def test_roll_number_is_found_like_the_other_scan_screens(w):
    """소문자로 들어온 롤 번호 · 앞뒤 공백 — LOT 추적·롤 이력처럼 찾는다 (D-201 · DEF-QA2-003). 롤이 아닌 번호는 422."""
    qc = client("qc")
    low = (P + "R1").lower()
    assert low != P + "R1"
    r = qc.post(INSPECTIONS, data={"roll_no": f"  {low} ", "result": "합격", "delta_e": "1.0"})
    assert r.status_code == 200 and r.json()["roll_no"] == P + "R1"
    assert [x["roll_id"] for x in _rows(P + "R1")] == [w.r1]
    r = qc.get(INSPECTIONS, params={"no": low}, headers=HTML)
    assert r.status_code == 200 and f"<code>{P}R1</code>" in r.text
    assert f'name="roll_no" value="{P}R1"' in r.text                      # 등록칸에는 저장된 번호(대문자)가 채워진다
    lot = w.material_lot("M1", w.item_a)
    assert lot
    r = qc.post(INSPECTIONS, data={"roll_no": P + "M1", "result": "합격"})
    assert r.status_code == 422 and r.json()["message"] == "롤 번호가 아닙니다"


@pytest.mark.fn("F-QUA-01", "F-QUA-02")
def test_delta_e_out_of_column_range_is_422(w):
    """ΔE 는 numeric(7,2) — 담기지 않는 값은 500 이 아니라 422 이고 어느 칸인지 알려 준다 (DEF-QA1-002)."""
    qc = client("qc")
    for bad in ("99999.999", "99999.995", "100000", "1e15", "1e999", "-0.01", "NaN", "Infinity", "가"):
        r = qc.post(INSPECTIONS, data={"roll_no": P + "R1", "result": "합격", "delta_e": bad})
        assert r.status_code == 422, (bad, r.status_code, r.text[:120])
        assert r.json()["fields"][0]["name"] == "ΔE", bad
    assert _rows(P + "R1") == []                                          # 아무것도 쓰이지 않았다
    r = qc.post(INSPECTIONS, data={"roll_no": P + "R1", "result": "합격", "delta_e": "99999.994"})   # 담기는 가장 큰 값
    assert r.status_code == 200 and _rows(P + "R1")[0]["delta_e"] == Decimal("99999.99")
    iid = r.json()["inspection_id"]
    r = qc.post(f"{INSPECTIONS}/{iid}", data={"result": "합격", "delta_e": "99999.999"})
    assert r.status_code == 422 and _rows(P + "R1")[0]["delta_e"] == Decimal("99999.99")
    r = qc.post(f"{INSPECTIONS}/{iid}", data={"result": "합격", "delta_e": "1.005"})    # 소수 셋째 자리는 반올림
    assert r.status_code == 200 and _rows(P + "R1")[0]["delta_e"] == Decimal("1.01")


@pytest.mark.fn("F-QUA-02", "F-QUA-03")
def test_non_numeric_inspection_key_is_404(w):
    """경로의 검사 키 자리에 숫자가 아닌 글자 · 담기지 않는 큰 수 — 그런 검사는 없다(404). 다른 화면과 같다 (DEF-QA1-007)."""
    qc = client("qc")
    for key in ("abc", "1.5", "-1", "²", "9" * 30):
        for path, data in ((f"{INSPECTIONS}/{key}", {"result": "합격"}), (f"{INSPECTIONS}/{key}/delete", None)):
            r = qc.post(path, data=data)
            assert r.status_code == 404, (path, r.status_code, r.text[:100])
            assert r.json() == {"code": "not_found", "message": "대상을 찾을 수 없습니다"}
    assert client("field").post(f"{INSPECTIONS}/abc", data={"result": "합격"}).status_code == 403   # 권한이 먼저다


@pytest.mark.fn("F-QUA-05")
def test_item_condition_with_odd_digits_is_422(w):
    """품목 조건에 `²` 같은 글자 — isdigit() 은 참이지만 숫자가 아니다. 500 이 아니라 422."""
    qc = client("qc")
    for bad in ("²", "9" * 30, "abc"):
        for path in (DEFECT_STATS, DEFECT_STATS + "/rolls", nav.path_of("STA-01")):
            assert qc.get(path, params={"item_id": bad}).status_code == 422, (path, bad)
