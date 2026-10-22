# tests/test_arch_usecases.py — 업무별 유스케이스 10 (D-530 · 공통 참고 페이지 `/guide/usecases`) — 실제 DB `lcomfine_db` · 시드 뒤.
# 페이지에 적힌 단계 · 부서 · 알림 · 막힘 규칙이 코드와 계약에서 온 것인지 대조한다(지어내지 않는다):
#   단계의 화면 = nav · 기능 = contracts(그 기능의 화면) · 하는 부서 = permission-matrix 의 W 칸 · 알림 = notify.EVENTS +
#   그 단계 라우터의 실제 `notify.emit` · 알림이 여는 화면 = emit 의 link 식 · 막히는 경우 = 라우터가 내는 422 문장.
# 1280 · 390 가로 스크롤은 Playwright 캡처로 확인한다(progress.md) — 여기서는 그림 · 표가 스크롤 상자 안에 있는지만 본다.
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lcomfine.app import contracts, nav, notify, usecases
from lcomfine.app.main import app
from lcomfine.app.settings import get_settings
from lcomfine.db import conn
from lcomfine.db.seed import USERS

HTML = {"accept": "text/html"}
PKG = Path(__file__).resolve().parents[1] / "src" / "lcomfine"
LOGIN_OF = {code: login_id for login_id, _name, code in USERS}
PATH_OF_RE = re.compile(r"""path_of\(\s*['"]([A-Z]+-\d{3})['"]\s*\)""")


def _cells() -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for sid, role, level in contracts.permission_cells():
        out.setdefault(sid, {})[role] = level
    return out


def _client(login_id: str | None = None) -> TestClient:
    c = TestClient(app, raise_server_exceptions=False)
    if login_id:
        pw = get_settings().seed_password
        assert pw, "LCOMFINE_SEED_PASSWORD 미설정 — `make setup`"
        r = c.post("/login", data={"login_id": login_id, "password": pw}, headers=HTML, follow_redirects=False)
        assert r.status_code == 303, f"{login_id} 로그인 {r.status_code}"
    return c


@pytest.fixture(scope="module")
def pages() -> dict[str, str]:
    out = {}
    for code, login_id in LOGIN_OF.items():
        r = _client(login_id).get(usecases.PATH, headers=HTML)
        assert r.status_code == 200, f"{code} {r.status_code}"
        out[code] = r.text
    return out


def _src(rel: str) -> str:
    return (PKG / rel).read_text(encoding="utf-8")


def _steps():
    return [(uc, s) for uc in usecases.USECASES for s in uc.steps]


# ── 페이지 · 상단 바 ──────────────────────────────────────────────────────

def test_page_200_logged_in_and_303_anonymous():
    assert _client("admin").get(usecases.PATH, headers=HTML).status_code == 200
    r = _client().get(usecases.PATH, headers=HTML, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login")
    assert _client().get(usecases.PATH, follow_redirects=False).status_code == 401


def test_common_page_outside_screen_contract():
    """정본 화면이 아니다 — nav 화면 · 권한 칸 · 기능 목록에 없다(G-01~G-03 기대값 불변) · 공통 라우트로 집계에서 빠진다."""
    from tools.check_trace import COMMON_ROUTES
    assert nav.by_path(usecases.PATH) is None
    assert all(usecases.PATH not in f.api for f in contracts.functions())
    assert usecases.PATH in COMMON_ROUTES
    assert len(nav.SCREENS) == 66


def test_ten_usecases_in_order(pages):
    titles = [uc.title for uc in usecases.USECASES]
    assert len(titles) == 10 and [uc.no for uc in usecases.USECASES] == list(range(1, 11))
    html = pages["ADM"]
    assert "<title>업무별 유스케이스" in html
    found = re.findall(r'<details class="panel uc" id="uc-(\d+)" data-usecase="\d+"( open)?>', html)
    assert [int(n) for n, _ in found] == list(range(1, 11))
    assert [bool(o) for _, o in found] == [True] + [False] * 9            # 첫 하나만 열림
    for n in range(1, 11):
        assert f'href="#uc-{n}"' in html                                  # 목차 · 지도 · 다음 링크(앵커)
    pos = [html.index(t) for t in titles]
    assert pos == sorted(pos)
    assert html.count('<svg class="swim"') == 10                          # 유스케이스마다 스윔레인
    assert 'data-section="flow-map"' in html and 'data-table="uc-dept"' in html
    assert "<script" not in html.split("</head>", 1)[1]                    # 본문에 스크립트 없음


def test_topnav_link_for_every_department(pages):
    for code, login_id in LOGIN_OF.items():
        home = _client(login_id).get("/", headers=HTML).text
        nav_html = re.search(r'<nav class="topnav".*?</nav>', home, re.S)
        assert nav_html, f"{code}: 상단 바 없음"
        links = re.findall(r'<a href="([^"]+)"[^>]*>([^<]+)</a>', nav_html.group(0))
        names = [n for _, n in links]
        assert names[0] == "내 할 일" and names[-1] == "업무별 유스케이스", (code, names)
        assert ("/guide/usecases", "업무별 유스케이스") in links
        page_nav = re.search(r'<nav class="topnav".*?</nav>', pages[code], re.S).group(0)
        assert f'href="{usecases.PATH}" aria-current="page"' in page_nav, code
    assert "대시보드" not in re.search(r'<nav class="topnav".*?</nav>', pages["DS"], re.S).group(0)   # RPT 칸 없는 부서


# ── 사실 대조 — nav · 계약 · 권한 칸 ─────────────────────────────────────

def test_every_step_screen_in_nav_and_function_of_that_screen():
    for uc, s in _steps():
        if s.screen_id is None:                                            # 배치 단계 — 화면 · 기능 없음
            assert s.lane == usecases.BATCH and s.fn is None and s.command and s.event
            continue
        sc = nav.by_id(s.screen_id)
        assert not sc.common, (uc.no, s.screen_id)
        f = contracts.function(s.fn)
        assert f.screen_id == s.screen_id, f"UC{uc.no}: {s.fn} 의 화면은 {f.screen_id} ≠ {s.screen_id}"
    for uc in usecases.USECASES:
        for sid in uc.checks:
            nav.by_id(sid)
        lo, hi = uc.stages
        assert 0 <= lo <= hi < len(nav.FLOW)


def test_step_departments_match_permission_matrix(pages):
    cells = _cells()
    for uc, s in _steps():
        if s.screen_id is None:
            continue
        row = cells.get(s.screen_id, {})
        w = [c for c in usecases.role_order() if row.get(c) == "W"]
        r = [c for c in usecases.role_order() if row.get(c) == "R"]
        assert usecases.doers(s.screen_id) == w, (uc.no, s.screen_id)
        assert usecases.readers(s.screen_id) == r, (uc.no, s.screen_id)
        if usecases.is_write(s):
            assert s.lane in w, f"UC{uc.no} {s.fn}: 그림의 부서 {s.lane} 가 W 칸 {w} 에 없다"
        else:
            assert s.lane in w + r, f"UC{uc.no} {s.fn}: 그림의 부서 {s.lane} 가 R 이상 {w + r} 에 없다"
    # 페이지의 「처리」 부서 = W 칸 · 「조회」 = R 칸(쓰기 단계) / R 이상(조회 단계)
    html = pages["ADM"]
    for uc in usecases.USECASES:
        body = re.search(rf'data-table="uc-steps-{uc.no}".*?</table>', html, re.S).group(0)
        rows = re.findall(r'<tr data-step="(\d+)" data-screen="([^"]*)" data-fn="([^"]*)">.*?data-doers="([^"]*)" data-viewers="([^"]*)"', body, re.S)
        assert len(rows) == len(uc.steps)
        for (n, sid, fn, doers, viewers), s in zip(rows, uc.steps):
            assert (sid, fn) == (s.screen_id or "", s.fn or "")
            if not sid:
                continue
            row = cells[sid]
            w = [c for c in usecases.role_order() if row.get(c) == "W"]
            r = [c for c in usecases.role_order() if row.get(c) == "R"]
            if usecases.is_write(s):
                assert doers.split() == w and viewers.split() == r, (uc.no, n)
            else:
                assert doers == "" and viewers.split() == [c for c in usecases.role_order() if c in w + r], (uc.no, n)


def test_department_matrix_marks_writers_strong(pages):
    cells = _cells()
    html = pages["ADM"]
    table = re.search(r'data-table="uc-dept".*?</table>', html, re.S).group(0)
    rows = re.findall(r"<tr>\s*<td><a href=\"#uc-(\d+)\".*?</tr>", table, re.S)
    assert rows == [str(n) for n in range(1, 11)]
    for uc in usecases.USECASES:
        writers = {c for s in uc.steps if s.screen_id and usecases.is_write(s)
                   for c, lv in cells[s.screen_id].items() if lv == "W"}
        inv = usecases.involvement(uc)
        assert {c for c, lv in inv.items() if lv == "W"} == writers, uc.no


# ── 알림 — notify.EVENTS · 실제 emit · 알림이 여는 화면 ─────────────────

def _emit_calls(text: str, event: str) -> list[str]:
    calls = []
    for m in re.finditer(rf'notify\.emit\(\s*cur,\s*"{re.escape(event)}"', text):
        depth = 0
        for j in range(text.index("(", m.start()), len(text)):
            depth += {"(": 1, ")": -1}.get(text[j], 0)
            if depth == 0:
                calls.append(text[m.start():j + 1])
                break
    return calls


def _link_screens(text: str, call: str) -> set[str]:
    """emit 의 `link=` 식이 가리키는 화면 — 직접 `path_of('X')` · 같은 파일의 link 함수 본문 · `P_*` 상수까지 따라간다."""
    link = re.search(r"link=(.*?),\s*dedupe_key=", call, re.S).group(1)
    parts = [link]
    for name in re.findall(r"\b([A-Za-z_]\w*)\(", link):
        body = re.search(rf"^def {name}\(.*?(?=^\S)", text, re.S | re.M)
        if body:
            parts.append(body.group(0))
    ids = set()
    for part in parts:
        ids |= set(PATH_OF_RE.findall(part))
        for const in re.findall(r"\b(P_[A-Z_]+)\b", part):
            m = re.search(rf"^{const} = nav\.path_of\(\s*['\"]([A-Z]+-\d{{3}})['\"]", text, re.M)
            if m:
                ids.add(m.group(1))
    return ids


def test_event_tables_match_notify():
    assert set(usecases.EVENT_LABEL) == set(notify.EVENTS)
    assert set(usecases.EVENT_SCREEN) == set(notify.EVENTS)
    used = {s.event for _, s in _steps() if s.event}
    assert used == set(notify.EVENTS), f"유스케이스에 나오지 않는 알림: {set(notify.EVENTS) - used}"


def test_each_step_event_is_really_emitted_there():
    for uc, s in _steps():
        if not s.event:
            continue
        assert s.event in notify.EVENTS
        rel = usecases.emit_source(s)
        text = _src(rel)
        calls = _emit_calls(text, s.event)
        assert calls, f"UC{uc.no} {s.fn or s.command}: {rel} 에 notify.emit(cur, \"{s.event}\") 가 없다"
        # 알림이 여는 화면 = emit 의 link 식
        for call in calls:
            assert _link_screens(text, call) == {usecases.EVENT_SCREEN[s.event]}, (s.event, rel)
        # 라우터 밖에서 emit 하면 그 화면의 라우터가 그 함수를 부른다
        if s.emit_in == "app/erp_upload.py":
            assert "erp_upload.apply(" in _src(f"app/routers/{nav.by_id(s.screen_id).module}.py")
        if s.emit_in == "jobs.py":
            assert s.command == "uv run python -m lcomfine.jobs due-check" and '"due-check": due_check' in text
        if s.screen_id and not s.emit_in:
            fn = contracts.function(s.fn)
            assert f'require_fn("{s.fn}")' in text, f"{rel} 에 {s.fn} 쓰기 라우트가 없다"
            assert fn.is_write


def test_emit_free_steps_do_not_claim_events():
    """알림을 적지 않은 쓰기 단계의 라우트에는 정말 emit 이 없는가 — 그 함수 본문(데코레이터 ~ 다음 데코레이터)을 본다."""
    for uc, s in _steps():
        if s.event or not s.screen_id or not usecases.is_write(s):
            continue
        text = _src(f"app/routers/{nav.by_id(s.screen_id).module}.py")
        m = re.search(rf'require_fn\("{s.fn}"\)\).*?(?=^@router|\Z)', text, re.S | re.M)
        assert m, (uc.no, s.fn)
        assert "notify.emit(" not in m.group(0), f"UC{uc.no} {s.fn}: 라우트가 알림을 내는데 유스케이스에 없다"


# ── 막히는 경우 — 라우터가 실제로 422 로 막는 문장 ─────────────────────────

def test_blocks_are_real_422_messages():
    for uc in usecases.USECASES:
        assert uc.blocks, uc.no
        for b in uc.blocks:
            text = _src(b.src)
            assert b.message in text, f"UC{uc.no}: {b.src} 에 「{b.message}」 가 없다"
            raised = [m for m in re.finditer(re.escape(b.message), text)
                      if re.search(r"(raise (http\.validation_error|_bad|bad|UploadError)|errors\.append)\([^\n]*(\n[^\n]*){0,2}$",
                                   text[max(0, m.start() - 300):m.start()])]
            assert raised, f"UC{uc.no}: 「{b.message}」 를 422 로 올리는 raise 가 {b.src} 에 없다"
            # errors.append(...) 로 모은 사유는 같은 함수 끝에서 validation_error(..., fields=errors) 로 한꺼번에 422 (shp)
            if not re.search(r"raise ", text[max(0, raised[0].start() - 300):raised[0].start()]):
                rest = text[raised[0].start():raised[0].start() + 1200]          # 같은 함수 안
                assert re.search(r"raise http\.validation_error\(.{0,200}?fields=errors\)", rest, re.S), (uc.no, b.message)


def test_undecided_items_are_open_decisions():
    text = (Path(__file__).resolve().parents[1] / "decisions.md").read_text(encoding="utf-8")
    for uc in usecases.USECASES:
        for dn, _ in list(uc.undecided) + [u for s in uc.steps for u in s.undecided]:
            head = re.search(rf"^## {dn} .*$", text, re.M)
            assert head and "차단" in head.group(0), f"{dn} 는 차단(미확정) 결정이 아니다"


# ── 링크 · 권한 ────────────────────────────────────────────────────────

def _href(path: str) -> str:
    return rf'href="{re.escape(path)}(\?[^"]*)?"'


def test_links_only_to_screens_the_user_can_open(pages):
    cells = _cells()
    screens = {s.screen_id for _, s in _steps() if s.screen_id} | {sid for uc in usecases.USECASES for sid in uc.checks} \
        | set(usecases.EVENT_SCREEN.values()) | set(nav.FLOW)
    for code, html in pages.items():
        main = html.split('<main class="main" id="main">', 1)[1]
        for sid in screens:
            path = nav.path_of(sid)
            can = sid in cells and code in cells[sid]
            linked = re.search(_href(path), main) is not None
            assert linked == can, f"{code} {sid}: 칸 {'있음' if can else '없음'} · 링크 {'있음' if linked else '없음'}"
            if not can:
                assert f'data-screen-off="{sid}"' in main, (code, sid)
    assert "권한 없음" in pages["DS"].split('<main class="main" id="main">', 1)[1]


def test_page_writes_no_business_rows():
    """페이지는 읽기만 — 열기 전후로 모든 표의 행 수가 같다(조회 로그도 남기지 않는다 · /ia 와 같다)."""
    c = _client("pr")
    tables = [r["table_name"] for r in conn.q(
        "select table_name from information_schema.tables where table_schema = 'public' and table_type = 'BASE TABLE' "
        "order by table_name")]
    count_sql = " union all ".join(f"select '{t}' as t, count(*) as n from \"{t}\"" for t in tables)
    before = {r["t"]: r["n"] for r in conn.q(count_sql)}
    for _ in range(2):
        assert c.get(usecases.PATH, headers=HTML).status_code == 200
    after = {r["t"]: r["n"] for r in conn.q(count_sql)}
    assert after == before, {t: (before[t], after[t]) for t in tables if before[t] != after[t]}


def test_layout_boxes_scroll_inside_not_page(pages):
    """390 에서 페이지가 가로로 밀리지 않게 — 넓은 그림 · 지도 · 표는 스크롤 상자 안에 있다. 색은 토큰만."""
    html = pages["ADM"]
    assert html.count('<div class="uc-scroll uc-scroll--swim">') == 10
    assert re.search(r'<div class="uc-scroll">\s*<div class="ucmap"', html)
    css = (PKG / "app" / "static" / "style.css").read_text(encoding="utf-8")
    block = css[css.index("/* ── 업무별 유스케이스"):]
    assert ".uc-scroll { overflow-x: auto" in block
    assert "@media (max-width: 720px)" in block and ".uc-steps thead { display: none; }" in block
    assert not re.search(r"#[0-9a-fA-F]{3,6}\b|rgb\(", block), "유스케이스 CSS 에 색 값을 직접 적었다 — 토큰만"
    tpl = (PKG / "app" / "templates" / "guide_usecases.html").read_text(encoding="utf-8")
    assert not re.search(r"#[0-9a-fA-F]{6}\b|rgb\(|<script", tpl)
