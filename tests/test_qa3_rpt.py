# tests/test_qa3_rpt.py — QA3 W3 대시보드(RPT): G-19 RPT 8 × 부서 8 · G-20 · G-22 조회 로그 · X-09 · X-10 ·
# G-16 · G-17 의 「제외」 근거(데이터 질의는 D-529 로 없앴다 — 옛 경로 404 · 메뉴 · 기능 · 칸 · 로그 표 · 허용 뷰 · AI 키 환경변수가 없다).
# tools/check_security.py 의 검사를 그대로 부른다. 임시 계정(접두 q3…) · 임시 거래처 · 의뢰만 쓰고 끝나면 지운다.
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
    return [r for r in results if any(n in r.item for n in needles)]


@pytest.fixture(scope="module")
def removed(lab):
    return cs.check_query_removed(lab)


def test_g16_excluded_evidence_old_path_404_for_all_departments(removed):
    """G-16 제외 근거 (D-529) — 옛 데이터 질의 경로 GET · POST 가 부서 8 모두 404."""
    rows = _pick(removed, "옛 데이터 질의 경로")
    assert rows and all(r.gid == "G-16" for r in rows)
    _assert(rows)


def test_g16_excluded_evidence_menu_functions_cells_db(removed):
    """G-16 제외 근거 — nav · 메뉴 · 대시보드 탭에 없음 · 기능 · 권한 칸(계약 · DB) 없음 · 로그 표 · 허용 뷰 · 채번 DQ 없음 · 모듈 파일 없음 · SYS-040 옛 탭 422."""
    rows = _pick(removed, "nav · 메인 메뉴", "기능 · 권한 칸", "DB 에 없음", "모듈 · 템플릿")
    assert len(rows) == 4
    _assert(rows)


def test_g17_excluded_evidence_no_ai_key_or_outbound_call(removed):
    """G-17 제외 근거 — AI 키 환경변수(settings · .env.example · compose 두 벌)와 앱 코드의 바깥 AI 호출이 없다."""
    rows = [r for r in removed if r.gid == "G-17"]
    assert rows
    _assert(rows)


@pytest.mark.fn("F-RPT-011")
@pytest.mark.fn("F-RPT-021")
@pytest.mark.fn("F-RPT-031")
@pytest.mark.fn("F-RPT-041")
@pytest.mark.fn("F-RPT-051")
@pytest.mark.fn("F-RPT-061")
@pytest.mark.fn("F-RPT-071")
@pytest.mark.fn("F-RPT-081")
@pytest.mark.fn("F-SYS-013")
def test_g19_g20_rpt_screens_by_department(lab):
    _assert(cs.check_rpt_access(lab))


def test_g19_permission_exception_expectation_is_the_screen_cell(lab):
    """progress-dev3 §3-12 — 권한 예외 기능(F-DOC-011 · F-HOME-022)은 「칸이 없으면 403 · R 이면 통과」(api-contract §4). 전수 403 검사가 이 기대값으로 PASS 한다."""
    _assert(cs.check_write_403(lab))


@pytest.mark.fn("F-RPT-011")
def test_g22_dashboards_access_log(lab):
    _assert(cs.check_rpt_access_log(lab))


@pytest.mark.fn("F-RPT-011")
@pytest.mark.fn("F-RPT-051")
def test_dashboard_escapes_customer_name_and_writes_nothing(lab):
    _assert(cs.check_rpt_escape(lab))


def test_dashboard_and_rpt_router_have_no_write_sql():
    _assert(cs.check_rpt_static())


def test_db_down_rpt_screen_is_503(lab):
    _assert([r for r in cs.check_db_down(lab) if "RPT" in r.item])
