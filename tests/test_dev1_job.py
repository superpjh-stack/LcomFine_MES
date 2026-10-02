"""작업지시 관리 — 작업지시 5(등록·수정·취소·조회·작업지시서 출력) + Job-Lot-Roll 매핑 2(등록·조회) = F-JOB-01~07.

- Job 번호·생산 LOT 번호는 `numbering` 이 낸다(G-08). 경로의 키는 Job 번호다(D-21).
- P2 는 D2(`job` `job_lot`)에만 쓴다. 작업 실적·롤은 현장 실행이 만들므로 여기서는 SQL 로 흉내 낸 행을 넣어 규칙만 확인한다.
- 권한: 관리자·생산 입력 · 품질·현장 조회(쓰기 403).
기준정보는 접두 `T1-…` 로 스스로 만들고, 만든 Job 과 함께 끝나면 지운다.
"""
import re
from datetime import date, timedelta

import pytest

from lcomfine.app import numbering
from lcomfine.db import conn
from test_dev1_helpers import TEST_BY, change_logs, cleanup, client, master_ids, tag

ORDERS, MAPPING = "/job/orders", "/job/mapping"


@pytest.fixture
def t():
    prefix = tag()
    yield prefix
    cleanup(prefix)


@pytest.fixture
def ids(t):
    return master_ids(t)


def _form(ids: dict, **override) -> dict:
    data = {"item_id": ids["item"], "customer_id": ids["customer"], "plate_spec_id": ids["plate"], "anilox_id": ids["anilox"],
            "ink_formula_id": ids["ink"], "equipment_id": ids["equipment"], "order_qty": "1200.5", "qty_unit": "m",
            "due_date": (date.today() + timedelta(days=14)).isoformat(), "note": "비고 (예시)"}
    data.update(override)
    return {k: v for k, v in data.items() if v is not None}


def _create(c, ids: dict, **override) -> str:
    r = c.post(ORDERS, data=_form(ids, **override))
    assert r.status_code == 200, r.text
    return r.json()["job_no"]


def _job(job_no: str) -> dict | None:
    return conn.q1("select * from job where job_no = %s", (job_no,))


def _work_result(job_no: str) -> int:
    """현장 실행(P5)이 만든 작업 실적을 흉내 낸다 — Job 이 "진행" 인지는 이 행이 있는가로 읽는다."""
    return conn.q1("""insert into work_result (job_id, worker) select job_id, %s from job where job_no = %s
                      returning work_result_id""", (TEST_BY, job_no))["work_result_id"]


def _outside_d2(ids: dict) -> dict:
    """이 테스트의 품목·Job 에 걸린 D2 밖의 행 수 — P2 는 D2(`job` `job_lot`)에만 쓴다(G-05).
    다른 사람의 테스트가 같은 DB 에 쓰는 중이어도 흔들리지 않게 자기 데이터로 좁혀서 센다."""
    job = "select job_id from job where item_id = %(item)s"
    sql = {
        "material_lot": "select count(*) as n from material_lot where item_id in (%(item)s, %(raw)s)",
        "work_result": f"select count(*) as n from work_result where job_id in ({job})",
        "roll": f"select count(*) as n from roll where job_id in ({job})",
        "roll_genealogy": f"""select count(*) as n from roll_genealogy g
                               where g.parent_roll_id in (select roll_id from roll where job_id in ({job}))
                                  or g.child_roll_id in (select roll_id from roll where job_id in ({job}))""",
        "color_record": f"select count(*) as n from color_record where job_id in ({job})",
        "inspection": f"select count(*) as n from inspection where job_id in ({job})",
        "shipment": f"select count(*) as n from shipment where job_id in ({job})",
    }
    return {name: conn.q1(q, ids)["n"] for name, q in sql.items()}


# ── F-JOB-01 작업지시 등록 ──────────────────────────────────────────────
@pytest.mark.fn("F-JOB-01")
def test_create_order_numbers_from_numbering(t, ids):
    c = client("admin")
    rule = numbering.rule("JOB")
    r = c.post(ORDERS, data=_form(ids))
    assert r.status_code == 200, r.text
    body = r.json()
    job_no = body["job_no"]
    assert body["status"] == "등록"
    assert job_no.startswith(rule["prefix"]) and re.fullmatch(r"[A-Z0-9-]+", job_no)        # 형식은 sys_number_rule 행
    assert int(job_no[-rule["seq_digits"]:]) >= 1
    row = _job(job_no)
    assert (row["item_id"], row["customer_id"], row["plate_spec_id"], row["anilox_id"], row["ink_formula_id"],
            row["equipment_id"]) == (ids["item"], ids["customer"], ids["plate"], ids["anilox"], ids["ink"], ids["equipment"])
    assert str(row["order_qty"]) == "1200.500" and row["qty_unit"] == "m" and row["status"] == "등록"
    assert row["created_by"] == "admin" and row["due_date"] == date.today() + timedelta(days=14)
    assert change_logs("F-JOB-01", f"job:{job_no}") == 1

    second = _create(c, ids, plate_spec_id=None, anilox_id=None, ink_formula_id=None, equipment_id=None, qty_unit=None)
    assert second != job_no                                                                 # 번호는 겹치지 않는다
    assert _job(second)["qty_unit"] == "m" and _job(second)["plate_spec_id"] is None        # 단위는 품목의 단위
    assert set(_outside_d2(ids).values()) == {0}                                            # P2 는 D2 에만 쓴다 (G-05)


@pytest.mark.fn("F-JOB-01")
def test_create_order_validation(t, ids):
    c = client("admin")
    before = conn.q1("select count(*) as n from job where item_id = %s", (ids["item"],))["n"]
    bad = [
        {"item_id": None}, {"customer_id": None}, {"order_qty": None}, {"due_date": None},      # 필수값 누락
        {"item_id": 999999999}, {"customer_id": 999999999}, {"plate_spec_id": 999999999},       # 없는 기준정보
        {"item_id": ids["raw"]},                                                                # 원재료는 지시 대상이 아니다
        {"order_qty": "0"}, {"order_qty": "-3"}, {"order_qty": "많이"}, {"order_qty": "NaN"},
        {"due_date": "2026-13-40"}, {"due_date": "내일"},
    ]
    for override in bad:
        r = c.post(ORDERS, data=_form(ids, **override))
        assert r.status_code == 422 and r.json()["code"] == "validation_error", (override, r.text)
    assert conn.q1("select count(*) as n from job where item_id = %s", (ids["item"],))["n"] == before

    conn.x("update customer set use_yn = 'N' where customer_id = %s", (ids["customer"],))      # 미사용 기준정보로는 새로 지시하지 못한다
    assert c.post(ORDERS, data=_form(ids)).status_code == 422


# ── F-JOB-02 작업지시 수정 ──────────────────────────────────────────────
@pytest.mark.fn("F-JOB-02")
def test_update_order_rules(t, ids):
    c = client("prod")                                                       # 생산도 입력한다
    job_no = _create(c, ids)
    path = f"{ORDERS}/{job_no}"

    # 실적이 생기기 전에는 품목·수량도 바꾼다
    r = c.post(path, data={"order_qty": "900", "note": "바뀐 비고 (예시)"})
    assert r.status_code == 200, r.text
    row = _job(job_no)
    assert str(row["order_qty"]) == "900.000" and row["note"] == "바뀐 비고 (예시)" and row["updated_by"] == "prod"
    assert row["customer_id"] == ids["customer"]                              # 폼에 없던 항목은 그대로
    assert change_logs("F-JOB-02", f"job:{job_no}") == 1
    assert c.post(path, data={"order_qty": "900"}).status_code == 422         # 바뀌는 값이 없다
    assert c.post(path, data={"order_qty": "0"}).status_code == 422
    assert c.post(path, data={"status": "보류"}).status_code == 422
    assert c.post(path, data={"status": "취소"}).status_code == 422           # 취소는 취소 기능으로

    # 작업 실적이 생긴 뒤 — 품목·수량은 422, 납기·비고·마감은 된다
    _work_result(job_no)
    r = c.post(path, data={"order_qty": "500"})
    assert r.status_code == 422 and "작업 실적" in r.json()["message"]
    assert c.post(path, data={"item_id": ids["raw"]}).status_code == 422
    assert str(_job(job_no)["order_qty"]) == "900.000"
    new_due = (date.today() + timedelta(days=30)).isoformat()
    assert c.post(path, data={"due_date": new_due, "note": "납기 변경 (예시)"}).status_code == 200
    assert c.post(path, data={"status": "완료"}).status_code == 200           # 마감
    row = _job(job_no)
    assert row["due_date"].isoformat() == new_due and row["status"] == "완료"

    assert c.post(f"{ORDERS}/{t}-없는번호", data={"note": "x"}).status_code == 404   # 경로의 키가 없으면 404


@pytest.mark.fn("F-JOB-02", "F-JOB-03")
def test_cancelled_order_cannot_be_updated(t, ids):
    c = client("admin")
    job_no = _create(c, ids)
    assert c.post(f"{ORDERS}/{job_no}/cancel").status_code == 200
    r = c.post(f"{ORDERS}/{job_no}", data={"note": "취소 뒤 수정 (예시)"})
    assert r.status_code == 422 and _job(job_no)["note"] == "비고 (예시)"


# ── F-JOB-03 작업지시 취소 ──────────────────────────────────────────────
@pytest.mark.fn("F-JOB-03")
def test_cancel_order_keeps_the_row(t, ids):
    c = client("admin")
    job_no = _create(c, ids)
    r = c.post(f"{ORDERS}/{job_no}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "취소"
    row = _job(job_no)
    assert row is not None and row["status"] == "취소" and row["updated_by"] == "admin"   # 행은 지우지 않는다 (D-21)
    assert change_logs("F-JOB-03", f"job:{job_no}") == 1
    assert c.post(f"{ORDERS}/{job_no}/cancel").status_code == 422             # 이미 취소
    assert c.post(f"{ORDERS}/{t}-없는번호/cancel").status_code == 404

    busy = _create(c, ids)                                                    # 작업 실적이 있으면 422
    _work_result(busy)
    r = c.post(f"{ORDERS}/{busy}/cancel")
    assert r.status_code == 422 and r.json()["fields"][0]["name"] == "작업 실적"
    assert _job(busy)["status"] == "등록"

    rolled = _create(c, ids)                                                  # 롤이 있어도 422
    conn.x("""insert into roll (roll_no, process_type, job_id, produced_by)
              select %s, '후가공', job_id, %s from job where job_no = %s""", (f"{t}-R1", TEST_BY, rolled))
    r = c.post(f"{ORDERS}/{rolled}/cancel")
    assert r.status_code == 422 and r.json()["fields"][0]["name"] == "롤"
    assert _job(rolled)["status"] == "등록"


# ── F-JOB-04 작업지시 조회 ──────────────────────────────────────────────
@pytest.mark.fn("F-JOB-04")
def test_orders_search_and_open_by_number(t, ids):
    c = client("qc")                                                          # 품질은 조회만
    admin = client("admin")
    a = _create(admin, ids, due_date="2031-03-10")
    b = _create(admin, ids, due_date="2031-04-20")
    assert admin.post(f"{ORDERS}/{b}/cancel").status_code == 200

    page = c.get(ORDERS, params={"item_id": ids["item"]}).text
    assert a in page and b in page and "미구현" not in page
    page = c.get(ORDERS, params={"item_id": ids["item"], "status": "취소"}).text
    assert b in page and a not in page
    page = c.get(ORDERS, params={"item_id": ids["item"], "due_from": "2031-03-01", "due_to": "2031-03-31"}).text
    assert a in page and b not in page
    page = c.get(ORDERS, params={"customer_id": ids["customer"], "q": a[2:]}).text          # 번호 일부
    assert a in page
    page = c.get(ORDERS, params={"q": f"{t}-없는번호"}).text
    assert 'class="empty">미수집' in page                                     # 0건이면 미수집 (G-11)
    assert c.get(ORDERS, params={"due_from": "어제"}).status_code == 422

    page = c.get(ORDERS, params={"no": a}).text                               # `?no=` 스캔 진입 — 한 건이 열린다
    assert f'action="{ORDERS}/{a}"' in page and f"{ORDERS}/{a}/print" in page and f"{t}-FG" in page
    r = c.get(ORDERS, params={"no": f"{t}-없는번호"})                          # 입력한 번호가 없으면 422
    assert r.status_code == 422 and r.json()["fields"][0]["name"] == "Job 번호"


# ── F-JOB-05 작업지시서 출력 ────────────────────────────────────────────
@pytest.mark.fn("F-JOB-05")
def test_print_order_has_barcode_of_job_number(t, ids):
    admin = client("admin")
    job_no = _create(admin, ids)
    conn.x("insert into ink_formula_component (ink_formula_id, seq_no, component_name, ratio_pct) values (%s, 1, %s, 100)",
           (ids["ink"], f"{t} 성분 (예시)"))
    lot_no = admin.post(MAPPING, data={"job_no": job_no, "planned_roll_count": "2"}).json()["lot_no"]

    r = client("field").get(f"{ORDERS}/{job_no}/print")                       # 현장도 조회 이상 — 출력한다
    assert r.status_code == 200
    page = r.text
    assert "작업지시서" in page and 'data-print="작업지시서"' in page
    assert f'data-barcode="{job_no}"' in page and 'data-symbology="code128"' in page   # 바코드가 담는 값 = Job 번호 그대로
    for shown in (f"{t}-FG", f"{t}-CU", f"{t}-PL", f"{t}-AN", f"{t}-INK", f"{t}-EQ", f"{t} 성분 (예시)", lot_no, "1,200.500 m"):
        assert shown in page, shown
    assert (date.today() + timedelta(days=14)).isoformat() in page            # 납기
    assert "window.print()" in page

    assert client("admin").get(f"{ORDERS}/{t}-없는번호/print").status_code == 404
    assert client().get(f"{ORDERS}/{job_no}/print").status_code == 401


# ── F-JOB-06 Job-Lot-Roll 매핑 등록 ─────────────────────────────────────
@pytest.mark.fn("F-JOB-06")
def test_mapping_attaches_production_lots(t, ids):
    c = client("admin")
    job_no = _create(c, ids)
    job_id = _job(job_no)["job_id"]
    rule = numbering.rule("JOB_LOT")

    r = c.post(MAPPING, data={"job_no": job_no, "planned_roll_count": "3", "planned_length_m": "1500", "note": "계획 (예시)"})
    assert r.status_code == 200, r.text
    body = r.json()
    lot_no = body["lot_no"]
    assert body["created"] is True and body["job_no"] == job_no
    assert lot_no.startswith(rule["prefix"]) and re.fullmatch(r"[A-Z0-9-]+", lot_no)
    lot = conn.q1("select * from job_lot where lot_no = %s", (lot_no,))
    assert (lot["job_id"], lot["planned_roll_count"], str(lot["planned_length_m"]), lot["created_by"]) == (job_id, 3, "1500.000", "admin")
    assert change_logs("F-JOB-06", f"job_lot:{lot_no}") == 1

    second = c.post(MAPPING, data={"job_no": job_no}).json()["lot_no"]        # 한 Job 에 생산 LOT 여럿 (D-10)
    assert second != lot_no
    assert conn.q1("select count(*) as n from job_lot where job_id = %s", (job_id,))["n"] == 2

    # 같은 요청으로 계획값 수정 — LOT 번호를 주면 그 LOT 을 고친다(새로 만들지 않는다)
    r = c.post(MAPPING, data={"job_no": job_no, "lot_no": lot_no, "planned_roll_count": "5", "planned_length_m": "2000"})
    assert r.status_code == 200 and r.json()["created"] is False
    lot = conn.q1("select * from job_lot where lot_no = %s", (lot_no,))
    assert (lot["planned_roll_count"], str(lot["planned_length_m"]), lot["note"], lot["updated_by"]) == (5, "2000.000", "계획 (예시)", "admin")
    assert conn.q1("select count(*) as n from job_lot where job_id = %s", (job_id,))["n"] == 2
    assert set(_outside_d2(ids).values()) == {0}                              # 원재료 LOT·롤을 미리 묶지 않는다 (G-05 · D-10)

    for data in ({"job_no": f"{t}-없는번호"}, {}, {"job_no": job_no, "planned_roll_count": "0"},
                 {"job_no": job_no, "planned_roll_count": "두 개"}, {"job_no": job_no, "planned_length_m": "-1"},
                 {"job_no": job_no, "lot_no": f"{t}-없는LOT", "planned_roll_count": "1"}):
        assert c.post(MAPPING, data=data).status_code == 422, data
    other = _create(c, ids)                                                   # 다른 Job 의 LOT 을 이 Job 으로 고칠 수 없다
    assert c.post(MAPPING, data={"job_no": other, "lot_no": lot_no, "planned_roll_count": "9"}).status_code == 422
    assert c.post(f"{ORDERS}/{other}/cancel").status_code == 200              # 취소된 Job 에는 붙이지 못한다
    assert c.post(MAPPING, data={"job_no": other}).status_code == 422
    assert conn.q1("select count(*) as n from job_lot where job_id = (select job_id from job where job_no = %s)", (other,))["n"] == 0


# ── F-JOB-07 Job-Lot-Roll 매핑 조회 ─────────────────────────────────────
@pytest.mark.fn("F-JOB-07")
def test_mapping_view_groups_job_lot_roll(t, ids):
    admin = client("admin")
    job_no = _create(admin, ids)
    lot_no = admin.post(MAPPING, data={"job_no": job_no, "planned_roll_count": "2"}).json()["lot_no"]
    c = client("field")                                                       # 현장은 조회만

    page = c.get(MAPPING, params={"no": job_no}).text
    assert job_no in page and lot_no in page and "미구현" not in page
    assert 'class="empty">미수집' in page                                     # 롤이 없으면 미수집

    # 현장 실행이 만든 롤을 흉내 낸다 — 생산 LOT 아래 인쇄 롤 하나, LOT 없는 후가공 롤 하나
    conn.x("""insert into roll (roll_no, process_type, job_id, job_lot_id, length_m, produced_by)
              select %s, '인쇄', l.job_id, l.job_lot_id, 500, %s from job_lot l where l.lot_no = %s""",
           (f"{t}-R1", TEST_BY, lot_no))
    conn.x("""insert into roll (roll_no, process_type, job_id, produced_by)
              select %s, '후가공', job_id, %s from job where job_no = %s""", (f"{t}-R2", TEST_BY, job_no))
    def mine() -> dict:                                                       # 이 Job 에 걸린 행 수 (자기 데이터로 좁혀 센다)
        return {"job": conn.q1("select count(*) as n from job where item_id = %s", (ids["item"],))["n"],
                "job_lot": conn.q1("select count(*) as n from job_lot where job_id = (select job_id from job where job_no = %s)", (job_no,))["n"],
                "updated": conn.q1("select count(*) as n from job_lot where updated_at is not null and lot_no = %s", (lot_no,))["n"],
                **_outside_d2(ids)}

    before = mine()
    page = c.get(MAPPING, params={"no": job_no}).text
    assert f"{t}-R1" in page and f"{t}-R2" in page and "인쇄" in page and "후가공" in page and "재고" in page
    listing = c.get(MAPPING, params={"q": job_no}).text                       # 목록에서도 찾는다
    assert job_no in listing
    assert mine() == before and before["roll"] == 2                           # 읽기만 한다

    r = c.get(MAPPING, params={"no": f"{t}-없는번호"})
    assert r.status_code == 422
    assert c.get(MAPPING, params={"no": job_no, "lot": f"{t}-없는LOT"}).status_code == 422
    assert f'value="{lot_no}"' in admin.get(MAPPING, params={"no": job_no, "lot": lot_no}).text   # 계획 수정 폼


# ── 권한 ────────────────────────────────────────────────────────────────
def test_read_only_roles_cannot_write(t, ids):
    """작업지시 관리 — 품질·현장은 조회. 쓰기 4기능 전부 403 이고 아무것도 바뀌지 않는다. 미로그인 401."""
    job_no = _create(client("admin"), ids)
    writes = [(ORDERS, _form(ids)), (f"{ORDERS}/{job_no}", {"note": "x"}), (f"{ORDERS}/{job_no}/cancel", {}),
              (MAPPING, {"job_no": job_no}), (ORDERS, {}), (MAPPING, {})]
    for login_id in ("qc", "field"):
        c = client(login_id)
        assert c.get(ORDERS).status_code == 200 and c.get(MAPPING).status_code == 200
        for path, data in writes:
            r = c.post(path, data=data)
            assert r.status_code == 403 and r.json()["code"] == "forbidden", (login_id, path)
    anon = client()
    for path, data in writes:
        assert anon.post(path, data=data).status_code == 401
    assert anon.get(ORDERS).status_code == 401 and anon.get(MAPPING).status_code == 401
    row = _job(job_no)
    assert row["status"] == "등록" and row["note"] == "비고 (예시)" and row["updated_at"] is None
    assert conn.q1("select count(*) as n from job where item_id = %s", (ids["item"],))["n"] == 1
    assert conn.q1("select count(*) as n from job_lot where job_id = %s", (row["job_id"],))["n"] == 0
