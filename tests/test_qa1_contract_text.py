# tests/test_qa1_contract_text.py — QA1 계약 문장 대조: 계약(function-list.md) · 결정(decisions.md)이 화면에 보이라고 한 「미확정 (D-nn)」 이
# 화면 본문(<main>)에 보인다 — goal §2.7 「501 `미확정 (D-nn)` 명시 · 조용한 폴백 금지」. L3 낱말 대조는 자동 판정이 아니라 outputs/qa1-기능계약.md §4.
import pytest

from lcomfine.app import nav
from tools import check_screens as cs


@pytest.fixture(scope="module")
def admin():
    _, clients = cs.app_and_clients()
    return clients["admin"]


def _body(admin, screen_id: str) -> str:
    r = admin.get(nav.path_of(screen_id), headers=cs.HTML)
    assert r.status_code == 200, f"{screen_id} {r.status_code}"
    return cs._norm(" ".join(cs.parse(r.text).text))


@pytest.mark.fn("F-HOME-032", "F-HOME-031")
def test_home_030_shows_d518_and_d526(admin):
    """HOME-030: 메일·메신저 칸 `미확정 (D-518)` · 개인 추가 알림의 범위 `미확정 (D-526)` (Ruling 24 · decisions.md D-526)."""
    text = _body(admin, "HOME-030")
    for d in ("D-518", "D-526"):
        assert f"미확정({d})" in text, f"HOME-030 본문에 미확정 ({d}) 가 없다"


@pytest.mark.fn("F-PRD-041", "F-INS-041")
def test_loss_rate_screens_show_d519(admin):
    """PRD-040 · INS-040: 로스율 산식 `미확정 (D-519)` 와 원 수량을 함께 보인다 (D-519 「그동안」)."""
    for sid in ("PRD-040", "INS-040"):
        assert "미확정(D-519)" in _body(admin, sid), f"{sid} 본문에 미확정 (D-519) 가 없다"


@pytest.mark.fn("F-STD-024", "F-STD-064", "F-SHP-022")
def test_every_w1_screen_shows_its_contract_undecided(admin):
    """범위 화면 65(W1 49 + COL 7 + RPT 9) 전부: 계약 문장 · 결정의 「미확정 (D-nn)」 이 그 화면 본문에 보인다 (STD-020 · STD-060 D-519 · SHP-020 D-515 ·
    COL-010 · COL-050 · COL-060 D-516 · …). 조건부(TRK-030 D-516)는 test_qa1_col.py 가 조건을 만들어 본다."""
    missing = []
    checked = 0
    for s in nav.SCREENS:
        if s.common or s.menu_code in cs.LATER_MENUS:
            continue
        want = cs.undecided_expected(s.screen_id)
        if not want:
            continue
        checked += 1
        text = _body(admin, s.screen_id)
        gone = [d for d in want if f"미확정({d})" not in text]
        if gone:
            missing.append(f"{s.screen_id}: {gone}")
    assert checked >= 6, f"미확정이 걸린 화면이 {checked} 뿐이다"
    assert not missing, "\n".join(missing)
