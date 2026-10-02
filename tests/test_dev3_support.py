"""개발3 테스트의 공용 도우미 — 테스트가 아니다(이 파일에는 test_ 함수가 없다).

다른 사람의 시드·화면·데이터에 기대지 않는다. 필요한 기준정보·Job·롤·계보는 여기서 **SQL 로 직접** 만들고
(번호는 접두 `T3?-` — 채번 형식과 겹치지 않는다), 끝나면 `cleanup(접두)` 가 그 접두의 행을 전부 지운다.
계정만 공통 시드의 4개(admin · prod · qc · field)를 쓴다. 값은 전부 `(예시)` 다 — 실데이터가 아니다.
"""
from __future__ import annotations

from datetime import date, datetime

from fastapi.testclient import TestClient

from lcomfine.app.main import app
from lcomfine.app.settings import get_settings
from lcomfine.db import conn

BY = "t3"


def client(login_id: str | None = None) -> TestClient:
    c = TestClient(app, raise_server_exceptions=False)
    if login_id:
        r = c.post("/login", data={"login_id": login_id, "password": get_settings().seed_password}, follow_redirects=False)
        assert r.status_code == 303, f"{login_id} 로그인 실패 {r.status_code} — 공통 시드와 .env 를 확인한다"
    return c


def one(sql: str, params=()) -> dict:
    row = conn.q1(sql, params)
    assert row is not None, sql
    return row


def count(sql: str, params=()) -> int:
    return one(sql, params)["n"]


class World:
    """접두 하나로 묶인 테스트 데이터. 만드는 함수는 전부 내부 키를 돌려준다."""

    def __init__(self, prefix: str):
        assert prefix.startswith("T3") and prefix.endswith("-"), prefix
        self.p = prefix
        cleanup(prefix)   # 앞선 실행이 중간에 죽어 남긴 것이 있으면 먼저 치운다

    # ── D1 ──
    def item(self, code: str, item_type: str = "제품") -> int:
        return one("""insert into item (item_code, item_name, item_type, unit, created_by)
                      values (%s, %s, %s, 'm', %s) returning item_id""",
                   (self.p + code, f"{item_type} {code} (예시)", item_type, BY))["item_id"]

    def customer(self, code: str = "C1") -> int:
        return one("insert into customer (customer_code, customer_name, created_by) values (%s, %s, %s) returning customer_id",
                   (self.p + code, f"고객 {code} (예시)", BY))["customer_id"]

    def defect_code(self, code: str) -> int:
        return one("insert into defect_code (defect_code, defect_name, created_by) values (%s, %s, %s) returning defect_code_id",
                   (self.p + code, f"불량 {code} (예시)", BY))["defect_code_id"]

    # ── D2 ──
    def job(self, no: str, item_id: int, customer_id: int, due: date | None = None, status: str = "등록") -> int:
        return one("""insert into job (job_no, item_id, customer_id, order_qty, qty_unit, due_date, status, created_by)
                      values (%s, %s, %s, 100, 'm', %s, %s, %s) returning job_id""",
                   (self.p + no, item_id, customer_id, due or date.today(), status, BY))["job_id"]

    # ── D3 ──
    def material_lot(self, no: str, item_id: int) -> int:
        return one("""insert into material_lot (lot_no, item_id, received_qty, qty_unit, received_by, insp_status, insp_at)
                      values (%s, %s, 100, 'm', %s, '합격', now()) returning material_lot_id""",
                   (self.p + no, item_id, BY))["material_lot_id"]

    # ── D5 ──
    def work(self, job_id: int, ended_at: datetime | None, output_qty=None, scraps: tuple = ()) -> int:
        status = "완료" if ended_at else "진행"
        wid = one("""insert into work_result (job_id, status, started_at, ended_at, output_qty, qty_unit, worker)
                     values (%s, %s, coalesce(%s::timestamptz, now()) - interval '1 hour', %s, %s, 'm', %s)
                     returning work_result_id""", (job_id, status, ended_at, ended_at, output_qty, BY))["work_result_id"]
        for qty in scraps:
            conn.x("insert into work_scrap (work_result_id, scrap_qty, qty_unit, created_by) values (%s, %s, 'm', %s)",
                   (wid, qty, BY))
        return wid

    # ── D6 ──
    def roll(self, no: str, job_id: int, process_type: str = "슬리팅") -> int:
        return one("insert into roll (roll_no, process_type, job_id, produced_by) values (%s, %s, %s, %s) returning roll_id",
                   (self.p + no, process_type, job_id, BY))["roll_id"]

    def edge(self, relation: str, *, lot: int | None = None, parent: int | None = None, child: int | None = None,
             ship: int | None = None) -> None:
        """계보 한 줄을 SQL 로 직접 넣는다(테스트 픽스처 — `tests/test_arch_genealogy.py` 와 같은 방식)."""
        conn.x("""insert into roll_genealogy (parent_material_lot_id, parent_roll_id, child_roll_id, child_shipment_id, relation, created_by)
                  values (%s, %s, %s, %s, %s, %s)""", (lot, parent, child, ship, relation, BY))

    # ── D7 ──
    def inspection(self, roll_id: int, job_id: int, result: str = "합격", delta_e=None, at: datetime | None = None,
                   defects: tuple = ()) -> int:
        """`defects` 는 (defect_code_id, 위치) 의 모음."""
        iid = one("""insert into inspection (roll_id, job_id, delta_e, result, inspected_at, inspected_by)
                     values (%s, %s, %s, %s, coalesce(%s::timestamptz, now()), %s) returning inspection_id""",
                  (roll_id, job_id, delta_e, result, at, BY))["inspection_id"]
        for defect_code_id, position in defects:
            conn.x("insert into inspection_defect (inspection_id, defect_code_id, position) values (%s, %s, %s)",
                   (iid, defect_code_id, position))
        return iid

    # ── D8 ──
    def shipment(self, no: str, job_id: int, customer_id: int, ship_date: date | None = None, status: str = "등록") -> int:
        approved = status == "승인"
        return one("""insert into shipment (shipment_no, job_id, customer_id, ship_date, status, registered_by,
                                            approved_at, approved_by)
                      values (%s, %s, %s, %s, %s, %s, case when %s then now() end, case when %s then %s end)
                      returning shipment_id""",
                   (self.p + no, job_id, customer_id, ship_date or date.today(), status, BY, approved, approved, BY))["shipment_id"]

    def approve_sql(self, shipment_id: int) -> None:
        """화면을 거치지 않고 출하를 `승인` 으로 만든다(다른 기능의 전제 조건을 차릴 때)."""
        conn.x("update shipment set status = '승인', approved_at = now(), approved_by = %s where shipment_id = %s",
               (BY, shipment_id))


def cleanup(prefix: str) -> None:
    """그 접두로 만든 행을 FK 순서대로 전부 지운다. 화면(API)이 만든 행도 그 접두의 Job·롤에 딸려 있으면 같이 지운다."""
    like = prefix + "%"
    with conn.tx() as cur:
        cur.execute("select job_id from job where job_no like %s", (like,))
        jobs = [r["job_id"] for r in cur.fetchall()]
        cur.execute("select roll_id from roll where roll_no like %s or job_id = any(%s)", (like, jobs))
        rolls = [r["roll_id"] for r in cur.fetchall()]
        cur.execute("select shipment_id from shipment where shipment_no like %s or job_id = any(%s)", (like, jobs))
        ships = [r["shipment_id"] for r in cur.fetchall()]
        cur.execute("select material_lot_id from material_lot where lot_no like %s", (like,))
        lots = [r["material_lot_id"] for r in cur.fetchall()]
        cur.execute("select work_result_id from work_result where job_id = any(%s)", (jobs,))
        works = [r["work_result_id"] for r in cur.fetchall()]
        cur.execute("""delete from roll_genealogy where parent_roll_id = any(%s) or child_roll_id = any(%s)
                          or child_shipment_id = any(%s) or parent_material_lot_id = any(%s)""", (rolls, rolls, ships, lots))
        cur.execute("delete from inspection where roll_id = any(%s) or job_id = any(%s)", (rolls, jobs))
        cur.execute("delete from shipment where shipment_id = any(%s)", (ships,))
        cur.execute("delete from roll where roll_id = any(%s)", (rolls,))
        cur.execute("delete from material_input where work_result_id = any(%s) or material_lot_id = any(%s)", (works, lots))
        cur.execute("delete from work_scrap where work_result_id = any(%s)", (works,))
        cur.execute("delete from work_stop where work_result_id = any(%s)", (works,))
        cur.execute("delete from work_result where work_result_id = any(%s)", (works,))
        cur.execute("delete from material_lot where material_lot_id = any(%s)", (lots,))
        cur.execute("delete from color_record where job_id = any(%s)", (jobs,))
        cur.execute("delete from job_lot where job_id = any(%s) or lot_no like %s", (jobs, like))
        cur.execute("delete from job where job_id = any(%s)", (jobs,))
        cur.execute("delete from plate_spec where plate_code like %s", (like,))
        cur.execute("delete from anilox where anilox_code like %s", (like,))
        cur.execute("delete from ink_formula where ink_code like %s", (like,))
        cur.execute("delete from equipment where equipment_code like %s", (like,))
        cur.execute("delete from process where process_code like %s", (like,))
        cur.execute("delete from defect_code where defect_code like %s", (like,))
        cur.execute("delete from customer where customer_code like %s", (like,))
        cur.execute("delete from item where item_code like %s", (like,))
        cur.execute("delete from sys_migration_log where run_by like %s", (like,))
        cur.execute("delete from sys_access_log where log_type = '변경' and target like %s", (f"%{prefix}%",))


def leftovers(prefix: str) -> dict[str, int]:
    """그 접두의 행이 남은 테이블 — 비어 있어야 한다."""
    like = prefix + "%"
    checks = {
        "item": "select count(*) as n from item where item_code like %s",
        "customer": "select count(*) as n from customer where customer_code like %s",
        "process": "select count(*) as n from process where process_code like %s",
        "equipment": "select count(*) as n from equipment where equipment_code like %s",
        "defect_code": "select count(*) as n from defect_code where defect_code like %s",
        "plate_spec": "select count(*) as n from plate_spec where plate_code like %s",
        "anilox": "select count(*) as n from anilox where anilox_code like %s",
        "ink_formula": "select count(*) as n from ink_formula where ink_code like %s",
        "job": "select count(*) as n from job where job_no like %s",
        "job_lot": "select count(*) as n from job_lot where lot_no like %s",
        "material_lot": "select count(*) as n from material_lot where lot_no like %s",
        "roll": "select count(*) as n from roll where roll_no like %s",
        "shipment": "select count(*) as n from shipment where shipment_no like %s",
        "sys_migration_log": "select count(*) as n from sys_migration_log where run_by like %s",
    }
    return {t: n for t, sql in checks.items() if (n := count(sql, (like,)))}


#: G-05 — P9·P10 화면이 건드리면 안 되는 D1~D8 의 23개 테이블
DATA_TABLES = ("item", "customer", "process", "equipment", "defect_code", "plate_spec", "anilox", "ink_formula",
               "ink_formula_component", "job", "job_lot", "material_lot", "color_record", "color_record_mix",
               "work_result", "work_stop", "work_scrap", "material_input", "roll", "roll_genealogy",
               "inspection", "inspection_defect", "shipment")


class SqlSpy:
    """요청 하나가 실행한 SQL 을 전부 적는다 — "이 화면은 아무 테이블에도 쓰지 않는다"(G-05)를 행 수가 아니라 SQL 로 판정한다.

    (같은 DB 를 여럿이 동시에 쓰므로 전후 행 수 비교는 남의 쓰기에 흔들린다.) `conn.q` · `conn.x` · `conn.tx` 를 감싼다.
    """

    def __init__(self, monkeypatch):
        self.reads: list[str] = []
        self.writes: list[str] = []
        self.transactions = 0
        real_q, real_x, real_tx = conn.q, conn.x, conn.tx

        def q(sql, params=None):
            self.reads.append(" ".join(sql.split()))
            return real_q(sql, params)

        def x(sql, params=None):
            self.writes.append(" ".join(sql.split()))
            return real_x(sql, params)

        def tx():
            self.transactions += 1
            return real_tx()

        monkeypatch.setattr(conn, "q", q)
        monkeypatch.setattr(conn, "x", x)
        monkeypatch.setattr(conn, "tx", tx)

    def assert_read_only(self) -> None:
        """쓰기는 공통 접근 로그(`sys_access_log`) 한 종류뿐이고, 읽기는 전부 select 다. 트랜잭션(쓰기 묶음)은 열지 않았다."""
        assert self.reads, "조회 SQL 이 하나도 없다 — 화면이 DB 를 읽지 않았다"
        assert self.transactions == 0, "쓰기 트랜잭션을 열었다"
        assert all(w.lower().startswith("insert into sys_access_log") for w in self.writes), self.writes
        bad = [r for r in self.reads if not r.lower().startswith(("select", "with"))
               or any(k in f" {r.lower()} " for k in (" insert ", " update ", " delete ", " into "))]
        assert not bad, bad
