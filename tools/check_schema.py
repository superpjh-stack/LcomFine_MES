#!/usr/bin/env python
"""G-04 저장소 검사 — `make check-schema`. (아키텍트 초판 · QA2 가 이어받아 넓힌다, decisions.md D-24)

  1. D1~D8 이 `contracts/db-schema.md` 의 테이블에 빠짐없이 대응하는가
  2. `material_lot` · `roll` · `roll_genealogy` · `shipment` 가 이 이름 그대로 실제 DB 에 있는가
  3. 계약의 테이블·컬럼(이름·타입·NULL) = 실제 DB
  4. 렌더본(db-schema.md §4)이 원본(schema.sql)과 어긋나지 않았는가
  5. `roll` 이 한 테이블에 공정 구분으로 · `roll_genealogy` 에 순환을 막는 제약이 있는가

출력 행 형식: `G-04  항목  PASS|FAIL  실측`.  종료코드: 0 = PASS, 1 = FAIL.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from lcomfine.app import contracts  # noqa: E402
from lcomfine.db import conn  # noqa: E402

FIXED_NAMES = ["material_lot", "roll", "roll_genealogy", "shipment"]
STORES = [f"D{i}" for i in range(1, 9)]


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
