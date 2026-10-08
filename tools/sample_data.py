#!/usr/bin/env python
"""(예시) 샘플 데이터 — 업무 테이블(D1~D8 23개)에 **100행 안팎**씩 + (예시) 계정 100 + 수주 100(설계도 밖 확장 · D-418). `make sample` / `make sample-clean`.

    uv run python tools/sample_data.py            # 넣는다 (이미 들어 있으면 건너뛴다 — 두 번 돌려도 행 수가 같다. 수주 샘플만 없으면 수주만 더한다)
    uv run python tools/sample_data.py --clean    # 샘플만 전부 지운다 (공통·개발 시드 행 · 테스트가 만든 행은 건드리지 않는다)
    uv run python tools/sample_data.py --counts   # 테이블별 행 수만 찍는다

지키는 것
  · **앱 모듈을 거친다.** 번호는 `numbering.next(kind, cur=, at=)` 만(과거 시각을 주면 그날 번호가 나온다). 인쇄 롤·후가공·splice·슬리팅·
    출하 롤 스캔과 `roll_genealogy` 는 `lineage.*` 만. 원시 INSERT 는 기준정보·작업지시·원재료 LOT·조색·실적·정지·폐기·투입·검사·출하 행에만.
    `lineage` 가 만든 롤·계보 행은 **일시만** 과거로 되돌린다(`produced_at`·`created_at` UPDATE — 부모·자식·관계는 손대지 않는다).
  · 실제 업무 순서대로: 기준정보 → Job·생산 LOT → 입고·입고검사 → 조색 → 실적(시작·투입·정지·폐기·종료 → 인쇄 롤) → 후가공·splice·슬리팅 →
    검사(+불량) → 출하 등록·롤 스캔·승인(COA) → Job 마감. 규칙(D-13 합격 LOT 만 투입 · D-17 불합격 롤 출하 금지 · D-208 등록 Job 만 후가공 ·
    취소 Job 은 실적·롤 없음 · 완료 Job 은 열린 실적 없음)을 어기지 않는다. 트리거·CHECK·뷰(`v_roll_state` `v_material_lot_stock`)와 모순되는 행을 만들지 않는다.
  · 이름은 전부 `(예시)`, 업무 코드는 `SMP-…`, 계정은 `smp_…` — 등록자·작업자·검사자 칸이 전부 `smp_` 계정이라 `--clean` 이 그것으로 찾아 지운다.
    고객명·품목명·규격값은 받은 적이 없으므로 `품목 001 (예시)` 꼴이고 기준정보의 규격 숫자(도수·선수·셀 용적·기준 색상값)는 비운다.
    실적 수치(수량·길이·ΔE·색상값)는 자리만 채운 예시 값이다.
  · 날짜는 최근 90일에 고르게(집계·현황판·납기 준수율이 보이도록). 난수는 고정 시드. 전체가 **한 트랜잭션** — 중간에 실패하면 아무것도 남지 않는다.
  · 계정 비밀번호는 `LCOMFINE_SEED_PASSWORD` 그대로(코드·문서에 값을 적지 않는다). sys_role · sys_permission · sys_number_rule 은 건드리지 않는다.
    접근 로그는 쓰지 않는다 — 화면을 거치지 않았으므로 쌓일 것이 없다.
"""

from __future__ import annotations

import random
import sys
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lcomfine.app import auth, lineage, numbering  # noqa: E402
from lcomfine.app.settings import get_settings  # noqa: E402
from lcomfine.app.util.screen import example  # noqa: E402
from lcomfine.db import conn  # noqa: E402

CODE = "SMP-"          # 업무 코드 접두
USER = "smp_"          # 계정 접두 (등록자·작업자·검사자 칸)
SEED = 20261003        # 고정 난수 시드
DAYS = 90              # 최근 90일

#: 업무 테이블 23 (D1~D8) + 계정 — 행 수 표의 순서
TABLES = ("item", "customer", "process", "equipment", "defect_code", "plate_spec", "anilox", "ink_formula", "ink_formula_component",
          "job", "job_lot", "material_lot", "color_record", "color_record_mix",
          "work_result", "work_stop", "work_scrap", "material_input", "roll", "roll_genealogy",
          "inspection", "inspection_defect", "shipment", "sales_order", "sys_user")

TZ = datetime.now().astimezone().tzinfo
TODAY = date.today()
NOW = datetime.now(TZ)


def at(day: date, hour: int = 9, minute: int = 0) -> datetime:
    """그날의 시각(세션 시간대). 분이 59 를 넘으면 그만큼 뒤로 민다."""
    return datetime.combine(day, time(hour, 0), tzinfo=TZ) + timedelta(minutes=minute)


def not_future(t: datetime) -> datetime:
    """지금을 넘지 않게 — 오늘 자 행이 미래 시각이 되지 않는다."""
    return min(t, NOW - timedelta(minutes=5))


def code(kind: str, n: int) -> str:
    return f"{CODE}{kind}-{n:03d}"


def counts() -> dict[str, int]:
    return {t: conn.q1(f"select count(*) as n from {t}")["n"] for t in TABLES}


def print_counts(title: str, c: dict[str, int], base: dict[str, int] | None = None) -> None:
    print(title)
    for t in TABLES:
        extra = f"  ({c[t] - base[t]:+d})" if base is not None else ""
        print(f"  {t:<24}{c[t]:>7}{extra}")


def orders_in() -> bool:
    return conn.q1("select 1 as x from sales_order where created_by like %s limit 1", (USER.replace("_", r"\_") + "%",)) is not None


def already_in() -> bool:
    return conn.q1("select 1 as x from item where item_code like %s limit 1", (CODE + "%",)) is not None \
        or conn.q1("select 1 as x from sys_user where login_id like %s limit 1", (USER.replace("_", r"\_") + "%",)) is not None


# ══════════════════════════════════════════════════════════════════════
# 넣기
# ══════════════════════════════════════════════════════════════════════
class Sample:
    def __init__(self, cur) -> None:
        self.cur = cur
        self.rng = random.Random(SEED)
        self.n: dict[str, int] = defaultdict(int)     # 이 실행이 넣은 행 수
        self.users: dict[str, list[str]] = defaultdict(list)   # 역할 → 정상 계정 login_id

    # ── 공용 ──
    def x(self, table: str, sql: str, params=()) -> dict | None:
        """INSERT 한 문장 — 넣은 행 수를 센다. `returning` 이 있으면 그 행."""
        self.cur.execute(sql, params)
        self.n[table] += self.cur.rowcount
        return self.cur.fetchone() if self.cur.description else None

    def u(self, sql: str, params=()) -> None:
        """UPDATE 한 문장 — 세지 않는다."""
        self.cur.execute(sql, params)

    def who(self, role: str) -> str:
        return self.rng.choice(self.users[role])

    def day(self, offset_from_today: int) -> date:
        return TODAY - timedelta(days=offset_from_today)

    # ── 0. 계정 100 (ADMIN 10 · PROD 30 · QC 20 · FIELD 40) ──
    def users_(self) -> None:
        password = get_settings().seed_password
        if not password:
            raise SystemExit("LCOMFINE_SEED_PASSWORD 미설정 — (예시) 계정을 만들 수 없다 (G-19). `.env` 를 확인한다")
        # 같은 비밀번호라도 계정마다 솔트가 달라야 한다(G-19 — 해시를 복사하지 않는다). PBKDF2 100회라 몇 초 걸린다
        plan = [("ADMIN", 10), ("PROD", 30), ("QC", 20), ("FIELD", 40)]
        statuses = ["정상"] * 92 + ["잠금"] * 5 + ["중지"] * 3
        self.rng.shuffle(statuses)
        i = 0
        creator = f"{USER}admin_01"
        for role, cnt in plan:
            for k in range(1, cnt + 1):
                login = f"{USER}{role.lower()}_{k:02d}"
                status = "정상" if (role == "ADMIN" and k == 1) else statuses[i]     # 첫 관리자는 늘 정상 (등록자)
                i += 1
                created = at(self.day(DAYS + 5 - (i * 2) % 20), 10, 0)
                self.x("sys_user", """insert into sys_user (login_id, user_name, password_hash, role_code, status, created_at, created_by)
                                      values (%s, %s, %s, %s, %s, %s, %s)""",
                       (login, example(f"사용자 {i:03d}"), auth.hash_password(password), role, status, created, creator))
                if status == "정상":
                    self.users[role].append(login)

    # ── 1. 기준정보 (D1) ──
    def masters(self) -> None:
        admin, t0 = self.users["ADMIN"][0], at(self.day(DAYS + 3), 9, 0)
        self.items_fg, self.items_rm = [], []                   # (item_id, unit)
        for i in range(1, 61):
            r = self.x("item", """insert into item (item_code, item_name, item_type, unit, created_at, created_by)
                                  values (%s, %s, '제품', 'm', %s, %s) returning item_id""",
                       (code("FG", i), example(f"품목 {i:03d}"), t0, admin))
            self.items_fg.append(r["item_id"])
        for i in range(1, 41):
            unit = "kg" if i > 30 else "m"
            r = self.x("item", """insert into item (item_code, item_name, item_type, unit, created_at, created_by)
                                  values (%s, %s, '원재료', %s, %s, %s) returning item_id""",
                       (code("RM", i), example(f"원재료 {i:03d}"), unit, t0, admin))
            self.items_rm.append((r["item_id"], unit))
        self.customers = [self.x("customer", """insert into customer (customer_code, customer_name, note, created_at, created_by)
                                                values (%s, %s, %s, %s, %s) returning customer_id""",
                                 (code("CU", i), example(f"고객 {i:03d}"), example("샘플 고객"), t0, admin))["customer_id"]
                          for i in range(1, 101)]
        # 공정 100 — 인쇄 30 · 후가공 30 · 슬리팅 20 · 기타 20
        self.process: dict[str, list[int]] = defaultdict(list)
        ptypes = ["인쇄"] * 30 + ["후가공"] * 30 + ["슬리팅"] * 20 + ["기타"] * 20
        for i, ptype in enumerate(ptypes, start=1):
            r = self.x("process", """insert into process (process_code, process_name, process_type, sort_no, created_at, created_by)
                                     values (%s, %s, %s, %s, %s, %s) returning process_id""",
                       (code("PR", i), example(f"공정 {i:03d}"), ptype, i * 10, t0, admin))
            self.process[ptype].append(r["process_id"])
        # 설비 100 — 인쇄 40 · 후가공 30 · 슬리팅 30 (공정에 고르게 붙인다)
        self.equip: dict[str, list[int]] = defaultdict(list)
        etypes = ["인쇄"] * 40 + ["후가공"] * 30 + ["슬리팅"] * 30
        for i, etype in enumerate(etypes, start=1):
            procs = self.process[etype]
            r = self.x("equipment", """insert into equipment (equipment_code, equipment_name, process_id, note, created_at, created_by)
                                       values (%s, %s, %s, %s, %s, %s) returning equipment_id""",
                       (code("EQ", i), example(f"설비 {i:03d}"), procs[(i - 1) % len(procs)], example("샘플 설비"), t0, admin))
            self.equip[etype].append(r["equipment_id"])
        self.defects = []
        groups = ["인쇄"] * 40 + ["후가공"] * 30 + ["슬리팅"] * 30
        for i, g in enumerate(groups, start=1):
            r = self.x("defect_code", """insert into defect_code (defect_code, defect_name, defect_group, created_at, created_by)
                                         values (%s, %s, %s, %s, %s) returning defect_code_id""",
                       (code("DF", i), example(f"불량 {i:03d}"), g, t0, admin))
            self.defects.append(r["defect_code_id"])
        # 인쇄 기준 — 판사양 100 · 아니록스 100 · 잉크조성 100 (+ 조성 행). 규격 숫자는 비운다(받은 적 없음)
        prod = self.users["PROD"][0]
        self.plates = [self.x("plate_spec", """insert into plate_spec (plate_code, plate_name, item_id, spec_note, created_at, created_by)
                                               values (%s, %s, %s, %s, %s, %s) returning plate_spec_id""",
                              (code("PL", i), example(f"판 {i:03d}"), self.items_fg[(i - 1) % 60], example("사양 메모"), t0, prod))["plate_spec_id"]
                       for i in range(1, 101)]
        self.anilox = [self.x("anilox", """insert into anilox (anilox_code, anilox_name, note, created_at, created_by)
                                           values (%s, %s, %s, %s, %s) returning anilox_id""",
                              (code("AN", i), example(f"아니록스 {i:03d}"), example("샘플 아니록스"), t0, prod))["anilox_id"]
                       for i in range(1, 101)]
        self.inks = []
        for i in range(1, 101):
            r = self.x("ink_formula", """insert into ink_formula (ink_code, ink_name, color_name, note, created_at, created_by)
                                         values (%s, %s, %s, %s, %s, %s) returning ink_formula_id""",
                       (code("INK", i), example(f"잉크 {i:03d}"), example(f"색 {i:03d}"), example("샘플 잉크조성"), t0, prod))
            self.inks.append(r["ink_formula_id"])
            comps = [("성분 1", "100")] if i % 2 else [("성분 1", "60"), ("성분 2", "40")]
            for seq, (name, pct) in enumerate(comps, start=1):
                self.x("ink_formula_component", """insert into ink_formula_component (ink_formula_id, seq_no, component_name, ratio_pct)
                                                   values (%s, %s, %s, %s)""", (r["ink_formula_id"], seq, example(name), pct))

    # ── 2b. 수주 (EXT · D-418) — 100건: 지시 80(샘플 Job 을 가리킨다) · 미지시 12 · 취소 8. 번호는 numbering 만 ──
    def sales_orders(self) -> None:
        """샘플 Job 을 DB 에서 읽어 수주를 만든다 — 새로 넣는 실행에서는 같은 트랜잭션의 Job, 수주만 더하는 실행에서는 이미 들어 있는 Job.
        규칙(라우터 `sal` 과 같다): 수주의 고객·품목 = 그 Job 의 고객·품목, 납기는 수주일보다 앞서지 않는다, 취소된 수주에는 Job 이 없다."""
        rng = random.Random(SEED + 1)
        u = USER.replace("_", r"\_") + "%"
        if not self.users["PROD"]:                                       # 수주만 더하는 실행 — 등록자 계정을 DB 에서
            self.cur.execute("select login_id from sys_user where login_id like %s and status = '정상' order by login_id",
                             (USER.replace("_", r"\_") + r"prod\_%",))
            self.users["PROD"] = [r["login_id"] for r in self.cur.fetchall()]
            if not self.users["PROD"]:
                raise SystemExit("샘플 계정(smp_prod_*)이 없다 — 샘플 데이터를 먼저 넣는다")
        self.cur.execute("""select job_id, item_id, customer_id, order_qty, qty_unit, due_date, created_at, status
                              from job where created_by like %s and sales_order_id is null order by job_id""", (u,))
        jobs = self.cur.fetchall()
        linked = [j for j in jobs if j["status"] != "취소"][:80]
        if len(linked) < 80:
            raise SystemExit(f"수주를 붙일 샘플 Job 이 모자란다 — 취소 아닌 Job {len(linked)} (80 필요)")
        n = 0
        for j in linked:                                                 # 지시 80 — Job 보다 1~5일 앞서 받은 수주
            n += 1
            created = not_future(j["created_at"] - timedelta(days=rng.randint(1, 5), hours=rng.randint(0, 6)))
            order_date = created.date()
            qty = j["order_qty"] + Decimal(rng.choice((0, 0, 500, 1000)))   # 지시 수량과 같거나 조금 큰 수주 수량
            self._order(n, created, order_date, max(j["due_date"], order_date), j["customer_id"], j["item_id"], qty, j["qty_unit"], "등록",
                        by=rng.choice(self.users["PROD"]), job_id=j["job_id"])
        pool = [j for j in jobs if j["status"] != "취소"]
        for k in range(20):                                              # 미지시 12 · 취소 8 — 최근 12일에 받은 수주, Job 없음
            n += 1
            j = rng.choice(pool)
            created = not_future(at(self.day(rng.randint(1, 12)), 9, rng.randrange(0, 59)))
            order_date = created.date()
            status = "취소" if k >= 12 else "등록"
            self._order(n, created, order_date, order_date + timedelta(days=rng.randint(7, 30)), j["customer_id"], j["item_id"],
                        Decimal(rng.randrange(1000, 20001, 500)), j["qty_unit"], status, by=rng.choice(self.users["PROD"]))

    def _order(self, n: int, created: datetime, order_date: date, due: date, customer_id: int, item_id: int, qty: Decimal, unit: str,
               status: str, *, by: str, job_id: int | None = None) -> None:
        """수주 한 행. 등록자는 수주 단계의 난수(`rng`)로 고른다 — 본류 난수(`self.rng`)를 건드리지 않아 다른 표의 샘플은 전과 같다."""
        order_no = numbering.next(numbering.SALES_ORDER, cur=self.cur, at=created)
        cancelled = status == "취소"
        r = self.x("sales_order", """insert into sales_order (order_no, customer_id, item_id, order_qty, qty_unit, order_date, due_date, customer_po,
                                                              status, note, created_at, created_by, updated_at, updated_by)
                                     values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) returning sales_order_id""",
                   (order_no, customer_id, item_id, qty, unit, order_date, due, f"{CODE}PO-{n:03d}", status,
                    example("샘플 수주" + (" — 취소" if cancelled else "")), created, by,
                    created + timedelta(hours=3) if cancelled else None, by if cancelled else None))
        if job_id is not None:
            self.u("update job set sales_order_id = %s where job_id = %s", (r["sales_order_id"], job_id))

    # ── 2. 작업지시 (D2) — Job 100 (등록 · 완료 · 취소 섞임) · 생산 LOT 100 ──
    def jobs(self) -> None:
        rng = self.rng
        self.job: list[dict] = []
        cancelled = set(rng.sample(range(100), 10))
        for i in range(100):
            base = self.day(DAYS - 1 - (i * (DAYS - 2)) // 99)          # 오늘-89 … 오늘-1 에 고르게
            created = at(base, 8, rng.randrange(0, 50))
            due = base + timedelta(days=rng.randint(10, 25))
            fg = self.items_fg[i % 60]
            by = self.who("PROD")
            job_no = numbering.next(numbering.JOB, cur=self.cur, at=created)
            status = "취소" if i in cancelled else "등록"
            r = self.x("job", """insert into job (job_no, item_id, customer_id, plate_spec_id, anilox_id, ink_formula_id, equipment_id,
                                                  order_qty, qty_unit, due_date, status, note, created_at, created_by, updated_at, updated_by)
                                 values (%s, %s, %s, %s, %s, %s, %s, %s, 'm', %s, %s, %s, %s, %s, %s, %s) returning job_id""",
                       (job_no, fg, self.customers[(i * 7) % 100], self.plates[i % 100], self.anilox[(i * 3) % 100], self.inks[i % 100],
                        self.equip["인쇄"][i % 40], Decimal(rng.randrange(1000, 20001, 500)), due, status,
                        example("샘플 작업지시" + (" — 취소" if status == "취소" else "")), created,
                        by, created + timedelta(hours=2) if status == "취소" else None, by if status == "취소" else None))
            self.job.append({"i": i, "job_id": r["job_id"], "job_no": job_no, "base": base, "created": created, "due": due,
                             "status": status, "item_id": fg, "customer_id": self.customers[(i * 7) % 100],
                             "equipment_id": self.equip["인쇄"][i % 40], "ink": self.inks[i % 100], "lots": [], "works": []})
        # 납기가 오늘인 Job 3개 (현황판의 납기 칸)
        for j in [j for j in self.job if j["status"] == "등록"][-25:-22]:
            j["due"] = TODAY
            self.u("update job set due_date = %s where job_id = %s", (TODAY, j["job_id"]))
        active = [j for j in self.job if j["status"] == "등록"]
        self.double = active[:-20][::7][:10]                              # 고르게 흩은 10개 Job 은 생산 LOT 2 · 실적 2 (splice 후보 — 최근 20개는 뺀다)
        for j in active:
            self._lot(j)
        for j in self.double:
            self._lot(j)

    def _lot(self, j: dict) -> None:
        t = j["created"] + timedelta(hours=1, minutes=len(j["lots"]) * 15)
        lot_no = numbering.next(numbering.JOB_LOT, cur=self.cur, at=t)
        r = self.x("job_lot", """insert into job_lot (job_id, lot_no, planned_roll_count, planned_length_m, note, created_at, created_by)
                                 values (%s, %s, %s, %s, %s, %s, %s) returning job_lot_id""",
                   (j["job_id"], lot_no, self.rng.randint(1, 3), Decimal(self.rng.randrange(500, 3001, 100)), example("샘플 생산 LOT"), t, self.who("PROD")))
        j["lots"].append(r["job_lot_id"])

    # ── 3. 원재료 LOT (D3) — 입고 100 · 입고검사 합격 80 · 대기 10 · 불합격 10 ──
    def material_lots(self) -> None:
        rng = self.rng
        self.mlots: list[dict] = []
        results = ["합격"] * 68 + ["불합격"] * 10                    # 13~90번 LOT 78개 — 앞 12개 합격과 합쳐 합격 80 · 불합격 10 · 대기 10
        rng.shuffle(results)
        for i in range(1, 101):
            received = at(self.day(DAYS + 6 - (i * (DAYS + 6)) // 100), 10, rng.randrange(0, 60))   # 오늘-96 … 오늘 에 고르게
            received = not_future(received)
            if i <= 12:
                result = "합격"                                        # 맨 앞 LOT 은 합격 — 첫 작업에 투입할 것이 있어야 한다
            elif i > 90:
                result = "대기"                                        # 최근 입고는 검사 대기
            else:
                result = results[i - 13]
            item_id, unit = self.items_rm[(i - 1) % 40]
            qty = Decimal(rng.randrange(2000, 5001, 100)) if unit == "m" else Decimal(rng.randrange(50, 301, 10))
            insp_at = not_future(received + timedelta(hours=rng.randint(1, 36))) if result != "대기" else None
            by = self.who(rng.choice(["PROD", "FIELD"]))
            lot_no = numbering.next(numbering.MAT_LOT, cur=self.cur, at=received)
            r = self.x("material_lot", """insert into material_lot (lot_no, item_id, supplier_name, supplier_lot_no, received_qty, qty_unit,
                                                                    received_at, received_by, insp_status, insp_at, insp_by, insp_note, note, created_at)
                                          values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) returning material_lot_id""",
                       (lot_no, item_id, example(f"공급처 {(i - 1) % 12 + 1:02d}"), f"{CODE}SL-{i:03d}", qty, unit, received, by, result,
                        insp_at, self.who("QC") if insp_at else None, example(f"입고검사 {result}") if insp_at else None,
                        example("샘플 원재료 LOT"), received))
            self.mlots.append({"id": r["material_lot_id"], "lot_no": lot_no, "unit": unit, "status": result,
                               "insp_at": insp_at, "remaining": qty})

    def pick_lots(self, when: datetime, n: int) -> list[dict]:
        """그 시각에 합격이고 잔량이 있는 LOT 중에서 n개 — 뷰 v_material_lot_stock 의 잔량이 음수가 되지 않는다."""
        pool = [m for m in self.mlots if m["status"] == "합격" and m["insp_at"] <= when and m["remaining"] >= 100]
        if len(pool) < n:
            raise RuntimeError(f"{when:%Y-%m-%d} 에 투입할 합격 LOT 이 모자란다 ({len(pool)} < {n}) — 입고 일정을 앞당긴다")
        return self.rng.sample(pool, n)

    # ── 4. 조색 기록 (D4) — 100 (+ 배합비 행 100) ──
    def colors(self) -> None:
        rng = self.rng
        active = [j for j in self.job if j["status"] == "등록"]
        chosen = rng.sample(active, 50)
        k = 0
        for idx, j in enumerate(chosen):
            specs = [("색 1", 1), ("색 1", 2)] if idx < 10 else [("색 1", 1), ("색 2", 1)]      # 10개 Job 은 재조색(2차)
            for color, seq in specs:
                k += 1
                t = j["created"] + timedelta(hours=1 + seq, minutes=rng.randrange(0, 60))
                lab = (Decimal(rng.randrange(4000, 8000)) / 100, Decimal(rng.randrange(-2000, 2000)) / 100, Decimal(rng.randrange(-2000, 2000)) / 100)
                r = self.x("color_record", """insert into color_record (job_id, ink_formula_id, color_name, seq_no, color_l, color_a, color_b, note,
                                                                        recorded_at, recorded_by)
                                              values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) returning color_record_id""",
                           (j["job_id"], j["ink"], example(color), seq, *lab, example("재조색" if seq > 1 else "샘플 조색 기록"),
                            not_future(t), self.who(rng.choice(["QC", "FIELD"]))))
                if k % 2 == 0:                                                  # 절반은 배합비 2행 (합 100)
                    a = rng.choice([55, 60, 65, 70, 75])
                    for seq_no, (name, pct) in enumerate([("성분 1", a), ("성분 2", 100 - a)], start=1):
                        self.x("color_record_mix", """insert into color_record_mix (color_record_id, seq_no, component_name, ratio_pct)
                                                      values (%s, %s, %s, %s)""", (r["color_record_id"], seq_no, example(name), pct))

    # ── 5. 생산 실적 (D5) — 실적 100 (완료 85 · 진행 8 · 정지 7) · 투입 · 정지 100 · 폐기 100 → 인쇄 롤 (lineage) ──
    def works(self) -> None:
        rng = self.rng
        active = [j for j in self.job if j["status"] == "등록"]
        double_ids = {j["job_id"] for j in self.double}
        recent = [j for j in active[-25:] if j["job_id"] not in double_ids]
        open_jobs = {j["job_id"] for j in rng.sample(recent, 15)}        # 최근 25개 Job 중 15개의 실적은 아직 열려 있다 (진행 8 · 정지 7)
        today_jobs = {j["job_id"] for j in recent if j["job_id"] not in open_jobs}
        today_jobs = set(sorted(today_jobs)[-3:])                        # 그중 3개는 오늘 끝난 실적 (현황판)
        open_status = ["진행"] * 8 + ["정지"] * 7
        rng.shuffle(open_status)
        plan: list[tuple[dict, int, str]] = []                         # (Job, 생산 LOT 순번, 상태)
        for j in active:
            plan.append((j, 0, open_status.pop() if j["job_id"] in open_jobs else "완료"))
        for j in self.double:
            plan.append((j, 1, "완료"))
        self.work: list[dict] = []
        self.print_rolls: list[dict] = []
        for j, lot_idx, status in plan:
            if status == "완료":
                wday = TODAY if j["job_id"] in today_jobs else min(j["base"] + timedelta(days=rng.randint(1, 3) + lot_idx), TODAY - timedelta(days=1))
                if wday == TODAY:                                        # 오늘 끝난 실적 — 현황판에 보인다
                    started = NOW - timedelta(hours=rng.randint(4, 9))
                    ended = not_future(started + timedelta(hours=rng.randint(1, 2), minutes=rng.randrange(0, 60)))
                else:
                    started = at(wday, 8, rng.randrange(0, 180))
                    ended = started + timedelta(hours=rng.randint(2, 8), minutes=rng.randrange(0, 60))
            else:
                back = rng.choice([0, 0, 1, 1, 2])
                started = at(self.day(back), 8, rng.randrange(0, 240)) if back else NOW - timedelta(hours=rng.randint(1, 5))
                started, ended = not_future(started), None
            worker = self.who("FIELD")
            qty = Decimal(rng.randrange(500, 3001, 50))
            r = self.x("work_result", """insert into work_result (job_id, job_lot_id, process_id, equipment_id, status, started_at, worker, note, created_at)
                                         values (%s, %s, %s, %s, '진행', %s, %s, %s, %s) returning work_result_id""",
                       (j["job_id"], j["lots"][lot_idx], self.process["인쇄"][j["i"] % 30], j["equipment_id"], started, worker,
                        example("샘플 작업 실적"), started))
            wid = r["work_result_id"]
            w = {"id": wid, "job": j, "status": status, "started": started, "ended": ended, "worker": worker, "qty": qty}
            self.work.append(w)
            j["works"].append(w)
            # 자재 투입 스캔 1~2건 (합격 LOT · 잔량 안)
            for m in self.pick_lots(started, rng.choice([1, 1, 2])):
                in_qty = min(Decimal(rng.randrange(100, 601, 10)), m["remaining"])
                m["remaining"] -= in_qty
                self.x("material_input", """insert into material_input (work_result_id, material_lot_id, input_qty, qty_unit, scanned_at, scanned_by)
                                            values (%s, %s, %s, %s, %s, %s)""",
                       (wid, m["id"], in_qty, m["unit"], started + timedelta(minutes=rng.randint(5, 40)), worker))
            if status == "완료":                                       # 작업 종료 = 인쇄 롤 1개 (실적 1 = 롤 1, D-13) — lineage 가 투입 계보까지 만든다
                width = rng.choice([1000, 1100, 1200, 1300])
                roll = lineage.make_print_roll(self.cur, work_result_id=wid, by=worker, length_m=qty, width_mm=width)
                self.u("""update work_result set status = '완료', ended_at = %s, output_qty = %s, qty_unit = 'm',
                                                 updated_at = %s, updated_by = %s where work_result_id = %s""",
                       (ended, qty, ended, worker, wid))
                self._backdate_roll(roll["roll_id"], ended)
                self.print_rolls.append({"id": roll["roll_id"], "no": roll["roll_no"], "job": j, "at": ended, "width": width, "len": qty})
            elif status == "정지":                                     # 정지 중 — 재개하지 않은 정지 행 하나 (work_stop_open_uq)
                self.x("work_stop", """insert into work_stop (work_result_id, stop_reason, stopped_at, created_by) values (%s, %s, %s, %s)""",
                       (wid, example(f"정지 사유 {rng.randint(1, 8)}"), not_future(started + timedelta(minutes=rng.randint(30, 120))), worker))
                self.u("update work_result set status = '정지', updated_at = %s, updated_by = %s where work_result_id = %s",
                       (NOW, worker, wid))
        # 정지(재개됨) — 완료 실적에 0~2건씩, 합계 100 이 될 때까지
        done = [w for w in self.work if w["status"] == "완료"]
        while self.n["work_stop"] < 100:
            w = rng.choice(done)
            span = int((w["ended"] - w["started"]).total_seconds() // 60)
            s = w["started"] + timedelta(minutes=rng.randint(10, max(11, span - 60)))
            self.x("work_stop", """insert into work_stop (work_result_id, stop_reason, stopped_at, resumed_at, created_by)
                                   values (%s, %s, %s, %s, %s)""",
                   (w["id"], example(f"정지 사유 {rng.randint(1, 8)}"), s, s + timedelta(minutes=rng.randint(5, 45)), w["worker"]))
        # 폐기 100 — 실적 아무 데나
        while self.n["work_scrap"] < 100:
            w = rng.choice(self.work)
            end = w["ended"] or not_future(w["started"] + timedelta(hours=1))
            t = w["started"] + (end - w["started"]) * rng.random()
            self.x("work_scrap", """insert into work_scrap (work_result_id, scrap_qty, qty_unit, defect_code_id, reason, scrapped_at, created_by)
                                    values (%s, %s, 'm', %s, %s, %s, %s)""",
                   (w["id"], Decimal(rng.randrange(5, 81)), rng.choice(self.defects), example("폐기 사유"), t, w["worker"]))

    def _backdate_roll(self, roll_id: int, when: datetime) -> None:
        """lineage 가 만든 롤·계보 행의 **일시만** 과거로 — 부모·자식·관계·수량은 손대지 않는다(트리거가 그것을 막기도 한다)."""
        self.u("update roll set produced_at = %s, created_at = %s where roll_id = %s", (when, when, roll_id))
        self.u("update roll_genealogy set created_at = %s where child_roll_id = %s", (when, roll_id))

    # ── 6. 후가공 10 · splice 10 · 슬리팅 15×3 (D6 · lineage) ──
    def finishing(self) -> None:
        rng = self.rng
        self.fin_rolls: list[dict] = []
        by_job: dict[int, list[dict]] = defaultdict(list)
        for p in self.print_rolls:
            by_job[p["job"]["job_id"]].append(p)
        used: set[int] = set()
        # splice — 인쇄 롤 2개가 있는 Job 10개
        for j in self.double:
            pr = by_job[j["job_id"]]
            if len(pr) < 2:
                continue
            when = min(max(p["at"] for p in pr[:2]) + timedelta(hours=rng.randint(12, 30)), NOW - timedelta(hours=1))
            by = self.who("FIELD")
            roll = lineage.make_finishing_roll(self.cur, parent_roll_ids=[p["id"] for p in pr[:2]], by=by, job_id=j["job_id"],
                                               equipment_id=rng.choice(self.equip["후가공"]), length_m=sum(p["len"] for p in pr[:2]),
                                               width_mm=pr[0]["width"])
            self._backdate_roll(roll["roll_id"], when)
            used.update(p["id"] for p in pr[:2])
            self.fin_rolls.append({"id": roll["roll_id"], "no": roll["roll_no"], "job": j, "at": when, "width": pr[0]["width"], "len": roll["length_m"]})
        # 후가공 1:1 — 아직 안 쓴 인쇄 롤 10개 (Job 은 전부 아직 `등록` — 마감은 맨 끝에 한다, D-208)
        singles = [p for p in self.print_rolls if p["id"] not in used]
        for p in rng.sample(singles, 10):
            when = min(p["at"] + timedelta(hours=rng.randint(12, 30)), NOW - timedelta(hours=1))
            by = self.who("FIELD")
            roll = lineage.make_finishing_roll(self.cur, parent_roll_ids=[p["id"]], by=by, equipment_id=rng.choice(self.equip["후가공"]),
                                               length_m=p["len"], width_mm=p["width"])
            self._backdate_roll(roll["roll_id"], when)
            self.fin_rolls.append({"id": roll["roll_id"], "no": roll["roll_no"], "job": p["job"], "at": when, "width": p["width"], "len": p["len"]})
        # 슬리팅 — 후가공 롤 15개를 3개씩
        self.slit_rolls: list[dict] = []
        for f in rng.sample(self.fin_rolls, 15):
            when = min(f["at"] + timedelta(hours=rng.randint(6, 24)), NOW - timedelta(minutes=30))
            by = self.who("FIELD")
            w3 = (Decimal(f["width"]) / 3).quantize(Decimal("0.01"))
            rolls = lineage.slit_roll(self.cur, parent_roll_id=f["id"], count=3, by=by, equipment_id=rng.choice(self.equip["슬리팅"]),
                                      widths_mm=[w3, w3, w3], length_m=f["len"])
            for r in rolls:
                self._backdate_roll(r["roll_id"], when)
                self.slit_rolls.append({"id": r["roll_id"], "no": r["roll_no"], "job": f["job"], "at": when})

    # ── 7. 검사 (D7) — 100 (롤 90 + 재검사 10) · 불량 행 ──
    def inspections(self) -> None:
        rng = self.rng
        rolls = self.print_rolls + self.fin_rolls + self.slit_rolls
        targets = rng.sample(rolls, min(90, len(rolls)))
        self.last_result: dict[int, str] = {}
        first_fail: list[dict] = []
        for idx, r in enumerate(targets):
            result = "불합격" if idx % 5 == 0 else "합격"                       # 18 불합격
            self._inspect(r, result, r["at"] + timedelta(hours=rng.randint(1, 20)))
            if result == "불합격":
                first_fail.append(r)
        for r in first_fail[:10]:                                              # 10개는 재검사 → 합격 (최신 검사가 판정)
            self._inspect(r, "합격", r["at"] + timedelta(hours=rng.randint(24, 48)), note="재검사")

    def _inspect(self, r: dict, result: str, when: datetime, note: str = "샘플 검사") -> None:
        rng = self.rng
        when = not_future(when)
        de = None if rng.random() < 0.2 else (Decimal(rng.randrange(250, 601)) / 100 if result == "불합격" else Decimal(rng.randrange(30, 250)) / 100)
        row = self.x("inspection", """insert into inspection (roll_id, job_id, delta_e, result, inspected_at, inspected_by, note)
                                      values (%s, %s, %s, %s, %s, %s, %s) returning inspection_id""",
                     (r["id"], r["job"]["job_id"], de, result, when, self.who("QC"), example(note)))
        n_def = rng.randint(2, 4) if result == "불합격" else (1 if rng.random() < 0.55 else 0)
        for k in range(n_def):
            self.x("inspection_defect", "insert into inspection_defect (inspection_id, defect_code_id, position, note) values (%s, %s, %s, %s)",
                   (row["inspection_id"], rng.choice(self.defects), example(f"위치 {rng.randint(1, 500)}m"), example("샘플 불량") if k == 0 else None))
        self.last_result[r["id"]] = result
        r["insp_at"] = max(r.get("insp_at") or when, when)

    # ── 8. 출하 (D8) — 100 (승인 ~60 · 등록 ~20 · 취소 ~20) · 출하 롤 스캔은 lineage.ship_roll ──
    def shipments(self) -> None:
        rng = self.rng
        self.cur.execute("select roll_id, state from v_roll_state where roll_id = any(%s)",
                         ([r["id"] for r in self.print_rolls + self.fin_rolls + self.slit_rolls],))
        state = {x["roll_id"]: x["state"] for x in self.cur.fetchall()}
        shippable: dict[int, list[dict]] = defaultdict(list)
        for r in self.print_rolls + self.fin_rolls + self.slit_rolls:
            if state[r["id"]] == lineage.IN_STOCK and self.last_result.get(r["id"]) != "불합격":
                shippable[r["job"]["job_id"]].append(r)
        made = 0
        self.approved_jobs: set[int] = set()
        jobs_with = [j for j in self.job if shippable.get(j["job_id"])]
        for k, j in enumerate(jobs_with):
            rolls = shippable[j["job_id"]][: rng.choice([1, 1, 2])]
            ready = max(max(r["at"], r.get("insp_at") or r["at"]) for r in rolls)
            ship_date = max(ready.date() + timedelta(days=1), j["due"] + timedelta(days=rng.randint(-3, 5)))   # 납기 전후 — 준수·지연 섞임
            if j["due"] == TODAY and ready.date() < TODAY:
                ship_date = TODAY                                        # 오늘 납기 Job 은 오늘 출하 (현황판의 납기 칸)
            registered = at(ship_date - timedelta(days=1), 14, rng.randrange(0, 60))
            if registered < ready:
                registered = ready + timedelta(hours=1)
            if ship_date <= TODAY and registered < NOW - timedelta(hours=2) and k % 6 != 5:
                status = "승인"
            else:                                                        # 아직 안 나간 출하 (등록) — 출하일은 앞으로
                status = "등록"
                registered = min(registered, NOW - timedelta(hours=1))
                if ship_date <= TODAY:
                    ship_date = TODAY + timedelta(days=rng.randint(1, 5))
            sid = self._shipment(j, ship_date, registered, status)
            for r in rolls:                                                  # 출하 롤 스캔 — lineage 만 (D-12)
                lineage.ship_roll(self.cur, shipment_id=sid, roll_id=r["id"], by=self.who("PROD"))
            self.u("update roll_genealogy set created_at = %s where child_shipment_id = %s", (registered + timedelta(minutes=10), sid))
            if status == "승인":
                approved = not_future(at(ship_date, 9, rng.randrange(0, 90)))
                coa = numbering.next(numbering.COA, cur=self.cur, at=approved)
                self.u("""update shipment set status = '승인', approved_at = %s, approved_by = %s, coa_no = %s, coa_issued_at = %s,
                                               updated_at = %s, updated_by = %s where shipment_id = %s""",
                       (approved, self.who("ADMIN"), coa, approved, approved, self.who("ADMIN"), sid))
                self.approved_jobs.add(j["job_id"])
            made += 1
        # 나머지 — 롤 없는 등록 출하와 취소 출하로 100 을 채운다
        active = [j for j in self.job if j["status"] == "등록"]
        k = 0
        while made < 100:
            j = active[(k * 13) % len(active)]
            k += 1
            registered = not_future(j["created"] + timedelta(days=rng.randint(3, 12), hours=rng.randint(0, 8)))
            status = "취소" if made % 2 else "등록"
            sid = self._shipment(j, max(registered.date() + timedelta(days=1), TODAY if status == "등록" else registered.date()), registered, status)
            if status == "취소":
                self.u("update shipment set status = '취소', updated_at = %s, updated_by = %s where shipment_id = %s",
                       (not_future(registered + timedelta(hours=3)), self.who("PROD"), sid))
            made += 1

    def _shipment(self, j: dict, ship_date: date, registered: datetime, status: str) -> int:
        no = numbering.next(numbering.SHIPMENT, cur=self.cur, at=registered)
        r = self.x("shipment", """insert into shipment (shipment_no, job_id, customer_id, ship_date, status, registered_at, registered_by, note)
                                  values (%s, %s, %s, %s, '등록', %s, %s, %s) returning shipment_id""",
                   (no, j["job_id"], j["customer_id"], ship_date, registered, self.who("PROD"),
                    example("샘플 출하" + (" — 취소" if status == "취소" else ""))))
        return r["shipment_id"]

    # ── 9. Job 마감 — 실적이 전부 완료이고 오래된 Job 20개 ──
    def close_jobs(self) -> None:
        cands = [j for j in self.job if j["status"] == "등록" and j["works"] and all(w["status"] == "완료" for w in j["works"])
                 and j["base"] <= TODAY - timedelta(days=30)]
        cands.sort(key=lambda j: (j["job_id"] not in self.approved_jobs, j["i"]))
        for j in cands[:20]:
            last = max(w["ended"] for w in j["works"])
            self.u("update job set status = '완료', updated_at = %s, updated_by = %s where job_id = %s",
                   (not_future(last + timedelta(days=2)), self.who("PROD"), j["job_id"]))
            j["status"] = "완료"

    def run(self) -> None:
        self.users_()
        self.masters()
        self.jobs()
        self.sales_orders()
        self.material_lots()
        self.colors()
        self.works()
        self.finishing()
        self.inspections()
        self.shipments()
        self.close_jobs()


def insert() -> int:
    before = counts()
    if already_in():
        if orders_in():
            print("샘플 데이터가 이미 들어 있다 — 건너뛴다 (멱등). 지우려면 --clean")
            print_counts("행 수 (지금)", before)
            return 0
        with conn.tx() as cur:                                           # 수주(D-418)가 생기기 전에 넣은 샘플 — 수주 100 만 더한다
            Sample(cur).sales_orders()
        print("샘플은 이미 있고 수주 샘플만 없었다 — 수주 100 을 더했다")
    else:
        with conn.tx() as cur:
            s = Sample(cur)
            s.run()
    after = counts()
    print_counts("샘플 넣음 — 테이블별 행 수 (괄호: 이 실행이 더한 행)", after, before)
    summary = conn.q1("""select (select count(*) from job where created_by like %(u)s and status = '등록') as job_open,
                                (select count(*) from job where created_by like %(u)s and status = '완료') as job_done,
                                (select count(*) from job where created_by like %(u)s and status = '취소') as job_cancel,
                                (select count(*) from work_result where worker like %(u)s and status = '완료') as wr_done,
                                (select count(*) from work_result where worker like %(u)s and status <> '완료') as wr_open,
                                (select count(*) from roll where produced_by like %(u)s and process_type = '인쇄') as r_print,
                                (select count(*) from roll where produced_by like %(u)s and process_type = '후가공') as r_fin,
                                (select count(*) from roll where produced_by like %(u)s and process_type = '슬리팅') as r_slit,
                                (select count(*) from shipment where registered_by like %(u)s and status = '승인') as sh_ok,
                                (select count(*) from shipment where registered_by like %(u)s and status = '등록') as sh_reg,
                                (select count(*) from shipment where registered_by like %(u)s and status = '취소') as sh_cancel,
                                (select count(*) from inspection where inspected_by like %(u)s and result = '불합격') as insp_fail,
                                (select count(*) from material_lot where received_by like %(u)s and insp_status = '합격') as ml_ok""",
                      {"u": USER.replace("_", r"\_") + "%"})
    rel = {r["relation"]: r["n"] for r in conn.q("select relation, count(*) as n from roll_genealogy where created_by like %s group by relation",
                                                  (USER.replace("_", r"\_") + "%",))}
    print(f"흐름 — Job 등록 {summary['job_open']} · 완료 {summary['job_done']} · 취소 {summary['job_cancel']} / "
          f"실적 완료 {summary['wr_done']} · 열림 {summary['wr_open']} / 롤 인쇄 {summary['r_print']} · 후가공 {summary['r_fin']} · 슬리팅 {summary['r_slit']} / "
          f"계보 {' · '.join(f'{k} {v}' for k, v in rel.items())} / 검사 불합격 {summary['insp_fail']} / "
          f"출하 승인 {summary['sh_ok']} · 등록 {summary['sh_reg']} · 취소 {summary['sh_cancel']} / 원재료 LOT 합격 {summary['ml_ok']}")
    so = conn.q1("""select count(*) filter (where status = '등록' and exists (select 1 from job j where j.sales_order_id = so.sales_order_id)) as linked,
                           count(*) filter (where status = '등록' and not exists (select 1 from job j where j.sales_order_id = so.sales_order_id)) as open,
                           count(*) filter (where status = '취소') as cancel
                      from sales_order so where created_by like %s""", (USER.replace("_", r"\_") + "%",))
    print(f"수주(확장 D-418) — 지시 {so['linked']} · 미지시 {so['open']} · 취소 {so['cancel']}")
    return 0


# ══════════════════════════════════════════════════════════════════════
# 지우기 — FK 순서대로. 샘플 계정(smp_)이 만든 것과 샘플 코드(SMP-)에 매달린 것만
# ══════════════════════════════════════════════════════════════════════
def clean() -> int:
    before = counts()
    u = USER.replace("_", r"\_") + "%"
    jobs = "select job_id from job where created_by like %(u)s"
    rolls = f"select roll_id from roll where job_id in ({jobs})"
    lots = "select material_lot_id from material_lot where received_by like %(u)s"
    works = f"select work_result_id from work_result where job_id in ({jobs})"
    ships = f"select shipment_id from shipment where job_id in ({jobs})"
    steps = [
        ("roll_genealogy", f"""delete from roll_genealogy where created_by like %(u)s or parent_material_lot_id in ({lots})
                               or parent_roll_id in ({rolls}) or child_roll_id in ({rolls}) or child_shipment_id in ({ships})"""),
        ("inspection", f"delete from inspection where roll_id in ({rolls}) or inspected_by like %(u)s"),          # 불량 행은 cascade
        ("shipment", f"delete from shipment where job_id in ({jobs}) or registered_by like %(u)s"),
        ("roll", f"delete from roll where job_id in ({jobs}) or produced_by like %(u)s"),
        ("material_input", f"delete from material_input where work_result_id in ({works}) or material_lot_id in ({lots}) or scanned_by like %(u)s"),
        ("work_stop", f"delete from work_stop where work_result_id in ({works}) or created_by like %(u)s"),
        ("work_scrap", f"delete from work_scrap where work_result_id in ({works}) or created_by like %(u)s"),
        ("work_result", f"delete from work_result where job_id in ({jobs}) or worker like %(u)s"),
        ("color_record", f"delete from color_record where job_id in ({jobs}) or recorded_by like %(u)s"),        # 배합비 행은 cascade
        ("job_lot", f"delete from job_lot where job_id in ({jobs}) or created_by like %(u)s"),
        ("job", "delete from job where created_by like %(u)s"),
        ("sales_order", "delete from sales_order where created_by like %(u)s"),                                  # Job 이 먼저 지워져야 한다 (FK)
        ("material_lot", "delete from material_lot where received_by like %(u)s"),
        ("plate_spec", "delete from plate_spec where plate_code like %(c)s"),
        ("ink_formula", "delete from ink_formula where ink_code like %(c)s"),                                     # 조성 행은 cascade
        ("anilox", "delete from anilox where anilox_code like %(c)s"),
        ("equipment", "delete from equipment where equipment_code like %(c)s"),
        ("process", "delete from process where process_code like %(c)s"),
        ("defect_code", "delete from defect_code where defect_code like %(c)s"),
        ("customer", "delete from customer where customer_code like %(c)s"),
        ("item", "delete from item where item_code like %(c)s"),
        ("sys_user", "delete from sys_user where login_id like %(u)s"),
    ]
    removed: dict[str, int] = {}
    with conn.tx() as cur:
        for table, sql in steps:
            cur.execute(sql, {"u": u, "c": CODE + "%"})
            removed[table] = cur.rowcount
    after = counts()
    print("샘플 지움 — " + " · ".join(f"{t} {n}" for t, n in removed.items() if n))
    print_counts("행 수 (지운 뒤)", after, before)
    left = [f"{t} {n}" for t, n in leftovers().items() if n]
    if left:
        print("남은 샘플 행 — " + " · ".join(left))
        return 1
    return 0


def leftovers() -> dict[str, int]:
    u = USER.replace("_", r"\_") + "%"
    return {
        "item": conn.q1("select count(*) as n from item where item_code like %s", (CODE + "%",))["n"],
        "job": conn.q1("select count(*) as n from job where created_by like %s", (u,))["n"],
        "sales_order": conn.q1("select count(*) as n from sales_order where created_by like %s", (u,))["n"],
        "material_lot": conn.q1("select count(*) as n from material_lot where received_by like %s", (u,))["n"],
        "roll": conn.q1("select count(*) as n from roll where produced_by like %s", (u,))["n"],
        "roll_genealogy": conn.q1("select count(*) as n from roll_genealogy where created_by like %s", (u,))["n"],
        "sys_user": conn.q1("select count(*) as n from sys_user where login_id like %s", (u,))["n"],
    }


def main(argv: list[str]) -> int:
    if "--counts" in argv:
        print_counts("행 수", counts())
        return 0
    if "--clean" in argv:
        return clean()
    return insert()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
