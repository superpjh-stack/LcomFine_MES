"""대시보드용 데이터 품질 점검 — 읽기 전용.

Phase 2의 첫 구현은 데이터를 고치거나 보정하지 않는다. 현재 MES 원천에서
확인 가능한 연결 누락만 집계하고, 담당자가 기존 처리 화면으로 이동할 수
있는 근거 링크를 함께 만든다.
"""

from __future__ import annotations

import os

from ..db import conn
from . import erp_upload, equipment_gateway, gallus_ems430, nav


def _item(key: str, label: str, count: int, *, href: str, source: str, note: str,
          severity: str = "정상") -> dict:
    return {"key": key, "label": label, "count": count, "severity": severity,
            "href": href, "source": source, "note": note}


def data_quality() -> dict:
    """현재 원천 데이터의 연결·입력 품질을 읽어 요약한다.

    숫자 0은 정상적으로 점검했으나 대상이 없는 상태다. 조회 자체가
    불가능한 경우를 별도 미수집으로 감추지 않고, DB 연결 오류는 기존
    화면 오류 처리로 전달한다.
    """
    unmapped = len(erp_upload.unmapped_codes())
    upload_errors = conn.q1(
        """select count(*) as n
             from erp_upload_row r
             join erp_upload_batch b on b.id = r.batch_id
            where b.status = '반영' and r.error is not null"""
    )["n"]
    not_started = conn.q1(
        """select count(*) as n
             from production_request r
            where r.status <> '취소'
              and not exists (select 1 from work_order w
                               where w.request_id = r.id and w.status <> '취소')"""
    )["n"]
    no_issue = conn.q1(
        """select count(*) as n
             from work_order w
            where w.status in ('발행', '진행')
              and not exists (
                    select 1
                      from material_issue_line l
                      join material_issue i on i.id = l.issue_id
                     where l.work_order_id = w.id and i.canceled_at is null
              )"""
    )["n"]
    product_qc_wait = conn.q1(
        """select count(distinct s.lot_id) as n
             from lot_stock s
            where s.lot_kind = '제품' and s.status = '검사대기' and s.qty > 0
              and not exists (
                    select 1 from product_inspection p
                     where p.product_lot_id = s.lot_id
              )"""
    )["n"]
    inactive_customers = conn.q1(
        """select count(distinct customer_id) as n
             from (
                   select r.customer_id from production_request r
                    join customer c on c.id = r.customer_id
                   where r.status <> '취소' and c.use_yn = 'N'
                   union
                   select s.customer_id from shipment_order s
                    join customer c on c.id = s.customer_id
                   where s.status <> '취소' and c.use_yn = 'N'
             ) x"""
    )["n"]
    inactive_items = conn.q1(
        """select count(distinct item_id) as n
             from (
                   select r.item_id from production_request r
                    join item i on i.id = r.item_id
                   where r.status <> '취소' and i.use_yn = 'N'
                   union
                   select w.item_id from work_order w
                    join item i on i.id = w.item_id
                   where w.status <> '취소' and i.use_yn = 'N'
             ) x"""
    )["n"]
    equipment_invalid = conn.q1(
        """select count(*) as n
             from work_order w
            where w.status in ('발행', '진행')
              and (w.equipment_code is null or not exists (
                    select 1 from sys_common_code c
                     where c.group_code = '설비' and c.code = w.equipment_code
              ))"""
    )["n"]
    production_equipment_mismatch = conn.q1(
        """select count(*) as n
             from production_daily d
             join work_order w on w.id = d.work_order_id
            where d.equipment_code is distinct from w.equipment_code"""
    )["n"]
    inspection_defect_code_invalid = conn.q1(
        """select count(distinct x.code) as n
             from inspection_daily d
             cross join lateral jsonb_object_keys(coalesce(d.defects, '{}'::jsonb)) as x(code)
            where not exists (
                    select 1 from sys_common_code c
                     where c.group_code = '불량유형' and c.code = x.code
            )"""
    )["n"]

    checks = [
        _item("erp_unmapped", "ERP 거래처 미매핑", unmapped,
              href=nav.path_of("COL-030"), source="ERP 업로드 · 거래처 매핑",
              note="ERP 거래처코드와 MES 거래처 연결이 필요합니다.",
              severity="위험" if unmapped else "정상"),
        _item("erp_errors", "ERP 업로드 오류", upload_errors,
              href=nav.path_of("COL-020"), source="ERP 업로드 · 반영 회차",
              note="오류 행은 수금 집계에서 제외됩니다.",
              severity="위험" if upload_errors else "정상"),
        _item("request_not_started", "생산지시 없는 수주", not_started,
              href=nav.path_of("WO-020"), source="수주 · 생산지시",
              note="수주가 생산 흐름에 연결되지 않았습니다.",
              severity="주의" if not_started else "정상"),
        _item("work_order_no_issue", "자재 불출 누락 지시", no_issue,
              href=nav.path_of("MAT-020"), source="생산지시 · 자재불출",
              note="발행·진행 지시에 유효한 불출 이력이 없습니다.",
              severity="주의" if no_issue else "정상"),
        _item("product_qc_wait", "제품검사 미판정 LOT", product_qc_wait,
              href=nav.path_of("QC-020"), source="제품 LOT · 제품검사",
              note="검사대기 제품 LOT에 최종 판정이 없습니다.",
              severity="주의" if product_qc_wait else "정상"),
        _item("inactive_customer_ref", "사용중지 거래처 연결", inactive_customers,
              href=nav.path_of("BAS-020"), source="수주·출하 · 거래처 기준정보",
              note="업무 데이터가 사용중지 거래처를 참조합니다.",
              severity="위험" if inactive_customers else "정상"),
        _item("inactive_item_ref", "사용중지 품목 연결", inactive_items,
              href=nav.path_of("BAS-010"), source="수주·지시 · 품목 기준정보",
              note="업무 데이터가 사용중지 품목을 참조합니다.",
              severity="위험" if inactive_items else "정상"),
        _item("equipment_invalid", "설비 코드 누락·미등록", equipment_invalid,
              href=nav.path_of("WO-020"), source="작업지시 · 설비 공통코드",
              note="발행·진행 지시에 유효한 설비 코드가 없습니다.",
              severity="주의" if equipment_invalid else "정상"),
        _item("production_equipment_mismatch", "일보·지시 설비 불일치", production_equipment_mismatch,
              href=nav.path_of("PRD-010"), source="생산일보 · 작업지시",
              note="생산일보의 설비와 작업지시 설비가 다릅니다.",
              severity="주의" if production_equipment_mismatch else "정상"),
        _item("inspection_defect_code_invalid", "검사 불량유형 미등록", inspection_defect_code_invalid,
              href=nav.path_of("SYS-030"), source="검사일보 · 불량유형 공통코드",
              note="검사일보에 공통코드로 등록되지 않은 불량유형이 있습니다.",
              severity="주의" if inspection_defect_code_invalid else "정상"),
    ]
    issue_count = sum(row["count"] for row in checks if row["severity"] != "정상")
    risk_count = sum(1 for row in checks if row["severity"] == "위험")
    return {
        "checks": checks,
        "summary": {
            "total": len(checks),
            "issue_count": issue_count,
            "risk_count": risk_count,
            "status": "위험" if risk_count else ("주의" if issue_count else "정상"),
        },
    }


def equipment_monitor() -> dict:
    """설비 수집 파일럿용 읽기 모델.

    아직 장비 수집 서버가 연결되지 않았으므로 연결 여부를 추정하지 않는다.
    공통코드에 등록된 설비와 업무 데이터에 등장한 설비를 보여주고, 생산일보
    최근 기록만으로 MES 입력 상태를 표시한다.
    """
    rows = conn.q(
        """select x.equipment_code, x.equipment_name, x.use_yn,
                      max(d.work_date) as last_work_date,
                      count(d.id) filter (where d.work_date >= current_date - 30) as recent_entries,
                      count(d.id) as total_entries
             from (
                   select code as equipment_code, code_name as equipment_name, use_yn
                     from sys_common_code where group_code = '설비'
                   union
                   select distinct equipment_code, equipment_code, 'N'
                     from work_order where equipment_code is not null
             ) x
             left join production_daily d on d.equipment_code = x.equipment_code
            group by x.equipment_code, x.equipment_name, x.use_yn
            order by x.equipment_code"""
    )
    probes = equipment_gateway.probe_all()
    for row in rows:
        if row["use_yn"] != "Y":
            row["status"] = "사용중지"
        elif row["last_work_date"] is None:
            row["status"] = "미수집"
        else:
            row["status"] = "일보 수집"
        connection = probes.get(row["equipment_code"])
        row["connection"] = connection["status"] if connection else "연동 대기"
        row["connection_detail"] = connection["detail"] if connection else "Ethernet endpoint 설정 필요"
        row["href"] = nav.path_of("PRP-020") if nav.by_id("PRP-020") else nav.path_of("PRD-030")
    sample = gallus_ems430.sample_snapshot() if os.getenv("LCOMFINE_EQUIPMENT_SAMPLE", "").upper() == "Y" else None
    return {
        "rows": rows,
        "sample": sample,
        "summary": {
            "total": len(rows),
            "collected": sum(1 for row in rows if row["status"] == "일보 수집"),
            "missing": sum(1 for row in rows if row["status"] == "미수집"),
            "waiting": len(rows),
        },
    }
