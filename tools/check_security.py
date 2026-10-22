#!/usr/bin/env python
"""G-16~G-22 보안 · 운영 판정 (QA3) — `make check-security`. 서버를 띄우지 않고 TestClient 로 앱을 직접 부른다.

출력은 `G-nn  항목  PASS|FAIL  실측` 행이다(gate.py `_ROW_RE`). 종료코드 = FAIL 행 수.
  · G-16 데이터 질의 검증 · G-17 키 없음 (W3): fake AI 를 `ai.set_client` 로 주입해 우회 SQL 50여 건을 보내고(422 · 실행 0 · 로그 1행), 키 없음은
    프로세스 안(`ai._config` 비움)과 하위 프로세스(`LCOMFINE_OPENAI_API_KEY=` 빈 값 · settings 실제 경로) 둘로 잰다. **실제 OpenAI 는 절대 부르지 않는다** —
    `no_real_ai()` 가 `urllib.request.urlopen` 을 막아 두고, 막힌 호출이 있으면 그 자체가 FAIL 로 보인다. 키 값은 어디에도 찍지 않는다.
  · G-18 SSO (W4): `sso.issue` · `sso.consume` 직접(재사용 · 만료 now 주입 · 변조 · 다른 비밀 · 형식 · 동시 2 스레드 · 비활성 · 매핑) +
    `POST /doc/go` 화면 경로(토큰 = hidden 1곳 · 주소/헤더/JSON/DB/로그 0 · 미확정 (D-517) 422 · SSO 로그 · SYS-040) + 하위 프로세스 uvicorn 서버 로그.
    주소 · 비밀은 `sso_env()` 가 잠깐 가짜 값(`https://doc.example.invalid/sso` · 난수)으로 바꾸고 되돌린다 — 외부로 아무것도 보내지 않는다.
  · X-11 앱 DB 역할(D-524 · DEF-QA3-003): 한 트랜잭션 안에서 `roles.apply` → `set local role` 로 잰 뒤 되돌린다(클러스터에 역할 0).
  · G-19 권한 403 전수 · G-20 세션 상태 · G-21 비밀 · G-22 변경 감사 로그 를 실제 요청으로 잰다.
  · G-24 는 compose 문법 · Dockerfile 정적 검사만(컨테이너는 띄우지 않는다 — gate.py 가 G-24 를 따로 판정한다).
  · `X-nn` 행은 조용한 실패 사냥(DB 끊김 · 이상한 입력)이다 — 게이트 번호가 아니라 gate.py 는 읽지 않지만 FAIL 이면 종료코드에 센다.
  · W2 수금(COL): 화면 7 × 부서 8 · 쓰기 4 × 부서 8 · 비활성/로그아웃 세션의 COL 401 · 쓰기 4 의 변경 로그 · 업로드 보안(X-05~X-08) 을 더 잰다.
    업로드 회차는 1985년 기준 기간(다른 테스트는 1990~1993 · 자기 접두) · 파일 이름 `q3…` · 끝에 지운다. 열 매핑은 **바꾸지 않는다**(지금 매핑의 열 이름으로 파일을 만든다).

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
import io
import json
import os
import re
import secrets
import subprocess
import sys
import time
import uuid
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
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
            cleanup_col(cur, like)
            cur.execute("delete from standard where standard_code ilike %s", (like,))
            cur.execute("delete from location where warehouse_id in (select id from warehouse where warehouse_code ilike %s)", (like,))
            cur.execute("delete from location where location_code ilike %s", (like,))
            cur.execute("delete from warehouse where warehouse_code ilike %s", (like,))
            cur.execute("delete from item where item_code ilike %s or item_code ilike %s", (like, up))
            cur.execute("delete from customer where customer_code ilike %s", (like,))
            cur.execute("delete from sys_common_code where code ilike %s or group_code ilike %s", (like, like))
            cur.execute("delete from notification_setting where user_id in (select user_id from sys_user where login_id ilike %s)",
                        (like,))
            # W3 — 임시 계정의 데이터 질의 · AI 호출 로그는 sys_user FK 라 계정을 지우기 전에 같이 지운다(내 시험 질의만 · 다른 사용자 행은 그대로).
            # sys_change_log · sys_access_log(login_id 글자) 는 W1 과 같이 남긴다.
            # W4 — 임시 계정의 SSO 토큰 · 문서관리 매핑(sys_user FK). SSO 접근 로그(sys_access_log)는 남긴다.
            cur.execute("delete from sso_token where user_id in (select user_id from sys_user where login_id ilike %s)", (like,))
            cur.execute("delete from doc_account_map where user_id in (select user_id from sys_user where login_id ilike %s)", (like,))
            cur.execute("delete from data_query_log where user_id in (select user_id from sys_user where login_id ilike %s)", (like,))
            cur.execute("delete from sys_ai_call_log where user_id in (select user_id from sys_user where login_id ilike %s)", (like,))
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
    """쓰기 기능 × 부서 8 전수 — 계약(function-list 권한 열)에 W 가 없는 부서는 403, W 부서는 403·401 이 아니다(본문이 비어 422/404).
    권한 예외 기능(`R 이상(권한 예외)` — F-RPT-132 · F-DOC-011 · F-HOME-022)은 api-contract §4 「칸이 없으면 403 · R 이면 통과」 —
    기대값은 그 화면의 권한 칸(`rbac.level`)이다(W3 수정 · progress-dev3 §3-12: 옛 기대값은 권한 예외를 전 부서 통과로 봤다)."""
    from lcomfine.app import rbac

    fns = write_functions_routed()
    bad, n403, nother = [], 0, 0
    for f in fns:
        for r in rbac.roles():
            if f.permission_exception:
                expect_403 = rbac.level(r.code, f.screen_id) is None
            else:
                expect_403 = r.code not in f.roles_w
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
    from lcomfine.app import contracts, notify
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
    # F-HOME-031 (Ruling 24 · D-526): 자기 부서가 수신하는 이벤트를 전부 켠 채 저장하는 것만 200 — 생산부(PR)로 잰다.
    # 전산 관리자(ADM)는 수신 이벤트가 없어 어떤 본문도 422 다(아래 음성 표본).
    pr_events = [k for k, roles in notify.EVENTS.items() if "PR" in roles]
    ctx: dict = {}
    cases = [
        ("F-BAS-011", "ADM", "/bas/items", lambda: {"item_code": f"{p}it", "item_name": f"{p} 품목 (예시)", "item_type": "제품"}),
        ("F-BAS-012", "ADM", lambda: f"/bas/items/{ctx['item']}", lambda: {"item_code": f"{p}it", "item_name": f"{p} 품목 수정 (예시)",
                                                                              "item_type": "제품", "use_yn": "Y"}),
        ("F-BAS-013", "ADM", lambda: f"/bas/items/{ctx['item']}/delete", lambda: {}),
        ("F-BAS-021", "ADM", "/bas/customers", lambda: {"customer_code": f"{p}cu", "customer_name": f"{p} 거래처 (예시)"}),
        ("F-BAS-022", "ADM", f"/bas/customers/{cu}", lambda: {"customer_code": f"{p}c2", "customer_name": f"{p} 거래처 수정 (예시)",
                                                                "use_yn": "Y"}),
        ("F-BAS-031", "ADM", "/bas/warehouses", lambda: {"target": "warehouse", "warehouse_code": f"{p}wh", "warehouse_name": f"{p} 창고 (예시)"}),
        ("F-STD-021", "ADM", "/std/standards", lambda: {"standard_code": f"{p}sd", "standard_name": f"{p} 표준 (예시)"}),
        ("F-STD-022", "ADM", lambda: f"/std/standards/{ctx['std']}", lambda: {"standard_code": f"{p}sd",
                                                                                 "standard_name": f"{p} 표준 수정 (예시)", "use_yn": "Y"}),
        ("F-WO-011", "ADM", "/wo/requests", lambda: {"customer_id": str(cu), "item_id": str(fg), "qty": "5", "due_date": "2027-01-31"}),
        ("F-WO-012", "ADM", lambda: f"/wo/requests/{ctx['req']}", lambda: {"customer_id": str(cu), "item_id": str(fg), "qty": "6",
                                                                              "due_date": "2027-01-31", "status": "확인대기"}),
        ("F-HOME-022", "ADM", f"/home/notifications/{note_id}/handle", lambda: {}),
        ("F-HOME-031", "PR", "/home/notification-settings", lambda: {"events": pr_events, "enabled": pr_events}),
        ("F-SYS-011", "ADM", "/sys/users", lambda: {"login_id": f"{p}nu", "user_name": f"{p} 사용자 (예시)", "role_code": "SL",
                                                    "password": secrets.token_urlsafe(12)}),
        ("F-SYS-012", "ADM", f"/sys/users/{tmp_user[2]}", lambda: {"login_id": tmp_user[0], "user_name": "QA3 임시 수정 (예시)",
                                                                     "role_code": "SL", "status": "정상"}),
        ("F-SYS-031", "ADM", "/sys/codes", lambda: {"group_code": "설비", "code": f"{p}cd", "code_name": f"{p} 코드 (예시)", "sort_no": "1"}),
    ]
    bad, logs = [], []
    for fid, role, path, body in cases:
        path = path() if callable(path) else path
        fn = contracts.function(fid)
        since = _max_change_id()
        r = lab.client(role).post(path, data=body())
        rows = _changes_since(since, lab.users[role][0])
        if r.status_code != 200:
            bad.append(f"{fid} 쓰기 {r.status_code} {r.text[:120]}")
            continue
        data = r.json()
        if fid == "F-BAS-011":
            ctx["item"] = data.get("id")
        if fid == "F-STD-021":
            ctx["std"] = data.get("id")
        if fid == "F-WO-011":
            ctx["req"] = data.get("id")
        if len(rows) != 1:
            bad.append(f"{fid} 변경 로그 {len(rows)}행 (1 기대)")
            continue
        rw = rows[0]
        if (rw["function_id"], rw["screen_id"], rw["method"], rw["path"]) != (fid, fn.screen_id, "POST", path) or not rw["target"]:
            bad.append(f"{fid} 로그 값 {rw}")
        logs.append((lab.users[role][0], rw["target"]))
    mods = len({contracts.function(fid).screen_id.split("-")[0] for fid, *_ in cases})
    out = [res("G-22", "쓰기 성공 → sys_change_log 1행", not bad, f"쓰기 표본 {len(cases)} (모듈 {mods}) · 어긋남 {len(bad)}", bad)]
    # 실패한 쓰기는 로그 0행 — 빈 본문 422 · 칸 없는 부서 403 · F-HOME-031 의 범위 밖(ADM 은 수신 이벤트 없음) 422 ·
    # 부서 기본 끄기 422 · 메일 501(D-518). 응답 코드도 계약(function-list F-HOME-031 · D-526)과 맞아야 한다.
    bad2 = []
    neg = [
        ("ADM", "/bas/items", {}, (422,)),
        ("SL", "/bas/warehouses", {}, (403,)),
        ("ADM", "/wo/requests", {}, (422,)),
        ("ADM", "/home/notification-settings", {"events": ["material_received"], "enabled": ["material_received"]}, (422,)),
        ("PR", "/home/notification-settings", {"events": pr_events, "enabled": pr_events[1:]}, (422,)),
        ("PR", "/home/notification-settings", {"events": pr_events, "enabled": pr_events, "mail": "on"}, (501,)),
    ]
    for role, path, body, want in neg:
        lid = lab.users[role][0]
        since = _max_change_id()
        got = lab.client(role).post(path, data=body).status_code
        n = len(_changes_since(since, lid))
        if got not in want or n:
            bad2.append(f"{role} {path} → {got} (기대 {'/'.join(map(str, want))}) · 로그 {n}행")
    out.append(res("G-22", "실패한 쓰기(422·403·501) → 0행", not bad2, f"표본 {len(neg)} · 어긋남 {len(bad2)}", bad2))
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
    pages = {lid: adm.get("/sys/logs", params={"tab": "change", "login": lid}).text for lid in {lid for lid, _ in logs}}
    seen = [t for lid, t in logs if t in pages[lid]]
    out.append(res("G-22", "SYS-040 에서 조회", bool(logs) and len(seen) == len(logs),
                   f"방금 쓴 변경 로그 {len(logs)} 중 SYS-040 화면에 보인 것 {len(seen)}",
                   [f"{lid} {t}" for lid, t in logs if t not in pages[lid]]))
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
import json, os, sys, warnings, urllib.request
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.join(os.environ["QA3_ROOT"], "src"))
def _blocked(*a, **k):
    raise RuntimeError("QA3 — 실제 OpenAI 호출 차단")
urllib.request.urlopen = _blocked          # DB 끊김 재현 중에도 바깥으로 나가는 호출은 없다(키도 빈 값으로 넘긴다)
from fastapi.testclient import TestClient
from lcomfine.app.main import app
c = TestClient(app, raise_server_exceptions=False)
for k, v in json.loads(os.environ["QA3_COOKIE"]).items():
    c.cookies.set(k, v)
ex = TestClient(app, raise_server_exceptions=False)   # 경영진 세션 — RPT 화면 · 데이터 질의
for k, v in json.loads(os.environ["QA3_COOKIE_EX"]).items():
    ex.cookies.set(k, v)
out = {}
def grab(name, r):
    out[name] = {"status": r.status_code, "body": r.text[:4000]}
grab("rpt_screen", ex.get("/rpt/orders"))
grab("rpt_screen_html", ex.get("/rpt/orders", headers={"accept": "text/html"}, follow_redirects=False))
grab("rpt_query", ex.post("/rpt/query", data={"question": "q3 DB 끊김 (예시)"}))
grab("health", c.get("/health"))
grab("screen_json", c.get("/bas/items"))
grab("screen_html", c.get("/bas/items", headers={"accept": "text/html"}, follow_redirects=False))
grab("home_html", c.get("/", headers={"accept": "text/html"}, follow_redirects=False))
grab("write", c.post("/bas/items", data={"item_code": "x", "item_name": "y", "item_type": "제품"}))
grab("login_page", c.get("/login", headers={"accept": "text/html"}))
grab("login_post", c.post("/login", data={"login_id": "x", "password": "y"}))
import io
from openpyxl import Workbook
wb = Workbook(); ws = wb.active; ws.append(["a", "b"]); ws.append(["1", "2"]); buf = io.BytesIO(); wb.save(buf)
grab("col_upload", c.post("/col/uploads", data={"action": "apply", "period_from": "1985-01-01", "period_to": "1985-01-31"},
                          files={"file": ("q3 db-down (예시).xlsx", buf.getvalue(),
                                          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}))
grab("col_screen", c.get("/col/collections"))
print("QA3JSON" + json.dumps(out, ensure_ascii=False))
"""


def db_down_probe(lab: Lab) -> dict:
    cookie = dict(lab.fresh("PR").cookies)
    cookie_ex = dict(lab.fresh("EX").cookies)
    env = dict(os.environ, LCOMFINE_PG_DSN=ABSENT_DB_DSN, LCOMFINE_OPENAI_API_KEY="", QA3_ROOT=str(ROOT),
               QA3_COOKIE=json.dumps(cookie), QA3_COOKIE_EX=json.dumps(cookie_ex))
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
                       ("write", "쓰기 POST"), ("login_page", "로그인 화면"), ("login_post", "로그인 POST"),
                       ("col_upload", "COL 업로드 POST(multipart)"), ("col_screen", "COL 화면 GET"),
                       ("rpt_screen", "RPT 대시보드 GET(JSON)"), ("rpt_screen_html", "RPT 대시보드 GET(브라우저)"),
                       ("rpt_query", "RPT-130 질의 POST")):
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

    cached = getattr(lab, "_malformed_cases", None)
    if cached is not None:  # 같은 Lab 에서 두 번 부르면(check_malformed 뒤 test_nul_…) 기준 행을 다시 넣지 않는다
        return cached
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
    lab._malformed_cases = [
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
    return lab._malformed_cases


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
E2E_TAG = "q3e2e"                                  # 브라우저 한 바퀴가 만든 회차 · 매핑의 접두 — 끝에 지운다
E2E_PERIOD = ("1985-02-01", "1985-02-28")          # 다른 테스트와 겹치지 않는 해
E2E_W2_AC = ("/col/uploads", "/col/upload-history", "/col/customer-map",
             f"/col/collections?date_from={E2E_PERIOD[0]}&date_to={E2E_PERIOD[1]}", f"/col/receivables?asof={E2E_PERIOD[1]}",
             f"/col/aging?asof={E2E_PERIOD[1]}", "/col/shipment-vs-collection?ym_from=1984-09&ym_to=1985-02")
#: W3 — 경영진(ex)이 대시보드 8 + 데이터 질의. RPT-130 은 **키 없는 서버**에서 질의를 실제로 눌러 「AI 키가 설정되지 않았습니다」 가 화면에 보이는지 본다.
E2E_W3_EX = ("/rpt/orders", "/rpt/production", "/rpt/quality", "/rpt/inventory", "/rpt/shipment", "/rpt/collection",
             "/rpt/order-flow", "/rpt/summary", "/rpt/query")
E2E_QUESTION = "이번 달 거래처별 출하 수량 (예시)"
#: E2E 서버 — 키 빈 값(환경) + `urllib.request.urlopen` 차단(이중 안전장치) 뒤 uvicorn. 실제 OpenAI 호출은 일어날 수 없다.
_E2E_SERVER = r"""
import sys, urllib.request
def _blocked(*a, **k):
    raise RuntimeError("QA3 — 실제 OpenAI 호출 차단")
urllib.request.urlopen = _blocked
import uvicorn
uvicorn.run("lcomfine.app.main:app", host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
"""


def _e2e_xlsx(tmp_dir: Path) -> tuple[Path, str, str]:
    """지금 열 매핑의 열 이름으로 (예시) 수금현황 xlsx 를 임시 폴더에 쓴다 — (경로, 매핑할 ERP 코드, 미매핑 ERP 코드)."""
    cmap, fields, hdrs = col_map()
    code_e, code_u = f"{E2E_TAG}-E", f"{E2E_TAG}-U"
    rows = [col_row(fields, customer_code=code_e, txn_date="1985-02-05", sales_amount="1000", collected_amount="0", method="PM (예시)"),
            col_row(fields, customer_code=code_e, txn_date="1985-02-20", collected_amount="600", method="PM (예시)", bill_due_date="1985-03-15"),
            col_row(fields, customer_code=code_u, txn_date="1985-02-21", sales_amount="500")]
    path = tmp_dir / f"{E2E_TAG} 수금현황 (예시).xlsx"
    path.write_bytes(xlsx_bytes(hdrs, rows))
    return path, code_e, code_u


def _e2e_cleanup() -> None:
    from lcomfine.db import conn

    with conn.tx() as cur:
        cleanup_col(cur, E2E_TAG + "%")


def e2e(port: int = 8020) -> int:
    """앱을 port 에 띄우고(하위 프로세스) Playwright 로 1280 · 390 캡처 + 가로 스크롤 0 확인 → outputs/e2e/.
    W1 화면 5 + W2: 회계부(ac)가 COL-010 에서 (예시) 엑셀을 **실제로 올리고**(1280 = 1회차 · 390 = 2회차 교체) → COL-020 이력 →
    COL-030 매핑 등록(1280 에서 한 번) → COL-040 · 050 · 060 · 070, 영업부(sl)가 TRK-030 수금 칸. 만든 회차 · 매핑은 끝에 지운다."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("E2E  Playwright 없음 — `uv run --offline --with playwright python tools/check_security.py --e2e` (전역 설치 안 함)")
        return 1
    import tempfile
    import urllib.request

    from lcomfine.db import conn

    E2E_DIR.mkdir(parents=True, exist_ok=True)
    tmp_dir = Path(tempfile.mkdtemp(prefix="qa3-e2e-"))
    xlsx_path, code_e, _ = _e2e_xlsx(tmp_dir)
    cust = conn.q1("select id, customer_code from customer order by id limit 1")       # TRK-030 · 매핑 대상 (시드 거래처)
    if cust is None:
        print("E2E  거래처가 없다 — 시드를 먼저 돌린다")
        return 1
    server = subprocess.Popen([sys.executable, "-c", _E2E_SERVER, str(port)],
                              cwd=ROOT, env=dict(os.environ, PYTHONPATH=str(ROOT / "src"), LCOMFINE_OPENAI_API_KEY="", LCOMFINE_DOC_SSO_URL=""),
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
        plan = ([("admin", p) for p in E2E_PATHS] + [("sl", "/wo/requests"), ("sh", "/shp/orders"), ("pr", "/lot/backward")]
                + [("ac", p) for p in E2E_W2_AC] + [("sl", f"/trk/customers?customer={cust['id']}")]
                + [("ex", p) for p in E2E_W3_EX] + list(E2E_W4))
        with sync_playwright() as play:
            browser = play.chromium.launch()
            for width in E2E_WIDTHS:
                for account in sorted({a for a, _ in plan}, key=SEED_ACCOUNTS.index):
                    ctx = browser.new_context(viewport={"width": width, "height": 900})
                    page = ctx.new_page()
                    page.on("dialog", lambda d: d.accept())          # data-confirm (반영 · 삭제) 는 승인
                    page.goto(base + "/login")
                    page.fill("input[name=login_id]", account)
                    page.fill("input[name=password]", pw)
                    page.locator("#login-form button.btn-primary").click()
                    page.wait_for_load_state("networkidle")
                    for acc, path in plan:
                        if acc != account:
                            continue
                        action, want_text = "", ""
                        resp = page.goto(base + path)
                        page.wait_for_load_state("networkidle")
                        if account == "ac" and path == "/col/uploads":                       # COL-010 업로드 (apply)
                            action, want_text = "upload-apply", "반영했습니다"
                            page.fill("input[name=period_from]", E2E_PERIOD[0])
                            page.fill("input[name=period_to]", E2E_PERIOD[1])
                            page.set_input_files("input[name=file]", str(xlsx_path))
                            page.click("button[name=action][value=apply]")
                            page.wait_for_load_state("networkidle")
                        elif account == "ac" and path == "/col/customer-map" and width == E2E_WIDTHS[0]:   # COL-030 매핑 등록
                            action, want_text = "map-create", "매핑을 등록했습니다"
                            form = page.locator("form[method=post]").filter(has=page.locator("input[name=erp_code]"))
                            form.locator("input[name=erp_code]").fill(code_e)
                            form.locator("input[name=erp_name]").fill(f"{E2E_TAG} ERP 거래처 (예시)")
                            form.locator("select[name=customer_id]").select_option(str(cust["id"]))
                            form.locator("button[type=submit]").click()
                            page.wait_for_load_state("networkidle")
                        elif account == "ex" and path == "/rpt/query":                        # RPT-130 질의 실행 — 키 없는 서버 → 422 문장이 화면에
                            action, want_text = "query-nokey", "AI 키가 설정되지 않았습니다 — LCOMFINE_OPENAI_API_KEY"
                            page.fill("input[name=question]", E2E_QUESTION)
                            page.locator("form.search button[type=submit]").click()
                            page.wait_for_load_state("networkidle")
                        elif (account, path) in E2E_W4_WANT:                                   # W4 DOC — 화면 글자만 본다(SSO 진입은 누르지 않는다)
                            want_text = E2E_W4_WANT[(account, path)]
                        sw, iw = page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
                        clean = path.split("?")[0]
                        name = f"{account}{clean.replace('/', '_') if clean != '/' else '_home'}{'-' + action if action else ''}-{width}.png"
                        page.screenshot(path=str(E2E_DIR / name), full_page=True)
                        body = page.content()
                        ok = (resp is not None and resp.status == 200 and sw <= iw and "/login" not in page.url
                              and (not want_text or want_text in body))
                        fails += 0 if ok else 1
                        results.append({"account": account, "path": path, "action": action or None, "width": width,
                                        "status": resp.status if resp else None, "url": page.url.replace(base, ""),
                                        "scrollWidth": sw, "innerWidth": iw, "ok": ok, "file": name,
                                        **({"flash": want_text, "flash_seen": want_text in body} if want_text else {})})
                        print(f"E2E  {account} {path}{' [' + action + ']' if action else ''} @{width}  {'PASS' if ok else 'FAIL'}  "
                              f"status {resp.status if resp else '?'} · scrollWidth {sw} ≤ innerWidth {iw}"
                              f"{' · ' + want_text + (' 보임' if want_text in body else ' 안 보임') if want_text else ''} · {name}")
                    ctx.close()
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=10)
        _e2e_cleanup()
        left = conn.q1("select (select count(*) from erp_upload_batch where source_file ilike %s) as b, "
                       "(select count(*) from erp_customer_map where erp_code ilike %s) as m", (E2E_TAG + "%", E2E_TAG + "%"))
        print(f"E2E  정리 — 남은 {E2E_TAG} 회차 {left['b']} · 매핑 {left['m']}")
        # W3 — 키 없는 서버에서 ex 가 누른 질의의 로그(data_query_log · sys_ai_call_log · 둘 다 ok=false)는 남긴다(감사 로그 · 시드 계정 행).
        dq = conn.q1("select count(*) as n, bool_and(not ok) as all_fail from data_query_log where question = %s", (E2E_QUESTION,))
        print(f"E2E  RPT-130 키 없음 질의 로그 — data_query_log {dq['n']}행 · 전부 ok=false {dq['all_fail']}")
    (E2E_DIR / "result.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    return fails


# ── W2 수금 (COL) ───────────────────────────────────────────────────────
# 회차는 1985년 기준 기간(개발3 테스트 1990~1993 · QA2 는 자기 접두와 겹치지 않는다) · 파일 이름 · 거래처 · ERP 코드는 전부 `q3<난수>` 접두.
# 열 매핑(`erp_column_map`)은 전역 설정이라 **바꾸지 않는다** — 지금 저장된 매핑의 열 이름으로 (예시) xlsx 를 만든다.
COL_PERIOD = (date(1985, 1, 1), date(1985, 1, 31))          # G-22 표본
COL_PERIOD_ABUSE = (date(1985, 3, 1), date(1985, 3, 31))    # X-05~X-07
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_COL_WRITE_PATTERNS = (r"\bopen\(", r"\.write\(", r"\bPath\(", r"\bos\.", r"\bshutil\b", r"\btempfile\b", r"NamedTemporaryFile",
                       r"\.save\((?!buf\))")


def cleanup_col(cur, like: str) -> None:
    """이 Lab 이 만든 수금 회차 · 행 · 알림 · 거래처 매핑을 지운다(사용자 login_id · 파일 이름 · ERP 코드가 접두로 시작하는 것)."""
    from lcomfine.app import erp_upload

    cur.execute("select id from erp_upload_batch where created_by ilike %s or source_file ilike %s", (like, like))
    ids = [r["id"] for r in cur.fetchall()]
    if ids:
        cur.execute("delete from notification where link = any(%s)", ([erp_upload.error_link(i) for i in ids],))
        cur.execute("delete from erp_upload_row where batch_id = any(%s)", (ids,))
        cur.execute("delete from erp_upload_batch where id = any(%s)", (ids,))     # replaced_by FK 는 문장 끝에 검사된다
    cur.execute("delete from erp_customer_map where erp_code ilike %s or customer_id in (select id from customer where customer_code ilike %s)",
                (like, like))


def col_map() -> tuple[dict[str, str], list[str], list[str]]:
    """지금 저장된 열 매핑 — (항목→열 이름, 매핑된 항목 순서, 그 열 이름). 필수 매핑이 없으면 UploadError 로 검사가 FAIL 한다."""
    from lcomfine.app import erp_upload

    cmap = erp_upload.column_map()
    erp_upload.check_map(cmap)
    fields = [f for f in erp_upload.FIELDS if cmap.get(f)]
    return cmap, fields, [cmap[f] for f in fields]


def col_row(fields: list[str], **vals) -> list:
    return [vals.get(f) for f in fields]


def xlsx_bytes(headers: list, rows: list[list], *, text_formulas: bool = True) -> bytes:
    """(예시) xlsx — 저장소에 바이너리를 두지 않는다. `=` 로 시작하는 글자는 기본으로 **글자 셀**(ERP 가 값으로 내려준 꼴)로 쓴다.
    text_formulas=False 면 openpyxl 기본대로 수식 셀이 된다(캐시 값 없음)."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for r in rows:
        ws.append(r)
    if text_formulas:
        for row in ws.iter_rows(min_row=2):
            for c in row:
                if isinstance(c.value, str) and c.value.startswith("="):
                    c.data_type = "s"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def col_post(client, period: tuple[date, date], data: bytes, *, action: str = "apply", name: str = "q3 erp (예시).xlsx",
             extra: dict | None = None, headers: dict | None = None):
    form = {"action": action, "period_from": period[0].isoformat(), "period_to": period[1].isoformat(), **(extra or {})}
    return client.post("/col/uploads", data=form, files={"file": (name, data, XLSX_MIME)}, headers=headers or {})


def _counts() -> tuple[int, int, int]:
    from lcomfine.db import conn

    r = conn.q1("select (select count(*) from erp_upload_batch) as b, (select count(*) from erp_upload_row) as r, "
                "(select count(*) from notification) as n")
    return r["b"], r["r"], r["n"]


def check_col_access(lab: Lab) -> list[Result]:
    """COL 화면 7 × 부서 8 — 칸 있으면 200 · 없으면 403 · R 칸에는 쓰기 폼이 없다. COL 쓰기 4 × 부서 8 — W 아닌 부서는 403."""
    from lcomfine.app import contracts, nav, rbac

    cells = {(sid, rc): lv for sid, rc, lv in contracts.permission_cells()}
    screens = [sc for sc in nav.SCREENS if sc.screen_id.startswith("COL-")]
    fns = [f for f in write_functions_routed() if f.id.startswith("F-COL-")]
    bad, n200, n403, forms = [], 0, 0, 0
    for r in rbac.roles():
        c = lab.client(r.code)
        for sc in screens:
            lv = cells.get((sc.screen_id, r.code))
            want = 200 if lv else 403
            got = c.get(sc.path).status_code
            if want == 200:
                n200 += 1
            else:
                n403 += 1
            if got != want:
                bad.append(f"{sc.screen_id}×{r.code} {got} ({want} 기대)")
            if lv == "R" and sc.screen_id in ("COL-010", "COL-030"):
                forms += 1
                html = c.get(sc.path, headers={"accept": "text/html"}).text
                if 'enctype="multipart/form-data"' in html or 'name="action" value="map"' in html or 'name="erp_code"' in html:
                    bad.append(f"{sc.screen_id}×{r.code} R 칸인데 쓰기 폼이 보인다")
    out = [res("G-19", "COL 화면 7 × 부서 8 (200/403 · R 칸 쓰기 폼 없음)", not bad,
               f"화면 {len(screens)} × 부서 {len(rbac.roles())} — 200 기대 {n200} · 403 기대 {n403} · R 칸 폼 검사 {forms} · 어긋남 {len(bad)}", bad)]
    bad2, n403w, nw = [], 0, 0
    for f in fns:
        for r in rbac.roles():
            got = lab.client(r.code).post(concrete(f.path), data={}).status_code
            if r.code not in f.roles_w:
                n403w += 1
                if got != 403:
                    bad2.append(f"{f.id}×{r.code} {got} (403 기대)")
            else:
                nw += 1
                if got in (401, 403) or got >= 500:
                    bad2.append(f"{f.id}×{r.code} {got} (W 칸 — 403/401/5xx 아님 기대)")
    out.append(res("G-19", "COL 쓰기 4 × 부서 8 (R·없음 403)", not bad2 and len(fns) == 4,
                   f"쓰기 기능 {len(fns)} × 부서 8 — 403 기대 {n403w} · 통과 기대 {nw} (빈 본문 → 422/404) · 어긋남 {len(bad2)}", bad2))
    return out


def check_col_sessions(lab: Lab) -> Result:
    """회계부 세션 — 비활성(F-SYS-013) 다음 요청부터 COL GET · POST 401 · 로그아웃 뒤 같은 쿠키 COL 401."""
    admin = lab.client("ADM")
    lid, pw, uid = lab.make_user("AC", "cac")
    c = login(lid, pw)
    a = c.get("/col/uploads").status_code
    deact = admin.post(f"/sys/users/{uid}/delete").status_code
    b, bp = c.get("/col/collections").status_code, c.post("/col/customer-map", data={}).status_code
    lid2, pw2, _ = lab.make_user("AC", "cac2")
    c2 = login(lid2, pw2)
    a2 = c2.get("/col/customer-map").status_code
    c2.post("/logout", follow_redirects=False)
    d, dp = c2.get("/col/uploads").status_code, c2.post("/col/uploads", data={"action": "preview"}).status_code
    got = (a, deact, b, bp, a2, d, dp)
    return res("G-20", "COL 비활성 · 로그아웃 → 401", got == (200, 200, 401, 401, 200, 401, 401),
               f"AC 전 {a} · 비활성 {deact} → COL-040 GET {b} · 매핑 POST {bp} / 다른 AC 전 {a2} · 로그아웃 → COL-010 GET {d} · 업로드 POST {dp}")


def check_col_change_log(lab: Lab) -> list[Result]:
    """COL 쓰기 4(업로드 apply · 매핑 등록 · 수정 · 삭제) + 열 매핑 저장 → 쓰기 성공마다 sys_change_log 1행 · preview · 422 · 403 · 404 는 0행."""
    from lcomfine.app import contracts, erp_upload
    from lcomfine.db import conn

    p = lab.prefix
    ac, ac_lid = lab.client("AC"), lab.users["AC"][0]
    cmap, fields, hdrs = col_map()
    cu = conn.q1("insert into customer (customer_code, customer_name, created_by) values (%s, %s, 'qa3') returning id",
                 (f"{p}cc", f"{p} 거래처 (예시)"))["id"]
    code_e, code_x = f"{p}E", f"{p}X"
    rows1 = [col_row(fields, customer_code=code_e, txn_date="1985-01-05", sales_amount="1000", collected_amount="0", method="PM (예시)"),
             col_row(fields, customer_code=code_e, txn_date="1985-01-20", collected_amount="600", method="PM (예시)"),
             col_row(fields, customer_code=code_e, txn_date="1985/13/01", sales_amount="1")]          # 날짜 형식 오류
    rows2 = rows1 + [col_row(fields, customer_code=code_e, txn_date="1985-01-25", collected_amount="100")]   # 날짜 오류 행은 그대로
    ctx: dict = {}
    map_before = erp_upload.column_map()

    def c_map():
        return ac.post("/col/uploads", data={"action": "map", **{f"map_{f}": c for f, c in map_before.items()}})

    def c_apply(rows, name):
        return col_post(ac, COL_PERIOD, xlsx_bytes(hdrs, rows), name=name)

    cases = [
        ("열 매핑 저장(같은 값)", "F-COL-011", "/col/uploads", c_map),
        ("업로드 apply 1회차", "F-COL-011", "/col/uploads", lambda: c_apply(rows1, f"{p} 1회차 (예시).xlsx")),
        ("업로드 apply 2회차(교체)", "F-COL-011", "/col/uploads", lambda: c_apply(rows2, f"{p} 2회차 (예시).xlsx")),
        ("매핑 등록(참조 있음)", "F-COL-031", "/col/customer-map",
         lambda: ac.post("/col/customer-map", data={"erp_code": code_e, "erp_name": f"{p} ERP (예시)", "customer_id": str(cu)})),
        ("매핑 등록(참조 없음)", "F-COL-031", "/col/customer-map",
         lambda: ac.post("/col/customer-map", data={"erp_code": code_x, "customer_id": str(cu)})),
        ("매핑 수정", "F-COL-032", lambda: f"/col/customer-map/{ctx['map_e']}",
         lambda: ac.post(f"/col/customer-map/{ctx['map_e']}", data={"erp_name": f"{p} ERP 수정 (예시)", "customer_id": str(cu), "use_yn": "Y"})),
        ("매핑 삭제(참조 → 사용 중지)", "F-COL-033", lambda: f"/col/customer-map/{ctx['map_e']}/delete",
         lambda: ac.post(f"/col/customer-map/{ctx['map_e']}/delete")),
        ("매핑 삭제(참조 없음 → 삭제)", "F-COL-033", lambda: f"/col/customer-map/{ctx['map_x']}/delete",
         lambda: ac.post(f"/col/customer-map/{ctx['map_x']}/delete")),
    ]
    bad, logs, notes = [], [], []
    for label, fid, path, call in cases:
        path = path() if callable(path) else path
        fn = contracts.function(fid)
        since = _max_change_id()
        r = call()
        rows = _changes_since(since, ac_lid)
        if r.status_code != 200:
            bad.append(f"{label} {r.status_code} {r.text[:120]}")
            continue
        data = r.json()
        if label == "업로드 apply 1회차":
            ctx["b1"] = data["id"]
            if (data["rows"], data["errors"], data["round_no"], data["replaced"]) != (3, 3, 1, None):
                bad.append(f"{label} 응답 {data}")
            notes_ac = conn.q("select to_role, handled_at from notification where link = %s", (erp_upload.error_link(data["id"]),))
            if [n["to_role"] for n in notes_ac] != ["AC"]:
                bad.append(f"{label} erp_upload_error 알림 {notes_ac} (AC 1행 기대)")
        if label == "업로드 apply 2회차(교체)":
            ctx["b2"] = data["id"]
            b1 = conn.q1("select status, replaced_by from erp_upload_batch where id = %s", (ctx["b1"],))
            if (data["rows"], data["errors"], data["round_no"]) != (4, 4, 2) or b1["status"] != "교체" or b1["replaced_by"] != data["id"]:
                bad.append(f"{label} 교체 안 됨 — 응답 {data} · 1회차 {b1}")
        if label == "매핑 등록(참조 있음)":
            ctx["map_e"] = data["id"]
            ec = conn.q1("select error_count from erp_upload_batch where id = %s", (ctx["b2"],))["error_count"]
            if data["remapped"] < 1 or ec != 1:
                bad.append(f"{label} 재해석 {data['remapped']} · 2회차 error_count {ec} (1 기대 — 날짜 오류 행만)")
        if label == "매핑 등록(참조 없음)":
            ctx["map_x"] = data["id"]
        if label == "매핑 삭제(참조 → 사용 중지)":
            m = conn.q1("select use_yn from erp_customer_map where id = %s", (ctx["map_e"],))
            if not data.get("disabled") or not m or m["use_yn"] != "N":
                bad.append(f"{label} 사용 중지 아님 — 응답 {data} · 행 {m}")
        if label == "매핑 삭제(참조 없음 → 삭제)":
            if data.get("disabled") or conn.q1("select 1 from erp_customer_map where id = %s", (ctx["map_x"],)):
                bad.append(f"{label} 지워지지 않음 — 응답 {data}")
        if label == "열 매핑 저장(같은 값)" and erp_upload.column_map() != map_before:
            bad.append("열 매핑 저장(같은 값) 이 매핑을 바꿨다")
        if len(rows) != 1:
            bad.append(f"{label} 변경 로그 {len(rows)}행 (1 기대)")
            continue
        rw = rows[0]
        if (rw["function_id"], rw["screen_id"], rw["method"], rw["path"]) != (fid, fn.screen_id, "POST", path) or not rw["target"]:
            bad.append(f"{label} 로그 값 {rw}")
        logs.append(rw["target"])
    out = [res("G-22", "COL 쓰기 성공 → sys_change_log 1행", not bad, f"쓰기 표본 {len(cases)} (기능 4 · 업로드 apply 2 · map 1) · 어긋남 {len(bad)}", bad)]
    # 쓰지 않는 요청 — preview 200 · 422 · 403 · 404 → 로그 0행 · 회차/행/알림 수 불변
    bad2 = []
    sl = lab.client("SL")
    neg = [
        ("AC preview", lambda: col_post(ac, COL_PERIOD, xlsx_bytes(hdrs, rows2), action="preview"), (200,)),
        ("AC preview(HTML)", lambda: col_post(ac, COL_PERIOD, xlsx_bytes(hdrs, rows2), action="preview", headers={"accept": "text/html"}), (200,)),
        ("AC apply 파일 없음", lambda: ac.post("/col/uploads", data={"action": "apply", "period_from": "1985-01-01", "period_to": "1985-01-31"}), (422,)),
        ("AC apply 텍스트 파일", lambda: col_post(ac, COL_PERIOD, b"not,an,xlsx\n"), (422,)),
        ("AC apply 헤더만", lambda: col_post(ac, COL_PERIOD, xlsx_bytes(hdrs, [])), (422,)),
        ("AC map 필수 빠짐", lambda: ac.post("/col/uploads", data={"action": "map", "map_txn_date": "x"}), (422,)),
        ("AC 매핑 중복(사용 중지된 코드)", lambda: ac.post("/col/customer-map", data={"erp_code": code_e, "customer_id": str(cu)}), (422,)),
        ("AC 매핑 수정 없는 id", lambda: ac.post("/col/customer-map/999999999", data={"customer_id": str(cu)}), (404,)),
        ("SL(R) apply", lambda: col_post(sl, COL_PERIOD, xlsx_bytes(hdrs, rows2)), (403,)),
        ("SL(R) 매핑 등록", lambda: sl.post("/col/customer-map", data={"erp_code": f"{p}SL", "customer_id": str(cu)}), (403,)),
    ]
    for label, call, want in neg:
        role_lid = lab.users["SL"][0] if label.startswith("SL") else ac_lid
        since, before = _max_change_id(), _counts()
        got = call().status_code
        n, after = len(_changes_since(since, role_lid)), _counts()
        if got not in want or n or after != before:
            bad2.append(f"{label} → {got} (기대 {'/'.join(map(str, want))}) · 로그 {n}행 · 회차/행/알림 {before}→{after}")
    if erp_upload.column_map() != map_before:
        bad2.append("음성 표본이 열 매핑을 바꿨다")
    out.append(res("G-22", "COL preview · 422 · 403 · 404 → 0행 · 회차/행/알림 불변", not bad2, f"표본 {len(neg)} · 어긋남 {len(bad2)}", bad2))
    page = lab.client("ADM").get("/sys/logs", params={"tab": "change", "login": ac_lid}).text
    seen = [t for t in logs if t in page]
    out.append(res("G-22", "COL 변경 로그 SYS-040 에서 조회", bool(logs) and len(seen) == len(logs),
                   f"변경 로그 {len(logs)} 중 SYS-040 에 보인 것 {len(seen)}", [t for t in logs if t not in page]))
    return out


def _zip_not_xlsx() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("a.txt", "q3 (예시)")
    return buf.getvalue()


def check_col_upload_abuse(lab: Lab) -> list[Result]:
    """업로드 보안 — 엑셀 아닌 파일 · 빈 파일 · 20MB 초과 · 헤더 결함 → 422(500 0) · 셀의 수식/스크립트/긴 글자는 값으로만 저장되고
    화면에 이스케이프돼 나온다 · 내려받는 엑셀(COL-040)에 수식으로 되살아나지 않는다 · 파일 이름의 경로는 글자로만 저장된다."""
    from lcomfine.db import conn
    from openpyxl import load_workbook

    cached = getattr(lab, "_col_abuse", None)
    if cached is not None:        # 같은 Lab 에서 여러 테스트가 부른다 — 거래처 · 매핑 · 회차를 두 번 만들지 않는다
        return cached
    lab._col_abuse = out = _check_col_upload_abuse(lab, conn, load_workbook)
    return out


def _check_col_upload_abuse(lab: Lab, conn, load_workbook) -> list[Result]:
    p = lab.prefix
    ac = lab.client("AC")
    P = COL_PERIOD_ABUSE
    cmap, fields, hdrs = col_map()
    good = [col_row(fields, customer_code=f"{p}M", txn_date="1985-03-05", collected_amount="1")]
    out: list[Result] = []
    # 1. 파일 수준
    files = [
        ("텍스트(csv)", b"a,b\n1,2\n"), ("HTML", b"<html><body><script>alert(1)</script></body></html>"),
        ("zip(엑셀 아님)", _zip_not_xlsx()), ("0 바이트", b""), ("PNG 머리", b"\x89PNG\r\n\x1a\n" + b"\x00" * 64),
        ("20MB+1", b"\x00" * (erp_upload_max_bytes() + 1)),
        ("헤더만", xlsx_bytes(hdrs, [])), ("열 이름 중복", xlsx_bytes(hdrs + [hdrs[0]], [good[0] + ["x"]])),
        ("1행(열 이름) 비어 있음", xlsx_bytes([None] * len(hdrs), good)), ("__row_no 열", xlsx_bytes(hdrs + ["__row_no"], [good[0] + ["1"]])),
        ("매핑된 열이 파일에 없음", xlsx_bytes([f"q3없는열{i}" for i in range(len(hdrs))], good)),
        # W4 에 더함(DEF-QA3-009) — openpyxl 이 쓸 수 없는 시트 XML: 날 NUL · 닫는 태그 없음 · XML 아님 (read_only 는 행을 읽을 때 ParseError)
        ("날 NUL 이 든 시트 XML", _xlsx_patch(xlsx_bytes(hdrs, good), f"{p}M".encode(), f"{p}\x00M".encode())),
        ("깨진 시트 XML(닫는 태그 없음)", _xlsx_patch(xlsx_bytes(hdrs, good), b"</sheetData>", b"")),
        ("시트 XML 이 XML 아님", _xlsx_patch(xlsx_bytes(hdrs, good), b"<sheetData>", b"<sheetData><<<")),
    ]
    bad, statuses = [], []
    for label, data in files:
        r = col_post(ac, P, data, name=f"{p} {label} (예시).xlsx")
        statuses.append(f"{label} {r.status_code}")
        if r.status_code != 422:
            bad.append(f"{label} {r.status_code} (422 기대){' — 500!' if r.status_code >= 500 else ''} {r.text[:100]}")
        elif not r.json().get("fields"):
            bad.append(f"{label} 422 인데 fields 없음")
    for label, extra in (("기준 기간 NUL", {"period_from": "1985-03-01\x00"}), ("기준 기간 99999년", {"period_to": "99999-03-31"}),
                         ("동작 NUL", {"action": "apply\x00"})):
        r = col_post(ac, P, xlsx_bytes(hdrs, good), extra=extra)
        statuses.append(f"{label} {r.status_code}")
        if r.status_code != 422:
            bad.append(f"{label} {r.status_code} (422 기대)")
    out.append(res("X-05", "업로드: 엑셀 아닌 파일 · 빈 파일 · 20MB 초과 · 헤더 결함 → 422", not bad,
                   f"파일 {len(files)} + 폼 3 — 500 {sum(1 for s in statuses if s.endswith(('500', '502', '503')))} · 어긋남 {len(bad)}", bad))
    # 2. 셀 내용 — 수식 글자 · 스크립트 · 10만 자 · NUL 이스케이프 · 파일 이름 경로. 거래처 코드 {p}M 은 매핑해 COL-040 까지 흐르게 한다
    cu = conn.q1("insert into customer (customer_code, customer_name, created_by) values (%s, %s, 'qa3') returning id",
                 (f"{p}cx", f"{p} 거래처 X (예시)"))["id"]
    r = ac.post("/col/customer-map", data={"erp_code": f"{p}M", "erp_name": "<i>q3</i> (예시)", "customer_id": str(cu)})
    bad2 = []
    if r.status_code != 200:
        bad2.append(f"매핑 등록 {r.status_code}")
    evil_code = f"{p}<script>alert(1)</script>"
    hyper = '=HYPERLINK("http://evil.example/q3","클릭")'
    dde = "=CMD|' /C calc'!A0"
    big = "가" * 100_000
    rows = [col_row(fields, customer_code=evil_code, txn_date="1985-03-05", collected_amount="1", method=hyper),
            col_row(fields, customer_code=f"{p}M", txn_date="1985-03-06", collected_amount="2", method=dde),
            col_row(fields, customer_code=f"{p}M", txn_date="1985-03-07", collected_amount="3", method=hyper),
            col_row(fields, customer_code=f"{p}M", txn_date="1985-03-08", collected_amount="4", method=big),
            col_row(fields, customer_code=f"{p}M", txn_date="1985-03-09", collected_amount="5", method="a_x0000_b"),
            col_row(fields, customer_code=f"{p}M", txn_date="1985-03-10", collected_amount="6", method="<img src=x onerror=alert(1)>")]
    fname = f"../../../etc/{p}<b>passwd</b>.xlsx"
    r = col_post(ac, P, xlsx_bytes(hdrs, rows), name=fname)
    if r.status_code != 200:
        bad2.append(f"셀 내용 업로드 {r.status_code} {r.text[:160]}")
        out.append(res("X-06", "셀의 수식·스크립트·긴 글자 → 값으로 저장 · 화면 이스케이프", False, "업로드 실패", bad2))
        return out
    bid = r.json()["id"]
    b = conn.q1("select source_file, row_count, error_count from erp_upload_batch where id = %s", (bid,))
    if b["source_file"] != fname[:200]:
        bad2.append(f"source_file 저장 값 {b['source_file']!r} (올린 이름 그대로 기대)")
    if (b["row_count"], b["error_count"]) != (6, 1):
        bad2.append(f"행 {b['row_count']} · 오류 {b['error_count']} (6 · 1 기대 — 미매핑 코드 1행만)")
    stored = {r_["row_no"]: r_ for r_ in conn.q("select row_no, raw, parsed, error from erp_upload_row where batch_id = %s", (bid,))}
    mcol = cmap.get("method")
    if mcol:
        if stored[3]["raw"].get(mcol) != dde or stored[3]["parsed"].get("method") != dde:
            bad2.append(f"DDE 글자가 그대로 저장되지 않음 raw={stored[3]['raw'].get(mcol)!r}")
        # 엑셀 셀 상한은 32,767자 — openpyxl 이 쓴 파일에 든 길이 그대로 raw 에 보존되고 parsed 는 200자로 잘린다
        raw_len = len(stored[5]["raw"].get(mcol) or "")
        if raw_len < 32_767 or len(stored[5]["parsed"].get("method") or "") != 200:
            bad2.append(f"10만 자 — raw {raw_len} · parsed {len(stored[5]['parsed'].get('method') or '')} (≥32767 · 200 기대)")
    if stored[2]["error"] is None or evil_code not in (stored[2]["error"] or ""):
        bad2.append(f"<script> 거래처 코드 행이 미매핑 오류가 아님 {stored[2]['error']!r}")
    pages = {
        "COL-010 ?batch": ac.get("/col/uploads", params={"batch": str(bid)}, headers={"accept": "text/html"}),
        "COL-020 ?batch": ac.get("/col/upload-history", params={"batch": str(bid)}, headers={"accept": "text/html"}),
        "COL-030": ac.get("/col/customer-map", headers={"accept": "text/html"}),
        "COL-040": ac.get("/col/collections", params={"date_from": "1985-03-01", "date_to": "1985-03-31", "customer": str(cu)},
                          headers={"accept": "text/html"}),
        "HOME": ac.get("/", headers={"accept": "text/html"}),
    }
    escaped_seen = 0
    for name, pg in pages.items():
        if pg.status_code != 200:
            bad2.append(f"{name} {pg.status_code}")
            continue
        html = pg.text
        if "<script>alert(1)</script>" in html or "<img src=x onerror" in html or 'href="http://evil.example' in html or "<b>passwd</b>" in html:
            bad2.append(f"{name}: 저장된 글자가 이스케이프 없이 렌더됨")
        if "&lt;script&gt;alert(1)&lt;/script&gt;" in html or "&lt;img src=x" in html or "&lt;b&gt;passwd" in html:
            escaped_seen += 1
    if not escaped_seen:
        bad2.append("어느 화면에도 이스케이프된 글자가 보이지 않는다(저장 글자가 화면에 안 나왔다 — 검사가 비었다)")
    out.append(res("X-06", "셀의 수식·스크립트·10만 자·파일 이름 경로 → 값으로만 저장 · 화면 이스케이프", not bad2,
                   f"행 6 · 화면 {len(pages)} · 이스케이프 확인 화면 {escaped_seen} · source_file 글자 보존 · 10만 자 셀 raw {len(stored[5]['raw'].get(mcol) or '') if mcol else '-'}자(엑셀 상한 32767) · 어긋남 {len(bad2)}", bad2))
    # 3. 내려받는 엑셀(COL-040 ?format=xlsx) — 저장된 `=…` 글자가 수식 셀로 되살아나면 수식 주입(DDE · HYPERLINK)
    bad3 = []
    x = ac.get("/col/collections", params={"date_from": "1985-03-01", "date_to": "1985-03-31", "customer": str(cu), "format": "xlsx"})
    if x.status_code != 200 or not x.headers.get("content-type", "").startswith(XLSX_MIME):
        bad3.append(f"xlsx 내려받기 {x.status_code} {x.headers.get('content-type')}")
    else:
        wb = load_workbook(io.BytesIO(x.content))
        formulas = [(c.coordinate, str(c.value)[:40]) for row in wb.active.iter_rows() for c in row if c.data_type == "f"]
        if formulas:
            bad3.append(f"수식 셀 {len(formulas)}: " + " · ".join(f"{k}={v}" for k, v in formulas[:3]))
    out.append(res("X-07", "COL-040 엑셀 내려받기 — 저장된 `=…` 글자가 수식 셀로 되살아나지 않는다", not bad3,
                   "수식 셀 0" if not bad3 else "DDE · HYPERLINK 글자가 수식 셀(data_type f)로 쓰였다 — 여는 사람의 엑셀에서 실행될 수 있다", bad3))
    # 4. 진짜 수식 셀(캐시 값 없음)은 빈 칸으로 읽힌다 — preview 로 쓰지 않고 확인 (참고)
    pv = col_post(ac, P, xlsx_bytes(hdrs, [col_row(fields, customer_code=f"{p}M", txn_date="1985-03-11", collected_amount="=1+1")],
                                     text_formulas=False), action="preview")
    if pv.status_code == 200:
        item = pv.json()["items"][0]
        print(f"참고 (X-06): 진짜 수식 셀 `=1+1`(캐시 값 없음)은 수금액 {item['parsed'].get('collected_amount')!r} 로 읽힌다 · error {item['error']!r}"
              " — 값이 아닌 수식은 빈 칸(조용히 0 이 되지는 않는다)")
    return out


def erp_upload_max_bytes() -> int:
    from lcomfine.app import erp_upload

    return erp_upload.MAX_BYTES


def check_col_static() -> list[Result]:
    """정적 — 업로드 모듈 · 라우터가 파일을 디스크에 쓰지 않는다(open · write · Path · tempfile 0) · 쓰기 4 전부 require_fn + log_change."""
    hits = []
    for rel in ("src/lcomfine/app/erp_upload.py", "src/lcomfine/app/routers/col.py"):
        for i, ln in enumerate((ROOT / rel).read_text(encoding="utf-8").splitlines(), 1):
            if ln.strip().startswith("#"):
                continue
            for pat in _COL_WRITE_PATTERNS:
                if re.search(pat, ln):
                    hits.append(f"{rel}:{i} {ln.strip()[:60]}")
    return [res("X-08", "정적: 업로드 파일을 디스크에 쓰지 않는다", not hits,
                f"erp_upload.py · col.py 의 open/write/Path/os./tempfile {len(hits)} (wb.save(buf) BytesIO 만 허용)", hits)]


def check_seed_dev3_static() -> Result:
    """seed_dev3.py — `on conflict … do nothing`(멱등) · 지우는 문장 없음 · created_by 'seed'. 실측(2회 실행 diff 0)은 gate-full 이 잰다."""
    from lcomfine.db import conn

    src = (ROOT / "src/lcomfine/db/seed_dev3.py").read_text(encoding="utf-8")
    body = "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith("#"))
    idem = "on conflict (field) do nothing" in body
    destructive = bool(re.search(r"\b(delete|truncate|drop)\b", body, re.I))
    seeded = conn.q1("select count(*) as n from erp_column_map where created_by = 'seed'")["n"]
    ex = "(예시)" in src
    ok = idem and not destructive and "SEEDED_BY = \"seed\"" in body
    return res("G-21", "seed_dev3 멱등 · (예시) (정적)", ok,
               f"on conflict do nothing {'있음' if idem else '없음'} · delete/truncate {'있음' if destructive else '없음'} · "
               f"erp_column_map(created_by=seed) {seeded}행 · 열 이름은 정본 낱말이라 (예시) 표식 없음(문서에만 — D-802) · 실측 멱등은 gate-full")


# ── W3 대시보드 · 데이터 질의 (RPT) ─────────────────────────────────────
# AI 는 **절대 실제로 부르지 않는다** — `ai.set_client(fake)` 로 SQL 을 내가 정해 넣고, `no_real_ai()` 가 ai.py 가 쓰는 `urllib.request.urlopen` 을
# 막아 둔다(막힌 호출이 있으면 422 「AI 호출 실패 — _NoNetwork」 로 드러나 FAIL). 키 없음은 ① 프로세스 안에서 `ai._config` 를 비우고 ② 하위
# 프로세스 `LCOMFINE_OPENAI_API_KEY=`(빈 값 · settings 실제 경로)로 잰다. 키 값은 어디에도 찍지 않는다(응답 · 로그에 실리지 않는 것만 센다).
RPT_SCREENS = ("RPT-010", "RPT-020", "RPT-030", "RPT-040", "RPT-050", "RPT-060", "RPT-070", "RPT-080", "RPT-130")
QUERY_PATH = "/rpt/query"
#: 질의 · 호출 · 변경 · 조회 로그와 채번 — 업무 테이블 diff 에서 뺀다(데이터 질의가 써도 되는 것 · D-513)
LOG_TABLES = ("data_query_log", "sys_ai_call_log", "sys_access_log", "sys_change_log", "sys_number_seq")
_NBSP, _ZWSP = " ", "​"


class _NoNetwork(RuntimeError):
    """QA3 — 실제 OpenAI 호출 차단. 이 예외가 응답에 보이면 검사가 바깥으로 나가려 한 것이다(= FAIL)."""


@contextmanager
def no_real_ai():
    """ai.py 의 바깥 호출을 막고 `_config` · `_openai` · 주입 클라이언트를 끝에 원래대로 돌린다."""
    import urllib.request as _ur

    from lcomfine.app import ai

    orig_open, orig_cfg, orig_openai = _ur.urlopen, ai._config, ai._openai

    def blocked(*a, **k):
        raise _NoNetwork("QA3 — 실제 OpenAI 호출 차단")

    _ur.urlopen = blocked          # ai.py 는 호출 시점에 urllib.request.urlopen 을 찾는다
    try:
        yield ai
    finally:
        _ur.urlopen = orig_open
        ai._config = orig_cfg
        ai._openai = orig_openai
        ai.set_client(None)


def _marks() -> dict:
    from lcomfine.db import conn

    return conn.q1("select (select coalesce(max(id), 0) from data_query_log) as dq, (select coalesce(max(id), 0) from sys_ai_call_log) as ai, "
                   "(select coalesce(max(id), 0) from sys_change_log) as ch")


def _logs_since(lab: Lab, m: dict) -> tuple[list[dict], list[dict], list[dict]]:
    """이 Lab 의 임시 계정이 남긴 새 행만 — (data_query_log, sys_ai_call_log, sys_change_log). 다른 QA 가 동시에 돌아도 섞이지 않는다."""
    from lcomfine.db import conn

    like = lab.prefix + "%"
    dq = conn.q("select d.* from data_query_log d join sys_user u on u.user_id = d.user_id where d.id > %s and u.login_id ilike %s order by d.id",
                (m["dq"], like))
    ai = conn.q("select a.* from sys_ai_call_log a join sys_user u on u.user_id = a.user_id where a.id > %s and u.login_id ilike %s order by a.id",
                (m["ai"], like))
    ch = conn.q("select * from sys_change_log where id > %s and login_id ilike %s order by id", (m["ch"], like))
    return dq, ai, ch


def _ask(lab: Lab, role: str, fake, question: str, *, html: bool = False):
    """fake(SQL 글자 · 호출형 · None=실제 경로) 를 주입하고 POST /rpt/query. → (응답, dq 새 행, ai 새 행, 변경 로그 새 행, 경과 ms)."""
    from lcomfine.app import ai

    if fake is None or callable(fake):
        ai.set_client(fake)
    else:
        ai.set_client(lambda m, s, u, _sql=fake: _sql)
    m = _marks()
    t0 = time.monotonic()
    headers = {"accept": "text/html", "referer": QUERY_PATH} if html else {}
    r = lab.client(role).post(QUERY_PATH, data={"question": question}, headers=headers, follow_redirects=False)
    ms = int((time.monotonic() - t0) * 1000)
    dq, ai_rows, ch = _logs_since(lab, m)
    return r, dq, ai_rows, ch, ms


def business_counts() -> dict[str, int]:
    from lcomfine.db import conn

    names = [r["tablename"] for r in conn.q("select tablename from pg_tables where schemaname = 'public' order by 1")]
    return {t: conn.q1(f"select count(*) as n from {t}")["n"] for t in names if t not in LOG_TABLES}


def _dq_fixture(lab: Lab) -> dict:
    """내 거래처 · 품목 · 생산의뢰 4(오늘 · v_dq_orders 에 보인다) + 이스케이프 시험용 `<script>` 거래처 1 — Lab 에 캐시 · cleanup 이 지운다."""
    from lcomfine.db import conn

    cached = getattr(lab, "_dq_fixture", None)
    if cached is not None:
        return cached
    p = lab.prefix
    cu = conn.q1("insert into customer (customer_code, customer_name, created_by) values (%s, %s, 'qa3') returning id",
                 (f"{p}dq", f"{p} 질의 거래처 (예시)"))["id"]
    xs = conn.q1("insert into customer (customer_code, customer_name, created_by) values (%s, %s, 'qa3') returning id",
                 (f"{p}xs", f"{p} <script>alert(1)</script> <img src=x onerror=alert(2)> (예시)"))["id"]
    it = conn.q1("insert into item (item_code, item_name, item_type, created_by) values (%s, %s, '제품', 'qa3') returning id",
                 (f"{p}dqi", f"{p} 질의 품목 (예시)"))["id"]
    for i in range(4):
        conn.x("insert into production_request (request_no, customer_id, item_id, qty, due_date, status, created_by) "
               "values (%s, %s, %s, %s, current_date + 7, '확인대기', 'qa3')", (f"{p}DQ{i}", cu, it, 10 + i))
    conn.x("insert into production_request (request_no, customer_id, item_id, qty, due_date, status, created_by) "
           "values (%s, %s, %s, 7, current_date + 7, '확인대기', 'qa3')", (f"{p}XS", xs, it))
    lab._dq_fixture = {"cu": cu, "xs": xs, "it": it, "code": f"{p}dq"}
    return lab._dq_fixture


def _dq_invariants(lab: Lab) -> dict:
    """우회 SQL 이 노리는 자리 — 내 거래처 행 · 내 의뢰 4 · 내 계정 수 · 주입 거래처 0 · customer 테이블 존재 · `{p}tmp` 테이블 없음."""
    from lcomfine.db import conn

    p = lab.prefix
    return conn.q1(
        """select (select count(*) from customer where customer_code = %s) as cu,
                  (select string_agg(r.request_no || ':' || r.qty::text, ',' order by r.request_no) from production_request r
                     join customer c on c.id = r.customer_id where c.customer_code = %s) as reqs,
                  (select count(*) from sys_user where login_id ilike %s) as users,
                  (select count(*) from customer where customer_code = %s) as injected,
                  (to_regclass('customer') is not null) as customer_table,
                  (to_regclass(%s) is null) as no_tmp_table""",
        (f"{p}dq", f"{p}dq", f"{p}%", f"{p}inj", f"{p}tmp"))


def bypass_cases(lab: Lab) -> list[tuple[str, str]]:
    """(라벨, fake 가 돌려줄 SQL) — 전부 422 「허용되지 않는 질의 — …」 · 실행 0 이어야 한다."""
    p = lab.prefix
    return [
        ("쓰기 update", "update customer set customer_name = 'q3' where customer_code = '%sdq'" % p),
        ("쓰기 delete", "delete from v_dq_orders"),
        ("쓰기 insert", f"insert into customer (customer_code, customer_name, created_by) values ('{p}inj', 'q3 (예시)', 'qa3')"),
        ("DDL drop", "drop table customer"),
        ("DDL truncate", "truncate customer"),
        ("다중 문장 ;", "select * from v_dq_orders; delete from customer"),
        ("다중 문장 주석 --", "select * from v_dq_orders -- ; delete from customer"),
        ("블록 주석 /* */", "select * from v_dq_orders /* x */"),
        ("허용 밖 뷰", "select * from v_work_order_status"),
        ("업무 테이블 직접", "select * from customer"),
        ("계정 테이블 직접", "select login_id, password_hash from sys_user"),
        ("카탈로그 pg_tables", "select * from pg_tables"),
        ("카탈로그 pg_catalog.", "select * from pg_catalog.pg_class"),
        ("카탈로그 information_schema", "select * from information_schema.tables"),
        ("함수 pg_sleep(10)", "select pg_sleep(10) from v_dq_orders"),
        ("함수 PG_SLEEP 대문자", "select PG_SLEEP(10) from v_dq_orders"),
        ("함수 pg_read_file", "select pg_read_file('/etc/passwd')"),
        ("함수 current_setting", "select current_setting('data_directory')"),
        ("함수 lo_import", "select lo_import('/etc/passwd')"),
        ("함수 query_to_xml", "select query_to_xml('select * from sys_user', true, false, '')"),
        ("함수 version()", "select version()"),
        ("함수 md5 (허용 밖)", "select md5(request_no) from v_dq_orders"),
        ("읽기 전용 확인 pg_is_in_recovery", "select pg_is_in_recovery()"),
        ("CTE with", "with x as (select * from v_dq_orders) select * from x"),
        ("select … into", f"select * into {p}tmp from v_dq_orders"),
        ("for update", "select * from v_dq_orders for update"),
        ("copy", "copy (select * from v_dq_orders) to '/tmp/q3'"),
        ("set", "set statement_timeout = 0"),
        ("show", "show data_directory"),
        ("explain", "explain select * from v_dq_orders"),
        ("백슬래시 \\copy", "\\copy v_dq_orders to '/tmp/q3'"),
        ("유니코드 공백 NBSP", f"select{_NBSP}*{_NBSP}from{_NBSP}customer"),
        ("유니코드 ZWSP 낱말 쪼개기", f"select * from cust{_ZWSP}omer"),
        ("유니코드 ZWSP select", f"sel{_ZWSP}ect * from v_dq_orders"),
        ("대소문자 혼합 테이블", "SeLeCt * FrOm CuStOmEr"),
        ("큰따옴표 식별자", 'select * from "customer"'),
        ("스키마 한정 허용 뷰", "select * from public.v_dq_orders"),
        ("스키마 한정 업무 테이블", "select * from public.customer"),
        ("union 으로 업무 테이블", "select request_no from v_dq_orders union all select customer_code from customer"),
        ("하위 질의 계정 테이블", "select (select count(*) from sys_user) from v_dq_orders"),
        ("exists 하위 질의", "select * from v_dq_orders where exists (select 1 from sys_user)"),
        ("join 업무 테이블", "select * from v_dq_orders o join customer c on true"),
        ("쉼표 조인 업무 테이블", "select * from v_dq_orders, customer"),
        ("cross join 계정 테이블", "select * from v_dq_orders cross join sys_user"),
        ("파생 테이블 안 업무 테이블", "select * from (select * from customer) x"),
        ("lateral", "select * from v_dq_orders o, lateral (select * from customer) c"),
        ("returning", "select * from v_dq_orders returning *"),
        ("달러 따옴표", "select $$x$$ from v_dq_orders"),
        ("닫히지 않은 문자열", "select * from v_dq_orders where status = 'open"),
        ("허용 뷰 없음 select 1", "select 1"),
        ("빈 SQL", ""),
        ("SQL 속 NUL", "select * from v_dq_orders\x00"),
        ("SQL 4001자", "select * from v_dq_orders where request_no = '" + "x" * 3960 + "'"),
        ("코드 펜스 속 쓰기", "```sql\ndelete from customer\n```"),
    ]


def check_dataquery_bypass(lab: Lab) -> list[Result]:
    """G-16 — fake AI 가 돌려주는 SQL 로 우회 시도 → 전부 422 「허용되지 않는 질의 — 이유」 · 실행 0 · 거부도 data_query_log 1행(ok false) ·
    허용 질의 200 · 행 상한 · statement_timeout · 읽기 전용 · 수금 뷰 부서 제한 · 질문의 NUL/10만 자/<script>."""
    from lcomfine.app import dataquery
    from lcomfine.db import conn

    fx = _dq_fixture(lab)
    out: list[Result] = []
    with no_real_ai():
        inv0 = _dq_invariants(lab)
        counts0 = business_counts()
        cases = bypass_cases(lab)
        bad, slow, sleep_ms, n422 = [], [], [0], 0
        for label, sql in cases:
            r, dq, ai_rows, ch, ms = _ask(lab, "EX", sql, f"q3 우회 {label}")
            want_sql = dataquery._strip_fence(sql)
            why = []
            if "sleep" in label.lower():
                sleep_ms.append(ms)
            if r.status_code != 422:
                why.append(f"{r.status_code} (422 기대)")
            else:
                n422 += 1
                body = r.json()
                if not str(body.get("message", "")).startswith(dataquery.REJECT_PREFIX + " — "):
                    why.append(f"message {body.get('message')!r}")
                names = [f["name"] for f in body.get("fields", [])]
                if "질의 번호" not in names or (want_sql and "SQL" not in names):
                    why.append(f"fields {names}")
                if "rows" in body or "columns" in body:
                    why.append("422 에 결과 열·행이 실렸다")
            if len(dq) != 1:
                why.append(f"data_query_log {len(dq)}행 (1 기대)")
            else:
                d = dq[0]
                if d["ok"] or (d["sql_text"] or "") != want_sql or not (d["error"] or "").startswith(dataquery.REJECT_PREFIX) \
                        or d["question"] != f"q3 우회 {label}" or d["role_code"] != "EX" or d["row_count"] is not None:
                    why.append(f"로그 값 ok={d['ok']} sql={d['sql_text']!r:.40} error={d['error']!r:.60} rows={d['row_count']}")
            if len(ai_rows) != 1 or not ai_rows[0]["ok"]:
                why.append(f"sys_ai_call_log {len(ai_rows)}행 / ok {[a['ok'] for a in ai_rows]} (fake 성공 1행 기대)")
            if ch:
                why.append(f"sys_change_log {len(ch)}행 (거부는 변경 아님 · 0 기대)")
            if "sleep" in label.lower() and ms > 3000:
                slow.append(f"{label} {ms}ms")
            if why:
                bad.append(f"{label}: " + " · ".join(why))
        inv1 = _dq_invariants(lab)
        if inv1 != inv0 or inv1["injected"] != 0 or not inv1["customer_table"] or not inv1["no_tmp_table"]:
            bad.append(f"대상 행이 바뀌었다 — 전 {inv0} 후 {inv1}")
        if slow:
            bad.append("pg_sleep 이 돌았다(3초 초과): " + " · ".join(slow))
        diff = {t: (counts0.get(t), n) for t, n in business_counts().items() if counts0.get(t) != n}
        out.append(res("G-16", "우회 SQL → 422 · 실행 0 · 거부도 로그 1행", not bad,
                       f"우회 {len(cases)}건(쓰기 5 · 다중 문장·주석 3 · 허용 밖 뷰/테이블/카탈로그 6 · 함수 9 · CTE·into·for·copy·set·show·explain·\\ 8 · "
                       f"유니코드 3 · 대소문자·따옴표·스키마 4 · 하위 질의·조인 8 · 그 밖 7) · 422 {n422} · "
                       f"내 행 불변 {inv1 == inv0} · pg_sleep 요청 최대 {max(sleep_ms)}ms · 업무 테이블 {len(counts0)} 전수 diff {len(diff)}"
                       f"{' ' + str(diff)[:120] if diff else ''}", bad))
        # 허용 질의 — 200 · 결과 · 로그 ok · 변경 로그 1행 (JSON) / 브라우저는 같은 화면 200 에 SQL · 결과 표 (api-contract §2 예외)
        bad2 = []
        good_sql = f"```sql\nSELECT request_no, qty FROM v_dq_orders WHERE customer_code = '{fx['code']}' ORDER BY request_no;\n```"
        r, dq, ai_rows, ch, _ = _ask(lab, "EX", good_sql, "q3 허용 질의 (예시)")
        if r.status_code != 200:
            bad2.append(f"허용 질의 {r.status_code} {r.text[:120]}")
        else:
            b = r.json()
            if not (b.get("ok") and b.get("row_count") == 4 and b.get("columns") == ["request_no", "qty"] and b.get("truncated") is False
                    and str(b.get("sql", "")).startswith("SELECT request_no") and str(b.get("query_no", "")).startswith("DQ-")):
                bad2.append(f"허용 질의 응답 {str(b)[:160]}")
            if len(dq) != 1 or not dq[0]["ok"] or dq[0]["row_count"] != 4 or dq[0]["sql_text"] != b.get("sql") or dq[0]["error"]:
                bad2.append(f"허용 질의 로그 {dq and {k: dq[0][k] for k in ('ok', 'row_count', 'error')}}")
            if len(ai_rows) != 1 or not ai_rows[0]["ok"] or ai_rows[0]["kind"] != dataquery.AI_KIND:
                bad2.append(f"허용 질의 ai 로그 {[(a['ok'], a['kind']) for a in ai_rows]}")
            if len(ch) != 1 or ch[0]["function_id"] != "F-RPT-132" or ch[0]["target"] != f"data_query_log:{b.get('query_no')}":
                bad2.append(f"허용 질의 변경 로그 {[(c['function_id'], c['target']) for c in ch]} (F-RPT-132 · data_query_log:<번호> 1행 기대)")
        r, dq, _, _, _ = _ask(lab, "ST", f"select * from v_dq_orders where customer_code = '{fx['code']}' and status <> 'a;b--'", "q3 리터럴 속 ; -- (예시)")
        if r.status_code != 200 or not dq or not dq[0]["ok"]:
            bad2.append(f"문자열 리터럴 속 ;-- 는 문장이 아니다 — {r.status_code} (200 기대)")
        r, dq, _, _, _ = _ask(lab, "ST", "select count(*) from V_DQ_ORDERS", "q3 대문자 허용 뷰 (예시)")
        if r.status_code != 200:
            bad2.append(f"대문자 허용 뷰 {r.status_code} (200 기대)")
        hr, dq, _, ch, _ = _ask(lab, "EX", good_sql, "q3 브라우저 허용 질의 (예시)", html=True)
        if hr.status_code != 200 or "SELECT request_no" not in hr.text or f'data-result="{dq[0]["query_no"] if dq else ""}"' not in hr.text \
                or f"{lab.prefix}DQ0" not in hr.text or len(ch) != 1:
            bad2.append(f"브라우저 허용 질의 {hr.status_code} · 결과 표/SQL/변경 로그 {len(ch)} (같은 화면 200 기대 · D-806)")
        out.append(res("G-16", "허용 질의 → 200 · 결과 · 로그 ok · 변경 로그 1행 · 브라우저 같은 화면", not bad2,
                       f"JSON 허용 1(행 4) · 리터럴 ;-- 1 · 대문자 뷰 1 · 브라우저 1 · 어긋남 {len(bad2)}", bad2))
        # 행 상한 · statement_timeout
        bad3 = []
        r, dq, _, _, _ = _ask(lab, "EX", "select a.request_no from v_dq_orders a, v_dq_orders b, v_dq_orders c, v_dq_orders d, v_dq_orders e limit 5000",
                              "q3 행 상한 (예시)")
        if r.status_code != 200 or r.json().get("row_count") != dataquery.MAX_ROWS or r.json().get("truncated") is not True \
                or len(r.json().get("rows", [])) != dataquery.MAX_ROWS or not dq or dq[0]["row_count"] != dataquery.MAX_ROWS:
            bad3.append(f"행 상한 {r.status_code} row_count={r.json().get('row_count') if r.status_code == 200 else '-'} truncated={r.json().get('truncated') if r.status_code == 200 else '-'} "
                        f"(200 · {dataquery.MAX_ROWS} · True 기대)")
        n = conn.q1("select count(*) as n from v_dq_orders")["n"]
        k = 32 if n < 2 else min(40, max(3, int(__import__('math').ceil(__import__('math').log(3e9) / __import__('math').log(n)))))
        heavy = "select count(*) from " + ", ".join(f"v_dq_orders a{i}" for i in range(k))
        r, dq, _, _, ms = _ask(lab, "EX", heavy, "q3 느린 조인 (예시)")
        timeout_ok = (r.status_code == 422 and str(r.json().get("message", "")).startswith("실행 실패 — ") and "timeout" in r.json().get("message", "").lower()
                      and dq and not dq[0]["ok"] and str(dq[0]["error"]).startswith("실행 실패"))
        if not timeout_ok:
            bad3.append(f"느린 조인({k}중 · 뷰 {n}행) {r.status_code} {str(r.json().get('message', ''))[:80]} · {ms}ms (422 「실행 실패 — … timeout」 기대)")
        elif ms > dataquery.STATEMENT_TIMEOUT_MS + 6000:
            bad3.append(f"statement_timeout {dataquery.STATEMENT_TIMEOUT_MS}ms 인데 {ms}ms 걸렸다")
        out.append(res("G-16", f"행 상한 {dataquery.MAX_ROWS} · statement_timeout {dataquery.STATEMENT_TIMEOUT_MS}ms", not bad3,
                       f"5중 교차 조인 limit 5000 → row_count {dataquery.MAX_ROWS} 잘림 · {k}중 교차 조인(뷰 {n}행 ≈ {n}^{k}) → 422 실행 실패(timeout) {ms}ms", bad3))
        # 실행 계층 — 검증을 우회했다고 가정하고 `_run_readonly` 를 직접 부른다: 트랜잭션 읽기 전용 · 제한 시간 · 쓰기 거부 · 역할은 복제본이 아니다(D-524 W4)
        bad4, notes = [], []
        try:
            ro = dataquery._run_readonly("select current_setting('transaction_read_only') as ro, current_setting('statement_timeout') as st")[1][0]
            if ro["ro"] != "on":
                bad4.append(f"transaction_read_only={ro['ro']} (on 기대)")
            if ro["st"] not in (f"{dataquery.STATEMENT_TIMEOUT_MS}ms", f"{dataquery.STATEMENT_TIMEOUT_MS // 1000}s"):
                bad4.append(f"statement_timeout={ro['st']} ({dataquery.STATEMENT_TIMEOUT_MS}ms 기대)")
            notes.append(f"transaction_read_only={ro['ro']} · statement_timeout={ro['st']}")
        except Exception as exc:  # noqa: BLE001
            bad4.append(f"설정 조회 실패 {type(exc).__name__}: {str(exc)[:80]}")
        try:
            dataquery._run_readonly(f"insert into customer (customer_code, customer_name, created_by) values ('{lab.prefix}inj', 'q3', 'qa3')")
            bad4.append("읽기 전용 연결에서 insert 가 성공했다")
        except Exception as exc:  # noqa: BLE001 — 25006 read_only_sql_transaction 이 기대값
            notes.append(f"insert → {type(exc).__name__}")
            if "ReadOnly" not in type(exc).__name__:
                bad4.append(f"insert 거부 사유가 읽기 전용이 아니다 — {type(exc).__name__}")
        try:
            rec = dataquery._run_readonly("select pg_is_in_recovery() as r")[1][0]["r"]
            notes.append(f"pg_is_in_recovery={rec} (복제본 아님 — 읽기 전용은 트랜잭션 수준 · 역할 분리는 D-524 W4)")
        except Exception as exc:  # noqa: BLE001
            notes.append(f"pg_is_in_recovery 조회 실패 {type(exc).__name__}")
        if _dq_invariants(lab)["injected"] != 0:
            bad4.append("실행 계층 insert 가 행을 남겼다")
        out.append(res("G-16", "실행 계층(검증 우회 가정) 읽기 전용 · 제한 시간", not bad4, " · ".join(notes), bad4))
        # 수금 뷰 부서 제한 (D-513) — 전략부(RPT-130 R · 수금 뷰 밖) 422 · PR/DS(RPT-130 칸 없음) 403 · EX/ADM 200
        bad5, got = [], []
        for role, view, want in (("ST", "v_dq_collections", 422), ("ST", "v_dq_receivables", 422), ("PR", "v_dq_collections", 403),
                                 ("DS", "v_dq_receivables", 403), ("SL", "v_dq_collections", 403), ("AC", "v_dq_collections", 403),
                                 ("SH", "v_dq_collections", 403), ("EX", "v_dq_collections", 200), ("ADM", "v_dq_receivables", 200)):
            r, dq, ai_rows, _, _ = _ask(lab, role, f"select * from {view} limit 3", f"q3 수금 뷰 {role} (예시)")
            got.append(f"{role} {r.status_code}")
            if r.status_code != want:
                bad5.append(f"{role} {view} {r.status_code} ({want} 기대)")
            elif want == 422 and ("부서" not in r.json().get("message", "") or not dq or dq[0]["ok"]):
                bad5.append(f"{role} 422 문장에 부서 사유 없음 / 로그 {len(dq)} — {r.json().get('message')!r:.80}")
            elif want == 403 and (dq or ai_rows):
                bad5.append(f"{role} 403 인데 로그 dq {len(dq)} · ai {len(ai_rows)} (칸 없음 → AI 호출 전 거부 · 0 기대)")
        out.append(res("G-16", "수금 뷰 부서 제한(D-513)", not bad5,
                       "ST 422(부서 사유 · 로그 1행) · PR·DS·SL·AC·SH 403(RPT-130 칸 없음 · AI 호출 0) · EX·ADM 200 — " + " · ".join(got), bad5))
        # 질문 자체 — NUL · 10만 자 → 422 (AI 호출 전 · 로그 0) · <script> 는 저장되고 화면에 이스케이프
        bad6 = []
        for label, q, want_logs in (("질문 NUL", "출하\x00수량", 0), ("질문 10만 자", "가" * 100_000, 0), ("질문 1001자", "가" * 1001, 0)):
            r, dq, ai_rows, _, _ = _ask(lab, "EX", "select 1 from v_dq_orders", q)
            if r.status_code != 422 or len(dq) != want_logs or len(ai_rows) != want_logs:
                bad6.append(f"{label} {r.status_code} · dq {len(dq)} · ai {len(ai_rows)} (422 · 0 · 0 기대)")
            elif r.json().get("fields", [{}])[0].get("name") != "질문":
                bad6.append(f"{label} fields {r.json().get('fields')}")
        xss_q = f"{lab.prefix} <script>alert(1)</script> \" onfocus=alert(2) autofocus=\" (예시)"
        r, dq, _, _, _ = _ask(lab, "EX", f"select request_no from v_dq_orders where customer_code = '{fx['code']}'", xss_q)
        page = lab.client("EX").get(QUERY_PATH, headers={"accept": "text/html"}).text
        hp = _ask(lab, "EX", f"select request_no from v_dq_orders where customer_code = '{fx['code']}'", xss_q, html=True)[0].text
        for name, html in (("RPT-130 GET", page), ("RPT-130 POST(브라우저)", hp)):
            if "<script>alert(1)</script>" in html or 'onfocus=alert(2) autofocus=" ' in html.replace("&quot;", '"') and "<script>" in html:
                bad6.append(f"{name}: 질문의 <script> 가 그대로 렌더됨")
            if "&lt;script&gt;alert(1)&lt;/script&gt;" not in html:
                bad6.append(f"{name}: 이스케이프된 질문이 보이지 않는다(저장 글자가 화면에 안 나왔다)")
        if r.status_code != 200 or not dq or dq[0]["question"] != xss_q:
            bad6.append(f"<script> 질문 {r.status_code} · 저장 질문 일치 {bool(dq) and dq[0]['question'] == xss_q}")
        out.append(res("G-16", "질문 NUL · 10만 자 → 422(AI 호출 0) · <script> 질문 이스케이프", not bad6,
                       f"NUL · 10만 자 · 1001자 → 422 · 로그 0 / <script> 질문 → 200 · DB 원문 · RPT-130 GET·POST 에 &lt;script&gt; · 어긋남 {len(bad6)}", bad6))
        # SYS-040 — 거부 행이 dq 탭에 · 호출 행이 ai 탭에 보인다(G-16 「거부 포함」이 눈에 보인다)
        adm = lab.client("ADM")
        rej = conn.q1("select d.query_no, d.error from data_query_log d join sys_user u on u.user_id = d.user_id where u.login_id = %s and not d.ok "
                      "and d.error like %s order by d.id desc limit 1", (lab.users["EX"][0], dataquery.REJECT_PREFIX + "%"))
        dq_page = adm.get("/sys/logs", params={"tab": "dq", "login": lab.users["EX"][0]}, headers={"accept": "text/html"})
        ai_page = adm.get("/sys/logs", params={"tab": "ai", "login": lab.users["EX"][0]}, headers={"accept": "text/html"})
        seen_dq = bool(rej) and dq_page.status_code == 200 and rej["query_no"] in dq_page.text and (rej["error"] or "")[:30] in dq_page.text
        seen_ai = ai_page.status_code == 200 and dataquery.AI_KIND in ai_page.text
        out.append(res("G-16", "SYS-040 dq · ai 탭에 거부 질의가 보인다", seen_dq and seen_ai,
                       f"dq 탭 {dq_page.status_code} 거부 {rej['query_no'] if rej else '-'} {'보임' if seen_dq else '안 보임'} · ai 탭 {ai_page.status_code} "
                       f"{'보임' if seen_ai else '안 보임'}"))
    return out


_KEYLESS_SCRIPT = r"""
import json, os, sys, warnings, urllib.request
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.join(os.environ["QA3_ROOT"], "src"))
def _blocked(*a, **k):
    raise RuntimeError("QA3 — 실제 OpenAI 호출 차단")
urllib.request.urlopen = _blocked
from lcomfine.app.settings import get_settings
s = get_settings()
out = {"key_empty": s.openai_api_key == "", "model": s.openai_model}
if not out["key_empty"]:
    print("QA3JSON" + json.dumps(out)); sys.exit(0)      # 키가 비지 않았다 — 요청을 보내지 않는다(실제 호출 위험)
from fastapi.testclient import TestClient
from lcomfine.app.main import app
c = TestClient(app, raise_server_exceptions=False)
for k, v in json.loads(os.environ["QA3_COOKIE"]).items():
    c.cookies.set(k, v)
q = os.environ["QA3_Q"]
r = c.post("/rpt/query", data={"question": q})
out["json"] = {"status": r.status_code, "body": r.text[:2000]}
r2 = c.post("/rpt/query", data={"question": q}, headers={"accept": "text/html", "referer": "/rpt/query"}, follow_redirects=False)
out["html_post"] = {"status": r2.status_code, "location": r2.headers.get("location")}
r3 = c.get("/rpt/query", headers={"accept": "text/html"})
out["html_get"] = {"status": r3.status_code, "body": r3.text[:200000]}
print("QA3JSON" + json.dumps(out, ensure_ascii=False))
"""


def check_ai_key_missing(lab: Lab) -> list[Result]:
    """G-17 — 키 없음 → 422 「AI 키가 설정되지 않았습니다 — LCOMFINE_OPENAI_API_KEY」 가 화면에 그대로 · sys_ai_call_log 1행(ok false · error) ·
    data_query_log 1행 · 다른 테이블 쓰기 0 · 하드코딩 결과 0. 호출 실패(fake 예외 · 글자 아닌 응답) → 422 · 로그 ok false. 키 값은 로그 · 문장에 없다."""
    from lcomfine.app import dataquery
    from lcomfine.db import conn

    _dq_fixture(lab)
    out: list[Result] = []
    msg = "AI 키가 설정되지 않았습니다 — LCOMFINE_OPENAI_API_KEY"
    ex_lid = lab.users["EX"][0]
    with no_real_ai() as ai:
        if ai.NOT_CONFIGURED_MESSAGE != msg:
            out.append(res("G-17", "키 없음 문장(계약 글자 그대로)", False, f"ai.NOT_CONFIGURED_MESSAGE = {ai.NOT_CONFIGURED_MESSAGE!r}"))
        # 1. 프로세스 안 — settings 의 키를 비운다(실제 경로 · fake 없음) → NotConfigured
        ai._config = lambda: ("", "gpt-4.1")
        counts0 = business_counts()
        inv0 = _dq_invariants(lab)
        bad = []
        r, dq, ai_rows, ch, _ = _ask(lab, "EX", None, "q3 키 없음 (예시)")
        if r.status_code != 422 or r.json().get("message") != msg:
            bad.append(f"JSON {r.status_code} {r.text[:120]} (422 · 문장 그대로 기대)")
        else:
            b = r.json()
            if "rows" in b or "columns" in b or [f["name"] for f in b.get("fields", [])] != ["질의 번호"]:
                bad.append(f"422 본문 {str(b)[:160]} (결과 없음 · fields = 질의 번호만 기대)")
        if len(ai_rows) != 1 or ai_rows[0]["ok"] or ai_rows[0]["error"] != msg or ai_rows[0]["model"] != "gpt-4.1" or ai_rows[0]["kind"] != dataquery.AI_KIND:
            bad.append(f"sys_ai_call_log {[(a['ok'], a['error'], a['model']) for a in ai_rows]} (1행 · ok false · 문장 기대)")
        if len(dq) != 1 or dq[0]["ok"] or dq[0]["sql_text"] is not None or dq[0]["error"] != msg or dq[0]["row_count"] is not None:
            bad.append(f"data_query_log {[(d['ok'], d['sql_text'], d['error']) for d in dq]} (1행 · ok false · sql 없음 · 문장 기대)")
        if ch:
            bad.append(f"sys_change_log {len(ch)}행 (키 없음은 변경 아님 · 0 기대)")
        # 브라우저 — 폼 POST 는 303 + 알림 → 같은 화면 GET 에 문장이 보인다 · 결과 표 없음
        hr, dq2, ai2, _, _ = _ask(lab, "EX", None, "q3 키 없음 브라우저 (예시)", html=True)
        page = lab.client("EX").get(QUERY_PATH, headers={"accept": "text/html"})
        if hr.status_code != 303 or not hr.headers.get("location", "").startswith(QUERY_PATH):
            bad.append(f"브라우저 POST {hr.status_code} → {hr.headers.get('location')} (303 /rpt/query 기대)")
        if page.status_code != 200 or msg not in page.text or 'data-result="' in page.text:
            bad.append(f"브라우저 화면 {page.status_code} · 문장 {'보임' if msg in page.text else '안 보임'} · 결과 표 {'있음' if 'data-result=' in page.text else '없음'}")
        if dq2 and dq2[0]["query_no"] not in page.text:
            bad.append("최근 질의 목록에 키 없음 질의가 없다")
        if len(dq2) != 1 or len(ai2) != 1:
            bad.append(f"브라우저 질의 로그 dq {len(dq2)} · ai {len(ai2)} (1 · 1 기대)")
        if _dq_invariants(lab) != inv0:
            bad.append("키 없음 요청이 업무 행을 바꿨다")
        diff = {t: (counts0.get(t), n) for t, n in business_counts().items() if counts0.get(t) != n}
        out.append(res("G-17", "키 없음(프로세스 안 · settings 비움) → 422 문장 그대로 · 로그 1·1 · 결과 0", not bad,
                       f"JSON 422 · 브라우저 303→화면에 문장 · sys_ai_call_log ok=false error=문장 · data_query_log ok=false sql 없음 · 변경 로그 0 · "
                       f"업무 테이블 전수 diff {len(diff)}{' ' + str(diff)[:100] if diff else ''}", bad))
        # 2. 하위 프로세스 — LCOMFINE_OPENAI_API_KEY= (빈 값) · settings 실제 경로 · urlopen 차단
        bad2 = []
        q = f"q3 키 없음 하위 프로세스 {lab.prefix} (예시)"
        m = _marks()
        env = dict(os.environ, LCOMFINE_OPENAI_API_KEY="", QA3_ROOT=str(ROOT), QA3_COOKIE=json.dumps(dict(lab.fresh("EX").cookies)), QA3_Q=q)
        p = subprocess.run([sys.executable, "-c", _KEYLESS_SCRIPT], cwd=ROOT, env=env, capture_output=True, text=True, timeout=180)
        mm = re.search(r"QA3JSON(.*)$", p.stdout, re.S)
        if not mm:
            bad2.append(f"하위 프로세스 실패 rc={p.returncode}: {(p.stderr or p.stdout)[-300:]}")
            got = {}
        else:
            got = json.loads(mm.group(1))
        if not got.get("key_empty"):
            bad2.append("하위 프로세스의 settings 키가 비지 않았다(.env 가 빈 환경변수를 덮었다?) — 요청을 보내지 않았다")
        else:
            j = got["json"]
            if j["status"] != 422 or msg not in j["body"] or "rows" in j["body"]:
                bad2.append(f"JSON {j['status']} {j['body'][:120]}")
            if got["html_post"]["status"] != 303:
                bad2.append(f"브라우저 POST {got['html_post']}")
            if got["html_get"]["status"] != 200 or msg not in got["html_get"]["body"] or 'data-result="' in got["html_get"]["body"]:
                bad2.append(f"브라우저 화면 {got['html_get']['status']} · 문장 {'보임' if msg in got['html_get']['body'] else '안 보임'}")
            dq, ai_rows, ch = _logs_since(lab, m)
            if len(dq) != 2 or any(d["ok"] for d in dq) or any(d["error"] != msg for d in dq) or any(d["question"] != q for d in dq):
                bad2.append(f"data_query_log {[(d['ok'], d['error']) for d in dq]} (2행 · ok false · 문장 기대)")
            if len(ai_rows) != 2 or any(a["ok"] for a in ai_rows) or any(a["error"] != msg for a in ai_rows):
                bad2.append(f"sys_ai_call_log {[(a['ok'], a['error']) for a in ai_rows]} (2행 · ok false 기대)")
            if ch:
                bad2.append(f"sys_change_log {len(ch)}행 (0 기대)")
        out.append(res("G-17", "키 없음(하위 프로세스 LCOMFINE_OPENAI_API_KEY= · settings 실제 경로)", not bad2,
                       f"키 빈 값 확인 {got.get('key_empty')} · JSON {got.get('json', {}).get('status')} · 브라우저 POST {got.get('html_post', {}).get('status')} → "
                       f"GET {got.get('html_get', {}).get('status')} 문장 보임 · 로그 dq 2 · ai 2 · 변경 0", bad2))
        # 3. 호출 실패 — 주입 클라이언트가 예외 · 글자 아닌 응답 → 422 「AI 호출 실패 — …」 · 로그 ok false
        bad3 = []

        def boom(m_, s_, u_):
            raise RuntimeError("연결 거부 (예시)")

        r, dq, ai_rows, ch, _ = _ask(lab, "EX", boom, "q3 호출 실패 (예시)")
        if r.status_code != 422 or not r.json().get("message", "").startswith("AI 호출 실패 — ") or "연결 거부" not in r.json().get("message", ""):
            bad3.append(f"예외 fake {r.status_code} {r.text[:120]}")
        if len(ai_rows) != 1 or ai_rows[0]["ok"] or "연결 거부" not in (ai_rows[0]["error"] or "") or ai_rows[0]["ms"] is None:
            bad3.append(f"예외 fake ai 로그 {[(a['ok'], a['error']) for a in ai_rows]}")
        if len(dq) != 1 or dq[0]["ok"] or not (dq[0]["error"] or "").startswith("AI 호출 실패") or dq[0]["sql_text"] is not None or ch:
            bad3.append(f"예외 fake dq 로그 {[(d['ok'], d['sql_text'], d['error']) for d in dq]} · 변경 {len(ch)}")
        r, dq, ai_rows, _, _ = _ask(lab, "EX", lambda m_, s_, u_: {"sql": "select 1"}, "q3 글자 아닌 응답 (예시)")
        if r.status_code != 422 or "응답이 글자가 아니다" not in r.json().get("message", "") or len(ai_rows) != 1 or ai_rows[0]["ok"] or len(dq) != 1 or dq[0]["ok"]:
            bad3.append(f"글자 아닌 응답 {r.status_code} {r.text[:100]} · ai {[(a['ok'], a['error']) for a in ai_rows]}")
        r, dq, ai_rows, _, _ = _ask(lab, "EX", lambda m_, s_, u_: "", "q3 빈 응답 (예시)")
        if r.status_code != 422 or len(dq) != 1 or dq[0]["ok"]:
            bad3.append(f"빈 응답 {r.status_code} · dq {len(dq)}")
        # 실제 호출 경로가 바깥으로 나가면 차단기(_NoNetwork)에 걸린다 — 키가 있을 때 fake 없이 부르면 「AI 호출 실패 — _NoNetwork」 · 그래도 로그 1행
        ai._config = lambda: ("q3-not-a-real-key", "gpt-4.1")
        r, dq, ai_rows, _, _ = _ask(lab, "EX", None, "q3 차단기 (예시)")
        blocked = r.status_code == 422 and "_NoNetwork" in r.json().get("message", "") and len(ai_rows) == 1 and not ai_rows[0]["ok"]
        if not blocked:
            bad3.append(f"차단기 경로 {r.status_code} {r.text[:120]} · ai {[(a['ok'], a['error']) for a in ai_rows]} (실제 urlopen 이 불렸어야 하는데 안 불렸거나 다른 길)")
        out.append(res("G-17", "호출 실패(예외 · 글자 아닌 응답 · 빈 응답 · 네트워크 차단) → 422 「AI 호출 실패 — …」 · 로그 ok false", not bad3,
                       f"예외 fake · dict 응답 · 빈 응답 · urlopen 차단 4 → 422 · sys_ai_call_log ok=false · data_query_log ok=false · 어긋남 {len(bad3)}", bad3))
        # 4. 키 값이 로그 · 문장에 실리지 않는다 — 가짜 키(sentinel)로 잰다 · 실제 키 값은 응답·로그에 없는지만 센다(찍지 않는다)
        bad4, notes = [], []
        sentinel = "q3sentinel" + secrets.token_hex(8)
        ai._config = lambda: (sentinel, "gpt-4.1")

        def leak_client(m_, s_, u_):
            raise RuntimeError(f"Authorization: Bearer {sentinel} rejected")

        r, dq, ai_rows, _, _ = _ask(lab, "EX", leak_client, "q3 키 가림 주입 (예시)")
        a_err = (ai_rows[0]["error"] or "") if ai_rows else ""
        d_err = (dq[0]["error"] or "") if dq else ""
        if sentinel in a_err or sentinel in d_err or sentinel in r.text:
            bad4.append(f"주입 예외의 키 글자가 남았다 — ai 로그 {sentinel in a_err} · dq 로그 {sentinel in d_err} · 422 본문 {sentinel in r.text}")
        notes.append(f"주입 예외: ai 로그 {'***' if '***' in a_err else '가림 표식 없음'} · dq {'가림' if sentinel not in d_err else '노출'} · 응답 {'가림' if sentinel not in r.text else '노출'}")

        def fail_openai(model, system, user, *, key):   # 실제 호출 함수 자리 — HTTP 오류 본문이 키를 되비추는 상황(OpenAI 401 「Incorrect API key provided: …」)
            raise ai.CallFailed(f"HTTP 401 Unauthorized Incorrect API key provided: {key}")

        ai._openai = fail_openai
        r, dq, ai_rows, _, _ = _ask(lab, "EX", None, "q3 키 가림 HTTP 오류 (예시)")
        a_err = (ai_rows[0]["error"] or "") if ai_rows else ""
        d_err = (dq[0]["error"] or "") if dq else ""
        leak_http = [k for k, v in (("sys_ai_call_log.error", a_err), ("data_query_log.error", d_err), ("422 본문", r.text)) if sentinel in v]
        if leak_http:
            bad4.append("HTTP 오류 문장의 키가 그대로 남았다: " + " · ".join(leak_http))
        notes.append(f"HTTP 오류: ai 로그 {'가림(***)' if sentinel not in a_err else '노출'} · dq 로그 {'가림' if sentinel not in d_err else '노출'} · 422 본문 {'가림' if sentinel not in r.text else '노출'}")
        real = [v for v in (os.environ.get("LCOMFINE_OPENAI_API_KEY"),) if v and len(v) >= 8]
        if real:
            n_leak = conn.q1("select (select count(*) from sys_ai_call_log where error like %s) + (select count(*) from data_query_log where error like %s "
                             "or sql_text like %s or question like %s) as n", (f"%{real[0]}%", f"%{real[0]}%", f"%{real[0]}%", f"%{real[0]}%"))["n"]
            if n_leak:
                bad4.append(f"실제 키 값이 든 로그 행 {n_leak}")
            notes.append(f"실제 키 값이 든 로그 행 {n_leak}(.env 의 값으로 DB 를 검색만 — 값은 찍지 않는다)")
        # 정적 — ai.py 에서 `key` 가 쓰이는 줄은 Authorization 헤더와 _mask 뿐
        src = (ROOT / "src/lcomfine/app/ai.py").read_text(encoding="utf-8").splitlines()
        uses = [f"{i}: {ln.strip()[:70]}" for i, ln in enumerate(src, 1) if re.search(r"\bkey\b", ln) and not ln.strip().startswith(("#", '"""', "'''"))
                and "_mask(" not in ln and "key=key" not in ln and "def _openai" not in ln and "def _mask" not in ln and "key, model = _config()" not in ln
                and "if key:" not in ln and "not key" not in ln and '"***"' not in ln]        # `_mask` 본문(replace(key, "***"))은 가리는 줄이다
        allowed_static = all("Authorization" in u for u in uses)
        if not allowed_static:
            bad4.append("ai.py 의 key 사용 줄: " + " / ".join(uses))
        notes.append(f"정적 ai.py key 사용 {len(uses)}줄(Authorization 헤더만 {allowed_static})")
        out.append(res("G-17", "키 값이 로그 · 예외 문장 · 응답에 없다", not bad4, " · ".join(notes), bad4))
        # 5. 하드코딩 결과 0 — 정적: dataquery · rpt · ai 에 결과 행 리터럴 · 예외 삼키기 없음
        hits = []
        for rel in ("src/lcomfine/app/dataquery.py", "src/lcomfine/app/routers/rpt.py", "src/lcomfine/app/ai.py"):
            text = (ROOT / rel).read_text(encoding="utf-8")
            for i, ln in enumerate(text.splitlines(), 1):
                s_ = ln.strip()
                if s_.startswith("#"):
                    continue
                literal_rows = re.search(r'"rows":\s*\[\s*\{\s*"', s_)      # 결과 행 리터럴(글자 키의 dict) — `[{k: … for …}]` 직렬화 컴프리헨션은 리터럴이 아니다
                if literal_rows or re.search(r"except\s+\w*\s*:\s*pass\b", s_) or re.search(r"except Exception:\s*$", s_):
                    hits.append(f"{rel}:{i} {s_[:60]}")
        out.append(res("G-17", "정적: 하드코딩 결과 · 예외 삼키기 없음", not hits, f"dataquery.py · rpt.py · ai.py — 결과 리터럴/except pass {len(hits)}", hits))
    return out


def check_rpt_access(lab: Lab) -> list[Result]:
    """G-19 · G-20 (RPT) — 화면 9 × 부서 8 200/403 · F-RPT-132 × 8(칸 R 이상 → 빈 본문 422 · 칸 없음 403 · AI 호출 0) · 미로그인 401 ·
    비활성 · 로그아웃 401."""
    from lcomfine.app import contracts, nav, rbac

    cells = {(sid, rc): lv for sid, rc, lv in contracts.permission_cells()}
    screens = [sc for sc in nav.SCREENS if sc.screen_id in RPT_SCREENS]
    out: list[Result] = []
    bad, n200, n403 = [], 0, 0
    for r in rbac.roles():
        c = lab.client(r.code)
        for sc in screens:
            want = 200 if cells.get((sc.screen_id, r.code)) else 403
            got = c.get(sc.path).status_code
            n200 += want == 200
            n403 += want == 403
            if got != want:
                bad.append(f"{sc.screen_id}×{r.code} {got} ({want} 기대)")
        html = c.get("/", headers={"accept": "text/html"}).text
        hrefs = set(re.findall(r'href="([^"?#]+)', html))
        for sc in screens:
            if not cells.get((sc.screen_id, r.code)) and sc.path in hrefs:
                bad.append(f"메뉴 {r.code}: 칸 없는 {sc.screen_id} 링크")
    out.append(res("G-19", "RPT 화면 9 × 부서 8 (200/403 · 메뉴 숨김)", not bad and len(screens) == 9,
                   f"화면 {len(screens)} × 부서 {len(rbac.roles())} — 200 기대 {n200} · 403 기대 {n403} · 어긋남 {len(bad)}", bad))
    fn = contracts.function("F-RPT-132")
    bad2, got = [], []
    with no_real_ai():
        m = _marks()
        for r in rbac.roles():
            lv = rbac.level(r.code, "RPT-130")
            st = lab.client(r.code).post(QUERY_PATH, data={}).status_code
            got.append(f"{r.code}({lv or '없음'}) {st}")
            want = 422 if lv else 403
            if st != want:
                bad2.append(f"F-RPT-132×{r.code} 칸 {lv or '없음'} → {st} ({want} 기대)")
        dq, ai_rows, _ = _logs_since(lab, m)
        if dq or ai_rows:
            bad2.append(f"빈 본문으로 로그가 남았다 dq {len(dq)} · ai {len(ai_rows)} (질문 누락은 AI 호출 전 422 · 0 기대)")
        anon = new_client()
        a1 = anon.post(QUERY_PATH, data={"question": "x"}).status_code
        a2 = anon.get(QUERY_PATH).status_code
        a3 = anon.get(QUERY_PATH, headers={"accept": "text/html"}, follow_redirects=False)
        if (a1, a2, a3.status_code) != (401, 401, 303) or not a3.headers.get("location", "").startswith("/login"):
            bad2.append(f"미로그인 POST {a1} · GET {a2} · GET(html) {a3.status_code}→{a3.headers.get('location')} (401 · 401 · 303 /login 기대)")
    out.append(res("G-19", "F-RPT-132 질의 실행 × 부서 8 (권한 예외 — 칸 R 이상 통과 · 칸 없음 403) · 미로그인 401", not bad2 and fn.permission_exception,
                   f"권한 예외 {fn.permission_exception} — " + " · ".join(got) + f" · 미로그인 POST {a1} GET {a2} · 어긋남 {len(bad2)}", bad2))
    # G-20 — 비활성 · 로그아웃 → RPT 401
    admin = lab.client("ADM")
    lid, pw, uid = lab.make_user("EX", "rex")
    c = login(lid, pw)
    a = c.get("/rpt/orders").status_code
    deact = admin.post(f"/sys/users/{uid}/delete").status_code
    b, bp = c.get("/rpt/summary").status_code, c.post(QUERY_PATH, data={"question": "x"}).status_code
    lid2, pw2, _ = lab.make_user("ST", "rst")
    c2 = login(lid2, pw2)
    a2_ = c2.get(QUERY_PATH).status_code
    c2.post("/logout", follow_redirects=False)
    d, dp = c2.get("/rpt/orders").status_code, c2.post(QUERY_PATH, data={"question": "x"}).status_code
    got2 = (a, deact, b, bp, a2_, d, dp)
    out.append(res("G-20", "RPT 비활성 · 로그아웃 → 401", got2 == (200, 200, 401, 401, 200, 401, 401),
                   f"EX 전 {a} · 비활성 {deact} → RPT-080 GET {b} · 질의 POST {bp} / ST 전 {a2_} · 로그아웃 → RPT-010 GET {d} · 질의 POST {dp}"))
    return out


def check_rpt_change_log(lab: Lab) -> list[Result]:
    """G-22 (RPT) — 성공 질의 → sys_change_log 정확히 1행(F-RPT-132 · RPT-130 · POST · target data_query_log:<번호>) · 거부 · 키 없음 · 403 · 422 → 0행 ·
    SYS-040 변경 탭에 보인다 · 대시보드 8 GET → sys_access_log 조회 1행씩."""
    from lcomfine.db import conn

    fx = _dq_fixture(lab)
    out: list[Result] = []
    ex_lid = lab.users["EX"][0]
    with no_real_ai() as ai:
        bad = []
        r, dq, _, ch, _ = _ask(lab, "EX", f"select request_no, qty from v_dq_orders where customer_code = '{fx['code']}'", "q3 변경 로그 성공 (예시)")
        if r.status_code != 200 or len(ch) != 1:
            bad.append(f"성공 질의 {r.status_code} · 변경 로그 {len(ch)}행 (200 · 1 기대)")
        else:
            c = ch[0]
            want = ("F-RPT-132", "RPT-130", "POST", QUERY_PATH, f"data_query_log:{r.json()['query_no']}", ex_lid, "EX")
            got = (c["function_id"], c["screen_id"], c["method"], c["path"], c["target"], c["login_id"], c["role_code"])
            if got != want:
                bad.append(f"변경 로그 값 {got} (기대 {want})")
        target = ch[0]["target"] if ch else ""
        neg = [("거부(쓰기 SQL)", "EX", "delete from customer", 422), ("키 없음", "EX", None, 422), ("칸 없음 403", "PR", "select 1 from v_dq_orders", 403)]
        for label, role, fake, want in neg:
            if fake is None:
                ai._config = lambda: ("", "gpt-4.1")
            r, _, _, ch2, _ = _ask(lab, role, fake, f"q3 변경 로그 {label} (예시)")
            if r.status_code != want or ch2:
                bad.append(f"{label} → {r.status_code} (기대 {want}) · 변경 로그 {len(ch2)}행 (0 기대)")
        ai._config = lambda: ("q3-not-a-real-key", "gpt-4.1")
        m = _marks()
        st = lab.client("EX").post(QUERY_PATH, data={"question": ""}).status_code
        _, _, ch3 = _logs_since(lab, m)
        if st != 422 or ch3:
            bad.append(f"빈 질문 → {st} · 변경 로그 {len(ch3)}행 (422 · 0 기대)")
        page = lab.client("ADM").get("/sys/logs", params={"tab": "change", "login": ex_lid}, headers={"accept": "text/html"})
        if not target or page.status_code != 200 or target not in page.text:
            bad.append(f"SYS-040 변경 탭 {page.status_code} 에 {target!r} 안 보임")
        out.append(res("G-22", "RPT 질의 성공 → sys_change_log 1행 · 거부/키 없음/403/422 → 0행 · SYS-040", not bad,
                       f"성공 1 → 1행(F-RPT-132 · RPT-130 · POST /rpt/query · {target or '-'}) · 음성 4 → 0행 · SYS-040 변경 탭 보임 · 어긋남 {len(bad)}", bad))
    # 대시보드 8 GET → sys_access_log 조회 1행씩 (경영진 임시 계정)
    bad2 = []
    c = lab.client("EX")
    for sid in RPT_SCREENS[:-1]:
        from lcomfine.app import nav
        path = nav.path_of(sid)
        before = conn.q1("select count(*) as n from sys_access_log where login_id = %s and log_type = '조회' and screen_id = %s", (ex_lid, sid))["n"]
        st = c.get(path, headers={"accept": "text/html"}).status_code
        after = conn.q1("select count(*) as n from sys_access_log where login_id = %s and log_type = '조회' and screen_id = %s", (ex_lid, sid))["n"]
        if st != 200 or after - before != 1:
            bad2.append(f"{sid} {st} · 조회 로그 +{after - before}")
    out.append(res("G-22", "RPT 대시보드 8 조회 → sys_access_log 1행씩", not bad2, f"화면 8 · 어긋남 {len(bad2)}", bad2))
    return out


def check_rpt_escape(lab: Lab) -> list[Result]:
    """X-09 — 거래처 이름의 `<script>` 가 대시보드 화면(표 · 거래처 선택) 과 인라인 SVG `<title>` 에 이스케이프돼 나온다 · 대시보드 GET 은 업무 테이블을 바꾸지 않는다."""
    from lcomfine.app import templating
    from lcomfine.db import conn

    fx = _dq_fixture(lab)
    raw, esc = "<script>alert(1)</script>", "&lt;script&gt;alert(1)&lt;/script&gt;"
    today = date.today().isoformat()
    c = lab.client("EX")
    counts0 = business_counts()
    bad, seen = [], []
    pages = {"RPT-010 (표 top_customers · 선택)": f"/rpt/orders?date_from={today}&date_to={today}",
             "RPT-050 (거래처 선택)": "/rpt/shipment", "RPT-060 (거래처 선택)": "/rpt/collection",
             "RPT-070 (거래처 선택)": "/rpt/order-flow", "RPT-080 (거래처 선택)": "/rpt/summary",
             "RPT-010 ?customer=<script>": f"/rpt/orders?customer={fx['xs']}&date_from={today}&date_to={today}"}
    for label, path in pages.items():
        r = c.get(path, headers={"accept": "text/html"})
        if r.status_code != 200:
            bad.append(f"{label} {r.status_code}")
            continue
        if raw in r.text or "<img src=x onerror=alert(2)>" in r.text:
            bad.append(f"{label}: 거래처 이름의 태그가 그대로 렌더됨")
        if esc in r.text:
            seen.append(label)
    if not seen:
        bad.append("어느 화면에도 이스케이프된 이름이 안 보인다(검사가 비었다)")
    # 인라인 SVG <title> — 차트 매크로를 직접 렌더해 라벨의 태그가 이스케이프되는지 (대시보드 템플릿과 같은 Jinja 환경 · autoescape)
    svg = templating.env.from_string('{% import "_macros.html" as ui %}{{ ui.svg_bar(series) }}{{ ui.svg_line(series) }}').render(
        series=[{"label": raw, "value": 3}, {"label": "b", "value": None}])
    if raw in svg or esc not in svg or "<title>" not in svg:
        bad.append(f"SVG <title> 이스케이프 — raw {raw in svg} · esc {esc in svg}")
    # RPT-010 의 수주 표에 그 거래처 행이 있다(이름이 실제로 화면에 흐른다)
    r = c.get(f"/rpt/orders?date_from={today}&date_to={today}", headers={"accept": "text/html"})
    if f"{lab.prefix}XS" not in r.text and f"{lab.prefix}xs" not in r.text:
        bad.append("RPT-010 에 <script> 거래처의 의뢰가 보이지 않는다")
    for sid in RPT_SCREENS[:-1]:
        from lcomfine.app import nav
        c.get(nav.path_of(sid))
    diff = {t: (counts0.get(t), n) for t, n in business_counts().items() if counts0.get(t) != n}
    return [res("X-09", "대시보드 — 거래처 이름 <script> 이스케이프(화면 · SVG title) · GET 이 업무 테이블을 바꾸지 않음", not bad,
                f"화면 {len(pages)} 중 이스케이프 보인 곳 {len(seen)} · 원문 태그 0 · SVG 막대·선 title 이스케이프 · 대시보드 8 GET 뒤 업무 테이블 전수 diff {len(diff)}"
                f"{' ' + str(diff)[:100] if diff else ''}", bad)]


def check_rpt_static() -> list[Result]:
    """X-10 — dashboard.py · rpt.py 에 쓰기 SQL(insert · update … set · delete from · truncate · create · alter · drop) 0 · dashboard 는 conn.x/tx 0 ·
    rpt.py 의 conn.tx 는 dataquery.ask(로그) 하나 · 쓰기 테이블은 계약(db-schema F-RPT-132) 둘뿐."""
    write_re = re.compile(r"\b(insert\s+into|update\s+\w+\s+set|delete\s+from|truncate\s|create\s+(table|temp|index)|alter\s+table|drop\s+(table|view))\b", re.I)
    hits, tx = [], []
    for rel in ("src/lcomfine/app/dashboard.py", "src/lcomfine/app/routers/rpt.py"):
        for i, ln in enumerate((ROOT / rel).read_text(encoding="utf-8").splitlines(), 1):
            s_ = ln.strip()
            if s_.startswith("#"):
                continue
            if write_re.search(s_):
                hits.append(f"{rel}:{i} {s_[:60]}")
            if re.search(r"\bconn\.(x|tx)\(", s_):
                tx.append(f"{rel}:{i} {s_[:60]}")
    dq_src = (ROOT / "src/lcomfine/app/dataquery.py").read_text(encoding="utf-8")
    ai_src = (ROOT / "src/lcomfine/app/ai.py").read_text(encoding="utf-8")
    writes = set(re.findall(r"insert into (\w+)", dq_src + ai_src, re.I))
    ok_tx = all("routers/rpt.py" in t and "conn.tx()" in t for t in tx) and len(tx) == 1
    ok_w = writes == {"data_query_log", "sys_ai_call_log"}
    return [res("X-10", "정적: 대시보드 · RPT 라우터 쓰기 SQL 0 · 데이터 질의 쓰기 테이블 = 로그 2", not hits and ok_tx and ok_w,
                f"dashboard.py · rpt.py 쓰기 SQL {len(hits)} · conn.x/tx {len(tx)}(rpt.py 의 dataquery.ask 트랜잭션만 {ok_tx}) · "
                f"dataquery.py · ai.py 의 insert 대상 {sorted(writes)}", hits + ([] if ok_tx else tx))]


# ── W4 문서 SSO (DOC) · DB 역할 (D-524) ─────────────────────────────────
# 문서관리 시스템은 없다 — 자동 POST 폼은 렌더만 보고 검증은 `sso.consume`(문서관리 쪽 규칙의 재현)으로 한다. 외부로 보내지 않는다.
# 주소 · 비밀은 `sso_env()` 안에서만 가짜 값(주소 `.invalid` · 비밀 난수)으로 바꾸고 끝에 원래 값으로 되돌린다 — 값은 어디에도 찍지 않는다.
SSO_FAKE_URL = "https://doc.example.invalid/sso"
SSO_ENV = ("LCOMFINE_DOC_SSO_URL", "LCOMFINE_SSO_SECRET")
_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}")


@contextmanager
def sso_env(*, url: bool = True, secret: bool = True):
    """SSO 주소 · 비밀을 잠깐 바꾼다(url/secret False = 빈 값 → 미설정). yield = 가짜 비밀(또는 ""). 끝에 되돌리고 settings 캐시를 비운다."""
    from lcomfine.app import settings as st

    saved = {k: os.environ.get(k) for k in SSO_ENV}
    fake = secrets.token_urlsafe(32) if secret else ""
    os.environ["LCOMFINE_DOC_SSO_URL"] = SSO_FAKE_URL if url else ""
    os.environ["LCOMFINE_SSO_SECRET"] = fake
    st.reset_cache()
    try:
        yield fake
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        st.reset_cache()


def _sso_user(lab: Lab, tag: str, role: str = "PR", *, mapped: bool = True, active: bool = True) -> tuple[str, str, int, str]:
    from lcomfine.db import conn

    lid, pw, uid = lab.make_user(role, tag)
    acc = f"{lab.prefix}{tag}-acc"
    if mapped:
        conn.x("insert into doc_account_map (user_id, account_id, active, created_by) values (%s, %s, %s, 'qa3')", (uid, acc, active))
    return lid, pw, uid, acc


def _issue(lid: str, *, now=None) -> tuple[str, str]:
    from lcomfine.app import rbac, sso
    from lcomfine.db import conn

    with conn.tx() as cur:
        return sso.issue(cur, rbac.load_user(lid), now=now)


def _consume(token, *, now=None) -> dict:
    from lcomfine.app import sso
    from lcomfine.db import conn

    with conn.tx() as cur:
        return sso.consume(cur, token, now=now)


def _refused(fn, *exc_types) -> str | None:
    """fn() 이 exc_types 중 하나를 올리면 그 사유, 통과하면 None, 다른 예외면 'X:<종류>'."""
    try:
        fn()
    except exc_types as e:  # noqa: PERF203
        return getattr(e, "reason", str(e))
    except Exception as e:  # noqa: BLE001 — 사유 없는 다른 예외는 그 자체가 어긋남
        return f"X:{type(e).__name__}"
    return None


def _tokens_of(uid: int) -> int:
    from lcomfine.db import conn

    return conn.q1("select count(*) as n from sso_token where user_id = %s", (uid,))["n"]


def _max_access_id() -> int:
    from lcomfine.db import conn

    return conn.q1("select coalesce(max(log_id), 0) as m from sys_access_log")["m"]


def _sso_logs(lid: str, since: int = 0) -> list[dict]:
    from lcomfine.db import conn

    return conn.q("select log_id, login_id, role_code, logged_at, method, path, screen_id, function_id, target, result, detail "
                  "from sys_access_log where log_type = 'SSO' and login_id = %s and log_id > %s order by log_id", (lid, since))


def _hidden_tokens(html: str) -> list[str]:
    return re.findall(r'<input type="hidden" name="token" value="([^"]*)">', html)


def _b64(d: dict) -> str:
    import base64

    return base64.urlsafe_b64encode(json.dumps(d, separators=(",", ":")).encode()).rstrip(b"=").decode()


def _sign_with(key: str, body: str) -> str:
    import base64
    import hashlib
    import hmac

    return base64.urlsafe_b64encode(hmac.new(key.encode(), body.encode(), hashlib.sha256).digest()).rstrip(b"=").decode()


def _token_in_db(needles: list[str]) -> list[str]:
    """public 의 모든 표에서 행 글자(row::text)에 needle 이 든 표 — 토큰 평문 · 서명이 DB 어디에도 없는지."""
    from lcomfine.db import conn

    tables = [r["table_name"] for r in conn.q("select table_name from information_schema.tables "
                                                "where table_schema = 'public' and table_type = 'BASE TABLE' order by 1")]
    hits = []
    with conn.tx() as cur:
        for t in tables:
            for nd in needles:
                cur.execute(f'select count(*) as n from "{t}" x where position(%s in x::text) > 0', (nd,))
                if cur.fetchone()["n"]:
                    hits.append(f"{t}({len(nd)}자)")
    return hits


def check_sso_token(lab: Lab) -> list[Result]:
    """G-18 토큰 규칙 — `sso.issue` · `sso.consume` 를 직접 부른다(가짜 주소 · 가짜 비밀). 발급 → 1회 사용 · 재사용 · 만료(now 주입) ·
    서명/본문 변조 · 다른 비밀 · 형식 깨짐 · 발급 기록 없는 서명 토큰 · 동시 consume 2 스레드 · 발급 뒤 매핑 사용 중지/계정 변경 · 비밀 없음."""
    import threading
    from datetime import UTC, datetime, timedelta

    from lcomfine.app import sso
    from lcomfine.db import conn

    out: list[Result] = []
    with sso_env() as key:
        lid, pw, uid, acc = _sso_user(lab, "sw1")
        # 1. 발급 → consume 1회 · 재사용 거부 · sso_token 행에 토큰 글자 없음
        bad = []
        token, jti = _issue(lid)
        row = conn.q1("select jti::text as jti, user_id, account_id, issued_at, expires_at, used_at from sso_token where jti = %s", (jti,))
        if row is None or row["used_at"] is not None or (row["expires_at"] - row["issued_at"]).total_seconds() != sso.TTL_SECONDS:
            bad.append(f"발급 행 {row}")
        got = _consume(token)
        if (got.get("account_id"), got.get("user_id"), got.get("login_id"), got.get("jti")) != (acc, uid, lid, jti):
            bad.append(f"consume 값 {got}")
        again = _refused(lambda: _consume(token), sso.Invalid)
        if again != "이미 사용한 토큰입니다":
            bad.append(f"재사용 → {again!r} (이미 사용한 토큰 기대)")
        used = conn.q1("select used_at from sso_token where jti = %s", (jti,))["used_at"]
        out.append(res("G-18", "발급 → consume 1회 · 재사용 거부", not bad and used is not None,
                       f"sso_token 1행(유효 {sso.TTL_SECONDS}초 · used_at 채워짐 {used is not None}) · 1회째 통과(계정 · 사용자 일치) · 2회째 「{again}」", bad))
        # 2. 만료 — now 주입: +59초 통과 · +60초 · +61초 거부(거부는 토큰을 태우지 않는다)
        bad = []
        t0 = datetime.now(UTC).replace(microsecond=0)
        tk61, j61 = _issue(lid, now=t0)
        r61 = _refused(lambda: _consume(tk61, now=t0 + timedelta(seconds=61)), sso.Invalid)
        r60 = _refused(lambda: _consume(tk61, now=t0 + timedelta(seconds=60)), sso.Invalid)
        burnt = conn.q1("select used_at from sso_token where jti = %s", (j61,))["used_at"]
        tk59, _ = _issue(lid, now=t0)
        r59 = _refused(lambda: _consume(tk59, now=t0 + timedelta(seconds=59)), sso.Invalid)
        if r61 != "만료된 토큰입니다" or r60 != "만료된 토큰입니다":
            bad.append(f"+61초 {r61!r} · +60초 {r60!r} (만료 기대)")
        if r59 is not None:
            bad.append(f"+59초 {r59!r} (통과 기대)")
        if burnt is not None:
            bad.append("만료 거부가 토큰을 사용 처리했다")
        # 실제 시계: DB 의 만료를 과거로 돌린 토큰(서명은 맞다) — now 없이도 거부
        tkp, jp = _issue(lid, now=t0 - timedelta(seconds=120))
        rp = _refused(lambda: _consume(tkp), sso.Invalid)
        if rp != "만료된 토큰입니다":
            bad.append(f"120초 전 발급 · now 없음 {rp!r}")
        out.append(res("G-18", "만료(60초 · now 주입 61초) 거부", not bad,
                       f"+59초 통과 · +60초 「{r60}」 · +61초 「{r61}」 · 120초 전 발급(지금 시계) 「{rp}」 · 거부한 토큰 used_at 그대로", bad))
        # 3. 변조 · 다른 비밀 · 형식 깨짐 — 전부 sso.Invalid(다른 예외 0) · 원 토큰은 태워지지 않는다
        base, jb = _issue(lid)
        body, sig = base.split(".")
        payload = json.loads(__import__("base64").urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        other_acc = dict(payload, sub=f"{lab.prefix}other-acc")
        long_ttl = dict(payload, exp=payload["iat"] + 3600)
        forged_jti = dict(payload, jti=str(uuid.uuid4()))
        flip = sig[:-1] + ("A" if sig[-1] != "A" else "B")
        cases = [
            ("서명 끝 글자 변조", f"{body}.{flip}", "서명이 맞지 않습니다"),
            ("서명 빈 칸", f"{body}.", "토큰 형식이 아닙니다"),
            ("본문 변조(계정 ID 바꿈 · 옛 서명)", f"{_b64(other_acc)}.{sig}", "서명이 맞지 않습니다"),
            ("본문 변조(만료 1시간 · 옛 서명)", f"{_b64(long_ttl)}.{sig}", "서명이 맞지 않습니다"),
            ("다른 비밀로 서명(같은 본문)", f"{body}.{_sign_with(secrets.token_urlsafe(32), body)}", "서명이 맞지 않습니다"),
            ("다른 비밀로 서명(위조 본문)", f"{_b64(other_acc)}.{_sign_with('q3-other-' + secrets.token_hex(8), _b64(other_acc))}", "서명이 맞지 않습니다"),
            ("맞는 비밀 · 유효 1시간 본문", f"{_b64(long_ttl)}.{_sign_with(key, _b64(long_ttl))}", "토큰 형식이 아닙니다"),
            ("맞는 비밀 · 발급 기록 없는 jti", f"{_b64(forged_jti)}.{_sign_with(key, _b64(forged_jti))}", "발급 기록이 없는 토큰입니다"),
            ("맞는 비밀 · 다른 계정 ID(같은 jti)", f"{_b64(other_acc)}.{_sign_with(key, _b64(other_acc))}", None),
            ("alg none 꼴(점 하나 · 서명 없음)", body, "토큰 형식이 아닙니다"),
            ("점 3개(JWT 꼴)", f"eyJhbGciOiJub25lIn0.{body}.{sig}", "토큰 형식이 아닙니다"),
            ("빈 글자", "", "토큰 형식이 아닙니다"),
            ("한글", "토큰.서명", "토큰 형식이 아닙니다"),
            ("NUL", f"{body}\x00.{sig}", "토큰 형식이 아닙니다"),
            ("공백 덧붙임", f" {base} ", "토큰 형식이 아닙니다"),
            ("= 패딩", f"{body}==.{sig}", "토큰 형식이 아닙니다"),
            ("3000자", "a" * 1500 + "." + "b" * 1500, "토큰 형식이 아닙니다"),
            ("본문 JSON 아님(서명 맞음)", f"{_b64({'x': 1})[:-2]}QQ.{_sign_with(key, _b64({'x': 1})[:-2] + 'QQ')}", "토큰 형식이 아닙니다"),
            ("숫자 아닌 글자 타입", None, "토큰 형식이 아닙니다"),
            ("bytes", base.encode(), "토큰 형식이 아닙니다"),
        ]
        bad = []
        for label, tk, want in cases:
            got = _refused(lambda tk=tk: _consume(tk), sso.Invalid)
            if want is None:            # 다른 계정 ID 로 서명을 맞춰도 그 jti 의 발급 행 계정과 달라 사용 처리되지 않아야 한다
                if got is None or got.startswith("X:"):
                    bad.append(f"{label} → {got!r} (거부 기대)")
            elif got != want:
                bad.append(f"{label} → {got!r} ({want!r} 기대)")
        still = conn.q1("select used_at from sso_token where jti = %s", (jb,))["used_at"]
        ok_base = _refused(lambda: _consume(base), sso.Invalid) is None
        out.append(res("G-18", "서명 변조 · 본문 변조 · 다른 비밀 · 형식 깨짐 거부", not bad and still is None and ok_base,
                       f"사례 {len(cases)} 전부 sso.Invalid(다른 예외 0) · 거부 뒤 원 토큰 used_at 그대로 {still is None} · 원 토큰 그 뒤 1회 통과 {ok_base}", bad))
        # 4. 동시 consume — 2 스레드 × 5 회, 매번 하나만 통과
        bad = []
        for i in range(5):
            tk, _ = _issue(lid)
            gate_ = threading.Barrier(2)
            got_: list = []

            def worker(tk=tk, gate_=gate_, got_=got_):
                gate_.wait()
                got_.append(_refused(lambda: _consume(tk), sso.Invalid))

            ths = [threading.Thread(target=worker) for _ in range(2)]
            for t in ths:
                t.start()
            for t in ths:
                t.join(30)
            if sorted(map(str, got_)) != ["None", "이미 사용한 토큰입니다"]:
                bad.append(f"{i + 1}회 {got_}")
        out.append(res("G-18", "동시 consume(스레드 2) 하나만", not bad, f"5회 × 2 스레드 — 매번 통과 1 · 「이미 사용한 토큰입니다」 1 · 어긋남 {len(bad)}", bad))
        # 5. 발급 뒤 매핑 사용 중지 · 계정 ID 변경 → 미사용 토큰 consume 거부
        bad = []
        tka, _ = _issue(lid)
        conn.x("update doc_account_map set active = false where user_id = %s", (uid,))
        ra = _refused(lambda: _consume(tka), sso.Invalid)
        ia = _refused(lambda: _issue(lid), sso.NotMapped)
        conn.x("update doc_account_map set active = true where user_id = %s", (uid,))
        tkb, _ = _issue(lid)
        conn.x("update doc_account_map set account_id = %s where user_id = %s", (acc + "-2", uid))
        rb = _refused(lambda: _consume(tkb), sso.Invalid)
        conn.x("update doc_account_map set account_id = %s where user_id = %s", (acc, uid))
        if ra != "문서관리 계정 매핑이 사용 중지되었습니다":
            bad.append(f"사용 중지 뒤 consume {ra!r}")
        if ia != "문서관리 계정 매핑이 사용 중지되었습니다":
            bad.append(f"사용 중지 뒤 issue {ia!r}")
        if rb != "발급 뒤 문서관리 계정 매핑이 바뀌었습니다":
            bad.append(f"계정 ID 변경 뒤 consume {rb!r}")
        out.append(res("G-18", "발급 뒤 매핑 사용 중지 · 계정 변경 → 미사용 토큰 거부", not bad,
                       f"사용 중지 → consume 「{ra}」 · issue 「{ia}」 / 계정 ID 변경 → consume 「{rb}」", bad))
    # 6. 비밀 없음 — 발급도 검증도 하지 않는다(서명 없는 토큰을 만들지 않는다)
    with sso_env() as key:
        tk_live, _ = _issue(lid)
    with sso_env(secret=False):
        ri = _refused(lambda: _issue(lid), sso.NotConfigured)
        rc = _refused(lambda: _consume(tk_live), sso.NotConfigured)
        conf = sso.configured()
    n_before = _tokens_of(uid)
    ok = ri is not None and not ri.startswith("X:") and rc is not None and not rc.startswith("X:") and not conf
    out.append(res("G-18", "비밀 없음 → 발급 · 검증 안 함(NotConfigured)", ok,
                   f"issue 「{ri}」 · consume 「{rc}」 · configured() {conf} · 토큰 행 {n_before}(늘지 않음)"))
    return out


def check_sso_http(lab: Lab) -> list[Result]:
    """G-18 화면 경로 — DOC-010 `POST /doc/go`(F-DOC-011) · `GET /doc/go`(F-DOC-012). 토큰이 hidden 1곳 말고 어디에도 없다 ·
    GET 은 발급하지 않는다 · 비활성(SYS-010) 직후 발급 거부 · 미매핑/사용 중지 매핑 422 · 주소/비밀 없음 422 미확정 (D-517) · SSO 로그 · SYS-040."""
    import base64
    import logging

    from lcomfine.app import sso
    from lcomfine.db import conn

    out: list[Result] = []
    HTML, JSN = {"accept": "text/html"}, {"accept": "application/json"}
    adm = lab.client("ADM")
    calls: list[tuple[str, bool, str | None]] = []       # (login_id, 성공 기대, jti) — SSO 로그 대조용
    t_start = conn.q1("select now() as t")["t"]
    a0 = _max_access_id()
    # 서버 로그(프로세스 안) — 모든 logger 의 기록을 잡아 토큰 글자를 찾는다
    records: list[str] = []

    class _Grab(logging.Handler):
        def emit(self, rec):
            try:
                records.append(f"{rec.name} {rec.getMessage()}")
            except Exception:  # noqa: BLE001 — 형식이 깨진 기록도 원문으로 남겨 검색한다
                records.append(f"{rec.name} {rec.msg!r} {rec.args!r}")

    grab, root = _Grab(level=logging.DEBUG), logging.getLogger()
    old_level = root.level
    root.addHandler(grab)
    root.setLevel(logging.DEBUG)
    try:
        with sso_env():
            lid, pw, uid, acc = _sso_user(lab, "swweb", role="SL")
            c = login(lid, pw)
            # 1. 브라우저 POST → 200 같은 화면 · 자동 POST 폼 · hidden 1곳
            r = c.post("/doc/go", headers=HTML, follow_redirects=False)
            hid = _hidden_tokens(r.text)
            token = hid[0] if len(hid) == 1 else ""
            calls.append((lid, True, None))
            bad = []
            if r.status_code != 200 or len(hid) != 1:
                bad.append(f"POST(html) {r.status_code} · hidden 토큰 {len(hid)}")
            form = re.search(r"<form[^>]*data-auto-submit[^>]*>", r.text)
            ftxt = form.group(0) if form else ""
            if not (form and 'method="post"' in ftxt and f'action="{SSO_FAKE_URL}"' in ftxt):
                bad.append(f"자동 POST 폼 {ftxt!r}")
            if token:
                sig = token.split(".")[1]
                body_cnt, sig_cnt = r.text.count(token), r.text.count(sig)
                hdrs = " ".join(f"{k}: {v}" for k, v in r.headers.items())
                if body_cnt != 1 or sig_cnt != 1:
                    bad.append(f"본문 안 토큰 {body_cnt}회 · 서명 {sig_cnt}회 (1 기대)")
                if token in hdrs or sig in hdrs:
                    bad.append("응답 헤더(Location · Set-Cookie 등)에 토큰")
                if token in str(r.url) or "token=" in str(r.url):
                    bad.append(f"주소에 토큰 {r.url}")
                ck = " ".join(f"{k}={v}" for k, v in c.cookies.items())
                decoded = ""
                for v in c.cookies.values():
                    try:
                        decoded += base64.urlsafe_b64decode(v.split(".")[0] + "==").decode("utf-8", "replace")
                    except Exception:  # noqa: BLE001 — 쿠키 꼴이 달라도 원문 검색은 한다
                        pass
                if sig in ck or sig in decoded or token in decoded:
                    bad.append("세션 쿠키에 토큰")
                if "no-store" not in r.headers.get("cache-control", ""):
                    bad.append(f"Cache-Control {r.headers.get('cache-control')!r} (no-store 기대)")
                if r.headers.get("referrer-policy") not in ("same-origin", "no-referrer", "strict-origin"):
                    bad.append(f"Referrer-Policy {r.headers.get('referrer-policy')!r}")
            # JSON 응답 — 토큰 없음(jti 만)
            rj = c.post("/doc/go", headers=JSN)
            calls.append((lid, True, None))
            jbody = rj.text
            if rj.status_code != 200 or "token" in rj.json() or _TOKEN_RE.search(jbody):
                bad.append(f"JSON {rj.status_code} — 토큰 꼴 글자 {bool(_TOKEN_RE.search(jbody))} · 키 {sorted(rj.json())}")
            jj = rj.json().get("jti")
            jrow = conn.q1("select user_id, used_at from sso_token where jti::text = %s", (jj,)) if jj else None
            if not jrow or jrow["user_id"] != uid:
                bad.append(f"JSON jti 의 발급 행 {jrow}")
            calls[-1] = (lid, True, jj)
            # 토큰은 문서관리 쪽 규칙(consume)으로 1회 통과
            if token:
                got = _refused(lambda: _consume(token), sso.Invalid)
                if got is not None:
                    bad.append(f"폼 토큰 consume {got!r}")
            # DB · 로그 어디에도 토큰 평문 · 서명 없음
            if token:
                hits = _token_in_db([token, token.split(".")[1]])
                if hits:
                    bad.append(f"DB 에 토큰 글자 {hits}")
                logs_txt = " ".join(records)
                if token in logs_txt or token.split(".")[1] in logs_txt:
                    bad.append("서버 로그(logging)에 토큰")
                acc_rows = conn.q("select x::text as t from sys_access_log x where log_id > %s", (a0,))
                chg_rows = conn.q("select x::text as t from sys_change_log x where login_id = %s", (lid,))
                if any(token.split(".")[1] in a["t"] for a in acc_rows + chg_rows):
                    bad.append("접근 · 변경 로그에 서명")
            n_tables = conn.q1("select count(*) as n from information_schema.tables where table_schema = 'public' and table_type = 'BASE TABLE'")["n"]
            out.append(res("G-18", "토큰 평문 = HTML hidden 1곳뿐", not bad and bool(token),
                           f"POST(html) 200 · 자동 POST 폼(method post · action 가짜 주소 · data-auto-submit) · 본문 안 토큰 1회 · 헤더 · 주소 · 세션 쿠키 0 · "
                           f"JSON 200 키 {sorted(rj.json()) if rj.status_code == 200 else '-'}(토큰 꼴 0) · DB 표 {n_tables} 전수 · 접근/변경 로그 · "
                           f"logging {len(records)}건 — 토큰 · 서명 0 · Cache-Control no-store · Referrer-Policy {r.headers.get('referrer-policy')}", bad))
            # 2. 주소창 — GET 은 발급하지 않는다 · 쿼리의 token 은 무시 · 바로가기 폼은 method post
            bad = []
            before = _tokens_of(uid)
            g1 = c.get("/doc/go", headers=HTML)
            g2 = c.get("/doc/go", params={"token": "q3-" + secrets.token_hex(8)}, headers=HTML)
            g3 = c.get("/doc/go", headers=JSN)
            after = _tokens_of(uid)
            if after != before:
                bad.append(f"GET 이 토큰을 발급했다 {before} → {after}")
            for name, g in (("GET", g1), ("GET ?token", g2)):
                if g.status_code != 200 or _hidden_tokens(g.text) or (g is g2 and "q3-" in g.text):
                    bad.append(f"{name} {g.status_code} · hidden {len(_hidden_tokens(g.text))}")
            fm = re.search(r'<form method="post" action="/doc/go"[^>]*>', g1.text)
            if not fm:
                bad.append("DOC-010 바로가기 폼이 method post 가 아니다")
            app_js = (ROOT / "src/lcomfine/app/static/app.js").read_text(encoding="utf-8")
            js_ok = "form[data-auto-submit]" in app_js and ".submit()" in app_js and not re.search(r"location\s*=|window\.open\(|\.href\s*=", app_js)
            if not js_ok:
                bad.append("app.js 자동 제출이 form.submit() 이 아니다(주소 이동 · window.open)")
            gp = r.headers.get("location")
            out.append(res("G-18", "토큰이 주소창에 없다(GET 발급 0 · POST 폼)", not bad,
                           f"GET /doc/go ×3(쿼리 token 포함) 발급 {after - before} · hidden 0 · 바로가기 폼 method post · 발급 응답 Location {gp!r} · "
                           f"app.js `form[data-auto-submit]` → form.submit() (주소 이동 0) · JSON GET {g3.status_code}", bad))
            # 3. 비활성 — SYS-010(F-SYS-013) 직후 발급 거부 · 이미 받은 미사용 토큰 거부 · 잠금도
            bad = []
            dl, dpw, duid, _ = _sso_user(lab, "swdeac", role="SL")
            dc = login(dl, dpw)
            rr = dc.post("/doc/go", headers=HTML)
            calls.append((dl, True, None))
            held = (_hidden_tokens(rr.text) or [""])[0]
            n0 = _tokens_of(duid)
            dz = adm.post(f"/sys/users/{duid}/delete")
            p1 = dc.post("/doc/go", headers=JSN).status_code             # 세션 401 — 로그 없음(로그인 전 단계)
            g1d = dc.get("/doc/go").status_code
            relog = new_client().post("/login", data={"login_id": dl, "password": dpw}, follow_redirects=False).status_code
            iss = _refused(lambda: _issue(dl), sso.NotMapped)
            con = _refused(lambda: _consume(held), sso.Invalid) if held else "토큰 없음"
            n1 = _tokens_of(duid)
            st = conn.q1("select status from sys_user where user_id = %s", (duid,))["status"]
            if dz.status_code != 200 or st != "중지":
                bad.append(f"비활성 {dz.status_code} · 상태 {st}")
            if (p1, g1d) != (401, 401) or relog == 303:
                bad.append(f"비활성 뒤 POST {p1} · GET {g1d} · 다시 로그인 {relog}")
            if not iss or not iss.startswith("비활성 사용자"):
                bad.append(f"issue {iss!r}")
            if not con or not con.startswith("비활성 사용자"):
                bad.append(f"이미 받은 토큰 consume {con!r}")
            if n1 != n0:
                bad.append(f"비활성 뒤 토큰 행 {n0} → {n1}")
            # 잠금(SYS-012)
            kl, kpw, kuid, _ = _sso_user(lab, "swlock", role="SL")
            tk_lock, _ = _issue(kl)
            ru = adm.post(f"/sys/users/{kuid}", data={"login_id": kl, "user_name": "QA3 임시 잠금 (예시)", "role_code": "SL", "status": "잠금"})
            il = _refused(lambda: _issue(kl), sso.NotMapped)
            cl = _refused(lambda: _consume(tk_lock), sso.Invalid)
            if ru.status_code != 200 or not (il or "").startswith("비활성") or not (cl or "").startswith("비활성"):
                bad.append(f"잠금 {ru.status_code} · issue {il!r} · consume {cl!r}")
            out.append(res("G-18", "비활성(SYS-010 직후) 발급 거부 · 받은 미사용 토큰 거부", not bad,
                           f"F-SYS-013 {dz.status_code}(상태 {st}) → 그 세션 POST /doc/go {p1} · GET {g1d} · 다시 로그인 {relog} · "
                           f"sso.issue 「{iss}」 · 이미 받은 토큰 「{con}」 · 토큰 행 {n0} → {n1} / 잠금(SYS-012) issue 「{il}」 · consume 「{cl}」", bad))
            # 4. 미매핑 · 사용 중지 매핑 → 422 「관리자에게 계정 연결을 요청하세요」 · 발급 0
            bad = []
            meas = []
            for tag, kw in (("swnomap", {"mapped": False}), ("swoffmap", {"active": False})):
                ul, upw, uuid_, _ = _sso_user(lab, tag, role="SL", **kw)
                uc = login(ul, upw)
                pj = uc.post("/doc/go", headers=JSN)
                calls.append((ul, False, None))
                ph = uc.post("/doc/go", headers=HTML, follow_redirects=False)
                calls.append((ul, False, None))
                gh = uc.get("/doc/go", headers=HTML)
                msg = pj.json().get("message", "") if pj.headers.get("content-type", "").startswith("application/json") else ""
                fields = pj.json().get("fields", []) if msg else []
                n = _tokens_of(uuid_)
                meas.append(f"{tag}: JSON {pj.status_code} 「{msg[:60]}」 · html {ph.status_code} · 토큰 {n} · GET 안내 {sso.REQUEST_MAPPING in gh.text}")
                if pj.status_code != 422 or sso.REQUEST_MAPPING not in msg or not any(f.get("name") == "계정 매핑" for f in fields):
                    bad.append(f"{tag} JSON {pj.status_code} {msg!r}")
                if ph.status_code >= 500 or _hidden_tokens(ph.text) or (ph.status_code == 200 and sso.REQUEST_MAPPING not in ph.text):
                    bad.append(f"{tag} html {ph.status_code}")
                if n or sso.REQUEST_MAPPING not in gh.text or 'action="/doc/go"' in gh.text:
                    bad.append(f"{tag} 토큰 {n} · GET 안내 {sso.REQUEST_MAPPING in gh.text} · 진입 폼 {'action=\"/doc/go\"' in gh.text}")
            out.append(res("G-18", "미매핑 · 사용 중지 매핑 → 422 「관리자에게 계정 연결을 요청하세요」 · 발급 0", not bad, " / ".join(meas), bad))
        # 5. 주소 없음 / 비밀 없음 / 둘 다 없음 → 422 미확정 (D-517) · 발급 0 · GET 안내
        bad, meas = [], []
        for label, kw in (("주소 없음", {"url": False}), ("비밀 없음", {"secret": False}), ("둘 다 없음", {"url": False, "secret": False})):
            with sso_env(**kw):
                ul, upw, uuid_, _ = _sso_user(lab, "swcfg" + str(len(meas)), role="SL")
                uc = login(ul, upw)
                pj = uc.post("/doc/go", headers=JSN)
                calls.append((ul, False, None))
                ph = uc.post("/doc/go", headers=HTML, follow_redirects=False)
                calls.append((ul, False, None))
                gh = uc.get("/doc/go", headers=HTML)
                msg = pj.json().get("message", "") if pj.status_code == 422 else pj.text[:80]
                n = _tokens_of(uuid_)
                meas.append(f"{label}: JSON {pj.status_code} 「{msg[:70]}」 · html {ph.status_code}"
                            f"{' → ' + ph.headers.get('location', '') if ph.status_code == 303 else ''} · 토큰 {n} · GET 「미확정 (D-517)」 {'미확정 (D-517)' in gh.text}")
                if pj.status_code != 422 or "미확정 (D-517)" not in msg or "토큰을 발급하지 않았습니다" not in msg:
                    bad.append(f"{label} JSON {pj.status_code} {msg!r}")
                if ph.status_code >= 500 or _hidden_tokens(ph.text):
                    bad.append(f"{label} html {ph.status_code}")
                if n or "미확정 (D-517)" not in gh.text or _hidden_tokens(gh.text) or 'action="/doc/go"' in gh.text:
                    bad.append(f"{label} 토큰 {n} · GET 안내")
        out.append(res("G-18", "주소 없음 · 비밀 없음 → 422 「미확정 (D-517)」 · 발급 0", not bad, " / ".join(meas), bad))
        # 6. 지금 설정(.env 그대로 — 주소 없음) 의 화면
        g_now = lab.client("SL").get("/doc/go", headers=HTML)
        p_now = lab.client("SL").post("/doc/go", headers=JSN)
        calls.append((lab.users["SL"][0], False, None))
        now_ok = g_now.status_code == 200 and "미확정 (D-517)" in g_now.text and p_now.status_code == 422 and "미확정 (D-517)" in p_now.json().get("message", "")
        out.append(res("G-18", "지금 설정(.env · 주소 없음) → 화면 「미확정 (D-517)」", now_ok,
                       f"주소 설정 {bool(get_settings().doc_sso_url)} · GET /doc/go {g_now.status_code} 「미확정 (D-517)」 {'미확정 (D-517)' in g_now.text} · "
                       f"POST {p_now.status_code} 「{p_now.json().get('message', '')[:60] if p_now.status_code == 422 else ''}」"))
        # 7. SSO 로그 — 호출마다 1행(사용자 · 시각 · 성공/실패 · 사유) · 성공은 target sso_token:<jti> · 실패도
        bad = []
        by_user: dict[str, list] = {}
        for l_, okx, j in calls:
            by_user.setdefault(l_, []).append((okx, j))
        n_ok = n_fail = 0
        for l_, want in by_user.items():
            rows = _sso_logs(l_, a0)
            if len(rows) != len(want):
                bad.append(f"{l_[-6:]} 호출 {len(want)} · 로그 {len(rows)}")
                continue
            for (okx, j), rw in zip(want, rows):
                good = (rw["result"] == ("성공" if okx else "실패") and rw["login_id"] == l_ and rw["logged_at"] is not None
                        and rw["logged_at"] >= t_start and rw["screen_id"] == "DOC-010" and rw["function_id"] == "F-DOC-011"
                        and rw["path"] == "/doc/go" and rw["method"] == "POST" and (rw["detail"] or "")
                        and ((rw["target"] or "").startswith("sso_token:") if okx else rw["target"] is None)
                        and (j is None or rw["target"] == f"sso_token:{j}"))
                n_ok += okx
                n_fail += not okx
                if not good:
                    bad.append(f"{l_[-6:]} 로그 {dict((k, rw[k]) for k in ('result', 'target', 'detail'))}")
        out.append(res("G-18", "SSO 로그 — 호출마다 sys_access_log 1행(사용자 · 시각 · 성공/실패)", not bad,
                       f"POST /doc/go {len(calls)}회(성공 {n_ok} · 실패 {n_fail}) = SSO 로그 {n_ok + n_fail}행 · login_id · logged_at · result · detail(사유) · "
                       f"성공 target sso_token:<jti>(JSON jti 일치) · 세션 401(비활성 뒤)은 로그인 전 단계라 SSO 로그 0", bad))
        # 8. SYS-040 SSO 탭
        page = adm.get("/sys/logs", params={"tab": "sso", "login": lid}, headers=HTML)
        page_f = adm.get("/sys/logs", params={"tab": "sso", "login": lab.users["SL"][0]}, headers=HTML)
        seen_ok = page.status_code == 200 and lid in page.text and "성공" in page.text and (jj or "?") in page.text
        seen_fail = page_f.status_code == 200 and "실패" in page_f.text and "미확정 (D-517)" in page_f.text
        out.append(res("G-18", "SYS-040 SSO 탭에 보인다(성공 · 실패)", seen_ok and seen_fail,
                       f"ADM GET /sys/logs?tab=sso&login=<성공 사용자> {page.status_code} · 사용자 · 성공 · jti 보임 {seen_ok} / "
                       f"<실패 사용자> {page_f.status_code} · 실패 · 사유 「미확정 (D-517)」 보임 {seen_fail}"))
    finally:
        root.removeHandler(grab)
        root.setLevel(old_level)
    return out


_SSO_SERVER = r"""
import logging, sys, urllib.request
def _blocked(*a, **k):
    raise RuntimeError("QA3 — 바깥 호출 차단")
urllib.request.urlopen = _blocked
logging.basicConfig(level=logging.DEBUG, stream=sys.stderr, format="%(levelname)s %(name)s %(message)s")
import uvicorn
uvicorn.run("lcomfine.app.main:app", host="127.0.0.1", port=int(sys.argv[1]), log_level="debug", access_log=True)
"""


def check_sso_server_log(lab: Lab, port: int = 8037) -> Result:
    """G-18 서버 로그 — 앱을 하위 프로세스 uvicorn(로그 debug · access log 켬 · 가짜 주소 · 가짜 비밀 · 바깥 호출 차단)으로 띄워
    실제 HTTP 로 발급받고, 그 프로세스의 stdout/stderr 전체에 토큰 · 서명 글자가 없는지 본다. 로그 파일은 임시 폴더 · 끝에 지운다."""
    import tempfile
    import urllib.request

    import httpx

    lid, pw, uid, _ = _sso_user(lab, "swsrv", role="SL")
    tmp = Path(tempfile.mkdtemp(prefix="qa3-sso-"))
    logf = tmp / "server.log"
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), LCOMFINE_OPENAI_API_KEY="", LCOMFINE_DOC_SSO_URL=SSO_FAKE_URL,
               **{SSO_ENV[1]: secrets.token_urlsafe(32)})          # 가짜 비밀(실행마다 난수) — 키 이름을 글자로 붙여 쓰지 않는다(G-21 스캔)
    with open(logf, "wb") as fh:
        server = subprocess.Popen([sys.executable, "-c", _SSO_SERVER, str(port)], cwd=ROOT, env=env, stdout=fh, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    token, status, lines = "", None, 0
    try:
        for _ in range(60):
            try:
                if urllib.request.urlopen(base + "/health", timeout=2).status == 200:
                    break
            except Exception:  # noqa: BLE001 — 기동 대기
                time.sleep(0.5)
        else:
            return res("G-18", "서버 로그(uvicorn debug · access)에 토큰 없음", False, "하위 프로세스 앱이 뜨지 않았다")
        with httpx.Client(base_url=base, follow_redirects=False, timeout=10) as hc:
            r = hc.post("/login", data={"login_id": lid, "password": pw})
            if r.status_code != 303:
                return res("G-18", "서버 로그(uvicorn debug · access)에 토큰 없음", False, f"로그인 {r.status_code}")
            r = hc.post("/doc/go", headers={"accept": "text/html"})
            status = r.status_code
            hid = _hidden_tokens(r.text)
            token = hid[0] if len(hid) == 1 else ""
            hc.post("/doc/go", headers={"accept": "application/json"})
    finally:
        server.terminate()
        server.wait(timeout=10)
    text = logf.read_text(encoding="utf-8", errors="replace")
    lines = text.count("\n")
    access_seen = "POST /doc/go" in text
    leak = bool(token) and (token in text or token.split(".")[1] in text)
    for f in tmp.iterdir():
        f.unlink()
    tmp.rmdir()
    ok = status == 200 and bool(token) and access_seen and not leak
    return res("G-18", "서버 로그(uvicorn debug · access)에 토큰 없음", ok,
               f"하위 프로세스 uvicorn(log debug · access log) · POST /doc/go(html) {status} · hidden 토큰 {'1' if token else '0'} · "
               f"서버 로그 {lines}줄(access 줄 「POST /doc/go」 {access_seen}) — 토큰 · 서명 글자 {'있음' if leak else '0'} · 로그 파일은 지웠다")


def _xlsx_doc(rows: list[list], headers=("사번", "문서관리 계정 ID"), *, text_formulas: bool = True) -> bytes:
    return xlsx_bytes(list(headers), rows, text_formulas=text_formulas)


def _xlsx_patch(data: bytes, old: bytes, new: bytes, member: str = "xl/worksheets/sheet1.xml") -> bytes:
    """xlsx 안의 XML 글자를 바꾼다 — openpyxl 이 쓸 수 없는 날 NUL · 깨진 XML 을 만든다."""
    zin, buf = zipfile.ZipFile(io.BytesIO(data)), io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zout:
        for it in zin.infolist():
            b = zin.read(it.filename)
            if it.filename == member:
                b = b.replace(old, new)
            zout.writestr(it, b)
    return buf.getvalue()


def check_doc_map(lab: Lab) -> list[Result]:
    """G-18 DOC-020 — 1:1 깨짐 422 · 엑셀 일괄(이상 파일 · 수식 셀 · NUL · 오류 행 하나면 전체 거부) · 저장 글자 이스케이프."""
    from lcomfine.db import conn

    out: list[Result] = []
    adm = lab.client("ADM")
    adm_lid = lab.users["ADM"][0]
    p = lab.prefix
    users = [lab.make_user("SL", f"dwm{i}") for i in range(6)]          # (login_id, pw, user_id)

    def my_maps() -> int:
        return conn.q1("select count(*) as n from doc_account_map m join sys_user u on u.user_id = m.user_id where u.login_id like %s",
                       (p + "dwm%",))["n"]

    # 1. 1:1
    bad = []
    a, b_ = users[0], users[1]
    r1 = adm.post("/doc/account-map", data={"user_id": str(a[2]), "account_id": f"{p}acc-a"})
    since = _max_change_id()
    cases = [
        ("같은 사용자에 두 번째 계정", {"user_id": str(a[2]), "account_id": f"{p}acc-a2"}, "MES 사용자"),
        ("다른 사용자에 같은 계정", {"user_id": str(b_[2]), "account_id": f"{p}acc-a"}, "문서관리 계정 ID"),
    ]
    got_ = []
    for label, body, field_ in cases:
        r = adm.post("/doc/account-map", data=body)
        got_.append(f"{label} {r.status_code}")
        if r.status_code != 422 or not any(f.get("name") == field_ for f in r.json().get("fields", [])):
            bad.append(f"{label} {r.status_code} {r.text[:120]}")
    mid_a = r1.json().get("id") if r1.status_code == 200 else None
    # 사용 중지 매핑도 자리를 차지한다
    adm.post(f"/doc/account-map/{mid_a}", data={"account_id": f"{p}acc-a", "use_yn": "N"})
    r = adm.post("/doc/account-map", data={"user_id": str(b_[2]), "account_id": f"{p}acc-a"})
    got_.append(f"사용 중지 매핑의 계정 {r.status_code}")
    if r.status_code != 422:
        bad.append(f"사용 중지 매핑의 계정 ID 재사용 {r.status_code}")
    r2 = adm.post("/doc/account-map", data={"user_id": str(b_[2]), "account_id": f"{p}acc-b"})
    mid_b = r2.json().get("id") if r2.status_code == 200 else None
    r = adm.post(f"/doc/account-map/{mid_b}", data={"account_id": f"{p}acc-a", "use_yn": "Y"})
    got_.append(f"수정으로 남의 계정 {r.status_code}")
    if r.status_code != 422:
        bad.append(f"수정으로 남의 계정 ID {r.status_code}")
    r = adm.post(f"/doc/account-map/{mid_b}", data={"user_id": str(a[2]), "account_id": f"{p}acc-b", "use_yn": "Y"})
    got_.append(f"수정으로 사용자 바꿈 {r.status_code}")
    if r.status_code != 422:
        bad.append(f"수정으로 MES 사용자 바꿈 {r.status_code}")
    rows_ = conn.q("select u.login_id, m.account_id, m.active from doc_account_map m join sys_user u on u.user_id = m.user_id "
                   "where u.login_id like %s order by 1", (p + "dwm%",))
    if [(x["account_id"], x["active"]) for x in rows_] != [(f"{p}acc-a", False), (f"{p}acc-b", True)]:
        bad.append(f"매핑 행 {rows_}")
    if len(_changes_since(since, adm_lid)) != 2:      # 성공한 쓰기 = 사용 중지(022) 1 + 등록(021) 1
        bad.append(f"변경 로그 {len(_changes_since(since, adm_lid))}행 (2 기대 — 성공한 쓰기만)")
    out.append(res("G-18", "DOC-020 1:1 깨짐 → 422(항목 이름) · 사용 중지 매핑도 자리 차지", r1.status_code == 200 and not bad,
                   f"등록 {r1.status_code} · " + " · ".join(got_) + f" · 행 {len(rows_)} 그대로 · 변경 로그 = 성공 2만", bad))
    # 2. 엑셀 — 이상 파일
    good_rows = [[users[2][0], f"{p}x-2"], [users[3][0], f"{p}x-3"]]
    good = _xlsx_doc(good_rows)
    big = b"PK" + b"\x00" * (5 * 1024 * 1024)
    files = [
        ("0 바이트", b""), ("텍스트(csv)", "사번,문서관리 계정 ID\nsl,x\n".encode()), ("HTML", b"<html><script>alert(1)</script></html>"),
        ("zip(엑셀 아님)", _zip_not_xlsx()), ("PNG 머리", b"\x89PNG\r\n\x1a\n" + b"\x00" * 64), ("5MB 초과", big),
        ("헤더 없음(열 이름 다름)", _xlsx_doc(good_rows, headers=("login", "account"))), ("헤더만", _xlsx_doc([])),
        ("날 NUL 이 든 시트 XML", _xlsx_patch(good, f"{p}x-2".encode(), f"{p}x\x00-2".encode())),
        ("깨진 시트 XML(닫는 태그 없음)", _xlsx_patch(good, b"</sheetData>", b"")),
        ("시트 XML 이 XML 아님", _xlsx_patch(good, b"<sheetData>", b"<sheetData><<<")),
        ("5001행", _xlsx_doc([[f"{p}n{i}", f"{p}n{i}"] for i in range(5001)])),
    ]
    bad, meas = [], []
    before = my_maps()
    for label, data in files:
        since = _max_change_id()
        r = adm.post("/doc/account-map", files={"file": (f"{p} {label} (예시).xlsx", data, XLSX_MIME)})
        meas.append(f"{label} {r.status_code}")
        if r.status_code != 422:
            bad.append(f"{label} {r.status_code} (422 기대){' — 500!' if r.status_code >= 500 else ''}")
        elif not r.json().get("fields"):
            bad.append(f"{label} 422 인데 fields 없음")
        if _changes_since(since, adm_lid):
            bad.append(f"{label} 변경 로그 생김")
    if my_maps() != before:
        bad.append(f"이상 파일 뒤 매핑 {before} → {my_maps()}")
    out.append(res("X-12", "DOC-020 엑셀 — 이상 파일 → 422(500 0) · 등록 0", not bad,
                   f"파일 {len(files)} — " + " · ".join(meas), bad))
    # 3. 셀 내용 — 수식 셀 · NUL 표기 · 오류 행 하나 → 전체 거부(행마다 사유)
    bad, meas = [], []
    mixed = [
        ("수식 셀(=1+1 · 캐시 값 없음)", _xlsx_doc([[users[2][0], f"{p}y-2"], [users[3][0], "=1+1"]], text_formulas=False), "3행"),
        ("_x0000_ 표기(엑셀의 NUL 꼴)", _xlsx_doc([[users[2][0], f"{p}y-2"], [users[3][0], f"{p}a_x0000_b"]]), None),
        ("없는 사번 1행 + 정상 2행", _xlsx_doc([[users[2][0], f"{p}y-2"], [users[3][0], f"{p}y-3"], [f"{p}nobody", f"{p}y-9"]]), "4행"),
        ("파일 안 사번 중복", _xlsx_doc([[users[2][0], f"{p}y-2"], [users[2][0], f"{p}y-3"]]), "3행"),
        ("DB 매핑과 1:1 깨짐(남의 계정)", _xlsx_doc([[users[2][0], f"{p}acc-b"]]), "2행"),
        ("201자 계정 ID", _xlsx_doc([[users[2][0], "가" * 201]]), "2행"),
        ("빈 칸", _xlsx_doc([[users[2][0], f"{p}y-2"], [users[3][0], None]]), "3행"),
    ]
    for label, data, row_name in mixed:
        before = my_maps()
        since = _max_change_id()
        r = adm.post("/doc/account-map", files={"file": (f"{p} (예시).xlsx", data, XLSX_MIME)})
        after = my_maps()
        if row_name is None:          # `_x0000_` 은 openpyxl 이 글자 그대로 읽는다 — 저장되면 그 글자 그대로(NUL 아님)
            stored = conn.q("select account_id from doc_account_map where account_id like %s", (f"{p}%a_x0000_b",))
            meas.append(f"{label} {r.status_code} · 저장 {[s_['account_id'][-9:] for s_ in stored]}")
            if r.status_code >= 500 or any("\x00" in s_["account_id"] for s_ in stored):
                bad.append(f"{label} {r.status_code}")
            if r.status_code == 200:
                conn.x("delete from doc_account_map where user_id = any(%s)", ([users[2][2], users[3][2]],))
            continue
        names = [f.get("name") for f in (r.json().get("fields", []) if r.status_code == 422 else [])]
        meas.append(f"{label} {r.status_code} {names}")
        if r.status_code != 422 or row_name not in names or after != before or _changes_since(since, adm_lid):
            bad.append(f"{label} {r.status_code} · fields {names} · 매핑 {before} → {after}")
    # 정상 파일 2행 → 200 · 2건 · 변경 로그 1행 · 저장 글자(= · <script>) 는 값으로 · 화면 이스케이프
    evil = "<script>alert(1)</script>"
    since = _max_change_id()
    r = adm.post("/doc/account-map", files={"file": (f"{p} 정상 (예시).xlsx",
                                                     _xlsx_doc([[users[4][0], f"{p}{evil}"], [users[5][0], '=HYPERLINK("http://evil.example/q3","x")']]),
                                                     XLSX_MIME)})
    chg = _changes_since(since, adm_lid)
    pg = adm.get("/doc/account-map", params={"q": p + "dwm"}, headers={"accept": "text/html"})
    stored = conn.q("select account_id from doc_account_map where user_id = any(%s) order by account_id", ([users[4][2], users[5][2]],))
    esc_ok = pg.status_code == 200 and evil not in pg.text and "&lt;script&gt;alert(1)&lt;/script&gt;" in pg.text
    if r.status_code != 200 or r.json().get("count") != 2 or len(chg) != 1 or chg[0]["function_id"] != "F-DOC-021" or len(stored) != 2 or not esc_ok:
        bad.append(f"정상 파일 {r.status_code} {r.text[:100]} · 변경 로그 {len(chg)} · 저장 {len(stored)} · 이스케이프 {esc_ok}")
    out.append(res("X-12", "DOC-020 엑셀 — 수식 셀 · 오류 행 하나 → 전체 거부(행마다 사유) · 정상 2행 등록 · 이스케이프", not bad,
                   " · ".join(meas) + f" / 정상 2행 {r.status_code}(count {r.json().get('count') if r.status_code == 200 else '-'}) · 변경 로그 {len(chg)}행 · "
                   f"`<script>` · `=HYPERLINK` 계정 ID 는 글자로 저장 · DOC-020 화면 이스케이프 {esc_ok}", bad))
    return out


def check_doc_access(lab: Lab) -> list[Result]:
    """G-19 DOC 2 화면 × 8 · 쓰기 F-DOC-011(권한 예외) · 021~023(ADM 만) × 8 / G-20 비활성 · 로그아웃 401 / G-22 쓰기 성공마다 1행 · 422 0행."""
    from lcomfine.app import contracts, rbac
    from lcomfine.db import conn

    out: list[Result] = []
    cells = {(sid, rc): lv for sid, rc, lv in contracts.permission_cells()}
    bad, counts = [], {"200": 0, "403": 0}
    for r in rbac.roles():
        c = lab.client(r.code)
        for sid, path in (("DOC-010", "/doc/go"), ("DOC-020", "/doc/account-map")):
            want = 200 if cells.get((sid, r.code)) else 403
            got = c.get(path).status_code
            counts[str(want)] += 1
            if got != want:
                bad.append(f"{sid}×{r.code} {got} ({want} 기대)")
        html = c.get("/", headers={"accept": "text/html"}).text
        if not cells.get(("DOC-020", r.code)) and 'href="/doc/account-map"' in html:
            bad.append(f"메뉴 {r.code}: 칸 없는 DOC-020 링크")
    lv = {r.code: (cells.get(("DOC-010", r.code)) or "-") + "/" + (cells.get(("DOC-020", r.code)) or "-") for r in rbac.roles()}
    out.append(res("G-19", "DOC 2 화면 × 부서 8 (200/403 · 메뉴)", not bad,
                   f"200 기대 {counts['200']} · 403 기대 {counts['403']} · 칸(DOC-010/020) {lv} · 어긋남 {len(bad)}", bad))
    # 쓰기 4 × 부서 8 (빈 본문) — 칸 없으면 403 · F-DOC-011 은 칸이 있으면 통과(지금 .env = 주소 없음 → 422) · 021~023 은 W(ADM)만
    bad, meas = [], []
    for fid, path in (("F-DOC-011", "/doc/go"), ("F-DOC-021", "/doc/account-map"), ("F-DOC-022", "/doc/account-map/0"),
                      ("F-DOC-023", "/doc/account-map/0/delete")):
        f = contracts.function(fid)
        got_by = {}
        for r in rbac.roles():
            since = _max_change_id()
            got = lab.client(r.code).post(path, data={}).status_code
            got_by[r.code] = got
            expect_403 = (rbac.level(r.code, f.screen_id) is None) if f.permission_exception else (r.code not in f.roles_w)
            if expect_403 and got != 403:
                bad.append(f"{fid}×{r.code} {got} (403 기대)")
            if not expect_403 and (got in (401, 403) or got >= 500):
                bad.append(f"{fid}×{r.code} {got} (통과 기대)")
            if _changes_since(since, lab.users[r.code][0]):
                bad.append(f"{fid}×{r.code} 실패 쓰기에 변경 로그")
        meas.append(f"{fid} " + " ".join(f"{k}{v}" for k, v in got_by.items()))
    out.append(res("G-19", "DOC 쓰기 4 × 부서 8 (F-DOC-011 권한 예외 · 021~023 ADM 만)", not bad, " / ".join(meas), bad))
    # G-20 — 비활성 · 로그아웃 → DOC GET · POST 401
    bad = []
    adm = lab.client("ADM")
    sl, slpw, sluid = lab.make_user("SL", "dw20a")
    c = login(sl, slpw)
    a = (c.get("/doc/go").status_code, c.post("/doc/go").status_code)
    z = adm.post(f"/sys/users/{sluid}/delete").status_code
    b = (c.get("/doc/go").status_code, c.post("/doc/go").status_code)
    ad, adpw, _ = lab.make_user("ADM", "dw20b")
    c2 = login(ad, adpw)
    a2 = (c2.get("/doc/account-map").status_code, c2.post("/doc/account-map", data={}).status_code)
    c2.post("/logout", follow_redirects=False)
    b2 = (c2.get("/doc/account-map").status_code, c2.post("/doc/account-map", data={}).status_code,
          c2.post("/doc/account-map/0/delete").status_code, c2.post("/doc/go").status_code)
    if a[0] != 200 or z != 200 or b != (401, 401):
        bad.append(f"비활성 전 {a} · 비활성 {z} · 뒤 {b}")
    if a2 != (200, 422) or b2 != (401, 401, 401, 401):
        bad.append(f"로그아웃 전 {a2} · 뒤 {b2}")
    out.append(res("G-20", "DOC 비활성 · 로그아웃 → 401", not bad,
                   f"SL 비활성 전 GET/POST /doc/go {a} · F-SYS-013 {z} → {b} / ADM 로그아웃 전 DOC-020 GET · 빈 POST {a2} → 뒤 GET · 021 · 023 · 011 {b2}", bad))
    # G-22 — 쓰기 성공마다 변경 로그 1행 · 422 → 0행 · DOC 화면 조회 → 접근 로그
    bad, meas = [], []
    adm_lid = lab.users["ADM"][0]
    u1 = lab.make_user("SL", "dw22a")
    u2 = lab.make_user("SL", "dw22b")
    p = lab.prefix
    since = _max_change_id()
    r0 = adm.post("/doc/account-map", data={"user_id": str(u1[2]), "account_id": f"{p}d22-a"})
    rows0 = _changes_since(since, adm_lid)
    meas.append(f"F-DOC-021 {r0.status_code}→{len(rows0)}행")
    if r0.status_code != 200 or len(rows0) != 1 or rows0[0]["function_id"] != "F-DOC-021":
        bad.append(f"F-DOC-021 {r0.status_code} · 변경 로그 {len(rows0)}행 (1 기대)")
    mid = r0.json().get("id") if r0.status_code == 200 else 0
    seq = [
        ("F-DOC-022", f"/doc/account-map/{mid}", {"account_id": f"{p}d22-a2", "use_yn": "Y"}, 200),
        ("F-DOC-022", f"/doc/account-map/{mid}", {"account_id": "", "use_yn": "Y"}, 422),
        ("F-DOC-022", f"/doc/account-map/{mid}", {"account_id": "a\x00b", "use_yn": "Y"}, 422),
        ("F-DOC-022", "/doc/account-map/999999999999", {"account_id": "x", "use_yn": "Y"}, 404),
        ("F-DOC-021", "/doc/account-map", {"user_id": "abc", "account_id": "x"}, 422),
        ("F-DOC-021", "/doc/account-map", {"user_id": "99999999999999999999", "account_id": "x"}, 422),
        ("F-DOC-021", "/doc/account-map", {"user_id": str(u2[2]), "account_id": "가" * 201}, 422),
        ("F-DOC-023", f"/doc/account-map/{mid}/delete", {}, 200),
        ("F-DOC-023", f"/doc/account-map/{mid}/delete", {}, 404),
        ("F-DOC-023", "/doc/account-map/abc/delete", {}, 404),
    ]
    for fid, path, body, want in seq:
        since = _max_change_id()
        r = adm.post(path, data=body)
        rows = _changes_since(since, adm_lid)
        n_want = 1 if want == 200 else 0
        meas.append(f"{fid} {r.status_code}→{len(rows)}행")
        if r.status_code != want or len(rows) != n_want or (rows and rows[0]["function_id"] != fid):
            bad.append(f"{fid} {path[-12:]} {r.status_code} ({want} 기대) · 변경 로그 {len(rows)}행 ({n_want} 기대)")
    # F-DOC-011 성공 1 · 거부(미매핑) 0
    with sso_env():
        conn.x("insert into doc_account_map (user_id, account_id, created_by) values (%s, %s, 'qa3')", (u2[2], f"{p}d22-b"))
        c3 = login(u2[0], u2[1])
        since = _max_change_id()
        r = c3.post("/doc/go")
        rows = _changes_since(since, u2[0])
        meas.append(f"F-DOC-011 {r.status_code}→{len(rows)}행")
        if r.status_code != 200 or len(rows) != 1 or rows[0]["function_id"] != "F-DOC-011" or rows[0]["target"] != f"sso_token:{r.json().get('jti')}":
            bad.append(f"F-DOC-011 성공 {r.status_code} · 변경 로그 {rows}")
        conn.x("update doc_account_map set active = false where user_id = %s", (u2[2],))
        since = _max_change_id()
        r = c3.post("/doc/go")
        rows = _changes_since(since, u2[0])
        meas.append(f"F-DOC-011(사용 중지) {r.status_code}→{len(rows)}행")
        if r.status_code != 422 or rows:
            bad.append(f"F-DOC-011 거부 {r.status_code} · 변경 로그 {len(rows)}행")
    # 화면 조회 로그
    lid = lab.users["ADM"][0]
    for path, sid in (("/doc/go", "DOC-010"), ("/doc/account-map", "DOC-020")):
        b0 = conn.q1("select count(*) as n from sys_access_log where login_id = %s and log_type = '조회' and screen_id = %s", (lid, sid))["n"]
        st = adm.get(path).status_code
        b1 = conn.q1("select count(*) as n from sys_access_log where login_id = %s and log_type = '조회' and screen_id = %s", (lid, sid))["n"]
        meas.append(f"GET {sid} {st} 조회 로그 +{b1 - b0}")
        if st != 200 or b1 - b0 != 1:
            bad.append(f"GET {sid} {st} · 조회 로그 +{b1 - b0}")
    out.append(res("G-22", "DOC 쓰기 성공 → 변경 로그 1행 · 422/404 → 0행 · 조회 로그", not bad, " · ".join(meas), bad))
    return out


# ── D-524 · DEF-QA3-003 — 앱 DB 역할 재검증 (한 트랜잭션 · 되돌림) ─────────────
class _RoleRollback(Exception):
    pass


def check_db_role() -> list[Result]:
    """`roles.apply` 로 역할을 만들고 `set local role` 로 그 역할이 되어 잰다 — 끝에 트랜잭션을 되돌려 클러스터에 역할 0.
    불변 이력 · 감사 로그 6 표 UPDATE/DELETE/TRUNCATE 거부 · session_replication_role 거부 · DDL 거부 · 카탈로그 비밀 · 서버 파일 거부 ·
    업무 쓰기(bigserial 시퀀스) · v_dq_* 읽기 · 데이터 질의 읽기 전용 실행이 그 역할로 돈다."""
    import psycopg

    from lcomfine.app import dataquery
    from lcomfine.db import conn, roles

    role = "lcomfine_app_q3" + secrets.token_hex(3)
    meas: dict = {}
    bad: list[str] = []

    def denied(cur, stmt, params=(), *, errs=(psycopg.errors.InsufficientPrivilege,)) -> bool:
        cur.execute("savepoint q3")
        try:
            cur.execute(stmt, params)
        except errs:
            cur.execute("rollback to savepoint q3")
            return True
        except psycopg.Error as e:
            cur.execute("rollback to savepoint q3")
            bad.append(f"{stmt[:50]} → {type(e).__name__}(권한 거부 아님)")
            return False
        cur.execute("rollback to savepoint q3")
        return False

    def allowed(cur, stmt, params=()):
        cur.execute("savepoint q3")
        try:
            cur.execute(stmt, params)
            rows = cur.fetchall() if cur.description else []
            cur.execute("release savepoint q3")
            return rows
        except psycopg.Error as e:
            cur.execute("rollback to savepoint q3")
            bad.append(f"허용 기대 {stmt[:60]} → {type(e).__name__}: {str(e)[:80]}")
            return None

    try:
        with conn.tx() as cur:
            out = roles.apply(cur, role, secrets.token_urlsafe(18))
            cur.execute("select rolsuper, rolcreatedb, rolcreaterole, rolbypassrls, rolreplication, rolinherit, rolcanlogin from pg_roles where rolname = %s", (role,))
            meas["attrs"] = dict(cur.fetchone())
            cur.execute("select count(*) as n from pg_auth_members m join pg_roles r on r.oid = m.member where r.rolname = %s", (role,))
            meas["member_of"] = cur.fetchone()["n"]
            cur.execute("select count(*) as n from pg_tables where schemaname = 'public' and tableowner = %s", (role,))
            meas["owns"] = cur.fetchone()["n"]
            meas["tables"] = out["tables"]
            cur.execute("select table_name from information_schema.views where table_schema = 'public' and table_name like 'v_dq_%%' order by 1")
            dq_views = [r["table_name"] for r in cur.fetchall()]
            cur.execute(f'set local role "{role}"')
            cur.execute("select current_user as u, (select rolsuper from pg_roles where rolname = current_user) as su")
            meas["whoami"] = dict(cur.fetchone())
            # 불변 이력 · 감사 로그 6 표
            cols = {}
            for t in roles.APPEND_ONLY:
                cur.execute("select column_name from information_schema.columns where table_schema = 'public' and table_name = %s "
                            "and is_generated = 'NEVER' and is_identity = 'NO' order by ordinal_position limit 1 offset 1", (t,))
                cols[t] = cur.fetchone()["column_name"]
            ap = {}
            for t in roles.APPEND_ONLY:
                ap[t] = (denied(cur, f'update "{t}" set "{cols[t]}" = "{cols[t]}"'),       # where 없이 — 권한 검사가 먼저
                         denied(cur, f'delete from "{t}"'),
                         denied(cur, f'truncate "{t}"'),
                         denied(cur, f'select 1 from "{t}" for update limit 1'))
            meas["append_only"] = ap
            # 이 역할이 넣은 로그 행도 지우지 못한다 (INSERT 는 된다)
            ins = allowed(cur, "insert into sys_access_log (log_type, login_id, result, detail) values ('조회', %s, '성공', 'QA3 D-524 (예시)') returning log_id", (role,))
            meas["log_insert"] = bool(ins)
            if ins:
                meas["log_delete_own"] = denied(cur, "delete from sys_access_log where log_id = %s", (ins[0]["log_id"],))
            # 트리거 끄기 · DDL · 권한 올리기 · 카탈로그 비밀 · 서버 파일
            deny = {
                "session_replication_role=replica": denied(cur, "set local session_replication_role = replica"),
                "alter table … disable trigger": denied(cur, "alter table stock_adjust disable trigger all"),
                "create table": denied(cur, "create table q3_role_probe (id int)"),
                "drop table": denied(cur, "drop table stock_adjust"),
                "alter table add column": denied(cur, "alter table customer add column q3x int"),
                "create function": denied(cur, "create function q3f() returns int language sql as 'select 1'"),
                "create schema": denied(cur, "create schema q3s"),
                # `set role 소유자` · `set session authorization` 은 이 방법으로 잴 수 없다 — 검사는 세션 사용자(로컬 superuser)의 자격을 보기 때문.
                # 실 로그인(lcomfine_app 으로 접속)에서만 의미가 있다 → D-525 실기동 때 잰다(보고서 §9).
                "set_config(session_replication_role)": denied(cur, "select set_config('session_replication_role', 'replica', true)"),
                "select pg_authid": denied(cur, "select rolpassword from pg_authid limit 1"),
                "pg_read_file": denied(cur, "select pg_read_file('postgresql.conf')"),
                "copy … to 파일": denied(cur, "copy (select 1) to '/tmp/q3_role_probe.txt'"),
                "copy … from program": denied(cur, "copy customer from program 'true'"),
                "lo_import": denied(cur, "select lo_import('/etc/hosts')"),
                "create database": denied(cur, "create database q3_role_probe_db", errs=(psycopg.errors.InsufficientPrivilege, psycopg.errors.ActiveSqlTransaction)),
            }
            # GRANT 는 오류 없이 경고만 낸다(가진 권한이 없으면 「no privileges were granted」) — 실제로 권한이 늘었는지를 본다
            cur.execute(f'grant update, delete on sys_change_log to "{role}"')
            cur.execute("select has_table_privilege(%s, 'sys_change_log', 'UPDATE') or has_table_privilege(%s, 'sys_change_log', 'DELETE') as g",
                        (role, role))
            deny["grant (자기에게) — 권한 늘지 않음"] = cur.fetchone()["g"] is False
            meas["deny"] = deny
            # 업무 쓰기 — 시퀀스(bigserial) · update · delete
            p = "q3role" + secrets.token_hex(3)
            ins = allowed(cur, "insert into customer (customer_code, customer_name, created_by) values (%s, %s, 'qa3') returning id", (p, f"{p} (예시)"))
            cid = ins[0]["id"] if ins else None
            upd = allowed(cur, "update customer set customer_name = %s where id = %s returning id", (f"{p} 수정 (예시)", cid)) if cid else None
            dl = allowed(cur, "delete from customer where id = %s returning id", (cid,)) if cid else None
            seq = allowed(cur, "select count(*) as n from information_schema.usage_privileges where grantee = %s and object_type = 'SEQUENCE'", (role,))
            meas["business"] = {"insert": bool(ins), "update": bool(upd), "delete": bool(dl), "seq_grants": seq[0]["n"] if seq else None}
            # 채번 표(sys_number_seq)는 갱신이 필요하다
            meas["number_seq_update"] = allowed(cur, "update sys_number_seq set last_value = last_value where false") is not None
            # v_dq_* 읽기
            reads = {}
            for v in dq_views:
                r_ = allowed(cur, f'select count(*) as n from "{v}"')
                reads[v] = r_[0]["n"] if r_ else None
            meas["v_dq"] = reads
            # 데이터 질의 실행 계층 — 검증 통과 SQL 을 읽기 전용 · statement_timeout 으로 이 역할이 돌린다(_run_readonly 와 같은 설정)
            sql_ok = "select request_no, qty from v_dq_orders limit 5"
            sql_ok = dataquery.validate_sql(sql_ok, dataquery.allowed_views("EX"))      # 검증을 통과한 SQL 만 돌린다
            cur.execute(f"set local statement_timeout = {int(dataquery.STATEMENT_TIMEOUT_MS)}")
            cur.execute("set local transaction_read_only = on")
            ro = allowed(cur, sql_ok)
            ro_write = denied(cur, "insert into customer (customer_code, customer_name) values ('q3ro', 'q3ro')", errs=(psycopg.errors.ReadOnlySqlTransaction,))
            cur.execute("show transaction_read_only")
            meas["dq"] = {"rows": None if ro is None else len(ro), "read_only_write_refused": ro_write, "ro": cur.fetchone()["transaction_read_only"],
                          "timeout_ms": int(dataquery.STATEMENT_TIMEOUT_MS)}
            raise _RoleRollback
    except _RoleRollback:
        pass
    left = conn.q1("select count(*) as n from pg_roles where rolname like 'lcomfine_app_q3%%'")["n"]
    a = meas.get("attrs", {})
    out_rows: list[Result] = []
    ok_attrs = a and not any(a[k] for k in ("rolsuper", "rolcreatedb", "rolcreaterole", "rolbypassrls", "rolreplication")) and a["rolcanlogin"] \
        and meas.get("member_of") == 0 and meas.get("owns") == 0 and meas.get("whoami", {}).get("su") is False
    out_rows.append(res("X-11", "D-524 앱 역할 속성 — superuser · 소유자 · 역할 상속 아님", bool(ok_attrs),
                        f"roles.apply 표 {meas.get('tables')} · 속성 {a} · 소속 역할 {meas.get('member_of')} · 소유 표 {meas.get('owns')} · set local role 뒤 superuser {meas.get('whoami', {}).get('su')}"))
    ap = meas.get("append_only", {})
    ap_bad = [f"{t} {v}" for t, v in ap.items() if not all(v)]
    out_rows.append(res("X-11", "D-524 불변 이력 · 감사 로그 6 표 UPDATE/DELETE/TRUNCATE/FOR UPDATE 거부 · INSERT 만", len(ap) == 6 and not ap_bad
                        and meas.get("log_insert") and meas.get("log_delete_own"),
                        f"표 {len(ap)} × (update · delete · truncate · for update) 전부 InsufficientPrivilege {not ap_bad} · sys_access_log insert {meas.get('log_insert')} · "
                        f"자기가 넣은 행 delete 거부 {meas.get('log_delete_own')}", ap_bad))
    dn = meas.get("deny", {})
    dn_bad = [k for k, v in dn.items() if not v]
    out_rows.append(res("X-11", "D-524 트리거 끄기 · DDL · 권한 올리기 · 카탈로그 비밀 · 서버 파일 거부", bool(dn) and not dn_bad,
                        f"{len(dn)} 시도 — " + " · ".join(f"{k} {'거부' if v else '통과!'}" for k, v in dn.items()), dn_bad))
    bz, dq = meas.get("business", {}), meas.get("dq", {})
    vd = meas.get("v_dq", {})
    ok_b = bz.get("insert") and bz.get("update") and bz.get("delete") and (bz.get("seq_grants") or 0) > 0 and meas.get("number_seq_update") \
        and vd and all(v is not None for v in vd.values()) and dq.get("rows") is not None and dq.get("read_only_write_refused") and dq.get("ro") == "on"
    out_rows.append(res("X-11", "D-524 그 역할로 업무 쓰기 · 시퀀스 · v_dq_* 읽기 · 데이터 질의 읽기 전용 실행", bool(ok_b),
                        f"customer insert(bigserial)/update/delete {bz.get('insert')}/{bz.get('update')}/{bz.get('delete')} · 시퀀스 권한 {bz.get('seq_grants')} · "
                        f"sys_number_seq update {meas.get('number_seq_update')} · v_dq_* {len(vd)} 읽기 {vd} · 질의(읽기 전용 · timeout {dq.get('timeout_ms')}ms) 행 {dq.get('rows')} · "
                        f"읽기 전용 중 쓰기 ReadOnlySqlTransaction {dq.get('read_only_write_refused')}"))
    out_rows.append(res("X-11", "D-524 되돌림 → 클러스터에 시험 역할 0", left == 0 and not bad, f"남은 lcomfine_app_q3* 역할 {left}", bad))
    return out_rows


def check_db_role_static() -> list[Result]:
    """앱 코드가 그 역할로 돌 수 있는가(정적) — 불변 6 표에 UPDATE/DELETE/TRUNCATE · 런타임 DDL · session_replication_role 이 없다.
    compose 두 벌 — `app` = lcomfine_app · `seed` = 소유자(`docker compose config` 출력 · 비밀 값은 찍지 않는다)."""
    from urllib.parse import urlparse

    import yaml

    from lcomfine.db import roles

    out: list[Result] = []
    hits = []
    pat_ap = re.compile(r"\b(update\s+(%s)\b|delete\s+from\s+(%s)\b|truncate\s+(table\s+)?(%s)\b)" % (("|".join(roles.APPEND_ONLY),) * 3), re.I)
    pat_ddl = re.compile(r"\b(create\s+(table|index|view|function|role|schema)\s+\w|alter\s+(table|role|system)\s+\w|drop\s+(table|view|role)\s+\w|session_replication_role|"
                         r"grant\s+(select|insert|update|delete|all|usage)\b|revoke\s+(select|insert|update|delete|all|usage|create)\b)", re.I)
    files = sorted((ROOT / "src/lcomfine/app").rglob("*.py"))
    for f in files:
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            s_ = line.split("#", 1)[0]
            if pat_ap.search(s_) or pat_ddl.search(s_):
                hits.append(f"{f.relative_to(ROOT)}:{i}")
    out.append(res("X-11", "정적: 앱 코드(src/lcomfine/app) — 불변 6 표 UPDATE/DELETE/TRUNCATE · 런타임 DDL · GRANT · replica 0", not hits,
                   f"파일 {len(files)} · 걸린 줄 {len(hits)}", hits))
    # compose 두 벌 — docker compose config (값은 메모리에서만 · 사용자 이름만 본다)
    bad, meas = [], []
    for rel in ("docker-compose.yml", "deploy/hostinger/docker-compose.yml"):
        cmd = ["docker", "compose", "-f", rel, "--project-directory", str(ROOT), "config", "--format", "json"]
        try:
            pr = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as exc:
            bad.append(f"{rel}: docker compose 실행 실패 {type(exc).__name__}")
            continue
        if pr.returncode != 0:
            # 오류 문장에는 값이 없다(변수 이름만) — 첫 줄만
            bad.append(f"{rel}: config rc {pr.returncode} {pr.stderr.strip().splitlines()[-1][:120] if pr.stderr.strip() else ''}")
            continue
        cfg = json.loads(pr.stdout)
        svc = cfg.get("services", {})
        users = {}
        for name in ("app", "seed"):
            dsn_ = (svc.get(name, {}).get("environment") or {}).get("LCOMFINE_PG_DSN") or ""
            users[name] = urlparse(dsn_).username
        app_pw_env = "LCOMFINE_APP_DB_PASSWORD" in (svc.get("seed", {}).get("environment") or {})
        app_has_owner = any(k == "LCOMFINE_DB_PASSWORD" for k in (svc.get("app", {}).get("environment") or {}))
        db_user = (svc.get("db", {}).get("environment") or {}).get("POSTGRES_USER")
        seed_cmd = " ".join(svc.get("seed", {}).get("command") or [])
        meas.append(f"{rel}: app={users['app']} · seed={users['seed']} · db POSTGRES_USER={db_user} · seed 에 앱 비밀번호 변수 {app_pw_env} · "
                    f"seed command docker_init {('docker_init.py' in seed_cmd)} · app 에 소유자 비밀번호 {app_has_owner}")
        if users["app"] != "lcomfine_app" or users["seed"] != db_user or not app_pw_env or "docker_init.py" not in seed_cmd or app_has_owner:
            bad.append(f"{rel}: app {users['app']} · seed {users['seed']} (소유자 {db_user})")
        # 원문(YAML) 에서도 확인 — app 서비스의 DSN 사용자
        raw = yaml.safe_load((ROOT / rel).read_text(encoding="utf-8"))
        rdsn = ((raw.get("services", {}).get("app", {}).get("environment") or {}).get("LCOMFINE_PG_DSN") or "")
        if "lcomfine_app:" not in rdsn:
            bad.append(f"{rel}: 원문 app DSN 이 lcomfine_app 이 아니다")
    di = (ROOT / "tools/docker_init.py").read_text(encoding="utf-8")
    di_ok = "roles.apply(" in di and "LCOMFINE_APP_DB_PASSWORD" in di
    if not di_ok:
        bad.append("docker_init.py 가 roles.apply 를 부르지 않는다")
    out.append(res("G-24", "compose 두 벌 — app = lcomfine_app · seed = 소유자 (D-524 · 정적)", not bad,
                   " / ".join(meas) + f" · docker_init roles.apply {di_ok} · 실기동은 D-525", bad))
    return out


#: W4 E2E — 전산 관리자 DOC-020 · 영업부 DOC-010(지금 .env = 주소 없음 → `미확정 (D-517)` 화면)
E2E_W4 = (("admin", "/doc/account-map"), ("sl", "/doc/go"))
E2E_W4_WANT = {("admin", "/doc/account-map"): "미연결 사용자", ("sl", "/doc/go"): "미확정 (D-517)"}


# ── 판정표 ──────────────────────────────────────────────────────────────
def run_all(run_seeds: bool = False) -> list[Result]:
    rows: list[Result] = []

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
        # W2 수금 (COL)
        rows += guard("G-19", "COL 화면·쓰기 × 부서 8", check_col_access, lab)
        rows += guard("G-20", "COL 비활성·로그아웃 401", check_col_sessions, lab)
        rows += guard("G-22", "COL 쓰기 4 변경 로그", check_col_change_log, lab)
        rows += guard("X-05", "COL 업로드 보안", check_col_upload_abuse, lab)
        # W3 대시보드 · 데이터 질의 (RPT) — AI 는 fake · 실제 호출 차단
        rows += guard("G-19", "RPT 화면 9 · 질의 실행 × 부서 8", check_rpt_access, lab)
        rows += guard("G-16", "데이터 질의 우회 시도", check_dataquery_bypass, lab)
        rows += guard("G-17", "키 없음 · 호출 실패", check_ai_key_missing, lab)
        rows += guard("G-22", "RPT 변경 로그", check_rpt_change_log, lab)
        rows += guard("X-09", "대시보드 이스케이프", check_rpt_escape, lab)
        # W4 문서 SSO (DOC) — 가짜 주소(.invalid) · 가짜 비밀 · 외부 전송 0
        rows += guard("G-18", "SSO 토큰 규칙", check_sso_token, lab)
        rows += guard("G-18", "SSO 화면 경로", check_sso_http, lab)
        rows += guard("G-18", "SSO 서버 로그", check_sso_server_log, lab)
        rows += guard("G-18", "DOC-020 계정 매핑", check_doc_map, lab)
        rows += guard("G-19", "DOC 화면 · 쓰기 × 부서 8", check_doc_access, lab)
    rows += guard("X-08", "COL 정적", check_col_static)
    rows += guard("X-10", "RPT 정적", check_rpt_static)
    rows += guard("G-21", "seed_dev3 정적", check_seed_dev3_static)
    rows += guard("G-24", "docker", check_docker)
    rows += guard("X-11", "DB 역할 (D-524)", check_db_role)
    rows += guard("X-11", "DB 역할 정적 · compose", check_db_role_static)
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
