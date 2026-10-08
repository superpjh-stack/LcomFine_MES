"""좌측 메뉴 표시 순서 (D-417) — 묶음 없이 한 줄씩, 일하는 순서: 메인 → 실적 현황 → 영업 → 작업지시 → 입고 → 공정 → 품질 → 출하 → 추적 → 기준정보 → 시스템.

설계도의 묶음·순서(`nav.GROUPS` · `nav.MENUS`)는 그대로이고(G-01), 좌측 메뉴만 `nav.SIDEBAR` 순서로 그린다.
메인 화면의 카드도 같은 순서다(`tests/test_dev1_home.py`). 공통 시드가 들어 있어야 한다(`make db-reset`).
"""
import re

import pytest
from fastapi.testclient import TestClient

from lcomfine.app import nav, rbac
from lcomfine.app.main import app
from lcomfine.app.settings import get_settings

pytestmark = pytest.mark.fn("F-SYS-05")


def _client(login_id: str | None = None) -> TestClient:
    c = TestClient(app, raise_server_exceptions=False)
    if login_id:
        r = c.post("/login", data={"login_id": login_id, "password": get_settings().seed_password}, follow_redirects=False)
        assert r.status_code == 303, f"{login_id} 로그인 실패 {r.status_code}"
    return c


def _sidebar(html: str) -> str:
    m = re.search(r'<nav class="side"[^>]*>(.*?)</nav>', html, re.S)
    assert m, "좌측 메뉴가 없다"
    return m.group(1)


def _heads(side: str) -> list[str]:
    return re.findall(r'class="menu-head"[^>]*>([^<]+)<', side)


def test_sidebar_spec_is_flat_working_order_and_design_order_is_untouched():
    assert nav.SIDEBAR[0] == "home"
    codes = [k for k in nav.SIDEBAR if k != "home"]
    assert codes == ["STA", "SAL", "JOB", "MAT", "CLR", "POP", "RLL", "QUA", "SHP", "TRC", "BAS", "PRT", "SYS"]
    assert sorted(codes) == sorted(m.code for m in nav.MENUS + nav.EXT_MENUS)
    items = nav.sidebar_items()
    assert items[0]["kind"] == "screen" and items[0]["screen"].screen_id == "home"
    assert [it["menu"].code for it in items[1:]] == codes
    # 설계도 순서는 건드리지 않았다 — G-01 과 메인 화면의 근거
    assert [m.code for m in nav.MENUS] == ["BAS", "PRT", "JOB", "POP", "MAT", "CLR", "RLL", "QUA", "SHP", "TRC", "STA", "SYS"]
    assert [n["group"] for n in nav.menu_tree()] == list(nav.GROUPS) and len(nav.GROUPS) == 4


def test_admin_sidebar_has_no_group_labels_and_lists_menus_in_working_order():
    html = _client("admin").get("/bas/items").text
    side = _sidebar(html)
    assert 'class="menu-gname"' not in side and "menu-section" not in side          # 묶음 이름 없음
    heads = _heads(side)
    assert heads[0] == "메인"
    assert heads[1:] == [nav.menu(c).name for c in nav.SIDEBAR if c != "home"]
    assert side.index("출하 승인") < side.index("품목 관리")                         # 기준정보는 출하보다 뒤
    assert side.index("수주 관리") < side.index("작업지시")                           # 수주는 작업지시보다 앞
    # 지금 화면의 대메뉴만 `on`(펼침) — 나머지는 접혀 있고 누르면 펼쳐진다(app.js)
    assert side.count('class="menu-group on"') == 1 and "기준정보 관리" in re.search(r'class="menu-group on">\s*<div class="menu-head">([^<]+)<', side).group(1)
    assert re.search(r'<div class="menu-group">\s*<a class="menu-head" href="/">메인</a>', side)
    home = _sidebar(_client("admin").get("/").text)
    assert re.search(r'<div class="menu-group on">\s*<a class="menu-head" href="/">메인</a>', home)
    for s in nav.SCREENS + nav.EXT_SCREENS:                                           # 중메뉴 32 + 확장 3 링크가 전부 있다
        assert f'href="{s.path}"' in side, s.screen_id


def test_sidebar_hides_menus_without_permission_but_keeps_main():
    for role_code, login_id in (("FIELD", "field"), ("QC", "qc"), ("PROD", "prod")):
        side = _sidebar(_client(login_id).get("/").text)
        for m in nav.MENUS + nav.EXT_MENUS:
            shown = f">{m.name}<span" in side
            assert shown == rbac.cell(role_code, m.code).can_read, (login_id, m.code)
        assert 'href="/">메인</a>' in side
    field = _sidebar(_client("field").get("/").text)
    assert "기준정보 관리" not in field and "시스템 관리" not in field and "LOT 추적" not in field
    assert "인쇄 기준 관리" in field and "영업관리" in field                           # 영업관리는 작업지시 관리 칸(현장 = 조회)을 따른다


def test_sidebar_empty_without_login():
    """오류 안내(`/error`)는 로그인 없이 열린다 — 좌측 메뉴는 비어 있고 메인 링크도 없다."""
    html = _client().get("/error").text
    assert "로그인이 필요합니다" in html and 'class="menu-head"' not in html and 'href="/">메인</a>' not in html
