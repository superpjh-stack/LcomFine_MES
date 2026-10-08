#!/usr/bin/env python
"""G-05~G-12 계보·데이터 검사 — `make check-data` (QA2 · goal.md §2.1·§2.2 · §3.3).

    uv run python tools/check_data.py                 # G-05~G-12 판정 행. 종료코드 0 = FAIL 없음, 1 = FAIL 있음
    uv run python tools/check_data.py --run-seeds     # + 시드를 두 번 돌려 G-09(행 수 diff 0)를 잰다 (`make gate-full` 이 이렇게 부른다)
    uv run python tools/check_data.py --only G-06,G-07
    uv run python tools/check_data.py --keep          # 만든 데이터를 지우지 않는다 (디버깅용 — 다음 실행의 --purge 로 지운다)
    uv run python tools/check_data.py --purge         # 남아 있는 `Q2-` 데이터를 전부 지우고 끝낸다

출력 행 형식: `G-nn  항목  PASS|FAIL|WARN|BLOCKED|미검증  실측` (tools/gate.py 의 per_gate 가 읽는다).

원칙
  · **기대값은 설계도에서 직접 읽는다** — §3 계보 그림의 상자·화살표(SVG 좌표)와 §2 「프로세스별 입력과 출력」 표.
  · **개발이 짠 추적·집계 코드를 믿지 않는다.** 계보는 화면이 부르는 것과 같은 API 로 직접 만들고, 추적·집계는 이 파일의
    독립 SQL(`TRACE_SQL` · `sql_*`)과 파이썬 모델로 다시 계산해 화면 값과 대조한다. `app/lineage.py` · `app/stats.py` 를 부르지 않는다
    (G-10 의 「함수값 = 독립 SQL」 한 줄만 `stats` 함수의 반환값을 받아 비교한다).
  · 검사기는 스스로 데이터를 만들고 재고 **지운다**. 업무 코드는 전부 `Q2-<6자>-…` 이고, 끝나면 그 접두에 매달린 것을 전부 지운다.
    다른 QA 가 같은 DB 를 쓰므로 `db-reset`/`db-schema` 를 부르지 않고, 행 수 대조는 내 접두 데이터 기준으로 한다.
  · 결함이 있으면 FAIL 을 낸다. 재지 못한 것은 `미검증` 이다 — 통과한 것처럼 적지 않는다.
"""

from __future__ import annotations

import warnings

warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient`")

import ast
import hashlib
import os
import inspect
import random
import re
import subprocess
import sys
import textwrap
import threading
import traceback
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT / "tools"))

import psycopg  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

import design_doc  # noqa: E402
from lcomfine.app import contracts, nav  # noqa: E402
from lcomfine.app.settings import get_settings  # noqa: E402
from lcomfine.db import conn as appconn  # noqa: E402  (DSN 만 쓴다)

PASS, FAIL, WARN, UNVERIFIED = "PASS", "FAIL", "WARN", "미검증"
PREFIX = "Q2-"
HTML = {"accept": "text/html"}
NOT_COLLECTED, UNDECIDED = "미수집", "미확정 (D-"
BUSINESS_STORES = [f"D{i}" for i in range(1, 9)]
#: 공통 코드가 쓰는 시스템 테이블 — 접근 로그와 채번 카운터 (decisions.md D-15). 업무 라우터가 쓸 수 있는 sys_* 는 이 둘뿐이어야 한다
COMMON_SYS = {"sys_access_log", "sys_number_seq"}
RELATIONS = ("투입", "후가공", "splice", "슬리팅", "출하")


# ════════════════════════════════════════════════════════════════════════
# 0. 판정 행
# ════════════════════════════════════════════════════════════════════════
class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str, str]] = []

    def add(self, gid: str, item: str, status, actual: str) -> None:
        if isinstance(status, bool):
            status = PASS if status else FAIL
        item = re.sub(r"\s{2,}", " ", item.strip())
        actual = re.sub(r"\s+", " ", str(actual).strip())
        self.rows.append((gid, item, status, actual))

    def failed(self, gid: str | None = None) -> list[tuple[str, str, str, str]]:
        return [r for r in self.rows if r[2] == FAIL and (gid is None or r[0] == gid)]

    def print(self) -> None:
        w = max((len(r[1]) for r in self.rows), default=10)
        for gid, item, status, actual in self.rows:
            print(f"{gid}  {item:<{w}}  {status}  {actual}")


# ════════════════════════════════════════════════════════════════════════
# 1. 실행된 SQL 가로채기 — 요청 한 건이 실제로 실행한 쓰기 문장을 본다 (G-05 동적 검사)
# ════════════════════════════════════════════════════════════════════════
_TAP: dict = {"on": False, "log": []}
_TAP_LOCK = threading.Lock()


def install_tap() -> None:
    """psycopg 의 `Cursor.execute` 를 감싼다. 앱(TestClient)이 같은 프로세스에서 돌기 때문에 요청이 실행한 SQL 이 그대로 보인다."""
    orig = psycopg.Cursor.execute
    if getattr(orig, "_qa2_tap", False):
        return

    def execute(self, query, params=None, **kw):
        if _TAP["on"]:
            with _TAP_LOCK:
                _TAP["log"].append(query if isinstance(query, str) else str(query))
        return orig(self, query, params, **kw)

    execute._qa2_tap = True
    psycopg.Cursor.execute = execute


_WRITE_RE = re.compile(r"\b(insert\s+into|delete\s+from|update)\s+(?:only\s+)?\"?([a-z_][a-z0-9_]*)\"?", re.I)


def writes_of(sql: str) -> list[tuple[str, str]]:
    """SQL 한 문장이 쓰는 (동사, 테이블). `for update` · `for no key update` · `on conflict … do update` 는 쓰기 대상이 아니다."""
    s = re.sub(r"--[^\n]*", " ", sql)
    s = re.sub(r"\s+", " ", s)
    out: list[tuple[str, str]] = []
    for m in _WRITE_RE.finditer(s):
        verb, table = m.group(1).split()[0].lower(), m.group(2).lower()
        before = s[max(0, m.start() - 16):m.start()].lower()
        if verb == "update" and (table in ("set", "of", "nowait", "skip") or re.search(r"\b(for|for no key|do)\s*$", before)):
            continue
        out.append((verb, table))
    return out


# ════════════════════════════════════════════════════════════════════════
# 2. DB (QA2 의 독립 연결) · API 클라이언트
# ════════════════════════════════════════════════════════════════════════
class Db:
    def __init__(self) -> None:
        self.c = psycopg.connect(appconn.dsn(), autocommit=True, row_factory=dict_row)

    def q(self, sql: str, params=None) -> list[dict]:
        with self.c.cursor() as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()] if cur.description else []

    def q1(self, sql: str, params=None) -> dict | None:
        rows = self.q(sql, params)
        return rows[0] if rows else None

    def v(self, sql: str, params=None):
        row = self.q1(sql, params)
        return next(iter(row.values())) if row else None

    def x(self, sql: str, params=None) -> int:
        with self.c.cursor() as cur:
            cur.execute(sql, params)
            return cur.rowcount

    def close(self) -> None:
        self.c.close()


def _fn_matchers() -> list[tuple[str, re.Pattern, object, int]]:
    out = []
    for f in contracts.functions():
        if f.is_batch:
            continue
        pat = re.compile("^" + re.sub(r"\{[^}]+\}", "[^/]+", f.path) + "$")
        out.append((f.method, pat, f, f.path.count("{")))
    return sorted(out, key=lambda t: t[3])       # 경로 변수가 없는 것을 먼저 맞춘다


class Api:
    """화면이 부르는 것과 같은 엔드포인트를 부른다 (앱을 같은 프로세스에서 — FastAPI TestClient).

    POST 는 폼(HTML 폼과 같은 필드), 응답은 JSON(`accept` 를 주지 않는다). 화면 GET 은 `accept: text/html`.
    요청마다 실제 실행된 쓰기 SQL 을 `calls` 에 남긴다.
    환경변수 `QA2_BASE_URL` 을 주면 같은 요청을 실제로 띄운 서버에 HTTP 로 보낸다(이때는 SQL 캡처가 비어 G-05·G-07 의 캡처 행은 잴 수 없다).
    """

    def __init__(self) -> None:
        from fastapi.testclient import TestClient

        from lcomfine.app.main import app

        install_tap()
        self.app = app
        self._TestClient = TestClient
        self._clients: dict[str, object] = {}
        self._matchers = _fn_matchers()
        self.calls: list[dict] = []
        self.base_url = os.environ.get("QA2_BASE_URL") or None   # 주면 그 서버에 HTTP 로 보낸다 (실행 SQL 캡처는 안 된다 → G-06·G-10 용)
        self.password = get_settings().seed_password
        if not self.password:
            raise SystemExit("LCOMFINE_SEED_PASSWORD 미설정 — 시드 계정으로 로그인할 수 없다 (`.env`)")

    def new_client(self, role: str):
        if self.base_url:                                         # 실제로 띄운 서버 (QA2_BASE_URL=http://127.0.0.1:8022)
            import httpx

            c = httpx.Client(base_url=self.base_url, timeout=30)
        else:
            c = self._TestClient(self.app, raise_server_exceptions=False)
        r = c.post("/login", data={"login_id": role, "password": self.password}, follow_redirects=False)
        if r.status_code != 303:
            raise SystemExit(f"{role} 로그인 실패 {r.status_code} — 공통 시드와 .env 를 확인한다")
        return c

    def client(self, role: str):
        if role not in self._clients:
            self._clients[role] = self.new_client(role)
        return self._clients[role]

    def fn_of(self, method: str, path: str):
        for m, pat, f, _n in self._matchers:
            if m == method and pat.match(path):
                return f
        return None

    def _send(self, role: str, method: str, path: str, client=None, **kw):
        c = client or self.client(role)
        with _TAP_LOCK:
            _TAP["log"] = []
            _TAP["on"] = True
        try:
            r = c.request(method, path, follow_redirects=False, **kw)
        finally:
            with _TAP_LOCK:
                _TAP["on"] = False
                log = list(_TAP["log"])
        writes = [w for s in log for w in writes_of(s)]
        f = self.fn_of(method, path.split("?")[0])
        self.calls.append({"role": role, "method": method, "path": path.split("?")[0], "status": r.status_code,
                           "writes": writes, "sql": log, "fn": f})
        return r

    def post(self, role: str, path: str, data: dict | None = None, client=None) -> tuple[int, dict]:
        r = self._send(role, "POST", path, client=client, data=data or {})
        try:
            body = r.json()
        except Exception:  # noqa: BLE001 — JSON 이 아니면 본문 앞부분을 그대로 본다
            body = {"_text": r.text[:300]}
        return r.status_code, body

    def get(self, role: str, path: str, params: dict | None = None, client=None):
        return self._send(role, "GET", path, client=client, params=params or {}, headers=HTML)

    @property
    def last(self) -> dict:
        return self.calls[-1]


class FlowError(AssertionError):
    pass


# ════════════════════════════════════════════════════════════════════════
# 3. 흐름 — 화면이 부르는 API 로 한 걸음씩 (기준정보 → Job → 입고 → 인쇄 → 후가공 → 슬리팅 → 검사 → 출하)
# ════════════════════════════════════════════════════════════════════════
class Flow:
    """내 데이터 한 벌. 업무 코드는 `Q2-<6자>-…`. 내가 **요청한** 화살표를 `edges`(모델)에 적어 둔다 — 추적 대조의 기대값이다."""

    def __init__(self, api: Api, db: Db) -> None:
        self.api, self.db = api, db
        self.tag = PREFIX + uuid.uuid4().hex[:6].upper()
        self.kind: dict[str, str] = {}          # 번호 → L(원재료 LOT) | R(롤) | S(출하 LOT)
        self.ptype: dict[str, str] = {}         # 롤 번호 → 인쇄 | 후가공 | 슬리팅
        self.job_of: dict[str, str] = {}        # 롤·출하 번호 → Job 번호
        self.edges: set[tuple[str, str, str]] = set()   # (부모 번호, 자식 번호, 관계)
        self.jobs: list[str] = []
        self.numbers: dict[str, list[str]] = defaultdict(list)   # 채번 종류 → 받은 번호 (G-08)
        self.work_of: dict[str, int] = {}       # 인쇄 롤 번호 → work_result_id
        self.p8_changes: list[dict] = []        # P8 요청 전후 계보 행의 변화 (D-12 범위 검사)
        self._n = 0

    # ── 도우미 ──
    def code(self, suffix: str) -> str:
        return f"{self.tag}-{suffix}"

    def label(self, text: str) -> str:
        return f"{self.tag} {text} (예시)"

    def seq(self) -> int:
        self._n += 1
        return self._n

    def must(self, res: tuple[int, dict], what: str) -> dict:
        status, body = res
        if status != 200:
            raise FlowError(f"{what} — HTTP {status} {str(body)[:300]}")
        return body

    # ── 기준정보 (P1 · 관리자) ──
    def item(self, suffix: str, item_type: str, unit: str = "m") -> int:
        b = self.must(self.api.post("admin", "/bas/items", {
            "item_code": self.code(suffix), "item_name": self.label(f"{item_type} {suffix}"), "item_type": item_type,
            "unit": unit}), f"품목 등록 {suffix}")
        return b["id"]

    def customer(self, suffix: str = "CU") -> int:
        return self.must(self.api.post("admin", "/bas/customers", {
            "customer_code": self.code(suffix), "customer_name": self.label("고객")}), "고객 등록")["id"]

    def defect(self, suffix: str) -> str:
        self.must(self.api.post("admin", "/bas/defect-codes", {
            "defect_code": self.code(suffix), "defect_name": self.label(f"불량 {suffix}"), "defect_group": "(예시)"}),
            f"불량코드 등록 {suffix}")
        return self.code(suffix)

    # ── 작업지시 (P2 · 생산) ──
    def job(self, item_id: int, customer_id: int, due: date | str, qty: str = "1000", **extra) -> str:
        b = self.must(self.api.post("prod", "/job/orders", {
            "item_id": str(item_id), "customer_id": str(customer_id), "order_qty": qty, "due_date": str(due), **extra}),
            "작업지시 등록")
        self.jobs.append(b["job_no"])
        self.numbers["JOB"].append(b["job_no"])
        return b["job_no"]

    def job_lot(self, job_no: str, planned: int = 2) -> str:
        b = self.must(self.api.post("prod", "/job/mapping", {"job_no": job_no, "planned_roll_count": str(planned)}),
                      "Job-Lot-Roll 매핑 등록")
        self.numbers["JOB_LOT"].append(b["lot_no"])
        return b["lot_no"]

    # ── 자재 입고 · 입고검사 (P3) ──
    def receive(self, raw_code: str, qty: str = "500") -> str:
        b = self.must(self.api.post("prod", "/mat/receipts", {
            "item_code": raw_code, "supplier_name": self.label("공급처"), "supplier_lot_no": self.code(f"SL{self.seq()}"),
            "received_qty": qty}), "입고 등록")
        self.kind[b["lot_no"]] = "L"
        self.numbers["MAT_LOT"].append(b["lot_no"])
        return b["lot_no"]

    def lot_inspect(self, lot_no: str, result: str = "합격") -> None:
        self.must(self.api.post("qc", "/mat/inspections", {"lot_no": lot_no, "result": result}), f"입고검사 {result}")

    def lot(self, raw_code: str, qty: str = "500") -> str:
        no = self.receive(raw_code, qty)
        self.lot_inspect(no, "합격")
        return no

    # ── 인쇄 (P5) — 작업 시작 → 자재 투입 스캔 → 작업 종료 = 인쇄 롤 1개 ──
    def start(self, job_no: str, lot_no: str = "") -> int:
        return self.must(self.api.post("prod", "/pop/work/start", {"job_no": job_no, "lot_no": lot_no}), "작업 시작")["work_id"]

    def input(self, work_id: int, lot_no: str, qty: str = "") -> None:
        self.must(self.api.post("field", "/mat/inputs", {"work_id": str(work_id), "lot_no": lot_no, "input_qty": qty}),
                  f"자재 투입 스캔 {lot_no}")

    def finish(self, work_id: int, output_qty: str = "100", qty_unit: str = "", length_m: str = "") -> str:
        b = self.must(self.api.post("prod", f"/pop/work/{work_id}/finish",
                                    {"output_qty": output_qty, "qty_unit": qty_unit, "length_m": length_m}), "작업 종료")
        return b["roll_no"]

    def print_roll(self, job_no: str, lots: list[str], output_qty: str = "100", qty_unit: str = "", job_lot: str = "",
                   input_qty: str = "") -> str:
        wid = self.start(job_no, job_lot)
        for lot_no in lots:
            self.input(wid, lot_no, input_qty)
        roll = self.finish(wid, output_qty, qty_unit)
        self._roll(roll, "인쇄", job_no)
        self.work_of[roll] = wid
        for lot_no in lots:
            self.edges.add((lot_no, roll, "투입"))
        return roll

    def _roll(self, roll_no: str, ptype: str, job_no: str) -> None:
        self.kind[roll_no], self.ptype[roll_no], self.job_of[roll_no] = "R", ptype, job_no
        self.numbers["ROLL"].append(roll_no)

    # ── 후가공 · 슬리팅 (P6) ──
    def finishing(self, roll_no: str) -> str:
        b = self.must(self.api.post("field", "/rll/finishing", {"roll_no": roll_no}), f"후가공 {roll_no}")
        self._roll(b["roll_no"], "후가공", self.job_of[roll_no])
        self.edges.add((roll_no, b["roll_no"], "후가공"))
        return b["roll_no"]

    def splice(self, rolls: list[str], job_no: str = "") -> str:
        b = self.must(self.api.post("prod", "/rll/finishing/splice", {"roll_no": rolls, "job_no": job_no}),
                      f"splice {rolls}")
        self._roll(b["roll_no"], "후가공", job_no or self.job_of[rolls[0]])
        for r in rolls:
            self.edges.add((r, b["roll_no"], "splice"))
        return b["roll_no"]

    def slit(self, roll_no: str, count: int) -> list[str]:
        b = self.must(self.api.post("prod", "/rll/slitting", {"roll_no": roll_no, "count": str(count)}), f"슬리팅 {roll_no}")
        for r in b["rolls"]:
            self._roll(r, "슬리팅", self.job_of[roll_no])
            self.edges.add((roll_no, r, "슬리팅"))
        return b["rolls"]

    # ── 품질 검사 (P7 · 품질) ──
    def inspect(self, roll_no: str, result: str = "합격", delta_e: str = "", defects: list[tuple[str, str]] | None = None) -> int:
        data: dict = {"roll_no": roll_no, "delta_e": delta_e, "result": result}
        if defects:
            data["defect_code"] = [d for d, _ in defects]
            data["position"] = [p for _, p in defects]
        return self.must(self.api.post("qc", "/qua/inspections", data), f"검사 결과 등록 {roll_no}")["inspection_id"]

    # ── 출하 (P8) ──
    def _genealogy_of_tag(self) -> dict[int, str]:
        return {r["genealogy_id"]: r["relation"] for r in self.db.q(SCOPE_ROWS_SQL, {"like": self.tag + "-%"})}

    def shipment(self, job_no: str, ship_date: date | str) -> str:
        b = self.must(self.api.post("field", "/shp/shipments", {"job_no": job_no, "ship_date": str(ship_date)}), "출하 등록")
        self.kind[b["shipment_no"]], self.job_of[b["shipment_no"]] = "S", job_no
        self.numbers["SHIPMENT"].append(b["shipment_no"])
        return b["shipment_no"]

    def scan(self, shipment_no: str, roll_no: str) -> None:
        before = self._genealogy_of_tag()
        self.must(self.api.post("field", f"/shp/shipments/{shipment_no}/rolls", {"roll_no": roll_no}),
                  f"출하 롤 스캔 {roll_no}")
        after = self._genealogy_of_tag()
        self.p8_changes.append({"fn": "F-SHP-02", "added": [after[k] for k in after.keys() - before.keys()],
                                "removed": [before[k] for k in before.keys() - after.keys()]})
        self.edges.add((roll_no, shipment_no, "출하"))

    def approve(self, shipment_no: str) -> str:
        before = self._genealogy_of_tag()
        b = self.must(self.api.post("admin", f"/shp/approvals/{shipment_no}/approve"), f"출하 승인 {shipment_no}")
        after = self._genealogy_of_tag()
        self.p8_changes.append({"fn": "F-SHP-05", "added": [after[k] for k in after.keys() - before.keys()],
                                "removed": [before[k] for k in before.keys() - after.keys()]})
        self.numbers["COA"].append(b["coa_no"])
        return b["coa_no"]

    def cancel_shipment(self, shipment_no: str) -> None:
        before = self._genealogy_of_tag()
        self.must(self.api.post("field", f"/shp/shipments/{shipment_no}/cancel"), f"출하 취소 {shipment_no}")
        after = self._genealogy_of_tag()
        self.p8_changes.append({"fn": "F-SHP-03", "added": [after[k] for k in after.keys() - before.keys()],
                                "removed": [before[k] for k in before.keys() - after.keys()]})
        self.edges = {e for e in self.edges if e[1] != shipment_no}

    # ── 뒷정리 ──
    def cleanup(self) -> None:
        purge(self.db, self.tag + "-%")


#: 내 접두(품목 코드)에 매달린 계보 행 — 부모나 자식이 내 Job 의 롤·출하이거나 내 원재료 LOT 인 행
SCOPE_ROWS_SQL = """
select g.genealogy_id, g.relation
  from roll_genealogy g
 where g.parent_material_lot_id in (select m.material_lot_id from material_lot m join item i on i.item_id = m.item_id
                                     where i.item_code like %(like)s)
    or g.parent_roll_id in (select r.roll_id from roll r join job j on j.job_id = r.job_id join item i on i.item_id = j.item_id
                             where i.item_code like %(like)s)
    or g.child_roll_id in (select r.roll_id from roll r join job j on j.job_id = r.job_id join item i on i.item_id = j.item_id
                            where i.item_code like %(like)s)
    or g.child_shipment_id in (select s.shipment_id from shipment s join job j on j.job_id = s.job_id
                                 join item i on i.item_id = j.item_id where i.item_code like %(like)s)
"""


def purge(db: Db, like: str) -> dict[str, int]:
    """`like`(예: `Q2-AB12CD-%`)에 맞는 업무 코드에 매달린 것을 전부 지운다. 지운 행 수를 테이블별로 돌려준다.

    접근 로그(sys_access_log)와 채번 카운터(sys_number_seq)는 건드리지 않는다 — 로그는 지우지 않는 것이 맞고 카운터는 되돌릴 수 없다.
    """
    p = {"like": like}
    items = "(select item_id from item where item_code like %(like)s)"
    jobs = f"(select job_id from job where item_id in {items})"
    lots = f"(select material_lot_id from material_lot where item_id in {items})"
    rolls = f"(select roll_id from roll where job_id in {jobs})"
    ships = f"(select shipment_id from shipment where job_id in {jobs})"
    works = f"(select work_result_id from work_result where job_id in {jobs})"
    insps = f"(select inspection_id from inspection where job_id in {jobs})"
    steps = [
        ("inspection_defect", f"inspection_id in {insps} or defect_code_id in (select defect_code_id from defect_code where defect_code like %(like)s)"),
        ("inspection", f"job_id in {jobs}"),
        ("roll_genealogy", f"parent_roll_id in {rolls} or child_roll_id in {rolls} or child_shipment_id in {ships} "
                           f"or parent_material_lot_id in {lots}"),
        ("shipment", f"job_id in {jobs}"),
        ("roll", f"job_id in {jobs}"),
        ("material_input", f"work_result_id in {works} or material_lot_id in {lots}"),
        ("work_scrap", f"work_result_id in {works}"),
        ("work_stop", f"work_result_id in {works}"),
        ("work_result", f"job_id in {jobs}"),
        ("color_record_mix", f"color_record_id in (select color_record_id from color_record where job_id in {jobs})"),
        ("color_record", f"job_id in {jobs}"),
        ("job_lot", f"job_id in {jobs}"),
        ("job", f"item_id in {items}"),
        ("material_lot", f"item_id in {items}"),
        ("plate_spec", "plate_code like %(like)s"),
        ("anilox", "anilox_code like %(like)s"),
        ("ink_formula_component", "ink_formula_id in (select ink_formula_id from ink_formula where ink_code like %(like)s)"),
        ("ink_formula", "ink_code like %(like)s"),
        ("equipment", "equipment_code like %(like)s"),
        ("process", "process_code like %(like)s"),
        ("defect_code", "defect_code like %(like)s"),
        ("customer", "customer_code like %(like)s"),
        ("item", "item_code like %(like)s"),
    ]
    out: dict[str, int] = {}
    with psycopg.connect(appconn.dsn(), row_factory=dict_row) as c, c.cursor() as cur:   # 한 트랜잭션
        for table, where in steps:
            cur.execute(f"delete from {table} where {where}", p)
            if cur.rowcount:
                out[table] = cur.rowcount
    return out


def leftovers(db: Db, like: str = PREFIX + "%") -> dict[str, int]:
    """내 접두 데이터가 얼마나 남아 있는가 (잔여 0 확인)."""
    p = {"like": like}
    q = {
        "item": "select count(*) from item where item_code like %(like)s",
        "customer": "select count(*) from customer where customer_code like %(like)s",
        "defect_code": "select count(*) from defect_code where defect_code like %(like)s",
        "process": "select count(*) from process where process_code like %(like)s",
        "equipment": "select count(*) from equipment where equipment_code like %(like)s",
        "plate_spec": "select count(*) from plate_spec where plate_code like %(like)s",
        "anilox": "select count(*) from anilox where anilox_code like %(like)s",
        "ink_formula": "select count(*) from ink_formula where ink_code like %(like)s",
        "material_lot(공급사 LOT)": "select count(*) from material_lot where supplier_lot_no like %(like)s",
    }
    return {k: n for k, sql in q.items() if (n := db.v(sql, p))}


# ════════════════════════════════════════════════════════════════════════
# 4. 설계도 §3 계보 그림 → 기대 그래프 (상자 · 화살표 · 관계 이름 · `재고` 표시를 SVG 좌표에서 읽는다)
# ════════════════════════════════════════════════════════════════════════
def design_graph() -> dict:
    h = design_doc.html()
    sec = design_doc._section(h, "lineage", "arch")
    svg = sec[sec.index("<svg"):sec.index("</svg>")]
    heads = [(int(x), proc, table) for x, proc, table in re.findall(
        r'<text class="t-b" x="(\d+)" y="28"[^>]*>(.*?)</text><text class="t-s" x="\d+" y="44"[^>]*>(.*?)</text>', svg)]
    texts = [(cls, int(x), int(y), t) for cls, x, y, t in re.findall(
        r'<text class="(t|t-b|t-s)" x="(\d+)" y="(\d+)"[^>]*>(.*?)</text>', svg)]
    nodes: dict[str, dict] = {}
    for x, y, w, hh in re.findall(r'<rect class="bx" x="(\d+)" y="(\d+)" width="(\d+)" height="(\d+)"/>', svg):
        x, y, w, hh = int(x), int(y), int(w), int(hh)
        name = next(t for cls, tx, ty, t in texts if cls in ("t", "t-b") and x <= tx <= x + w and y <= ty <= y + hh)
        col = min(heads, key=lambda hd: abs(hd[0] - (x + w / 2)))
        nodes[name] = {"x": x, "y": y, "w": w, "h": hh, "process": col[1], "table": col[2]}
    block = svg[svg.index("<!-- 계보 선: 부모 → 자식 -->"):svg.index("<!-- 관계 이름")]
    rel_labels = [(tx, t) for cls, tx, ty, t in texts if cls == "t-s" and ty == 258]

    def rel_name(text: str) -> str:
        text = re.sub(r"\s*(N:1|1:N)$", "", text).strip()
        return "투입" if text.endswith("투입") else text

    def at(px: int, py: int, side: str) -> str:
        for name, n in nodes.items():
            edge_x = n["x"] + n["w"] if side == "right" else n["x"]
            if edge_x == px and n["y"] <= py <= n["y"] + n["h"]:
                return name
        raise SystemExit(f"설계도 §3 화살표의 끝점 ({px},{py}) 에 닿는 상자를 찾지 못했다 — 그림이 바뀌었는가")

    edges = []
    for d in re.findall(r'<path class="ln" d="([^"]+)"', block):
        m = re.match(r"M(\d+) (\d+)(?:H(\d+)|L(\d+) (\d+))$", d)
        x1, y1 = int(m.group(1)), int(m.group(2))
        x2, y2 = (int(m.group(3)), y1) if m.group(3) else (int(m.group(4)), int(m.group(5)))
        rel = rel_name(min(rel_labels, key=lambda r: abs(r[0] - (x1 + x2) / 2))[1])
        edges.append((at(x1, y1, "right"), at(x2, y2, "left"), rel))
    stock = []
    for cls, tx, ty, t in texts:
        if t == "재고":
            stock.append(next(name for name, n in nodes.items()
                              if n["y"] <= ty <= n["y"] + n["h"] and 0 <= tx - (n["x"] + n["w"]) <= 30))
    same_job = "같은 Job" in svg
    coa = "COA 발행" in svg
    return {"nodes": nodes, "edges": edges, "stock": stock, "same_job": same_job, "coa": coa,
            "arrows": design_doc.lineage_arrows(h)}


def build_design_scenario(flow: Flow, g: dict) -> dict[str, str]:
    """설계도 §3 예시를 화면 API 로 만든다. 돌려주는 것: 그림의 상자 이름 → 실제 번호.

    만드는 순서(그림을 왼쪽에서 오른쪽으로): 원재료 LOT 2(입고 + 입고검사 합격) → 같은 Job 의 인쇄 롤 2
    (LOT ① 은 두 롤에 투입, LOT ② 는 인쇄 롤 ② 에만) → splice 2:1 → 슬리팅 1:3 → 출하 LOT 1 에 슬리팅 ①② 스캔 → 승인(COA).
    Job 도 API(`POST /job/orders`)로 등록한다.
    """
    fg = flow.item("FG", "제품")
    flow.item("RM", "원재료")
    cu = flow.customer()
    job = flow.job(fg, cu, date.today() + timedelta(days=7))
    job_lot = flow.job_lot(job, planned=2)
    m: dict[str, str] = {"Job": job, "생산 LOT": job_lot}
    for name, n in g["nodes"].items():
        if n["table"] == "material_lot":
            m[name] = flow.lot(flow.code("RM"))
    for name, n in sorted(g["nodes"].items(), key=lambda kv: kv[1]["y"]):
        if n["process"] == "인쇄":
            parents = [p for p, c, _ in g["edges"] if c == name]
            m[name] = flow.print_roll(job, [m[p] for p in parents], job_lot=job_lot, input_qty="10")
    for name, n in g["nodes"].items():
        if n["process"] == "후가공":
            parents = [p for p, c, _ in g["edges"] if c == name]
            m[name] = flow.splice([m[p] for p in parents]) if len(parents) > 1 else flow.finishing(m[parents[0]])
    slit_parents = defaultdict(list)
    for p, c, rel in g["edges"]:
        if g["nodes"][c]["process"] == "슬리팅":
            slit_parents[p].append(c)
    for p, children in slit_parents.items():
        made = flow.slit(m[p], len(children))
        for name, no in zip(sorted(children, key=lambda c: g["nodes"][c]["y"]), made):   # 위에서 아래로 ①②③ = 분할 순번 1·2·3
            m[name] = no
    for name, n in g["nodes"].items():
        if n["table"] == "shipment":
            sh = flow.shipment(job, date.today())
            for p in sorted((p for p, c, _ in g["edges"] if c == name), key=lambda p: g["nodes"][p]["y"]):
                flow.scan(sh, m[p])
            m[name] = sh
            m["COA"] = flow.approve(sh)
    return m



# ════════════════════════════════════════════════════════════════════════
# 4b. 화면의 폼만으로 — HTML 폼을 읽어 브라우저처럼 그대로 제출한다 (JS 없이)
# ════════════════════════════════════════════════════════════════════════
class FormWalk:
    """화면을 열어(`GET`) 그 안의 `<form>` 을 찾고, 폼에 **있는** 입력칸만 채워 제출한다(`accept: text/html` → 303 → 다음 화면).

    폼에 그 입력칸이 없거나, 선택 목록에 그 값이 없거나, 쓰기 버튼이 비활성이면 실패다 — API 로는 되는데 화면으로는 못 하는 일을 잡는다.
    """

    def __init__(self, api: Api) -> None:
        self.api = api
        self.steps: list[str] = []

    def open(self, role: str, path: str, params: dict | None = None) -> tuple[str, str]:
        """화면을 연다. 303(스캔 진입의 주소 정리 등)은 따라간다. → (최종 주소, HTML)"""
        r = self.api.get(role, path, params)
        url = str(r.request.url)
        hops = 0
        while r.status_code == 303 and hops < 5:
            url = r.headers["location"]
            r = self.api.client(role).get(url, headers=HTML, follow_redirects=False)
            hops += 1
        if r.status_code != 200:
            raise FlowError(f"화면 {path} {params or ''} — HTTP {r.status_code}")
        return url, r.text

    @staticmethod
    def forms(html: str) -> list[dict]:
        out = []
        for attrs, inner in re.findall(r"<form\b([^>]*)>(.*?)</form>", html, re.S):
            a = dict(re.findall(r'([\w\-]+)="([^"]*)"', attrs))
            fid = a.get("id")
            scope = inner
            if fid:                                                # 폼 밖에 있으면서 form="id" 로 묶인 요소
                scope += "".join(re.findall(rf'<(?:input|button|select)\b[^>]*\bform="{re.escape(fid)}"[^>]*>', html))
            fields: list[list] = []
            options: dict[str, list[str]] = {}
            for tag in re.findall(r"<input\b[^>]*>", scope):
                t = dict(re.findall(r'([\w\-]+)="([^"]*)"', tag))
                if t.get("name") and " disabled" not in tag and t.get("type") not in ("submit", "button"):
                    fields.append([t["name"], t.get("value", "")])
            for name, body in re.findall(r'<select\b[^>]*\bname="([^"]+)"[^>]*>(.*?)</select>', scope, re.S):
                opts = re.findall(r'<option\b[^>]*\bvalue="([^"]*)"([^>]*)>', body)
                options[name] = [v for v, _ in opts]
                fields.append([name, next((v for v, rest in opts if "selected" in rest), opts[0][0] if opts else "")])
            for name in re.findall(r'<textarea\b[^>]*\bname="([^"]+)"', scope):
                fields.append([name, ""])
            buttons = [dict(re.findall(r'([\w\-]+)="([^"]*)"', b)) | {"_disabled": " disabled" in b}
                       for b in re.findall(r"<button\b[^>]*>", scope) if 'type="button"' not in b]
            out.append({"action": a.get("action", ""), "method": a.get("method", "get").lower(), "id": fid, "fields": fields,
                        "options": options, "buttons": buttons})
        return out

    def submit(self, role: str, page: tuple[str, str], action: str, values: dict, button: tuple[str, str] | None = None,
               method: str = "post", what: str = "") -> str:
        """`page` 화면에서 action 이 `action`(정규식)인 폼을 찾아 `values` 를 채워 제출한다. 처리 뒤의 화면 HTML 을 돌려준다."""
        url, html = page
        cands = [f for f in self.forms(html) if f["method"] == method and re.fullmatch(action, f["action"] or url.split("?")[0])]
        cands = [f for f in cands if all(any(n == k for n, _ in f["fields"]) for k in values)] or cands
        if not cands:
            raise FlowError(f"{what}: 화면 {url} 에 action `{action}` 인 {method} 폼이 없다")
        form = cands[0]
        names = [n for n, _ in form["fields"]]
        for k, v in values.items():
            if k not in names:
                raise FlowError(f"{what}: 폼(action {form['action']})에 입력칸 `{k}` 가 없다 — 있는 칸 {sorted(set(names))}")
            if k in form["options"] and str(v) not in form["options"][k]:
                raise FlowError(f"{what}: 선택칸 `{k}` 의 목록에 `{v}` 가 없다 (선택지 {len(form['options'][k])}개)")
        usable = [b for b in form["buttons"] if not b["_disabled"]]
        if method == "post" and form["buttons"] and not usable:
            raise FlowError(f"{what}: 쓰기 버튼이 비활성이다 (역할 {role})")
        data: dict[str, list[str]] = defaultdict(list)
        done: set[str] = set()
        for n, v in form["fields"]:
            if n in values and n not in done and not isinstance(values[n], list):
                data[n].append(str(values[n]))
                done.add(n)
            elif n not in values:
                data[n].append(v)
        if button:
            if not any(b.get("name") == button[0] and b.get("value") == button[1] for b in usable):
                raise FlowError(f"{what}: 폼에 `{button[0]}={button[1]}` 버튼이 없다")
            data[button[0]].append(button[1])
        target = form["action"] or url.split("?")[0]
        c = self.api.client(role)
        if method == "get":
            r = c.get(target, params=dict(data), headers=HTML, follow_redirects=False)
        else:
            origin = self.api.base_url or "http://testserver"
            r = c.post(target, data=dict(data), headers={**HTML, "referer": url if url.startswith("http") else origin + url},
                       follow_redirects=False)
            if r.status_code != 303:
                raise FlowError(f"{what}: 폼 제출 HTTP {r.status_code} (303 을 기대)")
        hops = 0
        while r.status_code == 303 and hops < 5:
            r = c.get(r.headers["location"], headers=HTML, follow_redirects=False)
            hops += 1
        if r.status_code != 200:
            raise FlowError(f"{what}: 처리 뒤 화면 HTTP {r.status_code}")
        if method == "post":
            m = re.search(r'<script type="application/json" id="flash-data">(.*?)</script>', r.text, re.S)
            flash = m.group(1) if m else ""
            if '"kind": "ok"' not in flash and '"kind":"ok"' not in flash:
                raise FlowError(f"{what}: 처리 뒤 알림이 성공이 아니다 — {text_of_html(flash)[:200] or '알림 없음'}")
        self.steps.append(what)
        return r.text


def build_design_by_forms(ctx: "Ctx", g: dict) -> tuple["Flow", dict[str, str]]:
    """설계도 §3 예시를 **화면의 폼만으로** 만든다 (기준정보 → Job → 입고·입고검사 → 인쇄 → splice → 슬리팅 → 출하 → 승인)."""
    db = ctx.db
    flow = ctx.flow()
    w = FormWalk(ctx.api)
    fg_code, rm_code, cu_code = flow.code("FG"), flow.code("RM"), flow.code("CU")
    for code, typ in ((fg_code, "제품"), (rm_code, "원재료")):
        w.submit("admin", w.open("admin", "/bas/items"), "/bas/items",
                 {"item_code": code, "item_name": flow.label(typ), "item_type": typ, "unit": "m"}, what=f"품목 등록({typ})")
    w.submit("admin", w.open("admin", "/bas/customers"), "/bas/customers",
             {"customer_code": cu_code, "customer_name": flow.label("고객")}, what="고객 등록")
    fg = db.v("select item_id from item where item_code = %s", (fg_code,))
    cu = db.v("select customer_id from customer where customer_code = %s", (cu_code,))
    w.submit("prod", w.open("prod", "/job/orders"), "/job/orders",
             {"item_id": fg, "customer_id": cu, "order_qty": "1000", "due_date": str(date.today() + timedelta(days=7))}, what="작업지시 등록")
    job = db.v("select job_no from job where item_id = %s order by job_id desc limit 1", (fg,))
    flow.jobs.append(job)
    w.submit("prod", w.open("prod", "/job/mapping", {"no": job}), "/job/mapping", {"planned_roll_count": "2"}, what="Job-Lot-Roll 매핑 등록")
    job_lot = db.v("select lot_no from job_lot l join job j on j.job_id = l.job_id where j.job_no = %s", (job,))
    m: dict[str, str] = {"Job": job, "생산 LOT": job_lot}
    for name, n in sorted(g["nodes"].items(), key=lambda kv: kv[1]["y"]):
        if n["table"] != "material_lot":
            continue
        sl = flow.code(f"SL{flow.seq()}")
        w.submit("prod", w.open("prod", "/mat/receipts"), "/mat/receipts",
                 {"item_code": rm_code, "supplier_name": flow.label("공급처"), "supplier_lot_no": sl, "received_qty": "500"}, what="입고 등록")
        lot = db.v("select lot_no from material_lot where supplier_lot_no = %s", (sl,))
        w.submit("qc", w.open("qc", "/mat/inspections", {"no": lot}), "/mat/inspections", {}, button=("result", "합격"), what="입고검사 합격")
        m[name] = lot
        flow.kind[lot] = "L"
    for name, n in sorted(g["nodes"].items(), key=lambda kv: kv[1]["y"]):
        if n["process"] != "인쇄":
            continue
        w.submit("prod", w.open("prod", "/pop/work", {"no": job}), "/pop/work/start", {"lot_no": job_lot}, what="작업 시작")
        wid = db.v("select max(work_result_id) from work_result w join job j on j.job_id = w.job_id where j.job_no = %s", (job,))
        for p in sorted((p for p, c, _ in g["edges"] if c == name), key=lambda p: g["nodes"][p]["y"]):
            w.submit("field", w.open("field", "/mat/inputs", {"work_id": str(wid)}), "/mat/inputs", {"lot_no": m[p], "input_qty": "10"},
                     what="자재 투입 스캔")
        w.submit("prod", w.open("prod", "/pop/work"), f"/pop/work/{wid}/finish", {"output_qty": "100"}, what="작업 종료")
        m[name] = db.v("select roll_no from roll where work_result_id = %s", (wid,))
    for name, n in g["nodes"].items():
        if n["process"] != "후가공":
            continue
        parents = sorted((p for p, c, _ in g["edges"] if c == name), key=lambda p: g["nodes"][p]["y"])
        page = w.open("field", "/rll/finishing", {"add": m[parents[0]]})          # 롤을 하나씩 스캔해 쌓는다 (스캔칸 = GET 폼)
        for p in parents[1:]:
            html = w.submit("field", page, "/rll/finishing", {"add": m[p]}, method="get", what="후가공 부모 롤 스캔")
            page = ("/rll/finishing?rolls=" + ",".join(m[x] for x in parents[:parents.index(p) + 1]), html)
        w.submit("field", page, "/rll/finishing(/splice)?", {}, what="splice 등록")
        m[name] = db.v("""select r.roll_no from roll r join job j on j.job_id = r.job_id
                           where j.job_no = %s and r.process_type = '후가공' order by r.roll_id desc limit 1""", (job,))
    for name, n in g["nodes"].items():
        if n["process"] != "후가공":
            continue
        kids = sorted((c for p, c, _ in g["edges"] if p == name), key=lambda c: g["nodes"][c]["y"])
        w.submit("prod", w.open("prod", "/rll/slitting", {"no": m[name]}), "/rll/slitting", {"count": str(len(kids))}, what="슬리팅 분할 등록")
        made = [r["roll_no"] for r in db.q("""select c.roll_no from roll_genealogy g join roll p on p.roll_id = g.parent_roll_id
                                               join roll c on c.roll_id = g.child_roll_id where p.roll_no = %s order by c.slit_seq""", (m[name],))]
        if len(made) != len(kids):
            raise FlowError(f"슬리팅 분할: 자식 {len(made)}개 (기대 {len(kids)})")
        m.update(dict(zip(kids, made)))
    for name, n in g["nodes"].items():
        if n["table"] != "shipment":
            continue
        w.submit("field", w.open("field", "/shp/shipments"), "/shp/shipments", {"job_no": job, "ship_date": str(date.today())}, what="출하 등록")
        sh = db.v("select shipment_no from shipment s join job j on j.job_id = s.job_id where j.job_no = %s order by shipment_id desc limit 1", (job,))
        for p in sorted((p for p, c, _ in g["edges"] if c == name), key=lambda p: g["nodes"][p]["y"]):
            w.submit("field", w.open("field", "/shp/shipments", {"no": sh}), f"/shp/shipments/{sh}/rolls", {"roll_no": m[p]}, what="출하 롤 스캔")
        w.submit("admin", w.open("admin", "/shp/approvals"), f"/shp/approvals/{sh}/approve", {}, what="출하 승인")
        m[name] = sh
    m["_steps"] = w.steps
    return flow, m

# ════════════════════════════════════════════════════════════════════════
# 5. 독립 SQL — 계보 행 · 추적 (app/lineage.py 를 쓰지 않는다)
# ════════════════════════════════════════════════════════════════════════
#: 계보 행을 번호로 읽는다 (부모 번호, 자식 번호, 관계)
EDGE_SQL = """
select g.genealogy_id,
       case when g.parent_material_lot_id is not null
            then (select m.lot_no from material_lot m where m.material_lot_id = g.parent_material_lot_id)
            else (select r.roll_no from roll r where r.roll_id = g.parent_roll_id) end as parent_no,
       case when g.child_roll_id is not null
            then (select r.roll_no from roll r where r.roll_id = g.child_roll_id)
            else (select s.shipment_no from shipment s where s.shipment_id = g.child_shipment_id) end as child_no,
       g.relation
  from roll_genealogy g
"""

#: 추적 — **노드**를 따라 번져 가는 재귀 조회 (lineage 의 화살표 걷기와 다른 식으로 짰다).
#: `seen` = 출발 노드에서 닿는 노드 전부. 결과 = 그 노드들에 붙은(역방향: 자식 쪽이 seen, 정방향: 부모 쪽이 seen) 화살표.
TRACE_SQL = """
with recursive arrow as (
    select g.genealogy_id,
           case when g.parent_material_lot_id is not null then 'L' || g.parent_material_lot_id
                else 'R' || g.parent_roll_id end as p,
           case when g.child_roll_id is not null then 'R' || g.child_roll_id
                else 'S' || g.child_shipment_id end as c
      from roll_genealogy g
), seen (node) as (
    select %(start)s::text
    union
    select a.{far} from arrow a join seen s on a.{near} = s.node
)
select a.genealogy_id from arrow a where a.{near} in (select node from seen)
"""

NODE_KEY_SQL = """
select 'L' || material_lot_id as k from material_lot where lot_no = %(no)s
union all select 'R' || roll_id from roll where roll_no = %(no)s
union all select 'S' || shipment_id from shipment where shipment_no = %(no)s
"""


def sql_edges_of_tag(db: Db, tag: str) -> set[tuple[str, str, str]]:
    ids = [r["genealogy_id"] for r in db.q(SCOPE_ROWS_SQL, {"like": tag + "-%"})]
    if not ids:
        return set()
    return {(r["parent_no"], r["child_no"], r["relation"]) for r in db.q(EDGE_SQL + " where g.genealogy_id = any(%s)", (ids,))}


def sql_trace(db: Db, no: str, direction: str) -> dict:
    """독립 재귀 SQL 로 추적. direction = forward | backward. → {edges, lots, ships, stock}."""
    keys = db.q(NODE_KEY_SQL, {"no": no})
    if len(keys) != 1:
        return {"edges": set(), "lots": set(), "ships": set(), "stock": set(), "error": f"번호 {no} 의 노드 {len(keys)}개"}
    near, far = ("c", "p") if direction == "backward" else ("p", "c")
    ids = [r["genealogy_id"] for r in db.q(TRACE_SQL.format(near=near, far=far), {"start": keys[0]["k"]})]
    rows = db.q(EDGE_SQL + " where g.genealogy_id = any(%s)", (ids,)) if ids else []
    edges = {(r["parent_no"], r["child_no"], r["relation"]) for r in rows}
    nodes = {no} | {e[0] for e in edges} | {e[1] for e in edges}
    lots = {r["lot_no"] for r in db.q("select lot_no from material_lot where lot_no = any(%s)", (list(nodes),))}
    ships = {r["shipment_no"] for r in db.q("select shipment_no from shipment where shipment_no = any(%s)", (list(nodes),))}
    # 재고 = 닿은 롤 가운데 어떤 화살표의 부모도 아닌 롤 (다음 공정에도 출하에도 쓰이지 않았다)
    stock = {r["roll_no"] for r in db.q(
        """select r.roll_no from roll r
            where r.roll_no = any(%s)
              and not exists (select 1 from roll_genealogy x where x.parent_roll_id = r.roll_id)""", (list(nodes),))}
    return {"edges": edges, "lots": lots, "ships": ships, "stock": stock}


def model_trace(flow_edges: set[tuple[str, str, str]], kind: dict[str, str], no: str, direction: str) -> dict:
    """내가 API 로 요청한 화살표(모델)만으로 파이썬에서 따라간다 — 세 번째 계산."""
    seen, frontier = {no}, [no]
    while frontier:
        cur = frontier.pop()
        for p, c, _ in flow_edges:
            nxt = p if (direction == "backward" and c == cur) else c if (direction == "forward" and p == cur) else None
            if nxt and nxt not in seen:
                seen.add(nxt)
                frontier.append(nxt)
    edges = {e for e in flow_edges if (e[1] if direction == "backward" else e[0]) in seen}
    has_child = {p for p, _, _ in flow_edges}
    return {"edges": edges, "lots": {n for n in seen if kind.get(n) == "L"}, "ships": {n for n in seen if kind.get(n) == "S"},
            "stock": {n for n in seen if kind.get(n) == "R" and n not in has_child}}


# ── 화면(HTML) 읽기 ─────────────────────────────────────────────────────
def main_of(html: str) -> str:
    """화면의 본문(`<main>`)만 — 왼쪽 메뉴와 오른쪽 계약 패널(계약 문장에 `미수집` 이 적혀 있다)을 뺀다."""
    a = html.find("<main")
    b = html.find("</main>", a)
    return html[a:b] if a >= 0 and b > a else html


def text_of_html(html: str) -> str:
    html = re.sub(r"<(script|style)\b.*?</\1>", " ", html, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def screen_trace(api: Api, no: str, direction: str, role: str = "admin") -> dict:
    """LOT 추적 화면(`GET /trc/trace/forward|backward?no=`)의 결과를 읽는다."""
    r = api.get(role, f"/trc/trace/{direction}", {"no": no})
    out = {"status": r.status_code, "edges": set(), "lots": set(), "ships": set(), "stock": set(), "sql": api.last["sql"],
           "writes": api.last["writes"], "n_edges": None}
    if r.status_code != 200:
        return out
    body = main_of(r.text)
    for blk in re.findall(r'<div class="edge">(.*?)</div>', body, re.S):
        codes = re.findall(r"<code>([^<]+)</code>", blk)
        arrow = text_of_html(re.search(r'<span class="arrow">(.*?)</span>', blk, re.S).group(1))
        rel = next((x for x in RELATIONS if re.search(rf"(^|\s){re.escape(x)}(\s|$)", arrow)), arrow)
        parent, child = (codes[0], codes[1]) if direction == "forward" else (codes[1], codes[0])
        out["edges"].add((parent, child, rel))

    def row(title: str) -> set[str] | None:
        m = re.search(rf'<div class="row"><strong>{title} (\d+)[건개]</strong>(.*?)</div>', body, re.S)
        if not m:
            return None
        codes = set(re.findall(r"<code>([^<]+)</code>", m.group(2)))
        if len(codes) != int(m.group(1)):
            out.setdefault("notes", []).append(f"{title} 제목 {m.group(1)} ≠ 표시 {len(codes)}")
        return codes

    out["lots"] = row("닿은 원재료 LOT") or set()
    out["ships"] = row("닿은 출하 LOT") or set()
    out["stock"] = row("재고로 남은 롤") or set()
    m = re.search(r"화살표 (\d+)줄 · 노드 (\d+)개", body)
    if m:
        out["n_edges"], out["n_nodes"] = int(m.group(1)), int(m.group(2))
    out["text"] = text_of_html(body)
    return out


def compare_trace(api: Api, db: Db, flow: Flow, no: str, direction: str) -> list[str]:
    """한 번호 · 한 방향 — 화면 vs 독립 SQL vs 모델. 다른 점을 글로 돌려준다(없으면 빈 목록)."""
    scr, mine, model = screen_trace(api, no, direction), sql_trace(db, no, direction), \
        model_trace(flow.edges, flow.kind, no, direction)
    diffs: list[str] = []
    if scr["status"] != 200:
        return [f"{direction} {no}: 화면 HTTP {scr['status']}"]
    if mine.get("error"):
        diffs.append(f"{direction} {no}: {mine['error']}")
    keys = ("edges", "lots") if direction == "backward" else ("edges", "ships", "stock")
    for key in keys:
        if scr[key] != mine[key]:
            diffs.append(f"{direction} {no} {key}: 화면 {len(scr[key])} ≠ 독립 SQL {len(mine[key])} "
                         f"(화면에만 {sorted(scr[key] - mine[key])[:2]} · SQL 에만 {sorted(mine[key] - scr[key])[:2]})")
        if mine[key] != model[key]:
            diffs.append(f"{direction} {no} {key}: 독립 SQL {len(mine[key])} ≠ 모델 {len(model[key])} "
                         f"(SQL 에만 {sorted(mine[key] - model[key])[:2]} · 모델에만 {sorted(model[key] - mine[key])[:2]})")
    if scr["n_edges"] is not None and scr["n_edges"] != len(scr["edges"]):
        diffs.append(f"{direction} {no}: 화면 제목의 화살표 {scr['n_edges']}줄 ≠ 그려진 {len(scr['edges'])}줄")
    diffs.extend(f"{direction} {no}: {n}" for n in scr.get("notes", []))
    return diffs


def longest_path(edges: set[tuple[str, str, str]]) -> int:
    """모델 그래프에서 가장 긴 길의 화살표 수."""
    children = defaultdict(list)
    for p, c, _ in edges:
        children[p].append(c)
    memo: dict[str, int] = {}

    def depth(n: str) -> int:
        if n not in memo:
            memo[n] = 1 + max((depth(c) for c in children[n]), default=-1) if children[n] else 0
        return memo[n]

    return max((depth(n) for n in list(children)), default=0)


# ════════════════════════════════════════════════════════════════════════
# 6. 임의 계보 — 깊이·분기를 키운다 (5단 이상 · 다중 splice · 한 원재료 LOT 이 여러 Job 으로 · 부분 출하 · 취소 출하)
# ════════════════════════════════════════════════════════════════════════
def build_random_lineage(flow: Flow, rng: random.Random, n_jobs: int = 2) -> dict:
    fg = flow.item("FG", "제품")
    flow.item("RM", "원재료")
    cu = flow.customer()
    raw = flow.code("RM")
    lots = [flow.lot(raw) for _ in range(rng.randint(3, 5))]
    unused_lot = flow.lot(raw)                                 # 투입되지 않은 LOT (정방향 추적 0건)
    jobs = [flow.job(fg, cu, date.today() + timedelta(days=rng.randint(1, 20))) for _ in range(n_jobs)]
    stock: dict[str, list[str]] = {j: [] for j in jobs}
    shared = lots[0]                                           # 모든 Job 에 들어가는 LOT — 한 원재료 LOT 이 여러 Job 으로
    for j in jobs:
        for _ in range(rng.randint(2, 4)):
            picked = {shared} if rng.random() < 0.6 else set()
            picked |= set(rng.sample(lots, rng.randint(1, min(3, len(lots)))))
            stock[j].append(flow.print_roll(j, sorted(picked)))
        if not any((shared, r, "투입") in flow.edges for r in stock[j]):
            stock[j].append(flow.print_roll(j, [shared]))

    def take(j: str, n: int) -> list[str]:
        picked = rng.sample(stock[j], n)
        for r in picked:
            stock[j].remove(r)
        return picked

    # 깊은 줄기 하나를 일부러 만든다: 인쇄 → 후가공 → 슬리팅(3) → splice(2) → 후가공 → 슬리팅(2) → splice(나머지와) …
    j0 = jobs[0]
    a = flow.finishing(take(j0, 1)[0])
    s1 = flow.slit(a, 3)
    b = flow.splice(s1[:2])
    c = flow.finishing(b)
    s2 = flow.slit(c, 2)
    d = flow.splice([s2[0], s1[2]])
    stock[j0] += [d, s2[1]]
    stats = {"splice": 2, "slit": 2, "finishing": 2, "cross_job_splice": 0}
    # 임의 조작
    for _ in range(rng.randint(5, 9)):
        j = rng.choice(jobs)
        if not stock[j]:
            continue
        op = rng.choice(["finishing", "splice", "splice", "slit", "slit"])
        if op == "splice" and len(stock[j]) >= 2:
            stock[j].append(flow.splice(take(j, rng.randint(2, min(3, len(stock[j]))))))
            stats["splice"] += 1
        elif op == "slit":
            stock[j] += flow.slit(take(j, 1)[0], rng.randint(2, 4))
            stats["slit"] += 1
        else:
            stock[j].append(flow.finishing(take(j, 1)[0]))
            stats["finishing"] += 1
    if n_jobs >= 2 and stock[jobs[0]] and stock[jobs[1]]:      # 서로 다른 Job 의 롤을 잇는다 (D-203: Job 을 지정)
        x, y = take(jobs[0], 1)[0], take(jobs[1], 1)[0]
        stock[jobs[1]].append(flow.splice([x, y], job_no=jobs[1]))
        stats["cross_job_splice"] = 1
    # 부분 출하 · 등록만 한 출하 · 취소한 출하
    ships = {"approved": [], "registered": [], "cancelled": []}
    for j in jobs:
        avail = list(stock[j])
        rng.shuffle(avail)
        if len(avail) >= 2:
            sh = flow.shipment(j, date.today())
            for r in avail[:max(1, len(avail) // 2)]:
                flow.scan(sh, r)
                stock[j].remove(r)
            flow.approve(sh)
            ships["approved"].append(sh)
        rest = list(stock[j])
        if rest:
            sh = flow.shipment(j, date.today())
            flow.scan(sh, rest[0])
            if rng.random() < 0.5:
                flow.cancel_shipment(sh)                       # 롤은 다시 재고
                ships["cancelled"].append(sh)
            else:
                stock[j].remove(rest[0])
                ships["registered"].append(sh)
    return {"lots": lots, "unused_lot": unused_lot, "jobs": jobs, "ships": ships, "ops": stats,
            "depth": longest_path(flow.edges), "edges": len(flow.edges)}


# ════════════════════════════════════════════════════════════════════════
# 7. 정적 분석 — 라우트가 쓰는 테이블 (소스에서 SQL 쓰기 문장을 찾고, 부르는 함수를 따라 들어간다)
# ════════════════════════════════════════════════════════════════════════
_SRC_WRITE_RE = re.compile(
    r"\b(insert\s+into|delete\s+from)\s+(\{[^}]+\}|\"?[a-z_][a-z0-9_]*\"?)"
    r"|\b(update)\s+(\{[^}]+\}|[a-z_][a-z0-9_]*)\s+set\b", re.I)


def _scan_sql_text(text: str, resolve) -> set[str]:
    out: set[str] = set()
    for m in _SRC_WRITE_RE.finditer(text):
        table = (m.group(2) or m.group(4)).strip('"')
        before = text[max(0, m.start() - 16):m.start()].lower()
        if m.group(3) and re.search(r"\b(for|key|do)\s*$", before):
            continue
        if table.startswith("{"):
            table = resolve(table.strip("{}").strip())
        out.add(str(table).lower())
    return out


def tables_written_by(fn, _seen: set | None = None) -> set[str]:
    """함수 `fn` 이 쓰는 테이블 — 그 소스의 SQL 쓰기 문장 + 부르는 `lcomfine.*` 함수(재귀). 못 푼 동적 이름은 `?이름`."""
    seen = _seen if _seen is not None else set()
    fn = inspect.unwrap(fn)
    if fn in seen or not (inspect.isfunction(fn) or inspect.ismethod(fn)):
        return set()
    seen.add(fn)
    try:
        src = textwrap.dedent(inspect.getsource(fn))
        tree = ast.parse(src)
    except (OSError, TypeError, SyntaxError):
        return set()
    try:
        cv = inspect.getclosurevars(fn)
        scope = {**cv.globals, **cv.nonlocals}
    except (TypeError, ValueError):
        scope = dict(getattr(fn, "__globals__", {}))
    scope = {**getattr(fn, "__globals__", {}), **scope}

    def lookup(dotted: str):
        parts = dotted.split(".")
        if parts[0] not in scope:
            return None
        obj = scope[parts[0]]
        for p in parts[1:]:
            if not hasattr(obj, p):
                return None
            obj = getattr(obj, p)
        return obj

    def resolve(expr: str) -> str:
        obj = lookup(expr) if re.fullmatch(r"[A-Za-z_][\w.]*", expr) else None
        return obj if isinstance(obj, str) else f"?{expr}"

    out = _scan_sql_text(src, resolve)

    def dotted(node) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            base = dotted(node.value)
            return f"{base}.{node.attr}" if base else None
        return None

    names = {d for node in ast.walk(tree) if isinstance(node, (ast.Name, ast.Attribute)) and (d := dotted(node))}
    for name in sorted(names):
        obj = lookup(name)
        if isinstance(obj, str):                                 # 모듈 상수에 담긴 SQL
            out |= _scan_sql_text(obj, resolve)
        elif callable(obj):
            try:
                target = inspect.unwrap(obj)
            except ValueError:
                continue
            if (inspect.isfunction(target) or inspect.ismethod(target)) and (getattr(target, "__module__", None) or "").startswith("lcomfine."):
                out |= tables_written_by(target, seen)
    return out


def store_tables() -> dict[str, set[str]]:
    spec = contracts.db_tables()
    out: dict[str, set[str]] = defaultdict(set)
    for t in spec.values():
        out[t.store].add(t.name)
    return out


def allowed_tables(process: str) -> set[str] | None:
    """설계도 §2 표의 「쓰는 저장소」 → 그 프로세스가 쓸 수 있는 테이블. `공통`(시스템 관리)은 SYS. 모르는 프로세스는 None."""
    stores = store_tables()
    if process == "공통":
        return set(stores["SYS"])
    p = design_doc.processes().get(process)
    if p is None:
        return None
    out: set[str] = set()
    for d in p["writes"]:
        out |= stores[d]
    return out


def business_tables() -> set[str]:
    stores = store_tables()
    return set().union(*(stores[d] for d in BUSINESS_STORES))


def api_routes(app) -> list[tuple[str, str, object]]:
    """앱의 (메서드, 경로, 엔드포인트 함수). 이 FastAPI 는 `include_router` 한 라우터를 `app.routes` 에 풀지 않고
    한 덩어리(`original_router`)로 두므로 안으로 들어가며 편다."""
    out: list[tuple[str, str, object]] = []

    def walk(routes, prefix: str = "") -> None:
        for r in routes:
            inner = getattr(r, "original_router", None)
            if inner is not None:
                walk(inner.routes, prefix + (getattr(getattr(r, "include_context", None), "prefix", "") or ""))
                continue
            endpoint, path = getattr(r, "endpoint", None), getattr(r, "path", None)
            if endpoint is None or path is None:
                continue
            for m in sorted(getattr(r, "methods", None) or ()):
                if m in ("GET", "POST", "PUT", "PATCH", "DELETE"):
                    out.append((m, prefix + path, endpoint))

    walk(app.routes)
    return out


# ════════════════════════════════════════════════════════════════════════
# 8. 게이트별 검사
# ════════════════════════════════════════════════════════════════════════
class Ctx:
    """검사 한 번의 공용 물건 — API · DB · 만든 흐름들(끝나면 전부 지운다)."""

    def __init__(self) -> None:
        self.db = Db()
        self.api = Api()
        self.flows: list[Flow] = []
        self._design: tuple[Flow, dict, dict] | None = None

    def flow(self) -> Flow:
        f = Flow(self.api, self.db)
        self.flows.append(f)
        return f

    def design(self) -> tuple[Flow, dict, dict]:
        """설계도 §3 예시 한 벌 (G-06·G-07·G-08·G-05 가 같이 쓴다). (flow, 그림, 상자 이름 → 번호)"""
        if self._design is None:
            g = design_graph()
            flow = self.flow()
            self._design = (flow, g, build_design_scenario(flow, g))
        return self._design

    def cleanup(self) -> dict[str, int]:
        total: dict[str, int] = defaultdict(int)
        for f in self.flows:
            for k, n in purge(self.db, f.tag + "-%").items():
                total[k] += n
        return dict(total)

    def close(self) -> None:
        self.db.close()


# ── G-06 계보 재현 ──────────────────────────────────────────────────────
def check_g06(ctx: Ctx, rep: Report) -> None:
    flow, g, m = ctx.design()
    inv = {v: k for k, v in m.items()}
    rows = ctx.db.q(SCOPE_ROWS_SQL, {"like": flow.tag + "-%"})
    rep.add("G-06", "§3 예시를 API 로 재현 — roll_genealogy 행 수 = 그림의 화살표 수", len(rows) == g["arrows"] == len(g["edges"]),
            f"DB {len(rows)}행 · 설계도 화살표 {g['arrows']}개 (Job {m['Job']} — POST /job/orders 로 등록)")
    by_rel: dict[str, int] = defaultdict(int)
    for r in rows:
        by_rel[r["relation"]] += 1
    want_rel: dict[str, int] = defaultdict(int)
    for _, _, rel in g["edges"]:
        want_rel[rel] += 1
    rep.add("G-06", "관계별 행 수 = 그림 (투입 · splice · 슬리팅 · 출하)", dict(by_rel) == dict(want_rel),
            "DB " + " · ".join(f"{k} {v}" for k, v in sorted(by_rel.items()))
            + " / 그림 " + " · ".join(f"{k} {v}" for k, v in sorted(want_rel.items())))
    got = {(inv.get(p, p), inv.get(c, c), rel) for p, c, rel in sql_edges_of_tag(ctx.db, flow.tag)}
    want = set(g["edges"])
    rep.add("G-06", "화살표마다 부모 → 자식 · 관계 = 그림", got == want,
            f"일치 {len(got & want)}/{len(want)}" + (f" · DB 에만 {sorted(got - want)[:2]} · 그림에만 {sorted(want - got)[:2]}" if got != want else ""))
    # 노드: 종류·공정 구분·같은 Job
    bad = []
    for name, n in g["nodes"].items():
        no = m.get(name)
        if n["table"] == "material_lot":
            ok = ctx.db.v("select count(*) from material_lot where lot_no = %s and insp_status = '합격'", (no,)) == 1
        elif n["table"] == "roll":
            ok = ctx.db.v("select count(*) from roll where roll_no = %s and process_type = %s", (no, n["process"])) == 1
        else:
            ok = ctx.db.v("select count(*) from shipment where shipment_no = %s", (no,)) == 1
        if not ok:
            bad.append(name)
    print_jobs = {r["job_no"] for r in ctx.db.q(
        "select j.job_no from roll r join job j on j.job_id = r.job_id where r.roll_no = any(%s)",
        ([m[k] for k, n in g["nodes"].items() if n["process"] == "인쇄"],))}
    n_by = defaultdict(int)
    for n in g["nodes"].values():
        n_by[n["process"]] += 1
    rep.add("G-06", "노드 = 그림의 상자 (테이블 · 공정 구분 · 인쇄 롤은 같은 Job)",
            not bad and (print_jobs == {m["Job"]} or not g["same_job"]),
            " · ".join(f"{k} {v}" for k, v in n_by.items()) + f" · 인쇄 롤의 Job {sorted(print_jobs)}" + (f" · 어긋난 상자 {bad}" if bad else ""))
    # 재고 · 출하 · COA
    states = {r["roll_no"]: r for r in ctx.db.q(
        """select r.roll_no,
                  exists (select 1 from roll_genealogy x where x.parent_roll_id = r.roll_id and x.child_shipment_id is not null) as shipped,
                  exists (select 1 from roll_genealogy x where x.parent_roll_id = r.roll_id and x.child_roll_id is not null) as consumed,
                  (select v.state from v_roll_state v where v.roll_id = r.roll_id) as view_state
             from roll r where r.roll_no = any(%s)""", ([m[k] for k, n in g["nodes"].items() if n["process"] == "슬리팅"],))}
    stock_ok = all(not states[m[s]]["shipped"] and not states[m[s]]["consumed"] and states[m[s]]["view_state"] == "재고"
                   for s in g["stock"])
    shipped = [k for k, n in g["nodes"].items() if n["process"] == "슬리팅" and k not in g["stock"]]
    ship_ok = all(states[m[s]]["shipped"] and states[m[s]]["view_state"] == "출하" for s in shipped)
    sh = ctx.db.q1("select status, coa_no, coa_issued_at from shipment where shipment_no = %s", (m["출하 LOT"],))
    rep.add("G-06", "슬리팅 ③ 은 재고 · ①② 는 출하 · 출하 LOT 승인 = COA 발행",
            stock_ok and ship_ok and sh["status"] == "승인" and bool(sh["coa_no"]),
            f"재고 {[k for k in g['stock']]} {'맞음' if stock_ok else '어긋남'} · 출하 {len(shipped)}개 {'맞음' if ship_ok else '어긋남'} · "
            f"출하 LOT {sh['status']} · COA {sh['coa_no'] or '없음'}")


    # 같은 예시를 화면의 폼만으로 한 번 더 (goal.md §1-3 「화면 조작만으로」)
    try:
        f2, m2 = build_design_by_forms(ctx, g)
        inv2 = {v: k for k, v in m2.items() if isinstance(v, str)}
        got2 = {(inv2.get(p, p), inv2.get(c, c), rel) for p, c, rel in sql_edges_of_tag(ctx.db, f2.tag)}
        rep.add("G-06", "§3 예시를 화면의 폼만으로 재현 (화면을 열어 그 안의 폼을 그대로 제출 · JS 없이)", got2 == want,
                f"폼 제출 {len(m2['_steps'])}단계 · roll_genealogy {len(got2)}행 · 그림과 일치 {len(got2 & want)}/{len(want)}")
    except FlowError as exc:
        rep.add("G-06", "§3 예시를 화면의 폼만으로 재현 (화면을 열어 그 안의 폼을 그대로 제출 · JS 없이)", FAIL, f"중단 — {str(exc)[:260]}")


# ── G-07 추적 ───────────────────────────────────────────────────────────
def guard_probes(ctx: Ctx) -> list[tuple[str, bool, str]]:
    """순환 · 자기 부모 · 재출하 · 소진 롤 재사용을 API 로 두드린다. (이름, 막혔는가, 실측)"""
    api, db = ctx.api, ctx.db
    flow = ctx.flow()
    fg, fg2 = flow.item("FG", "제품"), flow.item("FG2", "제품")
    flow.item("RM", "원재료")
    cu = flow.customer()
    raw = flow.code("RM")
    lot = flow.lot(raw)
    job, job2 = flow.job(fg, cu, date.today()), flow.job(fg2, cu, date.today())
    p1, p2, p3, p4, p5 = (flow.print_roll(job, [lot]) for _ in range(5))
    q1 = flow.print_roll(job2, [lot])
    out: list[tuple[str, bool, str]] = []

    def n_rows() -> tuple[int, int]:
        """(내 계보 행 수, 내 롤 수) — 막힌 요청 뒤에 둘 다 그대로여야 한다 (롤만 생기고 계보가 빠지는 반쪽 쓰기가 없다)."""
        return (len(db.q(SCOPE_ROWS_SQL, {"like": flow.tag + "-%"})),
                db.v("""select count(*) from roll r join job j on j.job_id = r.job_id join item i on i.item_id = j.item_id
                         where i.item_code like %s""", (flow.tag + "-%",)))

    def probe(name: str, role: str, path: str, data: dict) -> None:
        before = n_rows()
        status, body = api.post(role, path, data)
        after = n_rows()
        out.append((name, status == 422 and after == before, f"HTTP {status} · (계보 행, 롤) {before}→{after} · {str(body.get('message', body))[:60]}"))

    probe("자기 자신과 splice (같은 롤 두 번)", "prod", "/rll/finishing/splice", {"roll_no": [p1, p1]})
    f1 = flow.finishing(p1)                                   # p1 소진
    probe("소진된 롤을 다시 후가공", "field", "/rll/finishing", {"roll_no": p1})
    probe("소진된 롤을 splice 의 부모로", "prod", "/rll/finishing/splice", {"roll_no": [p1, p2]})
    probe("소진된 롤을 다시 슬리팅", "prod", "/rll/slitting", {"roll_no": p1, "count": "2"})
    s = flow.slit(f1, 2)
    probe("슬리팅한 롤을 다시 슬리팅 (다른 작업에서 재사용)", "prod", "/rll/slitting", {"roll_no": f1, "count": "2"})
    sh1, sh2 = flow.shipment(job, date.today()), flow.shipment(job, date.today())
    probe("소진된 롤 출하", "field", f"/shp/shipments/{sh1}/rolls", {"roll_no": f1})
    flow.scan(sh1, s[0])
    probe("같은 출하에 같은 롤 두 번", "field", f"/shp/shipments/{sh1}/rolls", {"roll_no": s[0]})
    probe("이미 출하된 롤을 다른 출하에 (재출하)", "field", f"/shp/shipments/{sh2}/rolls", {"roll_no": s[0]})
    probe("출하된 롤을 슬리팅", "prod", "/rll/slitting", {"roll_no": s[0], "count": "2"})
    probe("출하된 롤을 후가공", "field", "/rll/finishing", {"roll_no": s[0]})
    probe("출하된 롤을 splice 의 부모로", "prod", "/rll/finishing/splice", {"roll_no": [s[0], p2]})
    probe("다른 Job 의 롤을 출하 LOT 에", "field", f"/shp/shipments/{sh1}/rolls", {"roll_no": q1})
    flow.inspect(p3, "불합격", "9.9")
    probe("최신 검사가 불합격인 롤 출하", "field", f"/shp/shipments/{sh1}/rolls", {"roll_no": p3})
    probe("없는 롤 번호 스캔", "field", f"/shp/shipments/{sh1}/rolls", {"roll_no": flow.code("NOPE")})
    probe("원재료 LOT 번호를 롤 자리에 스캔", "field", f"/shp/shipments/{sh1}/rolls", {"roll_no": lot})
    flow.approve(sh1)
    probe("승인된 출하에 롤 추가", "field", f"/shp/shipments/{sh1}/rolls", {"roll_no": s[1]})
    before = n_rows()
    status, body = api.post("field", f"/shp/shipments/{sh1}/cancel")
    out.append(("승인된 출하 취소", status == 422 and n_rows() == before, f"HTTP {status} · (계보 행, 롤) {before}→{n_rows()}"))
    probe("splice 부모가 서로 다른 Job 인데 Job 미지정", "prod", "/rll/finishing/splice", {"roll_no": [p2, q1]})
    # 불합격·검사 대기 LOT 투입
    lot_wait = flow.receive(raw)
    wid = flow.start(job)
    status, body = api.post("field", "/mat/inputs", {"work_id": str(wid), "lot_no": lot_wait})
    out.append(("검사 대기 LOT 투입", status == 422, f"HTTP {status}"))
    flow.lot_inspect(lot_wait, "불합격")
    status, body = api.post("field", "/mat/inputs", {"work_id": str(wid), "lot_no": lot_wait})
    out.append(("불합격 LOT 투입", status == 422, f"HTTP {status}"))
    status, body = api.post("prod", f"/pop/work/{wid}/finish", {"output_qty": "1"})
    out.append(("투입 0건인 실적 종료 (롤·계보 없이)", status == 422 and db.v("select count(*) from roll where work_result_id = %s", (wid,)) == 0,
                f"HTTP {status}"))
    flow.input(wid, lot)
    flow.finish(wid, "1")
    # 순환 — API 는 자식 롤을 늘 새로 만들기 때문에 순환을 요청할 길이 없다. 마지막 방어선(DB 트리거·CHECK)을 SQL 로 직접 두드린다(롤백)
    f2 = flow.finishing(s[1])                                  # f1 → s[1] → f2 : f2 는 f1 의 손자
    ids = {r["roll_no"]: r["roll_id"] for r in db.q("select roll_no, roll_id from roll where roll_no = any(%s)", ([p1, f1, f2, s[1], p4],))}
    for name, parent, child, rel in (
            ("[DB] 자식(슬리팅 롤)을 그 부모(후가공 롤)의 부모로 — 순환", s[1], f1, "후가공"),
            ("[DB] 손자(후가공 롤)를 조상(후가공 롤)의 부모로 — 긴 순환", f2, f1, "후가공"),
            ("[DB] 자기 자신을 부모로", f2, f2, "후가공")):
        try:
            with psycopg.connect(appconn.dsn()) as c, c.cursor() as cur:
                cur.execute("""insert into roll_genealogy (parent_roll_id, child_roll_id, relation, created_by)
                               values (%s, %s, %s, 'qa2')""", (ids[parent], ids[child], rel))
                c.rollback()
            out.append((name, False, "INSERT 가 통과했다 (롤백함)"))
        except psycopg.errors.IntegrityError as exc:
            out.append((name, True, f"{type(exc).__name__}: {str(exc).splitlines()[0][:50]}"))
    try:                                                       # 계보 행 UPDATE 로 부모를 바꿔치기
        with psycopg.connect(appconn.dsn()) as c, c.cursor() as cur:
            cur.execute("update roll_genealogy set parent_roll_id = %s where child_roll_id = %s", (ids[p4], ids[f1]))
            c.rollback()
        out.append(("[DB] 계보 행의 부모를 UPDATE 로 바꾸기", False, "UPDATE 가 통과했다 (롤백함)"))
    except psycopg.errors.IntegrityError as exc:
        out.append(("[DB] 계보 행의 부모를 UPDATE 로 바꾸기", True, type(exc).__name__))
    # 동시성 — 같은 롤을 두 사람이 동시에
    results: list[int] = []

    def fire(role: str, path: str, data: dict) -> None:
        c = api.new_client(role)
        r = c.post(path, data=data, follow_redirects=False)
        results.append(r.status_code)

    ts = [threading.Thread(target=fire, args=("prod", "/rll/slitting", {"roll_no": p4, "count": "2"})) for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    kids = db.v("select count(*) from roll_genealogy g join roll r on r.roll_id = g.parent_roll_id where r.roll_no = %s", (p4,))
    out.append(("[동시] 같은 롤을 동시에 두 번 슬리팅 → 한 번만", sorted(results) == [200, 422] and kids == 2,
                f"HTTP {sorted(results)} · 자식 {kids}개"))
    results.clear()
    wid2 = flow.start(job)                                     # 같은 실적을 두 사람이 동시에 종료 → 인쇄 롤 1개
    flow.input(wid2, lot)
    ts = [threading.Thread(target=fire, args=("prod", f"/pop/work/{wid2}/finish", {"output_qty": "1"})) for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    n_roll = db.v("select count(*) from roll where work_result_id = %s", (wid2,))
    n_in = db.v("select count(*) from roll_genealogy g join roll r on r.roll_id = g.child_roll_id where r.work_result_id = %s", (wid2,))
    out.append(("[동시] 같은 실적을 동시에 두 번 종료 → 인쇄 롤 1개", sorted(results) == [200, 422] and n_roll == 1 and n_in == 1,
                f"HTTP {sorted(results)} · 롤 {n_roll} · 투입 행 {n_in}"))
    results.clear()
    purge_extra = db.q("select r.roll_no from roll r join roll_genealogy g on g.child_roll_id = r.roll_id "
                       "join roll p on p.roll_id = g.parent_roll_id where p.roll_no = %s", (p4,))
    for r in purge_extra:
        flow._roll(r["roll_no"], "슬리팅", job)
        flow.edges.add((p4, r["roll_no"], "슬리팅"))
    sh3, sh4 = flow.shipment(job, date.today()), flow.shipment(job, date.today())
    ts = [threading.Thread(target=fire, args=("field", f"/shp/shipments/{s_}/rolls", {"roll_no": p5})) for s_ in (sh3, sh4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    n_ship = db.v("select count(*) from roll_genealogy g join roll r on r.roll_id = g.parent_roll_id "
                  "where r.roll_no = %s and g.child_shipment_id is not null", (p5,))
    out.append(("[동시] 같은 롤을 동시에 두 출하에 → 한 곳만", sorted(results) == [200, 422] and n_ship == 1,
                f"HTTP {sorted(results)} · 출하 행 {n_ship}"))
    return out


def check_g07(ctx: Ctx, rep: Report, n_random: int = 5, seed: int = 20261003) -> dict:
    flow, g, m = ctx.design()
    api, db = ctx.api, ctx.db
    inv = {v: k for k, v in m.items()}
    design_edges = {(m[p], m[c], rel) for p, c, rel in g["edges"]}
    kind = {m[k]: ("L" if n["table"] == "material_lot" else "S" if n["table"] == "shipment" else "R") for k, n in g["nodes"].items()}
    lots = sorted((k for k, n in g["nodes"].items() if n["table"] == "material_lot"), key=lambda k: g["nodes"][k]["y"])
    ship = next(k for k, n in g["nodes"].items() if n["table"] == "shipment")

    def names(nos) -> list[str]:
        return sorted(inv.get(n, n) for n in nos)

    # 역방향: 출하 LOT → 원재료 LOT ①·② 둘 다
    want = model_trace(design_edges, kind, m[ship], "backward")       # 그림의 화살표를 거꾸로 따라간 기대값
    scr, mine = screen_trace(api, m[ship], "backward"), sql_trace(db, m[ship], "backward")
    ok = scr["status"] == 200 and scr["lots"] == mine["lots"] == want["lots"] == {m[x] for x in lots} \
        and scr["edges"] == mine["edges"] == want["edges"]
    rep.add("G-07", "역방향 — 출하 LOT → 원재료 LOT ①·② (화면 = 독립 SQL = 그림)", ok,
            f"화면 닿은 LOT {names(scr['lots'])} · 화살표 화면 {len(scr['edges'])} / 독립 SQL {len(mine['edges'])} / 그림 {len(want['edges'])}")
    # 정방향: 원재료 LOT ① → 인쇄 ①② → 후가공 → 슬리팅 ①②③ → 출하 LOT, ③ 은 재고
    want = model_trace(design_edges, kind, m[lots[0]], "forward")
    scr, mine = screen_trace(api, m[lots[0]], "forward"), sql_trace(db, m[lots[0]], "forward")
    want_stock = {m[s] for s in g["stock"]}
    rolls_reached = {e[1] for e in scr["edges"] if kind.get(e[1]) == "R"}
    all_rolls = {no for no, k in kind.items() if k == "R"}
    ok = scr["status"] == 200 and scr["edges"] == mine["edges"] == want["edges"] and scr["ships"] == mine["ships"] == {m[ship]} \
        and scr["stock"] == mine["stock"] == want_stock and rolls_reached == all_rolls and "재고" in scr.get("text", "")
    rep.add("G-07", "정방향 — 원재료 LOT ① → 인쇄 ①② → 후가공 → 슬리팅 ①②③ → 출하 LOT · ③ 재고", ok,
            f"화살표 화면 {len(scr['edges'])} / 독립 SQL {len(mine['edges'])} / 그림 {len(want['edges'])} · 닿은 롤 {len(rolls_reached)}/{len(all_rolls)} · "
            f"출하 {names(scr['ships'])} · 재고 {names(scr['stock'])}")
    # 원재료 LOT ② 의 정방향에는 인쇄 롤 ① 이 없어야 한다 · 예시의 모든 노드 양방향
    diffs: list[str] = []
    n_req = 0
    for no, k in sorted(kind.items()):
        for direction in (("forward",) if k == "L" else ("backward",) if k == "S" else ("forward", "backward")):
            n_req += 1
            dflow = Flow.__new__(Flow)
            dflow.edges, dflow.kind = design_edges, kind
            diffs += compare_trace(api, db, dflow, no, direction)
    scr2 = screen_trace(api, m[lots[1]], "forward")
    first_print = next(k for k, n in sorted(g["nodes"].items(), key=lambda kv: kv[1]["y"]) if n["process"] == "인쇄")
    leak = m[first_print] in {e[1] for e in scr2["edges"]} | {e[0] for e in scr2["edges"]}
    rep.add("G-07", "예시의 모든 노드 양방향 추적 (화면 = 독립 SQL = 그림) · LOT ② 정방향에 인쇄 롤 ① 없음", not diffs and not leak,
            f"추적 {n_req}건 · 불일치 {len(diffs)}" + (f" — {diffs[0]}" if diffs else "") + (" · LOT ② 에 인쇄 롤 ① 이 섞였다" if leak else ""))

    # 임의 계보
    rng = random.Random(seed)
    info, all_diffs, n_trace = [], [], 0
    for i in range(n_random):
        f = ctx.flow()
        meta = build_random_lineage(f, rng, n_jobs=1 + (i % 3))
        db_edges = sql_edges_of_tag(db, f.tag)
        if db_edges != f.edges:                                   # 내가 요청한 화살표 = DB 의 행 (독립 SQL)
            all_diffs.append(f"계보 {i + 1}: 모델 {len(f.edges)}줄 ≠ DB {len(db_edges)}행")
        for no, k in sorted(f.kind.items()):
            for direction in (("forward",) if k == "L" else ("backward",) if k == "S" else ("forward", "backward")):
                n_trace += 1
                all_diffs += [f"계보 {i + 1} {d}" for d in compare_trace(api, db, f, no, direction)]
        shared_jobs = len({f.job_of[c] for p, c, rel in f.edges if p == meta["lots"][0] and rel == "투입"})
        meta.update(nodes=len(f.kind), shared_jobs=shared_jobs)
        info.append(meta)
    min_depth = min(x["depth"] for x in info)
    rep.add("G-07", f"임의 계보 {n_random}개 — 모든 노드에서 화면 추적 = 독립 재귀 SQL = 모델",
            not all_diffs and min_depth >= 5,
            f"추적 {n_trace}건 · 불일치 {len(all_diffs)} · 화살표 {sum(x['edges'] for x in info)}줄 · 노드 {sum(x['nodes'] for x in info)}개 · "
            f"깊이 {min_depth}~{max(x['depth'] for x in info)}단 · splice {sum(x['ops']['splice'] for x in info)}회"
            f"(Job 간 {sum(x['ops']['cross_job_splice'] for x in info)}) · 한 LOT → 최대 Job {max(x['shared_jobs'] for x in info)}개 · "
            f"출하 승인 {sum(len(x['ships']['approved']) for x in info)} · 등록 {sum(len(x['ships']['registered']) for x in info)} · "
            f"취소 {sum(len(x['ships']['cancelled']) for x in info)}" + (f" — {all_diffs[0]}" if all_diffs else ""))

    # LOT 검색 (F-TRC-03) — 번호 일부로 찾은 목록 = 독립 SQL
    s_bad, s_n = [], 0
    some_roll = m[next(k for k, n in g["nodes"].items() if n["process"] == "후가공")]
    for q in (some_roll, m[lots[0]][:-2], m[ship][:-1], some_roll.lower(), flow.code("NOPE")):
        r = api.get("qc", "/trc/trace", {"q": q})
        body = main_of(r.text)
        hits = [re.search(r"<code>([^<]+)</code>", h).group(1) for h in re.findall(r'<div class="hit">(.*?)</div>', body, re.S)]
        mine = {x["no"] for x in db.q("""select no from (select lot_no as no from material_lot union all select roll_no from roll
                                                         union all select shipment_no from shipment) x
                                          where position(lower(%s) in lower(no)) > 0""", (q,))}
        s_n += 1
        if r.status_code != 200:
            s_bad.append(f"`{q}` HTTP {r.status_code}")
        elif len(mine) <= 50 and set(hits) != mine:
            s_bad.append(f"`{q}` 화면 {len(hits)}건 ≠ 독립 SQL {len(mine)}건")
        elif len(mine) > 50 and not (len(hits) == 50 and set(hits) <= mine):
            s_bad.append(f"`{q}` 화면 {len(hits)}건 (상한 50) · 독립 SQL {len(mine)}건")
        elif not mine and NOT_COLLECTED not in text_of_html(body):
            s_bad.append(f"`{q}` 0건인데 미수집이 없다")
    rep.add("G-07", "LOT 검색 — 번호 일부로 찾은 원재료 LOT · 롤 · 출하 LOT = 독립 SQL (상한 50 · 0건은 미수집)", not s_bad,
            f"검색 {s_n}건 · 불일치 {len(s_bad)}" + (f" — {s_bad[:2]}" if s_bad else ""))

    # 추적은 조회 하나 · 쓰지 않는다
    scr = screen_trace(api, m[ship], "backward")
    scr_f = screen_trace(api, m[lots[0]], "forward")
    rec = [sum(1 for s in t["sql"] if re.search(r"\bwith\s+recursive\b", s, re.I)) for t in (scr, scr_f)]
    wr = {tbl for t in (scr, scr_f) for _, tbl in t["writes"]}
    n_gen_sql = [sum(1 for s in t["sql"] if "roll_genealogy" in s) for t in (scr, scr_f)]
    rep.add("G-07", "추적 한 번 = 재귀 조회 하나 · 쓰기는 접근 로그뿐 (실행 SQL 캡처)",
            rec == [1, 1] and wr <= {"sys_access_log"} and n_gen_sql == [1, 1],
            f"요청당 with recursive {rec} · roll_genealogy 를 읽는 문장 {n_gen_sql} · 쓴 테이블 {sorted(wr) or '없음'}")
    # 경로를 따로 저장하지 않는다
    spec_tables = set(contracts.db_tables())
    live = {r["table_name"] for r in db.q("select table_name from information_schema.tables where table_schema = 'public' and table_type = 'BASE TABLE'")}
    matviews = db.v("select count(*) from pg_matviews where schemaname = 'public'")
    suspicious = sorted(t for t in live if re.search(r"trace|path|cache|closure|ancest|descend|lineage|tree", t))
    extra = sorted(live - spec_tables)
    # 계보가 바뀌면 추적 결과가 곧바로 바뀐다 (캐시가 없다는 동적 증거)
    f = ctx.flow()
    fg = f.item("FG", "제품")
    f.item("RM", "원재료")
    job = f.job(fg, f.customer(), date.today())
    lot = f.lot(f.code("RM"))
    roll = f.print_roll(job, [lot])
    sh = f.shipment(job, date.today())
    t0 = screen_trace(api, lot, "forward")
    f.scan(sh, roll)
    t1 = screen_trace(api, lot, "forward")
    f.cancel_shipment(sh)
    t2 = screen_trace(api, lot, "forward")
    live_ok = (t0["ships"], t1["ships"], t2["ships"]) == (set(), {sh}, set()) and t0["stock"] == t2["stock"] == {roll} and t1["stock"] == set()
    rep.add("G-07", "추적 결과를 따로 저장하지 않는다 (경로·캐시 테이블 0 · 계보가 바뀌면 곧바로 바뀜)",
            not suspicious and not extra and matviews == 0 and live_ok,
            f"계약 밖 테이블 {extra or 0} · 경로/캐시류 이름 {suspicious or 0} · 구체화 뷰 {matviews} · "
            f"스캔 전/후/취소 후 닿은 출하 {len(t0['ships'])}/{len(t1['ships'])}/{len(t2['ships'])}")
    # 막기
    probes = guard_probes(ctx)
    bad = [(n, d) for n, ok_, d in probes if not ok_]
    rep.add("G-07", "순환 · 자기 부모 · 재출하 · 소진/출하 롤 재사용 · 동시 사용을 막는다", not bad,
            f"시도 {len(probes)} · 막힘 {len(probes) - len(bad)}" + (" — 안 막힘: " + " / ".join(f"{n} ({d})" for n, d in bad[:3]) if bad else ""))
    return {"random": info, "n_trace": n_trace, "diffs": all_diffs, "probes": probes}


# ── G-05 쓰기 경계 ──────────────────────────────────────────────────────
def exercise_remaining_writes(ctx: Ctx) -> Flow:
    """G-06·G-07 시나리오가 부르지 않은 쓰기 기능을 마저 부른다 (기준정보·인쇄 기준의 수정·삭제, 조색, 정지·폐기, 검사 수정·삭제 …)."""
    api = ctx.api
    f = ctx.flow()
    post, must = api.post, f.must
    # P1 기준정보 5종: 등록 → 수정 → 삭제
    pr = must(post("admin", "/bas/processes", {"process_code": f.code("PR"), "process_name": f.label("공정"),
                                               "process_type": "인쇄", "sort_no": "900"}), "공정 등록")["id"]
    eq = must(post("admin", "/bas/equipment", {"equipment_code": f.code("EQ"), "equipment_name": f.label("설비"),
                                               "process_id": str(pr)}), "설비 등록")["id"]
    fg = f.item("FG", "제품")
    tmp_item = f.item("TMP", "제품")
    f.item("RM", "원재료")
    cu = f.customer()
    tmp_cu = f.customer("CU2")
    df = f.defect("DF")
    df_id = ctx.db.v("select defect_code_id from defect_code where defect_code = %s", (df,))
    for path, row_id, name_col in (("/bas/items", tmp_item, "item_name"), ("/bas/customers", tmp_cu, "customer_name"),
                                   ("/bas/processes", pr, "process_name"), ("/bas/equipment", eq, "equipment_name"),
                                   ("/bas/defect-codes", df_id, "defect_name")):
        must(post("admin", f"{path}/{row_id}", {name_col: f.label("수정")}), f"{path} 수정")
    must(post("admin", f"/bas/equipment/{eq}/delete"), "설비 삭제")
    must(post("admin", f"/bas/processes/{pr}/delete"), "공정 삭제")
    must(post("admin", f"/bas/items/{tmp_item}/delete"), "품목 삭제")
    must(post("admin", f"/bas/customers/{tmp_cu}/delete"), "고객 삭제")
    tmp_df = must(post("admin", "/bas/defect-codes", {"defect_code": f.code("DF9"), "defect_name": f.label("불량")}), "불량코드 등록")["id"]
    must(post("admin", f"/bas/defect-codes/{tmp_df}/delete"), "불량코드 삭제")
    # P1 인쇄 기준 3종
    pl = must(post("prod", "/prt/plates", {"plate_code": f.code("PL"), "plate_name": f.label("판"), "item_id": str(fg)}), "판사양 등록")["id"]
    must(post("prod", f"/prt/plates/{pl}", {"plate_name": f.label("판 수정")}), "판사양 수정")
    must(post("prod", f"/prt/plates/{pl}/delete"), "판사양 삭제")
    an = must(post("prod", "/prt/anilox", {"anilox_code": f.code("AN"), "anilox_name": f.label("아니록스")}), "아니록스 등록")["id"]
    must(post("prod", f"/prt/anilox/{an}", {"anilox_name": f.label("아니록스 수정")}), "아니록스 수정")
    must(post("prod", f"/prt/anilox/{an}/delete"), "아니록스 삭제")
    ink = must(post("prod", "/prt/inks", {"ink_code": f.code("INK"), "ink_name": f.label("잉크"),
                                          "component_name": [f.label("성분 1"), f.label("성분 2")], "ratio_pct": ["70", "30"]}), "잉크조성 등록")["id"]
    must(post("prod", f"/prt/inks/{ink}", {"ink_name": f.label("잉크 수정"), "component_name": [f.label("성분 1")], "ratio_pct": ["100"]}), "잉크조성 수정")
    must(post("prod", f"/prt/inks/{ink}/delete"), "잉크조성 삭제")
    # P2 작업지시: 수정 · 취소 · 매핑
    job = f.job(fg, cu, date.today() + timedelta(days=3))
    must(post("prod", f"/job/orders/{job}", {"note": "QA2 (예시)"}), "작업지시 수정")
    tmp_job = f.job(fg, cu, date.today() + timedelta(days=3))
    must(post("prod", f"/job/orders/{tmp_job}/cancel"), "작업지시 취소")
    jl = f.job_lot(job)
    must(post("prod", "/job/mapping", {"job_no": job, "lot_no": jl, "planned_roll_count": "3"}), "매핑 계획 수정")
    # P4 조색: 등록 · 배합비 · 수정 · 삭제
    cid = must(post("qc", "/clr/records", {"job_no": job, "color_name": f.label("색"), "color_l": "50", "color_a": "1", "color_b": "2"}), "조색 기록 등록")["id"]
    must(post("qc", f"/clr/records/{cid}/mix", {"component_name": [f.label("성분 1"), f.label("성분 2")], "ratio_pct": ["60", "40"]}), "배합비 등록")
    must(post("field", f"/clr/records/{cid}", {"color_name": f.label("색"), "color_l": "51", "color_a": "1", "color_b": "2"}), "조색 기록 수정")
    must(post("qc", f"/clr/records/{cid}/delete"), "조색 기록 삭제")
    # P3 · P5: 입고 · 입고검사 · 작업 시작 · 투입 · 정지 · 재개 · 폐기 · 종료
    lot = f.lot(f.code("RM"))
    wid = f.start(job, jl)
    f.input(wid, lot, "5")
    sid = must(post("field", "/pop/stops", {"work_id": str(wid), "stop_reason": "QA2 (예시)"}), "정지 등록")["stop_id"]
    must(post("field", f"/pop/stops/{sid}/resume"), "재개 등록")
    must(post("prod", "/pop/stops/scrap", {"work_id": str(wid), "scrap_qty": "1.5", "defect_code": df}), "폐기 등록")
    roll = f.finish(wid, "10")
    f._roll(roll, "인쇄", job)
    f.edges.add((lot, roll, "투입"))
    # P6 후가공 1:1 (예시는 splice · 슬리팅만 쓴다)
    fin = f.finishing(roll)
    # P7 검사: 등록 · 수정 · 삭제
    iid = f.inspect(fin, "불합격", "3.3", [(df, "L1")])
    must(post("qc", f"/qua/inspections/{iid}", {"delta_e": "1.1", "result": "합격", "defect_code": [df], "position": ["L2"]}), "검사 결과 수정")
    must(post("qc", f"/qua/inspections/{iid}/delete"), "검사 결과 삭제")
    # P8 출하: 등록 · 스캔 · 취소 (승인은 예시에서)
    sh = f.shipment(job, date.today())
    f.scan(sh, fin)
    f.cancel_shipment(sh)
    return f


def snapshot_business(db: Db) -> dict[str, tuple[int, str]]:
    """D1~D8 23개 테이블의 (행 수, 내용 해시)."""
    out = {}
    for t in sorted(business_tables()):
        r = db.q1(f'select count(*) as n, md5(coalesce(string_agg(md5(x::text), \'\' order by md5(x::text)), \'\')) as h from "{t}" x')
        out[t] = (r["n"], r["h"])
    return out


def check_g05(ctx: Ctx, rep: Report) -> dict:
    api, db = ctx.api, ctx.db
    flow, g, m = ctx.design()
    biz = business_tables()
    procs = design_doc.processes()
    # ── 정적: 라우트마다 쓰는 테이블 ──
    static_rows, viol, unresolved, read_viol, beyond = [], [], [], [], []
    p8_static: set[str] = set()
    for method, path, endpoint in api_routes(api.app):
        f = api.fn_of(method, path)
        tables = tables_written_by(endpoint)
        dyn = {t for t in tables if t.startswith("?")}
        tables -= dyn
        if dyn:
            unresolved.append(f"{method} {path} {sorted(dyn)}")
        if f is None:                                             # 계약 기능이 아닌 경로 (화면 GET · 로그인 · /health · /erp)
            if tables & biz:
                read_viol.append(f"{method} {path} → {sorted(tables & biz)}")
            continue
        allowed = allowed_tables(f.process) or set()
        over = (tables & biz) - allowed if f.process != "공통" else tables & biz
        sys_over = {t for t in tables if t.startswith("sys_")} - COMMON_SYS if f.process != "공통" else set()
        if not f.is_write:
            if tables - {"sys_access_log"}:
                read_viol.append(f"{f.id} {method} {path} → {sorted(tables - {'sys_access_log'})}")
        elif f.process == "P8":
            p8_static |= over
            over -= {"roll_genealogy"}                            # D-12 — 따로 본다
        if f.is_write and (over or sys_over):
            viol.append(f"{f.id}({f.process}) → {sorted(over | sys_over)}")
        if f.is_write and (tables & (biz | {"sys_user", "sys_permission"})) - set(f.tables):   # 계약 줄의 `쓰는 테이블` 보다 더 쓰는가
            beyond.append(f"{f.id} → {sorted((tables & (biz | {'sys_user', 'sys_permission'})) - set(f.tables))}")
        static_rows.append((f.id, f.process, sorted(tables)))
    n_fn = sum(1 for f in contracts.functions() if not f.is_batch)
    n_write = sum(1 for fid, _, _ in static_rows if contracts.function(fid).is_write)
    n_read = len(static_rows) - n_write
    found_all = len({fid for fid, _, _ in static_rows}) == n_fn       # 라우트를 하나도 못 읽고 「위반 0」 이 되는 일을 막는다
    wrote_nothing = [fid for fid, _, t in static_rows if contracts.function(fid).is_write and not (set(t) - COMMON_SYS)]
    rep.add("G-05", "[정적] 쓰기 라우트가 쓰는 테이블 ⊆ 설계도 §2 표의 쓰는 저장소", found_all and not viol and not unresolved and not wrote_nothing,
            f"라우트로 이어진 기능 {len(static_rows)}/{n_fn} · 쓰기 기능 {n_write}개 · 표 밖 쓰기 {len(viol)}" + (f" — {viol[:3]}" if viol else "")
            + (f" · 테이블 이름을 못 푼 SQL {unresolved[:2]}" if unresolved else "")
            + (f" · 쓰기 SQL 을 못 찾은 쓰기 기능 {wrote_nothing[:3]}" if wrote_nothing else ""))
    rep.add("G-05", "[정적] 쓰기 라우트가 쓰는 테이블 ⊆ function-list.md 의 그 기능 `쓰는 테이블`", found_all and not beyond,
            f"쓰기 기능 {n_write}개 · 계약 줄보다 더 쓰는 기능 {len(beyond)}" + (f" — {beyond[:3]}" if beyond else ""))
    p9p10 = [fid for fid, proc, _ in static_rows if proc in ("P9", "P10")]
    rep.add("G-05", "[정적] 조회·출력 라우트(P9·P10 포함)는 업무 테이블에 쓰지 않는다", found_all and not read_viol and len(p9p10) == 7,
            f"읽기 기능 {n_read}개(P9·P10 {len(p9p10)}개) + 계약 밖 경로 · 쓰기 {len(read_viol)}" + (f" — {read_viol[:3]}" if read_viol else ""))

    # ── 정적: 이관 배치 6명령 (화면이 아니라 명령 — db-schema.md §2 의 「배치」 줄) ──
    from lcomfine import migration
    from lcomfine.migration import files as mig_files

    batch_bad, batch_seen = [], []
    for name, fn in migration.COMMANDS.items():
        f = contracts.function(migration.FUNCTION_IDS[name])
        tables = tables_written_by(fn)
        if "?spec.table" in tables:                                # 적재 명령은 파일 규격(SPECS)의 대상 테이블에 쓴다
            tables = (tables - {"?spec.table"}) | {sp.table for sp in mig_files.SPECS if sp.command == name and sp.loadable}
        batch_seen.append(f"{name}→{len(tables)}")
        if tables - set(f.tables):
            batch_bad.append(f"{f.id} {name} → {sorted(tables - set(f.tables))}")
    rep.add("G-05", "[정적] 이관 배치 6명령이 쓰는 테이블 ⊆ function-list.md 의 그 배치 줄 · validate·report 는 쓰기 0", not batch_bad,
            f"명령별 쓰는 테이블 수 {' · '.join(batch_seen)} · 계약 밖 쓰기 {len(batch_bad)}" + (f" — {batch_bad[:2]}" if batch_bad else ""))

    # ── 동적: 실제 요청이 실행한 쓰기 SQL ──
    exercise_remaining_writes(ctx)
    write_fns = [f for f in contracts.functions() if f.is_write and not f.is_batch and f.process != "공통"]
    done: dict[str, set[str]] = defaultdict(set)
    dyn_viol: list[str] = []
    per_proc: dict[str, set[str]] = defaultdict(set)
    for c in api.calls:
        f = c["fn"]
        if f is None or c["status"] != 200 or not f.is_write or f.process == "공통":
            continue
        tables = {t for _, t in c["writes"]}
        done[f.id] |= tables
        per_proc[f.process] |= tables & biz
        allowed = allowed_tables(f.process) or set()
        over = (tables & biz) - allowed
        if f.process == "P8":
            over -= {"roll_genealogy"}
        sys_over = {t for t in tables if t.startswith("sys_")} - COMMON_SYS
        if over or sys_over:
            dyn_viol.append(f"{f.id}({f.process}) → {sorted(over | sys_over)}")
    missing = sorted(f.id for f in write_fns if f.id not in done)
    rep.add("G-05", "[동적] 실제 요청이 실행한 쓰기 SQL ⊆ 쓰는 저장소 (psycopg 실행 문장 캡처)",
            not dyn_viol and not missing,
            f"쓰기 기능 {len(done)}/{len(write_fns)}개 실행 · 표 밖 쓰기 {len(set(dyn_viol))}"
            + (f" — {sorted(set(dyn_viol))[:3]}" if dyn_viol else "") + (f" · 실행 못 한 기능 {missing}" if missing else ""))
    summary = " · ".join(f"{p}→{'+'.join(sorted({contracts.db_tables()[t].store for t in per_proc[p]}))}" for p in sorted(per_proc, key=lambda x: int(x[1:])))
    want = " · ".join(f"{p}→{'+'.join(v['writes']) or '없음'}" for p, v in procs.items() if v["writes"])
    design_match = all({contracts.db_tables()[t].store for t in per_proc[p]} - set(procs[p]["writes"]) <= ({"D6"} if p == "P8" else set())
                       for p in per_proc)
    rep.add("G-05", "[동적] 프로세스별 실제로 쓴 저장소 = 설계도 표", design_match, f"실측 {summary} / 설계도 {want}")

    # ── P9 · P10: 조회 전후 업무 테이블 diff 0 ──
    lots = [k for k, n in g["nodes"].items() if n["table"] == "material_lot"]
    ship = next(k for k, n in g["nodes"].items() if n["table"] == "shipment")
    roll = next(k for k, n in g["nodes"].items() if n["process"] == "후가공")
    today = date.today()
    reads = [("admin", "/trc/trace", {"q": m[lots[0]][:4]}), ("qc", "/trc/trace", {"no": m[ship]}),
             ("admin", "/trc/trace/forward", {"no": m[lots[0]]}), ("prod", "/trc/trace/forward", {"no": m[roll]}),
             ("admin", "/trc/trace/backward", {"no": m[ship]}), ("qc", "/trc/trace/backward", {"no": m[roll]}),
             ("admin", "/trc/trace/backward", {"no": m[ship], "device": "mobile"}),
             ("admin", "/sta/summary", {}), ("prod", "/sta/summary", {"date_from": str(today - timedelta(days=30)), "date_to": str(today)}),
             ("admin", "/sta/summary/production", {}), ("qc", "/sta/summary/quality", {}), ("field", "/sta/summary/delivery", {}),
             ("admin", "/sta/board", {}), ("field", "/sta/board", {"device": "board"})]
    result = None
    for attempt in range(1, 6):                                   # 다른 QA 의 동시 쓰기와 구분 — 다섯 번 안에 diff 0 이 한 번이라도 나오면 라우트의 쓰기가 아니다
        before = snapshot_business(db)
        log_before = db.v("select count(*) from sys_access_log")
        statuses, wr = [], set()
        for role, path, params in reads:
            r = api.get(role, path, params, client=api.new_client(role) if "device" in params else None)
            statuses.append(r.status_code)
            wr |= {t for _, t in api.last["writes"]}
        after = snapshot_business(db)
        changed = sorted(t for t in before if before[t] != after[t])
        result = {"attempt": attempt, "changed": changed, "statuses": statuses, "writes": wr,
                  "log_delta": db.v("select count(*) from sys_access_log") - log_before}
        if not changed:
            break
    ok = not result["changed"] and all(s == 200 for s in result["statuses"]) and result["writes"] <= {"sys_access_log"}
    rep.add("G-05", "P9 LOT 추적 · P10 실적 현황 — 조회 전후 업무 테이블 23개 행 수·내용 diff 0", ok,
            f"조회 {len(reads)}건(HTTP 200 {sum(1 for s in result['statuses'] if s == 200)}) · 달라진 테이블 {result['changed'] or 0} · "
            f"실행된 쓰기 SQL 의 대상 {sorted(result['writes']) or '없음'} (접근 로그 +{result['log_delta']} — D-15) · 시도 {result['attempt']}")

    # ── D-12: P8 이 roll_genealogy 에 쓰는 것은 `출하` 행뿐 · lineage 경유뿐 ──
    changes = [c for f in ctx.flows for c in f.p8_changes]
    rel_added = {r for c in changes for r in c["added"]}
    rel_removed = {r for c in changes for r in c["removed"]}
    approve_touch = [c for c in changes if c["fn"] == "F-SHP-05" and (c["added"] or c["removed"])]
    shp_src = (SRC / "lcomfine/app/routers/shp.py").read_text(encoding="utf-8")
    shp_direct = _scan_sql_text(shp_src, lambda e: f"?{e}") & {"roll_genealogy", "roll"}
    shp_calls = set(re.findall(r"\blineage\.([a-z_]+)\(", shp_src))
    lineage_writers = {"link", "make_print_roll", "make_finishing_roll", "slit_roll", "ship_roll", "unlink_shipment"}
    ok = rel_added <= {"출하"} and rel_removed <= {"출하"} and not approve_touch and not shp_direct \
        and (shp_calls & lineage_writers) <= {"ship_roll", "unlink_shipment"} and p8_static <= {"roll_genealogy"}
    rep.add("G-05", "P8 출하가 D6 에 쓰는 것은 roll_genealogy 의 `출하` 행뿐 · lineage 경유뿐 (D-12 범위 — 사람 확인)", ok,
            f"P8 요청 {len(changes)}건 · 생긴 행의 관계 {sorted(rel_added) or '없음'} · 지운 행의 관계 {sorted(rel_removed) or '없음'} · "
            f"승인이 건드린 계보 행 {len(approve_touch)} · shp.py 의 직접 쓰기 SQL {sorted(shp_direct) or 0} · "
            f"부르는 lineage 쓰기 함수 {sorted(shp_calls & lineage_writers)} — 설계도 §2 표(P8 → D8)와 §3 그림의 모순은 사람 확인")

    # ── roll_genealogy 에 쓰는 곳은 lineage.py 뿐 · 업무 라우터가 쓰는 sys_* 는 공통 2개뿐 ──
    writers = []
    for p in sorted((SRC / "lcomfine").rglob("*.py")):
        if "roll_genealogy" in _scan_sql_text(p.read_text(encoding="utf-8"), lambda e: f"?{e}"):
            writers.append(str(p.relative_to(SRC / "lcomfine")))
    sys_used = sorted({t for c in api.calls if c["fn"] is not None and c["fn"].process != "공통" and c["status"] == 200
                       for _, t in c["writes"] if t.startswith("sys_")})
    rep.add("G-05", "roll_genealogy 에 쓰는 코드는 app/lineage.py 한 곳 · 업무 라우터의 sys_* 쓰기는 접근 로그·채번 카운터뿐 (D-15)",
            writers == ["app/lineage.py"] and set(sys_used) <= COMMON_SYS,
            f"roll_genealogy 쓰기 SQL 이 있는 파일 {writers} · 업무 요청이 쓴 sys_* {sys_used}")
    return {"static": static_rows, "per_proc": {k: sorted(v) for k, v in per_proc.items()}, "done": sorted(done), "p9p10": result}


# ── G-08 키 연결 · 채번 ─────────────────────────────────────────────────
def check_g08(ctx: Ctx, rep: Report) -> None:
    api, db = ctx.api, ctx.db
    flow, g, m = ctx.design()
    job = m["Job"]
    slit = sorted((k for k, n in g["nodes"].items() if n["process"] == "슬리팅" and k not in g["stock"]), key=lambda k: g["nodes"][k]["y"])
    prints = sorted((k for k, n in g["nodes"].items() if n["process"] == "인쇄"), key=lambda k: g["nodes"][k]["y"])
    s1, s2 = m[slit[0]], m[slit[1]]
    fin = m[next(k for k, n in g["nodes"].items() if n["process"] == "후가공")]
    # 조색 2건 (출하 승인과 무관) — 검사는 승인 전에만 넣을 수 있으므로(D-304) 승인된 예시의 롤 대신 재고 롤 ③ 과 따로 만든 롤로 본다
    for i in (1, 2):
        flow.must(api.post("qc", "/clr/records", {"job_no": job, "color_name": flow.label("색"), "color_l": "50", "color_a": str(i), "color_b": "2"}),
                  "조색 기록 등록")
    stock_roll = m[g["stock"][0]]
    flow.inspect(stock_roll, "불합격", "4.20", None)
    flow.inspect(stock_roll, "합격", "1.20", None)
    works = {flow.work_of[m[p]] for p in prints}
    # ── SQL: 롤 번호 하나에서 Job-Lot-Roll 키로 ──
    def by_sql(roll_no: str) -> dict:
        r = db.q1("select roll_id, job_id, job_lot_id, work_result_id from roll where roll_no = %s", (roll_no,))
        anc = [x["genealogy_id"] for x in db.q(TRACE_SQL.format(near="c", far="p"), {"start": f"R{r['roll_id']}"})]
        print_rolls = db.q("""select distinct r.roll_id, r.work_result_id from roll_genealogy g join roll r on r.roll_id = g.child_roll_id
                               where g.genealogy_id = any(%s) and r.process_type = '인쇄'""", (anc,)) if anc else []
        own = [r["work_result_id"]] if r["work_result_id"] else []
        return {
            "job": db.v("select job_no from job where job_id = %s", (r["job_id"],)),
            "job_lot": db.v("select lot_no from job_lot where job_lot_id = %s", (r["job_lot_id"],)),
            "color": db.v("select count(*) from color_record where job_id = %s", (r["job_id"],)),
            "works": set(own) | {x["work_result_id"] for x in print_rolls},
            "inspections": db.v("select count(*) from inspection where roll_id = %s", (r["roll_id"],)),
            "latest": db.v("select result from inspection where roll_id = %s order by inspected_at desc, inspection_id desc limit 1", (r["roll_id"],)),
            "shipment": db.v("""select s.shipment_no from roll_genealogy g join shipment s on s.shipment_id = g.child_shipment_id
                                 where g.parent_roll_id = %s""", (r["roll_id"],)),
        }

    a, b, c = by_sql(s1), by_sql(stock_roll), by_sql(m[prints[0]])
    ok = a["job"] == job and a["job_lot"] == m["생산 LOT"] and a["color"] == 2 and a["works"] == works and a["shipment"] == m["출하 LOT"] \
        and b["inspections"] == 2 and b["latest"] == "합격" and c["works"] == {flow.work_of[m[prints[0]]]}
    rep.add("G-08", "[SQL] 롤 번호 하나 → 작업지시 · 생산 LOT · 조색 기록 · 생산 실적 · 검사 결과 · 출하", ok,
            f"슬리팅 롤 {s1}: Job {a['job']} · 생산 LOT {a['job_lot']} · 조색 {a['color']}건 · 실적 {sorted(a['works'])}(조상 인쇄 롤) · 출하 {a['shipment']} / "
            f"재고 롤 {stock_roll}: 검사 {b['inspections']}회 최신 {b['latest']}")
    # ── 화면: 롤 이력(F-RLL-06) ──
    def screen(roll_no: str) -> str:
        r = api.get("admin", "/rll/history", {"no": roll_no})
        return text_of_html(main_of(r.text)) if r.status_code == 200 else f"HTTP {r.status_code}"

    t_print, t_slit, t_stock, t_fin = screen(m[prints[0]]), screen(s1), screen(stock_roll), screen(fin)
    w_print = flow.work_of[m[prints[0]]]
    checks = {
        "인쇄 롤 → 작업지시": job in t_print,
        "인쇄 롤 → 생산 실적": f"실적 {w_print}" in t_print,
        "인쇄 롤 → 조색 기록": re.search(r"조색 기록\s*2건", t_print) is not None,
        "슬리팅 롤 → 작업지시": job in t_slit,
        "슬리팅 롤 → 조색 기록": re.search(r"조색 기록\s*2건", t_slit) is not None,
        "슬리팅 롤 → 출하": m["출하 LOT"] in t_slit,
        "재고 롤 → 검사 결과": "합격" in t_stock and "2회" in t_stock,
    }
    bad = [k for k, v in checks.items() if not v]
    rep.add("G-08", "[화면] 롤 이력(GET /rll/history?no=) → 작업지시 · 조색 기록 · 검사 결과 · 출하 · (인쇄 롤) 생산 실적", not bad,
            f"확인 {len(checks) - len(bad)}/{len(checks)}" + (f" · 안 보임 {bad}" if bad else ""))
    # 후가공·슬리팅 롤의 생산 실적 — 계약(db-schema.md §6): 「계보를 거슬러 올라간 인쇄 롤의 실적」
    shown = {name: [w for w in sorted(works) if re.search(rf"실적 {w}\b", t)] for name, t in (("슬리팅 롤", t_slit), ("후가공 롤", t_fin))}
    rep.add("G-08", "[화면] 후가공·슬리팅 롤 번호 → 그 롤의 생산 실적 (조상 인쇄 롤의 실적 — db-schema.md §6)",
            all(len(v) == len(works) for v in shown.values()),
            " · ".join(f"{k} 화면에 보인 실적 {len(v)}/{len(works)}" for k, v in shown.items())
            + (" — 화면 문구: " + (re.search(r"생산 실적 (.{0,40})", t_slit).group(1).strip() if re.search(r"생산 실적 (.{0,40})", t_slit) else "없음")))
    # 매핑 조회(F-JOB-07): Job → 생산 LOT → Roll → 출하 LOT
    r = api.get("admin", "/job/mapping", {"no": job})
    t = text_of_html(main_of(r.text))
    all_rolls = [m[k] for k, n in g["nodes"].items() if n["table"] == "roll"]
    seen = [x for x in all_rolls if x in t]
    rep.add("G-08", "[화면] Job-Lot-Roll 매핑(GET /job/mapping?no=) — Job → 생산 LOT → Roll → 출하 LOT",
            r.status_code == 200 and len(seen) == len(all_rolls) and m["생산 LOT"] in t and m["출하 LOT"] in t,
            f"HTTP {r.status_code} · 롤 {len(seen)}/{len(all_rolls)} · 생산 LOT {'보임' if m['생산 LOT'] in t else '안 보임'} · 출하 LOT {'보임' if m['출하 LOT'] in t else '안 보임'}")
    # ── 키 무결성 (DB 전체 — 화면으로 만든 롤: 만든 사람이 계정에 있는 것. 다른 테스트가 SQL 로 직접 넣은 행은 앱이 만든 것이 아니다) ──
    app = "r.produced_by in (select login_id from sys_user)"
    broken = {
        "inspection.job_id ≠ roll.job_id": db.v(f"select count(*) from inspection n join roll r on r.roll_id = n.roll_id where n.job_id <> r.job_id and {app}"),
        "출하 롤의 Job ≠ shipment.job_id": db.v("""select count(*) from roll_genealogy g join roll r on r.roll_id = g.parent_roll_id
                                                   join shipment s on s.shipment_id = g.child_shipment_id where r.job_id <> s.job_id and """ + app),
        "roll.job_lot 의 Job ≠ roll.job_id": db.v(f"select count(*) from roll r join job_lot l on l.job_lot_id = r.job_lot_id where l.job_id <> r.job_id and {app}"),
        "인쇄 롤의 Job ≠ 그 실적의 Job": db.v(f"select count(*) from roll r join work_result w on w.work_result_id = r.work_result_id where w.job_id <> r.job_id and {app}"),
        "인쇄 롤인데 투입 행 없음": db.v(f"""select count(*) from roll r where r.process_type = '인쇄' and {app}
                                            and not exists (select 1 from roll_genealogy g where g.child_roll_id = r.roll_id and g.relation = '투입')"""),
        "후가공·슬리팅 롤인데 부모 행 없음": db.v(f"""select count(*) from roll r where r.process_type <> '인쇄' and {app}
                                                    and not exists (select 1 from roll_genealogy g where g.child_roll_id = r.roll_id)"""),
        "슬리팅·후가공(1:1) 자식 롤의 Job ≠ 부모 롤의 Job": db.v("""
            select count(*) from roll_genealogy g join roll p on p.roll_id = g.parent_roll_id join roll r on r.roll_id = g.child_roll_id
             where g.relation in ('슬리팅', '후가공') and p.job_id <> r.job_id and """ + app),
        "취소된 Job 에 롤이 있다 (내 데이터 제외)": db.v("""
            select count(*) from roll r join job j on j.job_id = r.job_id join item i on i.item_id = j.item_id
             where j.status = '취소' and i.item_code not like 'Q2-%%' and """ + app),
        # 재검(웨이브 D 뒤 · DEF-QA2-004): 닫힌 Job 에 실적이 남아 있으면 안 된다 (F-JOB-03 「실적 없는 Job 만 취소」 · D-107 「열린 실적이 있으면 마감 불가」)
        "취소된 Job 에 작업 실적이 있다 (내 데이터 제외)": db.v("""
            select count(*) from work_result w join job j on j.job_id = w.job_id join item i on i.item_id = j.item_id
             where j.status = '취소' and i.item_code not like 'Q2-%%' and w.worker in (select login_id from sys_user)"""),
        "완료된 Job 에 열린(진행·정지) 작업 실적이 있다 (내 데이터 제외)": db.v("""
            select count(*) from work_result w join job j on j.job_id = w.job_id join item i on i.item_id = j.item_id
             where j.status = '완료' and w.status <> '완료' and i.item_code not like 'Q2-%%' and w.worker in (select login_id from sys_user)"""),
        "계보 투입 행의 수량 ≠ 투입 스캔의 투입량": db.v("""
            select count(*) from roll_genealogy g join roll r on r.roll_id = g.child_roll_id
              join material_input mi on mi.work_result_id = r.work_result_id and mi.material_lot_id = g.parent_material_lot_id
             where g.relation = '투입' and g.qty is distinct from mi.input_qty and """ + app),
        "투입 스캔(완료 실적)과 계보 투입 행 불일치": db.v("""
            select count(*) from material_input mi join work_result w on w.work_result_id = mi.work_result_id and w.status = '완료'
              join roll r on r.work_result_id = w.work_result_id
             where not exists (select 1 from roll_genealogy g where g.parent_material_lot_id = mi.material_lot_id
                                and g.child_roll_id = r.roll_id and g.relation = '투입') and """ + app),
    }
    bad = {k: v for k, v in broken.items() if v}
    rep.add("G-08", "[SQL] Job-Lot-Roll 키 무결성 — D5·D6·D7·D8 의 Job 키와 계보가 서로 맞는다 (DB 전체 · 화면으로 만든 롤)", not bad,
            f"검사 {len(broken)}종 · 어긋난 행 {sum(broken.values())}" + (f" — {bad}" if bad else ""))
    # ── 롤의 Job 키 — 취소된 Job 에 롤이 생기면 안 된다 (F-JOB-03 「작업 실적·롤이 없는 Job 만 취소」 · F-POP-01 「취소·완료 Job 은 422」) ──
    f2 = ctx.flow()
    fg2 = f2.item("FG", "제품")
    f2.item("RM", "원재료")
    cu2 = f2.customer()
    lot2 = f2.lot(f2.code("RM"))
    j_a, j_b, j_x = (f2.job(fg2, cu2, date.today()) for _ in range(3))
    f2.must(api.post("prod", f"/job/orders/{j_x}/cancel"), "작업지시 취소")
    a1, a2, a3, a4 = (f2.print_roll(j_a, [lot2]) for _ in range(4))
    st_x, _ = api.post("prod", "/rll/finishing/splice", {"roll_no": [a1, a2], "job_no": j_x})
    n_x = db.v("select count(*) from roll r join job j on j.job_id = r.job_id where j.job_no = %s", (j_x,))
    st_b, _ = api.post("prod", "/rll/finishing/splice", {"roll_no": [a3, a4], "job_no": j_b})
    n_b = db.v("select count(*) from roll r join job j on j.job_id = r.job_id where j.job_no = %s", (j_b,))
    # 재검(웨이브 D 뒤): 계약 F-RLL-02 에 문장이 생겼다(D-208 확정) — 「`job_no` 는 부모 롤의 Job 중 하나여야 하고(그 밖의 Job 은 422),
    # 취소·완료된 Job 은 422」. 그래서 무관한 Job · 마감(`완료`)한 부모 Job 도 판정에 넣는다(전에는 사람 확인으로 적기만 했다).
    j_d = f2.job(fg2, cu2, date.today())
    d1 = f2.print_roll(j_d, [lot2])
    f2.must(api.post("prod", f"/job/orders/{j_d}", {"status": "완료"}), "작업지시 마감")
    st_d, _ = api.post("prod", "/rll/finishing/splice", {"roll_no": [a3, d1], "job_no": j_d})
    n_d = db.v("select count(*) from roll r join job j on j.job_id = r.job_id where j.job_no = %s and r.process_type <> '인쇄'", (j_d,))
    kept = db.v("select count(*) from v_roll_state s join roll r on r.roll_id = s.roll_id where r.roll_no = any(%s) and s.state = '재고'",
                ([a1, a2, a3, a4, d1],))
    rep.add("G-08", "[API] 롤의 Job 키를 지킨다 — splice 의 Job 지정으로 취소된 Job 에 롤이 생기지 않는다",
            st_x == 422 and n_x == 0 and st_b == 422 and n_b == 0 and st_d == 422 and n_d == 0 and kept == 5,
            f"부모 2개(같은 Job) + job_no=취소된 Job → HTTP {st_x} · 취소 Job 의 롤 {n_x}개 (기대 422 · 0개) / "
            f"부모와 무관한 `등록` Job 지정 → HTTP {st_b} · 그 Job 의 롤 {n_b}개 (기대 422 · 0개 — F-RLL-02 · D-208) / "
            f"부모의 Job 이지만 `완료` 로 마감한 Job 지정 → HTTP {st_d} · 그 Job 의 후가공 롤 {n_d}개 (기대 422 · 0개) / 422 뒤 부모 롤 재고 {kept}/5")
    # ── COA: 그 출하의 롤마다 최신 검사 (D6 → D7 → D8) ──
    f3 = ctx.flow()
    fg3 = f3.item("FG", "제품")
    f3.item("RM", "원재료")
    j3 = f3.job(fg3, f3.customer(), date.today())
    lot3 = f3.lot(f3.code("RM"))
    r_a, r_b = f3.print_roll(j3, [lot3]), f3.print_roll(j3, [lot3])
    f3.inspect(r_a, "불합격", "7.77")
    f3.inspect(r_a, "합격", "1.11")
    sh3 = f3.shipment(j3, date.today())
    f3.scan(sh3, r_a)
    f3.scan(sh3, r_b)
    coa = f3.approve(sh3)
    r = api.get("admin", f"/shp/coa/{sh3}/print")
    t = text_of_html(main_of(r.text)) if r.status_code == 200 else ""
    ok = r.status_code == 200 and all(x in t for x in (coa, sh3, j3, r_a, r_b, "1.11", NOT_COLLECTED)) and "7.77" not in t
    rep.add("G-08", "[화면] COA(GET /shp/coa/{출하 LOT}/print) — 출하 롤마다 최신 검사 · 검사 없는 롤은 미수집", ok,
            f"HTTP {r.status_code} · COA·출하 LOT·Job·롤 2개 {'보임' if all(x in t for x in (coa, sh3, j3, r_a, r_b)) else '빠짐'} · "
            f"최신 ΔE 1.11 {'보임' if '1.11' in t else '안 보임'} · 옛 검사 7.77 {'안 보임' if '7.77' not in t else '보임'} · 미검사 롤 {'미수집' if NOT_COLLECTED in t else '표시 없음'}")
    # ── 채번 한 곳 (정적) ──
    hits = numbering_static()
    rep.add("G-08", "[정적] 번호를 만드는 코드는 app/numbering.py 한 곳", not hits["violations"],
            f"번호 컬럼 INSERT {hits['inserts']}곳 전부 numbering.next 경유 · 카운터(sys_number_seq)를 쓰는 파일 {hits['seq_writers']} · "
            f"업무 번호 둘레의 자리 채움·날짜 조립 {hits['compose'] or 0} (번호와 무관한 자리 채움 {hits['other_pad'] or 0})"
            + (f" — 위반 {hits['violations'][:3]}" if hits["violations"] else "")
            + (f" · 예외(이관 배치 — 기존 번호 그대로, D-303) {hits['migration']}" if hits["migration"] else ""))
    # ── 채번 (동적): 형식 · 중복 · 동시 발번 ──
    rules = {r["seq_kind"]: r for r in db.q("select seq_kind, prefix, date_format, seq_digits from sys_number_rule")}
    numbers = defaultdict(list)
    for f in ctx.flows:
        for k, v in f.numbers.items():
            numbers[k] += v
    bad_fmt = []
    for kind_, nos in numbers.items():
        r = rules.get(kind_)
        if r is None:
            bad_fmt.append(f"{kind_}: 형식 행 없음")
            continue
        date_part = db.v("select case when %(f)s = '' then '' else to_char(now(), %(f)s) end", {"f": r["date_format"]})
        pat = re.compile("^" + re.escape(r["prefix"] + date_part) + r"\d{" + str(r["seq_digits"]) + r",}$")
        bad_fmt += [f"{kind_}:{n}" for n in nos if not pat.match(n)]
    dup = sum(len(v) - len(set(v)) for v in numbers.values())
    made: list[str] = []
    fg, cu = db.v("select item_id from item where item_code = %s", (flow.code("FG"),)), db.v("select customer_id from customer where customer_code = %s", (flow.code("CU"),))

    def create_job() -> None:
        c = api.new_client("prod")
        r = c.post("/job/orders", data={"item_id": str(fg), "customer_id": str(cu), "order_qty": "1", "due_date": str(date.today())}, follow_redirects=False)
        if r.status_code == 200:
            made.append(r.json()["job_no"])

    ts = [threading.Thread(target=create_job) for _ in range(6)]
    for t_ in ts:
        t_.start()
    for t_ in ts:
        t_.join()
    kinds_seen = sorted(numbers)
    design_kinds = set(rules) - EXT_KINDS                           # 설계도의 번호 6종 — 확장 종류(D-418)는 이 흐름이 발번하지 않는다
    rep.add("G-08", "[동적] 받은 번호가 전부 sys_number_rule 형식 · 중복 0 · 동시 발번 중복 0",
            not bad_fmt and dup == 0 and len(made) == 6 and len(set(made)) == 6 and set(kinds_seen) == design_kinds,
            f"번호 {sum(len(v) for v in numbers.values())}개 (종류 {len(kinds_seen)}/{len(design_kinds)}"
            + (f" + 확장 {sorted(set(rules) & EXT_KINDS)}" if set(rules) & EXT_KINDS else "") + ": " + " · ".join(f"{k} {len(numbers[k])}" for k in kinds_seen)
            + f") · 형식 어긋남 {len(bad_fmt)} · 중복 {dup} · 동시 6건 → 서로 다른 번호 {len(set(made))}" + (f" — {bad_fmt[:3]}" if bad_fmt else ""))


#: 업무 번호 컬럼 → 채번 종류 (설계도 6종 + 확장 — 정적 검사는 확장 테이블도 numbering.next 경유를 요구한다)
NUMBER_COLUMNS = {("job", "job_no"): "JOB", ("job_lot", "lot_no"): "JOB_LOT", ("material_lot", "lot_no"): "MAT_LOT",
                  ("roll", "roll_no"): "ROLL", ("shipment", "shipment_no"): "SHIPMENT", ("shipment", "coa_no"): "COA",
                  ("sales_order", "order_no"): "SALES_ORDER"}
#: 설계도 밖 확장(D-418)의 번호 종류 — QA 흐름이 발번하지 않으므로 동적 대조(종류 집합)에서만 뺀다
EXT_KINDS = {"SALES_ORDER"}


def numbering_static() -> dict:
    """`src/` 전체에서 번호 컬럼을 채우는 INSERT/UPDATE 를 찾아, 그 함수가 `numbering.next` 를 부르는지 본다."""
    out = {"inserts": 0, "violations": [], "migration": [], "seq_writers": [], "compose": [], "other_pad": []}
    for p in sorted((SRC / "lcomfine").rglob("*.py")):
        rel = str(p.relative_to(SRC / "lcomfine"))
        text = p.read_text(encoding="utf-8")
        if "sys_number_seq" in _scan_sql_text(text, lambda e: f"?{e}"):
            out["seq_writers"].append(rel)
        if rel == "app/numbering.py":
            continue
        lines = text.splitlines()
        for i, ln in enumerate(lines, start=1):                   # 번호를 손으로 조립하는 흔적 — 자리 채움 · 날짜 글자
            if re.search(r"\.zfill\(|\.rjust\(|:0\d+d\}|strftime\([\"']%y%m%d|to_char\([^)]*YYMMDD", ln):
                near = "\n".join(lines[max(0, i - 15):i + 15])    # 그 둘레에서 업무 번호 컬럼을 만지는가 (화면 ID 같은 것은 번호가 아니다)
                (out["compose"] if re.search(r"\b(job_no|lot_no|roll_no|shipment_no|coa_no)\b", near) else out["other_pad"]).append(f"{rel}:{i}")
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            src = ast.get_source_segment(text, node) or ""
            for (table, col), kind_ in NUMBER_COLUMNS.items():
                ins = re.search(rf"insert\s+into\s+{table}\s*\(([^)]*)\)", src, re.I | re.S)
                upd = re.search(rf"update\s+{table}\s+set\b[^;]*?\b{col}\s*=", src, re.I | re.S)
                if not ((ins and re.search(rf"\b{col}\b", ins.group(1))) or (upd and col == "coa_no")):
                    continue
                out["inserts"] += 1
                uses = re.search(rf"numbering\.next\(\s*(numbering\.{kind_}|[\"']{kind_}[\"'])", src) is not None
                if rel.startswith("migration/"):
                    out["migration"].append(f"{rel}:{node.name}({table}.{col})")
                    out["inserts"] -= 1
                elif rel.startswith("db/seed") and uses:
                    pass
                elif not uses:
                    out["violations"].append(f"{rel}:{node.name} — {table}.{col} 을 numbering.next('{kind_}') 없이 채운다")
    out["violations"] += [f"자리 채움·날짜 조립 {x}" for x in out["compose"]]
    out["seq_writers"] = sorted(set(out["seq_writers"]))
    if out["seq_writers"] != ["app/numbering.py"]:
        out["violations"].append(f"sys_number_seq 에 쓰는 파일 {out['seq_writers']}")
    return out


# ── G-09 시드 ───────────────────────────────────────────────────────────
#: 시드가 넣은 행(등록자 `seed`)의 이름·글자 컬럼 — `(예시)` 가 붙어 있어야 한다
SEED_NAME_COLUMNS = [
    ("item", "item_name", "created_by"), ("customer", "customer_name", "created_by"), ("process", "process_name", "created_by"),
    ("equipment", "equipment_name", "created_by"), ("defect_code", "defect_name", "created_by"),
    ("plate_spec", "plate_name", "created_by"), ("anilox", "anilox_name", "created_by"), ("ink_formula", "ink_name", "created_by"),
    ("ink_formula", "color_name", "created_by"), ("sys_user", "user_name", "created_by"),
    ("material_lot", "supplier_name", "received_by"), ("material_lot", "note", "received_by"), ("material_lot", "insp_note", "received_by"),
]
SEED_COUNT_SQL = {
    "item": "select count(*) from item where created_by = 'seed'", "customer": "select count(*) from customer where created_by = 'seed'",
    "process": "select count(*) from process where created_by = 'seed'", "equipment": "select count(*) from equipment where created_by = 'seed'",
    "defect_code": "select count(*) from defect_code where created_by = 'seed'", "plate_spec": "select count(*) from plate_spec where created_by = 'seed'",
    "anilox": "select count(*) from anilox where created_by = 'seed'", "ink_formula": "select count(*) from ink_formula where created_by = 'seed'",
    "ink_formula_component": "select count(*) from ink_formula_component where ink_formula_id in (select ink_formula_id from ink_formula where created_by = 'seed')",
    "material_lot": "select count(*) from material_lot where received_by = 'seed'",
    "sys_user": "select count(*) from sys_user where created_by = 'seed'", "sys_role": "select count(*) from sys_role",
    "sys_permission": "select count(*) from sys_permission", "sys_number_rule": "select count(*) from sys_number_rule",
}
REAL_NAME_RE = re.compile(r"\(주\)|㈜|주식회사|유한회사|\bCo\.?,?\s*Ltd|\bInc\b|\bCorp\b|엘컴|lcom", re.I)


def seed_counts(db: Db) -> dict[str, int]:
    return {k: db.v(sql) for k, sql in SEED_COUNT_SQL.items()}


def seed_content(db: Db) -> str:
    """시드 행의 내용 해시 — 수정 시각·비밀번호 해시(시드가 매번 다시 쓴다)를 뺀다."""
    parts = []
    for t, who in (("item", "created_by"), ("customer", "created_by"), ("process", "created_by"), ("equipment", "created_by"),
                   ("defect_code", "created_by"), ("plate_spec", "created_by"), ("anilox", "created_by"), ("ink_formula", "created_by"),
                   ("material_lot", "received_by")):
        parts.append(db.v(f"select coalesce(string_agg(md5((to_jsonb(x) - 'updated_at')::text), '' order by md5((to_jsonb(x) - 'updated_at')::text)), '') "
                          f"from {t} x where {who} = 'seed'"))
    for t in ("sys_role", "sys_permission", "sys_number_rule"):
        parts.append(db.v(f"select coalesce(string_agg(md5((to_jsonb(x) - 'updated_at')::text), '' order by md5((to_jsonb(x) - 'updated_at')::text)), '') from {t} x"))
    parts.append(db.v("""select coalesce(string_agg(login_id || user_name || role_code || status, ',' order by login_id), '')
                           from sys_user where created_by = 'seed'"""))
    return hashlib.md5("|".join(parts).encode()).hexdigest()


def check_g09(ctx: Ctx, rep: Report, run_seeds: bool) -> None:
    db = ctx.db
    # (예시) 표기
    total, missing = 0, []
    for table, col, who in SEED_NAME_COLUMNS:
        for r in db.q(f"select {col} as v from {table} where {who} = 'seed' and {col} is not null"):
            total += 1
            if "(예시)" not in r["v"]:
                missing.append(f"{table}.{col}={r['v']!r}")
    codes = []
    for table, col in (("item", "item_code"), ("customer", "customer_code"), ("process", "process_code"), ("equipment", "equipment_code"),
                       ("defect_code", "defect_code"), ("plate_spec", "plate_code"), ("anilox", "anilox_code"), ("ink_formula", "ink_code")):
        codes += [f"{table}.{col}={r['v']}" for r in db.q(f"select {col} as v from {table} where created_by = 'seed'") if not r["v"].startswith("EX-")]
    rep.add("G-09", "시드가 넣은 이름·글자 값에 `(예시)` · 업무 코드는 `EX-` (실제 DB 의 시드 행)", total > 0 and not missing and not codes,
            f"이름·글자 값 {total}개 · (예시) 없는 값 {len(missing)}" + (f" {missing[:3]}" if missing else "")
            + f" · EX- 가 아닌 코드 {len(codes)}" + (f" {codes[:3]}" if codes else ""))
    # 그 밖의 시드 값 — 이름은 아니지만 지어낸 값일 수 있는 것
    other = []
    for r in db.q("select defect_code, defect_group from defect_code where created_by = 'seed' and defect_group is not null"):
        if "(예시)" not in r["defect_group"]:
            other.append(f"defect_code.defect_group={r['defect_group']!r}")
    for r in db.q("select item_code, spec from item where created_by = 'seed' and spec is not null"):
        other.append(f"item.spec={r['spec']!r}")
    spec_values = db.v("""select (select count(*) from plate_spec where created_by = 'seed' and color_count is not null)
                               + (select count(*) from anilox where created_by = 'seed' and (line_count is not null or cell_volume is not null))
                               + (select count(*) from ink_formula where created_by = 'seed' and (target_l is not null or target_a is not null or target_b is not null))""")
    src_hits = []
    for p in sorted((SRC / "lcomfine/db").glob("seed*.py")):
        for i, ln in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
            code = ln.split("#")[0]
            if REAL_NAME_RE.search(code) and "lcomfine" not in code.lower():
                src_hits.append(f"{p.name}:{i}")
    db_hits = []
    for table, col, who in SEED_NAME_COLUMNS:
        db_hits += [f"{table}.{col}={r['v']!r}" for r in db.q(f"select {col} as v from {table} where {who} = 'seed' and {col} is not null")
                    if REAL_NAME_RE.search(r["v"])]
    distinct_groups = sorted({o.split("=")[1] for o in other if o.startswith("defect_code.defect_group")})
    rep.add("G-09", "실 고객명·품목명·규격값처럼 보이는 지어낸 값 없음 (시드 소스 + 시드 행)", not src_hits and not db_hits and spec_values == 0,
            f"회사명 꼴(㈜·주식회사·Co., Ltd 등) 소스 {len(src_hits)} · 행 {len(db_hits)} · 규격 숫자(도수·선수·셀 용적·기준 색상값)를 채운 시드 행 {spec_values}"
            + (f" · 참고: `(예시)` 없이 들어간 분류 값 {distinct_groups} (설계도의 공정 이름)" if distinct_groups else ""))
    # 멱등
    if not run_seeds:
        rep.add("G-09", "시드 2회 실행 — 행 수 diff 0", UNVERIFIED,
                "이 실행에서는 시드를 돌리지 않았다 — `uv run python tools/check_data.py --run-seeds` (`make gate-full`)")
        return
    c0, h0 = seed_counts(db), seed_content(db)
    runs = []
    for _ in range(2):
        p = subprocess.run(["uv", "run", "python", "-m", "lcomfine.db.seed"], cwd=ROOT, capture_output=True, text=True, timeout=300)
        runs.append(p.returncode)
    c2, h2 = seed_counts(db), seed_content(db)
    diff = {k: (c0[k], c2[k]) for k in c0 if c0[k] != c2[k]}
    mods = ["lcomfine.db.seed"] + [f"lcomfine.db.{n}" for n in ("seed_dev1", "seed_dev2", "seed_dev3") if (SRC / "lcomfine/db" / f"{n}.py").exists()]
    rep.add("G-09", "시드 2회 실행 — 시드 행 수 diff 0 · 내용 그대로", runs == [0, 0] and not diff and h0 == h2,
            f"`python -m lcomfine.db.seed` ×2 종료코드 {runs} (공통 → {' → '.join(x.split('.')[-1] for x in mods[1:])}) · 시드 행 {sum(c2.values())}개"
            f"(테이블 {len(c2)}) diff {diff or 0} · 내용 해시 {'같음' if h0 == h2 else '다름'} (시드가 넣은 행 기준 — 다른 QA 의 동시 쓰기와 구분)")


# ── G-10 집계 ───────────────────────────────────────────────────────────
#: 산식 문장(contracts/interfaces.md §7 · D-25 · D-301)만 보고 따로 짠 SQL. 품목은 job.item_id, 날짜는 DB 세션 시간대의 날짜.
SQL_PRODUCTION = """
with done as (
    select w.work_result_id, w.output_qty, (select j.item_id from job j where j.job_id = w.job_id) as item_id
      from work_result w
     where w.status = '완료'
       and (w.ended_at at time zone current_setting('TimeZone'))::date >= %(d1)s
       and (w.ended_at at time zone current_setting('TimeZone'))::date <= %(d2)s
)
select d.item_id, count(*) as work_count, coalesce(sum(d.output_qty), 0) as output_qty,
       (select coalesce(sum(s.scrap_qty), 0) from work_scrap s
         where s.work_result_id in (select x.work_result_id from done x where x.item_id = d.item_id)) as scrap_qty
  from done d
 where %(item)s::bigint is null or d.item_id = %(item)s::bigint
 group by d.item_id
"""
SQL_QUALITY = """
select (select j.item_id from job j where j.job_id = n.job_id) as item_id,
       count(*) as inspection_count,
       sum(case when n.result = '불합격' then 1 else 0 end) as fail_count,
       sum(n.delta_e) as delta_sum, count(n.delta_e) as delta_n
  from inspection n
 where (n.inspected_at at time zone current_setting('TimeZone'))::date between %(d1)s and %(d2)s
   and (%(item)s::bigint is null or n.job_id in (select job_id from job where item_id = %(item)s::bigint))
 group by 1
"""
SQL_DEFECT = """
select (select dc.defect_code from defect_code dc where dc.defect_code_id = x.defect_code_id) as defect_code,
       count(*) as defect_count, count(distinct n.roll_id) as roll_count
  from inspection_defect x, inspection n
 where n.inspection_id = x.inspection_id
   and (n.inspected_at at time zone current_setting('TimeZone'))::date between %(d1)s and %(d2)s
   and (%(item)s::bigint is null or n.job_id in (select job_id from job where item_id = %(item)s::bigint))
 group by 1
"""


def sql_production(db: Db, d1: date, d2: date, item: int | None = None) -> dict[int, dict]:
    return {r["item_id"]: {"work_count": r["work_count"], "output_qty": r["output_qty"], "scrap_qty": r["scrap_qty"]}
            for r in db.q(SQL_PRODUCTION, {"d1": d1, "d2": d2, "item": item})}


def sql_quality(db: Db, d1: date, d2: date, item: int | None = None) -> dict[int, dict]:
    out = {}
    for r in db.q(SQL_QUALITY, {"d1": d1, "d2": d2, "item": item}):
        out[r["item_id"]] = {"inspection_count": r["inspection_count"], "fail_count": r["fail_count"],
                             "fail_rate": r["fail_count"] / r["inspection_count"] if r["inspection_count"] else None,
                             "avg_delta_e": (r["delta_sum"] / r["delta_n"]) if r["delta_n"] else None,
                             "_sum": r["delta_sum"] or Decimal(0), "_n": r["delta_n"]}
    return out


def sql_delivery(db: Db, d1: date, d2: date, item: int | None = None, today: date | None = None) -> dict[int, dict]:
    """납기 — Job 과 승인된 출하를 날것으로 읽어 파이썬에서 가른다."""
    today = today or db.v("select current_date")
    jobs = db.q("""select job_id, item_id, due_date from job
                    where due_date between %(d1)s and %(d2)s and status <> '취소'
                      and (%(item)s::bigint is null or item_id = %(item)s::bigint)""", {"d1": d1, "d2": d2, "item": item})
    first: dict[int, date] = {}
    for s in db.q("select job_id, ship_date from shipment where status = '승인' and job_id = any(%s)", ([j["job_id"] for j in jobs],)):
        if s["job_id"] not in first or s["ship_date"] < first[s["job_id"]]:
            first[s["job_id"]] = s["ship_date"]
    out: dict[int, dict] = {}
    for j in jobs:
        o = out.setdefault(j["item_id"], {"job_count": 0, "on_time": 0, "late": 0, "pending": 0})
        o["job_count"] += 1
        ship = first.get(j["job_id"])
        if ship is not None:
            o["on_time" if ship <= j["due_date"] else "late"] += 1
        else:
            o["late" if j["due_date"] < today else "pending"] += 1
    for o in out.values():
        den = o["on_time"] + o["late"]
        o["on_time_rate"] = o["on_time"] / den if den else None
    return out


def sql_defects(db: Db, d1: date, d2: date, item: int | None = None) -> dict[str, dict]:
    return {r["defect_code"]: {"defect_count": r["defect_count"], "roll_count": r["roll_count"]}
            for r in db.q(SQL_DEFECT, {"d1": d1, "d2": d2, "item": item})}


def total_of(kind: str, rows: dict) -> dict | None:
    """품목별 값을 한 줄로 (합계 줄의 기대값). 비율은 더한 값으로 다시 나눈다."""
    if not rows:
        return None
    v = list(rows.values())
    if kind == "production":
        return {k: sum((r[k] for r in v), Decimal(0)) if k != "work_count" else sum(r[k] for r in v) for k in ("work_count", "output_qty", "scrap_qty")}
    if kind == "quality":
        n, f = sum(r["inspection_count"] for r in v), sum(r["fail_count"] for r in v)
        s, c = sum((r["_sum"] for r in v), Decimal(0)), sum(r["_n"] for r in v)
        return {"inspection_count": n, "fail_count": f, "fail_rate": f / n if n else None, "avg_delta_e": s / c if c else None}
    on, late = sum(r["on_time"] for r in v), sum(r["late"] for r in v)
    return {"job_count": sum(r["job_count"] for r in v), "on_time": on, "late": late, "pending": sum(r["pending"] for r in v),
            "on_time_rate": on / (on + late) if on + late else None}


STA_COLUMNS = {"production": [("work_count", 0, 1), ("output_qty", 1, 1), ("scrap_qty", 1, 1)],
               "quality": [("inspection_count", 0, 1), ("fail_count", 0, 1), ("fail_rate", 1, 100), ("avg_delta_e", 2, 1)],
               "delivery": [("job_count", 0, 1), ("on_time", 0, 1), ("late", 0, 1), ("pending", 0, 1), ("on_time_rate", 1, 100)]}


def _cell(html: str):
    t = text_of_html(html)
    if t in ("-", ""):
        return None
    if t == NOT_COLLECTED:
        return NOT_COLLECTED
    return Decimal(t.rstrip("%").replace(",", ""))


def parse_summary(html: str) -> dict[str, dict]:
    """집계 화면 → {kind: {rows: {품목 코드: [칸…]}, total: [칸…]|None, empty: bool}}."""
    out = {}
    for kind in STA_COLUMNS:
        m = re.search(rf'<section class="panel sta-panel" id="{kind}">(.*?)</section>', html, re.S)
        if not m:
            continue
        sec = m.group(1)
        tbody = re.search(r"<tbody>(.*?)</tbody>", sec, re.S).group(1)
        rows = {}
        for tr in re.findall(r"<tr>(.*?)</tr>", tbody, re.S):
            tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
            code = re.search(r"<code>(.*?)</code>", tds[0])
            if code:
                rows[code.group(1)] = [_cell(td) for td in tds[1:]]
        foot = re.search(r"<tfoot>(.*?)</tfoot>", sec, re.S)
        total = [_cell(td) for td in re.findall(r"<td[^>]*>(.*?)</td>", foot.group(1), re.S)] if foot else None
        out[kind] = {"rows": rows, "total": total, "empty": NOT_COLLECTED in text_of_html(tbody)}
    return out


def plain(cells) -> str:
    """화면 칸 값들을 글자로 (없음은 `-`)."""
    if cells is None:
        return "없음"
    return "[" + ", ".join("-" if c is None else str(c) for c in cells) + "]"


def diff_cells(kind: str, label: str, shown: list | None, want: dict | None) -> tuple[int, list[str]]:
    """화면의 한 줄(표시값) ↔ 기대값. 화면은 표시 자릿수로 자르므로 그 자릿수의 반 단위까지 허용한다. → (대조한 칸 수, 다른 칸)."""
    cols = STA_COLUMNS[kind]
    if want is None or shown is None:
        return (1, [] if want is None and shown is None else [f"{label}: 화면 {'없음' if shown is None else '있음'} ≠ 기대 {'없음' if want is None else '있음'}"])
    bad = []
    for (name, digits, scale), got in zip(cols, shown):
        exp = want[name]
        if exp is None or got is None:
            if exp is not None or got is not None:
                bad.append(f"{label}.{name}: 화면 {got} ≠ 기대 {exp}")
            continue
        exp = Decimal(str(exp)) * scale
        tol = Decimal(1) / (Decimal(10) ** digits) / 2 if digits else Decimal(0)
        if abs(Decimal(got) - exp) > tol + Decimal("0.0000001"):
            bad.append(f"{label}.{name}: 화면 {got} ≠ 기대 {round(exp, digits + 2)}")
    return len(cols), bad


def build_stats_data(ctx: Ctx) -> dict:
    """집계 검사용 데이터 — 화면 API 로 만들고, API 로는 줄 수 없는 시각(작업 종료·검사 일시)만 내 행에 한해 SQL 로 옮긴다."""
    db = ctx.db
    f = ctx.flow()
    a, b = f.item("FGA", "제품"), f.item("FGB", "제품")
    f.item("RM", "원재료")
    cu = f.customer()
    dx, dy = f.defect("DX"), f.defect("DY")
    lot = f.lot(f.code("RM"), "100000")
    far = date.today() + timedelta(days=400)                      # 생산·품질용 Job 의 납기 — 납기 집계의 기간 밖
    ja1, ja2, jb = f.job(a, cu, far), f.job(a, cu, far), f.job(b, cu, far)
    P1, P2 = date(2001, 3, 1), date(2001, 3, 31)                  # 생산·품질의 기간 — 다른 데이터가 없는 옛 달

    def work(job: str, qty: str, ended: str | None, unit: str = "", scraps: tuple[str, ...] = (), finish: bool = True) -> tuple[int, str | None]:
        wid = f.start(job)
        f.input(wid, lot, "1")
        for s in scraps:
            f.must(f.api.post("prod", "/pop/stops/scrap", {"work_id": str(wid), "scrap_qty": s, "defect_code": dx}), "폐기 등록")
        roll = None
        if finish:
            roll = f.finish(wid, qty, unit)
            f._roll(roll, "인쇄", job)
            f.edges.add((lot, roll, "투입"))
            db.x("update work_result set started_at = %(t)s::timestamptz - interval '1 hour', ended_at = %(t)s::timestamptz where work_result_id = %(w)s",
                 {"t": ended, "w": wid})
        else:
            db.x("update work_result set started_at = %s::timestamptz where work_result_id = %s", (ended, wid))
        return wid, roll

    # 생산 — 품목 A: 기간 안 3건(가운데 · 끝날 23:59:59 · 첫날 00:00:00), 밖 2건(다음 날 00:00:00 · 전날 23:59:59), 진행 중 1건
    _, ra1 = work(ja1, "100.5", "2001-03-15 10:00:00", scraps=("2", "3.5"))        # 폐기 2 + 3.5 (폐기 시각은 오늘 — 실적이 대상이면 센다, D-301)
    _, ra2 = work(ja1, "0", "2001-03-31 23:59:59")                                 # 끝날의 마지막 초 · 실적 수량 0
    work(ja1, "7", "2001-04-01 00:00:00")                                          # 다음 날 0시 — 제외
    work(ja2, "20.25", "2001-03-01 00:00:00", unit="kg")                           # 첫날 0시 · 단위가 다르다(kg) · 다른 Job 같은 품목
    work(ja2, "9", "2001-02-28 23:59:59", scraps=("1",))                           # 전날 — 제외 (폐기도 제외)
    work(ja2, "0", "2001-03-10 09:00:00", finish=False)                            # 진행 중 — 제외
    _, rb = work(jb, "50", "2001-03-20 12:00:00")                                  # 품목 B
    expect_prod = {a: {"work_count": 3, "output_qty": Decimal("120.75"), "scrap_qty": Decimal("5.5")},
                   b: {"work_count": 1, "output_qty": Decimal("50"), "scrap_qty": Decimal("0")}}

    # 품질 — 롤 ra1 은 검사 3번(불합격 · 불합격(ΔE 없음) · 합격), ra2 는 2번(하나는 기간 밖), rb 는 ΔE 없는 합격 1번
    def insp(roll: str, result: str, de: str, at: str, defects=None) -> int:
        iid = f.inspect(roll, result, de, defects)
        db.x("update inspection set inspected_at = %s::timestamptz where inspection_id = %s", (at, iid))
        return iid

    insp(ra1, "불합격", "5.25", "2001-03-10 09:00:00", [(dx, "L10"), (dx, "L20"), (dy, "R5")])
    insp(ra1, "불합격", "", "2001-03-11 09:00:00", [(dx, "L30")])
    insp(ra1, "합격", "1.10", "2001-03-31 23:59:59")
    insp(ra2, "합격", "2.00", "2001-04-01 00:00:00", [(dx, "X")])                 # 기간 밖
    insp(ra2, "합격", "0.65", "2001-03-01 00:00:00", [(dy, "R1")])
    insp(rb, "합격", "", "2001-03-20 09:00:00", [(dy, "R9")])
    avg_a = (Decimal("5.25") + Decimal("1.10") + Decimal("0.65")) / 3
    expect_qual = {a: {"inspection_count": 4, "fail_count": 2, "fail_rate": 0.5, "avg_delta_e": avg_a, "_sum": Decimal("7.00"), "_n": 3},
                   b: {"inspection_count": 1, "fail_count": 0, "fail_rate": 0.0, "avg_delta_e": None, "_sum": Decimal(0), "_n": 0}}
    expect_def_a = {dx: {"defect_count": 3, "roll_count": 1}, dy: {"defect_count": 2, "roll_count": 2}}
    expect_def_all = {dx: {"defect_count": 3, "roll_count": 1}, dy: {"defect_count": 3, "roll_count": 3}}

    # 납기 — 오늘 기준. 기간 = 오늘−5 ~ 오늘+5
    T = db.v("select current_date")
    d = lambda n: T + timedelta(days=n)   # noqa: E731

    def shipped(job: str, ship_day: date, approve: bool = True, cancel: bool = False) -> None:
        roll = f.print_roll(job, [lot])
        sh = f.shipment(job, ship_day)
        f.scan(sh, roll)
        if cancel:
            f.cancel_shipment(sh)
        elif approve:
            f.approve(sh)

    j = f.job(a, cu, d(2)); shipped(j, d(1))                                        # 준수 (출하일 < 납기)      # noqa: E702
    j = f.job(a, cu, d(-2)); shipped(j, d(-1))                                      # 지연 (출하일 > 납기)      # noqa: E702
    j = f.job(a, cu, d(1)); shipped(j, d(3)); shipped(j, d(1))                      # 승인 출하 2건 — 이른 날 = 납기 → 준수 (경계 ≤)  # noqa: E702
    j = f.job(a, cu, d(-1)); shipped(j, d(-3), approve=False)                       # 등록만 한 출하 · 납기 지남 → 지연  # noqa: E702
    f.job(a, cu, d(0))                                                              # 납기 = 오늘 · 출하 없음 → 미출하 (경계)
    j = f.job(a, cu, d(4)); shipped(j, d(0), cancel=True)                           # 취소한 출하뿐 → 미출하   # noqa: E702
    j = f.job(a, cu, d(-1)); f.must(f.api.post("prod", f"/job/orders/{j}/cancel"), "작업지시 취소")   # 취소 Job — 제외  # noqa: E702
    f.job(a, cu, d(-6))                                                             # 기간 밖 (하루 앞)
    f.job(a, cu, d(6))                                                              # 기간 밖 (하루 뒤)
    j = f.job(a, cu, d(5)); f.must(f.api.post("prod", f"/job/orders/{j}", {"status": "완료"}), "작업지시 마감")  # 끝날 · 완료 Job → 미출하  # noqa: E702
    f.job(a, cu, d(-5))                                                             # 첫날 · 출하 없음 → 지연
    f.job(b, cu, d(1))                                                              # 품목 B — 미출하뿐 → 준수율 분모 0
    expect_del = {a: {"job_count": 8, "on_time": 2, "late": 3, "pending": 3, "on_time_rate": 0.4},
                  b: {"job_count": 1, "on_time": 0, "late": 0, "pending": 1, "on_time_rate": None}}
    return {"flow": f, "a": a, "b": b, "codes": {a: f.code("FGA"), b: f.code("FGB")}, "P": (P1, P2), "D": (d(-5), d(5)), "today": T,
            "expect": {"production": expect_prod, "quality": expect_qual, "delivery": expect_del},
            "defects": {"a": expect_def_a, "all": expect_def_all}, "dx": dx, "dy": dy}


def check_g10(ctx: Ctx, rep: Report) -> dict:
    api, db = ctx.api, ctx.db
    s = build_stats_data(ctx)
    a, b, codes = s["a"], s["b"], s["codes"]
    detail: dict = {}
    sql_fn = {"production": sql_production, "quality": sql_quality, "delivery": sql_delivery}
    labels = {"production": "생산", "quality": "품질", "delivery": "납기"}
    for kind in ("production", "quality", "delivery"):
        d1, d2 = s["P"] if kind != "delivery" else s["D"]
        n_cells, bad = 0, []
        # (1) 내 독립 SQL = 데이터를 만들며 정한 기대값
        mine = sql_fn[kind](db, d1, d2)
        mine_own = {k: v for k, v in mine.items() if k in (a, b)}
        for item in (a, b):
            exp, got = s["expect"][kind][item], mine_own.get(item)
            for k, v in exp.items():
                n_cells += 1
                gv = got.get(k) if got else None
                if (v is None) != (gv is None) or (v is not None and abs(Decimal(str(gv)) - Decimal(str(v))) > Decimal("0.0000001")):
                    bad.append(f"독립 SQL {codes[item]}.{k} {gv} ≠ 설계한 값 {v}")
        # (2) 화면(품목 조건) = 독립 SQL
        shown_rows = {}
        for item in (a, b):
            for path in (f"/sta/summary/{kind}", "/sta/summary"):
                r = api.get("admin", path, {"date_from": str(d1), "date_to": str(d2), "item_id": str(item)})
                scr = parse_summary(r.text).get(kind) if r.status_code == 200 else None
                if scr is None:
                    bad.append(f"{path} HTTP {r.status_code}")
                    continue
                want = sql_fn[kind](db, d1, d2, item).get(item)
                n, x = diff_cells(kind, f"{path}?item={codes[item]}", scr["rows"].get(codes[item]), want)
                n_cells += n
                bad += x
                n, x = diff_cells(kind, f"{path}?item={codes[item]} 합계", scr["total"], total_of(kind, {item: want} if want else {}))
                n_cells += n
                bad += x
                shown_rows[item] = scr["rows"].get(codes[item])
        # (3) 화면(전체 품목) = 독립 SQL — 그 사이 다른 QA 가 쓰면 달라질 수 있어 세 번까지 다시 잰다
        for attempt in range(5):
            before = sql_fn[kind](db, d1, d2)
            r = api.get("qc", f"/sta/summary/{kind}", {"date_from": str(d1), "date_to": str(d2)})
            after = sql_fn[kind](db, d1, d2)
            if before == after:
                break
        scr = parse_summary(r.text)[kind]
        code_of = {x["item_id"]: x["item_code"] for x in db.q("select item_id, item_code from item where item_id = any(%s)", (list(after),))}
        x_all, n_all = [], 0
        for item, want in after.items():
            n, x = diff_cells(kind, f"전체 {code_of[item]}", scr["rows"].get(code_of[item]), want)
            n_all += n
            x_all += x
        if set(scr["rows"]) != set(code_of.values()):
            x_all.append(f"전체 품목 화면 {len(scr['rows'])}종 ≠ 독립 SQL {len(after)}종")
        n, x = diff_cells(kind, "전체 합계", scr["total"], total_of(kind, after))
        n_cells += n_all + n
        bad += x_all + x
        # (4) stats 함수의 반환값(반올림 전) = 독립 SQL
        from lcomfine.app import stats

        fn_rows = {r["item_id"]: r for r in getattr(stats, kind)(d1, d2)}
        for item in (a, b):
            for k, v in s["expect"][kind][item].items():
                if k.startswith("_"):
                    continue
                n_cells += 1
                gv = fn_rows.get(item, {}).get(k)
                if (v is None) != (gv is None) or (v is not None and abs(Decimal(str(gv)) - Decimal(str(v))) > Decimal("0.000000001")):
                    bad.append(f"stats.{kind} {codes[item]}.{k} {gv} ≠ {v}")
        ea, eb = s["expect"][kind][a], s["expect"][kind][b]
        show = lambda e: " · ".join(f"{k} {round(v, 4) if isinstance(v, (float, Decimal)) else v}" for k, v in e.items() if not k.startswith("_"))   # noqa: E731
        note = {"production": "경계: 끝날 23:59:59 포함 · 다음 날 00:00 제외 · 첫날 00:00 포함 · 수량 0 · 진행 중 제외 · m+kg 섞어 더함(D-301)",
                "quality": "경계: 한 롤 검사 3번 = 3행 · ΔE 없는 검사는 평균에서 제외 · B 는 평균 없음(-)",
                "delivery": "경계: 출하일 = 납기 → 준수 · 납기 = 오늘 → 미출하 · 등록·취소 출하는 안 본다 · 취소 Job 제외 · B 는 분모 0(-)"}[kind]
        rep.add("G-10", f"{labels[kind]} 집계 — 화면(GET /sta/summary/{kind}) = 독립 SQL = 설계한 기대값", not bad,
                f"대조 {n_cells}칸 · 불일치 {len(bad)} · {d1}~{d2} 품목 A [{show(ea)}] 화면 {plain(shown_rows.get(a))} · B [{show(eb)}] 화면 {plain(shown_rows.get(b))} · {note}"
                + (f" — {bad[:3]}" if bad else ""))
        detail[kind] = {"cells": n_cells, "bad": bad, "screen": {"A": plain(shown_rows.get(a)), "B": plain(shown_rows.get(b))},
                        "sql": {"A": {k: v for k, v in (mine_own.get(a) or {}).items() if not k.startswith("_")},
                                "B": {k: v for k, v in (mine_own.get(b) or {}).items() if not k.startswith("_")}}}

    # 불량 유형별 집계 (F-QUA-05) + 내역 (F-QUA-06)
    d1, d2 = s["P"]
    bad, n_cells, shown = [], 0, {}
    for label, item, expect in (("품목 A", a, s["defects"]["a"]), ("전체", None, s["defects"]["all"])):
        mine = sql_defects(db, d1, d2, item)
        mine_own = {k: v for k, v in mine.items() if k in (s["dx"], s["dy"])}
        if mine_own != expect:
            bad.append(f"{label}: 독립 SQL {mine_own} ≠ 설계한 값 {expect}")
        params = {"date_from": str(d1), "date_to": str(d2)} | ({"item_id": str(item)} if item else {})
        r = api.get("qc", "/qua/defect-stats", params)
        body = main_of(r.text)
        tbody = re.search(r"<tbody>(.*?)</tbody>", body, re.S).group(1)
        rows = {}
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", tbody, re.S):
            tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
            code = re.search(r"<code>(.*?)</code>", tds[0]) if tds else None
            if code:
                rows[code.group(1)] = {"defect_count": int(_cell(tds[2])), "roll_count": int(_cell(tds[3]))}
        shown[label] = {k.split("-")[-1]: (v["defect_count"], v["roll_count"]) for k, v in rows.items() if k in (s["dx"], s["dy"])}
        for code, want in mine.items():
            n_cells += 2
            if rows.get(code) != want:
                bad.append(f"{label} {code}: 화면 {rows.get(code)} ≠ 독립 SQL {want}")
        if set(rows) != set(mine):
            bad.append(f"{label}: 화면의 불량 유형 {len(rows)}종 ≠ 독립 SQL {len(mine)}종")
        total = re.search(r"불량 행 (\d+)건", text_of_html(body))
        if not total or int(total.group(1)) != sum(v["defect_count"] for v in mine.values()):
            bad.append(f"{label}: 화면 제목의 불량 행 {total.group(1) if total else '?'}건 ≠ {sum(v['defect_count'] for v in mine.values())}")
        # 내역: 행 수 = 불량 행 수
        for code in (s["dx"], s["dy"]):
            r = api.get("qc", "/qua/defect-stats/rolls", params | {"defect_code": code})
            sec = re.search(r'<section class="panel grid-panel" id="rolls">(.*?)</section>', r.text, re.S)
            n_rows = len(re.findall(r"<tr>\s*<td>", re.search(r"<tbody>(.*?)</tbody>", sec.group(1), re.S).group(1))) if sec else -1
            n_cells += 1
            if n_rows != mine.get(code, {}).get("defect_count", 0):
                bad.append(f"{label} {code} 내역 {n_rows}행 ≠ 불량 행 {mine.get(code, {}).get('defect_count', 0)}")
    rep.add("G-10", "불량 유형별 집계 — 화면(GET /qua/defect-stats · /rolls) = 독립 SQL = 설계한 기대값", not bad,
            f"대조 {n_cells}칸 · 불일치 {len(bad)} · (불량 행 수, 롤 수) 화면 {shown} · 한 검사에 같은 불량 2행 · 한 롤에 검사 여러 번 · 기간 밖 검사 제외"
            + (f" — {bad[:3]}" if bad else ""))
    detail["defects"] = {"cells": n_cells, "bad": bad, "screen": shown}

    # 현황판 (오늘) — 화면의 큰 숫자 = 독립 SQL
    today = s["today"]
    bad, n_cells, kp = [], 0, {}
    for attempt in range(5):
        want = {k: total_of(k, sql_fn[k](db, today, today)) for k in sql_fn}
        r = api.get("field", "/sta/board", {"device": "board"}, client=api.new_client("field"))
        again = {k: total_of(k, sql_fn[k](db, today, today)) for k in sql_fn}
        if want == again:
            break
    tiles = re.findall(r'<section class="panel tile">(.*?)</section>', r.text, re.S)
    names = {"생산": "production", "품질": "quality", "납기": "delivery"}
    for tile in tiles:
        title = text_of_html(re.search(r"<h2>(.*?)<small", tile, re.S).group(1))
        kind = names.get(title)
        kpis = [_cell(v) for v in re.findall(r'<div class="kpi[^"]*"><span>.*?</span><b>(.*?)</b></div>', tile, re.S)]
        kp[title] = plain(kpis)
        shown_k = None if kpis == [NOT_COLLECTED] else kpis
        n, x = diff_cells(kind, f"현황판 {title}", shown_k, want[kind])
        n_cells += n
        bad += x
    rep.add("G-10", "현황판 — 화면(GET /sta/board) 오늘의 생산·품질·납기 = 독립 SQL", len(tiles) == 3 and not bad,
            f"대조 {n_cells}칸 · 불일치 {len(bad)} · 오늘 {today} 화면 {kp} (다른 QA 의 오늘 데이터 포함 · 시도 {attempt + 1})" + (f" — {bad[:3]}" if bad else ""))
    detail["board"] = {"cells": n_cells, "bad": bad, "screen": kp, "sql": {k: v for k, v in want.items()}}

    # 빈 기간 — 대상 행이 없으면 `미수집`, 0 이나 0% 로 지어내지 않는다
    r = api.get("admin", "/sta/summary", {"date_from": "1990-01-01", "date_to": "1990-01-31"})
    scr = parse_summary(r.text)
    empty_ok = all(v["empty"] and not v["rows"] and v["total"] is None for v in scr.values()) and len(scr) == 3
    r2 = api.get("admin", "/sta/summary", {"date_from": "2001-04-02", "date_to": "2001-03-01"})
    rep.add("G-10", "대상 행이 없는 기간 → `미수집` (0 으로 지어내지 않음) · 시작 > 끝 은 422", empty_ok and r2.status_code == 422,
            f"1990-01 세 집계 미수집 {sum(1 for v in scr.values() if v['empty'])}/3 · 합계 줄 {sum(1 for v in scr.values() if v['total'])} · 거꾸로 된 기간 HTTP {r2.status_code}")
    return detail


# ── G-11 빈 화면 ────────────────────────────────────────────────────────
def empty_state_of(body: str) -> dict:
    """본문(`<main>`)의 빈 상태 — 표마다 데이터 행 수와 빈 줄의 글. 빈 표(행도 안내도 없는 tbody)를 찾는다."""
    tables = []
    for t in re.findall(r"<table\b.*?</table>", body, re.S):
        if "<thead" not in t:                                     # 머리 줄이 없는 표는 목록이 아니다 (라벨 미리보기의 배치용 표)
            continue
        tb = re.search(r"<tbody>(.*?)</tbody>", t, re.S)
        inner = tb.group(1) if tb else ""
        trs = re.findall(r"<tr\b[^>]*>(.*?)</tr>", inner, re.S)
        empty_rows = [text_of_html(tr) for tr in trs if 'class="empty"' in tr]
        data_rows = len(trs) - len(empty_rows)
        tables.append({"data": data_rows, "empty_text": empty_rows, "bare": data_rows == 0 and not empty_rows})
    text = text_of_html(body)
    return {"tables": tables, "has_marker": NOT_COLLECTED in text or UNDECIDED in text, "text": text}


def check_g11(ctx: Ctx, rep: Report) -> dict:
    """데이터가 없을 때 각 화면의 본문이 `미수집` / `미확정 (D-nn)` 을 보이는가 — 중메뉴 32 전수.

    DB 를 비우지 않는다. ① 없는 조건(없는 번호·옛 기간)이나 ② 내 빈 데이터(투입 없는 실적 등)로 빈 결과를 만들고,
    조건을 줄 수 없는 목록 화면은 ③ 그 목록이 지금 실제로 비어 있으면 그대로, 아니면 ④ 라우트는 그대로 돌리고 템플릿에 넘어가는
    목록만 비워(`templating.render` 의 인자) 빈 상태를 그린다. ④ 는 「테이블이 실제로 비었을 때 라우트가 죽지 않는가」 까지는 재지 못한다.
    """
    api = ctx.api
    f = ctx.flow()
    fg = f.item("FG", "제품")
    f.item("RM", "원재료")
    job = f.job(fg, f.customer(), date.today())
    wid = f.start(job)                                            # 투입·정지·폐기가 없는 내 진행 중 실적
    none = f.code("NONE")
    old = {"date_from": "1990-01-01", "date_to": "1990-01-02"}
    specs: dict[str, tuple[str, dict, str]] = {
        "BAS-01": ("admin", {"code": none}, "조건"), "BAS-02": ("admin", {"code": none}, "조건"), "BAS-03": ("admin", {"code": none}, "조건"),
        "BAS-04": ("admin", {"code": none}, "조건"), "BAS-05": ("admin", {"code": none}, "조건"),
        "PRT-01": ("admin", {"code": none}, "조건"), "PRT-02": ("admin", {"code": none}, "조건"), "PRT-03": ("admin", {"code": none}, "조건"),
        "JOB-01": ("admin", {"q": none}, "조건"), "JOB-02": ("admin", {"q": none}, "조건"),
        "POP-01": ("prod", {"day": "1990-01-01"}, "목록"), "POP-02": ("prod", {"work_id": str(wid)}, "내 빈 데이터"), "POP-03": ("prod", {}, "목록"),
        "MAT-01": ("prod", old, "조건"), "MAT-02": ("qc", {"insp_status": none}, "조건"), "MAT-03": ("prod", {"lot": none}, "조건"),
        "MAT-04": ("prod", {"work_id": str(wid)}, "내 빈 데이터"),
        "CLR-01": ("qc", {"job_no": none}, "조건"),
        "RLL-01": ("prod", {}, "목록"), "RLL-02": ("prod", {"parent": none}, "목록"), "RLL-03": ("prod", {}, "목록"),
        "QUA-01": ("qc", {"roll_no": none}, "조건"), "QUA-02": ("qc", old, "조건"),
        "SHP-01": ("prod", {"shipment_no": none}, "조건"), "SHP-02": ("admin", {}, "목록"), "SHP-03": ("admin", {"shipment_no": none}, "조건"),
        "TRC-01": ("admin", {"q": none}, "조건"),
        "STA-01": ("admin", old, "조건"), "STA-02": ("admin", {}, "목록"),
        "SYS-01": ("admin", {"login_id": none}, "조건"), "SYS-02": ("admin", {}, "고정"), "SYS-03": ("admin", old, "조건"),
    }
    from lcomfine.app import stats as app_stats
    from lcomfine.app import templating as app_templating

    def blank(v):
        """템플릿에 넘어가는 값에서 목록(행)을 비운다. 선택 목록(옵션)은 그대로 둔다."""
        return [] if isinstance(v, list) and v and isinstance(v[0], dict) else v

    orig_render, orig_board = app_templating.render, app_stats.board

    def get_blanked(role: str, path: str, params: dict):
        def render(request, template, ctx_=None, **kw):
            return orig_render(request, template, {k: blank(v) for k, v in (ctx_ or {}).items()}, **kw)

        app_templating.render = render
        app_stats.board = lambda today=None: orig_board(date(1990, 1, 1))     # 현황판 — 데이터가 없는 날
        try:
            return api.get(role, path, params)
        finally:
            app_templating.render, app_stats.board = orig_render, orig_board

    results: dict[str, dict] = {}
    for s in nav.SCREENS:
        role, params, how = specs[s.screen_id]
        r = api.get(role, s.path, params)
        st = empty_state_of(main_of(r.text)) if r.status_code == 200 else None
        method = how
        if st is not None and how == "목록":
            if any(t["data"] for t in st["tables"]) or not st["has_marker"]:
                r = get_blanked(role, s.path, params)             # ④ 목록만 비워 다시 그린다
                st = empty_state_of(main_of(r.text)) if r.status_code == 200 else None
                method = "목록을 비워 렌더"
            else:
                method = "지금 실제로 빈 목록"
        if st is None:
            results[s.screen_id] = {"ok": False, "why": f"HTTP {r.status_code}", "method": method, "name": s.name}
            continue
        if how == "고정":                                          # 권한 표 — 48칸이 늘 있다. 빈 상태가 없다
            results[s.screen_id] = {"ok": True, "why": "빈 상태 없음 (권한 표 48칸 고정)", "method": "해당 없음", "name": s.name}
            continue
        lists = [t for t in st["tables"]]
        bare = sum(1 for t in lists if t["bare"])
        still = sum(1 for t in lists if t["data"])
        silent = [t for t in lists if not t["data"] and not t["bare"] and not any(NOT_COLLECTED in x or UNDECIDED in x for x in t["empty_text"])]
        ok = st["has_marker"] and bare == 0 and not silent and (how != "조건" or still == 0)
        why = f"표 {len(lists)} · 빈 표(안내 없음) {bare} · 본문 표식 {'있음' if st['has_marker'] else '없음'}"
        if still:
            why += f" · 조건으로 못 비운 표 {still}"
        if silent:
            why += f" · 미수집이 아닌 빈 줄 {[x for t in silent for x in t['empty_text']][:1]}"
        results[s.screen_id] = {"ok": ok, "why": why, "method": method, "name": s.name, "still": still, "silent": len(silent)}
    # 판정 행 — 대메뉴마다 한 줄
    for menu in nav.MENUS:
        ids = [s.screen_id for s in menu.screens]
        bad = [f"{i} {results[i]['name']} ({results[i]['why']})" for i in ids if not results[i]["ok"]]
        methods = sorted({results[i]["method"] for i in ids})
        rep.add("G-11", f"빈 화면 — {menu.name} (중메뉴 {len(ids)})", not bad,
                f"미수집/미확정 렌더 {len(ids) - len(bad)}/{len(ids)} · 재는 법 {methods}" + (f" — {bad[:2]}" if bad else ""))
    # 한 건을 연 상세 화면의 빈 구역 — 생산 LOT·롤이 없는 Job, 투입 이력이 없는 LOT, 검사·부모가 없는 롤, 롤이 없는 출하, 미검사 롤의 COA
    lot = f.lot(f.code("RM"))
    lot2 = f.lot(f.code("RM"))
    job2 = f.job(fg, ctx.db.v("select customer_id from customer where customer_code = %s", (f.code("CU"),)), date.today())
    roll = f.print_roll(job2, [lot2])
    sh_empty = f.shipment(job, date.today())
    sh = f.shipment(job2, date.today())
    f.scan(sh, roll)
    f.approve(sh)
    details = [("Job 상세 (생산 LOT·롤 없음)", "admin", "/job/mapping", {"no": job}), ("작업지시 상세", "admin", "/job/orders", {"no": job}),
               ("원재료 LOT 상세 (투입 이력 없음)", "prod", "/mat/lots", {"no": lot}), ("롤 이력 (검사 없음)", "prod", "/rll/history", {"no": roll}),
               ("출하 상세 (롤 0개)", "prod", "/shp/shipments", {"no": sh_empty}), ("COA (미검사 롤)", "admin", f"/shp/coa/{sh}/print", {}),
               ("정방향 추적 (투입 안 된 LOT)", "admin", "/trc/trace/forward", {"no": lot}), ("검사 결과 (그 롤의 검사 없음)", "qc", "/qua/inspections", {"no": roll}),
               ("조색 기록 (그 Job 의 기록 없음)", "qc", "/clr/records", {"job_no": job}), ("불량 롤 내역 (옛 기간)", "qc", "/qua/defect-stats/rolls", old)]
    d_bad, d_note = [], []
    for name, role, path, params in details:
        r = api.get(role, path, params)
        if r.status_code != 200:
            d_bad.append(f"{name}: HTTP {r.status_code}")
            continue
        st = empty_state_of(main_of(r.text))
        if any(t["bare"] for t in st["tables"]):
            d_bad.append(f"{name}: 안내 없는 빈 표 {sum(1 for t in st['tables'] if t['bare'])}")
        elif not st["has_marker"]:
            d_bad.append(f"{name}: 본문에 미수집/미확정 없음")
        d_note += [f"{name}: `{x[:30]}`" for t in st["tables"] if not t["data"] for x in t["empty_text"]
                   if NOT_COLLECTED not in x and UNDECIDED not in x]
    rep.add("G-11", "빈 화면 — 한 건을 연 상세 화면의 빈 구역 (롤 없는 Job · 투입 없는 LOT · 검사 없는 롤 · 롤 없는 출하 · 미검사 COA …)", not d_bad,
            f"상세 화면 {len(details)} · 미수집 렌더 {len(details) - len(d_bad)}" + (f" — {d_bad[:3]}" if d_bad else "")
            + (f" · 참고: `미수집` 대신 상태를 적은 빈 줄 {d_note[:2]}" if d_note else ""))
    results["_details"] = {"bad": d_bad, "note": d_note, "n": len(details)}
    # 미확정 (D-nn): 채번 형식 행이 없을 때 번호 미리보기가 `미확정 (D-05)`
    from lcomfine.app import numbering as app_numbering

    orig_rule = app_numbering.rule
    app_numbering.rule = lambda kind: None
    try:
        shown = {sid: UNDECIDED + "05)" in text_of_html(main_of(api.get(role, nav.path_of(sid), {}).text))
                 for sid, role in (("JOB-01", "prod"), ("MAT-01", "prod"), ("SHP-01", "prod"), ("SHP-02", "admin"))}
    finally:
        app_numbering.rule = orig_rule
    n_methods = defaultdict(int)
    for k, v in results.items():
        if not k.startswith("_"):
            n_methods[v["method"]] += 1
    rep.add("G-11", "정해지지 않은 값은 `미확정 (D-nn)` — 채번 형식 행이 없을 때 번호 칸", all(shown.values()),
            f"`미확정 (D-05)` 표시 {sum(shown.values())}/{len(shown)} 화면 {[k for k, v in shown.items() if not v] or ''} · "
            f"32 화면 재는 법: " + " · ".join(f"{k} {v}" for k, v in sorted(n_methods.items())))
    return results


# ── G-12 범위 밖 ────────────────────────────────────────────────────────
SCOPE_RE = re.compile(
    r"\bplc\b|opc[\s\-]?ua|\bmodbus\b|\bmqtt\b|\bscada\b|센서|\bsensor|telemetry|실시간\s*수집|자동\s*수집|설비\s*(데이터\s*)?수집|수집값"
    r"|비전|\bvision\b|카메라|\bcamera|opencv|\bcv2\b"
    r"|\bAI\b|인공지능|머신\s*러닝|machine[\s_\-]?learning|딥\s*러닝|deep[\s_\-]?learning|예측|\bpredict|anomaly|이상\s*탐지|\bllm\b|openai|anthropic|\btorch\b|tensorflow|sklearn",
    re.I)
#: 「만들지 않는다」 고 밝히는 문장 — 범위 밖 기능이 아니라 그 반대다
DISCLAIMER_RE = re.compile(r"않는다|않습니다|없다|없음|없습니다|범위 밖|G-12|금지|받지|만들지|아니다")


def check_g12(ctx: Ctx, rep: Report) -> None:
    api, db = ctx.api, ctx.db
    # 메뉴 · 경로
    names = [m.name for m in nav.MENUS] + [s.name for s in nav.SCREENS] + [g if isinstance(g, str) else getattr(g, "name", str(g)) for g in nav.GROUPS]
    paths = sorted({p for _, p, _ in api_routes(api.app)})
    fn_names = [f"{f.id} {f.name}" for f in contracts.functions()]
    hits = [x for x in names + paths + fn_names if SCOPE_RE.search(x)]
    rep.add("G-12", "메뉴 · 엔드포인트 · 기능 이름에 PLC/설비 수집 · 비전 · AI 없음", not hits,
            f"메뉴·화면 이름 {len(names)} · 경로 {len(paths)} · 기능 {len(fn_names)} · 걸린 것 {len(hits)}" + (f" {hits[:3]}" if hits else ""))
    # 테이블 · 컬럼
    cols = db.q("select table_name, column_name from information_schema.columns where table_schema = 'public'")
    objs = sorted({r["table_name"] for r in cols}) + [f"{r['table_name']}.{r['column_name']}" for r in cols]
    hits = [x for x in objs if SCOPE_RE.search(x) or re.search(r"realtime|collect|signal|\btag_|image|frame|model_|score", x)]
    eq_cols = sorted(r["column_name"] for r in cols if r["table_name"] == "equipment")
    bad_words = {"status", "state", "value", "speed", "temp", "temperature", "run", "running", "signal", "ip", "port", "address",
                 "collect", "collected", "plc", "tag", "alarm", "count", "rpm"}
    eq_extra = [c for c in eq_cols if set(c.split("_")) & bad_words]
    rep.add("G-12", "테이블 · 컬럼에 수집·비전·AI 없음 · 설비는 기준정보 컬럼뿐", not hits and not eq_extra,
            f"테이블 {len({r['table_name'] for r in cols})} · 컬럼 {len(cols)} · 걸린 것 {len(hits)}" + (f" {hits[:3]}" if hits else "")
            + f" · equipment 컬럼 {len(eq_cols)}개 중 상태·수집값류 {len(eq_extra)}" + (f" {eq_extra}" if eq_extra else ""))
    # 소스 · 템플릿 · 정적 파일 문구
    found, disclaim, violations = 0, 0, []
    for p in sorted((SRC / "lcomfine").rglob("*")):
        if p.suffix not in (".py", ".html", ".js", ".css", ".sql") or "__pycache__" in p.parts:
            continue
        for i, ln in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
            if not SCOPE_RE.search(ln):
                continue
            found += 1
            if DISCLAIMER_RE.search(ln):
                disclaim += 1
            else:
                violations.append(f"{p.relative_to(SRC / 'lcomfine')}:{i} {ln.strip()[:60]}")
    rep.add("G-12", "소스 · 템플릿 문구 정적 스캔 — 범위 밖 기능의 흔적 없음", not violations,
            f"낱말이 걸린 줄 {found} · 그중 「만들지 않는다」 는 문장 {disclaim} · 남는 것 {len(violations)}" + (f" — {violations[:3]}" if violations else ""))
    # 의존성 · import
    dep = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    bad_dep = re.findall(r"opencv|torch|tensorflow|scikit|sklearn|openai|anthropic|pymodbus|opcua|asyncua|paho|pycomm|snap7|langchain|transformers|numpy|pandas", dep, re.I)
    bad_imp = []
    for p in sorted((SRC / "lcomfine").rglob("*.py")):
        for i, ln in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
            if re.match(r"\s*(import|from)\s+(cv2|torch|tensorflow|sklearn|openai|anthropic|pymodbus|opcua|asyncua|paho|snap7|socket|serial)\b", ln):
                bad_imp.append(f"{p.relative_to(SRC / 'lcomfine')}:{i}")
    rep.add("G-12", "의존성 · import 에 수집·비전·AI 라이브러리 없음", not bad_dep and not bad_imp,
            f"pyproject 걸린 것 {bad_dep or 0} · import 걸린 것 {bad_imp or 0}")


# ════════════════════════════════════════════════════════════════════════
# 9. 실행
# ════════════════════════════════════════════════════════════════════════
CHECKS = ["G-05", "G-06", "G-07", "G-08", "G-09", "G-10", "G-11", "G-12"]
TITLES = {"G-05": "쓰기 경계", "G-06": "계보 재현", "G-07": "추적", "G-08": "키 연결 · 채번", "G-09": "시드 멱등 · (예시)",
          "G-10": "집계", "G-11": "빈 화면", "G-12": "범위 밖 0"}


def run(only: list[str] | None = None, run_seeds: bool = False, keep: bool = False) -> tuple[Report, dict, dict]:
    rep, extra = Report(), {}
    ctx = Ctx()
    todo = [g for g in CHECKS if not only or g in only]
    fns = {"G-05": lambda: check_g05(ctx, rep), "G-06": lambda: check_g06(ctx, rep), "G-07": lambda: check_g07(ctx, rep),
           "G-08": lambda: check_g08(ctx, rep), "G-09": lambda: check_g09(ctx, rep, run_seeds), "G-10": lambda: check_g10(ctx, rep),
           "G-11": lambda: check_g11(ctx, rep), "G-12": lambda: check_g12(ctx, rep)}
    # G-06 을 먼저(예시 한 벌을 만든다) → G-07 → G-08 → G-05(쓰기 기능을 마저 부르고 요청 기록 전체를 본다) → 나머지
    order = [g for g in ("G-06", "G-07", "G-08", "G-10", "G-11", "G-05", "G-09", "G-12") if g in todo]
    try:
        for gid in order:
            try:
                extra[gid] = fns[gid]()
            except Exception as exc:  # noqa: BLE001 — 검사가 끝까지 못 간 것도 실측이다. 통과로 두지 않는다
                tb = traceback.extract_tb(exc.__traceback__)[-1]
                rep.add(gid, f"{TITLES[gid]} — 검사 도중 중단", FAIL,
                        f"{type(exc).__name__}: {str(exc)[:300]} ({Path(tb.filename).name}:{tb.lineno})")
    finally:
        removed = {} if keep else ctx.cleanup()
        left = {} if keep else {k: v for f in ctx.flows for k, v in leftovers(ctx.db, f.tag + "-%").items()}
        extra["cleanup"] = {"removed": removed, "left": left, "tags": [f.tag for f in ctx.flows], "requests": len(ctx.api.calls)}
        ctx.close()
    rep.rows.sort(key=lambda r: r[0])
    return rep, extra, {"todo": todo}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--purge" in argv:
        db = Db()
        removed = purge(db, PREFIX + "%")
        print(f"`{PREFIX}` 데이터 삭제 — {removed or '지울 것 없음'} · 잔여 {leftovers(db) or 0}")
        return 0
    only = None
    if "--only" in argv:
        only = [x.strip() for x in argv[argv.index("--only") + 1].split(",")]
    started = datetime.now()
    rep, extra, meta = run(only, run_seeds="--run-seeds" in argv, keep="--keep" in argv)
    print(f"G-05~G-12 계보 · 데이터 (tools/check_data.py · QA2) — {started.strftime('%Y-%m-%d %H:%M')}"
          + (" · 시드 재실행 포함" if "--run-seeds" in argv else ""))
    print("-" * 120)
    rep.print()
    print("-" * 120)
    for gid in meta["todo"]:
        rows = [r for r in rep.rows if r[0] == gid]
        sts = [r[2] for r in rows]
        verdict = FAIL if FAIL in sts else WARN if WARN in sts else UNVERIFIED if UNVERIFIED in sts or not rows else PASS
        print(f"{gid} 판정: {verdict} (검사 {len(rows)} · 실패 {sts.count(FAIL)}) {TITLES[gid]}")
    c = extra["cleanup"]
    print(f"데이터: API 요청 {c['requests']}건 · 만든 묶음 {len(c['tags'])}개(`{PREFIX}…`) · 지운 행 {sum(c['removed'].values())}"
          f" · 잔여 {c['left'] or 0} · 걸린 시간 {(datetime.now() - started).seconds}초")
    return 1 if rep.failed() else 0


if __name__ == "__main__":
    raise SystemExit(main())
