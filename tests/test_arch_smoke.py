# tests/test_arch_smoke.py — 앱 전체 연기 시험 (Task 9 · G-03 의 바탕) — 실제 DB `lcomfine_db` · 시드 뒤
# /health · 부서 8 로그인 · 화면 67 전부 권한 있는 부서로 200(placeholder 포함) · 칸 없는 부서 403 · 미로그인 401/303.
# 기대값은 `contracts.permission_cells()`(= contracts/permission-matrix.md = ia.json) 에서 읽는다 — 역할·칸을 여기 적지 않는다.
import pytest
from fastapi.testclient import TestClient

from lcomfine.app import contracts, nav
from lcomfine.app.main import app
from lcomfine.app.settings import get_settings
from lcomfine.db.seed import USERS

LOGIN_OF = {code: login_id for login_id, _name, code in USERS}   # 부서 코드 → 시드 계정


def _cells() -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for sid, role, level in contracts.permission_cells():
        out.setdefault(sid, {})[role] = level
    return out


@pytest.fixture(scope="module")
def clients() -> dict[str, TestClient]:
    pw = get_settings().seed_password
    assert pw, "LCOMFINE_SEED_PASSWORD 미설정 — `make setup`"
    out = {}
    for code, login_id in LOGIN_OF.items():
        c = TestClient(app, raise_server_exceptions=False)
        r = c.post("/login", data={"login_id": login_id, "password": pw}, follow_redirects=False)
        assert r.status_code == 303, f"{login_id} 로그인 {r.status_code}"
        out[code] = c
    return out


def test_health_200_and_keys():
    r = TestClient(app).get("/health")
    assert r.status_code == 200
    body = r.json()
    assert {"ok", "menus", "screens", "placeholders", "db", "router_include_errors"} <= set(body)
    assert body["ok"] is True and body["screens"] == len(nav.SCREENS) == 66 and body["menus"] == len(nav.MENUS)
    assert body["placeholders"] == len(app.state.placeholder_paths)


def test_eight_department_logins(clients):
    assert set(clients) == set(contracts.ROLE_CODES.values()) and len(clients) == 8
    for code, c in clients.items():
        r = c.get("/", follow_redirects=False)
        assert r.status_code == 200, f"{code} 로그인 뒤 / → {r.status_code}"


def test_every_screen_200_for_a_permitted_department(clients):
    cells = _cells()
    bad = []
    for s in nav.SCREENS:
        allowed = cells.get(s.screen_id, {})
        assert allowed, f"{s.screen_id} 에 칸 있는 부서가 없다"
        for role in allowed:
            r = clients[role].get(s.path, headers={"accept": "text/html"})
            if r.status_code != 200:
                bad.append(f"{role} {s.screen_id} {s.path} → {r.status_code}")
    assert not bad, bad[:5]


def test_screen_without_cell_403(clients):
    cells = _cells()
    bad, checked = [], 0
    for s in nav.SCREENS:
        allowed = cells.get(s.screen_id, {})
        for role in clients:
            if role in allowed:
                continue
            checked += 1
            r = clients[role].get(s.path)
            if r.status_code != 403:
                bad.append(f"{role} {s.screen_id} {s.path} → {r.status_code}")
    assert checked == 66 * 8 - 257
    assert not bad, bad[:5]


def test_placeholder_routes_cover_unregistered_screens():
    ph = set(app.state.placeholder_paths)
    assert ph <= {s.path for s in nav.SCREENS}
    for path in ph:   # placeholder 도 require_screen 을 탄다 — 미로그인 401
        assert TestClient(app).get(path, follow_redirects=False).status_code == 401


def test_placeholder_page_shows_owner_and_function_rows(clients):
    ph = set(app.state.placeholder_paths)
    for s in nav.SCREENS:
        if s.path not in ph:
            continue
        html = clients["ADM"].get(s.path, headers={"accept": "text/html"}).text
        assert 'class="tag"' in html and "미구현" in html, s.screen_id
        assert f"담당 {s.owner}" in html, s.screen_id
        for f in contracts.functions_of(s.screen_id):
            assert f.id in html, f"{s.screen_id} placeholder 에 {f.id} 줄이 없다"


def test_anonymous_screen_get_401_or_login_redirect():
    anon = TestClient(app, raise_server_exceptions=False)
    s = nav.SCREENS[1]
    assert anon.get(s.path, follow_redirects=False).status_code == 401
    r = anon.get(s.path, headers={"accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login")


def test_common_screens_200(clients):
    assert TestClient(app).get("/login").status_code == 200
    assert TestClient(app).get("/error").status_code == 200
    assert clients["ADM"].get("/ia").status_code == 200
