#!/usr/bin/env python
"""QA1 기능 · 계약 전수 (W1) — `uv run python tools/check_screens.py`. 서버를 띄우지 않고 TestClient 로 앱을 부른다.

기대값은 개발 테스트가 아니라 계약에서 직접 끌어온다:
  · `contracts/function-list.md` (contracts.functions()) — 기능 · API · 권한(W 부서 · R 이상 · 권한 예외)
  · `contracts/permission-matrix.md` (contracts.permission_cells()) — 화면 67 × 부서 8 칸
  · `contracts/ia.json` + `ia-overrides.json` (tools.design_doc.effective()) — 정본 L3 · logic
  · `contracts/api-contract.md` — 오류 계약(422 · 404 · 501 · 403 문장)

검사 (W1 범위 = 대메뉴가 DOC · COL · RPT 가 아닌 기능 109):
  G-02  ① W1 기능의 API 가 라우트에 글자 그대로 ② `@pytest.mark.fn` 표식 ③ 쓰기 라우트의 `require_fn(<그 기능 ID>)` (정적)
  G-03  화면 67 × 계정 8 GET — 칸 W/R → 200 · 칸 없음 → 403 (placeholder 18 포함) · W1 화면 placeholder 0
  G-19  같은 전수의 403 쪽 + 메뉴에 칸 밖 화면 없음 + 쓰기 58 × 계정 8 POST (W → 권한 통과 · R/없음 → 403 · 권한 예외 R 통과)
        + DB `sys_permission` = 권한 매트릭스
  G-02  오류 계약 (api-contract §1 · §3 · goal §2.7 — QA1 몫): QA1 세계(접두 `QA1-`)를 화면의 HTTP 로 만들고
        쓰기 기능마다 누락 422 · 없는 ID 404 · 미확정 501 · NUL · 자릿수 초과 · 음수 422 를 두드린 뒤 지운다(응답 모양까지).
        화면 GET 의 조회 칸에 NUL · 틀린 날짜를 넣어 500 이 아닌지 · 화면 GET 403 의 문장 · 계약의 「미확정 (D-nn)」 이 본문에 보이는지.
        §3 은 따로 한 행 — 422 가 어느 항목인지 짚는가(라우터 선검사 · 핸들러의 「입력」 한 줄이 아님).
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

LATER_MENUS = ("DOC", "COL", "RPT")          # W2~W4 — 아직 placeholder
LOGINS = ("sl", "pr", "sh", "ds", "ac", "st", "ex", "admin")
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
    from lcomfine.app import contracts

    return [f for f in contracts.functions() if f.menu_code not in LATER_MENUS]


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
    rep.add("G-02", f"W1 기능 {len(fns)} — API 가 라우트에 글자 그대로", not no_route,
            f"라우트 있음 {len(fns) - len(no_route)}/{len(fns)}", no_route)

    marks, errs = fn_marks(sorted((ROOT / "tests").glob("test_*.py")))
    no_mark = [f.id for f in fns if f.id not in marks]
    rep.add("G-02", f"W1 기능 {len(fns)} — @pytest.mark.fn 표식", not no_mark and not errs,
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
    rep.add("G-19", f"W1 쓰기 라우트 {len(writes)} — require_fn(<그 기능 ID>) (정적)", not wrong,
            f"맞음 {len(writes) - len(wrong)}/{len(writes)}", wrong)
    reads = [f for f in fns if not f.is_write]
    rbad = [f"{f.id} {f.api} → {deps.get((f.method, f.path))}" for f in reads
            if not deps.get((f.method, f.path)) or not ({f.id, "screen:" + f.screen_id} & set(deps.get((f.method, f.path))))]
    rep.add("G-19", f"W1 조회 라우트 {len(reads)} — require_screen(화면) 또는 require_fn(기능) (정적)", not rbad,
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
    rep.add("G-03", f"W1 화면 {len(w1)} — placeholder 0 (DOC·COL·RPT 18 은 W2~W4)", not w1_ph,
            f"W1 placeholder {len(w1_ph)} · 전체 placeholder {len(ph)}", w1_ph)

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
        return self

    def failed_steps(self) -> list[str]:
        return [f"{s} → {st} {m}" for s, st, m in self.steps if st != 200]

    def cleanup(self) -> None:
        from lcomfine.db import conn

        like = self.p + "%"
        with conn.tx() as cur:
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

    def leftovers(self) -> dict[str, int]:
        from lcomfine.db import conn

        like = self.p + "%"
        q = {"item": "item_code", "customer": "customer_code", "warehouse": "warehouse_code", "location": "location_code",
             "standard": "standard_code", "plate": "plate_code", "sys_user": "login_id", "sys_common_code": "code",
             "notification": "dedupe_key"}
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

    out = {}
    for s in nav.SCREENS:
        if s.common or s.menu_code in LATER_MENUS:
            continue
        r = w.c.get(s.path, headers=HTML, follow_redirects=False)
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
        html_world = world_html(w)
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


def undecided_expected(screen_id: str) -> list[str]:
    """그 화면 본문에 보여야 하는 「미확정 (D-nn)」 — 계약 문장(function-list.md)의 D-번호 + decisions.md 가 화면에 적으라고 한 것."""
    from lcomfine.app import contracts

    und = set(re.findall(r"미확정 \((D-\d+)\)", " ".join(f.contract for f in contracts.functions_of(screen_id))))
    und |= set(DECISION_UNDECIDED.get(screen_id, ()))
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
    print("QA1 기능 · 계약 전수 (tools/check_screens.py · W1) — 기대값: function-list.md · permission-matrix.md · ia.json · api-contract.md")
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
