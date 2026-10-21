# tests/test_qa3_robustness.py — QA3 조용한 실패 사냥 (DB 끊김 · 이상한 입력) · G-24 Dockerfile 정적 검사
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


def test_db_down_is_503_not_silent(lab):
    _assert(cs.check_db_down(lab))


def test_malformed_inputs_are_422_not_500(lab):
    _assert(cs.check_malformed(lab))


def test_g24_docker_static():
    """compose 문법 · openpyxl 설치 · Dockerfile 의 COPY 원본이 전부 있다(없으면 이미지 빌드가 실패한다)."""
    _assert(cs.check_docker())


@pytest.mark.fn("F-BAS-011")
@pytest.mark.fn("F-BAS-021")
@pytest.mark.fn("F-WO-011")
@pytest.mark.fn("F-SYS-031")
def test_nul_input_names_the_field(lab):
    """DEF-QA3-002 — api-contract §3: 사람이 읽을 문장(어느 항목인지)은 라우터가 먼저 검사해서 준다 · 핸들러의 `입력` 한 줄은 마지막 방어선.
    개발2 의 MAT-010 은 `공급사: 글자에 NUL…` 로 항목을 짚는다 — 개발1 의 쓰기도 같아야 한다."""
    cases = {label: (role, path, body) for label, role, path, body, _ in cs.malformed_cases(lab)
             if label in ("품목 코드 NUL", "거래처명 NUL", "의뢰 비고 NUL", "공통코드 NUL", "원자재 입고 공급사 NUL")}
    generic = []
    for label, (role, path, body) in cases.items():
        r = lab.client(role).post(path, data=body)
        assert r.status_code == 422, f"{label} {r.status_code}"
        names = [f["name"] for f in r.json().get("fields", [])]
        if names == ["입력"]:
            generic.append(f"{label} ({path}) → fields {names}")
    assert not generic, "항목을 짚지 않는 NUL 422:\n" + "\n".join(generic)
