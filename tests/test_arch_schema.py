# tests/test_arch_schema.py — 스키마 v2 (D-521 · D-522) — 실제 DB `lcomfine_db` 에 대고 본다
# 쓰는 테스트는 `conn.tx()` 안에서 예외로 끝나 롤백된다 — 데이터를 남기지 않는다.
import re
from pathlib import Path

import psycopg
import pytest

from lcomfine.app import contracts
from lcomfine.db import conn

SCHEMA_SQL = Path(__file__).resolve().parents[1] / "src" / "lcomfine" / "db" / "schema.sql"

# 스펙 §4.1 · task-6 addendum §A — 이름 집합이 기대값이다 (D-521). 수(46)로 판정하지 않는다. 데이터 질의의 로그 표 2 · 허용 뷰 8 은 D-529 로 없앴다.
EXPECTED_TABLES = {
    "BAS": "item customer warehouse location",
    "STD": "spec_sheet standard plate plate_usage artwork sample_sheet exception_item",
    "WO": "production_request work_order work_sequence",
    "MAT": "material_receipt material_lot material_issue material_issue_line product_receipt product_lot",
    "PRD": "production_daily",
    "INS": "inspection_daily",
    "QC": "incoming_inspection product_inspection",
    "INV": "lot_stock stock_move stock_adjust",
    "SHP": "shipment_order shipment_line shipment_adjust",
    "COL": "erp_upload_batch erp_upload_row erp_customer_map erp_column_map",
    "DOC": "doc_account_map sso_token",
    "HOME": "notification notification_setting",
    "SYS": "sys_role sys_user sys_permission sys_common_code sys_access_log sys_change_log sys_number_rule "
           "sys_number_seq",
}
EXPECTED_VIEWS = {"v_work_order_status"}


def _names(kind: str) -> set[str]:
    return {r["table_name"] for r in conn.q(
        "select table_name from information_schema.tables where table_schema = 'public' and table_type = %s", (kind,))}


def test_schema_has_expected_tables():
    want = {t for ts in EXPECTED_TABLES.values() for t in ts.split()}
    assert len(want) == 46
    tables = _names("BASE TABLE")
    assert want <= tables, f"DB 에 없는 테이블 {sorted(want - tables)}"
    assert tables == want, f"계약 밖 테이블 {sorted(tables - want)}"
    views = _names("VIEW")
    assert views == EXPECTED_VIEWS, f"뷰 {sorted(views)} (v_work_order_status 하나 기대 — D-529)"
    # schema.sql 의 @table 태그도 같은 이름 · 같은 영역
    tags = dict(re.findall(r"^-- @table (\w+) \| (\w+) \|", SCHEMA_SQL.read_text(encoding="utf-8"), re.M))
    assert tags == {t: area for area, ts in EXPECTED_TABLES.items() for t in ts.split()}


def test_trace_spine_fks():
    rows = conn.q(
        """select kcu.table_name as t, kcu.column_name as c, ccu.table_name as ref
             from information_schema.referential_constraints rc
             join information_schema.key_column_usage kcu
               on kcu.constraint_name = rc.constraint_name and kcu.constraint_schema = rc.constraint_schema
             join information_schema.constraint_column_usage ccu
               on ccu.constraint_name = rc.unique_constraint_name and ccu.constraint_schema = rc.unique_constraint_schema
            where rc.constraint_schema = 'public'""")
    fks = {(r["t"], r["c"], r["ref"]) for r in rows}
    spine = {
        ("material_issue_line", "material_lot_id", "material_lot"),
        ("material_issue_line", "work_order_id", "work_order"),
        ("product_receipt", "product_lot_id", "product_lot"),
        ("shipment_line", "product_lot_id", "product_lot"),
    }
    assert spine <= fks, f"추적 척추 FK 없음 {sorted(spine - fks)}"
    # 척추를 잇는 나머지 고리 — 지시 → 의뢰 · 제품 입고 → 지시 · 출하 행 → 출하 지시 · 분할 LOT → 원 LOT
    links = {
        ("work_order", "request_id", "production_request"),
        ("product_receipt", "work_order_id", "work_order"),
        ("product_lot", "work_order_id", "work_order"),
        ("product_lot", "parent_lot_id", "product_lot"),
        ("shipment_line", "shipment_order_id", "shipment_order"),
        ("material_lot", "receipt_id", "material_receipt"),
    }
    assert links <= fks, f"척추 고리 FK 없음 {sorted(links - fks)}"


def _location(cur) -> int:
    cur.execute("insert into warehouse (warehouse_code, warehouse_name) values ('TST-W', '(예시) 시험 창고') returning id")
    wid = cur.fetchone()["id"]
    cur.execute("""insert into location (warehouse_id, location_code, location_name)
                   values (%s, 'TST-L', '(예시) 시험 위치') returning id""", (wid,))
    return cur.fetchone()["id"]


@pytest.mark.parametrize("stmt", ["update stock_adjust set reason = '바꿈' where id = %s",
                                  "delete from stock_adjust where id = %s"])
def test_adjust_tables_are_append_only(stmt):
    with pytest.raises(psycopg.errors.RaiseException, match="불변 이력입니다"):
        with conn.tx() as cur:
            loc = _location(cur)
            cur.execute("""insert into stock_adjust (lot_kind, lot_id, location_id, book_qty, actual_qty, reason, created_by)
                           values ('원자재', 1, %s, 10, 9, '실사 차이 (시험)', 'test') returning id""", (loc,))
            cur.execute(stmt, (cur.fetchone()["id"],))


def test_shipment_adjust_has_append_only_triggers():
    trg = conn.q("""select tgrelid::regclass::text as t, tgtype from pg_trigger
                     where not tgisinternal and tgrelid in ('stock_adjust'::regclass, 'shipment_adjust'::regclass)""")
    # tgtype 비트: 2 = BEFORE, 8 = DELETE, 16 = UPDATE
    for table in ("stock_adjust", "shipment_adjust"):
        bits = [r["tgtype"] for r in trg if r["t"] == table]
        assert any(b & 2 and b & 8 and b & 16 for b in bits), f"{table}: before update or delete 트리거 없음"
        assert any(b & 2 and b & 32 for b in bits), f"{table}: before truncate 트리거 없음"   # 32 = TRUNCATE


def test_lot_stock_allocation_check():
    with pytest.raises(psycopg.errors.CheckViolation) as exc:
        with conn.tx() as cur:
            loc = _location(cur)
            cur.execute("""insert into lot_stock (lot_kind, lot_id, location_id, qty, allocated_qty, status)
                           values ('제품', 1, %s, 5, 6, '가용')""", (loc,))
    assert exc.value.diag.constraint_name == "lot_stock_alloc_chk"


def test_product_receipt_work_order_matches_lot():
    """제품 입고의 지시 = 그 제품 LOT 의 지시 — 복합 FK (product_lot_id, work_order_id) 가 어긋남을 막는다."""
    with pytest.raises(psycopg.errors.ForeignKeyViolation) as exc:
        with conn.tx() as cur:
            loc = _location(cur)
            cur.execute("""insert into item (item_code, item_name, item_type) values ('TST-I', '(예시) 시험 제품', '제품')
                           returning id""")
            item = cur.fetchone()["id"]
            cur.execute("""insert into customer (customer_code, customer_name) values ('TST-C', '(예시) 시험 거래처')
                           returning id""")
            cust = cur.fetchone()["id"]
            cur.execute("""insert into production_request (request_no, customer_id, item_id, qty, due_date)
                           values ('TST-REQ', %s, %s, 10, current_date) returning id""", (cust, item))
            req = cur.fetchone()["id"]
            wo = []
            for no in ("TST-WO-A", "TST-WO-B"):
                cur.execute("""insert into work_order (work_order_no, request_id, item_id, qty)
                               values (%s, %s, %s, 10) returning id""", (no, req, item))
                wo.append(cur.fetchone()["id"])
            cur.execute("""insert into product_lot (lot_no, item_id, work_order_id, qty)
                           values ('TST-PLOT', %s, %s, 10) returning id""", (item, wo[0]))
            lot = cur.fetchone()["id"]
            cur.execute("""insert into product_receipt (work_order_id, product_lot_id, location_id, qty)
                           values (%s, %s, %s, 10)""", (wo[1], lot, loc))
    assert exc.value.diag.constraint_name == "product_receipt_lot_wo_fk"


def test_function_list_tables_exist_in_schema():
    tags = set(re.findall(r"^-- @table (\w+) \|", SCHEMA_SQL.read_text(encoding="utf-8"), re.M))
    used = {t for f in contracts.functions() for t in f.tables}
    assert used and used <= tags, f"schema.sql 에 없는 쓰는 테이블 {sorted(used - tags)}"
