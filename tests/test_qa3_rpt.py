# tests/test_qa3_rpt.py — QA3 W3 대시보드 · 데이터 질의(RPT): G-16 질의 검증 우회 · G-17 키 없음 · G-19 RPT 9 × 부서 8 · G-20 · G-22 변경 로그 · X-09 · X-10.
# tools/check_security.py 의 검사를 그대로 부른다. **실제 OpenAI 는 부르지 않는다** — `ai.set_client(fake)` 주입 + `no_real_ai()` 가 urlopen 을 막는다 ·
# 키 없음은 `ai._config` 비움(프로세스 안)과 `LCOMFINE_OPENAI_API_KEY=` 빈 값의 하위 프로세스로 잰다. 키 값은 어디에도 찍지 않는다.
# 임시 계정(접두 q3…) · 임시 거래처 · 의뢰만 쓰고 끝나면 지운다(임시 계정의 data_query_log · sys_ai_call_log 행도 — sys_user FK).
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
def bypass(lab):
    return cs.check_dataquery_bypass(lab)


@pytest.fixture(scope="module")
def keyless(lab):
    return cs.check_ai_key_missing(lab)


@pytest.mark.fn("F-RPT-132")
def test_g16_bypass_sql_is_rejected_not_executed_and_logged(bypass):
    """G-16 — 쓰기 · 다중 문장 · 주석 · 허용 밖 뷰/테이블 · 카탈로그 · 함수 · CTE · into · for update · copy · set · \\ · 유니코드 공백 · 대소문자 · 큰따옴표 ·
    스키마 한정 → 전부 422 「허용되지 않는 질의 — 이유」 · 실행 0(내 행 불변 · pg_sleep 안 돎) · 거부도 data_query_log 1행."""
    _assert(_pick(bypass, "우회 SQL"))


@pytest.mark.fn("F-RPT-132")
def test_g16_allowed_query_runs_and_logs_once(bypass):
    _assert(_pick(bypass, "허용 질의"))


@pytest.mark.fn("F-RPT-132")
def test_g16_row_limit_statement_timeout_and_readonly_execution(bypass):
    _assert(_pick(bypass, "행 상한", "실행 계층"))


@pytest.mark.fn("F-RPT-132")
def test_g16_collection_views_are_department_restricted(bypass):
    """D-513 — 전략부는 수금 뷰 422(부서 사유) · RPT-130 칸 없는 부서는 403(AI 호출 0) · 경영진 · 전산 관리자 200."""
    _assert(_pick(bypass, "수금 뷰 부서 제한"))


@pytest.mark.fn("F-RPT-131")
@pytest.mark.fn("F-RPT-132")
def test_g16_question_nul_huge_and_script_are_safe(bypass):
    _assert(_pick(bypass, "질문 NUL"))


@pytest.mark.fn("F-SYS-041")
def test_g16_rejected_queries_visible_in_sys_logs(bypass):
    _assert(_pick(bypass, "SYS-040"))


@pytest.mark.fn("F-RPT-132")
def test_g17_missing_key_is_explicit_in_process_and_subprocess(keyless):
    """G-17 — 422 「AI 키가 설정되지 않았습니다 — LCOMFINE_OPENAI_API_KEY」 가 화면에 그대로 · sys_ai_call_log · data_query_log 1행(ok false) · 다른 쓰기 0."""
    _assert(_pick(keyless, "키 없음(프로세스 안", "키 없음(하위 프로세스"))


@pytest.mark.fn("F-RPT-132")
def test_g17_call_failure_is_422_and_logged(keyless):
    _assert(_pick(keyless, "호출 실패"))


@pytest.mark.fn("F-RPT-132")
def test_g17_key_value_never_in_logs_or_messages(keyless):
    """G-21 · G-17 — 키 글자는 sys_ai_call_log · data_query_log · 422 본문 어디에도 없다(가짜 키로 잰다 · 실제 키는 DB 에 없는지만 센다)."""
    _assert(_pick(keyless, "키 값이 로그"))


def test_g17_static_no_hardcoded_result(keyless):
    _assert(_pick(keyless, "정적: 하드코딩"))


@pytest.mark.fn("F-RPT-011")
@pytest.mark.fn("F-RPT-021")
@pytest.mark.fn("F-RPT-031")
@pytest.mark.fn("F-RPT-041")
@pytest.mark.fn("F-RPT-051")
@pytest.mark.fn("F-RPT-061")
@pytest.mark.fn("F-RPT-071")
@pytest.mark.fn("F-RPT-081")
@pytest.mark.fn("F-RPT-131")
@pytest.mark.fn("F-RPT-132")
@pytest.mark.fn("F-SYS-013")
def test_g19_g20_rpt_screens_and_query_by_department(lab):
    _assert(cs.check_rpt_access(lab))


def test_g19_permission_exception_expectation_is_the_screen_cell(lab):
    """progress-dev3 §3-12 — 권한 예외 기능(F-RPT-132)은 「칸이 없으면 403 · R 이면 통과」(api-contract §4). 전수 403 검사가 이 기대값으로 PASS 한다."""
    _assert(cs.check_write_403(lab))


@pytest.mark.fn("F-RPT-132")
@pytest.mark.fn("F-SYS-041")
def test_g22_query_change_log_once_and_dashboards_access_log(lab):
    _assert(cs.check_rpt_change_log(lab))


@pytest.mark.fn("F-RPT-011")
@pytest.mark.fn("F-RPT-051")
def test_dashboard_escapes_customer_name_and_writes_nothing(lab):
    _assert(cs.check_rpt_escape(lab))


def test_dashboard_and_rpt_router_have_no_write_sql():
    _assert(cs.check_rpt_static())


def test_db_down_rpt_screen_and_query_are_503(lab):
    _assert([r for r in cs.check_db_down(lab) if "RPT" in r.item])
