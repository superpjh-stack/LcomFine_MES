# tests/test_qa2_col.py — QA2 W2 수금: G-11 `erp_upload_error` · G-12 회차 교체 · G-13 오류 행 · 미매핑 · G-14 출하 대비 수금.
#
# - tools/check_data.py 의 흐름 중 기준정보(BAS) → E2E(의뢰 → 출하 확정) → 수금(collections) 만 한 번 돌리고 그 실측 위에서 판정한다.
#   업로드는 **HTTP 만**(COL-010 `POST /col/uploads` multipart · openpyxl 로 만든 (예시) xlsx · 계정 ac) · 매핑은 COL-030 POST · 조회는 화면 GET.
# - 회차 교체 · 반영 제외 · 출하 대비 수금은 check_data 의 독립 SQL 과 **이 파일의 두 번째 독립 SQL**(date_trunc · 테이블 직접) 로 다시 센다.
# - 만든 행은 접두 `QA2-` 로 구분하고 모듈이 끝나면 지운다(ERP 회차 · 행 · 알림 · 거래처 매핑 · 거래처 2 — 열 매핑은 바꿨을 때만 되돌린다).
from decimal import Decimal

import pytest

from lcomfine.app import erp_upload
from tools import check_data as cd


@pytest.fixture(scope="module")
def flow():
    """기준정보 → E2E → 수금 단계만 돈다(추적 · 차단 · 할당 · 알림 · diff 는 tests/test_qa2_flow.py)."""
    report = cd.Report()
    f = cd.Flow(report)
    f.run(keep=True, only={"base", "e2e", "collections"})
    try:
        yield f
    finally:
        note = f.cleanup()
        assert note.startswith("정리 완료"), note


def _rows(f: cd.Flow, gate: str, prefix: str) -> list[cd.Check]:
    rows = [c for c in f.r.checks if c.gate == gate and c.item.startswith(prefix)]
    assert rows, f"{gate} {prefix!r} 검사 행이 없다 — 앞 단계 실패: " + "; ".join(
        f"{c.item}: {c.measured}" for c in f.r.checks if c.status == cd.FAIL)
    return rows


def _all_pass(rows: list[cd.Check]) -> None:
    bad = [f"{c.gate}  {c.item}  {c.status}  {c.measured}" for c in rows if c.status != cd.PASS]
    assert not bad, "\n".join(bad)


# ── G-11 erp_upload_error ────────────────────────────────────────────────────
@pytest.mark.fn("F-COL-011")
def test_g11_erp_upload_error_one_row_for_ac_dedupe_and_closed_by_replacement(flow):
    """오류 · 미매핑 행이 있는 회차마다 AC 1행(D-511) · 같은 키 재발생 새 행 0(D-522) · 같은 기간 재업로드(교체)가 이전 회차 알림을 닫는다."""
    _all_pass(_rows(flow, "G-11", "erp_upload_error"))
    links = [erp_upload.error_link(b) for b in flow.erp_batches]
    rows = flow.q("select to_role, count(*) as n from notification where event_key = 'erp_upload_error' and link = any(%s) group by to_role",
                  (links,))
    # 이 흐름의 회차 3(1회차 · 2회차 · 기간 Q) 전부 업로드 시점에 오류가 있었다 → 회차마다 AC 1행 · 다른 부서 0
    assert {r["to_role"] for r in rows} == {"AC"}, rows
    assert rows[0]["n"] == 3 == len(flow.erp_batches), rows


@pytest.mark.fn("F-COL-031")
def test_g11_erp_upload_error_closed_when_remap_clears_errors(flow):
    """매핑 등록 → 반영 회차 재해석 → 오류 0 이 된 회차의 알림은 같은 트랜잭션에서 닫힌다(D-802)."""
    _all_pass(_rows(flow, "G-11", "erp_upload_error — 매핑 뒤"))


# ── G-12 회차 교체 ───────────────────────────────────────────────────────────
@pytest.mark.fn("F-COL-011")
@pytest.mark.fn("F-COL-021")
def test_g12_reupload_replaces_previous_batch_and_keeps_its_rows(flow):
    """같은 기준 기간 재업로드 = 새 회차 `반영` · 이전 회차 `교체` + replaced_by · 이전 행 보존 · 기간마다 반영 하나 · COL-020 구분."""
    _all_pass(_rows(flow, "G-12", "같은 기간 재업로드"))
    _all_pass(_rows(flow, "G-12", "기간마다 반영 하나"))
    _all_pass(_rows(flow, "G-12", "COL-020 이력"))
    # 독립 SQL — 기간 P 의 회차: 상태 [교체, 반영] · 교체 ⇔ replaced_by · 저장된 행 수 = row_count(지우지 않았다)
    bs = flow.q("""select b.id, b.status, b.replaced_by, b.row_count, b.round_no,
                          (select count(*) from erp_upload_row u where u.batch_id = b.id) as stored
                     from erp_upload_batch b where b.period_from = %s and b.period_to = %s order by b.round_no""", flow.v["P"])
    assert [b["status"] for b in bs] == ["교체", "반영"] and [b["round_no"] for b in bs] == [1, 2], bs
    assert bs[0]["replaced_by"] == bs[1]["id"] and bs[1]["replaced_by"] is None, bs
    assert all(b["stored"] == b["row_count"] for b in bs) and bs[0]["stored"] == 4 and bs[1]["stored"] == 6, bs
    live = flow.q1("select count(*) as n from erp_upload_batch where status = '반영' and period_from = %s and period_to = %s", flow.v["P"])["n"]
    assert live == 1


# ── G-13 오류 행 · 미매핑 ────────────────────────────────────────────────────
@pytest.mark.fn("F-COL-011")
@pytest.mark.fn("F-COL-021")
@pytest.mark.fn("F-COL-041")
@pytest.mark.fn("F-COL-051")
def test_g13_error_rows_kept_with_reason_and_excluded_from_live_views(flow):
    """날짜 · 금액 · 필수 · 미매핑 행은 error 사유 · 원문(raw)과 함께 보존되고 뷰 · COL-040 · COL-050 에서 빠진다. COL-020 ?batch= 에는 보인다."""
    _all_pass(_rows(flow, "G-13", "오류 행 보존"))
    _all_pass(_rows(flow, "G-13", "오류 행 · 미매핑 행은 반영에서 제외"))
    _all_pass(_rows(flow, "G-13", "COL-020 회차별 오류 행 보기"))
    # 독립 SQL — 이 흐름의 회차마다: 뷰 행 = (반영이면) error 없는 행 수, (교체면) 0
    for b in flow.q("select id, batch_no, status, error_count, row_count from erp_upload_batch where id = any(%s)", (flow.erp_batches,)):
        clean = flow.q1("select count(*) as n from erp_upload_row where batch_id = %s and error is null", (b["id"],))["n"]
        in_view = flow.q1("select count(*) as n from v_dq_collections where batch_no = %s", (b["batch_no"],))["n"]
        assert in_view == (clean if b["status"] == "반영" else 0), (b, clean, in_view)
        assert b["error_count"] == b["row_count"] - clean, b


@pytest.mark.fn("F-COL-031")
@pytest.mark.fn("F-COL-034")
def test_g13_unmapped_list_then_remap_only_live_batch(flow):
    """미매핑 코드는 COL-030 목록에 쌓이고, 매핑하면 반영 회차의 그 코드 행만 재해석(error is null) — 교체 회차는 이력이라 그대로."""
    _all_pass(_rows(flow, "G-13", "COL-030 미매핑 목록"))
    info = flow.v["col070"]
    # 독립 SQL — 반영 회차의 parsed.customer_code 중 사용 중 매핑 없는 QA2 코드 = {U} 만 (E · E2 는 매핑됨)
    left = {r["code"] for r in flow.q(
        """select distinct u.parsed ->> 'customer_code' as code
             from erp_upload_row u join erp_upload_batch b on b.id = u.batch_id and b.status = '반영'
            where u.batch_id = any(%s) and coalesce(u.parsed ->> 'customer_code', '') like %s
              and not exists (select 1 from erp_customer_map m where m.erp_code = u.parsed ->> 'customer_code' and m.use_yn = 'Y')""",
        (flow.erp_batches, f"{flow.tag}%"))}
    assert left == {info["U"]}, left
    assert erp_upload.column_map(), "열 매핑이 비어 있다"


# ── G-14 출하 대비 수금 ──────────────────────────────────────────────────────
@pytest.mark.fn("F-COL-071")
def test_g14_col070_equals_independent_recalculation(flow):
    """COL-070 화면의 (월, 거래처) 값 = 이 파일의 독립 SQL(확정 출하 confirmed_at 월 × 반영 · 오류 없음 · 사용 중 매핑 행의 txn_date 월).
    출하만 있는 거래처는 MES 쪽만 · ERP 만 있는 거래처는 ERP 쪽만 · 미매핑 코드는 어디에도 없다 · 건 단위 짝짓기 없음."""
    _all_pass(_rows(flow, "G-14", ""))
    info = flow.v["col070"]
    ym = info["ym"]
    for cid in (info["C1"], info["C2"]):
        ship = flow.q1("""select count(distinct o.id) as n, sum(l.qty) as q
                            from shipment_order o join shipment_line l on l.shipment_order_id = o.id
                           where o.status = '확정' and o.customer_id = %s
                             and date_trunc('month', o.confirmed_at) = date_trunc('month', to_date(%s, 'YYYY-MM'))""", (cid, ym))
        erp = flow.q1("""select count(*) as n, sum((u.parsed ->> 'sales_amount')::numeric) as s, sum((u.parsed ->> 'collected_amount')::numeric) as c
                           from erp_upload_row u
                           join erp_upload_batch b on b.id = u.batch_id and b.status = '반영'
                           join erp_customer_map m on m.erp_code = u.parsed ->> 'customer_code' and m.use_yn = 'Y' and m.customer_id = %s
                          where u.error is null
                            and date_trunc('month', (u.parsed ->> 'txn_date')::date) = date_trunc('month', to_date(%s, 'YYYY-MM'))""", (cid, ym))
        mine = (ship["n"] or None, ship["q"] if ship["n"] else None, erp["s"] if erp["n"] else None, erp["c"] if erp["n"] else None)
        assert info["screen"][cid] == mine == info["indep"][cid], (cid, info["screen"][cid], mine, info["indep"][cid])
    assert info["screen"][info["C1"]][:2] == (1, Decimal("60.000")) and info["screen"][info["C2"]][:2] == (None, None)
    assert info["screen"][info["C1"]][2:] == (Decimal(1000), Decimal(300)) and info["screen"][info["C2"]][2:] == (Decimal(500), Decimal(200))
    assert flow.q1("select count(*) as n from v_dq_collections where erp_customer_code = %s", (info["U"],))["n"] == 0


# ── 정리 확인 — 이 모듈이 만든 ERP 행이 남지 않는다 ───────────────────────────
def test_zz_previous_runs_left_no_erp_rows():
    """직전 실행들의 QA2 접두 ERP 행이 없음을 본다(이번 실행 분은 모듈 픽스처의 finally 가 지운다 — 1분 전보다 오래된 행만 센다)."""
    from lcomfine.db import conn

    left = conn.q1(
        """select (select count(*) from erp_upload_batch where source_file like 'QA2-%%' and created_at < now() - interval '1 minute')
                + (select count(*) from erp_customer_map where erp_code like 'QA2-%%' and created_at < now() - interval '1 minute') as n""")["n"]
    assert left == 0, f"직전 실행의 QA2 ERP 행 {left}"
