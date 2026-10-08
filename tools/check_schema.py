#!/usr/bin/env python
"""G-04 저장소 검사 — `make check-schema`. (아키텍트 초판 → QA2 가 이어받아 넓혔다, decisions.md D-24)

아키텍트 초판 (1~5)
  1. D1~D8 이 `contracts/db-schema.md` 의 테이블에 빠짐없이 대응하는가
  2. `material_lot` · `roll` · `roll_genealogy` · `shipment` 가 이 이름 그대로 실제 DB 에 있는가
  3. 계약의 테이블·컬럼(이름·타입·NULL) = 실제 DB
  4. 렌더본(db-schema.md §4)이 원본(schema.sql)과 어긋나지 않았는가
  5. `roll` 이 한 테이블에 공정 구분으로 · `roll_genealogy` 에 순환을 막는 제약이 있는가

QA2 가 더한 것 (6~13) — 기대값을 **설계도에서 직접** 읽는다
  6. 설계도 §2 의 저장소 D1~D8(번호·이름) = 계약 §1 표의 저장소 · 계약 §1 표의 테이블 = §4 렌더본의 저장소별 테이블
  7. 설계도 §3 그림에 적힌 테이블 이름(열 머리 + 본문의 `roll_genealogy`) = 실제 DB 의 테이블
  8. 계약 §2 쓰기 경계 표(프로세스 → 테이블) = 설계도 §2 「프로세스별 입력과 출력」 표의 쓰는 저장소 (P8 의 D6 은 D-12 — 사람 확인)
  9. `roll_genealogy` 의 네 끝 컬럼이 전부 실제 FK · 중복/재출하를 막는 유니크 인덱스 3개 (D-11)
 10. 롤 상태·추적 경로를 저장하는 컬럼/테이블이 없다 — 뷰 2개로 계산한다 (D-11 · db-schema.md §5)
 11. Job 키가 D2·D4·D5·D6·D7·D8 의 머리 테이블에 전부 있다 · `inspection` 은 (roll_id, job_id) 복합 FK (D-16 · §6)
 12. schema.sql 의 제약·인덱스·트리거 이름 = 실제 DB (컬럼만 같고 제약이 빠진 DB 를 잡는다)
 13. 테이블 수 = D1~D8 23 + SYS 7 = 30 · 테이블마다 PK

출력 행 형식: `G-04  항목  PASS|FAIL  실측`.  종료코드: 0 = PASS, 1 = FAIL.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import design_doc  # noqa: E402
from lcomfine.app import contracts  # noqa: E402
from lcomfine.db import conn  # noqa: E402

FIXED_NAMES = ["material_lot", "roll", "roll_genealogy", "shipment"]
STORES = [f"D{i}" for i in range(1, 9)]
DB_SCHEMA_MD = ROOT / "contracts" / "db-schema.md"
SCHEMA_SQL = ROOT / "src" / "lcomfine" / "db" / "schema.sql"


def design_stores() -> dict[str, str]:
    """설계도 §2 DFD 에 적힌 저장소 → {D1: 기준정보, …}."""
    sec = design_doc._section(design_doc.html(), "dfd", "lineage")
    return {m.group(1): m.group(2).strip() for m in re.finditer(r">(D\d) ([^<,]+)<", sec)}


def design_table_names() -> list[str]:
    """설계도 §3 계보 그림의 열 머리(테이블 이름)와 본문에 적힌 테이블 이름."""
    sec = design_doc._section(design_doc.html(), "lineage", "arch")
    heads = re.findall(r'<text class="t-s" x="\d+" y="44"[^>]*>(\w+)</text>', sec)
    body = re.findall(r"\b([a-z]+(?:_[a-z]+)+)\s*테이블", re.sub(r"<[^>]+>", " ", sec))
    return sorted(set(heads) | set(body))


def contract_store_table() -> dict[str, dict]:
    """계약 §1 「저장소 → 테이블」 표 → {D1: {name, tables}}."""
    text = DB_SCHEMA_MD.read_text(encoding="utf-8")
    sec = text[text.index("## 1."):text.index("## 2.")]
    out: dict[str, dict] = {}
    for ln in sec.splitlines():
        m = re.match(r"\|\s*(D\d|SYS)\s+([^|]+?)\s*\|[^|]*\|([^|]*)\|", ln)
        if m:
            out[m.group(1)] = {"name": m.group(2).strip(), "tables": re.findall(r"`(\w+)`", m.group(3))}
    return out


def contract_write_boundary() -> dict[str, list[str]]:
    """계약 §2 쓰기 경계 표 → {P1: [테이블…]}. 「쓸 수 있는 테이블」 칸의 백틱 이름과 `D1 9개` 꼴을 읽는다."""
    text = DB_SCHEMA_MD.read_text(encoding="utf-8")
    sec = text[text.index("## 2."):text.index("## 3.")]
    spec = contracts.db_tables()
    out: dict[str, list[str]] = {}
    for ln in sec.splitlines():
        m = re.match(r"\|\s*\**(P\d+)[^|]*\|[^|]*\|([^|]*)\|", ln)
        if not m:
            continue
        cell = m.group(2)
        tables = [t for t in re.findall(r"`(\w+)`", cell) if t in spec]
        for d in re.findall(r"\b(D\d) \d+개", cell):
            tables += [t.name for t in spec.values() if t.store == d]
        out[m.group(1)] = sorted(set(tables))
    return out


def schema_sql_names() -> dict[str, set[str]]:
    text = SCHEMA_SQL.read_text(encoding="utf-8")
    code = "\n".join(ln.split("--")[0] for ln in text.splitlines())
    return {
        "constraint": set(re.findall(r"^\s*constraint\s+(\w+)\s", code, re.M)),
        "index": set(re.findall(r"^create\s+(?:unique\s+)?index\s+(\w+)\s", code, re.M)),
        "trigger": set(re.findall(r"^create\s+trigger\s+(\w+)", code, re.M)),
        "view": set(re.findall(r"^create\s+view\s+(\w+)", code, re.M)),
    }


def main() -> int:
    rows: list[tuple[str, bool, str]] = []

    def add(item: str, ok: bool, actual: str) -> None:
        rows.append((item, bool(ok), actual))

    try:
        spec = contracts.db_tables()
    except Exception as exc:  # noqa: BLE001
        print(f"G-04  db-schema.md 로드  FAIL  {type(exc).__name__}: {exc}")
        return 1
    import gen_contracts

    live = gen_contracts.db_columns()

    # ── 1~5 (아키텍트 초판) ──
    per_store = {s: [t.name for t in spec.values() if t.store == s] for s in STORES}
    empty = [s for s, ts in per_store.items() if not ts]
    add("D1~D8 → 계약 테이블 (저장소마다 1개 이상)", not empty,
        " · ".join(f"{s} {len(ts)}" for s, ts in per_store.items()) + (f" · 빈 저장소 {empty}" if empty else ""))
    missing = [n for n in FIXED_NAMES if n not in live or n not in spec]
    add("material_lot · roll · roll_genealogy · shipment 이름 그대로", not missing,
        f"있음 {len(FIXED_NAMES) - len(missing)}/{len(FIXED_NAMES)}" + (f" · 없음 {missing}" if missing else ""))
    only_spec, only_live = sorted(set(spec) - set(live)), sorted(set(live) - set(spec))
    add("계약 테이블 = 실제 DB 테이블", not only_spec and not only_live,
        f"계약 {len(spec)} · DB {len(live)}" + (f" · 계약에만 {only_spec[:3]}" if only_spec else "")
        + (f" · DB 에만 {only_live[:3]}" if only_live else ""))
    diffs: list[str] = []
    n_spec = n_live = 0
    for name, t in spec.items():
        want = [(c.name, c.type, c.nullable) for c in t.columns]
        got = live.get(name, [])
        n_spec += len(want)
        n_live += len(got)
        if want != got:
            w, gt = {c[0]: c for c in want}, {c[0]: c for c in got}
            for col in sorted(set(w) | set(gt)):
                if w.get(col) != gt.get(col):
                    diffs.append(f"{name}.{col}")
    add("계약 컬럼 = 실제 DB 컬럼 (이름·타입·NULL·순서)", not diffs,
        f"계약 {n_spec} · DB {n_live} · 불일치 {len(diffs)}" + (f" {diffs[:3]}" if diffs else ""))
    try:
        text = gen_contracts.DB_SCHEMA_MD.read_text(encoding="utf-8")
        same = gen_contracts.replace_block(text, "tables", gen_contracts.render_tables(), gen_contracts.DB_SCHEMA_MD) == text
        add("db-schema.md §4 렌더본 = schema.sql", same, "일치" if same else "다르다 — `make contracts`")
    except SystemExit as exc:
        add("db-schema.md §4 렌더본 = schema.sql", False, str(exc)[:160])

    chk = conn.q1("""select pg_get_constraintdef(c.oid) as def from pg_constraint c
                      where c.conrelid = 'roll'::regclass and c.conname = 'roll_process_chk'""") if "roll" in live else None
    kinds = [k for k in ("인쇄", "후가공", "슬리팅") if chk and k in chk["def"]]
    add("roll 한 테이블 + 공정 구분 (인쇄·후가공·슬리팅)", len(kinds) == 3, f"process_type CHECK 값 {len(kinds)}/3")
    guards = conn.q("""select conname from pg_constraint where conrelid = 'roll_genealogy'::regclass and contype = 'c'""") \
        if "roll_genealogy" in live else []
    trg = conn.q("""select tgname from pg_trigger where tgrelid = 'roll_genealogy'::regclass and not tgisinternal""") \
        if "roll_genealogy" in live else []
    names = {g["conname"] for g in guards}
    need = {"roll_genealogy_parent_chk", "roll_genealogy_child_chk", "roll_genealogy_self_chk"}
    add("roll_genealogy 부모/자식 하나씩 + 순환 금지 제약", need <= names and bool(trg),
        f"CHECK {len(need & names)}/3 · 지킴이 트리거 {len(trg)} · 전체 CHECK {len(names)}")

    # ── 6. 설계도의 저장소 = 계약 §1 표 = §4 렌더본 ──
    d_stores, c_stores = design_stores(), contract_store_table()
    bad = [f"{d}: 설계도 `{d_stores.get(d)}` ≠ 계약 `{c_stores.get(d, {}).get('name')}`" for d in STORES
           if d_stores.get(d) != c_stores.get(d, {}).get("name")]
    bad += [f"{d}: §1 표 {sorted(c_stores.get(d, {}).get('tables', []))} ≠ §4 {sorted(per_store[d])}" for d in STORES
            if sorted(c_stores.get(d, {}).get("tables", [])) != sorted(per_store[d])]
    add("설계도 §2 저장소 D1~D8 (이름) = 계약 §1 표 · §1 표의 테이블 = §4 렌더본", sorted(d_stores) == STORES and not bad,
        f"설계도 저장소 {len(d_stores)}개 {' · '.join(f'{k} {v}' for k, v in sorted(d_stores.items()))}" + (f" — 어긋남 {bad[:2]}" if bad else ""))

    # ── 7. 설계도 §3 그림의 테이블 이름 ──
    d_names = design_table_names()
    lost = [n for n in d_names if n not in live]
    add("설계도 §3 그림에 적힌 테이블 이름이 실제 DB 에 그대로", bool(d_names) and not lost and set(d_names) == set(FIXED_NAMES),
        f"설계도에서 읽은 이름 {d_names} · DB 에 없는 것 {lost or 0}")

    # ── 8. 계약 §2 쓰기 경계 = 설계도 쓰는 저장소 ──
    procs, boundary = design_doc.processes(), contract_write_boundary()
    bad, d12 = [], ""
    for pcode, p in procs.items():
        got = sorted({spec[t].store for t in boundary.get(pcode, [])})
        want = sorted(p["writes"])
        if pcode == "P8" and got == sorted(set(want) | {"D6"}):
            d12 = " · P8 은 계약 D6+D8 / 설계도 D8 (D-12 — §3 그림을 따른 결정, 사람 확인)"
            continue
        if got != want:
            bad.append(f"{pcode}: 계약 {got or '없음'} ≠ 설계도 {want or '없음'}")
    add("계약 §2 쓰기 경계 (프로세스 → 테이블) = 설계도 §2 표의 쓰는 저장소", len(boundary) == len(procs) == 10 and not bad,
        f"프로세스 {len(boundary)}/{len(procs)} · 어긋남 {len(bad)}" + (f" {bad[:3]}" if bad else "") + d12)

    # ── 9. roll_genealogy 의 FK 4개 · 유니크 인덱스 3개 ──
    fks = {r["col"]: r["ref"] for r in conn.q(
        """select a.attname as col, c.confrelid::regclass::text as ref
             from pg_constraint c join pg_attribute a on a.attrelid = c.conrelid and a.attnum = c.conkey[1]
            where c.conrelid = 'roll_genealogy'::regclass and c.contype = 'f'""")} if "roll_genealogy" in live else {}
    want_fk = {"parent_material_lot_id": "material_lot", "parent_roll_id": "roll", "child_roll_id": "roll", "child_shipment_id": "shipment"}
    uq = {r["indexname"] for r in conn.q(
        "select indexname from pg_indexes where schemaname = 'public' and tablename = 'roll_genealogy' and indexdef like 'CREATE UNIQUE%%'")}
    want_uq = {"roll_genealogy_lot_roll_uq", "roll_genealogy_roll_roll_uq", "roll_genealogy_ship_once_uq"}
    add("roll_genealogy 의 부모·자식 네 컬럼 전부 FK · 중복/재출하 유니크 인덱스", fks == want_fk and want_uq <= uq,
        f"FK {sum(1 for k, v in want_fk.items() if fks.get(k) == v)}/4 · 유니크 인덱스 {len(want_uq & uq)}/3")

    # ── 10. 상태·경로를 저장하지 않는다 ──
    roll_cols = [c[0] for c in live.get("roll", [])]
    state_cols = [c for c in roll_cols if re.search(r"state|status|shipped|consumed", c)]
    path_tables = sorted(t for t in live if re.search(r"trace|path|cache|closure|ancest|descend|lineage|tree|stat_|summary|agg", t))
    views = {r["viewname"] for r in conn.q("select viewname from pg_views where schemaname = 'public'")}
    matviews = conn.q1("select count(*) as n from pg_matviews where schemaname = 'public'")["n"]
    view_cols = {v: [r["column_name"] for r in conn.q(
        "select column_name from information_schema.columns where table_schema = 'public' and table_name = %s order by ordinal_position", (v,))]
        for v in views}
    want_views = {"v_roll_state": ["roll_id", "roll_no", "process_type", "job_id", "state", "shipment_id"],
                  "v_material_lot_stock": ["material_lot_id", "lot_no", "item_id", "insp_status", "received_qty", "input_qty",
                                           "remaining_qty", "input_count"]}
    add("롤 상태·추적 경로·집계를 저장하지 않는다 — 뷰 2개로 계산", not state_cols and not path_tables and matviews == 0 and view_cols == want_views,
        f"roll 의 상태 컬럼 {state_cols or 0} · 경로/캐시/집계 테이블 {path_tables or 0} · 구체화 뷰 {matviews} · 뷰 {sorted(views)}"
        + ("" if view_cols == want_views else " · 뷰 컬럼이 계약 §5 와 다르다"))

    # ── 11. Job 키 ──
    heads = {"D2": "job", "D4": "color_record", "D5": "work_result", "D6": "roll", "D7": "inspection", "D8": "shipment"}
    no_job = [f"{d} {t}" for d, t in heads.items() if "job_id" not in [c[0] for c in live.get(t, [])]]
    comp = conn.q1("""select count(*) as n from pg_constraint
                       where conrelid = 'inspection'::regclass and contype = 'f' and array_length(conkey, 1) = 2
                         and confrelid = 'roll'::regclass""")["n"] if "inspection" in live else 0
    not_null = [t for t in heads.values() if any(c[0] == "job_id" and c[2] for c in live.get(t, []))]
    add("Job 키(job_id)가 D2·D4·D5·D6·D7·D8 의 머리 테이블에 NOT NULL 로 · inspection 은 (roll_id, job_id) 복합 FK",
        not no_job and comp == 1 and not not_null,
        f"job_id 있는 머리 테이블 {len(heads) - len(no_job)}/{len(heads)} · NULL 허용 {not_null or 0} · inspection→roll 복합 FK {comp}")

    # ── 12. schema.sql 의 제약·인덱스·트리거·뷰 = 실제 DB ──
    want = schema_sql_names()
    have = {
        "constraint": {r["conname"] for r in conn.q(
            "select conname from pg_constraint c join pg_namespace n on n.oid = c.connamespace where n.nspname = 'public'")},
        "index": {r["indexname"] for r in conn.q("select indexname from pg_indexes where schemaname = 'public'")},
        "trigger": {r["tgname"] for r in conn.q("select tgname from pg_trigger where not tgisinternal")},
        "view": views,
    }
    lost = {k: sorted(want[k] - have[k]) for k in want if want[k] - have[k]}
    add("schema.sql 의 제약·인덱스·트리거·뷰 이름이 실제 DB 에 전부 있다", not lost,
        " · ".join(f"{k} {len(want[k] & have[k])}/{len(want[k])}" for k in want) + (f" — DB 에 없는 것 {lost}" if lost else ""))

    # ── 13. 테이블 수 · PK ──
    n_d = sum(len(v) for v in per_store.values())
    n_sys = sum(1 for t in spec.values() if t.store == "SYS")
    n_ext = sum(1 for t in spec.values() if t.store == "EXT")        # 설계도 밖 확장 테이블 (D-418) — 설계도 수 30 밖에서 따로 센다
    no_pk = sorted(t for t in live if not conn.q1(
        "select 1 from pg_constraint where conrelid = %s::regclass and contype = 'p'", (t,)))
    add("테이블 수 = D1~D8 23 + SYS 7 = 30 · 테이블마다 PK", (n_d, n_sys, len(live) - n_ext) == (23, 7, 30) and not no_pk,
        f"D1~D8 {n_d} · SYS {n_sys} · DB {len(live)}{f' (확장 EXT {n_ext} 제외 시 {len(live) - n_ext})' if n_ext else ''} · PK 없는 테이블 {no_pk or 0}")

    w = max(len(i) for i, _, _ in rows)
    print("G-04 저장소 ↔ 계약 ↔ 실제 DB (tools/check_schema.py)")
    print("-" * 100)
    for item, ok, actual in rows:
        print(f"G-04  {item:<{w}}  {'PASS' if ok else 'FAIL'}  {actual}")
    print("-" * 100)
    failed = sum(1 for _, ok, _ in rows if not ok)
    print(f"G-04 판정: {'PASS' if failed == 0 else 'FAIL'} (검사 {len(rows)} · 실패 {failed})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
