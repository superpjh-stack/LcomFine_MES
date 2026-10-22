# tests/test_dev1_sys.py — SYS 사용자 · 역할·권한 · 공통코드 · 로그 — 실제 DB · 시드 뒤 · 만든 행은 지운다
# 시드 계정은 바꾸지 않는다(다른 개발자 테스트가 쓴다). 사용자 변경은 테스트 계정(난수 비밀번호)으로만 한다.
import pytest
from fastapi.testclient import TestClient

from lcomfine.app import rbac
from lcomfine.app.main import app
from lcomfine.db import conn
from test_dev1_common import cleanup, client, login, make_user, uniq


@pytest.fixture
def p():
    prefix = uniq("sys")
    yield prefix
    cleanup(prefix)


# ── SYS-010 사용자 ──
@pytest.mark.fn("F-SYS-011")
def test_user_create(p):
    c = client("admin")
    r = c.post("/sys/users", data={"login_id": p + "N", "user_name": "신규 (예시)", "role_code": "SH", "password": p})
    assert r.status_code == 200, r.text
    row = conn.q1("select role_code, status, password_hash from sys_user where login_id = %s", (p + "N",))
    assert row["role_code"] == "SH" and row["status"] == "정상" and p not in row["password_hash"]
    assert login(p + "N", p).get("/home/notifications").status_code == 200
    assert c.post("/sys/users", data={"login_id": p + "N", "user_name": "x", "role_code": "SH", "password": "x"}).status_code == 422
    assert c.post("/sys/users", data={"login_id": p + "M", "user_name": "x", "role_code": "ZZ", "password": "x"}).status_code == 422
    assert c.post("/sys/users", data={"login_id": p + "M", "user_name": "x", "role_code": "SH"}).status_code == 422
    assert client("pr").post("/sys/users", data={"login_id": p + "M", "user_name": "x", "role_code": "SH",
                                                 "password": "x"}).status_code == 403


@pytest.mark.fn("F-SYS-012")
def test_user_update_role_applies_next_request(p):
    lid, pw, uid = make_user(p, "SL")
    u = login(lid, pw)
    assert u.get("/bas/warehouses").status_code == 403           # 영업부는 BAS-030 칸 없음
    c = client("admin")
    r = c.post(f"/sys/users/{uid}", data={"user_name": "바꾼 이름", "role_code": "PR", "status": "정상"})
    assert r.status_code == 200, r.text
    assert u.get("/bas/warehouses").status_code == 200           # 다음 요청부터 생산부 권한 (세션 그대로)
    r = c.post(f"/sys/users/{uid}", data={"user_name": "x", "role_code": "PR", "status": "잠금"})
    assert r.status_code == 200
    assert u.get("/bas/warehouses", headers={"accept": "application/json"}).status_code == 401
    assert c.post(f"/sys/users/{uid}", data={"login_id": "다른", "user_name": "x", "role_code": "PR",
                                             "status": "정상"}).status_code == 422
    admin_id = rbac.load_user("admin").id
    assert c.post(f"/sys/users/{admin_id}", data={"user_name": "x", "role_code": "ADM",
                                                  "status": "중지"}).status_code == 422   # 자기 계정
    assert c.post("/sys/users/99999999999", data={"user_name": "x", "role_code": "PR", "status": "정상"}).status_code == 404


@pytest.mark.fn("F-SYS-013")
def test_user_deactivate_next_request_401(p):
    lid, pw, uid = make_user(p, "PR")
    u = login(lid, pw)
    assert u.get("/").status_code == 200
    r = client("admin").post(f"/sys/users/{uid}/delete")
    assert r.status_code == 200 and r.json()["status"] == "중지"
    assert conn.q1("select status from sys_user where user_id = %s", (uid,))["status"] == "중지"   # 지우지 않는다
    assert u.get("/", headers={"accept": "application/json"}).status_code == 401
    assert TestClient(app).post("/login", data={"login_id": lid, "password": pw}).status_code == 401
    assert client("admin").post(f"/sys/users/{rbac.load_user('admin').id}/delete").status_code == 422
    assert client("admin").post("/sys/users/99999999999/delete").status_code == 404


@pytest.mark.fn("F-SYS-014")
def test_user_list(p):
    make_user(p, "AC")
    r = client("admin").get("/sys/users", params={"q": p})
    assert r.status_code == 200 and p + "U" in r.text and "pbkdf2" not in r.text.lower()
    assert client("pr").get("/sys/users").status_code == 403


# ── SYS-020 역할·권한 ──
@pytest.mark.fn("F-SYS-021")
def test_roles_save_cell_and_restore(p):
    lid, pw, _ = make_user(p, "ST")
    u = login(lid, pw)
    before = rbac.level("ST", "SYS-030")
    assert before is None
    c = client("admin")
    try:
        r = c.post("/sys/roles", data={"cell:ST:SYS-030": "R"})
        assert r.status_code == 200 and r.json()["changed"] == 1
        assert conn.q1("select level, updated_by from sys_permission where role_code = 'ST' and screen_id = 'SYS-030'") == \
            {"level": "R", "updated_by": "admin"}
        assert u.get("/sys/codes").status_code == 200              # 다음 요청부터 (invalidate)
        assert c.post("/sys/roles", data={"cell:ST:SYS-030": "R"}).json()["changed"] == 0
    finally:
        c.post("/sys/roles", data={"cell:ST:SYS-030": ""})
    assert u.get("/sys/codes").status_code == 403
    # 검증 — 값 · 없는 칸 · 누락 · 전산 관리자 보호
    assert c.post("/sys/roles", data={"cell:ST:SYS-030": "X"}).status_code == 422
    assert c.post("/sys/roles", data={"cell:ZZ:SYS-030": "R"}).status_code == 422
    assert c.post("/sys/roles", data={"cell:ST:NOPE-1": "R"}).status_code == 422
    assert c.post("/sys/roles", data={}).status_code == 422
    assert c.post("/sys/roles", data={"cell:ADM:BAS-010": ""}).status_code == 422
    assert c.post("/sys/roles", data={"cell:ADM:SYS-020": "R"}).status_code == 422
    assert rbac.level("ADM", "SYS-020") == "W"
    assert client("ex").post("/sys/roles", data={"cell:ST:SYS-030": "R"}).status_code == 403


@pytest.mark.fn("F-SYS-022")
def test_roles_view(p):
    r = client("admin").get("/sys/roles")
    assert r.status_code == 200 and "시드를 다시 돌리면 매트릭스" in r.text and 'name="cell:SL:WO-010"' in r.text


# ── SYS-030 공통코드 ──
@pytest.mark.fn("F-SYS-031")
def test_code_save_update_delete(p):
    c = client("admin")
    r = c.post("/sys/codes", data={"group_code": "불량유형", "code": p + "D", "code_name": "불량 (예시)", "sort_no": "9"})
    assert r.status_code == 200 and r.json()["result"] == "등록"
    cid = r.json()["id"]
    assert c.post("/sys/codes", data={"group_code": "불량유형", "code": p + "D", "code_name": "x"}).status_code == 422
    assert c.post("/sys/codes", data={"group_code": "색상", "code": p + "E", "code_name": "x"}).status_code == 422
    assert c.post("/sys/codes", data={"group_code": "설비", "code": p + "E"}).status_code == 422
    r = c.post("/sys/codes", data={"id": str(cid), "code_name": "바꾼 이름", "use_yn": "N"})
    assert r.status_code == 200 and r.json()["result"] == "수정"
    assert conn.q1("select code_name, use_yn from sys_common_code where id = %s", (cid,)) == {"code_name": "바꾼 이름", "use_yn": "N"}
    assert c.post("/sys/codes", data={"id": str(cid), "code": "다른", "code_name": "x"}).status_code == 422
    assert c.post("/sys/codes", data={"id": "99999999999", "code_name": "x"}).status_code == 404
    assert c.post("/sys/codes", data={"id": str(cid), "action": "delete"}).json()["result"] == "삭제"
    # 참조가 있으면 사용 중지 — 설비 코드를 지시가 쓴다
    from test_dev1_common import make_customer, make_item, make_order, make_request
    eq = c.post("/sys/codes", data={"group_code": "설비", "code": p + "EQ", "code_name": "설비 (예시)"}).json()["id"]
    it, cu = make_item(p), make_customer(p)
    rq = make_request(p, customer_id=cu["id"], item_id=it["id"])
    make_order(p, request_id=rq["id"], item_id=it["id"], equipment_code=p + "EQ")
    assert c.post("/sys/codes", data={"id": str(eq), "action": "delete"}).json()["result"] == "사용 중지"
    assert c.post("/sys/codes", data={"action": "delete"}).status_code == 422
    assert client("pr").post("/sys/codes", data={"group_code": "설비", "code": p + "Z", "code_name": "x"}).status_code == 403


@pytest.mark.fn("F-SYS-032")
def test_code_list(p):
    r = client("admin").get("/sys/codes", params={"group": "설비"})
    assert r.status_code == 200 and "설비" in r.text
    assert client("admin").get("/sys/codes", params={"group": "없는그룹"}).status_code == 422


# ── SYS-040 로그 ──
@pytest.mark.fn("F-SYS-041")
def test_logs_three_tabs(p):
    c = client("admin")
    c.post("/sys/codes", data={"group_code": "수금수단", "code": p + "M", "code_name": "x (예시)"})
    r = c.get("/sys/logs", params={"tab": "change", "log_type": "F-SYS-031"})
    assert r.status_code == 200 and f"sys_common_code:수금수단/{p}M" in r.text
    r = c.get("/sys/logs", params={"tab": "access", "login": "admin", "log_type": "조회"})
    assert r.status_code == 200 and "SYS-040" in r.text
    assert c.get("/sys/logs", params={"tab": "x"}).status_code == 422
    assert client("pr").get("/sys/logs").status_code == 403


# ── SYS-040 로그 — W3 보강 (ERP 업로드 · SSO 탭 — 전부 읽기만 · AI 호출 · 데이터 질의 탭은 D-529 로 없앴다) ──
LOG_TABS_W3 = ("erp", "sso")


def _admin_uid() -> int:
    return rbac.load_user("admin").id


def _purge_logs(p: str) -> None:
    with conn.tx() as cur:
        cur.execute("delete from erp_upload_batch where batch_no like %s", (p + "%",))
        cur.execute("delete from sys_access_log where log_type = 'SSO' and login_id like %s", (p + "%",))


@pytest.fixture
def lp():
    """로그 행 접두 — 이 테스트가 넣은 로그 행만 끝에 지운다(개발3 의 행은 건드리지 않는다)."""
    prefix = uniq("log")
    yield prefix
    _purge_logs(prefix)
    for t, col in (("erp_upload_batch", "batch_no"),):
        assert conn.q1(f"select count(*) as n from {t} where {col} like %s", (prefix + "%",))["n"] == 0


@pytest.mark.fn("F-SYS-041")
def test_logs_four_tabs_200_and_empty_is_uncollected(lp):
    """탭 4 전부 200 · 내 접두로 거르면 행 0 → 「미수집」 · 원본 표 이름이 화면에 적힌다 · 틀린 구분값 422 · 없앤 탭(ai · dq — D-529) 422."""
    from lcomfine.app.routers import sys as sysr

    assert sysr.LOG_TABS == ("access", "change", "erp", "sso")
    c = client("admin")
    for tab, table in (("access", "sys_access_log"), ("change", "sys_change_log"), ("erp", "erp_upload_batch"),
                       ("sso", "sys_access_log")):
        r = c.get("/sys/logs", params={"tab": tab, "login": lp})
        assert r.status_code == 200, (tab, r.text[:300])
        assert "미수집" in r.text and f"<code>{table}" in r.text
    assert c.get("/sys/logs", params={"tab": "erp", "log_type": "삭제"}).status_code == 422
    assert c.get("/sys/logs", params={"tab": "sso", "log_type": "모름"}).status_code == 422
    assert c.get("/sys/logs", params={"tab": "erp", "date_from": "2026-13-45"}).status_code == 422
    # 없앤 탭 — AI 호출 · 데이터 질의 (D-529): 선택지 밖이라 422 · 화면 탭 목록에도 없다
    assert c.get("/sys/logs", params={"tab": "ai"}).status_code == 422
    assert c.get("/sys/logs", params={"tab": "dq"}).status_code == 422
    page = c.get("/sys/logs", headers={"accept": "text/html"}).text
    assert "?tab=ai" not in page and "?tab=dq" not in page and "AI 호출" not in page and "데이터 질의" not in page


@pytest.mark.fn("F-SYS-041")
def test_logs_erp_tab_shows_batches_and_replacement(lp):
    """ERP 업로드 탭 — 회차 · 반영/교체 · 교체한 회차 번호 · 올린 사람 · 건수 · 오류 건. 기간 1979(다른 테스트와 겹치지 않는다)."""
    with conn.tx() as cur:
        cur.execute("""insert into erp_upload_batch (batch_no, period_from, period_to, round_no, status, source_file, row_count,
                                                     error_count, created_by)
                       values (%s, '1979-01-01', '1979-01-31', 2, '반영', %s, 12, 2, %s) returning id""",
                    (lp + "B2", f"{lp} (예시).xlsx", lp + "ac"))
        new_id = cur.fetchone()["id"]
        cur.execute("""insert into erp_upload_batch (batch_no, period_from, period_to, round_no, status, replaced_by, source_file,
                                                     row_count, error_count, created_by)
                       values (%s, '1979-01-01', '1979-01-31', 1, '교체', %s, %s, 10, 0, %s)""",
                    (lp + "B1", new_id, f"{lp} 이전 (예시).xlsx", lp + "ac"))
    c = client("admin")
    r = c.get("/sys/logs", params={"tab": "erp", "login": lp})
    assert r.status_code == 200
    assert f"{lp}B2" in r.text and f"{lp}B1" in r.text and f"{lp} (예시).xlsx" in r.text and f"{lp}ac" in r.text
    assert 'data-log-tab="erp" data-n="2" data-live="1" data-replaced="1" data-errors="2"' in r.text
    # 교체 회차만 — 교체한 회차 열에 새 회차 번호
    r = c.get("/sys/logs", params={"tab": "erp", "login": lp, "log_type": "교체"})
    assert f"{lp}B1" in r.text and f">{lp}B2<" in r.text and 'data-n="1"' in r.text
    r = c.get("/sys/logs", params={"tab": "erp", "login": lp, "log_type": "반영"})
    assert f"{lp}B1" not in r.text and f"{lp}B2" in r.text
    # 기간 필터 — 업로드 일시(오늘) 밖이면 0
    r = c.get("/sys/logs", params={"tab": "erp", "login": lp, "date_to": "1979-12-31"})
    assert "미수집" in r.text and f"{lp}B2" not in r.text
    # 화면은 쓰지 않는다 — 회차 상태 그대로
    assert conn.q("select status from erp_upload_batch where batch_no like %s order by round_no", (lp + "%",)) == \
        [{"status": "교체"}, {"status": "반영"}]


@pytest.mark.fn("F-SYS-041")
def test_logs_sso_tab_uncollected_until_w4(lp):
    """SSO 탭 — `sys_access_log` 구분 SSO 행만. W4 전엔 행 0 = 「미수집」(0 으로 지어내지 않는다) · 행을 넣으면 사용자·시각·성공 여부가 보인다."""
    c = client("admin")
    r = c.get("/sys/logs", params={"tab": "sso", "login": lp})
    assert r.status_code == 200 and "미수집" in r.text and 'data-log-tab="sso" data-n="0"' in r.text
    if not conn.q1("select count(*) as n from sys_access_log where log_type = 'SSO'")["n"]:
        assert "미수집" in c.get("/sys/logs", params={"tab": "sso"}).text
    with conn.tx() as cur:
        cur.execute("""insert into sys_access_log (log_type, login_id, role_code, method, path, screen_id, function_id, result, detail)
                       values ('SSO', %s, 'SL', 'GET', '/doc/go', 'DOC-010', 'F-DOC-011', '성공', 'SSO 토큰 발급 (예시)'),
                              ('SSO', %s, 'SL', 'GET', '/doc/go', 'DOC-010', 'F-DOC-011', '실패', '계정 매핑 없음 (예시)')""",
                    (lp + "S", lp + "S"))
    r = c.get("/sys/logs", params={"tab": "sso", "login": lp})
    assert 'data-n="2" data-failed="1"' in r.text and "계정 매핑 없음 (예시)" in r.text and f"{lp}S" in r.text
    r = c.get("/sys/logs", params={"tab": "sso", "login": lp, "log_type": "실패"})
    assert "계정 매핑 없음 (예시)" in r.text and "SSO 토큰 발급 (예시)" not in r.text
    # 접속 로그 탭의 구분 SSO 와 같은 행
    assert "계정 매핑 없음 (예시)" in c.get("/sys/logs", params={"tab": "access", "login": lp, "log_type": "SSO"}).text


@pytest.mark.fn("F-SYS-041")
def test_logs_tabs_permission_cells(lp):
    """권한 칸 그대로 — SYS-040 은 전산 관리자 R 만(permission-matrix). 다른 부서는 탭마다 403."""
    for lid in ("pr", "sl", "ac", "ex"):
        for tab in ("access", "change") + LOG_TABS_W3:
            assert client(lid).get("/sys/logs", params={"tab": tab}).status_code == 403, (lid, tab)
    for tab in LOG_TABS_W3:
        assert client("admin").get("/sys/logs", params={"tab": tab}).status_code == 200


# ── SYS-030 공통코드 — 그룹 3 시드 (W3) ──
@pytest.mark.fn("F-SYS-032")
def test_code_groups_seeded_and_idempotent(p):
    """계약 「설비 · 불량유형 · 수금수단 코드를 여기서 관리한다」 — 그룹 3 에 사용 중 코드가 있고 화면이 그룹별로 보인다.
    `seed_dev1.run()` 은 빈 그룹에만 (예시) 코드를 더하고 두 번 돌려도 행 수가 같다."""
    from lcomfine.db import seed_dev1
    before = conn.q1("select count(*) as n from sys_common_code")["n"]
    out = seed_dev1.run()
    assert out["code_group"] == 3 and out["code_added"] == 0, out
    assert seed_dev1.run() == out
    assert conn.q1("select count(*) as n from sys_common_code")["n"] == before
    rows = conn.q("select group_code, count(*) filter (where use_yn = 'Y') as live from sys_common_code group by 1")
    assert {r["group_code"] for r in rows} >= {"설비", "불량유형", "수금수단"} and all(r["live"] >= 1 for r in rows)
    c = client("admin")
    for g in ("설비", "불량유형", "수금수단"):
        r = c.get("/sys/codes", params={"group": g})
        assert r.status_code == 200 and "(예시)" in r.text
    assert client("ex").get("/sys/codes").status_code == 403


@pytest.mark.fn("F-SYS-041")
def test_logs_access_and_change_filter_outside_choices_422(lp):
    """DEF-QA1-008 — 접속 탭 구분은 db-schema 값 집합(로그인·조회·변경·오류·SSO) 밖이면 422, 변경 탭 기능 ID 는 계약에 없으면 422.
    값 집합 안은 200 (erp · dq · sso 와 같은 `choice()` 규칙 · D-609)."""
    c = client("admin")
    assert c.get("/sys/logs", params={"tab": "access", "log_type": "XYZ"}).status_code == 422
    assert c.get("/sys/logs", params={"tab": "change", "log_type": "F-ZZ-999"}).status_code == 422
    assert c.get("/sys/logs", params={"tab": "change", "log_type": "XYZ"}).status_code == 422
    for lt in ("로그인", "조회", "변경", "오류", "SSO"):
        assert c.get("/sys/logs", params={"tab": "access", "log_type": lt, "login": lp}).status_code == 200, lt
    assert c.get("/sys/logs", params={"tab": "change", "log_type": "F-SYS-041", "login": lp}).status_code == 200
    assert c.get("/sys/logs", params={"tab": "access"}).status_code == 200
