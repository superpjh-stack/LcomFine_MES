"""D-531 경영관리의 IA·기능·권한 계약 표식.

동작 검증은 각 구현 Task의 dev/QA 테스트가 맡고, 이 파일은 계약 단계에서 신규 기능이
정해진 화면·권한·쓰기 경계를 벗어나지 않는지만 고정한다.
"""

import pytest

from lcomfine.app import contracts, nav


MGT_FUNCTIONS = (
    "F-MGT-011", "F-MGT-012", "F-MGT-013", "F-MGT-014",
    "F-MGT-021", "F-MGT-022", "F-MGT-023", "F-MGT-024",
    "F-MGT-031", "F-MGT-032", "F-MGT-033", "F-MGT-034",
    "F-MGT-041", "F-MGT-042", "F-MGT-043",
)


@pytest.mark.fn(
    "F-MGT-011", "F-MGT-012", "F-MGT-013", "F-MGT-014",
    "F-MGT-021", "F-MGT-022", "F-MGT-023", "F-MGT-024",
    "F-MGT-031", "F-MGT-032", "F-MGT-033", "F-MGT-034",
    "F-MGT-041", "F-MGT-042", "F-MGT-043",
)
def test_mgt_contract_surface():
    assert nav.menu("MGT").name == "경영관리"
    assert [s.screen_id for s in nav.menu("MGT").screens] == ["MGT-010", "MGT-020", "MGT-030", "MGT-040"]
    got = contracts.functions_of_menu("MGT")
    assert tuple(f.id for f in got) == MGT_FUNCTIONS
    assert sum(f.is_write for f in got) == 11
    assert {t for f in got for t in f.tables} == {
        "management_target", "management_target_version", "management_threshold",
        "management_action", "management_issue", "financial_import_batch", "financial_fact",
    }
