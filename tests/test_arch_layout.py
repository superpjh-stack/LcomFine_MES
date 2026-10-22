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
    files = [p for d in (TEMPLATES, STATIC) for ext in ("*.html", "*.css", "*.js") for p in d.rglob(ext)]
    assert files
    hits = [str(p) for p in files if "device=" in p.read_text()]
    assert hits == []


def test_ia_page_counts_from_contracts(app):
    assert _client(app).get("/ia", headers=HTML, follow_redirects=False).status_code == 303   # 로그인 필요
    r = _client(app, "admin").get("/ia", headers=HTML)
    assert r.status_code == 200
    stats = dict(re.findall(r'data-count="(\w+)">(\d+)<', r.text))
    assert stats["menus"] == "17" and stats["screens"] == "66" and stats["cells"] == "257"
    c = rbac.counts()
    assert stats["w"] == str(c["W"]) and stats["r"] == str(c["R"])
    assert stats["functions"] == str(len(contracts.functions()))
    assert len(re.findall(r'<tr data-perm="[A-Z]+-\d+"', r.text)) == 66


def test_theme_tokens_present():
    css = (STATIC / "style.css").read_text()
    for tok in ("--bg: #f5f6f8", "--surface: #fff", "--ink: #1b2333", "--muted: #5d6779", "--line: #dde1e8",
                "--brand: #b3122e", "--brand-soft: #fbe8eb",                       # D-527 브랜드 크림슨(라이트)
                "--bg: #11151d", "--surface: #181e29", "--ink: #e4e8ef", "--muted: #99a3b5", "--line: #2a3242",
                "--brand: #f2667c",                                                 # 다크
                "--cyan: var(--brand)", "--cyan-soft: var(--brand-soft)"):          # 옛 이름은 브랜드의 별칭
        assert tok in css, tok
    assert ':root:not([data-theme="light"])' in css and ':root[data-theme="dark"]' in css
    assert '"IBM Plex Sans KR","Apple SD Gothic Neo","Malgun Gothic",sans-serif' in css


def _theme_blocks(css: str) -> dict[str, dict[str, str]]:
    """라이트(:root) · 다크(media) · 다크(data-theme) 세 토큰 묶음의 `--이름: #hex` 값."""
    def grab(start: str) -> dict[str, str]:
        i = css.index(start)
        body = css[i:css.index("}", i)]
        return dict(re.findall(r"(--[\w-]+):\s*(#[0-9a-fA-F]{3,6})\b", body))
    return {"light": grab(":root {"), "dark_media": grab(':root:not([data-theme="light"])'), "dark_attr": grab(':root[data-theme="dark"]')}


def _contrast(a: str, b: str) -> float:
    def lum(h: str) -> float:
        h = h.lstrip("#")
        h = "".join(c * 2 for c in h) if len(h) == 3 else h
        ch = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        ch = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in ch]
        return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_brand_tokens_contrast():
    """D-527 — 브랜드 토큰이 세 묶음에 모두 있고, 글자 대비 ≥ 4.5:1 · 상태 「나쁨」 은 브랜드와 다른 값."""
    blocks = _theme_blocks((STATIC / "style.css").read_text())
    assert blocks["dark_media"] == blocks["dark_attr"]          # 시스템 다크 = 토글 다크
    for name, t in blocks.items():
        for k in ("--brand", "--brand-strong", "--brand-soft", "--brand-ink", "--bad", "--bad-soft", "--surface", "--ink", "--bg"):
            assert k in t, (name, k)
        assert _contrast(t["--brand-ink"], t["--brand"]) >= 4.5, (name, "주요 단추 글자")
        assert _contrast(t["--brand-ink"], t["--brand-strong"]) >= 4.5, (name, "주요 단추 hover")
        assert _contrast(t["--brand"], t["--surface"]) >= 4.5, (name, "링크 · 현재 단계")
        assert _contrast(t["--brand"], t["--bg"]) >= 4.5, (name, "링크 · 바탕")
        assert _contrast(t["--ink"], t["--brand-soft"]) >= 4.5, (name, "선택 메뉴 글자")
        assert _contrast(t["--bad"], t["--bad-soft"]) >= 4.5, (name, "오류 칩 · 오류 행 글자")
        assert _contrast(t["--bad"], t["--surface"]) >= 4.5, (name, "오류 글자")
        assert t["--bad"].lower() != t["--brand"].lower() and t["--bad-soft"].lower() != t["--brand-soft"].lower(), name


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
    assert body["menus"] == 17 and body["screens"] == 66
    assert isinstance(body["placeholders"], int)


def test_layout_shell_for_logged_in_user(app):
    html = _client(app, "sh").get("/", headers=HTML).text
    for land in ("<header", '<nav class="side"', "<main"):
        assert land in html
    assert "출하실 (예시)" in html                      # 사용자 이름(부서)
    assert f'href="{nav.path_of("HOME-020")}"' in html   # 알림 종
    assert "data-theme-toggle" in html
    assert "fonts.googleapis.com" in html


# ── 매크로 (Jinja env 로 직접 렌더) ──
def _macro(expr: str) -> str:
    from lcomfine.app import templating
    return templating.env.from_string('{% import "_macros.html" as ui %}' + expr).render()


def test_macros_table_empty_shows_misujip():
    html = _macro('{{ ui.table([("a", "A")], []) }}')
    assert "미수집" in html and "<table" not in html
    html = _macro('{{ ui.table([("a", "A")], [], empty_text="조회 결과 없음") }}')
    assert "조회 결과 없음" in html
    html = _macro('{{ ui.table([("a", "A"), {"key": "b", "label": "B", "num": true}], [{"a": "x", "b": 1234}]) }}')
    assert '<td class="num">1,234</td>' in html and "<td>x</td>" in html
    assert "미수집" in _macro("{{ ui.empty() }}")


def test_macros_undecided_and_chip_mapping():
    assert "미확정 (D-12)" in _macro('{{ ui.undecided("D-12") }}')
    want = {"가용": "ok", "합격": "ok", "확정": "ok", "반영": "ok",
            "검사대기": "warn", "보류": "warn", "지시": "warn", "확인대기": "warn",
            "불합격": "bad", "취소": "bad", "기타 상태": "muted"}
    for status, tone in want.items():
        html = _macro("{{ ui.chip(s) }}".replace("s", repr(status)))
        assert f'class="chip chip--{tone}">{status}<' in html, status


def _svg(html: str):
    import xml.etree.ElementTree as ET
    m = re.search(r"<svg.*?</svg>", html, re.S)
    assert m, html
    return ET.fromstring(m.group(0))


SVG_NS = "{http://www.w3.org/2000/svg}"


@pytest.mark.parametrize("values", [[0, 0, 0], [None, None], [3, None, 5], [-4, 2, None, 6], [-3, -1]])
def test_svg_macros_handle_zero_none_negative(values):
    from lcomfine.app import templating
    series = [{"label": f"p{i}", "value": v} for i, v in enumerate(values)]
    tpl = templating.env.from_string('{% import "_macros.html" as ui %}{{ ui.svg_bar(s) }}|||{{ ui.svg_line(s) }}')
    bar_html, line_html = tpl.render(s=series).split("|||")
    for html in (bar_html, line_html):
        root = _svg(html.replace("<svg ", '<svg xmlns="http://www.w3.org/2000/svg" ', 1))
        for el in root.iter():
            for k in ("x", "y", "width", "height", "x1", "y1", "x2", "y2"):
                if k in el.attrib:
                    v = float(el.attrib[k])
                    assert v == v and (k in ("x", "x1", "x2") or v >= 0), (k, v, values)
                    if k == "height":
                        assert v <= 160
        titles = [t.text for t in root.iter(f"{SVG_NS}title")]
        assert len(titles) == len(values)
        for v, t in zip(values, titles):
            assert t.endswith("미수집") if v is None else "미수집" not in t
    bars = [r for r in _svg(bar_html.replace("<svg ", '<svg xmlns="http://www.w3.org/2000/svg" ', 1)).iter(f"{SVG_NS}rect")]
    assert len(bars) == len(values)
    for v, r in zip(values, bars):
        if v is None or v == 0:
            assert float(r.attrib["height"]) == 0
        else:
            assert float(r.attrib["height"]) > 0


def test_health_returns_503_when_db_down(app, monkeypatch):
    from lcomfine.db import conn

    def down():
        raise conn.DbUnavailable("test: DB down")
    monkeypatch.setattr(conn, "ping", down)
    r = TestClient(app).get("/health")
    assert r.status_code == 503
    body = r.json()
    assert body["ok"] is False and body["db"] != "ok"
    assert "test: DB down" not in r.text    # 원문은 응답에 싣지 않는다


# ── 화면 도움말 패널 · 미확정 칩 · /ia 기능 계약 표 (UI 공용 틀 — docs/ui-guide.md) ──

def _help(html: str) -> str:
    m = re.search(r'<aside class="help" aria-label="화면 도움말">.*?</aside>', html, re.S)
    assert m, "화면 도움말 패널(aside.help) 없음"
    return m.group(0)


def test_help_panel_default_lists_function_names_without_contract_text(app):
    """help 블록을 채우지 않은 화면: 기능 **이름** 목록 + 내 권한. 기능 ID · 계약 문장 · 옛 계약 패널은 화면에 없다."""
    sid = "BAS-010"
    r = _client(app, "admin").get(nav.path_of(sid), headers=HTML)
    assert r.status_code == 200
    panel = _help(r.text)
    for f in contracts.functions_of(sid):
        assert f.name in panel, f.name
        assert f.id not in panel and f.contract not in panel
    assert "내 권한" in panel and ("등록·수정 가능" in panel or "조회만" in panel)
    assert 'class="contract"' not in r.text and "계약 패널" not in r.text
    assert "</main>" in r.text and r.text.index("</main>") < r.text.index('<aside class="help"')   # 본문(<main>) 밖 — 본문 대조에서 빠진다


def test_help_panel_permission_follows_rbac(app):
    sid = "WO-010"
    for login in ("sl", "ex"):
        panel = _help(_client(app, login).get(nav.path_of(sid), headers=HTML).text)
        w = rbac.can(rbac.load_user(login), sid, "W")
        assert ("등록·수정 가능" in panel) == w and ("조회만" in panel) == (not w), login


def test_help_block_and_undecided_chip_on_exemplars(app):
    """본보기 2 화면: help 블록(업무 문장 · 다음 단계 링크)이 기본 목록을 대신한다 · 미확정 글자는 본문에 칩으로 남는다."""
    c = _client(app, "admin")
    r = c.get(nav.path_of("WO-010"), headers=HTML)
    panel = _help(r.text)
    assert f'href="{nav.path_of("WO-020")}"' in panel and "이 화면에서 할 일" in panel
    assert 'class="panel panel--form"' in r.text and 'class="filters"' in r.text
    r = c.get(nav.path_of("RPT-020"), headers=HTML)
    body = r.text.split('<main class="main"', 1)[1].split("</main>", 1)[0]
    assert re.search(r'<span class="chip chip--undecided undecided" title="[^"]+">미확정 \(D-519\)</span>', body)
    assert '<details class="data-table">' in body and 'data-series-table="good_qty"' in body
    assert f'href="{nav.path_of("PRD-040")}"' in _help(r.text)


def test_ia_lists_function_contracts(app):
    r = _client(app, "admin").get("/ia", headers=HTML)
    rows = re.findall(r'<tr data-fn="(F-[A-Z]+-\d+)"', r.text)
    assert rows == [f.id for f in contracts.functions()]
    f0 = contracts.functions()[0]
    assert f0.contract.split("·")[0].strip()[:20] in r.text


def test_viz_geometry_is_safe_for_none_negative_and_empty():
    from lcomfine.app.util import viz
    g = viz.columns([{"label": "a", "value": None}, {"label": "b", "value": -5}, {"label": "c", "value": 10}])
    assert [c["none"] for c in g["cols"]] == [True, False, False] and g["cols"][1]["neg"]
    assert 0 <= g["y0"] <= 100 and all(0 <= c["top"] <= 100 for c in g["cols"])
    assert viz.columns([{"label": "a", "value": None}])["ticks"]                 # 전부 None — 눈금 폭 1
    assert viz.columns([{"label": "a", "value": 0}])["segments"] == ["50.0,100.0"]
    p = viz.parts([{"label": "x", "value": 3}, {"label": "y", "value": None}, {"label": "z", "value": -1}])
    assert p["total"] == 2 and [q["slot"] for q in p["parts"]] == [1, 0, 0]
    assert viz.parts([])["total"] is None and viz.bars_h([])["rows"] == []
    assert viz.meter(None)["none"] and viz.meter(150)["pct"] == 100 and viz.meter(150)["over"]
    assert viz.spark([{"value": None}, {"value": 1}]) == ""
    assert viz.short_label("2026-10-01") == "10-01" and viz.short_label("2026-10") == "2026-10"
