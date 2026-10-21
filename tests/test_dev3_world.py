# tests/test_dev3_world.py — 개발3 테스트의 기준 데이터(테스트 함수 없음).
# 다른 개발자의 화면 · 시드에 기대지 않는다: 품목 · 거래처 · 창고/위치 · 생산의뢰 · 지시 · 제품 LOT · 재고 · 판정을 SQL 로 직접 만들고
# 끝에 지운다. 이름은 전부 고유 접두 `T3{시각}-` + `(예시)`. 같은 DB 를 다른 개발자의 테스트와 함께 쓴다.
from __future__ import annotations

import itertools
import time
from datetime import date, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient

from lcomfine.app.main import app
from lcomfine.app.settings import get_settings
from lcomfine.db import conn

_seq = itertools.count(1)


def login(login_id: str) -> TestClient:
    c = TestClient(app)
    pw = get_settings().seed_password
    assert pw, "LCOMFINE_SEED_PASSWORD 가 .env 에 없다"
    r = c.post("/login", data={"login_id": login_id, "password": pw}, follow_redirects=False)
    assert r.status_code == 303, f"{login_id} 로그인 {r.status_code}"
    return c


class World:
    """한 테스트의 기준 데이터. `close()` 가 이 World 가 만든(그리고 그 거래처로 생긴) 행을 전부 지운다."""

    def __init__(self) -> None:
        self.tag = f"T3{int(time.time() * 1000) % 10**10}{next(_seq):03d}"
        self.items: list[int] = []
        self.lots: list[int] = []
        self.wos: list[int] = []
        self.reqs: list[int] = []
        with conn.tx() as cur:
            cur.execute("insert into customer (customer_code, customer_name, created_by) values (%s, %s, 'test') returning id",
                        (f"{self.tag}-C", f"고객 {self.tag} (예시)"))
            self.customer_id = cur.fetchone()["id"]
            cur.execute("insert into warehouse (warehouse_code, warehouse_name, created_by) values (%s, %s, 'test') returning id",
                        (f"{self.tag}-W", f"창고 {self.tag} (예시)"))
            self.warehouse_id = cur.fetchone()["id"]
            cur.execute("""insert into location (warehouse_id, location_code, location_name, created_by)
                           values (%s, %s, %s, 'test') returning id""", (self.warehouse_id, "L1", "위치 1 (예시)"))
            self.location_id = cur.fetchone()["id"]
        self.item_id = self.item()
        self.request_id, self.request_no = self.request(self.item_id, Decimal("50"), date.today() + timedelta(days=10))
        self.wo_id = self.work_order(self.request_id, self.item_id)

    # ── 만들기 ──
    def item(self, use_yn: str = "Y") -> int:
        n = len(self.items) + 1
        row = conn.q1("""insert into item (item_code, item_name, item_type, use_yn, created_by)
                         values (%s, %s, '제품', %s, 'test') returning id""",
                      (f"{self.tag}-I{n}", f"제품 {self.tag}-{n} (예시)", use_yn))
        self.items.append(row["id"])
        return row["id"]

    def request(self, item_id: int, qty: Decimal, due: date) -> tuple[int, str]:
        no = f"{self.tag}-REQ{len(self.reqs) + 1}"
        row = conn.q1("""insert into production_request (request_no, customer_id, item_id, qty, due_date, status, created_by)
                         values (%s, %s, %s, %s, %s, '확정', 'test') returning id""",
                      (no, self.customer_id, item_id, qty, due))
        self.reqs.append(row["id"])
        return row["id"], no

    def work_order(self, request_id: int, item_id: int, equipment: str | None = None) -> int:
        row = conn.q1("""insert into work_order (work_order_no, request_id, item_id, qty, equipment_code, created_by)
                         values (%s, %s, %s, 100, %s, 'test') returning id""",
                      (f"{self.tag}-WO{len(self.wos) + 1}", request_id, item_id, equipment))
        self.wos.append(row["id"])
        return row["id"]

    def lot(self, qty: str | Decimal = "10", *, judge: str | None = "합격", status: str | None = None,
            item_id: int | None = None, wo_id: int | None = None, received_on: date | None = None) -> dict:
        """제품 LOT + 제품 입고 + 재고 행(+ 판정 1차). status 기본 = 판정이 합격이면 가용, 불합격이면 보류, 없으면 검사대기."""
        item_id = item_id or self.item_id
        wo_id = wo_id or self.wo_id
        qty = Decimal(str(qty))
        st = status or {"합격": "가용", "불합격": "보류", None: "검사대기"}[judge]
        with conn.tx() as cur:
            cur.execute("""insert into product_lot (lot_no, item_id, work_order_id, qty, created_by)
                           values (%s, %s, %s, %s, 'test') returning id, lot_no""",
                        (f"{self.tag}-PL{len(self.lots) + 1}", item_id, wo_id, qty))
            lot = dict(cur.fetchone())
            cur.execute("""insert into product_receipt (work_order_id, product_lot_id, location_id, qty, received_on, created_by)
                           values (%s, %s, %s, %s, %s, 'test')""",
                        (wo_id, lot["id"], self.location_id, qty, received_on or date.today()))
            cur.execute("""insert into lot_stock (lot_kind, lot_id, location_id, qty, status, created_by)
                           values ('제품', %s, %s, %s, %s, 'test') returning id""", (lot["id"], self.location_id, qty, st))
            lot["stock_id"] = cur.fetchone()["id"]
            if judge:
                cur.execute("""insert into product_inspection (product_lot_id, seq, result, items, inspected_at, inspector)
                               values (%s, 1, %s, '{}'::jsonb, now(), 'test')""", (lot["id"], judge))
        self.lots.append(lot["id"])
        return lot

    def judge(self, lot_id: int, result: str, status: str) -> None:
        """재판정(새 차수) + 재고 상태 — QC 가 하는 일을 테스트가 흉내 낸다."""
        with conn.tx() as cur:
            cur.execute("""insert into product_inspection (product_lot_id, seq, result, items, inspected_at, inspector)
                           select %s, coalesce(max(seq), 0) + 1, %s, '{}'::jsonb, now(), 'test'
                             from product_inspection where product_lot_id = %s""", (lot_id, result, lot_id))
            cur.execute("update lot_stock set status = %s where lot_kind = '제품' and lot_id = %s", (status, lot_id))

    # ── 읽기 ──
    def stock(self, stock_id: int) -> dict:
        return conn.q1("select qty, allocated_qty, status from lot_stock where id = %s", (stock_id,))

    def order(self, shipment_no: str) -> dict:
        return conn.q1("select * from shipment_order where shipment_no = %s", (shipment_no,))

    # ── 정리 ──
    def close(self) -> None:
        orders = [r["id"] for r in conn.q("select id from shipment_order where customer_id = %s", (self.customer_id,))]
        nos = [r["shipment_no"] for r in conn.q("select shipment_no from shipment_order where customer_id = %s",
                                                 (self.customer_id,))]
        with conn.tx() as cur:
            if nos:
                cur.execute("delete from notification where dedupe_key = any(%s)",
                            ([f"{e}:{n}" for n in nos for e in ("shipment_ordered", "shipment_confirmed")],))
            if orders:
                cur.execute("delete from stock_move where ref_table = 'shipment_order' and ref_id = any(%s)", (orders,))
                # shipment_adjust 는 불변 이력(트리거가 DELETE 를 막는다) — 테스트 행만 이 트랜잭션에서 트리거를 끄고 지운다
                cur.execute("set local session_replication_role = replica")
                cur.execute("delete from shipment_adjust where shipment_order_id = any(%s)", (orders,))
                cur.execute("set local session_replication_role = origin")
                cur.execute("delete from shipment_line where shipment_order_id = any(%s)", (orders,))
                cur.execute("delete from shipment_order where id = any(%s)", (orders,))
            if self.lots:
                cur.execute("delete from stock_move where lot_kind = '제품' and lot_id = any(%s)", (self.lots,))
                cur.execute("delete from product_inspection where product_lot_id = any(%s)", (self.lots,))
                cur.execute("delete from lot_stock where lot_kind = '제품' and lot_id = any(%s)", (self.lots,))
                cur.execute("delete from product_receipt where product_lot_id = any(%s)", (self.lots,))
                cur.execute("delete from product_lot where id = any(%s)", (self.lots,))
            if self.wos:
                cur.execute("delete from production_daily where work_order_id = any(%s)", (self.wos,))
                cur.execute("delete from work_order where id = any(%s)", (self.wos,))
            if self.reqs:
                cur.execute("delete from production_request where id = any(%s)", (self.reqs,))
            cur.execute("delete from location where id = %s", (self.location_id,))
            cur.execute("delete from warehouse where id = %s", (self.warehouse_id,))
            cur.execute("delete from customer where id = %s", (self.customer_id,))
            if self.items:
                cur.execute("delete from item where id = any(%s)", (self.items,))
