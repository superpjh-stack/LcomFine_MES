#!/usr/bin/env python
"""(예시) 샘플 데이터 — 화면에서 둘러볼 수 있게 업무 문서마다 약 N건(기본 100)을 **앱의 HTTP 를 거쳐** 쌓는다.

    uv run python tools/sample_data.py              넣기 (이미 `SMP-` 데이터가 있으면 안내하고 멈춘다)
    uv run python tools/sample_data.py --count 30   규모를 바꿔 넣기
    uv run python tools/sample_data.py --clean      `SMP-` 로 만든 것을 지운다
    uv run python tools/sample_data.py --retime     이미 넣은 샘플의 시스템 시각만 업무 날짜에 다시 맞춘다(넣기 끝에서도 자동)

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
폼이 받는 날짜 칸(의뢰일 · 납기 · 생산 예정일 · 입고일 · 불출일 · 일보 일자 · 제품 입고일 · ERP 거래일)은 최근 약 6개월에 퍼뜨린다.
앱이 `now()` 로 찍는 칸(등록 시각 · 판정 시각 · 재고 이동 · 출하 확정 · 알림 · ERP 업로드 시각)은 넣은 직후 「시각 맞추기」
(`retime` · 직접 UPDATE — 이유는 그 docstring)가 업무 날짜에 맞춰 과거로 옮긴다. 감사 로그 · 접속 로그는 실제 넣은 시각 그대로다.
실패는 삼키지 않는다 — 응답이 기대와 다르면 단계 · 응답을 찍고 종료코드 1 로 멈춘다(그때까지 넣은 것은 `--clean` 으로 지운다).
"""
from __future__ import annotations

import argparse
import calendar
import io
import random
import sys
import time
from datetime import date, datetime, timedelta
from datetime import time as dtime
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
# DB 읽기 (다음 단계에 쓸 id · 범위 · 행 수) — 쓰기는 --clean 의 삭제 · 시각 맞추기의 시각 칸 UPDATE 뿐
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
        """의뢰마다 운명 · 의뢰일 · 흐름 날짜 간격 · 납기를 정한다.

        의뢰일은 최근 180일에 고르게 놓고, 오래된 것은 끝난 흐름(출하 확정 · 제품 불합격), 최근 것은 진행 중(의뢰만 · 지시만 ·
        불출까지 · 일보까지 · 판정 대기 · 출하 미확정)이 되게 날짜 순으로 운명을 놓는다. 흐름 날짜(입고 · 불출 · 일보 · 제품 입고)는
        여기서 정해 `flow` 가 그대로 쓴다 — 그래서 제품 입고일 P 를 미리 안다. 납기는 「시각 맞추기」(`retime`)가 실제 확정 시각을
        놓는 규칙에 맞춘다: 정시 출하 = 납기 > P (retime 이 마지막 확정을 납기 − 0~10일에 놓는다) · 지연 출하 = 납기 ≤ P
        (retime 이 P + 1~8일에 확정 → 1~20일 지연). 미출하 · 진행 중은 오늘 근처(지난 것 약 25% · D-3 임박 약 30%).
        """
        n, rnd, T = self.n, self.rnd, self.today
        early = ("의뢰만", "지시만")                         # 원자재 입고 전에 멈추는 운명 — 오늘 가까이 둘 수 있다
        open_ = ("불출까지", "일보까지", "판정 대기", "출하 미확정")
        counts = {name: (max(1, round(n * share)) if n >= 20 else round(n * share)) for name, share in FATES}
        a = [f for f in early for _ in range(counts[f])]
        b = [f for f in open_ for _ in range(counts[f])]
        rest = ["제품 불합격"] * counts["제품 불합격"]
        rest += [SHIPPED] * max(0, n - len(a) - len(b) - len(rest))
        for x in (a, b, rest):
            rnd.shuffle(x)
        # 날짜 오름차순 — 오래된 것은 끝난 흐름. 그 뒤 구간은 끝난 것과 진행 중(b)이 반씩, 가장 최근 구간은 끝난 것과 착수 전(a)이
        # 반씩 섞인다(끝난 흐름은 오늘 − 14일 이전으로 당긴다 — 사슬이 오늘을 넘지 않게)
        na, nb = min(len(a), len(rest) // 3), min(len(b), len(rest) // 3)
        head, mid, tail = rest[:len(rest) - na - nb], rest[len(rest) - na - nb:len(rest) - na] + b, rest[len(rest) - na:] + a
        rnd.shuffle(mid)
        rnd.shuffle(tail)
        fates = (head + mid + tail)[:n]
        plans = []
        for i in range(n):
            fate = fates[i]
            r = T - timedelta(days=180 - (180 * i) // max(1, n - 1)) + timedelta(days=rnd.randint(-2, 2))
            # 입고 → 불출 → 일보 → 제품 입고 사슬(최대 12일)이 오늘을 넘지 않게 — 같은 날 · 같은 설비 일보 중복을 막는다
            r = min(r, T if fate in early else T - timedelta(days=14))
            qty = rnd.randrange(100, 2001, 10)
            g = {"recv": rnd.randint(1, 4), "issue": rnd.randint(1, 4), "days": 1 if rnd.random() < 0.6 else 2,
                 "prd": rnd.randint(0, 2)}
            P_ = r + timedelta(days=g["recv"] + g["issue"] + g["days"] + g["prd"])      # 제품 입고일
            if fate == SHIPPED:
                if rnd.random() < 0.15 and (P_ - r).days >= 4:
                    due = P_ - timedelta(days=rnd.randint(0, min(12, (P_ - r).days - 4)))   # 지연 출하 — 납기 ≤ P
                else:
                    conf = min(P_ + timedelta(days=rnd.randint(2, 25)), T)                     # 정시 — 확정 + 0~10일
                    due = max(conf + timedelta(days=rnd.randint(0, 10)), P_ + timedelta(days=1))
            elif fate == "제품 불합격":
                due = r + timedelta(days=rnd.randint(14, 40))      # 끝난(막힌) 흐름 — 오래된 것은 지연으로 남는다
            else:                                                  # 진행 중 · 출하 미확정 — 납기는 오늘 근처
                k = rnd.random()
                due = (T + timedelta(days=rnd.randint(1, 3)) if k < 0.3 else                  # 납기 D-3 임박
                       max(r + timedelta(days=7), T - timedelta(days=rnd.randint(1, 15))) if k < 0.55 else   # 지난 납기(지연)
                       max(r + timedelta(days=7), T + timedelta(days=rnd.randint(4, 30))))
            plans.append({"i": i + 1, "fate": fate, "r": r, "due": due, "qty": qty, "g": g,
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
        g = p["g"]
        recv = r + timedelta(days=g["recv"])
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
        issued_on = recv + timedelta(days=g["issue"])
        iq = [max(1, (lot["qty"] * rnd.randint(85, 100)) // 100) for lot in lots]
        self.post("MAT-020 불출", "pr", "/mat/issues",
                  {"work_order_no": wo_no, "issued_on": self.d(issued_on), "note": "(예시) 샘플 데이터",
                   "lot_no": [lot["no"] for lot in lots], "location_id": [str(lot["loc"]) for lot in lots],
                   "qty": [str(q) for q in iq]})
        self.note("불출")
        if fate == "불출까지":
            return
        # 6 생산일보 · 검사일보 (생산부) — 1~2 일
        days = g["days"]
        produced = int(p["qty"] * rnd.uniform(1.08, 1.15))      # 손실 · 불량을 빼고도 의뢰 수량 이상 — 완납 출하가 되게
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
        recv_p = work_day + timedelta(days=g["prd"])
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
            if fate == "출하 미확정" or (k == 1 and p["due"] >= self.today and rnd.random() < 0.4):   # 나눈 출하의 남은 지시는 납기 전인 것만
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
        retime()
        print("감사 로그 · 접속 로그 · 납기 D-3 알림은 실제 넣은 시각 그대로다.")


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
# 시각 맞추기 (--retime · 넣기 끝에서 자동)
# ════════════════════════════════════════════════════════════════════════════
class Clock:
    """한 의뢰의 흐름 시계 — 앞으로만 간다(단조) · `cap`(지금 직전)을 넘지 않는다."""

    def __init__(self, rnd: random.Random, tz, cap: datetime, start: datetime) -> None:
        self.rnd, self.tz, self.cap, self.t = rnd, tz, cap, start

    def on(self, d: date, lo: int = 9, hi: int = 17) -> datetime:
        """업무 날짜 `d` 의 lo~hi 시 사이 — 직전 사건보다 앞이면 직전 + 몇 분."""
        base = datetime.combine(d, dtime(0), tzinfo=self.tz) + timedelta(minutes=self.rnd.randint(lo * 60, hi * 60))
        self.t = min(max(base, self.t + timedelta(minutes=self.rnd.randint(3, 40))), max(self.cap, self.t))
        return self.t

    def later(self, d0: int, d1: int, lo: int = 9, hi: int = 17) -> datetime:
        """직전 사건 날짜 + d0~d1 일."""
        return self.on(self.t.date() + timedelta(days=self.rnd.randint(d0, d1)), lo, hi)


def retime() -> int:
    """앱이 저장 순간에 `now()` 로 찍은 시스템 시각을 그 문서의 **업무 날짜**에 맞춰 과거로 옮긴다 — `SMP-` 범위의 행만 · 한 트랜잭션.

    왜 직접 UPDATE 인가 — 샘플은 HTTP 로 오늘 한꺼번에 넣으므로 생산지시 `created_at` · 출하 확정 `confirmed_at` · 재고 이동
    `moved_at` · 판정 `inspected_at` · 알림 `created_at` 이 전부 오늘이 된다. 그러면 RPT-070 「지시 → 생산 완료」 가 음수가 되고
    월별 확정 출하(RPT-050 · 060 · COL-070)가 이번 달에 몰린다. 앱에는 이 시각을 과거로 받는 폼이 없다(받아서도 안 된다).
    그래서 샘플 도구에 한해 넣은 뒤 그 칸만 고친다 — 업무 값(수량 · 상태 · 업무 날짜 · 번호)은 건드리지 않는다.

    순서(의뢰마다 난수 시드 고정 · 단조): 의뢰일 ≤ 지시 ≤ 원자재 입고 · 입고검사 ≤ (분할) ≤ 불출 ≤ 생산일보 · 검사일보 ≤ 제품 입고
    ≤ 판정(재판정) ≤ (분할) ≤ 출하 지시 ≤ 출하 확정. 업무 날짜가 있는 단계는 그 날짜, 없는 단계(검사 · 판정 · 출하)는 앞 단계 + 0~5일.
    지금을 넘지 않는다. 마지막 확정은 납기 > 제품 입고일이면 납기 − 0~10일(정시), 아니면 제품 입고일 + 1~8일(지연 — `plan` 의
    납기 규칙과 짝).
    옮기지 않는 것 — 감사 로그(`sys_change_log` · `sys_access_log` · 실제로 넣은 시각이 맞다) · 납기 D-3 알림(오늘 돈 배치) ·
    불변 이력(`stock_adjust` · `shipment_adjust` — 샘플은 만들지 않는다) · 채번 카운터. 여러 번 돌려도 같은 결과다.
    """
    s = scope()
    if not s["production_request"]:
        print("시각을 맞출 SMP- 샘플 데이터가 없다.")
        return 0
    c = _conn()
    now = c.q1("select now() as n")["n"]
    tz, cap = now.tzinfo, now - timedelta(minutes=5)
    today = cap.date()
    rnd = random.Random(SEED + 1)
    by = lambda rows, k: {r[k]: r for r in rows}  # noqa: E731

    def rows(table: str, cols: str) -> list[dict]:
        return c.q(f"select {cols} from {table} where id = any(%s) order by id", (s[table],))

    def group(rs: list[dict], k: str) -> dict:
        out: dict = {}
        for r in rs:
            out.setdefault(r[k], []).append(r)
        return out

    reqs = rows("production_request", "id, request_no, request_date, due_date")
    wos = group(rows("work_order", "id, work_order_no, request_id, planned_on"), "request_id")
    mlots = rows("material_lot", "id, lot_no, receipt_id, supplier_lot_no, parent_lot_id")
    receipts = by(rows("material_receipt", "id, received_on"), "id")
    iinsp = group(rows("incoming_inspection", "id, material_lot_id, seq"), "material_lot_id")
    ilines = group(rows("material_issue_line", "id, issue_id, material_lot_id, work_order_id"), "work_order_id")
    issues = by(rows("material_issue", "id, issued_on"), "id")
    moves = rows("stock_move", "id, move_kind, lot_kind, lot_id, source_lot_id, ref_table, ref_id")
    pdaily = group(rows("production_daily", "id, work_order_id, work_date"), "work_order_id")
    idaily = group(rows("inspection_daily", "id, work_order_id, work_date"), "work_order_id")
    wseq = group(rows("work_sequence", "id, work_order_id"), "work_order_id")
    plots = rows("product_lot", "id, lot_no, work_order_id, parent_lot_id")
    preceipts = group(rows("product_receipt", "id, product_lot_id, work_order_id, received_on"), "work_order_id")
    pinsp = group(rows("product_inspection", "id, product_lot_id, seq"), "product_lot_id")
    sorders = group(rows("shipment_order", "id, shipment_no, request_id, status, due_date"), "request_id")
    slines = group(rows("shipment_line", "id, shipment_order_id, product_lot_id"), "shipment_order_id")

    # 원자재 LOT → 의뢰 순번(공급사 LOT 번호 SMP-S{i:03d}-… · 분할 자식은 원 LOT 의 것을 물려받는다)
    req_by_i = {k: r["id"] for k, r in enumerate(reqs, 1)}
    mlot_by_req: dict[int, list[dict]] = {}
    for m in mlots:
        i = int(m["supplier_lot_no"][len(P) + 1:].split("-")[0])
        mlot_by_req.setdefault(req_by_i[i], []).append(m)
    split_m = group([m for m in moves if m["move_kind"] == "분할" and m["lot_kind"] == "원자재"], "source_lot_id")
    split_p = group([m for m in moves if m["move_kind"] == "분할" and m["lot_kind"] == "제품"], "source_lot_id")
    issue_moves = group([m for m in moves if m["ref_table"] == "material_issue_line"], "ref_id")
    ship_moves = group([m for m in moves if m["ref_table"] == "shipment_order"], "ref_id")
    plot_by_wo = group([p for p in plots if p["parent_lot_id"] is None], "work_order_id")
    plot_no = {p["id"]: p["lot_no"] for p in plots}
    plot_root = {p["id"]: p["parent_lot_id"] or p["id"] for p in plots}

    T: dict[str, dict[int, datetime]] = {k: {} for k in s}     # 표 → id → 새 created_at(또는 그 표의 시각 칸)
    conf: dict[int, datetime] = {}                                # shipment_order.confirmed_at
    touch: dict[tuple[str, int], datetime] = {}                   # (LOT 구분, lot id) → 마지막으로 건드린 시각
    nkey: dict[str, datetime] = {}                                # 알림 dedupe_key → 발생 시각
    nhandled: dict[str, datetime] = {}                            # 알림 dedupe_key → 처리 시각
    last: dict[str, dict[int, datetime]] = {"production_request": {}, "work_order": {}}
    first_ship_of_lot: dict[int, datetime] = {}

    def tch(kind: str, lot_id: int, t: datetime) -> None:
        touch[(kind, lot_id)] = max(t, touch.get((kind, lot_id), t))

    def handled(key: str, t: datetime) -> None:
        nhandled.setdefault(key, t)

    for rq in reqs:
        R = rq["request_date"]
        ck = Clock(rnd, tz, cap, datetime.combine(R, dtime(8), tzinfo=tz))
        tr = ck.on(R, 9, 11)
        T["production_request"][rq["id"]] = tr
        nkey[f"request_created:{rq['request_no']}"] = tr
        for wo in wos.get(rq["id"], []):
            lots = sorted(mlot_by_req.get(rq["id"], []), key=lambda m: m["id"])
            roots = [m for m in lots if m["parent_lot_id"] is None]
            rec_ids = sorted({m["receipt_id"] for m in roots})
            lines = ilines.get(wo["id"], [])
            issue_ids = sorted({ln["issue_id"] for ln in lines})
            issued_on = min((issues[x]["issued_on"] for x in issue_ids), default=None)
            upper = min([wo["planned_on"]] + [receipts[x]["received_on"] for x in rec_ids])
            tw = ck.on(R + timedelta(days=rnd.randint(0, max(0, (upper - R).days))), 9, 17)
            T["work_order"][wo["id"]] = tw
            for ws in wseq.get(wo["id"], []):
                T["work_sequence"][ws["id"]] = tw
            nkey[f"order_issued:{wo['work_order_no']}"] = tw
            handled(f"request_created:{rq['request_no']}", tw)
            # 원자재 입고 → 입고검사 (입고 회차 순 · 불합격 대체 입고는 다음 날)
            for rid in rec_ids:
                recv = receipts[rid]["received_on"]
                trc = ck.on(recv, 8, 12)
                T["material_receipt"][rid] = trc
                rlots = [m for m in roots if m["receipt_id"] == rid]
                nkey[f"material_received:{rlots[0]['lot_no']}"] = trc
                for m in rlots:
                    T["material_lot"][m["id"]] = trc
                    tch("원자재", m["id"], trc)
                gap = 1 if issued_on is None or (issued_on - recv).days >= 1 else 0
                ck.on(recv + timedelta(days=rnd.randint(0, gap)), 13, 17)
                for m in rlots:
                    for q in sorted(iinsp.get(m["id"], []), key=lambda q: q["seq"]):
                        ti = ck.later(0, 0, 13, 17)
                        T["incoming_inspection"][q["id"]] = ti
                        tch("원자재", m["id"], ti)
                        handled(f"material_received:{rlots[0]['lot_no']}", ti)
            # 원자재 분할 — 검사 뒤 · 불출 앞
            for m in roots:
                for mv in split_m.get(m["id"], []):
                    tsp = ck.later(0, 0)
                    T["stock_move"][mv["id"]] = tsp
                    T["material_lot"][mv["lot_id"]] = tsp
                    tch("원자재", m["id"], tsp)
                    tch("원자재", mv["lot_id"], tsp)
            # 불출
            for x in issue_ids:
                tis = ck.on(issues[x]["issued_on"], 9, 12)
                T["material_issue"][x] = tis
                handled(f"order_issued:{wo['work_order_no']}", tis)
                for ln in lines:
                    if ln["issue_id"] != x:
                        continue
                    T["material_issue_line"][ln["id"]] = tis
                    tch("원자재", ln["material_lot_id"], tis)
                    for mv in issue_moves.get(ln["id"], []):
                        T["stock_move"][mv["id"]] = tis
            # 생산일보 · 검사일보 (일자 순)
            days = sorted({d["work_date"] for d in pdaily.get(wo["id"], []) + idaily.get(wo["id"], [])})
            for wd in days:
                for d in pdaily.get(wo["id"], []):
                    if d["work_date"] == wd:
                        T["production_daily"][d["id"]] = ck.on(wd, 16, 18)
                for d in idaily.get(wo["id"], []):
                    if d["work_date"] == wd:
                        T["inspection_daily"][d["id"]] = ck.on(wd, 17, 19)
            # 제품 입고 → 판정(재판정) → 분할
            for pr in sorted(preceipts.get(wo["id"], []), key=lambda r: r["id"]):
                tpr = ck.on(pr["received_on"], 9, 18)
                T["product_receipt"][pr["id"]] = tpr
                T["product_lot"][pr["product_lot_id"]] = tpr
                tch("제품", pr["product_lot_id"], tpr)
                nkey[f"product_received:{plot_no[pr['product_lot_id']]}"] = tpr
            last["work_order"][wo["id"]] = ck.t
        # 제품 입고 뒤 — 판정(재판정) · 제품 분할 · 출하 지시 · 출하 확정을 [제품 입고일, 끝날 E] 에 앞으로만 펼친다.
        # E — 확정 출하가 있으면: 납기 > 제품 입고일 이면 납기 − 0~10일(정시 · 마지막 확정 ≤ 납기), 아니면 제품 입고일 + 1~8일
        # (납기가 제품 입고일 이하 = 지연 출하로 계획된 의뢰 → 마지막 확정 > 납기). 미확정 지시만 있으면 + 1~5일, 판정만이면 + 0~2일.
        rq_plots = [pl for wo in wos.get(rq["id"], []) for pl in plot_by_wo.get(wo["id"], [])]
        sos = sorted(sorders.get(rq["id"], []), key=lambda o: o["id"])
        p_on, due = ck.t.date(), rq["due_date"]
        if any(o["status"] == "확정" for o in sos):
            E = (due - timedelta(days=rnd.randint(0, min(10, (due - p_on).days - 1))) if due > p_on
                 else p_on + timedelta(days=rnd.randint(1, 8)))
        else:
            E = p_on + timedelta(days=rnd.randint(1, 5) if sos else rnd.randint(0, 2))
        E = min(E, today)
        events: list[tuple] = [("판정", pl, q) for pl in rq_plots for q in sorted(pinsp.get(pl["id"], []), key=lambda q: q["seq"])]
        events += [("분할", pl, mv) for pl in rq_plots for mv in split_p.get(pl["id"], [])]
        for so in sos:
            events.append(("지시", so, None))
            if so["status"] == "확정":
                events.append(("확정", so, None))
        for k, (kind, a, b) in enumerate(events):
            if k == len(events) - 1:
                d = E
            else:
                span = max(0, (E - ck.t.date()).days)
                d = ck.t.date() + timedelta(days=rnd.randint(0, span // (len(events) - k)))
            t = ck.on(d)
            if kind == "판정":
                T["product_inspection"][b["id"]] = t
                tch("제품", a["id"], t)
                nkey[f"judged:{a['lot_no']}:{b['seq']}"] = t
                handled(f"product_received:{a['lot_no']}", t)
            elif kind == "분할":
                T["stock_move"][b["id"]] = t
                T["product_lot"][b["lot_id"]] = t
                tch("제품", a["id"], t)
                tch("제품", b["lot_id"], t)
            elif kind == "지시":
                T["shipment_order"][a["id"]] = t
                nkey[f"shipment_ordered:{a['shipment_no']}"] = t
                for ln in slines.get(a["id"], []):
                    T["shipment_line"][ln["id"]] = t
                    tch("제품", ln["product_lot_id"], t)
                    first_ship_of_lot.setdefault(ln["product_lot_id"], t)
                    first_ship_of_lot.setdefault(plot_root[ln["product_lot_id"]], t)
            else:
                conf[a["id"]] = t
                nkey[f"shipment_confirmed:{a['shipment_no']}"] = t
                handled(f"shipment_ordered:{a['shipment_no']}", t)
                for ln in slines.get(a["id"], []):
                    tch("제품", ln["product_lot_id"], t)
                for mv in ship_moves.get(a["id"], []):
                    T["stock_move"][mv["id"]] = t
        last["production_request"][rq["id"]] = ck.t
        for wo in wos.get(rq["id"], []):
            last["work_order"][wo["id"]] = ck.t
    for pid, t in first_ship_of_lot.items():
        for q in pinsp.get(pid, []):
            handled(f"judged:{plot_no[pid]}:{q['seq']}", t)

    # 기준정보 · ERP — 기준정보는 첫 의뢰 일주일 전, ERP 회차는 기준 기간 끝 + 1~3일(이번 달은 지금 직전)
    t_base = datetime.combine(min(r["request_date"] for r in reqs) - timedelta(days=7), dtime(9), tzinfo=tz)
    for k in ("customer", "item", "warehouse", "location", "erp_customer_map"):
        for n_, i in enumerate(s[k]):
            T[k][i] = t_base + timedelta(minutes=n_ % 240)
    from lcomfine.app import erp_upload
    batch_t: dict[int, datetime] = {}
    for b in c.q("select id, period_to from erp_upload_batch where id = any(%s) order by period_to, id", (s["erp_upload_batch"],)):
        d = b["period_to"] + timedelta(days=rnd.randint(1, 3))
        t = min(datetime.combine(d, dtime(10), tzinfo=tz) + timedelta(minutes=rnd.randint(0, 300)), cap)
        batch_t[b["id"]] = T["erp_upload_batch"][b["id"]] = t
        nkey[f"link:{erp_upload.error_link(b['id'])}"] = t
    for r in c.q("select id, batch_id from erp_upload_row where id = any(%s)", (s["erp_upload_row"],)):
        T["erp_upload_row"][r["id"]] = batch_t[r["batch_id"]]

    missing = [(k, len(set(s[k]) - set(T[k]))) for k in s
               if k not in ("notification", "lot_stock", "stock_adjust", "shipment_adjust") and set(s[k]) - set(T[k])]
    if missing:
        raise Failed(f"[시각 맞추기] 시각을 정하지 못한 행이 있다 — {missing} (흐름 연결을 못 찾음). 아무것도 바꾸지 않았다.")

    # 쓰기 — 한 트랜잭션
    moved: dict[str, int] = {}
    with c.tx() as cur:
        def upd(table: str, sets: str, params: list[tuple]) -> None:
            if params:
                cur.executemany(f"update {table} set {sets} where id = %s", params)
                moved[table] = moved.get(table, 0) + len(params)

        upd_cu = "created_at = %s, updated_at = case when updated_at is null then null else %s::timestamptz end"
        for k in ("customer", "item", "warehouse", "location", "erp_customer_map", "work_sequence", "material_receipt",
                  "material_issue", "material_issue_line", "production_daily", "inspection_daily", "product_receipt",
                  "shipment_line", "erp_upload_row"):
            upd(k, upd_cu, [(t, t, i) for i, t in T[k].items()])
        for k in ("production_request", "work_order"):
            upd(k, upd_cu, [(t, last[k][i], i) for i, t in T[k].items()])
        upd("material_lot", upd_cu, [(t, touch.get(("원자재", i), t), i) for i, t in T["material_lot"].items()])
        upd("product_lot", upd_cu, [(t, touch.get(("제품", i), t), i) for i, t in T["product_lot"].items()])
        for k in ("incoming_inspection", "product_inspection"):
            upd(k, "inspected_at = %s, " + upd_cu, [(t, t, t, i) for i, t in T[k].items()])
        upd("stock_move", "moved_at = %s, " + upd_cu, [(t, t, t, i) for i, t in T["stock_move"].items()])
        upd("shipment_order", "confirmed_at = case when confirmed_at is null then null else %s::timestamptz end, " + upd_cu,
            [(conf.get(i), t, conf.get(i, t), i) for i, t in T["shipment_order"].items()])
        upd("erp_upload_batch", "uploaded_at = %s, " + upd_cu, [(t, t, t, i) for i, t in T["erp_upload_batch"].items()])
        # 재고 행 — 그 LOT 이 그 위치에 처음 생긴 시각(입고 · 분할) · 마지막으로 건드린 시각
        ls = c.q("select id, lot_kind, lot_id from lot_stock where id = any(%s)", (s["lot_stock"],))
        tbl = {"원자재": T["material_lot"], "제품": T["product_lot"]}
        upd("lot_stock", upd_cu, [(tbl[r["lot_kind"]][r["lot_id"]], touch.get((r["lot_kind"], r["lot_id"]), tbl[r["lot_kind"]][r["lot_id"]]),
                                   r["id"]) for r in ls if r["lot_id"] in tbl[r["lot_kind"]]])
        # 알림 — 발생 = 그 사건 시각 · 처리 = 다음 단계 시각(못 찾으면 발생 + 30분). 납기 D-3(due:) 는 오늘 돈 배치라 그대로
        notes = c.q("select id, event_key, dedupe_key, link, handled_at from notification where id = any(%s)", (s["notification"],))
        nparams = []
        for n_ in notes:
            key = f"link:{n_['link']}" if n_["event_key"] == "erp_upload_error" else n_["dedupe_key"]
            t = nkey.get(key)
            if t is None:
                continue
            h = None
            if n_["handled_at"] is not None:
                h = min(max(nhandled.get(n_["dedupe_key"], t + timedelta(minutes=30)), t), cap)
            nparams.append((t, h, n_["id"]))
        upd("notification", "created_at = %s, handled_at = %s::timestamptz", nparams)
        # 검산 — 흐름 순서 · 미래 시각. 하나라도 어긋나면 되돌린다
        bad = []
        chk = [
            ("의뢰일 > 지시", """select count(*) as n from work_order w join production_request r on r.id = w.request_id
                                where w.id = any(%s) and w.created_at::date < r.request_date""", s["work_order"]),
            ("지시 > 원자재 입고", """select count(*) as n from material_issue_line l join work_order w on w.id = l.work_order_id
                                   join material_lot m on m.id = l.material_lot_id join material_receipt rc on rc.id = m.receipt_id
                                  where w.id = any(%s) and rc.created_at < w.created_at""", s["work_order"]),
            ("입고검사 > 불출", """select count(*) as n from material_issue_line l join material_issue i on i.id = l.issue_id
                                  join incoming_inspection q on q.material_lot_id = coalesce(
                                       (select parent_lot_id from material_lot where id = l.material_lot_id), l.material_lot_id)
                                 where l.id = any(%s) and q.inspected_at > i.created_at""", s["material_issue_line"]),
            ("불출 > 일보", """select count(*) as n from production_daily d join material_issue_line l on l.work_order_id = d.work_order_id
                              join material_issue i on i.id = l.issue_id where d.id = any(%s) and d.created_at < i.created_at""",
             s["production_daily"]),
            ("지시 > 마지막 일보 일자", """select count(*) as n from production_daily d join work_order w on w.id = d.work_order_id
                                        where d.id = any(%s) and d.work_date < w.created_at::date""", s["production_daily"]),
            ("제품 입고 > 판정", """select count(*) as n from product_inspection q join product_lot p on p.id = q.product_lot_id
                                   where q.id = any(%s) and q.inspected_at < p.created_at""", s["product_inspection"]),
            ("판정 > 출하 지시", """select count(*) as n from shipment_line l join shipment_order o on o.id = l.shipment_order_id
                                   join product_lot p on p.id = l.product_lot_id
                                   join product_inspection q on q.product_lot_id = coalesce(p.parent_lot_id, p.id)
                                  where o.id = any(%s) and q.inspected_at > o.created_at""", s["shipment_order"]),
            ("출하 지시 > 확정", "select count(*) as n from shipment_order where id = any(%s) and confirmed_at < created_at",
             s["shipment_order"]),
            ("정시 계획인데 납기 뒤 확정", """select count(*) as n from shipment_order o join production_request r on r.id = o.request_id
                                         where o.id = any(%s) and o.status = '확정' and o.confirmed_at::date > r.due_date
                                           and r.due_date > (select max(p.received_on) from product_receipt p
                                                              join work_order w on w.id = p.work_order_id where w.request_id = r.id)""",
             s["shipment_order"]),
            ("지연 계획인데 납기 안 확정", """select count(*) as n from production_request r where r.id = any(%s)
                                           and r.due_date <= (select max(p.received_on) from product_receipt p
                                                              join work_order w on w.id = p.work_order_id where w.request_id = r.id)
                                           and (select max(o.confirmed_at)::date from shipment_order o
                                                 where o.request_id = r.id and o.status = '확정') <= r.due_date""",
             s["production_request"]),
        ]
        for name, sql, ids in chk:
            cur.execute(sql, (ids,))
            n_ = cur.fetchone()["n"]
            if n_:
                bad.append(f"{name} {n_}")
        for k, ts in T.items():
            if ts and max(ts.values()) > now:
                bad.append(f"{k} 미래 시각")
        if bad:
            raise Failed("[시각 맞추기] 검산 실패 — " + " · ".join(bad) + ". 되돌렸다(아무것도 바꾸지 않았다).")
    print("\n시각 맞추기 (SMP- 범위 · 한 트랜잭션 · 검산 10 통과)")
    for k, v in moved.items():
        print(f"  {k:<22} {v:>6}")
    months = c.q("""select to_char(confirmed_at, 'YYYY-MM') as ym, count(*) as n from shipment_order
                     where id = any(%s) and status = '확정' group by 1 order by 1""", (s["shipment_order"],))
    print("  확정 출하 월별: " + " · ".join(f"{m['ym']} {m['n']}" for m in months))
    return 0


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
    ap.add_argument("--retime", action="store_true", help="이미 넣은 SMP- 샘플의 시스템 시각만 업무 날짜에 다시 맞춘다")
    a = ap.parse_args(argv)
    try:
        if a.clean:
            return clean()
        if a.retime:
            return retime()
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
