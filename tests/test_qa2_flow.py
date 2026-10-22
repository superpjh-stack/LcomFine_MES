# tests/test_qa2_flow.py — QA2 G-06 ~ G-11 (+ G-05 동적) · tools/check_data.py 의 흐름을 한 번 돌리고 그 실측 위에서 판정한다.
#
# - E2E 1건은 **HTTP 만**(TestClient · 부서 계정 sl · pr · sh · ds 교대)으로 만든다. DB 는 확인(SELECT)과 끝의 정리에만 쓴다.
# - 역추적 · 정방향 · 가용 · 할당 합은 trace.py · 화면 값과 **이 파일(check_data) 의 독립 SQL** 을 대조한다.
# - 알림 수신 부서의 기대값은 notify.EVENTS 가 아니라 decisions.md D-511 표를 여기 글자로 옮긴 것이다(독립 기대값).
# - 만든 행은 접두 `QA2-` 로 구분하고 모듈이 끝나면 지운다(다른 QA 가 같은 DB 를 함께 쓴다).
from decimal import Decimal

import pytest

from tools import check_data as cd

#: decisions.md D-511 알림 9종 — 이벤트 키 → 수신 부서 (업무 흐름이 내는 8종 · erp_upload_error(AC) 는 tests/test_qa2_col.py)
D511 = {
    "request_created": {"PR", "DS"}, "order_issued": {"PR"}, "material_received": {"PR"}, "product_received": {"PR"},
    "judged": {"SH", "SL"}, "shipment_confirmed": {"SL", "AC"}, "due_d3_unshipped": {"SL", "PR"}, "shipment_ordered": {"SH"},
}


@pytest.fixture(scope="module")
def flow():
    """check_data 의 흐름 전부(기준정보 → E2E → 추적 → 차단 → 할당 → 재판정 → 알림 → 조회 diff → F-SHP-012 취소)를 한 번 돈다."""
    report = cd.Report()
    f = cd.Flow(report)
    f.run(keep=True)
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


# ── G-06 E2E ────────────────────────────────────────────────────────────────
@pytest.mark.fn("F-WO-011")
@pytest.mark.fn("F-WO-012")
@pytest.mark.fn("F-WO-021")
@pytest.mark.fn("F-MAT-011")
@pytest.mark.fn("F-QC-011")
@pytest.mark.fn("F-INV-021")
@pytest.mark.fn("F-MAT-021")
@pytest.mark.fn("F-PRD-011")
@pytest.mark.fn("F-INS-011")
@pytest.mark.fn("F-MAT-031")
@pytest.mark.fn("F-QC-021")
@pytest.mark.fn("F-SHP-011")
@pytest.mark.fn("F-SHP-021")
def test_g06_e2e_http_only_with_department_rotation(flow):
    """의뢰(sl) → 지시(pr) → 입고 → 입고검사 → 분할 → 불출 → 일보 · 검사일보 → 제품 입고 → 판정(pr) → 출하 지시(sl) → 확정(sh)."""
    _all_pass(_rows(flow, "G-06", "E2E 의뢰 → 출하 확정"))
    _all_pass(_rows(flow, "G-06", "의뢰번호로 이어진 행"))
    _all_pass(_rows(flow, "G-06", "WO-040 뷰 수량"))
    e2e_steps = [s for s in flow.r.steps if s.step.startswith(("WO-", "MAT-", "QC-", "INV-020", "PRD-", "INS-", "SHP-"))]
    assert {"sl", "pr", "sh"} <= {s.account for s in e2e_steps}, "부서 계정 교대(sl · pr · sh)가 아니다"
    assert all(str(s.request).startswith(("POST ", "GET ")) for s in e2e_steps), "HTTP 가 아닌 단계가 있다"
    # 의뢰번호 하나로 지시 → 불출 → 제품 입고 → 확정 출하가 이어진다 (독립 SQL)
    chain = flow.q1(
        """select count(distinct w.id) as wo, count(distinct l.id) as issue_lines, count(distinct p.id) as plots,
                  count(distinct o.id) as shipped
             from production_request r join work_order w on w.request_id = r.id
             left join material_issue_line l on l.work_order_id = w.id and l.issue_id = %s
             left join product_lot p on p.work_order_id = w.id
             left join shipment_order o on o.request_id = r.id and o.status = '확정'
            where r.request_no = %s""", (flow.issue_ids[0], flow.v["R1"]))
    # E2E 불출 1건의 행 3(A1 · A1 분할 · A2) — 뒤 단계의 동시 불출(G-10)이 더한 행은 세지 않는다
    assert chain == {"wo": 1, "issue_lines": 3, "plots": 3, "shipped": 1}, chain


# ── G-07 역추적 ─────────────────────────────────────────────────────────────
@pytest.mark.fn("F-LOT-021")
def test_g07_backward_trace_equals_independent_sql(flow):
    from lcomfine.app import trace

    _all_pass(_rows(flow, "G-07", "LOT-020 화면이 원자재 LOT 까지"))
    _all_pass(_rows(flow, "G-07", "trace.backward(출하) = 독립 SQL"))
    _all_pass(_rows(flow, "G-07", "trace.backward(제품 LOT) = 독립 SQL"))
    _all_pass(_rows(flow, "G-07", "DB 의 모든 출하 trace.backward = 독립 SQL"))
    v = flow.v
    bw = trace.backward(shipment_no=v["S1"])
    origin, issued = flow.indep_backward(shipment_no=v["S1"])
    assert set(bw["origin_material_lot_nos"]) == origin == {v["A1"], v["A2"]}
    assert set(bw["issued_material_lot_nos"]) == issued == {v["A1"], v["A1s"], v["A2"]}, "분할 LOT 가 원 LOT 로 이어지지 않는다"


@pytest.mark.fn("F-QC-022")
@pytest.mark.fn("F-LOT-021")
def test_g07_reject_after_shipment_keeps_shipment_and_flags(flow):
    """D-515 3 · D-702 — 확정 뒤 재판정 불합격은 출하를 바꾸지 않고 역추적에 「출하 후 불합격」 표시."""
    _all_pass(_rows(flow, "G-07", "출하 후 불합격"))


# ── G-08 정방향 ─────────────────────────────────────────────────────────────
@pytest.mark.fn("F-LOT-011")
def test_g08_forward_trace_equals_independent_sql(flow):
    from lcomfine.app import trace

    _all_pass(_rows(flow, "G-08", "LOT-010 화면이 출하까지"))
    _all_pass(_rows(flow, "G-08", "trace.forward = 독립 SQL"))
    _all_pass(_rows(flow, "G-08", "DB 의 모든 원 입고 LOT trace.forward = 독립 SQL"))
    v = flow.v
    fw = trace.forward(v["A1"])
    pls, shs = flow.indep_forward(v["A1"])
    assert set(fw["product_lot_nos"]) == pls and v["P1"] in pls
    assert set(fw["shipment_nos"]) == shs and v["S1"] in shs


# ── G-09 차단 ───────────────────────────────────────────────────────────────
@pytest.mark.fn("F-MAT-021")
def test_g09_pending_or_held_lot_issue_is_422(flow):
    _all_pass(_rows(flow, "G-09", "검사대기 · 보류 LOT 불출 422"))
    steps = [s for s in flow.r.steps if s.step.startswith("MAT-020 불출(") and "LOT)" in s.step]
    assert [s.status for s in steps] == [422, 422], [(s.step, s.status) for s in steps]


@pytest.mark.fn("F-SHP-021")
@pytest.mark.fn("F-QC-022")
def test_g09_held_lot_shipment_confirm_is_422(flow):
    _all_pass(_rows(flow, "G-09", "보류(불합격) LOT 출하 확정 422"))
    _all_pass(_rows(flow, "G-09", "출하 뒤 재판정 불합격 LOT 의 남은 지시 확정 422"))


@pytest.mark.fn("F-SHP-011")
@pytest.mark.fn("F-MAT-011")
def test_g09_disabled_item_and_pending_lot_blocked(flow):
    _all_pass(_rows(flow, "G-09", "사용 중지 품목 입고 422"))
    _all_pass(_rows(flow, "G-09", "사용 중지 품목 출하 지시 422"))
    _all_pass(_rows(flow, "G-09", "검사대기 제품 LOT 할당 422"))


@pytest.mark.fn("F-QC-012")
def test_g09_rejudge_fail_to_pass_restores_available(flow):
    _all_pass(_rows(flow, "G-09", "재판정 불합격 → 합격"))


# ── G-10 가용 ───────────────────────────────────────────────────────────────
@pytest.mark.fn("F-SHP-011")
@pytest.mark.fn("F-SHP-021")
@pytest.mark.fn("F-INV-011")
def test_g10_available_equals_qty_minus_allocated(flow):
    _all_pass(_rows(flow, "G-10", "할당 뒤 가용"))
    _all_pass(_rows(flow, "G-10", "INV-010 화면 가용 = 재계산"))
    _all_pass(_rows(flow, "G-10", "확정 뒤 qty · allocated"))
    _all_pass(_rows(flow, "G-10", "전 LOT 할당 = 열린 출하 행 합"))
    _all_pass(_rows(flow, "G-10", "INV-010 화면 가용 = qty − allocated (전 행)"))
    # 독립 재계산 — 지금 DB 의 모든 제품 재고 행: allocated_qty = 열린(지시) 출하 행 합
    bad = flow.q("""
        select s.id, s.allocated_qty,
               coalesce((select sum(sl.qty) from shipment_line sl join shipment_order so on so.id = sl.shipment_order_id
                          where so.status = '지시' and sl.product_lot_id = s.lot_id and sl.location_id = s.location_id), 0) as open_alloc
          from lot_stock s where s.lot_kind = '제품'""")
    mism = [r for r in bad if r["allocated_qty"] != r["open_alloc"]]
    assert not mism, mism[:5]


@pytest.mark.fn("F-SHP-011")
@pytest.mark.fn("F-MAT-021")
def test_g10_concurrent_allocation_and_issue_never_exceed(flow):
    _all_pass(_rows(flow, "G-10", "동시 할당(스레드 2)"))
    _all_pass(_rows(flow, "G-10", "동시 불출(스레드 2)"))


@pytest.mark.fn("F-SHP-012")
def test_g10_shp012_update_reallocates_and_empty_lines_cancel(flow):
    """할당 30 → 25 다시 잡기 · 라인 전부 제거 = 지시 취소(Ruling 21) → 할당 0 · 가용 복원 · 독립 SQL 대조."""
    _all_pass(_rows(flow, "G-10", "수정으로 할당 다시 잡기"))
    _all_pass(_rows(flow, "G-10", "F-SHP-012 라인 전부 제거 = 지시 취소"))
    v = flow.v
    o = flow.q1("select status, (select count(*) from shipment_line where shipment_order_id = %s) as lines "
                "from shipment_order where id = %s", (v["S2id"], v["S2id"]))
    assert o == {"status": "취소", "lines": 0}, o
    s = flow.stock1("제품", v["P2"])
    assert s["allocated_qty"] == 0 and s["qty"] - s["allocated_qty"] == Decimal(10), dict(s)


# ── G-11 알림 ───────────────────────────────────────────────────────────────
@pytest.mark.fn("F-WO-011")
@pytest.mark.fn("F-WO-021")
@pytest.mark.fn("F-MAT-011")
@pytest.mark.fn("F-MAT-031")
@pytest.mark.fn("F-QC-021")
@pytest.mark.fn("F-SHP-011")
@pytest.mark.fn("F-SHP-021")
def test_g11_each_event_one_row_per_receiving_department(flow):
    """D-511 표(이 파일에 글자로 옮김) = 실제 notification 행의 to_role 집합 · 처리 화면이 닫은 부서는 handled_at 있음."""
    v = flow.v
    keys = {"request_created": f"request_created:{v['R1']}", "order_issued": f"order_issued:{v['WO']}",
            "material_received": f"material_received:{v['A1']}", "product_received": f"product_received:{v['P1']}",
            "judged": f"judged:{v['P1']}:1", "shipment_ordered": f"shipment_ordered:{v['S1']}",
            "shipment_confirmed": f"shipment_confirmed:{v['S1']}", "due_d3_unshipped": f"due:{v['R2']}:{flow.today.isoformat()}"}
    for ev, key in keys.items():
        rows = flow.q("select to_role, event_key from notification where dedupe_key = %s", (key,))
        assert {r["to_role"] for r in rows} == D511[ev], f"{ev} {key} → {sorted(r['to_role'] for r in rows)} (D-511 {sorted(D511[ev])})"
        assert all(r["event_key"] == ev for r in rows), rows
        assert len(rows) == len(D511[ev]), "수신 부서마다 정확히 1행이어야 한다"
    for c in [c for c in flow.r.checks if c.gate == "G-11" and c.item in D511]:
        assert c.status == cd.PASS, f"{c.item}: {c.measured}"


def test_g11_same_key_reemit_is_ignored(flow):
    """D-522 — 같은 dedupe_key 재발생은 부서마다 1행 유지(emit 반환 0 · 행 수 그대로)."""
    _all_pass(_rows(flow, "G-11", "같은 키 재발생 무시"))


@pytest.mark.fn("F-HOME-022")
@pytest.mark.fn("F-HOME-021")
def test_g11_home020_handle_closes_for_department_and_404_for_others(flow):
    _all_pass(_rows(flow, "G-11", "HOME-020 처리"))
    _all_pass(_rows(flow, "G-11", "이미 처리된 알림 다시 처리 200"))


def test_g11_due_check_batch_is_idempotent(flow):
    """`uv run python -m lcomfine.jobs due-check` 2회 → SL · PR 1행씩, 2회째 새 행 0(일 단위 dedupe)."""
    _all_pass(_rows(flow, "G-11", "due_d3_unshipped"))


# ── G-05 동적 ───────────────────────────────────────────────────────────────
@pytest.mark.fn("F-LOT-011")
@pytest.mark.fn("F-LOT-021")
@pytest.mark.fn("F-TRK-011")
@pytest.mark.fn("F-PRP-011")
def test_g05_readonly_screens_do_not_write(flow):
    _all_pass(_rows(flow, "G-05", "조회 화면 GET 전후 업무 테이블 diff 0"))


# ── 참고 — 개발2 가 이번에 고친 것 (게이트 밖 · 오류 계약 §2.7) ─────────────
@pytest.mark.fn("F-MAT-012")
@pytest.mark.fn("F-MAT-022")
@pytest.mark.fn("F-MAT-032")
@pytest.mark.fn("F-QC-013")
@pytest.mark.fn("F-QC-023")
def test_dev2_empty_body_is_422_and_qc_status_filter(flow):
    v = flow.v
    prid = flow.q1("select id from product_receipt where product_lot_id = %s", (v["P1id"],))["id"]
    pr = flow.c("pr")
    for path in (f"/mat/receipts/{v['rcp1']}", f"/mat/issues/{flow.issue_ids[0]}", f"/mat/product-receipts/{prid}"):
        resp = pr.post(path, data={}, follow_redirects=False)
        assert resp.status_code == 422, f"POST {path} 빈 본문 → {resp.status_code} (기대 422)"
    for path in ("/qc/incoming?status=보류", "/qc/product?status=가용", "/qc/incoming?status=없는상태"):
        resp = pr.get(path, follow_redirects=False)
        assert resp.status_code == (422 if "없는상태" in path else 200), f"GET {path} → {resp.status_code}"
