"""채번 — Job · 생산 LOT · 원재료 LOT · 롤 · 출하 LOT · COA 번호를 내는 **한 곳** (G-08 · decisions.md D-05).

담당 **개발1**. 형식은 코드에 박지 않는다. `sys_number_rule`(접두 · 날짜 형식 · 자릿수) 행이 형식이고
`sys_number_seq` 가 카운터다. 채번 규칙이 확정되면(D-05) 행만 바꾼다. 다른 모듈은 번호를 직접 조립하지 않는다.

    번호 = prefix + to_char(기준 시각, date_format) + 일련번호(seq_digits 자리, 0 채움)

- 구분 기호(`-`)는 따로 두지 않는다. 필요하면 `prefix` 나 `date_format` 안에 글자로 넣는다(예: `YYMMDD-`).
- 카운터 범위(`seq_scope`)는 **날짜 부분의 값**이다 — 날짜 부분이 바뀌면 1 부터 다시 센다. 날짜 형식이 비어 있으면 범위는 빈 글자(통산).
- 일련번호가 자릿수를 넘으면 자르지 않고 자릿수를 늘린다(같은 번호가 두 번 나오지 않는 것이 먼저다).
- 가설 형식과 시드 6행은 `progress-dev1.md` §1 · `db/seed_dev1.py` (D-101).
"""

from __future__ import annotations

from datetime import datetime

from ..db import conn

#: 번호 종류 — sys_number_rule.seq_kind
JOB, JOB_LOT, MAT_LOT, ROLL, SHIPMENT, COA = "JOB", "JOB_LOT", "MAT_LOT", "ROLL", "SHIPMENT", "COA"
KINDS: tuple[str, ...] = (JOB, JOB_LOT, MAT_LOT, ROLL, SHIPMENT, COA)

# 형식 행과 그 시각의 날짜 부분을 한 번에 읽는다. 날짜 부분은 DB 의 to_char 가 만든다(형식 열이 to_char 형식이다).
_RULE_SQL = """
select seq_kind, prefix, date_format, seq_digits,
       case when date_format = '' then ''
            else to_char(coalesce(%(at)s::timestamptz, now()), date_format) end as date_part
  from sys_number_rule
 where seq_kind = %(kind)s
"""

# 카운터 행을 잠그고 올린다. 같은 (종류, 범위)를 동시에 부르면 뒤에 온 쪽이 앞의 커밋/롤백을 기다린다.
_BUMP_SQL = """
insert into sys_number_seq (seq_kind, seq_scope, last_value) values (%s, %s, 1)
on conflict (seq_kind, seq_scope) do update set last_value = sys_number_seq.last_value + 1
returning last_value
"""


def _check_kind(kind: str) -> None:
    if kind not in KINDS:
        raise ValueError(f"번호 종류가 아니다: {kind!r} — {', '.join(KINDS)} 중 하나")


def _compose(rule_row: dict, value: int) -> str:
    return f"{rule_row['prefix']}{rule_row['date_part']}{str(value).zfill(rule_row['seq_digits'])}"


def _missing(kind: str) -> RuntimeError:
    return RuntimeError(f"sys_number_rule 에 {kind} 형식 행이 없다 — `uv run python -m lcomfine.db.seed_dev1` (D-05)")


def _next_in(cur, kind: str, at: datetime | None) -> str:
    cur.execute(_RULE_SQL, {"kind": kind, "at": at})
    rule_row = cur.fetchone()
    if rule_row is None:
        raise _missing(kind)
    cur.execute(_BUMP_SQL, (kind, rule_row["date_part"]))
    return _compose(rule_row, cur.fetchone()["last_value"])


def next(kind: str, *, cur=None, at: datetime | None = None) -> str:  # noqa: A001 — 계약상 이름
    """다음 번호를 **발번**한다(카운터 +1). 동시에 불러도 같은 번호가 두 번 나오지 않는다(카운터 행 잠금).

    kind  KINDS 중 하나. 아니면 ValueError.
    cur   `conn.tx()` 의 커서. 주면 그 트랜잭션 안에서 발번한다(업무 행과 함께 롤백된다). 없으면 자체 트랜잭션.
    at    날짜 부분의 기준 시각. 기본 now().
    `sys_number_rule` 에 그 종류의 행이 없으면 422 가 아니라 **RuntimeError** — 설정 누락은 사용자 입력 오류가 아니다.
    """
    _check_kind(kind)
    if cur is not None:
        return _next_in(cur, kind, at)
    with conn.tx() as own:
        return _next_in(own, kind, at)


def peek(kind: str, *, at: datetime | None = None) -> str:
    """다음에 나올 번호를 **발번하지 않고** 보여 준다(등록 화면의 미리보기용). 그 사이 다른 사람이 발번하면 달라진다."""
    _check_kind(kind)
    rule_row = conn.q1(_RULE_SQL, {"kind": kind, "at": at})
    if rule_row is None:
        raise _missing(kind)
    seq = conn.q1("select last_value from sys_number_seq where seq_kind = %s and seq_scope = %s",
                  (kind, rule_row["date_part"]))
    return _compose(rule_row, (seq["last_value"] if seq else 0) + 1)


def rule(kind: str) -> dict | None:
    """그 종류의 형식 행(`sys_number_rule`). 없으면 None — 화면은 `미확정 (D-05)` 를 보여 준다."""
    _check_kind(kind)
    return conn.q1("""select seq_kind, prefix, date_format, seq_digits, note, updated_at, updated_by
                        from sys_number_rule where seq_kind = %s""", (kind,))
