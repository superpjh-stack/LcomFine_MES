"""로그인 화면 상세 · 퀵 로그인 (D-416) — 아키텍트.

퀵 로그인은 `LCOMFINE_QUICK_LOGIN` 이 켜져 있고 운영(`prod`)이 아닐 때만 보이고 통한다. 비밀번호 값은 화면 어디에도 없다 (G-19).
공통 시드가 들어 있어야 한다(`make db-reset`). 시드 비밀번호는 `.env` 의 `LCOMFINE_SEED_PASSWORD`.
"""
import re

import pytest
from fastapi.testclient import TestClient

from lcomfine.app import auth, rbac
from lcomfine.app.main import app
from lcomfine.app.settings import get_settings, reset_cache
from lcomfine.db import conn

HTML = {"accept": "text/html"}


@pytest.fixture
def env(monkeypatch):
    """환경변수를 바꾸고 설정 캐시를 비운다. 끝나면 되돌린다."""
    def set_(**kv):
        for k, v in kv.items():
            monkeypatch.setenv("LCOMFINE_" + k, v)
        reset_cache()
    yield set_
    reset_cache()


@pytest.fixture
def quick_on(env):
    env(QUICK_LOGIN="1", ENV="dev")
    assert auth.quick_login_enabled()


def _client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def test_quick_login_panel_lists_every_role_and_never_the_password(quick_on):
    r = _client().get("/login", headers=HTML)
    assert r.status_code == 200 and 'class="login-quick"' in r.text
    roles = re.findall(r'data-role="(\w+)"', r.text)
    assert roles == [x.code for x in rbac.roles() if conn.q1("select 1 from sys_user where role_code = %s", (x.code,))]
    users = conn.q("select login_id, status from sys_user u join sys_role r using (role_code) where r.use_yn = 'Y'")
    assert r.text.count('name="quick_id"') == len(users)                       # 계정마다 단추 하나
    for u in users:                                                           # 정상이 아닌 계정의 단추는 막혀 있다
        m = re.search(rf'<button[^>]*value="{re.escape(u["login_id"])}"[^>]*>', r.text)
        assert m and (("disabled" in m.group(0)) == (u["status"] != "정상")), u
    assert get_settings().seed_password not in r.text                          # G-19
    assert "입력" in r.text and "조회" in r.text                               # 역할별 권한 요약


def test_quick_login_opens_a_session_and_logs_the_path(quick_on):
    c = _client()
    r = c.post("/login/quick", data={"quick_id": "admin", "device": "web"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert c.get("/").status_code == 200
    row = conn.q1("select detail from sys_access_log where log_type = '로그인' and login_id = 'admin' order by log_id desc limit 1")
    assert row and "로그인 성공" in row["detail"] and auth.QUICK_VIA in row["detail"]
    assert get_settings().seed_password not in row["detail"]


def test_quick_login_keeps_the_chosen_channel(quick_on):
    c = _client()
    r = c.post("/login/quick", data={"quick_id": "field", "device": "pop"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/pop/")
    assert 'class="ch-pop' in c.get(r.headers["location"], headers=HTML).text


def test_quick_login_refuses_unknown_and_inactive_accounts(quick_on):
    c = _client()
    r = c.post("/login/quick", data={"quick_id": "없는계정"}, follow_redirects=False)
    assert r.status_code == 401 and r.json()["code"] == "unauthorized"
    r = c.post("/login/quick", data={"quick_id": "없는계정"}, headers=HTML, follow_redirects=False)
    assert r.status_code == 401 and auth.QUICK_VIA in r.text and 'class="login-quick"' in r.text   # 화면을 다시 그린다
    conn.x("""insert into sys_user (login_id, user_name, password_hash, role_code, status, created_by)
              values ('t_quick_stop', '퀵 중지 (예시)', %s, 'QC', '중지', 'test')
              on conflict (login_id) do update set status = '중지', password_hash = excluded.password_hash""",
           (auth.hash_password(get_settings().seed_password),))
    try:
        r = c.post("/login/quick", data={"quick_id": "t_quick_stop"}, follow_redirects=False)
        assert r.status_code == 401 and "중지" in r.json()["message"]
    finally:
        conn.x("delete from sys_user where login_id = 't_quick_stop'")


def test_quick_login_is_off_in_prod_and_without_the_flag(env):
    for kv in ({"QUICK_LOGIN": "1", "ENV": "prod"}, {"QUICK_LOGIN": "", "ENV": "dev"}, {"QUICK_LOGIN": "0", "ENV": "dev"}):
        env(**kv)
        assert not auth.quick_login_enabled(), kv
        c = _client()
        assert 'class="login-quick"' not in c.get("/login", headers=HTML).text, kv
        assert "/login/quick" not in c.get("/login", headers=HTML).text, kv
        r = c.post("/login/quick", data={"quick_id": "admin"}, follow_redirects=False)
        assert r.status_code == 404 and r.json()["code"] == "not_found", kv
        assert c.get("/", follow_redirects=False).status_code == 401                 # 세션이 열리지 않았다


def test_normal_login_still_works_and_shows_the_reason(quick_on):
    c = _client()
    r = c.post("/login", data={"login_id": "admin", "password": "틀린-비밀번호"}, headers=HTML, follow_redirects=False)
    assert r.status_code == 401 and 'role="alert"' in r.text and auth.BAD_CREDENTIALS in r.text
    r = c.post("/login", data={"login_id": "admin", "password": get_settings().seed_password}, follow_redirects=False)
    assert r.status_code == 303
