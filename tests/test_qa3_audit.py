# tests/test_qa3_audit.py — QA3 G-21 비밀 · G-22 감사 로그
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


def test_g21_no_secrets_and_seed_examples():
    _assert(cs.check_secrets())


@pytest.mark.fn("F-SYS-041")
def test_g22_change_and_access_log(lab):
    _assert(cs.check_change_log(lab))


def test_g22_every_post_calls_log_change():
    _assert(cs.check_static_log_change())
