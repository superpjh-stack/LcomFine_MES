"""채번 — Job · 생산 LOT · 원재료 LOT · 롤 · 출하 LOT · COA 번호를 내는 **한 곳** (G-08 · decisions.md D-05).

담당 **개발1**. 아키텍트가 만든 것은 시그니처뿐이다 — 본문은 개발1 이 R1 에서 가장 먼저 채우고,
가설 형식을 `progress-dev1.md` §1 에 공표한다(개발2·3 이 기다린다).

형식은 코드에 박지 않는다. `sys_number_rule`(접두 · 날짜 형식 · 자릿수) 행이 형식이고 `sys_number_seq` 가 카운터다.
채번 규칙이 확정되면(D-05) 행만 바꾼다. 다른 모듈은 번호를 직접 조립하지 않는다.
"""

from __future__ import annotations

from datetime import datetime

#: 번호 종류 — sys_number_rule.seq_kind
JOB, JOB_LOT, MAT_LOT, ROLL, SHIPMENT, COA = "JOB", "JOB_LOT", "MAT_LOT", "ROLL", "SHIPMENT", "COA"
KINDS: tuple[str, ...] = (JOB, JOB_LOT, MAT_LOT, ROLL, SHIPMENT, COA)

_TODO = "미구현 — 담당 개발1 (app/numbering.py)"


def next(kind: str, *, cur=None, at: datetime | None = None) -> str:  # noqa: A001 — 계약상 이름
    """다음 번호를 **발번**한다(카운터 +1). 동시에 불러도 같은 번호가 두 번 나오지 않는다(카운터 행 잠금).

    kind  KINDS 중 하나. 아니면 ValueError.
    cur   `conn.tx()` 의 커서. 주면 그 트랜잭션 안에서 발번한다(업무 행과 함께 롤백된다). 없으면 자체 트랜잭션.
    at    날짜 부분의 기준 시각. 기본 now().
    `sys_number_rule` 에 그 종류의 행이 없으면 422 가 아니라 **RuntimeError** — 설정 누락은 사용자 입력 오류가 아니다.
    """
    raise NotImplementedError(_TODO)


def peek(kind: str, *, at: datetime | None = None) -> str:
    """다음에 나올 번호를 **발번하지 않고** 보여 준다(등록 화면의 미리보기용)."""
    raise NotImplementedError(_TODO)


def rule(kind: str) -> dict | None:
    """그 종류의 형식 행(`sys_number_rule`). 없으면 None — 화면은 `미확정 (D-05)` 를 보여 준다."""
    raise NotImplementedError(_TODO)
