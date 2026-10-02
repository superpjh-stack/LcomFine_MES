#!/usr/bin/env python
"""QA1 화면·기능·권한 검사 — G-02 기능 · G-03 화면 · G-17 RBAC  (`uv run python tools/check_screens.py`).

`tools/check_trace.py`(라우트 표를 읽는다) · `tools/check_routes.py`(관리자로 화면 35개를 연다)와 **다른 방법**으로 같은 게이트를 다시 잰다.

  · 기대값은 설계도(정본 HTML)를 **이 파일의 파서로 직접** 읽는다 — `tools/design_doc.py` · `app/nav.py` · `app/contracts.py` 를 쓰지 않는다.
    기능 목록도 `contracts/function-list.md` 를 이 파일이 따로 읽는다.
  · 실제 서버를 포트 8021 에 띄워 **HTTP 로** 두드린다(포트를 못 쓰면 같은 프로세스의 TestClient 로 내려가고 그 사실을 출력한다).
  · G-02  한 Job 을 화면이 부르는 API 로 끝까지 흘린다(기준정보 → 작업지시 → 입고·검사 → 조색 → 인쇄 → 후가공·슬리팅 → 검사 → 출하·승인 → 추적).
          기능 94개를 전부 실제로 부르고, 쓰기 54개는 계약의 「쓰는 테이블」에 행이 생겼는지 SQL 로 확인한다. 이관 배치 6개는 명령을 돌린다.
  · G-03  역할별 세션으로 중메뉴 32 + 공통 3 을 브라우저처럼(Accept: text/html) 열어 200 · placeholder 0 · **방금 만든 데이터가 화면에 보이는지** 본다.
  · G-17  설계도 §6 의 48칸으로 기대값을 만들고 역할 4 × (화면 32 · 읽기 기능 40 · 쓰기 기능 54) 를 전수로 두드린다.
          권한 표가 데이터인지는 **검사 전용 역할**을 하나 만들어 본다 — 시드 역할 4개의 48칸은 건드리지 않는다.

테스트 데이터의 업무 코드는 전부 `Q1-<6자>-…` 이고 끝나면 지운다(`--keep` 이면 남긴다). `make db-reset` 을 하지 않는다.

출력 행 형식: `G-nn  항목  PASS|FAIL  실측`  (`tools/gate.py` 의 `per_gate()` 가 읽는다).  종료코드: 0 = 전부 PASS, 1 = 하나라도 FAIL.

    uv run python tools/check_screens.py               # 서버(8021) 기동 → 검사 → 종료
    uv run python tools/check_screens.py --inprocess   # 서버를 띄우지 않고 TestClient 로
    uv run python tools/check_screens.py --purge       # 앞선 실행이 죽어 남긴 `Q1-` 행을 전부 지우고 끝낸다
"""

from __future__ import annotations

import warnings

warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient`")

import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

DESIGN_HTML = ROOT / "엘컴화인_MES_설계도 복사본.html"
FUNCTION_LIST = ROOT / "contracts" / "function-list.md"
PORT = int(os.environ.get("LCOMFINE_QA1_PORT", "8021"))
PREFIX = "Q1-"
HTML = {"accept": "text/html"}
PLACEHOLDER_MARKS = ('class="tag"', "미구현")
WRITE_KINDS = {"등록", "수정", "삭제", "승인", "스캔"}
READ_KINDS = {"조회", "출력"}
ROLE_ORDER = ("관리자", "생산", "품질", "현장")


# ════════════════════════════════════════════════════════════════════════
# 1. 기대값 — 설계도와 계약을 이 파일이 직접 읽는다
# ════════════════════════════════════════════════════════════════════════
def design_html() -> str:
    return DESIGN_HTML.read_text(encoding="utf-8")


def design_ia(h: str | None = None) -> list[dict]:
    """설계도 §5 IA 구성도 → [{menu, count, subs}] (goal.md §9 의 정규식 그대로)."""
    h = h or design_html()
    found = re.findall(r'<div class="ia-menu[^"]*"><h4>(.*?) <span>(\d+)</span></h4><ul>(.*?)</ul>', h)
    return [{"menu": name, "count": int(n), "subs": re.findall(r"<li>(.*?)</li>", lis)} for name, n, lis in found]


def design_access(h: str | None = None) -> dict:
    """설계도 §6 역할과 채널 표 → {roles: [4], cells: {대메뉴: {역할: 칸 글자}}, channels: {대메뉴: [채널]}}. 칸 글자는 설계도 그대로."""
    h = h or design_html()
    sec = h[h.index('id="access"'): h.index('id="open"')]
    heads = re.findall(r"<th>(.*?)</th>", re.search(r"<thead><tr>(.*?)</tr></thead>", sec, re.S).group(1))
    roles = heads[1:5]
    cells: dict[str, dict[str, str]] = {}
    channels: dict[str, list[str]] = {}
    for tr in re.findall(r"<tr>(.*?)</tr>", sec.split("<tbody>")[1].split("</tbody>")[0], re.S):
        tds = [re.sub(r"\s+", " ", t).strip() for t in re.findall(r"<td[^>]*>(.*?)</td>", tr)]
        cells[tds[0]] = dict(zip(roles, tds[1:5]))
        channels[tds[0]] = [c.strip() for c in tds[5].split(",")]
    return {"roles": roles, "cells": cells, "channels": channels}


def access_counts(access: dict) -> dict[str, int]:
    flat = [c for row in access["cells"].values() for c in row.values()]
    return {"전체": len(flat), "입력": sum(c.startswith("입력") for c in flat), "조회": flat.count("조회"),
            "없음": flat.count("없음")}


@dataclass(frozen=True)
class Fn:
    id: str
    menu: str          # 대메뉴명
    screen: str        # 중메뉴명
    name: str
    kind: str
    tables: tuple[str, ...]
    api: str

    @property
    def is_batch(self) -> bool:
        return self.kind == "배치"

    @property
    def is_write(self) -> bool:
        return self.kind in WRITE_KINDS

    @property
    def method(self) -> str:
        return self.api.split(" ", 1)[0]

    @property
    def path(self) -> str:
        return self.api.split(" ", 1)[1]

    @property
    def module(self) -> str:
        return self.path.split("/")[1]

    @property
    def menu_code(self) -> str:
        return self.module.upper()


def contract_functions() -> list[Fn]:
    """`contracts/function-list.md` §2 의 표 — 머리행이 `| ID | 대메뉴 | …` 인 표의 줄을 그대로 읽는다."""
    out: list[Fn] = []
    head: list[str] | None = None
    for ln in FUNCTION_LIST.read_text(encoding="utf-8").splitlines():
        if not ln.startswith("|"):
            head = None if head and out else head
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if cells[:2] == ["ID", "대메뉴"]:
            head = cells
            continue
        if head is None or set("".join(cells)) <= set("-: "):
            continue
        row = dict(zip(head, cells))
        if not re.fullmatch(r"[FB]-[A-Z]{3}-\d{2}", row["ID"]):
            continue
        tables = tuple(t.strip() for t in row["쓰는 테이블"].split(",") if t.strip() not in ("", "-"))
        out.append(Fn(row["ID"], row["대메뉴"], row["중메뉴"], row["기능명"], row["유형"], tables, row["API"].strip("`")))
    return out


def expected(access: dict, role: str, fn: Fn) -> str:
    """설계도 §6 의 칸으로 이 역할이 이 기능을 할 수 있는가 → `allow` | `deny` | `d14`.

    없음 = 전부 403 · 조회 = 읽기만 · 입력 = 읽기 + 쓰기 · `입력 (X)` = 읽기 + 중메뉴 이름에 X 가 든 쓰기만
    (설계도 IA 의 중메뉴 「입고검사」 「출하 승인」 — goal.md G-17 의 괄호 조건 2개).
    `d14` = 괄호 없는 `입력` 칸의 역할이 **다른 역할의 괄호 기능**(입고검사 결과 등록 · 출하 승인)을 부르는 경우다.
    설계도 문장만으로는 정해지지 않고 decisions.md D-14 가 403 으로 정했다 — 실측은 하되 「확인 필요」 로 따로 센다.
    """
    cell = access["cells"][fn.menu][role]
    if cell == "없음":
        return "deny"
    if not fn.is_write:
        return "allow"
    if cell == "조회":
        return "deny"
    words = {c[c.index("(") + 1: c.rindex(")")].strip() for c in access["cells"][fn.menu].values() if "(" in c}
    mine = cell[cell.index("(") + 1: cell.rindex(")")].strip() if "(" in cell else None
    fn_word = next((w for w in words if w in fn.screen), None)
    if mine is not None:                      # 입력 (X) — X 기능만
        return "allow" if fn_word == mine else "deny"
    return "d14" if fn_word else "allow"      # 괄호 없는 입력


# ════════════════════════════════════════════════════════════════════════
# 2. DB · HTTP
# ════════════════════════════════════════════════════════════════════════
def _dsn() -> str:
    from lcomfine.app import settings  # noqa: F401 — 로컬 .env 를 읽는다

    return os.environ.get("LCOMFINE_PG_DSN") or "postgresql:///lcomfine_db"


def db(sql: str, params=None) -> list[dict]:
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(_dsn(), row_factory=dict_row, autocommit=True) as c, c.cursor() as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()] if cur.description else []


def db1(sql: str, params=None) -> dict | None:
    rows = db(sql, params)
    return rows[0] if rows else None


def seed_password() -> str:
    from lcomfine.app.settings import get_settings

    pw = get_settings().seed_password
    if not pw:
        raise SystemExit("LCOMFINE_SEED_PASSWORD 미설정 — 시드 계정으로 로그인할 수 없다 (`make setup`)")
    return pw


def role_logins() -> dict[str, dict]:
    """역할명 → {code, login_id}. 역할 코드·계정은 코드에 적지 않고 DB 에서 읽는다.
    그 역할의 `정상` 계정 가운데 **가장 먼저 만들어진 것**(공통 시드 계정)을 쓴다 — 다른 사람이 같은 역할로 계정을 더 만들어도 흔들리지 않는다."""
    rows = db("""select r.role_name, r.role_code,
                        (array_agg(u.login_id order by u.user_id) filter (where u.status = '정상'))[1] as login_id
                   from sys_role r left join sys_user u on u.role_code = r.role_code
                  where r.use_yn = 'Y' group by r.role_name, r.role_code""")
    return {r["role_name"]: {"code": r["role_code"], "login_id": r["login_id"]} for r in rows}


class Http:
    """세션을 만드는 곳. `server` 면 실제 서버(8021)에 HTTP, 아니면 같은 프로세스의 TestClient."""

    def __init__(self, inprocess: bool = False, port: int = PORT):
        self.mode, self.port, self.proc, self.log, self.note = "inprocess", port, None, None, ""
        self._clients: list = []
        if not inprocess:
            self._start_server()

    def _start_server(self) -> None:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", self.port)) == 0:
                self.note = f"포트 {self.port} 사용 중 — TestClient 로 내려감"
                return
        self.log = tempfile.NamedTemporaryFile("w+", prefix="qa1-uvicorn-", suffix=".log", delete=False)
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "lcomfine.app.main:app", "--app-dir", str(SRC), "--host", "127.0.0.1",
             "--port", str(self.port), "--log-level", "warning"], cwd=ROOT, stdout=self.log, stderr=subprocess.STDOUT)
        import httpx

        deadline = time.time() + 30
        while time.time() < deadline:
            if self.proc.poll() is not None:
                break
            try:
                if httpx.get(f"http://127.0.0.1:{self.port}/health", timeout=2).status_code == 200:
                    self.mode = "server"
                    return
            except httpx.HTTPError:
                time.sleep(0.2)
        self.close()
        self.note = f"서버 기동 실패(포트 {self.port}) — TestClient 로 내려감"

    def session(self, login_id: str | None = None, password: str | None = None):
        if self.mode == "server":
            import httpx

            c = httpx.Client(base_url=f"http://127.0.0.1:{self.port}", follow_redirects=False, timeout=60)
        else:
            from fastapi.testclient import TestClient

            from lcomfine.app.main import app

            c = TestClient(app, raise_server_exceptions=False, follow_redirects=False)
        self._clients.append(c)
        if login_id:
            r = c.post("/login", data={"login_id": login_id, "password": password or seed_password()})
            if r.status_code != 303:
                raise RuntimeError(f"{login_id} 로그인 실패 — HTTP {r.status_code}")
        return c

    def close(self) -> None:
        for c in self._clients:
            try:
                c.close()
            except Exception:  # noqa: BLE001
                pass
        self._clients = []
        if self.proc is not None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.proc = None
        if self.log is not None:
            self.log.close()
            try:
                os.unlink(self.log.name)
            except OSError:
                pass
            self.log = None


def is_placeholder(html: str) -> bool:
    return all(m in html for m in PLACEHOLDER_MARKS)


# ════════════════════════════════════════════════════════════════════════
# 3. 뒷정리 — 접두 하나로 만든 것을 전부 지운다
# ════════════════════════════════════════════════════════════════════════
def cleanup(tag: str) -> None:
    """`tag` 로 시작하는 업무 코드의 기준정보와, 거기에 매달린 Job · LOT · 롤 · 계보 · 검사 · 출하 · 로그 · 계정 · 검사용 역할."""
    import psycopg
    from psycopg.rows import dict_row

    like, low = tag + "%", tag.lower() + "%"
    role_like = tag.replace("-", "") + "%"
    with psycopg.connect(_dsn(), row_factory=dict_row) as c, c.cursor() as cur:
        def ids(sql: str, params: tuple) -> list:
            cur.execute(sql, params)
            return [next(iter(r.values())) for r in cur.fetchall()]

        items = ids("select item_id from item where item_code like %s", (like,))
        jobs = ids("select job_id from job where item_id = any(%s) or job_no like %s", (items, like))
        lots = ids("select material_lot_id from material_lot where item_id = any(%s)", (items,))
        works = ids("select work_result_id from work_result where job_id = any(%s)", (jobs,))
        rolls = ids("select roll_id from roll where job_id = any(%s)", (jobs,))
        ships = ids("select shipment_id from shipment where job_id = any(%s)", (jobs,))
        targets = (
            ids("select 'job:' || job_no from job where job_id = any(%s)", (jobs,))
            + ids("select 'job_lot:' || lot_no from job_lot where job_id = any(%s)", (jobs,))
            + ids("select 'material_lot:' || lot_no from material_lot where material_lot_id = any(%s)", (lots,))
            + ids("select 'roll:' || roll_no from roll where roll_id = any(%s)", (rolls,))
            + [f"work_result:{w}" for w in works]
            + ids("select 'work_stop:' || work_stop_id from work_stop where work_result_id = any(%s)", (works,))
            + ids("select 'work_scrap:' || work_scrap_id from work_scrap where work_result_id = any(%s)", (works,))
            + ids("select 'material_input:' || material_input_id from material_input where work_result_id = any(%s)", (works,)))
        likes = ([f"%:{tag}%", f"sys_user:{tag.lower()}%", f"sys_permission:{role_like}"]
                 + ids("select 'color_record:' || job_no || '/%%' from job where job_id = any(%s)", (jobs,))
                 + ids("select 'shipment:' || shipment_no || '%%' from shipment where shipment_id = any(%s)", (ships,))
                 + ids("select 'inspection:%% roll:' || roll_no from roll where roll_id = any(%s)", (rolls,)))
        cur.execute("delete from sys_access_log where log_type = '변경' and (target = any(%s) or target like any(%s))",
                    (targets, likes))
        cur.execute("delete from sys_access_log where login_id like %s", (low,))
        cur.execute("""delete from roll_genealogy where child_roll_id = any(%s) or parent_roll_id = any(%s)
                          or parent_material_lot_id = any(%s) or child_shipment_id = any(%s)""", (rolls, rolls, lots, ships))
        cur.execute("delete from inspection where roll_id = any(%s) or job_id = any(%s)", (rolls, jobs))
        cur.execute("delete from shipment where shipment_id = any(%s)", (ships,))
        cur.execute("delete from roll where roll_id = any(%s)", (rolls,))
        cur.execute("delete from material_input where work_result_id = any(%s) or material_lot_id = any(%s)", (works, lots))
        cur.execute("delete from work_stop where work_result_id = any(%s)", (works,))
        cur.execute("delete from work_scrap where work_result_id = any(%s)", (works,))
        cur.execute("delete from work_result where work_result_id = any(%s)", (works,))
        cur.execute("delete from color_record where job_id = any(%s)", (jobs,))
        cur.execute("delete from material_lot where material_lot_id = any(%s)", (lots,))
        cur.execute("delete from job_lot where job_id = any(%s) or lot_no like %s", (jobs, like))
        cur.execute("delete from job where job_id = any(%s)", (jobs,))
        for table, col in (("plate_spec", "plate_code"), ("anilox", "anilox_code"), ("ink_formula", "ink_code"),
                           ("equipment", "equipment_code"), ("process", "process_code"), ("defect_code", "defect_code"),
                           ("customer", "customer_code"), ("item", "item_code")):
            cur.execute(f"delete from {table} where {col} like %s", (like,))
        cur.execute("delete from sys_migration_log where run_by like %s", (like,))
        cur.execute("delete from sys_user where login_id like %s", (low,))
        cur.execute("delete from sys_permission where role_code like %s", (role_like,))
        cur.execute("delete from sys_role where role_code like %s", (role_like,))
        c.commit()


def leftovers(tag: str) -> dict[str, int]:
    like = tag + "%"
    checks = {
        "item": ("item_code", like), "customer": ("customer_code", like), "process": ("process_code", like),
        "equipment": ("equipment_code", like), "defect_code": ("defect_code", like), "plate_spec": ("plate_code", like),
        "anilox": ("anilox_code", like), "ink_formula": ("ink_code", like), "job": ("job_no", like),
        "job_lot": ("lot_no", like), "sys_user": ("login_id", tag.lower() + "%"),
        "sys_role": ("role_code", tag.replace("-", "") + "%"), "sys_permission": ("role_code", tag.replace("-", "") + "%"),
        "sys_migration_log": ("run_by", like),
    }
    out = {}
    for table, (col, pat) in checks.items():
        n = db1(f"select count(*) as n from {table} where {col} like %s", (pat,))["n"]
        if n:
            out[table] = n
    return out


def permission_state() -> dict:
    """지금 DB 의 권한 표 — 행 수와 등급별 수, 역할 수."""
    by = {r["level"]: r["n"] for r in db("select level, count(*) as n from sys_permission group by level")}
    return {"rows": sum(by.values()), "입력": by.get("입력", 0), "조회": by.get("조회", 0), "없음": by.get("없음", 0),
            "roles": db1("select count(*) as n from sys_role")["n"]}


# ════════════════════════════════════════════════════════════════════════
# 4. G-02 — 한 Job 을 API 로 끝까지 (기능 94 전부 호출 · 쓰기 54 는 쓰는 테이블 확인)
# ════════════════════════════════════════════════════════════════════════
@dataclass
class Step:
    fn_id: str
    role: str
    call: str
    status: int
    ok: bool
    evidence: str = ""


@dataclass
class Flow:
    http: Http
    tag: str = field(default_factory=lambda: f"{PREFIX}{uuid.uuid4().hex[:6].upper()}")
    steps: list[Step] = field(default_factory=list)
    stage_errors: list[str] = field(default_factory=list)
    v: dict = field(default_factory=dict)          # 흐름이 만든 번호·키
    batch: dict[str, tuple[bool, str]] = field(default_factory=dict)
    audit: dict[str, list[bool]] = field(default_factory=dict)   # 쓰기 기능 → 성공한 호출마다 `변경` 로그가 남았는가

    def __post_init__(self) -> None:
        self.roles = role_logins()
        self.c = {name: self.http.session(info["login_id"]) for name, info in self.roles.items() if info["login_id"]}
        self.role_code = self.tag.replace("-", "") + "R"       # 검사 전용 역할 (권한 표가 데이터인지 볼 때 쓴다)
        self.v["admin_login"] = self.roles.get("관리자", {}).get("login_id")
        self.today = date.today().isoformat()

    # ── 한 걸음 ──
    def call(self, fn_id: str, role: str, method: str, path: str, *, data=None, params=None, check=None,
             html: bool = False):
        last_log = db1("select coalesce(max(log_id), 0) as m from sys_access_log")["m"] if method == "POST" else 0
        r = self.c[role].request(method, path, data=data, params=params, headers=HTML if html else None)
        body = None
        if "application/json" in r.headers.get("content-type", ""):
            body = r.json()
        ok, evidence = r.status_code == 200, ""
        if ok and method == "POST":
            # 쓰기 성공의 모양(api-contract §2): 200 `{"ok": true, "message": …}` + 누가·무엇을 했는지 `변경` 로그 한 줄
            if not (isinstance(body, dict) and body.get("ok") is True and body.get("message")):
                ok, evidence = False, f"쓰기 성공 응답이 {{ok: true, message}} 가 아니다: {str(body)[:100]}"
            logged = db1("""select count(*) as n from sys_access_log where log_id > %s and log_type = '변경'
                               and function_id = %s and login_id = %s and result = '성공'""",
                         (last_log, fn_id, self.roles[role]["login_id"]))["n"]
            self.audit.setdefault(fn_id, []).append(logged >= 1)
        if ok and method == "GET" and is_placeholder(r.text):
            ok, evidence = False, "placeholder(미구현) 화면"
        if ok and check is not None:
            try:
                res = check(r, body)
                ok, evidence = (res if isinstance(res, tuple) else (bool(res), ""))
            except Exception as exc:  # noqa: BLE001 — 확인 자체가 실패한 것도 실측이다
                ok, evidence = False, f"확인 실패 {type(exc).__name__}: {exc}"
        if not ok and not evidence:
            evidence = (r.text or "")[:160].replace("\n", " ")
        self.steps.append(Step(fn_id, role, f"{method} {path}", r.status_code, ok, evidence))
        return body if body is not None else r

    @staticmethod
    def has(*needles: str):
        def check(r, _body):
            missing = [n for n in needles if n not in r.text]
            return (not missing, f"화면에 없음 {missing}" if missing else f"화면에 {', '.join(needles)[:60]}")
        return check

    @staticmethod
    def row(sql: str, params: tuple, want=None, label: str = ""):
        """쓰기 확인 — 그 키의 행을 SQL 로 다시 읽는다. `want(row)` 가 참이어야 한다(없으면 행이 있기만 하면 된다)."""
        def check(_r, _body):
            got = db1(sql, params)
            good = (got is not None) if want is None else bool(want(got))
            return good, f"{label} {got}"[:200]
        return check

    def run(self, batch: bool = True) -> "Flow":
        db("insert into sys_role (role_code, role_name, sort_no, use_yn) values (%s, %s, 99, 'N')",
           (self.role_code, f"{self.tag} 검사 역할 (예시)"))
        for stage in (self.s_bas, self.s_prt, self.s_job, self.s_mat, self.s_clr, self.s_pop, self.s_rll, self.s_qua,
                      self.s_shp, self.s_trc, self.s_sta, self.s_sys, *((self.s_batch,) if batch else ())):
            try:
                stage()
            except Exception as exc:  # noqa: BLE001 — 앞 단계가 실패하면 뒤 단계는 미도달로 남는다
                self.stage_errors.append(f"{stage.__name__[2:]}: {type(exc).__name__}: {str(exc)[:120]}")
        return self

    # ── 마스터 4기능 공통 ──
    def master(self, fns: tuple[str, str, str, str], path: str, table: str, code_col: str, name_col: str, suffix: str,
               extra: dict, *, writer: str, reader: str, key: str, after=None) -> None:
        code = f"{self.tag}-{suffix}"
        b = self.call(fns[0], writer, "POST", path, data={code_col: code, name_col: f"{code} (예시)", **extra},
                      check=self.row(f"select {code_col}, created_by from {table} where {code_col} = %s", (code,),
                                     lambda g: g["created_by"] == self.roles[writer]["login_id"], table))
        self.v[key], self.v[key + "_code"] = b["id"], code
        if after:
            after(b["id"])
        self.call(fns[1], writer, "POST", f"{path}/{b['id']}", data={name_col: f"{code} 수정 (예시)"},
                  check=self.row(f"select {name_col} as name, updated_by from {table} where {code_col} = %s", (code,),
                                 lambda g: g["name"] == f"{code} 수정 (예시)" and g["updated_by"], table))
        d = self.call(fns[0], writer, "POST", path, data={code_col: code + "X", name_col: f"{code}X (예시)", **extra})
        self.call(fns[2], writer, "POST", f"{path}/{d['id']}/delete",
                  check=lambda _r, _b: (db1(f"select 1 from {table} where {code_col} = %s", (code + "X",)) is None,
                                        f"{table} 행 삭제됨"))
        self.call(fns[3], reader, "GET", path, params={"code": self.tag}, check=self.has(code), html=True)

    def s_bas(self) -> None:
        A = "관리자"
        self.master(("F-BAS-01", "F-BAS-02", "F-BAS-03", "F-BAS-04"), "/bas/items", "item", "item_code", "item_name", "FG",
                    {"item_type": "제품", "unit": "m"}, writer=A, reader="생산", key="item")
        b = self.call("F-BAS-01", A, "POST", "/bas/items",
                      data={"item_code": f"{self.tag}-RM", "item_name": f"{self.tag}-RM (예시)", "item_type": "원재료", "unit": "m"})
        self.v["raw"], self.v["raw_code"] = b["id"], f"{self.tag}-RM"
        self.master(("F-BAS-05", "F-BAS-06", "F-BAS-07", "F-BAS-08"), "/bas/customers", "customer", "customer_code",
                    "customer_name", "CU", {}, writer=A, reader="품질", key="customer")
        self.master(("F-BAS-09", "F-BAS-10", "F-BAS-11", "F-BAS-12"), "/bas/processes", "process", "process_code",
                    "process_name", "PR", {"process_type": "인쇄", "sort_no": "1"}, writer=A, reader="생산", key="process")
        self.master(("F-BAS-13", "F-BAS-14", "F-BAS-15", "F-BAS-16"), "/bas/equipment", "equipment", "equipment_code",
                    "equipment_name", "EQ", {"process_id": str(self.v["process"])}, writer=A, reader="품질", key="equipment")
        self.master(("F-BAS-17", "F-BAS-18", "F-BAS-19", "F-BAS-20"), "/bas/defect-codes", "defect_code", "defect_code",
                    "defect_name", "DF", {"defect_group": "외관 (예시)"}, writer=A, reader="생산", key="defect")

    def s_prt(self) -> None:
        self.master(("F-PRT-01", "F-PRT-02", "F-PRT-03", "F-PRT-04"), "/prt/plates", "plate_spec", "plate_code", "plate_name",
                    "PL", {"item_id": str(self.v["item"]), "color_count": "4"}, writer="생산", reader="품질", key="plate")
        self.master(("F-PRT-05", "F-PRT-06", "F-PRT-07", "F-PRT-08"), "/prt/anilox", "anilox", "anilox_code", "anilox_name",
                    "AN", {"line_count": "400", "cell_volume": "4.5"}, writer="관리자", reader="현장", key="anilox")

        def components(ink_id: int) -> None:
            n = db1("select count(*) as n from ink_formula_component where ink_formula_id = %s", (ink_id,))["n"]
            self.steps.append(Step("F-PRT-09", "생산", "SQL ink_formula_component", 200, n == 2, f"조성 행 {n} (기대 2)"))

        self.master(("F-PRT-09", "F-PRT-10", "F-PRT-11", "F-PRT-12"), "/prt/inks", "ink_formula", "ink_code", "ink_name",
                    "INK", {"color_name": "청 (예시)", "target_l": "50", "target_a": "-3", "target_b": "-40",
                            "component_name": ["안료 (예시)", "용제 (예시)"], "ratio_pct": ["60", "40"]},
                    writer="생산", reader="현장", key="ink", after=components)

    def s_job(self) -> None:
        v, P = self.v, "생산"
        form = {"item_id": str(v["item"]), "customer_id": str(v["customer"]), "plate_spec_id": str(v["plate"]),
                "anilox_id": str(v["anilox"]), "ink_formula_id": str(v["ink"]), "equipment_id": str(v["equipment"]),
                "order_qty": "1000", "due_date": self.today}
        b = self.call("F-JOB-01", P, "POST", "/job/orders", data=form)
        v["job_no"] = b["job_no"]
        self.steps.append(self._sql("F-JOB-01", P, "job", "select status, created_by, item_id from job where job_no = %s",
                                    (v["job_no"],), lambda g: g["status"] == "등록" and g["item_id"] == v["item"]))
        self.call("F-JOB-02", "관리자", "POST", f"/job/orders/{v['job_no']}", data={"note": f"{self.tag} 비고 (예시)"},
                  check=self.row("select note, updated_by from job where job_no = %s", (v["job_no"],),
                                 lambda g: g["note"] == f"{self.tag} 비고 (예시)", "job"))
        b2 = self.call("F-JOB-01", "관리자", "POST", "/job/orders", data=form)
        v["job_cancel"] = b2["job_no"]
        self.call("F-JOB-03", P, "POST", f"/job/orders/{b2['job_no']}/cancel",
                  check=self.row("select status from job where job_no = %s", (b2["job_no"],),
                                 lambda g: g["status"] == "취소", "job"))
        self.call("F-JOB-04", "품질", "GET", "/job/orders", params={"no": v["job_no"]}, check=self.has(v["job_no"]), html=True)
        self.call("F-JOB-05", "현장", "GET", f"/job/orders/{v['job_no']}/print", check=self.has(v["job_no"], "<svg"), html=True)
        b = self.call("F-JOB-06", P, "POST", "/job/mapping", data={"job_no": v["job_no"], "planned_roll_count": "3"})
        v["job_lot"] = b["lot_no"]
        self.steps.append(self._sql("F-JOB-06", P, "job_lot",
                                    "select l.planned_roll_count, j.job_no from job_lot l join job j on j.job_id = l.job_id where l.lot_no = %s",
                                    (v["job_lot"],), lambda g: g["job_no"] == v["job_no"] and g["planned_roll_count"] == 3))
        self.call("F-JOB-07", "관리자", "GET", "/job/mapping", params={"no": v["job_no"]}, check=self.has(v["job_lot"]), html=True)

    def _sql(self, fn_id: str, role: str, label: str, sql: str, params: tuple, want) -> Step:
        got = db1(sql, params)
        return Step(fn_id, role, f"SQL {label}", 200, got is not None and bool(want(got)), f"{label} {got}"[:200])

    def s_mat(self) -> None:
        v = self.v
        for key, role in (("lot1", "현장"), ("lot2", "생산")):
            b = self.call("F-MAT-01", role, "POST", "/mat/receipts",
                          data={"item_code": v["raw_code"], "supplier_name": "공급처 (예시)",
                                "supplier_lot_no": f"{self.tag}-{key}", "received_qty": "1000"})
            v[key] = b["lot_no"]
            self.steps.append(self._sql("F-MAT-01", role, "material_lot",
                                        "select insp_status, received_by from material_lot where lot_no = %s", (v[key],),
                                        lambda g: g["insp_status"] == "대기"))
        self.call("F-MAT-02", "관리자", "GET", "/mat/receipts", params={"item_code": v["raw_code"]},
                  check=self.has(v["lot1"], v["lot2"]), html=True)
        for key in ("lot1", "lot2"):
            self.call("F-MAT-03", "품질", "POST", "/mat/inspections", data={"lot_no": v[key], "result": "합격"},
                      check=self.row("select insp_status, insp_by from material_lot where lot_no = %s", (v[key],),
                                     lambda g: g["insp_status"] == "합격" and g["insp_by"] == self.roles["품질"]["login_id"],
                                     "material_lot"))
        self.call("F-MAT-04", "관리자", "GET", "/mat/inspections", params={"no": v["lot1"]}, check=self.has(v["lot1"]), html=True)
        self.call("F-MAT-05", "생산", "GET", "/mat/lots", params={"no": v["lot1"]}, check=self.has(v["lot1"]), html=True)
        self.call("F-MAT-06", "현장", "GET", f"/mat/lots/{v['lot1']}/label", check=self.has(v["lot1"], "<svg"), html=True)

    def s_clr(self) -> None:
        v = self.v
        color = f"{self.tag} 청 (예시)"
        form = {"job_no": v["job_no"], "color_name": color, "color_l": "50.1", "color_a": "-3.2", "color_b": "-40.5",
                "ink_code": v["ink_code"]}
        b = self.call("F-CLR-01", "품질", "POST", "/clr/records", data=form)
        v["color"], v["color_name"] = b["id"], color
        self.steps.append(self._sql("F-CLR-01", "품질", "color_record",
                                    "select seq_no, recorded_by from color_record where color_record_id = %s", (b["id"],),
                                    lambda g: g["seq_no"] == 1))
        self.call("F-CLR-02", "현장", "POST", f"/clr/records/{v['color']}/mix",
                  data={"component_name": ["안료 (예시)", "용제 (예시)"], "ratio_pct": ["60", "40"]},
                  check=self.row("select count(*) as n, sum(ratio_pct) as total from color_record_mix where color_record_id = %s",
                                 (v["color"],), lambda g: g["n"] == 2 and g["total"] == 100, "color_record_mix"))
        self.call("F-CLR-03", "품질", "POST", f"/clr/records/{v['color']}",
                  data={"color_name": color, "color_l": "51", "color_a": "-3.2", "color_b": "-40.5"},
                  check=self.row("select color_l, updated_by from color_record where color_record_id = %s", (v["color"],),
                                 lambda g: float(g["color_l"]) == 51.0 and g["updated_by"], "color_record"))
        b2 = self.call("F-CLR-01", "현장", "POST", "/clr/records", data=form)
        self.call("F-CLR-04", "현장", "POST", f"/clr/records/{b2['id']}/delete",
                  check=lambda _r, _b: (db1("select 1 from color_record where color_record_id = %s", (b2["id"],)) is None,
                                        "color_record 행 삭제됨"))
        self.call("F-CLR-05", "생산", "GET", "/clr/records", params={"job_no": v["job_no"]}, check=self.has(color), html=True)

    def _print_roll(self, key: str, role: str, lots: list[str], *, stop: bool = False) -> None:
        v = self.v
        b = self.call("F-POP-01", role, "POST", "/pop/work/start",
                      data={"job_no": v["job_no"], "lot_no": v["job_lot"], "equipment_code": v["equipment_code"]})
        work = b["work_id"]
        v[key + "_work"] = work
        self.steps.append(self._sql("F-POP-01", role, "work_result",
                                    "select status, worker from work_result where work_result_id = %s", (work,),
                                    lambda g: g["status"] == "진행"))
        for lot in lots:
            self.call("F-MAT-07", role, "POST", "/mat/inputs", data={"work_id": str(work), "lot_no": lot, "input_qty": "100"},
                      check=self.row("""select count(*) as n from material_input mi join material_lot m using (material_lot_id)
                                         where mi.work_result_id = %s and m.lot_no = %s""", (work, lot),
                                     lambda g: g["n"] == 1, "material_input"))
        if stop:
            reason = f"{self.tag} 판 교체 (예시)"
            v["stop_reason"] = reason
            self.call("F-MAT-08", "관리자", "GET", "/mat/inputs", params={"work_id": str(work)}, check=self.has(lots[0]), html=True)
            s = self.call("F-POP-04", "생산", "POST", "/pop/stops", data={"work_id": str(work), "stop_reason": reason})
            self.steps.append(self._sql("F-POP-04", "생산", "work_stop + work_result", """
                select s.resumed_at, w.status from work_stop s join work_result w using (work_result_id) where s.work_stop_id = %s""",
                                        (s["stop_id"],), lambda g: g["resumed_at"] is None and g["status"] == "정지"))
            self.call("F-POP-05", "현장", "POST", f"/pop/stops/{s['stop_id']}/resume",
                      check=self.row("""select s.resumed_at, w.status from work_stop s join work_result w using (work_result_id)
                                         where s.work_stop_id = %s""", (s["stop_id"],),
                                     lambda g: g["resumed_at"] is not None and g["status"] == "진행", "work_stop + work_result"))
            c = self.call("F-POP-06", "생산", "POST", "/pop/stops/scrap",
                          data={"work_id": str(work), "scrap_qty": "5", "defect_code": v["defect_code"], "reason": "시험 인쇄 (예시)"})
            self.steps.append(self._sql("F-POP-06", "생산", "work_scrap",
                                        "select scrap_qty, defect_code_id from work_scrap where work_scrap_id = %s",
                                        (c["scrap_id"],), lambda g: float(g["scrap_qty"]) == 5 and g["defect_code_id"] == v["defect"]))
            self.call("F-POP-07", "품질", "GET", "/pop/stops", params={"work_id": str(work)}, check=self.has(reason), html=True)
        b = self.call("F-POP-02", role, "POST", f"/pop/work/{work}/finish",
                      data={"output_qty": "500", "length_m": "500", "width_mm": "1000"})
        v[key] = b["roll_no"]
        self.steps.append(self._sql("F-POP-02", role, "work_result + roll + roll_genealogy", """
            select w.status, r.process_type,
                   (select count(*) from roll_genealogy g where g.child_roll_id = r.roll_id and g.relation = '투입') as inputs
              from roll r join work_result w on w.work_result_id = r.work_result_id where r.roll_no = %s""", (v[key],),
                                    lambda g: g["status"] == "완료" and g["process_type"] == "인쇄" and g["inputs"] == len(lots)))

    def s_pop(self) -> None:
        v = self.v
        self._print_roll("p1", "현장", [v["lot1"]], stop=True)             # 설계도 §3: LOT① → 인쇄 롤 ①
        self._print_roll("p2", "생산", [v["lot1"], v["lot2"]])              #           LOT①② → 인쇄 롤 ②
        self._print_roll("p3", "현장", [v["lot2"]])                         # 1:1 후가공(F-RLL-01)에 쓸 롤
        self.call("F-POP-03", "관리자", "GET", "/pop/work", check=self.has(v["p1"], v["job_no"]), html=True)
        self.call("F-POP-08", "품질", "GET", f"/pop/roll-labels/{v['p1']}/print", check=self.has(v["p1"], "<svg"), html=True)

    def _edges(self, child: str, relation: str) -> int:
        return db1("""select count(*) as n from roll_genealogy g join roll c on c.roll_id = g.child_roll_id
                       where c.roll_no = %s and g.relation = %s""", (child, relation))["n"]

    def s_rll(self) -> None:
        v = self.v
        b = self.call("F-RLL-02", "생산", "POST", "/rll/finishing/splice",
                      data={"roll_no": [v["p1"], v["p2"]], "equipment_code": v["equipment_code"], "length_m": "900"})
        v["fn1"] = b["roll_no"]
        n = self._edges(v["fn1"], "splice")
        self.steps.append(Step("F-RLL-02", "생산", "SQL roll + roll_genealogy", 200, n == 2, f"splice 행 {n} (기대 2)"))
        b = self.call("F-RLL-04", "현장", "POST", "/rll/slitting",
                      data={"roll_no": v["fn1"], "count": "3", "widths_mm": "300,300,400"})
        v["s1"], v["s2"], v["s3"] = b["rolls"]
        n = sum(self._edges(x, "슬리팅") for x in b["rolls"])
        self.steps.append(Step("F-RLL-04", "현장", "SQL roll + roll_genealogy", 200, n == 3, f"슬리팅 행 {n} (기대 3)"))
        b = self.call("F-RLL-01", "현장", "POST", "/rll/finishing", data={"roll_no": v["p3"], "length_m": "480"})
        v["fn2"] = b["roll_no"]
        n = self._edges(v["fn2"], "후가공")
        self.steps.append(Step("F-RLL-01", "현장", "SQL roll + roll_genealogy", 200, n == 1, f"후가공 행 {n} (기대 1)"))
        self.call("F-RLL-03", "관리자", "GET", "/rll/finishing", check=self.has(v["fn1"], v["fn2"]), html=True)
        self.call("F-RLL-05", "품질", "GET", "/rll/slitting", params={"parent": v["fn1"]}, check=self.has(v["s1"], v["s3"]), html=True)
        self.call("F-RLL-06", "관리자", "GET", "/rll/history", params={"no": v["s1"]}, check=self.has(v["s1"], v["fn1"]), html=True)
        self.call("F-RLL-07", "생산", "GET", f"/rll/history/{v['s1']}/label", check=self.has(v["s1"], "<svg"), html=True)

    def s_qua(self) -> None:
        v, Q = self.v, "품질"
        for key in ("s1", "s2"):
            b = self.call("F-QUA-01", Q, "POST", "/qua/inspections", data={"roll_no": v[key], "delta_e": "1.2", "result": "합격"})
            self.steps.append(self._sql("F-QUA-01", Q, "inspection", """
                select n.result, n.job_id = r.job_id as same_job from inspection n join roll r using (roll_id)
                 where n.inspection_id = %s""", (b["inspection_id"],), lambda g: g["result"] == "합격" and g["same_job"]))
        b = self.call("F-QUA-01", Q, "POST", "/qua/inspections",
                      data={"roll_no": v["s3"], "delta_e": "6.5", "result": "불합격", "defect_code": [v["defect_code"]],
                            "position": ["50m (예시)"]})
        n = db1("select count(*) as n from inspection_defect where inspection_id = %s", (b["inspection_id"],))["n"]
        self.steps.append(Step("F-QUA-01", Q, "SQL inspection_defect", 200, n == 1, f"불량 행 {n} (기대 1)"))
        self.call("F-QUA-02", Q, "POST", f"/qua/inspections/{b['inspection_id']}",
                  data={"delta_e": "7.5", "result": "불합격", "defect_code": [v["defect_code"]], "position": ["60m (예시)"]},
                  check=self.row("""select n.delta_e, (select position from inspection_defect d where d.inspection_id = n.inspection_id) as pos
                                      from inspection n where n.inspection_id = %s""", (b["inspection_id"],),
                                 lambda g: float(g["delta_e"]) == 7.5 and g["pos"] == "60m (예시)", "inspection + inspection_defect"))
        x = self.call("F-QUA-01", Q, "POST", "/qua/inspections", data={"roll_no": v["fn2"], "result": "합격"})
        self.call("F-QUA-03", Q, "POST", f"/qua/inspections/{x['inspection_id']}/delete",
                  check=lambda _r, _b: (db1("select 1 from inspection where inspection_id = %s", (x["inspection_id"],)) is None,
                                        "inspection 행 삭제됨"))
        self.call("F-QUA-04", "관리자", "GET", "/qua/inspections", params={"no": v["s1"]}, check=self.has(v["s1"], "합격"), html=True)
        self.call("F-QUA-05", "생산", "GET", "/qua/defect-stats", check=self.has(f"{v['defect_code']} 수정 (예시)"), html=True)
        self.call("F-QUA-06", "현장", "GET", "/qua/defect-stats/rolls", params={"defect_code": v["defect_code"]},
                  check=self.has(v["s3"]), html=True)

    def s_shp(self) -> None:
        v = self.v
        b = self.call("F-SHP-01", "현장", "POST", "/shp/shipments", data={"job_no": v["job_no"], "ship_date": self.today})
        v["ship1"] = b["shipment_no"]
        self.steps.append(self._sql("F-SHP-01", "현장", "shipment",
                                    "select s.status, j.job_no from shipment s join job j using (job_id) where s.shipment_no = %s",
                                    (v["ship1"],), lambda g: g["status"] == "등록" and g["job_no"] == v["job_no"]))
        for key, role in (("s1", "현장"), ("s2", "생산")):
            self.call("F-SHP-02", role, "POST", f"/shp/shipments/{v['ship1']}/rolls", data={"roll_no": v[key]},
                      check=self.row("""select g.relation, s.shipment_no from roll_genealogy g
                                          join roll r on r.roll_id = g.parent_roll_id
                                          join shipment s on s.shipment_id = g.child_shipment_id where r.roll_no = %s""",
                                     (v[key],), lambda g: g["relation"] == "출하" and g["shipment_no"] == v["ship1"],
                                     "roll_genealogy"))
        b = self.call("F-SHP-01", "생산", "POST", "/shp/shipments", data={"job_no": v["job_no"], "ship_date": self.today})
        v["ship2"] = b["shipment_no"]
        self.call("F-SHP-02", "생산", "POST", f"/shp/shipments/{v['ship2']}/rolls", data={"roll_no": v["fn2"]})
        self.call("F-SHP-03", "생산", "POST", f"/shp/shipments/{v['ship2']}/cancel",
                  check=self.row("""select s.status, (select count(*) from roll_genealogy g where g.child_shipment_id = s.shipment_id) as rolls,
                                           (select state from v_roll_state where roll_no = %s) as state
                                      from shipment s where s.shipment_no = %s""", (v["fn2"], v["ship2"]),
                                 lambda g: g["status"] == "취소" and g["rolls"] == 0 and g["state"] == "재고",
                                 "shipment + roll_genealogy"))
        self.call("F-SHP-04", "품질", "GET", "/shp/shipments", params={"no": v["ship1"]}, check=self.has(v["ship1"], v["s1"], v["s2"]), html=True)
        v["approvals_before"] = v["ship1"] in self.c["관리자"].get("/shp/approvals", headers=HTML).text
        b = self.call("F-SHP-05", "관리자", "POST", f"/shp/approvals/{v['ship1']}/approve")
        v["coa"] = b["coa_no"]
        self.steps.append(self._sql("F-SHP-05", "관리자", "shipment",
                                    "select status, approved_by, coa_no, coa_issued_at from shipment where shipment_no = %s",
                                    (v["ship1"],), lambda g: g["status"] == "승인" and g["coa_no"] == v["coa"]
                                    and g["approved_by"] == self.roles["관리자"]["login_id"] and g["coa_issued_at"]))
        self.call("F-SHP-06", "품질", "GET", "/shp/coa", params={"shipment_no": v["ship1"]}, check=self.has(v["coa"]), html=True)
        self.call("F-SHP-07", "관리자", "GET", f"/shp/coa/{v['ship1']}/print", check=self.has(v["coa"], v["s1"], v["s2"], "<svg"), html=True)

    def s_trc(self) -> None:
        v = self.v
        # 정방향: 원재료 LOT ① → … → 출하 LOT. 슬리팅 ③ 은 출하되지 않았다(재고).  역방향: 출하 LOT → 원재료 LOT ①·② (완료 기준)
        self.call("F-TRC-01", "관리자", "GET", "/trc/trace/forward", params={"no": v["lot1"]},
                  check=self.has(v["p1"], v["p2"], v["fn1"], v["s1"], v["s2"], v["s3"], v["ship1"], "재고"), html=True)
        self.call("F-TRC-02", "품질", "GET", "/trc/trace/backward", params={"no": v["ship1"]},
                  check=self.has(v["lot1"], v["lot2"], v["fn1"], v["p1"], v["p2"]), html=True)
        self.call("F-TRC-03", "생산", "GET", "/trc/trace", params={"q": v["ship1"]}, check=self.has(v["ship1"]), html=True)

    def s_sta(self) -> None:
        v = self.v
        name = f"{v['item_code']} 수정 (예시)"
        params = {"item_id": str(v["item"])}
        self.call("F-STA-01", "관리자", "GET", "/sta/summary/production", params=params, check=self.has(name), html=True)
        self.call("F-STA-02", "생산", "GET", "/sta/summary/quality", params=params, check=self.has(name), html=True)
        self.call("F-STA-03", "품질", "GET", "/sta/summary/delivery", params=params, check=self.has(name), html=True)
        self.call("F-STA-04", "현장", "GET", "/sta/board", check=self.has("마지막 갱신"), html=True)

    def s_sys(self) -> None:
        v, A = self.v, "관리자"
        uid, pw = f"{self.tag.lower()}-u1", secrets.token_urlsafe(12)
        v["user"], v["user_pw"] = uid, pw
        self.call("F-SYS-01", A, "POST", "/sys/users",
                  data={"login_id": uid, "user_name": f"{self.tag} 사용자 (예시)", "role_code": self.role_code, "password": pw},
                  check=self.row("select role_code, status, password_hash from sys_user where login_id = %s", (uid,),
                                 lambda g: g["role_code"] == self.role_code and g["status"] == "정상"
                                 and pw not in g["password_hash"] and g["password_hash"].startswith("pbkdf2"), "sys_user"))
        self.call("F-SYS-02", A, "POST", f"/sys/users/{uid}", data={"user_name": f"{self.tag} 사용자 수정 (예시)"},
                  check=self.row("select user_name from sys_user where login_id = %s", (uid,),
                                 lambda g: g["user_name"].endswith("수정 (예시)"), "sys_user"))
        uid2 = f"{self.tag.lower()}-u2"
        self.call("F-SYS-01", A, "POST", "/sys/users",
                  data={"login_id": uid2, "user_name": f"{self.tag} 삭제 대상 (예시)", "role_code": self.role_code,
                        "password": secrets.token_urlsafe(12)})
        self.call("F-SYS-03", A, "POST", f"/sys/users/{uid2}/delete",
                  check=self.row("select status from sys_user where login_id = %s", (uid2,), lambda g: g["status"] == "중지",
                                 "sys_user"))
        self.call("F-SYS-04", A, "GET", "/sys/users", params={"login_id": self.tag.lower()},
                  check=lambda r, _b: (uid in r.text and uid2 in r.text and "pbkdf2" not in r.text, "계정 2 · 해시 노출 없음"),
                  html=True)
        self.call("F-SYS-05", A, "GET", "/sys/permissions", check=self.has(*ROLE_ORDER), html=True)
        self.call("F-SYS-06", A, "POST", "/sys/permissions", data={"role_code": self.role_code, "menu_code": "STA", "level": "조회"},
                  check=self.row("select level, write_scope, updated_by from sys_permission where role_code = %s and menu_code = 'STA'",
                                 (self.role_code,), lambda g: g["level"] == "조회" and g["write_scope"] == "", "sys_permission"))
        self.call("F-SYS-07", A, "GET", "/sys/logs", params={"login_id": self.roles[A]["login_id"], "log_type": "변경"},
                  check=self.has(f"sys_user:{uid2}"), html=True)

    def s_batch(self) -> None:
        """이관 배치 6 — 예시 Import 파일의 코드 접두를 `Q1-…` 로 바꾼 사본으로 명령을 실제로 돌린다."""
        src = SRC / "lcomfine" / "migration" / "examples"
        tmp = Path(tempfile.mkdtemp(prefix="qa1-import-"))
        try:
            for f in src.glob("*.csv"):
                (tmp / f.name).write_text(f.read_text(encoding="utf-8").replace("IMP-", f"{self.tag}-MG"), encoding="utf-8")
            env = {**os.environ, "PYTHONPATH": str(SRC)}

            def run(cmd: str) -> tuple[int, str]:
                p = subprocess.run([sys.executable, "-m", "lcomfine.migration", cmd, "--dir", str(tmp), "--by", self.tag],
                                   cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
                return p.returncode, (p.stdout + p.stderr).strip()

            def count(table: str, col: str) -> int:
                return db1(f"select count(*) as n from {table} where {col} like %s", (f"{self.tag}-MG%",))["n"]

            def logs(cmd: str) -> int:
                return db1("select count(*) as n from sys_migration_log where run_by = %s and command = %s", (self.tag, cmd))["n"]

            rc, out = run("validate")
            self.batch["B-MIG-01"] = (rc == 0 and count("item", "item_code") == 0 and logs("validate") == 0,
                                      f"validate rc={rc} · 적재 0 · 로그 0 — {out.splitlines()[-1][:60] if out else ''}")
            rc, _ = run("load-master")
            n = {t: count(t, c) for t, c in (("item", "item_code"), ("customer", "customer_code"), ("process", "process_code"),
                                             ("equipment", "equipment_code"), ("defect_code", "defect_code"))}
            rc2, _ = run("load-master")
            n2 = {t: count(t, c) for t, c in (("item", "item_code"), ("customer", "customer_code"), ("process", "process_code"),
                                              ("equipment", "equipment_code"), ("defect_code", "defect_code"))}
            self.batch["B-MIG-02"] = (rc == 0 and rc2 == 0 and n == {"item": 4, "customer": 2, "process": 3, "equipment": 2,
                                                                     "defect_code": 2} and n2 == n and logs("load-master") == 10,
                                      f"load-master rc={rc}/{rc2} · {n} · 재실행 뒤 같음 {n2 == n} · 로그 {logs('load-master')}")
            rc, _ = run("load-print-std")
            n = {"plate_spec": count("plate_spec", "plate_code"), "anilox": count("anilox", "anilox_code"),
                 "ink_formula": count("ink_formula", "ink_code"),
                 "ink_formula_component": db1("""select count(*) as n from ink_formula_component c join ink_formula k using (ink_formula_id)
                                                  where k.ink_code like %s""", (f"{self.tag}-MG%",))["n"]}
            self.batch["B-MIG-03"] = (rc == 0 and n == {"plate_spec": 1, "anilox": 1, "ink_formula": 1, "ink_formula_component": 2},
                                      f"load-print-std rc={rc} · {n}")
            rc, _ = run("load-jobs")
            n = {"job": count("job", "job_no"), "job_lot": count("job_lot", "lot_no")}
            self.batch["B-MIG-04"] = (rc == 0 and n == {"job": 2, "job_lot": 2}, f"load-jobs rc={rc} · {n}")
            rc, out = run("load-history")
            self.batch["B-MIG-05"] = (rc == 0 and logs("load-history") == 5 and "D-01" in out,
                                      f"load-history rc={rc} (빈 파일 5) · 로그 {logs('load-history')} · `미확정 (D-01)` 표기 {'D-01' in out}")
            rc, out = run("report")
            self.batch["B-MIG-06"] = (rc == 0, f"report rc={rc} — {out.splitlines()[-1][:80] if out else ''}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # ── 결과 ──
    def by_fn(self) -> dict[str, list[Step]]:
        out: dict[str, list[Step]] = {}
        for s in self.steps:
            out.setdefault(s.fn_id, []).append(s)
        return out

    def genealogy(self) -> dict[str, int]:
        """이 흐름의 Job 이 만든 계보 행 — 관계별 수."""
        rows = db("""select g.relation, count(*) as n from roll_genealogy g
                      where g.child_roll_id in (select roll_id from roll r join job j using (job_id) where j.job_no = %(j)s)
                         or g.parent_roll_id in (select roll_id from roll r join job j using (job_id) where j.job_no = %(j)s)
                      group by g.relation""", {"j": self.v.get("job_no")})
        return {r["relation"]: r["n"] for r in rows}


# ── 화면 32 → (여는 주소, 화면에 보여야 하는 방금 만든 값) ──
def screen_probes(v: dict, tag: str) -> dict[str, tuple[dict, list[str]]]:
    g = v.get
    return {
        "/bas/items": ({"code": tag}, [g("item_code")]), "/bas/customers": ({"code": tag}, [g("customer_code")]),
        "/bas/processes": ({"code": tag}, [g("process_code")]), "/bas/equipment": ({"code": tag}, [g("equipment_code")]),
        "/bas/defect-codes": ({"code": tag}, [g("defect_code")]), "/prt/plates": ({"code": tag}, [g("plate_code")]),
        "/prt/anilox": ({"code": tag}, [g("anilox_code")]), "/prt/inks": ({"code": tag}, [g("ink_code"), "안료 (예시)"]),
        "/job/orders": ({"q": g("job_no")}, [g("job_no")]), "/job/mapping": ({"no": g("job_no")}, [g("job_lot"), g("s1")]),
        "/pop/work": ({}, [g("job_no"), g("p1")]), "/pop/stops": ({"work_id": g("p1_work")}, [g("stop_reason")]),
        "/pop/roll-labels": ({"no": g("p1")}, [g("p1")]), "/mat/receipts": ({"item_code": g("raw_code")}, [g("lot1")]),
        "/mat/inspections": ({"no": g("lot1")}, [g("lot1"), "합격"]), "/mat/lots": ({"no": g("lot1")}, [g("lot1")]),
        "/mat/inputs": ({"work_id": g("p2_work")}, [g("lot1"), g("lot2")]),
        "/clr/records": ({"job_no": g("job_no")}, [g("color_name")]), "/rll/finishing": ({}, [g("fn1")]),
        "/rll/slitting": ({"parent": g("fn1")}, [g("s1"), g("s2"), g("s3")]), "/rll/history": ({"no": g("fn1")}, [g("p1"), g("p2"), g("s1")]),
        "/qua/inspections": ({"no": g("s3")}, [g("s3"), "불합격"]), "/qua/defect-stats": ({}, [g("defect_code")]),
        "/shp/shipments": ({"no": g("ship1")}, [g("ship1"), g("s1")]), "/shp/approvals": ({}, [g("ship1")]),
        "/shp/coa": ({"shipment_no": g("ship1")}, [g("coa")]), "/trc/trace": ({"q": g("lot1")}, [g("lot1")]),
        "/sta/summary": ({"item_id": g("item")}, [g("item_code")]), "/sta/board": ({}, ["마지막 갱신"]),
        "/sys/users": ({"login_id": tag.lower()}, [g("user")]), "/sys/permissions": ({}, list(ROLE_ORDER)),
        "/sys/logs": ({"log_type": "변경", "login_id": g("admin_login")}, ["sys_user:" + str(g("user"))]),
    }


# ════════════════════════════════════════════════════════════════════════
# 5. G-17 — 역할 4 × (화면 32 · 읽기 40 · 쓰기 54) 전수
# ════════════════════════════════════════════════════════════════════════
MISSING = {"id": "999999999", "inspection_id": "999999999", "work_id": "999999999", "stop_id": "999999999"}


def sweep_path(fn: Fn) -> str:
    """경로의 키 자리에 **없는 값**을 넣는다 — 권한이 있으면 404/422, 없으면 403 이 나와야 한다(어느 쪽도 쓰지 않는다)."""
    return re.sub(r"\{(\w+)\}", lambda m: MISSING.get(m.group(1), "Q1-NONE"), fn.path)


@dataclass
class Rbac:
    http: Http
    access: dict
    fns: list[Fn]
    requests: int = 0
    violations: list[str] = field(default_factory=list)
    d14: list[str] = field(default_factory=list)
    detail: dict[str, tuple[int, int]] = field(default_factory=dict)      # 항목 → (요청 수, 위반 수)
    bad: dict[str, list[str]] = field(default_factory=dict)               # 항목 → 위반 목록

    def __post_init__(self) -> None:
        self.roles = role_logins()
        self.c = {name: self.http.session(info["login_id"]) for name, info in self.roles.items() if info["login_id"]}
        self.ia = design_ia()

    def _count(self, key: str, bad: list[str], n: int) -> None:
        self.requests += n
        self.violations += bad
        self.bad[key] = bad
        self.detail[key] = (n, len(bad))

    def screens(self) -> None:
        """화면 GET: 없음 = 403, 그 밖 = 200. 중메뉴 → 경로는 계약의 조회 기능 주소에서 찾는다(그 중메뉴 기능들의 공통 앞부분)."""
        bad, n = [], 0
        for role in self.access["roles"]:
            for path, menu in screen_paths(self.fns).items():
                want = 403 if self.access["cells"][menu][role] == "없음" else 200
                got = self.c[role].get(path, headers=HTML).status_code
                n += 1
                if got != want:
                    bad.append(f"{role} GET {path} 기대 {want} 실제 {got}")
        self._count("화면", bad, n)

    def menus(self) -> None:
        """메뉴 숨김: 메인(`/`)의 좌측 메뉴·바로가기에 `없음` 대메뉴의 화면 링크가 없고, 그 밖은 있다."""
        bad, n = [], 0
        paths = screen_paths(self.fns)
        for role in self.access["roles"]:
            home = self.c[role].get("/", headers=HTML).text
            for menu, row in self.access["cells"].items():
                mine = [p for p, m in paths.items() if m == menu]
                shown = [p for p in mine if f'href="{p}"' in home]
                n += 1
                if row[role] == "없음" and shown:
                    bad.append(f"{role}: `없음` 인 {menu} 이 메뉴에 보인다 {shown[:2]}")
                if row[role] != "없음" and len(shown) != len(mine):
                    bad.append(f"{role}: {menu} 의 화면 {len(mine)} 중 {len(shown)} 만 메뉴에 있다")
        self._count("메뉴", bad, n)

    def functions(self, write: bool) -> None:
        bad, n = [], 0
        for role in self.access["roles"]:
            for fn in self.fns:
                if fn.is_batch or fn.is_write != write:
                    continue
                want = expected(self.access, role, fn)
                r = self.c[role].request(fn.method, sweep_path(fn))
                n += 1
                denied = r.status_code == 403
                if want == "d14":
                    self.d14.append(f"{role} × {fn.id} {fn.name} → {r.status_code}")
                    want = "deny"                          # D-14 의 판정대로 재고, 「확인 필요」 로 따로 적는다
                if want == "deny" and not denied:
                    bad.append(f"{role} {fn.id} {fn.method} {sweep_path(fn)} 기대 403 실제 {r.status_code}")
                if want == "allow" and (denied or r.status_code in (401, 405, 500) or (write and r.status_code == 200)):
                    bad.append(f"{role} {fn.id} {fn.method} {sweep_path(fn)} 기대 허용(404·422) 실제 {r.status_code}")
        self._count("쓰기" if write else "읽기", bad, n)

    def anonymous(self) -> None:
        """미로그인: 기능 94 전부 401(JSON) · 브라우저 GET 은 /login 303. 순서는 401 → 403 → 422."""
        bad, n = [], 0
        anon = self.http.session()
        for fn in self.fns:
            if fn.is_batch:
                continue
            r = anon.request(fn.method, sweep_path(fn))
            n += 1
            if r.status_code != 401:
                bad.append(f"미로그인 {fn.id} {fn.method} {sweep_path(fn)} 기대 401 실제 {r.status_code}")
            if fn.method == "GET":
                h = anon.get(sweep_path(fn), headers=HTML)
                n += 1
                if h.status_code != 303 or not h.headers.get("location", "").startswith("/login"):
                    bad.append(f"미로그인 브라우저 {fn.id} GET 기대 303 /login 실제 {h.status_code} {h.headers.get('location')}")
        self._count("미로그인", bad, n)

    def run(self) -> "Rbac":
        self.screens()
        self.menus()
        self.functions(write=False)
        self.functions(write=True)
        self.anonymous()
        return self


def screen_paths(fns: list[Fn]) -> dict[str, str]:
    """중메뉴 32 의 화면 경로 → 대메뉴명. 계약 표에서만 끌어낸다: 그 중메뉴 기능들의 API 경로의 공통 앞 두 마디."""
    out: dict[str, str] = {}
    for fn in fns:
        if fn.is_batch:
            continue
        parts = fn.path.split("/")
        out.setdefault("/" + "/".join(parts[1:3]), fn.menu)
    return out


def role_as_data(http: Http, flow: Flow) -> tuple[bool, str]:
    """권한 표가 데이터인가 — 검사 전용 역할(`sys_role` 한 행, 코드 수정 없음)에 칸을 주고 빼며 즉시 반영되는지 본다.

    시드 역할 4개의 48칸은 건드리지 않는다. 칸 변경은 화면 기능(F-SYS-06)으로, 마지막 한 번은 SQL 로 직접 한다.
    """
    v, code = flow.v, flow.role_code
    admin = flow.c["관리자"]
    try:
        u = http.session(v["user"], v["user_pw"])
    except Exception as exc:  # noqa: BLE001
        return False, f"검사 역할 계정 로그인 실패 — {exc}"
    notes, bad = [], []

    def set_cell(menu: str, level: str, scope: str | None = None) -> None:
        data = {"role_code": code, "menu_code": menu, "level": level}
        if scope:
            data["write_scope"] = scope
        r = admin.post("/sys/permissions", data=data)
        if r.status_code != 200:
            bad.append(f"F-SYS-06 {menu}={level}({scope}) → {r.status_code}")

    def expect(label: str, got: int, want) -> None:
        good = got in want if isinstance(want, tuple) else got == want
        notes.append(f"{label} {got}")
        if not good:
            bad.append(f"{label}: 기대 {want} 실제 {got}")

    expect("행 없는 칸(TRC) 조회", u.get("/trc/trace").status_code, 403)
    hidden = 'href="/trc/trace"' not in u.get("/", headers=HTML).text
    set_cell("TRC", "조회")
    expect("→ 조회로 바꾼 직후", u.get("/trc/trace").status_code, 200)
    shown = 'href="/trc/trace"' in u.get("/", headers=HTML).text
    if not (hidden and shown):
        bad.append(f"메뉴 숨김/표시가 칸을 따르지 않는다 (숨김 {hidden} · 표시 {shown})")
    set_cell("BAS", "조회")
    expect("BAS 조회 칸의 쓰기", u.post("/bas/items").status_code, 403)
    set_cell("BAS", "입력")
    expect("→ 입력으로 바꾼 직후 쓰기", u.post("/bas/items").status_code, 422)
    set_cell("MAT", "입력", "입고검사")
    expect("MAT 입력(입고검사) 의 입고검사 등록", u.post("/mat/inspections").status_code, 422)
    expect("같은 칸의 입고 등록", u.post("/mat/receipts").status_code, 403)
    set_cell("SHP", "입력", "승인")
    expect("SHP 입력(승인) 의 승인", u.post("/shp/approvals/Q1-NONE/approve").status_code, 404)
    expect("같은 칸의 출하 등록", u.post("/shp/shipments").status_code, 403)
    set_cell("SHP", "입력", "일반,승인")
    expect("SHP 입력(일반,승인) 의 출하 등록", u.post("/shp/shipments").status_code, 422)
    # SQL 로 직접 바꾼다 — 화면 기능을 거치지 않아도(코드 수정 없이) 따라오는가. 앱은 권한 표를 짧게 캐시한다
    db("update sys_permission set level = '없음', write_scope = '' where role_code = %s and menu_code = 'TRC'", (code,))
    t0, lag = time.time(), None
    while time.time() - t0 < 12:
        if u.get("/trc/trace").status_code == 403:
            lag = time.time() - t0
            break
        time.sleep(0.5)
    notes.append(f"SQL 로 없음 → 403 까지 {lag:.1f}초" if lag is not None else "SQL 변경이 12초 안에 반영되지 않음")
    if lag is None:
        bad.append("sys_permission 을 SQL 로 바꿔도 12초 안에 반영되지 않는다")
    return not bad, (" · ".join(notes) if not bad else "위반 " + " / ".join(bad))


# ════════════════════════════════════════════════════════════════════════
# 6. 실행
# ════════════════════════════════════════════════════════════════════════
class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, bool, str]] = []

    def add(self, gate: str, item: str, ok: bool, actual: str) -> None:
        self.rows.append((gate, item, bool(ok), re.sub(r"\s+", " ", str(actual)).strip()))

    def failed(self, gate: str) -> int:
        return sum(1 for g, _, ok, _ in self.rows if g == gate and not ok)


def check_g02(r: Report, flow: Flow, fns: list[Fn], ia: list[dict]) -> None:
    g = "G-02"
    screen_fns = [f for f in fns if not f.is_batch]
    per_menu = [(m["menu"], sum(1 for f in screen_fns if f.menu == m["menu"])) for m in ia]
    r.add(g, "계약 100줄 = 설계도 §5 의 대메뉴별 수 (자체 파싱)",
          len(screen_fns) == 94 and len(fns) - len(screen_fns) == 6 and per_menu == [(m["menu"], m["count"]) for m in ia],
          f"화면 {len(screen_fns)} + 배치 {len(fns) - len(screen_fns)} · " + "·".join(str(n) for _, n in per_menu)
          + " (설계도 " + "·".join(str(m["count"]) for m in ia) + ")")
    by = flow.by_fn()
    called = [f for f in screen_fns if f.id in by]
    route_miss = [f"{f.id}:{s.status}" for f in called for s in by[f.id] if s.status in (404, 405) and not s.call.startswith("SQL")]
    r.add(g, "기능 94 실호출 — 로그인 세션으로 API 를 불러 404·405 가 아니다",
          len(called) == 94 and not route_miss,
          f"호출한 기능 {len(called)}/94 · 요청 {sum(1 for s in flow.steps if not s.call.startswith('SQL'))} · 404·405 {len(route_miss)} {route_miss[:3] if route_miss else ''}"
          + (f" · 미도달 {[f.id for f in screen_fns if f.id not in by][:4]}" if len(called) != 94 else ""))
    reads = [f for f in screen_fns if not f.is_write]
    bad = [f"{f.id} {[f'{s.status} {s.evidence}'[:70] for s in by.get(f.id, []) if not s.ok] or '미도달'}" for f in reads
           if f.id not in by or not all(s.ok for s in by[f.id])]
    r.add(g, "읽기 기능 40 — 200 이고 방금 만든 값이 화면에 있다", len(reads) == 40 and not bad,
          f"통과 {len(reads) - len(bad)}/{len(reads)}" + (f" · 실패 {bad[:3]}" if bad else ""))
    writes = [f for f in screen_fns if f.is_write]
    bad = [f"{f.id} {[f'{s.call} {s.status} {s.evidence}'[:90] for s in by.get(f.id, []) if not s.ok] or '미도달'}" for f in writes
           if f.id not in by or not all(s.ok for s in by[f.id])]
    r.add(g, "쓰기 기능 54 — 200 이고 계약의 「쓰는 테이블」 에 행이 생긴다 (SQL 확인)", len(writes) == 54 and not bad,
          f"통과 {len(writes) - len(bad)}/{len(writes)}" + (f" · 실패 {bad[:3]}" if bad else ""))
    ge = flow.genealogy()
    want = {"투입": 4, "splice": 2, "후가공": 1, "슬리팅": 3, "출하": 2}
    r.add(g, "흐름이 남긴 계보 — 설계도 §3 예시 10행 + 1:1 후가공 2행", ge == want,
          " · ".join(f"{k} {ge.get(k, 0)}" for k in want) + f" = {sum(ge.values())}행 (기대 12)")
    try:
        # 재검(웨이브 D 뒤): `/openapi.json` 은 이제 미로그인 401 · 시스템 관리 조회 역할만 200 이다(D-29 · DEF-QA1-006).
        # 「실행 중인 앱」 을 계속 재려면 **그 서버에 관리자로 로그인해** 읽는다 — 미로그인으로 읽으면 늘 대체 경로(app.openapi())로만 내려간다.
        anon_status = flow.http.session().get("/openapi.json").status_code
        resp = flow.c["관리자"].get("/openapi.json")
        if resp.status_code == 200:
            spec, source = resp.json(), f"서버의 /openapi.json (관리자 세션 · 미로그인은 {anon_status})"
        else:                                   # 문서 주소를 아예 닫았으면 같은 앱 객체에서 읽는다
            from lcomfine.app.main import app

            spec, source = app.openapi(), f"app.openapi() (서버의 /openapi.json 은 관리자 {resp.status_code} · 미로그인 {anon_status})"
        norm = lambda path: re.sub(r"\{[^}]*\}", "{}", path)  # noqa: E731
        live = {(m.upper(), norm(path)) for path, ops in spec["paths"].items() for m in ops}
        mods = tuple(f"/{x}/" for x in sorted({f.module for f in screen_fns}))
        want_api = {(f.method, norm(f.path)) for f in screen_fns}
        screens = {("GET", path) for path in screen_paths(fns)}
        in_mods = {x for x in live if x[1].startswith(mods)}
        orphans = sorted(f"{m} {path}" for m, path in in_mods if (m, path) not in want_api | screens)
        missing = sorted(f"{m} {path}" for m, path in want_api - live)
        # 읽은 양을 판정에 넣는다 — 0개를 읽고 「고아 0」 으로 통과하지 않게 (계약 94개가 전부 읽은 것 안에 있어야 한다)
        r.add(g, "등록된 API = 계약 94 (고아 0 · 누락 0) — 실행 중인 앱의 OpenAPI",
              not orphans and not missing and len(want_api) == 94 and len(in_mods) >= 94,
              f"{source}: 경로·메서드 {len(live)} (업무 모듈 {len(in_mods)}) · 계약 {len(want_api)} · 계약에 없는 것 {len(orphans)} {orphans[:3] if orphans else ''} · 계약인데 없는 것 {len(missing)} {missing[:3] if missing else ''}")
    except Exception as exc:  # noqa: BLE001
        r.add(g, "등록된 API = 계약 94 (고아 0 · 누락 0) — 실행 중인 앱의 OpenAPI", False, f"{type(exc).__name__}: {exc}")
    bad = [f"{k}: {d}" for k, (ok, d) in flow.batch.items() if not ok]
    r.add(g, "이관 배치 6 — 명령을 실제로 돌린다 (Q1 사본 폴더)", len(flow.batch) == 6 and not bad,
          f"통과 {sum(ok for ok, _ in flow.batch.values())}/6" + (f" · 실패 {bad[:2]}" if bad else "")
          + (f" · 미도달 {6 - len(flow.batch)}" if len(flow.batch) != 6 else ""))
    if flow.stage_errors:
        r.add(g, "흐름 단계 오류 0", False, " / ".join(flow.stage_errors)[:300])


def check_g03(r: Report, http: Http, flow: Flow, fns: list[Fn], ia: list[dict]) -> None:
    g = "G-03"
    paths = screen_paths(fns)
    subs = sum(len(m["subs"]) for m in ia)
    r.add(g, "중메뉴 32 의 화면 경로가 계약에서 나온다 (설계도 중메뉴 수와 같다)", len(paths) == subs == 32,
          f"계약의 화면 경로 {len(paths)} · 설계도 중메뉴 {subs}")
    probes = screen_probes(flow.v, flow.tag)
    admin = flow.c["관리자"]
    not200, ph, unlinked = [], [], []
    for path in paths:
        params, needles = probes.get(path, ({}, []))
        if any(x is None for x in list(params.values()) + needles):
            unlinked.append(f"{path} (앞 단계 실패로 값 없음)")
            params, needles = {}, []
        resp = admin.get(path, params=params, headers=HTML)
        if resp.status_code != 200:
            not200.append(f"{path} {resp.status_code}")
            continue
        if is_placeholder(resp.text):
            ph.append(path)
        missing = [n for n in needles if str(n) not in resp.text]
        if missing:
            unlinked.append(f"{path} 에 {missing[:2]} 없음")
    r.add(g, "중메뉴 32 화면 — 브라우저(Accept: text/html) GET 200", not not200, f"200 {32 - len(not200)}/32" + (f" · {not200[:3]}" if not200 else ""))
    r.add(g, "placeholder(미구현) 0", not ph, f"placeholder {len(ph)} {ph[:3] if ph else ''}".strip())
    r.add(g, "실 데이터 연동 — 방금 API 로 만든 값이 32 화면에 보인다", not unlinked,
          f"연동 확인 {32 - len(unlinked)}/32" + (f" · {unlinked[:3]}" if unlinked else ""))
    common = {"/": admin.get("/", headers=HTML).status_code, "/login": http.session().get("/login", headers=HTML).status_code,
              "/error": admin.get("/error", headers=HTML).status_code}
    r.add(g, "공통 3 (메인 · 로그인 · 오류) 200", all(s == 200 for s in common.values()), " · ".join(f"{k} {s}" for k, s in common.items()))
    other = {name: c.get("/", headers=HTML).status_code for name, c in flow.c.items()}
    r.add(g, "역할 4 모두 메인 200", all(s == 200 for s in other.values()), " · ".join(f"{k} {s}" for k, s in other.items()))
    miss = admin.get("/q1-no-such-screen", headers=HTML)
    r.add(g, "없는 주소 404 오류 화면", miss.status_code == 404 and "대상을 찾을 수 없습니다" in miss.text, f"HTTP {miss.status_code}")


def check_g17(r: Report, http: Http, flow: Flow, rb: Rbac, access: dict) -> None:
    g = "G-17"
    cnt = access_counts(access)
    r.add(g, "설계도 §6 = 48칸 (입력 19 · 조회 24 · 없음 5)", cnt == {"전체": 48, "입력": 19, "조회": 24, "없음": 5},
          f"{cnt['전체']}칸 = 입력 {cnt['입력']} · 조회 {cnt['조회']} · 없음 {cnt['없음']}")
    code = {name: info["code"] for name, info in rb.roles.items()}
    menu_code = {f.menu: f.menu_code for f in rb.fns if not f.is_batch}
    have = {(x["role_code"], x["menu_code"]): x for x in db("select role_code, menu_code, level, write_scope from sys_permission")}
    diff = []
    for menu, row in access["cells"].items():
        for role, cell in row.items():
            x = have.get((code.get(role), menu_code.get(menu)))
            word = cell[cell.index("(") + 1: cell.rindex(")")].strip() if "(" in cell else ("일반" if cell.startswith("입력") else "")
            if x is None or x["level"] != cell.split(" ")[0] or x["write_scope"] != word:
                diff.append(f"{menu}×{role}: DB {x and (x['level'], x['write_scope'])} ≠ 설계도 {cell}")
    r.add(g, "DB sys_permission = 설계도 48칸 (칸마다 대조)", not diff, f"다른 칸 {len(diff)} {diff[:2] if diff else ''}".strip())
    for key, label in (("화면", "화면 GET — 없음 403 · 그 밖 200 (역할 4 × 화면 32)"),
                       ("메뉴", "메뉴 숨김 — 없음 칸의 화면 링크 0 (48칸)"),
                       ("읽기", "읽기 기능 — 없음 403 · 그 밖 허용 (역할 4 × 40)"),
                       ("쓰기", "쓰기 기능 전수 — 조회·없음 403 · 입력 허용 (역할 4 × 54)"),
                       ("미로그인", "미로그인 — 기능 94 전부 401 · 브라우저 GET 303")):
        n, b = rb.detail.get(key, (0, -1))
        r.add(g, label, b == 0, f"요청 {n} · 위반 {b}" + (f" — {rb.bad.get(key, [])[:3]}" if b else ""))
    qc, admin = "품질", "관리자"
    by_id = {f.id: f for f in rb.fns}
    mat_w = [f for f in rb.fns if f.menu == "자재 · 입고" and f.is_write]
    shp_w = [f for f in rb.fns if f.menu == "출하" and f.is_write]
    b1 = {f.id: expected(access, qc, f) for f in mat_w}
    b2 = {f.id: expected(access, admin, f) for f in shp_w}
    viol = [x for x in rb.violations if (x.startswith(qc) and any(f.id in x for f in mat_w))
            or (x.startswith(admin) and any(f.id in x for f in shp_w))]
    r.add(g, "괄호 조건 2 — 품질은 입고검사만 · 관리자는 출하 승인만",
          not viol and [k for k, w in b1.items() if w == "allow"] == ["F-MAT-03"] and [k for k, w in b2.items() if w == "allow"] == ["F-SHP-05"],
          f"품질×자재·입고 쓰기 {len(b1)}: 허용 {[k for k, w in b1.items() if w == 'allow']} 나머지 403 · "
          f"관리자×출하 쓰기 {len(b2)}: 허용 {[k for k, w in b2.items() if w == 'allow']} 나머지 403 · 위반 {len(viol)}")
    assert by_id
    ok, detail = role_as_data(http, flow) if flow.v.get("user") else (False, "검사 역할 계정을 만들지 못했다 (F-SYS-01 실패)")
    r.add(g, "권한 표는 데이터 — 새 역할 한 행 + 칸 변경이 코드 수정 없이 반영", ok, detail)


def main(argv: list[str]) -> int:
    if "--purge" in argv:
        cleanup(PREFIX)
        print(f"`{PREFIX}` 행을 지웠다 · 남은 것 {leftovers(PREFIX) or '없음'} · 권한 표 {permission_state()}")
        return 0
    seed_password()
    h = design_html()
    ia, access, fns = design_ia(h), design_access(h), contract_functions()
    before = permission_state()
    http = Http(inprocess="--inprocess" in argv)
    r = Report()
    flow = None
    rb = None
    try:
        flow = Flow(http).run()
        check_g02(r, flow, fns, ia)
        check_g03(r, http, flow, fns, ia)
        rb = Rbac(http, access, fns).run()
        check_g17(r, http, flow, rb, access)
    finally:
        if flow is not None and "--keep" not in argv:
            try:
                cleanup(flow.tag)
            except Exception as exc:  # noqa: BLE001
                r.add("G-17", "뒷정리", False, f"{type(exc).__name__}: {exc}")
        http.close()
    after = permission_state()
    left = leftovers(flow.tag) if flow is not None and "--keep" not in argv else {}
    r.add("G-17", "검사 뒤 권한 표 원상 — 48행 = 입력 19 · 조회 24 · 없음 5 · 역할 4",
          after == {"rows": 48, "입력": 19, "조회": 24, "없음": 5, "roles": 4} and not left,
          f"sys_permission {after['rows']}행 = 입력 {after['입력']} · 조회 {after['조회']} · 없음 {after['없음']} · sys_role {after['roles']}"
          f" (검사 전 {before['rows']}행) · 남은 Q1 행 {left or 0}")

    print(f"G-02 기능 · G-03 화면 · G-17 RBAC (tools/check_screens.py) — 방식: {http.mode}"
          + (f" ({http.note})" if http.note else f" (포트 {http.port})" if http.mode == "server" else "")
          + f" · 테스트 데이터 접두 {flow.tag if flow else '-'}")
    print("-" * 110)
    w = max(len(i) for _, i, _, _ in r.rows)
    for gate, item, ok, actual in r.rows:
        print(f"{gate}  {item:<{w}}  {'PASS' if ok else 'FAIL'}  {actual}")
    print("-" * 110)
    if rb is not None:
        print(f"권한 전수: 요청 {rb.requests} 건 (" + " · ".join(f"{k} {n}" for k, (n, _) in rb.detail.items())
              + f") · 위반 {len(rb.violations)} 건")
        for x in rb.violations[:40]:
            print(f"    위반 — {x}")
        if rb.d14:
            print(f"확인 필요 (D-14 해석 · 게이트 판정에 넣지 않음): 괄호 없는 `입력` 칸의 역할이 다른 역할의 괄호 기능을 부른 {len(rb.d14)} 건 — "
                  + " / ".join(rb.d14))
    if flow is not None:
        no_log = sorted(k for k, oks in flow.audit.items() if not all(oks))
        print(f"참고 (G-18 은 QA3 판정): 쓰기 기능 {len(flow.audit)} 개의 성공한 호출 {sum(len(x) for x in flow.audit.values())} 건 가운데 "
              f"`변경` 로그가 남지 않은 기능 {len(no_log)} {no_log[:5] if no_log else ''}".rstrip())
        for s in flow.steps:
            if not s.ok:
                print(f"    흐름 실패 — {s.fn_id} [{s.role}] {s.call} → {s.status} {s.evidence[:160]}")
    for gate in ("G-02", "G-03", "G-17"):
        n = sum(1 for x in r.rows if x[0] == gate)
        print(f"{gate} 판정: {'PASS' if r.failed(gate) == 0 else 'FAIL'} (검사 {n} · 실패 {r.failed(gate)})")
    return 1 if any(not ok for _, _, ok, _ in r.rows) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
