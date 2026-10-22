# tests/test_qa3_col.py — QA3 W2 수금(COL): G-19 COL 화면 7 · 쓰기 4 × 부서 8 · G-20 COL 세션 · G-22 COL 쓰기 4 변경 로그 · 업로드 보안(X-05~X-08).
# tools/check_security.py 의 검사를 그대로 부른다. 임시 계정(접두 q3…) · 1985년 기준 기간 · 자기 파일 이름 · ERP 코드만 쓰고 끝나면 지운다.
# 열 매핑(erp_column_map)은 바꾸지 않는다 — 지금 매핑의 열 이름으로 (예시) xlsx 를 openpyxl 로 만든다(저장소에 바이너리 없음).
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


@pytest.mark.fn("F-COL-011")
@pytest.mark.fn("F-COL-031")
@pytest.mark.fn("F-COL-032")
@pytest.mark.fn("F-COL-033")
def test_g19_col_screens_and_writes_by_department(lab):
    _assert(cs.check_col_access(lab))


@pytest.mark.fn("F-SYS-013")
def test_g20_col_inactive_and_logged_out_are_401(lab):
    _assert(cs.check_col_sessions(lab))


@pytest.mark.fn("F-COL-011")
@pytest.mark.fn("F-COL-031")
@pytest.mark.fn("F-COL-032")
@pytest.mark.fn("F-COL-033")
@pytest.mark.fn("F-SYS-041")
def test_g22_col_writes_log_once_and_preview_logs_nothing(lab):
    _assert(cs.check_col_change_log(lab))


@pytest.mark.fn("F-COL-011")
def test_upload_rejects_non_xlsx_and_header_defects_without_500(lab):
    """X-05 — 텍스트 · HTML · zip · 0바이트 · PNG · 20MB+1 · 헤더만 · 열 이름 중복 · 빈 1행 · __row_no · 매핑 열 없음 → 422(500 없음)."""
    out = cs.check_col_upload_abuse(lab)
    _assert([r for r in out if r.gid == "X-05"])


@pytest.mark.fn("F-COL-011")
@pytest.mark.fn("F-COL-012")
@pytest.mark.fn("F-COL-021")
@pytest.mark.fn("F-COL-034")
def test_upload_cells_are_stored_as_text_and_escaped_on_screens(lab):
    """X-06 — `=HYPERLINK` · DDE · <script> · 10만 자 · 파일 이름의 경로는 값으로만 저장되고 COL-010/020/030/040 · HOME 에 이스케이프돼 나온다."""
    out = cs.check_col_upload_abuse(lab)
    _assert([r for r in out if r.gid == "X-06"])


@pytest.mark.fn("F-COL-041")
def test_collections_xlsx_export_has_no_live_formula_cells(lab):
    """X-07 (DEF-QA3-004) — COL-040 `?format=xlsx` 가 저장된 `=…` 글자를 수식 셀로 쓰면 여는 사람의 엑셀에서 DDE · HYPERLINK 가 산다."""
    out = cs.check_col_upload_abuse(lab)
    _assert([r for r in out if r.gid == "X-07"])


def test_upload_module_never_writes_to_disk_and_seed_dev3_is_idempotent_by_source():
    _assert(cs.check_col_static())
    _assert(cs.check_seed_dev3_static())


def test_db_down_upload_and_col_screen_are_503(lab):
    _assert([r for r in cs.check_db_down(lab) if "COL" in r.item])
