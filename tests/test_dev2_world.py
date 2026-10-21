# tests/test_dev2_world.py — 개발2 테스트 공용 바탕 (테스트 없음 · 다른 test_dev2_* 가 import 한다)
# 실제 DB `lcomfine_db` · 시드 뒤. 다른 개발자와 같은 DB 를 쓰므로 기준 데이터(품목 · 거래처 · 창고 · 위치 · 의뢰 · 지시)는
# 고유 접두 `T<시각><난수>-` 로 SQL 로 직접 만들고, 끝에 그 접두로 만든 것과 거기서 이어진 행을 전부 지운다.
# 개발1 의 WO 화면 · 시드에 기대지 않는다. 출하(개발3 SHP)도 필요한 테스트에서는 SQL 로 직접 만든다.
from __future__ import annotations

import time
import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from lcomfine.app.main import app
from lcomfine.app.settings import get_settings
from lcomfine.db import conn


def login(login_id: str) -> TestClient:
    pw = get_settings().seed_password
    assert pw, "LCOMFINE_SEED_PASSWORD 미설정 — `make setup`"
    c = TestClient(app, raise_server_exceptions=False)
    r = c.post("/login", data={"login_id": login_id, "password": pw}, follow_redirects=False)
    assert r.status_code == 303, f"{login_id} 로그인 {r.status_code}"
    return c


class World:
    """테스트 하나가 쓰는 기준 데이터 묶음."""

    def __init__(self) -> None:
        self.p = f"T{int(time.time() * 1000) % 10**10}{uuid.uuid4().hex[:4]}-"
        with conn.tx() as cur:
            def ins(sql, args):
                cur.execute(sql + " returning id", args)
                return cur.fetchone()["id"]
            self.rm = ins("insert into item (item_code, item_name, item_type) values (%s, %s, '원자재')",
                          (self.p + "RM", "원자재 A (예시)"))
            self.rm_off = ins("insert into item (item_code, item_name, item_type, use_yn) values (%s, %s, '원자재', 'N')",
                              (self.p + "RMX", "원자재 중지 (예시)"))
            self.fg = ins("insert into item (item_code, item_name, item_type) values (%s, %s, '제품')",
                          (self.p + "FG", "제품 A (예시)"))
            self.wh = ins("insert into warehouse (warehouse_code, warehouse_name) values (%s, %s)",
                          (self.p + "WH", "창고 A (예시)"))
            self.loc1 = ins("insert into location (warehouse_id, location_code, location_name) values (%s, %s, %s)",
                            (self.wh, self.p + "L1", "위치 1 (예시)"))
            self.loc2 = ins("insert into location (warehouse_id, location_code, location_name) values (%s, %s, %s)",
                            (self.wh, self.p + "L2", "위치 2 (예시)"))
            self.cust = ins("insert into customer (customer_code, customer_name) values (%s, %s)",
                            (self.p + "C", "고객 A (예시)"))
            self.req = ins("""insert into production_request (request_no, customer_id, item_id, qty, due_date, status)
                              values (%s, %s, %s, 100, current_date + 7, '지시완료')""", (self.p + "REQ", self.cust, self.fg))
            self.wo = ins("""insert into work_order (work_order_no, request_id, item_id, qty, equipment_code, status)
                             values (%s, %s, %s, 100, 'EQ01', '발행')""", (self.p + "WO1", self.req, self.fg))
            self.wo2 = ins("""insert into work_order (work_order_no, request_id, item_id, qty, equipment_code, status)
                              values (%s, %s, %s, 50, 'EQ01', '발행')""", (self.p + "WO2", self.req, self.fg))
        self.wo_no, self.wo2_no = self.p + "WO1", self.p + "WO2"

    # ── 화면이 부르는 HTTP 로 흐름 만들기 ──
    def receive(self, c: TestClient, *qtys, loc=None, item=None) -> list[str]:
        r = c.post("/mat/receipts", data={"supplier_name": "공급사 A (예시)", "item_id": [str(item or self.rm)] * len(qtys),
                                          "qty": [str(q) for q in qtys], "location_id": [str(loc or self.loc1)] * len(qtys),
                                          "supplier_lot_no": [""] * len(qtys)})
        assert r.status_code == 200, r.text
        return r.json()["lot_nos"]

    def pass_incoming(self, c: TestClient, lot_no: str, result: str = "합격") -> dict:
        r = c.post("/qc/incoming", data={"lot_no": lot_no, "result": result})
        assert r.status_code == 200, r.text
        return r.json()

    def issue(self, c: TestClient, lot_no: str, qty, wo_id=None, loc=None):
        return c.post("/mat/issues", data={"work_order_id": str(wo_id or self.wo), "lot_no": [lot_no],
                                           "location_id": [str(loc or self.loc1)], "qty": [str(qty)]})

    def daily(self, c: TestClient, good, wo_id=None, day="2026-10-20", eq="EQ01"):
        r = c.post("/prd/daily", data={"work_order_id": str(wo_id or self.wo), "work_date": day, "equipment_code": eq,
                                       "produced_qty": str(good + 5), "good_qty": str(good), "loss_qty": "5"})
        assert r.status_code == 200, r.text
        return r.json()["daily_id"]

    def product_receive(self, c: TestClient, qty=None, wo_id=None, loc=None) -> dict:
        data = {"work_order_id": str(wo_id or self.wo), "location_id": str(loc or self.loc1)}
        if qty is not None:
            data["qty"] = str(qty)
        r = c.post("/mat/product-receipts", data=data)
        assert r.status_code == 200, r.text
        return r.json()

    def ship(self, product_lot_no: str, qty, *, confirm: bool = True, loc=None) -> str:
        """출하(개발3 SHP)를 SQL 로 직접 — 지시 행 · 할당 · 확정(현재고 차감 · stock_move 출하)."""
        no = self.p + f"SHP{uuid.uuid4().hex[:4]}"
        loc = loc or self.loc1
        q = Decimal(str(qty))
        with conn.tx() as cur:
            cur.execute("select id from product_lot where lot_no = %s", (product_lot_no,))
            pid = cur.fetchone()["id"]
            cur.execute("""insert into shipment_order (shipment_no, request_id, customer_id, due_date, status, confirmed_at, confirmed_by)
                           values (%s, %s, %s, current_date + 7, %s, %s, %s) returning id""",
                        (no, self.req, self.cust, "확정" if confirm else "지시",
                         "now" if confirm else None, "sh" if confirm else None))
            sid = cur.fetchone()["id"]
            cur.execute("insert into shipment_line (shipment_order_id, product_lot_id, location_id, qty) values (%s, %s, %s, %s)",
                        (sid, pid, loc, q))
            if confirm:
                cur.execute("update lot_stock set qty = qty - %s where lot_kind = '제품' and lot_id = %s and location_id = %s",
                            (q, pid, loc))
                cur.execute("""insert into stock_move (move_kind, lot_kind, lot_id, from_location_id, qty, ref_table, ref_id)
                               values ('출하', '제품', %s, %s, %s, 'shipment_order', %s)""", (pid, loc, q, sid))
            else:
                cur.execute("update lot_stock set allocated_qty = allocated_qty + %s "
                            "where lot_kind = '제품' and lot_id = %s and location_id = %s", (q, pid, loc))
        return no

    def stock(self, kind: str, lot_no: str) -> list[dict]:
        table = "material_lot" if kind == "원자재" else "product_lot"
        return conn.q(f"""select s.location_id, s.qty, s.allocated_qty, s.status from lot_stock s join {table} t on t.id = s.lot_id
                           where s.lot_kind = %s and t.lot_no = %s order by s.location_id""", (kind, lot_no))

    # ── 정리 ──
    def cleanup(self) -> None:
        items = [self.rm, self.rm_off, self.fg]
        locs = [self.loc1, self.loc2]
        wos = [self.wo, self.wo2]
        with conn.tx() as cur:
            cur.execute("select id, lot_no, receipt_id from material_lot where item_id = any(%s)", (items,))
            mls = cur.fetchall()
            cur.execute("select id, lot_no from product_lot where item_id = any(%s)", (items,))
            pls = cur.fetchall()
            m_ids, p_ids = [r["id"] for r in mls], [r["id"] for r in pls]
            nos = [r["lot_no"] for r in mls] + [r["lot_no"] for r in pls]
            cur.execute("delete from notification where split_part(dedupe_key, ':', 2) = any(%s)", (nos,))
            cur.execute("select id from shipment_order where customer_id = %s", (self.cust,))
            s_ids = [r["id"] for r in cur.fetchall()]
            cur.execute("delete from shipment_line where shipment_order_id = any(%s) or product_lot_id = any(%s)", (s_ids, p_ids))
            cur.execute("delete from shipment_order where id = any(%s)", (s_ids,))
            cur.execute("""delete from stock_move where (lot_kind = '원자재' and lot_id = any(%s)) or (lot_kind = '제품' and lot_id = any(%s))
                              or from_location_id = any(%s) or to_location_id = any(%s)""", (m_ids, p_ids, locs, locs))
            cur.execute("set local session_replication_role = replica")   # 불변 이력 트리거 — 테스트가 만든 행만 지운다
            cur.execute("delete from stock_adjust where location_id = any(%s)", (locs,))
            cur.execute("set local session_replication_role = origin")
            cur.execute("delete from lot_stock where location_id = any(%s)", (locs,))
            cur.execute("delete from product_inspection where product_lot_id = any(%s)", (p_ids,))
            cur.execute("delete from incoming_inspection where material_lot_id = any(%s)", (m_ids,))
            cur.execute("delete from product_receipt where work_order_id = any(%s) or product_lot_id = any(%s)", (wos, p_ids))
            cur.execute("select distinct issue_id from material_issue_line where work_order_id = any(%s) or material_lot_id = any(%s)",
                        (wos, m_ids))
            i_ids = [r["issue_id"] for r in cur.fetchall()]
            cur.execute("delete from material_issue_line where issue_id = any(%s)", (i_ids,))
            cur.execute("delete from material_issue where id = any(%s)", (i_ids,))
            cur.execute("delete from product_lot where id = any(%s)", (p_ids,))
            cur.execute("delete from material_lot where id = any(%s)", (m_ids,))
            cur.execute("delete from material_receipt where id = any(%s)", (list({r["receipt_id"] for r in mls}),))
            cur.execute("delete from production_daily where work_order_id = any(%s)", (wos,))
            cur.execute("delete from inspection_daily where work_order_id = any(%s)", (wos,))
            cur.execute("delete from work_order where id = any(%s)", (wos,))
            cur.execute("delete from production_request where id = %s", (self.req,))
            cur.execute("delete from customer where id = %s", (self.cust,))
            cur.execute("delete from location where id = any(%s)", (locs,))
            cur.execute("delete from warehouse where id = %s", (self.wh,))
            cur.execute("delete from item where id = any(%s)", (items,))


@pytest.fixture
def world():
    w = World()
    try:
        yield w
    finally:
        w.cleanup()


@pytest.fixture(scope="module")
def pr() -> TestClient:
    return login("pr")       # 생산부 — 개발2 쓰기 화면의 W 칸


@pytest.fixture(scope="module")
def sh() -> TestClient:
    return login("sh")       # 출하실 — QC-020 · LOT 은 R, MAT · INV 쓰기는 칸 없음


@pytest.fixture(scope="module")
def sl() -> TestClient:
    return login("sl")       # 영업부 — MAT 칸 없음

