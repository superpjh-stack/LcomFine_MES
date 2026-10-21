# tests/test_qa3_security.py — QA3 G-19 권한 · G-20 세션 (tools/check_security.py 의 검사를 그대로 부른다)
# 임시 계정(접두 q3…)만 쓰고 끝나면 지운다. 시드 계정의 상태는 바꾸지 않는다(같은 DB 를 쓰는 다른 테스트의 세션을 끊지 않게).
import pytest

from tools import check_security as cs


@pytest.fixture(scope="module")
def lab():
    with cs.Lab() as lab_:
        yield lab_


def _assert(results):
    results = results if isinstance(results, list) else [results]
    bad = [r.line() for r in results if not r.ok]
    assert not bad, "\n".join(bad)


def test_g19_every_write_route_has_require_fn():
    _assert(cs.check_static_require_fn())


def test_g19_no_session_is_401():
    _assert(cs.check_no_session_401())


def test_g19_write_403_full_sweep(lab):
    _assert(cs.check_write_403(lab))


def test_g19_screen_403_and_menu_hidden(lab):
    _assert(cs.check_screen_403(lab))


@pytest.mark.fn("F-HOME-022")
@pytest.mark.fn("F-WO-012")
def test_g19_idor_other_department(lab):
    _assert(cs.check_idor(lab))


@pytest.mark.fn("F-SYS-021")
def test_g19_permission_cell_change_next_request(lab):
    _assert(cs.check_permission_change(lab))


@pytest.mark.fn("F-SYS-012")
@pytest.mark.fn("F-SYS-013")
def test_g20_session_rules(lab):
    _assert(cs.check_sessions(lab))
