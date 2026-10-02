"""개발3 담당분의 계약 대조 (G-02 · G-03) — 기능 20 + 배치 6 이 라우트/명령 · 테스트 표식과 이어져 있는가.

`tools/check_trace.py` 와 같은 규칙으로 센다(메서드 + 경로, 경로 변수 이름은 무시, 표식은 `mark.fn(...)` 만).
라우트는 `main.py` 가 include 한 라우터까지 **펼쳐서** 읽는다 — 이 FastAPI(0.142)는 include 한 라우터를 `app.routes` 에
펼쳐 두지 않는다(`_IncludedRouter.original_router`).
"""
import re
from pathlib import Path

from lcomfine import migration
from lcomfine.app import contracts, nav
from lcomfine.app.main import app

OWNER = "개발3"
MODULES = ("qua", "shp", "trc", "sta")
TESTS = Path(__file__).resolve().parent
FN_MARK_RE = re.compile(r"mark\.fn\(([^)]*)\)")
FN_ID_RE = re.compile(r"""["']([FB]-[A-Z]{3}-\d{2})["']""")


def norm(path: str) -> str:
    return re.sub(r"\{[^}]*\}", "{}", path)


def flat(routes):
    """include 된 라우터를 끝까지 펼친다."""
    for rt in routes:
        inner = getattr(rt, "original_router", None)
        if inner is not None:
            yield from flat(inner.routes)
        else:
            yield rt


def registered() -> set[tuple[str, str]]:
    placeholder = set(app.state.placeholder_paths)
    return {(m, norm(rt.path)) for rt in flat(app.routes) for m in (getattr(rt, "methods", None) or ())
            if not (m == "GET" and getattr(rt, "path", "") in placeholder)}


def mine() -> list:
    return [f for f in contracts.functions() if f.owner == OWNER and not f.is_batch]


def test_twenty_functions_are_registered_routes():
    fns, routes = mine(), registered()
    assert len(fns) == 20 and [f.menu_code for f in fns].count("QUA") == 6
    missing = [f"{f.id} {f.api}" for f in fns if (f.method, norm(f.path)) not in routes]
    assert missing == []                                           # API 열의 메서드·경로 글자 그대로


def test_no_placeholder_and_no_orphan_route():
    screens = [s for s in nav.SCREENS if s.owner == OWNER]
    assert len(screens) == 8 and not [s.path for s in screens if s.path in app.state.placeholder_paths]
    apis = {(f.method, norm(f.path)) for f in mine()} | {("GET", s.path) for s in screens}
    prefixes = tuple(f"/{m}/" for m in MODULES)
    orphans = sorted(f"{m} {p}" for m, p in registered()
                     if p.startswith(prefixes) and m not in ("HEAD", "OPTIONS") and (m, p) not in apis)
    assert orphans == []                                           # 계약에 없는 엔드포인트를 만들지 않았다
    assert app.state.include_errors == []


def test_every_function_and_batch_has_a_marked_test():
    seen: set[str] = set()
    for p in sorted(TESTS.glob("test_dev3_*.py")):
        if p.name == Path(__file__).name:
            continue
        for args in FN_MARK_RE.findall(p.read_text(encoding="utf-8")):
            seen.update(FN_ID_RE.findall(args))
    want = {f.id for f in mine()} | {f.id for f in contracts.batch_functions()}
    assert len(want) == 26 and want - seen == set()
    assert seen - {f.id for f in contracts.functions()} == set()   # 계약에 없는 ID 에 표식을 붙이지 않았다
    assert {f.path for f in contracts.batch_functions()} == set(migration.COMMANDS)


def test_write_endpoints_require_fn_and_log_change():
    """쓰기 기능 7개(품질 3 · 출하 4)는 전부 `rbac.require_fn(그 기능 ID)` 로 막고, 성공 직후 `audit.log_change(…, 그 기능 ID, …)` 를 부른다 (G-17 · G-18)."""
    import inspect

    from lcomfine.app.routers import qua, shp
    src = inspect.getsource(qua) + inspect.getsource(shp)
    writes = [f for f in mine() if f.is_write]
    assert len(writes) == 7
    for f in writes:
        assert f'rbac.require_fn("{f.id}")' in src, f.id
        assert f'audit.log_change(request, user, "{f.id}"' in src, f.id
