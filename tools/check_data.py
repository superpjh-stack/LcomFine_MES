#!/usr/bin/env python
"""QA2 흐름 · 데이터 검사기 — G-05 ~ G-15 판정 (`make check-data` · `tools/gate.py` 가 부른다). 소유 QA2.

W1 = G-05 ~ G-11 · W2 = G-11 `erp_upload_error` + G-12 ~ G-14(수금). G-15(대시보드)는 W3 화면이 없어 `FAIL  W3` 로 찍는다(게이트를 낮추지 않는다).

하는 일 — **코드는 읽기만 한다. 만든 행은 끝에 지운다(접두 `QA2-`).**
  G-05  쓰기 경계 — 라우터 파일별 쓰기 SQL 정적 스캔(+ 그 라우터가 부르는 공용 모듈 · COL 은 `erp_upload.py` 포함) ↔ `function-list.md`
        「쓰는 테이블」 + `db-schema.md` §2.2 예외 · TRK/LOT/PRP · trace · stats 쓰기 0 · 조회 화면(COL 7 포함) GET 전후 업무 테이블 행 수 diff 0
  G-06  E2E 1건을 **HTTP 만으로** — 부서 계정을 바꿔 가며 기준정보(BAS) → 의뢰 → 지시 → 입고 → 입고검사 → (분할) → 불출 → 일보
        → 검사일보 → 제품 입고 → 판정 → 출하 지시 → 확정. 단계마다 계약이 말하는 DB 상태를 확인한다.
  G-07  역추적 — LOT-020 화면 · `trace.backward` = QA2 독립 SQL(원 입고 LOT 집합) · 출하 후 불합격 표시(D-515 · D-702)
  G-08  정방향 — LOT-010 화면 · `trace.forward` = 독립 SQL(제품 LOT · 출하 집합)
  G-09  차단 — 검사대기 · 보류 LOT 불출 422 · 보류 LOT 출하 확정 422 · 검사대기 LOT 할당 422 · 중지 품목 입고 · 출하 지시 422
  G-10  가용 — 할당 뒤 가용 = qty − allocated · 확정 뒤 가용 불변 · 동시 할당(스레드 2) 초과 없음 · 전 LOT 할당 = 열린 출하 행 합 · INV-010 화면 값
        · F-SHP-012 라인 전부 제거 = 지시 취소(Ruling 21) → 할당 0 · 가용 복원 · 독립 SQL 대조
  G-11  알림 — W1 7종 + due_d3_unshipped(배치) + erp_upload_error(W2 · AC 1행 · dedupe · 교체 · 재해석으로 닫힘) 수신 부서마다 1행
        · dedupe · 처리 화면에서 닫힘 · HOME-020 처리 · 남의 부서 404
  G-12  회차 교체 — 같은 기준 기간 재업로드(HTTP · openpyxl 로 만든 (예시) xlsx) → 새 회차 `반영` · 이전 회차 `교체` + replaced_by · 행 보존 ·
        기간마다 `반영` 하나 · `v_dq_collections` 는 반영 회차만 · COL-020 구분 · col.py 의 POST 는 업로드 · 매핑뿐(정적)
  G-13  오류 행 · 미매핑 — 날짜 · 금액 · 필수 · 미매핑 행이 error 와 함께 보존 · 반영(뷰 · COL-040 · COL-050)에서 제외 · COL-030 미매핑 목록 ·
        매핑 뒤 반영 회차만 재해석(error is null) · 교체 회차 그대로 · COL-020 회차별 오류 행 · erp_upload_row 쓰기 = parsed · error 만(정적)
  G-14  출하 대비 수금 — E2E 의 확정 출하 + 같은 월 · 거래처의 ERP 매출 · 수금 → COL-070 화면 값 = QA2 독립 SQL(shipment_order 확정 confirmed_at 월
        × erp_upload_row 반영 · error 없음 · 사용 중 매핑 · txn_date 월) · 출하만 = MES 쪽만 · ERP 만 = ERP 쪽만 · 미매핑 코드 제외

    uv run python tools/check_data.py                # 판정표 (종료코드 = FAIL 수)
    uv run python tools/check_data.py --transcript   # + E2E 기록(마크다운 표) — outputs/qa2-흐름데이터.md 에 붙인다
    uv run python tools/check_data.py --keep         # 정리하지 않는다(디버그)
"""

from __future__ import annotations

import warnings

warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient`")

import html as _html
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

PASS, FAIL, UNVERIFIED = "PASS", "FAIL", "미검증"

GATE_NAMES = {
    "G-05": "쓰기 경계", "G-06": "E2E 흐름 1건", "G-07": "역추적", "G-08": "정방향 추적", "G-09": "차단 규칙",
    "G-10": "가용 재계산", "G-11": "알림 9종", "G-12": "회차 교체", "G-13": "오류 행 · 미매핑",
    "G-14": "출하 대비 수금", "G-15": "대시보드 8 수치",
}
LATER = {"G-15": "W3"}
#: 흐름이 앞에서 끊기면 행이 없어 PASS 로 보일 수 있는 것 — 행이 없으면 FAIL 을 넣는다 (게이트를 낮추지 않는다)
MUST_MEASURE = {("G-11", "erp_upload_error"), ("G-12", "같은 기간 재업로드"), ("G-13", "오류 행 보존"), ("G-14", "COL-070 화면")}
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# ════════════════════════════════════════════════════════════════════════════
# 기록
# ════════════════════════════════════════════════════════════════════════════
@dataclass
class Check:
    gate: str
    item: str
    status: str
    measured: str


@dataclass
class Step:
    step: str
    account: str
    request: str
    status: int | str
    numbers: str = ""
    db: str = ""


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def add(self, gate: str, item: str, ok: bool | str, measured: str) -> bool:
        st = ok if isinstance(ok, str) else (PASS if ok else FAIL)
        self.checks.append(Check(gate, item, st, " ".join(str(measured).split())))
        return st == PASS

    def get(self, gate: str, item_prefix: str) -> Check | None:
        return next((c for c in self.checks if c.gate == gate and c.item.startswith(item_prefix)), None)


class StepFailed(RuntimeError):
    """흐름의 앞 단계가 실패해 뒤 단계를 이어 갈 수 없다."""


# ════════════════════════════════════════════════════════════════════════════
# G-05 쓰기 경계 — 정적 스캔
# ════════════════════════════════════════════════════════════════════════════
ROUTERS = ROOT / "src/lcomfine/app/routers"
APP = ROOT / "src/lcomfine/app"
WRITE_RE = re.compile(r"\b(?:insert\s+into|delete\s+from)\s+([A-Za-z_{}]+)|\bupdate\s+([A-Za-z_{}]+)\s+set\b", re.I)
#: 공용 모듈 → 그 모듈이 쓰는 테이블(정적 스캔으로 다시 확인한다)
HELPERS = {"notify": "notify.py", "numbering": "numbering.py", "audit": "util/audit.py", "auth": "auth.py"}
#: 모든 라우터에 허용 — db-schema §2.2 「모든 쓰기」 · 「모든 화면 조회」 줄
ALWAYS = {"notification", "sys_change_log", "sys_access_log"}
#: 읽기만 하는 모듈 (db-schema §2.1 규칙 4 · CLAUDE.md)
READ_ONLY = {"trk.py": "TRK", "lot.py": "LOT", "prp.py": "PRP"}
READ_ONLY_HELPERS = ("trace.py", "stats.py")


def _sql_writes(text: str) -> list[str]:
    out = []
    for m in WRITE_RE.finditer(text):
        t = (m.group(1) or m.group(2) or "").lower()
        if t and t not in ("set",):
            out.append(t)
    return out


def contract_writes() -> dict[str, set[str]]:
    """function-list.md §2 → {대메뉴: 쓰는 테이블 합}."""
    out: dict[str, set[str]] = {}
    for ln in (ROOT / "contracts/function-list.md").read_text(encoding="utf-8").splitlines():
        if not ln.startswith("| F-"):
            continue
        cells = [c.strip() for c in ln.strip("|").split("|")]
        menu, tables = cells[1], cells[5]
        if tables and tables != "-":
            out.setdefault(menu, set()).update(t.strip() for t in tables.split(","))
        else:
            out.setdefault(menu, set())
    return out


def schema_exceptions() -> set[str]:
    """db-schema.md §2.2 예외 표에 나온 테이블 이름 전부."""
    text = (ROOT / "contracts/db-schema.md").read_text(encoding="utf-8")
    sec = text.split("### 2.2", 1)[1].split("### 2.3", 1)[0]
    return set(re.findall(r"`([a-z_]+)`", sec)) - {"status", "allocated_qty", "qty", "parent_lot_id"}


def helper_writes() -> dict[str, set[str]]:
    return {name: set(_sql_writes((APP / rel).read_text(encoding="utf-8"))) for name, rel in HELPERS.items()}


def _resolve_dynamic(fname: str, text: str, tables: list[str]) -> tuple[set[str], list[str]]:
    """f-string 테이블(`{table}` · `{insp}`)을 그 파일 안의 근거로 푼다. 못 풀면 목록으로 돌려준다."""
    real, unresolved = set(), []
    for t in tables:
        if "{" not in t:
            real.add(t)
            continue
        if t == "{table}" and "def remove_or_disable" in text:
            # bas.remove_or_disable 은 호출한 라우터의 테이블에 쓴다 — 호출 쪽에서 센다(아래 callers)
            continue
        if t == "{insp}" and fname == "qc.py":
            real.update(re.findall(r'"((?:incoming|product)_inspection)"', text))
            continue
        unresolved.append(f"{fname}:{t}")
    return real, unresolved


def static_scan(report: Report) -> None:
    contract = contract_writes()
    exc = schema_exceptions()
    helpers = helper_writes()
    menu_of = {p.stem.upper(): p for p in ROUTERS.glob("*.py") if p.stem != "__init__"}
    violations, unresolved, detail = [], [], []
    infra = {}   # 공용 모듈의 쓰기 중 §2.2 에 없는 것 → 그 모듈을 부르는 라우터
    # COL 영역 모듈 erp_upload.py — 라우터가 부르면 그 쓰기(+ 안에서 부르는 notify · numbering)는 부른 라우터의 쓰기다
    erp_text = (APP / "erp_upload.py").read_text(encoding="utf-8")
    erp_tables = set(_sql_writes(erp_text))
    erp_callers = []
    for menu, path in sorted(menu_of.items()):
        text = path.read_text(encoding="utf-8")
        tables, unr = _resolve_dynamic(path.name, text, _sql_writes(text))
        unresolved += unr
        tables |= set(re.findall(r'remove_or_disable\(cur,\s*"([a-z_]+)"', text))
        for h in ("notify", "numbering"):
            if re.search(rf"\b{h}\.(emit|handle|handle_by_link|next)\(", text):
                tables |= helpers[h]
        if re.search(r"\berp_upload\.(apply|remap|save_column_map)\(", text):
            erp_callers.append(menu)
            tables |= erp_tables | helpers["notify"] | helpers["numbering"]
        if re.search(r"\baudit\.log_change\(", text) or "templating.render(" in text:
            tables |= helpers["audit"]
        # 공용 모듈(numbering · notify · audit)이 쓰는 테이블은 db-schema §2.2 「이 표가 전부다」 에 있으면 허용 — 라우터가 부른 결과다
        helper_tables = set().union(*helpers.values())
        allowed = contract.get(menu, set()) | ALWAYS | (helper_tables & exc)
        bad = sorted(tables - allowed)
        for t in bad:
            if t in helper_tables:
                infra.setdefault(t, []).append(menu)
            else:
                violations.append(f"{menu}→{t}")
        detail.append(f"{menu} {len(tables)}")
    # 공용 모듈 자체 — 라우터가 부르지 않는 auth(로그인 · 로그아웃)도 §2.2 에 있어야 한다
    for name, ts in helpers.items():
        for t in sorted(ts - exc - ALWAYS):
            if name == "auth":
                infra.setdefault(t, []).append("auth(로그인)")
    report.add("G-05", "쓰기 경계 — 라우터 정적 스캔", not violations and not unresolved,
               f"라우터 {len(menu_of)} 의 쓰기 테이블 ⊆ 계약(function-list 쓰는 테이블 ∪ 알림 · 로그) · "
               f"위반 {len(violations)} {violations or ''} · 해석 못한 동적 쓰기 {len(unresolved)} {unresolved or ''}")
    # COL — col.py 자신의 쓰기 + erp_upload.py 의 쓰기 ⊆ F-COL 계약 테이블. erp_upload 를 부르는 라우터는 col.py 만 · 다른 라우터가 erp_* 에 쓰지 않는다
    col_contract = contract.get("COL", set())
    col_own = set(_sql_writes((ROUTERS / "col.py").read_text(encoding="utf-8"))) if (ROUTERS / "col.py").exists() else set()
    erp_bad = sorted(erp_tables - col_contract)
    col_bad = sorted(col_own - col_contract - ALWAYS)
    others = sorted(f"{m}→{t}" for m, p in menu_of.items() if m != "COL"
                    for t in set(_sql_writes(p.read_text(encoding="utf-8"))) if t.startswith("erp_"))
    erp_helpers = sorted(h for h in ("notify", "numbering") if re.search(rf"\b{h}\.(emit|handle_by_link|next)\(", erp_text))
    report.add("G-05", "COL 라우터 · erp_upload.py 쓰기 ⊆ F-COL 계약 테이블 ∪ 알림 · 채번",
               not erp_bad and not col_bad and not others and erp_callers == ["COL"],
               f"erp_upload.py 쓰기 {sorted(erp_tables)} · col.py 직접 쓰기 {sorted(col_own)} ⊆ F-COL 「쓰는 테이블」 {sorted(col_contract)} · "
               f"계약 밖 {erp_bad + col_bad or 0} · erp_upload 쓰기 함수를 부르는 라우터 {erp_callers} (기대 ['COL']) · "
               f"다른 라우터의 erp_* 쓰기 {others or 0} · erp_upload 안의 공용 모듈 {erp_helpers} (§2.2 notification · sys_number_seq)")
    helper_in_exc = sorted(t for t in set().union(*helpers.values()) if t in exc)
    report.add("G-05", "쓰기 경계 — 공용 모듈의 계약 밖 쓰기", not infra,
               "db-schema §2.2 「이 표가 전부다」에 없는 쓰기: "
               + (" · ".join(f"{t} ← {', '.join(sorted(set(v)))}" for t, v in sorted(infra.items())) or "0")
               + f" · §2.2 가 허용한 공용 모듈 쓰기 {helper_in_exc} (numbering → sys_number_seq · auth → sys_user)")
    # 예외 줄의 컬럼 — QC 는 lot_stock.status 만, SHP 지시는 allocated_qty 만, SHP 확정은 qty · allocated_qty (db-schema §2.2)
    col_rules = {("qc.py", None): {"status"}, ("shp.py", "create_order"): {"allocated_qty"},
                 ("shp.py", "update_order"): {"allocated_qty"}, ("shp.py", "confirm_order"): {"qty", "allocated_qty"}}
    col_bad, col_seen = [], 0
    for fname in ("qc.py", "shp.py"):
        text = (ROUTERS / fname).read_text(encoding="utf-8")
        for m in re.finditer(r'update\s+lot_stock\s+set\s+([^"]*?)(?:\s|")+where', text, re.I):
            func = re.findall(r"^def (\w+)\(", text[: m.start()], re.M)
            func = func[-1] if func else "?"
            cols = {c.split("=")[0].strip() for c in m.group(1).split(",")} - {"updated_at", "updated_by"}
            allowed = col_rules.get((fname, None)) or col_rules.get((fname, func))
            col_seen += 1
            if allowed is None or not cols <= allowed:
                col_bad.append(f"{fname}:{func} {sorted(cols)}")
    report.add("G-05", "예외 줄의 lot_stock 컬럼 (QC status · SHP allocated_qty/qty)", not col_bad,
               f"update lot_stock {col_seen} 문 · 허용 밖 컬럼 {len(col_bad)} {col_bad or ''}")
    ro_hits = []
    for fname, menu in READ_ONLY.items():
        p = ROUTERS / fname
        if p.exists():
            w = _sql_writes(p.read_text(encoding="utf-8"))
            if w or re.search(r"\b(notify\.emit|numbering\.next|conn\.x|conn\.tx)\(", p.read_text(encoding="utf-8")):
                ro_hits.append(f"{menu}:{w}")
    for fname in READ_ONLY_HELPERS:
        t = (APP / fname).read_text(encoding="utf-8")
        if _sql_writes(t) or re.search(r"\b(conn\.x|conn\.tx)\(", t):
            ro_hits.append(f"{fname}:{_sql_writes(t)}")
    report.add("G-05", "TRK · LOT · PRP · trace · stats 쓰기 0 (정적)", not ro_hits,
               f"쓰기 문 {len(ro_hits)} {ro_hits or ''} — trk.py · lot.py · prp.py · trace.py · stats.py")


# ════════════════════════════════════════════════════════════════════════════
# G-12 · G-13 정적 — MES 에 수금 금액을 고치는 경로가 없다 (db-schema §2.1 규칙 5 · 정본 「MES 는 수금 데이터를 고치지 않는다」)
# ════════════════════════════════════════════════════════════════════════════
#: erp_upload_row 에서 바뀌어도 되는 컬럼 — 재해석(parsed · error) 과 수정 표시만. raw(원문) · batch_id · row_no 는 불변
ROW_MUTABLE = {"parsed", "error", "updated_at", "updated_by"}
#: erp_upload_batch 에서 바뀌어도 되는 컬럼 — 교체 표시 · 오류 수 갱신만. 기간 · 행 수 · 번호는 불변
BATCH_MUTABLE = {"status", "replaced_by", "error_count", "updated_at", "updated_by"}
#: F-COL-011 · 031 · 032 · 033 — function-list 의 COL 쓰기 기능 API (수금 금액 수정 엔드포인트는 없다)
COL_WRITE_PATHS = {"/col/uploads", "/col/customer-map", "/col/customer-map/{id}", "/col/customer-map/{id}/delete"}


def _set_clauses(text: str, table: str) -> list[tuple[str, set[str]]]:
    """`update <table> [alias] set … where` 의 set 절을 괄호 깊이 0 의 `where` 까지 잘라 대입 컬럼 집합으로. [(set 절, 컬럼들)]."""
    out = []
    for m in re.finditer(rf"\bupdate\s+{table}\s+(?:\w+\s+)?set\s+", text, re.I):
        i, depth, buf = m.end(), 0, []
        while i < len(text):
            ch = text[i]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif depth == 0 and re.match(r"\s+where\b|\s+returning\b|\"\"\"", text[i:], re.I):
                break
            buf.append(ch)
            i += 1
        clause = "".join(buf)
        cols, depth, cur = set(), 0, []
        for ch in clause + ",":
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            if ch == "," and depth == 0:
                piece = "".join(cur).strip()
                if "=" in piece:
                    cols.add(piece.split("=", 1)[0].strip().split(".")[-1])
                cur = []
            else:
                cur.append(ch)
        out.append((" ".join(clause.split())[:80], cols))
    return out


def static_col(report: Report) -> None:
    """G-12 · G-13 정적 — col.py 의 POST 는 업로드 · 매핑뿐 · erp_upload_row 쓰기는 parsed · error 재해석만 · raw 불변 · 삭제 0."""
    from lcomfine.app.main import app

    def walk(routes):
        """FastAPI 가 include 한 라우터(`_IncludedRouter.original_router`)까지 펼친다."""
        for r in routes:
            inner = getattr(r, "original_router", None) or (r if hasattr(r, "routes") and not hasattr(r, "endpoint") else None)
            if inner is not None and hasattr(inner, "routes"):
                yield from walk(inner.routes)
            else:
                yield r

    posts = sorted(r.path for r in walk(app.routes) if getattr(r, "path", "").startswith("/col/") and "POST" in (getattr(r, "methods", None) or ()))
    col_text = (ROUTERS / "col.py").read_text(encoding="utf-8") if (ROUTERS / "col.py").exists() else ""
    # col.py 가 수금 행 · 회차 테이블을 직접 쓰지 않는다 (erp_customer_map 만) — 금액을 받는 폼 칸이 없다
    col_direct = sorted(t for t in set(_sql_writes(col_text)) if t in ("erp_upload_row", "erp_upload_batch"))
    form_names = sorted(set(re.findall(r"(\w+):\s*str\s*\|\s*None\s*=\s*Form\(", col_text)))
    report.add("G-12", "col.py 의 POST = 업로드 · 매핑만 (수금 금액 수정 경로 없음 · 정적)",
               set(posts) == COL_WRITE_PATHS and not col_direct,
               f"POST {posts} = function-list F-COL-011 · 031 · 032 · 033 {sorted(COL_WRITE_PATHS)} · col.py 가 직접 쓰는 수금 테이블 {col_direct or 0} "
               f"· 폼 칸 {form_names} (금액 칸 없음) · 수금 데이터는 erp_upload.apply(회차 교체) · remap(재해석)으로만 바뀐다")
    # 앱 전체에서 erp_upload_row · erp_upload_batch 의 update 컬럼 · delete
    bad, seen, deletes = [], [], []
    for p in sorted(APP.rglob("*.py")):
        text = p.read_text(encoding="utf-8")
        for table, allowed in (("erp_upload_row", ROW_MUTABLE), ("erp_upload_batch", BATCH_MUTABLE)):
            for clause, cols in _set_clauses(text, table):
                seen.append(f"{p.name}:{table} {sorted(cols)}")
                if not cols or not cols <= allowed:
                    bad.append(f"{p.name}: update {table} set {sorted(cols)} (허용 {sorted(allowed)})")
        deletes += [f"{p.name}:{t}" for t in _sql_writes(text) if t in ("erp_upload_row", "erp_upload_batch")
                    and re.search(rf"delete\s+from\s+{t}\b", text, re.I)]
    report.add("G-13", "erp_upload_row 쓰기 = parsed · error 재해석만 · raw 불변 · 회차 삭제 0 (정적)", not bad and not deletes,
               f"update 문 {len(seen)} {seen} · 허용 밖 {bad or 0} · delete {deletes or 0} — raw(원문) · 기간 · 행 수는 어디서도 바꾸지 않는다")


# ════════════════════════════════════════════════════════════════════════════
# HTTP 흐름
# ════════════════════════════════════════════════════════════════════════════
ACCOUNTS = ("sl", "pr", "sh", "ds", "ac", "st", "ex", "admin")
READ_SCREENS = ["/trk/orders", "/trk/due", "/trk/customers", "/lot/forward", "/lot/backward", "/prp/utilization",
                "/prp/machines", "/prp/completion", "/wo/status", "/inv/stock", "/qc/history", "/shp/history", "/",
                "/col/uploads", "/col/upload-history", "/col/customer-map", "/col/collections", "/col/receivables",
                "/col/aging", "/col/shipment-vs-collection"]
LOG_TABLES = {"sys_access_log"}


def num(text: str) -> Decimal:
    return Decimal(text.replace(",", "").strip() or "0")


class Flow:
    def __init__(self, report: Report) -> None:
        from fastapi.testclient import TestClient

        from lcomfine.app.main import app
        from lcomfine.app.settings import get_settings
        from lcomfine.db import conn

        self.TestClient, self.app, self.conn = TestClient, app, conn
        self.pw = get_settings().seed_password
        if not self.pw:
            raise RuntimeError("LCOMFINE_SEED_PASSWORD 가 .env 에 없다 — 로그인할 수 없다")
        self.r = report
        self.tag = f"QA2-{int(time.time() * 1000) % 10**9}"
        self.today = date.today()
        self.clients: dict[str, object] = {}
        # 만든 것 (정리용)
        self.items: list[int] = []
        self.customer_id: int | None = None
        self.warehouse_id: int | None = None
        self.locations: list[int] = []
        self.req_ids: list[int] = []
        self.req_nos: list[str] = []
        self.wo_ids: list[int] = []
        self.wo_nos: list[str] = []
        self.receipt_ids: list[int] = []
        self.mlot_nos: list[str] = []
        self.plot_nos: list[str] = []
        self.ship_nos: list[str] = []
        self.issue_ids: list[int] = []
        # W2 수금 (정리용)
        self.customer2_id: int | None = None
        self.erp_batches: list[int] = []
        self.erp_codes: list[str] = []
        self.cmap_before: list[dict] | None = None     # 열 매핑을 바꿨으면 원래 행(되돌린다)
        self.v: dict[str, object] = {}

    # ── HTTP ──
    def c(self, login: str):
        if login not in self.clients:
            cl = self.TestClient(self.app)
            resp = cl.post("/login", data={"login_id": login, "password": self.pw}, follow_redirects=False)
            if resp.status_code != 303:
                raise StepFailed(f"{login} 로그인 {resp.status_code}")
            self.clients[login] = cl
        return self.clients[login]

    def post(self, step: str, login: str, path: str, data: dict, expect: int = 200, numbers=None) -> dict:
        resp = self.c(login).post(path, data=data, follow_redirects=False)
        body: dict = {}
        try:
            body = resp.json()
        except Exception:  # noqa: BLE001 — 본문이 JSON 이 아니면 그대로 적는다
            body = {"text": resp.text[:200]}
        msg = body.get("message") if isinstance(body.get("message"), str) else (body.get("detail") or {}).get("message", "") \
            if isinstance(body.get("detail"), dict) else ""
        nums = numbers(body) if (numbers and resp.status_code == expect) else (msg or "")
        self.r.steps.append(Step(step, login, f"POST {path}", resp.status_code, str(nums)))
        if resp.status_code != expect:
            raise StepFailed(f"{step}: POST {path} ({login}) → {resp.status_code} (기대 {expect}) {str(body)[:300]}")
        return body

    def try_post(self, step: str, login: str, path: str, data: dict) -> tuple[int, dict]:
        resp = self.c(login).post(path, data=data, follow_redirects=False)
        try:
            body = resp.json()
        except Exception:  # noqa: BLE001
            body = {"text": resp.text[:200]}
        det = body.get("detail") if isinstance(body.get("detail"), dict) else {}
        self.r.steps.append(Step(step, login, f"POST {path}", resp.status_code, det.get("message", "") or body.get("message", "")))
        return resp.status_code, body

    def get(self, step: str, login: str, path: str, expect: int | None = 200, note: str = ""):
        resp = self.c(login).get(path, follow_redirects=False)
        self.r.steps.append(Step(step, login, f"GET {path}", resp.status_code, note))
        if expect is not None and resp.status_code != expect:
            raise StepFailed(f"{step}: GET {path} ({login}) → {resp.status_code} (기대 {expect})")
        return resp

    def db(self, text: str) -> None:
        """방금 단계의 DB 확인 문장을 기록에 붙인다."""
        if self.r.steps:
            s = self.r.steps[-1]
            s.db = (s.db + " · " if s.db else "") + text

    # ── DB 읽기 (확인용 · 쓰지 않는다) ──
    def q(self, sql: str, params=()):
        return self.conn.q(sql, params)

    def q1(self, sql: str, params=()):
        return self.conn.q1(sql, params)

    def stock(self, kind: str, lot_no: str) -> list[dict]:
        table = "material_lot" if kind == "원자재" else "product_lot"
        return self.q(f"""select s.id, s.qty, s.allocated_qty, s.status, l.location_code
                            from lot_stock s join {table} t on t.id = s.lot_id join location l on l.id = s.location_id
                           where s.lot_kind = %s and t.lot_no = %s order by s.id""", (kind, lot_no))

    def stock1(self, kind: str, lot_no: str) -> dict:
        rows = self.stock(kind, lot_no)
        if len(rows) != 1:
            raise StepFailed(f"{lot_no} 재고 행 {len(rows)}개")
        return rows[0]

    def notes(self, dedupe_key: str) -> dict[str, dict]:
        return {r["to_role"]: r for r in self.q(
            "select id, to_role, handled_at, handled_by, link, event_key from notification where dedupe_key = %s", (dedupe_key,))}

    def expect(self, cond: bool, what: str) -> None:
        self.db(("OK " if cond else "불일치 ") + what)
        if not cond:
            raise StepFailed(what)

    # ════════════════════════════════════════════════════════════════════════
    # G-06 E2E
    # ════════════════════════════════════════════════════════════════════════
    def base(self) -> None:
        t = self.tag
        P = self.post("BAS-010 품목(제품)", "pr", "/bas/items",
                      {"item_code": f"{t}-P", "item_name": f"{t} 제품 (예시)", "item_type": "제품", "unit": "EA"},
                      numbers=lambda b: f"item {b['id']}")
        M = self.post("BAS-010 품목(원자재)", "pr", "/bas/items",
                      {"item_code": f"{t}-M", "item_name": f"{t} 원자재 (예시)", "item_type": "원자재", "unit": "KG"},
                      numbers=lambda b: f"item {b['id']}")
        X = self.post("BAS-010 품목(원자재 · 중지용)", "pr", "/bas/items",
                      {"item_code": f"{t}-X", "item_name": f"{t} 중지 원자재 (예시)", "item_type": "원자재"},
                      numbers=lambda b: f"item {b['id']}")
        self.items += [P["id"], M["id"], X["id"]]
        self.v.update(item_p=P["id"], item_m=M["id"], item_x=X["id"])
        self.post("BAS-010 품목 사용 중지", "pr", f"/bas/items/{X['id']}",
                  {"item_name": f"{t} 중지 원자재 (예시)", "item_type": "원자재", "use_yn": "N"})
        self.expect(self.q1("select use_yn from item where id = %s", (X["id"],))["use_yn"] == "N", "item.use_yn = N")
        C = self.post("BAS-020 거래처", "sl", "/bas/customers",
                      {"customer_code": f"{t}-C", "customer_name": f"{t} 거래처 (예시)"}, numbers=lambda b: f"customer {b['id']}")
        self.customer_id = C["id"]
        W = self.post("BAS-030 창고", "pr", "/bas/warehouses",
                      {"target": "warehouse", "warehouse_code": f"{t}-W", "warehouse_name": f"{t} 창고 (예시)"},
                      numbers=lambda b: f"warehouse {b['id']}")
        self.warehouse_id = W["id"]
        for code in ("L1", "L2"):
            L = self.post(f"BAS-030 위치 {code}", "pr", "/bas/warehouses",
                          {"target": "location", "warehouse_id": str(W["id"]), "location_code": code,
                           "location_name": f"{t} {code} (예시)"}, numbers=lambda b: f"location {b['id']}")
            self.locations.append(L["id"])
        self.v.update(L1=self.locations[0], L2=self.locations[1])

    def e2e(self) -> None:
        v, t = self.v, self.tag
        L1, L2 = str(v["L1"]), str(v["L2"])
        # 1 의뢰 (영업부)
        due1 = self.today + timedelta(days=10)
        b = self.post("WO-010 생산의뢰 등록", "sl", "/wo/requests",
                      {"customer_id": str(self.customer_id), "item_id": str(v["item_p"]), "qty": "100",
                       "due_date": due1.isoformat(), "note": f"{t} (예시)"}, numbers=lambda b: b["request_no"])
        R1, R1id = b["request_no"], b["id"]
        self.req_nos.append(R1)
        self.req_ids.append(R1id)
        v.update(R1=R1, R1id=R1id, due1=due1)
        row = self.q1("select status, qty, due_date from production_request where id = %s", (R1id,))
        self.expect(row["status"] == "확인대기" and row["qty"] == 100, f"production_request {R1} 확인대기 · 100")
        n = self.notes(f"request_created:{R1}")
        self.expect(set(n) == {"PR", "DS"} and all(x["handled_at"] is None for x in n.values()),
                    f"notification request_created:{R1} → PR · DS 1행씩 미처리")
        html = self.get("WO-010 의뢰 목록에서 번호 확인", "sl", f"/wo/requests?q={R1}").text
        self.expect(R1 in html, f"목록 화면에 {R1}")
        # 1b 단가·납기 확인 → 확정 (영업부)
        self.post("WO-010 의뢰 확정(수정)", "sl", f"/wo/requests/{R1id}",
                  {"customer_id": str(self.customer_id), "item_id": str(v["item_p"]), "qty": "100",
                   "due_date": due1.isoformat(), "status": "확정"})
        self.expect(self.q1("select status from production_request where id = %s", (R1id,))["status"] == "확정", "의뢰 확정")
        # 1c 납기 D-3 용 의뢰 (출하 없음)
        due2 = self.today + timedelta(days=2)
        b = self.post("WO-010 생산의뢰 등록(납기 D-2 · 출하 없음)", "sl", "/wo/requests",
                      {"customer_id": str(self.customer_id), "item_id": str(v["item_p"]), "qty": "10",
                       "due_date": due2.isoformat()}, numbers=lambda b: b["request_no"])
        self.req_nos.append(b["request_no"])
        self.req_ids.append(b["id"])
        v.update(R2=b["request_no"], R2id=b["id"])

        # 2 지시 (생산부)
        b = self.post("WO-020 생산지시서 작성", "pr", "/wo/orders",
                      {"request_id": str(R1id), "qty": "100", "equipment_code": "EQ01",
                       "planned_on": self.today.isoformat()}, numbers=lambda b: b["work_order_no"])
        WO, WOid = b["work_order_no"], b["id"]
        self.wo_nos.append(WO)
        self.wo_ids.append(WOid)
        v.update(WO=WO, WOid=WOid)
        w = self.q1("select status, request_id, item_id from work_order where id = %s", (WOid,))
        self.expect(w["status"] == "발행" and w["request_id"] == R1id and w["item_id"] == v["item_p"],
                    f"work_order {WO} 발행 · 의뢰 {R1} · 제품 품목")
        self.expect(self.q1("select status from production_request where id = %s", (R1id,))["status"] == "지시완료",
                    "의뢰 지시완료")
        n = self.notes(f"order_issued:{WO}")
        self.expect(set(n) == {"PR"} and n["PR"]["handled_at"] is None, f"order_issued:{WO} → PR 1행 미처리")
        n = self.notes(f"request_created:{R1}")
        self.expect(n["PR"]["handled_at"] is not None and n["DS"]["handled_at"] is None,
                    "request_created PR 처리됨(지시서 작성이 닫음) · DS 미처리")

        # 3 원자재 입고 (생산부)
        b = self.post("MAT-010 원자재 입고", "pr", "/mat/receipts",
                      {"supplier_name": f"{t} 공급사 (예시)", "received_on": self.today.isoformat(),
                       "item_id": [str(v["item_m"])] * 2, "qty": ["120", "80"], "location_id": [L1, L1],
                       "supplier_lot_no": ["S-1", "S-2"]}, numbers=lambda b: ", ".join(b["lot_nos"]))
        A1, A2 = b["lot_nos"]
        self.receipt_ids.append(b["receipt_id"])
        self.mlot_nos += [A1, A2]
        v.update(A1=A1, A2=A2, rcp1=b["receipt_id"])
        s1, s2 = self.stock1("원자재", A1), self.stock1("원자재", A2)
        self.expect(s1["status"] == s2["status"] == "검사대기" and s1["qty"] == 120 and s2["qty"] == 80
                    and s1["allocated_qty"] == s2["allocated_qty"] == 0, f"lot_stock {A1} 120 · {A2} 80 검사대기")
        n = self.notes(f"material_received:{A1}")
        self.expect(set(n) == {"PR"} and n["PR"]["handled_at"] is None, f"material_received:{A1} → PR 1행")

        # 4 입고검사 (생산부)
        self.post("QC-010 입고검사 합격", "pr", "/qc/incoming",
                  {"lot_no": A1, "result": "합격", "item_name": ["외관"], "item_value": ["양호"]},
                  numbers=lambda b: f"{b['lot_no']} #{b['seq']} → {b['status']}")
        self.expect(self.stock1("원자재", A1)["status"] == "가용"
                    and self.notes(f"material_received:{A1}")["PR"]["handled_at"] is None,
                    f"{A1} 가용 · 입고 알림은 아직 열림(같은 입고의 {A2} 미판정)")
        self.post("QC-010 입고검사 합격", "pr", "/qc/incoming", {"lot_no": A2, "result": "합격"},
                  numbers=lambda b: f"{b['lot_no']} #{b['seq']} → {b['status']}")
        self.expect(self.stock1("원자재", A2)["status"] == "가용"
                    and self.notes(f"material_received:{A1}")["PR"]["handled_at"] is not None,
                    f"{A2} 가용 · material_received 처리됨(입고 LOT 전부 판정)")

        # 4b 분할 (생산부 · INV-020) — 분할 LOT 를 불출해 역추적이 원 LOT 로 잇는지 본다
        b = self.post("INV-020 원자재 LOT 분할", "pr", "/inv/moves",
                      {"lot_kind": "원자재", "lot_no": A1, "from_location_id": L1, "to_location_id": L2, "qty": "20",
                       "split": "1"}, numbers=lambda b: b["lot_no"])
        A1s = b["lot_no"]
        self.mlot_nos.append(A1s)
        v["A1s"] = A1s
        par = self.q1("""select p.lot_no from material_lot c join material_lot p on p.id = c.parent_lot_id
                          where c.lot_no = %s""", (A1s,))
        self.expect(A1s == f"{A1}-01" and par and par["lot_no"] == A1
                    and self.stock1("원자재", A1)["qty"] == 100 and self.stock1("원자재", A1s)["qty"] == 20
                    and self.stock1("원자재", A1s)["status"] == "가용",
                    f"{A1s} parent={A1} · {A1} 100 · {A1s} 20 가용")

        # 5 불출 (생산부)
        b = self.post("MAT-020 불출", "pr", "/mat/issues",
                      {"work_order_no": WO, "issued_on": self.today.isoformat(),
                       "lot_no": [A1, A1s, A2], "location_id": [L1, L2, L1], "qty": ["80", "20", "50"]},
                      numbers=lambda b: f"issue {b['issue_id']} ← {', '.join(b['lot_nos'])}")
        self.issue_ids.append(b["issue_id"])
        q = {x: self.stock1("원자재", x)["qty"] for x in (A1, A1s, A2)}
        self.expect(q == {A1: 20, A1s: 0, A2: 30}, f"lot_stock qty {A1} 20 · {A1s} 0 · {A2} 30")
        mv = self.q1("""select count(*) as n, sum(qty) as s from stock_move
                         where move_kind = '불출' and ref_table = 'material_issue_line'
                           and ref_id in (select id from material_issue_line where issue_id = %s)""", (b["issue_id"],))
        self.expect(mv["n"] == 3 and mv["s"] == 150, "stock_move 불출 3행 · 합 150")
        self.expect(self.notes(f"order_issued:{WO}")["PR"]["handled_at"] is not None, "order_issued 처리됨(불출이 닫음)")

        # 6 생산일보 · 검사일보 (생산부)
        b = self.post("PRD-010 생산일보", "pr", "/prd/daily",
                      {"work_order_no": WO, "work_date": self.today.isoformat(), "equipment_code": "EQ01",
                       "produced_qty": "100", "good_qty": "95", "loss_qty": "5", "run_minutes": "480", "stop_minutes": "30"},
                      numbers=lambda b: f"daily {b['daily_id']}")
        self.expect(self.q1("select good_qty from production_daily where id = %s", (b["daily_id"],))["good_qty"] == 95,
                    "production_daily 양품 95")
        b = self.post("INS-010 검사일보", "pr", "/ins/daily",
                      {"work_order_no": WO, "work_date": self.today.isoformat(), "inspected_qty": "95", "defect_qty": "2",
                       "defect_code": ["DF01"], "defect_code_qty": ["2"]}, numbers=lambda b: f"daily {b['daily_id']}")
        self.expect(self.q1("select inspected_qty, defect_qty from inspection_daily where id = %s",
                            (b["daily_id"],)) == {"inspected_qty": 95, "defect_qty": 2}, "inspection_daily 95 · 불량 2")

        # 7 제품 입고 (생산부) — 수량을 비우면 일보 완료 수량
        b = self.post("MAT-030 제품 입고(수량 비움 = 일보 양품)", "pr", "/mat/product-receipts",
                      {"work_order_no": WO, "qty": "", "location_id": L1, "received_on": self.today.isoformat()},
                      numbers=lambda b: f"{b['lot_no']} · {b['qty']}")
        P1, P1id = b["lot_no"], b["product_lot_id"]
        self.plot_nos.append(P1)
        v.update(P1=P1, P1id=P1id)
        s = self.stock1("제품", P1)
        self.expect(Decimal(b["qty"]) == 95 and s["qty"] == 95 and s["status"] == "검사대기",
                    f"product_lot {P1} 95(= 일보 양품) · lot_stock 검사대기")
        n = self.notes(f"product_received:{P1}")
        self.expect(set(n) == {"PR"} and n["PR"]["handled_at"] is None, f"product_received:{P1} → PR 1행")
        for key, qty in (("P2", "10"), ("P3", "5")):
            b = self.post(f"MAT-030 제품 입고({key} · 차단 시험용)", "pr", "/mat/product-receipts",
                          {"work_order_no": WO, "qty": qty, "location_id": L1}, numbers=lambda b: f"{b['lot_no']} · {b['qty']}")
            self.plot_nos.append(b["lot_no"])
            v[key], v[key + "id"] = b["lot_no"], b["product_lot_id"]

        # 8 제품검사 판정 (생산부)
        self.post("QC-020 제품검사 합격", "pr", "/qc/product", {"lot_no": P1, "result": "합격"},
                  numbers=lambda b: f"{b['lot_no']} #{b['seq']} → {b['status']}")
        n = self.notes(f"judged:{P1}:1")
        self.expect(self.stock1("제품", P1)["status"] == "가용" and set(n) == {"SH", "SL"}
                    and self.notes(f"product_received:{P1}")["PR"]["handled_at"] is not None,
                    f"{P1} 가용 · judged:{P1}:1 → SH · SL · product_received 처리됨")
        self.post("QC-020 제품검사 합격(P2)", "pr", "/qc/product", {"lot_no": v["P2"], "result": "합격"},
                  numbers=lambda b: f"{b['lot_no']} #{b['seq']} → {b['status']}")

        # 9 출하 지시 (영업부 — 정본 영업부 흐름 · D-523) — 판정 알림 링크 화면에서 재고 행을 고른다
        html = self.get("SHP-010 판정 알림 링크로 열기", "sl", f"/shp/orders?lot={P1}").text
        m = re.search(r'<option value="(\d+)" selected>' + re.escape(P1), html)
        self.expect(m is not None, f"SHP-010 ?lot={P1} 가 1번 줄에 그 LOT 재고를 골라 둔다")
        sid = m.group(1)
        v["P1sid"] = sid
        b = self.post("SHP-010 출하 지시 등록(의뢰번호 · LOT 60)", "sl", "/shp/orders",
                      {"request_no": R1, "stock_id": [sid], "qty": ["60"]}, numbers=lambda b: b["shipment_no"])
        S1, S1id = b["shipment_no"], b["id"]
        self.ship_nos.append(S1)
        v.update(S1=S1, S1id=S1id)
        o = self.q1("select status, request_id, customer_id, due_date from shipment_order where id = %s", (S1id,))
        self.expect(o["status"] == "지시" and o["request_id"] == R1id and o["customer_id"] == self.customer_id
                    and o["due_date"] == due1, f"shipment_order {S1} 지시 · 의뢰 {R1} 의 거래처 · 납기")
        s = self.stock1("제품", P1)
        self.expect(s["qty"] == 95 and s["allocated_qty"] == 60 and s["qty"] - s["allocated_qty"] == 35,
                    f"{P1} qty 95 · allocated 60 · 가용 35")
        self.r.add("G-10", "할당 뒤 가용 = qty − allocated", s["qty"] - s["allocated_qty"] == 35,
                   f"{P1} qty {s['qty']} − 할당 {s['allocated_qty']} = {s['qty'] - s['allocated_qty']} (기대 35)")
        n = self.notes(f"shipment_ordered:{S1}")
        j = self.notes(f"judged:{P1}:1")
        self.expect(set(n) == {"SH"} and n["SH"]["handled_at"] is None and j["SL"]["handled_at"] is not None
                    and j["SH"]["handled_at"] is None,
                    f"shipment_ordered:{S1} → SH · judged SL 처리됨(등록 부서) · SH 미처리")
        avail_screen = self.inv_available("sl", P1)
        self.r.add("G-10", "INV-010 화면 가용 = 재계산 (할당 뒤)", avail_screen == [Decimal(35)],
                   f"INV-010 ?lot={P1} 가용 칸 {avail_screen} (기대 [35])")

        # 10 출하 확정 (출하실)
        b = self.post("SHP-020 출하 확정", "sh", f"/shp/confirm/{S1id}/confirm", {}, numbers=lambda b: b["shipment_no"])
        o = self.q1("select status, confirmed_at from shipment_order where id = %s", (S1id,))
        s = self.stock1("제품", P1)
        mv = self.q("""select qty, from_location_id from stock_move where move_kind = '출하' and ref_table = 'shipment_order'
                        and ref_id = %s""", (S1id,))
        self.expect(o["status"] == "확정" and o["confirmed_at"] is not None, f"{S1} 확정 · confirmed_at")
        self.expect(s["qty"] == 35 and s["allocated_qty"] == 0, f"{P1} qty 95→35 · allocated 60→0")
        self.r.add("G-10", "확정 뒤 qty · allocated 함께 감소 · 가용 불변",
                   s["qty"] == 35 and s["allocated_qty"] == 0 and s["qty"] - s["allocated_qty"] == 35,
                   f"확정 전 95/60 가용 35 → 확정 뒤 {s['qty']}/{s['allocated_qty']} 가용 {s['qty'] - s['allocated_qty']}")
        self.expect(len(mv) == 1 and mv[0]["qty"] == 60 and mv[0]["from_location_id"] == v["L1"], "stock_move 출하 1행 60")
        n1, n2 = self.notes(f"shipment_ordered:{S1}"), self.notes(f"shipment_confirmed:{S1}")
        self.expect(n1["SH"]["handled_at"] is not None and set(n2) == {"SL", "AC"},
                    f"shipment_ordered 처리됨(확정이 닫음) · shipment_confirmed:{S1} → SL · AC")
        v["S1_confirmed_at"] = o["confirmed_at"]

        # 의뢰번호로 이어진 행 (G-06)
        chain = self.q1(
            """select r.request_no, w.work_order_no,
                      (select count(*) from material_issue_line l where l.work_order_id = w.id) as issue_lines,
                      (select count(*) from production_daily d where d.work_order_id = w.id) as daily,
                      (select count(*) from inspection_daily d where d.work_order_id = w.id) as insp,
                      (select count(*) from product_receipt p where p.work_order_id = w.id) as receipts,
                      (select count(*) from shipment_order o where o.request_id = r.id and o.status = '확정') as shipped,
                      (select count(*) from shipment_line sl join product_lot p on p.id = sl.product_lot_id
                        where p.work_order_id = w.id) as ship_lines
                 from production_request r join work_order w on w.request_id = r.id where r.request_no = %s""", (R1,))
        ok = chain and chain["issue_lines"] == 3 and chain["daily"] == 1 and chain["insp"] == 1 and chain["receipts"] == 3 \
            and chain["shipped"] == 1 and chain["ship_lines"] == 1
        self.r.add("G-06", "의뢰번호로 이어진 행", bool(ok), f"{R1} → {dict(chain) if chain else '없음'}")
        vw = self.q1("select daily_good_qty, receipt_qty, shipped_qty from v_work_order_status where work_order_id = %s", (WOid,))
        self.r.add("G-06", "WO-040 뷰 수량 = 흐름 (일보 95 · 입고 110 · 출하 60)",
                   vw is not None and (vw["daily_good_qty"], vw["receipt_qty"], vw["shipped_qty"]) == (95, 110, 60),
                   f"v_work_order_status {WO} → {dict(vw) if vw else '없음'}")

    def inv_available(self, login: str, lot_no: str) -> list[Decimal]:
        html = self.c(login).get(f"/inv/stock?lot={lot_no}").text
        out = []
        for m in re.finditer(r'<tr data-lot="([^"]+)">(.*?)</tr>', html, re.S):
            if m.group(1) == lot_no:
                a = re.search(r"data-available>([^<]*)<", m.group(2))
                out.append(num(a.group(1)) if a else None)
        return out

    # ════════════════════════════════════════════════════════════════════════
    # G-07 · G-08 추적
    # ════════════════════════════════════════════════════════════════════════
    def indep_backward(self, shipment_no: str | None = None, product_lot_no: str | None = None) -> tuple[set, set]:
        """QA2 독립 SQL — (원 입고 LOT 번호 집합, 실제 불출 LOT 번호 집합)."""
        if shipment_no:
            start = "select sl.product_lot_id as id from shipment_line sl join shipment_order so on so.id = sl.shipment_order_id " \
                    "where so.shipment_no = %(no)s"
        else:
            start = "select id from product_lot where lot_no = %(no)s"
        rows = self.q(f"""
            with recursive up as (
                select p.id, p.parent_lot_id, p.work_order_id from product_lot p where p.id in ({start})
                union
                select p.id, p.parent_lot_id, p.work_order_id from product_lot p join up on p.id = up.parent_lot_id
            ), issued as (
                select distinct m.id, m.lot_no, m.parent_lot_id
                  from material_issue_line l join material_issue i on i.id = l.issue_id and i.canceled_at is null
                  join material_lot m on m.id = l.material_lot_id
                 where l.work_order_id in (select work_order_id from up)
            ), mup as (
                select id as start_id, id, parent_lot_id, lot_no from issued
                union
                select mup.start_id, m.id, m.parent_lot_id, m.lot_no from material_lot m join mup on m.id = mup.parent_lot_id
            )
            select (select lot_no from issued where issued.id = mup.start_id) as issued_no, mup.lot_no as root_no
              from mup where mup.parent_lot_id is null""", {"no": shipment_no or product_lot_no})
        return {r["root_no"] for r in rows}, {r["issued_no"] for r in rows}

    def indep_forward(self, material_lot_no: str) -> tuple[set, set]:
        rows = self.q("""
            with recursive down as (
                select id from material_lot where lot_no = %(no)s
                union
                select m.id from material_lot m join down on m.parent_lot_id = down.id
            ), wos as (
                select distinct l.work_order_id as id from material_issue_line l
                  join material_issue i on i.id = l.issue_id and i.canceled_at is null
                 where l.material_lot_id in (select id from down)
            ), pls as (
                select p.id, p.lot_no from product_lot p where p.work_order_id in (select id from wos)
                   and not exists (select 1 from product_receipt r where r.product_lot_id = p.id and r.canceled_at is not null)
            )
            select 'P' as k, lot_no as v from pls
            union
            select 'S', so.shipment_no from shipment_line sl join shipment_order so on so.id = sl.shipment_order_id
             where sl.product_lot_id in (select id from pls) and so.status <> '취소'""", {"no": material_lot_no})
        return {r["v"] for r in rows if r["k"] == "P"}, {r["v"] for r in rows if r["k"] == "S"}

    def traces(self) -> None:
        from lcomfine.app import trace

        v = self.v
        S1, P1, A1, A2, A1s = v["S1"], v["P1"], v["A1"], v["A2"], v["A1s"]
        html = self.get("LOT-020 역추적(출하 번호)", "sl", f"/lot/backward?shipment_no={S1}").text
        on_screen = all(x in html for x in (S1, P1, v["WO"], A1, A2, A1s))
        bw = trace.backward(shipment_no=S1)
        origin, issued = self.indep_backward(shipment_no=S1)
        self.db(f"화면에 {S1} · {P1} · {v['WO']} · {A1} · {A2} · {A1s} {'있음' if on_screen else '빠짐'}")
        self.r.add("G-07", "LOT-020 화면이 원자재 LOT 까지", on_screen,
                   f"GET /lot/backward?shipment_no={S1} 200 · 화면 글자 {S1} → {P1} → {v['WO']} → {A1}/{A1s}/{A2} {'전부' if on_screen else '빠짐'}")
        self.r.add("G-07", "trace.backward(출하) = 독립 SQL",
                   set(bw["origin_material_lot_nos"]) == origin == {A1, A2} and set(bw["issued_material_lot_nos"]) == issued,
                   f"origin {sorted(bw['origin_material_lot_nos'])} · 독립 {sorted(origin)} · 기대 {{{A1}, {A2}}} · "
                   f"불출 LOT {sorted(bw['issued_material_lot_nos'])} = 독립 {sorted(issued)} (분할 {A1s} → 원 {A1})")
        bw2 = trace.backward(product_lot_no=P1)
        o2, _ = self.indep_backward(product_lot_no=P1)
        self.r.add("G-07", "trace.backward(제품 LOT) = 독립 SQL", set(bw2["origin_material_lot_nos"]) == o2 == {A1, A2},
                   f"{P1} → {sorted(bw2['origin_material_lot_nos'])} · 독립 {sorted(o2)}")
        # 전 출하 대조 (DB 에 있는 모든 출하 — 다른 사람이 지우는 중이면 건너뛴다)
        mism, n, gone = [], 0, 0
        for r in self.q("select shipment_no from shipment_order where status <> '취소' order by id"):
            try:
                got = set(trace.backward(shipment_no=r["shipment_no"])["origin_material_lot_nos"])
            except trace.NotFound:
                gone += 1
                continue
            exp, _ = self.indep_backward(shipment_no=r["shipment_no"])
            n += 1
            if got != exp:
                mism.append(f"{r['shipment_no']}: trace {sorted(got)} ≠ 독립 {sorted(exp)}")
        self.r.add("G-07", "DB 의 모든 출하 trace.backward = 독립 SQL", not mism,
                   f"출하 {n} 건 대조 · 불일치 {len(mism)} {mism[:3] or ''} · 대조 중 사라짐 {gone}")
        # G-08
        html = self.get("LOT-010 정방향(원자재 LOT)", "pr", f"/lot/forward?lot_no={A1}").text
        on_screen = all(x in html for x in (A1, A1s, v["WO"], P1, S1))
        self.db(f"화면에 {A1} · {A1s} · {v['WO']} · {P1} · {S1} {'있음' if on_screen else '빠짐'}")
        fw = trace.forward(A1)
        pls, shs = self.indep_forward(A1)
        self.r.add("G-08", "LOT-010 화면이 출하까지", on_screen,
                   f"GET /lot/forward?lot_no={A1} 200 · {A1} → {A1s} → {v['WO']} → {P1} → {S1} {'전부' if on_screen else '빠짐'}")
        self.r.add("G-08", "trace.forward = 독립 SQL", set(fw["product_lot_nos"]) == pls and set(fw["shipment_nos"]) == shs
                   and S1 in shs and P1 in pls,
                   f"{A1}: 제품 LOT {sorted(fw['product_lot_nos'])} = 독립 {sorted(pls)} · 출하 {sorted(fw['shipment_nos'])} = 독립 {sorted(shs)}")
        mism, n = [], 0
        for r in self.q("select lot_no from material_lot where canceled_at is null and parent_lot_id is null order by id"):
            try:
                f = trace.forward(r["lot_no"])
            except trace.NotFound:
                continue
            p, s = self.indep_forward(r["lot_no"])
            n += 1
            if set(f["product_lot_nos"]) != p or set(f["shipment_nos"]) != s:
                mism.append(r["lot_no"])
        self.r.add("G-08", "DB 의 모든 원 입고 LOT trace.forward = 독립 SQL", not mism,
                   f"원자재 LOT {n} 건 대조 · 불일치 {len(mism)} {mism[:3] or ''}")

    # ════════════════════════════════════════════════════════════════════════
    # G-09 차단
    # ════════════════════════════════════════════════════════════════════════
    def blocks(self) -> None:
        v, t = self.v, self.tag
        L1 = str(v["L1"])
        b = self.post("MAT-010 원자재 입고(차단 시험 B · C)", "pr", "/mat/receipts",
                      {"supplier_name": f"{t} 공급사 (예시)", "item_id": [str(v["item_m"])] * 2, "qty": ["10", "10"],
                       "location_id": [L1, L1]}, numbers=lambda b: ", ".join(b["lot_nos"]))
        B, C = b["lot_nos"]
        self.receipt_ids.append(b["receipt_id"])
        self.mlot_nos += [B, C]
        self.post("QC-010 입고검사 불합격(C)", "pr", "/qc/incoming", {"lot_no": C, "result": "불합격"},
                  numbers=lambda b: f"{b['lot_no']} → {b['status']}")
        self.expect(self.stock1("원자재", C)["status"] == "보류", f"{C} 보류")
        before = self.q1("select count(*) as n from material_issue_line where work_order_id = %s", (v["WOid"],))["n"]
        res = {}
        for lot, label in ((B, "검사대기"), (C, "보류")):
            code, body = self.try_post(f"MAT-020 불출({label} LOT)", "pr", "/mat/issues",
                                       {"work_order_no": v["WO"], "lot_no": [lot], "location_id": [L1], "qty": ["1"]})
            res[label] = code
        after = self.q1("select count(*) as n from material_issue_line where work_order_id = %s", (v["WOid"],))["n"]
        qb, qc = self.stock1("원자재", B)["qty"], self.stock1("원자재", C)["qty"]
        self.r.add("G-09", "검사대기 · 보류 LOT 불출 422", res == {"검사대기": 422, "보류": 422} and before == after and qb == qc == 10,
                   f"불출 {B}(검사대기) {res['검사대기']} · {C}(보류) {res['보류']} · 불출 행 {before}→{after} · 재고 {qb}/{qc}")
        code, _ = self.try_post("MAT-010 입고(사용 중지 품목)", "pr", "/mat/receipts",
                                {"supplier_name": f"{t} 공급사 (예시)", "item_id": [str(v["item_x"])], "qty": ["1"],
                                 "location_id": [L1]})
        n = self.q1("select count(*) as n from material_lot where item_id = %s", (v["item_x"],))["n"]
        self.r.add("G-09", "사용 중지 품목 입고 422", code == 422 and n == 0, f"중지 품목 {t}-X 입고 {code} · LOT {n}")
        # 검사대기 제품 LOT 할당 → 422 (화면에는 가용 LOT 만 나온다 — 재고 행 id 를 직접 넣어 본다)
        p3sid = str(self.stock1("제품", v["P3"])["id"])
        html = self.c("sl").get("/shp/orders").text
        listed = f'value="{p3sid}"' in html
        code, _ = self.try_post("SHP-010 출하 지시(검사대기 LOT)", "sl", "/shp/orders",
                                {"customer_id": str(self.customer_id), "due_date": self.today.isoformat(),
                                 "stock_id": [p3sid], "qty": ["1"]})
        self.r.add("G-09", "검사대기 제품 LOT 할당 422 · 목록에 없음", code == 422 and not listed
                   and self.stock1("제품", v["P3"])["allocated_qty"] == 0,
                   f"{v['P3']} 할당 {code} · SHP-010 LOT 목록에 {'있음' if listed else '없음'}")
        # 보류(재판정 불합격) LOT 이 걸린 출하 확정 → 422
        p2sid = str(self.stock1("제품", v["P2"])["id"])
        b = self.post("SHP-010 출하 지시(P2 10)", "sl", "/shp/orders",
                      {"request_no": v["R1"], "stock_id": [p2sid], "qty": ["10"]}, numbers=lambda b: b["shipment_no"])
        S2, S2id = b["shipment_no"], b["id"]
        self.ship_nos.append(S2)
        v.update(S2=S2, S2id=S2id)
        self.post("QC-020 제품검사 재판정 불합격(P2)", "pr", f"/qc/product/{v['P2id']}", {"result": "불합격"},
                  numbers=lambda b: f"{b['lot_no']} #{b['seq']} → {b['status']}")
        st = self.stock1("제품", v["P2"])
        code, body = self.try_post("SHP-020 출하 확정(재판정 불합격 LOT)", "sh", f"/shp/confirm/{S2id}/confirm", {})
        st2 = self.stock1("제품", v["P2"])
        o = self.q1("select status from shipment_order where id = %s", (S2id,))
        self.r.add("G-09", "보류(불합격) LOT 출하 확정 422", code == 422 and o["status"] == "지시" and st == st2
                   and st["status"] == "보류" and st["allocated_qty"] == 10,
                   f"{S2} 확정 {code} · 상태 {o['status']} · {v['P2']} {st2['status']} qty {st2['qty']} 할당 {st2['allocated_qty']} 그대로(D-515 2)")
        # 불합격 → 합격 재판정은 보류 → 가용 (D-515 4) — 원자재 C 로 본다
        cid = self.q1("select id from material_lot where lot_no = %s", (C,))["id"]
        self.post("QC-010 입고검사 재판정 합격(C)", "pr", f"/qc/incoming/{cid}", {"result": "합격"},
                  numbers=lambda b: f"{b['lot_no']} #{b['seq']} → {b['status']}")
        stc = self.stock1("원자재", C)
        seqs = [r["result"] for r in self.q("select result from incoming_inspection where material_lot_id = %s order by seq", (cid,))]
        self.r.add("G-09", "재판정 불합격 → 합격 = 보류 → 가용 · 이전 판정 행 유지", stc["status"] == "가용" and seqs == ["불합격", "합격"],
                   f"{C} 판정 이력 {seqs} · 재고 {stc['status']} (D-515 4 · 새 행)")
        # 동시 불출 — 같은 원자재 LOT(가용 20)에 15 × 2
        A1 = v["A1"]
        s0 = self.stock1("원자재", A1)
        cl = [self.TestClient(self.app) for _ in range(2)]
        for x in cl:
            x.post("/login", data={"login_id": "pr", "password": self.pw}, follow_redirects=False)
        res: list = []
        bar = threading.Barrier(2)

        def go(x):
            bar.wait()
            resp = x.post("/mat/issues", data={"work_order_no": v["WO"], "lot_no": [A1], "location_id": [L1], "qty": ["15"]})
            res.append(resp.status_code)
            try:
                body = resp.json()
                if body.get("issue_id"):
                    self.issue_ids.append(body["issue_id"])
            except Exception:  # noqa: BLE001
                pass

        ths = [threading.Thread(target=go, args=(x,)) for x in cl]
        for th in ths:
            th.start()
        for th in ths:
            th.join(60)
        for code in res:
            self.r.steps.append(Step("MAT-020 동시 불출(스레드 2 · 각 15 / 가용 20)", "pr", "POST /mat/issues", code))
        s1 = self.stock1("원자재", A1)
        self.r.add("G-10", "동시 불출(스레드 2) 초과 없음", sorted(res) == [200, 422] and s1["qty"] == s0["qty"] - 15,
                   f"{A1} 가용 {s0['qty'] - s0['allocated_qty']} 에 15 × 2 동시 → 응답 {sorted(res)} · 남은 qty {s1['qty']}")

    # ════════════════════════════════════════════════════════════════════════
    # G-10 동시 할당 · 전 LOT 재계산 · 사용 중지 품목 출하 지시
    # ════════════════════════════════════════════════════════════════════════
    def allocation(self) -> None:
        v = self.v
        P1, sid = v["P1"], v["P1sid"]
        s0 = self.stock1("제품", P1)          # 확정 뒤 35 / 0
        results: dict[str, tuple[int, dict]] = {}
        clients = {lg: self.c(lg) for lg in ("sl", "sh")}
        barrier = threading.Barrier(2)

        def go(login: str) -> None:
            barrier.wait()
            resp = clients[login].post("/shp/orders", data={"request_no": v["R1"], "stock_id": [sid], "qty": ["30"]})
            try:
                results[login] = (resp.status_code, resp.json())
            except Exception:  # noqa: BLE001
                results[login] = (resp.status_code, {})

        ths = [threading.Thread(target=go, args=(lg,)) for lg in ("sl", "sh")]
        for th in ths:
            th.start()
        for th in ths:
            th.join(60)
        codes = sorted(c for c, _ in results.values())
        for lg, (c, body) in results.items():
            self.r.steps.append(Step("SHP-010 동시 할당(스레드 2 · 각 30 / 가용 35)", lg, "POST /shp/orders", c,
                                     body.get("shipment_no") or (body.get("detail") or {}).get("message", "")))
            if body.get("shipment_no"):
                self.ship_nos.append(body["shipment_no"])
                v.update(S3=body["shipment_no"], S3id=body["id"])
        s1 = self.stock1("제품", P1)
        self.r.add("G-10", "동시 할당(스레드 2) 초과 없음", codes == [200, 422] and s1["allocated_qty"] == 30 and s1["qty"] == 35,
                   f"가용 {s0['qty'] - s0['allocated_qty']} 에 30 × 2 동시 → 응답 {codes} · {P1} qty {s1['qty']} 할당 {s1['allocated_qty']}")
        # F-SHP-012 할당 다시 잡기 → 25
        if "S3id" in v:
            self.post("SHP-010 출하 지시 수정(할당 30 → 25)", "sl", f"/shp/orders/{v['S3id']}", {"stock_id": [sid], "qty": ["25"]})
            s2 = self.stock1("제품", P1)
            self.r.add("G-10", "수정으로 할당 다시 잡기", s2["allocated_qty"] == 25, f"{P1} 할당 30 → {s2['allocated_qty']} (기대 25)")
        # 사용 중지 제품 품목 → 출하 지시 422, 다시 사용
        self.post("BAS-010 제품 품목 사용 중지", "pr", f"/bas/items/{v['item_p']}",
                  {"item_name": f"{self.tag} 제품 (예시)", "item_type": "제품", "unit": "EA", "use_yn": "N"})
        html = self.c("sl").get("/shp/orders").text
        listed = f'value="{sid}"' in html
        code, _ = self.try_post("SHP-010 출하 지시(사용 중지 품목 LOT)", "sl", "/shp/orders",
                                {"request_no": v["R1"], "stock_id": [sid], "qty": ["1"]})
        self.post("BAS-010 제품 품목 다시 사용", "pr", f"/bas/items/{v['item_p']}",
                  {"item_name": f"{self.tag} 제품 (예시)", "item_type": "제품", "unit": "EA", "use_yn": "Y"})
        self.r.add("G-09", "사용 중지 품목 출하 지시 422 · 목록에 없음", code == 422 and not listed
                   and self.stock1("제품", P1)["allocated_qty"] == 25,
                   f"{self.tag}-P 중지 중 {P1} 할당 {code} · SHP-010 LOT 목록에 {'있음' if listed else '없음'}")
        self.global_allocation()

    def global_allocation(self) -> None:
        """전 LOT: allocated_qty = 열린(지시) 출하 행 합 · 가용 = qty − allocated · INV-010 화면 값 = DB 재계산."""
        rows = self.q("""
            select s.id, s.lot_kind, coalesce(m.lot_no, p.lot_no) as lot_no, w.warehouse_code, l.location_code,
                   s.qty, s.allocated_qty,
                   coalesce((select sum(sl.qty) from shipment_line sl join shipment_order so on so.id = sl.shipment_order_id
                              where so.status = '지시' and s.lot_kind = '제품' and sl.product_lot_id = s.lot_id
                                and sl.location_id = s.location_id), 0) as open_lines
              from lot_stock s
              left join material_lot m on s.lot_kind = '원자재' and m.id = s.lot_id
              left join product_lot p on s.lot_kind = '제품' and p.id = s.lot_id
              join location l on l.id = s.location_id join warehouse w on w.id = l.warehouse_id
             where m.canceled_at is null""")
        bad = [f"{r['lot_no']}@{r['location_code']}: 할당 {r['allocated_qty']} ≠ 열린 출하 행 {r['open_lines']}"
               for r in rows if r["allocated_qty"] != r["open_lines"]]
        self.r.add("G-10", "전 LOT 할당 = 열린 출하 행 합 (독립 재계산)", not bad,
                   f"lot_stock {len(rows)} 행 · 불일치 {len(bad)} {bad[:3] or ''}")
        html = self.c("admin").get("/inv/stock").text
        screen = {}
        for m in re.finditer(r'<tr data-lot="([^"]+)">(.*?)</tr>', html, re.S):
            tds = re.findall(r"<td[^>]*>(.*?)</td>", m.group(2), re.S)
            if len(tds) >= 9:
                key = (m.group(1), _html.unescape(re.sub("<[^>]+>", "", tds[4])).strip(),
                       _html.unescape(re.sub("<[^>]+>", "", tds[5])).strip())
                screen[key] = num(re.sub("<[^>]+>", "", tds[8]))
        dbv = {(r["lot_no"], r["warehouse_code"], r["location_code"]): r["qty"] - r["allocated_qty"] for r in rows}
        mism = [f"{k}: 화면 {screen.get(k)} ≠ {dbv[k]}" for k in dbv if k in screen and screen[k] != dbv[k]]
        missing = [k for k in dbv if k not in screen]
        self.r.add("G-10", "INV-010 화면 가용 = qty − allocated (전 행)", not mism and not missing,
                   f"화면 {len(screen)} 행 · DB {len(dbv)} 행 · 값 불일치 {len(mism)} {mism[:3] or ''} · 화면에 없음 {len(missing)} {missing[:3] or ''}")

    # ════════════════════════════════════════════════════════════════════════
    # 재판정 후 출하 (Review Focus 3 · D-515 3 · D-702)
    # ════════════════════════════════════════════════════════════════════════
    def rejudge_after_shipment(self) -> None:
        from lcomfine.app import trace

        v = self.v
        S1, P1 = v["S1"], v["P1"]
        before = self.q1("""select o.status, o.confirmed_at, (select sum(qty) from shipment_line where shipment_order_id = o.id) as q,
                                   (select count(*) from shipment_adjust where shipment_order_id = o.id) as adj
                              from shipment_order o where o.id = %s""", (v["S1id"],))
        b = self.post("QC-020 출하 뒤 재판정 불합격(P1)", "pr", f"/qc/product/{v['P1id']}", {"result": "불합격"},
                      numbers=lambda b: f"{b['lot_no']} #{b['seq']} → {b['status']} · shipped_after {b['shipped_after']}")
        after = self.q1("""select o.status, o.confirmed_at, (select sum(qty) from shipment_line where shipment_order_id = o.id) as q,
                                  (select count(*) from shipment_adjust where shipment_order_id = o.id) as adj
                             from shipment_order o where o.id = %s""", (v["S1id"],))
        st = self.stock1("제품", P1)
        flag = [x for x in trace.backward(shipment_no=S1)["rejected_after_shipment"] if x["product_lot_no"] == P1]
        html = self.get("LOT-020 역추적(재판정 뒤)", "sl", f"/lot/backward?shipment_no={S1}").text
        self.db(f"출하 {before['status']}→{after['status']} · 수량 {before['q']}→{after['q']} · 반품정정 {after['adj']} · "
                f"재고 {st['status']} · 「출하 후 불합격」 {'있음' if '출하 후 불합격' in html else '없음'}")
        self.r.add("G-07", "출하 후 불합격 — 출하 유지 · 역추적 표시",
                   before == after and b.get("shipped_after") is True and st["status"] == "보류" and bool(flag)
                   and "출하 후 불합격" in html,
                   f"{S1} {after['status']} · 확정 시각 · 수량 {after['q']} 그대로 · shipment_adjust {after['adj']} · "
                   f"남은 재고 {st['qty']} {st['status']} · trace.rejected_after_shipment {len(flag)} · LOT-020 「출하 후 불합격」 "
                   f"{'있음' if '출하 후 불합격' in html else '없음'}")
        if "S3id" in v:
            code, _ = self.try_post("SHP-020 출하 확정(재판정 불합격 P1 할당분)", "sh", f"/shp/confirm/{v['S3id']}/confirm", {})
            self.r.add("G-09", "출하 뒤 재판정 불합격 LOT 의 남은 지시 확정 422", code == 422, f"{v['S3']} 확정 {code}")

    # ════════════════════════════════════════════════════════════════════════
    # G-11 알림
    # ════════════════════════════════════════════════════════════════════════
    def notifications(self) -> None:
        v = self.v
        expected = {
            "request_created": (f"request_created:{v['R1']}", {"PR", "DS"}),
            "order_issued": (f"order_issued:{v['WO']}", {"PR"}),
            "material_received": (f"material_received:{v['A1']}", {"PR"}),
            "product_received": (f"product_received:{v['P1']}", {"PR"}),
            "judged": (f"judged:{v['P1']}:1", {"SH", "SL"}),
            "shipment_ordered": (f"shipment_ordered:{v['S1']}", {"SH"}),
            "shipment_confirmed": (f"shipment_confirmed:{v['S1']}", {"SL", "AC"}),
        }
        closed_by_screen = {"request_created": {"PR"}, "order_issued": {"PR"}, "material_received": {"PR"},
                            "product_received": {"PR"}, "judged": {"SL"}, "shipment_ordered": {"SH"}}
        for ev, (key, roles) in expected.items():
            n = self.notes(key)
            ok = set(n) == roles and all(x["event_key"] == ev for x in n.values())
            closed = closed_by_screen.get(ev, set())
            ok_closed = all(n.get(r, {}).get("handled_at") is not None for r in closed)
            self.r.add("G-11", f"{ev}", ok and ok_closed,
                       f"{key} → {sorted(n)} (기대 {sorted(roles)}) · 처리 화면이 닫음 {sorted(closed) or '-'} "
                       f"{'OK' if ok_closed else '안 닫힘'}")
        # dedupe — 같은 키 재발생은 무시 (notify.emit 을 같은 키로 다시 불러 본다: on conflict do nothing → 0행)
        from lcomfine.app import notify

        key = f"request_created:{v['R1']}"
        with self.conn.tx() as cur:
            again = notify.emit(cur, "request_created", link="/wo/requests", dedupe_key=key, text="QA2 dedupe 재발생")
        rows = self.q("select count(*) as n from notification where dedupe_key = %s", (key,))[0]["n"]
        self.r.add("G-11", "같은 키 재발생 무시 (D-522)", again == 0 and rows == 2, f"emit 재호출 새 행 {again} · {key} 행 {rows}")
        # HOME-020 처리 — 디자인·개발실의 request_created(처리 화면이 없는 부서)
        ds_id = self.notes(key)["DS"]["id"]
        html = self.get("HOME-020 알림함(ds)", "ds", "/home/notifications").text
        listed = f"/home/notifications/{ds_id}/handle" in html
        code, _ = self.try_post("HOME-020 다른 부서 알림 처리", "sh", f"/home/notifications/{ds_id}/handle", {})
        self.post("HOME-020 알림 처리", "ds", f"/home/notifications/{ds_id}/handle", {})
        n = self.notes(key)["DS"]
        html2 = self.c("ds").get("/home/notifications").text
        still = f"/home/notifications/{ds_id}/handle" in html2
        self.r.add("G-11", "HOME-020 처리 → 부서 처리됨 · 남의 부서 404",
                   listed and code == 404 and n["handled_by"] == "ds" and not still,
                   f"ds 알림함에 처리 버튼 {'있음' if listed else '없음'} → 처리 후 {'남음' if still else '사라짐'} · "
                   f"handled_by {n['handled_by']} · sh 가 처리 시도 {code}")
        code2, _ = self.try_post("HOME-020 이미 처리한 알림 다시 처리", "ds", f"/home/notifications/{ds_id}/handle", {})
        self.r.add("G-11", "이미 처리된 알림 다시 처리 200", code2 == 200, f"재처리 {code2}")
        # due_d3_unshipped — 배치
        rc1, out1 = self.due_check()
        k = f"due:{v['R2']}:{self.today.isoformat()}"
        n1 = self.notes(k)
        rc2, out2 = self.due_check()
        n2 = self.notes(k)
        r1_due = self.q("select count(*) as n from notification where dedupe_key like %s", (f"due:{v['R1']}:%",))[0]["n"]
        self.r.add("G-11", "due_d3_unshipped (jobs due-check)",
                   rc1 == rc2 == 0 and set(n1) == {"SL", "PR"} and set(n2) == {"SL", "PR"}
                   and {r: x["id"] for r, x in n1.items()} == {r: x["id"] for r, x in n2.items()} and r1_due == 0,
                   f"`python -m lcomfine.jobs due-check` ×2 rc {rc1}/{rc2} · {k} → {sorted(n1)} · 2회째 같은 행 · "
                   f"납기 D-10 의뢰 {v['R1']} 알림 {r1_due} · 출력 「{out2.strip().splitlines()[-1] if out2.strip() else ''}」")
        # erp_upload_error 는 수금 단계(collections)가 잰다 — 행이 없으면 run() 끝에서 FAIL 로 채운다

    def due_check(self) -> tuple[int, str]:
        p = subprocess.run(["uv", "run", "python", "-m", "lcomfine.jobs", "due-check"], cwd=ROOT, capture_output=True,
                           text=True, timeout=300)
        self.r.steps.append(Step("jobs due-check", "(배치)", "uv run python -m lcomfine.jobs due-check", p.returncode,
                                 (p.stdout or p.stderr).strip()[:160]))
        return p.returncode, p.stdout + p.stderr

    # ════════════════════════════════════════════════════════════════════════
    # G-05 동적 — 조회 화면 GET 전후 행 수
    # ════════════════════════════════════════════════════════════════════════
    def table_counts(self) -> dict[str, int]:
        names = [r["table_name"] for r in self.q("""select table_name from information_schema.tables
                                                    where table_schema = 'public' and table_type = 'BASE TABLE'""")]
        return {n: self.q1(f'select count(*) as n from "{n}"')["n"] for n in names if n not in LOG_TABLES}

    def readonly_diff(self) -> None:
        v = self.v
        paths = READ_SCREENS + [f"/lot/backward?shipment_no={v.get('S1', '')}", f"/lot/forward?lot_no={v.get('A1', '')}",
                                f"/trk/orders?q={v.get('R1', '')}"]
        diff = None
        for _ in range(3):          # 같은 DB 를 다른 QA 가 함께 쓴다 — 바깥 변화면 다시 잰다
            before = self.table_counts()
            codes = [self.c("admin").get(p).status_code for p in paths]
            after = self.table_counts()
            diff = {k: (before[k], after.get(k)) for k in before if before[k] != after.get(k)}
            if not diff:
                break
        self.r.add("G-05", "조회 화면 GET 전후 업무 테이블 diff 0",
                   not diff and all(c == 200 for c in codes),
                   f"admin GET {len(paths)} 화면(TRK 3 · LOT 2 · PRP 3 · WO-040 · INV-010 · QC-030 · SHP-030 · HOME · COL 7) "
                   f"응답 {sorted(set(codes))} · 테이블 diff {diff or 0} (sys_access_log 제외)")

    # ════════════════════════════════════════════════════════════════════════
    # G-10 — F-SHP-012 라인 전부 제거 = 지시 취소 (function-list 계약 문장 · Ruling 21) → 할당 해제 · 가용 복원
    # ════════════════════════════════════════════════════════════════════════
    def shp012_cancel(self) -> None:
        """취소 뒤 할당 0 · 가용 = qty 복원 · 독립 SQL(열린 출하 행 합) 대조 · INV-010 화면 값 · 알림 없음."""
        v = self.v
        if "S2id" not in v:
            self.r.add("G-10", "F-SHP-012 라인 전부 제거 = 지시 취소 · 할당 해제 · 가용 복원 (Ruling 21)", FAIL,
                       "앞 단계에서 S2 출하 지시가 만들어지지 않았다")
            return
        P2 = v["P2"]
        before = self.stock1("제품", P2)
        lb = self.q1("select count(*) as n, coalesce(sum(qty), 0) as s from shipment_line where shipment_order_id = %s", (v["S2id"],))
        ev_before = self.q1("select count(*) as n from notification where dedupe_key like %s", (f"%:{v['S2']}",))["n"]
        code, body = self.try_post("SHP-010 출하 지시 수정(라인 전부 제거 = 취소)", "sl", f"/shp/orders/{v['S2id']}",
                                   {"stock_id": [""], "qty": [""]})
        o = self.q1("select status from shipment_order where id = %s", (v["S2id"],))
        after = self.stock1("제품", P2)
        la = self.q1("select count(*) as n from shipment_line where shipment_order_id = %s", (v["S2id"],))["n"]
        # 독립 재계산 — 그 재고 행의 할당 = 열린(지시) 출하 행 합. 취소 뒤 0 이어야 하고 가용 = qty − 0 = qty
        indep = self.q1("""select coalesce(sum(sl.qty), 0) as open_alloc
                             from shipment_line sl join shipment_order so on so.id = sl.shipment_order_id
                            where so.status = '지시' and sl.product_lot_id = %s and sl.location_id = %s""",
                        (v["P2id"], v["L1"]))["open_alloc"]
        ev_after = self.q1("select count(*) as n from notification where dedupe_key like %s", (f"%:{v['S2']}",))["n"]
        avail_screen = self.inv_available("sl", P2)
        self.db(f"응답 {code} · 상태 {o['status']} · {P2} 할당 {before['allocated_qty']}→{after['allocated_qty']} · 독립 열린 출하 행 합 {indep} · "
                f"shipment_line {lb['n']}→{la} · INV-010 가용 {avail_screen} · 알림 행 {ev_before}→{ev_after}")
        ok = (code == 200 and o["status"] == "취소" and lb["n"] == 1 and la == 0
              and before["allocated_qty"] == lb["s"] and after["allocated_qty"] == 0 == indep
              and after["qty"] == before["qty"] and avail_screen == [after["qty"]] and ev_after == ev_before)
        self.r.add("G-10", "F-SHP-012 라인 전부 제거 = 지시 취소 · 할당 해제 · 가용 복원 (Ruling 21)", ok,
                   f"{v['S2']} 라인 {lb['n']}→{la} → 응답 {code} · 상태 {o['status']} · {P2} qty {after['qty']} 할당 "
                   f"{before['allocated_qty']}→{after['allocated_qty']} = 독립 SQL(열린 출하 행 합) {indep} · 가용 {after['qty'] - after['allocated_qty']} "
                   f"= INV-010 {avail_screen} · 알림 없음({ev_before}→{ev_after})")

    # ════════════════════════════════════════════════════════════════════════
    # W2 수금 — G-11 erp_upload_error · G-12 회차 교체 · G-13 오류 행 · 미매핑 · G-14 출하 대비 수금
    # ════════════════════════════════════════════════════════════════════════
    @staticmethod
    def xlsx(headers: list[str], rows: list[list]) -> bytes:
        """(예시) ERP 수금현황 엑셀 — 첫 시트 · 1행 열 이름. 값은 글자 그대로(원문 보존을 본다)."""
        import io

        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.append(headers)
        for r in rows:
            ws.append(r)
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def post_file(self, step: str, login: str, period: tuple[date, date], headers: list[str], rows: list[list],
                  action: str = "apply", expect: int = 200) -> dict:
        """COL-010 `POST /col/uploads` — 화면 폼과 같은 multipart(action · period_from · period_to · file)."""
        f, t = period
        resp = self.c(login).post("/col/uploads", data={"action": action, "period_from": f.isoformat(), "period_to": t.isoformat()},
                                  files={"file": (f"{self.tag}-erp (예시).xlsx", self.xlsx(headers, rows), XLSX_MIME)},
                                  follow_redirects=False)
        try:
            body = resp.json()
        except Exception:  # noqa: BLE001
            body = {"text": resp.text[:200]}
        det = body.get("detail") if isinstance(body.get("detail"), dict) else {}
        nums = (f"{body.get('batch_no')} {body.get('round_no')}회차 · 행 {body.get('rows')} · 오류 {body.get('errors')} · 교체 {body.get('replaced')}"
                if resp.status_code == 200 and action == "apply" else (det.get("message") or body.get("message", "")))
        self.r.steps.append(Step(step, login, f"POST /col/uploads action={action} {f}~{t} ({len(rows)}행)", resp.status_code, nums))
        if resp.status_code != expect:
            raise StepFailed(f"{step}: POST /col/uploads ({login}) → {resp.status_code} (기대 {expect}) {str(body)[:300]}")
        if action == "apply" and resp.status_code == 200:
            self.erp_batches.append(body["id"])
        return body

    def free_period(self, f: date, t: date) -> tuple[date, date]:
        """다른 사람의 회차와 (기준 기간 시작, 끝)이 겹치지 않는 기간 — 같은 기간 재업로드는 그 회차를 교체하기 때문이다."""
        while t > f and self.q1("select 1 from erp_upload_batch where period_from = %s and period_to = %s", (f, t)):
            t -= timedelta(days=1)
        return f, t

    @staticmethod
    def row_cells(html: str, attrs: str) -> list[str] | None:
        """`<tr {attrs}>` 한 행의 td 글자(태그 제거). 없으면 None."""
        m = re.search(r"<tr " + attrs + r">(.*?)</tr>", html, re.S)
        if not m:
            return None
        return [_html.unescape(re.sub("<[^>]+>", "", td)).strip() for td in re.findall(r"<td[^>]*>(.*?)</td>", m.group(1), re.S)]

    @staticmethod
    def cell(text: str | None) -> Decimal | None:
        """화면 숫자 칸 → Decimal. 빈 칸(`-`) 은 None."""
        from lcomfine.app.util.screen import EMPTY

        if text is None or text.strip() in ("", EMPTY):
            return None
        return num(text)

    def col070(self, ym: str, customer_id: int | None = None) -> dict[int, tuple]:
        """COL-070 화면의 (월 = ym) 거래처 행 → {customer_id: (출하 건수, 출하 수량, 매출, 수금)} (빈 칸 None)."""
        q = f"/col/shipment-vs-collection?ym_from={ym}&ym_to={ym}" + (f"&customer={customer_id}" if customer_id else "")
        html = self.get("COL-070 출하 대비 수금", "ac", q).text
        out = {}
        for m in re.finditer(r'<tr data-month="' + re.escape(ym) + r'" data-customer="(\d+)">(.*?)</tr>', html, re.S):
            tds = [_html.unescape(re.sub("<[^>]+>", "", td)).strip() for td in re.findall(r"<td[^>]*>(.*?)</td>", m.group(2), re.S)]
            out[int(m.group(1))] = tuple(self.cell(x) for x in tds[2:6])
        return out

    def indep_ship_vs_coll(self, ym: str, customer_id: int) -> tuple:
        """QA2 독립 SQL — (확정 출하 건수, 출하 수량, ERP 매출 합, ERP 수금 합). 뷰를 거치지 않고 테이블에서 직접:
        출하 = shipment_order status '확정' · confirmed_at 의 월 / ERP = erp_upload_row ← 반영 회차 · error 없음 · 사용 중 매핑 · txn_date 의 월."""
        s = self.q1("""select count(distinct o.id) as n, sum(l.qty) as q
                         from shipment_order o join shipment_line l on l.shipment_order_id = o.id
                        where o.status = '확정' and o.customer_id = %s and to_char(o.confirmed_at, 'YYYY-MM') = %s""", (customer_id, ym))
        e = self.q1("""select sum(nullif(u.parsed ->> 'sales_amount', '')::numeric) as s,
                              sum(nullif(u.parsed ->> 'collected_amount', '')::numeric) as c, count(*) as n
                         from erp_upload_row u
                         join erp_upload_batch b on b.id = u.batch_id and b.status = '반영'
                         join erp_customer_map m on m.erp_code = u.parsed ->> 'customer_code' and m.use_yn = 'Y'
                        where u.error is null and m.customer_id = %s
                          and to_char((u.parsed ->> 'txn_date')::date, 'YYYY-MM') = %s""", (customer_id, ym))
        ship_n = s["n"] or None
        return (ship_n, s["q"] if ship_n else None, e["s"] if e["n"] else None, e["c"] if e["n"] else None)

    def collections(self) -> None:
        from lcomfine.app import erp_upload, notify, stats

        v, t = self.v, self.tag
        C1 = self.customer_id
        # 월 · 날짜는 DB 가 센 값(세션 시간대) — 확정 출하 S1 의 confirmed_at 월 = ERP 일자 월
        anchor = self.q1("select to_char(confirmed_at, 'YYYY-MM') as ym, confirmed_at::date as d from shipment_order where id = %s", (v["S1id"],))
        ym, d = anchor["ym"], anchor["d"]
        m1 = date(int(ym[:4]), int(ym[5:7]), 1)
        m_last = (m1 + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        P = self.free_period(m1, m_last)                    # 기준 기간 P — 회차 1 · 2 (교체)
        Q = self.free_period(m1, max(m1, min(m1 + timedelta(days=14), P[1] - timedelta(days=1))))   # 기준 기간 Q — ERP 만 있는 거래처
        v.update(ym=ym, P=P, Q=Q)
        # 열 매핑 — 지금 저장된 것을 쓴다. 거래처코드 · 일자 · 매출액 · 수금액이 없으면 시드 매핑(정본 낱말 7)을 HTTP 로 저장하고 끝에 되돌린다
        cmap = erp_upload.column_map()
        if not all(cmap.get(f) for f in ("customer_code", "txn_date", "sales_amount", "collected_amount")):
            from lcomfine.db import seed_dev3

            self.cmap_before = self.q("select field, column_name, created_by from erp_column_map order by id")
            self.post("COL-010 열 매핑 저장(시드 낱말 7)", "ac", "/col/uploads",
                      {"action": "map", **{f"map_{f}": c for f, c in seed_dev3.COLUMN_MAP.items()}})
            cmap = erp_upload.column_map()
        fields = [f for f in erp_upload.FIELDS if cmap.get(f)]
        heads = [cmap[f] for f in fields]

        def row(code, day, sales=None, collected=None, method=None, bill_due=None, balance=None):
            vals = {"customer_code": code, "txn_date": day, "sales_amount": sales, "collected_amount": collected,
                    "balance_amount": balance, "method": method, "bill_due_date": bill_due}
            return [vals[f] for f in fields]

        E, U, E2 = f"{t}-E", f"{t}-U", f"{t}-E2"           # E → 거래처 C1(출하 있음) · U 미매핑 · E2 → 거래처 C2(출하 없음)
        self.erp_codes += [E, U, E2]
        d1, d2 = m1.isoformat(), d.isoformat()
        link = erp_upload.error_link

        def notes_for(bid: int) -> list[dict]:
            return self.q("select to_role, handled_at, event_key, dedupe_key, message from notification where link = %s order by to_role",
                          (link(bid),))

        # ── 회차 1 (기간 P) — E 는 아직 미매핑이라 전부 오류 행 · 알림 1행 (AC)
        A = self.post_file("COL-010 ERP 업로드 1회차(기간 P · 미매핑 E · U · 날짜 오류)", "ac", P, heads,
                           [row(E, d1, "1000", "0"), row(E, d2, "0", "300"), row(U, d1, "77", "77"), row(E, f"{m1.year}/13/01", "1", "1")])
        bA = self.q1("select * from erp_upload_batch where id = %s", (A["id"],))
        nA = notes_for(A["id"])
        all_err = self.q1("select count(*) as n from notification where event_key = 'erp_upload_error' and link = %s", (link(A["id"]),))["n"]
        self.expect(bA["status"] == "반영" and bA["row_count"] == 4 and bA["error_count"] == 4 and A["round_no"] == 1 and A["replaced"] is None,
                    f"{bA['batch_no']} 반영 · 1회차 · 행 4 · 오류 4(E 미매핑 3 + 날짜 1 · U 1 — 겹침)")
        ok_note = ([n["to_role"] for n in nA] == ["AC"] and nA[0]["handled_at"] is None and nA[0]["event_key"] == "erp_upload_error"
                   and nA[0]["dedupe_key"] == f"erp_upload_error:{bA['batch_no']}" and all_err == 1
                   and "4행" in nA[0]["message"] and U in nA[0]["message"])
        with self.conn.tx() as cur:
            again = notify.emit(cur, "erp_upload_error", link=link(A["id"]), dedupe_key=f"erp_upload_error:{bA['batch_no']}", text="QA2 dedupe")
        n_after = len(notes_for(A["id"]))
        self.db(f"notification erp_upload_error → {[n['to_role'] for n in nA]} · link {link(A['id'])} · dedupe 재호출 새 행 {again}")
        # 매핑 전 COL-070 — C1 은 출하만 (MES 쪽만)
        before_map = self.col070(ym, C1)
        s1q = self.q1("select sum(l.qty) as q from shipment_line l where l.shipment_order_id = %s", (v["S1id"],))["q"]
        self.r.add("G-14", "출하만 있는 거래처 = MES 쪽만 (ERP 코드 매핑 전)",
                   before_map.get(C1) == (1, s1q, None, None),
                   f"COL-070 {ym} {t}-C → 출하 {before_map.get(C1)} (기대 (1, {s1q}, None, None)) — E 미매핑이라 ERP 쪽 비어 있음")

        # ── 회차 2 (같은 기간 P) — 교체 · 이전 회차 행 보존 · 교체된 회차의 알림 닫힘
        rows2 = [row(E, d1, "1000", "0"), row(E, d2, "0", "300", "PM (예시)", d2),      # 2 · 3 정상(매핑 뒤)
                 row(U, d1, "77", "77"),                                                  # 4 미매핑
                 row(E, f"{m1.year}/13/01", "1", "1"),                                    # 5 날짜 형식
                 row(E, d2, "abc", "0"),                                                  # 6 금액 형식
                 row("", d2, "5", "0")]                                                   # 7 필수(거래처코드) 누락
        A2 = self.post_file("COL-010 ERP 재업로드 2회차(같은 기간 P · 6행)", "ac", P, heads, rows2)
        bA_after = self.q1("select * from erp_upload_batch where id = %s", (A["id"],))
        bA2 = self.q1("select * from erp_upload_batch where id = %s", (A2["id"],))
        rowsA = self.q("select row_no, error from erp_upload_row where batch_id = %s order by row_no", (A["id"],))
        live_n = self.q1("select count(*) as n from erp_upload_batch where period_from = %s and period_to = %s and status = '반영'", P)["n"]
        viewA = self.q1("select count(*) as n from v_dq_collections where batch_no = %s", (bA["batch_no"],))["n"]
        nA_after = notes_for(A["id"])
        nA2 = notes_for(A2["id"])
        self.db(f"{bA['batch_no']} {bA_after['status']} replaced_by {bA_after['replaced_by']} · 행 {len(rowsA)} · {bA2['batch_no']} {bA2['status']} {bA2['round_no']}회차")
        self.r.add("G-12", "같은 기간 재업로드 = 새 회차 반영 · 이전 회차 교체 + replaced_by · 이전 회차 행 보존",
                   A2["replaced"] == bA["batch_no"] and A2["round_no"] == 2 and bA_after["status"] == "교체"
                   and bA_after["replaced_by"] == A2["id"] and bA2["status"] == "반영" and bA2["replaced_by"] is None
                   and len(rowsA) == 4 and bA_after["row_count"] == 4 and all(r["error"] for r in rowsA),
                   f"기간 {P[0]}~{P[1]}: {bA['batch_no']} 1회차 → {bA2['batch_no']} 2회차(응답 replaced {A2['replaced']}) · 이전 status {bA_after['status']} "
                   f"replaced_by {bA_after['replaced_by']} (= 새 회차 id {A2['id']}) · 이전 회차 행 4→{len(rowsA)} 그대로 · 새 회차 {bA2['status']} · 행 {A2['rows']} 오류 {A2['errors']}")
        self.r.add("G-12", "기간마다 반영 하나 · v_dq_collections 는 반영 회차만",
                   live_n == 1 and viewA == 0,
                   f"기간 {P[0]}~{P[1]} 의 반영 회차 {live_n} · 교체 회차 {bA['batch_no']} 의 뷰 행 {viewA} (이전엔 오류 4 라 0 · 교체 뒤에도 0)")
        self.r.add("G-11", "erp_upload_error",
                   ok_note and again == 0 and n_after == 1 and nA_after and nA_after[0]["handled_at"] is not None
                   and [n["to_role"] for n in nA2] == ["AC"] and nA2[0]["handled_at"] is None,
                   f"회차 {bA['batch_no']}(오류 4) → AC 1행 {'OK' if ok_note else '불일치'} · dedupe erp_upload_error:{bA['batch_no']} 재발생 새 행 {again} · "
                   f"같은 기간 교체 → 그 알림 닫힘 {'OK' if nA_after and nA_after[0]['handled_at'] else '안 닫힘'} · 새 회차 {bA2['batch_no']}(오류 {A2['errors']}) → AC 1행 미처리 "
                   f"{[n['to_role'] for n in nA2]} · 재해석으로 오류 0 → 닫힘은 다음 행(기간 Q 회차)")
        # COL-020 — 반영 / 교체됨 구분 · 회차별 오류 행
        html = self.get("COL-020 업로드 이력", "ac", "/col/upload-history").text
        segA = html[html.find(f'data-batch="{A["id"]}"'):][:240] if f'data-batch="{A["id"]}"' in html else ""
        segA2 = html[html.find(f'data-batch="{A2["id"]}"'):][:240] if f'data-batch="{A2["id"]}"' in html else ""
        detail = self.get("COL-020 회차별 오류 행 (2회차)", "ac", f"/col/upload-history?batch={A2['id']}").text
        err_rows_shown = sorted(int(x) for x in re.findall(r'<tr data-row="(\d+)"', detail))
        self.r.add("G-12", "COL-020 이력 — 반영 / 교체됨 구분 · 교체한 회차 번호",
                   'data-status="교체"' in segA and "교체됨" in segA and 'data-status="반영"' in segA2 and bA2["batch_no"] in detail,
                   f"{bA['batch_no']} 행 data-status {'교체 · 「교체됨」' if '교체됨' in segA else segA[:60]} · {bA2['batch_no']} 행 {'반영' if '반영' in segA2 else segA2[:60]}")
        self.r.add("G-13", "COL-020 회차별 오류 행 보기 (매핑 전 — 6행 전부 오류)", err_rows_shown == [2, 3, 4, 5, 6, 7],
                   f"?batch={A2['id']} 오류 행 data-row {err_rows_shown} (엑셀 행 2~7 · E 미매핑 포함)")

        # ── 회차 B (기간 Q) — ERP 만 있는 거래처 C2 · 미매핑 E2 → 매핑 등록으로 오류 0 → 알림 닫힘 (G-11 · G-13)
        C2 = self.post("BAS-020 거래처(ERP 만 · 출하 없음)", "sl", "/bas/customers",
                       {"customer_code": f"{t}-C2", "customer_name": f"{t} 거래처 2 (예시)"}, numbers=lambda b: f"customer {b['id']}")["id"]
        self.customer2_id = C2
        B = self.post_file("COL-010 ERP 업로드(기간 Q · 미매핑 E2 2행)", "ac", Q, heads, [row(E2, d1, "500", "0"), row(E2, d2, "0", "200")])
        bB = self.q1("select * from erp_upload_batch where id = %s", (B["id"],))
        nB = notes_for(B["id"])
        html = self.get("COL-030 거래처 코드 매핑(미매핑 목록)", "ac", "/col/customer-map").text
        listed_before = {c: f'data-unmapped="{c}"' in html for c in (E, U, E2)}
        unm = {u["erp_code"]: u for u in erp_upload.unmapped_codes() if u["erp_code"] in (E, U, E2)}
        self.db(f"COL-030 미매핑 목록 {listed_before} · unmapped_codes {sorted(unm)}")
        m2 = self.post("COL-030 거래처 코드 매핑 등록(E2 → C2)", "ac", "/col/customer-map",
                       {"erp_code": E2, "erp_name": f"{t} ERP 거래처 2 (예시)", "customer_id": str(C2)},
                       numbers=lambda b: f"map {b['id']} · 재해석 {b['reinterpreted']} · 반영 {b['applied']} · 여전히 오류 {b['still_error']}")
        bB_after = self.q1("select * from erp_upload_batch where id = %s", (B["id"],))
        rowsB = self.q("select row_no, error, updated_at from erp_upload_row where batch_id = %s order by row_no", (B["id"],))
        nB_after = notes_for(B["id"])
        viewB = self.q1("select count(*) as n from v_dq_collections where batch_no = %s and customer_code = %s", (bB["batch_no"], f"{t}-C2"))["n"]
        self.r.add("G-11", "erp_upload_error — 매핑 뒤 재해석으로 오류 0 이면 닫힘",
                   bB["error_count"] == 2 and [n["to_role"] for n in nB] == ["AC"] and nB[0]["handled_at"] is None
                   and (m2["reinterpreted"], m2["applied"], m2["still_error"], m2["remapped"]) == (2, 2, 0, 2)
                   and bB_after["error_count"] == 0 and nB_after and nB_after[0]["handled_at"] is not None,
                   f"회차 {bB['batch_no']} 오류 {bB['error_count']}(E2 미매핑) → AC 1행 미처리 → E2 매핑 등록 → 재해석 {m2['reinterpreted']} · 반영 {m2['applied']} · "
                   f"여전히 오류 {m2['still_error']} (remapped = applied {m2['remapped']}) · "
                   f"error_count {bB_after['error_count']} · 알림 handled_at {'있음(닫힘)' if nB_after and nB_after[0]['handled_at'] else '없음'}")
        # ── E → C1 매핑 — 반영 회차 A2 의 E 행만 재해석 · 교체 회차 A 는 그대로 · 오류 남은 알림은 열린 채
        m1_ = self.post("COL-030 거래처 코드 매핑 등록(E → C1)", "ac", "/col/customer-map",
                        {"erp_code": E, "erp_name": f"{t} ERP 거래처 (예시)", "customer_id": str(C1)},
                        numbers=lambda b: f"map {b['id']} · 재해석 {b['reinterpreted']} · 반영 {b['applied']} · 여전히 오류 {b['still_error']} · 「{b.get('message', '')[-60:]}」")
        rowsA2 = self.q("select row_no, raw, parsed, error, updated_at from erp_upload_row where batch_id = %s order by row_no", (A2["id"],))
        rowsA_after = self.q("select row_no, error from erp_upload_row where batch_id = %s order by row_no", (A["id"],))
        bA2_after = self.q1("select * from erp_upload_batch where id = %s", (A2["id"],))
        bA_final = self.q1("select * from erp_upload_batch where id = %s", (A["id"],))
        nA2_after = notes_for(A2["id"])
        err = {r["row_no"]: (r["error"] or "") for r in rowsA2}
        UP = erp_upload.UNMAPPED_PREFIX
        kept = (rowsA2[2]["raw"].get(cmap["customer_code"]) == U and rowsA2[3]["raw"].get(cmap["txn_date"]) == f"{m1.year}/13/01"
                and rowsA2[4]["raw"].get(cmap["sales_amount"]) == "abc")
        ok_err = (err[2] == "" and err[3] == "" and err[4].startswith(UP) and U in err[4]
                  and "일자" in err[5] and UP not in err[5] and "매출액" in err[6] and UP not in err[6]
                  and "거래처코드" in err[7] and "필수" in err[7])
        self.db(f"A2 error 행 {dict((k, x[:40]) for k, x in err.items())} · 재해석 {m1_['reinterpreted']} · 반영 {m1_['applied']} · 여전히 오류 {m1_['still_error']}")
        self.r.add("G-13", "오류 행 보존 — 날짜 · 금액 · 필수 · 미매핑 행이 error 사유 · 원문(raw)과 함께 저장",
                   kept and ok_err and bA2_after["error_count"] == 4 and bA2_after["row_count"] == 6,
                   f"{bA2['batch_no']} 행 6: 2 · 3 정상(error null) · 4 「{err[4][:30]}」 · 5 「{err[5][:24]}…」 · 6 「{err[6][:26]}…」 · 7 「{err[7][:30]}」 "
                   f"· raw 원문 그대로 {'OK' if kept else '불일치'} · error_count {bA2_after['error_count']}")
        self.r.add("G-13", "COL-030 미매핑 목록 · 매핑 뒤 반영 회차만 재해석(error is null) · 교체 회차 그대로",
                   listed_before == {E: True, U: True, E2: True} and set(unm) == {E, U, E2} and unm[E]["rows"] == 4 and unm[U]["rows"] == 1
                   and (m1_["reinterpreted"], m1_["applied"], m1_["still_error"], m1_["remapped"]) == (4, 2, 2, 2)
                   and "다시 해석한 행 4" in m1_.get("message", "") and "그중 반영 2" in m1_.get("message", "") and "여전히 제외 2" in m1_.get("message", "")
                   and all(r["error"] and UP in r["error"] for r in rowsA_after) and bA_final["error_count"] == 4
                   and nA2_after and nA2_after[0]["handled_at"] is None
                   and f'data-unmapped="{E}"' not in self.c("ac").get("/col/customer-map").text
                   and f'data-unmapped="{U}"' in self.c("ac").get("/col/customer-map").text,
                   f"매핑 전 COL-030 data-unmapped {listed_before} · unmapped_codes E {unm.get(E, {}).get('rows')}행(반영 회차만 · 교체 회차의 3행은 세지 않음) U {unm.get(U, {}).get('rows')}행 · "
                   f"E 매핑 → 반영 회차 {bA2['batch_no']} 응답 재해석 {m1_['reinterpreted']} · 반영 {m1_['applied']} · 여전히 오류 {m1_['still_error']} "
                   f"(remapped = applied {m1_['remapped']} · 문장 「{m1_.get('message', '')[-48:]}」 — DEF-QA2-004 해소) · 교체 회차 {bA['batch_no']} 오류 4 그대로 · "
                   f"남은 오류 4 라 알림 열린 채 · 매핑 뒤 목록에서 E 사라짐 · U 남음")
        # 반영에서 빠진다 — 뷰 · COL-040 · COL-050 · COL-020 오류 행
        viewA2 = self.q("select erp_customer_code, sales_amount, collected_amount from v_dq_collections where batch_no = %s order by txn_date",
                        (bA2["batch_no"],))
        viewU = self.q1("select count(*) as n from v_dq_collections where erp_customer_code = %s", (U,))["n"]
        c040 = self.get("COL-040 수금 현황(거래처 C1 · 이 달)", "ac",
                        f"/col/collections?date_from={m1.isoformat()}&date_to={m_last.isoformat()}&customer={C1}").text
        c040_rows = re.findall(r'<tr data-erp-code="([^"]+)"', c040)
        c050 = self.get("COL-050 거래처별 미수", "ac", f"/col/receivables?asof={m_last.isoformat()}").text
        c050_cells = self.row_cells(c050, f'data-customer="{C1}"')
        c050_nums = tuple(self.cell(x) for x in c050_cells[3:6]) if c050_cells and len(c050_cells) >= 6 else None
        detail2 = self.get("COL-020 회차별 오류 행 (E 매핑 뒤)", "ac", f"/col/upload-history?batch={A2['id']}").text
        err_rows_after = sorted(int(x) for x in re.findall(r'<tr data-row="(\d+)"', detail2))
        self.db(f"뷰 {len(viewA2)}행 · U {viewU} · COL-040 행 {c040_rows} · COL-050 {c050_nums} · COL-020 오류 행 {err_rows_after}")
        self.r.add("G-13", "오류 행 · 미매핑 행은 반영에서 제외 (v_dq_collections · COL-040 · COL-050) · COL-020 에는 보임",
                   len(viewA2) == 2 and {r["erp_customer_code"] for r in viewA2} == {E} and viewU == 0
                   and c040_rows == [E, E] and U not in c040 and c050_nums == (Decimal(1000), Decimal(300), Decimal(700)) and U not in c050
                   and err_rows_after == [4, 5, 6, 7],
                   f"뷰 {bA2['batch_no']} 행 {len(viewA2)}(E 만) · 미매핑 {U} 뷰 {viewU} · COL-040 행 {len(c040_rows)} {U} {'없음' if U not in c040 else '있음'} · "
                   f"COL-050 {t}-C 매출 · 수금 · 미수 {c050_nums} (기대 1000 · 300 · 700) · COL-020 ?batch= 오류 행 {err_rows_after} (기대 [4, 5, 6, 7])")

        # ── G-14 — COL-070 화면 = 독립 SQL (C1 양쪽 · C2 ERP 만 · U 제외)
        screen_all = self.col070(ym)
        screen_c1 = self.col070(ym, C1)
        ind1, ind2 = self.indep_ship_vs_coll(ym, C1), self.indep_ship_vs_coll(ym, C2)
        mod = {r["customer_id"]: (r["shipments"], r["shipped_qty"], r["sales_amount"], r["collected_amount"])
               for r in stats.shipment_vs_collection(ym, ym)["rows"] if r["ym"] == ym}
        view_c1 = self.q1("""select sum(sales_amount) as s, sum(collected_amount) as c from v_dq_collections
                              where customer_code = %s and to_char(txn_date, 'YYYY-MM') = %s""", (f"{t}-C", ym))
        v["col070"] = {"ym": ym, "C1": C1, "C2": C2, "screen": {C1: screen_all.get(C1), C2: screen_all.get(C2)}, "indep": {C1: ind1, C2: ind2},
                       "E": E, "U": U, "E2": E2}
        self.db(f"화면 C1 {screen_all.get(C1)} C2 {screen_all.get(C2)} · 독립 C1 {ind1} C2 {ind2} · 모듈 C1 {mod.get(C1)} C2 {mod.get(C2)}")
        self.r.add("G-14", "COL-070 화면 (월 · 거래처) = QA2 독립 SQL — 출하 · ERP 양쪽 있는 거래처",
                   screen_all.get(C1) == ind1 == (1, s1q, Decimal(1000), Decimal(300)) and screen_c1.get(C1) == ind1,
                   f"{ym} {t}-C: 화면 (출하 건수 · 수량 · 매출 · 수금) {screen_all.get(C1)} = 독립 SQL {ind1} (기대 (1, {s1q}, 1000, 300)) · ?customer= 필터 {screen_c1.get(C1)}")
        self.r.add("G-14", "ERP 만 있는 거래처 = ERP 쪽만 · 미매핑 코드는 어느 쪽에도 없음",
                   screen_all.get(C2) == ind2 == (None, None, Decimal(500), Decimal(200)) and viewU == 0 and U not in self.c("ac").get(
                       f"/col/shipment-vs-collection?ym_from={ym}&ym_to={ym}").text,
                   f"{ym} {t}-C2: 화면 {screen_all.get(C2)} = 독립 SQL {ind2} (기대 (None, None, 500, 200)) · {U}(미매핑 77/77) 뷰 {viewU} · 화면에 없음")
        self.r.add("G-14", "stats.shipment_vs_collection = 독립 SQL · 뷰(v_dq_collections) = 테이블 직접 집계",
                   mod.get(C1) == ind1 and mod.get(C2) == ind2 and (view_c1["s"], view_c1["c"]) == ind1[2:],
                   f"모듈 C1 {mod.get(C1)} C2 {mod.get(C2)} · 뷰 C1 매출 · 수금 ({view_c1['s']}, {view_c1['c']}) = 테이블 직접 {ind1[2:]} · 건 단위 짝짓기 없음(월 · 거래처 합만)")

    # ════════════════════════════════════════════════════════════════════════
    # 정리
    # ════════════════════════════════════════════════════════════════════════
    def cleanup(self) -> str:
        c = self.conn
        self.cleanup_erp()
        mlots = [r["id"] for r in c.q("select id from material_lot where lot_no = any(%s) or receipt_id = any(%s)",
                                      (self.mlot_nos, self.receipt_ids or [0]))]
        wos = [r["id"] for r in c.q("select id from work_order where request_id = any(%s)", (self.req_ids or [0],))] + self.wo_ids
        plots = [r["id"] for r in c.q("select id from product_lot where work_order_id = any(%s) or lot_no = any(%s)",
                                      (wos or [0], self.plot_nos))]
        orders = [r["id"] for r in c.q("select id from shipment_order where customer_id = %s", (self.customer_id or 0,))]
        ship_nos = [r["shipment_no"] for r in c.q("select shipment_no from shipment_order where id = any(%s)", (orders,))]
        plot_nos = [r["lot_no"] for r in c.q("select lot_no from product_lot where id = any(%s)", (plots,))]
        mlot_nos = [r["lot_no"] for r in c.q("select lot_no from material_lot where id = any(%s)", (mlots,))]
        wo_nos = [r["work_order_no"] for r in c.q("select work_order_no from work_order where id = any(%s)", (wos or [0],))]
        keys = ([f"request_created:{n}" for n in self.req_nos] + [f"order_issued:{n}" for n in wo_nos]
                + [f"material_received:{n}" for n in mlot_nos] + [f"product_received:{n}" for n in plot_nos]
                + [f"shipment_ordered:{n}" for n in ship_nos] + [f"shipment_confirmed:{n}" for n in ship_nos])
        likes = [f"judged:{n}:%" for n in plot_nos] + [f"due:{n}:%" for n in self.req_nos]
        adj = c.q1("select count(*) as n from shipment_adjust where shipment_order_id = any(%s)", (orders,))["n"]
        sadj = c.q1("select count(*) as n from stock_adjust where (lot_kind = '원자재' and lot_id = any(%s)) "
                    "or (lot_kind = '제품' and lot_id = any(%s))", (mlots, plots))["n"]
        if adj or sadj:
            return f"정리 보류 — 불변 이력 shipment_adjust {adj} · stock_adjust {sadj} 행이 있어 LOT · 출하를 지우지 않았다"
        with c.tx() as cur:
            cur.execute("delete from notification where dedupe_key = any(%s) or dedupe_key like any(%s)", (keys, likes or [""]))
            cur.execute("delete from stock_move where (lot_kind = '원자재' and lot_id = any(%s)) or (lot_kind = '제품' and lot_id = any(%s))"
                        " or (ref_table = 'shipment_order' and ref_id = any(%s))", (mlots, plots, orders))
            cur.execute("delete from shipment_line where shipment_order_id = any(%s)", (orders,))
            cur.execute("delete from shipment_order where id = any(%s)", (orders,))
            cur.execute("delete from product_inspection where product_lot_id = any(%s)", (plots,))
            cur.execute("delete from incoming_inspection where material_lot_id = any(%s)", (mlots,))
            cur.execute("delete from lot_stock where (lot_kind = '원자재' and lot_id = any(%s)) or (lot_kind = '제품' and lot_id = any(%s))",
                        (mlots, plots))
            cur.execute("delete from product_receipt where product_lot_id = any(%s) or work_order_id = any(%s)", (plots, wos or [0]))
            cur.execute("delete from product_lot where id = any(%s) and parent_lot_id is not null", (plots,))
            cur.execute("delete from product_lot where id = any(%s)", (plots,))
            cur.execute("delete from production_daily where work_order_id = any(%s)", (wos or [0],))
            cur.execute("delete from inspection_daily where work_order_id = any(%s)", (wos or [0],))
            cur.execute("delete from material_issue_line where work_order_id = any(%s) or material_lot_id = any(%s)", (wos or [0], mlots))
            cur.execute("delete from material_issue where id = any(%s)", (self.issue_ids or [0],))
            cur.execute("delete from material_lot where id = any(%s) and parent_lot_id is not null", (mlots,))
            cur.execute("delete from material_lot where id = any(%s)", (mlots,))
            cur.execute("delete from material_receipt where id = any(%s)", (self.receipt_ids or [0],))
            cur.execute("delete from work_sequence where work_order_id = any(%s)", (wos or [0],))
            cur.execute("delete from work_order where id = any(%s)", (wos or [0],))
            cur.execute("delete from production_request where id = any(%s)", (self.req_ids or [0],))
            if self.locations:
                cur.execute("delete from location where id = any(%s)", (self.locations,))
            if self.warehouse_id:
                cur.execute("delete from warehouse where id = %s", (self.warehouse_id,))
            if self.customer_id:
                cur.execute("delete from customer where id = %s", (self.customer_id,))
            if self.customer2_id:
                cur.execute("delete from customer where id = %s", (self.customer2_id,))
            if self.items:
                cur.execute("delete from item where id = any(%s)", (self.items,))
        left = c.q1("""select (select count(*) from item where item_code like %(t)s) + (select count(*) from customer where customer_code like %(t)s)
                            + (select count(*) from warehouse where warehouse_code like %(t)s)
                            + (select count(*) from erp_customer_map where erp_code like %(t)s)
                            + (select count(*) from erp_upload_batch where source_file like %(t)s) as n""", {"t": f"{self.tag}%"})["n"]
        return f"정리 완료 — {self.tag} 기준정보 · ERP 회차 · 매핑 남은 행 {left} (sys_change_log · sys_access_log 감사 행과 채번 카운터는 남긴다)"

    def cleanup_erp(self) -> None:
        """W2 가 만든 ERP 회차(행 · 알림) · 거래처 매핑을 지우고, 바꿨으면 열 매핑을 원래대로 되돌린다."""
        from lcomfine.app import erp_upload

        c = self.conn
        bids = [r["id"] for r in c.q("select id from erp_upload_batch where id = any(%s) or source_file like %s",
                                     (self.erp_batches or [0], f"{self.tag}%"))]
        with c.tx() as cur:
            if bids:
                cur.execute("delete from notification where event_key = 'erp_upload_error' and link = any(%s)",
                            ([erp_upload.error_link(b) for b in bids],))
                cur.execute("delete from erp_upload_row where batch_id = any(%s)", (bids,))
                cur.execute("delete from erp_upload_batch where id = any(%s)", (bids,))      # replaced_by FK 는 문장 끝에 검사된다
            cur.execute("delete from erp_customer_map where erp_code = any(%s) or customer_id = any(%s)",
                        (self.erp_codes or [""], [x for x in (self.customer_id, self.customer2_id) if x] or [0]))
            if self.cmap_before is not None:
                cur.execute("delete from erp_column_map")
                for b in self.cmap_before:
                    cur.execute("insert into erp_column_map (field, column_name, created_by) values (%s, %s, %s)",
                                (b["field"], b["column_name"], b["created_by"]))

    # ════════════════════════════════════════════════════════════════════════
    def run(self, keep: bool = False, only: set[str] | None = None) -> None:
        """`only` = 돌릴 단계의 메서드 이름 집합(테스트가 일부만 돌릴 때 · 예 {"base", "e2e", "collections"}). 기본 전부."""
        stages = [("G-06", "기준정보 BAS (HTTP)", self.base), ("G-06", "E2E 의뢰 → 출하 확정", self.e2e),
                  ("G-07", "추적", self.traces), ("G-09", "차단", self.blocks), ("G-10", "할당", self.allocation),
                  ("G-07", "재판정 후 출하", self.rejudge_after_shipment), ("G-11", "알림", self.notifications),
                  ("G-05", "조회 diff", self.readonly_diff), ("G-10", "F-SHP-012 취소 = 할당 해제", self.shp012_cancel),
                  ("G-12", "수금 — 회차 교체 · 오류 행 · erp_upload_error · 출하 대비 수금", self.collections)]
        if only:
            stages = [s for s in stages if s[2].__name__ in only]
        failed = None
        try:
            for gate, name, fn in stages:
                if failed:
                    self.r.add(gate, f"{name}", FAIL, f"앞 단계 실패로 돌리지 못함 — {failed}")
                    continue
                try:
                    fn()
                    if name.startswith("E2E"):
                        self.r.add("G-06", "E2E 의뢰 → 출하 확정 (HTTP 만)", True,
                                   f"{self.v['R1']} → {self.v['WO']} → {self.v['A1']}/{self.v['A1s']}/{self.v['A2']} → "
                                   f"{self.v['P1']} → {self.v['S1']} 확정 · 부서 sl · pr · sh · 요청 {len(self.r.steps)} 전부 기대 응답")
                except StepFailed as exc:
                    failed = f"{name}: {exc}"
                    self.r.add(gate, f"{name}", FAIL, str(exc))
                except Exception as exc:  # noqa: BLE001 — 예상 못한 실패도 그대로 FAIL 로 보인다(조용히 넘기지 않는다)
                    failed = f"{name}: {type(exc).__name__} {exc}"
                    self.r.add(gate, f"{name}", FAIL, f"{type(exc).__name__}: {str(exc)[:300]}")
            # 재지 못한 게이트는 행이 없어 PASS 로 보이면 안 된다
            if not only or "collections" in only:
                for gate, prefix in sorted(MUST_MEASURE):
                    if not any(c.gate == gate and c.item.startswith(prefix) for c in self.r.checks):
                        self.r.add(gate, f"{prefix} ({GATE_NAMES[gate]})", FAIL, f"수금 단계가 돌지 못해 재지 못함 — {failed or '행 없음'}")
        finally:
            if keep:
                self.r.notes.append(f"--keep — {self.tag} 행을 지우지 않았다")
            else:
                try:
                    self.r.notes.append(self.cleanup())
                except Exception as exc:  # noqa: BLE001
                    self.r.notes.append(f"정리 실패 — {type(exc).__name__}: {exc}")


# ════════════════════════════════════════════════════════════════════════════
def seed_idempotence(report: Report) -> None:
    """개발 시드 2회 — 행 수 diff 0 (G-21 은 QA3 판정 · 여기서는 참고 행)."""
    import importlib

    from lcomfine.db import conn

    def counts():
        names = [r["table_name"] for r in conn.q("""select table_name from information_schema.tables
                                                     where table_schema = 'public' and table_type = 'BASE TABLE'""")]
        return {n: conn.q1(f'select count(*) as n from "{n}"')["n"] for n in names if n not in ("sys_access_log", "sys_change_log")}

    mods = [m for m in ("seed_dev1", "seed_dev2", "seed_dev3") if (ROOT / f"src/lcomfine/db/{m}.py").exists()]
    out = []
    for m in mods:
        mod = importlib.import_module(f"lcomfine.db.{m}")
        mod.run()
        a = counts()
        mod.run()
        b = counts()
        d = {k: (a[k], b.get(k)) for k in a if a[k] != b.get(k)}
        out.append((m, d))
    report.notes.append("시드 멱등(참고 · G-21 은 QA3) — " + " · ".join(f"{m}.run() 2회 diff {d or 0}" for m, d in out)
                        + f" · 없는 개발 시드 {sorted(set(['seed_dev1', 'seed_dev2', 'seed_dev3']) - set(mods))}")
    report.seed = out  # type: ignore[attr-defined]


def run_all(keep: bool = False) -> Report:
    report = Report()
    try:
        static_scan(report)
    except Exception as exc:  # noqa: BLE001
        report.add("G-05", "쓰기 경계 — 정적 스캔", FAIL, f"스캔 실패 {type(exc).__name__}: {exc}")
    try:
        static_col(report)
    except Exception as exc:  # noqa: BLE001
        report.add("G-13", "수금 수정 경로 없음 — 정적 스캔", FAIL, f"스캔 실패 {type(exc).__name__}: {exc}")
    try:
        Flow(report).run(keep=keep)
    except Exception as exc:  # noqa: BLE001
        report.add("G-06", "E2E 흐름", FAIL, f"흐름을 시작하지 못함 {type(exc).__name__}: {exc}")
    for gid, w in LATER.items():
        report.add(gid, GATE_NAMES[gid], FAIL, f"{w} — 화면 · 기능이 아직 없다 (W2/W3 에서 잰다)")
    return report


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    from lcomfine.app.settings import get_settings

    get_settings()
    report = run_all(keep="--keep" in argv)
    if "--seed" in argv:
        seed_idempotence(report)
    for gid in GATE_NAMES:
        for c in [c for c in report.checks if c.gate == gid]:
            print(f"{c.gate}  {c.item}  {c.status}  {c.measured}")
    print()
    for n in report.notes:
        print(f"참고: {n}")
    if "--transcript" in argv:
        print()
        print("| # | 단계 | 계정 | 요청 | 응답 | 번호 · 메시지 | DB 확인 |")
        print("|---|---|---|---|---|---|---|")
        for i, s in enumerate(report.steps, 1):
            cell = lambda x: str(x).replace("|", "\\|")  # noqa: E731
            print(f"| {i} | {cell(s.step)} | {s.account} | `{cell(s.request)}` | {s.status} | {cell(s.numbers)} | {cell(s.db)} |")
    fails = sum(1 for c in report.checks if c.status == FAIL)
    by_gate = {g: ("FAIL" if any(c.status == FAIL for c in report.checks if c.gate == g) else
                   "미검증" if any(c.status != PASS for c in report.checks if c.gate == g) else "PASS") for g in GATE_NAMES}
    print()
    print("게이트 요약: " + " · ".join(f"{g} {s}" for g, s in by_gate.items()) + f" — FAIL 행 {fails} → 종료코드 {min(fails, 125)}")
    return min(fails, 125)


if __name__ == "__main__":
    raise SystemExit(main())
