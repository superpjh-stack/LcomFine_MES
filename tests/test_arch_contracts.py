# tests/test_arch_contracts.py — 기능 목록 · 권한 매트릭스 계약 (D-508)
import re

from lcomfine.app import contracts, nav
from tools import design_doc

# 스펙 §3.2 · D-508 — 정본 type → 전개 기능 유형 (순서대로 순번 1, 2, …)
EXPANSION = {
    "조회": ["조회"],
    "리포트": ["조회"],
    "출력": ["조회"],
    "등록": ["등록", "수정", "조회"],
    "목록·등록": ["등록", "수정", "삭제", "조회"],
    "등록·출력": ["등록", "수정", "조회", "출력"],
    "처리": ["처리", "조회"],
    "설정": ["저장", "조회"],
    "외부 연계(SSO)": ["진입", "조회"],
}


def _screens():
    return [s for m in design_doc.effective()["menus"] for s in m["screens"]]


def test_function_list_covers_every_screen_by_expansion_rule():
    screens = _screens()
    assert len(screens) == 67
    for s in screens:
        fns = contracts.functions_of(s["id"])
        assert fns, f"{s['id']}: 기능이 없다"
        kinds = [f.kind for f in fns]
        text = " ".join(f.contract for f in fns)
        expected = list(EXPANSION[s["type"]])
        if "수정 없음" in text:
            expected.remove("수정")
        if "유형 예외" in text:                       # 정본 type 밖 쓰기 기능 하나를 화면 끝에 더한다 (예외 3)
            extra = kinds[len(expected):]
            assert len(extra) == 1 and extra[0] in contracts.WRITE_KINDS, f"{s['id']}: 유형 예외 — {kinds}"
            kinds = kinds[:len(expected)]
        assert kinds == expected, f"{s['id']} ({s['type']}): {kinds} ≠ {expected}"
        prefix = f"F-{s['id'].split('-')[0]}-{s['id'].split('-')[1][:2]}"
        assert [f.id for f in fns] == [f"{prefix}{i}" for i in range(1, len(fns) + 1)], f"{s['id']}: 순번"
    # 예외 문구는 정해진 화면에만
    exc = sorted({f.screen_id for f in contracts.functions() if "수정 없음" in f.contract})
    assert exc == ["COL-010", "INV-030"]
    # 유형 예외는 정확히 셋 — 질의 실행 (D-513) · 반품·정정 (D-515) · 알림 처리 (D-511)
    kind_exc = sorted(f.id for f in contracts.functions() if "유형 예외" in f.contract)
    assert kind_exc == ["F-HOME-022", "F-RPT-132", "F-SHP-023"]
    assert [(f.kind, f.api) for f in map(contracts.function, kind_exc)] == [
        ("처리", "POST /home/notifications/{id}/handle"), ("처리", "POST /rpt/query"),
        ("처리", "POST /shp/confirm/{id}/adjust")]
    total = sum(len(EXPANSION[s["type"]]) for s in screens) - len(exc) + len(kind_exc)
    assert len(contracts.functions()) == total == 136


def test_function_ids_unique_and_api_prefix_matches_nav_path():
    fns = contracts.functions()
    ids = [f.id for f in fns]
    assert len(ids) == len(set(ids))
    apis = [f.api for f in fns]
    assert len(apis) == len(set(apis))
    for f in fns:
        assert re.fullmatch(r"F-[A-Z]+-\d{3}", f.id), f.id
        s = nav.by_id(f.screen_id)
        assert f.menu_code == s.menu_code and f.owner == s.owner, f.id
        method, path = f.api.split(" ", 1)
        assert method == ("GET" if f.kind in {"조회", "출력"} else "POST"), f.id
        base = nav.path_of(f.screen_id)
        assert path == base or path.startswith(base.rstrip("/") + "/"), f"{f.id}: {path} ⊄ {base}"
        covering = [x.path for x in nav.SCREENS if x.path != "/" and (path == x.path or path.startswith(x.path + "/"))]
        assert (max(covering, key=len) if covering else "/") == base, f"{f.id}: 더 구체적인 화면 경로가 {path} 를 덮는다"
        assert contracts.function(f.id) is f
    assert {f.menu_code for f in fns} == {m.code for m in nav.MENUS}
    assert sum(len(contracts.functions_of_menu(m.code)) for m in nav.MENUS) == len(fns)


def test_permission_matrix_equals_effective_ia():
    e = design_doc.effective()
    expected = {(s["id"], r, v) for m in e["menus"] for s in m["screens"] for r, v in s["roles"].items()}
    cells = contracts.permission_cells()
    assert len(cells) == 260 and set(cells) == expected
    assert sum(1 for c in cells if c[2] == "W") == 64 and sum(1 for c in cells if c[2] == "R") == 196
    assert set(contracts.ROLE_CODES.values()) == {r["id"] for r in e["roles"]}
    assert list(contracts.ROLE_CODES) == [r["name"] for r in e["roles"]]


def test_every_write_function_has_w_role():
    e = design_doc.effective()
    w = {s["id"]: [r for r, v in s["roles"].items() if v == "W"] for m in e["menus"] for s in m["screens"]}
    order = [r["id"] for r in e["roles"]]
    writes = contracts.write_functions()
    assert writes and all(f.kind in contracts.WRITE_KINDS for f in writes)
    for f in contracts.functions():
        if f.is_write and "권한 예외" in f.contract:   # 정본 칸에 W 가 없는 화면의 쓰기 — 화면 R 이상이 실행
            assert f.permission_exception and f.read_ok, f.id
            assert f.roles_w == () and not w[f.screen_id], f.id
            assert f.tables, f.id
        elif f.is_write:
            assert f.roles_w, f"{f.id}: 쓰기 기능에 W 부서가 없다"
            assert list(f.roles_w) == sorted(w[f.screen_id], key=order.index), f"{f.id}: {f.roles_w}"
            assert f.tables, f"{f.id}: 쓰기 기능인데 쓰는 테이블이 없다"
        else:
            assert f.roles_w == () and f.tables == (), f"{f.id}: 읽기 기능은 R 이상 · 테이블 -"
        assert f.contract.strip(), f"{f.id}: 계약이 비었다"
    exc_ids = ["F-DOC-011", "F-HOME-022", "F-RPT-132"]
    assert sorted(f.id for f in writes if "권한 예외" in f.contract) == exc_ids
    assert sorted(f.id for f in contracts.functions() if f.permission_exception) == exc_ids
    assert all(not f.read_ok for f in writes if f.id not in exc_ids)
    # 권한 칸은 글자 그대로 `R 이상(권한 예외)`
    rows = [ln for ln in contracts.FUNCTION_LIST.read_text(encoding="utf-8").splitlines() if "R 이상(권한 예외)" in ln and ln.startswith("| F-")]
    assert sorted(r.split("|")[1].strip() for r in rows) == exc_ids
    assert all(r.split("|")[7].strip() == "R 이상(권한 예외)" for r in rows)
