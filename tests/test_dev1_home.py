"""공통 메인(`/`)과 개발1 담당 화면의 권한 전수 — 일하는 순서의 대메뉴 바로가기(좌측 메뉴와 같은 순서, D-417) · 역할에 맞는 메뉴만.

권한 표는 DB 데이터다. 기대값을 코드에 박지 않고 `rbac`(DB 의 지금 값)과 계약(`function-list.md`)에서 읽어 대조한다.
시드 계정은 로그인에만 쓰고 아무것도 바꾸지 않는다(쓰기는 전부 403 으로 끝나는 요청만 보낸다).
"""
import re

import pytest

from lcomfine.app import contracts, nav, rbac
from lcomfine.app.main import app
from lcomfine.db import conn
from test_dev1_helpers import client

DEV1_MODULES = ("bas", "prt", "job", "sys")
DEV1_SCREENS = [s for s in nav.SCREENS if s.owner == "개발1"]
DEV1_FUNCTIONS = [f for f in contracts.functions() if not f.is_batch and f.owner == "개발1"]


def _seed_logins() -> dict[str, str]:
    """역할 코드 → 그 역할의 정상 계정 하나 (공통 시드: admin · prod · qc · field)."""
    rbac.invalidate()
    codes = [r.code for r in rbac.roles()]
    rows = conn.q("""select role_code, min(login_id) as login_id from sys_user
                      where status = '정상' and login_id = lower(role_code) group by role_code""")
    found = {r["role_code"]: r["login_id"] for r in rows}
    assert set(codes) <= set(found), f"역할별 시드 계정이 없다: {sorted(set(codes) - set(found))}"
    return {code: found[code] for code in codes}


def _concrete(path: str) -> str:
    """경로 변수에 없는 키를 넣는다 — 권한 판정은 대상을 찾기 전에 끝난다."""
    return re.sub(r"\{[^}]*\}", "0", path)


def _all_routes(routes):
    """앱에 등록된 라우트를 전부 편다. 이 FastAPI 는 `include_router` 한 라우터를 `app.routes` 에 풀어 넣지 않고
    한 덩어리(`original_router`)로 둔다 — 그 안까지 들어가서 센다."""
    for route in routes:
        inner = getattr(route, "original_router", None)
        if inner is not None:
            yield from _all_routes(inner.routes)
        else:
            yield route


def test_dev1_owns_13_screens_and_46_functions():
    assert len(DEV1_SCREENS) == 13 and len(DEV1_FUNCTIONS) == 46
    assert {s.module for s in DEV1_SCREENS} == set(DEV1_MODULES)


def test_no_placeholder_left_in_dev1_screens():
    """담당 중메뉴 13개가 전부 실제 화면이다 — placeholder 0, 관리자로 전부 200."""
    left = [s.path for s in DEV1_SCREENS if s.path in app.state.placeholder_paths]
    assert left == []
    c = client("admin")
    for s in DEV1_SCREENS:
        r = c.get(s.path)
        assert r.status_code == 200, s.path
        assert 'class="tag"' not in r.text and "미구현" not in r.text, s.path
        assert f"<code>{s.screen_id}</code>" in r.text                       # 헤더에 화면 ID


def test_every_dev1_function_is_routed():
    """계약의 API 열(메서드·경로)이 글자 그대로 등록돼 있다 — 46기능. 계약에 없는 엔드포인트는 없다."""
    def norm(p: str) -> str:
        return re.sub(r"\{[^}]*\}", "{}", p)

    routes = {(m, norm(r.path)) for r in _all_routes(app.routes) for m in (getattr(r, "methods", None) or ())
              if m not in ("HEAD", "OPTIONS") and not (m == "GET" and r.path in app.state.placeholder_paths)}
    missing = [f.id for f in DEV1_FUNCTIONS if (f.method, norm(f.path)) not in routes]
    assert missing == []
    mine = {(m, p) for m, p in routes if p.startswith(tuple(f"/{mod}/" for mod in DEV1_MODULES))}
    assert mine == {(f.method, norm(f.path)) for f in DEV1_FUNCTIONS}        # 고아 라우트 0


def test_main_shows_only_menus_of_the_role():
    """메인 — 대메뉴 바로가기 카드가 좌측 메뉴와 같은 순서(`nav.SIDEBAR`, 묶음 없음)로 한 줄씩. 칸이 `없음` 인 대메뉴는 카드도 링크도 없다."""
    order = [c for c in nav.SIDEBAR if c != "home"]
    for role_code, login_id in _seed_logins().items():
        page = client(login_id).get("/")
        assert page.status_code == 200
        html = page.text
        visible = [m for m in nav.MENUS if rbac.cell(role_code, m.code).can_read]
        assert html.count('class="card"') == len(visible), login_id                        # 설계도 대메뉴 카드 수 (확장 카드는 card-ext)
        assert 'data-group="' not in html and 'class="menu-gname"' not in html.split('<main')[1]  # 묶음 이름을 그리지 않는다
        shown_codes = re.findall(r'<div class="card[^"]*" data-menu="([A-Z]+)"', html)
        expect = [c for c in order if rbac.cell(role_code, c).can_read]                   # 설계도 12 + 확장, 일하는 순서
        assert shown_codes == expect, (login_id, shown_codes)
        assert re.findall(r'<span class="step">(\d+)</span>', html) == [str(i) for i in range(1, len(expect) + 1)], login_id
        for m in nav.MENUS:
            shown = f'data-menu="{m.code}"' in html
            assert shown == (m in visible), (login_id, m.code)
            for s in m.screens:
                assert (f'href="{s.path}"' in html) == (m in visible), (login_id, s.path)
        assert f"대메뉴 {len(visible)} / {len(nav.MENUS)}" in html
    admin = client("admin").get("/").text
    assert re.findall(r'data-menu="([A-Z]+)"', admin) == order                               # 관리자에게는 전부, 좌측 메뉴 순서 그대로
    assert admin.index('data-menu="SHP"') < admin.index('data-menu="BAS"')                   # 기준정보는 출하보다 뒤
    assert len(nav.GROUPS) == 4 and [m.code for m in nav.MENUS][:2] == ["BAS", "PRT"]        # 설계도 묶음·순서는 건드리지 않았다 (G-01)


def test_main_needs_login():
    c = client()
    assert c.get("/").status_code == 401
    r = c.get("/", headers={"accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login")


@pytest.mark.parametrize("fn", [pytest.param(f, id=f.id) for f in DEV1_FUNCTIONS])
def test_permission_matrix_is_enforced_on_every_function(fn):
    """개발1 46기능 × 역할 — 권한 표(DB)에서 할 수 없는 역할은 403 이다.

    조회 역할의 쓰기 403 · 없음 역할은 조회도 쓰기도 403. 권한이 있는 역할은 403 이 아니다(없는 키라 404·422 가 난다).
    """
    path = _concrete(fn.path)
    for role_code, login_id in _seed_logins().items():
        c = client(login_id)
        r = c.get(path) if fn.method == "GET" else c.post(path, data={})
        if rbac.can_do(role_code, fn.id):
            assert r.status_code in (200, 404, 422), (fn.id, login_id, r.status_code)
        else:
            assert r.status_code == 403 and r.json()["code"] == "forbidden", (fn.id, login_id, r.status_code)
    anon = client()
    r = anon.get(path) if fn.method == "GET" else anon.post(path, data={})
    assert r.status_code == 401, fn.id
