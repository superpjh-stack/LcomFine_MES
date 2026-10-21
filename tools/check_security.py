#!/usr/bin/env python
"""G-16~G-22 보안 · 운영 판정 (QA3) — `make check-security`. 서버를 띄우지 않고 TestClient 로 앱을 직접 부른다.

출력은 `G-nn  항목  PASS|FAIL  실측` 행이다(gate.py `_ROW_RE`). 종료코드 = FAIL 행 수.
  · G-16 데이터 질의 · G-17 키 없음 · G-18 SSO 는 W3/W4 범위 — 아직 기능이 없으므로 FAIL 「W3/W4」 로 찍는다(게이트를 낮추지 않는다).
  · G-19 권한 403 전수 · G-20 세션 상태 · G-21 비밀 · G-22 변경 감사 로그 를 실제 요청으로 잰다.
  · G-24 는 compose 문법 · Dockerfile 정적 검사만(컨테이너는 띄우지 않는다 — gate.py 가 G-24 를 따로 판정한다).
  · `X-nn` 행은 조용한 실패 사냥(DB 끊김 · 이상한 입력)이다 — 게이트 번호가 아니라 gate.py 는 읽지 않지만 FAIL 이면 종료코드에 센다.

계정: 부서 8 의 **임시 계정**(접두 `q3…` · 난수 비밀번호 · 이름 `(예시)`)을 만들어 쓰고 끝나면 지운다. 시드 계정(sl pr sh ds ac st ex admin)은
로그인 확인에만 쓴다 — 시드 계정의 상태를 바꾸면 `session_epoch` 트리거가 같은 DB 를 쓰는 다른 검사·테스트의 세션까지 끊기 때문이다.
권한 판정은 부서 단위(`sys_permission`)라 임시 계정과 시드 계정의 판정은 같다. 비밀번호 · 비밀 값은 어디에도 찍지 않는다.

    uv run python tools/check_security.py               # 판정표
    uv run python tools/check_security.py --run-seeds   # + 시드 1회 더 돌려 행 수 diff (G-21 시드 멱등 — gate-full 과 같은 측정)
    uv run --offline --with playwright python tools/check_security.py --e2e   # 화면 캡처(1280 · 390) → outputs/e2e/
"""

from __future__ import annotations

import warnings

warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient`")

import importlib
import inspect
import json
import os
import re
import secrets
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from lcomfine.app.settings import get_settings  # noqa: E402 — .env 를 읽는다

PASS, FAIL, WARN = "PASS", "FAIL", "WARN"
SEED_ACCOUNTS = ("sl", "pr", "sh", "ds", "ac", "st", "ex", "admin")
ABSENT_DB_DSN = "postgresql:///lcomfine_qa3_absent_db"   # 없는 DB — DB 끊김 재현용 (같은 소켓 · 이름만 없는 것)
E2E_DIR = ROOT / "outputs" / "e2e"
E2E_PATHS = ("/", "/wo/requests", "/shp/orders", "/lot/backward", "/ia")
E2E_WIDTHS = (1280, 390)


@dataclass
class Result:
    gid: str
    item: str
    status: str
    measured: str
    bad: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == PASS

    def line(self) -> str:
        return f"{self.gid}  {self.item}  {self.status}  {self.measured}"


def res(gid: str, item: str, ok: bool, measured: str, bad: list[str] | None = None, *, soft: bool = False) -> Result:
    st = PASS if ok else (WARN if soft else FAIL)
    bad = bad or []
    if bad:
        measured += " — " + " / ".join(bad[:6]) + (f" … 외 {len(bad) - 6}" if len(bad) > 6 else "")
    return Result(gid, item, st, measured, bad)


# ── 앱 · 계정 ───────────────────────────────────────────────────────────
def _app():
    from lcomfine.app.main import app

    return app


def new_client():
    from fastapi.testclient import TestClient

    return TestClient(_app(), raise_server_exceptions=False)


def login(login_id: str, password: str):
    c = new_client()
    r = c.post("/login", data={"login_id": login_id, "password": password}, follow_redirects=False)
    if r.status_code != 303:
        raise AssertionError(f"{login_id} 로그인 {r.status_code}")
    return c


class Lab:
    """임시 계정 · 임시 행의 수명. `with Lab() as lab:` — 끝나면 만든 것을 지운다(로그 행은 남는다 — 감사 로그는 지우지 않는다)."""

    def __init__(self) -> None:
        self.prefix = "q3" + uuid.uuid4().hex[:8]
        self.users: dict[str, tuple[str, str, int]] = {}    # 부서 코드 → (login_id, 비밀번호, user_id)
        self._clients: dict[str, object] = {}
        self.extra_users: list[str] = []

    def __enter__(self) -> "Lab":
        from lcomfine.app import rbac

        for r in rbac.roles():
            self.users[r.code] = self.make_user(r.code, r.code)
        return self

    def __exit__(self, *exc) -> None:
        self.cleanup()

    def make_user(self, role_code: str, tag: str) -> tuple[str, str, int]:
        from lcomfine.app import auth
        from lcomfine.db import conn

        login_id, pw = f"{self.prefix}{tag}".lower(), secrets.token_urlsafe(12)
        uid = conn.q1("insert into sys_user (login_id, user_name, password_hash, role_code, created_by) "
                      "values (%s, %s, %s, %s, 'qa3') returning user_id",
                      (login_id, f"QA3 임시 {tag} (예시)", auth.hash_password(pw), role_code))["user_id"]
        return login_id, pw, uid

    def client(self, role_code: str):
        if role_code not in self._clients:
            lid, pw, _ = self.users[role_code]
            self._clients[role_code] = login(lid, pw)
        return self._clients[role_code]

    def fresh(self, role_code: str):
        lid, pw, _ = self.users[role_code]
        return login(lid, pw)

    def cleanup(self) -> None:
        from lcomfine.db import conn

        like = self.prefix + "%"
        up = self.prefix.upper() + "%"
        with conn.tx() as cur:
            cur.execute("select request_no from production_request where item_id in (select id from item where item_code ilike %s)",
                        (like,))
            reqs = [r["request_no"] for r in cur.fetchall()]
            # 이상한 입력이 잘못 저장된 경우까지 — 원자재 LOT · 입고 · 출하 지시 (만든 품목 · 거래처 기준)
            cur.execute("select id, lot_no, receipt_id from material_lot where item_id in (select id from item where item_code ilike %s)",
                        (like,))
            mls = cur.fetchall()
            m_ids, r_ids = [r["id"] for r in mls], [r["receipt_id"] for r in mls]
            cur.execute("delete from notification where split_part(dedupe_key, ':', 2) = any(%s)", ([r["lot_no"] for r in mls],))
            cur.execute("delete from stock_move where lot_kind = '원자재' and lot_id = any(%s)", (m_ids,))
            cur.execute("delete from lot_stock where lot_kind = '원자재' and lot_id = any(%s)", (m_ids,))
            cur.execute("delete from incoming_inspection where material_lot_id = any(%s)", (m_ids,))
            cur.execute("delete from material_lot where id = any(%s)", (m_ids,))
            cur.execute("delete from material_receipt where id = any(%s) or supplier_name ilike %s", (r_ids, like))
            cur.execute("select id from shipment_order where customer_id in (select id from customer where customer_code ilike %s)", (like,))
            s_ids = [r["id"] for r in cur.fetchall()]
            cur.execute("delete from shipment_line where shipment_order_id = any(%s)", (s_ids,))
            cur.execute("delete from shipment_order where id = any(%s)", (s_ids,))
            cur.execute("delete from notification where dedupe_key ilike %s or message ilike %s or dedupe_key = any(%s)",
                        (f"%{self.prefix}%", f"%{self.prefix}%", [f"request_created:{n}" for n in reqs]))
            cur.execute("delete from production_request where item_id in (select id from item where item_code ilike %s)", (like,))
            cur.execute("delete from standard where standard_code ilike %s", (like,))
            cur.execute("delete from location where warehouse_id in (select id from warehouse where warehouse_code ilike %s)", (like,))
            cur.execute("delete from location where location_code ilike %s", (like,))
            cur.execute("delete from warehouse where warehouse_code ilike %s", (like,))
            cur.execute("delete from item where item_code ilike %s or item_code ilike %s", (like, up))
            cur.execute("delete from customer where customer_code ilike %s", (like,))
            cur.execute("delete from sys_common_code where code ilike %s or group_code ilike %s", (like, like))
            cur.execute("delete from notification_setting where user_id in (select user_id from sys_user where login_id ilike %s)",
                        (like,))
            cur.execute("delete from sys_user where login_id ilike %s", (like,))


def router_routes() -> list[tuple[str, str, str, object, list[str]]]:
    """라우터 모듈의 (모듈, 메서드, 경로, endpoint, 의존성이 잡은 화면/기능 ID) — `main.py` 가 include 하는 그대로."""
    from lcomfine.app import nav

    def deps(d, out):
        for s in d.dependencies:
            for cell in (getattr(s.call, "__closure__", None) or ()):
                try:
                    v = cell.cell_contents
                except ValueError:
                    continue
                if isinstance(v, str) and re.fullmatch(r"(F-[A-Z]+-\d{3}|[A-Z]+-\d{3})", v):
                    out.append(v)
            deps(s, out)
        return out

    out = []
    for m in nav.MODULES:
        try:
            mod = importlib.import_module(f"lcomfine.app.routers.{m}")
        except ModuleNotFoundError:
            continue
        for r in mod.router.routes:
            for meth in sorted(getattr(r, "methods", None) or ()):
                out.append((m, meth, r.path, r.endpoint, deps(r.dependant, [])))
    return out


def write_functions_routed():
    """W1 에 라우트가 있는 쓰기 기능 — [(Function, 라우트 경로)]."""
    from lcomfine.app import contracts

    routed = {(meth, path) for _, meth, path, _, _ in router_routes()}
    return [f for f in contracts.write_functions() if (f.method, f.path) in routed]


def concrete(path: str, value: str = "0") -> str:
    return re.sub(r"\{[^}]+\}", value, path)


# ── G-19 권한 ───────────────────────────────────────────────────────────
def check_static_require_fn() -> Result:
    """라우터의 POST 마다 자기 기능 ID 의 `require_fn` 이 걸렸는가 (기능 목록의 API 열과 글자 그대로)."""
    from lcomfine.app import contracts

    by_api = {f.api: f for f in contracts.functions()}
    posts = [r for r in router_routes() if r[1] == "POST"]
    bad = []
    for m, meth, path, _, ids in posts:
        fn = by_api.get(f"POST {path}")
        if fn is None:
            bad.append(f"POST {path}: 기능 목록에 없는 쓰기 라우트")
        elif fn.id not in ids:
            bad.append(f"POST {path}: require_fn({fn.id}) 없음 (잡힌 것 {ids})")
    gets = [r for r in router_routes() if r[1] == "GET" and not r[4]]
    bad += [f"GET {p}: 권한 의존성 없음" for _, _, p, _, _ in gets]
    return res("G-19", "쓰기 라우트 require_fn", not bad, f"POST {len(posts)} · GET {len([r for r in router_routes() if r[1] == 'GET'])} 중 빠짐 {len(bad)}", bad)


def check_no_session_401() -> Result:
    """세션 없이 모든 W1 쓰기 API POST → 401 (JSON). 화면 GET 은 JSON 이면 401 · 브라우저면 /login 303."""
    from lcomfine.app import nav

    c = new_client()
    fns = write_functions_routed()
    bad = []
    for f in fns:
        r = c.post(concrete(f.path), data={})
        if r.status_code != 401:
            bad.append(f"{f.id} {r.status_code}")
    n_get = 0
    for sc in nav.SCREENS:
        if sc.common:
            continue
        n_get += 1
        r = c.get(sc.path)
        if r.status_code != 401:
            bad.append(f"GET {sc.path} {r.status_code}")
        r = c.get(sc.path, headers={"accept": "text/html"}, follow_redirects=False)
        if r.status_code != 303 or not r.headers.get("location", "").startswith("/login"):
            bad.append(f"GET {sc.path} (html) {r.status_code} → {r.headers.get('location')}")
    return res("G-19", "세션 없음 401", not bad, f"쓰기 POST {len(fns)} · 화면 GET {n_get}×2 중 어긋남 {len(bad)}", bad)


def check_write_403(lab: Lab) -> Result:
    """쓰기 기능 × 부서 8 전수 — 계약(function-list 권한 열)에 W 가 없는 부서는 403, W 부서는 403·401 이 아니다(본문이 비어 422/404)."""
    from lcomfine.app import rbac

    fns = write_functions_routed()
    bad, n403, nother = [], 0, 0
    for f in fns:
        for r in rbac.roles():
            expect_403 = (r.code not in f.roles_w) and not f.permission_exception
            got = lab.client(r.code).post(concrete(f.path), data={}).status_code
            if expect_403:
                n403 += 1
                if got != 403:
                    bad.append(f"{f.id}×{r.code} {got} (403 기대)")
            else:
                nother += 1
                if got in (401, 403) or got >= 500:
                    bad.append(f"{f.id}×{r.code} {got} (W 칸 — 403/401/5xx 아님 기대)")
    return res("G-19", "R·없음 부서 쓰기 403", not bad,
               f"쓰기 기능 {len(fns)} × 부서 {len(rbac.roles())} — 403 기대 {n403} · 통과 기대 {nother} · 어긋남 {len(bad)}", bad)


def check_screen_403(lab: Lab) -> Result:
    """화면 67 × 부서 8 — 계약 칸이 없으면 403 · 있으면 200, 그리고 메뉴(메인 화면의 링크)에 칸 없는 화면 경로가 없다."""
    from lcomfine.app import contracts, nav, rbac

    cells = {(sid, rc): lv for sid, rc, lv in contracts.permission_cells()}
    routed = {(meth, path) for _, meth, path, _, _ in router_routes()}
    screen_paths = {sc.path for sc in nav.SCREENS}
    read_fns = [f for f in contracts.functions() if not f.is_write and (f.method, f.path) in routed and f.path not in screen_paths]
    bad, n = [], 0
    for r in rbac.roles():
        c = lab.client(r.code)
        for sc in nav.SCREENS:
            if sc.common:
                continue
            n += 1
            want = 200 if cells.get((sc.screen_id, r.code)) else 403
            got = c.get(sc.path).status_code
            if got != want:
                bad.append(f"{sc.screen_id}×{r.code} {got} ({want} 기대)")
        for f in read_fns:   # 화면 경로가 아닌 조회·출력 기능(출력 · 하위 경로) — 칸 없으면 403, 칸 있으면 403/401/5xx 가 아니다
            n += 1
            has = bool(cells.get((f.screen_id, r.code)))
            got = c.get(concrete(f.path)).status_code
            if (not has and got != 403) or (has and (got in (401, 403) or got >= 500)):
                bad.append(f"{f.id}×{r.code} GET {got} ({'통과' if has else '403'} 기대)")
        html = c.get("/", headers={"accept": "text/html"}).text
        hrefs = set(re.findall(r'href="([^"?#]+)', html))
        for sc in nav.SCREENS:
            if not sc.common and sc.path != "/" and not cells.get((sc.screen_id, r.code)) and sc.path in hrefs:
                bad.append(f"메뉴 {r.code}: 칸 없는 {sc.screen_id} 링크")
    return res("G-19", "칸 밖 화면 GET 403 · 메뉴 숨김", not bad,
               f"화면 {len([s for s in nav.SCREENS if not s.common])} + 하위 조회·출력 {len(read_fns)} × 부서 8 = GET {n} · 어긋남 {len(bad)}", bad)


def check_permission_change(lab: Lab) -> Result:
    """권한 칸은 DB 데이터 — SYS-021 로 칸 하나(EX × WO-040 R)를 지우면 다음 요청 403, 되돌리면 200. 칸은 finally 에서 원래 값으로."""
    from lcomfine.app import rbac
    from lcomfine.db import conn

    rc, sid, path = "EX", "WO-040", "/wo/status"
    orig = conn.q1("select level from sys_permission where role_code = %s and screen_id = %s", (rc, sid))
    orig_lv = orig["level"] if orig else ""
    c, adm = lab.client(rc), lab.client("ADM")
    try:
        a = c.get(path).status_code
        s1 = adm.post("/sys/roles", data={f"cell:{rc}:{sid}": ""}).status_code
        b = c.get(path).status_code
        s2 = adm.post("/sys/roles", data={f"cell:{rc}:{sid}": orig_lv or "R"}).status_code
        d = c.get(path).status_code
    finally:
        if orig_lv:
            conn.x("insert into sys_permission (role_code, screen_id, level) values (%s, %s, %s) "
                   "on conflict (role_code, screen_id) do update set level = excluded.level", (rc, sid, orig_lv))
        else:
            conn.x("delete from sys_permission where role_code = %s and screen_id = %s", (rc, sid))
        rbac.invalidate()
    ok = (a, s1, b, s2, d) == (200, 200, 403, 200, 200) and orig_lv == "R"
    return res("G-19", "권한 칸 변경 다음 요청 반영", ok,
               f"{rc}×{sid} 칸 {orig_lv or '없음'} — 전 {a} · 칸 지움 {s1} → 다음 요청 {b} · 되돌림 {s2} → {d}")


def check_idor(lab: Lab) -> Result:
    """ID 바꿔치기 — 다른 부서 알림 처리 404(F-HOME-022 계약) · W 없는 부서의 남의 의뢰 수정 403(F-WO-012) · 행은 그대로."""
    from lcomfine.db import conn

    bad = []
    p = lab.prefix
    n = conn.q1("insert into notification (event_key, to_role, link, dedupe_key, message) values "
                "('request_created', 'PR', '/wo/requests', %s, %s) returning id",
                (f"qa3:{p}:idor", f"QA3 IDOR 시험 {p} (예시)"))["id"]
    for role in ("SL", "SH", "DS", "AC", "ST", "EX"):
        r = lab.client(role).post(f"/home/notifications/{n}/handle")
        if r.status_code != 404:
            bad.append(f"알림(PR) 처리 by {role} {r.status_code} (404 기대)")
    row = conn.q1("select handled_at from notification where id = %s", (n,))
    if row["handled_at"] is not None:
        bad.append("다른 부서가 알림을 처리해 버렸다")
    r = lab.client("PR").post(f"/home/notifications/{n}/handle")
    if r.status_code != 200 or conn.q1("select handled_by from notification where id = %s", (n,))["handled_by"] is None:
        bad.append(f"자기 부서(PR) 처리 {r.status_code} (200 + handled_by 기대)")
    for bogus in ("999999999999", "abc", "-1"):
        r = lab.client("PR").post(f"/home/notifications/{bogus}/handle")
        if r.status_code != 404:
            bad.append(f"알림 id {bogus!r} {r.status_code} (404 기대)")
    # 의뢰 수정 — 영업부가 만든 의뢰를 W 없는 부서가 고친다
    cu = conn.q1("insert into customer (customer_code, customer_name, created_by) values (%s, %s, 'qa3') returning id",
                 (f"{p}C", f"{p} 거래처 (예시)"))["id"]
    it = conn.q1("insert into item (item_code, item_name, item_type, created_by) values (%s, %s, '제품', 'qa3') returning id",
                 (f"{p}FG", f"{p} 제품 (예시)"))["id"]
    rq = conn.q1("insert into production_request (request_no, customer_id, item_id, qty, due_date, status, created_by) "
                 "values (%s, %s, %s, 10, current_date + 7, '확인대기', 'qa3') returning id",
                 (f"{p}REQ", cu, it))["id"]
    body = {"customer_id": str(cu), "item_id": str(it), "qty": "999", "due_date": "2027-01-31", "status": "확인대기",
            "note": "QA3 바꿔치기"}
    for role in ("DS", "AC", "ST", "EX", "SH"):
        r = lab.client(role).post(f"/wo/requests/{rq}", data=body)
        if r.status_code != 403:
            bad.append(f"의뢰 수정 by {role} {r.status_code} (403 기대)")
    if conn.q1("select qty from production_request where id = %s", (rq,))["qty"] != 10:
        bad.append("W 없는 부서가 의뢰 수량을 바꿨다")
    # API 명세 — 미로그인 401 · 시스템 관리 화면을 못 보는 부서 403 · /docs 없음
    anon = new_client()
    for path, want in (("/openapi.json", 401), ("/docs", 404), ("/redoc", 404)):
        got = anon.get(path).status_code
        if got != want:
            bad.append(f"미로그인 GET {path} {got} ({want} 기대)")
    got = lab.client("SL").get("/openapi.json").status_code
    if got != 403:
        bad.append(f"영업부 GET /openapi.json {got} (403 기대)")
    return res("G-19", "ID 바꿔치기 · 명세 노출", not bad, f"알림 다른 부서 6 · 의뢰 수정 W 없는 부서 5 · 명세 4 — 어긋남 {len(bad)}", bad)


# ── G-20 세션 ───────────────────────────────────────────────────────────
def _status(c, path: str = "/bas/items") -> int:
    return c.get(path).status_code


def check_sessions(lab: Lab) -> list[Result]:
    """요청마다 DB — 중지 · 잠금 · 비밀번호 초기화 · session_epoch · 로그아웃 쿠키 재사용 · 계정 삭제 → 401, 부서 변경은 다음 요청부터."""
    from lcomfine.db import conn

    out: list[Result] = []
    admin = lab.client("ADM")

    def target(tag: str, role: str = "PR"):
        lid, pw, uid = lab.make_user(role, tag)
        return lid, pw, uid, login(lid, pw)

    def upd(uid: int, lid: str, **kw):
        body = {"login_id": lid, "user_name": f"QA3 임시 {lid} (예시)", "role_code": kw.get("role", "PR"),
                "status": kw.get("status", "정상")}
        if "password" in kw:
            body["password"] = kw["password"]
        r = admin.post(f"/sys/users/{uid}", data=body)
        if r.status_code != 200:
            raise AssertionError(f"SYS-012 수정 {r.status_code} {r.text[:200]}")

    # 1. 중지(SYS-012 화면 경로) → 다음 요청 401 · 정상 복구해도 옛 세션은 401 · 다시 로그인하면 된다
    for st in ("중지", "잠금"):
        lid, pw, uid, c = target(f"st{'s' if st == '중지' else 'l'}")
        before = _status(c)
        upd(uid, lid, status=st)
        after, post = _status(c), c.post("/bas/items", data={}).status_code
        upd(uid, lid, status="정상")
        revived = _status(c)
        relog = _status(login(lid, pw))
        ok = (before, after, post, revived, relog) == (200, 401, 401, 401, 200)
        out.append(res("G-20", f"{st} → 401", ok,
                       f"전 {before} · {st} 뒤 GET {after} · POST {post} · 정상 복구 뒤 옛 세션 {revived} · 다시 로그인 {relog}"))
    # 2. 비활성(F-SYS-013)
    lid, pw, uid, c = target("deac")
    r = admin.post(f"/sys/users/{uid}/delete")
    got = _status(c)
    out.append(res("G-20", "비활성(F-SYS-013) → 401", r.status_code == 200 and got == 401, f"비활성 {r.status_code} · 다음 요청 {got}"))
    # 3. 부서 변경 — 끊기지 않고 다음 요청부터 새 부서 칸 (PR: BAS-030 W → SL: BAS-030 없음)
    lid, pw, uid, c = target("role")
    a = _status(c, "/bas/warehouses")
    upd(uid, lid, role="SL")
    b, home, w = _status(c, "/bas/warehouses"), _status(c, "/"), c.post("/bas/warehouses", data={}).status_code
    upd(uid, lid, role="PR")
    back = _status(c, "/bas/warehouses")
    ok = (a, b, home, w, back) == (200, 403, 200, 403, 200)
    out.append(res("G-20", "부서 변경 다음 요청 반영", ok,
                   f"PR 때 BAS-030 {a} · SL 로 바꾼 다음 요청 {b} · 같은 세션 메인 {home} · 쓰기 {w} · PR 복구 {back}"))
    # 4. 로그아웃 쿠키 재사용 · 다른 단말 세션은 그대로
    lid, pw, uid, c = target("lout")
    c2 = login(lid, pw)
    saved_cookie = dict(c.cookies)
    c.post("/logout", follow_redirects=False)
    replay = new_client()
    for k, v in saved_cookie.items():
        replay.cookies.set(k, v)
    got_r, got_c, other = _status(replay), _status(c), _status(c2)
    out.append(res("G-20", "로그아웃 쿠키 재사용 401", (got_r, got_c, other) == (401, 401, 200),
                   f"로그아웃 전 쿠키 재사용 {got_r} · 그 클라이언트 {got_c} · 같은 계정 다른 세션 {other}"))
    # 5. 비밀번호 초기화(SYS-012) → 옛 세션 401
    lid, pw, uid, c = target("pwd")
    upd(uid, lid, password=secrets.token_urlsafe(12))
    got = _status(c)
    out.append(res("G-20", "비밀번호 변경 뒤 옛 세션 401", got == 401, f"다음 요청 {got}"))
    # 6. session_epoch 를 SQL 로 올림 → 401
    lid, pw, uid, c = target("ep")
    conn.x("update sys_user set session_epoch = session_epoch + 1 where user_id = %s", (uid,))
    got = _status(c)
    out.append(res("G-20", "session_epoch 증가 → 401", got == 401, f"다음 요청 {got}"))
    # 7. 계정 삭제 → 401 (쿠키에 남은 login_id 로 통하지 않는다)
    lid, pw, uid, c = target("del")
    conn.x("delete from sys_user where user_id = %s", (uid,))
    got = _status(c)
    out.append(res("G-20", "계정 삭제 → 401", got == 401, f"다음 요청 {got}"))
    # 8. 쿠키의 부서 값을 믿지 않는다 — 쿠키는 서명돼 있어 고칠 수 없다(서명 깨진 쿠키는 미로그인)
    lid, pw, uid, c = target("tamp")
    forged = new_client()
    for k, v in dict(c.cookies).items():
        forged.cookies.set(k, v[:-4] + ("AAAA" if not v.endswith("AAAA") else "BBBB"))
    got = _status(forged)
    out.append(res("G-20", "서명 깨진 쿠키 → 401", got == 401, f"다음 요청 {got}"))
    return out


# ── G-21 비밀 ───────────────────────────────────────────────────────────
def _secret_values() -> list[str]:
    from tools import gate

    return [v for v in (os.environ.get(k) for k in gate.SECRET_KEYS) if v and len(v) >= 8]


def check_secrets() -> list[Result]:
    from tools import gate

    out = [Result("G-21", "비밀 스캔(추적 파일)", *gate.secret_scan())]
    try:
        out.append(Result("G-21", "시드 (예시)", *gate.seed_examples()))
    except Exception as exc:  # noqa: BLE001 — DB 가 없으면 그 사실이 실측이다
        out.append(Result("G-21", "시드 (예시)", FAIL, f"DB 조회 실패 — {type(exc).__name__}"))
    # 응답에 비밀 · 접속 문자열이 실리지 않는다 (인증 없이 열리는 것 + 오류 응답)
    values = _secret_values() + [get_settings().pg_dsn]
    c = new_client()
    bodies = {"/health": c.get("/health").text, "/login": c.get("/login").text, "/error?status=500": c.get("/error?status=500").text,
              "/nope (404)": c.get("/nope-qa3").text, "POST /login 실패": c.post("/login", data={"login_id": "x", "password": "y"}).text}
    leaks = [k for k, b in bodies.items() if any(v in b for v in values)]
    out.append(res("G-21", "응답에 비밀 값 없음", not leaks, f"인증 없는 응답 {len(bodies)} 중 비밀·접속 문자열 실린 것 {len(leaks)}", leaks))
    # 시드 계정 8 이 settings 의 비밀번호로 로그인된다(비밀번호는 코드·문서에 없다 — 위 스캔)
    pw = get_settings().seed_password or ""
    bad = []
    for lid in SEED_ACCOUNTS:
        r = new_client().post("/login", data={"login_id": lid, "password": pw}, follow_redirects=False)
        if r.status_code != 303:
            bad.append(f"{lid} {r.status_code}")
    out.append(res("G-21", "시드 계정 8 로그인(.env 비밀번호)", bool(pw) and not bad, f"{len(SEED_ACCOUNTS) - len(bad)}/{len(SEED_ACCOUNTS)} 로그인", bad))
    return out


def check_seed_idempotence() -> Result:
    from tools import gate

    return Result("G-21", "시드 멱등", *gate.seed_idempotence())


# ── G-22 감사 로그 ──────────────────────────────────────────────────────
def _max_change_id() -> int:
    from lcomfine.db import conn

    return conn.q1("select coalesce(max(id), 0) as m from sys_change_log")["m"]


def _changes_since(since: int, login_id: str) -> list[dict]:
    from lcomfine.db import conn

    return conn.q("select function_id, screen_id, target, method, path, login_id, role_code from sys_change_log "
                  "where id > %s and login_id = %s order by id", (since, login_id))


def check_change_log(lab: Lab) -> list[Result]:
    """쓰기 성공마다 sys_change_log 정확히 1행(기능 ID · 대상 · 사용자 · 경로) · 실패한 쓰기(422 · 403)는 0행."""
    from lcomfine.app import contracts
    from lcomfine.db import conn

    p = lab.prefix
    adm_lid = lab.users["ADM"][0]
    adm = lab.client("ADM")
    cu = conn.q1("insert into customer (customer_code, customer_name, created_by) values (%s, %s, 'qa3') returning id",
                 (f"{p}c2", f"{p} 거래처 (예시)"))["id"]
    fg = conn.q1("insert into item (item_code, item_name, item_type, created_by) values (%s, %s, '제품', 'qa3') returning id",
                 (f"{p}fg2", f"{p} 제품 (예시)"))["id"]
    note_id = conn.q1("insert into notification (event_key, to_role, link, dedupe_key, message) values "
                      "('request_created', 'ADM', '/wo/requests', %s, %s) returning id",
                      (f"qa3:{p}:log", f"QA3 감사 로그 시험 {p} (예시)"))["id"]
    tmp_user = lab.make_user("SL", "logu")
    ctx: dict = {}
    cases = [
        ("F-BAS-011", "/bas/items", lambda: {"item_code": f"{p}it", "item_name": f"{p} 품목 (예시)", "item_type": "제품"}),
        ("F-BAS-012", lambda: f"/bas/items/{ctx['item']}", lambda: {"item_code": f"{p}it", "item_name": f"{p} 품목 수정 (예시)",
                                                                       "item_type": "제품", "use_yn": "Y"}),
        ("F-BAS-013", lambda: f"/bas/items/{ctx['item']}/delete", lambda: {}),
        ("F-BAS-021", "/bas/customers", lambda: {"customer_code": f"{p}cu", "customer_name": f"{p} 거래처 (예시)"}),
        ("F-BAS-031", "/bas/warehouses", lambda: {"target": "warehouse", "warehouse_code": f"{p}wh", "warehouse_name": f"{p} 창고 (예시)"}),
        ("F-STD-021", "/std/standards", lambda: {"standard_code": f"{p}sd", "standard_name": f"{p} 표준 (예시)"}),
        ("F-WO-011", "/wo/requests", lambda: {"customer_id": str(cu), "item_id": str(fg), "qty": "5", "due_date": "2027-01-31"}),
        ("F-WO-012", lambda: f"/wo/requests/{ctx['req']}", lambda: {"customer_id": str(cu), "item_id": str(fg), "qty": "6",
                                                                       "due_date": "2027-01-31", "status": "확인대기"}),
        ("F-HOME-022", f"/home/notifications/{note_id}/handle", lambda: {}),
        ("F-HOME-031", "/home/notification-settings", lambda: {"events": ["material_received"], "enabled": ["material_received"]}),
        ("F-SYS-011", "/sys/users", lambda: {"login_id": f"{p}nu", "user_name": f"{p} 사용자 (예시)", "role_code": "SL",
                                             "password": secrets.token_urlsafe(12)}),
        ("F-SYS-012", f"/sys/users/{tmp_user[2]}", lambda: {"login_id": tmp_user[0], "user_name": "QA3 임시 수정 (예시)",
                                                              "role_code": "SL", "status": "정상"}),
        ("F-SYS-031", "/sys/codes", lambda: {"group_code": "설비", "code": f"{p}cd", "code_name": f"{p} 코드 (예시)", "sort_no": "1"}),
    ]
    bad, logs = [], []
    for fid, path, body in cases:
        path = path() if callable(path) else path
        fn = contracts.function(fid)
        since = _max_change_id()
        r = adm.post(path, data=body())
        rows = _changes_since(since, adm_lid)
        if r.status_code != 200:
            bad.append(f"{fid} 쓰기 {r.status_code} {r.text[:120]}")
            continue
        data = r.json()
        if fid == "F-BAS-011":
            ctx["item"] = data.get("id")
        if fid == "F-WO-011":
            ctx["req"] = data.get("id")
        if len(rows) != 1:
            bad.append(f"{fid} 변경 로그 {len(rows)}행 (1 기대)")
            continue
        rw = rows[0]
        if (rw["function_id"], rw["screen_id"], rw["method"], rw["path"]) != (fid, fn.screen_id, "POST", path) or not rw["target"]:
            bad.append(f"{fid} 로그 값 {rw}")
        logs.append(rw["target"])
    out = [res("G-22", "쓰기 성공 → sys_change_log 1행", not bad, f"쓰기 표본 {len(cases)} (모듈 6) · 어긋남 {len(bad)}", bad)]
    # 실패한 쓰기는 로그 0행
    bad2 = []
    for role, path in (("ADM", "/bas/items"), ("SL", "/bas/warehouses"), ("ADM", "/wo/requests")):
        lid = lab.users[role][0]
        since = _max_change_id()
        got = lab.client(role).post(path, data={}).status_code
        n = len(_changes_since(since, lid))
        if n:
            bad2.append(f"{role} {path} {got} 인데 로그 {n}행")
    out.append(res("G-22", "실패한 쓰기(422·403) → 0행", not bad2, f"표본 3 · 어긋남 {len(bad2)}", bad2))
    # 화면 조회 · 로그인 성공/실패 → sys_access_log
    bad3 = []
    lid = lab.users["PR"][0]

    def acc(kind: str, extra: str = "", args=()) -> int:
        return conn.q1(f"select count(*) as n from sys_access_log where login_id = %s and log_type = %s {extra}",
                       (lid, kind, *args))["n"]

    c = lab.client("PR")
    for path, sid in (("/bas/items", "BAS-010"), ("/wo/requests", "WO-010"), ("/mat/receipts", "MAT-010"), ("/lot/backward", "LOT-020")):
        before = acc("조회", "and screen_id = %s", (sid,))
        st = c.get(path).status_code
        after = acc("조회", "and screen_id = %s", (sid,))
        if st != 200 or after - before != 1:
            bad3.append(f"GET {path} {st} · 조회 로그 +{after - before}")
    ok_b, fail_b = acc("로그인", "and result = '성공'"), acc("로그인", "and result = '실패'")
    lab.fresh("PR")
    new_client().post("/login", data={"login_id": lid, "password": "wrong-" + secrets.token_hex(4)})
    ok_a, fail_a = acc("로그인", "and result = '성공'"), acc("로그인", "and result = '실패'")
    if (ok_a - ok_b, fail_a - fail_b) != (1, 1):
        bad3.append(f"로그인 성공 +{ok_a - ok_b} · 실패 +{fail_a - fail_b} (1·1 기대)")
    out.append(res("G-22", "화면 조회 · 로그인 → sys_access_log", not bad3, f"화면 4 · 로그인 2 · 어긋남 {len(bad3)}", bad3))
    # SYS-040 에서 보인다
    page = adm.get("/sys/logs", params={"tab": "change", "login": adm_lid}).text if logs else ""
    seen = [t for t in logs if t in page]
    out.append(res("G-22", "SYS-040 에서 조회", bool(logs) and len(seen) == len(logs),
                   f"방금 쓴 변경 로그 {len(logs)} 중 SYS-040 화면에 보인 것 {len(seen)}",
                   [t for t in logs if t not in seen]))
    # 정적 — 라우터 POST 마다 log_change 를 부르는가(같은 모듈의 도우미 한 단계까지)
    out.append(check_static_log_change())
    return out


def check_static_log_change() -> Result:
    bad, n = [], 0
    for m, meth, path, ep, ids in router_routes():
        if meth != "POST":
            continue
        n += 1
        mod = sys.modules[ep.__module__]
        src = inspect.getsource(ep)
        helpers = [getattr(mod, name) for name in set(re.findall(r"\b(_?\w+)\(", src)) if inspect.isfunction(getattr(mod, name, None))
                   and getattr(mod, name).__module__ == mod.__name__]
        text = src + "".join(inspect.getsource(h) for h in helpers)
        if "log_change(" not in text:
            bad.append(f"POST {path}")
    return res("G-22", "정적: POST 마다 log_change", not bad, f"POST {n} 중 log_change 없음 {len(bad)}", bad)


# ── 조용한 실패 (X) ──────────────────────────────────────────────────────
_DB_DOWN_SCRIPT = r"""
import json, os, sys, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.join(os.environ["QA3_ROOT"], "src"))
from fastapi.testclient import TestClient
from lcomfine.app.main import app
c = TestClient(app, raise_server_exceptions=False)
for k, v in json.loads(os.environ["QA3_COOKIE"]).items():
    c.cookies.set(k, v)
out = {}
def grab(name, r):
    out[name] = {"status": r.status_code, "body": r.text[:4000]}
grab("health", c.get("/health"))
grab("screen_json", c.get("/bas/items"))
grab("screen_html", c.get("/bas/items", headers={"accept": "text/html"}, follow_redirects=False))
grab("home_html", c.get("/", headers={"accept": "text/html"}, follow_redirects=False))
grab("write", c.post("/bas/items", data={"item_code": "x", "item_name": "y", "item_type": "제품"}))
grab("login_page", c.get("/login", headers={"accept": "text/html"}))
grab("login_post", c.post("/login", data={"login_id": "x", "password": "y"}))
print("QA3JSON" + json.dumps(out, ensure_ascii=False))
"""


def db_down_probe(lab: Lab) -> dict:
    cookie = dict(lab.fresh("PR").cookies)
    env = dict(os.environ, LCOMFINE_PG_DSN=ABSENT_DB_DSN, QA3_ROOT=str(ROOT), QA3_COOKIE=json.dumps(cookie))
    p = subprocess.run([sys.executable, "-c", _DB_DOWN_SCRIPT], cwd=ROOT, env=env, capture_output=True, text=True, timeout=180)
    m = re.search(r"QA3JSON(.*)$", p.stdout, re.S)
    if not m:
        raise AssertionError(f"하위 프로세스 실패 rc={p.returncode}: {(p.stderr or p.stdout)[-400:]}")
    return json.loads(m.group(1))


def check_db_down(lab: Lab) -> list[Result]:
    """DB 를 끊으면(없는 DB 이름) /health 503 · 화면 · 쓰기 · 로그인도 503 — 멀쩡한 화면이나 「미수집」 으로 보이면 결함."""
    got = db_down_probe(lab)
    values = _secret_values() + [ABSENT_DB_DSN, "lcomfine_qa3_absent_db"]
    out = []
    h = got["health"]
    out.append(res("X-01", "DB 끊김 /health 503", h["status"] == 503 and not any(v in h["body"] for v in values),
                   f"/health {h['status']} · 본문에 접속 문자열 {'있음' if any(v in h['body'] for v in values) else '없음'}"))
    for key, label in (("screen_json", "화면 GET(JSON)"), ("screen_html", "화면 GET(브라우저)"), ("home_html", "메인 GET(브라우저)"),
                       ("write", "쓰기 POST"), ("login_page", "로그인 화면"), ("login_post", "로그인 POST")):
        g = got[key]
        silent = g["status"] < 400 and key != "login_page"
        if key == "login_page":   # 퀵 로그인 패널이 DB 를 읽는다 — 200 이면 DB 를 읽지 않은 것이므로 「미수집」 류 거짓 값이 없어야 한다
            silent = g["status"] == 200 and "미수집" in g["body"]
        leak = any(v in g["body"] for v in values)
        out.append(res("X-02", f"DB 끊김 {label}", g["status"] == 503 and not leak and not silent,
                       f"{g['status']}{' · 미수집 표시' if '미수집' in g['body'] else ''}{' · 접속 문자열 노출' if leak else ''}"))
    return out


def malformed_cases(lab: Lab) -> list[tuple[str, str, str, dict, str]]:
    """(라벨, 부서, 경로, 본문, 기대) — 기대 '422' 는 422(또는 404 경로 키), 'reject' 는 2xx 가 아니어야 하고 500 도 아니어야 한다."""
    from lcomfine.db import conn

    p = lab.prefix
    cu = conn.q1("insert into customer (customer_code, customer_name, created_by) values (%s, %s, 'qa3') returning id",
                 (f"{p}c3", f"{p} 거래처 (예시)"))["id"]
    fg = conn.q1("insert into item (item_code, item_name, item_type, created_by) values (%s, %s, '제품', 'qa3') returning id",
                 (f"{p}fg3", f"{p} 제품 (예시)"))["id"]
    rm = conn.q1("insert into item (item_code, item_name, item_type, created_by) values (%s, %s, '원자재', 'qa3') returning id",
                 (f"{p}rm3", f"{p} 원자재 (예시)"))["id"]
    wh = conn.q1("insert into warehouse (warehouse_code, warehouse_name, created_by) values (%s, %s, 'qa3') returning id",
                 (f"{p}w3", f"{p} 창고 (예시)"))["id"]
    loc = conn.q1("insert into location (warehouse_id, location_code, location_name, created_by) values (%s, %s, %s, 'qa3') returning id",
                  (wh, f"{p}l3", f"{p} 위치 (예시)"))["id"]
    big = "가" * 100_000
    req = {"customer_id": str(cu), "item_id": str(fg), "qty": "5", "due_date": "2027-01-31"}
    rec = {"supplier_name": f"{p} 공급사 (예시)", "received_on": "2026-10-21", "item_id": [str(rm)], "qty": ["10"],
           "location_id": [str(loc)], "supplier_lot_no": [f"{p}S1"]}
    shp = {"customer_id": str(cu), "due_date": "2027-01-31", "stock_id": ["1"], "qty": ["1"]}
    return [
        ("품목 코드 NUL", "ADM", "/bas/items", {"item_code": f"{p}n\x00ul", "item_name": "x (예시)", "item_type": "제품"}, "reject"),
        ("품목명 10만 자", "ADM", "/bas/items", {"item_code": f"{p}big", "item_name": big, "item_type": "제품"}, "no500"),
        ("거래처명 NUL", "ADM", "/bas/customers", {"customer_code": f"{p}cn", "customer_name": "a\x00b"}, "reject"),
        ("거래처 10만 자", "ADM", "/bas/customers", {"customer_code": f"{p}cb", "customer_name": big}, "no500"),
        ("의뢰 수량 음수", "SL", "/wo/requests", {**req, "qty": "-5"}, "reject"),
        ("의뢰 수량 1e30", "SL", "/wo/requests", {**req, "qty": "1e30"}, "reject"),
        ("의뢰 수량 NaN", "SL", "/wo/requests", {**req, "qty": "NaN"}, "reject"),
        ("의뢰 납기 99999년", "SL", "/wo/requests", {**req, "due_date": "99999-01-01"}, "reject"),
        ("의뢰 없는 거래처 FK", "SL", "/wo/requests", {**req, "customer_id": "999999999"}, "reject"),
        ("의뢰 거래처 id bigint 초과", "SL", "/wo/requests", {**req, "customer_id": "99999999999999999999"}, "reject"),
        ("의뢰 비고 NUL", "SL", "/wo/requests", {**req, "note": "a\x00b"}, "reject"),
        ("원자재 입고 수량 음수", "PR", "/mat/receipts", {**rec, "qty": ["-10"]}, "reject"),
        ("원자재 입고 없는 품목 FK", "PR", "/mat/receipts", {**rec, "item_id": ["999999999"]}, "reject"),
        ("원자재 입고 없는 위치 FK", "PR", "/mat/receipts", {**rec, "location_id": ["999999999"]}, "reject"),
        ("원자재 입고 공급사 NUL", "PR", "/mat/receipts", {**rec, "supplier_name": "a\x00b"}, "reject"),
        ("원자재 입고일 99999년", "PR", "/mat/receipts", {**rec, "received_on": "99999-12-31"}, "reject"),
        ("원자재 입고 수량 10^40", "PR", "/mat/receipts", {**rec, "qty": ["1" + "0" * 40]}, "reject"),
        ("출하 지시 없는 재고 FK", "SH", "/shp/orders", {**shp, "stock_id": ["999999999"]}, "reject"),
        ("출하 지시 수량 음수", "SH", "/shp/orders", {**shp, "qty": ["-1"]}, "reject"),
        ("출하 지시 납기 99999년", "SH", "/shp/orders", {**shp, "due_date": "99999-01-01"}, "reject"),
        ("재고 조정 없는 LOT 번호", "PR", "/inv/adjustments", {"lot_kind": "원자재", "lot_no": "없는LOT", "location_id": str(loc),
                                                         "actual_qty": "-3", "reason": "QA3"}, "reject"),
        ("생산일보 지시 id bigint 초과", "PR", "/prd/daily", {"work_order_id": "99999999999999999999", "work_date": "2026-10-21",
                                                         "produced_qty": "1", "good_qty": "1", "loss_qty": "0"}, "reject"),
        ("공통코드 NUL", "ADM", "/sys/codes", {"group_code": "설비", "code": "a\x00b", "code_name": "x (예시)", "sort_no": "1"}, "reject"),
        ("공통코드 정렬 bigint 초과", "ADM", "/sys/codes", {"group_code": "설비", "code": f"{p}c", "code_name": "x (예시)",
                                                       "sort_no": "99999999999999999999"}, "reject"),
        ("경로 id bigint 초과", "ADM", "/bas/items/99999999999999999999", {"item_code": "x", "item_name": "y", "item_type": "제품"}, "reject"),
        ("경로 id NUL", "ADM", "/bas/items/1%00", {"item_code": "x", "item_name": "y", "item_type": "제품"}, "reject"),
    ]


def check_malformed(lab: Lab) -> list[Result]:
    """이상한 입력 → 422(또는 경로 키 404). 500 은 결함 · 음수/없는 FK 가 저장되면(2xx) 결함 · 10만 자 저장은 계약에 길이 제한이 없어 참고."""
    out, bad, notes = [], [], []
    cases = malformed_cases(lab)
    for label, role, path, body, want in cases:
        r = lab.client(role).post(path, data=body)
        st = r.status_code
        if st >= 500:
            bad.append(f"{label} {st} {r.text[:120]}")
        elif want == "reject" and st < 400:
            bad.append(f"{label} {st} 저장됨 (422 기대)")
        elif want == "reject" and st not in (404, 422):
            bad.append(f"{label} {st} (422 기대)")
        elif want == "no500" and st < 400:
            notes.append(f"{label} {st} 저장됨")
    out.append(res("X-03", "이상한 입력 → 422", not bad, f"POST {len(cases)} (API 9) · 어긋남 {len(bad)}", bad))
    # 조회 인자에 NUL · 형식이 틀린 날짜 — 422 (500 이 아니다)
    bad_q = []
    c = lab.client("ADM")
    for path, params in (("/bas/items", {"q": "a\x00b"}), ("/wo/requests", {"q": "a\x00b"}), ("/wo/requests", {"due_from": "99999-01-01"}),
                         ("/lot/backward", {"lot_no": "a\x00b"}), ("/lot/forward", {"lot_no": "a\x00b"}), ("/shp/history", {"q": "a\x00b"}),
                         ("/mat/history", {"date_from": "2026-13-45"}), ("/sys/logs", {"tab": "change", "login": "a\x00b"})):
        st = c.get(path, params=params).status_code
        if st >= 500:
            bad_q.append(f"GET {path} {params} {st}")
    out.append(res("X-04", "조회 인자 NUL · 틀린 날짜 → 500 아님", not bad_q, f"GET 8 · 500 {len(bad_q)}", bad_q))
    if notes:
        print("참고 (X-03): " + " / ".join(notes))
    return out


# ── G-24 (정적) ─────────────────────────────────────────────────────────
def check_docker() -> list[Result]:
    out = []
    try:
        p = subprocess.run(["docker", "compose", "config", "-q"], cwd=ROOT, capture_output=True, text=True, timeout=120)
        rc, tail = p.returncode, (p.stderr or p.stdout).strip()[-160:]
    except FileNotFoundError:
        rc, tail = 127, "docker 없음"
    out.append(res("G-24", "docker compose config -q", rc == 0, f"rc={rc}{' ' + tail if rc else ''}"))
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
    syncs = "uv sync --frozen --no-dev" in dockerfile
    has = 'openpyxl' in pyproject and 'name = "openpyxl"' in lock
    out.append(res("G-24", "Dockerfile 이 openpyxl 을 설치", syncs and has,
                   f"uv sync --frozen {'있음' if syncs else '없음'} · pyproject·uv.lock 의 openpyxl {'있음' if has else '없음'}"))
    ignored = [ln.strip() for ln in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")]
    missing = []
    for ln in dockerfile.splitlines():
        m = re.match(r"\s*COPY\s+(?!--from)(.+)$", ln)
        if not m:
            continue
        parts = m.group(1).split()
        for src in parts[:-1]:
            if not (ROOT / src).exists():
                missing.append(f"COPY {src} (파일 없음)")
            elif any(src.rstrip("/") == ig.rstrip("/") or src.startswith(ig.rstrip("/") + "/") for ig in ignored if not ig.startswith("!")):
                missing.append(f"COPY {src} (.dockerignore)")
    out.append(res("G-24", "Dockerfile COPY 원본이 있다", not missing, f"COPY 원본 없음 {len(missing)} — 이대로면 `docker compose build` 가 실패한다" if missing else "COPY 원본 전부 있음", missing))
    return out


# ── E2E 캡처 ────────────────────────────────────────────────────────────
def e2e(port: int = 8020) -> int:
    """앱을 port 에 띄우고(하위 프로세스) Playwright 로 1280 · 390 캡처 + 가로 스크롤 0 확인 → outputs/e2e/."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("E2E  Playwright 없음 — `uv run --offline --with playwright python tools/check_security.py --e2e` (전역 설치 안 함)")
        return 1
    import urllib.request

    E2E_DIR.mkdir(parents=True, exist_ok=True)
    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "lcomfine.app.main:app", "--host", "127.0.0.1", "--port", str(port)],
                              cwd=ROOT, env=dict(os.environ, PYTHONPATH=str(ROOT / "src")), stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    results, fails = [], 0
    try:
        for _ in range(60):
            try:
                if urllib.request.urlopen(base + "/health", timeout=2).status == 200:
                    break
            except Exception:  # noqa: BLE001 — 기동 대기
                time.sleep(0.5)
        else:
            print("E2E  앱이 뜨지 않았다")
            return 1
        pw = get_settings().seed_password or ""
        plan = [("admin", p) for p in E2E_PATHS] + [("sl", "/wo/requests"), ("sh", "/shp/orders"), ("pr", "/lot/backward")]
        with sync_playwright() as play:
            browser = play.chromium.launch()
            for width in E2E_WIDTHS:
                for account in sorted({a for a, _ in plan}, key=SEED_ACCOUNTS.index):
                    ctx = browser.new_context(viewport={"width": width, "height": 900})
                    page = ctx.new_page()
                    page.goto(base + "/login")
                    page.fill("input[name=login_id]", account)
                    page.fill("input[name=password]", pw)
                    page.locator("#login-form button.btn-primary").click()
                    page.wait_for_load_state("networkidle")
                    for acc, path in plan:
                        if acc != account:
                            continue
                        resp = page.goto(base + path)
                        page.wait_for_load_state("networkidle")
                        sw, iw = page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
                        name = f"{account}{path.replace('/', '_') if path != '/' else '_home'}-{width}.png"
                        page.screenshot(path=str(E2E_DIR / name), full_page=True)
                        ok = resp is not None and resp.status == 200 and sw <= iw and "/login" not in page.url
                        fails += 0 if ok else 1
                        results.append({"account": account, "path": path, "width": width, "status": resp.status if resp else None,
                                        "url": page.url.replace(base, ""), "scrollWidth": sw, "innerWidth": iw, "ok": ok, "file": name})
                        print(f"E2E  {account} {path} @{width}  {'PASS' if ok else 'FAIL'}  status {resp.status if resp else '?'} · scrollWidth {sw} ≤ innerWidth {iw} · {name}")
                    ctx.close()
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=10)
    (E2E_DIR / "result.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    return fails


# ── 판정표 ──────────────────────────────────────────────────────────────
def w3_rows() -> list[Result]:
    return [Result("G-16", "데이터 질의 검증", FAIL, "W3/W4 — RPT-130 데이터 질의 미구현 (라우터 없음 · 판정 대상 없음)"),
            Result("G-17", "키 없음", FAIL, "W3/W4 — AI 호출(ai.py · sys_ai_call_log) 미구현"),
            Result("G-18", "SSO 토큰", FAIL, "W3/W4 — DOC-010 SSO 미구현")]


def run_all(run_seeds: bool = False) -> list[Result]:
    rows: list[Result] = w3_rows()

    def guard(gid: str, item: str, fn, *args):
        try:
            got = fn(*args)
            return got if isinstance(got, list) else [got]
        except Exception as exc:  # noqa: BLE001 — 검사 자체가 깨진 것도 FAIL 로 보인다(조용히 넘기지 않는다)
            return [Result(gid, item, FAIL, f"검사 실패 — {type(exc).__name__}: {str(exc)[:200]}")]

    rows += guard("G-19", "쓰기 라우트 require_fn", check_static_require_fn)
    rows += guard("G-19", "세션 없음 401", check_no_session_401)
    with Lab() as lab:
        rows += guard("G-19", "R·없음 부서 쓰기 403", check_write_403, lab)
        rows += guard("G-19", "칸 밖 화면 GET 403", check_screen_403, lab)
        rows += guard("G-19", "ID 바꿔치기", check_idor, lab)
        rows += guard("G-19", "권한 칸 변경", check_permission_change, lab)
        rows += guard("G-20", "세션 상태", check_sessions, lab)
        rows += guard("G-21", "비밀", check_secrets)
        if run_seeds:
            rows += guard("G-21", "시드 멱등", check_seed_idempotence)
        rows += guard("G-22", "감사 로그", check_change_log, lab)
        rows += guard("X-01", "DB 끊김", check_db_down, lab)
        rows += guard("X-03", "이상한 입력", check_malformed, lab)
    rows += guard("G-24", "docker", check_docker)
    return rows


def main() -> int:
    if "--e2e" in sys.argv:
        return e2e()
    get_settings()
    t0 = time.time()
    rows = run_all("--run-seeds" in sys.argv)
    print("G-16~G-22 보안 · 운영 (tools/check_security.py · QA3) — 임시 계정으로 실제 요청")
    for r in rows:
        print(r.line())
    if "--run-seeds" not in sys.argv:
        print("참고 G-21 시드 멱등: 이 실행에서는 시드를 돌리지 않았다 — `make gate-full`(gate.py --run-seeds) 또는 `--run-seeds` 가 잰다")
    fails = sum(1 for r in rows if r.status == FAIL)
    print(f"판정: FAIL {fails} · PASS {sum(1 for r in rows if r.status == PASS)} · WARN {sum(1 for r in rows if r.status == WARN)} "
          f"({time.time() - t0:.0f}초)")
    return fails


if __name__ == "__main__":
    sys.exit(main())
