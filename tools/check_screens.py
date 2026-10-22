#!/usr/bin/env python
"""QA1 기능 · 계약 전수 (W1 · W2) — `uv run python tools/check_screens.py`. 서버를 띄우지 않고 TestClient 로 앱을 부른다.

기대값은 개발 테스트가 아니라 계약에서 직접 끌어온다:
  · `contracts/function-list.md` (contracts.functions()) — 기능 · API · 권한(W 부서 · R 이상 · 권한 예외)
  · `contracts/permission-matrix.md` (contracts.permission_cells()) — 화면 67 × 부서 8 칸
  · `contracts/ia.json` + `ia-overrides.json` (tools.design_doc.effective()) — 정본 L3 · logic
  · `contracts/api-contract.md` — 오류 계약(422 · 404 · 501 · 403 문장)

검사 (범위 = 대메뉴가 DOC · RPT 가 아닌 기능 120 — W1 109 + W2 COL 11. DOC · RPT 는 W3 · W4 까지 placeholder 라 FAIL 로 세지 않는다):
  G-02  ① 범위 기능의 API 가 라우트에 글자 그대로 ② `@pytest.mark.fn` 표식 ③ 쓰기 라우트의 `require_fn(<그 기능 ID>)` (정적)
  G-03  화면 67 × 계정 8 GET — 칸 W/R → 200 · 칸 없음 → 403 (placeholder 11 포함) · 범위 화면 56 placeholder 0
  G-19  같은 전수의 403 쪽 + 메뉴에 칸 밖 화면 없음 + 쓰기 62 × 계정 8 POST (W → 권한 통과 · R/없음 → 403 · 권한 예외 R 통과)
        + DB `sys_permission` = 권한 매트릭스
  G-02  오류 계약 (api-contract §1 · §3 · goal §2.7 — QA1 몫): QA1 세계(접두 `QA1-`)를 화면의 HTTP 로 만들고
        쓰기 기능마다 누락 422 · 없는 ID 404 · 미확정 501 · NUL · 자릿수 초과 · 음수 422 를 두드린 뒤 지운다(응답 모양까지).
        W2: (예시) xlsx 를 openpyxl 로 만들어 `POST /col/uploads` 로 올리고(회차 2 · 교체 · 오류 행 · 미매핑 · 알림) 파일 없음 · 엑셀 아닌 파일 ·
        20MB 초과 · 기준 기간 역순 · 날짜 형식 · 매핑 없는 열 · 데이터 행 0 · 거래처 매핑 중복 · 없는 거래처를 두드린다 — 자기 회차 · 매핑만 지운다.
        화면 GET 의 조회 칸에 NUL · 틀린 날짜를 넣어 500 이 아닌지 · 화면 GET 403 의 문장 · 계약의 「미확정 (D-nn)」 이 본문에 보이는지.
        §3 은 따로 한 행 — 422 가 어느 항목인지 짚는가(라우터 선검사 · 핸들러의 「입력」 한 줄이 아님).
  G-02  COL 계약 문장 (정본 L3 · logic · D-516 · D-608) — 세계가 있는 동안 자동 확인: 오류 행 `is-error`(빨간색) · 미매핑 목록 · 교체됨 ·
        매핑 뒤 재반영 · 어음 만기 도래 · 30/60/90 구간 · 출하 대비 나란히 · 매출 열 매핑을 잠깐 지워 COL-050 · COL-060 · TRK-030 · HOME 회계부 카드의
        `미확정 (D-516)` (지운 매핑은 같은 함수 안에서 되돌린다) · TRK-030 수금 칸 ok/미수집 · ERP 업로드 기준일
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
from dataclasses import dataclass, field
from datetime import date, timedelta
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from lcomfine.app.settings import get_settings  # noqa: E402 — .env 를 먼저 읽는다

LATER_MENUS = ("DOC", "RPT")                 # W3 · W4 — 아직 placeholder (COL 은 W2 에 범위로 들어왔다)
SCOPE = "W1·W2"
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
    """범위 기능 — 대메뉴가 DOC · RPT 가 아닌 것 (W1 109 + W2 COL 11 = 120). 이름은 W1 때 것을 그대로 둔다(테스트가 부른다)."""
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
    rep.add("G-03", f"{SCOPE} 화면 {len(w1)} — placeholder 0 (DOC·RPT 11 은 W3·W4)", not w1_ph,
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
    rep.add("G-19", "권한 예외 F-HOME-022 — 칸 R 부서 통과", bool(exc) and all(x["ok"] for x in exc),
            f"{sum(x['ok'] for x in exc)}/{len(exc)}", [fmt(x) for x in exc if not x["ok"]])
    return results


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
        I["code"] = self.post("공통코드", "/sys/codes", {"group_code": "설비", "code": p + "EQ", "code_name": p + "설비 (예시)"}, key="id")
        I["noti_adm"] = conn.q1("insert into notification (event_key, to_role, message, link, dedupe_key) values "
                                "('request_created', 'ADM', %s, '/', %s) returning id", (p + "알림", p + "N-ADM"))["id"]
        I["noti_sl"] = conn.q1("insert into notification (event_key, to_role, message, link, dedupe_key) values "
                               "('request_created', 'SL', %s, '/', %s) returning id", (p + "알림", p + "N-SL"))["id"]
        I["wo_no"] = wo_no
        I["req_no"] = conn.q1("select request_no from production_request where id = %s", (I["req"],))["request_no"] if I["req"] else None
        self.build_col()
        return self

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
            cur.execute("delete from sys_user where login_id like %s", (like,))
        self.restore_map()

    def leftovers(self) -> dict[str, int]:
        from lcomfine.db import conn

        like = self.p + "%"
        q = {"item": "item_code", "customer": "customer_code", "warehouse": "warehouse_code", "location": "location_code",
             "standard": "standard_code", "plate": "plate_code", "sys_user": "login_id", "sys_common_code": "code",
             "notification": "dedupe_key", "erp_customer_map": "erp_code", "erp_upload_batch": "source_file"}
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
        check_col_contract(w, rep)
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
