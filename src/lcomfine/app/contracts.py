"""계약 로더 — `contracts/*.md` 의 표를 기계가 읽는 형태로 준다 (D-508).

**계약 문서의 표가 원본**이다. 앱은 정본이나 `ia.json` 을 읽지 않는다.

    functions()                 contracts/function-list.md §2 → Function 목록
    function("F-WO-011")        한 줄
    functions_of("WO-010")      그 화면의 기능들 (placeholder 화면 · 우측 계약 패널이 쓴다)
    functions_of_menu("WO")     그 대메뉴의 기능들
    write_functions()           쓰기 기능만
    permission_cells()          contracts/permission-matrix.md → (화면 ID, 부서 코드, W|R) 260
    db_tables()                 contracts/db-schema.md 의 테이블 · 컬럼 (tools/check_schema.py 가 실제 DB 와 대조)

표가 깨졌거나 규칙이 안 맞으면 **처음 부를 때 실패한다** — 조용히 넘어가지 않는다.
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
PERMISSION_MATRIX = CONTRACTS_DIR / "permission-matrix.md"
DB_SCHEMA = CONTRACTS_DIR / "db-schema.md"

WRITE_KINDS: frozenset[str] = frozenset({"등록", "수정", "삭제", "처리", "저장", "진입"})
READ_KINDS: frozenset[str] = frozenset({"조회", "출력"})
READ_ROLE_LABEL = "R 이상"
EXCEPTION_ROLE_LABEL = "R 이상(권한 예외)"   # 정본 칸에 W 가 없는 화면의 쓰기 기능 — 화면 R 이상이 실행

#: 부서 이름 → 코드 (정본 순서). 앱은 ia.json 을 읽지 않으므로 리터럴이다 — 게이트가 정본과 대조한다.
ROLE_CODES: dict[str, str] = {
    "영업부": "SL", "생산부": "PR", "출하실": "SH", "디자인·개발실": "DS",
    "회계부": "AC", "전략부": "ST", "경영진": "EX", "전산 관리자": "ADM",
}
LEVELS: frozenset[str] = frozenset({"W", "R"})
NO_LEVEL = "·"

FUNCTION_HEADER = ["ID", "대메뉴", "화면 ID", "기능명", "유형", "쓰는 테이블", "권한", "API", "담당", "계약"]
PERMISSION_HEADER = ["화면 ID", "화면", *ROLE_CODES]

#: 규칙 A (D-508) — 화면 유형(nav.Screen.kind = 정본 type) → 전개 기능 유형, 순번 순서
EXPANSION: dict[str, tuple[str, ...]] = {
    "조회": ("조회",), "리포트": ("조회",), "출력": ("조회",),
    "등록": ("등록", "수정", "조회"),
    "목록·등록": ("등록", "수정", "삭제", "조회"),
    "등록·출력": ("등록", "수정", "조회", "출력"),
    "처리": ("처리", "조회"),
    "설정": ("저장", "조회"),
    "외부 연계(SSO)": ("진입", "조회"),
}
NO_EDIT_MARK = "수정 없음"          # 정본 logic 이 수정을 막는 등록 화면 — 수정 기능을 전개하지 않는다
KIND_EXCEPTION_MARK = "유형 예외"   # 정본 type 밖 쓰기 기능 하나를 뒤에 더한다 (RPT-130 질의 실행)
ROLE_EXCEPTION_MARK = "권한 예외"   # 정본 칸에 W 가 없는 화면의 쓰기 기능 — 권한 칸 EXCEPTION_ROLE_LABEL · 화면 R 이상이 실행

ID_RE = re.compile(r"F-([A-Z]+)-(\d{2})(\d)")
API_RE = re.compile(r"(GET|POST) (/\S*)")


# ── 마크다운 표 ─────────────────────────────────────────────────────────
def md_tables(text: str) -> list[tuple[list[str], list[list[str]]]]:
    """문서 안의 표를 전부 (머리행, 본문 행들) 로 돌려준다. 칸 전체를 싼 백틱은 벗긴다."""
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


def _split(cell: str, sep: str) -> tuple[str, ...]:
    return tuple(p.strip() for p in cell.split(sep) if p.strip() and p.strip() != "-")


def _role_codes(cell: str) -> tuple[str, ...]:
    """`영업부·디자인·개발실·전산 관리자` → ('SL', 'DS', 'ADM'). 부서 이름 안에도 `·` 가 있어(디자인·개발실)
    단순히 나누지 않고 아는 이름을 긴 것부터 앞에서 떼어 낸다."""
    rest, out = cell.strip(), []
    names = sorted(ROLE_CODES, key=len, reverse=True)
    while rest:
        hit = next((n for n in names if rest == n or rest.startswith(n + "·")), None)
        if hit is None:
            raise ValueError(f"모르는 부서 {rest!r}")
        out.append(ROLE_CODES[hit])
        rest = rest[len(hit) + 1:]
    return tuple(out)


# ── 기능 목록 ───────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Function:
    id: str                       # F-WO-011
    menu_code: str                # WO
    screen_id: str                # WO-010
    name: str                     # 기능명
    kind: str                     # 등록 · 수정 · 삭제 · 처리 · 저장 · 진입 · 조회 · 출력
    tables: tuple[str, ...]       # 쓰는 테이블 (읽기 기능은 빈 튜플)
    roles_w: tuple[str, ...]      # W 부서 코드 (읽기 기능 · 권한 예외는 빈 튜플 = 'R 이상')
    api: str                      # 'POST /wo/requests'
    owner: str                    # 개발1 · 개발2 · 개발3
    contract: str                 # 계약 문장
    permission_exception: bool = False   # 권한 칸이 'R 이상(권한 예외)' — 쓰기지만 화면 R 이상이 실행 (rbac.require_fn)

    @property
    def is_write(self) -> bool:
        return self.kind in WRITE_KINDS

    @property
    def read_ok(self) -> bool:
        """화면 R 이상이면 실행할 수 있는가 — 읽기 기능이거나 권한 예외 쓰기 기능."""
        return not self.is_write or self.permission_exception

    @property
    def method(self) -> str:
        return self.api.split(" ", 1)[0]

    @property
    def path(self) -> str:
        return self.api.split(" ", 1)[1]


def _parse_functions(text: str) -> tuple[Function, ...]:
    found = [rows for head, rows in md_tables(md_section(text, "2.")) if head == FUNCTION_HEADER]
    if len(found) != 1:
        raise RuntimeError(f"{FUNCTION_LIST.name} §2 에 머리행이 {FUNCTION_HEADER} 인 표가 정확히 하나 있어야 한다 — 실제 {len(found)}")
    out: list[Function] = []
    errs: list[str] = []
    for r in found[0]:
        if len(r) != len(FUNCTION_HEADER):
            raise RuntimeError(f"{FUNCTION_LIST.name}: 칸 수가 {len(FUNCTION_HEADER)} 이 아닌 행 — {r[:2]}")
        fid, menu_code, sid, name, kind, tables, roles, api, owner, body = r
        codes: tuple[str, ...] = ()
        if roles not in (READ_ROLE_LABEL, EXCEPTION_ROLE_LABEL):
            try:
                codes = _role_codes(roles)
            except ValueError as exc:
                errs.append(f"{fid}: {exc}")
        out.append(Function(id=fid, menu_code=menu_code, screen_id=sid, name=name, kind=kind,
                            tables=_split(tables, ","), roles_w=codes, api=api, owner=owner, contract=body,
                            permission_exception=(roles == EXCEPTION_ROLE_LABEL)))
    if errs:
        raise RuntimeError(f"{FUNCTION_LIST.name} 검증 실패 {len(errs)}건:\n  - " + "\n  - ".join(errs))
    _validate(out)
    return tuple(out)


def owner_path(api_path: str) -> str:
    """API 경로를 덮는 nav 화면 경로 중 가장 구체적인(가장 긴) 것 — 없으면 `/`.
    예: `/prd/daily/{id}` → `/prd/daily` (PRD-010), `/prd/daily/print` → `/prd/daily/print` (PRD-020)."""
    hits = [s.path for s in nav.SCREENS if s.path != "/" and (api_path == s.path or api_path.startswith(s.path + "/"))]
    return max(hits, key=len) if hits else "/"


def _validate(fns: list[Function]) -> None:
    errs: list[str] = []
    ids = [f.id for f in fns]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        errs.append(f"기능 ID 중복 {dup}")
    apis = [f.api for f in fns]
    dup = sorted({a for a in apis if apis.count(a) > 1})
    if dup:
        errs.append(f"API 중복 {dup}")
    for f in fns:
        try:
            s = nav.by_id(f.screen_id)
        except KeyError as exc:
            errs.append(f"{f.id}: {exc}")
            continue
        if s.common:
            errs.append(f"{f.id}: 공통 화면 {s.screen_id} 에는 기능을 두지 않는다")
        m = ID_RE.fullmatch(f.id)
        head, num = s.screen_id.split("-")
        if not m or m.group(1) != head or m.group(2) != num[:2] or m.group(3) == "0":
            errs.append(f"{f.id}: ID 는 F-{head}-{num[:2]}<순번 1~> 이어야 한다")
        if f.menu_code != s.menu_code:
            errs.append(f"{f.id}: 대메뉴 {f.menu_code} ≠ nav {s.menu_code}")
        if f.owner != s.owner:
            errs.append(f"{f.id}: 담당 {f.owner} ≠ nav {s.owner}")
        if f.kind not in WRITE_KINDS | READ_KINDS:
            errs.append(f"{f.id}: 유형 {f.kind!r}")
        am = API_RE.fullmatch(f.api)
        base = s.path
        if not am:
            errs.append(f"{f.id}: API 는 'GET|POST <경로>' — {f.api!r}")
        elif owner_path(am.group(2)) != base:
            errs.append(f"{f.id}: 경로 {am.group(2)} 의 가장 구체적인 nav 경로 {owner_path(am.group(2))} ≠ nav.path_of({s.screen_id}) = {base}")
        elif (am.group(1) == "GET") != (f.kind in READ_KINDS):
            errs.append(f"{f.id}: 읽기 기능은 GET, 쓰기 기능은 POST — {f.api}")
        if f.is_write:
            if not f.tables:
                errs.append(f"{f.id}: 쓰기 기능은 쓰는 테이블이 있어야 한다")
            marked = ROLE_EXCEPTION_MARK in f.contract
            if marked != f.permission_exception:
                errs.append(f"{f.id}: 계약의 「{ROLE_EXCEPTION_MARK}」와 권한 칸 '{EXCEPTION_ROLE_LABEL}' 은 함께 있어야 한다")
            if f.permission_exception and f.roles_w:
                errs.append(f"{f.id}: 권한 예외 기능에는 W 부서를 적지 않는다")
            if not f.roles_w and not f.permission_exception:
                errs.append(f"{f.id}: 쓰기 기능은 W 부서가 있어야 한다 (또는 권한 '{EXCEPTION_ROLE_LABEL}' + 계약 「{ROLE_EXCEPTION_MARK}」)")
        elif f.tables or f.roles_w or f.permission_exception:
            errs.append(f"{f.id}: 읽기 기능은 권한 '{READ_ROLE_LABEL}' · 쓰는 테이블 '-'")
        if not f.contract.strip():
            errs.append(f"{f.id}: 계약이 비었다")
    for s in nav.SCREENS:
        mine = [f for f in fns if f.screen_id == s.screen_id]
        if not mine:
            errs.append(f"{s.screen_id} {s.name}: 기능이 한 줄도 없다")
            continue
        text = " ".join(f.contract for f in mine)
        expected = list(EXPANSION.get(s.kind, ()))
        if NO_EDIT_MARK in text and "수정" in expected:
            expected.remove("수정")
        kinds = [f.kind for f in mine]
        if KIND_EXCEPTION_MARK in text:
            extra = kinds[len(expected):]
            if len(extra) != 1 or extra[0] not in WRITE_KINDS:
                errs.append(f"{s.screen_id}: 「{KIND_EXCEPTION_MARK}」는 쓰기 기능 하나를 뒤에 더한다 — {kinds}")
            kinds = kinds[:len(expected)]
        if kinds != expected:
            errs.append(f"{s.screen_id} ({s.kind}): 기능 유형 {kinds} ≠ 규칙 A {expected}")
        if [int(f.id[-1]) for f in mine] != list(range(1, len(mine) + 1)):
            errs.append(f"{s.screen_id}: 순번이 1 부터 이어지지 않는다 — {[f.id for f in mine]}")
    if errs:
        raise RuntimeError(f"{FUNCTION_LIST.name} 검증 실패 {len(errs)}건:\n  - " + "\n  - ".join(errs))


@lru_cache(maxsize=1)
def functions() -> tuple[Function, ...]:
    if not FUNCTION_LIST.exists():
        raise RuntimeError(f"계약 없음: {FUNCTION_LIST}")
    return _parse_functions(FUNCTION_LIST.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _by_id() -> dict[str, Function]:
    return {f.id: f for f in functions()}


def function(function_id: str) -> Function:
    try:
        return _by_id()[function_id]
    except KeyError:
        raise KeyError(f"function-list.md 에 없는 기능 ID: {function_id}") from None


def functions_of(screen_id: str) -> list[Function]:
    return [f for f in functions() if f.screen_id == screen_id]


def functions_of_menu(menu_code: str) -> list[Function]:
    return [f for f in functions() if f.menu_code == menu_code]


def write_functions() -> list[Function]:
    return [f for f in functions() if f.is_write]


# ── 권한 매트릭스 (permission-matrix.md · 렌더본) ───────────────────────
def permission_cells() -> list[tuple[str, str, str]]:
    """(화면 ID, 부서 코드, 'W'|'R') — `·` 칸은 빠진다. 화면 순서 × 부서 순서."""
    return list(_permission_cells())


@lru_cache(maxsize=1)
def _permission_cells() -> tuple[tuple[str, str, str], ...]:
    if not PERMISSION_MATRIX.exists():
        raise RuntimeError(f"계약 없음: {PERMISSION_MATRIX}")
    found = [rows for head, rows in md_tables(PERMISSION_MATRIX.read_text(encoding="utf-8")) if head == PERMISSION_HEADER]
    if len(found) != 1:
        raise RuntimeError(f"{PERMISSION_MATRIX.name}: 머리행이 {PERMISSION_HEADER} 인 표가 정확히 하나 있어야 한다 — 실제 {len(found)}")
    codes = list(ROLE_CODES.values())
    out: list[tuple[str, str, str]] = []
    errs: list[str] = []
    seen: list[str] = []
    for r in found[0]:
        if len(r) != len(PERMISSION_HEADER):
            errs.append(f"칸 수 {len(r)} — {r[:1]}")
            continue
        sid, name, *levels = r
        seen.append(sid)
        try:
            if nav.by_id(sid).name != name:
                errs.append(f"{sid}: 화면명 {name!r} ≠ nav {nav.by_id(sid).name!r}")
        except KeyError as exc:
            errs.append(str(exc))
        for code, lv in zip(codes, levels):
            if lv == NO_LEVEL:
                continue
            if lv not in LEVELS:
                errs.append(f"{sid}/{code}: 칸 값 {lv!r}")
                continue
            out.append((sid, code, lv))
    if seen != [s.screen_id for s in nav.SCREENS]:
        errs.append("화면 ID 목록 · 순서가 nav.SCREENS 와 다르다")
    if errs:
        raise RuntimeError(f"{PERMISSION_MATRIX.name} 검증 실패 {len(errs)}건:\n  - " + "\n  - ".join(errs))
    return tuple(out)


# ── 테이블 계약 (db-schema.md) ──────────────────────────────────────────
TABLE_HEAD_RE = re.compile(r"^### `(\w+)` — ([A-Z]+) · (.*)$", re.M)   # 영역 = 대메뉴 코드 · SYS (Task 6)
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
    store: str                 # 영역 — 대메뉴 코드 · SYS
    desc: str
    columns: tuple[Column, ...]


@lru_cache(maxsize=1)
def db_tables() -> dict[str, Table]:
    """`contracts/db-schema.md` 의 `### \\`테이블\\` — 영역 · 설명` + 컬럼 표."""
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
