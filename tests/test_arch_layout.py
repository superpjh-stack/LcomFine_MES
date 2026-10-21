# tests/test_arch_layout.py — 레이아웃 v2 (묶음 메뉴 · 흐름 띠 · 디자인 토큰 · /ia) — 실제 DB `lcomfine_db` · 시드 뒤
# 로그인은 실제 `/login` POST 를 탄다(비밀번호는 settings 에서 — 값을 적지 않는다).
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lcomfine.app import contracts, nav, rbac
from lcomfine.app.settings import get_settings

APP_DIR = Path(__file__).resolve().parents[1] / "src" / "lcomfine" / "app"
TEMPLATES = APP_DIR / "templates"
STATIC = APP_DIR / "static"
SEED_IDS = ("sl", "pr", "sh", "ds", "ac", "st", "ex", "admin")
HTML = {"accept": "text/html"}


@pytest.fixture(scope="module")
def app():
    from lcomfine.app.main import app as the_app
    return the_app


def _client(app, login_id: str | None = None) -> TestClient:
    c = TestClient(app)
    if login_id:
        pw = get_settings().seed_password
        assert pw, "LCOMFINE_SEED_PASSWORD 가 없다 (.env)"
        r = c.post("/login", data={"login_id": login_id, "password": pw}, headers=HTML, follow_redirects=False)
        assert r.status_code == 303, r.text[:300]
    return c


def _sidebar(html: str) -> str:
    m = re.search(r'<nav class="side".*?</nav>', html, re.S)
    assert m, "좌측 메뉴(nav.side) 없음"
    return m.group(0)


def _flow(html: str) -> str:
    m = re.search(r'<nav class="flow".*?</nav>', html, re.S)
    assert m, "흐름 띠(nav.flow) 없음"
    return m.group(0)


def test_login_page_lists_8_quick_accounts_in_dev(app):
    r = _client(app).get("/login", headers=HTML)
    assert r.status_code == 200
    ids = re.findall(r'name="quick_id" value="([^"]+)"', r.text)
    assert sorted(ids) == sorted(SEED_IDS)
    for role in rbac.roles():            # 부서 이름이 단추 묶음에 보인다 (DB 값)
        assert role.name in r.text
    assert 'name="device"' not in r.text and "device=" not in r.text.replace("width=device-width", "")


def test_login_failure_is_401(app):
    r = _client(app).post("/login", data={"login_id": "sh", "password": "x"}, headers=HTML)
    assert r.status_code == 401
    assert 'role="alert"' in r.text


def test_sidebar_shows_only_bundles_with_permitted_screens(app):
    side = _sidebar(_client(app, "sh").get("/", headers=HTML).text)
    bundles = re.findall(r'data-bundle="(s\d)"', side)
    menus = re.findall(r'data-menu="([A-Z]+)"', side)
    screens = re.findall(r'data-screen="([A-Z]+-\d+)"', side)
    sh = rbac.load_user("sh")
    # 사이드바 = rbac.visible_menu 그대로 — 볼 화면이 하나도 없는 묶음 · 대메뉴는 없다
    want = rbac.visible_menu(sh)
    assert bundles == [n["bundle"][0] for n in want]
    assert menus == [m.code for n in want for m in n["menus"]]
    assert screens == [sc.screen_id for n in want for m in n["menus"] for sc in m.screens]
    # 출하실의 ⑦ 지원에는 DOC 만(DOC-010 하나) — permission-matrix.md 기본값
    s7 = re.search(r'data-bundle="s7".*?(?=data-bundle=|</nav>)', side, re.S).group(0)
    assert re.findall(r'data-menu="([A-Z]+)"', s7) == ["DOC"]
    assert re.findall(r'data-screen="([A-Z]+-\d+)"', s7) == ["DOC-010"]
    assert "SYS" not in menus and "BAS-030" not in screens
    # 기준정보를 하나도 못 보는 부서(디자인·개발실)에는 BAS 대메뉴 자체가 없다
    ds_side = _sidebar(_client(app, "ds").get("/", headers=HTML).text)
    assert 'data-menu="BAS"' not in ds_side
    assert ds_side.count('aria-current="page"') == 1     # 지금 화면(HOME-010)


def test_flow_strip_links_only_permitted_steps(app):
    flow = _flow(_client(app, "pr").get("/", headers=HTML).text)
    steps = re.findall(r'data-step="([A-Z]+-\d+)"', flow)
    assert steps == list(nav.FLOW)
    pr = rbac.load_user("pr")
    for sid, ok in rbac.can_flow(pr):
        link = re.search(rf'<a [^>]*data-step="{sid}"', flow)
        span = re.search(rf'<span [^>]*data-step="{sid}"[^>]*aria-disabled="true"', flow)
        assert bool(link) == ok and bool(span) == (not ok), sid
    assert re.search(r'<span [^>]*data-step="COL-010"[^>]*aria-disabled="true"', flow)
    assert f'href="{nav.path_of("WO-010")}"' in flow


def test_no_device_param_in_templates():
    hits = [str(p) for d in (TEMPLATES, STATIC) for p in d.rglob("*") if p.is_file() and "device=" in p.read_text()]
    assert hits == []


def test_ia_page_counts_from_contracts(app):
    assert _client(app).get("/ia", headers=HTML, follow_redirects=False).status_code == 303   # 로그인 필요
    r = _client(app, "admin").get("/ia", headers=HTML)
    assert r.status_code == 200
    stats = dict(re.findall(r'data-count="(\w+)">(\d+)<', r.text))
    assert stats["menus"] == "17" and stats["screens"] == "67" and stats["cells"] == "260"
    c = rbac.counts()
    assert stats["w"] == str(c["W"]) and stats["r"] == str(c["R"])
    assert stats["functions"] == str(len(contracts.functions()))
    assert len(re.findall(r'<tr data-perm="[A-Z]+-\d+"', r.text)) == 67


def test_theme_tokens_present():
    css = (STATIC / "style.css").read_text()
    for tok in ("--bg: #f5f6f8", "--surface: #fff", "--ink: #1b2333", "--muted: #5d6779", "--line: #dde1e8",
                "--cyan: #0b7a8a", "--cyan-soft: #e0f1f3",
                "--bg: #11151d", "--surface: #181e29", "--ink: #e4e8ef", "--muted: #99a3b5", "--line: #2a3242",
                "--cyan: #4cc0cf"):
        assert tok in css, tok
    assert ':root:not([data-theme="light"])' in css and ':root[data-theme="dark"]' in css
    assert '"IBM Plex Sans KR","Apple SD Gothic Neo","Malgun Gothic",sans-serif' in css


def test_templates_have_no_inline_script():
    """스크립트는 `static/app.js` 하나뿐 — 템플릿에 인라인 `<script>` 가 없다 (base.html 의 app.js 한 줄만 외부 참조)."""
    for p in TEMPLATES.glob("*.html"):
        tags = re.findall(r"<script\b[^>]*>", p.read_text())
        assert all('src="/static/app.js' in t for t in tags), (p.name, tags)
    assert sum(len(re.findall(r"<script\b", p.read_text())) for p in TEMPLATES.glob("*.html")) == 1


def test_health_shape(app):
    r = TestClient(app).get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["db"] == "ok"
    assert body["menus"] == 17 and body["screens"] == 67
    assert isinstance(body["placeholders"], int)


def test_layout_shell_for_logged_in_user(app):
    html = _client(app, "sh").get("/", headers=HTML).text
    for land in ("<header", '<nav class="side"', "<main"):
        assert land in html
    assert "출하실 (예시)" in html                      # 사용자 이름(부서)
    assert f'href="{nav.path_of("HOME-020")}"' in html   # 알림 종
    assert "data-theme-toggle" in html
    assert "fonts.googleapis.com" in html
