# tests/test_arch_nav.py
from lcomfine.app import nav
from tools import design_doc

def test_nav_equals_effective_ia_word_for_word():
    e = design_doc.effective()
    assert [b[1] for b in nav.BUNDLES] == [b["name"] for b in e["bundles"]]
    assert [(m.code, m.name, m.bundle) for m in nav.MENUS] == [(m["code"], m["name"], m["bundle"]) for m in e["menus"]]
    assert [(s.screen_id, s.name, s.kind) for s in nav.SCREENS] == [(s["id"], s["name"], s["type"]) for m in e["menus"] for s in m["screens"]]
    assert len(nav.SCREENS) == 66 and nav.path_of("HOME-010") == "/" and nav.path_of("RPT-080") == "/rpt/summary"
    assert "RPT-130" not in {s.screen_id for s in nav.SCREENS}   # 데이터 질의는 D-529 로 없앴다
    assert [f for f in nav.FLOW] == [f["id"] for f in e["flow"]]

def test_paths_unique_and_validate():
    assert len({s.path for s in nav.ALL}) == len(nav.ALL)
    nav.validate()
