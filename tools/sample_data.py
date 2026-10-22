#!/usr/bin/env python
"""(예시) 샘플 데이터 — 화면에서 둘러볼 수 있게 업무 문서마다 약 N건(기본 100)을 **앱의 HTTP 를 거쳐** 쌓는다.

    uv run python tools/sample_data.py              넣기 (이미 `SMP-` 데이터가 있으면 안내하고 멈춘다)
    uv run python tools/sample_data.py --count 30   규모를 바꿔 넣기
    uv run python tools/sample_data.py --clean      `SMP-` 로 만든 것을 지운다

만드는 방법 — 업무 표에 SQL 로 직접 넣지 않는다. `fastapi.testclient.TestClient(lcomfine.app.main.app)` 로 부서 계정에
로그인해(영업부 sl · 생산부 pr · 출하실 sh · 회계부 ac) 화면 폼과 같은 칸으로 POST 한다 — 채번 · 재고 · 알림 · 감사 로그 ·
쓰기 경계가 계약대로 맞는다. 폼 칸 · 경로는 `tools/check_data.py` 의 `Flow` 와 같다. DB 는 다음 단계에 쓸 id 를 **읽기만** 한다.

흐름 — 거래처 · 품목(원자재 · 제품) · 창고/위치 → 생산의뢰 → 생산지시 → 원자재 입고 LOT(지시마다 1~2) → 입고검사 →
(일부 분할) → 불출 → 생산일보 · 검사일보 → 제품 입고 → 제품검사 판정 → (일부 분할) → 출하 지시 → 출하 확정(대부분) →
ERP 거래처 매핑 → ERP 수금 업로드(월 회차 · 지금 열 매핑 그대로).
다양성은 정해진 비율 + 고정 난수 시드(재현 가능): 미착수 의뢰 · 지시만 · 불출만 · 일보까지 · 판정 대기 · 제품 불합격 ·
출하 미확정 · 입고검사 불합격(보류) · 재판정 · 분할 LOT · 납기 지연 · 납기 임박 · ERP 오류 행 · 미매핑 코드 2.

지어내지 않는다 — 모든 이름에 `(예시)`, 코드 접두 `SMP-`. 규격(spec)은 비운다. 금액 · 수량은 난수 예시 값이다.
불변 이력(`stock_adjust` · `shipment_adjust`)은 만들지 않는다 — 그래서 `--clean` 이 일반 삭제로 지울 수 있다.
앱이 시각을 `now()` 로 찍는 칸(출하 확정 시각 · 재고 이동 시각 · 알림 · 감사 로그)은 실행 시각이 된다 — 폼이 받는 날짜 칸
(의뢰일 · 납기 · 생산 예정일 · 입고일 · 불출일 · 일보 일자 · 제품 입고일 · ERP 거래일)만 최근 약 6개월에 퍼뜨린다.
실패는 삼키지 않는다 — 응답이 기대와 다르면 단계 · 응답을 찍고 종료코드 1 로 멈춘다(그때까지 넣은 것은 `--clean` 으로 지운다).
"""
from __future__ import annotations

import argparse
import calendar
import io
import random
import sys
import time
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

P = "SMP-"                      # 모든 코드의 접두
SEED = 20261022                 # 난수 시드 고정 — 같은 날 같은 --count 면 같은 데이터
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# 의뢰의 운명(비율 · 합 1) — 나머지는 전부 출하 확정
FATES = [("의뢰만", 0.08), ("지시만", 0.04), ("불출까지", 0.03), ("일보까지", 0.03), ("판정 대기", 0.03),
         ("제품 불합격", 0.06), ("출하 미확정", 0.13)]
SHIPPED = "출하 확정"


class Failed(Exception):
    pass


# ════════════════════════════════════════════════════════════════════════════
# HTTP — 부서 계정으로 로그인한 TestClient
# ════════════════════════════════════════════════════════════════════════════
class Api:
    def __init__(self) -> None:
        from fastapi.testclient import TestClient

        from lcomfine.app.main import app
        from lcomfine.app.settings import get_settings

        self._TestClient, self._app = TestClient, app
        self._pw = get_settings().seed_password
        if not self._pw:
            raise Failed("LCOMFINE_SEED_PASSWORD 가 .env 에 없다 — 부서 계정으로 로그인할 수 없다")
        self._clients: dict[str, object] = {}
        self.calls = 0

    def _c(self, login: str):
        if login not in self._clients:
            cl = self._TestClient(self._app)
            resp = cl.post("/login", data={"login_id": login, "password": self._pw}, follow_redirects=False)
            if resp.status_code != 303:
                raise Failed(f"[로그인] {login} → {resp.status_code} (기대 303) {resp.text[:300]}")
            self._clients[login] = cl
        return self._clients[login]

    def post(self, step: str, login: str, path: str, data: dict, files: dict | None = None, expect: int = 200) -> dict:
        resp = self._c(login).post(path, data=data, files=files, follow_redirects=False)
        self.calls += 1
        try:
            body = resp.json()
        except Exception:  # noqa: BLE001 — 본문이 JSON 이 아니면 글자 그대로 실패 사유에 싣는다
            body = {"text": resp.text[:1000]}
        if resp.status_code != expect:
            raise Failed(f"[{step}] POST {path} ({login}) → {resp.status_code} (기대 {expect})\n  응답: {str(body)[:1500]}")
        return body


# ════════════════════════════════════════════════════════════════════════════
# DB 읽기 (다음 단계에 쓸 id · 범위 · 행 수) — 쓰기는 --clean 의 삭제뿐
# ════════════════════════════════════════════════════════════════════════════
def _conn():
    from lcomfine.db import conn

    return conn


def scope() -> dict[str, list]:
    """`SMP-` 로 만든 행의 id 묶음. 넣기 결과 집계와 --clean 이 함께 쓴다."""
    c = _conn()
    ids = lambda sql, p=(): [r["id"] for r in c.q(sql, p)]  # noqa: E731
    s: dict[str, list] = {}
    s["item"] = ids("select id from item where item_code like %s", (P + "%",))
    s["customer"] = ids("select id from customer where customer_code like %s", (P + "%",))
    s["warehouse"] = ids("select id from warehouse where warehouse_code like %s", (P + "%",))
    s["location"] = ids("select id from location where warehouse_id = any(%s)", (s["warehouse"],))
    s["production_request"] = ids("select id from production_request where customer_id = any(%s) or item_id = any(%s)",
                                  (s["customer"], s["item"]))
    s["work_order"] = ids("select id from work_order where request_id = any(%s) or item_id = any(%s)",
                          (s["production_request"], s["item"]))
    s["material_lot"] = ids("select id from material_lot where item_id = any(%s)", (s["item"],))
    s["material_receipt"] = ids("select distinct receipt_id as id from material_lot where id = any(%s) and receipt_id is not null",
                                (s["material_lot"],))
    s["material_issue_line"] = ids("select id from material_issue_line where work_order_id = any(%s) or material_lot_id = any(%s)",
                                   (s["work_order"], s["material_lot"]))
    s["material_issue"] = ids("select distinct issue_id as id from material_issue_line where id = any(%s)",
                              (s["material_issue_line"],))
    s["incoming_inspection"] = ids("select id from incoming_inspection where material_lot_id = any(%s)", (s["material_lot"],))
    s["production_daily"] = ids("select id from production_daily where work_order_id = any(%s)", (s["work_order"],))
    s["inspection_daily"] = ids("select id from inspection_daily where work_order_id = any(%s)", (s["work_order"],))
    s["work_sequence"] = ids("select id from work_sequence where work_order_id = any(%s)", (s["work_order"],))
    s["product_lot"] = ids("select id from product_lot where work_order_id = any(%s) or item_id = any(%s)",
                           (s["work_order"], s["item"]))
    s["product_receipt"] = ids("select id from product_receipt where product_lot_id = any(%s) or work_order_id = any(%s)",
                               (s["product_lot"], s["work_order"]))
    s["product_inspection"] = ids("select id from product_inspection where product_lot_id = any(%s)", (s["product_lot"],))
    s["shipment_order"] = ids("select id from shipment_order where customer_id = any(%s) or request_id = any(%s)",
                              (s["customer"], s["production_request"]))
    s["shipment_line"] = ids("select id from shipment_line where shipment_order_id = any(%s)", (s["shipment_order"],))
    s["lot_stock"] = ids("""select id from lot_stock where (lot_kind = '원자재' and lot_id = any(%s))
                              or (lot_kind = '제품' and lot_id = any(%s)) or location_id = any(%s)""",
                         (s["material_lot"], s["product_lot"], s["location"]))
    s["stock_move"] = ids("""select id from stock_move where (lot_kind = '원자재' and lot_id = any(%s))
                               or (lot_kind = '제품' and lot_id = any(%s))
                               or (ref_table = 'shipment_order' and ref_id = any(%s))""",
                          (s["material_lot"], s["product_lot"], s["shipment_order"]))
    s["stock_adjust"] = ids("""select id from stock_adjust where (lot_kind = '원자재' and lot_id = any(%s))
                                 or (lot_kind = '제품' and lot_id = any(%s)) or location_id = any(%s)""",
                            (s["material_lot"], s["product_lot"], s["location"]))
    s["shipment_adjust"] = ids("select id from shipment_adjust where shipment_order_id = any(%s) or product_lot_id = any(%s)",
                               (s["shipment_order"], s["product_lot"]))
    s["erp_customer_map"] = ids("select id from erp_customer_map where erp_code like %s or customer_id = any(%s)",
                                (P + "%", s["customer"]))
    s["erp_upload_batch"] = ids("select id from erp_upload_batch where source_file like %s", (P + "%",))
    s["erp_upload_row"] = ids("select id from erp_upload_row where batch_id = any(%s)", (s["erp_upload_batch"],))
    s["notification"] = _notification_ids(s)
    return s


def _notification_ids(s: dict[str, list]) -> list[int]:
    """샘플 문서 번호로 만든 알림 dedupe_key · ERP 오류 알림 link 로 찾는다(check_data 정리와 같은 키)."""
    from lcomfine.app import erp_upload

    c = _conn()
    col = lambda t, k, ids: [r[k] for r in c.q(f"select {k} from {t} where id = any(%s)", (ids,))]  # noqa: E731
    req = col("production_request", "request_no", s["production_request"])
    wo = col("work_order", "work_order_no", s["work_order"])
    ml = col("material_lot", "lot_no", s["material_lot"])
    pl = col("product_lot", "lot_no", s["product_lot"])
    sh = col("shipment_order", "shipment_no", s["shipment_order"])
    keys = ([f"request_created:{n}" for n in req] + [f"order_issued:{n}" for n in wo] + [f"material_received:{n}" for n in ml]
            + [f"product_received:{n}" for n in pl] + [f"shipment_ordered:{n}" for n in sh]
            + [f"shipment_confirmed:{n}" for n in sh])
    likes = [f"judged:{n}:%" for n in pl] + [f"due:{n}:%" for n in req]
    links = [erp_upload.error_link(b) for b in s["erp_upload_batch"]]
    return [r["id"] for r in c.q("""select id from notification
                                     where dedupe_key = any(%s) or dedupe_key like any(%s)
                                        or (event_key = 'erp_upload_error' and link = any(%s))""",
                                 (keys, likes or [""], links))]


ORDER = ["customer", "item", "warehouse", "location", "production_request", "work_order", "work_sequence",
         "material_receipt", "material_lot", "incoming_inspection", "material_issue", "material_issue_line",
         "production_daily", "inspection_daily", "product_receipt", "product_lot", "product_inspection",
         "lot_stock", "stock_move", "shipment_order", "shipment_line", "erp_customer_map", "erp_upload_batch",
         "erp_upload_row", "notification", "stock_adjust", "shipment_adjust"]


def print_counts(s: dict[str, list], title: str) -> None:
    print(f"\n{title}")
    print(f"  {'표':<22} {'행 수':>6}")
    for k in ORDER:
        print(f"  {k:<22} {len(s[k]):>6}")


# ════════════════════════════════════════════════════════════════════════════
# 넣기
# ════════════════════════════════════════════════════════════════════════════
class Builder:
    def __init__(self, n: int) -> None:
        self.n = n
        self.rnd = random.Random(SEED)
        self.api = Api()
        self.today = date.today()
        self.c = _conn()
        self.v: dict[str, object] = {}
        self.tally: dict[str, int] = {}

    # ── 작은 도구 ──
    def note(self, key: str, k: int = 1) -> None:
        self.tally[key] = self.tally.get(key, 0) + k

    def d(self, x: date) -> str:
        return min(x, self.today).isoformat()          # 폼에 넣는 과거 날짜 — 오늘을 넘기지 않는다

    def post(self, step, login, path, data, **kw):
        return self.api.post(step, login, path, data, **kw)

    # ── 기준정보 ──
    def base(self) -> None:
        n, rnd = self.n, self.rnd
        np_ = max(2, n // 2)
        nm = max(2, n - np_)
        self.customers: list[int] = []
        for i in range(1, n + 1):
            b = self.post("BAS-020 거래처 등록", "sl", "/bas/customers",
                          {"customer_code": f"{P}C{i:03d}", "customer_name": f"(예시) 거래처 {i:03d}"})
            self.customers.append(b["id"])
        self.mats: list[int] = []
        for i in range(1, nm + 1):
            b = self.post("BAS-010 품목 등록(원자재)", "pr", "/bas/items",
                          {"item_code": f"{P}M{i:03d}", "item_name": f"(예시) 원자재 {i:03d}", "item_type": "원자재", "unit": "KG"})
            self.mats.append(b["id"])
        self.prods: list[int] = []
        for i in range(1, np_ + 1):
            b = self.post("BAS-010 품목 등록(제품)", "pr", "/bas/items",
                          {"item_code": f"{P}P{i:03d}", "item_name": f"(예시) 제품 {i:03d}", "item_type": "제품", "unit": "EA"})
            self.prods.append(b["id"])
        # 제품마다 쓰는 원자재 1~2 (고정 짝)
        self.bom = {p: sorted({self.mats[k % len(self.mats)], self.mats[(k * 7 + 3) % len(self.mats)]})[: 1 + (k % 2)]
                    for k, p in enumerate(self.prods)}
        self.loc: dict[str, int] = {}
        for wcode, wname, locs in ((f"{P}W01", "(예시) 원자재 창고", [("L01", "원자재 위치 1"), ("L02", "원자재 위치 2 (분할)")]),
                                   (f"{P}W02", "(예시) 제품 창고", [("L11", "제품 위치 1"), ("L12", "제품 위치 2 (분할)")])):
            w = self.post("BAS-030 창고 등록", "pr", "/bas/warehouses",
                          {"target": "warehouse", "warehouse_code": wcode, "warehouse_name": wname})
            for lcode, lname in locs:
                b = self.post("BAS-030 위치 등록", "pr", "/bas/warehouses",
                              {"target": "location", "warehouse_id": str(w["id"]), "location_code": f"{P}{lcode}",
                               "location_name": f"(예시) {lname}"})
                self.loc[lcode] = b["id"]
        self.suppliers = [f"(예시) 공급사 {i:02d}" for i in range(1, 6)]
        self.equipment = [r["code"] for r in self.c.q(
            "select code from sys_common_code where group_code = '설비' and use_yn = 'Y' order by sort_no, code")]
        self.defects = [r["code"] for r in self.c.q(
            "select code from sys_common_code where group_code = '불량유형' and use_yn = 'Y' order by sort_no, code")]
        if not self.equipment:
            raise Failed("SYS-030 공통코드에 사용 중 설비가 없다 — 생산지시 · 일보를 넣을 수 없다")
        _ = rnd
        print(f"  기준정보: 거래처 {len(self.customers)} · 원자재 {len(self.mats)} · 제품 {len(self.prods)} · "
              f"창고 2 · 위치 {len(self.loc)}")

    # ── 운명 · 날짜 계획 ──
    def plan(self) -> list[dict]:
        n, rnd, T = self.n, self.rnd, self.today
        fates: list[str] = []
        for name, share in FATES:
            fates += [name] * max(1, round(n * share)) if n >= 20 else [name] * round(n * share)
        fates = fates[:n]
        fates += [SHIPPED] * (n - len(fates))
        rnd.shuffle(fates)
        plans = []
        for i in range(n):
            r = T - timedelta(days=180 - (180 * i) // max(1, n - 1)) + timedelta(days=rnd.randint(-2, 2))
            fate = fates[i]
            # 입고 → 불출 → 일보 → 제품 입고 사슬(최대 9일)이 오늘을 넘지 않게 — 같은 날 · 같은 설비 일보 중복을 막는다
            r = min(r, T if fate in ("의뢰만", "지시만") else T - timedelta(days=12))
            qty = rnd.randrange(100, 2001, 10)
            lead = rnd.randint(14, 40)
            natural = r + timedelta(days=lead)
            if fate == SHIPPED:
                # 확정 시각은 실행 시각(now) — 납기 준수가 현실적으로 보이게 대부분 오늘 이후, 일부(약 15%)는 지난 납기(지연 출하)
                if rnd.random() < 0.15 and r < T - timedelta(days=21):
                    due = max(r + timedelta(days=7), T - timedelta(days=rnd.randint(1, 20)))
                else:
                    due = max(natural, T + timedelta(days=rnd.randint(0, 30)))
            elif fate == "출하 미확정":
                k = rnd.random()
                due = (T + timedelta(days=rnd.randint(1, 3)) if k < 0.35 else          # 납기 D-3 임박 미출하
                       max(r + timedelta(days=7), T - timedelta(days=rnd.randint(1, 15))) if k < 0.7 else   # 지연
                       T + timedelta(days=rnd.randint(4, 30)))
            else:
                due = natural                       # 오래된 미완료 의뢰는 자연히 지연
            plans.append({"i": i + 1, "fate": fate, "r": r, "due": due, "qty": qty,
                          "customer": self.customers[rnd.randrange(len(self.customers))],
                          "item": self.prods[rnd.randrange(len(self.prods))],
                          "eq": self.equipment[rnd.randrange(len(self.equipment))]})
        return plans

    # ── 한 의뢰의 흐름 ──
    def flow(self, p: dict) -> None:
        rnd, fate = self.rnd, p["fate"]
        r = p["r"]
        # 1 생산의뢰 (영업부)
        b = self.post("WO-010 생산의뢰 등록", "sl", "/wo/requests",
                      {"customer_id": str(p["customer"]), "item_id": str(p["item"]), "qty": str(p["qty"]),
                       "due_date": p["due"].isoformat(), "request_date": self.d(r), "note": "(예시) 샘플 데이터"})
        req_id, req_no = b["id"], b["request_no"]
        self.note("생산의뢰")
        confirm = rnd.random() < 0.7
        if confirm:
            self.post("WO-010 의뢰 확정", "sl", f"/wo/requests/{req_id}",
                      {"customer_id": str(p["customer"]), "item_id": str(p["item"]), "qty": str(p["qty"]),
                       "due_date": p["due"].isoformat(), "status": "확정", "note": "(예시) 샘플 데이터"})
            self.note("의뢰 확정")
        if fate == "의뢰만":
            return
        # 2 생산지시 (생산부)
        planned = r + timedelta(days=rnd.randint(1, 3))
        b = self.post("WO-020 생산지시서 작성", "pr", "/wo/orders",
                      {"request_id": str(req_id), "qty": str(p["qty"]), "equipment_code": p["eq"],
                       "planned_on": planned.isoformat(), "note": "(예시) 샘플 데이터"})
        wo_no = b["work_order_no"]
        self.note("생산지시")
        # 3 원자재 입고 (생산부) — 제품의 원자재 1~2 LOT
        mats = self.bom[p["item"]]
        recv = r + timedelta(days=rnd.randint(1, 3))
        need = Decimal(p["qty"]) * Decimal("1.15")
        lots: list[dict] = []                        # {no, qty, loc}
        lines = [(m, int(need / len(mats)) + rnd.randint(5, 60)) for m in mats]
        b = self.post("MAT-010 원자재 입고", "pr", "/mat/receipts",
                      {"supplier_name": self.suppliers[rnd.randrange(len(self.suppliers))], "received_on": self.d(recv),
                       "note": "(예시) 샘플 데이터",
                       "item_id": [str(m) for m, _ in lines], "qty": [str(q) for _, q in lines],
                       "location_id": [str(self.loc["L01"])] * len(lines),
                       "supplier_lot_no": [f"{P}S{p['i']:03d}-{k + 1}" for k in range(len(lines))]})
        self.note("원자재 입고")
        received = [{"no": no, "qty": q, "item": m} for no, (m, q) in zip(b["lot_nos"], lines)]
        self.note("원자재 LOT", len(received))
        # 4 입고검사 (생산부) — 약 6% 불합격(보류) → 같은 원자재를 다시 입고해 합격
        leave_waiting = fate == "지시만" and rnd.random() < 0.5      # 일부는 검사대기로 남긴다
        for lot in received:
            if leave_waiting:
                continue
            if rnd.random() < 0.06:
                self.post("QC-010 입고검사 불합격", "pr", "/qc/incoming",
                          {"lot_no": lot["no"], "result": "불합격", "item_name": ["외관"], "item_value": ["(예시) 불량"],
                           "note": "(예시) 샘플 — 보류"})
                self.note("입고검사 불합격(보류)")
                b2 = self.post("MAT-010 원자재 재입고(불합격 대체)", "pr", "/mat/receipts",
                               {"supplier_name": self.suppliers[rnd.randrange(len(self.suppliers))],
                                "received_on": self.d(recv + timedelta(days=1)), "note": "(예시) 불합격 대체 입고",
                                "item_id": [str(lot["item"])], "qty": [str(lot["qty"])],
                                "location_id": [str(self.loc["L01"])], "supplier_lot_no": [f"{P}S{p['i']:03d}-R"]})
                self.note("원자재 입고")
                self.note("원자재 LOT")
                lot["no"] = b2["lot_nos"][0]
            self.post("QC-010 입고검사 합격", "pr", "/qc/incoming",
                      {"lot_no": lot["no"], "result": "합격", "item_name": ["외관"], "item_value": ["(예시) 양호"]})
            self.note("입고검사 합격")
            lots.append({"no": lot["no"], "qty": lot["qty"], "loc": self.loc["L01"]})
        if fate == "지시만":
            return
        # 4b 분할 (약 10%) — 첫 LOT 의 일부를 위치 2 로 나눠 옮긴다
        if rnd.random() < 0.10:
            first = lots[0]
            part = max(1, first["qty"] // 4)
            b = self.post("INV-020 원자재 LOT 분할", "pr", "/inv/moves",
                          {"lot_kind": "원자재", "lot_no": first["no"], "from_location_id": str(first["loc"]),
                           "to_location_id": str(self.loc["L02"]), "qty": str(part), "split": "1", "note": "(예시) 분할"})
            first["qty"] -= part
            lots.append({"no": b["lot_no"], "qty": part, "loc": self.loc["L02"]})
            self.note("원자재 분할 LOT")
        # 5 불출 (생산부) — LOT 마다 85~100%
        issued_on = recv + timedelta(days=rnd.randint(1, 3))
        iq = [max(1, (lot["qty"] * rnd.randint(85, 100)) // 100) for lot in lots]
        self.post("MAT-020 불출", "pr", "/mat/issues",
                  {"work_order_no": wo_no, "issued_on": self.d(issued_on), "note": "(예시) 샘플 데이터",
                   "lot_no": [lot["no"] for lot in lots], "location_id": [str(lot["loc"]) for lot in lots],
                   "qty": [str(q) for q in iq]})
        self.note("불출")
        if fate == "불출까지":
            return
        # 6 생산일보 · 검사일보 (생산부) — 1~2 일
        days = 1 if rnd.random() < 0.6 else 2
        produced = int(p["qty"] * rnd.uniform(1.0, 1.06))
        good_total = defect_total = 0
        work_day = issued_on
        for k in range(days):
            work_day = work_day + timedelta(days=1)
            prod = produced // days if k < days - 1 else produced - (produced // days) * (days - 1)
            loss = int(prod * rnd.uniform(0.01, 0.05))
            good = prod - loss
            self.post("PRD-010 생산일보", "pr", "/prd/daily",
                      {"work_order_no": wo_no, "work_date": self.d(work_day), "equipment_code": p["eq"],
                       "produced_qty": str(prod), "good_qty": str(good), "loss_qty": str(loss),
                       "run_minutes": str(rnd.randint(300, 540)), "stop_minutes": str(rnd.randint(0, 60)),
                       "note": "(예시) 샘플 데이터"})
            self.note("생산일보")
            defect = int(good * rnd.uniform(0, 0.02))
            ins = {"work_order_no": wo_no, "work_date": self.d(work_day), "inspected_qty": str(good),
                   "defect_qty": str(defect), "note": "(예시) 샘플 데이터"}
            if defect and self.defects:
                ins.update(defect_code=[self.defects[rnd.randrange(len(self.defects))]], defect_code_qty=[str(defect)])
            self.post("INS-010 검사일보", "pr", "/ins/daily", ins)
            self.note("검사일보")
            good_total += good
            defect_total += defect
        if fate == "일보까지":
            return
        # 7 제품 입고 (생산부) — 약 15% 는 두 LOT 로
        net = good_total - defect_total
        parts = [net] if rnd.random() < 0.85 or net < 20 else [net * 6 // 10, net - net * 6 // 10]
        plots: list[dict] = []
        recv_p = work_day + timedelta(days=rnd.randint(0, 1))
        for q in parts:
            b = self.post("MAT-030 제품 입고", "pr", "/mat/product-receipts",
                          {"work_order_no": wo_no, "qty": str(q), "location_id": str(self.loc["L11"]),
                           "received_on": self.d(recv_p), "note": "(예시) 샘플 데이터"})
            plots.append({"no": b["lot_no"], "id": b["product_lot_id"]})
            self.note("제품 LOT")
        if fate == "판정 대기":
            return
        # 8 제품검사 판정 (생산부)
        if fate == "제품 불합격":
            for pl in plots:
                self.post("QC-020 제품검사 불합격", "pr", "/qc/product",
                          {"lot_no": pl["no"], "result": "불합격", "item_name": ["외관"], "item_value": ["(예시) 불량"],
                           "note": "(예시) 샘플 — 보류"})
                self.note("제품검사 불합격(보류)")
            return
        rejudge = rnd.random() < 0.04
        for pl in plots:
            if rejudge:
                self.post("QC-020 제품검사 불합격(재판정 전)", "pr", "/qc/product",
                          {"lot_no": pl["no"], "result": "불합격", "note": "(예시) 샘플 — 재판정 대상"})
                self.post("QC-020 제품 재판정 합격", "pr", f"/qc/product/{pl['id']}",
                          {"result": "합격", "note": "(예시) 샘플 — 재판정"})
                self.note("제품 재판정")
            else:
                self.post("QC-020 제품검사 합격", "pr", "/qc/product",
                          {"lot_no": pl["no"], "result": "합격", "item_name": ["외관"], "item_value": ["(예시) 양호"]})
            self.note("제품검사 합격")
        # 8b 제품 분할 (약 6%)
        if rnd.random() < 0.06:
            pl0 = plots[0]
            row = self.c.q1("""select s.qty from lot_stock s where s.lot_kind = '제품' and s.lot_id = %s and s.location_id = %s""",
                            (pl0["id"], self.loc["L11"]))
            part = int(row["qty"]) * 3 // 10 if row else 0
            if part >= 1:
                self.post("INV-020 제품 LOT 분할", "pr", "/inv/moves",
                          {"lot_kind": "제품", "lot_no": pl0["no"], "from_location_id": str(self.loc["L11"]),
                           "to_location_id": str(self.loc["L12"]), "qty": str(part), "split": "1", "note": "(예시) 분할"})
                self.note("제품 분할 LOT")
        # 9 출하 지시 (영업부 대부분 · 일부 출하실) — 약 40% 는 두 번에 나눠 출하
        stock = self._available(p["item"], plots)
        total = sum(a for _, a in stock)
        ship_qty = min(total, Decimal(p["qty"]))
        two = rnd.random() < 0.40 and ship_qty >= 20
        amounts = [ship_qty] if not two else [ship_qty * 6 // 10, ship_qty - ship_qty * 6 // 10]
        for k, amt in enumerate(amounts):
            lines = self._take(stock, amt)
            who = "sl" if rnd.random() < 0.8 else "sh"
            b = self.post("SHP-010 출하 지시 등록", who, "/shp/orders",
                          {"request_no": req_no, "note": "(예시) 샘플 데이터",
                           "stock_id": [str(sid) for sid, _ in lines], "qty": [str(q) for _, q in lines]})
            self.note("출하 지시")
            # 10 출하 확정 (출하실) — 미확정 운명은 둘 다 지시로 남기고, 나눈 출하의 둘째는 40% 남긴다
            if fate == "출하 미확정" or (k == 1 and rnd.random() < 0.4):
                self.note("출하 미확정(지시)")
                continue
            self.post("SHP-020 출하 확정", "sh", f"/shp/confirm/{b['id']}/confirm", {})
            self.note("출하 확정")

    def _available(self, item_id: int, plots: list[dict]) -> list[list]:
        """이 지시의 제품 LOT(분할 자식 포함) 가용 재고 행 — [[stock_id, 가용]]."""
        rows = self.c.q("""select s.id, s.qty - s.allocated_qty as a
                             from lot_stock s join product_lot p on p.id = s.lot_id
                            where s.lot_kind = '제품' and s.status = '가용' and s.qty - s.allocated_qty > 0
                              and (p.id = any(%(ids)s) or p.parent_lot_id = any(%(ids)s))
                            order by s.id""", {"ids": [pl["id"] for pl in plots]})
        return [[r["id"], Decimal(r["a"])] for r in rows]

    @staticmethod
    def _take(stock: list[list], amount: Decimal) -> list[tuple[int, Decimal]]:
        out, left = [], Decimal(amount)
        for row in stock:
            if left <= 0:
                break
            q = min(row[1], left)
            if q > 0:
                out.append((row[0], q))
                row[1] -= q
                left -= q
        return out

    # ── ERP 수금 ──
    def erp(self) -> None:
        from openpyxl import Workbook

        from lcomfine.app import erp_upload

        rnd, T = self.rnd, self.today
        cmap = erp_upload.column_map()
        need = ("customer_code", "txn_date", "sales_amount", "collected_amount")
        if not all(cmap.get(f) for f in need):
            raise Failed(f"ERP 열 매핑(COL-010)에 {', '.join(erp_upload.FIELDS[f] for f in need if not cmap.get(f))} 이(가) 없다 — "
                         "열 매핑은 바꾸지 않으므로 업로드를 넣지 않는다")
        fields = [f for f in erp_upload.FIELDS if cmap.get(f)]
        heads = [cmap[f] for f in fields]
        # COL-030 거래처 코드 매핑 — 거래처마다 ERP 코드 하나(SMP-E001 …). SMP-E901 · SMP-E902 는 매핑하지 않는다(미매핑)
        for k, cid in enumerate(self.customers, 1):
            self.post("COL-030 거래처 코드 매핑", "ac", "/col/customer-map",
                      {"erp_code": f"{P}E{k:03d}", "erp_name": f"(예시) ERP 거래처 {k:03d}", "customer_id": str(cid)})
        self.note("ERP 거래처 매핑", len(self.customers))
        unmapped = [f"{P}E901", f"{P}E902"]
        methods = [r["code_name"] for r in self.c.q(
            "select code_name from sys_common_code where group_code = '수금수단' and use_yn = 'Y' order by sort_no, code")] \
            or ["(예시) 수단"]
        # 6개월 회차 — 이번 달 포함 최근 6개월, 행 합 = n
        months = []
        y, m = T.year, T.month
        for _ in range(6):
            months.append((y, m))
            y, m = (y - 1, 12) if m == 1 else (y, m - 1)
        months.reverse()
        per = [self.n // 6 + (1 if k < self.n % 6 else 0) for k in range(6)]
        special = {0: "date", 1: "amount", 2: "missing", 3: "unmapped0", 4: "unmapped1", 5: "unmapped0"}   # 오류 · 미매핑 행 (회차마다 하나)
        for k, ((yy, mm), cnt) in enumerate(zip(months, per)):
            if cnt <= 0:
                continue
            first = date(yy, mm, 1)
            last = date(yy, mm, calendar.monthrange(yy, mm)[1])
            rows = []
            age = (T - first).days
            for j in range(cnt):
                day = first + timedelta(days=rnd.randint(0, (min(last, T) - first).days))
                code = f"{P}E{rnd.randint(1, len(self.customers)):03d}"
                sales = rnd.randrange(500_000, 15_000_001, 10_000)
                frac = rnd.choice([0, 0.3, 0.5, 1, 1] if age > 60 else [0, 0, 0.3, 0.5, 1])
                coll = int(sales * frac) // 10_000 * 10_000
                method = methods[rnd.randrange(len(methods))] if coll else ""
                bill_due = (day + timedelta(days=rnd.choice([60, 90]))).isoformat() if coll and method == methods[-1] else ""
                vals = {"customer_code": code, "txn_date": day.isoformat(), "sales_amount": str(sales),
                        "collected_amount": str(coll), "balance_amount": str(sales - coll), "method": method,
                        "bill_due_date": bill_due}
                if j == 0 and k in special:
                    kind = special[k]
                    if kind == "date":
                        vals["txn_date"] = f"{yy}/13/{day.day:02d}"          # 날짜 형식 오류
                    elif kind == "amount":
                        vals["sales_amount"] = "(예시) 금액 오류"              # 숫자 형식 오류
                    elif kind == "missing":
                        vals["customer_code"] = ""                           # 필수 누락
                    else:
                        vals["customer_code"] = unmapped[int(kind[-1])]       # 미매핑 ERP 코드
                rows.append([vals[f] for f in fields])
            wb = Workbook()
            ws = wb.active
            ws.append(heads)
            for row in rows:
                ws.append(row)
            buf = io.BytesIO()
            wb.save(buf)
            name = f"{P}ERP-{yy}-{mm:02d} (예시).xlsx"
            if self.c.q1("select 1 from erp_upload_batch where period_from = %s and period_to = %s and status = '반영'", (first, last)):
                raise Failed(f"기준 기간 {first}~{last} 에 이미 반영 회차가 있다 — 샘플이 그 회차를 교체하지 않도록 멈춘다")
            b = self.post("COL-010 ERP 수금 업로드", "ac", "/col/uploads",
                          {"action": "apply", "period_from": first.isoformat(), "period_to": last.isoformat()},
                          files={"file": (name, buf.getvalue(), XLSX_MIME)})
            self.note("ERP 회차")
            self.note("ERP 행", b["rows"])
            self.note("ERP 오류·미매핑 행", b["errors"])
            print(f"  ERP {b['batch_no']} {first}~{last} · 행 {b['rows']} · 오류·미매핑 {b['errors']}")

    def run(self) -> None:
        t0 = time.time()
        print("기준정보 …")
        self.base()
        plans = self.plan()
        print(f"흐름 {len(plans)} 건 …  (운명: " + " · ".join(f"{f} {sum(1 for p in plans if p['fate'] == f)}"
                                                       for f in [x for x, _ in FATES] + [SHIPPED]) + ")")
        for k, p in enumerate(plans, 1):
            self.flow(p)
            if k % 10 == 0 or k == len(plans):
                print(f"  {k}/{len(plans)} · HTTP {self.api.calls} · {time.time() - t0:.0f}s")
        print("ERP 수금 …")
        self.erp()
        el = time.time() - t0
        print("\n단계 집계 (HTTP 응답 기준)")
        for k, v in self.tally.items():
            print(f"  {k:<20} {v:>6}")
        print_counts(scope(), "표마다 넣은 행 수 (SMP- 범위 · DB 에서 다시 셈)")
        print(f"\n완료 — HTTP {self.api.calls} 회 · {el:.1f}초 · 난수 시드 {SEED} · --count {self.n}")
        print("앱이 now() 로 찍는 칸(출하 확정 시각 · 재고 이동 · 알림 · 감사 로그)은 실행 시각이다.")


def existing() -> dict[str, int]:
    c = _conn()
    q = lambda sql: c.q1(sql, (P + "%",))["n"]  # noqa: E731
    found = {"item": q("select count(*) as n from item where item_code like %s"),
             "customer": q("select count(*) as n from customer where customer_code like %s"),
             "warehouse": q("select count(*) as n from warehouse where warehouse_code like %s"),
             "erp_customer_map": q("select count(*) as n from erp_customer_map where erp_code like %s"),
             "erp_upload_batch": q("select count(*) as n from erp_upload_batch where source_file like %s")}
    return {k: v for k, v in found.items() if v}


# ════════════════════════════════════════════════════════════════════════════
# 지우기 (--clean)
# ════════════════════════════════════════════════════════════════════════════
def clean() -> int:
    s = scope()
    total = sum(len(v) for v in s.values())
    if not total:
        print("지울 SMP- 샘플 데이터가 없다.")
        return 0
    if s["stock_adjust"] or s["shipment_adjust"]:
        print(f"멈춤 — 불변 이력 stock_adjust {len(s['stock_adjust'])} · shipment_adjust {len(s['shipment_adjust'])} 행이 샘플 LOT · 출하를 "
              "가리킨다(트리거가 삭제를 막는다). 아무것도 지우지 않았다.")
        return 1
    print_counts(s, "지울 행 수 (SMP- 범위)")
    c = _conn()
    with c.tx() as cur:
        d = lambda t: cur.execute(f"delete from {t} where id = any(%s)", (s[t],))  # noqa: E731
        d("notification")
        d("stock_move")
        d("shipment_line")
        d("shipment_order")
        d("product_inspection")
        d("incoming_inspection")
        d("lot_stock")
        d("product_receipt")
        cur.execute("delete from product_lot where id = any(%s) and parent_lot_id is not null", (s["product_lot"],))
        d("product_lot")
        d("production_daily")
        d("inspection_daily")
        d("material_issue_line")
        d("material_issue")
        cur.execute("delete from material_lot where id = any(%s) and parent_lot_id is not null", (s["material_lot"],))
        d("material_lot")
        d("material_receipt")
        d("work_sequence")
        d("work_order")
        d("production_request")
        d("erp_upload_row")
        d("erp_upload_batch")
        d("erp_customer_map")
        d("location")
        d("warehouse")
        d("customer")
        d("item")
    left = existing()
    print(f"\n지웠다 — 남은 SMP- 기준정보 · ERP {left or 0}")
    print("남기는 것: 감사 로그(sys_change_log) · 접속 로그(sys_access_log) · 채번 카운터 — 지운 문서의 기록으로 남아도 된다.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="(예시) 샘플 데이터 넣기 · 지우기 — 앱 HTTP 를 거친다")
    ap.add_argument("--count", type=int, default=100, help="거래처 · 의뢰 · ERP 행 수(기본 100). 품목은 원자재 N/2 · 제품 N/2")
    ap.add_argument("--clean", action="store_true", help="SMP- 로 만든 것을 지운다")
    a = ap.parse_args(argv)
    try:
        if a.clean:
            return clean()
        if a.count < 6:
            print("--count 는 6 이상이어야 한다(ERP 6개월 회차).")
            return 2
        found = existing()
        if found:
            print(f"이미 SMP- 샘플 데이터가 있다 — {found}. 두 번 넣지 않는다. "
                  "다시 넣으려면 먼저 `uv run python tools/sample_data.py --clean`.")
            return 1
        Builder(a.count).run()
        return 0
    except Failed as exc:
        print(f"\n실패 — 멈춘다\n{exc}\n(그때까지 넣은 것은 `uv run python tools/sample_data.py --clean` 으로 지운다)", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
