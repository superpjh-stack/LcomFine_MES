# tests/test_qa1_col.py — QA1 W2 수금(COL 7 화면 · 기능 11) + TRK-020 `?period=` + TRK-030 수금 칸 + HOME 회계부 카드.
# tools/check_screens.py 의 W2 몫을 그대로 돈다: QA1 세계(접두 `QA1-…-` · 거래처 · (예시) xlsx → `POST /col/uploads` 회차 2 · 거래처 매핑)를
# 화면이 부르는 HTTP 로 만들고, COL 쓰기 4 의 오류 계약 사례(파일 없음 · 엑셀 아닌 파일 · 20MB 초과 · 기준 기간 역순 · 날짜 형식 · 매핑 없는 열 ·
# 데이터 행 0 · NUL · 중복 · 없는 거래처 · 없는 경로 키)와 정본 L3 · logic 문장(오류 행 빨간색 · 처음 한 번 저장 · 미매핑 목록 · 교체됨 · 어음 만기 ·
# 30/60/90 · 출하 대비 나란히 · 미확정 (D-516))을 확인한 뒤 자기 회차 · 매핑만 지운다. 열 매핑을 바꾸면(D-516 확인) 같은 함수 안에서 되돌린다.
# 기대값은 계약(function-list.md · api-contract.md · ia.json · decisions.md D-516 · D-608 · D-802~D-804)에서 끌어온다. 고치지 않는다.
import pytest

from tools import check_screens as cs

COL_WRITES = ("F-COL-011", "F-COL-031", "F-COL-032", "F-COL-033")


@pytest.fixture(scope="module")
def lab():
    app, clients = cs.app_and_clients()
    w = cs.World(clients)
    try:
        w.build()
        assert not w.failed_steps(), "QA1 세계 만들기 실패:\n" + "\n".join(w.failed_steps())
        assert w.ids.get("batch1") and w.ids.get("batch2") and w.ids.get("map"), f"COL 세계가 없다 — {w.ids}"
        results = cs.run_cases(w, [c for c in cs.cases(w) if c.fid.startswith("F-COL-")])
        rep = cs.Report()
        contract = cs.check_col_contract(w, rep)        # 매핑 삭제 · 사용 중지까지 — 사례 뒤에 돈다
        yield {"world": w, "clients": clients, "results": results, "contract": contract, "rep": rep}
    finally:
        w.cleanup()
    assert not w.leftovers(), f"정리 후 남은 QA1 행 {w.leftovers()}"


def _fmt(x: dict) -> str:
    return f"{x['fid']} {x['label']} — [{x['login']}] POST {x['path']} → {x['status']} {x['message']!r} {x['why']}".strip()


def _bad(results, pred) -> list[str]:
    return [_fmt(x) for x in results if pred(x) and not x["ok"]]


def _items(contract, *keys) -> list[dict]:
    out = [x for x in contract if any(k in x["item"] for k in keys)]
    assert out, f"계약 문장 항목이 없다 — {keys}"
    return out


def _assert_items(contract, *keys) -> None:
    bad = [f"{x['item']} — {x['actual']}" for x in _items(contract, *keys) if not x["ok"]]
    assert not bad, "\n".join(bad)


# ── 오류 계약 (api-contract §1 · §3) ─────────────────────────────────────────

@pytest.mark.fn("F-COL-011")
def test_upload_input_errors_are_422_with_field_names(lab):
    """F-COL-011 `POST /col/uploads`: 파일 없음 · 기준 기간 누락 · 엑셀 아닌 파일 · 빈 파일 · 20MB 초과 · 기준 기간 역순 · 날짜 형식 · 매핑된 열이
    파일에 없음 · 데이터 행 0 · 모르는 동작 · 열 매핑 NUL · 열 매핑 필수 누락 → 422 `validation_error` + 항목을 짚는 fields (500 0)."""
    res = lab["results"]
    pred = lambda x: x["fid"] == "F-COL-011" and x["expect"] == 422  # noqa: E731
    n = sum(1 for x in res if pred(x))
    assert n >= 12, f"사례가 {n} 뿐이다 (기대 ≥ 12)"
    assert not _bad(res, pred), "\n".join(_bad(res, pred))
    generic = [_fmt(x) for x in res if pred(x) and x["generic_db_422"]]
    assert not generic, "항목을 짚지 않는 422:\n" + "\n".join(generic)


@pytest.mark.fn("F-COL-011", "F-COL-012")
def test_upload_preview_writes_nothing(lab):
    """F-COL-011 action=preview → 200 `applied false` · 회차 · 행 · 알림 수 불변 (D-802 「preview 검증만 — 아무것도 쓰지 않는다」)."""
    res = lab["results"]
    pred = lambda x: x["fid"] == "F-COL-011" and x["expect"] == 200  # noqa: E731
    assert sum(1 for x in res if pred(x)) >= 1
    assert not _bad(res, pred), "\n".join(_bad(res, pred))
    _assert_items(lab["contract"], "검증 미리보기")


@pytest.mark.fn("F-COL-031", "F-COL-032", "F-COL-033")
def test_customer_map_errors_422_and_path_key_404(lab):
    """F-COL-031 누락 · NUL · 코드 중복 · 없는 거래처(본문) · 거래처 값 틀림 → 422 / F-COL-032 누락 · 사용 여부 · NUL · 없는 거래처 → 422 ·
    없는 경로 키 · 숫자 아닌 키 → 404 / F-COL-033 없는 경로 키 → 404 (api-contract §1 「422 와 404 의 경계」)."""
    res = lab["results"]
    pred = lambda x: x["fid"] in ("F-COL-031", "F-COL-032", "F-COL-033")  # noqa: E731
    assert sum(1 for x in res if pred(x) and x["expect"] == 422) >= 9
    assert sum(1 for x in res if pred(x) and x["expect"] == 404) >= 4
    assert not _bad(res, pred), "\n".join(_bad(res, pred))
    generic = [_fmt(x) for x in res if pred(x) and x["generic_db_422"]]
    assert not generic, "항목을 짚지 않는 422:\n" + "\n".join(generic)


def test_no_col_case_returns_500(lab):
    """COL 사례 어디서도 5xx 가 나오지 않는다 — 입력값 오류는 500 이 아니다 (goal §2.7 · api-contract §3)."""
    s500 = [_fmt(x) for x in lab["results"] if cs.server_error(x["status"])]
    assert not s500, "\n".join(s500)


# ── 계약 문장 (정본 L3 · logic · D-516 · D-608 · D-802 · D-803) ─────────────────

@pytest.mark.fn("F-COL-011", "F-COL-021")
def test_reupload_replaces_round_and_keeps_history(lab):
    """같은 기준 기간 재업로드 → 새 회차 반영(round 2) · 이전 회차 `교체`(replaced_by · 행 보존) · 오류 행 `일자: …` · `거래처 코드 미매핑: <코드>` ·
    2회차는 열 매핑 동작 없이 올라간다(「처음 한 번 저장, 다음부터 자동」) · COL-020 이 반영/교체됨을 구분한다."""
    _assert_items(lab["contract"], "회차 교체", "오류 행 — 미매핑", "처음 한 번 저장", "COL-020")


@pytest.mark.fn("F-COL-011")
def test_erp_upload_error_alert_closes_when_batch_replaced(lab):
    """D-802 「닫힘 = 그 기간을 다시 올려 교체되거나 …」 — 교체된 회차의 `erp_upload_error`(→ 회계부) 알림은 닫히고 새 회차 알림 AC 1행만 미처리.
    업로더가 전산 관리자(COL-010 W)일 때도 같아야 한다 — DEF-QA1-006."""
    _assert_items(lab["contract"], "알림 erp_upload_error")


@pytest.mark.fn("F-COL-012")
def test_col_010_error_rows_red_and_undecided(lab):
    """COL-010: 오류 행은 빨간색(`class=\"is-error\"`) · 열 구성 `미확정 (D-516)` · 미매핑 코드가 보인다."""
    _assert_items(lab["contract"], "COL-010 — 오류 행 빨간색")


@pytest.mark.fn("F-COL-034", "F-COL-031", "F-COL-032", "F-COL-033")
def test_col_030_unmapped_list_remap_disable_delete(lab):
    """COL-030: 처음 보는 ERP 코드가 미매핑 목록에 쌓인다 → 매핑 등록하면 반영 회차의 그 행이 다시 반영(교체 회차는 그대로) · 사용 중지 → 미매핑 목록에 다시 ·
    삭제는 참조가 있으면 사용 중지, 없으면 삭제 (정본 logic · F-COL-033)."""
    _assert_items(lab["contract"], "COL-030")


@pytest.mark.fn("F-COL-041")
def test_col_040_bill_due_and_xlsx(lab):
    """COL-040: 기간 · 거래처 조건 · 어음은 만기일과 만기 도래 여부(도래 · 예정) · `?format=xlsx` (정본 L3 「엑셀」)."""
    _assert_items(lab["contract"], "COL-040")


@pytest.mark.fn("F-COL-051", "F-COL-061", "F-COL-071")
def test_col_050_060_070_numbers_and_layout(lab):
    """COL-050 매출 1,000 · 수금 400 · 미수 600(Σ매출 − Σ수금 · D-803) · COL-060 구간 0~30 · 31~60 · 61~90 · 90일 초과 · COL-070 MES 출하와
    ERP 매출·수금 나란히(건 단위 짝짓기 없음)."""
    _assert_items(lab["contract"], "COL-050", "COL-060", "COL-070")


@pytest.mark.fn("F-COL-051", "F-COL-061", "F-TRK-031", "F-HOME-011")
def test_sales_column_unmapped_shows_undecided_d516_everywhere(lab):
    """매출액 · 잔액 열 매핑을 지우면 COL-050 · COL-060 · TRK-030(`data-receivable=\"미확정 (D-516)\"`) · HOME 회계부 「90일 초과 미수」 가 `미확정 (D-516)`
    (수금 합은 수치) — D-516 · D-608. 매핑은 되돌아온다."""
    _assert_items(lab["contract"], "매출액 · 잔액 열 매핑 제거")


@pytest.mark.fn("F-TRK-031")
def test_trk_030_receivable_ok_and_empty(lab):
    """TRK-030 수금 칸(D-608): 매핑 · 반영 행이 있으면 status ok · 미수 잔액 · ERP 업로드 기준일(asof) · 매핑이 전부 사용 중지면 「미수집」(0 아님)."""
    _assert_items(lab["contract"], "TRK-030 —")


@pytest.mark.fn("F-TRK-021")
def test_trk_020_period_param(lab):
    """TRK-020 `?period=YYYY-MM` → 200 · data-compliance · data-period · 산식(D-804) / 형식 오류(1980-13 · 1980-1 · abcd-ef · 1980/01 · NUL) → 422."""
    _assert_items(lab["contract"], "TRK-020")


@pytest.mark.fn("F-HOME-011")
def test_home_ac_cards(lab):
    """HOME-010 회계부: 「미매핑 ERP 거래처」 · 「업로드 오류 행」 · 「90일 초과 미수」 카드 · COL-060 링크 (F-HOME-011 · D-608)."""
    _assert_items(lab["contract"], "HOME-010 회계부")


@pytest.mark.fn("F-COL-011")
def test_no_collection_edit_endpoint(lab):
    """정본 「MES 는 수금 데이터를 고치지 않는다」 — col 라우터의 POST 는 업로드 1 · 매핑 3 뿐 (G-13 「MES 화면에 수금 수정 경로 없음」)."""
    _assert_items(lab["contract"], "수정 엔드포인트 없음")
