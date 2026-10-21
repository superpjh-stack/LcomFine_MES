# tests/test_qa2_static.py — QA2 G-05 쓰기 경계(정적) · tools/check_data.py 의 정적 스캔을 그대로 부른다. DB 를 쓰지 않는다.
# 기대값은 contracts/function-list.md 「쓰는 테이블」 열 + contracts/db-schema.md §2.2 예외 표(「이 표가 전부다」)에서 읽는다.
import pytest

from tools import check_data as cd


@pytest.fixture(scope="module")
def static_report() -> cd.Report:
    r = cd.Report()
    cd.static_scan(r)
    return r


def _rows(report: cd.Report, gate: str, prefix: str) -> list[cd.Check]:
    rows = [c for c in report.checks if c.gate == gate and c.item.startswith(prefix)]
    assert rows, f"{gate} {prefix!r} 검사 행이 없다"
    return rows


def _all_pass(rows: list[cd.Check]) -> None:
    bad = [f"{c.gate}  {c.item}  {c.status}  {c.measured}" for c in rows if c.status != cd.PASS]
    assert not bad, "\n".join(bad)


def test_g05_router_writes_within_contract(static_report):
    """라우터 14 의 insert/update/delete 테이블 ⊆ function-list 「쓰는 테이블」 ∪ notification · 로그 ∪ §2.2 가 허용한 공용 모듈 쓰기."""
    _all_pass(_rows(static_report, "G-05", "쓰기 경계 — 라우터 정적 스캔"))


def test_g05_helper_writes_are_all_in_schema_2_2(static_report):
    """공용 모듈(numbering → sys_number_seq · auth → sys_user · notify · audit)의 쓰기는 db-schema §2.2 에 전부 있어야 한다."""
    rows = _rows(static_report, "G-05", "쓰기 경계 — 공용 모듈의 계약 밖 쓰기")
    _all_pass(rows)
    exc = cd.schema_exceptions()
    for t in ("sys_number_seq", "sys_user", "notification", "sys_change_log", "sys_access_log"):
        assert t in exc, f"db-schema §2.2 에 `{t}` 가 없다"


@pytest.mark.fn("F-QC-011")
@pytest.mark.fn("F-QC-021")
@pytest.mark.fn("F-SHP-011")
@pytest.mark.fn("F-SHP-012")
@pytest.mark.fn("F-SHP-021")
def test_g05_lot_stock_exception_columns(static_report):
    """§2.2 예외 줄의 컬럼 — QC 는 lot_stock.status 만, SHP 지시 · 수정은 allocated_qty 만, 확정은 qty · allocated_qty 만."""
    _all_pass(_rows(static_report, "G-05", "예외 줄의 lot_stock 컬럼"))


@pytest.mark.fn("F-LOT-011")
@pytest.mark.fn("F-LOT-021")
def test_g05_readonly_modules_have_no_write_sql(static_report):
    """TRK · LOT · PRP 라우터와 trace.py · stats.py 는 쓰기 SQL · conn.x · conn.tx · notify.emit · numbering.next 가 0."""
    _all_pass(_rows(static_report, "G-05", "TRK · LOT · PRP · trace · stats 쓰기 0"))
