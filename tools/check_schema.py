#!/usr/bin/env python
"""G-04 스키마 검사 — `make check-schema`. 기대값은 테이블 **이름 집합**이다(D-521).

  1. 계약 §1 표(영역 → 테이블) = schema.sql 의 `@table` = §4 렌더본 = 실제 DB 테이블 (이름 · 영역)
  2. 영역 코드 ⊆ 정본 대메뉴 코드(`design_doc.effective()`) ∪ {SYS} · 테이블 없는 대메뉴 = 쓰기 기능 없는 대메뉴
  3. 계약 컬럼(§4) = 실제 DB 컬럼 (이름 · 타입 · NULL · 순서)
  4. 렌더본(§2.3 쓰는 테이블 · §4 테이블 · §5 뷰)이 원본과 어긋나지 않았는가
  5. 계약 §1 뷰 표 = schema.sql 의 뷰 = 실제 DB 뷰 · 구체화 뷰 없음 · 추적·집계 캐시 테이블 없음
  6. 추적 척추 FK (스펙 §4.2 · §3) 가 실제 DB 에 있다
  7. 쓰기 경계: 기능이 쓰는 테이블은 계약에 있고, 그 기능의 대메뉴 영역이거나 §2.2 예외 표에 있다
  8. 상태 check 제약의 값 = §6 (한글 그대로)
  9. 불변 이력(stock_adjust · shipment_adjust)에 before update or delete 트리거
 10. schema.sql 의 제약 · 인덱스 · 트리거 · 뷰 이름 = 실제 DB · 테이블마다 PK

출력 행 형식: `G-04  항목  PASS|FAIL  실측`. 종료코드: 0 = PASS, 1 = FAIL (어긋난 것을 그 줄에 적는다).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import design_doc  # noqa: E402
import gen_contracts  # noqa: E402
from lcomfine.app import contracts  # noqa: E402
from lcomfine.db import conn  # noqa: E402

DB_SCHEMA_MD = ROOT / "contracts" / "db-schema.md"
SCHEMA_SQL = ROOT / "src" / "lcomfine" / "db" / "schema.sql"
FN_ID_RE = re.compile(r"F-[A-Z]+-\d+")
ANY_WRITE = "모든 쓰기"
ANY_READ = "모든 화면 조회"   # 읽기 쪽 공통 로그 — 기능의 쓰는 테이블과 대조하지 않는다

#: 추적 척추 — (테이블, 컬럼) → 참조 테이블 (db-schema.md §3)
SPINE_FKS = {
    ("material_issue_line", "material_lot_id"): "material_lot",
    ("material_issue_line", "work_order_id"): "work_order",
    ("material_issue_line", "issue_id"): "material_issue",
    ("material_lot", "receipt_id"): "material_receipt",
    ("material_lot", "parent_lot_id"): "material_lot",
    ("work_order", "request_id"): "production_request",
    ("product_receipt", "work_order_id"): "work_order",
    ("product_receipt", "product_lot_id"): "product_lot",
    ("product_lot", "work_order_id"): "work_order",
    ("product_lot", "parent_lot_id"): "product_lot",
    ("shipment_line", "product_lot_id"): "product_lot",
    ("shipment_line", "shipment_order_id"): "shipment_order",
    ("shipment_adjust", "shipment_order_id"): "shipment_order",
}
APPEND_ONLY = ("stock_adjust", "shipment_adjust")


def _section(text: str, head: str, nxt: str) -> str:
    return text[text.index(head):text.index(nxt)]


def contract_areas() -> tuple[dict[str, str], dict[str, str]]:
    """계약 §1 의 두 표 → ({테이블: 영역}, {뷰: 영역}). 첫 칸 = 영역 코드, 둘째 칸 = 백틱 이름 하나."""
    sec = _section(DB_SCHEMA_MD.read_text(encoding="utf-8"), "## 1.", "## 2.")
    tables: dict[str, str] = {}
    views: dict[str, str] = {}
    for ln in sec.splitlines():
        m = re.match(r"\|\s*([A-Z]+)\s*\|\s*`(\w+)`\s*\|", ln)
        if m:
            (views if m.group(2).startswith("v_") else tables)[m.group(2)] = m.group(1)
    return tables, views


def contract_exceptions() -> list[tuple[set[str] | None, set[str]]]:
    """계약 §2.2 예외 표 → [(기능 ID 집합 | None = 모든 쓰기, 테이블 집합)]."""
    sec = _section(DB_SCHEMA_MD.read_text(encoding="utf-8"), "### 2.2", "### 2.3")
    out: list[tuple[set[str] | None, set[str]]] = []
    for ln in sec.splitlines():
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) < 2 or not re.findall(r"`(\w+)`", cells[1]):
            continue
        ids = set(FN_ID_RE.findall(cells[0]))
        if not ids and cells[0] not in (ANY_WRITE, ANY_READ):
            continue
        if cells[0] == ANY_READ:
            out.append((set(), set(re.findall(r"`(\w+)`", cells[1]))))   # 기능에 걸리지 않는 행 — 표에 있음만 확인
            continue
        out.append((ids or None, set(re.findall(r"`(\w+)`", cells[1]))))
    return out


def contract_states() -> dict[tuple[str, str], set[str]]:
    """계약 §6 상태값 표 → {(테이블, 컬럼): 값 집합}. `테이블.컬럼` 칸이 하나인 행만."""
    sec = DB_SCHEMA_MD.read_text(encoding="utf-8").split("## 6.", 1)[1]
    out: dict[tuple[str, str], set[str]] = {}
    for ln in sec.splitlines():
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        keys = re.findall(r"`(\w+)\.(\w+)`", cells[0])
        if not keys:
            continue
        vals = set(re.findall(r"`([^`.]+)`", cells[1].split("—")[0].split("(")[0]))
        for k in keys:
            out[k] = vals
    return out


def schema_sql_names() -> dict[str, set[str]]:
    code = "\n".join(ln.split("--")[0] for ln in SCHEMA_SQL.read_text(encoding="utf-8").splitlines())
    return {
        "constraint": set(re.findall(r"^\s*constraint\s+(\w+)\s", code, re.M)),
        "index": set(re.findall(r"^create\s+(?:unique\s+)?index\s+(\w+)\s", code, re.M)),
        "trigger": set(re.findall(r"^create\s+trigger\s+(\w+)", code, re.M)),
        "view": set(re.findall(r"^create\s+view\s+(\w+)", code, re.M)),
    }


def live_fks() -> dict[tuple[str, str], str]:
    rows = conn.q(
        """select c.conrelid::regclass::text as t, a.attname as col, c.confrelid::regclass::text as ref
             from pg_constraint c
             join pg_namespace n on n.oid = c.connamespace
             join pg_attribute a on a.attrelid = c.conrelid and a.attnum = c.conkey[1]
            where n.nspname = 'public' and c.contype = 'f' and array_length(c.conkey, 1) = 1""")
    return {(r["t"], r["col"]): r["ref"] for r in rows}


def check_values(table: str, column: str) -> set[str] | None:
    """`column in ('a', 'b')` 꼴의 check 제약 값. 없으면 None."""
    for r in conn.q("""select pg_get_constraintdef(oid) as def from pg_constraint
                        where conrelid = %s::regclass and contype = 'c'""", (table,)):
        d = r["def"]
        if re.search(rf"\b{column}\b", d) and ("= ANY" in d or " IN " in d.upper()):
            m = re.search(rf"\(?{column}\b[^A]*= ANY \(\(?ARRAY\[(.*?)\]", d)
            if m:
                return set(re.findall(r"'([^']*)'", m.group(1)))
    return None


def main() -> int:
    rows: list[tuple[str, bool, str]] = []

    def add(item: str, ok: bool, actual: str) -> None:
        rows.append((item, bool(ok), actual))

    try:
        spec = contracts.db_tables()
        c_tables, c_views = contract_areas()
        sql_tables = {t["name"]: t["store"] for t in gen_contracts.parse_schema_sql()}
        sql_views = {n for n, _ in gen_contracts.parse_views()}
    except (Exception, SystemExit) as exc:  # noqa: BLE001
        print(f"G-04  계약 · schema.sql 읽기  FAIL  {type(exc).__name__}: {exc}")
        return 1
    live = gen_contracts.db_columns()

    # ── 1. 이름 집합 ──
    def diff(a: dict | set, b: dict | set, an: str, bn: str) -> list[str]:
        a, b = set(a), set(b)
        return ([f"{an}에만 {sorted(a - b)}"] if a - b else []) + ([f"{bn}에만 {sorted(b - a)}"] if b - a else [])

    bad = diff(c_tables, sql_tables, "§1 표", "schema.sql ") + diff(c_tables, spec, "§1 표", "§4 렌더본 ") \
        + diff(c_tables, live, "§1 표", "DB ")
    area_bad = sorted(f"{t}: §1 {a} · sql {sql_tables.get(t)} · §4 {spec[t].store if t in spec else None}"
                      for t, a in c_tables.items() if sql_tables.get(t) != a or (t in spec and spec[t].store != a))
    add("테이블 이름 집합: 계약 §1 = schema.sql = §4 렌더본 = 실제 DB (D-521)", not bad and not area_bad,
        f"§1 {len(c_tables)} · sql {len(sql_tables)} · §4 {len(spec)} · DB {len(live)}"
        + (f" — {' · '.join(bad)}" if bad else "") + (f" — 영역 불일치 {area_bad}" if area_bad else ""))

    # ── 2. 영역 코드 ──
    menus = [m["code"] for m in design_doc.effective()["menus"]]
    areas = set(c_tables.values())
    unknown = sorted(areas - set(menus) - {"SYS"})
    write_menus = {f.menu_code for f in contracts.write_functions()}
    no_table_but_writes = sorted(write_menus - areas)
    tables_but_no_writes = sorted(areas - write_menus)
    add("영역 = 정본 대메뉴 코드 ∪ SYS · 쓰기 기능이 있는 대메뉴만 테이블을 가진다",
        not unknown and not no_table_but_writes and not tables_but_no_writes,
        f"영역 {len(areas)} {' '.join(a for a in dict.fromkeys(menus + ['SYS']) if a in areas)} · 테이블 없는 대메뉴 "
        f"{' '.join(m for m in menus if m not in areas)}" + (f" — 정본에 없는 영역 {unknown}" if unknown else "")
        + (f" — 쓰기는 있는데 테이블 없음 {no_table_but_writes}" if no_table_but_writes else "")
        + (f" — 테이블은 있는데 쓰기 없음 {tables_but_no_writes}" if tables_but_no_writes else ""))

    # ── 3. 컬럼 ──
    diffs: list[str] = []
    n_spec = n_live = 0
    for name, t in spec.items():
        want = [(c.name, c.type, c.nullable) for c in t.columns]
        got = live.get(name, [])
        n_spec, n_live = n_spec + len(want), n_live + len(got)
        if want != got:
            w, g = {c[0]: c for c in want}, {c[0]: c for c in got}
            diffs += [f"{name}.{col}" for col in sorted(set(w) | set(g)) if w.get(col) != g.get(col)] or [f"{name}(순서)"]
    add("계약 컬럼 = 실제 DB 컬럼 (이름 · 타입 · NULL · 순서)", not diffs,
        f"계약 {n_spec} · DB {n_live} · 불일치 {len(diffs)}" + (f" {diffs[:5]}" if diffs else ""))

    # ── 4. 렌더본 ──
    text = DB_SCHEMA_MD.read_text(encoding="utf-8")
    stale: list[str] = []
    for key, fn in (("writes", gen_contracts.render_writes), ("tables", gen_contracts.render_tables),
                    ("views", gen_contracts.render_views)):
        try:
            if gen_contracts.replace_block(text, key, fn(), DB_SCHEMA_MD) != text:
                stale.append(key)
        except SystemExit as exc:
            stale.append(f"{key}: {str(exc)[:120]}")
    add("db-schema.md 렌더본(§2.3 writes · §4 tables · §5 views) = 원본", not stale,
        "일치" if not stale else f"다르다 {stale} — `make contracts`")

    # ── 5. 뷰 · 캐시 없음 ──
    db_views = {r["viewname"] for r in conn.q("select viewname from pg_views where schemaname = 'public'")}
    matviews = conn.q1("select count(*) as n from pg_matviews where schemaname = 'public'")["n"]
    vbad = diff(c_views, sql_views, "§1 뷰 표", "schema.sql ") + diff(c_views, db_views, "§1 뷰 표", "DB ")
    dq = sorted(v for v in c_views if v.startswith("v_dq_"))
    cache = sorted(t for t in live if re.search(r"trace|cache|closure|ancest|descend|summary|_agg|^stat", t))
    add("뷰 = 계약 §1 (v_work_order_status + v_dq_* 8) · 구체화 뷰 0 · 추적·집계 캐시 테이블 0",
        not vbad and len(dq) == 8 and "v_work_order_status" in c_views and matviews == 0 and not cache,
        f"뷰 {len(db_views)} · v_dq_* {len(dq)} · 구체화 뷰 {matviews} · 캐시 테이블 {cache or 0}"
        + (f" — {' · '.join(vbad)}" if vbad else ""))

    # ── 6. 추적 척추 ──
    fks = live_fks()
    lost = sorted(f"{t}.{c}→{ref}" for (t, c), ref in SPINE_FKS.items() if fks.get((t, c)) != ref)
    add("추적 척추 FK (원자재 LOT → 불출 → 지시 → 제품 LOT → 출하 · 분할 LOT)", not lost,
        f"{len(SPINE_FKS) - len(lost)}/{len(SPINE_FKS)}" + (f" — 없음 {lost}" if lost else ""))

    # ── 7. 쓰기 경계 ──
    exc = contract_exceptions()
    missing, outside, used_exc = [], [], set()
    for f in contracts.write_functions():
        for t in f.tables:
            if t not in c_tables:
                missing.append(f"{f.id}:{t}")
                continue
            if c_tables[t] == f.menu_code:
                continue
            hit = [i for i, (ids, ts) in enumerate(exc) if t in ts and (ids is None or f.id in ids)]
            if hit:
                used_exc.update(hit)
            else:
                outside.append(f"{f.id}({f.menu_code})→{t}({c_tables[t]})")
    readonly = sorted(f.id for f in contracts.functions() if f.menu_code in ("TRK", "LOT", "PRP") and f.tables)
    unused = [i for i, (ids, _) in enumerate(exc) if ids and i not in used_exc]   # 기능 ID 를 적은 행은 실제로 쓰여야 한다
    add("쓰기 경계: 쓰는 테이블 ⊆ 자기 대메뉴 영역 ∪ §2.2 예외 · TRK·LOT·PRP 쓰기 0",
        exc and not missing and not outside and not readonly and not unused,
        f"쓰기 기능 {len(contracts.write_functions())} · 예외 행 {len(exc)}(쓰임 {len(used_exc)})"
        + (f" — 계약에 없는 테이블 {missing}" if missing else "") + (f" — 영역 밖 {outside}" if outside else "")
        + (f" — 읽기 대메뉴의 쓰기 {readonly}" if readonly else "") + (f" — 쓰이지 않는 예외 행 {unused}" if unused else ""))

    # ── 8. 상태값 ──
    states = contract_states()
    sbad = []
    for (t, c), vals in states.items():
        got = check_values(t, c) if t in live else None
        if got != vals:
            sbad.append(f"{t}.{c}: 계약 {sorted(vals)} · DB {sorted(got) if got is not None else '제약 없음'}")
    add("상태 check 제약 값 = 계약 §6", bool(states) and not sbad,
        f"상태 컬럼 {len(states)}" + (f" — {sbad}" if sbad else ""))

    # ── 9. 불변 이력 ──
    trg = conn.q("""select tgrelid::regclass::text as t, tgtype from pg_trigger
                     where not tgisinternal and tgrelid::regclass::text = any(%s)""", (list(APPEND_ONLY),))
    guarded = sorted({r["t"] for r in trg if r["tgtype"] & 2 and r["tgtype"] & 8 and r["tgtype"] & 16})
    no_trunc = sorted({r["t"] for r in trg if r["tgtype"] & 2 and r["tgtype"] & 32})
    add("불변 이력 — stock_adjust · shipment_adjust 에 before update or delete · before truncate 트리거",
        guarded == sorted(APPEND_ONLY) and no_trunc == sorted(APPEND_ONLY),
        f"update·delete {guarded} · truncate {no_trunc}")

    # ── 10. 이름 · PK ──
    want = schema_sql_names()
    have = {
        "constraint": {r["conname"] for r in conn.q(
            "select conname from pg_constraint c join pg_namespace n on n.oid = c.connamespace where n.nspname = 'public'")},
        "index": {r["indexname"] for r in conn.q("select indexname from pg_indexes where schemaname = 'public'")},
        "trigger": {r["tgname"] for r in conn.q("select tgname from pg_trigger where not tgisinternal")},
        "view": db_views,
    }
    gone = {k: sorted(want[k] - have[k]) for k in want if want[k] - have[k]}
    no_pk = sorted(t for t in live if not conn.q1(
        "select 1 from pg_constraint where conrelid = %s::regclass and contype = 'p'", (t,)))
    add("schema.sql 의 제약·인덱스·트리거·뷰 이름이 실제 DB 에 · 테이블마다 PK", not gone and not no_pk,
        " · ".join(f"{k} {len(want[k] & have[k])}/{len(want[k])}" for k in want)
        + (f" — DB 에 없는 것 {gone}" if gone else "") + (f" — PK 없음 {no_pk}" if no_pk else ""))

    w = max(len(i) for i, _, _ in rows)
    print("G-04 스키마 ↔ 계약 ↔ 실제 DB (tools/check_schema.py)")
    print("-" * 100)
    for item, ok, actual in rows:
        print(f"G-04  {item:<{w}}  {'PASS' if ok else 'FAIL'}  {actual}")
    print("-" * 100)
    failed = sum(1 for _, ok, _ in rows if not ok)
    print(f"G-04 판정: {'PASS' if failed == 0 else 'FAIL'} (검사 {len(rows)} · 실패 {failed})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
