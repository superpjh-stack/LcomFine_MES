"""데이터 질의(RPT-130) — 질문 → SQL(`ai`) → **검증** → 읽기 전용 실행 → `data_query_log` (D-513 · 가설 D-806 · 개발3 · W3).

    VIEWS                                        허용 뷰 8 → 부서 제한(None = 전 부서) — 수금 뷰 2 는 SL · AC · ADM · EX 만 (D-513)
    allowed_views(role_code) -> list[str]        그 부서가 질의할 수 있는 뷰
    validate_sql(sql, allowed_views) -> str      SELECT 한 문장만 통과 — 어긋나면 QueryRejected(이유). 라우터는 422 「허용되지 않는 질의 — 이유」
    ask(cur, user, question) -> dict             질문 하나를 끝까지(거부 · 실패 포함) 처리하고 `data_query_log` 1행을 남긴다

검증 규칙(D-806 — 전부 거부 = 실행하지 않는다):
  · 빈 질의 · NUL · 4000자 초과 · 끝의 세미콜론 하나는 떼고, 그 밖의 세미콜론 = 다중 문장
  · 주석(`--` `/*` `*/`) · 달러 따옴표(`$$`) · 큰따옴표 식별자 · 닫히지 않은 문자열
  · `SELECT` 로 시작하지 않는 문장 · CTE(`with`) · 쓰기 · DDL · 세션 명령(`set` `show` …) · `into` · `for update/share` · `lateral`
  · 카탈로그(`pg_*` · `information_schema` · `current_setting` 등) · 허용 목록 밖의 함수 호출(집계 · 날짜 · 글자 함수만 허용 — `pg_sleep` 등 거부)
  · `from` · `join` 뒤의 대상(쉼표 조인 포함)이 허용 뷰가 아니면 거부(스키마 한정 `public.x` 도 거부) · 허용 뷰를 하나도 읽지 않는 질의도 거부
실행: 별도 연결 · `set transaction read only` · `statement_timeout` · 행 수 상한(MAX_ROWS) — 그 밖 어떤 테이블에도 쓰지 않는다.
"""

from __future__ import annotations

import re
import time

import psycopg
from psycopg.rows import dict_row

from ..db import conn
from . import ai, numbering

#: 허용 뷰 → 질의할 수 있는 부서(None = 화면 R 이상 전원). 수금 뷰 2 는 정본 「영업·경리·관리자·경영진」(D-513)
COLLECTION_ROLES: tuple[str, ...] = ("SL", "AC", "ADM", "EX")
VIEWS: dict[str, tuple[str, ...] | None] = {
    "v_dq_orders": None, "v_dq_work_orders": None, "v_dq_stock": None, "v_dq_shipments": None,
    "v_dq_quality": None, "v_dq_production_daily": None,
    "v_dq_collections": COLLECTION_ROLES, "v_dq_receivables": COLLECTION_ROLES,
}
#: 실행 제한 (D-806)
MAX_ROWS = 200
STATEMENT_TIMEOUT_MS = 5000
SQL_MAX_CHARS = 4000
QUESTION_MAX_CHARS = 1000
#: sys_ai_call_log.kind
AI_KIND = "데이터 질의"
REJECT_PREFIX = "허용되지 않는 질의"

#: 허용 함수 — 집계 · 날짜 · 글자 · 수 (이 밖의 `이름(` 은 전부 거부)
ALLOWED_FUNCTIONS = frozenset("""
count sum avg min max coalesce nullif round trunc floor ceil ceiling abs greatest least
date_trunc to_char to_date extract date_part age now current_date current_timestamp make_date
lower upper trim ltrim rtrim btrim length char_length substr substring left right replace concat concat_ws position strpos
string_agg array_agg row_number rank dense_rank lag lead first_value last_value nth_value
cast
""".split())
#: SQL 낱말 — 식별자 검사에서 뺀다
KEYWORDS = frozenset("""
select from where join inner left right full outer cross on as and or not in exists is null true false
between like ilike similar any all some distinct having group order by asc desc nulls first last limit offset
union intersect except case when then else end over partition filter within rows range unbounded preceding following current row
interval date timestamp timestamptz numeric decimal integer int bigint text boolean varchar char double precision real
using natural fetch next only ties escape
""".split())
#: 거부 낱말 — 쓰기 · DDL · 세션 · 다중 문장 우회 · CTE · 잠금
FORBIDDEN = frozenset("""
insert update delete merge drop alter create truncate grant revoke copy call do execute prepare deallocate
set reset show into lock vacuum analyze explain listen notify unlisten refresh with returning for lateral
begin commit rollback savepoint release declare cursor import load security
""".split())
#: 카탈로그 · 시스템 접근
CATALOG_PATTERNS = (r"\bpg_\w*", r"\binformation_schema\b", r"\bcurrent_setting\b", r"\bset_config\b", r"\bcurrent_user\b",
                    r"\bsession_user\b", r"\bversion\s*\(", r"\binet_\w+", r"\bquery_to_xml\b", r"\bdblink\w*", r"\blo_\w+")

_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*|\d+(?:\.\d+)?|::|<>|<=|>=|!=|\|\||[(),;*+\-/<>=%.]|\S")
_STRING = re.compile(r"'(?:[^']|'')*'")
_FUNC = re.compile(r"\b([a-z_][a-z0-9_]*)\s*\(")


class QueryRejected(ValueError):
    """검증 거부 — 실행하지 않는다. str(exc) = 사유."""


def allowed_views(role_code: str) -> list[str]:
    return [v for v, roles in VIEWS.items() if roles is None or role_code in roles]


def _reject(reason: str) -> QueryRejected:
    return QueryRejected(reason)


def validate_sql(sql: str, allowed_views) -> str:
    """SELECT 한 문장 · 허용 뷰만 — 통과하면 정리된 SQL(끝 세미콜론 제거), 어긋나면 `QueryRejected(이유)`."""
    allowed = {v.lower() for v in allowed_views}
    if sql is None or not str(sql).strip():
        raise _reject("질의가 비어 있다")
    s = str(sql).strip()
    if "\x00" in s:
        raise _reject(f"쓸 수 없는 글자(NUL) · 원문 {len(s)}자")
    if len(s) > SQL_MAX_CHARS:
        raise _reject(f"{len(s)}자 — {SQL_MAX_CHARS}자까지")
    if s.endswith(";"):
        s = s[:-1].rstrip()
    scan = _STRING.sub("''", s)                 # 문자열 리터럴 속 글자는 문장이 아니다 — 검사는 리터럴을 비운 꼴로
    if "'" in scan.replace("''", ""):
        raise _reject("닫히지 않은 문자열")
    if ";" in scan:
        raise _reject("세미콜론 — 문장은 하나만")
    if "--" in scan or "/*" in scan or "*/" in scan:
        raise _reject("주석은 쓸 수 없다")
    if "$" in scan:
        raise _reject("달러 따옴표 · 매개변수 자리는 쓸 수 없다")
    if '"' in scan:
        raise _reject("큰따옴표 식별자는 쓸 수 없다")
    low = scan.lower()
    first = (re.findall(r"[a-z_]+", low) or ["?"])[0]
    if first != "select":
        raise _reject(f"SELECT 문장만 실행한다 — `{first}` 로 시작하는 문장은 거부")
    for pat in CATALOG_PATTERNS:
        if re.search(pat, low):
            raise _reject("시스템 카탈로그 · 설정에는 접근할 수 없다")
    tokens = [t for t in _TOKEN.findall(scan)]
    words = [t.lower() for t in tokens if re.match(r"^[A-Za-z_]", t)]
    for w in words:
        if w in FORBIDDEN:
            raise _reject(f"`{w}` 는 쓸 수 없다 (SELECT 한 문장 · CTE 없음 · 쓰기 · 세션 명령 금지)")
    for fn in _FUNC.findall(low):
        if fn in KEYWORDS:
            continue
        if fn not in ALLOWED_FUNCTIONS:
            raise _reject(f"함수 `{fn}()` 은 허용되지 않는다")
    # from · join 뒤의 대상 (쉼표 조인 · 별칭 포함)
    refs: list[str] = []
    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i].lower()
        if tok in ("from", "join"):
            j = i + 1
            while True:
                if j >= n:
                    raise _reject("조회 대상이 없다")
                if tokens[j] == "(":            # 하위 질의 — 그 안의 from 은 뒤에서 다시 검사된다
                    break
                ident = tokens[j].lower()
                if not re.match(r"^[a-z_]", ident) or ident in KEYWORDS:
                    raise _reject("조회 대상이 없다")
                refs.append(ident)
                j += 1
                if j < n and tokens[j].lower() == "as":
                    j += 1
                if j < n and re.match(r"^[A-Za-z_]", tokens[j]) and tokens[j].lower() not in KEYWORDS and tokens[j].lower() not in FORBIDDEN:
                    j += 1                      # 별칭
                if j < n and tokens[j] == ",":
                    j += 1
                    continue
                break
            i = j
            continue
        i += 1
    if not refs:
        raise _reject("허용 뷰를 하나도 읽지 않는다")
    for ref in refs:
        if "." in ref:
            raise _reject(f"`{ref}` — 스키마를 붙인 이름은 쓸 수 없다")
        if ref not in allowed:
            if ref in VIEWS:
                raise _reject(f"`{ref}` 는 이 부서가 질의할 수 없는 뷰다 (영업부 · 회계부 · 전산 관리자 · 경영진만)")
            raise _reject(f"`{ref}` 는 허용 뷰가 아니다 (허용: {', '.join(sorted(allowed))})")
    return s


def view_columns(views: list[str]) -> dict[str, list[str]]:
    """허용 뷰의 열 이름 — AI 에 주는 스키마 설명(앱이 읽는 카탈로그 조회 · 질의 자체는 아니다)."""
    rows = conn.q(
        """select table_name, column_name from information_schema.columns
            where table_schema = 'public' and table_name = any(%s) order by table_name, ordinal_position""", (views,))
    out: dict[str, list[str]] = {v: [] for v in views}
    for r in rows:
        out[r["table_name"]].append(r["column_name"])
    return out


def system_prompt(views: list[str]) -> str:
    cols = view_columns(views)
    lines = [f"- {v}({', '.join(cols[v])})" for v in views]
    return ("당신은 PostgreSQL SELECT 문을 만드는 도우미다. 아래 뷰만 읽을 수 있다. 다른 테이블 · 카탈로그 · 함수(집계 · 날짜 · 글자 함수 제외)는 쓰지 않는다.\n"
            "규칙: SELECT 한 문장만 · CTE(with) 없음 · 세미콜론 · 주석 없음 · 큰따옴표 식별자 없음 · 결과는 200행 이하(limit) · 설명 없이 SQL 만 답한다.\n"
            "허용 뷰:\n" + "\n".join(lines))


NUL_GLYPH = "\\x00"


def _strip_fence(text: str) -> str:
    """AI 응답 → SQL 글자: 코드 펜스를 벗기고 NUL(0x00) 은 표시 글자 `\\x00` 로 바꾼다 — PostgreSQL text 열(`data_query_log.sql_text`)은
    NUL 을 담지 못한다(DEF-QA3-005). NUL 이 있었는지는 `ask` 가 원문으로 따로 본다(거부)."""
    t = (text or "").replace("\x00", NUL_GLYPH).strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
        t = re.sub(r"\s*```\s*$", "", t)
    return t.strip()


def _run_readonly(sql: str) -> tuple[list[str], list[dict], bool]:
    """별도 연결 · 읽기 전용 트랜잭션 · statement_timeout · 행 수 상한. (열, 행, 잘렸는가). DB 오류는 그대로 올라간다."""
    try:
        pg = psycopg.connect(conn.dsn(), row_factory=dict_row)
    except psycopg.Error as exc:
        raise conn.unavailable(exc) from None
    try:
        with pg.cursor() as cur:
            cur.execute("set transaction read only")
            cur.execute(f"set local statement_timeout = {int(STATEMENT_TIMEOUT_MS)}")
            cur.execute(sql)
            columns = [d.name for d in (cur.description or [])]
            rows = [dict(r) for r in cur.fetchmany(MAX_ROWS + 1)]
        pg.rollback()
    finally:
        pg.close()
    truncated = len(rows) > MAX_ROWS
    return columns, rows[:MAX_ROWS], truncated


def ask(cur, user, question: str) -> dict:
    """질문 하나 — AI → 검증 → 실행 — 결과 또는 거부 · 실패를 **전부 `data_query_log` 에 1행** 으로 남긴다(거부 포함 · D-513).

    반환 {"query_no", "question", "sql": str | None, "ok": bool, "columns": [...], "rows": [...], "row_count": int | None,
          "truncated": bool, "error": str | None, "ms": int, "views": [허용 뷰]}
    `cur` = 쓰기 트랜잭션 커서(`data_query_log` · `sys_ai_call_log` 를 여기에 쓴다). 실행은 별도 읽기 전용 연결이다.
    AI 키 없음 · 호출 실패 · 검증 거부 · 실행 실패는 예외가 아니라 `ok=False` + `error` 로 돌려준다 — 로그가 남은 뒤 라우터가 422 로 올린다.
    """
    t0 = time.monotonic()
    views = allowed_views(user.role_code)
    query_no = numbering.next(numbering.DQ, cur)
    out: dict = {"query_no": query_no, "question": question, "sql": None, "ok": False, "columns": [], "rows": [],
                 "row_count": None, "truncated": False, "error": None, "ms": 0, "views": views}
    sql: str | None = None
    had_nul = False
    try:
        raw = ai.complete(system_prompt(views), question, kind=AI_KIND, cur=cur, user_id=user.id)
        had_nul = "\x00" in (raw or "")
        sql = _strip_fence(raw)              # NUL 은 표시 글자로 — 로그 · 화면 · 422 fields 어디에도 NUL 원문이 가지 않는다(DEF-QA3-005)
        out["sql"] = sql
    except ai.NotConfigured as exc:
        out["error"] = str(exc)
    except ai.CallFailed as exc:
        out["error"] = f"AI 호출 실패 — {exc}"
    if sql is not None:
        if had_nul:                          # 원문에 NUL — 검증 전에 거부(validate_sql 도 같은 이유로 거부한다 · 심층 방어)
            out["error"] = f"{REJECT_PREFIX} — 쓸 수 없는 글자(NUL) · 원문 {len(raw)}자"
        else:
            try:
                clean = validate_sql(sql, views)
            except QueryRejected as exc:
                out["error"] = f"{REJECT_PREFIX} — {exc}"
            else:
                try:
                    columns, rows, truncated = _run_readonly(clean)
                except psycopg.Error as exc:
                    msg = str(getattr(exc, "diag", None) and exc.diag.message_primary or exc).strip()
                    out["error"] = f"실행 실패 — {msg[:300]}"
                else:
                    out.update({"ok": True, "columns": columns, "rows": rows, "row_count": len(rows), "truncated": truncated})
    out["ms"] = int((time.monotonic() - t0) * 1000)
    cur.execute(
        """insert into data_query_log (query_no, user_id, role_code, question, sql_text, ok, row_count, error, ms)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (query_no, user.id, user.role_code, question, out["sql"], out["ok"], out["row_count"], out["error"], out["ms"]))
    return out


def recent(user, limit: int = 20) -> list[dict]:
    """최근 질의(그 사용자) — 화면의 「최근 질의」 목록. 읽기만."""
    return conn.q(
        """select query_no, question, sql_text, ok, row_count, error, ms, created_at
             from data_query_log where user_id = %s order by id desc limit %s""", (user.id, limit))
