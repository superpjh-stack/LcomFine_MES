from tools import design_doc

def test_raw_matches_planning_doc():
    d = design_doc.load()
    c = design_doc.counts(d)
    assert (c["bundles"], c["menus"], c["screens"], c["roles"]) == (8, 17, 71, 8)
    assert (c["cells_w"], c["cells_r"]) == (76, 203)

def test_roles_equal_guide_page_ia_data():
    # 정본 2쪽(부서 간 업무 변화)의 IA_DATA 는 유효 권한을 JSON 으로 들고 있다 — 1쪽에서 계산한 값과 같아야 한다
    assert design_doc.roles_from_guide() == {s["id"]: s["roles"] for m in design_doc.load()["menus"] for s in m["screens"]}

def test_effective_applies_overrides():
    e = design_doc.effective()
    c = design_doc.counts(e)
    assert (c["menus"], c["screens"], c["cells_w"], c["cells_r"]) == (17, 66, 64, 193)
    assert next(m for m in e["menus"] if m["code"] == "RPT")["name"] == "대시보드"
    assert {s["id"] for m in e["menus"] for s in m["screens"]}.isdisjoint({"RPT-090", "RPT-100", "RPT-110", "RPT-120", "RPT-130"})   # D-505 · D-529

def test_ia_json_is_fresh():
    assert design_doc.write_json(check=True)  # contracts/ia.json == load()
