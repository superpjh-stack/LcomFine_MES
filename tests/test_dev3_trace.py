"""LOT 추적 (F-TRC-01~03 · P9) — 설계도 §3 예시를 SQL 로 차려 놓고 화면이 그 계보를 단계별로 보여 주는지 본다.

추적 자체(재귀 조회)는 개발2 `lineage` 의 것이다. 여기서는 **화면이 그 읽기 함수만 부르고 아무 테이블에도 쓰지 않는지**,
번호 하나로 경로가 나오는지, 재고 롤이 `재고` 로 표시되는지, 현장 역할이 403 인지를 본다. 데이터 접두 `T3T-`.
"""
import re

import pytest

from lcomfine.app import nav

from test_dev3_support import SqlSpy, World, cleanup, client, leftovers

P = "T3T-"
TRACE = nav.path_of("TRC-01")


@pytest.fixture(scope="module")
def ex():
    """설계도 §3 그림: LOT 2 → 인쇄 2 → 후가공 1(splice) → 슬리팅 3 → 출하 1(①② 출하, ③ 재고) = 계보 10행."""
    w = World(P)
    item, raw, cust = w.item("P1"), w.item("RAW", "원재료"), w.customer()
    job = w.job("JOB1", item, cust)
    lot1, lot2 = w.material_lot("LOT1", raw), w.material_lot("LOT2", raw)
    p1, p2 = w.roll("P1", job, "인쇄"), w.roll("P2", job, "인쇄")
    f = w.roll("F1", job, "후가공")
    s1, s2, s3 = (w.roll(f"S{i}", job, "슬리팅") for i in (1, 2, 3))
    ship = w.shipment("SHIP1", job, cust)
    w.edge("투입", lot=lot1, child=p1)
    w.edge("투입", lot=lot1, child=p2)
    w.edge("투입", lot=lot2, child=p2)
    w.edge("splice", parent=p1, child=f)
    w.edge("splice", parent=p2, child=f)
    for s in (s1, s2, s3):
        w.edge("슬리팅", parent=f, child=s)
    w.edge("출하", parent=s1, ship=ship)
    w.edge("출하", parent=s2, ship=ship)
    w.material_lot("LOT9", raw)                 # 아무 데도 투입되지 않은 LOT
    yield w
    cleanup(P)
    assert leftovers(P) == {}


def _main(html: str) -> str:
    """본문만 — 좌측 메뉴·계약 패널의 글자를 빼고 본다."""
    return html[html.index('<main class="main">'):html.index("</main>")]


@pytest.mark.fn("F-TRC-02")
def test_backward_from_shipment_reaches_both_material_lots(ex):
    """완료 기준 — 출하 LOT 하나에서 원재료 LOT ①② 까지 거슬러 올라간다."""
    r = client("qc").get(f"{TRACE}/backward", params={"no": P + "SHIP1"})
    assert r.status_code == 200
    body = _main(r.text)
    assert "역방향 추적" in body and "닿은 원재료 LOT 2건" in body
    assert P + "LOT1" in body and P + "LOT2" in body
    assert "4단계" in body and "화살표 9줄" in body                # 출하 2 → 슬리팅 2 → splice 2 → 투입 3
    assert P + "S3" not in body                                    # 출하되지 않은 ③ 은 이 출하의 계보가 아니다
    assert [s for s in re.findall(r"<h3>(\d+)단계", body)] == ["1", "2", "3", "4"]

    r = client("prod").get(f"{TRACE}/backward", params={"no": P + "S3"})     # 롤에서 시작해도 된다
    body = _main(r.text)
    assert r.status_code == 200 and "닿은 원재료 LOT 2건" in body and "3단계" in body and "4단계" not in body


@pytest.mark.fn("F-TRC-01")
def test_forward_from_material_lot_reaches_shipment_and_marks_stock(ex):
    r = client("admin").get(f"{TRACE}/forward", params={"no": P + "LOT1"})
    assert r.status_code == 200
    body = _main(r.text)
    assert "정방향 추적" in body and "닿은 출하 LOT 1건" in body and "재고로 남은 롤 1개" in body
    for no in ("P1", "P2", "F1", "S1", "S2", "S3", "SHIP1"):
        assert P + no in body, no
    assert P + "LOT2" not in body                                  # LOT ② 의 투입은 LOT ① 의 경로가 아니다
    assert "화살표 9줄" in body and "4단계" in body
    stock = re.findall(r'<code>([^<]+)</code></a>\s*<span class="badge stock">재고</span>', body)
    assert set(stock) == {P + "S3"}                                # 자식이 없는 롤만 `재고`

    body = _main(client("admin").get(f"{TRACE}/forward", params={"no": P + "S3"}).text)   # 재고 롤 — 이어진 것이 없다
    assert "미수집" in body and "(재고)" in body and "닿은 출하 LOT 0건" in body
    body = _main(client("admin").get(f"{TRACE}/forward", params={"no": P + "LOT9"}).text)
    assert "아직 투입되지 않았다" in body and "미수집" in body


@pytest.mark.fn("F-TRC-03")
def test_search_by_partial_number(ex):
    c = client("admin")
    r = c.get(TRACE, params={"q": P.lower()})                      # 번호 일부 · 대소문자 무시
    assert r.status_code == 200
    body = _main(r.text)
    assert "10건" in body                                          # 원재료 LOT 3 + 롤 6 + 출하 LOT 1
    for no in ("LOT1", "LOT2", "LOT9", "P1", "P2", "F1", "S1", "S2", "S3", "SHIP1"):
        assert P + no in body, no
    lot_hit = body[body.index(f"<code>{P}LOT1</code>"):body.index(f"<code>{P}LOT2</code>")]
    assert "forward?no=" in lot_hit and "backward?no=" not in lot_hit        # 원재료 LOT 은 정방향만
    ship_hit = body[body.index(f"<code>{P}SHIP1</code>"):]
    assert "backward?no=" in ship_hit and "forward?no=" not in ship_hit      # 출하 LOT 은 역방향만

    body = _main(c.get(TRACE, params={"no": P + "S2"}).text)       # 화면의 입력칸 이름(`no`)으로도 검색된다
    assert "1건" in body and "forward?no=" in body and "backward?no=" in body
    body = _main(c.get(TRACE, params={"q": P + "없는번호"}).text)
    assert "미수집" in body and "0건" in body
    assert "검색 결과" in _main(c.get(TRACE).text)                 # 검색어 없이 열면 안내만


@pytest.mark.fn("F-TRC-01", "F-TRC-02")
def test_unknown_or_wrong_direction_number_is_422(ex):
    c = client("admin")
    for path, no, text in [("forward", "", "번호를 입력"), ("backward", "", "번호를 입력"),
                           ("forward", P + "NOPE", "없는 번호"), ("backward", P + "NOPE", "없는 번호"),
                           ("forward", P + "SHIP1", "역방향 추적으로"), ("backward", P + "LOT1", "정방향 추적으로")]:
        r = c.get(f"{TRACE}/{path}", params={"no": no})
        assert r.status_code == 422 and r.json()["code"] == "validation_error" and text in r.json()["message"], (path, no)


@pytest.mark.fn("F-TRC-01", "F-TRC-02", "F-TRC-03")
def test_field_role_is_403_and_anonymous_401(ex):
    """권한 표: 현장 × LOT 추적 = 없음 → 403. 관리자·생산·품질은 조회."""
    field = client("field")
    for path, params in [(TRACE, {"q": P}), (f"{TRACE}/forward", {"no": P + "LOT1"}), (f"{TRACE}/backward", {"no": P + "SHIP1"})]:
        r = field.get(path, params=params)
        assert r.status_code == 403 and r.json()["code"] == "forbidden", path
        assert client().get(path, params=params).status_code == 401
        for login_id in ("admin", "prod", "qc"):
            assert client(login_id).get(path, params=params).status_code == 200, (login_id, path)


@pytest.mark.fn("F-TRC-01", "F-TRC-02", "F-TRC-03")
def test_trace_screens_write_nothing(ex, monkeypatch):
    """P9 는 어떤 테이블에도 쓰지 않는다(G-05) — 화면이 돌린 SQL 은 select 뿐이고, 쓰기는 공통 접근 로그 한 줄뿐이다."""
    c = client("admin")
    for path, params in [(TRACE, {"q": P}), (f"{TRACE}/forward", {"no": P + "LOT1"}), (f"{TRACE}/backward", {"no": P + "SHIP1"})]:
        spy = SqlSpy(monkeypatch)
        assert c.get(path, params=params).status_code == 200
        spy.assert_read_only()
        assert len(spy.writes) == 1                                # 화면 조회 로그 (D-15)
        monkeypatch.undo()
    import inspect

    from lcomfine.app.routers import trc
    src = inspect.getsource(trc)
    assert "import conn" not in src and "conn." not in src         # 라우터는 DB 를 직접 만지지 않는다 — lineage 의 읽기 함수만
    assert not re.search(r"\b(insert\s+into|update\s+\w+\s+set|delete\s+from)\b", src, re.I)


@pytest.mark.fn("F-TRC-01", "F-TRC-02", "F-TRC-03")
def test_mobile_layout_has_no_wide_table(ex):
    """모바일 채널(G-13) — 한 단 레이아웃이고, 추적 결과는 표가 아니라 세로로 쌓는 목록이다(가로로 넘칠 표가 없다)."""
    c = client("admin")
    for path, params in [(TRACE, {"q": P}), (f"{TRACE}/forward", {"no": P + "LOT1"}), (f"{TRACE}/backward", {"no": P + "SHIP1"})]:
        html = c.get(path, params={**params, "device": "mobile"}).text
        assert 'class="ch-mobile"' in html
        body = _main(html)
        assert "<table" not in body and "trace-panel" in body
