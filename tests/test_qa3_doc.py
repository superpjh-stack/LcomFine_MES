# tests/test_qa3_doc.py — QA3 W4 문서 SSO (DOC) · 앱 DB 역할 (D-524): G-18 토큰 규칙 · 화면 경로 · 서버 로그 · DOC-020 매핑 · G-19/G-20/G-22 DOC · X-11 · X-12.
# tools/check_security.py 의 검사를 그대로 부른다. 문서관리 시스템은 없다 — 주소는 가짜(`https://doc.example.invalid/sso`) · 비밀은 실행마다 난수이고
# `cs.sso_env()` 가 끝에 원래 값으로 되돌린다. 자동 POST 폼은 렌더만 본다(외부 전송 0). 임시 계정(접두 q3…)의 토큰 · 매핑은 끝에 지운다.
import pytest

from tools import check_security as cs


@pytest.fixture(scope="module")
def lab():
    with cs.Lab() as lab_:
        yield lab_


def _assert(results):
    results = results if isinstance(results, list) else [results]
    bad = [r.line() for r in results if not r.ok]
    assert not bad, "\n".join(bad)


def _pick(results, *needles):
    got = [r for r in results if any(n in r.item for n in needles)]
    assert got, f"검사 행이 없다: {needles}"
    return got


@pytest.fixture(scope="module")
def token_rules(lab):
    return cs.check_sso_token(lab)


@pytest.fixture(scope="module")
def http_rows(lab):
    return cs.check_sso_http(lab)


@pytest.fixture(scope="module")
def doc_map(lab):
    return cs.check_doc_map(lab)


@pytest.fixture(scope="module")
def db_role():
    return cs.check_db_role()


@pytest.mark.fn("F-DOC-011")
def test_g18_issue_consume_once_reuse_and_expiry(token_rules):
    """발급 → consume 1회 · 재사용 거부 · 만료(now 주입 +60 · +61초 거부 · +59초 통과)."""
    _assert(_pick(token_rules, "재사용 거부", "만료"))


@pytest.mark.fn("F-DOC-011")
def test_g18_tampered_wrong_secret_malformed_rejected(token_rules):
    """서명 · 본문 변조 · 다른 비밀 · 형식 깨짐 · 발급 기록 없는 jti → 전부 sso.Invalid · 원 토큰은 태워지지 않는다."""
    _assert(_pick(token_rules, "변조"))


@pytest.mark.fn("F-DOC-011")
def test_g18_concurrent_consume_only_one(token_rules):
    _assert(_pick(token_rules, "동시 consume"))


@pytest.mark.fn("F-DOC-011")
def test_g18_mapping_changed_after_issue_and_no_secret(token_rules):
    _assert(_pick(token_rules, "발급 뒤 매핑", "비밀 없음"))


@pytest.mark.fn("F-DOC-011")
def test_g18_token_only_in_hidden_field_never_in_url(http_rows):
    """토큰 평문은 HTML hidden 1곳뿐(헤더 · 주소 · 쿠키 · JSON · DB 전 표 · 로그 0) · GET 은 발급하지 않는다 · 폼은 POST."""
    _assert(_pick(http_rows, "hidden 1곳", "주소창"))


@pytest.mark.fn("F-DOC-011")
@pytest.mark.fn("F-SYS-013")
def test_g18_inactive_user_refused_right_after_sys010(http_rows):
    _assert(_pick(http_rows, "비활성(SYS-010"))


@pytest.mark.fn("F-DOC-011")
@pytest.mark.fn("F-DOC-012")
def test_g18_unmapped_and_unconfigured_are_422(http_rows):
    """미매핑 · 사용 중지 매핑 → 422 「관리자에게 계정 연결을 요청하세요」 · 주소/비밀 없음 → 422 「미확정 (D-517)」 · 지금 .env 화면."""
    _assert(_pick(http_rows, "미매핑", "주소 없음", "지금 설정"))


@pytest.mark.fn("F-DOC-011")
@pytest.mark.fn("F-SYS-041")
def test_g18_sso_log_every_call_and_sys040(http_rows):
    _assert(_pick(http_rows, "SSO 로그", "SYS-040"))


@pytest.mark.fn("F-DOC-011")
def test_g18_server_log_has_no_token(lab):
    _assert(cs.check_sso_server_log(lab))


@pytest.mark.fn("F-DOC-021")
@pytest.mark.fn("F-DOC-022")
def test_g18_doc020_one_to_one_422(doc_map):
    _assert(_pick(doc_map, "1:1"))


@pytest.mark.fn("F-DOC-021")
def test_x12_doc020_bulk_bad_files_are_422(doc_map):
    """이상 파일(빈 · 엑셀 아님 · 5MB 초과 · 헤더 결함 · 깨진 시트 XML · 5001행) → 422 · 500 0 · 등록 0."""
    _assert(_pick(doc_map, "이상 파일"))


@pytest.mark.fn("F-DOC-021")
@pytest.mark.fn("F-DOC-024")
def test_x12_doc020_bulk_one_bad_row_rejects_all(doc_map):
    _assert(_pick(doc_map, "오류 행 하나"))


@pytest.mark.fn("F-DOC-011")
@pytest.mark.fn("F-DOC-021")
@pytest.mark.fn("F-DOC-022")
@pytest.mark.fn("F-DOC-023")
@pytest.mark.fn("F-DOC-024")
def test_g19_g20_g22_doc_access_sessions_change_log(lab):
    _assert(cs.check_doc_access(lab))


def test_x11_d524_app_role_least_privilege(db_role):
    """DEF-QA3-003 재검증 — 한 트랜잭션 안에서 roles.apply → set local role: 불변 4 표 UPDATE/DELETE/TRUNCATE 거부 · replica 거부 · DDL 거부 ·
    업무 쓰기 · 시퀀스 · 뷰 읽기 · 읽기 전용 트랜잭션은 돈다 → 되돌림 → 역할 0."""
    _assert(db_role)


def test_x11_d524_static_and_compose():
    _assert(cs.check_db_role_static())
