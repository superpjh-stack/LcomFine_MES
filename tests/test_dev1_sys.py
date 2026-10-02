"""시스템 관리 — 사용자 4(등록·수정·삭제·조회) + 권한 2(조회·수정) + 로그 1(조회) = F-SYS-01~07.

- 권한: 관리자만(나머지 세 역할은 `없음` — 조회도 403).
- **시드 계정 4개와 권한 표 48칸은 바꾸지 않는다** — 다른 사람의 테스트가 같은 DB 에서 그것으로 로그인하고 판정한다.
  사용자 테스트는 `t1…` 계정을 만들어 쓰고, 권한 수정 테스트는 **사용 안 함(`use_yn='N'`) 임시 역할**의 칸을 바꾼다
  (권한 표의 칸 수 48 에 들어가지 않는다). 끝나면 계정·역할·칸·로그를 지운다.
"""
import uuid

import pytest

from lcomfine.app import rbac
from lcomfine.db import conn
from test_dev1_helpers import change_logs, client

USERS, PERMISSIONS, LOGS = "/sys/users", "/sys/permissions", "/sys/logs"
PW_A, PW_B = f"a-{uuid.uuid4().hex}", f"b-{uuid.uuid4().hex}"        # 테스트마다 난수 — 값을 적어 두지 않는다 (G-19)


@pytest.fixture
def uid():
    """이 테스트만의 로그인 ID 접두 `t1xxxxxxxx`. 끝나면 그 접두의 계정·로그를 지운다."""
    prefix = f"t1{uuid.uuid4().hex[:8]}"
    yield prefix
    like = f"{prefix}%"
    conn.x("delete from sys_access_log where login_id like %s or target like %s", (like, f"sys_user:{like}"))
    conn.x("delete from sys_user where login_id like %s", (like,))


@pytest.fixture
def temp_role(uid):
    """사용 안 함(`use_yn='N'`) 임시 역할 — `rbac.roles()` 와 권한 표 48칸에 들어가지 않는다."""
    code = uid.upper()
    conn.x("insert into sys_role (role_code, role_name, sort_no, use_yn) values (%s, %s, 99, 'N')", (code, f"{code} (예시)"))
    rbac.invalidate()
    yield code
    conn.x("delete from sys_access_log where target like %s", (f"sys_permission:{code}/%",))
    conn.x("delete from sys_user where role_code = %s", (code,))
    conn.x("delete from sys_role where role_code = %s", (code,))     # 칸(sys_permission)은 함께 지워진다
    rbac.invalidate()


def _user(login_id: str) -> dict | None:
    return conn.q1("select * from sys_user where login_id = %s", (login_id,))


def _add(c, login_id: str, role_code: str = "QC", password: str = PW_A, name: str | None = None):
    return c.post(USERS, data={"login_id": login_id, "user_name": name or f"{login_id} (예시)", "role_code": role_code,
                               "password": password})


def _login_status(login_id: str, password: str) -> int:
    return client().post("/login", data={"login_id": login_id, "password": password}, follow_redirects=False).status_code


def _cell(role_code: str, menu_code: str) -> dict | None:
    return conn.q1("select level, write_scope, updated_by from sys_permission where role_code = %s and menu_code = %s",
                   (role_code, menu_code))


# ── 사용자 ──────────────────────────────────────────────────────────────
@pytest.mark.fn("F-SYS-01")
def test_create_user_stores_only_hash(uid):
    c = client("admin")
    r = _add(c, uid)
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "message": f"사용자 {uid} 을(를) 등록했습니다", "login_id": uid, "role_code": "QC",
                        "status": "정상"}
    row = _user(uid)
    assert row["role_code"] == "QC" and row["status"] == "정상" and row["created_by"] == "admin"
    assert PW_A not in row["password_hash"] and row["password_hash"].startswith("pbkdf2_sha256$")   # 해시만 저장
    assert PW_A not in r.text
    assert _login_status(uid, PW_A) == 303                                    # 그 비밀번호로 로그인된다
    assert change_logs("F-SYS-01", f"sys_user:{uid}") == 1
    assert conn.q1("select count(*) as n from sys_access_log where detail like %s", (f"%{PW_A}%",))["n"] == 0

    assert _add(c, uid, name="중복 (예시)").status_code == 422                # ID 중복
    for data in ({"login_id": f"{uid}b", "user_name": "x (예시)", "role_code": "QC"},                     # 비밀번호 없음
                 {"login_id": f"{uid}b", "user_name": "x (예시)", "password": PW_A},                      # 역할 없음
                 {"login_id": f"{uid}b", "role_code": "QC", "password": PW_A},                            # 이름 없음
                 {"user_name": "x (예시)", "role_code": "QC", "password": PW_A},                          # ID 없음
                 {"login_id": f"{uid}b", "user_name": "x (예시)", "role_code": "없는역할", "password": PW_A},
                 {"login_id": f"{uid}/b", "user_name": "x (예시)", "role_code": "QC", "password": PW_A},  # 경로에 못 쓰는 글자
                 {"login_id": f"{uid} b", "user_name": "x (예시)", "role_code": "QC", "password": PW_A}):
        assert c.post(USERS, data=data).status_code == 422, data
    assert conn.q1("select count(*) as n from sys_user where login_id like %s", (f"{uid}%",))["n"] == 1


@pytest.mark.fn("F-SYS-02")
def test_update_user_and_reset_password(uid):
    c = client("admin")
    assert _add(c, uid).status_code == 200
    path = f"{USERS}/{uid}"

    r = c.post(path, data={"user_name": f"{uid} 바뀜 (예시)", "role_code": "PROD"})
    assert r.status_code == 200, r.text
    row = _user(uid)
    assert (row["user_name"], row["role_code"], row["status"], row["updated_by"]) == (f"{uid} 바뀜 (예시)", "PROD", "정상", "admin")
    assert _login_status(uid, PW_A) == 303                                    # 비밀번호는 그대로
    assert change_logs("F-SYS-02", f"sys_user:{uid}") == 1

    r = c.post(path, data={"password": PW_B})                                 # 비밀번호 초기화
    assert r.status_code == 200 and PW_B not in r.text
    assert _login_status(uid, PW_A) == 401 and _login_status(uid, PW_B) == 303
    assert PW_B not in _user(uid)["password_hash"]

    assert c.post(path, data={"status": "잠금"}).status_code == 200           # 상태 변경 — 정상이 아니면 로그인 못 한다
    assert _user(uid)["status"] == "잠금" and _login_status(uid, PW_B) == 401
    assert c.post(path, data={"status": "정상"}).status_code == 200
    assert _user(uid)["fail_count"] == 0 and _login_status(uid, PW_B) == 303

    assert c.post(path, data={"status": "휴면"}).status_code == 422
    assert c.post(path, data={"role_code": "없는역할"}).status_code == 422
    assert c.post(path, data={"user_name": ""}).status_code == 422
    assert c.post(path, data={}).status_code == 422                           # 바꿀 값이 없다
    assert c.post(f"{USERS}/{uid}-없음", data={"user_name": "x"}).status_code == 404

    me = client(uid, PW_B)                                                    # 관리자가 아닌 그 사용자는 시스템 관리가 `없음`
    assert me.post(path, data={"role_code": "ADMIN"}).status_code == 403      # 스스로 역할을 올릴 수 없다
    assert _user(uid)["role_code"] == "PROD"


@pytest.mark.fn("F-SYS-02", "F-SYS-03")
def test_admin_cannot_stop_own_account(uid):
    """자기 자신은 삭제(중지)·잠금할 수 없다 — 임시 관리자 계정으로 확인한다(시드 admin 은 건드리지 않는다)."""
    assert _add(client("admin"), uid, role_code="ADMIN").status_code == 200
    me = client(uid, PW_A)
    assert me.post(f"{USERS}/{uid}/delete").status_code == 422
    assert me.post(f"{USERS}/{uid}", data={"status": "중지"}).status_code == 422
    assert me.post(f"{USERS}/{uid}", data={"status": "잠금"}).status_code == 422
    assert _user(uid)["status"] == "정상"
    assert me.post(f"{USERS}/{uid}", data={"user_name": f"{uid} 본인 수정 (예시)"}).status_code == 200   # 이름은 바꾼다


@pytest.mark.fn("F-SYS-03")
def test_delete_user_is_status_stop(uid):
    c = client("admin")
    assert _add(c, uid).status_code == 200
    r = c.post(f"{USERS}/{uid}/delete")
    assert r.status_code == 200 and r.json()["status"] == "중지"
    row = _user(uid)
    assert row is not None and row["status"] == "중지" and row["updated_by"] == "admin"    # 행은 지우지 않는다 (D-21)
    assert _login_status(uid, PW_A) == 401                                    # 중지 계정은 로그인하지 못한다
    assert change_logs("F-SYS-03", f"sys_user:{uid}") == 1
    assert c.post(f"{USERS}/{uid}/delete").status_code == 422                 # 이미 중지
    assert c.post(f"{USERS}/{uid}-없음/delete").status_code == 404


@pytest.mark.fn("F-SYS-02", "F-SYS-04")
def test_user_screen_says_what_the_session_really_does(uid):
    """사용자 화면의 안내 문구와 실제 동작이 같다 (D-108 · D-26). 임시 계정으로 확인한다 — 시드 계정은 로그인에만 쓴다.
    ① 역할·이름 변경은 그 사용자의 다음 요청부터(다시 로그인하지 않는다) ② 잠금·중지·비밀번호 초기화는 그 계정의 세션을 곧바로 끊는다."""
    admin = client("admin")
    page = admin.get(USERS).text
    assert "다음 요청부터 반영된다" in page and "곧바로 전부 끊긴다" in page and "살아나지 않는다" in page
    assert "다음에 로그인할 때부터" not in page and "다음 로그인부터" not in page   # 옛 문구(D-105)는 사실이 아니다

    assert _add(admin, uid, role_code="QC").status_code == 200
    path = f"{USERS}/{uid}"
    me = client(uid, PW_A)                                                    # 이 세션 하나로 끝까지 본다 — 다시 로그인하지 않는다
    epoch = _user(uid)["session_epoch"]

    # ① 역할·이름 — 다음 요청부터 반영, 세션은 그대로
    assert me.get(USERS).status_code == 403                                   # 품질은 시스템 관리가 `없음`
    assert admin.post(path, data={"role_code": "ADMIN", "user_name": f"{uid} 새 이름 (예시)"}).status_code == 200
    r = me.get(USERS)
    assert r.status_code == 200 and f"{uid} 새 이름 (예시)" in r.text         # 같은 세션의 바로 다음 요청 — 새 역할 · 새 이름
    assert admin.post(path, data={"role_code": "QC"}).status_code == 200
    assert me.get(USERS).status_code == 403                                   # 내린 것도 다음 요청부터
    assert me.get("/").status_code == 200 and _user(uid)["session_epoch"] == epoch   # 세션은 끊기지 않았다

    # ② 잠금 — 그 계정의 세션이 전부(여러 단말) 곧바로 끊긴다. `정상` 으로 되돌려도 끊긴 세션은 살아나지 않는다
    other = client(uid, PW_A)
    assert other.get("/").status_code == 200
    assert admin.post(path, data={"status": "잠금"}).status_code == 200
    assert me.get("/").status_code == 401 and other.get("/").status_code == 401
    assert admin.post(path, data={"status": "정상"}).status_code == 200
    assert me.get("/").status_code == 401 and other.get("/").status_code == 401
    me = client(uid, PW_A)                                                    # 다시 로그인하면 된다
    assert me.get("/").status_code == 200

    # ② 비밀번호 초기화 — 옛 비밀번호로 들어와 있던 세션이 끊긴다
    assert admin.post(path, data={"password": PW_B}).status_code == 200
    assert me.get("/").status_code == 401
    me = client(uid, PW_B)
    assert me.get("/").status_code == 200

    # ② 중지(삭제) — 세션이 끊기고 다시 로그인도 못 한다
    assert admin.post(f"{path}/delete").status_code == 200
    assert me.get("/").status_code == 401 and _login_status(uid, PW_B) == 401
    assert admin.get(USERS).status_code == 200                                # 바꾼 사람(관리자)의 세션은 그대로다


@pytest.mark.fn("F-SYS-02")
def test_resetting_own_password_ends_own_session(uid):
    """자기 계정의 비밀번호를 초기화하면 지금 세션도 끊긴다 — 화면에 그렇게 적었다 (D-108). 임시 관리자 계정으로 확인한다."""
    assert _add(client("admin"), uid, role_code="ADMIN").status_code == 200
    me = client(uid, PW_A)
    assert "지금 이 세션도 끊긴다" in me.get(USERS).text
    r = me.post(f"{USERS}/{uid}", data={"password": PW_B})
    assert r.status_code == 200, r.text                                       # 그 요청 자체는 성공하고 변경 로그도 남는다
    assert change_logs("F-SYS-02", f"sys_user:{uid}") == 1
    assert me.get(USERS).status_code == 401                                   # 다음 요청부터 미로그인
    r = me.get(USERS, headers={"accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login")   # 브라우저는 로그인 화면으로 간다
    assert client(uid, PW_B).get(USERS).status_code == 200                    # 새 비밀번호로 다시 로그인한다


@pytest.mark.fn("F-SYS-04")
def test_users_list_never_shows_hash(uid):
    c = client("admin")
    assert _add(c, uid).status_code == 200
    assert _add(c, f"{uid}b", role_code="FIELD").status_code == 200
    assert c.post(f"{USERS}/{uid}b/delete").status_code == 200
    stored = _user(uid)["password_hash"]

    page = c.get(USERS, params={"login_id": uid}).text
    assert uid in page and f"{uid}b" in page and "미구현" not in page
    assert stored not in page and "pbkdf2_sha256" not in page and "password_hash" not in page   # 해시를 내보내지 않는다
    page = c.get(USERS, params={"login_id": uid, "status": "중지"}).text
    assert f"{uid}b" in page and f"<code>{uid}</code>" not in page
    page = c.get(USERS, params={"login_id": uid, "role_code": "QC"}).text
    assert f"<code>{uid}</code>" in page and f"<code>{uid}b</code>" not in page
    assert 'class="empty">미수집' in c.get(USERS, params={"login_id": f"{uid}-없음"}).text
    page = c.get(USERS, params={"edit": uid}).text                            # 수정 폼 — 비밀번호 칸은 비어 있다
    assert f'action="{USERS}/{uid}"' in page and stored not in page
    assert c.get(USERS, params={"edit": f"{uid}-없음"}).status_code == 404


# ── 권한 ────────────────────────────────────────────────────────────────
@pytest.mark.fn("F-SYS-05")
def test_permission_matrix_shows_db_cells():
    rbac.invalidate()
    page = client("admin").get(PERMISSIONS).text
    roles, counts = rbac.roles(), rbac.counts()
    assert page.count('class="perm-cell') == counts["전체"] == len(roles) * 12            # 역할 × 대메뉴 12
    assert f"입력 {counts['입력']} · 조회 {counts['조회']} · 없음 {counts['없음']}" in page
    for r in roles:                                                           # 칸의 값은 DB 그대로
        for menu_code in ("BAS", "MAT", "SHP", "SYS"):
            cell = rbac.cell(r.code, menu_code)
            assert f'data-role="{r.code}" data-menu="{menu_code}" data-level="{cell.level}"' in page
    assert "입력 (입고검사)" in page and "입력 (승인)" in page                # 괄호 조건 2개가 표기 그대로 보인다


@pytest.mark.fn("F-SYS-06")
def test_permission_change_applies_immediately(uid, temp_role):
    """한 칸을 바꾸면 다음 요청부터 반영된다. 임시 역할(사용 안 함)의 칸으로 확인한다 — 권한 표 48칸은 그대로다."""
    admin = client("admin")
    before = rbac.counts()
    assert _add(admin, uid, role_code=temp_role).status_code == 200
    me = client(uid, PW_A)
    code = f"{uid.upper()}-C"
    customer = {"customer_code": code, "customer_name": f"{code} (예시)"}

    assert me.get("/bas/customers").status_code == 403                        # 칸이 없으면 `없음`
    assert 'href="/bas/customers"' not in me.get("/").text                    # 메뉴에서도 숨는다

    r = admin.post(PERMISSIONS, data={"role_code": temp_role, "menu_code": "BAS", "level": "조회"})
    assert r.status_code == 200, r.text
    assert _cell(temp_role, "BAS") == {"level": "조회", "write_scope": "", "updated_by": "admin"}
    assert me.get("/bas/customers").status_code == 200                        # 즉시 조회 가능
    assert 'href="/bas/customers"' in me.get("/").text
    assert me.post("/bas/customers", data=customer).status_code == 403        # 조회 역할의 쓰기는 403

    r = admin.post(PERMISSIONS, data={"role_code": temp_role, "menu_code": "BAS", "level": "입력"})
    assert r.status_code == 200 and r.json()["write_scope"] == "일반"         # 괄호 없는 입력 = 일반
    try:
        r = me.post("/bas/customers", data=customer)
        assert r.status_code == 200, r.text                                   # 즉시 입력 가능
    finally:
        conn.x("delete from customer where customer_code = %s", (code,))
        conn.x("delete from sys_access_log where target = %s", (f"customer:{code}",))

    # 범위(괄호 조건) — 자재·입고를 `입력 (입고검사)` 로 주면 입고검사만 쓴다
    r = admin.post(PERMISSIONS, data={"role_code": temp_role, "menu_code": "MAT", "level": "입력", "write_scope": "입고검사"})
    assert r.status_code == 200 and _cell(temp_role, "MAT")["write_scope"] == "입고검사"
    assert rbac.can_do(temp_role, "F-MAT-03") and not rbac.can_do(temp_role, "F-MAT-01")
    r = admin.post(PERMISSIONS, data={"role_code": temp_role, "menu_code": "MAT", "level": "입력",
                                      "write_scope": ["일반", "입고검사"]})
    assert r.status_code == 200 and rbac.can_do(temp_role, "F-MAT-01") and rbac.can_do(temp_role, "F-MAT-03")

    r = admin.post(PERMISSIONS, data={"role_code": temp_role, "menu_code": "BAS", "level": "없음"})
    assert r.status_code == 200
    assert me.get("/bas/customers").status_code == 403                        # 즉시 막힌다
    assert change_logs("F-SYS-06", f"sys_permission:{temp_role}/BAS") == 3    # 바꿀 때마다 변경 로그

    for data in ({"role_code": temp_role, "menu_code": "BAS", "level": "관리"},
                 {"role_code": temp_role, "menu_code": "XXX", "level": "조회"},
                 {"role_code": "없는역할", "menu_code": "BAS", "level": "조회"},
                 {"role_code": temp_role, "menu_code": "BAS", "level": "입력", "write_scope": "없는범위"},
                 {"role_code": temp_role, "menu_code": "BAS"}, {"menu_code": "BAS", "level": "조회"}):
        assert admin.post(PERMISSIONS, data=data).status_code == 422, data
    assert _cell(temp_role, "BAS")["level"] == "없음"
    rbac.invalidate()
    assert rbac.counts() == before                                            # 권한 표 48칸은 건드리지 않았다


@pytest.mark.fn("F-SYS-06")
def test_admin_system_cell_cannot_be_lowered():
    """관리자의 시스템 관리 칸은 `입력` 아래로 못 내린다(잠김 방지). 422 이고 칸은 그대로다."""
    admin = client("admin")
    was = _cell("ADMIN", "SYS")
    assert was["level"] == "입력" and "일반" in was["write_scope"]
    for data in ({"level": "조회"}, {"level": "없음"}, {"level": "입력", "write_scope": "승인"}):
        r = admin.post(PERMISSIONS, data={"role_code": "ADMIN", "menu_code": "SYS", **data})
        assert r.status_code == 422 and "잠김 방지" in r.json()["message"], data
    assert _cell("ADMIN", "SYS") == was
    assert admin.get(PERMISSIONS).status_code == 200                          # 관리자는 여전히 들어온다


# ── 로그 ────────────────────────────────────────────────────────────────
@pytest.mark.fn("F-SYS-07")
def test_logs_show_login_view_change(uid):
    """로그인 성공·실패, 화면 조회, 데이터 변경이 로그 화면에 보인다 (G-18). 임시 관리자 계정의 흔적만 본다."""
    admin = client("admin")
    assert _add(admin, uid, role_code="ADMIN").status_code == 200
    assert _login_status(uid, "틀린-비밀번호") == 401                         # 로그인 실패
    me = client(uid, PW_A)                                                    # 로그인 성공
    assert me.get("/bas/customers").status_code == 200                        # 화면 조회
    code = f"{uid.upper()}-C"
    try:
        assert me.post("/bas/customers", data={"customer_code": code, "customer_name": f"{code} (예시)"}).status_code == 200
    finally:                                                                  # 데이터 변경 (만든 고객은 지운다 — 로그는 남는다)
        conn.x("delete from customer where customer_code = %s", (code,))

    page = admin.get(LOGS, params={"login_id": uid}).text
    assert "미구현" not in page
    for shown in ("로그인 성공", "로그인 실패: 비밀번호 불일치", "BAS-02", "F-BAS-05", f"customer:{code}"):
        assert shown in page, shown
    assert page.count('data-log-type="로그인"') == 2 and page.count('data-log-type="조회"') == 1
    assert page.count('data-log-type="변경"') == 1
    assert "로그인 2 · 조회 1 · 변경 1 · 오류 0" in page

    page = admin.get(LOGS, params={"login_id": uid, "log_type": "변경"}).text  # 구분으로
    assert page.count('data-log-type="변경"') == 1 and 'data-log-type="로그인"' not in page
    page = admin.get(LOGS, params={"login_id": uid, "result": "실패"}).text
    assert page.count('data-log-type="로그인"') == 1 and "비밀번호 불일치" in page
    today = conn.q1("select current_date as d")["d"].isoformat()
    page = admin.get(LOGS, params={"login_id": uid, "date_from": today, "date_to": today}).text    # 기간으로 (양 끝 포함)
    assert page.count("data-log-type=") == 4
    page = admin.get(LOGS, params={"login_id": uid, "date_from": "2099-01-01"}).text
    assert 'class="empty">미수집' in page                                     # 0건이면 미수집
    assert admin.get(LOGS, params={"date_from": "어제"}).status_code == 422
    assert PW_A not in admin.get(LOGS, params={"login_id": uid}).text         # 비밀번호는 로그에 없다


# ── 권한 없음 ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("login_id", ["prod", "qc", "field"])
def test_system_menu_is_admin_only(login_id, uid):
    """시스템 관리 — 생산·품질·현장은 `없음`. 화면 3개와 쓰기 4기능 전부 403 이고 아무것도 바뀌지 않는다."""
    c = client(login_id)
    for path in (USERS, PERMISSIONS, LOGS):
        r = c.get(path)
        assert r.status_code == 403 and r.json()["code"] == "forbidden", path
    was = _cell("QC", "BAS")
    writes = [(USERS, {"login_id": uid, "user_name": "x (예시)", "role_code": "ADMIN", "password": PW_A}),
              (f"{USERS}/{login_id}", {"role_code": "ADMIN"}),
              (f"{USERS}/admin/delete", {}),
              (PERMISSIONS, {"role_code": "QC", "menu_code": "BAS", "level": "입력"}),
              (USERS, {}), (PERMISSIONS, {})]
    for path, data in writes:
        assert c.post(path, data=data).status_code == 403, path
    assert _user(uid) is None and _user("admin")["status"] == "정상" and _cell("QC", "BAS") == was
    anon = client()
    for path in (USERS, PERMISSIONS, LOGS):
        assert anon.get(path).status_code == 401
    for path, data in writes:
        assert anon.post(path, data=data).status_code == 401
