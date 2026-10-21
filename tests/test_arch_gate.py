# tests/test_arch_gate.py — tools/gate.py 판정 규칙: 도구가 깨지면 찍다 만 PASS 를 통과로 보지 않는다
from tools import gate

OK = "G-05  쓰기 경계 스캔  PASS  0건\n"
BAD = "G-06  E2E 흐름  FAIL  2단계 422\n"


def test_rc0_keeps_pass():
    assert gate.tool_verdicts(0, OK)["G-05"][0] == gate.PASS


def test_nonzero_with_fail_row_keeps_other_pass():   # 종료코드 = FAIL 수 인 정상 종료
    v = gate.tool_verdicts(1, OK + BAD)
    assert v["G-05"][0] == gate.PASS and v["G-06"][0] == gate.FAIL


def test_nonzero_without_fail_row_downgrades_pass():
    v = gate.tool_verdicts(2, OK)
    assert v["G-05"][0] == gate.FAIL and "도구 종료코드 2" in v["G-05"][1]


def test_traceback_downgrades_pass_even_with_fail_row():
    v = gate.tool_verdicts(1, OK + BAD + "Traceback (most recent call last):\n  boom\n")
    assert v["G-05"][0] == gate.FAIL and "traceback" in v["G-05"][1]


def test_g12_wording_matches_goal():
    assert dict(gate.GATES)["G-12"] == "회차 교체" and len(gate.GATES) == 24
