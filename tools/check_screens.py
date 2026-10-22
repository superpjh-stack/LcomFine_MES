#!/usr/bin/env python
"""QA1 기능 · 계약 전수 (W1 · W2 · W3 · W4) — `uv run python tools/check_screens.py`. 서버를 띄우지 않고 TestClient 로 앱을 부른다.

기대값은 개발 테스트가 아니라 계약에서 직접 끌어온다:
  · `contracts/function-list.md` (contracts.functions()) — 기능 · API · 권한(W 부서 · R 이상 · 권한 예외)
  · `contracts/permission-matrix.md` (contracts.permission_cells()) — 화면 67 × 부서 8 칸
  · `contracts/ia.json` + `ia-overrides.json` (tools.design_doc.effective()) — 정본 L3 · logic
  · `contracts/api-contract.md` — 오류 계약(422 · 404 · 501 · 403 문장)

검사 (범위 = 기능 136 전부 — W1 109 + W2 COL 11 + W3 RPT 10 + W4 DOC 6 · LATER_MENUS 비움 · placeholder 0 기대):
  G-02  ① 범위 기능의 API 가 라우트에 글자 그대로 ② `@pytest.mark.fn` 표식 ③ 쓰기 라우트의 `require_fn(<그 기능 ID>)` (정적)
  G-03  화면 67 × 계정 8 GET — 칸 W/R → 200 · 칸 없음 → 403 (placeholder 2 포함) · 범위 화면 65 placeholder 0
  G-19  같은 전수의 403 쪽 + 메뉴에 칸 밖 화면 없음 + 쓰기 63 × 계정 8 POST (W → 권한 통과 · R/없음 → 403 · 권한 예외 R 통과 ·
        F-RPT-132 는 칸 없는 부서 403 — api-contract §4) + DB `sys_permission` = 권한 매트릭스
  G-02  오류 계약 (api-contract §1 · §3 · goal §2.7 — QA1 몫): QA1 세계(접두 `QA1-`)를 화면의 HTTP 로 만들고
        쓰기 기능마다 누락 422 · 없는 ID 404 · 미확정 501 · NUL · 자릿수 초과 · 음수 422 를 두드린 뒤 지운다(응답 모양까지).
        W2: (예시) xlsx 를 openpyxl 로 만들어 `POST /col/uploads` 로 올리고(회차 2 · 교체 · 오류 행 · 미매핑 · 알림) 파일 없음 · 엑셀 아닌 파일 ·
        20MB 초과 · 기준 기간 역순 · 날짜 형식 · 매핑 없는 열 · 데이터 행 0 · 거래처 매핑 중복 · 없는 거래처를 두드린다 — 자기 회차 · 매핑만 지운다.
        화면 GET 의 조회 칸에 NUL · 틀린 날짜를 넣어 500 이 아닌지 · 화면 GET 403 의 문장 · 계약의 「미확정 (D-nn)」 이 본문에 보이는지.
        §3 은 따로 한 행 — 422 가 어느 항목인지 짚는가(라우터 선검사 · 핸들러의 「입력」 한 줄이 아님).
  G-02  COL 계약 문장 (정본 L3 · logic · D-516 · D-608) — 세계가 있는 동안 자동 확인: 오류 행 `is-error`(빨간색) · 미매핑 목록 · 교체됨 ·
        매핑 뒤 재반영 · 어음 만기 도래 · 30/60/90 구간 · 출하 대비 나란히 · 매출 열 매핑을 잠깐 지워 COL-050 · COL-060 · TRK-030 · HOME 회계부 카드의
        `미확정 (D-516)` (지운 매핑은 같은 함수 안에서 되돌린다) · TRK-030 수금 칸 ok/미수집 · ERP 업로드 기준일
  G-02  RPT 계약 문장 (W3 · 정본 L3 · logic · D-512 · D-805 · D-806 · D-609 · goal §3.4) — 세계가 있는 동안 자동 확인: RPT 8 화면의 KPI · 차트 · 표 표식 ·
        **인라인 SVG <title> = 같은 숫자의 표 행** · 표는 전부 `grid-wrap`(390 가로 스크롤 0) · 스크립트 0 · `미확정 (D-519)` · `(D-520)` · RPT-060 ERP 업로드 기준일 ·
        RPT-080 일일 · 주간 · 월간 · RPT-130 질문 → SQL → 결과 표 · F-RPT-132 를 `ai.set_client(fake)` 로(실제 OpenAI 호출 0): 거부 SQL 422 「허용되지 않는 질의 — 이유」 ·
        부서 뷰 제한 · 키 없음 · 호출 실패 · 실행 실패 422 · 허용 SQL JSON 200 `http.saved` · 브라우저 같은 화면 200(계약 §2 예외) · 변경 로그 1행 · 로그 행 수 ·
        SYS-040 탭 6(열 = db-schema 컬럼 · 질의 · AI 호출 · ERP 회차가 보임 · 선택지 밖 422) · 좌측 메뉴 「대시보드」. 로그는 QA1 사용자(전략부)로 남겨 끝에 지운다.
  G-02  DOC 계약 문장 (W4 · 정본 L3 · logic · D-514 · D-517 · D-610 · D-611 · 계약 §2 F-DOC-011 예외) — 세계에 QA1 사용자 5 · 매핑 2 를 두고:
        주소 없음 GET 안내 · POST 422 `미확정 (D-517)` · `fake_sso()`(가짜 `.invalid` 주소 · 같은 함수 안에서 되돌림 · 외부 전송 0) 안에서 JSON 200(토큰 없음 · jti) ·
        브라우저 200 자동 POST 폼(hidden 토큰 · data-auto-submit · method post) · sso.consume · 재사용 거부 · 변경 로그 · SSO 로그 · 매핑 없음 · 사용 중지 · 비활성 거부 ·
        DOC-020 L3 · logic · 엑셀 오류 행 하나 → 전체 거부 · 수정 · 삭제/사용 중지 · SYS-040 SSO 탭 · 메뉴 클릭 → 새 창(DEF-QA1-010)
  G-19  F-DOC-011 × 8(권한 예외 · 칸 R 8 통과 · 5xx 0) · F-DOC-021~023 × 8(ADM 만) · 칸 없으면 F-DOC-011 403(rbac.level 을 프로세스 안에서 잠깐 바꿈)
  계약 문장 (참고 — 요약 표에만): 화면 본문(계약 패널 · 메뉴 제외)에 정본 L3 낱말이 보이는가 — 자동 대조라 사람이 판정한다(outputs/qa1-기능계약.md)

출력 행: `G-nn  항목  PASS|FAIL  실측` (tools/gate.py 의 `_ROW_RE`). 종료코드 = FAIL 행 수 (최대 125) — gate.py 는 「종료코드 ≠ 0 인데 FAIL 행이 없으면
도구가 깨진 것」으로 보므로 결함은 전부 G-행으로 찍는다.
비밀번호는 `settings` 에서 읽고 찍지 않는다. 만든 행은 끝에 지운다(불변 이력 행은 정리 트랜잭션 안에서만 replica 로).
"""

from __future__ import annotations

import warnings

warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient`")

import re
import secrets
import sys
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, timedelta
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from lcomfine.app.settings import get_settings  # noqa: E402 — .env 를 먼저 읽는다

LATER_MENUS: tuple[str, ...] = ()            # W4 — 비었다(COL W2 · RPT W3 · DOC W4 가 범위에 들어왔다 · placeholder 0 기대)
SCOPE = "W1·W2·W3·W4"
LOGINS = ("sl", "pr", "sh", "ds", "ac", "st", "ex", "admin")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
#: QA1 ERP 업로드의 기준 기간 — 개발3 1990~1993 · 개발1 1985 · QA2 는 비는 기간을 고른다. 1980 년은 어느 테스트도 쓰지 않는다
ERP_PERIOD = (date(1980, 1, 1), date(1980, 1, 31))
CODE_OF = {"sl": "SL", "pr": "PR", "sh": "SH", "ds": "DS", "ac": "AC", "st": "ST", "ex": "EX", "admin": "ADM"}
HTML = {"accept": "text/html"}
NOID = "999999999"                           # 없는 경로 키
PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
       b"\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")


# ── 공용 ────────────────────────────────────────────────────────────────
def app_and_clients():
    from fastapi.testclient import TestClient

    from lcomfine.app.main import app

    pw = get_settings().seed_password
    if not pw:
        raise SystemExit("LCOMFINE_SEED_PASSWORD 미설정 — `make setup`")
    clients = {}
    for lid in LOGINS:
        c = TestClient(app, raise_server_exceptions=False)
        r = c.post("/login", data={"login_id": lid, "password": pw}, follow_redirects=False)
        if r.status_code != 303:
            raise SystemExit(f"{lid} 로그인 {r.status_code} — 시드를 먼저 돌린다 (`make db-seed`)")
        clients[lid] = c
    return app, clients


def w1_functions():
    """범위 기능 — LATER_MENUS 밖 전부 (W1 109 + W2 COL 11 + W3 RPT 10 + W4 DOC 6 = 136). 이름은 W1 때 것을 그대로 둔다(테스트가 부른다)."""
    from lcomfine.app import contracts

    return [f for f in contracts.functions() if f.menu_code not in LATER_MENUS]


def xlsx_bytes(headers: list[str], rows: list[list]) -> bytes:
    """(예시) ERP 수금현황 xlsx — openpyxl 로 만든다(저장소에 바이너리 없음 · tests/test_dev3_col.py 와 같은 방식)."""
    import io

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _zip_not_xlsx() -> bytes:
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("qa1.txt", "QA1 (예시) — xlsx 가 아닌 zip")
    return buf.getvalue()


def fill(path: str, value: str) -> str:
    return re.sub(r"\{[^}]+\}", value, path)


def jget(r, key: str, default=None):
    try:
        return r.json().get(key, default)
    except Exception:  # noqa: BLE001 — JSON 이 아니면 그 사실이 실측이다
        return default


class _Main(HTMLParser):
    """`<main>` 본문의 글자 · 폼(메서드 · action · 입력 이름 · 유형)과 `<nav class="side">` 의 data-screen 을 모은다."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth_main = 0
        self.in_side = 0
        self.text: list[str] = []
        self.forms: list[dict] = []
        self.menu: set[str] = set()
        self._form: dict | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "main":
            self.depth_main += 1
        if tag == "nav" and "side" in (a.get("class") or "").split():
            self.in_side += 1
        if self.in_side and a.get("data-screen"):
            self.menu.add(a["data-screen"])
        if not self.depth_main:
            return
        if tag == "form":
            self._form = {"method": (a.get("method") or "get").lower(), "action": a.get("action") or "", "inputs": []}
            self.forms.append(self._form)
        elif tag in ("input", "select", "textarea") and self._form is not None and a.get("name"):
            self._form["inputs"].append({"name": a["name"], "type": (a.get("type") or tag).lower()})

    def handle_endtag(self, tag):
        if tag == "main" and self.depth_main:
            self.depth_main -= 1
        if tag == "nav" and self.in_side:
            self.in_side -= 1
        if tag == "form":
            self._form = None

    def handle_data(self, data):
        if self.depth_main:
            self.text.append(data)


def parse(html: str) -> _Main:
    p = _Main()
    p.feed(html)
    return p


# ── 결과 모음 ───────────────────────────────────────────────────────────
@dataclass
class Report:
    rows: list[tuple[str, str, bool, str]] = field(default_factory=list)   # (gate, 항목, ok, 실측)
    details: list[tuple[str, list[str]]] = field(default_factory=list)
    summary: list[tuple[str, str]] = field(default_factory=list)            # (구분, 실측) — 게이트 밖 요약 표
    defects: list[str] = field(default_factory=list)                        # 오류 계약 결함 (종료코드에 센다)

    def add(self, gate: str, item: str, ok: bool, actual: str, bad: list[str] | None = None) -> None:
        self.rows.append((gate, item, bool(ok), actual))
        if bad:
            self.details.append((f"{gate} {item}", bad))


# ── G-02 기능 1:1 ──────────────────────────────────────────────────────
def check_functions(app, rep: Report) -> None:
    from tools.check_trace import all_routes, fn_marks

    fns = w1_functions()
    routes: dict[str, set[str]] = {}
    for path, methods in all_routes(app.routes):
        routes.setdefault(path, set()).update(methods)
    no_route = [f"{f.id} {f.api}" for f in fns if f.method not in routes.get(f.path, set())]
    rep.add("G-02", f"{SCOPE} 기능 {len(fns)} — API 가 라우트에 글자 그대로", not no_route,
            f"라우트 있음 {len(fns) - len(no_route)}/{len(fns)}", no_route)

    marks, errs = fn_marks(sorted((ROOT / "tests").glob("test_*.py")))
    no_mark = [f.id for f in fns if f.id not in marks]
    rep.add("G-02", f"{SCOPE} 기능 {len(fns)} — @pytest.mark.fn 표식", not no_mark and not errs,
            f"표식 있음 {len(fns) - len(no_mark)}/{len(fns)} · 읽지 못한 테스트 {len(errs)}", no_mark + errs)

    # 쓰기 라우트의 의존성이 require_fn(<그 기능 ID>) 인가 — 클로저의 function_id 를 읽는다
    deps: dict[tuple[str, str], list[str]] = {}

    def walk(rts, prefix=""):
        for rt in rts:
            inner = getattr(rt, "original_router", None)
            if inner is not None:
                ctx = getattr(rt, "include_context", None)
                walk(inner.routes, prefix + (getattr(ctx, "prefix", "") or ""))
                continue
            dep = getattr(rt, "dependant", None)
            if dep is None:
                continue
            ids = []
            for d in dep.dependencies:
                call = d.call
                if getattr(call, "__qualname__", "").startswith("require_fn.") and call.__closure__:
                    ids += [c.cell_contents for c in call.__closure__ if isinstance(c.cell_contents, str)]
                if getattr(call, "__qualname__", "").startswith("require_screen.") and call.__closure__:
                    ids += ["screen:" + c.cell_contents for c in call.__closure__ if isinstance(c.cell_contents, str)]
            for m in getattr(rt, "methods", ()) or ():
                deps[(m, prefix + rt.path)] = ids

    walk(app.routes)
    writes = [f for f in fns if f.is_write]
    wrong = [f"{f.id} {f.api} → {deps.get((f.method, f.path))}" for f in writes if deps.get((f.method, f.path)) != [f.id]]
    rep.add("G-19", f"{SCOPE} 쓰기 라우트 {len(writes)} — require_fn(<그 기능 ID>) (정적)", not wrong,
            f"맞음 {len(writes) - len(wrong)}/{len(writes)}", wrong)
    reads = [f for f in fns if not f.is_write]
    rbad = [f"{f.id} {f.api} → {deps.get((f.method, f.path))}" for f in reads
            if not deps.get((f.method, f.path)) or not ({f.id, "screen:" + f.screen_id} & set(deps.get((f.method, f.path))))]
    rep.add("G-19", f"{SCOPE} 조회 라우트 {len(reads)} — require_screen(화면) 또는 require_fn(기능) (정적)", not rbad,
            f"맞음 {len(reads) - len(rbad)}/{len(reads)}", rbad)


# ── G-03 · G-19 화면 GET 전수 ──────────────────────────────────────────
def check_screens(app, clients, rep: Report) -> dict:
    from lcomfine.app import contracts, nav
    from lcomfine.db import conn

    cells = {(sid, rc): lv for sid, rc, lv in contracts.permission_cells()}
    db = {(r["screen_id"], r["role_code"]): r["level"] for r in conn.q("select screen_id, role_code, level from sys_permission")}
    diff = sorted(f"{sid} {rc}: 계약 {cells.get((sid, rc), '·')} · DB {db.get((sid, rc), '·')}"
                  for sid, rc in set(cells) | set(db) if cells.get((sid, rc)) != db.get((sid, rc)))
    rep.add("G-19", "DB sys_permission = 권한 매트릭스 260칸", not diff, f"계약 {len(cells)} · DB {len(db)} · 다름 {len(diff)}", diff)

    screens = [s for s in nav.SCREENS if not s.common]
    ph = set(app.state.placeholder_paths)
    n200 = ok200 = n403 = ok403 = 0
    bad200, bad403, badmsg = [], [], []
    w1_ph = []
    html_of: dict[str, str] = {}
    for s in screens:
        for lid, c in clients.items():
            rc = CODE_OF[lid]
            r = c.get(s.path, headers=HTML, follow_redirects=False)
            if (s.screen_id, rc) in cells:
                n200 += 1
                if r.status_code == 200:
                    ok200 += 1
                    if lid == "admin":
                        html_of[s.screen_id] = r.text
                else:
                    bad200.append(f"{lid} {s.screen_id} {s.path} → {r.status_code}")
            else:
                n403 += 1
                rj = c.get(s.path, follow_redirects=False)
                if r.status_code == 403 and rj.status_code == 403:
                    ok403 += 1
                    if jget(rj, "message") != "이 화면을 볼 권한이 없습니다":
                        badmsg.append(f"{lid} {s.screen_id} message={jget(rj, 'message')!r}")
                else:
                    bad403.append(f"{lid} {s.screen_id} {s.path} → 브라우저 {r.status_code} · JSON {rj.status_code}")
        if s.menu_code not in LATER_MENUS and s.path in ph:
            w1_ph.append(s.screen_id)
    rep.add("G-03", f"화면 {len(screens)} × 계정 {len(clients)} — 칸 W/R → 200", ok200 == n200 and not bad200, f"{ok200}/{n200}", bad200)
    rep.add("G-03", f"화면 {len(screens)} × 계정 {len(clients)} — 칸 없음 → 403 (placeholder 포함)", ok403 == n403,
            f"{ok403}/{n403}", bad403)
    rep.add("G-19", f"칸 밖 화면 GET {n403} → 403 (브라우저 · JSON)", ok403 == n403, f"403 {ok403}/{n403}", bad403)
    by_screen = sorted({b.split()[1] for b in badmsg})
    rep.summary.append(("화면 GET 403 의 문장 = 「이 화면을 볼 권한이 없습니다」 (api-contract §1)",
                        f"다른 문장 {len(badmsg)}/{ok403} — 화면 {len(by_screen)}: {', '.join(by_screen)}" if badmsg else f"전부 같음 {ok403}"))
    if badmsg:
        rep.defects.append(f"[403 문장] 화면 GET 403 인데 「이 기능을 실행할 권한이 없습니다」 — 화면 {len(by_screen)} ({', '.join(by_screen)}) "
                           f"· 예: {badmsg[0]}")
    w1 = [s for s in screens if s.menu_code not in LATER_MENUS]
    rep.add("G-03", f"{SCOPE} 화면 {len(w1)} — placeholder 0 (W4 DOC 2 포함)", not w1_ph,
            f"{SCOPE} placeholder {len(w1_ph)} · 전체 placeholder {len(ph)}", w1_ph)

    # 메뉴 — 칸 밖 화면이 메뉴에 없고, 칸 있는 화면은 메뉴에 있다
    bad_menu = []
    for lid, c in clients.items():
        rc = CODE_OF[lid]
        got = parse(c.get("/", headers=HTML).text).menu
        want = {s.screen_id for s in screens if (s.screen_id, rc) in cells}
        if got - want:
            bad_menu.append(f"{lid}: 칸 밖인데 메뉴에 {sorted(got - want)}")
        if want - got:
            bad_menu.append(f"{lid}: 칸 있는데 메뉴에 없음 {sorted(want - got)}")
    rep.add("G-19", f"메뉴 = 권한 칸 (계정 {len(clients)})", not bad_menu, f"어긋난 계정 {len(bad_menu)}", bad_menu)
    return html_of


# ── G-19 쓰기 기능 POST 전수 ───────────────────────────────────────────
def check_writes(clients, rep: Report) -> list[dict]:
    """빈 본문 · 없는 경로 키(999999999)로 두드린다 — W 부서는 401/403 이 아니고 500 도 아니어야 하고(권한 통과),
    R · 칸 없음은 403 + 「이 기능을 실행할 권한이 없습니다」. 권한 예외 3 은 R 이 통과. 쓰기가 일어나지 않게 빈 본문만 보낸다."""
    from lcomfine.app import contracts

    cells = {(sid, rc): lv for sid, rc, lv in contracts.permission_cells()}
    results = []
    for f in [f for f in w1_functions() if f.is_write]:
        path = fill(f.path, NOID)
        for lid, c in clients.items():
            rc = CODE_OF[lid]
            lv = cells.get((f.screen_id, rc))
            allowed = lv in ("W", "R") if f.permission_exception else lv == "W"
            r = c.post(path, data={}, follow_redirects=False)
            if allowed:
                ok = r.status_code not in (401, 403) and r.status_code < 500
                expect = "권한 통과 (2xx/303/404/422)"
            else:
                ok = r.status_code == 403 and jget(r, "message") == "이 기능을 실행할 권한이 없습니다"
                expect = "403 「이 기능을 실행할 권한이 없습니다」"
            results.append({"fid": f.id, "login": lid, "cell": lv or "·", "path": path, "status": r.status_code,
                            "message": jget(r, "message"), "ok": ok, "expect": expect, "allowed": allowed})
    allowed = [x for x in results if x["allowed"]]
    denied = [x for x in results if not x["allowed"]]
    exc = [x for x in allowed if contracts.function(x["fid"]).permission_exception and x["cell"] == "R"]
    fmt = lambda x: f"{x['fid']} {x['login']}(칸 {x['cell']}) POST {x['path']} → {x['status']} {x['message']!r} · 기대 {x['expect']}"  # noqa: E731
    nfn = len({x["fid"] for x in results})
    rep.add("G-19", f"쓰기 {nfn} × 계정 {len(clients)} — R · 칸 없음 → 403", all(x["ok"] for x in denied),
            f"{sum(x['ok'] for x in denied)}/{len(denied)}", [fmt(x) for x in denied if not x["ok"]])
    rep.add("G-19", f"쓰기 {nfn} × 계정 {len(clients)} — W 부서 권한 통과 (401/403/5xx 아님)", all(x["ok"] for x in allowed),
            f"{sum(x['ok'] for x in allowed)}/{len(allowed)}", [fmt(x) for x in allowed if not x["ok"]])
    rep.add("G-19", "권한 예외 F-HOME-022 · F-RPT-132 · F-DOC-011 — 칸 R 부서 통과", bool(exc) and all(x["ok"] for x in exc),
            f"{sum(x['ok'] for x in exc)}/{len(exc)}", [fmt(x) for x in exc if not x["ok"]])
    # api-contract §4 「권한 예외 쓰기 기능 … 칸이 없으면 → 403」 — RPT-130 은 ST · EX · ADM 만 칸이 있다(permission-matrix)
    exc_denied = [x for x in denied if contracts.function(x["fid"]).permission_exception]
    rep.add("G-19", "권한 예외 F-RPT-132 — 칸 없는 부서 → 403 (api-contract §4)", bool(exc_denied) and all(x["ok"] for x in exc_denied),
            f"{sum(x['ok'] for x in exc_denied)}/{len(exc_denied)} ({' · '.join(sorted({x['login'] for x in exc_denied}))})",
            [fmt(x) for x in exc_denied if not x["ok"]])
    # W4 DOC — F-DOC-011 진입은 8 부서 모두 칸 R(권한 예외 · 5xx 0 — 주소 없으면 422 미확정 D-517) · F-DOC-021~023 은 ADM 만 W
    d11 = [x for x in results if x["fid"] == "F-DOC-011"]
    rep.add("G-19", "F-DOC-011 × 계정 8 — 칸 R 8 부서 전부 통과 · 5xx 0 (권한 예외 · 계약 §2 주소 없음 422)",
            len(d11) == len(clients) and all(x["allowed"] and x["ok"] for x in d11),
            " · ".join(f"{x['login']} {x['status']}" for x in d11), [fmt(x) for x in d11 if not x["ok"]])
    d2x = [x for x in results if x["fid"] in ("F-DOC-021", "F-DOC-022", "F-DOC-023")]
    want = lambda x: x["login"] == "admin"  # noqa: E731 — permission-matrix DOC-020 = ADM W 하나
    rep.add("G-19", "F-DOC-021~023 × 계정 8 — ADM 만 통과 · 나머지 7 → 403",
            len(d2x) == 3 * len(clients) and all(x["ok"] and x["allowed"] == want(x) for x in d2x),
            f"통과 {sorted({x['login'] for x in d2x if x['allowed'] and x['ok']})} · 403 {sum(1 for x in d2x if not x['allowed'] and x['ok'])}/21",
            [fmt(x) for x in d2x if not x["ok"] or x["allowed"] != want(x)])
    rep.add("G-19", *doc_exception_denied(clients))
    return results


def doc_exception_denied(clients) -> tuple:
    """api-contract §4 「권한 예외 쓰기 … 칸이 없으면 → 403」 — DOC-010 은 정본이 8 부서 모두 R 이라 칸 없는 부서가 없다.
    프로세스 안에서만 `rbac.level` 을 잠깐 바꿔 경영진(EX)의 DOC-010 칸을 지운 상태를 흉내 내고(DB · 다른 QA 영향 0) 되돌린다."""
    from lcomfine.app import rbac

    c = clients["ex"]
    real = rbac.level
    rbac.level = lambda role, sid: None if (role, sid) == ("EX", "DOC-010") else real(role, sid)
    try:
        rp = c.post("/doc/go")
        rg = c.get("/doc/go")
        menu = "DOC-010" in parse(c.get("/", headers=HTML).text).menu
    finally:
        rbac.level = real
    back = c.post("/doc/go").status_code
    ok = (rp.status_code == 403 and jget(rp, "message") == "이 기능을 실행할 권한이 없습니다" and rg.status_code == 403 and not menu
          and back not in (401, 403) and back < 500)
    return ("권한 예외 F-DOC-011 — 칸 없는 부서 → 403 (rbac.level 을 프로세스 안에서 잠깐 바꿈 · 되돌린 뒤 통과)", ok,
            f"칸 지움: POST {rp.status_code} {jget(rp, 'message')!r} · GET {rg.status_code} · 메뉴에 DOC-010 {menu} · 되돌린 뒤 POST {back}")


# ── QA1 세계 — 오류 계약을 두드릴 실제 행 (화면이 부르는 HTTP 로 만든다) ─────
class World:
    """`clients` = 로그인한 TestClient 들(`app_and_clients()`). 쓰기는 admin 으로 하고, 만든 QA1 사용자(영업부)로도 로그인해
    `clients["qa1"]` 에 둔다 — HOME-030 처럼 「자기 부서가 받는 이벤트」 가 필요한 사례에 쓴다(전산 관리자는 받는 이벤트가 없다)."""

    def __init__(self, clients: dict | None) -> None:
        self.clients = dict(clients or {})
        self.c = self.clients.get("admin")
        self.p = f"QA1-{uuid.uuid4().hex[:6]}-"
        self.ids: dict[str, object] = {}
        self.steps: list[tuple[str, int, str]] = []    # (단계, 상태, 메시지)

    def post(self, step: str, path: str, data: dict, files=None, key: str | None = None):
        r = self.c.post(path, data=data, files=files)
        self.steps.append((step, r.status_code, str(jget(r, "message"))[:120]))
        if r.status_code != 200:
            return None
        body = r.json()
        return body.get(key) if key else body

    def build(self) -> "World":
        from lcomfine.db import conn

        p, today = self.p, date.today().isoformat()
        due = (date.today() + timedelta(days=10)).isoformat()
        I = self.ids
        I["fg"] = self.post("품목(제품)", "/bas/items", {"item_code": p + "FG", "item_name": p + "제품 (예시)", "item_type": "제품"}, key="id")
        I["rm"] = self.post("품목(원자재)", "/bas/items", {"item_code": p + "RM", "item_name": p + "원자재 (예시)", "item_type": "원자재"}, key="id")
        I["item_x"] = self.post("품목(삭제용)", "/bas/items", {"item_code": p + "X", "item_name": p + "x (예시)", "item_type": "제품"}, key="id")
        I["cust"] = self.post("거래처", "/bas/customers", {"customer_code": p + "C", "customer_name": p + "거래처 (예시)"}, key="id")
        I["wh"] = self.post("창고", "/bas/warehouses", {"target": "warehouse", "warehouse_code": p + "WH", "warehouse_name": p + "창고 (예시)"}, key="id")
        I["loc1"] = self.post("위치1", "/bas/warehouses", {"target": "location", "warehouse_id": str(I["wh"]), "location_code": p + "L1", "location_name": p + "위치1"}, key="id")
        I["loc2"] = self.post("위치2", "/bas/warehouses", {"target": "location", "warehouse_id": str(I["wh"]), "location_code": p + "L2", "location_name": p + "위치2"}, key="id")
        I["spec"] = self.post("제조사양", "/std/spec-sheets", {"item_id": str(I["fg"]), "title": p + "사양", "content": "QA1=1"}, key="id")
        I["std"] = self.post("표준", "/std/standards", {"standard_code": p + "S", "standard_name": p + "표준"}, key="id")
        I["plate"] = self.post("판", "/std/plates", {"plate_code": p + "PL", "plate_name": p + "판", "item_id": str(I["fg"])}, key="id")
        I["art"] = self.post("시안", "/std/artworks", {"item_id": str(I["fg"]), "title": p + "시안"},
                             files={"image": ("qa1.png", PNG, "image/png")}, key="id")
        I["sample"] = self.post("견본서", "/std/sample-sheets", {"item_id": str(I["fg"]), "title": p + "견본", "content": "QA1=1", "issued_on": today}, key="id")
        I["exc"] = self.post("예외제품", "/std/exception-items", {"item_id": str(I["fg"]), "reason": p + "사유"}, key="id")
        I["req"] = self.post("생산의뢰", "/wo/requests", {"customer_id": str(I["cust"]), "item_id": str(I["fg"]), "qty": "100", "due_date": due}, key="id")
        I["wo"] = self.post("생산지시", "/wo/orders", {"request_id": str(I["req"]), "qty": "100", "equipment_code": "EQ01"}, key="id")
        wo_no = conn.q1("select work_order_no from work_order where id = %s", (I["wo"],))["work_order_no"] if I["wo"] else None
        lots = self.post("원자재 입고", "/mat/receipts", {"supplier_name": p + "공급사", "received_on": today, "item_id": [str(I["rm"])],
                                                      "qty": ["50"], "location_id": [str(I["loc1"])], "supplier_lot_no": [""]})
        I["receipt"] = lots and lots.get("receipt_id")
        I["rm_lot"] = lots and lots.get("lot_nos", [None])[0]
        I["rm_lot_id"] = I["rm_lot"] and conn.q1("select id from material_lot where lot_no = %s", (I["rm_lot"],))["id"]
        self.post("입고검사 합격", "/qc/incoming", {"lot_no": I["rm_lot"] or "", "result": "합격"})
        I["issue"] = self.post("불출", "/mat/issues", {"work_order_id": str(I["wo"]), "issued_on": today, "lot_no": [I["rm_lot"] or ""],
                                                    "location_id": [str(I["loc1"])], "qty": ["10"]}, key="issue_id")
        I["pdaily"] = self.post("생산일보", "/prd/daily", {"work_order_id": str(I["wo"]), "work_date": today, "equipment_code": "EQ01",
                                                       "produced_qty": "60", "good_qty": "55", "loss_qty": "5", "run_minutes": "60", "stop_minutes": "0"}, key="daily_id")
        I["idaily"] = self.post("검사일보", "/ins/daily", {"work_order_id": str(I["wo"]), "work_date": today, "inspected_qty": "55", "defect_qty": "0"}, key="daily_id")
        pr = self.post("제품 입고", "/mat/product-receipts", {"work_order_id": str(I["wo"]), "qty": "50", "location_id": str(I["loc1"]), "received_on": today})
        I["preceipt"] = pr and pr.get("product_receipt_id")
        I["plot_id"] = pr and pr.get("product_lot_id")
        I["plot"] = pr and pr.get("lot_no")
        self.post("제품검사 합격", "/qc/product", {"lot_no": I["plot"] or "", "result": "합격"})
        I["move"] = self.post("재고 이동", "/inv/moves", {"lot_kind": "원자재", "lot_no": I["rm_lot"] or "", "from_location_id": str(I["loc1"]),
                                                     "to_location_id": str(I["loc2"]), "qty": "5"}, key="move_id")
        st = conn.q1("select id from lot_stock where lot_kind = '제품' and lot_id = %s and location_id = %s", (I["plot_id"], I["loc1"])) if I["plot_id"] else None
        I["stock"] = st and st["id"]
        I["ship"] = self.post("출하 지시", "/shp/orders", {"customer_id": str(I["cust"]), "due_date": due, "stock_id": [str(I["stock"])], "qty": ["10"]}, key="id")
        I["ship2"] = self.post("출하 지시(확정용)", "/shp/orders", {"customer_id": str(I["cust"]), "due_date": due, "stock_id": [str(I["stock"])], "qty": ["5"]}, key="id")
        if I["ship2"]:
            self.post("출하 확정", f"/shp/confirm/{I['ship2']}/confirm", {})
        I["user_pw"] = secrets.token_urlsafe(12)
        I["user"] = self.post("사용자", "/sys/users", {"login_id": p + "U", "user_name": p + "사용자 (예시)", "role_code": "SL", "password": I["user_pw"]}, key="id")
        if I["user"]:
            from fastapi.testclient import TestClient

            from lcomfine.app.main import app

            qa1 = TestClient(app, raise_server_exceptions=False)
            r = qa1.post("/login", data={"login_id": p + "U", "password": I["user_pw"]}, follow_redirects=False)
            self.steps.append(("QA1 사용자 로그인(영업부)", 200 if r.status_code == 303 else r.status_code, str(r.status_code)))
            if r.status_code == 303:
                self.clients["qa1"] = qa1
        # W3 — RPT-130 데이터 질의는 ST · EX · ADM 만 칸이 있다. 전략부 QA1 사용자로 질의해 `data_query_log` · `sys_ai_call_log` 를 user_id 로 지운다
        I["user_st_pw"] = secrets.token_urlsafe(12)
        I["user_st"] = self.post("사용자(전략부 · 데이터 질의용)", "/sys/users",
                                 {"login_id": p + "ST", "user_name": p + "전략부 사용자 (예시)", "role_code": "ST", "password": I["user_st_pw"]}, key="id")
        if I["user_st"]:
            from fastapi.testclient import TestClient

            from lcomfine.app.main import app

            st = TestClient(app, raise_server_exceptions=False)
            r = st.post("/login", data={"login_id": p + "ST", "password": I["user_st_pw"]}, follow_redirects=False)
            self.steps.append(("QA1 사용자 로그인(전략부)", 200 if r.status_code == 303 else r.status_code, str(r.status_code)))
            if r.status_code == 303:
                self.clients["qa1st"] = st
        I["code"] = self.post("공통코드", "/sys/codes", {"group_code": "설비", "code": p + "EQ", "code_name": p + "설비 (예시)"}, key="id")
        I["noti_adm"] = conn.q1("insert into notification (event_key, to_role, message, link, dedupe_key) values "
                                "('request_created', 'ADM', %s, '/', %s) returning id", (p + "알림", p + "N-ADM"))["id"]
        I["noti_sl"] = conn.q1("insert into notification (event_key, to_role, message, link, dedupe_key) values "
                               "('request_created', 'SL', %s, '/', %s) returning id", (p + "알림", p + "N-SL"))["id"]
        I["wo_no"] = wo_no
        I["req_no"] = conn.q1("select request_no from production_request where id = %s", (I["req"],))["request_no"] if I["req"] else None
        self.build_col()
        self.build_doc()
        return self

    # ── W4 DOC — 문서관리 계정 매핑 · SSO 진입 (admin · 화면의 HTTP) ─────
    def build_doc(self) -> None:
        """QA1 사용자 5(DA 생산부 · DB 출하실 · DC 회계부 · DD 디자인·개발실 · DE 전략부)를 SYS-010 HTTP 로 만들고,
        DA · DC 는 DOC-020 한 건 등록(F-DOC-021)으로 잇는다. DA · DB · DC 는 로그인 세션을 `clients["docDA"]` … 에 둔다.
        계정 ID 는 `<접두>ACC-<태그> (예시)` — 정리 · 남은 행 대조가 접두로 찾는다. 시드 계정의 매핑은 건드리지 않는다."""
        from fastapi.testclient import TestClient

        from lcomfine.app.main import app

        I, p = self.ids, self.p
        for tag, role in (("DA", "PR"), ("DB", "SH"), ("DC", "AC"), ("DD", "DS"), ("DE", "ST")):
            pw = secrets.token_urlsafe(12)
            uid = self.post(f"사용자(DOC {tag} · {role})", "/sys/users",
                            {"login_id": p + tag, "user_name": p + f"문서 {tag} (예시)", "role_code": role, "password": pw}, key="id")
            I["doc_" + tag] = uid
            if uid and tag in ("DA", "DB", "DC"):
                c = TestClient(app, raise_server_exceptions=False)
                r = c.post("/login", data={"login_id": p + tag, "password": pw}, follow_redirects=False)
                self.steps.append((f"QA1 사용자 로그인(DOC {tag})", 200 if r.status_code == 303 else r.status_code, str(r.status_code)))
                if r.status_code == 303:
                    self.clients["doc" + tag] = c
        for tag in ("DA", "DC"):
            I["map_" + tag] = self.post(f"계정 매핑 등록(DOC {tag})", "/doc/account-map",
                                        {"user_id": str(I["doc_" + tag]), "account_id": self.doc_acc(tag)}, key="id")

    def doc_acc(self, tag: str) -> str:
        return f"{self.p}ACC-{tag} (예시)"

    # ── W2 COL — ERP 수금현황 (예시) xlsx · 거래처 매핑 · 회차 2 (admin · 화면의 HTTP) ─────
    def ensure_map(self) -> dict[str, str]:
        """지금 열 매핑(시드 7)을 그대로 쓴다. 필수 항목이 비어 있을 때만(다른 검사기가 바꿔 둔 경우) 기본 항목 이름으로 저장하고 끝에 되돌린다."""
        from lcomfine.app import erp_upload
        from lcomfine.db import conn

        cmap = erp_upload.column_map()
        need = list(erp_upload.REQUIRED_FIELDS) + ["sales_amount", "collected_amount", "bill_due_date"]
        if not all(cmap.get(f) for f in need):
            self.map_before = conn.q("select field, column_name, created_by from erp_column_map order by id")
            self.post("열 매핑 저장(필수 항목이 비어 있어 기본 이름으로)", "/col/uploads",
                      {"action": "map", **{f"map_{k}": v for k, v in erp_upload.FIELDS.items()}})
            cmap = erp_upload.column_map()
        self.cmap = cmap
        return cmap

    def erp_xlsx(self, rows: list[tuple]) -> bytes:
        """rows = (거래처코드, 일자, 매출액, 수금액, 잔액, 수단, 어음 만기) — 매핑된 열은 파일에 전부 있어야 한다(check_map)."""
        from lcomfine.app import erp_upload

        order = list(erp_upload.FIELDS)
        fields = [f for f in order if self.cmap.get(f)]
        heads = [self.cmap[f] for f in fields]
        body = []
        for r in rows:
            vals = dict(zip(order, r))
            body.append([vals.get(f) for f in fields])
        return xlsx_bytes(heads, body)

    def upload(self, step: str, rows: list[tuple], *, action: str = "apply", period=ERP_PERIOD, name: str | None = None):
        f, t = period
        return self.post(step, "/col/uploads", {"action": action, "period_from": f.isoformat(), "period_to": t.isoformat()},
                         files={"file": (name or self.p + "erp (예시).xlsx", self.erp_xlsx(rows), XLSX)})

    def build_col(self) -> None:
        from lcomfine.db import conn

        I, p = self.ids, self.p
        self.map_before: list[dict] | None = getattr(self, "map_before", None)
        self.batches: list[int] = []
        if not I.get("cust"):
            return
        self.ensure_map()
        I["erp_code"] = p + "E"               # 매핑하는 ERP 거래처코드
        I["erp_unmapped"] = p + "U"           # 매핑하지 않는 코드 — 미매핑 목록에 쌓여야 한다
        I["map"] = self.post("거래처 코드 매핑", "/col/customer-map",
                             {"erp_code": I["erp_code"], "erp_name": p + "ERP 거래처 (예시)", "customer_id": str(I["cust"])}, key="id")
        I["map2"] = self.post("거래처 코드 매핑(삭제용 · 참조 없음)", "/col/customer-map",
                              {"erp_code": p + "E2", "erp_name": p + "ERP 거래처2 (예시)", "customer_id": str(I["cust"])}, key="id")
        f, t = ERP_PERIOD
        self.erp_rows = [
            (I["erp_code"], "1980-01-05", "1000", "0", "1000", "현금 (예시)", None),
            (I["erp_code"], "1980-01-20", "0", "400", "600", "어음 (예시)", "1980-02-15"),      # 어음 — 만기 도래
            (I["erp_code"], "1980-01-25", "0", "0", "600", "어음 (예시)", "2999-12-31"),       # 어음 — 만기 예정
            (I["erp_unmapped"], "1980-01-21", "500", None, None, None, None),                 # 거래처 코드 미매핑 → 오류 행
            (I["erp_code"], "1980/13/01", "1", "1", None, None, None),                        # 일자 형식 오류 → 오류 행
        ]
        if conn.q1("select 1 from erp_upload_batch where period_from = %s and period_to = %s", (f, t)):
            self.steps.append(("ERP 기준 기간 1980-01 에 이미 회차가 있다 — 다른 검사기의 행 · QA1 업로드를 건너뛴다", 409, "충돌"))
            return
        b1 = self.upload("ERP 업로드 1회차(반영 · 오류 2행)", self.erp_rows)
        I["batch1"] = b1 and b1.get("id")
        if I["batch1"]:
            self.batches.append(I["batch1"])
        b2 = self.upload("ERP 업로드 2회차(같은 기간 → 교체)", self.erp_rows)
        I["batch2"] = b2 and b2.get("id")
        if I["batch2"]:
            self.batches.append(I["batch2"])
        I["batch_replaced_no"] = b2 and b2.get("replaced")

    def restore_map(self) -> None:
        from lcomfine.db import conn

        before = getattr(self, "map_before", None)
        if before is None:
            return
        with conn.tx() as cur:
            cur.execute("delete from erp_column_map")
            for b in before:
                cur.execute("insert into erp_column_map (field, column_name, created_by) values (%s, %s, %s)",
                            (b["field"], b["column_name"], b["created_by"]))
        self.map_before = None

    def failed_steps(self) -> list[str]:
        return [f"{s} → {st} {m}" for s, st, m in self.steps if st != 200]

    def cleanup(self) -> None:
        from lcomfine.db import conn

        like = self.p + "%"
        with conn.tx() as cur:
            # W2 COL — 자기 회차(id) · 자기 매핑(접두)만. 다른 QA 의 회차 · 시드 열 매핑은 건드리지 않는다
            cur.execute("select id from erp_upload_batch where source_file like %s", (like,))
            batches = sorted({r["id"] for r in cur.fetchall()} | set(getattr(self, "batches", []) or []))
            if batches:
                from lcomfine.app import erp_upload

                cur.execute("delete from notification where dedupe_key like 'erp_upload_error:%%' and link = any(%s)",
                            ([erp_upload.error_link(i) for i in batches],))
                cur.execute("delete from erp_upload_row where batch_id = any(%s)", (batches,))
                cur.execute("delete from erp_upload_batch where id = any(%s)", (batches,))
            cur.execute("delete from erp_customer_map where erp_code like %s", (like,))
            cur.execute("select id from item where item_code like %s", (like,))
            items = [r["id"] for r in cur.fetchall()]
            cur.execute("select id from location where location_code like %s", (like,))
            locs = [r["id"] for r in cur.fetchall()]
            cur.execute("select id from customer where customer_code like %s", (like,))
            custs = [r["id"] for r in cur.fetchall()]
            cur.execute("select id from work_order where item_id = any(%s)", (items,))
            wos = [r["id"] for r in cur.fetchall()]
            cur.execute("select id from production_request where item_id = any(%s) or customer_id = any(%s)", (items, custs))
            reqs = [r["id"] for r in cur.fetchall()]
            cur.execute("select id, lot_no, receipt_id from material_lot where item_id = any(%s)", (items,))
            mls = cur.fetchall()
            cur.execute("select id, lot_no from product_lot where item_id = any(%s)", (items,))
            pls = cur.fetchall()
            m_ids, p_ids = [r["id"] for r in mls], [r["id"] for r in pls]
            cur.execute("select id, shipment_no from shipment_order where customer_id = any(%s)", (custs,))
            ships = cur.fetchall()
            s_ids = [r["id"] for r in ships]
            nos = [r["lot_no"] for r in mls] + [r["lot_no"] for r in pls] + [r["shipment_no"] for r in ships]
            cur.execute("select request_no from production_request where id = any(%s)", (reqs,))
            nos += [r["request_no"] for r in cur.fetchall()]
            cur.execute("select work_order_no from work_order where id = any(%s)", (wos,))
            nos += [r["work_order_no"] for r in cur.fetchall()]
            cur.execute("delete from notification where dedupe_key like %s or message like %s or split_part(dedupe_key, ':', 2) = any(%s)",
                        (like, f"%{self.p}%", nos))
            cur.execute("set local session_replication_role = replica")   # 불변 이력(stock_adjust · shipment_adjust) — QA1 행만
            cur.execute("delete from shipment_adjust where shipment_order_id = any(%s)", (s_ids,))
            cur.execute("delete from stock_adjust where location_id = any(%s)", (locs,))
            cur.execute("set local session_replication_role = origin")
            cur.execute("delete from shipment_line where shipment_order_id = any(%s) or product_lot_id = any(%s)", (s_ids, p_ids))
            cur.execute("delete from shipment_order where id = any(%s)", (s_ids,))
            cur.execute("""delete from stock_move where (lot_kind = '원자재' and lot_id = any(%s)) or (lot_kind = '제품' and lot_id = any(%s))
                              or from_location_id = any(%s) or to_location_id = any(%s)""", (m_ids, p_ids, locs, locs))
            cur.execute("delete from lot_stock where location_id = any(%s) or (lot_kind = '원자재' and lot_id = any(%s)) "
                        "or (lot_kind = '제품' and lot_id = any(%s))", (locs, m_ids, p_ids))
            cur.execute("delete from product_inspection where product_lot_id = any(%s)", (p_ids,))
            cur.execute("delete from incoming_inspection where material_lot_id = any(%s)", (m_ids,))
            cur.execute("delete from product_receipt where work_order_id = any(%s) or product_lot_id = any(%s)", (wos, p_ids))
            cur.execute("select distinct issue_id from material_issue_line where work_order_id = any(%s) or material_lot_id = any(%s)", (wos, m_ids))
            i_ids = [r["issue_id"] for r in cur.fetchall()]
            cur.execute("delete from material_issue_line where issue_id = any(%s)", (i_ids,))
            cur.execute("delete from material_issue where id = any(%s)", (i_ids,))
            cur.execute("update product_lot set parent_lot_id = null where id = any(%s)", (p_ids,))
            cur.execute("delete from product_lot where id = any(%s)", (p_ids,))
            cur.execute("update material_lot set parent_lot_id = null where id = any(%s)", (m_ids,))
            cur.execute("delete from material_lot where id = any(%s)", (m_ids,))
            cur.execute("delete from material_receipt where id = any(%s) or supplier_name like %s",
                        (list({r["receipt_id"] for r in mls}), like))
            cur.execute("delete from production_daily where work_order_id = any(%s)", (wos,))
            cur.execute("delete from inspection_daily where work_order_id = any(%s)", (wos,))
            cur.execute("delete from work_sequence where work_order_id = any(%s)", (wos,))
            cur.execute("delete from plate_usage where work_order_id = any(%s) or plate_id in (select id from plate where plate_code like %s)", (wos, like))
            cur.execute("delete from work_order where id = any(%s)", (wos,))
            cur.execute("delete from production_request where id = any(%s)", (reqs,))
            for t in ("spec_sheet", "artwork", "sample_sheet", "exception_item", "plate"):
                cur.execute(f"delete from {t} where item_id = any(%s)", (items,))
            cur.execute("delete from plate where plate_code like %s", (like,))
            cur.execute("delete from standard where standard_code like %s", (like,))
            cur.execute("delete from location where id = any(%s) or warehouse_id in (select id from warehouse where warehouse_code like %s)", (locs, like))
            cur.execute("delete from warehouse where warehouse_code like %s", (like,))
            cur.execute("delete from customer where id = any(%s)", (custs,))
            cur.execute("delete from item where id = any(%s)", (items,))
            cur.execute("delete from sys_common_code where code like %s", (like,))
            cur.execute("delete from notification_setting where user_id in (select user_id from sys_user where login_id like %s)", (like,))
            # W3 — QA1 사용자가 남긴 데이터 질의 · AI 호출 로그(결과 행은 저장되지 않는다 · D-806). 다른 사용자의 로그는 건드리지 않는다
            cur.execute("delete from data_query_log where user_id in (select user_id from sys_user where login_id like %s) or question like %s",
                        (like, like))
            cur.execute("delete from sys_ai_call_log where user_id in (select user_id from sys_user where login_id like %s)", (like,))
            # W4 DOC — QA1 사용자의 토큰 · 매핑(FK → sys_user). SSO 로그 · 변경 로그는 감사 이력이라 W1~W3 처럼 남긴다
            cur.execute("delete from sso_token where account_id like %s or user_id in (select user_id from sys_user where login_id like %s)",
                        (like, like))
            cur.execute("delete from doc_account_map where account_id like %s or user_id in (select user_id from sys_user where login_id like %s)",
                        (like, like))
            cur.execute("delete from sys_user where login_id like %s", (like,))
        self.restore_map()

    def leftovers(self) -> dict[str, int]:
        from lcomfine.db import conn

        like = self.p + "%"
        q = {"item": "item_code", "customer": "customer_code", "warehouse": "warehouse_code", "location": "location_code",
             "standard": "standard_code", "plate": "plate_code", "sys_user": "login_id", "sys_common_code": "code",
             "notification": "dedupe_key", "erp_customer_map": "erp_code", "erp_upload_batch": "source_file", "data_query_log": "question",
             "doc_account_map": "account_id", "sso_token": "account_id"}
        out = {}
        for t, col in q.items():
            n = conn.q1(f"select count(*) as n from {t} where {col} like %s", (like,))["n"]
            if n:
                out[t] = n
        return out


# ── 오류 계약 사례 ──────────────────────────────────────────────────────
@dataclass
class Case:
    fid: str
    label: str
    path: str
    data: dict
    expect: int                 # 422 · 404 · 501 · 200
    files: dict | None = None
    decision: str | None = None   # 501 이면 메시지에 `미확정 (D-nn)`
    method: str = "POST"
    login: str = "admin"          # 어느 세션으로 보내는가 — "admin" · "qa1"(World 가 만든 영업부 사용자)
    msg_has: str | None = None    # 있으면 message 에 이 낱말이 들어 있어야 한다(422 의 사유가 계약의 그 사유인지)


BIG = "999999999999"            # numeric(14,3) 정수부 11 자리 · integer 범위를 넘는다
NUL = "QA1\x00NUL"


def cases(w: World) -> list[Case]:
    I, p = w.ids, w.p
    today = date.today().isoformat()
    due = (date.today() + timedelta(days=10)).isoformat()
    s = str
    C: list[Case] = []

    def add(fid, label, path, data, expect, **kw):
        C.append(Case(fid, label, path, data, expect, **kw))

    def nf(fid, path_tpl, data, files=None):
        add(fid, "없는 경로 키 999999999 → 404", fill(path_tpl, NOID), data, 404, files=files)
        add(fid, "숫자가 아닌 경로 키 abc → 404", fill(path_tpl, "abc"), data, 404, files=files)

    # HOME
    nf("F-HOME-022", "/home/notifications/{id}/handle", {})
    add("F-HOME-022", "다른 부서(SL) 알림 ID → 404", f"/home/notifications/{I['noti_sl']}/handle", {}, 404)
    # HOME-030 — Ruling 24 · D-526: 자기 부서(QA1 사용자 = 영업부)가 받는 이벤트만 · 부서 기본은 끌 수 없음(422) · 다른 부서 이벤트 422 · 메일 501
    from lcomfine.app import notify

    mine = sorted(k for k, roles in notify.EVENTS.items() if "SL" in roles)          # 영업부가 받는 이벤트 (D-511)
    other = next(k for k, roles in notify.EVENTS.items() if "SL" not in roles)        # 영업부가 받지 않는 이벤트
    add("F-HOME-031", "누락(빈 본문) → 422", "/home/notification-settings", {}, 422)
    add("F-HOME-031", "메일 칸(자기 부서 이벤트) → 501 미확정 (D-518)", "/home/notification-settings",
        {"events": mine, "enabled": mine, "mail": "on"}, 501, decision="D-518", login="qa1")
    add("F-HOME-031", "NUL 이벤트 키 → 422", "/home/notification-settings", {"events": [NUL]}, 422)
    add("F-HOME-031", "다른 부서로 가는 이벤트 구독 → 422 (Ruling 24 · D-511)", "/home/notification-settings",
        {"events": mine + [other], "enabled": mine + [other]}, 422, login="qa1", msg_has="다른 부서")
    add("F-HOME-031", "부서 기본 알림 끄기 → 422", "/home/notification-settings",
        {"events": mine, "enabled": mine[1:]}, 422, login="qa1", msg_has="끌 수 없")
    add("F-HOME-031", "자기 부서 이벤트 전부 켠 채 저장 → 200", "/home/notification-settings",
        {"events": mine, "enabled": mine}, 200, login="qa1")
    # BAS
    add("F-BAS-011", "누락 → 422", "/bas/items", {}, 422)
    add("F-BAS-011", "NUL 품목명 → 422", "/bas/items", {"item_code": p + "N1", "item_name": NUL, "item_type": "제품"}, 422)
    add("F-BAS-011", "NUL 품목 코드 → 422", "/bas/items", {"item_code": p + NUL, "item_name": "x", "item_type": "제품"}, 422)
    add("F-BAS-011", "코드 중복 → 422", "/bas/items", {"item_code": p + "FG", "item_name": "x", "item_type": "제품"}, 422)
    add("F-BAS-012", "누락(빈 본문) → 422", f"/bas/items/{I['item_x']}", {}, 422)
    add("F-BAS-012", "NUL 비고 → 422", f"/bas/items/{I['item_x']}", {"item_name": "x", "item_type": "제품", "note": NUL}, 422)
    nf("F-BAS-012", "/bas/items/{id}", {"item_name": "x", "item_type": "제품"})
    nf("F-BAS-013", "/bas/items/{id}/delete", {})
    add("F-BAS-021", "누락 → 422", "/bas/customers", {}, 422)
    add("F-BAS-021", "NUL 거래처명 → 422", "/bas/customers", {"customer_code": p + "N2", "customer_name": NUL}, 422)
    add("F-BAS-021", "코드 중복 → 422", "/bas/customers", {"customer_code": p + "C", "customer_name": "x"}, 422)
    add("F-BAS-022", "누락(빈 본문) → 422", f"/bas/customers/{I['cust']}", {}, 422)
    add("F-BAS-022", "NUL 주소 → 422", f"/bas/customers/{I['cust']}", {"customer_name": "x (예시)", "address": NUL}, 422)
    nf("F-BAS-022", "/bas/customers/{id}", {"customer_name": "x"})
    nf("F-BAS-023", "/bas/customers/{id}/delete", {})
    add("F-BAS-031", "누락 → 422", "/bas/warehouses", {}, 422)
    add("F-BAS-031", "NUL 창고명 → 422", "/bas/warehouses", {"target": "warehouse", "warehouse_code": p + "N3", "warehouse_name": NUL}, 422)
    add("F-BAS-031", "없는 창고에 위치 → 422", "/bas/warehouses",
        {"target": "location", "warehouse_id": NOID, "location_code": p + "N4", "location_name": "x"}, 422)
    add("F-BAS-032", "누락(빈 본문) → 422", f"/bas/warehouses/{I['wh']}", {}, 422)
    nf("F-BAS-032", "/bas/warehouses/{id}", {"target": "warehouse", "warehouse_name": "x"})
    nf("F-BAS-033", "/bas/warehouses/{id}/delete", {"target": "warehouse"})
    # STD
    add("F-STD-011", "누락 → 422", "/std/spec-sheets", {}, 422)
    add("F-STD-011", "NUL 사양 이름 → 422", "/std/spec-sheets", {"item_id": s(I["fg"]), "title": NUL}, 422)
    add("F-STD-011", "개정 차수 자릿수 초과 → 422", "/std/spec-sheets", {"item_id": s(I["fg"]), "title": p + "R", "revision": BIG}, 422)
    add("F-STD-011", "개정 차수 음수 → 422", "/std/spec-sheets", {"item_id": s(I["fg"]), "title": p + "R", "revision": "-1"}, 422)
    add("F-STD-012", "누락(빈 본문) → 422", f"/std/spec-sheets/{I['spec']}", {}, 422)
    nf("F-STD-012", "/std/spec-sheets/{id}", {"title": "x"})
    nf("F-STD-013", "/std/spec-sheets/{id}/delete", {})
    add("F-STD-021", "누락 → 422", "/std/standards", {}, 422)
    add("F-STD-021", "NUL 내용 → 422", "/std/standards", {"standard_code": p + "N5", "standard_name": "x", "content": NUL}, 422)
    add("F-STD-021", "코드 중복 → 422", "/std/standards", {"standard_code": p + "S", "standard_name": "x"}, 422)
    add("F-STD-022", "누락(빈 본문) → 422", f"/std/standards/{I['std']}", {}, 422)
    nf("F-STD-022", "/std/standards/{id}", {"standard_name": "x"})
    nf("F-STD-023", "/std/standards/{id}/delete", {})
    add("F-STD-031", "누락 → 422", "/std/plates", {}, 422)
    add("F-STD-031", "NUL 판 이름 → 422", "/std/plates", {"plate_code": p + "N6", "plate_name": NUL, "item_id": s(I["fg"])}, 422)
    add("F-STD-031", "제작일 형식 오류 → 422", "/std/plates", {"plate_code": p + "N7", "plate_name": "x", "item_id": s(I["fg"]), "made_on": "2026-13-45"}, 422)
    add("F-STD-032", "누락(빈 본문) → 422", f"/std/plates/{I['plate']}", {}, 422)
    nf("F-STD-032", "/std/plates/{id}", {"plate_name": "x", "item_id": s(I["fg"])})
    nf("F-STD-033", "/std/plates/{id}/delete", {})
    add("F-STD-041", "누락 → 422", "/std/artworks", {}, 422)
    add("F-STD-041", "NUL 시안 이름 → 422", "/std/artworks", {"item_id": s(I["fg"]), "title": NUL}, 422, files={"image": ("q.png", PNG, "image/png")})
    add("F-STD-041", "이미지 아님 → 422", "/std/artworks", {"item_id": s(I["fg"]), "title": "x"}, 422, files={"image": ("q.png", b"notpng", "image/png")})
    add("F-STD-042", "누락(빈 본문) → 422", f"/std/artworks/{I['art']}", {}, 422)
    nf("F-STD-042", "/std/artworks/{id}", {"title": "x"})
    add("F-STD-051", "누락 → 422", "/std/sample-sheets", {}, 422)
    add("F-STD-051", "NUL 내용 → 422", "/std/sample-sheets", {"item_id": s(I["fg"]), "title": "x", "content": "QA1=" + NUL}, 422)
    add("F-STD-051", "발행일 형식 오류 → 422", "/std/sample-sheets", {"item_id": s(I["fg"]), "title": "x", "issued_on": "2026-02-30"}, 422)
    add("F-STD-052", "누락(빈 본문) → 422", f"/std/sample-sheets/{I['sample']}", {}, 422)
    nf("F-STD-052", "/std/sample-sheets/{id}", {"title": "x"})
    add("F-STD-061", "누락 → 422", "/std/exception-items", {}, 422)
    add("F-STD-061", "NUL 사유 → 422", "/std/exception-items", {"item_id": s(I["rm"]), "reason": NUL}, 422)
    add("F-STD-062", "누락(빈 본문) → 422", f"/std/exception-items/{I['exc']}", {}, 422)
    nf("F-STD-062", "/std/exception-items/{id}", {"reason": "x"})
    nf("F-STD-063", "/std/exception-items/{id}/delete", {})
    # WO
    base_req = {"customer_id": s(I["cust"]), "item_id": s(I["fg"]), "qty": "10", "due_date": due}
    add("F-WO-011", "누락 → 422", "/wo/requests", {}, 422)
    add("F-WO-011", "수량 음수 → 422", "/wo/requests", {**base_req, "qty": "-5"}, 422)
    add("F-WO-011", "수량 0 → 422", "/wo/requests", {**base_req, "qty": "0"}, 422)
    add("F-WO-011", "수량 자릿수 초과 → 422", "/wo/requests", {**base_req, "qty": BIG}, 422)
    add("F-WO-011", "NUL 비고 → 422", "/wo/requests", {**base_req, "note": NUL}, 422)
    add("F-WO-011", "납기 형식 오류 → 422", "/wo/requests", {**base_req, "due_date": "2026-13-01"}, 422)
    add("F-WO-012", "누락(빈 본문) → 422", f"/wo/requests/{I['req']}", {}, 422)
    add("F-WO-012", "수량 음수 → 422", f"/wo/requests/{I['req']}", {**base_req, "qty": "-5", "status": "확인대기"}, 422)
    nf("F-WO-012", "/wo/requests/{id}", {**base_req, "status": "확인대기"})
    base_wo = {"request_id": s(I["req"]), "qty": "10", "equipment_code": "EQ01"}
    add("F-WO-021", "누락 → 422", "/wo/orders", {}, 422)
    add("F-WO-021", "없는 의뢰 → 404 (계약 「없는 의뢰 404」)", "/wo/orders", {**base_wo, "request_id": NOID}, 404)
    add("F-WO-021", "수량 음수 → 422", "/wo/orders", {**base_wo, "qty": "-1"}, 422)
    add("F-WO-021", "수량 자릿수 초과 → 422", "/wo/orders", {**base_wo, "qty": BIG}, 422)
    add("F-WO-021", "NUL 설비 코드 → 422", "/wo/orders", {**base_wo, "equipment_code": NUL}, 422)
    add("F-WO-022", "누락(빈 본문) → 422", f"/wo/orders/{I['wo']}", {}, 422)
    add("F-WO-022", "수량 음수 → 422", f"/wo/orders/{I['wo']}", {"qty": "-1", "equipment_code": "EQ01", "status": "발행"}, 422)
    nf("F-WO-022", "/wo/orders/{id}", {"qty": "10", "equipment_code": "EQ01", "status": "발행"})
    add("F-WO-031", "누락(방향 없음) → 422", f"/wo/sequence/{I['wo']}/move", {}, 422)
    nf("F-WO-031", "/wo/sequence/{id}/move", {"direction": "up"})
    # MAT
    base_rc = {"supplier_name": p + "공급사", "received_on": today, "item_id": [s(I["rm"])], "qty": ["5"], "location_id": [s(I["loc1"])], "supplier_lot_no": [""]}
    add("F-MAT-011", "누락 → 422", "/mat/receipts", {}, 422)
    add("F-MAT-011", "수량 음수 → 422", "/mat/receipts", {**base_rc, "qty": ["-5"]}, 422)
    add("F-MAT-011", "수량 자릿수 초과 → 422", "/mat/receipts", {**base_rc, "qty": [BIG]}, 422)
    add("F-MAT-011", "NUL 공급사 → 422", "/mat/receipts", {**base_rc, "supplier_name": NUL}, 422)
    add("F-MAT-011", "NUL 공급사 LOT → 422", "/mat/receipts", {**base_rc, "supplier_lot_no": [NUL]}, 422)
    add("F-MAT-012", "누락(빈 본문) → 422", f"/mat/receipts/{I['receipt']}", {}, 422)
    add("F-MAT-012", "NUL 비고 → 422", f"/mat/receipts/{I['receipt']}", {"supplier_name": p + "공급사", "received_on": today, "note": NUL}, 422)
    nf("F-MAT-012", "/mat/receipts/{id}", {"supplier_name": "x", "received_on": today})
    base_is = {"work_order_id": s(I["wo"]), "issued_on": today, "lot_no": [I["rm_lot"] or ""], "location_id": [s(I["loc1"])], "qty": ["1"]}
    add("F-MAT-021", "누락 → 422", "/mat/issues", {}, 422)
    add("F-MAT-021", "수량 음수 → 422", "/mat/issues", {**base_is, "qty": ["-1"]}, 422)
    add("F-MAT-021", "수량 자릿수 초과 → 422", "/mat/issues", {**base_is, "qty": [BIG]}, 422)
    add("F-MAT-021", "없는 LOT 번호 → 422", "/mat/issues", {**base_is, "lot_no": [p + "NOLOT"]}, 422)
    add("F-MAT-021", "NUL LOT 번호 → 422", "/mat/issues", {**base_is, "lot_no": [NUL]}, 422)
    add("F-MAT-022", "누락(빈 본문) → 422", f"/mat/issues/{I['issue']}", {}, 422)
    nf("F-MAT-022", "/mat/issues/{id}", {"issued_on": today, "note": "x"})
    base_pr = {"work_order_id": s(I["wo"]), "qty": "1", "location_id": s(I["loc1"]), "received_on": today}
    add("F-MAT-031", "누락 → 422", "/mat/product-receipts", {}, 422)
    add("F-MAT-031", "수량 음수 → 422", "/mat/product-receipts", {**base_pr, "qty": "-1"}, 422)
    add("F-MAT-031", "수량 자릿수 초과 → 422", "/mat/product-receipts", {**base_pr, "qty": BIG}, 422)
    add("F-MAT-031", "NUL 지시번호 → 422", "/mat/product-receipts", {"work_order_no": NUL, "qty": "1", "location_id": s(I["loc1"])}, 422)
    add("F-MAT-032", "누락(빈 본문) → 422", f"/mat/product-receipts/{I['preceipt']}", {}, 422)
    add("F-MAT-032", "수량 음수 → 422", f"/mat/product-receipts/{I['preceipt']}", {"qty": "-1", "received_on": today}, 422)
    nf("F-MAT-032", "/mat/product-receipts/{id}", {"qty": "1", "received_on": today})
    # PRD · INS
    base_pd = {"work_order_id": s(I["wo"]), "work_date": today, "equipment_code": "EQ01", "produced_qty": "1", "good_qty": "1", "loss_qty": "0"}
    add("F-PRD-011", "누락 → 422", "/prd/daily", {}, 422)
    add("F-PRD-011", "생산 수량 음수 → 422", "/prd/daily", {**base_pd, "produced_qty": "-1", "good_qty": "0"}, 422)
    add("F-PRD-011", "생산 수량 자릿수 초과 → 422", "/prd/daily", {**base_pd, "produced_qty": BIG, "good_qty": BIG}, 422)
    add("F-PRD-011", "가동 분 integer 초과 → 422", "/prd/daily", {**base_pd, "run_minutes": BIG}, 422)
    add("F-PRD-011", "가동 분 음수 → 422", "/prd/daily", {**base_pd, "run_minutes": "-10"}, 422)
    add("F-PRD-011", "NUL 비고 → 422", "/prd/daily", {**base_pd, "note": NUL}, 422)
    add("F-PRD-012", "누락(빈 본문) → 422", f"/prd/daily/{I['pdaily']}", {}, 422)
    add("F-PRD-012", "로스 음수 → 422", f"/prd/daily/{I['pdaily']}", {"produced_qty": "60", "good_qty": "55", "loss_qty": "-5"}, 422)
    nf("F-PRD-012", "/prd/daily/{id}", {"produced_qty": "1", "good_qty": "1", "loss_qty": "0"})
    base_id = {"work_order_id": s(I["wo"]), "work_date": today, "inspected_qty": "1", "defect_qty": "0"}
    add("F-INS-011", "누락 → 422", "/ins/daily", {}, 422)
    add("F-INS-011", "검사 수량 음수 → 422", "/ins/daily", {**base_id, "inspected_qty": "-1"}, 422)
    add("F-INS-011", "검사 수량 자릿수 초과 → 422", "/ins/daily", {**base_id, "inspected_qty": BIG}, 422)
    add("F-INS-011", "NUL 불량 코드 → 422", "/ins/daily", {**base_id, "defect_qty": "1", "defect_code": [NUL], "defect_code_qty": ["1"]}, 422)
    add("F-INS-012", "누락(빈 본문) → 422", f"/ins/daily/{I['idaily']}", {}, 422)
    add("F-INS-012", "불량 수량 음수 → 422", f"/ins/daily/{I['idaily']}", {"inspected_qty": "55", "defect_qty": "-1"}, 422)
    nf("F-INS-012", "/ins/daily/{id}", {"inspected_qty": "1", "defect_qty": "0"})
    # QC
    add("F-QC-011", "누락 → 422", "/qc/incoming", {}, 422)
    add("F-QC-011", "없는 LOT 번호 → 422", "/qc/incoming", {"lot_no": p + "NOLOT", "result": "합격"}, 422)
    add("F-QC-011", "판정 값 틀림 → 422", "/qc/incoming", {"lot_no": I["rm_lot"] or "", "result": "보류"}, 422)
    add("F-QC-011", "NUL LOT 번호 → 422", "/qc/incoming", {"lot_no": NUL, "result": "합격"}, 422)
    add("F-QC-012", "누락(빈 본문) → 422", f"/qc/incoming/{I['rm_lot_id']}", {}, 422)
    add("F-QC-012", "NUL 검사 항목 → 422", f"/qc/incoming/{I['rm_lot_id']}", {"result": "합격", "item_name": [NUL], "item_value": ["1"]}, 422)
    nf("F-QC-012", "/qc/incoming/{id}", {"result": "합격"})
    add("F-QC-021", "누락 → 422", "/qc/product", {}, 422)
    add("F-QC-021", "없는 LOT 번호 → 422", "/qc/product", {"lot_no": p + "NOLOT", "result": "합격"}, 422)
    add("F-QC-021", "NUL 비고 → 422", "/qc/product", {"lot_no": I["plot"] or "", "result": "합격", "note": NUL}, 422)
    add("F-QC-022", "누락(빈 본문) → 422", f"/qc/product/{I['plot_id']}", {}, 422)
    nf("F-QC-022", "/qc/product/{id}", {"result": "합격"})
    # INV
    base_mv = {"lot_kind": "원자재", "lot_no": I["rm_lot"] or "", "from_location_id": s(I["loc1"]), "to_location_id": s(I["loc2"]), "qty": "1"}
    add("F-INV-021", "누락 → 422", "/inv/moves", {}, 422)
    add("F-INV-021", "수량 음수 → 422", "/inv/moves", {**base_mv, "qty": "-1"}, 422)
    add("F-INV-021", "수량 자릿수 초과 → 422", "/inv/moves", {**base_mv, "qty": BIG}, 422)
    add("F-INV-021", "가용 초과 → 422", "/inv/moves", {**base_mv, "qty": "100000"}, 422)
    add("F-INV-021", "없는 LOT 번호 → 422", "/inv/moves", {**base_mv, "lot_no": p + "NOLOT"}, 422)
    add("F-INV-022", "누락(빈 본문) → 422", f"/inv/moves/{I['move']}", {}, 422)
    add("F-INV-022", "수량 음수 → 422", f"/inv/moves/{I['move']}", {"from_location_id": s(I["loc1"]), "to_location_id": s(I["loc2"]), "qty": "-1"}, 422)
    nf("F-INV-022", "/inv/moves/{id}", {"from_location_id": s(I["loc1"]), "to_location_id": s(I["loc2"]), "qty": "1"})
    base_adj = {"lot_kind": "원자재", "lot_no": I["rm_lot"] or "", "location_id": s(I["loc2"]), "actual_qty": "5", "reason": p + "실사"}
    add("F-INV-031", "누락 → 422", "/inv/adjustments", {}, 422)
    add("F-INV-031", "사유 없음 → 422", "/inv/adjustments", {**base_adj, "reason": ""}, 422)
    add("F-INV-031", "실사 수량 음수 → 422", "/inv/adjustments", {**base_adj, "actual_qty": "-1"}, 422)
    add("F-INV-031", "실사 수량 자릿수 초과 → 422", "/inv/adjustments", {**base_adj, "actual_qty": BIG}, 422)
    add("F-INV-031", "NUL 사유 → 422", "/inv/adjustments", {**base_adj, "reason": NUL}, 422)
    # SHP
    base_sh = {"customer_id": s(I["cust"]), "due_date": due, "stock_id": [s(I["stock"])], "qty": ["1"]}
    add("F-SHP-011", "누락 → 422", "/shp/orders", {}, 422)
    add("F-SHP-011", "수량 음수 → 422", "/shp/orders", {**base_sh, "qty": ["-1"]}, 422)
    add("F-SHP-011", "수량 자릿수 초과 → 422", "/shp/orders", {**base_sh, "qty": [BIG]}, 422)
    add("F-SHP-011", "가용 초과 할당 → 422", "/shp/orders", {**base_sh, "qty": ["100000"]}, 422)
    add("F-SHP-011", "NUL 비고 → 422", "/shp/orders", {**base_sh, "note": NUL}, 422)
    add("F-SHP-012", "수량 음수 → 422", f"/shp/orders/{I['ship']}", {"due_date": due, "stock_id": [s(I["stock"])], "qty": ["-1"]}, 422)
    add("F-SHP-012", "확정된 출하 수정 → 422", f"/shp/orders/{I['ship2']}", {"due_date": due, "stock_id": [s(I["stock"])], "qty": ["1"]}, 422)
    nf("F-SHP-012", "/shp/orders/{id}", {"due_date": due, "stock_id": [s(I["stock"])], "qty": ["1"]})
    add("F-SHP-021", "이미 확정 → 422", f"/shp/confirm/{I['ship2']}/confirm", {}, 422)
    nf("F-SHP-021", "/shp/confirm/{id}/confirm", {})
    add("F-SHP-023", "누락(빈 본문) → 422", f"/shp/confirm/{I['ship2']}/adjust", {}, 422)
    add("F-SHP-023", "확정 전 → 422", f"/shp/confirm/{I['ship']}/adjust", {"kind": "반품", "qty": "1", "reason": "x"}, 422)
    add("F-SHP-023", "수량 자릿수 초과 → 422", f"/shp/confirm/{I['ship2']}/adjust", {"kind": "반품", "qty": BIG, "reason": "x"}, 422)
    add("F-SHP-023", "반품 누계 초과 → 422", f"/shp/confirm/{I['ship2']}/adjust", {"kind": "반품", "qty": "100", "reason": "x"}, 422)
    add("F-SHP-023", "NUL 사유 → 422", f"/shp/confirm/{I['ship2']}/adjust", {"kind": "반품", "qty": "1", "reason": NUL}, 422)
    nf("F-SHP-023", "/shp/confirm/{id}/adjust", {"kind": "반품", "qty": "1", "reason": "x"})
    # SYS
    add("F-SYS-011", "누락 → 422", "/sys/users", {}, 422)
    add("F-SYS-011", "NUL 이름 → 422", "/sys/users", {"login_id": p + "N8", "user_name": NUL, "role_code": "SL", "password": secrets.token_urlsafe(9)}, 422)
    add("F-SYS-011", "없는 부서 → 422", "/sys/users", {"login_id": p + "NA", "user_name": "x", "role_code": "XX", "password": secrets.token_urlsafe(9)}, 422)
    add("F-SYS-011", "사번 중복 → 422", "/sys/users", {"login_id": p + "U", "user_name": "x", "role_code": "SL", "password": secrets.token_urlsafe(9)}, 422)
    add("F-SYS-012", "누락(빈 본문) → 422", f"/sys/users/{I['user']}", {}, 422)
    add("F-SYS-012", "NUL 이름 → 422", f"/sys/users/{I['user']}", {"user_name": NUL, "role_code": "SL", "status": "정상"}, 422)
    nf("F-SYS-012", "/sys/users/{id}", {"user_name": "x", "role_code": "SL", "status": "정상"})
    nf("F-SYS-013", "/sys/users/{id}/delete", {})
    add("F-SYS-021", "누락 → 422", "/sys/roles", {}, 422)
    add("F-SYS-021", "칸 값 틀림 → 422", "/sys/roles", {"cell:SL:BAS-010": "X"}, 422)
    add("F-SYS-021", "NUL 칸 값 → 422", "/sys/roles", {"cell:SL:BAS-010": NUL}, 422)
    add("F-SYS-031", "누락 → 422", "/sys/codes", {}, 422)
    add("F-SYS-031", "NUL 코드 이름 → 422", "/sys/codes", {"group_code": "설비", "code": p + "NB", "code_name": NUL}, 422)
    add("F-SYS-031", "표시 순서 integer 초과 → 422", "/sys/codes", {"group_code": "설비", "code": p + "NC", "code_name": "x", "sort_no": BIG}, 422)
    add("F-SYS-031", "없는 id → 404", "/sys/codes", {"id": NOID, "code_name": "x"}, 404)
    # COL (W2) — 업로드 · 거래처 매핑. 쓰기가 일어나지 않는 입력만(422 · 404 · preview)
    if I.get("map") is not None:
        from lcomfine.app import erp_upload

        f, t = ERP_PERIOD
        per = {"period_from": f.isoformat(), "period_to": t.isoformat()}
        good = w.erp_xlsx(w.erp_rows)
        xf = lambda data, name="qa1 (예시).xlsx": {"file": (name, data, XLSX)}  # noqa: E731
        add("F-COL-011", "누락(빈 본문 · 파일 없음) → 422", "/col/uploads", {}, 422)
        add("F-COL-011", "기준 기간 누락 → 422", "/col/uploads", {}, 422, files=xf(good))
        add("F-COL-011", "엑셀 아닌 파일 → 422", "/col/uploads", per, 422, files=xf(b"QA1 not an xlsx file"))
        add("F-COL-011", "빈 파일 → 422", "/col/uploads", per, 422, files=xf(b""))
        add("F-COL-011", "20MB 초과 → 422", "/col/uploads", per, 422, files=xf(b"\0" * (erp_upload.MAX_BYTES + 1), "big (예시).xlsx"))
        add("F-COL-011", "기준 기간 역순 → 422", "/col/uploads", {"period_from": t.isoformat(), "period_to": f.isoformat()}, 422, files=xf(good))
        add("F-COL-011", "기준 기간 날짜 형식 오류 → 422", "/col/uploads", {"period_from": "1980-13-45", "period_to": t.isoformat()}, 422, files=xf(good))
        add("F-COL-011", "매핑된 열이 파일에 없음 → 422", "/col/uploads", per, 422, files=xf(xlsx_bytes(["QA1-A", "QA1-B"], [["1", "2"]])))
        add("F-COL-011", "데이터 행 0(열 이름만) → 422", "/col/uploads", per, 422, files=xf(w.erp_xlsx([])))
        add("F-COL-011", "모르는 동작 → 422", "/col/uploads", {**per, "action": "drop"}, 422, files=xf(good))
        add("F-COL-011", "열 매핑 NUL → 422 (저장 안 됨)", "/col/uploads", {"action": "map", "map_customer_code": NUL}, 422)
        add("F-COL-011", "열 매핑 필수 항목 누락 → 422 (저장 안 됨)", "/col/uploads", {"action": "map", "map_sales_amount": "매출액"}, 422)
        add("F-COL-011", "검증 미리보기 → 200 (반영 안 함)", "/col/uploads", {**per, "action": "preview"}, 200, files=xf(good))
        add("F-COL-031", "누락 → 422", "/col/customer-map", {}, 422)
        add("F-COL-031", "NUL ERP 거래처명 → 422", "/col/customer-map", {"erp_code": p + "N9", "erp_name": NUL, "customer_id": s(I["cust"])}, 422)
        add("F-COL-031", "NUL ERP 거래처코드 → 422", "/col/customer-map", {"erp_code": p + NUL, "customer_id": s(I["cust"])}, 422)
        add("F-COL-031", "코드 중복 → 422", "/col/customer-map", {"erp_code": I["erp_code"], "customer_id": s(I["cust"])}, 422)
        add("F-COL-031", "없는 거래처(본문) → 422", "/col/customer-map", {"erp_code": p + "NA", "customer_id": NOID}, 422)
        add("F-COL-031", "거래처 값 틀림 → 422", "/col/customer-map", {"erp_code": p + "NB", "customer_id": "abc"}, 422)
        add("F-COL-032", "누락(빈 본문) → 422", f"/col/customer-map/{I['map']}", {}, 422)
        add("F-COL-032", "사용 여부 값 틀림 → 422", f"/col/customer-map/{I['map']}", {"customer_id": s(I["cust"]), "use_yn": "X"}, 422)
        add("F-COL-032", "NUL ERP 거래처명 → 422", f"/col/customer-map/{I['map']}", {"customer_id": s(I["cust"]), "erp_name": NUL}, 422)
        add("F-COL-032", "없는 거래처(본문) → 422", f"/col/customer-map/{I['map']}", {"customer_id": NOID}, 422)
        nf("F-COL-032", "/col/customer-map/{id}", {"customer_id": s(I["cust"])})
        nf("F-COL-033", "/col/customer-map/{id}/delete", {})
    # RPT (W3) — F-RPT-132 질의 실행의 **AI 호출 전** 입력 오류(라우터 선검사 · 로그 0 · 실제 OpenAI 호출 0). fake 가 필요한 사례는 check_rpt_contract
    add("F-RPT-132", "누락(빈 본문) → 422", "/rpt/query", {}, 422, login="qa1st", msg_has="질문")
    add("F-RPT-132", "NUL 질문 → 422", "/rpt/query", {"question": p + NUL}, 422, login="qa1st", msg_has="NUL")
    add("F-RPT-132", "10만 자 질문 → 422 (상한 1000자)", "/rpt/query", {"question": p + "q" * 100_000}, 422, login="qa1st", msg_has="1000자")
    add("F-RPT-132", "공백만 → 422", "/rpt/query", {"question": "   "}, 422, login="qa1st", msg_has="질문")
    # DOC (W4) — F-DOC-011 주소 없음 · F-DOC-021~023 입력 · 1:1 · 엑셀 · 404. 성공 경로 · 주소가 있는 경우는 check_doc_contract(가짜 주소)
    if I.get("map_DA") and I.get("map_DC"):
        from lcomfine.app.settings import get_settings

        if not get_settings().doc_sso_url:
            add("F-DOC-011", "SSO 주소 없음 → 422 「미확정 (D-517) — 토큰을 발급하지 않았습니다」 (계약 §2 예외 · 5xx 아님)", "/doc/go", {}, 422,
                login="docDA", msg_has="미확정 (D-517) — 토큰을 발급하지 않았습니다")
        dd, da, ma = s(I["doc_DD"]), s(I["doc_DA"]), I["map_DA"]
        M = "/doc/account-map"
        H = ["사번", "문서관리 계정 ID"]
        xd = lambda data, name="qa1-doc (예시).xlsx": {"file": (name, data, XLSX)}  # noqa: E731
        add("F-DOC-021", "누락(빈 본문) → 422", M, {}, 422, msg_has="MES 사용자")
        add("F-DOC-021", "계정 ID 누락 → 422", M, {"user_id": dd}, 422, msg_has="문서관리 계정 ID")
        add("F-DOC-021", "NUL 계정 ID → 422", M, {"user_id": dd, "account_id": p + NUL}, 422, msg_has="문서관리 계정 ID")
        add("F-DOC-021", "계정 ID 201자 → 422 (상한 200자)", M, {"user_id": dd, "account_id": p + "a" * 201}, 422, msg_has="200자")
        add("F-DOC-021", "없는 사용자(본문 999999999) → 422", M, {"user_id": NOID, "account_id": p + "X1"}, 422, msg_has="MES 사용자")
        add("F-DOC-021", "사용자 값 틀림 abc → 422", M, {"user_id": "abc", "account_id": p + "X2"}, 422, msg_has="MES 사용자")
        add("F-DOC-021", "1:1 깨짐 — 이미 계정이 연결된 사용자 → 422", M, {"user_id": da, "account_id": p + "X3"}, 422, msg_has="1:1")
        add("F-DOC-021", "1:1 깨짐 — 다른 사용자에 연결된 계정 ID → 422", M, {"user_id": dd, "account_id": w.doc_acc("DA")}, 422, msg_has="1:1")
        add("F-DOC-021", "엑셀 아닌 파일 → 422", M, {}, 422, files=xd(b"QA1 not an xlsx file"), msg_has="엑셀")
        add("F-DOC-021", "빈 파일 → 422", M, {}, 422, files=xd(b""), msg_has="빈 파일")
        add("F-DOC-021", "헤더 틀림(사원번호 · 계정) → 422", M, {}, 422, files=xd(xlsx_bytes(["사원번호", "계정"], [[p + "DD", p + "X4"]])),
            msg_has="열 이름")
        add("F-DOC-021", "데이터 행 0(열 이름만) → 422", M, {}, 422, files=xd(xlsx_bytes(H, [])), msg_has="등록할 행")
        add("F-DOC-021", "5MB 초과 → 422 (D-611)", M, {}, 422, files=xd(b"\0" * (5 * 1024 * 1024 + 1)), msg_has="5MB")
        add("F-DOC-021", "xlsx 가 아닌 zip → 422", M, {}, 422, files=xd(_zip_not_xlsx()), msg_has="엑셀")
        add("F-DOC-021", "5,001 행 → 422 (상한 5,000 · D-611)", M, {}, 422,
            files=xd(xlsx_bytes(H, [[f"{p}Z{i}", f"{p}ACC-Z{i}"] for i in range(5001)])), msg_has="5000행")
        add("F-DOC-021", "오류 행 하나(없는 사번) → 전체 거부 422", M, {}, 422,
            files=xd(xlsx_bytes(H, [[p + "DD", w.doc_acc("DD")], [p + "NOPE", p + "ACC-NOPE"]])), msg_has="아무것도 등록하지 않았습니다")
        add("F-DOC-021", "오류 행 — 파일 안 사번 중복 → 전체 거부 422", M, {}, 422,
            files=xd(xlsx_bytes(H, [[p + "DD", w.doc_acc("DD")], [p + "DD", p + "ACC-DD2"]])), msg_has="아무것도 등록하지 않았습니다")
        add("F-DOC-021", "오류 행 — DB 매핑과 1:1 깨짐 → 전체 거부 422", M, {}, 422,
            files=xd(xlsx_bytes(H, [[p + "DD", w.doc_acc("DD")], [p + "DE", w.doc_acc("DA")]])), msg_has="아무것도 등록하지 않았습니다")
        add("F-DOC-022", "누락(빈 본문) → 422", f"{M}/{ma}", {}, 422, msg_has="문서관리 계정 ID")
        add("F-DOC-022", "NUL 계정 ID → 422", f"{M}/{ma}", {"account_id": p + NUL}, 422, msg_has="문서관리 계정 ID")
        add("F-DOC-022", "사용 여부 값 틀림 → 422", f"{M}/{ma}", {"account_id": w.doc_acc("DA"), "use_yn": "X"}, 422, msg_has="사용 여부")
        add("F-DOC-022", "1:1 깨짐 — 다른 사용자의 계정 ID → 422", f"{M}/{ma}", {"account_id": w.doc_acc("DC")}, 422, msg_has="1:1")
        add("F-DOC-022", "매핑의 MES 사용자 바꾸기 → 422 (D-611)", f"{M}/{ma}", {"account_id": w.doc_acc("DA"), "user_id": dd}, 422,
            msg_has="MES 사용자")
        nf("F-DOC-022", M + "/{id}", {"account_id": p + "X5"})
        nf("F-DOC-023", M + "/{id}/delete", {})
    return C


def run_cases(w: World, cs: list[Case]) -> list[dict]:
    out = []
    for cs_ in cs:
        c = w.clients.get(cs_.login)
        if c is None:
            out.append({"fid": cs_.fid, "label": cs_.label, "path": cs_.path, "data": cs_.data, "expect": cs_.expect, "status": 0,
                        "message": None, "ok": False, "why": f"세션 {cs_.login!r} 없음(QA1 사용자 로그인 실패)", "generic_db_422": False,
                        "login": cs_.login})
            continue
        files = cs_.files
        r = c.post(cs_.path, data=cs_.data, files=files) if files else c.post(cs_.path, data=cs_.data)
        msg = jget(r, "message")
        code = jget(r, "code")
        fields_ = jget(r, "fields")
        ok = r.status_code == cs_.expect
        why = ""
        if ok and cs_.expect == 422:
            if code != "validation_error" or not (msg or "").strip() or not fields_:
                ok, why = False, f"422 모양 — code={code!r} · message={msg!r} · fields={fields_!r}"
        if ok and cs_.expect == 404 and code != "not_found":
            ok, why = False, f"code={code!r}"
        if ok and cs_.expect == 501 and (code != "undecided" or f"미확정 ({cs_.decision})" not in (msg or "")):
            ok, why = False, f"501 모양 — code={code!r} · message={msg!r}"
        if ok and cs_.expect == 200 and jget(r, "ok") is not True:
            ok, why = False, f"200 모양 — ok={jget(r, 'ok')!r}"
        if ok and cs_.msg_has and cs_.msg_has not in (msg or ""):
            ok, why = False, f"사유 문장 — {cs_.msg_has!r} 가 message={msg!r} 에 없음"
        # api-contract §3 — 어느 항목인지 모르는 「입력」 한 줄(DB 핸들러의 마지막 방어선, 또는 라우터가 항목을 짚지 않은 것)
        generic = cs_.expect == 422 and r.status_code == 422 and bool(fields_) and all(f.get("name") == "입력" for f in fields_)
        out.append({"fid": cs_.fid, "label": cs_.label, "path": cs_.path, "data": {k: v for k, v in cs_.data.items() if k != "password"},
                    "expect": cs_.expect, "status": r.status_code, "message": msg, "ok": ok, "why": why,
                    "generic_db_422": bool(generic), "login": cs_.login})
    return out


def server_error(status: int) -> bool:
    """5xx 중 서버 오류 — 501 `undecided` 는 계약이 정한 응답이라 빼고 센다(api-contract §1)."""
    return status >= 500 and status != 501


def world_html(w: World) -> dict[str, str]:
    """QA1 세계가 있는 동안 W1 화면 49 를 admin 으로 다시 읽는다 — 목록 · 표에 행이 있어야 L3 낱말 대조가 뜻이 있다."""
    from lcomfine.app import nav

    I = w.ids
    f_, t_ = (d.isoformat() for d in ERP_PERIOD)
    query = {"TRK-030": {"customer": I.get("cust")}, "TRK-010": {"request": I.get("req_no")}, "COL-010": {"batch": I.get("batch2")},
             "COL-020": {"batch": I.get("batch1")}, "COL-040": {"date_from": f_, "date_to": t_},
             "COL-050": {"asof": t_}, "COL-060": {"asof": t_}, "COL-070": {"ym_from": "1980-01", "ym_to": "1980-01"}}
    out = {}
    for s in nav.SCREENS:
        if s.common or s.menu_code in LATER_MENUS:
            continue
        params = {k: v for k, v in query.get(s.screen_id, {}).items() if v}
        r = w.c.get(s.path, params=params or None, headers=HTML, follow_redirects=False)
        if r.status_code == 200:
            out[s.screen_id] = r.text
    return out


def check_errors(clients: dict, rep: Report, keep: bool = False) -> tuple[World, list[dict], dict[str, str]]:
    """G-02 오류 계약 — QA1 세계를 만들고 쓰기 기능 58 의 사례를 두드린 뒤 지운다. 세계가 있는 동안의 화면 HTML 도 돌려준다(L3 대조용)."""
    from lcomfine.app import contracts

    w = World(clients)
    html_world: dict[str, str] = {}
    res: list[dict] = []
    try:
        w.build()
        bad_steps = w.failed_steps()
        rep.summary.append(("오류 계약 — QA1 세계 만들기 (HTTP · admin)", f"단계 {len(w.steps)} · 실패 {len(bad_steps)}"
                            + (f" — {'; '.join(bad_steps)}" if bad_steps else "")))
        for s_ in bad_steps:
            rep.defects.append(f"[세계] {s_}")
        if not any(v is None for k, v in w.ids.items() if k not in ("user_pw",)):
            res = run_cases(w, cases(w))
        if not res:
            rep.defects.append("[세계] 기준 행이 모자라 오류 계약 사례를 돌리지 못했다")
        html_world = world_html(w)                 # COL 계약 문장 확인(매핑 삭제 · 사용 중지)보다 먼저 — 행이 있는 화면
        check_rpt_contract(w, rep)                 # W3 — RPT 8 · 데이터 질의 · SYS-040 (COL 매핑이 살아 있는 동안 — RPT-060 수금)
        check_col_contract(w, rep)
        check_doc_contract(w, rep)                 # W4 — DOC-010 · DOC-020 (가짜 SSO 주소는 함수 안에서만 · 되돌림)
    finally:
        if not keep:
            w.cleanup()
    left = w.leftovers()
    rep.summary.append(("오류 계약 — 정리 후 남은 QA1 행", str(left or 0)))
    if left:
        rep.defects.append(f"[정리] 남은 행 {left}")
    nf = len({x["fid"] for x in res})
    bad = [x for x in res if not x["ok"]]
    s500 = [x for x in res if server_error(x["status"])]
    generic = [x for x in res if x["generic_db_422"]]
    rep.summary.append(("오류 계약 — 사례 (쓰기 기능 × 누락 · 404 · 501 · NUL · 자릿수 · 음수 · HOME-030 Ruling 24)",
                        f"기능 {nf} · 사례 {len(res)} · 통과 {len(res) - len(bad)} · 어긋남 {len(bad)} · 500 {len(s500)}"
                        f" · 항목을 짚지 않는 일반 문장 422 {len(generic)}"))
    for x in bad:
        rep.defects.append(f"{x['fid']} {x['label']} — [{x['login']}] POST {x['path']} {x['data']} → {x['status']} {x['message']!r} {x['why']}".strip())
    # G-02 §3 — 422 가 어느 항목인지 짚는가 (라우터 선검사). 일반 문장은 결함(경미)이지만 계약 위반이므로 FAIL 로 센다
    fmt = lambda x: f"{x['fid']} ({contracts.function(x['fid']).owner}) {x['label']} — POST {x['path']} → {x['message']!r}"  # noqa: E731
    n422 = sum(1 for x in res if x["expect"] == 422 and x["status"] == 422)
    rep.add("G-02", "오류 계약 §3 — 422 가 항목을 짚음 (라우터 선검사 · 「입력」 한 줄 아님)", not generic,
            f"422 사례 {n422} 중 일반 문장 {len(generic)}" + (" — " + " · ".join(sorted({x['fid'] for x in generic})) if generic else ""),
            [fmt(x) for x in generic])
    return w, res, html_world


# ── W2 COL 계약 문장 — 세계가 있는 동안 자동 확인 (정본 L3 · logic · D-516 · D-608) ─────
def check_col_contract(w: World, rep: Report) -> list[dict]:
    """COL 7 화면 + TRK-030 · TRK-020 · HOME 회계부 카드 — 정본 문장이 화면에서 지켜지는지. 쓰기는 admin 세션 · 자기 행만.
    매출액 · 잔액 열 매핑을 잠깐 지워 `미확정 (D-516)` 을 보고 같은 함수 안에서 되돌린다(스냅샷 → SQL 복원)."""
    from lcomfine.app import erp_upload, nav
    from lcomfine.db import conn

    I, p, c = w.ids, w.p, w.c
    out: list[dict] = []

    def chk(item: str, ok: bool, actual: str) -> None:
        out.append({"item": item, "ok": bool(ok), "actual": actual})

    def text_of(resp) -> str:
        return _norm(" ".join(parse(resp.text).text))

    if not I.get("batch2") or not I.get("map"):
        chk("세계 — ERP 회차 2 · 거래처 매핑", False, f"batch1 {I.get('batch1')} · batch2 {I.get('batch2')} · map {I.get('map')}")
        rep.add("G-02", "COL 계약 문장 (정본 L3 · logic · D-516 · D-608) — 자동 확인", False, "세계가 없어 확인하지 못했다",
                [f"{x['item']} — {x['actual']}" for x in out])
        return out
    b1 = conn.q1("select * from erp_upload_batch where id = %s", (I["batch1"],))
    b2 = conn.q1("select * from erp_upload_batch where id = %s", (I["batch2"],))
    rows1 = conn.q("select row_no, error from erp_upload_row where batch_id = %s order by row_no", (I["batch1"],))
    rows2 = conn.q("select row_no, error, parsed from erp_upload_row where batch_id = %s order by row_no", (I["batch2"],))
    asof_q = ERP_PERIOD[1].isoformat()
    f_, t_ = (d.isoformat() for d in ERP_PERIOD)

    # 1 회차 교체 (정본 「같은 기준 기간을 다시 올리면 이전 회차를 새 회차로 바꾼다. 이전 회차는 지우지 않고 이력에 남는다」)
    chk("회차 교체 — 1회차 교체(replaced_by = 2회차) · 2회차 반영(round 2) · 행 보존 5 · 오류 2",
        b1["status"] == "교체" and b1["replaced_by"] == I["batch2"] and b2["status"] == "반영" and b2["round_no"] == 2
        and len(rows1) == 5 and len(rows2) == 5 and b1["error_count"] == 2 and b2["error_count"] == 2
        and I.get("batch_replaced_no") == b1["batch_no"],
        f"1회차 {b1['status']}→{b1['replaced_by']} 행 {len(rows1)} 오류 {b1['error_count']} · 2회차 {b2['status']} round {b2['round_no']} "
        f"행 {len(rows2)} 오류 {b2['error_count']} · 응답 replaced={I.get('batch_replaced_no')!r}")
    errs = {r["row_no"]: r["error"] for r in rows2 if r["error"]}
    chk("오류 행 — 미매핑 코드 행 `거래처 코드 미매핑: <코드>` · 일자 형식 오류 행 `일자: …` (항목 이름)",
        any(e.startswith(f"{erp_upload.UNMAPPED_PREFIX}: {I['erp_unmapped']}") for e in errs.values())
        and any(e.startswith("일자:") for e in errs.values()), str(errs))
    # 2 알림 (D-511 · D-802) — 2회차 AC 1행 미처리 · 교체된 1회차의 알림은 닫힘
    n2 = conn.q("select to_role, handled_at from notification where link = %s", (erp_upload.error_link(I["batch2"]),))
    n1 = conn.q("select to_role, handled_at from notification where link = %s", (erp_upload.error_link(I["batch1"]),))
    chk("알림 erp_upload_error — 2회차 AC 1행 미처리 · 1회차(교체됨) 알림 닫힘",
        [x["to_role"] for x in n2] == ["AC"] and n2[0]["handled_at"] is None and n1 and all(x["handled_at"] for x in n1),
        f"2회차 {[(x['to_role'], bool(x['handled_at'])) for x in n2]} · 1회차 {[(x['to_role'], bool(x['handled_at'])) for x in n1]}")
    # 3 「처음 한 번 저장, 다음부터 자동」 — 2회차는 열 매핑 동작 없이 올라갔다(build 가 map 을 다시 부르지 않았다)
    chk("열 매핑 — 처음 한 번 저장, 다음부터 자동 (2회차 업로드에 매핑 동작 없음)", bool(I.get("batch2")), f"2회차 id {I['batch2']} · 매핑 {w.cmap}")
    # 4 COL-010 · COL-020 — 오류 행은 빨간색(class is-error) · 반영/교체됨 구분
    r = c.get(nav.path_of("COL-010"), params={"batch": I["batch2"]}, headers=HTML)
    red = r.text.count('class="is-error"')
    chk("COL-010 — 오류 행 빨간색(`class=\"is-error\"` ≥ 2) · 미확정 (D-516) 표시 · 미매핑 코드",
        r.status_code == 200 and red >= 2 and "미확정(D-516)" in text_of(r) and I["erp_unmapped"] in r.text,
        f"{r.status_code} · is-error {red} · D-516 {'미확정(D-516)' in text_of(r)}")
    r = c.get(nav.path_of("COL-020"), params={"batch": I["batch1"]}, headers=HTML)
    t = r.text
    chk("COL-020 — 현재 반영 회차와 교체된 회차 구분(data-status 반영 · 교체 · 「교체됨」 칩) · 회차별 오류 행",
        r.status_code == 200 and f'data-batch="{I["batch1"]}" data-status="교체"' in t and f'data-batch="{I["batch2"]}" data-status="반영"' in t
        and "교체됨" in t and t.count('class="is-error"') >= 2,
        f"{r.status_code} · 교체 행 {f'data-batch=\"{I['batch1']}\" data-status=\"교체\"' in t} · 반영 행 {f'data-batch=\"{I['batch2']}\" data-status=\"반영\"' in t} · is-error {t.count('class=\"is-error\"')}")
    # 5 COL-030 — 미매핑은 목록에 쌓인다 → 매핑하면 해당 오류 행을 다시 반영
    r = c.get(nav.path_of("COL-030"), headers=HTML)
    chk("COL-030 — 업로드에서 처음 보는 ERP 코드가 미매핑 목록에 쌓인다(`data-unmapped`)",
        r.status_code == 200 and f'data-unmapped="{I["erp_unmapped"]}"' in r.text, f"{r.status_code} · 미매핑 {I['erp_unmapped']} 표에 {f'data-unmapped=\"{I['erp_unmapped']}\"' in r.text}")
    before = (conn.q1("select count(*) as n from erp_upload_batch")["n"], conn.q1("select count(*) as n from erp_upload_row")["n"],
              conn.q1("select count(*) as n from notification")["n"])
    pv = c.post("/col/uploads", data={"action": "preview", "period_from": f_, "period_to": t_},
                files={"file": ("qa1 preview (예시).xlsx", w.erp_xlsx(w.erp_rows), XLSX)})
    after = (conn.q1("select count(*) as n from erp_upload_batch")["n"], conn.q1("select count(*) as n from erp_upload_row")["n"],
             conn.q1("select count(*) as n from notification")["n"])
    chk("COL-010 검증 미리보기 — 200 · applied false · 행 5 오류 2 · 회차 · 행 · 알림 수 불변",
        pv.status_code == 200 and jget(pv, "applied") is False and jget(pv, "rows") == 5 and jget(pv, "errors") == 2 and before == after,
        f"{pv.status_code} applied={jget(pv, 'applied')} rows={jget(pv, 'rows')} errors={jget(pv, 'errors')} · 전후 {before}→{after}")
    # 6 COL-040 — 어음 만기일 · 만기 도래 여부 · 엑셀
    r = c.get(nav.path_of("COL-040"), params={"date_from": f_, "date_to": t_, "customer": str(I["cust"])}, headers=HTML)
    t = r.text
    chk("COL-040 — 어음 만기(1980-02-15 → 도래 · 2999-12-31 → 예정) · 기간 · 거래처 조건 · 매출 1000 수금 400",
        r.status_code == 200 and "1980-02-15" in t and "2999-12-31" in t and ">도래<" in t and ">예정<" in t and "1,000" in t and "400" in t,
        f"{r.status_code} · 도래 {'>도래<' in t} · 예정 {'>예정<' in t} · 만기일 {'1980-02-15' in t and '2999-12-31' in t}")
    rx = c.get(nav.path_of("COL-040"), params={"date_from": f_, "date_to": t_, "customer": str(I["cust"]), "format": "xlsx"})
    chk("COL-040 엑셀 — `?format=xlsx` 200 · xlsx 미디어 타입", rx.status_code == 200 and rx.headers.get("content-type", "").startswith(XLSX),
        f"{rx.status_code} {rx.headers.get('content-type', '')[:60]} · {len(rx.content)} bytes")
    # 7 COL-050 · COL-060 · COL-070 (매핑 정상) — 거래처별 매출·수금·미수 · 30/60/90 구간 · 출하 대비 나란히
    r = c.get(nav.path_of("COL-050"), params={"asof": asof_q}, headers=HTML)
    t = r.text
    chk("COL-050 — 기준일 · 거래처별 매출 1,000 · 수금 400 · 미수 잔액 600 (D-803) · ERP 업로드 기준일",
        r.status_code == 200 and f'data-customer="{I["cust"]}"' in t and "1,000" in t and "600" in t and "ERP업로드기준일" in text_of(r),
        f"{r.status_code} · 행 {f'data-customer=\"{I['cust']}\"' in t} · 1,000 {'1,000' in t} · 600 {'600' in t}")
    r = c.get(nav.path_of("COL-060"), params={"asof": asof_q}, headers=HTML)
    from lcomfine.app import stats

    names = [b[0] for b in stats.AGING_BUCKETS]
    chk(f"COL-060 — 기준일 · 구간 {names} · 매출일 기준 경과일 · 산식(D-803) 표기",
        r.status_code == 200 and all(n in r.text for n in names) and f'data-customer="{I["cust"]}"' in r.text and "D-803" in r.text,
        f"{r.status_code} · 구간 {[n in r.text for n in names]} · 행 {f'data-customer=\"{I['cust']}\"' in r.text}")
    r = c.get(nav.path_of("COL-070"), params={"ym_from": "1980-01", "ym_to": "1980-01", "customer": str(I["cust"])}, headers=HTML)
    t = r.text
    chk("COL-070 — 월·거래처 선택 · MES 출하 수량·건수와 ERP 매출·수금 나란히(열 4) · 짝짓기 없음 문장",
        r.status_code == 200 and all(h in t for h in ("출하 건수 (MES)", "출하 수량 (MES)", "매출액 (ERP)", "수금액 (ERP)"))
        and f'data-month="1980-01" data-customer="{I["cust"]}"' in t and "짝짓지는 않는다" in t,
        f"{r.status_code} · 열 {[h in t for h in ('출하 건수 (MES)', '출하 수량 (MES)', '매출액 (ERP)', '수금액 (ERP)')]} · 행 {f'data-month=\"1980-01\" data-customer=\"{I['cust']}\"' in t}")
    # 8 TRK-030 수금 칸 (D-608 · F-TRK-031) — ok · 기준일 / TRK-020 period
    r = c.get(nav.path_of("TRK-030"), params={"customer": str(I["cust"])}, headers=HTML)
    t = r.text
    chk("TRK-030 — 수금·미수 칸 status ok · 미수 잔액 600 · ERP 업로드 기준일(data-asof) 표시",
        r.status_code == 200 and 'data-receivable="ok"' in t and "600" in t and 'data-asof=""' not in t and "ERP업로드기준일" in text_of(r),
        f"{r.status_code} · {re.search(r'data-receivable=\"[^\"]*\" data-asof=\"[^\"]*\"', t).group(0) if re.search(r'data-receivable=', t) else 'data-receivable 없음'}")
    r = c.get(nav.path_of("TRK-020"), params={"period": "1980-01"}, headers=HTML)
    chk("TRK-020 — `?period=YYYY-MM` 200 · data-compliance · data-period · 산식 문장(D-804)",
        r.status_code == 200 and 'data-period="1980-01"' in r.text and "data-compliance=" in r.text and "D-804" in r.text,
        f"{r.status_code} · period {'data-period=\"1980-01\"' in r.text} · compliance {'data-compliance=' in r.text}")
    bad_p = {v: c.get(nav.path_of("TRK-020"), params={"period": v}).status_code for v in ("1980-13", "1980-1", "abcd-ef", "1980/01", NUL)}
    chk("TRK-020 — `?period=` 형식 오류 → 422 (1980-13 · 1980-1 · abcd-ef · 1980/01 · NUL)", all(v == 422 for v in bad_p.values()), str(bad_p))
    # 9 HOME 회계부 카드 (D-608) — 미매핑 · 업로드 오류 행 · 90일 초과 미수(수치 또는 미수집 · 0 으로 지어내지 않음)
    ac = w.clients.get("ac")
    r = ac.get("/", headers=HTML) if ac else None
    t = r.text if r is not None else ""
    chk("HOME-010 회계부 — 「미매핑 ERP 거래처」 · 「업로드 오류 행」 · 「90일 초과 미수」 카드 · COL-060 링크",
        r is not None and r.status_code == 200 and all(k in t for k in ("미매핑 ERP 거래처", "업로드 오류 행", "90일 초과 미수")) and nav.path_of("COL-060") in t,
        f"{r.status_code if r is not None else 'ac 세션 없음'} · 카드 {[k in t for k in ('미매핑 ERP 거래처', '업로드 오류 행', '90일 초과 미수')]}")
    # 10 매출액 · 잔액 열 매핑 제거 → 미확정 (D-516) (D-516 · D-608) — 스냅샷 → 저장 → 확인 → SQL 복원
    snap = conn.q("select field, column_name, created_by from erp_column_map order by id")
    und: dict[str, bool] = {}
    try:
        mapping = {f"map_{f}": (col if f not in ("sales_amount", "balance_amount") else "") for f, col in w.cmap.items()}
        rm = c.post("/col/uploads", data={"action": "map", **mapping})
        if rm.status_code != 200:
            und["매핑 저장"] = False
        else:
            r5 = c.get(nav.path_of("COL-050"), params={"asof": asof_q}, headers=HTML)
            r6 = c.get(nav.path_of("COL-060"), params={"asof": asof_q}, headers=HTML)
            r3 = c.get(nav.path_of("TRK-030"), params={"customer": str(I["cust"])}, headers=HTML)
            rh = ac.get("/", headers=HTML) if ac else None
            und["COL-050"] = r5.status_code == 200 and "미확정(D-516)" in text_of(r5) and "400" in r5.text        # 수금 합은 그대로
            und["COL-060"] = r6.status_code == 200 and "미확정(D-516)" in text_of(r6)
            und["TRK-030"] = r3.status_code == 200 and 'data-receivable="미확정 (D-516)"' in r3.text and "미확정(D-516)" in text_of(r3)
            und["HOME-010(ac)"] = rh is not None and rh.status_code == 200 and "미확정(D-516)" in text_of(rh)
    finally:
        with conn.tx() as cur:
            cur.execute("delete from erp_column_map")
            for b in snap:
                cur.execute("insert into erp_column_map (field, column_name, created_by) values (%s, %s, %s)",
                            (b["field"], b["column_name"], b["created_by"]))
    restored = conn.q("select field, column_name from erp_column_map order by field") == sorted(
        ({"field": b["field"], "column_name": b["column_name"]} for b in snap), key=lambda x: x["field"])
    chk("매출액 · 잔액 열 매핑 제거 → COL-050 · COL-060 · TRK-030(data-receivable) · HOME 회계부 카드에 `미확정 (D-516)` · 수금 합은 수치 · 매핑 복원",
        bool(und) and all(und.values()) and restored, f"{und} · 복원 {restored}")
    # 11 COL-030 매핑 → 재반영 · 사용 중지 → 미매핑 목록 복귀 · 삭제(참조 있음 → 사용 중지 · 없음 → 삭제)
    rmap = c.post("/col/customer-map", data={"erp_code": I["erp_unmapped"], "customer_id": str(I["cust"])})
    row_u = conn.q1("select error from erp_upload_row where batch_id = %s and parsed ->> 'customer_code' = %s", (I["batch2"], I["erp_unmapped"]))
    row_u1 = conn.q1("select error from erp_upload_row where batch_id = %s and parsed ->> 'customer_code' = %s", (I["batch1"], I["erp_unmapped"]))
    b2n = conn.q1("select error_count from erp_upload_batch where id = %s", (I["batch2"],))["error_count"]
    r = c.get(nav.path_of("COL-030"), headers=HTML)
    chk("COL-030 매핑 등록 → 반영 회차의 그 코드 행 재반영(error null · remapped 1 · error_count 1) · 교체 회차 행은 그대로 · 미매핑 목록에서 사라짐",
        rmap.status_code == 200 and jget(rmap, "remapped") == 1 and row_u and row_u["error"] is None and row_u1 and row_u1["error"]
        and b2n == 1 and f'data-unmapped="{I["erp_unmapped"]}"' not in r.text,
        f"{rmap.status_code} remapped={jget(rmap, 'remapped')} · 2회차 행 error={row_u and row_u['error']!r} · 1회차 행 error 유지 {bool(row_u1 and row_u1['error'])} · error_count {b2n}")
    mid_u = jget(rmap, "id")
    if mid_u:
        ru = c.post(f"/col/customer-map/{mid_u}", data={"customer_id": str(I["cust"]), "use_yn": "N"})
        r = c.get(nav.path_of("COL-030"), headers=HTML)
        row_u = conn.q1("select error from erp_upload_row where batch_id = %s and parsed ->> 'customer_code' = %s", (I["batch2"], I["erp_unmapped"]))
        chk("COL-030 사용 중지 → 미매핑 목록에 다시 · 행은 건드리지 않음(F-COL-033 「사용 중지는 매핑만 바꾼다」)",
            ru.status_code == 200 and jget(ru, "use_yn") == "N" and f'data-unmapped="{I["erp_unmapped"]}"' in r.text and row_u["error"] is None,
            f"{ru.status_code} use_yn={jget(ru, 'use_yn')} · 미매핑 표 {f'data-unmapped=\"{I['erp_unmapped']}\"' in r.text} · 행 error={row_u['error']!r}")
    rd2 = c.post(f"/col/customer-map/{I['map2']}/delete")
    gone = conn.q1("select count(*) as n from erp_customer_map where id = %s", (I["map2"],))["n"] == 0
    rd1 = c.post(f"/col/customer-map/{I['map']}/delete")
    m1 = conn.q1("select use_yn from erp_customer_map where id = %s", (I["map"],))
    chk("COL-030 삭제 — 참조 없는 매핑은 삭제(disabled false) · 업로드 행이 참조하면 지우지 않고 사용 중지(disabled true · refs ≥ 1 · use_yn N)",
        rd2.status_code == 200 and jget(rd2, "disabled") is False and gone and rd1.status_code == 200 and jget(rd1, "disabled") is True
        and jget(rd1, "refs", 0) >= 1 and m1 and m1["use_yn"] == "N",
        f"참조 없음 {rd2.status_code} disabled={jget(rd2, 'disabled')} 삭제됨 {gone} · 참조 있음 {rd1.status_code} disabled={jget(rd1, 'disabled')} refs={jget(rd1, 'refs')} use_yn={m1 and m1['use_yn']}")
    r = c.get(nav.path_of("TRK-030"), params={"customer": str(I["cust"])}, headers=HTML)
    chk("TRK-030 — 매핑이 전부 사용 중지된 거래처의 수금 칸은 「미수집」(0 으로 지어내지 않음)",
        r.status_code == 200 and 'data-receivable="미수집"' in r.text, f"{r.status_code} · {'data-receivable=\"미수집\"' in r.text}")
    # 수금 수정 경로 없음 (정본 「MES 는 수금 데이터를 고치지 않는다」) — col 라우터의 POST 는 업로드 · 매핑 넷뿐
    from tools.check_trace import all_routes

    from lcomfine.app.main import app

    col_posts = sorted(path for path, methods in all_routes(app.routes) if path.startswith("/col/") and "POST" in methods)
    chk("COL — 수금 데이터 수정 엔드포인트 없음(POST 는 업로드 1 · 매핑 3 뿐)",
        col_posts == ["/col/customer-map", "/col/customer-map/{id}", "/col/customer-map/{id}/delete", "/col/uploads"], str(col_posts))

    bad = [f"{x['item']} — {x['actual']}" for x in out if not x["ok"]]
    rep.add("G-02", "COL 계약 문장 (정본 L3 · logic · D-516 · D-608 · 수정 경로 없음) — 자동 확인", not bad,
            f"항목 {len(out)} · 어긋남 {len(bad)}", bad)
    for x in out:
        rep.summary.append((f"COL 계약 문장 — {x['item']}", ("OK — " if x["ok"] else "어긋남 — ") + x["actual"]))
    return out


# ── W4 DOC 문서관리 — 계약 문장 · SSO 진입 응답 모양 (세계가 있는 동안 자동 확인) ─────
#: 테스트 전용 SSO 주소 — `.invalid` 는 해석되지 않는 이름이고(RFC 6761) TestClient 는 폼 action 으로 아무것도 보내지 않는다(외부 전송 0).
FAKE_SSO_URL = "https://qa1-doc.example.invalid/sso/entry"


@contextmanager
def fake_sso(url: str = FAKE_SSO_URL):
    """`LCOMFINE_DOC_SSO_URL` 을 잠깐 가짜 값으로(비밀이 없으면 실행마다 난수 — 어디에도 적지 않는다) → settings.reset_cache() → 되돌린다."""
    import os

    from lcomfine.app import settings

    keys = ("LCOMFINE_DOC_SSO_URL", "LCOMFINE_SSO_SECRET")
    old = {k: os.environ.get(k) for k in keys}
    os.environ["LCOMFINE_DOC_SSO_URL"] = url
    if not settings.get_settings().sso_secret:
        os.environ["LCOMFINE_SSO_SECRET"] = secrets.token_urlsafe(32)
    settings.reset_cache()
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        settings.reset_cache()


class _Tags(HTMLParser):
    """`<main>` 안의 form · input · section 의 속성 전부(속성 이름 그대로 — data-auto-submit 처럼 값 없는 속성은 None)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.forms: list[dict] = []
        self.sections: list[dict] = []
        self._form: dict | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "main":
            self.depth += 1
        if not self.depth:
            return
        if tag == "form":
            self._form = {"attrs": a, "inputs": []}
            self.forms.append(self._form)
        elif tag in ("input", "select", "textarea", "button") and self._form is not None:
            self._form["inputs"].append({"tag": tag, **a})
        elif tag == "section":
            self.sections.append(a)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag == "main" and self.depth:
            self.depth -= 1
        if tag == "form":
            self._form = None


def tags(html: str) -> _Tags:
    t = _Tags()
    t.feed(html)
    return t


def check_doc_contract(w: World, rep: Report) -> list[dict]:
    """DOC-010 · DOC-020 — 정본 L3 · logic · function-list F-DOC-011 · 012 · 021~024 · api-contract §2 F-DOC-011 예외 · D-514 · D-517 · D-610 · D-611.
    성공 경로는 `fake_sso()` 안에서만(가짜 주소 · 외부 전송 0) · 받은 토큰은 `sso.consume` 으로 형식을 확인한다(문서관리 시스템 쪽 검증 재현).
    쓰기는 admin(DOC-020 W) · QA1 사용자 DA · DB · DC 세션(DOC-010 R) · 자기 행만."""
    from lcomfine.app import sso
    from lcomfine.app.settings import get_settings
    from lcomfine.db import conn

    I, p, c = w.ids, w.p, w.c
    out: list[dict] = []

    def chk(item: str, ok: bool, actual: str) -> None:
        out.append({"item": item, "ok": bool(ok), "actual": actual})

    def text_of(resp) -> str:
        return _norm(" ".join(parse(resp.text).text))

    def n(sql: str, args=()) -> int:
        return conn.q1(f"select count(*) as n from ({sql}) x", args)["n"]

    cA, cB, cC = (w.clients.get(k) for k in ("docDA", "docDB", "docDC"))
    undecided_html = None
    title = "DOC 계약 문장 (W4 · 정본 L3 · logic · D-514 · D-517 · D-610 · D-611 · 계약 §2 F-DOC-011 예외) — 자동 확인"
    if not (cA and cB and cC and I.get("map_DA") and I.get("map_DC")):
        chk("세계 — QA1 사용자 DA · DB · DC 세션 · 매핑 DA · DC", False,
            f"세션 {[k for k in ('docDA', 'docDB', 'docDC') if k in w.clients]} · map {I.get('map_DA')} · {I.get('map_DC')}")
        rep.add("G-02", title, False, "세계가 없어 확인하지 못했다", [f"{x['item']} — {x['actual']}" for x in out])
        return out
    uA, uB, uC, uD, uE = (I["doc_" + t] for t in ("DA", "DB", "DC", "DD", "DE"))
    lA, lB, lC = p + "DA", p + "DB", p + "DC"
    accA, accC = w.doc_acc("DA"), w.doc_acc("DC")
    before = (get_settings().doc_sso_url, get_settings().sso_secret)
    tok = lambda uid: n("select 1 from sso_token where user_id = %s", (uid,))  # noqa: E731
    slog = lambda lid, res: n("select 1 from sys_access_log where log_type = 'SSO' and login_id = %s and result = %s "  # noqa: E731
                              "and screen_id = 'DOC-010' and function_id = 'F-DOC-011'", (lid, res))
    clog = lambda fid, tgt: n("select 1 from sys_change_log where function_id = %s and target like %s", (fid, tgt))  # noqa: E731

    # ── 1. 주소 없음 (로컬 실제 설정 — 비밀 · 주소 값은 찍지 않는다) ──
    if not get_settings().doc_sso_url:
        g = cA.get("/doc/go", headers=HTML)
        undecided_html = g.text
        tg = tags(g.text)
        sec = [s_.get("data-doc-go") for s_ in tg.sections if s_.get("data-doc-go")]
        chk("DOC-010 주소 없음 GET — 200 · 안내 `미확정 (D-517)` · 토큰 칸 없음 (D-514 · D-517)",
            g.status_code == 200 and sec == ["undecided"] and "미확정(D-517)" in text_of(g) and 'name="token"' not in g.text,
            f"{g.status_code} · data-doc-go {sec} · D-517 {'미확정(D-517)' in text_of(g)} · token 칸 {'name=\"token\"' in g.text}")
        t0, f0 = tok(uA), slog(lA, "실패")
        r = cA.post("/doc/go")
        rh = cA.post("/doc/go", headers=HTML, follow_redirects=False)
        chk("F-DOC-011 주소 없음 POST — JSON 422 `validation_error` 「… 미확정 (D-517) — 토큰을 발급하지 않았습니다」 fields `SSO 설정` · "
            "브라우저 303 → /doc/go (폼 POST 422 · 계약 §2) · 5xx 0 · 토큰 0행 · SSO 로그 실패 +2",
            r.status_code == 422 and jget(r, "code") == "validation_error"
            and "미확정 (D-517) — 토큰을 발급하지 않았습니다" in (jget(r, "message") or "")
            and [f_.get("name") for f_ in jget(r, "fields") or []] == ["SSO 설정"]
            and rh.status_code == 303 and rh.headers.get("location", "").split("?")[0].endswith("/doc/go")
            and tok(uA) == t0 and slog(lA, "실패") == f0 + 2,
            f"JSON {r.status_code} {jget(r, 'message')!r} fields {jget(r, 'fields')} · 브라우저 {rh.status_code} → "
            f"{rh.headers.get('location')} · 토큰 {t0}→{tok(uA)} · SSO 실패 로그 {f0}→{slog(lA, '실패')}")
    else:
        chk("주소 없음 경우 — 로컬 설정에 주소가 있어 건너뜀", True, "LCOMFINE_DOC_SSO_URL 있음 (값은 찍지 않는다)")

    with fake_sso():
        # ── 2. GET 바로가기 — 새 창 · 로그인된 상태 · 검증 실패 시 로그인 화면 안내 · 토큰은 GET 이 발급하지 않음 ──
        t0 = tok(uA)
        g = cA.get("/doc/go", headers=HTML)
        tg = tags(g.text)
        tx = text_of(g)
        sec = [s_.get("data-doc-go") for s_ in tg.sections if s_.get("data-doc-go")]
        go_forms = [f_["attrs"] for f_ in tg.forms if (f_["attrs"].get("method") or "").lower() == "post" and f_["attrs"].get("action") == "/doc/go"]
        chk("DOC-010 바로가기 — 매핑 있는 사용자 GET 200 · `ready` · POST /doc/go 진입 폼 1(이미 새 창 — 폼에 target 없음) · 연결된 계정 ID · GET 은 토큰 0행",
            g.status_code == 200 and sec == ["ready"] and len(go_forms) == 1 and not go_forms[0].get("target") and _norm(accA) in tx
            and tok(uA) == t0 and 'name="token"' not in g.text,
            f"{g.status_code} · {sec} · 폼 {go_forms} · 계정 ID {_norm(accA) in tx} · 토큰 {t0}→{tok(uA)}")
        chk("DOC-010 logic — 서명 · 60초 · 한 번만 · POST(주소창에 남지 않음) · 검증 실패 시 문서관리 로그인 화면에서 직접 로그인 · 문서별 권한은 문서관리 · "
            "방식 SAML/OIDC `미확정 (D-517)`",
            all(k in tx for k in ("일회용", "60초", "한번만", "POST", "로그인화면", "직접로그인", "문서별권한", "SAML", "OIDC", "미확정(D-517)")),
            "빠진 낱말 " + str([k for k in ("일회용", "60초", "한번만", "POST", "로그인화면", "직접로그인", "문서별권한", "SAML", "OIDC", "미확정(D-517)")
                              if k not in tx]))
        # DEF-QA1-010 — 정본 L3 「메뉴 클릭 → 새 창」 · F-DOC-011 「메뉴를 누르면 … 토큰을 발급 … 새 창으로 … 연다」. 지금은 메뉴 = 같은 창의 안내 화면이고
        # 「문서관리 열기 (새 창)」 단추를 한 번 더 눌러야 발급된다. 통과 = 메뉴 링크 target=_blank + 안내 화면의 POST 폼 data-auto-submit (한 번 클릭)
        # 또는 decisions.md 에 이 편차의 판정(DEF-QA1-010)이 적힘
        home = cA.get("/", headers=HTML).text
        a_menu = re.search(r'<a\b[^>]*data-screen="DOC-010"[^>]*>', home)
        ready_auto = any("data-auto-submit" in a for a in go_forms)
        auto_in = lambda html: any("data-auto-submit" in f_["attrs"] for f_ in tags(html).forms)  # noqa: E731
        refused_auto = auto_in(cB.get("/doc/go", headers=HTML).text)
        undecided_auto = auto_in(undecided_html) if undecided_html else False
        chk("DOC-010 L3 「메뉴 클릭 → 새 창」 (DEF-QA1-010) — 메뉴 링크 target=_blank · 준비됐을 때(ready) 진입 폼 data-auto-submit · 준비 안 됐을 때(매핑 없음 · 주소 없음) 자동 제출 없음",
            bool(a_menu) and 'target="_blank"' in a_menu.group(0) and ready_auto and not refused_auto and not undecided_auto,
            f"메뉴 링크 {a_menu.group(0) if a_menu else None} · ready 자동 제출 {ready_auto} · 매핑 없음 자동 제출 {refused_auto} · "
            f"주소 없음 자동 제출 {undecided_auto}")
        chk("DOC-010 L3 「문서관리 시스템 첫 화면 (로그인된 상태)」 — 외부 시스템의 화면(범위 밖 §2.8 실 접속 확인 · D-517) · MES 쪽은 자동 POST 폼까지",
            True, "사람 판정 — 화면 문장 「문서관리 시스템으로 넘긴다」 · 실 접속은 확인할 수 없다(가짜 주소)")

        # ── 3. POST JSON — 200 · 토큰 없음(jti) · sso_token 1행 · 변경 로그 1행 · SSO 로그 성공 ──
        s0, c0 = slog(lA, "성공"), clog("F-DOC-011", "sso_token:%")
        r = cA.post("/doc/go")
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        jti = body.get("jti")
        row = conn.q1("select user_id, account_id, used_at, extract(epoch from expires_at - issued_at) as ttl from sso_token where jti::text = %s",
                      (str(jti),)) if jti else None
        tokenish = [k for k, v in body.items() if isinstance(v, str) and v.count(".") == 1 and len(v) > 60]
        chk("F-DOC-011 JSON 성공 — 200 `{ok, message, jti, ttl_seconds 60, method POST, field token}` · 토큰 글자 없음 · sso_token 1행(사용자 · 계정 ID · 60초 · 미사용) · "
            "`sys_change_log` 1행(target sso_token:<jti>) · SSO 로그 성공 1행",
            r.status_code == 200 and body.get("ok") is True and bool(jti) and "token" not in body and not tokenish
            and body.get("ttl_seconds") == 60 and body.get("method") == "POST"
            and row is not None and row["user_id"] == uA and row["account_id"] == accA and int(row["ttl"]) == 60 and row["used_at"] is None
            and clog("F-DOC-011", f"sso_token:{jti}") == 1 and clog("F-DOC-011", "sso_token:%") == c0 + 1 and slog(lA, "성공") == s0 + 1,
            f"{r.status_code} 키 {sorted(body)} · 토큰 같은 값 {tokenish} · 행 {dict(row) if row else None} · 변경 로그 "
            f"{clog('F-DOC-011', f'sso_token:{jti}')} · SSO 성공 {s0}→{slog(lA, '성공')}")

        # ── 4. POST 브라우저 — 200 자동 POST 폼 · hidden 토큰 · data-auto-submit · method post · 주소창 · 로그에 토큰 없음 ──
        rh = cA.post("/doc/go", headers=HTML, follow_redirects=False)
        th = tags(rh.text)
        sso_forms = [f_ for f_ in th.forms if f_["attrs"].get("action") == FAKE_SSO_URL]
        hidden = [i for f_ in sso_forms for i in f_["inputs"] if i.get("tag") == "input" and i.get("type") == "hidden" and i.get("name") == "token"]
        token = hidden[0].get("value") if hidden else None
        f_attrs = sso_forms[0]["attrs"] if sso_forms else {}
        consumed, again = None, None
        if token:
            try:
                with conn.tx() as cur:
                    consumed = sso.consume(cur, token)
            except sso.Invalid as exc:
                consumed = f"Invalid({exc.reason})"
            try:
                with conn.tx() as cur:
                    sso.consume(cur, token)
                again = "통과(재사용 허용)"
            except sso.Invalid as exc:
                again = f"거부 {exc.reason}"
        leaked = 0
        if token:
            leaked = n("select 1 from sys_access_log where position(%s in coalesce(detail,'') || coalesce(target,'') || coalesce(path,'')) > 0",
                       (token,)) + n("select 1 from sys_change_log where position(%s in coalesce(detail,'') || target) > 0", (token,))
        chk("F-DOC-011 브라우저 성공 — 200 text/html (303 아님 · 계약 §2 예외) · 폼 method=post · action=SSO 주소 · `data-auto-submit` · hidden `token` 1개 · "
            "「문서관리 열기」 단추 · 토큰이 본문에 1번 · 주소/Location 에 없음 · 로그에 없음 · `sso.consume` 통과 → 재사용 거부",
            rh.status_code == 200 and rh.headers.get("content-type", "").startswith("text/html") and len(sso_forms) == 1
            and (f_attrs.get("method") or "").lower() == "post" and "data-auto-submit" in f_attrs and len(hidden) == 1
            and "문서관리열기" in text_of(rh) and token and rh.text.count(token) == 1 and token not in str(rh.url)
            and token not in (rh.headers.get("location") or "") and leaked == 0
            and isinstance(consumed, dict) and consumed.get("account_id") == accA and (again or "").startswith("거부"),
            f"{rh.status_code} {rh.headers.get('content-type')} · 폼 {len(sso_forms)} {f_attrs} · hidden {len(hidden)} · 본문 등장 "
            f"{rh.text.count(token) if token else 0} · 로그 누출 {leaked} · consume {consumed if not isinstance(consumed, dict) else consumed.get('account_id')} · 재사용 {again} "
            f"· Cache-Control {rh.headers.get('cache-control')!r}")
        chk("static/app.js — `form[data-auto-submit]` 자동 제출 보조 (템플릿 스크립트 0)",
            "data-auto-submit" in (ROOT / "src/lcomfine/app/static/app.js").read_text(encoding="utf-8")
            and "<script" not in (ROOT / "src/lcomfine/app/templates/doc/go_post.html").read_text(encoding="utf-8"),
            "app.js 에 data-auto-submit · doc 템플릿 <script 0")

        # ── 5. 매핑 없음 · 사용 중지 매핑 → 토큰 없이 「관리자에게 계정 연결을 요청하세요」 ──
        g = cB.get("/doc/go", headers=HTML)
        sec = [s_.get("data-doc-go") for s_ in tags(g.text).sections if s_.get("data-doc-go")]
        r = cB.post("/doc/go")
        chk("DOC-010 logic 「계정 매핑이 없으면 토큰을 발급하지 않고 \"관리자에게 계정 연결을 요청하세요\" 안내」 — GET `refused` + 안내 문장 · POST 422 fields `계정 매핑` · 토큰 0 · SSO 실패 로그",
            g.status_code == 200 and sec == ["refused"] and _norm(sso.REQUEST_MAPPING) in text_of(g)
            and r.status_code == 422 and sso.REQUEST_MAPPING in (jget(r, "message") or "")
            and [f_.get("name") for f_ in jget(r, "fields") or []] == ["계정 매핑"] and tok(uB) == 0 and slog(lB, "실패") >= 1,
            f"GET {g.status_code} {sec} · POST {r.status_code} {jget(r, 'message')!r} · 토큰 {tok(uB)} · SSO 실패 {slog(lB, '실패')}")
        r1 = c.post(f"/doc/account-map/{I['map_DC']}", data={"account_id": accC, "use_yn": "N"})
        r = cC.post("/doc/go")
        m = c.get("/doc/account-map", headers=HTML)
        unm = m.text.split('data-unmapped="', 1)[-1]
        chk("F-DOC-022 사용 중지(use_yn N) → 그 사용자 POST 422 「… 사용 중지」 · 미연결 목록에 「사용 중지 매핑 <계정 ID>」 (D-611)",
            r1.status_code == 200 and r.status_code == 422 and "사용 중지" in (jget(r, "message") or "") and tok(uC) == 0
            and lC in unm and "사용 중지 매핑" in unm,
            f"수정 {r1.status_code} · POST {r.status_code} {jget(r, 'message')!r} · 미연결 표에 DC {lC in unm}")

        # ── 6. 비활성 → 발급 바로 막힘 (DOC-020 logic) ──
        c.post(f"/doc/account-map/{I['map_DC']}", data={"account_id": accC, "use_yn": "Y"})
        r1 = c.post(f"/sys/users/{uC}", data={"user_name": p + "문서 DC (예시)", "role_code": "AC", "status": "중지"})
        r = cC.post("/doc/go")
        with conn.tx() as cur:
            reason, _ = sso.refusal(cur, uC)
        chk("DOC-020 logic 「MES 에서 사용자를 비활성으로 바꾸면 SSO 토큰 발급도 바로 막힌다」 — SYS-010 상태 중지 → 그 세션 POST 401 · `sso.refusal` 비활성 · 토큰 0",
            r1.status_code == 200 and r.status_code == 401 and "비활성" in (reason or "") and tok(uC) == 0,
            f"SYS-010 {r1.status_code} · POST {r.status_code} · refusal {reason!r} · 토큰 {tok(uC)}")

    after = (get_settings().doc_sso_url, get_settings().sso_secret)
    chk("가짜 SSO 주소 되돌림 — fake_sso() 뒤 settings 의 주소 · 비밀이 앞과 같다", after == before,
        f"주소 있음 {bool(after[0])} · 비밀 있음 {bool(after[1])} · 같음 {after == before} (값은 찍지 않는다)")

    # ── 7. DOC-020 화면 — L3 3 · logic 3 ──
    m = c.get("/doc/account-map", headers=HTML)
    mt = text_of(m)
    tm = tags(m.text)
    unm_sec = [s_ for s_ in tm.sections if "data-unmapped" in s_]
    bulk = [f_ for f_ in tm.forms if (f_["attrs"].get("enctype") or "") == "multipart/form-data"
            and any(i.get("type") == "file" and i.get("name") == "file" for i in f_["inputs"])]
    unm_html = m.text.split('data-unmapped="', 1)[-1]
    chk("DOC-020 L3 「MES 사용자 ↔ 문서관리 계정 ID」 · 「미연결 사용자 목록」 · 「엑셀 일괄 등록」 — 매핑 표(사번 · 문서관리 계정 ID · QA1 DA 행) · 미연결 표(QA1 DB · DD 있음 · DA 없음) · "
        "multipart 파일 폼 · 열 이름 `사번` `문서관리 계정 ID`",
        m.status_code == 200 and "사번" in mt and "문서관리계정ID" in mt and _norm(accA) in mt and len(unm_sec) == 1 and "미연결사용자" in mt
        and lB in unm_html and p + "DD" in unm_html and lA not in unm_html and len(bulk) == 1 and "엑셀일괄등록" in mt,
        f"{m.status_code} · 미연결 섹션 {len(unm_sec)} · DB {lB in unm_html} · DD {p + 'DD' in unm_html} · DA(매핑됨) {lA in unm_html} · 엑셀 폼 {len(bulk)}")
    chk("DOC-020 logic 「1:1」 · 「양쪽 사번이 같으면 매핑 없이 … (설계 때 확정)」 = `미확정 (D-517)` · 매핑 필수",
        "1:1" in mt and "미확정(D-517)" in mt and 'data-same-id="undecided"' in m.text and "매핑은필수" in mt,
        f"1:1 {'1:1' in mt} · D-517 {'미확정(D-517)' in mt} · data-same-id {'data-same-id' in m.text}")
    e1 = c.get("/doc/account-map", params={"edit": NOID})
    e2 = c.get("/doc/account-map", params={"edit": "abc"})
    e3 = c.get("/doc/account-map", params={"edit": str(I["map_DA"])}, headers=HTML)
    chk("F-DOC-024 `?edit=` — 없는 매핑 404 · abc 404 · 있는 매핑 200 수정 폼(action /doc/account-map/<id>)",
        e1.status_code == 404 and e2.status_code == 404 and e3.status_code == 200
        and any(f_["attrs"].get("action") == f"/doc/account-map/{I['map_DA']}" for f_ in tags(e3.text).forms),
        f"{e1.status_code} · {e2.status_code} · {e3.status_code}")

    # ── 8. 엑셀 일괄 — 오류 행 하나 → 0행 등록 · 정상 → 2행 + 변경 로그 1 ──
    H = ["사번", "문서관리 계정 ID"]
    xd = lambda data: {"file": ("qa1-doc (예시).xlsx", data, XLSX)}  # noqa: E731
    mapped = lambda: n("select 1 from doc_account_map where user_id = any(%s)", ([uD, uE],))  # noqa: E731
    bad_x = c.post("/doc/account-map", files=xd(xlsx_bytes(H + ["비고"], [[p + "DD", w.doc_acc("DD"), "x"], ["", ""], [p + "NOPE", p + "ACC-NOPE"]])))
    fields_ = jget(bad_x, "fields") or []
    chk("F-DOC-021 엑셀 — 오류 행 하나(4행 없는 사번 · 3행 빈 줄은 세지 않음 · 다른 열 무시) → 422 · fields `4행` 하나 · 아무것도 등록하지 않음",
        bad_x.status_code == 422 and [f_.get("name") for f_ in fields_] == ["4행"] and "없는 사번" in (fields_[0].get("reason") if fields_ else "")
        and mapped() == 0,
        f"{bad_x.status_code} {jget(bad_x, 'message')!r} fields {fields_} · 등록 {mapped()}")
    c0 = clog("F-DOC-021", "doc_account_map:엑셀%")
    good_x = c.post("/doc/account-map", files=xd(xlsx_bytes(["문서관리 계정 ID", "사번"], [[w.doc_acc("DD"), p + "DD"], [w.doc_acc("DE"), p + "DE"]])))
    chk("F-DOC-021 엑셀 — 정상 2행(열 순서 바뀜) → 200 count 2 · 매핑 2 · `sys_change_log` 1행",
        good_x.status_code == 200 and (good_x.json().get("count") if good_x.status_code == 200 else None) == 2 and mapped() == 2
        and clog("F-DOC-021", "doc_account_map:엑셀%") == c0 + 1,
        f"{good_x.status_code} {jget(good_x, 'message')!r} · 매핑 {mapped()} · 변경 로그 {c0}→{clog('F-DOC-021', 'doc_account_map:엑셀%')}")

    # ── 9. 수정 · 삭제 — 성공 + 변경 로그 · 참조(발급 기록) 있으면 사용 중지 ──
    mE = conn.q1("select id from doc_account_map where user_id = %s", (uE,))
    mE = mE and mE["id"]
    c22 = clog("F-DOC-022", f"doc_account_map:{p}DE")
    u = c.post(f"/doc/account-map/{mE}", data={"account_id": w.doc_acc("DE2"), "use_yn": "Y"})
    acc_now = conn.q1("select account_id from doc_account_map where id = %s", (mE,))
    chk("F-DOC-022 수정 — 200 · 계정 ID 바뀜 · `sys_change_log` 1행",
        u.status_code == 200 and acc_now and acc_now["account_id"] == w.doc_acc("DE2") and clog("F-DOC-022", f"doc_account_map:{p}DE") == c22 + 1,
        f"{u.status_code} · {acc_now} · 변경 로그 {c22}→{clog('F-DOC-022', f'doc_account_map:{p}DE')}")
    d1 = c.post(f"/doc/account-map/{mE}/delete")
    d2 = c.post(f"/doc/account-map/{I['map_DA']}/delete")
    rowA = conn.q1("select active from doc_account_map where id = %s", (I["map_DA"],))
    chk("F-DOC-023 삭제 — 발급 기록 없음 → 삭제(행 없음) · 있음(DA) → 사용 중지(active false) · 변경 로그 각 1",
        d1.status_code == 200 and jget(d1, "result") == "삭제" and not conn.q1("select 1 from doc_account_map where id = %s", (mE,))
        and d2.status_code == 200 and jget(d2, "result") == "사용 중지" and rowA is not None and rowA["active"] is False
        and clog("F-DOC-023", f"doc_account_map:{p}DE") == 1 and clog("F-DOC-023", f"doc_account_map:{p}DA") == 1,
        f"DE {d1.status_code} {jget(d1, 'result')} · DA {d2.status_code} {jget(d2, 'result')} active {rowA and rowA['active']}")

    # ── 10. SYS-040 SSO 탭 — 사용자 · 시각 · 성공 여부 (DOC-010 logic 「SSO 호출은 로그에 남긴다」) ──
    lg = c.get("/sys/logs", params={"tab": "sso", "login": lA}, headers=HTML)
    nn = re.search(r'data-log-tab="sso" data-n="(\d+)"', lg.text)
    chk("DOC-010 logic 「SSO 호출(사용자, 시각, 성공·실패)은 로그에 남긴다」 — SYS-040 SSO 탭(QA1 DA) 200 · 행 ≥ 3 · 성공 · 실패 둘 다 보임",
        lg.status_code == 200 and nn and int(nn.group(1)) >= 3 and "성공" in lg.text and "실패" in lg.text and lA in lg.text,
        f"{lg.status_code} · data-n {nn and nn.group(1)} · DB 성공 {slog(lA, '성공')} 실패 {slog(lA, '실패')}")

    bad = [x for x in out if not x["ok"]]
    for x in out:
        rep.summary.append((f"DOC 계약 문장 — {x['item']}", ("OK — " if x["ok"] else "어긋남 — ") + x["actual"]))
    rep.add("G-02", title, not bad, f"항목 {len(out)} · 어긋남 {len(bad)}", [f"{x['item']} — {x['actual']}" for x in bad])
    return out


# ── W3 RPT 대시보드 · 데이터 질의 · SYS-040 로그 탭 — 세계가 있는 동안 자동 확인 ─────
RPT_SCREENS = ("RPT-010", "RPT-020", "RPT-030", "RPT-040", "RPT-050", "RPT-060", "RPT-070", "RPT-080")
VOID_TAGS = {"input", "br", "img", "meta", "link", "hr", "col", "wbr", "source", "area", "base", "track", "embed", "param"}
APP_JS = "/static/app.js"
#: D-805 · progress-dev3 §1.5 의 표식 — 화면마다 있어야 하는 KPI · 차트(data-series) · 표(data-table) 이름 (정본 L3 · D-512 수치가 화면에 있다는 기계 증거)
RPT_MARKS: dict[str, tuple[set[str], set[str], set[str]]] = {
    "RPT-010": ({"requests", "qty", "customers", "not_started"}, {"requests", "qty", "due"}, {"top_customers", "not_started"}),
    "RPT-020": ({"work_orders", "order_qty", "produced_qty", "good_qty", "loss_qty", "loss_rate", "utilization"},
                {"good_qty", "produced_qty", "by_equipment"}, {"by_work_order", "by_equipment"}),
    "RPT-030": ({"inspected_qty", "defect_qty", "loss_rate", "judgements", "rejected_lots", "rejudged"},
                {"defect_qty", "inspected_qty", "defects"}, {"rejected", "rejudged"}),
    "RPT-040": ({"material_receipts", "material_receipt_qty", "issues", "issue_qty", "product_receipts", "adjusts", "adjust_diff"},
                {"receipt_qty", "issue_qty"}, {"top_moves", "long_stay", "adjusts"}),
    "RPT-050": ({"shipments", "qty", "customers", "due_rate"}, {"qty", "shipments", "by_customer"}, {"by_customer", "by_item", "due_rows"}),
    "RPT-060": ({"asof", "collected", "sales", "shipped_qty", "over90"}, {"collected", "shipped_qty", "aging"}, {"monthly", "by_customer", "over90"}),
    "RPT-070": ({"requests", "shipped", "bottleneck"}, {"avg_days", "collected"}, {"stages", "rows", "collection_by_customer"}),
    "RPT-080": (set(), {"shipment_qty", "issue_qty"}, set()),
}


class _Rpt(HTMLParser):
    """RPT · SYS 화면 본문의 구조 증거 — data-series 묶음마다 SVG `<title>` 글자와 표 행(라벨 · 값) · `grid-wrap` 밖의 `<table>` ·
    `<script>`(src) · KPI `data-kpi` 값 글자 · data-table 이름 · `<th>` 수."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, str, dict]] = []
        self.series: dict[str, dict] = {}
        self.kpis: dict[str, str] = {}
        self.tables: set[str] = set()
        self.unwrapped_tables: list[str] = []
        self.scripts: list[str] = []
        self.svgs = 0
        self.th = 0
        self._series: str | None = None
        self._svg = 0
        self._title: list[str] | None = None
        self._stable = False
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._kpi: str | None = None
        self._kpi_text: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class") or ""
        if tag == "section" and a.get("data-series"):
            self._series = a["data-series"]
            self.series.setdefault(self._series, {"titles": [], "rows": []})
        if a.get("data-table"):
            self.tables.add(a["data-table"])
        if tag == "svg":
            self._svg += 1
            self.svgs += 1
        if tag == "title" and self._svg and self._series:
            self._title = []
        if tag == "table":
            if not any("grid-wrap" in c.split() for _, c, _ in self.stack):
                self.unwrapped_tables.append(self._series or (self.stack[-1][2].get("data-table") if self.stack else "") or "?")
            if a.get("data-series-table") and self._series:
                self._stable = True
        if tag == "th":
            self.th += 1
        if self._stable and tag == "tr":
            self._row = []
        if self._stable and tag == "td" and self._row is not None:
            self._cell = []
        if tag == "script":
            self.scripts.append(a.get("src") or "inline")
        if a.get("data-kpi"):
            self._kpi = a["data-kpi"]
        if tag == "strong" and self._kpi and "kpi__value" in cls.split():
            self._kpi_text = []
        if tag not in VOID_TAGS:
            self.stack.append((tag, cls, a))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in VOID_TAGS:
            return
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                popped = self.stack[i]
                del self.stack[i:]
                break
        else:
            return
        a = popped[2]
        if tag == "title" and self._title is not None:
            self.series[self._series]["titles"].append(_norm("".join(self._title)))
            self._title = None
        if tag == "td" and self._cell is not None and self._row is not None:
            self._row.append(_norm("".join(self._cell)))
            self._cell = None
        if tag == "tr" and self._row is not None:
            if self._row:
                self.series[self._series]["rows"].append(self._row)
            self._row = None
        if tag == "table" and self._stable:
            self._stable = False
        if tag == "svg":
            self._svg -= 1
        if tag == "section" and a.get("data-series"):
            self._series = None
        if tag == "strong" and self._kpi_text is not None:
            self.kpis[self._kpi] = _norm("".join(self._kpi_text))
            self._kpi_text = None
        if a.get("data-kpi"):
            self._kpi = None

    def handle_data(self, data):
        if self._title is not None:
            self._title.append(data)
        if self._cell is not None:
            self._cell.append(data)
        if self._kpi_text is not None:
            self._kpi_text.append(data)


def rpt_parse(html: str) -> _Rpt:
    p = _Rpt()
    p.feed(html)
    return p


def svg_table_mismatch(p: _Rpt) -> list[str]:
    """data-series 묶음마다 SVG `<title>` 「라벨: 값」 목록 = 표 행(라벨 · 값) — 차트와 표가 같은 숫자(goal §3.4). SVG 가 없는 묶음(전부 미수집)은 뺀다."""
    bad = []
    for name, s in p.series.items():
        if not s["titles"]:
            continue
        rows = [f"{r[0]}:{r[1]}" for r in s["rows"] if len(r) == 2]
        if s["titles"] != rows:
            bad.append(f"{name}: title {len(s['titles'])} {s['titles'][:3]} ≠ 표 {len(rows)} {rows[:3]}")
    return bad


def schema_columns(table: str) -> set[str]:
    """contracts/db-schema.md §4 의 `### \\`table\\`` 표에서 컬럼 이름을 읽는다."""
    text = (ROOT / "contracts" / "db-schema.md").read_text(encoding="utf-8")
    m = re.search(rf"^### `{re.escape(table)}`.*?\n(.*?)(?=^### |^## |\Z)", text, re.S | re.M)
    if not m:
        return set()
    return {mm.group(1) for line in m.group(1).splitlines() if (mm := re.match(r"\|\s*([a-z_]+)\s*\|", line))}


def check_rpt_contract(w: World, rep: Report) -> list[dict]:
    """W3 — RPT 8 대시보드 · RPT-130 데이터 질의 · SYS-040 로그 탭 6 · 좌측 메뉴 이름. 쓰기는 F-RPT-132 만(전략부 QA1 사용자 · fake AI · 자기 로그만).
    실제 OpenAI 는 부르지 않는다 — 질문을 보내는 모든 POST 앞에 `ai.set_client(fake)`, 끝에 `set_client(None)` · `_config` 복원."""
    from lcomfine.app import ai, dataquery, nav, stats
    from lcomfine.app.routers import sys as sysr
    from lcomfine.db import conn

    I, p, c = w.ids, w.p, w.c
    st = w.clients.get("qa1st")
    out: list[dict] = []

    def chk(item: str, ok: bool, actual: str) -> None:
        out.append({"item": item, "ok": bool(ok), "actual": actual})

    def text_of(resp) -> str:
        return _norm(" ".join(parse(resp.text).text))

    today = date.today()
    f_, t_ = today.replace(day=1).isoformat(), today.isoformat()
    cust = str(I.get("cust") or "")
    cust_code = p + "C"

    # 0 좌측 메뉴 — RPT 대메뉴 이름 「대시보드」 (D-505 · G-01). 옛 이름 「AI 리포트」 가 메뉴 어디에도(툴팁 포함) 없어야 한다
    r = c.get("/", headers=HTML)
    side = re.search(r'<nav class="side".*?</nav>', r.text, re.S)
    side_t = side.group(0) if side else ""
    label = re.search(r'data-menu="RPT">\s*<h3[^>]*>([^<]*)<', side_t)
    menu_name = next((m.name for m in nav.MENUS if m.code == "RPT"), None)
    chk("좌측 메뉴 — RPT 대메뉴 이름 「대시보드」(nav · 메뉴 글자) · 옛 이름 「AI 리포트」 가 메뉴(툴팁 포함)에 0 (D-505)",
        menu_name == "대시보드" and label is not None and label.group(1).strip() == "대시보드" and "AI 리포트" not in side_t,
        f"nav {menu_name!r} · 메뉴 글자 {label.group(1).strip() if label else None!r} · 「AI 리포트」 {side_t.count('AI 리포트')}회"
        + (f" — {re.search(r'<h2[^>]*AI 리포트[^>]*>', side_t).group(0)[:120]}" if "AI 리포트" in side_t and re.search(r'<h2[^>]*AI 리포트[^>]*>', side_t) else ""))

    # 1 RPT 8 — 200 · SVG <title> = 표 · grid-wrap · 스크립트 · 표식(KPI · 차트 · 표) · 미확정 글자 · 미수집
    params = {sid: {"date_from": f_, "date_to": t_} for sid in RPT_SCREENS}
    for sid in ("RPT-010", "RPT-050", "RPT-060", "RPT-070"):
        params[sid]["customer"] = cust
    params["RPT-080"] = {"tab": "monthly", "asof": t_, "customer": cust}
    pages: dict[str, _Rpt] = {}
    texts: dict[str, str] = {}
    raws: dict[str, str] = {}
    for sid in RPT_SCREENS:
        r = c.get(nav.path_of(sid), params=params[sid], headers=HTML)
        pg = rpt_parse(r.text)
        pages[sid], texts[sid], raws[sid] = pg, text_of(r), r.text
        mm = svg_table_mismatch(pg)
        n_svg = sum(1 for s in pg.series.values() if s["titles"])
        need_svg = sid in ("RPT-010", "RPT-020", "RPT-030", "RPT-040", "RPT-050")   # QA1 세계가 이번 달에 만든 행이 있다
        chk(f"{sid} — 200 · 인라인 SVG <title> = 같은 숫자의 표 행 (묶음 {len(pg.series)} · SVG 있는 묶음 {n_svg})",
            r.status_code == 200 and not mm and (n_svg >= 1 or not need_svg),
            f"{r.status_code} · 어긋남 {len(mm)}" + (" — " + "; ".join(mm[:3]) if mm else ""))
        bad_scripts = [s for s in pg.scripts if not s.startswith(APP_JS)]
        chk(f"{sid} — 표는 전부 grid-wrap 안(390 가로 스크롤 0 · overflow 래퍼) · 외부·인라인 스크립트 0 (app.js 만)",
            r.status_code == 200 and not pg.unwrapped_tables and not bad_scripts,
            f"table 래퍼 밖 {len(pg.unwrapped_tables)} {pg.unwrapped_tables[:3]} · 스크립트 {pg.scripts}")
        want_k, want_s, want_t = RPT_MARKS[sid]
        chk(f"{sid} — 정본 L3 · D-512 수치 표식: KPI {sorted(want_k)} · 차트 {sorted(want_s)} · 표 {sorted(want_t)}",
            want_k <= set(pg.kpis) and want_s <= set(pg.series) and want_t <= pg.tables,
            f"KPI 빠짐 {sorted(want_k - set(pg.kpis))} · 차트 빠짐 {sorted(want_s - set(pg.series))} · 표 빠짐 {sorted(want_t - pg.tables)}")
    k = pages["RPT-010"].kpis
    chk("RPT-010 — 기간 · 거래처 필터로 QA1 의뢰가 잡힌다(KPI requests ≠ 미수집 · 거래처 상위 표에 QA1 거래처) · 미착수 = 지시서 없는 의뢰(표 not_started)",
        k.get("requests") not in (None, "미수집") and cust_code in texts["RPT-010"] and "not_started" in pages["RPT-010"].tables,
        f"requests={k.get('requests')!r} · 거래처 {cust_code in texts['RPT-010']} · not_started={k.get('not_started')!r}")
    for sid in ("RPT-020", "RPT-030"):
        k = pages[sid].kpis
        chk(f"{sid} — 로스율은 `미확정 (D-519)` 글자(KPI loss_rate) + 원 수량(KPI 수치)", k.get("loss_rate") == "미확정(D-519)" and "미확정(D-519)" in texts[sid]
            and (k.get("produced_qty" if sid == "RPT-020" else "inspected_qty") not in (None, "미수집")),
            f"loss_rate={k.get('loss_rate')!r} · 원 수량 {k.get('produced_qty' if sid == 'RPT-020' else 'inspected_qty')!r}")
    k = pages["RPT-040"].kpis
    chk("RPT-040 — 입고·불출 KPI 가 QA1 세계의 입고(오늘)로 수치(≠ 미수집) · 장기 체류 LOT 표 · 실사 차이 표",
        k.get("material_receipts") not in (None, "미수집") and {"long_stay", "adjusts"} <= pages["RPT-040"].tables,
        f"material_receipts={k.get('material_receipts')!r} · issues={k.get('issues')!r}")
    k = pages["RPT-050"].kpis
    chk("RPT-050 — 확정 출하 KPI(≠ 미수집 · QA1 확정 1) · 거래처별 표에 QA1 거래처 · 납기 준수율 KPI(due_rate) · 모집단 표 due_rows",
        k.get("shipments") not in (None, "미수집") and cust_code in texts["RPT-050"] and "due_rate" in k and "due_rows" in pages["RPT-050"].tables,
        f"shipments={k.get('shipments')!r} · due_rate={k.get('due_rate')!r}")
    asof = stats.erp_asof()
    exp_asof = asof.isoformat() if asof else "미수집"
    k = pages["RPT-060"].kpis
    chk("RPT-060 — 「가장 최근 업로드 기준일」 명시(ERP 업로드 기준일 글자 + KPI asof = stats.erp_asof() · 없으면 미수집) · 90일 초과 거래처 표",
        "ERP업로드기준일" in texts["RPT-060"] and k.get("asof") == _norm(exp_asof) and "over90" in pages["RPT-060"].tables,
        f"asof KPI {k.get('asof')!r} · 기대 {exp_asof!r} · 글자 {'ERP업로드기준일' in texts['RPT-060']}")
    k = pages["RPT-070"].kpis
    chk("RPT-070 — 의뢰별 단계 소요일 표(QA1 의뢰번호 행) · 병목 = `미확정 (D-520)` 글자(KPI bottleneck · 행) · 수금은 거래처·월 단위",
        f'data-request="{I.get("req_no")}"' in raws["RPT-070"]
        and k.get("bottleneck") == "미확정(D-520)" and "미확정(D-520)" in texts["RPT-070"] and "건단위로짝짓지않음" in texts["RPT-070"],
        f"의뢰 행 {('data-request=' + chr(34) + str(I.get('req_no')) + chr(34)) in raws['RPT-070']} · bottleneck={k.get('bottleneck')!r}")
    # RPT-080 — 일일 · 주간 · 월간 탭 · 일일 = 040 · 050, 주간·월간 = + 010 · 020 · 060 (D-805) · 해설 문장 없음(D-505)
    secs = {}
    for tab in ("daily", "weekly", "monthly"):
        r = c.get(nav.path_of("RPT-080"), params={"tab": tab, "asof": t_}, headers=HTML)
        secs[tab] = (r.status_code, set(re.findall(r'data-section="([^"]+)"', r.text)), set(re.findall(r'data-tab="([^"]+)"', r.text)),
                     all(x in r.text for x in ("일일", "주간", "월간")))
    chk("RPT-080 — 탭 일일 · 주간 · 월간(data-tab 3 · 글자) · 일일 = RPT-040 · 050 · 주간 · 월간 = + RPT-010 · 020 · 060 (D-805 · 해설 없음 D-505)",
        all(v[0] == 200 and v[2] == {"daily", "weekly", "monthly"} and v[3] for v in secs.values())
        and secs["daily"][1] == {"RPT-040", "RPT-050"} and all(secs[t][1] == {"RPT-010", "RPT-020", "RPT-040", "RPT-050", "RPT-060"} for t in ("weekly", "monthly")),
        " · ".join(f"{t}: {v[0]} {sorted(v[1])}" for t, v in secs.items()))

    # 2 RPT 조회 칸 형식 오류 — 422 · 500 0 · 응답 모양(api-contract §2: Accept 에 text/html 없으면 JSON validation_error)
    probes = {
        "RPT-010 ?date_from=2026-13-45": c.get(nav.path_of("RPT-010"), params={"date_from": "2026-13-45"}),
        "RPT-010 ?date_from=NUL": c.get(nav.path_of("RPT-010"), params={"date_from": NUL}),
        "RPT-010 ?date_from>date_to": c.get(nav.path_of("RPT-010"), params={"date_from": t_, "date_to": "2000-01-01"}),
        "RPT-010 ?customer=999999999(없는 거래처)": c.get(nav.path_of("RPT-010"), params={"customer": NOID}),
        "RPT-010 ?customer=abc": c.get(nav.path_of("RPT-010"), params={"customer": "abc"}),
        "RPT-050 ?date_to=2026-02-30": c.get(nav.path_of("RPT-050"), params={"date_to": "2026-02-30"}),
        "RPT-080 ?tab=yearly": c.get(nav.path_of("RPT-080"), params={"tab": "yearly"}),
        "RPT-080 ?asof=2026-13-45": c.get(nav.path_of("RPT-080"), params={"asof": "2026-13-45"}),
        "RPT-080 ?customer=999999999": c.get(nav.path_of("RPT-080"), params={"customer": NOID}),
    }
    codes = {k_: r.status_code for k_, r in probes.items()}
    chk("RPT 조회 칸 형식 오류(틀린 날짜 · NUL · 기간 역순 · 없는 거래처 · 거래처 값 틀림 · 탭 · 기준일) → 전부 422 · 500 0 · 사람이 읽는 문장",
        all(v == 422 for v in codes.values()) and all(("형식" in r.text or "거래처" in r.text or "탭" in r.text or "늦습니다" in r.text or "NUL" in r.text)
                                                       for r in probes.values()), str(codes))
    rh = c.get(nav.path_of("RPT-010"), params={"date_from": "2026-13-45"}, headers=HTML)
    rj = probes["RPT-010 ?date_from=2026-13-45"]
    chk("RPT 422 응답 모양 — 브라우저 422 + 문장 · **Accept 에 text/html 이 없으면 JSON `{code: validation_error, message, fields}`**(api-contract §2)",
        rh.status_code == 422 and "형식이 올바르지" in rh.text and rj.status_code == 422 and jget(rj, "code") == "validation_error",
        f"브라우저 {rh.status_code} {rh.headers.get('content-type', '')[:20]} · JSON 요청 {rj.status_code} {rj.headers.get('content-type', '')[:24]} code={jget(rj, 'code')!r}")

    # 3 RPT-130 데이터 질의 — 화면(전략부 QA1 사용자) · F-RPT-132 fake 주입 사례 · 로그 · 변경 로그 · SYS-040 탭
    if st is None or not I.get("user_st"):
        chk("세계 — 전략부 QA1 사용자 세션(RPT-130 질의용)", False, f"user_st {I.get('user_st')} · 세션 {st is not None}")
    else:
        r = st.get(nav.path_of("RPT-130"), headers=HTML)
        t = text_of(r)
        qi = re.search(r'<input[^>]*name="question"[^>]*>', r.text)
        chk("RPT-130 — 질문 입력(required · maxlength 1000) → 생성된 쿼리 → 결과 표 글자 · 허용 뷰 8 표시 · 전략부는 수금 뷰 2 흐림(dim · D-513)",
            r.status_code == 200 and qi is not None and "required" in qi.group(0) and 'maxlength="1000"' in qi.group(0)
            and all(x in t for x in ("질문입력", "생성된쿼리", "결과표")) and all(v in r.text for v in dataquery.VIEWS)
            and r.text.count('<code class="dim"') == 2 and "v_dq_collections" in r.text,
            f"{r.status_code} · input {qi.group(0)[:80] if qi else None} · dim {r.text.count('<code class=\"dim\"')}")
        uid = I["user_st"]
        orig_config = ai._config
        n_dq = n_ai = n_ai_fail = n_rej = 0
        qnos: dict[str, str | None] = {}
        ch_before = conn.q1("select count(*) as n from sys_change_log where function_id = 'F-RPT-132' and login_id = %s", (p + "ST",))["n"]

        def post(label: str, fake, question: str, *, html: bool = False, no_key: bool = False):
            nonlocal n_dq, n_ai, n_ai_fail
            if no_key:
                ai._config = lambda: ("", orig_config()[1])
                ai.set_client(None)
            else:
                ai._config = orig_config
                ai.set_client(fake)
            try:
                r_ = st.post(nav.path_of("RPT-130"), data={"question": question}, headers=HTML if html else None, follow_redirects=False)
            finally:
                ai.set_client(None)
                ai._config = orig_config
            n_dq += 1
            n_ai += 1
            if no_key or (fake is not None and getattr(fake, "boom", False)):
                n_ai_fail += 1
            return r_

        def dq_row(q: str):
            return conn.q1("select query_no, ok, sql_text, error, row_count from data_query_log where user_id = %s and question = %s order by id desc limit 1", (uid, q))

        # a 거부 SQL → 422 「허용되지 않는 질의 — 이유」 · fields 질의 번호 · SQL · 로그 1행(ok false)
        q = p + "질문 a — 쓰기 문"
        r = post("거부", lambda m, s_, u: "delete from v_dq_orders", q)
        row = dq_row(q)
        n_rej += 1
        names = [f_.get("name") for f_ in (jget(r, "fields") or [])]
        chk("F-RPT-132 fake 거부 SQL(delete) → 422 「허용되지 않는 질의 — 이유」 · fields 질의 번호 · SQL · data_query_log ok=false 1행(거부 포함 · D-513)",
            r.status_code == 422 and jget(r, "code") == "validation_error" and (jget(r, "message") or "").startswith(dataquery.REJECT_PREFIX + " — ")
            and "질의 번호" in names and "SQL" in names and row is not None and row["ok"] is False and (row["error"] or "").startswith(dataquery.REJECT_PREFIX),
            f"{r.status_code} {jget(r, 'message')!r} fields={names} · 로그 {row and dict(row)}")
        qnos["a"] = row and row["query_no"]
        # b 허용 SQL (JSON) → 200 http.saved + {query_no, sql, columns, rows, row_count, truncated, ms} · 로그 ok · 변경 로그 1행
        q = p + "질문 b — 허용"
        r = post("허용", lambda m, s_, u: "select * from v_dq_orders limit 5", q)
        row = dq_row(q)
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        chk("F-RPT-132 fake 허용 SQL → JSON 200 `http.saved` {ok, message, query_no, sql, columns, rows, row_count, truncated, ms}(D-806) · data_query_log ok=true · row_count",
            r.status_code == 200 and body.get("ok") is True and {"message", "query_no", "sql", "columns", "rows", "row_count", "truncated", "ms"} <= set(body)
            and body.get("columns") and row is not None and row["ok"] is True and row["row_count"] == body.get("row_count") and row["query_no"] == body.get("query_no"),
            f"{r.status_code} keys={sorted(body)[:12]} · 로그 {row and dict(row)}")
        qnos["b"] = body.get("query_no")
        ch_b = conn.q1("select count(*) as n from sys_change_log where function_id = 'F-RPT-132' and login_id = %s and target = %s",
                       (p + "ST", f"data_query_log:{qnos['b']}"))["n"] if qnos.get("b") else 0
        chk("F-RPT-132 성공 → `audit.log_change` 1행(function_id F-RPT-132 · target data_query_log:<질의 번호>) · 거부에는 변경 로그 0",
            ch_b == 1 and conn.q1("select count(*) as n from sys_change_log where target = %s", (f"data_query_log:{qnos['a']}",))["n"] == 0,
            f"성공 변경 로그 {ch_b} · 거부 변경 로그 {conn.q1('select count(*) as n from sys_change_log where target = %s', (f'data_query_log:{qnos[chr(97)]}',))['n']}")
        # c 수금 뷰 — 전략부(ST)는 거부 · EX 는 validate_sql 통과 (D-513 부서 제한)
        q = p + "질문 c — 수금 뷰"
        r = post("부서 뷰 제한", lambda m, s_, u: "select * from v_dq_collections limit 1", q)
        n_rej += 1
        ok_ex = True
        try:
            dataquery.validate_sql("select * from v_dq_collections limit 1", dataquery.allowed_views("EX"))
        except dataquery.QueryRejected as exc:
            ok_ex = f"EX 거부 {exc}"
        chk("F-RPT-132 수금 뷰 v_dq_collections — 전략부(ST) 422 「이 부서가 질의할 수 없는 뷰」 · EX 는 validate_sql 통과 (D-513 SL · AC · ADM · EX)",
            r.status_code == 422 and "질의할 수 없는 뷰" in (jget(r, "message") or "") and ok_ex is True,
            f"ST {r.status_code} {jget(r, 'message')!r} · EX {ok_ex}")
        # d 키 없음 → 422 문장 그대로 · sys_ai_call_log 실패 1행 · data_query_log 거부 1행(sql null) (G-17 · 조용한 실패 금지)
        q = p + "질문 d — 키 없음"
        r = post("키 없음", None, q, no_key=True)
        row = dq_row(q)
        n_rej += 1
        ai_row = conn.q1("select ok, error from sys_ai_call_log where user_id = %s order by id desc limit 1", (uid,))
        chk("F-RPT-132 AI 키 없음 → 422 「AI 키가 설정되지 않았습니다 — LCOMFINE_OPENAI_API_KEY」 · sys_ai_call_log ok=false(같은 문장) · data_query_log 거부(sql null)",
            r.status_code == 422 and jget(r, "message") == ai.NOT_CONFIGURED_MESSAGE and ai_row and ai_row["ok"] is False
            and ai_row["error"] == ai.NOT_CONFIGURED_MESSAGE and row and row["ok"] is False and row["sql_text"] is None,
            f"{r.status_code} {jget(r, 'message')!r} · ai {ai_row and dict(ai_row)} · dq sql={row and row['sql_text']!r}")
        # e 호출 실패(fake 예외) → 422 「AI 호출 실패 — …」 · ai 로그 실패
        def boom(m, s_, u):
            raise RuntimeError("QA1 boom (예시)")
        boom.boom = True
        q = p + "질문 e — 호출 실패"
        r = post("호출 실패", boom, q)
        n_rej += 1
        ai_row = conn.q1("select ok, error from sys_ai_call_log where user_id = %s order by id desc limit 1", (uid,))
        chk("F-RPT-132 AI 호출 실패(fake 예외) → 422 「AI 호출 실패 — …」 · sys_ai_call_log ok=false 사유 · 하드코딩 결과 0",
            r.status_code == 422 and (jget(r, "message") or "").startswith("AI 호출 실패 — ") and ai_row and ai_row["ok"] is False and "QA1 boom" in (ai_row["error"] or ""),
            f"{r.status_code} {jget(r, 'message')!r} · ai {ai_row and dict(ai_row)}")
        # f 브라우저(Accept text/html) 허용 → 303 이 아니라 같은 화면 200 + data-result + SQL + 결과 표 (api-contract §2 예외 · D-806)
        q = p + "질문 f — 브라우저"
        r = post("브라우저", lambda m, s_, u: "select * from v_dq_orders limit 5", q, html=True)
        row = dq_row(q)
        qno = row and row["query_no"]
        pg = rpt_parse(r.text)
        chk("F-RPT-132 브라우저(Accept text/html) 허용 → **같은 화면 200**(303 아님) · data-result=질의 번호 · 생성된 쿼리(SQL) · 결과 표(grid-wrap) · 최근 질의에 행",
            r.status_code == 200 and qno and f'data-result="{qno}"' in r.text and "select * from v_dq_orders limit 5" in r.text
            and f'data-query="{qno}"' in r.text and not pg.unwrapped_tables and "결과표" in text_of(r),
            f"{r.status_code} · data-result {bool(qno and f'data-result=\"{qno}\"' in r.text)} · 래퍼 밖 표 {len(pg.unwrapped_tables)}")
        qnos["f"] = qno
        # g 실행 실패(검증 통과 · 없는 열) → 422 「실행 실패 — …」
        q = p + "질문 g — 실행 실패"
        r = post("실행 실패", lambda m, s_, u: "select qa1_no_such_column from v_dq_orders", q)
        n_rej += 1
        row = dq_row(q)
        chk("F-RPT-132 실행 실패(검증 통과 · 없는 열) → 422 「실행 실패 — 사유」 · data_query_log ok=false",
            r.status_code == 422 and (jget(r, "message") or "").startswith("실행 실패 — ") and row and row["ok"] is False,
            f"{r.status_code} {jget(r, 'message')!r}")
        # 로그 행 수 — 질의 7 → data_query_log 7(거부 5) · sys_ai_call_log 7(실패 2) · 업무 테이블에는 쓰지 않는다
        dq_n = conn.q1("select count(*) as n, count(*) filter (where not ok) as rej from data_query_log where user_id = %s", (uid,))
        ai_n = conn.q1("select count(*) as n, count(*) filter (where not ok) as fail from sys_ai_call_log where user_id = %s", (uid,))
        chk(f"F-RPT-132 로그 — 질의 {n_dq} → data_query_log {n_dq}(거부 {n_rej}) · sys_ai_call_log {n_ai}(실패 {n_ai_fail}) — 거부 · 키 없음 · 실패도 1행씩(D-513 · D-806)",
            dq_n["n"] == n_dq and dq_n["rej"] == n_rej and ai_n["n"] == n_ai and ai_n["fail"] == n_ai_fail,
            f"dq {dict(dq_n)} · ai {dict(ai_n)}")
        # 모든 질의가 최근 질의 목록에(거부 is-error)
        r = st.get(nav.path_of("RPT-130"), headers=HTML)
        chk("RPT-130 최근 질의 — 질의 7 전부 표에(data-query) · 거부 행 is-error · 사유 글자",
            all(f'data-query="{v}"' in r.text for v in qnos.values() if v) and r.text.count('class="is-error"') >= n_rej and dataquery.REJECT_PREFIX in r.text,
            f"행 {[bool(v and f'data-query=\"{v}\"' in r.text) for v in qnos.values()]} · is-error {r.text.count('class=\"is-error\"')}")

        # 4 SYS-040 로그 탭 6 (admin) — 열 = db-schema 컬럼 · 탭마다 200 · 질의 · AI 호출 · ERP 회차가 보임 · 선택지 밖 422 (D-609 · F-SYS-041)
        missing = {tab: sorted(set(cols) - schema_columns(src.split()[0])) for tab, (src, cols) in sysr.LOG_SOURCES.items()}
        chk("SYS-040 탭 6 (access · change · erp · ai · dq · sso) — 보이는 열 전부 db-schema.md 컬럼 (새 열 · 캐시 없음 · D-609)",
            tuple(sysr.LOG_TABS) == ("access", "change", "erp", "ai", "dq", "sso") and not any(missing.values()),
            f"탭 {sysr.LOG_TABS} · 계약 밖 열 {dict((k_, v) for k_, v in missing.items() if v)}")
        tabs_ok = {}
        for tab, (src, cols) in sysr.LOG_SOURCES.items():
            r = c.get(nav.path_of("SYS-040"), params={"tab": tab}, headers=HTML)
            pg = rpt_parse(r.text)
            tabs_ok[tab] = (r.status_code, pg.th == len(cols) or "미수집" in r.text, src.split()[0] in r.text, not pg.unwrapped_tables, [s_ for s_ in pg.scripts if not s_.startswith(APP_JS)])
        chk("SYS-040 탭 6 → 200 · 표 머리 = 열 수(또는 미수집) · 표 밑에 원본 표 이름 · 표는 grid-wrap 안 · 스크립트 0",
            all(v[0] == 200 and v[1] and v[2] and v[3] and not v[4] for v in tabs_ok.values()), str(tabs_ok))
        r = c.get(nav.path_of("SYS-040"), params={"tab": "dq", "login": p + "ST"}, headers=HTML)
        m_n, m_rej = re.search(r'data-n="(\d+)"', r.text), re.search(r'data-rejected="(\d+)"', r.text)
        chk(f"SYS-040 데이터 질의 탭(?login=QA1 전략부) — 머리 건수 {n_dq} · 거부 {n_rej}(거부 포함 · D-513) · 질의 번호 전부 행에 · 「허용」 「거부」 글자",
            r.status_code == 200 and m_n and int(m_n.group(1)) == n_dq and m_rej and int(m_rej.group(1)) == n_rej
            and all(v in r.text for v in qnos.values() if v) and "거부" in r.text and "허용" in r.text,
            f"{r.status_code} data-n={m_n and m_n.group(1)} data-rejected={m_rej and m_rej.group(1)} · 질의 번호 {[bool(v and v in r.text) for v in qnos.values()]}")
        r = c.get(nav.path_of("SYS-040"), params={"tab": "ai", "login": p + "ST"}, headers=HTML)
        m_n, m_f = re.search(r'data-n="(\d+)"', r.text), re.search(r'data-failed="(\d+)"', r.text)
        chk(f"SYS-040 AI 호출 탭(?login=QA1 전략부) — 머리 건수 {n_ai} · 실패 {n_ai_fail} · 평균 ms · 키 없음 문장이 실패 사유 열에(키 값 0)",
            r.status_code == 200 and m_n and int(m_n.group(1)) == n_ai and m_f and int(m_f.group(1)) == n_ai_fail and 'data-avg-ms="' in r.text
            and ai.NOT_CONFIGURED_MESSAGE in r.text and "QA1 boom" in r.text,
            f"{r.status_code} data-n={m_n and m_n.group(1)} data-failed={m_f and m_f.group(1)}")
        if I.get("batch1") and I.get("batch2"):
            b = {x["id"]: x["batch_no"] for x in conn.q("select id, batch_no from erp_upload_batch where id = any(%s)", ([I["batch1"], I["batch2"]],))}
            r = c.get(nav.path_of("SYS-040"), params={"tab": "erp", "date_from": t_, "date_to": t_}, headers=HTML)
            m_n = re.search(r'data-n="(\d+)"', r.text)
            chk("SYS-040 ERP 업로드 탭(오늘) — QA1 회차 2 가 행에 · 1회차 교체 · 교체한 회차 = 2회차 번호 · 머리 건수 ≥ 2",
                r.status_code == 200 and b.get(I["batch1"]) in r.text and b.get(I["batch2"]) in r.text and "교체" in r.text
                and m_n is not None and int(m_n.group(1)) >= 2
                and re.search(rf'{re.escape(b[I["batch1"]])}.*?교체.*?{re.escape(b[I["batch2"]])}', r.text, re.S) is not None,
                f"{r.status_code} · 회차 {list(b.values())} 보임 {[v in r.text for v in b.values()]} · data-n={m_n and m_n.group(1)}")
        bad_f = {k_: c.get(nav.path_of("SYS-040"), params=v).status_code for k_, v in {
            "tab=nope": {"tab": "nope"}, "dq log_type=XYZ": {"tab": "dq", "log_type": "XYZ"}, "erp log_type=XYZ": {"tab": "erp", "log_type": "XYZ"},
            "sso log_type=XYZ": {"tab": "sso", "log_type": "XYZ"}, "access log_type=XYZ": {"tab": "access", "log_type": "XYZ"},
            "date_from=2026-13-45": {"tab": "access", "date_from": "2026-13-45"}, "login=NUL": {"tab": "access", "login": NUL}}.items()}
        chk("SYS-040 필터 — 탭 · 구분 선택지 밖(access 로그인·조회·변경·오류·SSO · erp · dq · sso) · 틀린 날짜 · NUL → 422 (D-609 「선택지 밖은 422」)",
            all(v == 422 for v in bad_f.values()), str(bad_f))

    bad = [f"{x['item']} — {x['actual']}" for x in out if not x["ok"]]
    rep.add("G-02", "RPT 계약 문장 (W3 · 정본 L3 · logic · D-512 · D-805 · D-806 · D-609 · goal §3.4 SVG+표 · 계약 §2 예외) — 자동 확인", not bad,
            f"항목 {len(out)} · 어긋남 {len(bad)}", bad)
    for x in out:
        rep.summary.append((f"RPT 계약 문장 — {x['item']}", ("OK — " if x["ok"] else "어긋남 — ") + x["actual"]))
    return out


# ── 화면 GET 조회 칸 — NUL · 틀린 날짜 ──────────────────────────────────
def check_get_inputs(clients, html_of: dict, rep: Report) -> list[dict]:
    from lcomfine.app import nav

    adm = clients["admin"]
    out = []
    for sid, html in html_of.items():
        s = nav.by_id(sid)
        if s.menu_code in LATER_MENUS:
            continue
        for form in parse(html).forms:
            if form["method"] != "get":
                continue
            target = form["action"] or s.path
            for inp in form["inputs"]:
                if inp["type"] in ("hidden", "submit", "checkbox", "radio"):
                    continue
                vals = [("NUL", NUL)]
                if inp["type"] in ("date", "month") or re.search(r"date|_on$|from|to$|day|month|ym", inp["name"]):
                    vals.append(("틀린 날짜", "2026-13-45"))
                for tag, v in vals:
                    r = adm.get(target, params={inp["name"]: v})
                    out.append({"sid": sid, "path": target, "name": inp["name"], "tag": tag, "status": r.status_code})
    s500 = [x for x in out if server_error(x["status"])]
    ok_bad_date = [x for x in out if x["tag"] == "틀린 날짜" and x["status"] == 200]
    rep.summary.append(("화면 GET 조회 칸 — NUL · 틀린 날짜", f"요청 {len(out)} · 500 {len(s500)} · 422 {sum(x['status'] == 422 for x in out)}"
                        f" · 200 {sum(x['status'] == 200 for x in out)} (틀린 날짜를 200 으로 받은 칸 {len(ok_bad_date)})"))
    for x in s500:
        rep.defects.append(f"GET {x['path']}?{x['name']}=<{x['tag']}> ({x['sid']} · admin) → {x['status']}")
    return out


# ── 계약 문장 — 정본 L3 · 미확정 표시 (참고) ───────────────────────────
def _norm(t: str) -> str:
    return re.sub(r"\s+", "", t)


#: 계약 문장(function-list) 밖에서 화면 표시를 정한 결정 — decisions.md 의 「그동안 / 지금」 문장. 화면 ID → 보여야 하는 D-번호
DECISION_UNDECIDED: dict[str, tuple[str, ...]] = {
    "HOME-030": ("D-526",),     # D-526 「화면에 `미확정 (D-526)` 을 적는다」 (Ruling 24 뒤 · 개인 추가 알림의 범위)
    "PRD-040": ("D-519",),      # D-519 「로스율은 화면에 `미확정 (D-519)` 와 원 수량을 함께 보인다」
    "INS-040": ("D-519",),
}


#: 계약이 「…이면 미확정 (D-nn)」 처럼 조건부로 적은 것 — 늘 보일 필요가 없다. 조건을 만들어 따로 본다(check_col_contract 10)
CONDITIONAL_UNDECIDED: dict[str, tuple[str, ...]] = {
    "TRK-030": ("D-516",),      # F-TRK-031 「status 미수집 / 미확정 (D-516) / ok」 — 매출액 열이 매핑되지 않았을 때만
}


def undecided_expected(screen_id: str) -> list[str]:
    """그 화면 본문에 보여야 하는 「미확정 (D-nn)」 — 계약 문장(function-list.md)의 D-번호 + decisions.md 가 화면에 적으라고 한 것
    (조건부 표시 CONDITIONAL_UNDECIDED 는 뺀다)."""
    from lcomfine.app import contracts

    und = set(re.findall(r"미확정 \((D-\d+)\)", " ".join(f.contract for f in contracts.functions_of(screen_id))))
    und |= set(DECISION_UNDECIDED.get(screen_id, ()))
    und -= set(CONDITIONAL_UNDECIDED.get(screen_id, ()))
    return sorted(und)


def check_l3(html_of: dict, rep: Report) -> list[dict]:
    """계약 문장 대조. 「미확정 (D-nn)」 표시는 G-02 오류 계약(§2.7 「501 `미확정 (D-nn)` 명시 · 조용한 폴백 금지」)의 몫으로 결함에 센다.
    L3 낱말은 자동 대조라 참고만 — 사람이 화면을 열어 판정한다(「품목 목록」 글자가 없어도 표가 있으면 결함이 아니다)."""
    from tools import design_doc

    e = design_doc.effective()
    out = []
    for m in e["menus"]:
        if m["code"] in LATER_MENUS:
            continue
        for s in m["screens"]:
            html = html_of.get(s["id"])
            if html is None:
                continue
            text = _norm(" ".join(parse(html).text))
            missing = []
            for item in s["l3"]:
                parts = [x for x in re.split(r"[·,/()→+]|\s및\s", item) if x.strip()]
                for part in parts:
                    words = [w for w in part.split() if len(w) >= 2]
                    if _norm(part) in text or (words and all(_norm(w) in text for w in words)):
                        continue
                    missing.append(part.strip())
            und = undecided_expected(s["id"])
            und_missing = [d for d in und if f"미확정({d})" not in text]
            out.append({"sid": s["id"], "l3": s["l3"], "missing": missing, "undecided": und, "undecided_missing": und_missing})
    nm = sum(1 for x in out if x["missing"])
    nu = sum(1 for x in out if x["undecided_missing"])
    rep.summary.append(("계약 문장 — 화면 본문에 정본 L3 낱말 (참고 · 사람이 판정)",
                        f"화면 {len(out)} · 빠진 낱말이 있는 화면 {nm}"))
    rep.summary.append(("계약 문장 — 계약 · 결정의 「미확정 (D-nn)」 이 화면 본문에 보임", f"해당 화면 {sum(1 for x in out if x['undecided'])} · 안 보이는 화면 {nu}"
                        + (" — " + "; ".join(f"{x['sid']} {x['undecided_missing']}" for x in out if x["undecided_missing"]) if nu else "")))
    for x in out:
        if x["undecided_missing"]:
            rep.defects.append(f"[미확정 표시] {x['sid']} 본문에 {x['undecided_missing']} 가 안 보임 (계약 · decisions.md 는 보이라고 한다)")
    return out


# ── 실행 ────────────────────────────────────────────────────────────────
def main() -> int:
    if "--cleanup-all" in sys.argv:          # 앞 실행이 정리 전에 죽었을 때 — 접두 `QA1-` 행 전부
        w = World(None)
        w.p = "QA1-"
        w.cleanup()
        print("QA1- 남은 행:", w.leftovers() or 0)
        return 0
    rep = Report()
    app, clients = app_and_clients()
    check_functions(app, rep)
    html_of = check_screens(app, clients, rep)
    check_writes(clients, rep)
    _, err, html_world = check_errors(clients, rep)
    gets = check_get_inputs(clients, html_of, rep)
    l3 = check_l3({**html_of, **html_world}, rep)      # 세계가 있는 동안의 화면(행이 있는 목록)으로 대조 · 없으면 빈 화면

    # G-02 오류 계약 — 사례 · GET 조회 칸 · 403 문장 · 미확정 표시 · 세계 · 정리. 결함 하나라도 있으면 FAIL (게이트를 낮추지 않는다)
    n_case = len(err)
    n_bad = sum(1 for x in err if not x["ok"])
    n500 = sum(1 for x in err if server_error(x["status"]))
    g500 = sum(1 for x in gets if server_error(x["status"]))
    other = [d for d in rep.defects if d.startswith(("[세계]", "[정리]", "[403 문장]", "[미확정 표시]"))]
    rep.add("G-02", "오류 계약 (api-contract §1 · §3 · goal §2.7) — 쓰기 사례 · GET 조회 칸 · 403 문장 · 미확정 표시", not rep.defects,
            f"사례 {n_case} 어긋남 {n_bad} 500 {n500} · GET 조회 {len(gets)} 500 {g500} · 그 밖 결함 {len(other)}", rep.defects)

    w = max(len(i) for _, i, _, _ in rep.rows)
    print(f"QA1 기능 · 계약 전수 (tools/check_screens.py · {SCOPE}) — 기대값: function-list.md · permission-matrix.md · ia.json · api-contract.md")
    print("-" * 110)
    for g, item, ok, actual in rep.rows:
        print(f"{g}  {item:<{w}}  {'PASS' if ok else 'FAIL'}  {actual}")
    print("-" * 110)
    for title, bad in rep.details:
        print(f"[{title}] {len(bad)}")
        for b in bad[:40]:
            print(f"    - {b}")
        if len(bad) > 40:
            print(f"    … 외 {len(bad) - 40}")
    print("\n요약 (게이트 밖 — 오류 계약 · 계약 문장)")
    print("| 구분 | 실측 |\n|---|---|")
    for title, actual in rep.summary:
        print(f"| {title} | {actual} |")
    misses = [x for x in l3 if x["missing"]]
    if misses:
        print(f"\n[참고 · L3 낱말이 본문에 안 보이는 화면] {len(misses)} (자동 대조 — 결함 판정은 outputs/qa1-기능계약.md §4)")
        for x in misses:
            print(f"    - {x['sid']}: {x['missing']}  (L3 {x['l3']})")
    n_fail = sum(1 for *_, ok, _ in rep.rows if not ok)
    by_gate = {}
    for g, _, ok, _ in rep.rows:
        by_gate.setdefault(g, []).append(ok)
    print("\n" + " · ".join(f"{g} {'PASS' if all(v) else 'FAIL'} ({sum(v)}/{len(v)})" for g, v in by_gate.items())
          + f" · FAIL 행 {n_fail} → 종료코드 {min(n_fail, 125)}")
    if "--json" in sys.argv:                 # 사례별 실측을 파일로 (리포트 근거)
        import json

        out = Path(sys.argv[sys.argv.index("--json") + 1])
        out.write_text(json.dumps({"errors": err, "gets": gets, "l3": l3, "rows": rep.rows}, ensure_ascii=False, indent=1, default=str),
                       encoding="utf-8")
    return min(n_fail, 125)


if __name__ == "__main__":
    raise SystemExit(main())
