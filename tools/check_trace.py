#!/usr/bin/env python
"""G-01 정본 ↔ nav · G-02 기능 ↔ 라우트 ↔ 테스트 표식 — `make check-trace`.

기대값은 **정본 추출(`contracts/ia.json` + `contracts/ia-overrides.json` = `design_doc.effective()`)에서** 읽는다.
코드가 스스로 적은 숫자를 믿지 않는다.

  G-01  묶음 8 · 대메뉴 17 · 화면 66(goal.md §2.0 의 67 − RPT-130 · D-529) · 흐름 7 — 순서 · 이름 · 화면 유형이 글자 단위로 nav 와 같다.
        RPT 이름 「대시보드」 · RPT-090~120 없음(D-505) · RPT-130 없음(D-529). ia.json = 정본 HTML · permission-matrix.md = 정본 · screen-map.md §1 = nav.
  G-02  `contracts/function-list.md` 줄마다 API 열의 메서드 · 경로가 앱 라우트에 **글자 그대로** 있다(경로 매개변수 `{id}` 도 그대로).
        고아 3종 — 라우트 없는 계약 · 계약 없는 라우트 · 표식 없는 기능 — 을 각각 목록으로 찍는다. 셋 다 0 이어야 PASS.
        placeholder GET(main.py 가 붙인 미구현 화면)과 공통 라우트(/login · /logout · /error · /ia · /health · /openapi.json)는 라우트 집계에서 뺀다.
        표식은 `tests/` 의 `@pytest.mark.fn("F-…")` 를 ast 로 읽는다(본문에 ID 가 우연히 적힌 것은 세지 않는다).

출력 행 형식: `G-nn  항목  PASS|FAIL  실측` (tools/gate.py 가 읽는다). 종료코드: 0 = 둘 다 PASS, 1 = 하나라도 FAIL.
"""

from __future__ import annotations

import warnings

warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient`")

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from tools import design_doc  # noqa: E402

TESTS_DIR = ROOT / "tests"
#: goal.md §2.0 의 기대값 (정본에서 다시 센 수 — 이 수와 정본 추출이 다르면 정본 추출이 바뀐 것이다)
EXPECT = {"묶음": 8, "대메뉴": 17, "화면": 66, "흐름": 7}   # 화면 = goal.md §2.0 의 67 − RPT-130 (D-529)
REMOVED = ("RPT-090", "RPT-100", "RPT-110", "RPT-120", "RPT-130")   # D-505 · D-529
#: 기능 계약 밖의 공통 라우트 (main.py — Task 8)
COMMON_ROUTES = {"/login", "/login/quick", "/logout", "/error", "/ia", "/health", "/openapi.json"}
SKIP_METHODS = {"HEAD", "OPTIONS"}


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, bool, str]] = []
        self.lists: list[tuple[str, list[str]]] = []

    def add(self, gate: str, item: str, ok: bool, actual: str) -> None:
        self.rows.append((gate, item, bool(ok), actual))

    def listing(self, title: str, items: list[str]) -> None:
        self.lists.append((title, items))

    def failed(self, gate: str) -> int:
        return sum(1 for g, _, ok, _ in self.rows if g == gate and not ok)


def _diff(a: list, b: list) -> str:
    if len(a) != len(b):
        return f"개수 nav {len(a)} ≠ 정본 {len(b)}"
    bad = [f"{x} ≠ {y}" for x, y in zip(a, b) if x != y]
    return f"불일치 {len(bad)}" + (f" — {bad[:2]}" if bad else "")


def _run_check(args: list[str]) -> tuple[int, str]:
    p = subprocess.run(["uv", "run", "python", *args], cwd=ROOT, capture_output=True, text=True, timeout=300)
    lines = ((p.stdout or "") + (p.stderr or "")).strip().splitlines()
    return p.returncode, (lines[-1] if lines else "출력 없음")


def check_nav(r: Report) -> None:
    g = "G-01"
    try:
        e = design_doc.effective()
    except (Exception, SystemExit) as exc:  # noqa: BLE001 — 정본 추출이 깨졌으면 그 사실이 실측이다
        r.add(g, "정본 추출 로드 (ia.json + overrides)", False, f"{type(exc).__name__}: {exc}")
        return
    try:
        from lcomfine.app import nav
    except Exception as exc:  # noqa: BLE001
        r.add(g, "nav.py import", False, f"{type(exc).__name__}: {exc}")
        return
    scr = [s for m in e["menus"] for s in m["screens"]]
    got = {"묶음": len(e["bundles"]), "대메뉴": len(e["menus"]), "화면": len(scr), "흐름": len(e["flow"])}
    r.add(g, "정본 수 = goal.md §2.0 (묶음 8 · 대메뉴 17 · 화면 66 · 흐름 7 · D-529)", got == EXPECT,
          " · ".join(f"{k} {v}" for k, v in got.items()))

    a, b = [x[1] for x in nav.BUNDLES], [x["name"] for x in e["bundles"]]
    r.add(g, "묶음 — 이름 · 순서", a == b, f"nav {len(a)} · {_diff(a, b)}")
    a = [(m.code, m.name, m.bundle) for m in nav.MENUS]
    b = [(m["code"], m["name"], m["bundle"]) for m in e["menus"]]
    r.add(g, "대메뉴 — 코드 · 이름 · 묶음 · 순서", a == b, f"nav {len(a)} · {_diff(a, b)}")
    a = [(s.menu_code, s.screen_id, s.name, s.kind) for s in nav.SCREENS]
    b = [(m["code"], s["id"], s["name"], s["type"]) for m in e["menus"] for s in m["screens"]]
    r.add(g, "화면 — 대메뉴 · ID · 이름 · 유형 · 순서", a == b, f"nav {len(a)} · {_diff(a, b)}")
    a, b = list(nav.FLOW), [f["id"] for f in e["flow"]]
    r.add(g, "흐름 — 화면 ID · 순서", a == b, f"nav {len(a)} {' → '.join(a)} · {_diff(a, b)}")

    try:
        rpt = nav.menu("RPT").name
    except KeyError:
        rpt = "(없음)"
    left = [sid for sid in REMOVED if sid in {s.screen_id for s in nav.SCREENS}]
    r.add(g, "D-505 · D-529 — RPT 이름 「대시보드」 · RPT-090~130 없음", rpt == "대시보드" and not left,
          f"RPT 이름 「{rpt}」 · 남은 화면 {left or 0}")

    paths = [s.path for s in nav.ALL]
    r.add(g, "경로 중복 0", len(set(paths)) == len(paths), f"경로 {len(set(paths))}/{len(paths)}")

    try:
        same = design_doc.write_json(check=True)
        r.add(g, "contracts/ia.json = 정본 HTML 재추출", same, "일치" if same else "다르다 — `uv run python tools/design_doc.py`")
    except (Exception, SystemExit) as exc:  # noqa: BLE001
        r.add(g, "contracts/ia.json = 정본 HTML 재추출", False, f"{type(exc).__name__}: {str(exc)[:120]}")
    code, last = _run_check(["tools/gen_permissions.py", "--check"])
    r.add(g, "permission-matrix.md = 정본 (gen_permissions --check)", code == 0, f"rc={code} {last}")
    code, last = _run_check(["tools/gen_contracts.py", "--check", "--only", "screens"])
    r.add(g, "screen-map.md §1 렌더본 = nav (gen_contracts --check)", code == 0, f"rc={code} {last}")


def all_routes(routes, prefix: str = ""):
    """등록된 라우트를 (경로, 메서드들) 로 편다.

    FastAPI 는 `include_router` 한 라우터를 `app.routes` 에 한 덩어리(`original_router`)로 둘 수 있다.
    덩어리를 건너뛰면 기능 ↔ 라우트가 0 으로 세어지고 고아 검사도 빈 집합으로 통과한다.
    """
    for rt in routes:
        inner = getattr(rt, "original_router", None)
        if inner is not None:
            ctx = getattr(rt, "include_context", None)
            yield from all_routes(inner.routes, prefix + (getattr(ctx, "prefix", "") or ""))
        elif getattr(rt, "methods", None):
            yield prefix + getattr(rt, "path", ""), rt.methods


def fn_marks(files: list[Path]) -> tuple[set[str], list[str]]:
    """`@pytest.mark.fn("F-…", …)` 의 문자열 인자를 ast 로 모은다 → (ID 집합, 읽지 못한 파일)."""
    seen: set[str] = set()
    errors: list[str] = []
    for p in files:
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        except SyntaxError as exc:
            errors.append(f"{p.name}: {exc}")
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if isinstance(f, ast.Attribute) and f.attr == "fn" and isinstance(f.value, ast.Attribute) and f.value.attr == "mark":
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        seen.add(arg.value)
    return seen, errors


def check_functions(r: Report) -> None:
    g = "G-02"
    try:
        from lcomfine.app import contracts
        fns = contracts.functions()
    except (Exception, SystemExit) as exc:  # noqa: BLE001
        r.add(g, "function-list.md 로드", False, f"{type(exc).__name__}: {str(exc)[:160]}")
        return
    ids = [f.id for f in fns]
    r.add(g, "function-list.md 로드 · ID 중복 0", len(ids) == len(set(ids)),
          f"기능 {len(fns)} (GET {sum(f.method == 'GET' for f in fns)} · POST {sum(f.method == 'POST' for f in fns)}) · 중복 {len(ids) - len(set(ids))}")

    try:
        from lcomfine.app.main import app
    except Exception as exc:  # noqa: BLE001
        r.add(g, "앱 import", False, f"{type(exc).__name__}: {str(exc)[:160]}")
        return
    placeholder = set(app.state.placeholder_paths)
    routes = {(m, path) for path, methods in all_routes(app.routes) for m in methods
              if m not in SKIP_METHODS and path not in COMMON_ROUTES and not (m == "GET" and path in placeholder)}
    fn_apis = {(f.method, f.path) for f in fns}

    no_route = [f"{f.id} {f.api}" for f in fns if (f.method, f.path) not in routes]
    r.add(g, "고아 ① 라우트 없는 계약 0 (API 열이 글자 그대로 등록됨)", not no_route,
          f"라우트 없는 계약 {len(no_route)} · 이어진 기능 {len(fns) - len(no_route)}/{len(fns)}")
    r.listing("라우트 없는 계약", no_route)

    no_contract = sorted(f"{m} {p}" for m, p in routes if (m, p) not in fn_apis)
    writes = [x for x in no_contract if not x.startswith("GET ")]
    r.add(g, "고아 ② 계약 없는 라우트 0", not no_contract,
          f"계약 없는 라우트 {len(no_contract)} (쓰기 {len(writes)}) · 집계한 라우트 {len(routes)} · placeholder 제외 {len(placeholder)}")
    r.listing("계약 없는 라우트", no_contract)

    files = sorted(TESTS_DIR.glob("test_*.py")) if TESTS_DIR.exists() else []
    seen, errors = fn_marks(files)
    known = set(ids)
    unmarked = [f"{f.id} {f.name}" for f in fns if f.id not in seen]
    unknown = sorted(seen - known)
    r.add(g, "고아 ③ 표식 없는 기능 0 (@pytest.mark.fn)", not unmarked and not errors,
          f"표식 없는 기능 {len(unmarked)} · 표식 있는 기능 {len(known & seen)}/{len(known)} · 테스트 파일 {len(files)}"
          + (f" · 읽지 못한 파일 {errors[:2]}" if errors else ""))
    r.listing("표식 없는 기능", unmarked)
    r.add(g, "표식의 ID 가 전부 계약에 있다", not unknown, f"계약에 없는 표식 {len(unknown)} {unknown[:5] if unknown else ''}".strip())


def main() -> int:
    r = Report()
    check_nav(r)
    check_functions(r)

    w = max(len(i) for _, i, _, _ in r.rows)
    print("G-01 정본 ↔ nav · G-02 기능 ↔ 라우트 ↔ 테스트 표식 (tools/check_trace.py) — 기대값은 정본 추출에서 읽는다")
    print("-" * 100)
    for g, i, ok, a in r.rows:
        print(f"{g}  {i:<{w}}  {'PASS' if ok else 'FAIL'}  {a}")
    print("-" * 100)
    for title, items in r.lists:
        print(f"[{title}] {len(items)}")
        for x in items:
            print(f"    - {x}")
    print("-" * 100)
    for g in ("G-01", "G-02"):
        n = sum(1 for x in r.rows if x[0] == g)
        print(f"{g} 판정: {'PASS' if r.failed(g) == 0 else 'FAIL'} (검사 {n} · 실패 {r.failed(g)})")
    return 1 if (r.failed("G-01") or r.failed("G-02")) else 0


if __name__ == "__main__":
    sys.exit(main())
