"""개발2 테스트 공용 도구 — 로그인한 클라이언트 · 자기 데이터 한 벌(`World`) · 화면이 부르는 API 한 걸음씩 · 뒷정리. (테스트 함수는 없다)

- 다른 사람의 데이터에 기대지 않는다. 기준정보·Job 은 `World` 가 SQL 로 직접 만든다(업무 코드는 전부 `T2-<8자>-…`).
  기준정보(D1)·작업지시(D2)는 개발1 의 화면이 만드는 것이라 여기서는 **전제 데이터**로만 넣는다.
- 입고부터 슬리팅까지(D3~D6)는 **화면이 부르는 것과 같은 엔드포인트**로 만든다 — 아래 `receive` · `inspect` · `start` · …
- 끝나면 `World.cleanup()` 이 그 Job·품목에 매달린 것을 전부 지운다(계보 · 롤 · 실적 · 투입 · 조색 · 원재료 LOT · 변경 로그).
- 시드 계정(admin · prod · qc · field)은 **로그인에만** 쓴다.
"""
from __future__ import annotations

import re
import threading
import uuid

from fastapi.testclient import TestClient

from lcomfine.app import nav
from lcomfine.app.main import app
from lcomfine.app.settings import get_settings
from lcomfine.db import conn

TEST_BY = "t2-test"
HTML = {"accept": "text/html"}

_clients: dict[str, TestClient] = {}


def client(login_id: str | None = None) -> TestClient:
    """로그인한 클라이언트(역할마다 하나를 돌려쓴다). `None` 이면 미로그인."""
    if login_id is None:
        return TestClient(app, raise_server_exceptions=False)
    c = _clients.get(login_id)
    if c is None:
        c = TestClient(app, raise_server_exceptions=False)
        r = c.post("/login", data={"login_id": login_id, "password": get_settings().seed_password}, follow_redirects=False)
        assert r.status_code == 303, f"{login_id} 로그인 실패 {r.status_code} — 공통 시드와 .env 를 확인한다"
        _clients[login_id] = c
    return c


def pause_after(monkeypatch, module, name: str) -> tuple[threading.Event, threading.Event]:
    """동시 요청 테스트용 — `module.name` 의 **첫 호출**이 끝난 직후(= 그 함수가 잡은 잠금을 쥔 채)에 세워 둔다.

    돌려주는 것은 (들어왔다, 풀어라) 이벤트. 두 번째 호출부터는 그대로 지나간다. 호출자는 `finally` 에서 `풀어라.set()` 을 부른다.
    앱의 동작을 바꾸지 않는다 — 실제 함수를 그대로 부르고 멈추기만 한다(시간에 기대지 않고 겹치는 순간을 만든다)."""
    real = getattr(module, name)
    entered, release = threading.Event(), threading.Event()

    def paused(*args, **kwargs):
        out = real(*args, **kwargs)
        if not entered.is_set():
            entered.set()
            assert release.wait(30), f"{name} — 30초 동안 풀리지 않았다"
        return out

    monkeypatch.setattr(module, name, paused)
    return entered, release


def one(sql: str, params=()) -> dict | None:
    return conn.q1(sql, params)


def count(sql: str, params=()) -> int:
    return conn.q1(sql, params)["n"]


class World:
    """테스트 한 묶음의 전제 데이터 — 제품·원재료 품목, 고객, 설비, 불량코드, Job 1개(+ 생산 LOT 1개)."""

    def __init__(self) -> None:
        self.tag = f"T2-{uuid.uuid4().hex[:8].upper()}"
        t = self.tag
        with conn.tx() as cur:
            def ins(sql: str, params: tuple) -> int:
                cur.execute(sql, params)
                return next(iter(cur.fetchone().values()))

            self.item_code, self.raw_code = f"{t}-FG", f"{t}-RM"
            self.item_id = ins("""insert into item (item_code, item_name, item_type, unit, created_by)
                                  values (%s, %s, '제품', 'm', %s) returning item_id""",
                               (self.item_code, f"{t} 제품 (예시)", TEST_BY))
            self.raw_id = ins("""insert into item (item_code, item_name, item_type, unit, created_by)
                                 values (%s, %s, '원재료', 'm', %s) returning item_id""",
                              (self.raw_code, f"{t} 원재료 (예시)", TEST_BY))
            self.customer_id = ins("""insert into customer (customer_code, customer_name, created_by)
                                      values (%s, %s, %s) returning customer_id""", (f"{t}-CU", f"{t} 고객 (예시)", TEST_BY))
            self.eq_code = f"{t}-EQ"
            self.eq_id = ins("""insert into equipment (equipment_code, equipment_name, created_by)
                                values (%s, %s, %s) returning equipment_id""", (self.eq_code, f"{t} 설비 (예시)", TEST_BY))
            self.defect_code = f"{t}-DF"
            self.defect_id = ins("""insert into defect_code (defect_code, defect_name, created_by)
                                    values (%s, %s, %s) returning defect_code_id""",
                                 (self.defect_code, f"{t} 불량 (예시)", TEST_BY))
            self.ink_code = f"{t}-INK"
            self.ink_id = ins("""insert into ink_formula (ink_code, ink_name, created_by)
                                 values (%s, %s, %s) returning ink_formula_id""", (self.ink_code, f"{t} 잉크 (예시)", TEST_BY))
        self.job_id, self.job_no = self.new_job("J1")
        self.job_lot_no = f"{t}-L1"
        conn.x("insert into job_lot (job_id, lot_no, planned_roll_count, created_by) values (%s, %s, 2, %s)",
               (self.job_id, self.job_lot_no, TEST_BY))

    def new_job(self, suffix: str, status: str = "등록") -> tuple[int, str]:
        """전제 데이터 — Job 한 건을 SQL 로 넣는다(번호는 채번 형식과 겹치지 않는 `T2-…`)."""
        job_no = f"{self.tag}-{suffix}"
        row = conn.q1("""insert into job (job_no, item_id, customer_id, order_qty, qty_unit, due_date, status, created_by)
                         values (%s, %s, %s, 1000, 'm', current_date, %s, %s) returning job_id""",
                      (job_no, self.item_id, self.customer_id, status, TEST_BY))
        return row["job_id"], job_no

    def new_shipment(self, suffix: str = "S1", job_id: int | None = None, status: str = "등록") -> tuple[int, str]:
        """전제 데이터 — 출하 LOT 한 건을 SQL 로 넣는다(출하 화면은 개발3 소유)."""
        no = f"{self.tag}-{suffix}"
        approved = "now()" if status == "승인" else "null"
        row = conn.q1(f"""insert into shipment (shipment_no, job_id, customer_id, ship_date, status, registered_by, approved_at)
                          values (%s, %s, %s, current_date, %s, %s, {approved}) returning shipment_id""",
                      (no, job_id or self.job_id, self.customer_id, status, TEST_BY))
        return row["shipment_id"], no

    def good_lot(self, qty: str = "1000") -> str:
        """입고 → 입고검사 합격 (API). 원재료 LOT 번호."""
        lot_no = receive(self, qty=qty)
        inspect(lot_no, "합격")
        return lot_no

    def print_roll(self, lots: list[str], *, job_no: str | None = None, qty: str = "100") -> str:
        """작업 시작 → 투입 스캔(lots) → 작업 종료 (API). 인쇄 롤 번호."""
        work_id = start(self, job_no=job_no)
        for lot_no in lots:
            scan_input(work_id, lot_no)
        return finish(work_id, qty=qty)

    def roll_id(self, roll_no: str) -> int:
        return conn.q1("select roll_id from roll where roll_no = %s", (roll_no,))["roll_id"]

    def lot_id(self, lot_no: str) -> int:
        return conn.q1("select material_lot_id from material_lot where lot_no = %s", (lot_no,))["material_lot_id"]

    def genealogy(self) -> list[dict]:
        """이 World 의 계보 행 전부 (부모·자식 번호와 관계)."""
        return conn.q(
            """select g.genealogy_id, g.relation, g.qty,
                      coalesce(m.lot_no, pr.roll_no) as parent_no, coalesce(cr.roll_no, s.shipment_no) as child_no
                 from roll_genealogy g
                 left join material_lot m on m.material_lot_id = g.parent_material_lot_id
                 left join roll pr on pr.roll_id = g.parent_roll_id
                 left join roll cr on cr.roll_id = g.child_roll_id
                 left join shipment s on s.shipment_id = g.child_shipment_id
                where m.item_id = %(raw)s
                   or pr.job_id in (select job_id from job where item_id = %(item)s)
                   or cr.job_id in (select job_id from job where item_id = %(item)s)
                   or s.job_id in (select job_id from job where item_id = %(item)s)
                order by g.genealogy_id""", {"raw": self.raw_id, "item": self.item_id})

    def cleanup(self) -> None:
        with conn.tx() as cur:
            def ids(sql: str, params: tuple) -> list:
                cur.execute(sql, params)
                return [next(iter(r.values())) for r in cur.fetchall()]

            jobs = ids("select job_id from job where item_id = %s", (self.item_id,))
            lots = ids("select material_lot_id from material_lot where item_id = %s", (self.raw_id,))
            rolls = ids("select roll_id from roll where job_id = any(%s)", (jobs,))
            ships = ids("select shipment_id from shipment where job_id = any(%s)", (jobs,))
            works = ids("select work_result_id from work_result where job_id = any(%s)", (jobs,))
            targets = (
                ids("select 'material_lot:' || lot_no from material_lot where material_lot_id = any(%s)", (lots,))
                + ids("select 'roll:' || roll_no from roll where roll_id = any(%s)", (rolls,))
                + [f"work_result:{w}" for w in works]
                + ids("select 'work_stop:' || work_stop_id from work_stop where work_result_id = any(%s)", (works,))
                + ids("select 'work_scrap:' || work_scrap_id from work_scrap where work_result_id = any(%s)", (works,))
                + ids("select 'material_input:' || material_input_id from material_input where work_result_id = any(%s)", (works,)))
            ship_like = ids("select 'shipment:' || shipment_no || '%%' from shipment where shipment_id = any(%s)", (ships,))
            cur.execute("""delete from sys_access_log
                            where log_type = '변경' and (target = any(%s) or target like %s or target like any(%s))""",
                        (targets, f"color_record:{self.tag}%", ship_like))
            cur.execute("""delete from roll_genealogy
                            where child_roll_id = any(%s) or parent_roll_id = any(%s)
                               or parent_material_lot_id = any(%s) or child_shipment_id = any(%s)""",
                        (rolls, rolls, lots, ships))
            cur.execute("delete from inspection_defect where inspection_id in (select inspection_id from inspection where roll_id = any(%s))", (rolls,))
            cur.execute("delete from inspection where roll_id = any(%s)", (rolls,))
            cur.execute("delete from shipment where shipment_id = any(%s)", (ships,))
            cur.execute("delete from roll where roll_id = any(%s)", (rolls,))
            cur.execute("delete from material_input where work_result_id = any(%s) or material_lot_id = any(%s)", (works, lots))
            cur.execute("delete from work_stop where work_result_id = any(%s)", (works,))
            cur.execute("delete from work_scrap where work_result_id = any(%s)", (works,))
            cur.execute("delete from work_result where work_result_id = any(%s)", (works,))
            cur.execute("delete from color_record_mix where color_record_id in (select color_record_id from color_record where job_id = any(%s))", (jobs,))
            cur.execute("delete from color_record where job_id = any(%s)", (jobs,))
            cur.execute("delete from material_lot where material_lot_id = any(%s)", (lots,))
            cur.execute("delete from job_lot where job_id = any(%s)", (jobs,))
            cur.execute("delete from job where job_id = any(%s)", (jobs,))
            cur.execute("delete from equipment where equipment_code like %s", (f"{self.tag}%",))
            cur.execute("delete from defect_code where defect_code like %s", (f"{self.tag}%",))
            cur.execute("delete from ink_formula where ink_code like %s", (f"{self.tag}%",))
            cur.execute("delete from customer where customer_code like %s", (f"{self.tag}%",))
            cur.execute("delete from item where item_code like %s", (f"{self.tag}%",))

    def leftovers(self) -> int:
        """뒷정리 뒤에 남은 행 수 (0 이어야 한다)."""
        like = f"{self.tag}%"
        return (count("select count(*) as n from item where item_code like %s", (like,))
                + count("select count(*) as n from job where job_no like %s", (like,))
                + count("select count(*) as n from shipment where shipment_no like %s", (like,))
                + count("select count(*) as n from material_lot where item_id = %s", (self.raw_id,))
                + count("select count(*) as n from roll where job_id = %s", (self.job_id,)))


# ── 화면이 부르는 API 한 걸음씩 (JSON 으로 판정 — api-contract.md §2) ───
def ok(resp, what: str = "") -> dict:
    assert resp.status_code == 200, f"{what} → {resp.status_code} {resp.text[:300]}"
    body = resp.json()
    assert body["ok"] is True
    return body


def receive(w: World, *, qty: str = "1000", who: str = "field", **extra) -> str:
    """F-MAT-01 입고 등록 → 원재료 LOT 번호."""
    data = {"item_code": w.raw_code, "supplier_name": "공급처 (예시)", "supplier_lot_no": f"{w.tag}-SL",
            "received_qty": qty, **extra}
    return ok(client(who).post(nav.path_of("MAT-01"), data=data), "입고 등록")["lot_no"]


def inspect(lot_no: str, result: str = "합격", who: str = "qc"):
    """F-MAT-03 입고검사 결과 등록 (품질만)."""
    return ok(client(who).post(nav.path_of("MAT-02"), data={"lot_no": lot_no, "result": result}), "입고검사")


def start(w: World, *, job_no: str | None = None, who: str = "field", **extra) -> int:
    """F-POP-01 작업 시작 → work_id."""
    data = {"job_no": job_no or w.job_no, "equipment_code": w.eq_code, **extra}
    return ok(client(who).post(nav.path_of("POP-01") + "/start", data=data), "작업 시작")["work_id"]


def scan_input(work_id: int, lot_no: str, *, qty: str | None = "10", who: str = "field"):
    """F-MAT-07 자재 투입 스캔."""
    data = {"work_id": str(work_id), "lot_no": lot_no}
    if qty is not None:
        data["input_qty"] = qty
    return ok(client(who).post(nav.path_of("MAT-04"), data=data), "자재 투입 스캔")


def finish(work_id: int, *, qty: str = "100", who: str = "field", **extra) -> str:
    """F-POP-02 작업 종료 → 인쇄 롤 번호."""
    data = {"output_qty": qty, "length_m": "500", "width_mm": "1000", **extra}
    return ok(client(who).post(f"{nav.path_of('POP-01')}/{work_id}/finish", data=data), "작업 종료")["roll_no"]


def finishing(roll_no: str, *, who: str = "field", **extra) -> str:
    """F-RLL-01 후가공 실적 등록(부모 1개) → 후가공 롤 번호."""
    return ok(client(who).post(nav.path_of("RLL-01"), data={"roll_no": roll_no, **extra}), "후가공")["roll_no"]


def splice(roll_nos: list[str], *, who: str = "field", **extra) -> str:
    """F-RLL-02 splice 등록(부모 N개) → 후가공 롤 번호."""
    return ok(client(who).post(nav.path_of("RLL-01") + "/splice", data={"roll_no": roll_nos, **extra}), "splice")["roll_no"]


def slit(roll_no: str, n: int, *, who: str = "field", **extra) -> list[str]:
    """F-RLL-04 슬리팅 분할 등록 → 슬리팅 롤 번호 N개."""
    return ok(client(who).post(nav.path_of("RLL-02"), data={"roll_no": roll_no, "count": str(n), **extra}), "슬리팅")["rolls"]


def err(resp, status: int = 422) -> dict:
    """오류 계약(api-contract.md §1) — 상태코드와 `code` 를 함께 본다."""
    assert resp.status_code == status, f"기대 {status}, 실제 {resp.status_code} {resp.text[:300]}"
    body = resp.json()
    assert body["code"] == {422: "validation_error", 403: "forbidden", 404: "not_found", 401: "unauthorized"}[status]
    return body


def change_logs(function_id: str, target: str) -> int:
    """그 기능·대상의 `변경` 로그 수 (G-18)."""
    return count("select count(*) as n from sys_access_log where log_type = '변경' and function_id = %s and target = %s",
                 (function_id, target))


# ── 바코드 디코더 (라벨의 SVG → 번호. test_dev2_printing.py 의 것과 같은 방식) ──
def decode_barcode(html: str) -> str:
    """HTML 안의 첫 Code 128 SVG 를 모듈로 되읽어 체크섬을 검증하고 글자로 푼다."""
    from lcomfine.app import printing

    svg = html[html.index("<svg"): html.index("</svg>") + 6]
    m = int(re.search(r'data-module="(\d+)"', svg).group(1))
    total = int(re.search(r'viewBox="0 0 (\d+) ', svg).group(1)) // m
    cells = ["0"] * total
    bars = re.search(r'<g class="bars"[^>]*>(.*?)</g>', svg, re.S).group(1)
    for x, width in re.findall(r'<rect x="(\d+)" y="0" width="(\d+)"', bars):
        for k in range(int(x) // m, (int(x) + int(width)) // m):
            cells[k] = "1"
    modules = "".join(cells).strip("0")

    def pattern(widths: str) -> str:
        return "".join(("1" if k % 2 == 0 else "0") * int(c) for k, c in enumerate(widths))

    by_pattern = {pattern(p): v for v, p in enumerate(printing.CODE128_WIDTHS)}
    stop = pattern(printing.CODE128_STOP_WIDTHS)
    assert modules.endswith(stop)
    body = modules[: -len(stop)]
    values = [by_pattern[body[i:i + 11]] for i in range(0, len(body), 11)]
    start_v, data, check = values[0], values[1:-1], values[-1]
    assert check == (start_v + sum(pos * v for pos, v in enumerate(data, start=1))) % 103, "체크섬 불일치"
    code_set, out = ("B" if start_v == 104 else "C"), []
    for v in data:
        if code_set == "C":
            if v == 100:
                code_set = "B"
            else:
                out.append(f"{v:02d}")
        elif v == 99:
            code_set = "C"
        else:
            out.append(chr(v + 32))
    return "".join(out)
