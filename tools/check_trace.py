#!/usr/bin/env python
"""G-01 메뉴 · G-02 기능 추적 검사 — `make check-trace`.

기대값은 **설계도(정본 HTML)에서 직접** 끌어온다(`tools/design_doc.py`). 코드가 스스로 적은 숫자를 믿지 않는다.

  G-01  설계도 §5 `.ia-menu` 파싱값 ↔ `nav.py` (묶음 4 · 대메뉴 12 · 중메뉴 32 · 이름·순서·기능 수·채널) ↔ `screen-map.md` 렌더본
  G-02  `function-list.md` 100줄(화면 94 + 배치 6) · 대메뉴별 수 ↔ 설계도 · 쓰는 저장소 ↔ 설계도 §2 표 · 권한 열 ↔ 설계도 §6
        + 한 기능 = API 하나(라우터에 등록됐는가) = 테스트 하나 이상(`@pytest.mark.fn` 표식) · 고아 0

출력 행 형식: `G-nn  항목  PASS|FAIL  실측` (tools/gate.py 가 읽는다).  종료코드: 0 = 둘 다 PASS, 1 = 하나라도 FAIL.
"""

from __future__ import annotations

import warnings

warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient`")

import importlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import design_doc  # noqa: E402

TESTS_DIR = ROOT / "tests"
#: 테스트 ↔ 기능 연결은 표식으로만 센다 — `@pytest.mark.fn("F-BAS-01")` 또는 `pytest.mark.fn("F-BAS-01", "F-BAS-02")`.
#: 테스트 본문에 ID 가 우연히 적힌 것(권한 검사의 인자 등)은 세지 않는다.
FN_MARK_RE = re.compile(r"mark\.fn\(([^)]*)\)")
FN_ID_RE = re.compile(r"""["']([FB]-[A-Z]{3}-\d{2})["']""")


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, bool, str]] = []

    def add(self, gate: str, item: str, ok: bool, actual: str) -> None:
        self.rows.append((gate, item, bool(ok), actual))

    def failed(self, gate: str) -> int:
        return sum(1 for g, _, ok, _ in self.rows if g == gate and not ok)


def norm_path(path: str) -> str:
    """경로 변수 이름을 지운다 — `/job/orders/{job_no}` 와 `/job/orders/{no}` 를 같은 것으로 본다."""
    return re.sub(r"\{[^}]*\}", "{}", path)


def all_routes(routes, prefix: str = ""):
    """등록된 라우트를 (경로, 메서드들) 로 편다.

    FastAPI 는 `include_router` 한 라우터를 `app.routes` 에 풀지 않고 한 덩어리(`original_router`)로 둔다.
    덩어리를 건너뛰면 기능 ↔ 라우트가 0 으로 세어지고 고아 검사도 빈 집합으로 통과한다.
    """
    for rt in routes:
        inner = getattr(rt, "original_router", None)
        if inner is not None:
            ctx = getattr(rt, "include_context", None)
            yield from all_routes(inner.routes, prefix + (getattr(ctx, "prefix", "") or ""))
        elif getattr(rt, "methods", None):
            yield prefix + getattr(rt, "path", ""), rt.methods


def write_roles(access: dict, menu_name: str, scope: str) -> list[str]:
    """설계도 §6 에서 그 대메뉴의 그 범위 기능을 입력할 수 있는 역할 (D-14)."""
    row = next(r for r in access["rows"] if r["menu"] == menu_name)
    out = []
    for role, cell in zip(access["roles"], row["cells"]):
        if not cell.startswith("입력"):
            continue
        cell_scope = cell[cell.index("(") + 1: cell.rindex(")")].strip() if "(" in cell else "일반"
        if cell_scope == scope:
            out.append(role)
    return out


def check_menu(r: Report, ia: dict, access: dict) -> None:
    g = "G-01"
    try:
        from lcomfine.app import nav
    except Exception as exc:  # noqa: BLE001 — 코드가 없거나 깨졌으면 그 사실을 적는다
        r.add(g, "nav.py import", False, f"{type(exc).__name__}: {exc}")
        return
    d_groups = [x["name"] for x in ia["groups"]]
    d_menus = [(x["name"], m["name"]) for x in ia["groups"] for m in x["menus"]]
    d_subs = [(m["name"], s) for x in ia["groups"] for m in x["menus"] for s in m["subs"]]
    d_counts = [(m["name"], m["count"]) for x in ia["groups"] for m in x["menus"]]
    r.add(g, "설계도 IA 파싱 — 묶음 4 · 대메뉴 12 · 중메뉴 32 · 기능 94",
          (len(d_groups), len(d_menus), len(d_subs), sum(c for _, c in d_counts)) == (4, 12, 32, 94) and ia["root"] == (12, 32),
          f"묶음 {len(d_groups)} · 대메뉴 {len(d_menus)} · 중메뉴 {len(d_subs)} · 기능 {sum(c for _, c in d_counts)} · 뿌리 표기 {ia['root']}")
    r.add(g, "nav 묶음 = 설계도 (이름·순서)", list(nav.GROUPS) == d_groups, f"nav {len(nav.GROUPS)} — {' / '.join(nav.GROUPS)}")
    n_menus = [(m.group, m.name) for m in nav.MENUS]
    diff = [b for a, b in zip(n_menus, d_menus) if a != b] if len(n_menus) == len(d_menus) else ["개수 다름"]
    r.add(g, "nav 대메뉴 = 설계도 (이름·순서·묶음)", n_menus == d_menus, f"nav {len(n_menus)} · 불일치 {len(diff)} {diff[:3] if diff else ''}".strip())
    n_subs = [(s.menu, s.name) for s in nav.SCREENS]
    diff = sorted(set(n_subs) ^ set(d_subs))
    r.add(g, "nav 중메뉴 = 설계도 (이름·순서)", n_subs == d_subs, f"nav {len(n_subs)} · 불일치 {len(diff)} {diff[:3] if diff else ''}".strip())
    n_counts = [(m.name, m.fn_count) for m in nav.MENUS]
    r.add(g, "nav 대메뉴별 기능 수 = 설계도", n_counts == d_counts, " · ".join(str(m.fn_count) for m in nav.MENUS))
    d_ch = {row["menu"]: row["channels"] for row in access["rows"]}
    bad = [m.name for m in nav.MENUS if list(m.channels) != d_ch.get(m.name)]
    r.add(g, "nav 대메뉴 채널 = 설계도 §6 「주로 쓰는 채널」", not bad, f"불일치 {len(bad)} {bad[:3] if bad else ''}".strip())
    bad = [s.screen_id for m in nav.MENUS for s in m.screens if not set(s.channels) <= set(m.channels)]
    r.add(g, "중메뉴 채널 ⊆ 대메뉴 채널", not bad, f"벗어남 {len(bad)} {bad[:3] if bad else ''}".strip())
    paths = [s.path for s in nav.ALL]
    r.add(g, "화면 ID 32 · 경로 중복 0", len({s.screen_id for s in nav.SCREENS}) == 32 and len(set(paths)) == len(paths),
          f"화면 ID {len({s.screen_id for s in nav.SCREENS})} · 경로 {len(set(paths))}/{len(paths)}")
    try:
        import gen_contracts
        text = gen_contracts.SCREEN_MAP_MD.read_text(encoding="utf-8")
        same = gen_contracts.replace_block(text, "screens", gen_contracts.render_screens(), gen_contracts.SCREEN_MAP_MD) == text
        r.add(g, "screen-map.md §1 렌더본 = nav.py", same, "일치" if same else "다르다 — `make contracts`")
    except (Exception, SystemExit) as exc:  # noqa: BLE001
        r.add(g, "screen-map.md §1 렌더본 = nav.py", False, f"{type(exc).__name__}: {exc}")


def check_functions(r: Report, ia: dict, access: dict, procs: dict) -> None:
    g = "G-02"
    try:
        from lcomfine.app import contracts, nav
        fns = contracts.functions()
    except Exception as exc:  # noqa: BLE001
        r.add(g, "function-list.md 로드", False, f"{type(exc).__name__}: {str(exc)[:160]}")
        return
    screen_fns = [f for f in fns if not f.is_batch]
    batch_fns = [f for f in fns if f.is_batch]
    r.add(g, "계약 100줄 = 화면 기능 94 + 이관 배치 6", (len(screen_fns), len(batch_fns)) == (94, 6),
          f"{len(fns)}줄 = 화면 {len(screen_fns)} + 배치 {len(batch_fns)} · ID 중복 {len(fns) - len({f.id for f in fns})}")
    d_counts = [(m["name"], m["count"]) for x in ia["groups"] for m in x["menus"]]
    got = [(name, sum(1 for f in screen_fns if f.menu == name)) for name, _ in d_counts]
    r.add(g, "대메뉴별 기능 수 = 설계도 (20·12·7 / 8·8·5·7 / 6·7 / 3·4·7)", got == d_counts, " · ".join(str(n) for _, n in got))
    empty = [s.screen_id for s in nav.SCREENS if not contracts.functions_of(s.screen_id)]
    r.add(g, "중메뉴 32 마다 기능 1줄 이상", not empty, f"기능 없는 중메뉴 {len(empty)} {empty[:3] if empty else ''}".strip())

    # 쓰는 저장소 ⊆ 설계도 §2 표의 그 프로세스 「쓰는 저장소」. 예외는 P8 의 출하 화살표 하나 (D-12)
    bad, exceptions = [], []
    for f in screen_fns:
        if f.process == "공통":
            if set(f.stores) - {"SYS"}:
                bad.append(f.id)
            continue
        allowed = set(procs[f.process]["writes"])
        for st in f.stores:
            base = st.split("(")[0].strip()
            if base in allowed:
                continue
            if f.process == "P8" and base == "D6" and "출하 화살표" in st:
                exceptions.append(f.id)
                continue
            bad.append(f"{f.id}:{st}")
    readers = [f.id for f in screen_fns if f.process in ("P9", "P10") and (f.stores or f.tables)]
    r.add(g, "쓰는 저장소 ⊆ 설계도 §2 표 (P9·P10 은 쓰기 0)", not bad and not readers,
          f"벗어남 {len(bad)} {bad[:3] if bad else ''} · P9·P10 쓰기 {len(readers)} · 예외 {len(exceptions)}건 {exceptions} (D-12)".replace("  ", " "))
    try:
        known = contracts.db_tables()
        missing = sorted({t for f in fns for t in f.tables if t not in known})
        wrong = [f"{f.id}:{t}" for f in screen_fns for t in f.tables if t in known
                 and known[t].store not in {s.split('(')[0].strip() for s in f.stores}]
        r.add(g, "쓰는 테이블이 db-schema.md 에 있고 저장소가 맞다", not missing and not wrong,
              f"없는 테이블 {len(missing)} {missing[:3] if missing else ''} · 저장소 불일치 {len(wrong)} {wrong[:3] if wrong else ''}".replace("  ", " ").strip())
    except Exception as exc:  # noqa: BLE001
        r.add(g, "쓰는 테이블이 db-schema.md 에 있고 저장소가 맞다", False, f"{type(exc).__name__}: {exc}")

    # 권한 열 = 설계도 §6 에서 계산한 입력 역할
    bad = [f.id for f in screen_fns if f.is_write and list(f.roles) != write_roles(access, f.menu, f.scope)]
    scoped = sorted(f"{f.id}({f.scope})" for f in screen_fns if f.is_write and f.scope != "일반")
    r.add(g, "권한 열 = 설계도 §6 의 입력 역할 (괄호 조건 2개 포함)", not bad and len(scoped) == 2,
          f"불일치 {len(bad)} {bad[:3] if bad else ''} · 범위 기능 {' '.join(scoped)}".replace("  ", " "))

    # 한 기능 = API 하나 (라우터에 등록됐고 placeholder 가 아니다)
    try:
        from lcomfine.app.main import app
        placeholder = set(app.state.placeholder_paths)
        routes = {(m, norm_path(path)) for path, methods in all_routes(app.routes) for m in methods
                  if not (m == "GET" and path in placeholder)}
        linked = [f for f in screen_fns if (f.method, norm_path(f.path)) in routes]
        miss = [f.id for f in screen_fns if f not in linked]
        r.add(g, "기능 94 ↔ 라우트 (API 열의 메서드·경로가 등록됨)", len(linked) == 94,
              f"이어진 기능 {len(linked)}/94" + (f" · 미연결 예 {miss[:3]}" if miss else ""))
        # 고아 라우트: 담당 모듈 경로 아래인데 어느 기능의 API 도 아니고 중메뉴 화면 GET 도 아닌 것
        fn_apis = {(f.method, norm_path(f.path)) for f in screen_fns}
        screen_gets = {("GET", s.path) for s in nav.SCREENS}
        prefixes = tuple(f"/{m.module}/" for m in nav.MENUS)
        orphans = sorted(f"{m} {p}" for m, p in routes if p.startswith(prefixes) and m not in ("HEAD", "OPTIONS")
                         and (m, p) not in fn_apis and (m, p) not in screen_gets)
        r.add(g, "고아 라우트 0 (계약에 없는 엔드포인트)", not orphans, f"고아 {len(orphans)} {orphans[:3] if orphans else ''}".strip())
    except Exception as exc:  # noqa: BLE001
        r.add(g, "기능 94 ↔ 라우트", False, f"{type(exc).__name__}: {str(exc)[:160]}")

    # 한 기능 = 테스트 하나 이상 (`@pytest.mark.fn("F-BAS-01")` 표식이 붙은 테스트)
    seen: set[str] = set()
    files = sorted(TESTS_DIR.glob("test_*.py")) if TESTS_DIR.exists() else []
    for p in files:
        for args in FN_MARK_RE.findall(p.read_text(encoding="utf-8")):
            seen.update(FN_ID_RE.findall(args))
    ids = {f.id for f in fns}
    tested = ids & seen
    r.add(g, "기능 100 ↔ 테스트 (@pytest.mark.fn 표식)", tested == ids,
          f"표식이 붙은 기능 {len(tested)}/100 · 테스트 파일 {len(files)}" + (f" · 계약에 없는 ID {sorted(seen - ids)[:3]}" if seen - ids else ""))

    # 이관 배치 6 ↔ 명령
    try:
        mig = importlib.import_module("lcomfine.migration")
        commands = set(getattr(mig, "COMMANDS", {}) or {})
        have = [f.id for f in batch_fns if f.path in commands]
        r.add(g, "이관 배치 6 ↔ 명령 (lcomfine.migration.COMMANDS)", len(have) == 6, f"이어진 배치 {len(have)}/6")
    except ModuleNotFoundError:
        r.add(g, "이관 배치 6 ↔ 명령 (lcomfine.migration.COMMANDS)", False, "이어진 배치 0/6 · src/lcomfine/migration 없음 (개발3)")


def main() -> int:
    h = design_doc.html()
    ia, access, procs = design_doc.ia(h), design_doc.access(h), design_doc.processes(h)
    r = Report()
    check_menu(r, ia, access)
    check_functions(r, ia, access, procs)

    w = max(len(i) for _, i, _, _ in r.rows)
    print("G-01 메뉴 · G-02 기능 추적 (tools/check_trace.py) — 기대값은 설계도에서 직접 읽는다")
    print("-" * 100)
    for g, i, ok, a in r.rows:
        print(f"{g}  {i:<{w}}  {'PASS' if ok else 'FAIL'}  {a}")
    print("-" * 100)
    for g in ("G-01", "G-02"):
        n = sum(1 for x in r.rows if x[0] == g)
        print(f"{g} 판정: {'PASS' if r.failed(g) == 0 else 'FAIL'} (검사 {n} · 실패 {r.failed(g)})")
    return 1 if (r.failed("G-01") or r.failed("G-02")) else 0


if __name__ == "__main__":
    sys.exit(main())
