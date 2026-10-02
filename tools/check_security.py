#!/usr/bin/env python
"""QA3 검사기 — G-13~G-20 (채널 · 출력물 · 이관 배치 · ERP · 접근 로그 · 비밀 · 백업) + 조용한 실패 사냥.

    uv run python tools/check_security.py                # 전부 (브라우저 실측 포함 — 1~3분)
    uv run python tools/check_security.py --no-browser   # 브라우저 실측을 건너뛴다 → 그 행은 `미검증`
    uv run python tools/check_security.py --only G-18    # 한 게이트만 (임시 데이터는 그대로 만든다)

출력은 `G-nn  항목  PASS|FAIL|WARN|BLOCKED|미검증  실측` 행이다(`tools/gate.py` 의 `per_gate()` 가 읽는다).
`QA3-…` 로 시작하는 행은 게이트 밖 참고 행이다(gate.py 가 읽지 않는다 — 조용한 실패 사냥 · 보강 권고).
종료코드: G-13~G-20 중 FAIL 이 하나라도 있으면 1.

재는 방법
  · 기대값은 goal.md §2.3·§2.4 와 설계도·계약에서 온다. 개발이 짠 테스트를 부르지 않는다.
  · 임시 데이터(코드 접두 `Q3C-` · 이름에 `(예시) Q3`)를 **화면이 부르는 것과 같은 API** 로 만들어 쓰기 기능 54개를 전부 한 번씩 부르고,
    끝나면 지운다. 시드 계정·권한 표는 바꾸지 않는다(권한 수정은 같은 값으로 다시 저장). 계정 중지·잠금은 임시 계정(`q3c-…`)으로 한다.
  · 브라우저가 필요한 것(G-13 포커스·390px·현황판 새로고침, G-14 캡처 디코드)은 `tools/e2e/probe.py` 를 `uv run --with playwright` 로 띄워 잰다.
    띄울 수 없으면 그 행은 `미검증` 이고 사유를 실측 칸에 적는다 — 통과로 치지 않는다.
  · DB 끊김은 **하위 프로세스의 접속 설정만** 잘못된 값으로 바꿔 잰다. PostgreSQL 을 멈추지 않는다.
  · G-20 은 `tools/backup.py` 가 생기면 판정한다. 복구 검증이 `lcomfine_db` 를 건드렸는지(행 수 변화)도 본다.
"""

from __future__ import annotations

import warnings

warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient`")

import ast
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT / "tools"))

PASS, FAIL, WARN, BLOCKED, UNVERIFIED = "PASS", "FAIL", "WARN", "BLOCKED", "미검증"
#: 같은 DB 에서 검사기·pytest 가 동시에 여러 벌 돌 수 있다(QA 3명 + 오케스트레이터) → 실행마다 다른 꼬리표를 붙인다
TAG = f"{os.getpid() % 0xFFFF:04X}"
PREFIX = f"Q3C{TAG}-"    # 검사기가 만든 기준정보의 코드 접두
MIG = f"Q3M{TAG}-"       # 이관 배치 검사에서 `(예시)` CSV 의 `IMP-` 를 바꿔 쓰는 접두 (다른 실행과 겹치지 않게)
MARK = "(예시) Q3"
TMP_USER = f"q3c{TAG.lower()}-"
STALE_RE = r"^Q3[CMTNE][0-9A-F]{0,4}-"      # QA3 가 만든 코드 접두 전부 (오래된 잔여를 찾을 때)
NOPE = "Q3-NOPE-0000"
HTML = {"accept": "text/html"}

ROWS: list[tuple[str, str, str, str]] = []


def put(gid: str, item: str, status: str, measured: str) -> None:
    ROWS.append((gid, item, status, " ".join(str(measured).split())))


def ok(cond: bool) -> str:
    return PASS if cond else FAIL


def run(cmd: list[str], timeout: int = 600, env: dict | None = None) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout, env=env)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, f"timeout {timeout}s"
    except FileNotFoundError as exc:
        return 127, str(exc)


# ── 앱 · 클라이언트 ─────────────────────────────────────────────────────
from fastapi.testclient import TestClient  # noqa: E402

from lcomfine.app import contracts, nav  # noqa: E402
from lcomfine.app.main import app  # noqa: E402
from lcomfine.app.settings import get_settings  # noqa: E402
from lcomfine.db import conn  # noqa: E402

_clients: dict[tuple[str, str | None], TestClient] = {}


def cl(role: str | None = None, device: str | None = None, password: str | None = None) -> TestClient:
    """로그인한 클라이언트. role=None 이면 미로그인."""
    if role is None:
        return TestClient(app, raise_server_exceptions=False)
    key = (role, device)
    if key not in _clients:
        c = TestClient(app, raise_server_exceptions=False)
        data = {"login_id": role, "password": password or get_settings().seed_password or ""}
        if device:
            data["device"] = device
        r = c.post("/login", data=data, follow_redirects=False)
        if r.status_code != 303:
            raise RuntimeError(f"{role} 로그인 실패 {r.status_code} — 공통 시드와 .env(LCOMFINE_SEED_PASSWORD)를 확인한다")
        _clients[key] = c
    return _clients[key]


def one(sql: str, params=()) -> dict | None:
    return conn.q1(sql, params)


def n(sql: str, params=()) -> int:
    return conn.q1(sql, params)["n"]


def log_max() -> int:
    return conn.q1("select coalesce(max(log_id), 0) as n from sys_access_log")["n"]


def logs_since(since: int, **where) -> list[dict]:
    cond, params = ["log_id > %s"], [since]
    for k, v in where.items():
        cond.append(f"{k} = %s")
        params.append(v)
    return conn.q(f"select * from sys_access_log where {' and '.join(cond)} order by log_id", params)


# ═════════════════════════════════════════════════════════════════════════
# 임시 세계 — 쓰기 기능 54개를 화면 API 로 한 번씩 (G-18 전수 · G-13 · G-14 의 재료)
# ═════════════════════════════════════════════════════════════════════════
class World:
    def __init__(self) -> None:
        self.calls: list[dict] = []          # 쓰기 호출마다 {fid, status, delta, …}
        self.v: dict = {}                    # 번호들
        self.error: str | None = None
        self.tmp_password = secrets.token_urlsafe(12)

    # 쓰기 한 번 + 그 기능의 `변경` 로그가 정확히 한 줄 늘었는가
    def w(self, fid: str, role: str, path: str, data=None) -> dict:
        since = log_max()
        r = cl(role).post(path, data=data or {})
        rows = [g for g in logs_since(since, log_type="변경", function_id=fid, login_id=role) if g["path"] == path]
        body = {}
        try:
            body = r.json()
        except Exception:  # noqa: BLE001 — JSON 이 아니면 본문 앞부분을 실측으로 남긴다
            body = {"_text": r.text[:160]}
        if len(rows) > 1:      # 같은 시드 계정·같은 경로로 동시에 도는 다른 실행의 줄을 뺀다 — 응답·경로에 나온 번호가 대상에 있는 줄만
            mine = [str(x) for x in body.values() if isinstance(x, (str, int)) and len(str(x)) >= 3 and x is not True]
            mine += [seg for seg in path.split("/") if len(seg) >= 6]
            narrowed = [g for g in rows if any(val in (g["target"] or "") for val in mine)]
            rows = narrowed or rows
        rec = {"fid": fid, "role": role, "path": path, "status": r.status_code, "delta": len(rows),
               "who": rows[0]["login_id"] if rows else None, "target": rows[0]["target"] if rows else None,
               "when": bool(rows and rows[0]["logged_at"]), "message": body.get("message") or body.get("_text", "")}
        self.calls.append(rec)
        if r.status_code != 200:
            raise RuntimeError(f"{fid} {path} → {r.status_code} {str(body)[:200]}")
        return body

    def id_of(self, table: str, pk: str, code_col: str, code: str) -> int:
        return conn.q1(f"select {pk} as id from {table} where {code_col} = %s", (code,))["id"]

    def build(self) -> None:
        v, P = self.v, PREFIX
        # ── 기준정보 5종 (관리자) — 등록 · 수정 · 삭제 ──
        masters = [
            ("F-BAS-01", "/bas/items", "item", "item_id", "item_code",
             [{"item_code": f"{P}FG", "item_name": f"제품 {MARK}", "item_type": "제품", "unit": "m"},
              {"item_code": f"{P}RM", "item_name": f"원단 {MARK}", "item_type": "원재료", "unit": "m"}],
             {"item_code": f"{P}XX", "item_name": f"삭제용 {MARK}", "item_type": "제품", "unit": "m"}, {"item_name": f"제품 수정 {MARK}"}),
            ("F-BAS-05", "/bas/customers", "customer", "customer_id", "customer_code",
             [{"customer_code": f"{P}CU", "customer_name": f"고객 {MARK}"}],
             {"customer_code": f"{P}XX", "customer_name": f"삭제용 {MARK}"}, {"customer_name": f"고객 수정 {MARK}"}),
            ("F-BAS-09", "/bas/processes", "process", "process_id", "process_code",
             [{"process_code": f"{P}PR", "process_name": f"인쇄 {MARK}", "process_type": "인쇄", "sort_no": "97"}],
             {"process_code": f"{P}XX", "process_name": f"삭제용 {MARK}", "process_type": "기타"}, {"process_name": f"인쇄 수정 {MARK}"}),
            ("F-BAS-13", "/bas/equipment", "equipment", "equipment_id", "equipment_code",
             [{"equipment_code": f"{P}EQ", "equipment_name": f"인쇄기 {MARK}"}],
             {"equipment_code": f"{P}XX", "equipment_name": f"삭제용 {MARK}"}, {"equipment_name": f"인쇄기 수정 {MARK}"}),
            ("F-BAS-17", "/bas/defect-codes", "defect_code", "defect_code_id", "defect_code",
             [{"defect_code": f"{P}DF", "defect_name": f"색차 {MARK}"}],
             {"defect_code": f"{P}XX", "defect_name": f"삭제용 {MARK}"}, {"defect_name": f"색차 수정 {MARK}"}),
        ]

        def master(role, fid, path, table, pk, code_col, keeps, throwaway, change):
            base = int(fid[-2:])
            f_create, f_update, f_delete = fid, f"{fid[:-2]}{base + 1:02d}", f"{fid[:-2]}{base + 2:02d}"
            for row in keeps:
                self.w(f_create, role, path, row)
            first = self.id_of(table, pk, code_col, keeps[0][code_col])
            self.w(f_update, role, f"{path}/{first}", change)
            self.w(f_create, role, path, throwaway)
            self.w(f_delete, role, f"{path}/{self.id_of(table, pk, code_col, throwaway[code_col])}/delete")

        for fid, path, table, pk, code_col, keeps, throwaway, change in masters:
            master("admin", fid, path, table, pk, code_col, keeps, throwaway, change)
        item_id = self.id_of("item", "item_id", "item_code", f"{P}FG")
        # ── 인쇄 기준 3종 (생산) ──
        master("prod", "F-PRT-01", "/prt/plates", "plate_spec", "plate_spec_id", "plate_code",
               [{"plate_code": f"{P}PL", "plate_name": f"판 {MARK}", "item_id": str(item_id), "color_count": "4"}],
               {"plate_code": f"{P}XX", "plate_name": f"삭제용 {MARK}"}, {"plate_name": f"판 수정 {MARK}"})
        master("prod", "F-PRT-05", "/prt/anilox", "anilox", "anilox_id", "anilox_code",
               [{"anilox_code": f"{P}AN", "anilox_name": f"아니록스 {MARK}"}],
               {"anilox_code": f"{P}XX", "anilox_name": f"삭제용 {MARK}"}, {"anilox_name": f"아니록스 수정 {MARK}"})
        master("prod", "F-PRT-09", "/prt/inks", "ink_formula", "ink_formula_id", "ink_code",
               [{"ink_code": f"{P}INK", "ink_name": f"잉크 {MARK}", "component_name": ["안료 (예시)", "용제 (예시)"], "ratio_pct": ["60", "40"]}],
               {"ink_code": f"{P}XX", "ink_name": f"삭제용 {MARK}"}, {"ink_name": f"잉크 수정 {MARK}"})
        # ── 작업지시 (생산) ──
        job_form = {"item_id": str(item_id), "customer_id": str(self.id_of("customer", "customer_id", "customer_code", f"{P}CU")),
                    "plate_spec_id": str(self.id_of("plate_spec", "plate_spec_id", "plate_code", f"{P}PL")),
                    "anilox_id": str(self.id_of("anilox", "anilox_id", "anilox_code", f"{P}AN")),
                    "ink_formula_id": str(self.id_of("ink_formula", "ink_formula_id", "ink_code", f"{P}INK")),
                    "equipment_id": str(self.id_of("equipment", "equipment_id", "equipment_code", f"{P}EQ")),
                    "order_qty": "1000", "qty_unit": "m", "due_date": (date.today() + timedelta(days=3)).isoformat(),
                    "note": f"검사기 {MARK}"}
        v["job_no"] = self.w("F-JOB-01", "prod", "/job/orders", job_form)["job_no"]
        self.w("F-JOB-02", "prod", f"/job/orders/{v['job_no']}", {"note": f"검사기 수정 {MARK}"})
        gone = self.w("F-JOB-01", "prod", "/job/orders", job_form)["job_no"]
        self.w("F-JOB-03", "prod", f"/job/orders/{gone}/cancel")
        self.w("F-JOB-06", "prod", "/job/mapping", {"job_no": v["job_no"], "planned_roll_count": "2", "planned_length_m": "1000"})
        v["job_lot_no"] = one("select lot_no from job_lot l join job j on j.job_id = l.job_id where j.job_no = %s", (v["job_no"],))["lot_no"]
        # ── 입고 · 입고검사 (현장 · 품질) ──
        v["lot_no"] = self.w("F-MAT-01", "field", "/mat/receipts", {"item_code": f"{P}RM", "received_qty": "5000", "qty_unit": "m",
                                                                    "supplier_name": f"공급처 {MARK}"})["lot_no"]
        self.w("F-MAT-03", "qc", "/mat/inspections", {"lot_no": v["lot_no"], "result": "합격"})
        # ── 조색 (품질) ──
        rec = self.w("F-CLR-01", "qc", "/clr/records", {"job_no": v["job_no"], "color_name": f"청 {MARK}", "color_l": "50", "color_a": "-10", "color_b": "-30"})["id"]
        self.w("F-CLR-02", "qc", f"/clr/records/{rec}/mix", {"component_name": ["안료 (예시)", "용제 (예시)"], "ratio_pct": ["55", "45"]})
        self.w("F-CLR-03", "qc", f"/clr/records/{rec}", {"color_name": f"청 수정 {MARK}", "color_l": "51"})
        rec2 = self.w("F-CLR-01", "qc", "/clr/records", {"job_no": v["job_no"], "color_name": f"삭제용 {MARK}"})["id"]
        self.w("F-CLR-04", "qc", f"/clr/records/{rec2}/delete")
        # ── POP 인쇄 ×2 (현장) — 정지 · 재개 · 폐기 포함 ──
        prints = []
        for i in (1, 2):
            wid = self.w("F-POP-01", "field", "/pop/work/start", {"job_no": v["job_no"], "lot_no": v["job_lot_no"]})["work_id"]
            if i == 1:
                v["work_id"] = wid
                stop = self.w("F-POP-04", "field", "/pop/stops", {"work_id": str(wid), "stop_reason": f"판 교체 {MARK}"})["stop_id"]
                self.w("F-POP-05", "field", f"/pop/stops/{stop}/resume")
                self.w("F-POP-06", "field", "/pop/stops/scrap", {"work_id": str(wid), "scrap_qty": "5", "qty_unit": "m", "defect_code": f"{P}DF"})
            self.w("F-MAT-07", "field", "/mat/inputs", {"work_id": str(wid), "lot_no": v["lot_no"], "input_qty": "500"})
            if i == 1:        # 같은 LOT 을 한 번 더 — 한 번 스캔 = 한 건 (G-13)
                r = cl("field").post("/mat/inputs", data={"work_id": str(wid), "lot_no": v["lot_no"]})
                v["dup_input"] = {"status": r.status_code, "rows": n("select count(*) as n from material_input where work_result_id = %s", (wid,))}
                r = cl("field").post("/mat/inputs", data={"work_id": str(wid), "lot_no": NOPE})
                v["bad_input"] = {"status": r.status_code, "rows": n("select count(*) as n from material_input where work_result_id = %s", (wid,))}
            prints.append(self.w("F-POP-02", "field", f"/pop/work/{wid}/finish", {"output_qty": "500", "length_m": "500", "width_mm": "600"})["roll_no"])
        v["print_roll"] = prints[0]
        # ── 후가공 (생산) · 슬리팅 (현장) ──
        spliced = self.w("F-RLL-02", "prod", "/rll/finishing/splice", {"roll_no": prints, "length_m": "1000", "width_mm": "600"})["roll_no"]
        finished = self.w("F-RLL-01", "prod", "/rll/finishing", {"roll_no": spliced, "length_m": "1000", "width_mm": "600"})["roll_no"]
        slit = self.w("F-RLL-04", "field", "/rll/slitting", {"roll_no": finished, "count": "5", "widths_mm": "120,120,120,120,120"})["rolls"]
        slit = [x["roll_no"] if isinstance(x, dict) else x for x in slit]
        v["slit"] = slit
        v["roll"] = slit[0]
        # ── 품질 검사 (품질) ──
        self.w("F-QUA-01", "qc", "/qua/inspections", {"roll_no": slit[0], "delta_e": "0.9", "result": "합격"})
        insp = one("select inspection_id as id from inspection i join roll r on r.roll_id = i.roll_id where r.roll_no = %s", (slit[0],))["id"]
        self.w("F-QUA-02", "qc", f"/qua/inspections/{insp}", {"delta_e": "1.1", "result": "합격"})
        self.w("F-QUA-01", "qc", "/qua/inspections", {"roll_no": slit[4], "delta_e": "5.0", "result": "불합격", "defect_code": [f"{P}DF"], "position": ["끝단 (예시)"]})
        insp2 = one("select inspection_id as id from inspection i join roll r on r.roll_id = i.roll_id where r.roll_no = %s", (slit[4],))["id"]
        self.w("F-QUA-03", "qc", f"/qua/inspections/{insp2}/delete")
        # ── 출하 (현장) · 승인 (관리자) ──
        today = date.today().isoformat()
        v["shipment_no"] = self.w("F-SHP-01", "field", "/shp/shipments", {"job_no": v["job_no"], "ship_date": today})["shipment_no"]
        self.w("F-SHP-02", "field", f"/shp/shipments/{v['shipment_no']}/rolls", {"roll_no": slit[0]})
        r = cl("field").post(f"/shp/shipments/{v['shipment_no']}/rolls", data={"roll_no": slit[0]})     # 재출하 → 422
        v["reship"] = {"status": r.status_code, "rows": n("""select count(*) as n from roll_genealogy g join shipment s on s.shipment_id = g.child_shipment_id
                                                              where s.shipment_no = %s""", (v["shipment_no"],))}
        self.w("F-SHP-02", "field", f"/shp/shipments/{v['shipment_no']}/rolls", {"roll_no": slit[1]})
        gone = self.w("F-SHP-01", "field", "/shp/shipments", {"job_no": v["job_no"], "ship_date": today})["shipment_no"]
        self.w("F-SHP-03", "field", f"/shp/shipments/{gone}/cancel")
        self.w("F-SHP-05", "admin", f"/shp/approvals/{v['shipment_no']}/approve")
        v["coa_no"] = one("select coa_no from shipment where shipment_no = %s", (v["shipment_no"],))["coa_no"]
        # 브라우저 실측용 — 등록 상태 출하 1건(롤 0)과 재고 롤 2개
        v["probe_shipment_no"] = self.w("F-SHP-01", "field", "/shp/shipments", {"job_no": v["job_no"], "ship_date": today})["shipment_no"]
        v["probe_rolls"] = [slit[2], slit[3]]
        # ── 시스템 관리 (관리자) — 임시 계정 · 권한은 같은 값으로 다시 저장 ──
        v["tmp_user"] = f"{TMP_USER}{secrets.token_hex(3)}"
        self.w("F-SYS-01", "admin", "/sys/users", {"login_id": v["tmp_user"], "user_name": f"임시 {MARK}", "role_code": "QC", "password": self.tmp_password})
        self.w("F-SYS-02", "admin", f"/sys/users/{v['tmp_user']}", {"user_name": f"임시 수정 {MARK}"})
        cell = one("select level, write_scope from sys_permission where role_code = 'ADMIN' and menu_code = 'BAS'")
        v["perm_before"] = dict(cell)
        self.w("F-SYS-06", "admin", "/sys/permissions", {"role_code": "ADMIN", "menu_code": "BAS", "level": cell["level"], "write_scope": cell["write_scope"]})
        v["perm_after"] = dict(one("select level, write_scope from sys_permission where role_code = 'ADMIN' and menu_code = 'BAS'"))
        # F-SYS-03 은 세션 검사(check_sessions) 안에서 임시 계정을 중지하며 부른다

    def cleanup(self, prefixes: tuple[str, ...] | None = None, users: str | None = None) -> dict:
        out: dict[str, int] = {}
        prefixes = prefixes or (PREFIX, MIG)
        users = users or TMP_USER
        with conn.tx() as cur:
            def ids(sql, params):
                cur.execute(sql, params)
                return [next(iter(r.values())) for r in cur.fetchall()]

            def dele(name, sql, params):
                cur.execute(sql, params)
                if cur.rowcount:
                    out[name] = out.get(name, 0) + cur.rowcount

            for prefix in prefixes:
                like = f"{prefix}%"
                items = ids("select item_id from item where item_code like %s", (like,))
                jobs = ids("select job_id from job where item_id = any(%s) or job_no like %s", (items, like))
                lots = ids("select material_lot_id from material_lot where item_id = any(%s)", (items,))
                rolls = ids("select roll_id from roll where job_id = any(%s)", (jobs,))
                ships = ids("select shipment_id from shipment where job_id = any(%s)", (jobs,))
                works = ids("select work_result_id from work_result where job_id = any(%s)", (jobs,))
                dele("roll_genealogy", """delete from roll_genealogy where child_roll_id = any(%s) or parent_roll_id = any(%s)
                                            or parent_material_lot_id = any(%s) or child_shipment_id = any(%s)""", (rolls, rolls, lots, ships))
                dele("inspection_defect", "delete from inspection_defect where inspection_id in (select inspection_id from inspection where roll_id = any(%s))", (rolls,))
                dele("inspection", "delete from inspection where roll_id = any(%s) or job_id = any(%s)", (rolls, jobs))
                dele("shipment", "delete from shipment where shipment_id = any(%s)", (ships,))
                dele("roll", "delete from roll where roll_id = any(%s)", (rolls,))
                dele("material_input", "delete from material_input where work_result_id = any(%s) or material_lot_id = any(%s)", (works, lots))
                dele("work_stop", "delete from work_stop where work_result_id = any(%s)", (works,))
                dele("work_scrap", "delete from work_scrap where work_result_id = any(%s)", (works,))
                dele("work_result", "delete from work_result where work_result_id = any(%s)", (works,))
                dele("color_record_mix", "delete from color_record_mix where color_record_id in (select color_record_id from color_record where job_id = any(%s))", (jobs,))
                dele("color_record", "delete from color_record where job_id = any(%s)", (jobs,))
                dele("material_lot", "delete from material_lot where material_lot_id = any(%s)", (lots,))
                dele("job_lot", "delete from job_lot where job_id = any(%s) or lot_no like %s", (jobs, like))
                dele("job", "delete from job where job_id = any(%s)", (jobs,))
                for table, col in (("plate_spec", "plate_code"), ("anilox", "anilox_code"), ("ink_formula", "ink_code"),
                                   ("equipment", "equipment_code"), ("process", "process_code"), ("defect_code", "defect_code"),
                                   ("customer", "customer_code"), ("item", "item_code")):
                    dele(table, f"delete from {table} where {col} like %s", (like,))
                dele("sys_migration_log", "delete from sys_migration_log where run_by like %s", (like,))
                dele("sys_access_log", "delete from sys_access_log where target like %s", (f"%{prefix}%",))
            dele("sys_access_log", "delete from sys_access_log where login_id like %s or target like %s", (f"{users}%", f"%:{users}%"))
            dele("sys_user", "delete from sys_user where login_id like %s", (f"{users}%",))
        return out


# ═════════════════════════════════════════════════════════════════════════
# G-13 4채널
# ═════════════════════════════════════════════════════════════════════════
SCAN_ENTRY = ["/pop/work", "/pop/roll-labels", "/mat/inspections", "/mat/lots", "/rll/finishing", "/rll/slitting",
              "/rll/history", "/qua/inspections", "/shp/shipments"]          # `?no=` (후가공은 `?add=`) 로 스캔값을 받는 GET


def scan_param(path: str) -> str:
    return "add" if path == "/rll/finishing" else "no"


def board_refresh_of(html: str) -> dict:
    """현황판 새로고침 장치(D-27)를 HTML 에서 읽는다 — `<body data-refresh-seconds="N">` + `static/app.js` 적재.
    `<noscript>` 안의 meta refresh 는 대체물이라 따로 센다(그것만 있으면 통과가 아니다)."""
    body = re.search(r"<body[^>]*>", html)
    sec = re.search(r'data-refresh-seconds="(\d+)"', body.group(0)) if body else None
    without_noscript = re.sub(r"<noscript>.*?</noscript>", "", html, flags=re.S)
    ns = re.search(r'<noscript>\s*<meta http-equiv="refresh" content="(\d+)"', html)
    return {"seconds": int(sec.group(1)) if sec and int(sec.group(1)) > 0 else None,
            "script": bool(re.search(r'<script[^>]+src="/static/app\.js', html)),
            "noscript_meta": ns.group(1) + "초" if ns else None,
            "meta_outside_noscript": 'http-equiv="refresh"' in without_noscript}


def refresh_script_ok() -> bool:
    """`static/app.js` 에 주기 속성을 읽어 서버 응답을 확인하고 다시 그리는 코드가 있는가 (정적)."""
    js = (SRC / "lcomfine" / "app" / "static" / "app.js").read_text(encoding="utf-8")
    return "refreshSeconds" in js and "location.reload" in js and "/health" in js and "setTimeout" in js


def check_channels(w: World) -> None:
    g = "G-13"
    # (1) 같은 앱·같은 DB — 채널 4개의 레이아웃 훅
    got = {}
    for dev in ("web", "pop", "mobile", "board"):
        r = cl("prod").get(f"/sta/board?device={dev}")
        m = re.search(r'<body class="([^"]*)"', r.text)
        got[dev] = (r.status_code, m.group(1) if m else "")
    bad = [d for d, (st, c) in got.items() if st != 200 or f"ch-{d}" not in c]
    put(g, "4채널 — 같은 앱이 ?device= 로 네 채널 레이아웃을 낸다 (HTTP)", ok(not bad),
        " · ".join(f"{d} {st} {c}" for d, (st, c) in got.items()))

    # (2) POP — 채널을 고정해 로그인하면 이후 화면이 POP 로 나오고, 스캔칸이 autofocus 를 갖는다
    pop = cl("field", "pop")
    targets = [s.path for s in nav.SCREENS if "현장 POP" in s.channels and s.path not in ("/pop/stops", "/mat/receipts", "/mat/inputs")]
    miss = []
    for path in targets:
        r = pop.get(path, headers=HTML)
        has_scan = bool(re.search(r"<input[^>]*data-scan[^>]*autofocus|<input[^>]*autofocus[^>]*data-scan", r.text))
        if r.status_code != 200 or 'class="ch-pop"' not in r.text or not has_scan:
            miss.append(f"{path}({r.status_code}{'' if has_scan else ' 스캔칸 없음'})")
    r = pop.get(f"/mat/inputs?work_id={w.v.get('work_id', 0)}", headers=HTML) if w.v.get("work_id") else None
    put(g, "POP — 채널 고정 로그인 뒤 스캔 화면이 ch-pop + 스캔칸(autofocus) (HTTP)", ok(not miss),
        f"현장 POP 채널의 스캔 화면 {len(targets)}개 중 미달 {len(miss)} {miss[:4]}")

    # (3) 스캔 진입 GET 의 422 — 브라우저(Accept: text/html)에서 그 화면이 다시 그려져 스캔칸이 남는가 (goal §2.5: 다음 스캔을 막지 않는다)
    gone = []
    for path in SCAN_ENTRY:
        r = pop.get(f"{path}?{scan_param(path)}={NOPE}", headers=HTML)
        if r.status_code != 422 or "data-scan" not in r.text:
            gone.append(f"{path}({r.status_code}{' 스캔칸 사라짐' if 'data-scan' not in r.text else ''})")
    put(g, "POP — 없는 번호 스캔(GET 422) 뒤에도 스캔칸이 남는다 (HTTP)", ok(not gone),
        f"스캔 진입 화면 {len(SCAN_ENTRY)}개 중 스캔칸이 사라지는 화면 {len(gone)} {gone}" if gone else f"스캔 진입 화면 {len(SCAN_ENTRY)}개 전부 422 + 스캔칸 유지")

    # (4) 바코드 한 번 = 한 건 — 같은 번호를 두 번 쏘면 두 번째는 422, 행 수는 그대로 (HTTP)
    d, b, s = w.v.get("dup_input"), w.v.get("bad_input"), w.v.get("reship")
    if d and b and s:
        good = d["status"] == 422 and d["rows"] == 1 and b["status"] == 422 and b["rows"] == 1 and s["status"] == 422 and s["rows"] == 1
        put(g, "POP — 바코드 한 번 = 한 건, 중복·없는 번호는 422 이고 행이 늘지 않는다 (HTTP)", ok(good),
            f"자재 투입 중복 {d['status']}·{d['rows']}행 · 없는 LOT {b['status']}·{b['rows']}행 · 출하 재스캔 {s['status']}·{s['rows']}행")
    else:
        put(g, "POP — 바코드 한 번 = 한 건 (HTTP)", UNVERIFIED, f"임시 데이터를 만들지 못했다 — {w.error}")

    # (5) 현황판 — 새로고침 태그와 갱신 시각 (HTTP). 오류 화면으로 떨어졌을 때도 새로고침이 이어지는가
    # 재검(웨이브 D 뒤 · D-27): 새로고침은 이제 `<meta refresh>` 가 아니라 `static/app.js` 가 한다(`<body data-refresh-seconds>`).
    # meta 는 `<noscript>` 안의 대체물로만 남았다 — 그것만 보고 통과시키면 스크립트가 빠져도 PASS 가 된다. 그래서 주기 속성 + 스크립트 적재 +
    # 그 스크립트에 새로고침 코드가 있는지를 본다(실제로 다시 그려지는지는 아래 브라우저 실측 행).
    r = cl("prod").get("/sta/board?device=board", headers=HTML)
    br = board_refresh_of(r.text)
    stamp = re.search(r'id="refreshed-at">([^<]+)<', r.text)
    r2 = cl("prod").get("/sta/board", headers=HTML)
    br2 = board_refresh_of(r2.text)
    js_ok = refresh_script_ok()
    good = (bool(br["seconds"]) and br["script"] and js_ok and bool(stamp) and "마지막 갱신" in r.text
            and br2["seconds"] is None and not br2["meta_outside_noscript"] and not br["meta_outside_noscript"])
    put(g, "현황판 — ?device=board 에 자동 새로고침 태그 + 마지막 갱신 시각 (HTTP)", ok(good),
        f"data-refresh-seconds {str(br['seconds']) + '초' if br['seconds'] else '없음'} · app.js 적재 {br['script']} · app.js 에 새로고침 코드 {js_ok} · "
        f"noscript 대체 meta {br['noscript_meta'] or '없음'} · 갱신 시각 {stamp.group(1) if stamp else '없음'} · 일반 채널에는 주기 속성 {'없음' if br2['seconds'] is None else '있음'}")
    r3 = cl("prod").get("/sta/board/none?device=board", headers=HTML)      # 현황판 채널의 오류 화면 (404)
    br3 = board_refresh_of(r3.text)
    put(g, "현황판 — 오류 화면으로 떨어져도 자동 새로고침이 이어진다 (HTTP)", ok(bool(br3["seconds"]) and br3["script"] and js_ok),
        f"현황판 채널의 오류 화면({r3.status_code}) — data-refresh-seconds {str(br3['seconds']) + '초' if br3['seconds'] else '없음'} · app.js 적재 {br3['script']}"
        + ("" if br3["seconds"] and br3["script"] else " — 한 번 오류(일시적 503 포함)가 나면 사람이 누를 때까지 그 화면에 멈춘다"))

    # (6) 모바일 — 뷰포트 메타와 채널 훅 (폭 실측은 브라우저 행)
    r = cl("qc", "mobile").get("/trc/trace", headers=HTML)
    put(g, "모바일 — 채널 고정 로그인 뒤 LOT 추적이 ch-mobile + viewport 메타 (HTTP)",
        ok(r.status_code == 200 and 'class="ch-mobile"' in r.text and 'name="viewport"' in r.text),
        f"/trc/trace {r.status_code} · ch-mobile {'있음' if 'ch-mobile' in r.text else '없음'} · viewport {'있음' if 'name=\"viewport\"' in r.text else '없음'}")


def check_channels_browser(probe: dict | None, why: str) -> None:
    g = "G-13"
    if not probe or "pop" not in probe:
        for item in ("POP — 스캔칸 포커스 · 오류 뒤 다음 스캔 (브라우저 실측)", "모바일 — 폭 390px 가로 스크롤 없음 (브라우저 실측)",
                     "현황판 — 조작 없이 다시 그려진다 (브라우저 실측)"):
            put(g, item, UNVERIFIED, f"브라우저 실측을 돌리지 못했다 — {why}")
        return
    p = probe["pop"]
    size = p["size"]
    big = size["body_font_px"] > p["size_web"]["body_font_px"] and size["button_h_px"] >= 44 and size["scan_input_h_px"] >= 44
    put(g, "POP — 터치용 확대 (브라우저 실측)", ok(big and "ch-pop" in p["body_class"]),
        f"글자 {size['body_font_px']}px(Web {p['size_web']['body_font_px']}px) · 스캔칸 높이 {size['scan_input_h_px']:.0f}px · 버튼 높이 {size['button_h_px']:.0f}px(Web {p['size_web']['button_h_px']:.0f}px)")
    nofocus = [k for k, x in p["screens"].items() if not x["focus_on_scan"]]
    put(g, "POP — 화면을 열면 스캔칸이 포커스를 잡는다 (브라우저 실측)", ok(not nofocus),
        f"스캔칸이 있는 화면 {len(p['screens'])}개 중 포커스 못 잡는 화면 {len(nofocus)} {nofocus}")
    blocked = [k for k, x in p["bad_scan"].items() if not (x["scan_present"] and x["next_scan_received"])]
    put(g, "POP — 없는 번호 스캔 뒤에도 곧바로 다음 스캔을 받는다 (브라우저 실측)", ok(not blocked),
        (f"스캔칸이 사라져 다음 스캔 글자가 버려지는 화면 {len(blocked)}/{len(p['bad_scan'])} {blocked}" if blocked
         else f"{len(p['bad_scan'])}개 화면 전부 오류 문장 + 스캔칸 유지 + 다음 스캔 수신"))
    lost = [k for k, x in p["popup"].items() if x.get("popup_shown") and not x.get("typed_while_popup_reaches_scan")]
    nofoc = [k for k, x in p["popup"].items() if x.get("popup_shown") and not x.get("focus_on_scan_after_close")]
    put(g, "POP — 알림이 떠 있어도 스캔을 받고, 닫으면 스캔칸으로 돌아온다 (브라우저 실측)", ok(not lost and not nofoc),
        f"알림 중 스캔 글자가 버려지는 화면 {lost} · 「확인」 뒤 포커스가 안 돌아오는 화면 {nofoc}" if (lost or nofoc)
        else f"{list(p['popup'])} 전부 통과")
    o = p.get("one_scan_one_row")
    if o:
        good = o["first_scan_rows"] == 1 and o["second_scan_while_popup_rows"] == 1 and o["rescan_rows"] == 1
        put(g, "POP — 연속 스캔: 바코드 한 번 = 한 건 (브라우저 실측 · 출하 롤 스캔)", ok(good),
            f"롤 A 스캔 → 계보 {o['first_scan_rows']}행 · 알림이 뜬 채 롤 B 스캔 → {o['second_scan_while_popup_rows']}행"
            f"{'(버려짐 · 오류 표시 ' + ('있음' if o['error_shown_for_lost_scan'] else '없음') + ')' if o['second_scan_while_popup_rows'] != 1 else ''}"
            f" · 롤 A 재스캔 → {o['rescan_rows']}행(경고 {'있음' if o['rescan_warn'] else '없음'})")
    else:
        put(g, "POP — 연속 스캔: 바코드 한 번 = 한 건 (브라우저 실측)", UNVERIFIED, "임시 출하 LOT 이 없어 재지 못했다")
    m = probe.get("mobile")
    if m:
        pages = m["pages"]["mobile"]
        wide = [f"{k}({x['scrollWidth']}>{x['vw']})" for k, x in pages.items() if x["scrollWidth"] > x["vw"] or x["inner_scrollers"]]
        need = [k for k in pages if k.startswith("/trc/trace") or k.startswith("/sta/summary")]
        web_wide = [k for k, x in m["pages"]["web"].items() if x["scrollWidth"] > x["vw"]]
        put(g, "모바일 — 폭 390px 에서 LOT 추적·실적 현황 가로 스크롤 없음 (브라우저 실측)", ok(not wide and len(need) >= 5),
            f"뷰포트 390 · 화면 {len(pages)}개(추적 {sum(k.startswith('/trc') for k in pages)} · 실적 현황 {sum(k.startswith('/sta') for k in pages)}) "
            f"문서 scrollWidth 최대 {max(x['scrollWidth'] for x in pages.values())} · 넘치는 화면 {wide or 0} · Web 채널로 열어도 넘침 {web_wide or 0}")
    else:
        put(g, "모바일 — 폭 390px 가로 스크롤 없음 (브라우저 실측)", UNVERIFIED, f"재지 못했다 — {probe.get('errors', {}).get('mobile', why)}")
    b = probe.get("board")
    if b:
        setting = b.get("refresh_setting")        # <body data-refresh-seconds> — 브라우저가 실제로 받은 주기
        took = b["seconds_until_refresh"]
        on_time = bool(setting) and took is not None and setting - 2 <= took <= setting + 15   # 설정 주기에 맞게 도는가 (늦어도 +15초)
        put(g, "현황판 — 조작 없이 다시 그려진다 (브라우저 실측)", ok(b["refreshed"] and on_time and "ch-board" in b["body_after"] and not b["menu_visible"]),
            f"갱신 시각 {b['first_stamp']} → {b['second_stamp']} ({took}초 뒤 · 설정 {setting}초) · 새로고침 뒤에도 {b['body_after']} · 메뉴 {'보임' if b['menu_visible'] else '숨김'}")
        e = b.get("error_page")
        if e:
            e_ok = e["reloaded"] and bool(e["refresh_setting"]) and "ch-board" in e["body"] and e["status"] >= 400
            put(g, "현황판 — 오류 화면에서도 조작 없이 다시 그려진다 (브라우저 실측)", ok(e_ok),
                f"현황판 채널의 오류 화면(HTTP {e['status']} · {e['body']}) — {'다시 그려짐 ' + str(e['seconds_until_reload']) + '초 뒤' if e['reloaded'] else str(e['waited_seconds']) + '초를 기다려도 다시 그려지지 않음'}"
                f" (설정 {e['refresh_setting']}초 · 그동안 문서 적재 {e['loads']}회)")
        else:
            put(g, "현황판 — 오류 화면에서도 조작 없이 다시 그려진다 (브라우저 실측)", UNVERIFIED, "probe 결과에 error_page 없음 (옛 probe.py)")
    else:
        put(g, "현황판 — 조작 없이 다시 그려진다 (브라우저 실측)", UNVERIFIED, f"재지 못했다 — {probe.get('errors', {}).get('board', why)}")


# ═════════════════════════════════════════════════════════════════════════
# G-14 출력물 5종
# ═════════════════════════════════════════════════════════════════════════
def outputs_of(w: World) -> list[tuple[str, str, str, str]]:
    v = w.v
    return [("작업지시서", "prod", f"/job/orders/{v.get('job_no')}/print", v.get("job_no")),
            ("원재료 LOT 라벨", "field", f"/mat/lots/{v.get('lot_no')}/label", v.get("lot_no")),
            ("인쇄 롤 라벨", "field", f"/pop/roll-labels/{v.get('print_roll')}/print", v.get("print_roll")),
            ("롤 라벨", "field", f"/rll/history/{v.get('roll')}/label", v.get("roll")),
            ("COA", "admin", f"/shp/coa/{v.get('shipment_no')}/print", v.get("shipment_no"))]


def svg_to_pgm(svg: str, path: Path, scale: int = 2) -> None:
    """인라인 SVG 바코드(검은 사각형들)를 브라우저 없이 흑백 비트맵(PGM)으로 그린다 — zbarimg 에 먹일 그림."""
    width = int(float(re.search(r'viewBox="0 0 ([\d.]+) ', svg).group(1)))
    bars = re.search(r'<g class="bars"[^>]*>(.*?)</g>', svg, re.S).group(1)
    line = bytearray([255] * (width * scale))
    for m in re.finditer(r'<rect x="([\d.]+)" y="0" width="([\d.]+)"', bars):
        x, wd = int(float(m.group(1))) * scale, int(float(m.group(2))) * scale
        line[x:x + wd] = bytes([0] * wd)
    height = 60 * scale
    blank = bytes([255] * len(line))
    with path.open("wb") as f:
        f.write(f"P5 {len(line)} {height + 20 * scale}\n255\n".encode())
        f.write(blank * (10 * scale) + bytes(line) * height + blank * (10 * scale))


def check_outputs(w: World) -> None:
    g = "G-14"
    if w.error and not w.v.get("shipment_no"):
        put(g, "출력물 5종 — 인쇄용 화면 · 인라인 SVG 바코드 · 외부 참조 0 (HTTP)", UNVERIFIED, f"임시 데이터를 만들지 못했다 — {w.error}")
        return
    bad, facts, decoded, undecoded = [], [], [], []
    zbar = shutil.which("zbarimg")
    tmp = Path(tempfile.mkdtemp(prefix="q3-barcode-"))
    for name, role, url, no in outputs_of(w):
        r = cl(role).get(url, headers=HTML)
        svgs = re.findall(r"<svg[^>]*class=\"barcode\".*?</svg>", r.text, re.S)
        ext = [u for u in re.findall(r'(?:src|href)="(https?://[^"]+|//[^"]+)"', r.text)]
        has_print = "window.print" in r.text or "인쇄" in r.text
        problems = []
        if r.status_code != 200:
            problems.append(f"HTTP {r.status_code}")
        if not svgs:
            problems.append("인라인 SVG 바코드 없음")
        if no and no not in re.sub(r"<svg.*?</svg>", "", r.text, flags=re.S):
            problems.append("번호 글자 없음")
        if ext:
            problems.append(f"외부 참조 {ext[:2]}")
        if "<img" in r.text and re.search(r'<img[^>]*src="(?!data:|/static)', r.text):
            problems.append("외부 이미지")
        if not has_print:
            problems.append("인쇄 버튼 없음")
        if problems:
            bad.append(f"{name}: {' · '.join(problems)}")
        facts.append(f"{name} {r.status_code}·SVG {len(svgs)}")
        if svgs and zbar:
            pgm = tmp / f"{len(decoded) + len(undecoded)}.pgm"
            svg_to_pgm(svgs[0], pgm)
            _, out = run([zbar, "-q", str(pgm)])
            (decoded if f"CODE-128:{no}" in out else undecoded).append(f"{name}→{out.strip() or '판독 실패'}")
    shutil.rmtree(tmp, ignore_errors=True)
    put(g, "출력물 5종 — 인쇄용 화면 · 인라인 SVG 바코드 · 번호 · 외부 참조 0 (HTTP)", ok(not bad), " · ".join(facts) + (f" — 미달 {bad}" if bad else " · 외부 참조 0 · 인쇄 버튼 있음"))
    if not zbar:
        put(g, "바코드 — SVG 를 실제 디코더(zbarimg)로 판독 (브라우저 없이)", UNVERIFIED, "이 장비에 zbarimg 없음")
    else:
        put(g, "바코드 — SVG 를 실제 디코더(zbarimg)로 판독 (브라우저 없이)", ok(len(decoded) == 5 and not undecoded),
            f"판독 {len(decoded)}/5 {decoded}" + (f" · 실패 {undecoded}" if undecoded else ""))
    # 미승인 출하의 COA 는 422 (번호 없는 문서를 찍지 않는다)
    if w.v.get("probe_shipment_no"):
        r = cl("admin").get(f"/shp/coa/{w.v['probe_shipment_no']}/print")
        put(g, "COA — 미승인 출하는 찍지 않는다 (422)", ok(r.status_code == 422), f"/shp/coa/<등록 상태 출하>/print → {r.status_code}")
    # 출력은 printing 어댑터 뒤 — 바코드를 그리는 코드가 printing.py 밖에 없는가 (정적)
    stray = []
    for f in list((SRC / "lcomfine" / "app").rglob("*.py")) + list((SRC / "lcomfine" / "app" / "templates").rglob("*.html")):
        if f.name == "printing.py":
            continue
        t = f.read_text(encoding="utf-8")
        if re.search(r"code128|<rect[^>]*class=\"bar|JsBarcode|barcode\.js|cdn\.", t, re.I) and "printing." not in t:
            stray.append(str(f.relative_to(ROOT)))
    put(g, "출력 어댑터 — 바코드·라벨을 그리는 곳은 app/printing.py 뿐 (정적)", ok(not stray), f"printing.py 밖에서 바코드를 그리는 파일 {len(stray)} {stray[:3]}")


def check_outputs_browser(probe: dict | None, why: str) -> None:
    g = "G-14"
    o = (probe or {}).get("outputs")
    if not o:
        put(g, "출력물 — 브라우저 캡처를 디코더로 판독 · 네트워크 외부 요청 0 · 스캔칸에 넣으면 열린다 (브라우저 실측)", UNVERIFIED,
            f"브라우저 실측을 돌리지 못했다 — {(probe or {}).get('errors', {}).get('outputs', why)}")
        return
    done = {k: x for k, x in o.items() if "skipped" not in x}
    nodecode = [k for k, x in done.items() if not x["decode_ok"]]
    ext = [f"{k}({x['external_count']})" for k, x in done.items() if x["external_count"] or x["ext_tags"] or x["img"]]
    noopen = [k for k, x in done.items() if not (x["scan_opens"] and x["scan_opens"]["focus_on_scan"] and x["scan_opens"]["number_shown"] and x["scan_opens"]["http_ok"])]
    noprint = [k for k, x in done.items() if x["print_media"]["menu"] or x["print_media"]["header"] or x["print_media"]["buttons"] or not x["print_media"]["svg"]
               or f"CODE-128:{x['number']}" not in x["decoded_print_media"]]
    put(g, "출력물 — 화면 캡처의 바코드가 실제 디코더로 읽힌다 (브라우저 실측 · zbarimg)", ok(len(done) == 5 and not nodecode),
        f"{len(done) - len(nodecode)}/5 판독 " + " · ".join(f"{k}={','.join(x['decoded']) or '실패'}" for k, x in done.items()))
    put(g, "출력물 — 브라우저 네트워크의 외부 요청 0 (브라우저 실측)", ok(len(done) == 5 and not ext),
        f"출력 화면 {len(done)}개 · 요청 합 {sum(x['requests'] for x in done.values())}건 전부 같은 서버 · 외부 요청 {ext or 0}")
    put(g, "출력물 — 인쇄 매체에서 메뉴·헤더·버튼이 빠지고 바코드가 읽힌다 (브라우저 실측)", ok(len(done) == 5 and not noprint),
        f"인쇄 매체 미달 {noprint or 0}")
    put(g, "출력물 — 디코드한 값을 스캔칸에 넣으면 그 Job/LOT/롤/출하가 열린다 (브라우저 실측)", ok(len(done) == 5 and not noopen),
        " · ".join(f"{k}→{x['scan_opens']['url'] if x['scan_opens'] else '디코드 실패'}" for k, x in done.items()) + (f" — 안 열림 {noopen}" if noopen else ""))


# ═════════════════════════════════════════════════════════════════════════
# G-15 이관 배치
# ═════════════════════════════════════════════════════════════════════════
MIG_TABLES = ["item", "customer", "process", "equipment", "defect_code", "plate_spec", "anilox", "ink_formula",
              "ink_formula_component", "job", "job_lot", "material_lot", "roll", "roll_genealogy", "inspection", "shipment"]


def mig(cmd: str, folder: Path | None, by: str | None = None) -> tuple[int, str]:
    by = by or f"{MIG}check"
    args = ["uv", "run", "python", "-m", "lcomfine.migration", cmd]
    if folder is not None:
        args += ["--dir", str(folder)]
    return run(args + ["--by", by], timeout=120)


def mig_counts() -> dict[str, int]:
    """접두 Q3M- 로 적재된 행 수 (테이블별) + 전체 행 수."""
    out = {}
    for t, col in (("item", "item_code"), ("customer", "customer_code"), ("process", "process_code"), ("equipment", "equipment_code"),
                   ("defect_code", "defect_code"), ("plate_spec", "plate_code"), ("anilox", "anilox_code"), ("ink_formula", "ink_code"),
                   ("job", "job_no"), ("job_lot", "lot_no")):
        out[t] = n(f"select count(*) as n from {t} where {col} like %s", (f"{MIG}%",))
    out["ink_formula_component"] = n("""select count(*) as n from ink_formula_component c join ink_formula i on i.ink_formula_id = c.ink_formula_id
                                         where i.ink_code like %s""", (f"{MIG}%",))
    return out


def copy_examples(dst: Path) -> None:
    src = SRC / "lcomfine" / "migration" / "examples"
    dst.mkdir(parents=True, exist_ok=True)
    for f in src.glob("*.csv"):
        (dst / f.name).write_text(f.read_text(encoding="utf-8").replace("IMP-", MIG), encoding="utf-8")


def probe_migration_overwrite(w: World) -> dict | None:
    """이관 적재가 **화면에서 만든, 실적·출하가 있는 Job** 을 덮어쓰는가 (임시 세계가 살아 있을 때 잰다).

    계약 F-JOB-02: 작업 실적이 생긴 뒤에는 품목·수량을 못 바꾼다. 배치가 같은 번호의 Job 을 다른 품목·고객·수량으로 갈아치우면
    이미 만든 롤·검사·출하(COA)가 다른 제품의 것이 된다 — 계보의 뿌리가 바뀐다.
    """
    job_no = w.v.get("job_no")
    if not job_no or not w.v.get("shipment_no"):
        return None
    row = lambda: one("""select i.item_code, c.customer_code, j.order_qty::text as order_qty, j.updated_by,
                                (select count(*) from roll r where r.job_id = j.job_id) as rolls
                           from job j join item i on i.item_id = j.item_id join customer c on c.customer_id = j.customer_id
                          where j.job_no = %s""", (job_no,))  # noqa: E731
    before = row()
    tmp = Path(tempfile.mkdtemp(prefix="q3-mig-over-"))
    try:
        copy_examples(tmp)
        with (tmp / "job.csv").open("a", encoding="utf-8") as f:
            f.write(f"{job_no},{MIG}P02,{MIG}C02,,,,,7,m,2026-12-31,,(예시) 덮어쓰기\n")
        mig("load-master", tmp, by=f"{MIG}over")
        mig("load-print-std", tmp, by=f"{MIG}over")
        rc, out = mig("load-jobs", tmp, by=f"{MIG}over")
        after = row()
        res = {"rc": rc, "before": before, "after": after, "verdict": (re.findall(r"판정: (\w+)", out) or ["?"])[-1],
               "overwritten": (before["item_code"], before["customer_code"], before["order_qty"]) != (after["item_code"], after["customer_code"], after["order_qty"])}
        # 되돌린다 — 뒷정리가 이 Job 을 접두 Q3C- 품목으로 찾는다
        conn.x("""update job set item_id = (select item_id from item where item_code = %s),
                                 customer_id = (select customer_id from customer where customer_code = %s), order_qty = %s
                   where job_no = %s""", (before["item_code"], before["customer_code"], before["order_qty"], job_no))
        return res
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


OVERWRITE: dict | None = None


def check_migration() -> None:
    g = "G-15"
    from lcomfine import migration

    cmds = list(migration.COMMANDS)
    want = ["validate", "load-master", "load-print-std", "load-jobs", "load-history", "report"]
    spec = ROOT / "contracts" / "migration-files.md"
    put(g, "이관 배치 — 6 명령 · 파일 규격 문서", ok(cmds == want and spec.exists()), f"COMMANDS {cmds} · contracts/migration-files.md {'있음' if spec.exists() else '없음'}")
    examples = SRC / "lcomfine" / "migration" / "examples"
    rc, out = mig("validate", examples)
    put(g, "validate — (예시) 폴더 원본 검증 (적재하지 않는다)", ok(rc == 0 and "판정: PASS" in out), f"rc {rc} · {(out.strip().splitlines() or [''])[-1]}")

    tmp = Path(tempfile.mkdtemp(prefix="q3-mig-"))
    try:
        good = tmp / "good"
        copy_examples(good)
        before_all = {t: n(f"select count(*) as n from {t}") for t in MIG_TABLES}
        runs = []
        for c in ("load-master", "load-print-std", "load-jobs"):
            rc1, out1 = mig(c, good)
            first = mig_counts()
            rc2, out2 = mig(c, good)
            second = mig_counts()
            runs.append((c, rc1, rc2, first == second, sum(second.values()), out1, out2))
        counts = mig_counts()
        expect = {"item": 4, "customer": 2, "process": 3, "equipment": 2, "defect_code": 2, "plate_spec": 1, "anilox": 1, "ink_formula": 1,
                  "ink_formula_component": 2, "job": 2, "job_lot": 2}       # (예시) CSV 의 데이터 행 수
        idem = all(r[3] for r in runs) and all(r[1] == 0 and r[2] == 0 for r in runs)
        put(g, "적재 3명령 ×2 — 재실행 멱등 (행 수 동일) · 건수 = CSV 행 수", ok(idem and counts == expect),
            f"2회 실행 rc {[(r[0], r[1], r[2]) for r in runs]} · 1회째 = 2회째 {all(r[3] for r in runs)} · 적재 행 {counts}"
            + ("" if counts == expect else f" ≠ CSV {expect}"))
        second_report = all("신규" in r[6] and re.search(r"판정: PASS — 읽음 \d+ · 적재 \d+ · 오류 0", r[6]) for r in runs)
        logs = n("select count(*) as n from sys_migration_log where run_by = %s", (f"{MIG}check",))
        put(g, "건수·오류 리포트 — 실행마다 읽음·적재·오류 수 출력 + sys_migration_log 한 줄씩", ok(second_report and logs == 22),
            f"출력에 판정 줄 {second_report} · sys_migration_log {logs}줄 (기대 파일 11 × 2회 = 22)")
        rc, out = mig("load-history", good)
        put(g, "load-history — 빈 (예시) 이력 파일: 적재 0 · 범위 미확정 (D-01) 명시", ok(rc == 0 and "미확정 (D-01)" in out),
            f"rc {rc} · 미확정 (D-01) 문구 {'있음' if '미확정 (D-01)' in out else '없음'} — 실제 이관(기존 MES 접근)은 D-01 로 범위 밖")
        rc, out = mig("report", good)
        put(g, "report — 로그 ↔ 테이블 행 수 · 파일 키 대조", ok(rc == 0 and "판정: PASS" in out),
            f"rc {rc} · {(out.strip().splitlines() or [''])[-1]}")

        # ── 형식 오류 행: 조용히 사라지지 않는가 ──
        badrow = tmp / "badrow"
        copy_examples(badrow)
        with (badrow / "item.csv").open("a", encoding="utf-8") as f:
            f.write(f"{MIG}BAD1,형식 오류 (예시),반제품,,m,Y\n")            # item_type 이 선택지 밖
            f.write(f"{MIG}BAD2,,제품,,m,Y\n")                             # 필수값(품목명) 없음
        with (badrow / "job.csv").open("a", encoding="utf-8") as f:
            f.write(f"{MIG}JBAD,{MIG}NOITEM,{MIG}C01,,,,,100,m,2026-12-01,,(예시)\n")   # 없는 품목 코드
            f.write(f"{MIG}JBAD2,{MIG}P01,{MIG}C01,,,,,백,m,2026-13-45,,(예시)\n")      # 수량·날짜 형식 오류
        rcv, outv = mig("validate", badrow)
        rc1, out1 = mig("load-master", badrow)
        rc3, out3 = mig("load-jobs", badrow)
        loaded_bad = n("select count(*) as n from item where item_code like %s", (f"{MIG}BAD%",)) + n("select count(*) as n from job where job_no like %s", (f"{MIG}JBAD%",))
        named = all(x in outv for x in (f"{MIG}BAD1", f"{MIG}BAD2", f"{MIG}JBAD")) and f"{MIG}BAD1" in out1 and f"{MIG}JBAD" in out3
        logged = n("select count(*) as n from sys_migration_log where run_by = %s and error_count > 0 and error_detail like %s", (f"{MIG}check", f"%{MIG}BAD1%"))
        kept = mig_counts() == expect
        put(g, "형식 오류 행 — 건너뛰되 리포트·로그에 드러난다 (조용히 사라지지 않는다)",
            ok(rcv == 1 and rc1 == 1 and rc3 == 1 and loaded_bad == 0 and named and logged >= 1 and kept),
            f"오류 4행(선택지 밖 · 필수값 없음 · 없는 참조 · 수량/날짜 형식) → validate rc {rcv} · load-master rc {rc1} · load-jobs rc {rc3} · 적재된 오류 행 {loaded_bad} · "
            f"출력에 그 행의 키 {'있음' if named else '없음'} · 로그 error_detail {logged}줄 · 정상 행은 그대로 {kept}")

        # ── 망가진 파일: 열 누락 · 인코딩 · 파일 없음 ──
        results = []
        nocol = tmp / "nocol"
        copy_examples(nocol)
        (nocol / "customer.csv").write_text(f"customer_code,note,use_yn\n{MIG}CX,,Y\n", encoding="utf-8")      # 필수 열 customer_name 없음
        rc, out = mig("load-master", nocol)
        results.append(("필수 열 누락", rc == 1 and "customer.csv" in out and n("select count(*) as n from customer where customer_code = %s", (f"{MIG}CX",)) == 0
                        and "Traceback" not in out, f"rc {rc}"))
        enc = tmp / "enc"
        copy_examples(enc)
        (enc / "item.csv").write_bytes((examples / "item.csv").read_text(encoding="utf-8").replace("IMP-", MIG).replace(f"{MIG}P01", f"{MIG}ENC").encode("cp949"))
        rc, out = mig("load-master", enc)
        garbled = n("select count(*) as n from item where item_code = %s", (f"{MIG}ENC",))
        results.append(("CP949 인코딩", rc == 1 and garbled == 0 and "item.csv" in out and "Traceback" not in out, f"rc {rc} · 깨진 글자로 적재된 행 {garbled}{' · Traceback' if 'Traceback' in out else ''}"))
        nofile = tmp / "nofile"
        copy_examples(nofile)
        (nofile / "defect_code.csv").unlink()
        rc, out = mig("load-master", nofile)
        results.append(("필수 파일 없음", rc == 1 and "파일 없음" in out and "Traceback" not in out, f"rc {rc}"))
        extra = tmp / "extra"
        copy_examples(extra)
        (extra / "anilox.csv").write_text(f"anilox_code,anilox_name,line_count,cell_volume,note,use_yn,plc_tag\n{MIG}AX,규격 밖 열 (예시),,,,Y,X\n", encoding="utf-8")
        rc, out = mig("load-print-std", extra)
        results.append(("규격에 없는 열", rc == 1 and n("select count(*) as n from anilox where anilox_code = %s", (f"{MIG}AX",)) == 0 and "Traceback" not in out, f"rc {rc}"))
        hist = tmp / "hist"
        copy_examples(hist)
        with (hist / "material_lot.csv").open("a", encoding="utf-8") as f:
            f.write(f"{MIG}LOT1,{MIG}R01,(예시),,100,m,2026-09-01,합격\n")
        rc, out = mig("load-history", hist)
        results.append(("과거 이력 데이터 행", rc == 1 and "미확정 (D-01)" in out and n("select count(*) as n from material_lot where lot_no = %s", (f"{MIG}LOT1",)) == 0, f"rc {rc} · 적재 0"))
        rc, out = run(["uv", "run", "python", "-m", "lcomfine.migration", "load-master", "--dir", str(tmp / "none")], timeout=60)
        results.append(("없는 폴더", rc != 0 and "Traceback" not in out, f"rc {rc}"))
        failed = [f"{name}({fact})" for name, good_, fact in results if not good_]
        put(g, "망가진 파일 — 열 누락 · 인코딩 · 파일 없음 · 규격 밖 열 · 이력 데이터 · 없는 폴더", ok(not failed),
            " · ".join(f"{name} {fact}" for name, _, fact in results) + (f" — 미달 {failed}" if failed else " · 전부 종료코드 ≠ 0 + 사유 출력 + 부분 적재 0"))
        o = OVERWRITE
        if o is None:
            put(g, "적재 — 화면에서 만든(실적·출하가 있는) Job 을 덮어쓰지 않는다", UNVERIFIED, "임시 Job 을 만들지 못해 재지 못했다")
        else:
            put(g, "적재 — 화면에서 만든(실적·출하가 있는) Job 을 덮어쓰지 않는다", ok(not o["overwritten"]),
                f"롤 {o['before']['rolls']}개 · 승인된 출하가 있는 Job 과 같은 번호를 job.csv 에 넣고 load-jobs → rc {o['rc']} · 판정 {o['verdict']} · "
                f"품목 {o['before']['item_code']}→{o['after']['item_code']} · 고객 {o['before']['customer_code']}→{o['after']['customer_code']} · "
                f"수량 {o['before']['order_qty']}→{o['after']['order_qty']} (updated_by {o['after']['updated_by']})"
                + (" — 경고 없이 갈아치운다 (F-JOB-02 의 '실적 뒤 품목·수량 변경 금지' 를 배치가 우회)" if o["overwritten"] else ""))
        after_all = {t: n(f"select count(*) as n from {t}") for t in MIG_TABLES}
        w = World()
        removed = w.cleanup()
        final_all = {t: n(f"select count(*) as n from {t}") for t in MIG_TABLES}
        left = sum(mig_counts().values())
        put(g, "뒷정리 — 검사기가 적재한 행을 지웠다", ok(left == 0),
            f"이 실행의 접두 {MIG} 로 적재했던 행을 전부 삭제 → 잔여 {left} · sys_migration_log({MIG}) {n('select count(*) as n from sys_migration_log where run_by like %s', (f'{MIG}%',))}줄")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ═════════════════════════════════════════════════════════════════════════
# G-16 ERP
# ═════════════════════════════════════════════════════════════════════════
def check_erp() -> None:
    g = "G-16"
    from fastapi import HTTPException

    from lcomfine.app import erp

    ad = erp.adapter()
    res = []
    for name, call in (("status", lambda: ad.status()), ("receive", lambda: ad.receive("job")), ("send", lambda: ad.send("shipment", {}))):
        try:
            got = call()
            res.append(f"{name} → 값을 돌려줌 {str(got)[:40]}")
        except HTTPException as exc:
            msg = exc.detail.get("message") if isinstance(exc.detail, dict) else exc.detail
            res.append(f"{name} {exc.status_code} {msg}")
        except Exception as exc:  # noqa: BLE001 — 501 이 아닌 예외도 실측이다
            res.append(f"{name} {type(exc).__name__}")
    good = all("501 ERP 연계 미확정 (D-02)" in x for x in res)
    put(g, "어댑터 — app/erp.py 의 호출 3종이 전부 501 `ERP 연계 미확정 (D-02)`", ok(good), " · ".join(res))
    http_res = []
    for method, path in (("GET", "/erp/status"), ("GET", "/erp/job"), ("POST", "/erp/shipment"), ("GET", "/erp/anything")):
        r = cl("admin").request(method, path)
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        h = cl("admin").request(method, path, headers=HTML)
        http_res.append((f"{method} {path}", r.status_code, body.get("message"), body.get("decision"), h.status_code, "ERP 연계 미확정 (D-02)" in h.text))
    good = all(st == 501 and msg == "ERP 연계 미확정 (D-02)" and dec == "D-02" and hst == 501 and shown for _, st, msg, dec, hst, shown in http_res)
    r = cl(None).get("/erp/status")
    put(g, "엔드포인트 — /erp/* 는 JSON·브라우저 모두 501 + 문구 (미로그인 401)", ok(good and r.status_code == 401),
        " · ".join(f"{p} {st} `{msg}` 화면 {hst}" for p, st, msg, _, hst, _ in http_res) + f" · 미로그인 {r.status_code}")
    # 조용한 폴백 — erp 를 부르는 곳이 예외를 삼키거나, erp.py 가 가짜 값을 돌려주는가 (정적)
    src = (SRC / "lcomfine" / "app" / "erp.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    tries = sum(isinstance(x, ast.Try) for x in ast.walk(tree))
    returns = [x for x in ast.walk(tree) if isinstance(x, ast.Return) and x.value is not None
               and not (isinstance(x.value, ast.Call) or isinstance(x.value, ast.Name))]
    callers = []
    for f in (SRC / "lcomfine").rglob("*.py"):
        if f.name == "erp.py":
            continue
        t = f.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(t)):
            if isinstance(node, ast.Try) and re.search(r"\berp(_adapter)?\.", ast.get_source_segment(t, node) or ""):
                callers.append(str(f.relative_to(ROOT)))
    put(g, "조용한 폴백 0 — erp.py 에 try/except·가짜 반환 없음, 호출부가 501 을 삼키지 않음 (정적)", ok(tries == 0 and not returns and not callers),
        f"erp.py try {tries} · 값 반환 {len(returns)} · erp 호출을 try 로 감싼 파일 {callers or 0}")
    # 화면에 ERP 값을 지어내 보이는 곳이 없는가 — 템플릿의 ERP 언급은 `미확정 (D-02)` 와 함께여야 한다
    fake = []
    for f in (SRC / "lcomfine" / "app" / "templates").rglob("*.html"):
        for i, ln in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"\bERP\b", ln) and "D-02" not in ln and "미확정" not in ln and "{#" not in ln:
                fake.append(f"{f.relative_to(ROOT)}:{i}")
    put(g, "화면 — ERP 언급은 `미확정 (D-02)` 와 함께 (정적)", ok(not fake), f"미확정 표기 없이 ERP 를 말하는 템플릿 줄 {fake[:3] or 0}")


# ═════════════════════════════════════════════════════════════════════════
# G-18 접근 로그 · 세션
# ═════════════════════════════════════════════════════════════════════════
def check_logs(w: World) -> None:
    g = "G-18"
    v = w.v
    user = v.get("tmp_user")
    # (1) 로그인 성공·실패·로그아웃 — 임시 계정으로
    if not user:
        put(g, "로그인 — 성공·실패·로그아웃이 남는다", UNVERIFIED, f"임시 계정을 만들지 못했다 — {w.error}")
    else:
        cl("admin").post(f"/sys/users/{user}", data={"status": "정상"})      # 세션 검사가 중지시킨 임시 계정을 되살린다
        since = log_max()
        c = TestClient(app, raise_server_exceptions=False)
        r1 = c.post("/login", data={"login_id": user, "password": "틀린-" + secrets.token_hex(4)}, follow_redirects=False)
        r0 = c.post("/login", data={"login_id": f"{TMP_USER}none", "password": "x"}, follow_redirects=False)
        r2 = c.post("/login", data={"login_id": user, "password": w.tmp_password}, follow_redirects=False)
        rv = c.get("/trc/trace", headers=HTML)
        r3 = c.post("/logout", follow_redirects=False)
        rows = [x for x in logs_since(since) if (x["login_id"] or "").startswith(TMP_USER)]
        kinds = [(x["log_type"], x["result"], x["detail"]) for x in rows]
        fail_pw = any(t == "로그인" and res == "실패" and "비밀번호 불일치" in d for t, res, d in kinds)
        fail_id = any(t == "로그인" and res == "실패" and "미등록" in d for t, res, d in kinds)
        okay = any(t == "로그인" and res == "성공" and d == "로그인 성공" for t, res, d in kinds)
        out_ = any(t == "로그인" and "로그아웃" in d for t, res, d in kinds)
        view = [x for x in rows if x["log_type"] == "조회" and x["screen_id"] == "TRC-01"]
        when = all(x["logged_at"] is not None for x in rows)
        leaked = n("select count(*) as n from sys_access_log where log_id > %s and (detail like %s or target like %s)",
                   (since, f"%{w.tmp_password}%", f"%{w.tmp_password}%"))
        put(g, "로그인 — 성공·실패(비밀번호 불일치·미등록 ID)·로그아웃이 누가·언제와 함께 남는다",
            ok(r1.status_code == 401 and r0.status_code == 401 and r2.status_code == 303 and r3.status_code == 303 and fail_pw and fail_id and okay and out_ and when and not leaked),
            f"실패(비밀번호) {fail_pw} · 실패(미등록 ID) {fail_id} · 성공 {okay} · 로그아웃 {out_} · 시각 {when} · 비밀번호 값이 로그에 {leaked}건")
        put(g, "화면 조회 — 로그인한 사용자가 화면을 열면 `조회` 한 줄", ok(rv.status_code == 200 and len(view) == 1 and view[0]["login_id"] == user),
            f"임시 계정이 /trc/trace 1회 조회 → 로그 {len(view)}줄 (화면 TRC-01 · {view[0]['method'] + ' ' + view[0]['path'] if view else '-'})")

    # (1b) 읽기 기능 전수 — 조회·출력 기능의 엔드포인트를 열 때마다 `조회` 한 줄
    reads = [f for f in contracts.functions() if not f.is_write and not f.is_batch]
    fill = {"job_no": v.get("job_no"), "lot_no": v.get("lot_no"), "shipment_no": v.get("shipment_no")}
    silent, failed = [], []
    reader = None
    if user:
        reader = TestClient(app, raise_server_exceptions=False)
        if reader.post("/login", data={"login_id": user, "password": w.tmp_password}, follow_redirects=False).status_code != 303:
            reader = None
    for f in reads:
        path = f.api.split(" ", 1)[1]
        fill["roll_no"] = v.get("print_roll") if path.startswith("/pop/") else v.get("roll")
        if any(fill.get(k) is None for k in re.findall(r"\{(\w+)\}", path)):
            failed.append(f"{f.id}(임시 데이터 없음)")
            continue
        url = re.sub(r"\{(\w+)\}", lambda m: str(fill[m.group(1)]), path)
        query = {"/trc/trace/forward": f"?no={v.get('lot_no')}", "/trc/trace/backward": f"?no={v.get('shipment_no')}"}.get(url, "")
        since = log_max()
        if f.id.startswith("F-SYS-") or reader is None:        # 시스템 관리는 관리자만 연다 (다른 실행과 계정을 같이 쓰므로 '한 줄 이상')
            r = cl("admin").get(url + query, headers=HTML)
            got = [x for x in logs_since(since, log_type="조회", login_id="admin") if x["path"] == url]
            good = len(got) >= 1
        else:                                                  # 그 밖은 이 실행만 쓰는 임시 계정(품질) — 정확히 한 줄
            r = reader.get(url + query, headers=HTML)
            got = [x for x in logs_since(since, log_type="조회", login_id=user) if x["path"] == url]
            good = len(got) == 1
        if r.status_code != 200:
            failed.append(f"{f.id}({r.status_code})")
        elif not good:
            silent.append(f"{f.id}(로그 {len(got)}줄)")
    put(g, f"화면 조회 — 읽기 기능 {len(reads)}개 전수: 열 때마다 `조회` 한 줄", ok(not silent and not failed),
        f"조회·출력 엔드포인트 {len(reads)}개를 한 번씩(임시 품질 계정 · 시스템 관리 3개는 관리자) → 200 이 아닌 것 {failed or 0} · 로그가 안 남거나 한 줄이 아닌 것 {silent or 0}")

    # (2) 데이터 변경 — 쓰기 기능 전수: 한 번 부를 때마다 그 기능 ID 로 `변경` 이 정확히 한 줄 (누가·무엇을·언제)
    writes = [f.id for f in contracts.functions() if f.is_write]
    by_fid: dict[str, list[dict]] = {}
    for c_ in w.calls:
        by_fid.setdefault(c_["fid"], []).append(c_)
    not_called = [f for f in writes if f not in by_fid]
    wrong = [f"{c_['fid']}(로그 {c_['delta']}줄)" for c_ in w.calls if c_["status"] == 200 and c_["delta"] != 1]
    no_who = [c_["fid"] for c_ in w.calls if c_["status"] == 200 and c_["delta"] == 1 and not (c_["who"] == c_["role"] and c_["target"] and c_["when"])]
    covered = len(writes) - len(not_called)
    status = PASS if (not not_called and not wrong and not no_who) else (FAIL if (wrong or no_who) else UNVERIFIED)
    put(g, f"데이터 변경 — 쓰기 기능 {len(writes)}개 전수: 성공할 때마다 `변경` 한 줄 (누가·언제·무엇을)", status,
        f"화면 API 로 부른 쓰기 기능 {covered}/{len(writes)} · 호출 {len(w.calls)}회 · 로그가 한 줄이 아닌 호출 {wrong or 0} · 누가/대상이 빈 로그 {no_who or 0}"
        + (f" · 부르지 못한 기능 {not_called} ({w.error})" if not_called else ""))

    # (3) 실패한 쓰기(422·403)는 `변경` 으로 남지 않는다
    since = log_max()
    r422 = cl("admin").post("/bas/items", data={"item_code": f"{PREFIX}FG", "item_name": "중복", "item_type": "제품"})
    r403 = cl("qc").post("/bas/items", data={"item_code": f"{PREFIX}NO", "item_name": "권한 없음", "item_type": "제품"})
    ghost = [x for x in logs_since(since, log_type="변경") if x["path"] == "/bas/items" and PREFIX in (x["target"] or "")]
    denied = [x for x in logs_since(since) if x["login_id"] == "qc" and x["path"] == "/bas/items" and x["method"] == "POST"]
    put(g, "데이터 변경 — 실패한 쓰기(422·403)는 `변경` 으로 남지 않는다", ok(r422.status_code == 422 and r403.status_code == 403 and not ghost),
        f"중복 코드 {r422.status_code} · 조회 역할의 쓰기 {r403.status_code} · 그 사이 `변경` 로그 {len(ghost)}줄")
    put("QA3-LOG", "참고 — 거부된 접근(403)은 접근 로그에 남지 않는다", WARN if not denied else PASS,
        f"품질 계정의 POST /bas/items 403 → sys_access_log {len(denied)}줄 (게이트 문구에 403 기록은 없다 — 보강 권고)")

    # (4) 시스템 관리 > 로그 화면에서 조회된다 — 구분별
    seen = {}
    target = f"sys_user:{user}"          # 가장 최근의 관리자 변경 (임시 계정 중지 F-SYS-03)
    r = cl("admin").get(f"/sys/logs?log_type=변경&login_id=admin&date_from={date.today()}", headers=HTML)
    seen["변경"] = r.status_code == 200 and "F-SYS-03" in r.text and target in r.text
    if user:
        r = cl("admin").get(f"/sys/logs?log_type=로그인&login_id={user}", headers=HTML)
        seen["로그인 성공"] = "로그인 성공" in r.text
        seen["로그인 실패"] = "비밀번호 불일치" in r.text
        r = cl("admin").get(f"/sys/logs?log_type=조회&login_id={user}", headers=HTML)
        seen["조회"] = "TRC-01" in r.text or "/trc/trace" in r.text
    r = cl("qc").get("/sys/logs", headers=HTML)
    put(g, "로그 화면 — 시스템 관리 > 로그에서 로그인·조회·변경이 조회된다 (관리자만)", ok(all(seen.values()) and len(seen) == 4 and r.status_code == 403),
        " · ".join(f"{k} {'보임' if x else '안 보임'}" for k, x in seen.items()) + f" · 품질 계정 {r.status_code}")
    # (5) 로그는 고칠 수 없는가 — 로그를 지우거나 고치는 엔드포인트가 없다 (정적)
    hits = []
    for f in (SRC / "lcomfine" / "app" / "routers").glob("*.py"):
        t = f.read_text(encoding="utf-8")
        if re.search(r"(delete\s+from|update)\s+sys_access_log", t, re.I):
            hits.append(f.name)
    put(g, "로그 보존 — 라우터에 접근 로그를 고치거나 지우는 SQL 이 없다 (정적)", ok(not hits), f"sys_access_log 를 update/delete 하는 라우터 {hits or 0}")


def check_sessions(w: World) -> None:
    """세션·비밀번호 저장 (G-19 의 운영 쪽). 임시 계정으로만 — 시드 계정 4개는 건드리지 않는다."""
    g = "G-19"
    user = w.v.get("tmp_user")
    # 세션 쿠키 속성
    c = TestClient(app, raise_server_exceptions=False)
    r = c.post("/login", data={"login_id": "qc", "password": get_settings().seed_password or ""}, follow_redirects=False)
    cookie = r.headers.get("set-cookie", "")
    low = cookie.lower()
    m_ss, m_age = re.search(r"samesite=(\w+)", low), re.search(r"max-age=(\d+)", low)
    samesite, max_age = (m_ss.group(1) if m_ss else "없음"), (int(m_age.group(1)) if m_age else None)
    secure = "; secure" in low
    put(g, "세션 쿠키 — HttpOnly · SameSite", ok("httponly" in low and samesite in ("lax", "strict")),
        f"HttpOnly {'있음' if 'httponly' in low else '없음'} · SameSite {samesite} · Secure {'있음' if secure else '없음'} · Max-Age {max_age}초")
    put("QA3-SES", "참고 — 세션 쿠키 Secure · 유효 기간 · 자동 로그아웃", PASS if secure else WARN,
        f"Secure {'있음' if secure else '없음(운영 환경 D-03 이 HTTPS 면 켜야 한다)'} · 쿠키 수명 {max_age // 86400 if max_age else '?'}일 · "
        f"자동 로그아웃 {get_settings().session_idle_label} · 로그인 실패 잠금 없음 (D-20) · 비밀번호 길이·복잡도 규칙 없음 (D-20)")
    # 비밀번호 저장 방식
    rows = conn.q("select login_id, password_hash from sys_user")
    weak = [x["login_id"] for x in rows if not re.fullmatch(r"pbkdf2_sha256\$\d{5,}\$[A-Za-z0-9+/=]+\$[A-Za-z0-9+/=]+", x["password_hash"] or "")
            or int(x["password_hash"].split("$")[1]) < 100_000]
    salts = {x["password_hash"].split("$")[2] for x in rows if x["password_hash"].count("$") == 3}
    plain = [x["login_id"] for x in rows if get_settings().seed_password and get_settings().seed_password in (x["password_hash"] or "")]
    cols = [x["column_name"] for x in conn.q("select column_name from information_schema.columns where table_name = 'sys_user'")]
    put(g, "비밀번호 저장 — 솔트 든 PBKDF2 해시만 (평문·약한 해시 0)", ok(not weak and not plain and len(salts) == len(rows) and "password" not in cols),
        f"sys_user {len(rows)}행 전부 pbkdf2_sha256 · 반복 {sorted({x['password_hash'].split('$')[1] for x in rows if x['password_hash'].count('$') == 3})} · "
        f"솔트 {len(salts)}종(계정마다 다름) · 형식 밖 {weak or 0} · 평문 {plain or 0} · 컬럼 {[c_ for c_ in cols if 'pass' in c_]}")
    r = cl("admin").get("/sys/users", headers=HTML)
    put(g, "비밀번호 노출 — 사용자 화면·/health 에 해시·비밀이 나오지 않는다", ok("pbkdf2_sha256" not in r.text and (get_settings().session_secret or "\0") not in cl(None).get("/health").text),
        f"/sys/users 에 해시 {'있음' if 'pbkdf2_sha256' in r.text else '없음'} · /health 에 세션 비밀 없음")

    # 세션 무효화 — 중지·잠금된 계정의 살아 있는 세션, 로그아웃 뒤의 쿠키
    if not user:
        put(g, "세션 무효화 — 중지·잠금 계정의 세션 · 로그아웃 뒤 쿠키", UNVERIFIED, f"임시 계정을 만들지 못했다 — {w.error}")
        return
    facts, holes = [], []
    s1 = TestClient(app, raise_server_exceptions=False)
    s1.post("/login", data={"login_id": user, "password": w.tmp_password}, follow_redirects=False)
    base = s1.get("/trc/trace").status_code
    # 잠금
    cl("admin").post(f"/sys/users/{user}", data={"status": "잠금"})
    locked = s1.get("/trc/trace").status_code
    facts.append(f"잠금 뒤 같은 세션 {locked}")
    if locked == 200:
        holes.append("잠금")
    cl("admin").post(f"/sys/users/{user}", data={"status": "정상"})
    # 로그아웃 뒤 옛 쿠키 재사용
    jar = dict(s1.cookies)
    s1.post("/logout", follow_redirects=False)
    replay = TestClient(app, raise_server_exceptions=False, cookies=jar)
    rp = replay.get("/trc/trace").status_code
    facts.append(f"로그아웃 뒤 옛 쿠키 {rp}")
    if rp == 200:
        holes.append("로그아웃 뒤 쿠키 재사용")
    # 중지 (F-SYS-03) — 쓰기 기능 전수에도 센다
    s2 = TestClient(app, raise_server_exceptions=False)
    s2.post("/login", data={"login_id": user, "password": w.tmp_password}, follow_redirects=False)
    try:
        w.w("F-SYS-03", "admin", f"/sys/users/{user}/delete")
    except RuntimeError as exc:
        facts.append(f"F-SYS-03 실패 {exc}")
    stopped = s2.get("/trc/trace").status_code
    relogin = TestClient(app, raise_server_exceptions=False).post("/login", data={"login_id": user, "password": w.tmp_password}, follow_redirects=False).status_code
    facts.append(f"중지 뒤 같은 세션 {stopped} · 새 로그인 {relogin}")
    if stopped == 200:
        holes.append("중지")
    put(g, "세션 무효화 — 중지·잠금된 계정의 살아 있는 세션 · 로그아웃 뒤 쿠키가 막힌다", ok(base == 200 and not holes and relogin == 401),
        " · ".join(facts) + (f" — 계속 통하는 것: {holes} (rbac.current_user 가 쿠키만 읽고 DB 의 계정 상태를 다시 보지 않는다)" if holes else ""))


# ═════════════════════════════════════════════════════════════════════════
# G-19 비밀
# ═════════════════════════════════════════════════════════════════════════
SECRET_PATTERNS = [
    (r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key)\b\s*[:=]\s*[\"']([^\"'\s]{6,})[\"']", "글자 그대로의 비밀 대입"),
    (r"postgres(?:ql)?://[^:/\s]+:([^@\s]{3,})@", "DSN 안의 비밀번호"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "개인 키"),
]
SECRET_OK = re.compile(r"\*\*\*|<[^>]+>|\.\.\.|…|%s|\{|os\.environ|get_settings|token_urlsafe|token_hex|example|예시|틀린|wrong|bad|none|invalid|dummy", re.I)


def check_secrets() -> None:
    g = "G-19"
    values = {k: os.environ.get(k) for k in ("LCOMFINE_SEED_PASSWORD", "LCOMFINE_SESSION_SECRET")}
    _, listed = run(["git", "ls-files", "-co", "--exclude-standard"])
    files = [ROOT / f for f in listed.splitlines() if f.strip()]
    hit_files, pattern_hits = [], []
    for f in files:
        try:
            data = f.read_bytes()
        except OSError:
            continue
        if any(v and v.encode() in data for v in values.values()):
            hit_files.append(str(f.relative_to(ROOT)))
        if f.suffix in (".png", ".jpg", ".lock", ".pyc") or f.name == "uv.lock":
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for i, ln in enumerate(text.splitlines(), 1):
            for pat, label in SECRET_PATTERNS:
                m = re.search(pat, ln)
                if m and not SECRET_OK.search(m.group(0)) and f.name != "check_security.py":
                    pattern_hits.append(f"{f.relative_to(ROOT)}:{i} {label}")
    put(g, "저장소·문서 — 추적·미무시 파일에 시드 비밀번호·세션 비밀 값이 글자 그대로 없다", ok(not hit_files and all(values.values())),
        f"대상 파일 {len(files)}개(코드·문서·산출물·캡처 포함) 중 비밀 값이 든 파일 {hit_files or 0}" + ("" if all(values.values()) else " · .env 에 비밀이 없어 대조하지 못함"))
    put(g, "저장소·문서 — 글자 그대로 박힌 비밀번호·토큰·DSN 비밀번호 패턴 0", ok(not pattern_hits), f"패턴에 걸린 줄 {pattern_hits[:4] or 0}")
    rc_ign, _ = run(["git", "check-ignore", "-q", ".env"])
    _, tracked = run(["git", "ls-files", ".env"])
    hist = []
    for k, v in values.items():
        if v:
            _, out = run(["git", "log", "--all", "--oneline", f"-S{v}"])
            if out.strip():
                hist.append(k)
    put(g, ".env — gitignore 됨 · 추적 안 됨 · 커밋 이력에 비밀 값 없음", ok(rc_ign == 0 and not tracked.strip() and not hist),
        f".env 무시 {'됨' if rc_ign == 0 else '안 됨'} · 추적 {'안 됨' if not tracked.strip() else '됨'} · 이력에 값이 든 커밋 {hist or 0}")
    ex = (ROOT / ".env.example").read_text(encoding="utf-8") if (ROOT / ".env.example").exists() else ""
    filled = [ln.split("=")[0] for ln in ex.splitlines() if re.match(r"LCOMFINE_(SESSION_SECRET|SEED_PASSWORD)=\S", ln)]
    seed_src = "\n".join(f.read_text(encoding="utf-8") for f in (SRC / "lcomfine" / "db").glob("seed*.py"))
    literal_pw = re.findall(r"hash_password\(\s*[\"'][^\"']+[\"']", seed_src)
    put(g, "시드 비밀번호 — LCOMFINE_SEED_PASSWORD 로만 (.env.example 은 빈 값 · 시드 코드에 글자 비밀번호 없음)", ok(not filled and not literal_pw and "seed_password" in seed_src),
        f".env.example 에 값이 채워진 비밀 {filled or 0} · 시드 코드의 글자 비밀번호 {len(literal_pw)} · 시드가 settings.seed_password 를 읽음 {'seed_password' in seed_src}")
    mode = oct((ROOT / ".env").stat().st_mode & 0o777) if (ROOT / ".env").exists() else "없음"
    put("QA3-ENV", "참고 — .env 파일 권한", PASS if mode in ("0o600", "0o400") else WARN, f".env 권한 {mode}")


# ═════════════════════════════════════════════════════════════════════════
# G-20 백업
# ═════════════════════════════════════════════════════════════════════════
def check_backup() -> None:
    g = "G-20"
    tool = ROOT / "tools" / "backup.py"
    if not tool.exists():
        rc1, out1 = run(["make", "backup"], timeout=60)
        rc2, out2 = run(["make", "restore-check"], timeout=60)
        put(g, "make backup — 덤프 생성", FAIL, f"tools/backup.py 없음 · `make backup` rc {rc1} `{(out1.strip().splitlines() or [''])[-1][:60]}`")
        put(g, "make restore-check — 빈 DB 에 복구해 테이블별 행 수 일치", FAIL, f"tools/backup.py 없음 · `make restore-check` rc {rc2} `{(out2.strip().splitlines() or [''])[-1][:60]}`")
        return
    src = tool.read_text(encoding="utf-8")
    counts = lambda: {t["tablename"]: n(f'select count(*) as n from "{t["tablename"]}"') for t in conn.q("select tablename from pg_tables where schemaname = 'public'")}  # noqa: E731
    stamp = time.time()
    rc, out = run(["make", "backup"], timeout=600)
    dumps = [p for p in (ROOT / "backups").glob("*") if p.is_file() and p.stat().st_mtime >= stamp - 1] if (ROOT / "backups").exists() else []
    _, ign = run(["git", "check-ignore", "-q", "backups/x"])
    put(g, "make backup — 덤프 생성 (backups/ · 저장소에 안 들어감)", ok(rc == 0 and dumps and all(p.stat().st_size > 0 for p in dumps)),
        f"rc {rc} · 새 덤프 {[f'{p.name}({p.stat().st_size}B)' for p in dumps] or 0} · backups/ gitignore {'됨' if run(['git', 'check-ignore', '-q', 'backups/x'])[0] == 0 else '안 됨'}")
    # 복구 검증이 운영 DB 를 덮어쓰지 않는지 — 다른 이름의 임시 DB 를 만드는 코드인지 먼저 본다(아니면 돌리지 않는다)
    temp_db = bool(re.search(r"createdb|create database", src, re.I)) and bool(re.search(r"dropdb|drop database", src, re.I))
    if not temp_db:
        put(g, "make restore-check — 별도 임시 DB 에 복구해 테이블별 행 수 일치", FAIL,
            "tools/backup.py 에 임시 DB 를 만들고 지우는 코드가 안 보인다 — lcomfine_db 를 덮어쓸 수 있어 실행하지 않았다")
        return
    before = counts()
    dbs_before = {x["datname"] for x in conn.q("select datname from pg_database")}
    rc, out = run(["make", "restore-check"], timeout=900)
    after = counts()
    dbs_after = {x["datname"] for x in conn.q("select datname from pg_database")}
    changed = {k: (before.get(k), after.get(k)) for k in set(before) | set(after) if before.get(k) != after.get(k) and k != "sys_access_log"}
    said = bool(re.search(r"일치|match", out)) and not re.search(r"불일치|mismatch", out)
    put(g, "make restore-check — 별도 임시 DB 에 복구해 테이블별 행 수 일치", ok(rc == 0 and said and not changed and dbs_after == dbs_before),
        f"rc {rc} · 출력에 행 수 일치 {said} · lcomfine_db 행 수 변화 {changed or 0} · 남은 임시 DB {sorted(dbs_after - dbs_before) or 0} · {(out.strip().splitlines() or [''])[-1][:80]}")


# ═════════════════════════════════════════════════════════════════════════
# 조용한 실패 사냥 (게이트 밖 참고 행 QA3-SF)
# ═════════════════════════════════════════════════════════════════════════
#: 다시 올리지도 기록하지도 않는 except 중 QA3 가 읽어 보고 "데이터를 지어내지 않는다" 고 판정한 것 (파일, 함수) → 사유
REVIEWED_HANDLERS = {
    ("app/auth.py", "verify_password"): "저장된 해시의 형식이 깨졌으면 False = 로그인 거부 (통과시키지 않는다)",
    ("app/auth.py", "session_expired"): "세션의 last_seen 이 날짜가 아니면 만료 판정을 건너뛴다 (서명된 쿠키라 사용자가 못 고친다)",
    ("app/templating.py", "asset_version"): "정적 파일 수정 시각을 못 읽으면 캐시 키 '0' (업무 데이터 아님)",
    ("app/main.py", "health"): "DB 실패를 db.ok=false + 503 으로 그대로 보여 준다",
}


def scan_silent_failures() -> None:
    """`except` 뒤에 기본값·빈 목록·하드코딩으로 넘어가는 곳 — src/ 전체 AST 스캔.

    다시 올리는(raise) 핸들러와, 오류를 목록·로그에 **기록하는** 핸들러(`.fail(` `.append(` `log.exception(`)는 조용한 실패가 아니다.
    둘 다 아닌 핸들러는 사람이 읽어 본 목록(REVIEWED_HANDLERS)에 있어야 한다 — 새로 생기면 FAIL 로 드러난다.
    """
    total, recorded, reviewed, unknown = 0, 0, [], []
    for f in sorted((SRC / "lcomfine").rglob("*.py")):
        text = f.read_text(encoding="utf-8")
        tree = ast.parse(text)
        owner = {}
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for child in ast.walk(fn):
                    if isinstance(child, ast.ExceptHandler):
                        owner[child] = fn.name            # 가장 안쪽 함수가 나중에 덮어쓴다
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            total += 1
            if any(isinstance(x, ast.Raise) for b_ in node.body for x in ast.walk(b_)):
                continue
            calls = [ast.unparse(x.func) for b_ in node.body for x in ast.walk(b_) if isinstance(x, ast.Call)]
            if any(c.endswith((".fail", ".append", ".exception", ".error")) for c in calls):
                recorded += 1
                continue
            key = (str(f.relative_to(SRC / "lcomfine")), owner.get(node, "?"))
            (reviewed if key in REVIEWED_HANDLERS else unknown).append(f"{key[0]}:{node.lineno} {key[1]}()")
    put("QA3-SF", "조용한 실패 — except 뒤 기본값·빈 목록·삼킴 (정적 · src 전체)", PASS if not unknown else FAIL,
        f"except {total}곳 = 다시 올림 {total - recorded - len(reviewed) - len(unknown)} · 오류를 기록 {recorded} · 검토한 무해 핸들러 {len(reviewed)} · "
        f"검토 안 된 삼킴 {unknown or 0}")


DB_DOWN_SCRIPT = r'''
import json, os, re, sys, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, "src")
from fastapi.testclient import TestClient
from lcomfine.app import nav
from lcomfine.app.main import app
from lcomfine.app.settings import get_settings
HTML = {"accept": "text/html"}
clients = {}
for role in ("admin", "prod", "qc", "field"):
    c = TestClient(app, raise_server_exceptions=False)
    assert c.post("/login", data={"login_id": role, "password": get_settings().seed_password}, follow_redirects=False).status_code == 303
    c.get("/")                                  # 권한 캐시를 데운다 (끊긴 뒤 캐시로 통과하는 경로까지 본다)
    clients[role] = c
board = TestClient(app, raise_server_exceptions=False)
board.post("/login", data={"login_id": "prod", "password": get_settings().seed_password, "device": "board"}, follow_redirects=False)
os.environ["LCOMFINE_PG_DSN"] = "postgresql:///lcomfine_db?host=/nonexistent-q3-socket&connect_timeout=2"   # 이 프로세스의 접속 설정만
out = {"pages": [], "writes": [], "extra": {}}
paths = ["/"] + [s.path for s in nav.SCREENS]
for role, c in clients.items():
    for p in paths:
        r = c.get(p, headers=HTML)
        if r.status_code == 403:
            continue
        out["pages"].append([role, p, r.status_code, "서비스 일시 중단" in r.text])
for role, p, data in (("admin", "/bas/items", {"item_code": "Q3C-DOWN", "item_name": "x", "item_type": "제품"}),
                      ("field", "/mat/receipts", {"item_code": "EX-RM-01", "received_qty": "1"}),
                      ("field", "/mat/inputs", {"work_id": "1", "lot_no": "X"}),
                      ("qc", "/qua/inspections", {"roll_no": "X", "result": "합격"}),
                      ("field", "/shp/shipments", {"job_no": "X", "ship_date": "2026-10-03"})):
    r = clients[role].post(p, data=data)
    out["writes"].append([role, p, r.status_code, r.text[:80]])
r = TestClient(app).get("/health"); out["extra"]["health"] = [r.status_code, r.json().get("status")]
r = clients["qc"].get("/trc/trace/backward?no=S000", headers=HTML); out["extra"]["trace"] = r.status_code
r = clients["field"].get("/pop/work?no=J000", headers=HTML); out["extra"]["scan"] = r.status_code
r = board.get("/sta/board", headers=HTML); out["extra"]["board"] = [r.status_code, bool(re.search(r'<body[^>]*data-refresh-seconds="[1-9]', r.text)) and "/static/app.js" in r.text]
r = TestClient(app, raise_server_exceptions=False).post("/login", data={"login_id": "admin", "password": "x"}, headers=HTML); out["extra"]["login"] = [r.status_code, "서비스 일시 중단" in r.text]
r = clients["admin"].get("/erp/status"); out["extra"]["erp"] = r.status_code
print("RESULT " + json.dumps(out, ensure_ascii=False))
'''


def check_db_down() -> None:
    """그 프로세스의 접속 설정만 잘못된 값으로 바꾼 상태에서 화면이 200 을 주면 결함 (goal §2.5: 503 `서비스 일시 중단`)."""
    rc, out = run(["uv", "run", "python", "-c", DB_DOWN_SCRIPT], timeout=600)
    m = re.search(r"^RESULT (.*)$", out, re.M)
    if not m:
        put("QA3-SF", "조용한 실패 — DB 접속을 끊은 상태의 화면 (하위 프로세스)", UNVERIFIED, f"재지 못했다 rc {rc} · {(out.strip().splitlines() or [''])[-1][:160]}")
        return
    d = json.loads(m.group(1))
    alive = [f"{role} {p} {st}" for role, p, st, shown in d["pages"] if st != 503 or not shown]
    wr = [f"{role} POST {p} {st}" for role, p, st, _ in d["writes"] if st != 503]
    ex = d["extra"]
    put("QA3-SF", "조용한 실패 — DB 를 끊으면 로그인한 화면 전부 503 `서비스 일시 중단` (실측)", PASS if not alive else FAIL,
        f"역할 4 × 화면(메인 + 중메뉴 32, 권한 없는 칸 제외) {len(d['pages'])}건 중 503 이 아닌 것 {len(alive)} {alive[:6]}")
    put("QA3-SF", "조용한 실패 — DB 를 끊으면 쓰기·스캔·추적·로그인·/health 도 503 (실측)",
        PASS if (not wr and ex["health"][0] == 503 and ex["trace"] == 503 and ex["scan"] == 503 and ex["login"] == [503, True]) else FAIL,
        f"쓰기 5종 503 아닌 것 {wr or 0} · /health {ex['health']} · 역추적 {ex['trace']} · 스캔 진입 {ex['scan']} · 로그인 POST {ex['login'][0]} · "
        f"ERP {ex['erp']}(세션 확인이 요청마다 DB 를 본다(D-26) — DB 가 끊기면 ERP 주소도 501 보다 먼저 503 이다. 200 이면 조용한 실패)")
    put("QA3-SF", "현황판 — DB 가 잠깐 끊긴 뒤 스스로 돌아오는가 (503 화면의 새로고침 태그)", PASS if ex["board"][1] else FAIL,
        f"현황판 채널에서 DB 끊김 → {ex['board'][0]} · 그 화면에 새로고침 장치(data-refresh-seconds + app.js) {'있음' if ex['board'][1] else '없음 — DB 가 돌아와도 현황판은 오류 화면에 멈춘다'}")


# ═════════════════════════════════════════════════════════════════════════
def run_probe(w: World) -> tuple[dict | None, str]:
    keys = ("job_no", "lot_no", "print_roll", "roll", "shipment_no", "probe_shipment_no", "probe_rolls")
    world = {k: w.v[k] for k in keys if w.v.get(k)}
    out_file = ROOT / "outputs" / "e2e" / "_probe.json"
    rc, out = run(["uv", "run", "--with", "playwright", "python", str(ROOT / "tools" / "e2e" / "probe.py"),
                   "--world", json.dumps(world, ensure_ascii=False), "--out", str(out_file)], timeout=600)
    if rc != 0:
        return None, f"probe.py rc {rc} · {(out.strip().splitlines() or [''])[-1][:160]}"
    try:
        data = json.loads(out_file.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 — 결과 파일이 없으면 재지 못한 것이다
        return None, f"결과 파일을 읽지 못했다 — {exc}"
    return data, "; ".join(f"{k}: {v}" for k, v in data.get("errors", {}).items())


def _tag_alive(tag: str) -> bool:
    """꼬리표(프로세스 번호 % 0xFFFF)를 가진 실행이 아직 살아 있는가. 꼬리표가 없는 접두(`Q3E-` 등)는 False."""
    if not re.fullmatch(r"[0-9A-Fa-f]{4}", tag or ""):
        return False
    base = int(tag, 16)
    for pid in (base, base + 0xFFFF, base + 2 * 0xFFFF):
        if pid <= 1:
            continue
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            continue
        except PermissionError:
            return True
    return False


def cleanup_stale(hours: float = 2.0) -> dict:
    """중단된 실행이 남긴 QA3 임시 행 — 만든 지 `hours` 시간이 넘은 접두만 지운다(지금 돌고 있는 다른 실행의 것은 건드리지 않는다)."""
    out: dict = {}
    rows = conn.q("""select distinct substring(item_code from %s) as p from item
                      where item_code ~ %s and created_at < now() - make_interval(secs => %s)""", (STALE_RE, STALE_RE, hours * 3600))
    for r in rows:
        if r["p"] and r["p"] not in (PREFIX, MIG):
            if _tag_alive(r["p"][3:-1]):          # 지금 돌고 있는 다른 실행(검사기·pytest)의 것은 나이와 상관없이 건드리지 않는다
                out[r["p"]] = "실행 중 — 건너뜀"
                continue
            out[r["p"]] = sum(World().cleanup((r["p"],), users="q3-none-").values())
    old_users = conn.q("select login_id from sys_user where login_id ~ '^q3[ct]' and created_at < now() - make_interval(secs => %s)", (hours * 3600,))
    for u in old_users:
        if _tag_alive(u["login_id"][3:7]):
            continue
        conn.x("delete from sys_access_log where login_id = %s or target = %s", (u["login_id"], f"sys_user:{u['login_id']}"))
        conn.x("delete from sys_user where login_id = %s", (u["login_id"],))
        out[u["login_id"]] = 1
    return out


def main() -> int:
    if "--cleanup-all" in sys.argv:      # 사람이 부른다 — 중단된 실행이 남긴 QA3 임시 행을 나이와 상관없이 지운다 (살아 있는 실행의 것은 건너뛴다)
        print("지운 것:", cleanup_stale(hours=0))
        return 0
    only = None
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1]
    want = lambda gid: only is None or only == gid  # noqa: E731
    if not get_settings().seed_password:
        for gid in ("G-13", "G-14", "G-18"):
            put(gid, "시드 계정 로그인", FAIL, "LCOMFINE_SEED_PASSWORD 미설정 — 로그인할 수 없다")
        return finish()

    w = World()
    left = cleanup_stale()                  # 중단된 예전 실행이 남긴 것(2시간 넘은 것)부터 지운다
    if left:
        print(f"(예전 실행의 잔여를 지웠다: {left})", file=sys.stderr)
    probe, why = None, "--no-browser"
    try:
        try:
            w.build()
        except Exception as exc:  # noqa: BLE001 — 세계를 끝까지 못 만든 것도 실측이다 (그 뒤 기능은 `부르지 못한 기능` 으로 나온다)
            w.error = f"{type(exc).__name__}: {str(exc)[:200]}"
        if want("G-13"):
            check_channels(w)
        if want("G-14"):
            check_outputs(w)
        if "--no-browser" not in sys.argv and (want("G-13") or want("G-14")):
            probe, why = run_probe(w)
        if want("G-13"):
            check_channels_browser(probe, why)
        if want("G-14"):
            check_outputs_browser(probe, why)
        if want("G-18") or want("G-19"):
            # 세션 검사가 F-SYS-03(임시 계정 중지)을 부르므로 로그 판정보다 먼저 돈다
            rows_before = len(ROWS)
            check_sessions(w)
            session_rows = ROWS[rows_before:]
            del ROWS[rows_before:]
            if want("G-18"):
                check_logs(w)
            if want("G-19"):
                ROWS.extend(session_rows)
        if want("G-15"):
            global OVERWRITE
            try:
                OVERWRITE = probe_migration_overwrite(w)
            except Exception as exc:  # noqa: BLE001 — 재지 못한 것은 미검증으로 나온다
                print(f"(이관 덮어쓰기 실측 실패: {exc})", file=sys.stderr)
    finally:
        removed = w.cleanup()
    if want("G-15"):
        check_migration()
    if want("G-16"):
        check_erp()
    if want("G-19"):
        check_secrets()
    if want("G-20"):
        check_backup()
    if only is None or only == "SF":
        scan_silent_failures()
        check_db_down()
    leftovers = {t: n(f"select count(*) as n from {t} where {c} like %s or {c} like %s", (f"{PREFIX}%", f"{MIG}%"))
                 for t, c in (("item", "item_code"), ("customer", "customer_code"), ("job", "job_no"))}
    leftovers["sys_user(q3c-)"] = n("select count(*) as n from sys_user where login_id like %s", (f"{TMP_USER}%",))
    put("QA3-DB", "뒷정리 — 검사기가 만든 행", PASS if not any(leftovers.values()) else WARN,
        f"지운 행 {sum(removed.values())} · 남은 것 {leftovers} · 지울 수 없는 것: 채번 카운터(sys_number_seq)와 시드 계정의 접근 로그")
    return finish()


def finish() -> int:
    order = {f"G-{i}": i for i in range(13, 21)}
    gate_rows = sorted([r for r in ROWS if r[0] in order], key=lambda r: order[r[0]])
    extra = [r for r in ROWS if r[0] not in order]
    width = max((len(r[1]) for r in ROWS), default=10)
    print(f"QA3 채널·보안 검사 — 엘컴화인 MES · {time.strftime('%Y-%m-%d %H:%M')}")
    print()
    for gid, item, status, measured in gate_rows:
        print(f"{gid}  {item:<{width}}  {status}  {measured}")
    print()
    for gid, item, status, measured in extra:
        print(f"{gid}  {item:<{width}}  {status}  {measured}")
    print()
    summary = []
    for gid in order:
        sts = [r[2] for r in gate_rows if r[0] == gid]
        if not sts:
            continue
        st = FAIL if FAIL in sts else BLOCKED if BLOCKED in sts else WARN if WARN in sts else UNVERIFIED if UNVERIFIED in sts else PASS
        summary.append(f"{gid} {st}({sum(s == PASS for s in sts)}/{len(sts)})")
    print("판정: " + " · ".join(summary))
    return 1 if any(r[2] == FAIL for r in gate_rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
