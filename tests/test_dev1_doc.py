# tests/test_dev1_doc.py — DOC 문서관리 SSO (W4) — sso.issue · sso.consume · DOC-010 · DOC-020 — 실제 DB · 시드 뒤
# 문서관리 시스템이 없다 — 자동 POST 폼은 렌더만 보고, 토큰 검증은 sso.consume 으로 한다(외부로 보내지 않는다).
# 사용자는 테스트 계정(난수 비밀번호 · 고유 접두)만 쓰고 끝에 토큰 · 매핑 · SSO 로그 · 계정을 지운다. 시드 계정의 매핑은 건드리지 않는다.
import base64
import io
import json
import re
import secrets
import threading
from datetime import UTC, datetime, timedelta

import pytest

from lcomfine.app import rbac, settings, sso
from lcomfine.db import conn
from test_dev1_common import cleanup, client, login, make_user, uniq

HTML = {"accept": "text/html"}
JSON = {"accept": "application/json"}
URL = "https://doc.example.invalid/sso/entry"          # 테스트 전용 · 보내지 않는다(.invalid)


@pytest.fixture
def p(monkeypatch):
    """SSO 주소 · 비밀이 있는 상태. 비밀은 지금 .env 값을 쓰고, 없을 때만 실행마다 난수(어디에도 적지 않는다)."""
    prefix = uniq("doc")
    monkeypatch.setenv("LCOMFINE_DOC_SSO_URL", URL)
    if not settings.get_settings().sso_secret:
        monkeypatch.setenv("LCOMFINE_SSO_SECRET", secrets.token_urlsafe(32))
    settings.reset_cache()
    yield prefix
    monkeypatch.undo()
    settings.reset_cache()
    conn.x("delete from sys_access_log where log_type = 'SSO' and login_id like %s", (prefix + "%",))
    cleanup(prefix)


def mapped(prefix: str, role: str = "PR", tag: str = "U", *, active: bool = True):
    """테스트 계정 + 문서관리 매핑. 반환 (login_id, password, user_id, account_id)."""
    lid, pw, uid = make_user(prefix, role, tag)
    acc = f"{prefix}{tag}-acc"
    conn.x("insert into doc_account_map (user_id, account_id, active, created_by) values (%s, %s, %s, 'test')",
           (uid, acc, active))
    return lid, pw, uid, acc


def hidden_token(html: str) -> str:
    m = re.findall(r'<input type="hidden" name="token" value="([^"]+)">', html)
    assert len(m) == 1, "토큰 hidden 칸은 하나"
    return m[0]


def issue_direct(login_id: str, *, now=None) -> tuple[str, str]:
    with conn.tx() as cur:
        return sso.issue(cur, rbac.load_user(login_id), now=now)


def consume(token: str, *, now=None) -> dict:
    with conn.tx() as cur:
        return sso.consume(cur, token, now=now)


def sso_logs(login_id: str) -> list[dict]:
    return conn.q("select * from sys_access_log where log_type = 'SSO' and login_id = %s order by log_id", (login_id,))


# ── F-DOC-011 문서관리 진입 — 발급 → 자동 POST 폼 → consume 1회 ──
@pytest.mark.fn("F-DOC-011")
def test_go_issues_token_in_hidden_form_once(p):
    lid, pw, uid, acc = mapped(p)
    u = login(lid, pw)
    r = u.post("/doc/go", headers=HTML, follow_redirects=False)
    assert r.status_code == 200, r.text
    token = hidden_token(r.text)
    assert f'action="{URL}"' in r.text and 'method="post"' in r.text and "data-auto-submit" in r.text
    assert r.text.count(token) == 1                                          # 폼 hidden 칸 하나에만
    assert token not in str(r.url) and token not in (r.headers.get("location") or "")
    assert "no-store" in r.headers.get("cache-control", "")
    got = consume(token)
    assert got["account_id"] == acc and got["user_id"] == uid and got["login_id"] == lid and got["used_at"]
    with pytest.raises(sso.Invalid, match="이미 사용한"):
        consume(token)                                                       # 재사용 거부
    # 토큰 글자는 로그 · 변경 로그 · DB 어디에도 없다
    for row in sso_logs(lid):
        assert token not in json.dumps(row, default=str)
    assert not conn.q1("select 1 from sys_access_log where detail like %s or target like %s or path like %s",
                       (f"%{token}%", f"%{token}%", f"%{token}%"))
    assert not conn.q1("select 1 from sys_change_log where detail like %s or target like %s", (f"%{token}%",) * 2)
    logs = sso_logs(lid)
    assert logs and logs[-1]["result"] == "성공" and logs[-1]["screen_id"] == "DOC-010"
    assert logs[-1]["function_id"] == "F-DOC-011" and logs[-1]["role_code"] == "PR" and logs[-1]["logged_at"]
    assert conn.q1("select 1 from sys_change_log where login_id = %s and function_id = 'F-DOC-011'", (lid,))
    # JSON 응답에는 토큰이 없다(jti 만)
    j = u.post("/doc/go", headers=JSON)
    assert j.status_code == 200 and j.json()["ok"] is True and "token" not in json.dumps(j.json()).replace('"field": "token"', "")
    assert conn.q1("select 1 from sso_token where jti = %s and user_id = %s and used_at is null", (j.json()["jti"], uid))
    # GET 으로는 발급하지 않는다(안내 화면 · 토큰 없음)
    g = u.get("/doc/go")
    assert g.status_code == 200 and 'name="token"' not in g.text and 'data-doc-go="ready"' in g.text
    assert re.search(r'<form method="post" action="/doc/go" data-auto-submit>', g.text)          # 준비됨 → 자동 제출(같은 창)


@pytest.mark.fn("F-DOC-011")
def test_token_expiry_60s_with_injected_time(p):
    lid, _pw, _uid, _acc = mapped(p)
    t0 = datetime.now(UTC).replace(microsecond=0)
    token, jti = issue_direct(lid, now=t0)
    row = conn.q1("select issued_at, expires_at, used_at from sso_token where jti = %s", (jti,))
    assert row["expires_at"] - row["issued_at"] == timedelta(seconds=sso.TTL_SECONDS) == timedelta(seconds=60)
    with pytest.raises(sso.Invalid, match="만료"):
        consume(token, now=t0 + timedelta(seconds=60))
    with pytest.raises(sso.Invalid, match="만료"):
        consume(token, now=t0 + timedelta(hours=1))
    assert consume(token, now=t0 + timedelta(seconds=59))["jti"] == jti      # 만료 직전은 통과(그리고 쓰였다)
    old, _ = issue_direct(lid, now=t0 - timedelta(seconds=61))
    with pytest.raises(sso.Invalid, match="만료"):
        consume(old)


@pytest.mark.fn("F-DOC-011")
def test_tampered_or_malformed_token_rejected(p):
    lid, _pw, _uid, _acc = mapped(p)
    token, jti = issue_direct(lid)
    body, sig = token.split(".")
    flipped = sig[:-2] + ("A" if sig[-2] != "A" else "B") + sig[-1]
    with pytest.raises(sso.Invalid, match="서명"):
        consume(f"{body}.{flipped}")
    payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    payload["sub"] = "someone-else"
    forged = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    with pytest.raises(sso.Invalid, match="서명"):
        consume(f"{forged}.{sig}")
    for bad in ("", "abc", "a.b.c", f"{body}.", f".{sig}", "\x00.\x00", "가.나", f"{body}.{sig}x" * 200):
        with pytest.raises(sso.Invalid):
            consume(bad)
    assert conn.q1("select used_at from sso_token where jti = %s", (jti,))["used_at"] is None   # 거부된 시도는 쓰지 않는다
    assert consume(token)["jti"] == jti


@pytest.mark.fn("F-DOC-011")
def test_concurrent_consume_only_one_wins(p):
    lid, _pw, _uid, _acc = mapped(p)
    token, _jti = issue_direct(lid)
    barrier = threading.Barrier(2)
    results: list[str] = []

    def worker():
        barrier.wait()
        try:
            consume(token)
            results.append("ok")
        except sso.Invalid as exc:
            results.append(exc.reason)

    ts = [threading.Thread(target=worker) for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(20)
    assert sorted(results) == ["ok", "이미 사용한 토큰입니다"], results


@pytest.mark.fn("F-DOC-011")
def test_inactive_user_refused_and_unused_token_rejected(p):
    """SYS-010 에서 비활성으로 바꾸면 — 그 세션은 다음 요청부터 401(발급 없음) · issue 는 DB 를 다시 읽어 거부 · 이미 받은 미사용 토큰도 consume 거부."""
    lid, pw, uid, _acc = mapped(p)
    u = login(lid, pw)
    stale = rbac.load_user(lid)                                              # 상태 「정상」 때의 객체
    token, jti = issue_direct(lid)
    assert client("admin").post(f"/sys/users/{uid}/delete").status_code == 200   # F-SYS-013 → 중지
    n_before = conn.q1("select count(*) as n from sso_token where user_id = %s", (uid,))["n"]
    assert u.post("/doc/go", headers=JSON).status_code == 401
    with conn.tx() as cur, pytest.raises(sso.NotMapped, match="비활성"):
        sso.issue(cur, stale)                                                # 넘겨받은 객체가 아니라 DB 의 상태를 본다
    assert conn.q1("select count(*) as n from sso_token where user_id = %s", (uid,))["n"] == n_before
    with pytest.raises(sso.Invalid, match="비활성"):
        consume(token)
    # 잠금도 같다
    lid2, _pw2, uid2, _ = mapped(p, tag="L")
    tok2, _ = issue_direct(lid2)
    conn.x("update sys_user set status = '잠금' where user_id = %s", (uid2,))
    with pytest.raises(sso.Invalid, match="비활성"):
        consume(tok2)


@pytest.mark.fn("F-DOC-011")
def test_unmapped_or_disabled_mapping_refused_with_log(p):
    lid, pw, uid = make_user(p, "SH", "N")
    u = login(lid, pw)
    r = u.post("/doc/go", headers=JSON)
    assert r.status_code == 422 and "관리자에게 계정 연결을 요청하세요" in r.json()["message"]
    assert r.json()["fields"][0]["name"] == "계정 매핑"
    assert not conn.q1("select 1 from sso_token where user_id = %s", (uid,))
    log = sso_logs(lid)[-1]
    assert log["result"] == "실패" and "매핑이 없습니다" in log["detail"] and log["function_id"] == "F-DOC-011"
    g = u.get("/doc/go")
    assert g.status_code == 200 and "관리자에게 계정 연결을 요청하세요" in g.text and 'data-doc-go="refused"' in g.text
    b = u.post("/doc/go", headers=HTML, follow_redirects=False)              # 브라우저 폼 POST 422 → 303 + 알림
    assert b.status_code == 303 and "token" not in (b.headers.get("location") or "")
    lid2, pw2, uid2, _ = mapped(p, "SH", "D", active=False)                  # 사용 중지 매핑
    r = login(lid2, pw2).post("/doc/go", headers=JSON)
    assert r.status_code == 422 and "사용 중지" in r.json()["fields"][0]["reason"]
    assert not conn.q1("select 1 from sso_token where user_id = %s", (uid2,))
    with pytest.raises(sso.NotMapped):
        issue_direct(lid2)


@pytest.mark.fn("F-DOC-011")
def test_no_url_or_no_secret_is_undecided_d517(p, monkeypatch):
    lid, pw, uid, _acc = mapped(p)
    u = login(lid, pw)
    monkeypatch.setenv("LCOMFINE_DOC_SSO_URL", "")
    settings.reset_cache()
    g = u.get("/doc/go")
    assert g.status_code == 200 and "미확정 (D-517)" in g.text and 'data-doc-go="undecided"' in g.text
    assert "LCOMFINE_DOC_SSO_URL" in g.text and 'name="token"' not in g.text
    r = u.post("/doc/go", headers=JSON)
    assert r.status_code == 422 and "미확정 (D-517)" in r.json()["message"]                      # D-610 (5xx 아님 · G-19)
    assert r.json()["fields"] == [{"name": "SSO 설정", "reason": "문서관리 SSO 주소(LCOMFINE_DOC_SSO_URL) 미확정 (D-517)"}]
    assert not conn.q1("select 1 from sso_token where user_id = %s", (uid,))
    assert sso_logs(lid)[-1]["result"] == "실패" and "D-517" in sso_logs(lid)[-1]["detail"]
    # 비밀 없음 — 발급하지 않는다 · sso.issue 도 명시적 오류
    monkeypatch.setenv("LCOMFINE_DOC_SSO_URL", URL)
    monkeypatch.setenv("LCOMFINE_SSO_SECRET", "")
    settings.reset_cache()
    r = u.post("/doc/go", headers=JSON)
    assert r.status_code == 422 and "LCOMFINE_SSO_SECRET" in r.json()["message"] and "D-517" in r.json()["message"]
    with pytest.raises(sso.NotConfigured):
        issue_direct(lid)
    with pytest.raises(sso.NotConfigured):
        consume("a.b")
    assert "미확정 (D-517)" in u.get("/doc/go").text
    assert not conn.q1("select 1 from sso_token where user_id = %s", (uid,))


@pytest.mark.fn("F-DOC-011")
def test_go_forbidden_without_permission_cell(p, monkeypatch):
    """권한 예외 = 화면 R 이상. 칸이 없는 부서는 403(정본은 8 부서 모두 R — 칸을 지운 상태를 흉내 낸다)."""
    lid, pw, uid, _acc = mapped(p, "EX")
    real = rbac.level
    monkeypatch.setattr(rbac, "level", lambda role, sid: None if (role, sid) == ("EX", "DOC-010") else real(role, sid))
    u = login(lid, pw)
    assert u.post("/doc/go", headers=JSON).status_code == 403
    assert u.get("/doc/go", headers=JSON).status_code == 403
    assert not conn.q1("select 1 from sso_token where user_id = %s", (uid,))
    monkeypatch.setattr(rbac, "level", real)
    assert u.post("/doc/go", headers=JSON).status_code == 200                # R 이면 통과


# ── F-DOC-012 바로가기 조회 ──
@pytest.mark.fn("F-DOC-012")
def test_go_page_states(p):
    lid, pw, _uid, acc = mapped(p, "DS")
    g = login(lid, pw).get("/doc/go")
    assert g.status_code == 200 and acc in g.text and "문서관리 열기" in g.text
    assert 'method="post"' in g.text and 'name="token"' not in g.text
    for seed_login in ("sl", "pr", "sh", "ds", "ac", "st", "ex", "admin"):  # 정본 8 부서 모두 R
        assert client(seed_login).get("/doc/go").status_code == 200, seed_login


@pytest.mark.fn("F-DOC-012")
def test_go_page_auto_submit_only_when_ready(p, monkeypatch):
    """DEF-QA1-010 — 메뉴(새 창) 한 번 클릭으로 진입: 발급할 수 있을 때만 진입 폼에 data-auto-submit. 준비 안 됨(미매핑 · 사용 중지 매핑 ·
    주소 없음 · 비밀 없음)이면 안내만 — 자동 제출도 진입 폼도 없다. 메뉴 링크는 target=_blank(base.html · 아키텍트)."""
    lid, pw, _uid, _acc = mapped(p, "SL", "R")
    u = login(lid, pw)
    g = u.get("/doc/go")
    assert 'data-doc-go="ready"' in g.text and g.text.count("data-auto-submit") == 1 and 'target="_blank" rel="noopener"' not in g.text.split('data-doc-go="ready"')[1]
    menu = re.search(r'<a\b[^>]*data-screen="DOC-010"[^>]*>', u.get("/").text)
    assert menu and 'target="_blank"' in menu.group(0)
    ln, pn, _un = make_user(p, "SL", "Q")
    lu, pu, _uu, _ = mapped(p, "SL", "S", active=False)
    for c in (login(ln, pn), login(lu, pu)):
        g = c.get("/doc/go")
        assert 'data-doc-go="refused"' in g.text and "data-auto-submit" not in g.text and 'action="/doc/go"' not in g.text
    for k in ("LCOMFINE_DOC_SSO_URL", "LCOMFINE_SSO_SECRET"):
        monkeypatch.setenv(k, "")
        settings.reset_cache()
        g = u.get("/doc/go")
        assert 'data-doc-go="undecided"' in g.text and "data-auto-submit" not in g.text and "미확정 (D-517)" in g.text, k
        monkeypatch.undo()
        monkeypatch.setenv("LCOMFINE_DOC_SSO_URL", URL)
        settings.reset_cache()


# ── F-DOC-021 계정 매핑 등록 (한 건 · 엑셀 일괄) ──
@pytest.mark.fn("F-DOC-021")
def test_map_create_one_to_one(p):
    a = client("admin")
    _l1, _p1, u1 = make_user(p, "PR", "A")
    _l2, _p2, u2 = make_user(p, "PR", "B")
    r = a.post("/doc/account-map", data={"user_id": str(u1), "account_id": p + "acc1"})
    assert r.status_code == 200, r.text
    assert conn.q1("select active from doc_account_map where user_id = %s", (u1,))["active"] is True
    r = a.post("/doc/account-map", data={"user_id": str(u1), "account_id": p + "acc2"})        # 한 사용자에 둘
    assert r.status_code == 422 and r.json()["fields"][0]["name"] == "MES 사용자"
    r = a.post("/doc/account-map", data={"user_id": str(u2), "account_id": p + "acc1"})        # 한 계정에 둘
    assert r.status_code == 422 and r.json()["fields"][0]["name"] == "문서관리 계정 ID"
    conn.x("update doc_account_map set active = false where user_id = %s", (u1,))              # 사용 중지도 자리를 차지
    r = a.post("/doc/account-map", data={"user_id": str(u2), "account_id": p + "acc1"})
    assert r.status_code == 422 and "사용 중지" in r.json()["fields"][0]["reason"]
    assert a.post("/doc/account-map", data={"user_id": str(u2)}).status_code == 422             # 누락
    r = a.post("/doc/account-map", data={"user_id": str(u2), "account_id": "x\x00y"})
    assert r.status_code == 422 and r.json()["fields"][0]["name"] == "문서관리 계정 ID" and "NUL" in r.json()["fields"][0]["reason"]
    r = a.post("/doc/account-map", data={"user_id": "9999999999", "account_id": p + "z"})
    assert r.status_code == 422 and r.json()["fields"][0]["name"] == "MES 사용자"
    assert a.post("/doc/account-map", data={"user_id": "abc", "account_id": p + "z"}).status_code == 422
    for lid in ("pr", "sl", "ex"):                                                              # DOC-020 은 전산 관리자 W 만
        assert client(lid).post("/doc/account-map", data={"user_id": str(u2), "account_id": p + "z"}).status_code == 403
    assert conn.q1("select count(*) as n from sys_change_log where function_id = 'F-DOC-021' and target like %s",
                   (f"doc_account_map:{p}%",))["n"] == 1


def _xlsx(rows: list[tuple]) -> bytes:
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.mark.fn("F-DOC-021")
def test_map_bulk_excel(p):
    a = client("admin")
    l1, _, u1 = make_user(p, "PR", "X1")
    l2, _, u2 = make_user(p, "SH", "X2")
    l3, _, u3 = make_user(p, "SL", "X3")
    bad = _xlsx([("사번", "문서관리 계정 ID", "비고"), (l1, p + "b1", ""), (None, None, None), (l2, "", ""),
                 (p + "없음", p + "b3", ""), (l3, p + "b1", ""), (l1, p + "b4", "")])
    r = a.post("/doc/account-map", files={"file": ("map.xlsx", bad, XLSX)})
    assert r.status_code == 422, r.text
    reasons = {f["name"]: f["reason"] for f in r.json()["fields"]}
    assert "오류 행 4 / 5" in r.json()["message"] and "아무것도 등록하지 않았습니다" in r.json()["message"]
    assert "비었습니다" in reasons["4행"] and "없는 사번" in reasons["5행"]
    assert "계정 ID 가 겹칩니다 (2행)" in reasons["6행"] and "사번이 겹칩니다 (2행)" in reasons["7행"]
    assert "2행" not in reasons and "3행" not in reasons                                        # 빈 줄은 세지 않는다
    assert not conn.q1("select 1 from doc_account_map where user_id = any(%s)", ([u1, u2, u3],))
    ok = _xlsx([("문서관리 계정 ID", "사번"), (p + "b1", l1), (p + "b2", l2)])
    r = a.post("/doc/account-map", files={"file": ("map.xlsx", ok, XLSX)})
    assert r.status_code == 200 and r.json()["count"] == 2, r.text
    assert conn.q1("select account_id from doc_account_map where user_id = %s", (u2,))["account_id"] == p + "b2"
    r = a.post("/doc/account-map", files={"file": ("map.xlsx", _xlsx([("사번", "문서관리 계정 ID"), (l3, p + "b2")]), XLSX)})
    assert r.status_code == 422 and "다른 사용자" in r.json()["fields"][0]["reason"]           # DB 의 매핑과 1:1
    r = a.post("/doc/account-map", files={"file": ("map.xlsx", _xlsx([("ID", "계정")]), XLSX)})
    assert r.status_code == 422 and r.json()["fields"][0]["name"] == "엑셀 파일"
    r = a.post("/doc/account-map", files={"file": ("map.xlsx", b"not a zip", XLSX)})
    assert r.status_code == 422 and ".xlsx" in r.json()["fields"][0]["reason"]
    r = a.post("/doc/account-map", files={"file": ("map.xlsx", _xlsx([("사번", "문서관리 계정 ID"), (l3, "a" * 201)]), XLSX)})
    assert r.status_code == 422 and "200자" in r.json()["fields"][0]["reason"]                 # (NUL 은 xlsx 에 담기지 않는다)


# ── F-DOC-022 계정 매핑 수정 ──
@pytest.mark.fn("F-DOC-022")
def test_map_update(p):
    a = client("admin")
    lid, _pw, uid, acc = mapped(p, tag="E")
    _l2, _p2, _u2, acc2 = mapped(p, tag="F")
    mid = conn.q1("select id from doc_account_map where user_id = %s", (uid,))["id"]
    r = a.post(f"/doc/account-map/{mid}", data={"account_id": p + "new", "use_yn": "Y"})
    assert r.status_code == 200, r.text
    assert conn.q1("select account_id, updated_by from doc_account_map where id = %s", (mid,)) == {"account_id": p + "new",
                                                                                                    "updated_by": "admin"}
    r = a.post(f"/doc/account-map/{mid}", data={"account_id": acc2, "use_yn": "Y"})
    assert r.status_code == 422 and r.json()["fields"][0]["name"] == "문서관리 계정 ID"
    assert a.post(f"/doc/account-map/{mid}", data={"account_id": p + "new", "use_yn": "Y", "user_id": "1"}).status_code == 422
    assert a.post(f"/doc/account-map/{mid}", data={"use_yn": "Y"}).status_code == 422
    assert a.post(f"/doc/account-map/{mid}", data={"account_id": p + "new", "use_yn": "X"}).status_code == 422
    assert a.post("/doc/account-map/99999999999", data={"account_id": p + "q"}).status_code == 404
    assert a.post("/doc/account-map/abc", data={"account_id": p + "q"}).status_code == 404
    assert client("pr").post(f"/doc/account-map/{mid}", data={"account_id": p + "q"}).status_code == 403
    tok, _ = issue_direct(lid)                                                                  # 발급 뒤 계정 ID 를 바꾸면
    a.post(f"/doc/account-map/{mid}", data={"account_id": p + "new2", "use_yn": "Y"})
    with pytest.raises(sso.Invalid, match="매핑"):
        consume(tok)
    a.post(f"/doc/account-map/{mid}", data={"account_id": p + "new2", "use_yn": "N"})          # 사용 중지 → 발급 거부
    with pytest.raises(sso.NotMapped, match="사용 중지"):
        issue_direct(lid)


# ── F-DOC-023 계정 매핑 삭제 ──
@pytest.mark.fn("F-DOC-023")
def test_map_delete_or_disable(p):
    a = client("admin")
    _l, _pw, u1, _a = mapped(p, tag="G")
    lid2, _pw2, u2, _a2 = mapped(p, tag="H")
    m1 = conn.q1("select id from doc_account_map where user_id = %s", (u1,))["id"]
    m2 = conn.q1("select id from doc_account_map where user_id = %s", (u2,))["id"]
    r = a.post(f"/doc/account-map/{m1}/delete")
    assert r.status_code == 200 and r.json()["result"] == "삭제"
    assert not conn.q1("select 1 from doc_account_map where id = %s", (m1,))
    issue_direct(lid2)                                                                          # 발급 기록 → 사용 중지
    r = a.post(f"/doc/account-map/{m2}/delete")
    assert r.status_code == 200 and r.json()["result"] == "사용 중지"
    assert conn.q1("select active from doc_account_map where id = %s", (m2,))["active"] is False
    assert login(lid2, _pw2).post("/doc/go", headers=JSON).status_code == 422
    assert a.post("/doc/account-map/99999999999/delete").status_code == 404
    assert client("sl").post(f"/doc/account-map/{m2}/delete").status_code == 403


# ── F-DOC-024 계정 매핑 조회 ──
@pytest.mark.fn("F-DOC-024")
def test_map_view_unmapped_and_d517(p):
    a = client("admin")
    lid_n, _pw, _u = make_user(p, "AC", "N")
    lid_m, _pw2, _u2, acc = mapped(p, tag="M")
    lid_d, _pw3, _u3, acc_d = mapped(p, tag="D", active=False)
    r = a.get("/doc/account-map", params={"q": p})
    assert r.status_code == 200 and "미확정 (D-517)" in r.text and "매핑은 필수" in r.text
    unm = r.text.split("미연결 사용자", 1)[1]
    assert lid_n in unm and lid_d in unm and lid_m not in unm                                   # 사용 중지 매핑 = 미연결
    assert acc in r.text and "엑셀 일괄 등록" in r.text
    assert a.get("/doc/account-map", params={"edit": "abc"}).status_code == 404
    assert a.get("/doc/account-map", params={"q": "x\x00"}).status_code == 422
    for lid in ("sl", "pr", "sh", "ds", "ac", "st", "ex"):                                      # 칸 = 전산 관리자만
        assert client(lid).get("/doc/account-map").status_code == 403, lid
