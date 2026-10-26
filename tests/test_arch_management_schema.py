"""D-531 경영 Cockpit 관리·재무 스키마 계약."""

from pathlib import Path

import psycopg
import pytest

from lcomfine.db import conn


SCHEMA = Path(__file__).resolve().parents[1] / "src/lcomfine/db/schema.sql"
MGT_TABLES = {
    "management_metric", "management_target", "management_target_version", "management_threshold",
    "management_issue", "management_action", "financial_import_batch", "financial_fact",
}
EXPECTED_METRICS = {
    "orders.qty", "orders.amount", "production.attainment", "production.utilization",
    "quality.pass_rate", "quality.defect_qty", "inventory.available_qty", "inventory.long_stay",
    "inventory.amount", "shipment.qty", "shipment.amount", "shipment.due_rate",
    "collection.amount", "collection.receivable", "collection.over_90", "flow.lead_days",
}


def test_management_tables_exist_in_schema_and_database():
    sql = SCHEMA.read_text(encoding="utf-8")
    assert all(f"-- @table {name} | MGT |" in sql for name in MGT_TABLES)
    live = {r["table_name"] for r in conn.q(
        "select table_name from information_schema.tables where table_schema='public' and table_type='BASE TABLE'")}
    assert MGT_TABLES <= live


def test_management_foreign_keys_and_state_checks():
    fks = {(r["t"], r["c"], r["ref"]) for r in conn.q(
        """select kcu.table_name t, kcu.column_name c, ccu.table_name ref
             from information_schema.referential_constraints rc
             join information_schema.key_column_usage kcu
               on kcu.constraint_name=rc.constraint_name and kcu.constraint_schema=rc.constraint_schema
             join information_schema.constraint_column_usage ccu
               on ccu.constraint_name=rc.unique_constraint_name and ccu.constraint_schema=rc.unique_constraint_schema
            where rc.constraint_schema='public'""")}
    assert {
        ("management_target", "metric_key", "management_metric"),
        ("management_target_version", "target_id", "management_target"),
        ("management_threshold", "metric_key", "management_metric"),
        ("management_action", "issue_id", "management_issue"),
        ("financial_fact", "batch_id", "financial_import_batch"),
        ("financial_fact", "customer_id", "customer"),
        ("financial_fact", "item_id", "item"),
    } <= fks

    checks = {r["conname"] for r in conn.q(
        "select conname from pg_constraint where connamespace='public'::regnamespace and contype='c'")}
    assert {
        "management_metric_direction_chk", "management_target_period_chk", "management_target_status_chk",
        "management_threshold_level_chk", "management_issue_status_chk", "management_action_status_chk",
        "financial_import_batch_status_chk", "financial_fact_amount_chk",
    } <= checks


def test_management_metric_seed_defines_metadata_not_targets():
    assert {r["metric_key"] for r in conn.q("select metric_key from management_metric")} == EXPECTED_METRICS
    assert conn.q1("select count(*) n from management_target where created_by='seed'")["n"] == 0
    assert conn.q1("select count(*) n from management_threshold where created_by='seed'")["n"] == 0


def test_one_active_target_and_financial_batch_per_scope():
    indexes = {r["indexname"]: r["indexdef"] for r in conn.q(
        "select indexname,indexdef from pg_indexes where schemaname='public'")}
    assert "management_target_active_uq" in indexes and "WHERE (status = '사용'::text)" in indexes["management_target_active_uq"]
    assert "financial_import_batch_active_uq" in indexes and "WHERE (status = '반영'::text)" in indexes["financial_import_batch_active_uq"]


@pytest.mark.parametrize("table", ["management_target_version", "financial_fact"])
def test_append_only_management_history_has_update_delete_and_truncate_guards(table):
    rows = conn.q("select tgtype from pg_trigger where not tgisinternal and tgrelid=%s::regclass", (table,))
    bits = [r["tgtype"] for r in rows]
    assert any(b & 2 and b & 8 and b & 16 for b in bits)
    assert any(b & 2 and b & 32 for b in bits)


def test_financial_fact_rejects_all_null_amounts():
    with pytest.raises(psycopg.errors.CheckViolation) as exc:
        with conn.tx() as cur:
            cur.execute("""insert into financial_import_batch
                           (period_from, period_to, round_no, status, source_name)
                           values (current_date, current_date, 999999, '검증', '시험') returning id""")
            bid = cur.fetchone()["id"]
            cur.execute("""insert into financial_fact (batch_id, row_no, period_month, customer_id, item_id)
                           select %s, 1, date_trunc('month', current_date)::date, c.id, i.id
                             from customer c cross join item i limit 1""", (bid,))
    assert exc.value.diag.constraint_name == "financial_fact_amount_chk"
