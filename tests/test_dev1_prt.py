"""인쇄 기준 관리 — 판사양·아니록스·잉크조성 × (등록·수정·삭제·조회) = F-PRT-01~12.

규약은 기준정보와 같다(`routers/bas.py` 의 Master). 잉크조성만 조성 행(성분·비율)이 있다 — 수정하면 통째로 바꿔 넣는다.
권한: 관리자·생산은 입력 · 품질·현장은 조회(쓰기 403).
규격 값은 받은 적이 없으므로 테스트 값에도 `(예시)` 를 붙이고, 끝나면 지운다.
"""
from decimal import Decimal

import pytest

from lcomfine.db import conn
from test_dev1_helpers import (TEST_BY, check_master_create, check_master_delete, check_master_read,
                               check_master_update, cleanup, client, master_create, master_row, sql_job, tag)

PLATE = dict(path="/prt/plates", table="plate_spec", pk="plate_spec_id", code="plate_code", name="plate_name",
             extra={"color_count": "4", "spec_note": "사양 메모 (예시)"},
             bad_extra={"color_count": "0", "item_id": "999999999"},
             fns=("F-PRT-01", "F-PRT-02", "F-PRT-03", "F-PRT-04"))
ANILOX = dict(path="/prt/anilox", table="anilox", pk="anilox_id", code="anilox_code", name="anilox_name",
              extra={"line_count": "120.00", "cell_volume": "3.500", "note": "비고 (예시)"},
              bad_extra={"line_count": "많음", "cell_volume": "-1"},
              fns=("F-PRT-05", "F-PRT-06", "F-PRT-07", "F-PRT-08"))
INK = dict(path="/prt/inks", table="ink_formula", pk="ink_formula_id", code="ink_code", name="ink_name",
           extra={"color_name": "색 (예시)", "target_l": "50.00", "target_a": "-1.50", "target_b": "2.25"},
           bad_extra={"target_l": "밝음", "target_a": "1e9"},
           fns=("F-PRT-09", "F-PRT-10", "F-PRT-11", "F-PRT-12"))

CREATE = [
    pytest.param(PLATE, id="plate_spec", marks=pytest.mark.fn("F-PRT-01")),
    pytest.param(ANILOX, id="anilox", marks=pytest.mark.fn("F-PRT-05")),
    pytest.param(INK, id="ink_formula", marks=pytest.mark.fn("F-PRT-09")),
]
UPDATE = [
    pytest.param(PLATE, id="plate_spec", marks=pytest.mark.fn("F-PRT-02")),
    pytest.param(ANILOX, id="anilox", marks=pytest.mark.fn("F-PRT-06")),
    pytest.param(INK, id="ink_formula", marks=pytest.mark.fn("F-PRT-10")),
]
DELETE = [
    pytest.param(PLATE, id="plate_spec", marks=pytest.mark.fn("F-PRT-03")),
    pytest.param(ANILOX, id="anilox", marks=pytest.mark.fn("F-PRT-07")),
    pytest.param(INK, id="ink_formula", marks=pytest.mark.fn("F-PRT-11")),
]
READ = [
    pytest.param(PLATE, id="plate_spec", marks=pytest.mark.fn("F-PRT-04")),
    pytest.param(ANILOX, id="anilox", marks=pytest.mark.fn("F-PRT-08")),
    pytest.param(INK, id="ink_formula", marks=pytest.mark.fn("F-PRT-12")),
]
MASTERS = (PLATE, ANILOX, INK)

# 삭제를 막는 참조 (D-21) — 셋 다 작업지시가 가리킨다
REF_COLUMN = {"plate_spec": "plate_spec_id", "anilox": "anilox_id", "ink_formula": "ink_formula_id"}


@pytest.fixture
def t():
    prefix = tag()
    yield prefix
    cleanup(prefix)


def _marked(request) -> tuple:
    return request.node.get_closest_marker("fn").args


def _components(ink_id: int) -> list[tuple[int, str, Decimal]]:
    return [(r["seq_no"], r["component_name"], r["ratio_pct"]) for r in conn.q(
        "select seq_no, component_name, ratio_pct from ink_formula_component where ink_formula_id = %s order by seq_no",
        (ink_id,))]


@pytest.mark.parametrize("m", CREATE)
def test_create(m, t, request):
    assert _marked(request) == (m["fns"][0],)
    check_master_create(m, t)


@pytest.mark.parametrize("m", UPDATE)
def test_update(m, t, request):
    assert _marked(request) == (m["fns"][1],)
    check_master_update(m, t)


@pytest.mark.parametrize("m", DELETE)
def test_delete(m, t, request):
    assert _marked(request) == (m["fns"][2],)
    check_master_delete(m, t, lambda row_id, tt: sql_job(tt, **{REF_COLUMN[m["table"]]: row_id}))


@pytest.mark.parametrize("m", READ)
def test_read(m, t, request):
    assert _marked(request) == (m["fns"][3],)
    check_master_read(m, t)


@pytest.mark.fn("F-PRT-01", "F-PRT-02", "F-PRT-04")
def test_plate_points_to_a_product_item(t):
    """판사양의 품목은 품목 마스터에서 고른다. 없는 품목은 422. 규격 숫자를 안 주면 비어 있다(지어내지 않는다)."""
    c = client("admin")
    item_id = conn.q1("""insert into item (item_code, item_name, item_type, created_by) values (%s, %s, '제품', %s)
                         returning item_id""", (f"{t}-FG", f"{t} 제품 (예시)", TEST_BY))["item_id"]
    r = c.post("/prt/plates", data={"plate_code": f"{t}-P", "plate_name": f"{t} 판 (예시)", "item_id": str(item_id)})
    assert r.status_code == 200, r.text
    row = master_row(PLATE, r.json()["id"])
    assert row["item_id"] == item_id and row["color_count"] is None and row["spec_note"] is None
    assert f"{t}-FG" in c.get("/prt/plates", params={"code": f"{t}-P"}).text         # 목록에 품목이 보인다
    assert c.post(f"/prt/plates/{row['plate_spec_id']}", data={"item_id": "999999999"}).status_code == 422
    assert master_row(PLATE, row["plate_spec_id"])["item_id"] == item_id


@pytest.mark.fn("F-PRT-09")
def test_ink_create_with_components(t):
    """잉크조성 등록 — 조성 행(성분·비율)을 순서대로 넣는다. 빈 줄은 건너뛴다. 비율이 틀리면 잉크조성도 만들지 않는다."""
    c = client("admin")
    r = c.post("/prt/inks", data={"ink_code": f"{t}-I", "ink_name": f"{t} 잉크 (예시)",
                                  "component_name": ["성분 1 (예시)", "", "성분 2 (예시)"], "ratio_pct": ["60", "", "40"]})
    assert r.status_code == 200, r.text
    ink_id = r.json()["id"]
    assert _components(ink_id) == [(1, "성분 1 (예시)", Decimal("60.000")), (2, "성분 2 (예시)", Decimal("40.000"))]
    page = c.get("/prt/inks", params={"code": f"{t}-I"}).text
    assert "성분 1 (예시) 60% / 성분 2 (예시) 40%" in page                           # 목록에 조성이 보인다

    for names, ratios in ((["a"], ["0"]), (["a"], ["101"]), (["a"], ["많이"]), (["a"], [""]), ([""], ["10"]),
                          (["a", "b"], ["10"])):
        r = c.post("/prt/inks", data={"ink_code": f"{t}-BAD", "ink_name": "x (예시)",
                                      "component_name": names, "ratio_pct": ratios})
        assert r.status_code == 422, (names, ratios)
    assert conn.q1("select count(*) as n from ink_formula where ink_code = %s", (f"{t}-BAD",))["n"] == 0


@pytest.mark.fn("F-PRT-10")
def test_ink_update_replaces_components_wholesale(t):
    c = client("admin")
    ink_id = c.post("/prt/inks", data={"ink_code": f"{t}-I", "ink_name": f"{t} 잉크 (예시)",
                                       "component_name": ["a (예시)", "b (예시)"], "ratio_pct": ["70", "30"]}).json()["id"]
    # 조성 항목이 폼에 없으면 조성 행은 그대로다
    assert c.post(f"/prt/inks/{ink_id}", data={"color_name": "색 (예시)"}).status_code == 200
    assert [n for _, n, _ in _components(ink_id)] == ["a (예시)", "b (예시)"]
    # 있으면 통째로 바꿔 넣는다
    r = c.post(f"/prt/inks/{ink_id}", data={"component_name": ["c (예시)"], "ratio_pct": ["100"]})
    assert r.status_code == 200, r.text
    assert _components(ink_id) == [(1, "c (예시)", Decimal("100.000"))]
    # 틀린 조성은 422 이고 기존 조성이 남는다
    assert c.post(f"/prt/inks/{ink_id}", data={"component_name": ["d"], "ratio_pct": ["-5"]}).status_code == 422
    assert _components(ink_id) == [(1, "c (예시)", Decimal("100.000"))]
    # 수정 폼에 지금 조성이 실려 온다
    page = c.get("/prt/inks", params={"edit": ink_id}).text
    assert 'value="c (예시)"' in page and 'value="100.000"' in page


@pytest.mark.fn("F-PRT-11")
def test_ink_delete_removes_components(t):
    c = client("admin")
    ink_id = c.post("/prt/inks", data={"ink_code": f"{t}-I", "ink_name": f"{t} 잉크 (예시)",
                                       "component_name": ["a (예시)"], "ratio_pct": ["100"]}).json()["id"]
    assert c.post(f"/prt/inks/{ink_id}/delete").status_code == 200       # 조성 행은 참조로 치지 않는다 — 함께 지워진다
    assert master_row(INK, ink_id) is None and _components(ink_id) == []


@pytest.mark.parametrize("m", [pytest.param(m, id=m["table"]) for m in MASTERS])
def test_write_roles(m, t):
    """관리자·생산은 입력 · 품질·현장은 조회만(쓰기 403) · 미로그인 401."""
    row_id = master_create(client("prod"), m, t)["id"]                   # 생산도 등록한다
    assert master_row(m, row_id)["created_by"] == "prod"
    writes = [(m["path"], {m["code"]: f"{t}-X", m["name"]: "x (예시)", **m["extra"]}),
              (f"{m['path']}/{row_id}", {m["name"]: "바꿈 (예시)"}),
              (f"{m['path']}/{row_id}/delete", {}),
              (m["path"], {})]
    for login_id in ("qc", "field"):                                      # 인쇄 기준 관리 = 조회
        c = client(login_id)
        assert c.get(m["path"]).status_code == 200
        for path, data in writes:
            r = c.post(path, data=data)
            assert r.status_code == 403 and r.json()["code"] == "forbidden", (login_id, path)
    anon = client()
    assert anon.get(m["path"]).status_code == 401
    for path, data in writes:
        assert anon.post(path, data=data).status_code == 401, path
    row = master_row(m, row_id)
    assert row is not None and row[m["name"]] == f"{t}-A (예시)" and row["updated_at"] is None
