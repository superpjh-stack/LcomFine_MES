"""개발1 테스트 공용 도구 — 로그인한 클라이언트 · 고유 접두 · 뒷정리. (테스트 함수는 없다)

- 테스트 데이터의 업무 코드는 전부 `T1-<8자>-…` 로 시작한다. 다른 사람의 데이터에 기대지 않고, 끝나면 지운다.
- 시드 계정(admin·prod·qc·field)은 **로그인에만** 쓴다 — 계정·권한 표의 시드 행을 바꾸지 않는다.
"""
from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from lcomfine.app.main import app
from lcomfine.app.settings import get_settings
from lcomfine.db import conn

TEST_BY = "t1-test"


def tag() -> str:
    """이번 테스트만의 접두 — `T1-1A2B3C4D`."""
    return f"T1-{uuid.uuid4().hex[:8].upper()}"


def client(login_id: str | None = None, password: str | None = None) -> TestClient:
    c = TestClient(app, raise_server_exceptions=False)
    if login_id:
        r = c.post("/login", data={"login_id": login_id, "password": password or get_settings().seed_password},
                   follow_redirects=False)
        assert r.status_code == 303, f"{login_id} 로그인 실패 {r.status_code} — 공통 시드와 .env 를 확인한다"
    return c


def change_logs(function_id: str, target: str) -> int:
    """그 기능·대상의 `변경` 로그 수 (G-18)."""
    return conn.q1("""select count(*) as n from sys_access_log
                       where log_type = '변경' and function_id = %s and target = %s""", (function_id, target))["n"]


def drop_logs(target_prefix: str) -> None:
    """테스트가 만든 변경 로그를 치운다 (`target` 이 `테이블:T1-…`)."""
    conn.x("delete from sys_access_log where target like %s", (f"%:{target_prefix}%",))


def master_ids(t: str) -> dict:
    """작업지시 테스트용 기준정보 한 벌을 SQL 로 만든다(자기 데이터). 키: item · raw · customer · plate · anilox · ink · equipment."""
    with conn.tx() as cur:
        def one(sql: str, params: tuple) -> int:
            cur.execute(sql, params)
            return next(iter(cur.fetchone().values()))

        return {
            "item": one("""insert into item (item_code, item_name, item_type, unit, created_by)
                           values (%s, %s, '제품', 'm', %s) returning item_id""", (f"{t}-FG", f"{t} 제품 (예시)", TEST_BY)),
            "raw": one("""insert into item (item_code, item_name, item_type, unit, created_by)
                          values (%s, %s, '원재료', 'm', %s) returning item_id""", (f"{t}-RM", f"{t} 원재료 (예시)", TEST_BY)),
            "customer": one("""insert into customer (customer_code, customer_name, created_by)
                               values (%s, %s, %s) returning customer_id""", (f"{t}-CU", f"{t} 고객 (예시)", TEST_BY)),
            "plate": one("""insert into plate_spec (plate_code, plate_name, created_by)
                            values (%s, %s, %s) returning plate_spec_id""", (f"{t}-PL", f"{t} 판 (예시)", TEST_BY)),
            "anilox": one("""insert into anilox (anilox_code, anilox_name, created_by)
                             values (%s, %s, %s) returning anilox_id""", (f"{t}-AN", f"{t} 아니록스 (예시)", TEST_BY)),
            "ink": one("""insert into ink_formula (ink_code, ink_name, created_by)
                          values (%s, %s, %s) returning ink_formula_id""", (f"{t}-INK", f"{t} 잉크 (예시)", TEST_BY)),
            "equipment": one("""insert into equipment (equipment_code, equipment_name, created_by)
                                values (%s, %s, %s) returning equipment_id""", (f"{t}-EQ", f"{t} 설비 (예시)", TEST_BY)),
        }


def drop_jobs_of(t: str) -> None:
    """접두 `t` 의 품목으로 만든 Job 과 그 아래 것(실적·롤·생산 LOT)을 지운다."""
    with conn.tx() as cur:
        cur.execute("""select job_id from job where item_id in (select item_id from item where item_code like %s)""",
                    (f"{t}%",))
        ids = [r["job_id"] for r in cur.fetchall()]
        if ids:
            # 그 Job·생산 LOT 의 변경 로그도 치운다 (번호가 채번 형식이라 접두로는 못 찾는다)
            cur.execute("""delete from sys_access_log where log_type = '변경' and (
                               target in (select 'job:' || job_no from job where job_id = any(%s))
                            or target in (select 'job_lot:' || lot_no from job_lot where job_id = any(%s)))""", (ids, ids))
            cur.execute("delete from work_scrap where work_result_id in (select work_result_id from work_result where job_id = any(%s))", (ids,))
            cur.execute("delete from roll where job_id = any(%s)", (ids,))
            cur.execute("delete from work_result where job_id = any(%s)", (ids,))
            cur.execute("delete from job_lot where job_id = any(%s)", (ids,))
            cur.execute("delete from job where job_id = any(%s)", (ids,))


def drop_masters(t: str) -> None:
    """접두 `t` 로 만든 기준정보·인쇄 기준을 지운다 (참조 순서대로)."""
    like = f"{t}%"
    with conn.tx() as cur:
        cur.execute("delete from plate_spec where plate_code like %s", (like,))
        cur.execute("delete from anilox where anilox_code like %s", (like,))
        cur.execute("delete from ink_formula where ink_code like %s", (like,))
        cur.execute("delete from equipment where equipment_code like %s", (like,))
        cur.execute("delete from process where process_code like %s", (like,))
        cur.execute("delete from defect_code where defect_code like %s", (like,))
        cur.execute("delete from customer where customer_code like %s", (like,))
        cur.execute("delete from item where item_code like %s", (like,))


def cleanup(t: str) -> None:
    drop_sql_jobs(t)
    drop_jobs_of(t)
    drop_masters(t)
    drop_logs(t)


# ── 마스터 4기능(등록·수정·삭제·조회) 공통 검증 — 기준정보 5종과 인쇄 기준 3종이 같은 규약이다 ──
IN_USE = "사용 중이라 삭제할 수 없습니다"


def master_create(c: TestClient, m: dict, t: str, suffix: str = "A", **override) -> dict:
    """마스터 한 행을 API 로 등록하고 응답(JSON)을 돌려준다."""
    code = f"{t}-{suffix}"
    data = {m["code"]: code, m["name"]: f"{code} (예시)", **m["extra"], **override}
    r = c.post(m["path"], data=data)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["code"] == code and isinstance(body["id"], int)
    return body


def master_row(m: dict, row_id: int) -> dict | None:
    return conn.q1(f"select * from {m['table']} where {m['pk']} = %s", (row_id,))


def check_master_create(m: dict, t: str) -> None:
    c = client("admin")
    body = master_create(c, m, t)
    row = master_row(m, body["id"])
    assert row[m["code"]] == f"{t}-A" and row[m["name"]] == f"{t}-A (예시)"
    assert row["use_yn"] == "Y" and row["created_by"] == "admin"
    for k, v in m["extra"].items():
        assert str(row[k]) == str(v), (k, row[k], v)
    assert change_logs(m["fns"][0], f"{m['table']}:{t}-A") == 1                      # 쓰기 성공 = 변경 로그 한 줄

    # 코드 중복 422 · 필수값 누락 422 — 어느 쪽도 행을 만들지 않는다
    r = c.post(m["path"], data={m["code"]: f"{t}-A", m["name"]: "중복 (예시)", **m["extra"]})
    assert r.status_code == 422 and r.json()["code"] == "validation_error" and f"{t}-A" in r.text
    r = c.post(m["path"], data={m["code"]: f"{t}-B", **m["extra"]})                  # 이름 누락
    assert r.status_code == 422 and r.json()["fields"]
    r = c.post(m["path"], data={m["name"]: "코드 없음 (예시)", **m["extra"]})         # 코드 누락
    assert r.status_code == 422
    for k in m.get("required_extra", ()):                                            # 필수 선택값 누락
        data = {m["code"]: f"{t}-C", m["name"]: "x (예시)", **{a: b for a, b in m["extra"].items() if a != k}}
        assert c.post(m["path"], data=data).status_code == 422, k
    for k, v in m.get("bad_extra", {}).items():                                      # 형식이 틀린 값
        r = c.post(m["path"], data={m["code"]: f"{t}-D", m["name"]: "x (예시)", **m["extra"], k: v})
        assert r.status_code == 422, (k, v, r.text)
    assert conn.q1(f"select count(*) as n from {m['table']} where {m['code']} like %s", (f"{t}%",))["n"] == 1


def check_master_update(m: dict, t: str) -> None:
    c = client("admin")
    row_id = master_create(c, m, t)["id"]
    path = f"{m['path']}/{row_id}"
    r = c.post(path, data={m["name"]: f"{t} 바뀐 이름 (예시)", "use_yn": "N"})
    assert r.status_code == 200, r.text
    row = master_row(m, row_id)
    assert row[m["name"]] == f"{t} 바뀐 이름 (예시)" and row["use_yn"] == "N"
    assert row["updated_by"] == "admin" and row["updated_at"] is not None
    assert row[m["code"]] == f"{t}-A"
    for k, v in m["extra"].items():                                                  # 폼에 없던 항목은 그대로
        assert str(row[k]) == str(v), k
    assert change_logs(m["fns"][1], f"{m['table']}:{t}-A") == 1

    r = c.post(path, data={m["code"]: f"{t}-Z", m["name"]: "x (예시)"})               # 코드는 못 바꾼다
    assert r.status_code == 422 and master_row(m, row_id)[m["code"]] == f"{t}-A"
    assert c.post(path, data={m["code"]: f"{t}-A", "use_yn": "Y"}).status_code == 200  # 같은 코드를 보내는 것은 된다
    assert master_row(m, row_id)["use_yn"] == "Y"
    assert c.post(path, data={"use_yn": "X"}).status_code == 422
    assert c.post(path, data={m["name"]: ""}).status_code == 422                     # 이름을 비울 수 없다
    assert c.post(f"{m['path']}/999999999", data={m["name"]: "x"}).status_code == 404  # 없는 ID
    assert c.post(f"{m['path']}/abc", data={m["name"]: "x"}).status_code == 404


def check_master_delete(m: dict, t: str, make_reference) -> None:
    """`make_reference(row_id, t)` 는 그 행을 가리키는 다른 테이블의 행을 SQL 로 만든다."""
    c = client("admin")
    free = master_create(c, m, t, "A")["id"]
    used = master_create(c, m, t, "B")["id"]
    make_reference(used, t)

    r = c.post(f"{m['path']}/{used}/delete")                                         # 참조가 있으면 422, 행은 남는다
    assert r.status_code == 422 and r.json()["message"] == IN_USE and r.json()["fields"], r.text
    assert master_row(m, used) is not None
    assert change_logs(m["fns"][2], f"{m['table']}:{t}-B") == 0                      # 실패한 쓰기는 변경 로그가 없다

    r = c.post(f"{m['path']}/{free}/delete")                                         # 참조가 없으면 지운다
    assert r.status_code == 200, r.text
    assert master_row(m, free) is None
    assert change_logs(m["fns"][2], f"{m['table']}:{t}-A") == 1
    assert c.post(f"{m['path']}/{free}/delete").status_code == 404                   # 이미 없는 ID
    assert c.post(f"{m['path']}/abc/delete").status_code == 404


def check_master_read(m: dict, t: str) -> None:
    c = client("admin")
    a = master_create(c, m, t, "A")["id"]
    master_create(c, m, t, "B")
    assert c.post(f"{m['path']}/{a}", data={"use_yn": "N"}).status_code == 200

    r = c.get(m["path"], params={"code": t})
    assert r.status_code == 200 and "미구현" not in r.text
    assert f"{t}-A" in r.text and f"{t}-B" in r.text
    r = c.get(m["path"], params={"code": t.lower(), "use_yn": "Y"})                  # 대소문자 무시 · 사용 여부
    assert f"{t}-B" in r.text and f"{t}-A" not in r.text
    r = c.get(m["path"], params={"name": f"{t}-B (예시)"})                            # 이름으로
    assert f"{t}-B" in r.text and f"{t}-A" not in r.text
    r = c.get(m["path"], params={"code": f"{t}-없는코드"})                            # 0건이면 미수집 (G-11)
    assert r.status_code == 200 and 'class="empty">미수집' in r.text
    r = c.get(m["path"], params={"code": f"{t}-%"})                                  # `%` 는 와일드카드가 아니다
    assert 'class="empty">미수집' in r.text
    r = c.get(m["path"], params={"edit": a})                                         # 수정 폼이 그 행으로 열린다
    assert r.status_code == 200 and f'action="{m["path"]}/{a}"' in r.text
    assert c.get(m["path"], params={"edit": 999999999}).status_code == 404


def sql_job(t: str, *, item_id: int | None = None, customer_id: int | None = None, suffix: str = "J", **cols) -> int:
    """참조 검사용 Job 한 행을 SQL 로 만든다. 번호는 채번 형식과 겹치지 않는 테스트 접두다."""
    with conn.tx() as cur:
        if item_id is None:
            cur.execute("""insert into item (item_code, item_name, item_type, created_by) values (%s, %s, '제품', %s)
                           on conflict (item_code) do update set item_name = excluded.item_name returning item_id""",
                        (f"{t}-JI", f"{t} 제품 (예시)", TEST_BY))
            item_id = cur.fetchone()["item_id"]
        if customer_id is None:
            cur.execute("""insert into customer (customer_code, customer_name, created_by) values (%s, %s, %s)
                           on conflict (customer_code) do update set customer_name = excluded.customer_name
                           returning customer_id""", (f"{t}-JC", f"{t} 고객 (예시)", TEST_BY))
            customer_id = cur.fetchone()["customer_id"]
        names = ["job_no", "item_id", "customer_id", "order_qty", "qty_unit", "due_date", "created_by", *cols]
        values = [f"{t}-{suffix}", item_id, customer_id, 100, "m", "2099-12-31", TEST_BY, *cols.values()]
        cur.execute(f"insert into job ({', '.join(names)}) values ({', '.join(['%s'] * len(names))}) returning job_id", values)
        return cur.fetchone()["job_id"]


def drop_sql_jobs(t: str) -> None:
    """`sql_job` 이 만든 Job(번호가 접두 `t`)과 그 아래 것을 지운다."""
    with conn.tx() as cur:
        cur.execute("select job_id from job where job_no like %s", (f"{t}%",))
        ids = [r["job_id"] for r in cur.fetchall()]
        if ids:
            cur.execute("delete from work_scrap where work_result_id in (select work_result_id from work_result where job_id = any(%s))", (ids,))
            cur.execute("delete from roll where job_id = any(%s)", (ids,))
            cur.execute("delete from work_result where job_id = any(%s)", (ids,))
            cur.execute("delete from job_lot where job_id = any(%s)", (ids,))
            cur.execute("delete from job where job_id = any(%s)", (ids,))
