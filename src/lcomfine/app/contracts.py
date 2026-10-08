"""계약 로더 — `contracts/*.md` 의 표를 기계가 읽는 형태로 준다 (decisions.md D-08).

직전 사업의 `design.py`(design.json 로더) 자리다. 여기에는 정본 JSON 이 없으므로 **계약 문서의 표가 원본**이다.

    functions()            contracts/function-list.md §2 의 100줄 → Function 목록
    function("F-BAS-01")   한 줄
    functions_of("BAS-01") 그 중메뉴 화면의 기능들 (placeholder 화면·우측 계약 패널이 쓴다)
    db_tables()            contracts/db-schema.md §4 의 테이블·컬럼 (tools/check_schema.py 가 실제 DB 와 대조)

표가 깨졌거나 수가 안 맞으면 **import 시점에 실패한다** — 조용히 넘어가지 않는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from . import nav

ROOT = Path(__file__).resolve().parents[3]
CONTRACTS_DIR = ROOT / "contracts"
FUNCTION_LIST = CONTRACTS_DIR / "function-list.md"
EXT_FUNCTION_LIST = CONTRACTS_DIR / "extension-list.md"     # 설계도 밖 확장 (D-418) — 수를 세는 게이트 밖
DB_SCHEMA = CONTRACTS_DIR / "db-schema.md"

N_SCREEN_FUNCTIONS, N_BATCH_FUNCTIONS = 94, 6
EXT_PROCESS = "확장"                                         # 확장 기능의 프로세스 칸 — P1~P10 밖

WRITE_KINDS: frozenset[str] = frozenset({"등록", "수정", "삭제", "승인", "스캔"})
READ_KINDS: frozenset[str] = frozenset({"조회", "출력"})
BATCH_KIND = "배치"
PROCESSES: frozenset[str] = frozenset({f"P{i}" for i in range(1, 11)} | {"공통", "배치"})
SCOPE_GENERAL = "일반"
READ_ROLE_LABEL = "조회 이상"

FUNCTION_HEADER = ["ID", "대메뉴", "중메뉴", "기능명", "유형", "프로세스", "쓰는 저장소", "쓰는 테이블", "채널",
                   "권한", "범위", "API", "담당", "계약"]


# ── 마크다운 표 ─────────────────────────────────────────────────────────
def md_tables(text: str) -> list[tuple[list[str], list[list[str]]]]:
    """문서 안의 표를 전부 (머리행, 본문 행들) 로 돌려준다. 칸 안의 백틱은 벗긴다."""
    tables: list[tuple[list[str], list[list[str]]]] = []
    cur: list[list[str]] = []
    for ln in text.splitlines() + [""]:
        if ln.startswith("|"):
            cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            if set("".join(cells)) <= set("-: "):
                continue   # 구분선
            cur.append([_unquote(c) for c in cells])
        elif cur:
            tables.append((cur[0], cur[1:]))
            cur = []
    return tables


def _unquote(cell: str) -> str:
    """칸 전체가 백틱 한 쌍으로 싸여 있을 때만 벗긴다 (문장 속의 백틱은 그대로 둔다)."""
    if len(cell) >= 2 and cell.startswith("`") and cell.endswith("`") and cell.count("`") == 2:
        return cell[1:-1].strip()
    return cell


def md_section(text: str, head_prefix: str) -> str:
    """`## <head_prefix>…` 로 시작하는 절의 본문(다음 `## ` 전까지)."""
    m = re.search(rf"^## {re.escape(head_prefix)}.*?$(.*?)(?=^## |\Z)", text, re.S | re.M)
    return m.group(1) if m else ""


# ── 기능 100줄 ──────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Function:
    id: str                    # F-BAS-01 · B-MIG-01
    menu: str                  # 대메뉴명 (배치는 '(배치) 데이터 이관')
    screen_name: str           # 중메뉴명 (배치는 '-')
    name: str                  # 기능명
    kind: str                  # 등록 · 수정 · 삭제 · 승인 · 스캔 · 조회 · 출력 · 배치
    process: str               # P1~P10 · 공통 · 배치
    stores: tuple[str, ...]    # 쓰는 저장소 (읽기 기능은 빈 튜플)
    tables: tuple[str, ...]    # 쓰는 테이블
    channels: tuple[str, ...]
    roles: tuple[str, ...]     # 입력할 수 있는 역할명 (읽기 기능은 빈 튜플 = '조회 이상')
    scope: str                 # 일반 · 입고검사 · 승인 (읽기·배치는 '-')
    api: str                   # 'POST /bas/items' · 'cli validate'
    owner: str
    text: str                  # 계약 문장

    @property
    def is_batch(self) -> bool:
        return self.kind == BATCH_KIND

    @property
    def is_write(self) -> bool:
        return self.kind in WRITE_KINDS

    @property
    def method(self) -> str:
        return self.api.split(" ", 1)[0]

    @property
    def path(self) -> str:
        return self.api.split(" ", 1)[1]

    @property
    def menu_code(self) -> str:
        return "" if self.is_batch else nav.menu_by_name(self.menu).code

    @property
    def screen_id(self) -> str:
        return "" if self.is_batch else nav.screen_by_names(self.menu, self.screen_name).screen_id


def _split(cell: str, sep: str = ",") -> tuple[str, ...]:
    return tuple(p.strip() for p in cell.split(sep) if p.strip() and p.strip() != "-")


def _parse_functions(text: str, *, ext: bool = False) -> tuple[Function, ...]:
    source = EXT_FUNCTION_LIST.name if ext else FUNCTION_LIST.name
    found = [rows for head, rows in md_tables(md_section(text, "2.")) if head == FUNCTION_HEADER]
    if len(found) != 1:
        raise RuntimeError(f"{source} §2 에 머리행이 {FUNCTION_HEADER} 인 표가 정확히 하나 있어야 한다 — 실제 {len(found)}")
    out: list[Function] = []
    for r in found[0]:
        if len(r) != len(FUNCTION_HEADER):
            raise RuntimeError(f"{source}: 칸 수가 {len(FUNCTION_HEADER)} 이 아닌 행 — {r[:2]}")
        fid, menu, sub, name, kind, proc, stores, tables, channels, roles, scope, api, owner, body = r
        out.append(Function(
            id=fid, menu=menu, screen_name=sub, name=name, kind=kind, process=proc, stores=_split(stores),
            tables=_split(tables), channels=_split(channels),
            roles=() if roles == READ_ROLE_LABEL else _split(roles, "·"),
            scope=scope, api=api, owner=owner, text=body,
        ))
    _validate(out, ext=ext)
    return tuple(out)


def _validate(fns: list[Function], *, ext: bool = False) -> None:
    """설계도 목록(`ext=False`)은 94 + 6 을 꼭 채워야 하고, 확장 목록(`ext=True`, D-418)은 수가 정해져 있지 않되
    대메뉴가 `nav.EXT_MENUS` 의 것이어야 하고 ID 는 `X-<코드>-nn` 이다. 나머지 규칙은 같다."""
    source = EXT_FUNCTION_LIST.name if ext else FUNCTION_LIST.name
    menus = nav.EXT_MENUS if ext else nav.MENUS
    id_prefix = "X" if ext else "F"
    processes = {EXT_PROCESS} if ext else PROCESSES
    errs: list[str] = []
    ids = [f.id for f in fns]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        errs.append(f"기능 ID 중복 {dup}")
    screen_fns = [f for f in fns if not f.is_batch]
    batch_fns = [f for f in fns if f.is_batch]
    if ext:
        if batch_fns:
            errs.append(f"확장 목록에는 배치가 없다 — {[f.id for f in batch_fns]}")
    elif len(screen_fns) != N_SCREEN_FUNCTIONS or len(batch_fns) != N_BATCH_FUNCTIONS:
        errs.append(f"화면 기능 {N_SCREEN_FUNCTIONS} + 배치 {N_BATCH_FUNCTIONS} 이어야 한다 — 실제 {len(screen_fns)} + {len(batch_fns)}")
    for f in fns:
        if f.kind not in WRITE_KINDS | READ_KINDS | {BATCH_KIND}:
            errs.append(f"{f.id}: 유형 {f.kind!r}")
        if f.process not in processes:
            errs.append(f"{f.id}: 프로세스 {f.process!r}")
        if " " not in f.api:
            errs.append(f"{f.id}: API 는 '<메서드> <경로>' 형식 — {f.api!r}")
        if f.is_batch:
            if not re.fullmatch(r"B-MIG-\d{2}", f.id):
                errs.append(f"{f.id}: 배치 ID 형식 B-MIG-nn")
            continue
        try:
            m = nav.menu_by_name(f.menu)
            s = nav.screen_by_names(f.menu, f.screen_name)
        except KeyError as exc:
            errs.append(f"{f.id}: {exc}")
            continue
        if m.ext != ext:
            errs.append(f"{f.id}: 대메뉴 {f.menu} 는 {'확장' if m.ext else '설계도'} 대메뉴라 이 목록({source})에 올 수 없다")
        if not re.fullmatch(rf"{id_prefix}-{m.code}-\d{{2}}", f.id):
            errs.append(f"{f.id}: ID 는 {id_prefix}-{m.code}-nn 이어야 한다")
        if f.owner != m.owner:
            errs.append(f"{f.id}: 담당 {f.owner} ≠ nav {m.owner}")
        if f.channels != s.channels:
            errs.append(f"{f.id}: 채널 {f.channels} ≠ nav {s.channels}")
        if not f.path.startswith(f"/{m.module}/"):
            errs.append(f"{f.id}: 경로 {f.path} 가 /{m.module}/ 로 시작하지 않는다")
        if f.is_write and (not f.roles or f.scope == "-" or not f.stores):
            errs.append(f"{f.id}: 쓰기 기능은 권한·범위·쓰는 저장소가 있어야 한다")
        if not f.is_write and (f.roles or f.scope != "-" or f.stores):
            errs.append(f"{f.id}: 읽기 기능은 권한 '{READ_ROLE_LABEL}' · 범위 '-' · 쓰는 저장소 '-'")
    for m in menus:
        n = sum(1 for f in screen_fns if f.menu == m.name)
        if n != m.fn_count:
            errs.append(f"{m.name}: 기능 {n} ≠ {'nav' if ext else '설계도'} {m.fn_count}")
        for s in m.screens:
            if not any(f.menu == m.name and f.screen_name == s.name for f in screen_fns):
                errs.append(f"{s.screen_id} {s.name}: 기능이 한 줄도 없다")
    apis = [f.api for f in fns]
    dup_api = sorted({a for a in apis if apis.count(a) > 1})
    if dup_api:
        errs.append(f"API 중복 {dup_api}")
    if ext:                                                            # 설계도 목록과도 ID·API 가 겹치면 안 된다
        base = functions()
        clash = sorted({f.id for f in fns} & {f.id for f in base}) + sorted({f.api for f in fns} & {f.api for f in base})
        if clash:
            errs.append(f"설계도 목록과 겹침 {clash}")
    if errs:
        raise RuntimeError(f"{source} 검증 실패 {len(errs)}건:\n  - " + "\n  - ".join(errs))


@lru_cache(maxsize=1)
def functions() -> tuple[Function, ...]:
    """설계도의 기능 100줄 (화면 94 + 배치 6). 게이트가 세는 것은 이것뿐이다."""
    if not FUNCTION_LIST.exists():
        raise RuntimeError(f"계약 없음: {FUNCTION_LIST}")
    return _parse_functions(FUNCTION_LIST.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def ext_functions() -> tuple[Function, ...]:
    """확장(설계도 밖, D-418) 기능 — `contracts/extension-list.md`. 파일이 없으면 빈 튜플(확장이 없는 상태)."""
    if not EXT_FUNCTION_LIST.exists():
        if nav.EXT_MENUS:
            raise RuntimeError(f"확장 대메뉴 {[m.code for m in nav.EXT_MENUS]} 가 있는데 계약이 없다: {EXT_FUNCTION_LIST}")
        return ()
    return _parse_functions(EXT_FUNCTION_LIST.read_text(encoding="utf-8"), ext=True)


def all_functions() -> tuple[Function, ...]:
    """설계도 100줄 + 확장. 화면·권한 판정은 이것을 보고, 수를 세는 곳은 `functions()` 를 본다."""
    return functions() + ext_functions()


def function(function_id: str) -> Function:
    for f in all_functions():
        if f.id == function_id:
            return f
    raise KeyError(f"function-list.md · extension-list.md 에 없는 기능 ID: {function_id}")


def functions_of(screen_id: str) -> list[Function]:
    return [f for f in all_functions() if not f.is_batch and f.screen_id == screen_id]


def functions_of_menu(menu_code: str) -> list[Function]:
    return [f for f in all_functions() if not f.is_batch and f.menu_code == menu_code]


def batch_functions() -> list[Function]:
    return [f for f in functions() if f.is_batch]


# ── 테이블 계약 (db-schema.md §4) ───────────────────────────────────────
TABLE_HEAD_RE = re.compile(r"^### `(\w+)` — (D[1-8]|SYS|EXT) · (.*)$", re.M)   # EXT = 설계도 밖 확장 테이블 (D-418)
COLUMN_HEADER = ["컬럼", "타입", "NULL", "설명"]


@dataclass(frozen=True)
class Column:
    name: str
    type: str
    nullable: bool
    desc: str


@dataclass(frozen=True)
class Table:
    name: str
    store: str                 # D1~D8 · SYS
    desc: str
    columns: tuple[Column, ...]


@lru_cache(maxsize=1)
def db_tables() -> dict[str, Table]:
    """`contracts/db-schema.md` §4 의 `### \\`테이블\\` — 저장소 · 설명` + 컬럼 표."""
    if not DB_SCHEMA.exists():
        raise RuntimeError(f"계약 없음: {DB_SCHEMA}")
    text = DB_SCHEMA.read_text(encoding="utf-8")
    heads = list(TABLE_HEAD_RE.finditer(text))
    out: dict[str, Table] = {}
    for i, m in enumerate(heads):
        body = text[m.end(): heads[i + 1].start() if i + 1 < len(heads) else len(text)]
        tables = [rows for head, rows in md_tables(body) if head == COLUMN_HEADER]
        if not tables:
            raise RuntimeError(f"{DB_SCHEMA.name}: `{m.group(1)}` 아래에 컬럼 표가 없다")
        cols = tuple(Column(name=r[0], type=r[1], nullable=(r[2] == "Y"), desc=r[3]) for r in tables[0])
        out[m.group(1)] = Table(name=m.group(1), store=m.group(2), desc=m.group(3).strip(), columns=cols)
    return out


def tables_of_store(store: str) -> list[Table]:
    return [t for t in db_tables().values() if t.store == store]
