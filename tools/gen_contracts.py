#!/usr/bin/env python
"""계약 문서의 렌더본 구간을 원본에서 다시 찍는다 (decisions.md D-08) — `make contracts`.

  contracts/db-schema.md  §4  ← src/lcomfine/db/schema.sql (테이블·저장소·컬럼 설명) + 실제 DB(타입·NULL)
  contracts/screen-map.md §1  ← src/lcomfine/app/nav.py

문서의 `<!-- BEGIN:generated … -->` 와 `<!-- END:generated … -->` 사이만 바꾼다. 그 밖의 글은 사람이 쓴다.
`--check` 를 주면 파일을 고치지 않고, 다시 찍었을 때 달라지는지만 본다(달라지면 종료코드 1) —
`check_schema.py` · `check_trace.py` 가 "원본과 렌더본이 어긋났는가" 를 이것으로 잰다.

DB 에 스키마가 올라가 있어야 한다(`make db-schema`). schema.sql 의 컬럼과 DB 의 컬럼이 다르면 실패한다.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lcomfine.app import contracts, nav  # noqa: E402
from lcomfine.db import conn  # noqa: E402

SCHEMA_SQL = ROOT / "src" / "lcomfine" / "db" / "schema.sql"
DB_SCHEMA_MD = ROOT / "contracts" / "db-schema.md"
SCREEN_MAP_MD = ROOT / "contracts" / "screen-map.md"

TABLE_TAG_RE = re.compile(r"^-- @table (\w+) \| (D[1-8]|SYS|EXT) \| (.+)$")   # EXT = 설계도 밖 확장 (D-418)
COLUMN_RE = re.compile(r"^\s{4}(\w+)\s+.+?--\s*(.+)$")
STORES = ["D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8", "SYS", "EXT"]
STORE_NAMES = {"D1": "기준정보", "D2": "작업지시", "D3": "원재료 LOT", "D4": "조색 기록", "D5": "생산 실적",
               "D6": "Roll·계보", "D7": "품질 검사", "D8": "출하", "SYS": "공통(시스템)", "EXT": "확장(설계도 밖 · D-418)"}


def parse_schema_sql() -> list[dict]:
    """schema.sql → [{name, store, desc, columns: [(이름, 설명)]}] (파일에 적힌 순서)."""
    tables: list[dict] = []
    cur: dict | None = None
    inside = False
    for ln in SCHEMA_SQL.read_text(encoding="utf-8").splitlines():
        m = TABLE_TAG_RE.match(ln)
        if m:
            cur = {"name": m.group(1), "store": m.group(2), "desc": m.group(3).strip(), "columns": []}
            tables.append(cur)
            inside = False
            continue
        if cur is None:
            continue
        if ln.startswith("create table "):
            if ln.split()[2] != cur["name"]:
                raise SystemExit(f"schema.sql: `-- @table {cur['name']}` 다음의 create table 이름이 다르다 — {ln}")
            inside = True
            continue
        if inside and ln.startswith(");"):
            inside, cur = False, None
            continue
        if inside:
            if ln.strip().startswith("constraint ") or not ln.strip():
                continue
            cm = COLUMN_RE.match(ln)
            if cm:
                cur["columns"].append((cm.group(1), cm.group(2).strip()))
            elif cur["columns"] and "--" not in ln:
                continue   # 여러 줄 제약의 이어지는 줄
            else:
                raise SystemExit(f"schema.sql: `{cur['name']}` 의 컬럼 줄에 `-- 설명` 이 없다 — {ln.strip()}")
    return tables


def db_columns() -> dict[str, list[tuple[str, str, bool]]]:
    """실제 DB → {테이블: [(컬럼, 타입, NULL 허용)]}. 타입은 `format_type` 그대로."""
    rows = conn.q(
        """select c.relname as t, a.attname as col, format_type(a.atttypid, a.atttypmod) as typ, not a.attnotnull as nullable
             from pg_attribute a
             join pg_class c on c.oid = a.attrelid
             join pg_namespace n on n.oid = c.relnamespace
            where n.nspname = 'public' and c.relkind = 'r' and a.attnum > 0 and not a.attisdropped
            order by c.relname, a.attnum""")
    out: dict[str, list[tuple[str, str, bool]]] = {}
    for r in rows:
        out.setdefault(r["t"], []).append((r["col"], r["typ"], r["nullable"]))
    return out


def render_tables() -> str:
    spec = parse_schema_sql()
    live = db_columns()
    names = [t["name"] for t in spec]
    if set(names) != set(live):
        raise SystemExit(f"schema.sql 과 DB 의 테이블이 다르다 — sql 에만 {sorted(set(names) - set(live))} · "
                         f"DB 에만 {sorted(set(live) - set(names))}. `make db-schema` 를 먼저 돌린다.")
    out: list[str] = []
    for store in STORES:
        mine = [t for t in spec if t["store"] == store]
        out.append(f"#### {store} {STORE_NAMES[store]} — 테이블 {len(mine)}")
        out.append("")
        for t in mine:
            cols = live[t["name"]]
            if [c for c, _ in t["columns"]] != [c for c, _, _ in cols]:
                raise SystemExit(f"`{t['name']}`: schema.sql 의 컬럼과 DB 의 컬럼이 다르다. `make db-schema` 를 먼저 돌린다.")
            desc = dict(t["columns"])
            out.append(f"### `{t['name']}` — {store} · {t['desc']}")
            out.append("")
            out.append("| 컬럼 | 타입 | NULL | 설명 |")
            out.append("|---|---|---|---|")
            for col, typ, nullable in cols:
                out.append(f"| {col} | {typ} | {'Y' if nullable else 'N'} | {desc[col]} |")
            out.append("")
    return "\n".join(out).rstrip("\n")


def render_screens() -> str:
    fns = contracts.functions()
    out = ["| # | 화면 ID | 묶음 | 대메뉴 | 중메뉴 | 경로 | 모듈 | 담당 | 채널 | 기능 |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for i, s in enumerate(nav.SCREENS, start=1):
        ids = [f.id for f in fns if not f.is_batch and f.screen_id == s.screen_id]
        span = ids[0] if len(ids) == 1 else f"{ids[0]} ~ {ids[-1].rsplit('-', 1)[1]}"
        out.append(f"| {i} | {s.screen_id} | {s.group} | {s.menu} | {s.name} | `{s.path}` | {s.module} | {s.owner} | "
                   f"{', '.join(s.channels)} | {span} ({len(ids)}) |")
    return "\n".join(out)


def replace_block(text: str, key: str, body: str, path: Path) -> str:
    begin, end = f"<!-- BEGIN:generated {key} -->", f"<!-- END:generated {key} -->"
    if text.count(begin) != 1 or text.count(end) != 1:
        raise SystemExit(f"{path.name}: `{begin}` … `{end}` 구간이 정확히 하나 있어야 한다")
    a, b = text.index(begin) + len(begin), text.index(end)
    return text[:a] + "\n" + body + "\n" + text[b:]


def main(check: bool = False) -> int:
    jobs = [(DB_SCHEMA_MD, "tables", render_tables), (SCREEN_MAP_MD, "screens", render_screens)]
    stale: list[str] = []
    for path, key, fn in jobs:
        if not path.exists():
            print(f"FAIL {path.relative_to(ROOT)} 없음")
            return 1
        old = path.read_text(encoding="utf-8")
        new = replace_block(old, key, fn(), path)
        if new != old:
            stale.append(str(path.relative_to(ROOT)))
            if not check:
                path.write_text(new, encoding="utf-8")
    if check:
        print("렌더본 = 원본" if not stale else f"렌더본이 원본과 다르다: {', '.join(stale)} — `make contracts` 로 다시 찍는다")
        return 1 if stale else 0
    print(f"다시 찍음: {', '.join(stale) if stale else '변경 없음'}")
    return 0


if __name__ == "__main__":
    sys.exit(main("--check" in sys.argv))
