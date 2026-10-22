#!/usr/bin/env python
"""계약 문서의 렌더본 구간을 원본에서 다시 찍는다 (decisions.md D-08) — `make contracts`.

  contracts/db-schema.md  §2.2 ← contracts/function-list.md (화면 → 쓰는 테이블 · `writes`)
  contracts/db-schema.md  §4   ← src/lcomfine/db/schema.sql (테이블·영역·컬럼 설명) + 실제 DB(타입·NULL) (`tables`)
  contracts/db-schema.md  §5   ← schema.sql 의 `-- @view` 태그 + 실제 DB 의 뷰 컬럼 (`views`)
  contracts/screen-map.md §1  ← src/lcomfine/app/nav.py (DB 없이 `--only screens` 로 이것만 찍을 수 있다)

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

#: 영역 = 테이블을 쓰는 대메뉴 코드(nav.py) 또는 SYS — 스펙 §4.1 표의 순서. TRK · LOT · PRP 는 테이블이 없다(읽기만 한다)
AREAS = ["BAS", "STD", "WO", "MAT", "PRD", "INS", "QC", "INV", "SHP", "COL", "RPT", "DOC", "HOME", "SYS"]
TABLE_TAG_RE = re.compile(r"^-- @table (\w+) \| (" + "|".join(AREAS) + r") \| (.+)$")
VIEW_TAG_RE = re.compile(r"^-- @view (\w+) \| (.+)$")
COLUMN_RE = re.compile(r"^\s{4}(\w+)\s+.+?--\s*(.+)$")


def area_name(code: str) -> str:
    return "시스템" if code == "SYS" else nav.menu(code).name


def parse_schema_sql() -> list[dict]:
    """schema.sql → [{name, store(=영역), desc, columns: [(이름, 설명)]}] (파일에 적힌 순서)."""
    tables: list[dict] = []
    cur: dict | None = None
    inside = False
    for ln in SCHEMA_SQL.read_text(encoding="utf-8").splitlines():
        if ln.startswith("-- @table ") and not TABLE_TAG_RE.match(ln):
            raise SystemExit(f"schema.sql: 영역 코드가 {' · '.join(AREAS)} 가 아니다 — {ln}")
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
    for store in AREAS:
        mine = [t for t in spec if t["store"] == store]
        out.append(f"#### {store} {area_name(store)} — 테이블 {len(mine)}")
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


def parse_views() -> list[tuple[str, str]]:
    """schema.sql 의 `-- @view 이름 | 설명` → [(이름, 설명)]. 태그 다음 줄이 그 이름의 create view 여야 한다."""
    lines = SCHEMA_SQL.read_text(encoding="utf-8").splitlines()
    out: list[tuple[str, str]] = []
    for i, ln in enumerate(lines):
        m = VIEW_TAG_RE.match(ln)
        if m:
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            if not nxt.startswith(f"create view {m.group(1)} "):
                raise SystemExit(f"schema.sql: `-- @view {m.group(1)}` 다음 줄이 그 create view 가 아니다 — {nxt}")
            out.append((m.group(1), m.group(2).strip()))
    untagged = {v for v in re.findall(r"^create view (\w+)", "\n".join(lines), re.M)} - {n for n, _ in out}
    if untagged:
        raise SystemExit(f"schema.sql: `-- @view` 태그가 없는 뷰 {sorted(untagged)}")
    return out


def render_views() -> str:
    """뷰 → `| 뷰 | 컬럼 | 설명 |` (컬럼은 실제 DB 순서)."""
    live: dict[str, list[str]] = {}
    for r in conn.q("""select table_name as v, column_name as c from information_schema.columns
                        where table_schema = 'public'
                          and table_name in (select table_name from information_schema.views where table_schema = 'public')
                        order by table_name, ordinal_position"""):
        live.setdefault(r["v"], []).append(r["c"])
    spec = parse_views()
    if {n for n, _ in spec} != set(live):
        raise SystemExit(f"schema.sql 과 DB 의 뷰가 다르다 — sql {sorted(n for n, _ in spec)} · DB {sorted(live)}. `make db-schema` 를 먼저 돌린다.")
    out = ["| 뷰 | 컬럼 | 설명 |", "|---|---|---|"]
    for name, desc in spec:
        out.append(f"| `{name}` | {' '.join(f'`{c}`' for c in live[name])} | {desc} |")
    return "\n".join(out)


def render_writes() -> str:
    """function-list.md → 화면마다 `| 화면 ID | 화면 | 영역 | 쓰기 기능 | 쓰는 테이블 |` (nav 순서)."""
    out = ["| 화면 ID | 화면 | 대메뉴 | 쓰기 기능 | 쓰는 테이블 |", "|---|---|---|---|---|"]
    for s in nav.SCREENS:
        fns = [f for f in contracts.functions_of(s.screen_id) if f.is_write]
        if not fns:
            continue
        tables = list(dict.fromkeys(t for f in fns for t in f.tables))
        out.append(f"| {s.screen_id} | {s.name} | {s.menu_code} | {' '.join(f.id for f in fns)} | "
                   f"{' '.join(f'`{t}`' for t in tables)} |")
    return "\n".join(out)


def render_screens() -> str:
    """화면 66 → `ID | 화면 | 유형 | 경로 | 대메뉴 | 묶음 | 담당` (nav.py 순서 = 정본 순서)."""
    bundles = {k: name for k, name, _ in nav.BUNDLES}
    out = ["| ID | 화면 | 유형 | 경로 | 대메뉴 | 묶음 | 담당 |", "|---|---|---|---|---|---|---|"]
    for s in nav.SCREENS:
        out.append(f"| {s.screen_id} | {s.name} | {s.kind} | `{s.path}` | {s.menu_code} {s.menu} | {bundles[s.bundle]} | {s.owner} |")
    return "\n".join(out)


def replace_block(text: str, key: str, body: str, path: Path) -> str:
    begin, end = f"<!-- BEGIN:generated {key} -->", f"<!-- END:generated {key} -->"
    if text.count(begin) != 1 or text.count(end) != 1:
        raise SystemExit(f"{path.name}: `{begin}` … `{end}` 구간이 정확히 하나 있어야 한다")
    a, b = text.index(begin) + len(begin), text.index(end)
    return text[:a] + "\n" + body + "\n" + text[b:]


def main(check: bool = False, only: str | None = None) -> int:
    jobs = [(DB_SCHEMA_MD, "writes", render_writes), (DB_SCHEMA_MD, "tables", render_tables),
            (DB_SCHEMA_MD, "views", render_views), (SCREEN_MAP_MD, "screens", render_screens)]
    if only:
        jobs = [j for j in jobs if j[1] == only]
    stale: list[str] = []
    for path, key, fn in jobs:
        if not path.exists():
            print(f"FAIL {path.relative_to(ROOT)} 없음")
            return 1
        old = path.read_text(encoding="utf-8")
        new = replace_block(old, key, fn(), path)
        if new != old:
            stale.append(f"{path.relative_to(ROOT)} ({key})")
            if not check:
                path.write_text(new, encoding="utf-8")
    if check:
        print("렌더본 = 원본" if not stale else f"렌더본이 원본과 다르다: {', '.join(stale)} — `make contracts` 로 다시 찍는다")
        return 1 if stale else 0
    print(f"다시 찍음: {', '.join(stale) if stale else '변경 없음'}")
    return 0


if __name__ == "__main__":
    _only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None   # --only screens · tables · views · writes
    sys.exit(main("--check" in sys.argv, _only))
