# tests/test_dev1_std.py — STD 인쇄 기준 6 화면 — 실제 DB · 시드 뒤 · 만든 행은 지운다
import pytest

from lcomfine.db import conn
from test_dev1_common import cleanup, client, make_customer, make_item, make_order, make_request, uniq

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


@pytest.fixture
def p():
    prefix = uniq("std")
    yield prefix
    cleanup(prefix)


# ── STD-010 제조사양기준서 ──
@pytest.mark.fn("F-STD-011")
def test_spec_sheet_create(p):
    it = make_item(p)
    c = client("pr")
    r = c.post("/std/spec-sheets", data={"item_id": str(it["id"]), "title": "사양 (예시)", "content": "인쇄도수=4\n비고=x"})
    assert r.status_code == 200 and r.json()["revision"] == 1
    assert conn.q1("select content from spec_sheet where id = %s", (r.json()["id"],))["content"] == {"인쇄도수": "4", "비고": "x"}
    assert c.post("/std/spec-sheets", data={"item_id": str(it["id"]), "title": "x"}).json()["revision"] == 2
    assert c.post("/std/spec-sheets", data={"item_id": str(it["id"]), "title": "x", "revision": "1"}).status_code == 422
    assert c.post("/std/spec-sheets", data={"item_id": str(it["id"]), "title": "x", "content": "등호 없음"}).status_code == 422
    assert c.post("/std/spec-sheets", data={"item_id": str(it["id"])}).status_code == 422
    off = make_item(p + "N", use_yn="N")
    r = c.post("/std/spec-sheets", data={"item_id": str(off["id"]), "title": "x"})
    assert r.status_code == 422 and "사용 중지" in r.json()["fields"][0]["reason"]
    assert client("ds").post("/std/spec-sheets", data={"item_id": str(it["id"]), "title": "x"}).status_code == 403


@pytest.mark.fn("F-STD-012")
def test_spec_sheet_update(p):
    it = make_item(p)
    sid = conn.q1("insert into spec_sheet (item_id, title) values (%s, 'x') returning id", (it["id"],))["id"]
    c = client("admin")
    assert c.post(f"/std/spec-sheets/{sid}", data={"title": "새 제목", "content": "a=1", "use_yn": "N"}).status_code == 200
    assert conn.q1("select title, content, use_yn from spec_sheet where id = %s", (sid,)) == \
        {"title": "새 제목", "content": {"a": "1"}, "use_yn": "N"}
    assert c.post("/std/spec-sheets/99999999999", data={"title": "x"}).status_code == 404


@pytest.mark.fn("F-STD-013")
def test_spec_sheet_delete(p):
    it = make_item(p)
    cu = make_customer(p)
    rq = make_request(p, customer_id=cu["id"], item_id=it["id"])
    s1 = conn.q1("insert into spec_sheet (item_id, title, revision) values (%s, 'x', 1) returning id", (it["id"],))["id"]
    s2 = conn.q1("insert into spec_sheet (item_id, title, revision) values (%s, 'y', 2) returning id", (it["id"],))["id"]
    wo = make_order(p, request_id=rq["id"], item_id=it["id"])
    conn.x("update work_order set spec_sheet_id = %s where id = %s", (s2, wo["id"]))
    c = client("pr")
    assert c.post(f"/std/spec-sheets/{s1}/delete").json()["result"] == "삭제"
    assert c.post(f"/std/spec-sheets/{s2}/delete").json()["result"] == "사용 중지"
    assert c.post(f"/std/spec-sheets/{s1}/delete").status_code == 404


@pytest.mark.fn("F-STD-014")
def test_spec_sheet_list(p):
    it = make_item(p)
    conn.x("insert into spec_sheet (item_id, title, content) values (%s, %s, '{\"k\": \"v\"}')", (it["id"], p + "사양"))
    r = client("ds").get("/std/spec-sheets", params={"q": p})   # 디자인·개발실 R
    assert r.status_code == 200 and p + "사양" in r.text
    assert client("sl").get("/std/spec-sheets").status_code == 403


# ── STD-020 표준관리 ──
@pytest.mark.fn("F-STD-021")
def test_standard_create(p):
    c = client("pr")
    assert c.post("/std/standards", data={"standard_code": p + "S", "standard_name": "표준 (예시)",
                                          "content": "온도=미수집"}).status_code == 200
    assert c.post("/std/standards", data={"standard_code": p + "S", "standard_name": "x"}).status_code == 422
    assert c.post("/std/standards", data={"standard_name": "x"}).status_code == 422


@pytest.mark.fn("F-STD-022")
def test_standard_update(p):
    sid = conn.q1("insert into standard (standard_code, standard_name) values (%s, 'x') returning id", (p + "S",))["id"]
    c = client("admin")
    assert c.post(f"/std/standards/{sid}", data={"standard_name": "새 표준", "use_yn": "N"}).status_code == 200
    assert c.post(f"/std/standards/{sid}", data={"standard_code": "Z", "standard_name": "x"}).status_code == 422
    assert c.post("/std/standards/0", data={"standard_name": "x"}).status_code == 404


@pytest.mark.fn("F-STD-023")
def test_standard_delete(p):
    sid = conn.q1("insert into standard (standard_code, standard_name) values (%s, 'x') returning id", (p + "S",))["id"]
    assert client("pr").post(f"/std/standards/{sid}/delete").json()["result"] == "삭제"


@pytest.mark.fn("F-STD-024")
def test_standard_list(p):
    conn.x("insert into standard (standard_code, standard_name) values (%s, 'x')", (p + "S",))
    r = client("pr").get("/std/standards")
    assert r.status_code == 200 and p + "S" in r.text and "미확정 (D-519)" in r.text


# ── STD-030 판관리 ──
@pytest.mark.fn("F-STD-031")
def test_plate_create_with_usage(p):
    it = make_item(p)
    cu = make_customer(p)
    rq = make_request(p, customer_id=cu["id"], item_id=it["id"])
    wo = make_order(p, request_id=rq["id"], item_id=it["id"])
    c = client("ds")
    r = c.post("/std/plates", data={"plate_code": p + "P", "plate_name": "판 (예시)", "item_id": str(it["id"]),
                                    "used_on": "2026-10-01", "work_order_no": wo["work_order_no"]})
    assert r.status_code == 200, r.text
    u = conn.q1("select work_order_id, used_on::text as d from plate_usage where plate_id = %s", (r.json()["id"],))
    assert u == {"work_order_id": wo["id"], "d": "2026-10-01"}
    assert c.post("/std/plates", data={"plate_code": p + "P", "plate_name": "x"}).status_code == 422
    r = c.post("/std/plates", data={"plate_code": p + "Q", "plate_name": "x", "used_on": "2026-10-01",
                                    "work_order_no": "없는번호"})
    assert r.status_code == 422 and "지시번호" in r.json()["message"]
    assert conn.q1("select 1 from plate where plate_code = %s", (p + "Q",)) is None   # 같이 롤백


@pytest.mark.fn("F-STD-032")
def test_plate_update_adds_usage(p):
    pid = conn.q1("insert into plate (plate_code, plate_name) values (%s, 'x') returning id", (p + "P",))["id"]
    c = client("pr")
    assert c.post(f"/std/plates/{pid}", data={"plate_name": "판 (예시)", "used_on": "2026-10-02"}).status_code == 200
    assert conn.q1("select count(*) as n from plate_usage where plate_id = %s", (pid,))["n"] == 1
    assert c.post(f"/std/plates/{pid}", data={"plate_name": "x", "work_order_no": "WO"}).status_code == 422
    assert c.post(f"/std/plates/{pid}", data={"plate_code": "X", "plate_name": "x"}).status_code == 422
    assert c.post("/std/plates/99999999", data={"plate_name": "x"}).status_code == 404


@pytest.mark.fn("F-STD-033")
def test_plate_delete(p):
    used = conn.q1("insert into plate (plate_code, plate_name) values (%s, 'x') returning id", (p + "P",))["id"]
    conn.x("insert into plate_usage (plate_id, used_on) values (%s, current_date)", (used,))
    free = conn.q1("insert into plate (plate_code, plate_name) values (%s, 'x') returning id", (p + "Q",))["id"]
    c = client("ds")
    assert c.post(f"/std/plates/{used}/delete").json()["result"] == "사용 중지"
    assert c.post(f"/std/plates/{free}/delete").json()["result"] == "삭제"


@pytest.mark.fn("F-STD-034")
def test_plate_list(p):
    pid = conn.q1("insert into plate (plate_code, plate_name) values (%s, 'x') returning id", (p + "P",))["id"]
    r = client("ds").get("/std/plates", params={"plate": str(pid)})
    assert r.status_code == 200 and p + "P" in r.text
    assert client("ds").get("/std/plates", params={"plate": "x"}).status_code == 404


# ── STD-040 시안등록 ──
@pytest.mark.fn("F-STD-041")
def test_artwork_create_and_format(p):
    it = make_item(p)
    c = client("ds")
    r = c.post("/std/artworks", data={"item_id": str(it["id"]), "title": "시안 (예시)"},
               files={"image": ("a.png", PNG, "image/png")})
    assert r.status_code == 200, r.text
    assert r.json()["version"] == 1
    r = c.post("/std/artworks", data={"item_id": str(it["id"]), "title": "x"},
               files={"image": ("a.txt", b"hello", "text/plain")})
    assert r.status_code == 422 and "이미지 형식 오류" in r.json()["message"]
    r = c.post("/std/artworks", data={"item_id": str(it["id"]), "title": "x"},
               files={"image": ("a.png", b"not png", "image/png")})                 # 이름만 이미지
    assert r.status_code == 422
    assert c.post("/std/artworks", data={"item_id": str(it["id"]), "title": "x"}).status_code == 422   # 파일 누락
    assert client("pr").post("/std/artworks", data={"item_id": str(it["id"]), "title": "x"},
                             files={"image": ("a.png", PNG, "image/png")}).status_code == 403


@pytest.mark.fn("F-STD-042")
def test_artwork_update(p):
    it = make_item(p)
    aid = conn.q1("insert into artwork (item_id, title, file_name, content_type, image) values (%s, 'x', 'a.png', "
                  "'image/png', %s) returning id", (it["id"], PNG))["id"]
    c = client("admin")
    assert c.post(f"/std/artworks/{aid}", data={"title": "바꾼 시안", "use_yn": "N"}).status_code == 200
    gif = b"GIF89a" + b"\x00" * 10
    assert c.post(f"/std/artworks/{aid}", data={"title": "x"}, files={"image": ("b.gif", gif, "image/gif")}).status_code == 200
    assert conn.q1("select content_type, file_name from artwork where id = %s", (aid,)) == \
        {"content_type": "image/gif", "file_name": "b.gif"}
    assert c.post("/std/artworks/9999999999", data={"title": "x"}).status_code == 404


@pytest.mark.fn("F-STD-043")
def test_artwork_list(p):
    it = make_item(p)
    conn.x("insert into artwork (item_id, title, file_name, content_type, image) values (%s, %s, 'a.png', 'image/png', %s)",
           (it["id"], p + "시안", PNG))
    r = client("pr").get("/std/artworks", params={"item": str(it["id"])})
    assert r.status_code == 200 and p + "시안" in r.text and "data:image/png;base64," in r.text


# ── STD-050 표준견본서 ──
@pytest.mark.fn("F-STD-051")
def test_sample_sheet_create(p):
    it = make_item(p)
    c = client("sl")
    r = c.post("/std/sample-sheets", data={"item_id": str(it["id"]), "title": "견본 (예시)", "issued_on": "2026-10-21",
                                           "content": "색상=미수집"})
    assert r.status_code == 200
    assert c.post("/std/sample-sheets", data={"item_id": str(it["id"]), "title": "x", "issued_on": "21/10"}).status_code == 422
    assert c.post("/std/sample-sheets", data={"title": "x"}).status_code == 422
    assert client("pr").post("/std/sample-sheets", data={"item_id": str(it["id"]), "title": "x"}).status_code == 403


@pytest.mark.fn("F-STD-052")
def test_sample_sheet_update(p):
    it = make_item(p)
    sid = conn.q1("insert into sample_sheet (item_id, title) values (%s, 'x') returning id", (it["id"],))["id"]
    assert client("sl").post(f"/std/sample-sheets/{sid}", data={"title": "새 견본", "content": "a=b"}).status_code == 200
    assert conn.q1("select content from sample_sheet where id = %s", (sid,))["content"] == {"a": "b"}
    assert client("sl").post("/std/sample-sheets/99999999", data={"title": "x"}).status_code == 404


@pytest.mark.fn("F-STD-053")
def test_sample_sheet_list(p):
    it = make_item(p)
    conn.x("insert into sample_sheet (item_id, title) values (%s, %s)", (it["id"], p + "견본"))
    r = client("ac").get("/std/sample-sheets")
    assert r.status_code == 200 and p + "견본" in r.text


@pytest.mark.fn("F-STD-054")
def test_sample_sheet_print(p):
    it = make_item(p)
    sid = conn.q1("insert into sample_sheet (item_id, title, content) values (%s, %s, '{\"색상\": \"청\"}') returning id",
                  (it["id"], p + "견본"))["id"]
    r = client("pr").get(f"/std/sample-sheets/{sid}/print")
    assert r.status_code == 200 and p + "견본" in r.text and "색상" in r.text and "<script" not in r.text.split("</head>")[1]
    assert client("pr").get("/std/sample-sheets/99999999/print").status_code == 404
    assert client("sh").get(f"/std/sample-sheets/{sid}/print").status_code == 403


# ── STD-060 예외제품관리 ──
@pytest.mark.fn("F-STD-061")
def test_exception_item_create(p):
    it = make_item(p)
    c = client("admin")
    assert c.post("/std/exception-items", data={"item_id": str(it["id"]), "reason": "사유 (예시)"}).status_code == 200
    r = c.post("/std/exception-items", data={"item_id": str(it["id"]), "reason": "x"})
    assert r.status_code == 422 and "이미 예외" in r.json()["message"]
    assert c.post("/std/exception-items", data={"item_id": str(it["id"])}).status_code == 422
    assert client("pr").post("/std/exception-items", data={"item_id": str(it["id"]), "reason": "x"}).status_code == 403


@pytest.mark.fn("F-STD-062")
def test_exception_item_update(p):
    it = make_item(p)
    eid = conn.q1("insert into exception_item (item_id, reason) values (%s, 'x') returning id", (it["id"],))["id"]
    assert client("admin").post(f"/std/exception-items/{eid}", data={"reason": "새 사유", "use_yn": "N"}).status_code == 200
    assert conn.q1("select reason, use_yn from exception_item where id = %s", (eid,)) == {"reason": "새 사유", "use_yn": "N"}


@pytest.mark.fn("F-STD-063")
def test_exception_item_delete(p):
    it = make_item(p)
    eid = conn.q1("insert into exception_item (item_id, reason) values (%s, 'x') returning id", (it["id"],))["id"]
    assert client("admin").post(f"/std/exception-items/{eid}/delete").json()["result"] == "삭제"
    assert client("admin").post(f"/std/exception-items/{eid}/delete").status_code == 404


@pytest.mark.fn("F-STD-064")
def test_exception_item_list(p):
    it = make_item(p)
    conn.x("insert into exception_item (item_id, reason) values (%s, %s)", (it["id"], p + "사유"))
    r = client("admin").get("/std/exception-items")
    assert r.status_code == 200 and p + "사유" in r.text and "미확정 (D-519)" in r.text
