"""기준정보 관리 — 품목·고객·공정·설비·불량코드 × (등록·수정·삭제·조회) = F-BAS-01~20.

다섯 중메뉴가 같은 규약(`routers/bas.py` 의 Master)이라 검증도 한 벌(`test_dev1_helpers.check_master_*`)을 다섯 번 돈다.
권한: 관리자만 입력 · 생산/품질은 조회(쓰기 403) · 현장은 없음(조회도 403).
데이터는 전부 접두 `T1-…` 로 만들고 끝나면 지운다.
"""
import json
import re

import pytest

from lcomfine.db import conn
from test_dev1_helpers import (TEST_BY, check_master_create, check_master_delete, check_master_read,
                               check_master_update, cleanup, client, master_create, master_row, sql_job, tag)

ITEM = dict(path="/bas/items", table="item", pk="item_id", code="item_code", name="item_name",
            extra={"item_type": "원재료", "spec": "규격 (예시)", "unit": "kg"},
            required_extra=("item_type",), bad_extra={"item_type": "반제품"},
            fns=("F-BAS-01", "F-BAS-02", "F-BAS-03", "F-BAS-04"))
CUSTOMER = dict(path="/bas/customers", table="customer", pk="customer_id", code="customer_code", name="customer_name",
                extra={"note": "비고 (예시)"}, fns=("F-BAS-05", "F-BAS-06", "F-BAS-07", "F-BAS-08"))
PROCESS = dict(path="/bas/processes", table="process", pk="process_id", code="process_code", name="process_name",
               extra={"process_type": "후가공", "sort_no": "7"},
               required_extra=("process_type",), bad_extra={"process_type": "포장", "sort_no": "일곱"},
               fns=("F-BAS-09", "F-BAS-10", "F-BAS-11", "F-BAS-12"))
EQUIPMENT = dict(path="/bas/equipment", table="equipment", pk="equipment_id", code="equipment_code", name="equipment_name",
                 extra={"note": "비고 (예시)"}, bad_extra={"process_id": "999999999"},
                 fns=("F-BAS-13", "F-BAS-14", "F-BAS-15", "F-BAS-16"))
DEFECT = dict(path="/bas/defect-codes", table="defect_code", pk="defect_code_id", code="defect_code", name="defect_name",
              extra={"defect_group": "분류 (예시)"}, fns=("F-BAS-17", "F-BAS-18", "F-BAS-19", "F-BAS-20"))
MASTERS = (ITEM, CUSTOMER, PROCESS, EQUIPMENT, DEFECT)


# ── 삭제를 막는 참조 (D-21) — 그 행을 가리키는 다른 테이블의 행을 SQL 로 만든다 ──
def ref_item(item_id: int, t: str) -> None:           # 품목 ← 판사양
    conn.x("insert into plate_spec (plate_code, plate_name, item_id, created_by) values (%s, %s, %s, %s)",
           (f"{t}-REF", f"{t} 판 (예시)", item_id, TEST_BY))


def ref_customer(customer_id: int, t: str) -> None:   # 고객 ← 작업지시
    sql_job(t, customer_id=customer_id)


def ref_process(process_id: int, t: str) -> None:     # 공정 ← 설비
    conn.x("insert into equipment (equipment_code, equipment_name, process_id, created_by) values (%s, %s, %s, %s)",
           (f"{t}-REF", f"{t} 설비 (예시)", process_id, TEST_BY))


def ref_equipment(equipment_id: int, t: str) -> None:  # 설비 ← 작업지시(계획 설비)
    sql_job(t, equipment_id=equipment_id)


def ref_defect(defect_code_id: int, t: str) -> None:  # 불량코드 ← 폐기 기록
    job_id = sql_job(t)
    with conn.tx() as cur:
        cur.execute("insert into work_result (job_id, worker) values (%s, %s) returning work_result_id", (job_id, TEST_BY))
        cur.execute("insert into work_scrap (work_result_id, scrap_qty, defect_code_id, created_by) values (%s, 1, %s, %s)",
                    (cur.fetchone()["work_result_id"], defect_code_id, TEST_BY))


REFS = {"item": ref_item, "customer": ref_customer, "process": ref_process, "equipment": ref_equipment,
        "defect_code": ref_defect}


# 기능마다 표식 하나 — `check-trace`(G-02) 는 이 `mark.fn(...)` 글자만 센다. 그래서 ID 를 풀어서 적는다.
CREATE = [
    pytest.param(ITEM, id="item", marks=pytest.mark.fn("F-BAS-01")),
    pytest.param(CUSTOMER, id="customer", marks=pytest.mark.fn("F-BAS-05")),
    pytest.param(PROCESS, id="process", marks=pytest.mark.fn("F-BAS-09")),
    pytest.param(EQUIPMENT, id="equipment", marks=pytest.mark.fn("F-BAS-13")),
    pytest.param(DEFECT, id="defect_code", marks=pytest.mark.fn("F-BAS-17")),
]
UPDATE = [
    pytest.param(ITEM, id="item", marks=pytest.mark.fn("F-BAS-02")),
    pytest.param(CUSTOMER, id="customer", marks=pytest.mark.fn("F-BAS-06")),
    pytest.param(PROCESS, id="process", marks=pytest.mark.fn("F-BAS-10")),
    pytest.param(EQUIPMENT, id="equipment", marks=pytest.mark.fn("F-BAS-14")),
    pytest.param(DEFECT, id="defect_code", marks=pytest.mark.fn("F-BAS-18")),
]
DELETE = [
    pytest.param(ITEM, id="item", marks=pytest.mark.fn("F-BAS-03")),
    pytest.param(CUSTOMER, id="customer", marks=pytest.mark.fn("F-BAS-07")),
    pytest.param(PROCESS, id="process", marks=pytest.mark.fn("F-BAS-11")),
    pytest.param(EQUIPMENT, id="equipment", marks=pytest.mark.fn("F-BAS-15")),
    pytest.param(DEFECT, id="defect_code", marks=pytest.mark.fn("F-BAS-19")),
]
READ = [
    pytest.param(ITEM, id="item", marks=pytest.mark.fn("F-BAS-04")),
    pytest.param(CUSTOMER, id="customer", marks=pytest.mark.fn("F-BAS-08")),
    pytest.param(PROCESS, id="process", marks=pytest.mark.fn("F-BAS-12")),
    pytest.param(EQUIPMENT, id="equipment", marks=pytest.mark.fn("F-BAS-16")),
    pytest.param(DEFECT, id="defect_code", marks=pytest.mark.fn("F-BAS-20")),
]


@pytest.fixture
def t():
    prefix = tag()
    yield prefix
    cleanup(prefix)


def _marked(request) -> tuple:
    """이 테스트에 붙은 기능 표식 — 표식과 실제로 부르는 기능이 어긋나지 않게 대조한다."""
    return request.node.get_closest_marker("fn").args


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
    check_master_delete(m, t, REFS[m["table"]])


@pytest.mark.parametrize("m", READ)
def test_read(m, t, request):
    assert _marked(request) == (m["fns"][3],)
    check_master_read(m, t)


@pytest.mark.fn("F-BAS-13", "F-BAS-14")
def test_equipment_belongs_to_process(t):
    """설비는 공정을 고른다. 수정 폼에서 공정을 비우면 비워진다. 설비 상태·수집값은 받지 않는다(G-12)."""
    c = client("admin")
    process_id = master_create(c, PROCESS, t, "P")["id"]
    body = master_create(c, EQUIPMENT, t, "E", process_id=str(process_id))
    assert master_row(EQUIPMENT, body["id"])["process_id"] == process_id
    r = c.get("/bas/equipment", params={"code": f"{t}-E"})
    assert f"{t}-P" in r.text                                             # 목록에 공정이 보인다
    assert c.post(f"/bas/equipment/{body['id']}", data={"process_id": ""}).status_code == 200
    assert master_row(EQUIPMENT, body["id"])["process_id"] is None
    # 계약에 없는 항목(설비 상태 등)을 보내도 저장되는 컬럼이 없다
    assert c.post(f"/bas/equipment/{body['id']}", data={"equipment_name": f"{t} 설비 (예시)", "status": "가동"}).status_code == 200
    assert set(master_row(EQUIPMENT, body["id"])) == {"equipment_id", "equipment_code", "equipment_name", "process_id", "note",
                                                      "use_yn", "created_at", "created_by", "updated_at", "updated_by"}


@pytest.mark.parametrize("m", [pytest.param(m, id=m["table"]) for m in MASTERS])
def test_write_needs_input_permission(m, t):
    """조회 역할(생산·품질)의 쓰기 403 · 없음 역할(현장)은 조회도 403 · 미로그인 401. 권한 판정이 입력값 검증보다 먼저다."""
    row_id = master_create(client("admin"), m, t)["id"]
    writes = [(m["path"], {m["code"]: f"{t}-X", m["name"]: "x (예시)", **m["extra"]}),
              (f"{m['path']}/{row_id}", {m["name"]: "바꿈 (예시)"}),
              (f"{m['path']}/{row_id}/delete", {}),
              (m["path"], {})]                                            # 빈 폼이어도 422 가 아니라 403
    for login_id in ("prod", "qc"):                                       # 기준정보 관리 = 조회
        c = client(login_id)
        assert c.get(m["path"]).status_code == 200
        for path, data in writes:
            r = c.post(path, data=data)
            assert r.status_code == 403 and r.json()["code"] == "forbidden", (login_id, path)
    c = client("field")                                                   # 기준정보 관리 = 없음
    assert c.get(m["path"]).status_code == 403
    for path, data in writes:
        assert c.post(path, data=data).status_code == 403, path
    anon = client()
    assert anon.get(m["path"]).status_code == 401
    for path, data in writes:
        assert anon.post(path, data=data).status_code == 401, path
    row = master_row(m, row_id)                                           # 아무것도 바뀌지 않았다
    assert row is not None and row[m["name"]] == f"{t}-A (예시)" and row["updated_at"] is None
    assert conn.q1(f"select count(*) as n from {m['table']} where {m['code']} like %s", (f"{t}%",))["n"] == 1


def _flash(html: str) -> dict | None:
    """화면에 실린 알림(`base.html` 의 flash-data)."""
    found = re.search(r'<script type="application/json" id="flash-data">(.*?)</script>', html, re.S)
    return json.loads(found.group(1)) if found else None


def test_browser_form_post_redirects_with_notice(t):
    """브라우저(Accept: text/html)의 쓰기 — 성공도 422 도 303 으로 원래 화면에 돌아가 알림을 한 번 보인다."""
    c = client("admin")
    html = {"accept": "text/html"}
    r = c.post("/bas/customers", data={"customer_code": f"{t}-A", "customer_name": f"{t} 고객 (예시)"},
               headers=html, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/bas/customers"
    assert _flash(c.get("/bas/customers", headers=html).text)["message"] == "고객을(를) 등록했습니다"
    assert _flash(c.get("/bas/customers", headers=html).text) is None            # 알림은 한 번만
    r = c.post("/bas/customers", data={"customer_code": f"{t}-A", "customer_name": "중복 (예시)"},
               headers={**html, "referer": "http://testserver/bas/customers"}, follow_redirects=False)
    assert r.status_code == 303
    flash = _flash(c.get("/bas/customers", headers=html).text)
    assert flash["message"] == "이미 있는 고객 코드입니다" and flash["fields"][0]["reason"] == f"{t}-A"
