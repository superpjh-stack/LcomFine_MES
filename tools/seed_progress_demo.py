"""수주 진행보드 데모 데이터 10건을 넣는다.

별도 발주 테이블이 없는 현재 스키마에 맞춰 production_request.note 에 발주 요약을 남기고,
자재 발주 이후의 실제 흐름은 material_receipt/material_lot/material_issue 로 만든다.
재실행 시 DEMO-PROG-* 데이터만 지우고 다시 만든다.
"""

from __future__ import annotations

from datetime import date, timedelta

from lcomfine.db import conn


BY = "demo_progress"
PREFIX = "DEMO-PROG-"


def _cleanup(cur) -> None:
    cur.execute("select id from production_request where request_no like %s", (PREFIX + "%",))
    request_ids = [r["id"] for r in cur.fetchall()]
    if not request_ids:
        return
    cur.execute("select id from work_order where request_id = any(%s)", (request_ids,))
    work_ids = [r["id"] for r in cur.fetchall()]
    cur.execute("select id, product_lot_id from product_receipt where work_order_id = any(%s)", (work_ids or [-1],))
    receipt_rows = cur.fetchall()
    product_lot_ids = [r["product_lot_id"] for r in receipt_rows]
    cur.execute("select id from product_lot where work_order_id = any(%s)", (work_ids or [-1],))
    product_lot_ids += [r["id"] for r in cur.fetchall()]
    cur.execute("select id from material_lot where lot_no like %s", (PREFIX + "%",))
    material_lot_ids = [r["id"] for r in cur.fetchall()]
    cur.execute("delete from shipment_adjust where shipment_order_id in (select id from shipment_order where request_id = any(%s))", (request_ids,))
    cur.execute("delete from shipment_line where shipment_order_id in (select id from shipment_order where request_id = any(%s))", (request_ids,))
    cur.execute("delete from shipment_order where request_id = any(%s)", (request_ids,))
    cur.execute("delete from product_inspection where product_lot_id = any(%s)", (product_lot_ids or [-1],))
    cur.execute("delete from product_receipt where work_order_id = any(%s)", (work_ids or [-1],))
    cur.execute("delete from lot_stock where lot_kind = '제품' and lot_id = any(%s)", (product_lot_ids or [-1],))
    cur.execute("delete from product_lot where id = any(%s)", (product_lot_ids or [-1],))
    cur.execute("delete from inspection_daily where work_order_id = any(%s)", (work_ids or [-1],))
    cur.execute("delete from production_daily where work_order_id = any(%s)", (work_ids or [-1],))
    cur.execute("delete from material_issue_line where work_order_id = any(%s)", (work_ids or [-1],))
    cur.execute("delete from material_issue where note like %s", (PREFIX + "%",))
    cur.execute("delete from work_sequence where work_order_id = any(%s)", (work_ids or [-1],))
    cur.execute("delete from work_order where id = any(%s)", (work_ids or [-1],))
    cur.execute("delete from incoming_inspection where material_lot_id = any(%s)", (material_lot_ids or [-1],))
    cur.execute("delete from lot_stock where lot_kind = '원자재' and lot_id = any(%s)", (material_lot_ids or [-1],))
    cur.execute("delete from material_lot where id = any(%s)", (material_lot_ids or [-1],))
    cur.execute("delete from material_receipt where note like %s", (PREFIX + "%",))
    cur.execute("delete from production_request where id = any(%s)", (request_ids,))


def run() -> dict[str, int]:
    today = date.today()
    stage_due = (14, 12, 10, 8, 6, 4, 2, 0, -1, 5)
    stage_names = ("수주", "지시", "생산", "검사", "제품 입고", "출하", "출하 완료")
    with conn.tx() as cur:
        _cleanup(cur)
        cur.execute("select id from location order by id limit 1")
        location = cur.fetchone()
        if not location:
            raise RuntimeError("위치 데이터가 없습니다. 먼저 make db-seed 를 실행하세요.")
        location_id = location["id"]

        cur.execute("""insert into item (item_code, item_name, item_type, created_by)
                       values ('DEMO-PROG-RM', '데모 원자재', '원자재', %s)
                       on conflict (item_code) do update set item_name = excluded.item_name
                       returning id""", (BY,))
        material_item_id = cur.fetchone()["id"]

        product_ids = []
        for n in (1, 2):
            cur.execute("""insert into item (item_code, item_name, item_type, created_by)
                           values (%s, %s, '제품', %s)
                           on conflict (item_code) do update set item_name = excluded.item_name
                           returning id""", (f"DEMO-PROG-P0{n}", f"데모 제품 {n}", BY))
            product_ids.append(cur.fetchone()["id"])

        request_ids = []
        for i in range(10):
            n = i + 1
            stage = (0, 1, 2, 3, 4, 5, 6, 2, 3, 4)[i]
            qty = 100 + i * 10
            request_date = today - timedelta(days=12 - i)
            due_date = today + timedelta(days=stage_due[i])
            status = "확인대기" if stage == 0 else ("확정" if stage == 1 else "지시완료")
            customer_code = f"DEMO-PROG-C{n:02d}"
            cur.execute("""insert into customer (customer_code, customer_name, created_by)
                           values (%s, %s, %s)
                           on conflict (customer_code) do update set customer_name = excluded.customer_name
                           returning id""", (customer_code, f"데모 고객 {n:02d}", BY))
            customer_id = cur.fetchone()["id"]
            note = f"{PREFIX}{n:02d} · 발주: 데모 공급사 {((i % 3) + 1)} · 원자재 {qty}개"
            cur.execute("""insert into production_request
                           (request_no, request_date, customer_id, item_id, qty, due_date, status, note, created_by)
                           values (%s, %s, %s, %s, %s, %s, %s, %s, %s) returning id""",
                        (f"{PREFIX}{n:02d}", request_date, customer_id, product_ids[i % 2], qty,
                         due_date, status, note, BY))
            request_id = cur.fetchone()["id"]
            request_ids.append(request_id)

            cur.execute("""insert into material_receipt (supplier_name, received_on, note, created_by)
                           values (%s, %s, %s, %s) returning id""",
                        (f"데모 공급사 {((i % 3) + 1)}", request_date + timedelta(days=1), note, BY))
            material_receipt_id = cur.fetchone()["id"]
            cur.execute("""insert into material_lot (lot_no, receipt_id, item_id, qty, supplier_lot_no, created_by)
                           values (%s, %s, %s, %s, %s, %s) returning id""",
                        (f"{PREFIX}MLOT-{n:02d}", material_receipt_id, material_item_id, qty * 2,
                         f"SUP-{n:02d}", BY))
            material_lot_id = cur.fetchone()["id"]
            cur.execute("""insert into lot_stock (lot_kind, lot_id, location_id, qty, status, created_by)
                           values ('원자재', %s, %s, %s, '가용', %s)""",
                        (material_lot_id, location_id, qty * 2, BY))
            cur.execute("""insert into incoming_inspection (material_lot_id, seq, result, inspected_at, inspector, created_by)
                           values (%s, 1, '합격', %s, %s, %s)""",
                        (material_lot_id, request_date + timedelta(days=2), BY, BY))

            if stage >= 1:
                cur.execute("""insert into work_order
                               (work_order_no, request_id, item_id, qty, equipment_code, planned_on, status, created_by)
                               values (%s, %s, %s, %s, 'EX-EQ', %s, %s, %s) returning id""",
                            (f"{PREFIX}WO-{n:02d}", request_id, product_ids[i % 2], qty,
                             request_date + timedelta(days=3), "완료" if stage >= 6 else ("진행" if stage >= 2 else "발행"), BY))
                work_id = cur.fetchone()["id"]
                if stage >= 2:
                    cur.execute("""insert into material_issue (issued_on, note, created_by)
                                   values (%s, %s, %s) returning id""",
                                (request_date + timedelta(days=3), note, BY))
                    issue_id = cur.fetchone()["id"]
                    cur.execute("""insert into material_issue_line
                                   (issue_id, material_lot_id, work_order_id, location_id, qty, created_by)
                                   values (%s, %s, %s, %s, %s, %s)""",
                                (issue_id, material_lot_id, work_id, location_id, qty, BY))
                if stage >= 2:
                    cur.execute("""insert into production_daily
                                   (work_order_id, work_date, equipment_code, produced_qty, good_qty, loss_qty, created_by)
                                   values (%s, %s, 'EX-EQ', %s, %s, %s, %s)""",
                                (work_id, request_date + timedelta(days=4), qty, qty - 3, 3, BY))
                if stage >= 3:
                    cur.execute("""insert into inspection_daily
                                   (work_order_id, work_date, inspected_qty, defect_qty, created_by)
                                   values (%s, %s, %s, 0, %s)""",
                                (work_id, request_date + timedelta(days=5), qty - 3, BY))
                if stage >= 4:
                    product_qty = qty - 3
                    cur.execute("""insert into product_lot (lot_no, item_id, work_order_id, qty, created_by)
                                   values (%s, %s, %s, %s, %s) returning id""",
                                (f"{PREFIX}PLOT-{n:02d}", product_ids[i % 2], work_id, product_qty, BY))
                    product_lot_id = cur.fetchone()["id"]
                    cur.execute("""insert into lot_stock (lot_kind, lot_id, location_id, qty, status, created_by)
                                   values ('제품', %s, %s, %s, '가용', %s)""",
                                (product_lot_id, location_id, product_qty, BY))
                    cur.execute("""insert into product_receipt
                                   (work_order_id, product_lot_id, location_id, qty, received_on, created_by)
                                   values (%s, %s, %s, %s, %s, %s)""",
                                (work_id, product_lot_id, location_id, product_qty,
                                 request_date + timedelta(days=6), BY))
                    cur.execute("""insert into product_inspection
                                   (product_lot_id, seq, result, inspected_at, inspector, created_by)
                                   values (%s, 1, '합격', %s, %s, %s)""",
                                (product_lot_id, request_date + timedelta(days=7), BY, BY))
                    if stage >= 5:
                        shipped_qty = product_qty if stage >= 6 else product_qty * 0.5
                        shipment_status = "확정" if stage >= 6 else "지시"
                        confirmed_at = request_date + timedelta(days=8) if stage >= 6 else None
                        cur.execute("""insert into shipment_order
                                       (shipment_no, request_id, customer_id, due_date, status, confirmed_at, confirmed_by, created_by)
                                       values (%s, %s, %s, %s, %s, %s, %s, %s) returning id""",
                                    (f"{PREFIX}SHP-{n:02d}", request_id, customer_id, due_date,
                                     shipment_status, confirmed_at, BY if confirmed_at else None, BY))
                        shipment_id = cur.fetchone()["id"]
                        cur.execute("""insert into shipment_line (shipment_order_id, product_lot_id, location_id, qty, created_by)
                                       values (%s, %s, %s, %s, %s)""",
                                    (shipment_id, product_lot_id, location_id, shipped_qty, BY))
            
    return {"requests": len(request_ids), "stages": len(stage_names)}


if __name__ == "__main__":
    print("seed_progress_demo:", run())
