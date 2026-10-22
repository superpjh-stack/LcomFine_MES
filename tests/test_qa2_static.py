# tests/test_qa2_static.py — QA2 G-05 쓰기 경계(정적) · tools/check_data.py 의 정적 스캔을 그대로 부른다. DB 를 쓰지 않는다.
# 기대값은 contracts/function-list.md 「쓰는 테이블」 열 + contracts/db-schema.md §2.2 예외 표(「이 표가 전부다」)에서 읽는다.
import pytest

from tools import check_data as cd


@pytest.fixture(scope="module")
def static_report() -> cd.Report:
    r = cd.Report()
    cd.static_scan(r)
    cd.static_col(r)        # G-12 · G-13 정적 — 앱 라우트 표를 읽는다(DB 는 쓰지 않는다)
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


# ── W2 — COL · erp_upload ───────────────────────────────────────────────────
@pytest.mark.fn("F-COL-011")
@pytest.mark.fn("F-COL-031")
@pytest.mark.fn("F-COL-032")
@pytest.mark.fn("F-COL-033")
def test_g05_col_router_and_erp_upload_write_within_contract(static_report):
    """col.py 의 직접 쓰기 + erp_upload.py(apply · remap · save_column_map) 의 쓰기 ⊆ function-list F-COL 「쓰는 테이블」 ∪ notification · sys_number_seq.
    erp_upload 의 쓰기 함수를 부르는 라우터는 col.py 만 · 다른 라우터는 erp_* 테이블에 쓰지 않는다."""
    _all_pass(_rows(static_report, "G-05", "COL 라우터 · erp_upload.py 쓰기"))


@pytest.mark.fn("F-COL-011")
@pytest.mark.fn("F-COL-031")
@pytest.mark.fn("F-COL-032")
@pytest.mark.fn("F-COL-033")
def test_g12_col_posts_are_upload_and_mapping_only(static_report):
    """앱 라우트 표의 /col/* POST = 업로드 1 + 매핑 3(function-list) — 수금 금액을 받는 폼 칸 · 수정 엔드포인트가 없다(정본 「MES 는 수금 데이터를 고치지 않는다」)."""
    _all_pass(_rows(static_report, "G-12", "col.py 의 POST"))


@pytest.mark.fn("F-COL-011")
@pytest.mark.fn("F-COL-031")
def test_g13_erp_upload_row_updates_only_parsed_and_error(static_report):
    """앱 전체에서 erp_upload_row 의 update 는 parsed · error(재해석) 만, erp_upload_batch 는 status · replaced_by · error_count 만. raw · 기간 · 행 수 불변 · 회차 삭제 0."""
    _all_pass(_rows(static_report, "G-13", "erp_upload_row 쓰기"))


# ── W4 — DOC 문서관리 · sso.py ──────────────────────────────────────────────
@pytest.mark.fn("F-DOC-011")
@pytest.mark.fn("F-DOC-021")
@pytest.mark.fn("F-DOC-022")
@pytest.mark.fn("F-DOC-023")
def test_g05_doc_router_and_sso_write_within_contract(static_report):
    """doc.py POST 4 의 쓰기(같은 파일 안 호출 · sso.issue/consume · audit 를 따라가며) ⊆ 그 기능의 「쓰는 테이블」 ∪ 알림 · 로그.
    F-DOC-011 = sso_token + sys_access_log(§2.2 예외 줄) · F-DOC-021~023 = doc_account_map · GET 핸들러 쓰기 0 · 동적 쓰기 0 ·
    doc.py · sso.py 밖의 app 모듈은 doc_account_map · sso_token 에 쓰지 않고 sso 쓰기 함수를 부르지 않는다."""
    _all_pass(_rows(static_report, "G-05", "DOC 라우터 · sso.py 쓰기"))
    # 두 번째 독립 확인 — 계약 글자와 파일 글자를 이 테스트가 직접 읽는다(check_data 의 함수 단위 해석을 거치지 않는다)
    fl = (cd.ROOT / "contracts/function-list.md").read_text(encoding="utf-8")
    assert "| F-DOC-011 |" in fl and "| sso_token, sys_access_log |" in fl.split("| F-DOC-011 |", 1)[1].split("\n", 1)[0]
    for fid in ("F-DOC-021", "F-DOC-022", "F-DOC-023"):
        assert "| doc_account_map |" in fl.split(f"| {fid} |", 1)[1].split("\n", 1)[0], fid
    sso_w = set(cd._sql_writes((cd.APP / "sso.py").read_text(encoding="utf-8")))
    doc_w = set(cd._sql_writes((cd.ROUTERS / "doc.py").read_text(encoding="utf-8")))
    assert sso_w == {"sso_token"}, sso_w
    assert doc_w == {"doc_account_map"}, doc_w
    for p in cd.APP.rglob("*.py"):
        if p.name in ("doc.py", "sso.py"):
            continue
        t = p.read_text(encoding="utf-8")
        assert not set(cd._sql_writes(t)) & cd.DOC_TABLES, p
        assert "sso.issue(" not in t and "sso.consume(" not in t, p
