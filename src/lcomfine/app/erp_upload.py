"""ERP 수금현황 엑셀 업로드 — 열 매핑 · 검증 · 회차 교체를 하는 **한 곳** (개발3 · `contracts/interfaces.md` §9 · D-516 · D-802).

정본 COL-010: 「ERP 에서 내려받은 수금현황 엑셀을 양식 변환 없이 그대로 올린다 · 처음 한 번 열 이름 매핑을 저장해 두고 다음부터
자동 적용한다 · 검증: 필수 열, 숫자·날짜 형식, 거래처 코드 매핑 여부. 오류 행은 반영에서 뺀다 · 같은 기준 기간을 다시 올리면
이전 회차를 새 회차로 바꾼다. 이전 회차는 지우지 않고 이력에 남는다 · MES 는 수금 데이터를 고치지 않는다」.

    read_xlsx(file: bytes) -> list[dict]                    첫 시트 · 1행 = 열 이름 · 행마다 {열 이름: 글자} (+ "__row_no" 엑셀 행 번호)
    headers(file: bytes) -> list[str]                        첫 시트의 열 이름 (매핑 화면의 선택지)
    column_map() -> dict[str, str]                           MES 항목 → 엑셀 열 이름 (`erp_column_map`)
    save_column_map(cur, mapping, user) -> int               열 매핑 저장 (처음 한 번 · 다시 저장하면 바꾼다) — 바뀐 항목 수
    validate(rows, cmap, customer_map=None) -> list[dict]    행마다 {"row_no", "raw", "parsed", "error"} — error 가 있으면 반영 제외
    apply(cur, period_from, period_to, rows, user, *, source_file="") -> int   회차 등록 · 같은 기간의 이전 회차 교체 — 새 회차 id
    remap(cur, batch_id=None, erp_code=None, user=None) -> dict                 매핑 뒤 재해석 — {reviewed, changed, applied, still_error}

열 구성은 사람이 정하지 않았다(D-516 차단) — `erp_column_map` 이 흡수한다. 필드 7 (`FIELDS`)의 이름은 `db-schema.md` 의
`erp_upload_row.parsed` 키와 같다. 필수 = 거래처코드 · 일자 · (매출액 또는 수금액 중 하나 이상). 그 밖 열이 매핑되지 않으면
그 열을 쓰는 화면(COL-050 · COL-060 의 매출 · 잔액)은 `미확정 (D-516)` 이다.
**조용한 실패 금지** — 파일 · 열 · 값의 문제는 `UploadError`(라우터가 422 로 바꾼다) 또는 행의 `error` 로 드러난다.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from ..db import conn
from . import nav, notify, numbering

#: MES 항목 7 (erp_upload_row.parsed 의 키 · erp_column_map.field) → 화면 이름. 순서 = 화면 순서
FIELDS: dict[str, str] = {
    "customer_code": "거래처코드",
    "txn_date": "일자",
    "sales_amount": "매출액",
    "collected_amount": "수금액",
    "balance_amount": "잔액",
    "method": "수단",
    "bill_due_date": "어음 만기",
}
#: 열 단위 필수 — 이 항목이 매핑되지 않으면 업로드할 수 없다 (D-802)
REQUIRED_FIELDS: tuple[str, ...] = ("customer_code", "txn_date")
#: 금액 열은 둘 중 하나 이상 매핑되어야 한다 (D-802)
AMOUNT_FIELDS: tuple[str, ...] = ("sales_amount", "collected_amount")
DATE_FIELDS: tuple[str, ...] = ("txn_date", "bill_due_date")
NUMBER_FIELDS: tuple[str, ...] = ("sales_amount", "collected_amount", "balance_amount")
#: 거래처 미매핑 오류 문장의 머리 — 미매핑 목록 · 재해석이 이 글자로 찾는다
UNMAPPED_PREFIX = "거래처 코드 미매핑"
#: 파일 크기 상한 (D-802)
MAX_BYTES = 20 * 1024 * 1024
#: numeric(16,2) 가 담을 수 있는 가장 큰 수 + 1
_AMOUNT_LIMIT = Decimal("100000000000000")
_DATE_PATTERNS = (
    re.compile(r"^(\d{4})[-./](\d{1,2})[-./](\d{1,2})$"),
    re.compile(r"^(\d{4})(\d{2})(\d{2})$"),
)
DECISION = "D-516"


class UploadError(ValueError):
    """파일 · 열 매핑 수준의 오류 — 라우터가 422 로 바꾼다. `field` 는 사람이 읽는 항목 이름."""

    def __init__(self, field: str, reason: str, message: str | None = None) -> None:
        super().__init__(message or f"{field}: {reason}")
        self.field = field
        self.reason = reason
        self.message = message or f"{field}: {reason}"


# ── 엑셀 읽기 ────────────────────────────────────────────────────────────

def _cell_text(v) -> str:
    """원문 보존 — 날짜 셀은 ISO, 수는 글자로. None 은 빈 글자."""
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.date().isoformat() if (v.hour, v.minute, v.second) == (0, 0, 0) else v.isoformat(sep=" ")
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def _sheet(file: bytes) -> tuple[list[str], list[dict]]:
    if not file:
        raise UploadError("파일", "빈 파일입니다")
    if len(file) > MAX_BYTES:
        raise UploadError("파일", f"{MAX_BYTES // (1024 * 1024)}MB 이하만 올릴 수 있습니다")
    try:
        wb = load_workbook(io.BytesIO(file), read_only=True, data_only=True)
    except (zipfile.BadZipFile, InvalidFileException, KeyError, OSError, ValueError) as exc:
        raise UploadError("파일", f"엑셀(.xlsx) 파일이 아닙니다 [{type(exc).__name__}]") from None
    try:
        ws = wb.worksheets[0]
        it = ws.iter_rows(values_only=True)
        try:
            head = next(it)
        except StopIteration:
            raise UploadError("파일", "첫 시트에 열 이름 행이 없습니다") from None
        headers = [_cell_text(h) for h in head]
        if not any(headers):
            raise UploadError("파일", "첫 시트의 1행(열 이름)이 비어 있습니다")
        if "__row_no" in headers:
            raise UploadError("파일", "열 이름 `__row_no` 는 쓸 수 없습니다")
        seen: dict[str, int] = {}
        for h in headers:
            if h:
                seen[h] = seen.get(h, 0) + 1
        dup = [h for h, n in seen.items() if n > 1]
        if dup:
            raise UploadError("파일", f"같은 열 이름이 두 번 있습니다: {', '.join(dup[:5])}")
        rows: list[dict] = []
        for idx, values in enumerate(it, start=2):
            texts = [_cell_text(v) for v in values]
            if not any(texts):
                continue                                  # 완전히 빈 줄은 세지 않는다
            row = {"__row_no": idx}
            for h, t in zip(headers, texts):
                if h:
                    row[h] = t
            rows.append(row)
    finally:
        wb.close()
    return [h for h in headers if h], rows


def read_xlsx(file: bytes) -> list[dict]:
    """첫 시트를 읽는다. 1행 = 열 이름. 돌려주는 행은 {열 이름: 글자, "__row_no": 엑셀 행 번호}. 빈 줄은 건너뛴다."""
    return _sheet(file)[1]


def headers(file: bytes) -> list[str]:
    """첫 시트의 열 이름(빈 열 제외)."""
    return _sheet(file)[0]


# ── 열 매핑 (erp_column_map) ──────────────────────────────────────────────

def column_map() -> dict[str, str]:
    """MES 항목 → 엑셀 열 이름. 저장된 것이 없으면 빈 dict (화면은 매핑을 먼저 받는다)."""
    return {r["field"]: r["column_name"] for r in conn.q("select field, column_name from erp_column_map order by id")}


def column_map_in(cur) -> dict[str, str]:
    cur.execute("select field, column_name from erp_column_map order by id")
    return {r["field"]: r["column_name"] for r in cur.fetchall()}


def check_map(cmap: dict[str, str], file_headers: list[str] | None = None) -> None:
    """필수 항목 · 금액 항목 매핑과(파일을 주면) 열 존재를 확인한다. 어긋나면 UploadError."""
    for f in REQUIRED_FIELDS:
        if not cmap.get(f):
            raise UploadError(FIELDS[f], "열 매핑이 없습니다 — 먼저 열 매핑을 저장해 주세요", f"열 매핑이 없습니다 — {FIELDS[f]}")
    if not any(cmap.get(f) for f in AMOUNT_FIELDS):
        raise UploadError("매출액·수금액", "둘 중 하나 이상 열 매핑이 있어야 합니다", "열 매핑이 없습니다 — 매출액 또는 수금액")
    if file_headers is not None:
        missing = [(FIELDS[f], col) for f, col in cmap.items() if col and col not in file_headers]
        if missing:
            label, col = missing[0]
            raise UploadError(label, f"파일에 열 '{col}' 이 없습니다 — 열 매핑을 다시 저장하거나 파일을 확인해 주세요",
                              f"파일에 매핑된 열이 없습니다 — {label} ← '{col}'")


def save_column_map(cur, mapping: dict[str, str | None], user) -> int:
    """열 매핑 저장 — 값이 있는 항목은 upsert, 빈 항목은 지운다. 필수 · 금액 규칙(check_map)에 어긋나면 UploadError.
    같은 열 이름을 두 항목에 매핑하면 UploadError."""
    clean = {f: (mapping.get(f) or "").strip() for f in FIELDS}
    check_map({f: c for f, c in clean.items() if c})
    used: dict[str, str] = {}
    for f, c in clean.items():
        if c and c in used:
            raise UploadError(FIELDS[f], f"'{c}' 은(는) {FIELDS[used[c]]} 에 이미 매핑했습니다")
        if c:
            used[c] = f
    n = 0
    for f, c in clean.items():
        if c:
            cur.execute("""insert into erp_column_map (field, column_name, created_by) values (%s, %s, %s)
                           on conflict (field) do update set column_name = excluded.column_name, updated_at = now(),
                                                             updated_by = excluded.created_by
                            where erp_column_map.column_name is distinct from excluded.column_name""",
                        (f, c, user.login_id))
        else:
            cur.execute("delete from erp_column_map where field = %s", (f,))
        n += cur.rowcount
    return n


# ── 값 해석 ──────────────────────────────────────────────────────────────

def parse_date(text: str) -> date:
    t = (text or "").strip()
    for pat in _DATE_PATTERNS:
        m = pat.match(t)
        if m:
            try:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                break
    if " " in t:                                           # 날짜 + 시각(엑셀 날짜 셀) — 날짜만
        try:
            return parse_date(t.split(" ", 1)[0])
        except ValueError:
            pass
    raise ValueError(f"날짜 형식이 아닙니다 '{t[:30]}' (YYYY-MM-DD)")


def parse_amount(text: str) -> Decimal | None:
    t = (text or "").strip().replace(",", "").replace(" ", "")
    if not t or t == "-":
        return None
    neg = t.startswith("(") and t.endswith(")")
    if neg:
        t = t[1:-1]
    try:
        v = Decimal(t)
    except InvalidOperation:
        raise ValueError(f"숫자가 아닙니다 '{text.strip()[:30]}'") from None
    if not v.is_finite():
        raise ValueError(f"숫자가 아닙니다 '{text.strip()[:30]}'")
    if abs(v) >= _AMOUNT_LIMIT:
        raise ValueError(f"저장할 수 있는 범위를 넘었습니다 '{text.strip()[:30]}'")
    return (-v if neg else v).quantize(Decimal("0.01"))


def active_customer_map(cur=None) -> dict[str, int]:
    """사용 중(use_yn = 'Y')인 ERP 코드 → MES 거래처 id."""
    sql = "select erp_code, customer_id from erp_customer_map where use_yn = 'Y'"
    if cur is None:
        rows = conn.q(sql)
    else:
        cur.execute(sql)
        rows = cur.fetchall()
    return {r["erp_code"]: r["customer_id"] for r in rows}


def _validate_one(raw: dict, cmap: dict[str, str], customer_map: dict[str, int]) -> tuple[dict, str | None]:
    parsed: dict = {}
    problems: list[str] = []
    for f, col in cmap.items():
        if not col:
            continue
        text = (raw.get(col) or "").strip()
        label = FIELDS[f]
        if f in REQUIRED_FIELDS and not text:
            problems.append(f"{label}: 필수 항목이 비어 있습니다")
            continue
        if not text:
            continue
        try:
            if f in DATE_FIELDS:
                parsed[f] = parse_date(text).isoformat()
            elif f in NUMBER_FIELDS:
                v = parse_amount(text)
                if v is not None:
                    parsed[f] = str(v)
            else:
                if "\x00" in text:
                    raise ValueError("글자에 NUL(0x00)을 넣을 수 없습니다")
                parsed[f] = text[:200]
        except ValueError as exc:
            problems.append(f"{label}: {exc}")
    code = parsed.get("customer_code")
    if code and code not in customer_map:
        problems.append(f"{UNMAPPED_PREFIX}: {code}")
    return parsed, (" · ".join(problems) if problems else None)


def validate(rows: list[dict], cmap: dict[str, str], customer_map: dict[str, int] | None = None) -> list[dict]:
    """행마다 `parsed`(매핑 적용 값 · 오류 항목은 빠진다) 와 `error`(없으면 None). 열 매핑이 모자라면 UploadError.
    `customer_map` 을 주지 않으면 DB 의 사용 중 매핑을 읽는다."""
    check_map(cmap)
    cm = active_customer_map() if customer_map is None else customer_map
    out = []
    for raw in rows:
        parsed, error = _validate_one(raw, cmap, cm)
        out.append({"row_no": raw.get("__row_no"), "raw": {k: v for k, v in raw.items() if k != "__row_no"},
                    "parsed": parsed, "error": error})
    return out


# ── 회차 반영 · 교체 (G-12 · G-13) ──────────────────────────────────────────

def error_link(batch_id: int) -> str:
    """`erp_upload_error` 알림의 link — 그 회차의 오류 행을 보는 업로드 이력(COL-020)."""
    return f"{nav.path_of('COL-020')}?batch={batch_id}"


def apply(cur, period_from: date, period_to: date, rows: list[dict], user, *, source_file: str = "") -> int:
    """검증된 행(`validate` 의 결과)을 새 회차로 넣는다 — **쓰기 트랜잭션의 커서** 안에서.

    같은 (period_from, period_to) 의 `반영` 회차가 있으면 그 회차를 `교체`(replaced_by = 새 회차)로 바꾸고 행은 그대로 둔다(G-12).
    오류 행도 저장하지만 `error` 가 있어 집계에서 빠진다(G-13). 오류 · 미매핑 행이 하나라도 있으면 같은 트랜잭션에서
    `notify.emit("erp_upload_error")` → 회계부(D-511). 반환 = 새 회차 id.
    """
    if period_from > period_to:
        raise UploadError("기준 기간", f"시작일이 종료일보다 늦습니다 ({period_from} > {period_to})")
    if not rows:
        raise UploadError("파일", "읽은 데이터 행이 없습니다 (열 이름 행만 있음)")
    cur.execute("""select id, batch_no, round_no from erp_upload_batch
                    where period_from = %s and period_to = %s order by round_no for update""", (period_from, period_to))
    previous = cur.fetchall()              # 이 기간의 모든 회차 (반영 1 + 교체 n)
    cur.execute("select id from erp_upload_batch where period_from = %s and period_to = %s and status = '반영'",
                (period_from, period_to))
    live_row = cur.fetchone()
    round_no = (max(p["round_no"] for p in previous) + 1) if previous else 1
    batch_no = numbering.next(numbering.ERP, cur)
    error_count = sum(1 for r in rows if r["error"])
    if live_row is None:
        cur.execute(
            """insert into erp_upload_batch (batch_no, period_from, period_to, round_no, status, source_file, row_count,
                                             error_count, created_by)
               values (%s, %s, %s, %s, '반영', %s, %s, %s, %s) returning id""",
            (batch_no, period_from, period_to, round_no, source_file[:200] or "(이름 없음)", len(rows), error_count,
             user.login_id))
        new_id = cur.fetchone()["id"]
    else:
        # 기간마다 `반영` 은 하나(부분 유니크) · `교체` ⇔ replaced_by(check) 라서 세 단계로 바꾼다 — 중간 상태도 제약을 지킨다
        old_id = live_row["id"]
        cur.execute(
            """insert into erp_upload_batch (batch_no, period_from, period_to, round_no, status, replaced_by, source_file,
                                             row_count, error_count, created_by)
               values (%s, %s, %s, %s, '교체', %s, %s, %s, %s, %s) returning id""",
            (batch_no, period_from, period_to, round_no, old_id, source_file[:200] or "(이름 없음)", len(rows),
             error_count, user.login_id))
        new_id = cur.fetchone()["id"]
        cur.execute("""update erp_upload_batch set status = '교체', replaced_by = %s, updated_at = now(), updated_by = %s
                        where id = %s""", (new_id, user.login_id, old_id))
        cur.execute("""update erp_upload_batch set status = '반영', replaced_by = null where id = %s""", (new_id,))
        notify.resolve_by_link(cur, error_link(old_id), user)         # 교체된 회차의 오류 알림은 수신 부서와 무관하게 닫힌다(DEF-QA1-006)
    for r in rows:
        cur.execute(
            """insert into erp_upload_row (batch_id, row_no, raw, parsed, error, created_by)
               values (%s, %s, %s::jsonb, %s::jsonb, %s, %s)""",
            (new_id, r["row_no"], json.dumps(r["raw"], ensure_ascii=False),
             json.dumps(r["parsed"], ensure_ascii=False) if r["parsed"] is not None else None, r["error"], user.login_id))
    if error_count:
        unmapped = sorted({r["parsed"].get("customer_code") for r in rows
                           if r["error"] and UNMAPPED_PREFIX in r["error"] and r["parsed"].get("customer_code")})
        text = f"ERP 업로드 {batch_no} ({period_from}~{period_to}) — 오류·미매핑 {error_count}행 / {len(rows)}행"
        if unmapped:
            text += f" · 미매핑 거래처 코드 {len(unmapped)}개 ({', '.join(unmapped[:3])}{' …' if len(unmapped) > 3 else ''})"
        notify.emit(cur, "erp_upload_error", link=error_link(new_id), dedupe_key=f"erp_upload_error:{batch_no}", text=text)
    return new_id


def remap(cur, batch_id: int | None = None, erp_code: str | None = None, user=None) -> dict:
    """매핑이 바뀐 뒤 **반영 회차**의 행을 지금 열 매핑 · 거래처 매핑으로 다시 해석한다(교체 회차는 이력이라 건드리지 않는다).

    batch_id 를 주면 그 회차만, erp_code 를 주면 원문의 거래처코드가 그 코드인 행만. 둘 다 없으면 반영 회차 전부.
    `parsed` · `error` 를 다시 쓰고 회차의 `error_count` 를 맞춘다. 오류가 0 이 된 회차의 `erp_upload_error` 알림은
    user 를 주면 그 사람(회계부)이 처리한 것으로 닫는다.
    반환 {"reviewed": 다시 해석한 행 수, "changed": error 글자가 바뀐 행 수, "applied": error 가 None 이 되어 반영에 든 행 수,
          "still_error": 다시 해석했지만 여전히 오류인 행 수} — 사람에게는 「다시 해석 reviewed · 그중 반영 applied」 로 보인다(DEF-QA2-004).
    """
    cmap = column_map_in(cur)
    check_map(cmap)
    cm = active_customer_map(cur)
    code_col = cmap["customer_code"]
    cur.execute(
        """select u.id, u.batch_id, u.raw, u.parsed, u.error
             from erp_upload_row u join erp_upload_batch b on b.id = u.batch_id
            where b.status = '반영'
              and (%(b)s::bigint is null or u.batch_id = %(b)s::bigint)
              and (%(c)s::text is null or trim(u.raw ->> %(col)s) = %(c)s::text)
            order by u.id""", {"b": batch_id, "c": erp_code, "col": code_col})
    out = {"reviewed": 0, "changed": 0, "applied": 0, "still_error": 0}
    touched: set[int] = set()
    for row in cur.fetchall():
        parsed, error = _validate_one(row["raw"], cmap, cm)
        out["reviewed"] += 1
        out["still_error"] += error is not None
        if error != row["error"] or parsed != (row["parsed"] or {}):
            cur.execute("""update erp_upload_row set parsed = %s::jsonb, error = %s, updated_at = now(), updated_by = %s
                            where id = %s""",
                        (json.dumps(parsed, ensure_ascii=False), error, getattr(user, "login_id", None), row["id"]))
            out["changed"] += error != row["error"]
            out["applied"] += error is None and row["error"] is not None
            touched.add(row["batch_id"])
    for bid in touched:
        cur.execute("""update erp_upload_batch b
                          set error_count = (select count(*) from erp_upload_row u where u.batch_id = b.id and u.error is not null),
                              updated_at = now(), updated_by = %s
                        where b.id = %s returning error_count""", (getattr(user, "login_id", None), bid))
        if cur.fetchone()["error_count"] == 0 and user is not None:
            notify.resolve_by_link(cur, error_link(bid), user)
    return out


# ── 조회 보조 (화면 · stats 가 쓴다 — 읽기만) ──────────────────────────────

def unmapped_codes() -> list[dict]:
    """반영 회차에 올라온 ERP 거래처코드 중 사용 중 매핑이 없는 것 — COL-030 미매핑 목록.
    [{erp_code, rows, batches, first_seen, last_seen, sample_name}] (ERP 거래처명 열은 매핑 항목에 없어 미수집)."""
    return conn.q(
        """select u.parsed ->> 'customer_code' as erp_code, count(*) as rows, count(distinct u.batch_id) as batches,
                  min(b.period_from) as first_seen, max(b.period_to) as last_seen,
                  bool_or(u.error is not null) as has_error
             from erp_upload_row u join erp_upload_batch b on b.id = u.batch_id and b.status = '반영'
            where coalesce(u.parsed ->> 'customer_code', '') <> ''
              and not exists (select 1 from erp_customer_map m where m.erp_code = u.parsed ->> 'customer_code' and m.use_yn = 'Y')
            group by 1 order by 1""")


def mapped_fields() -> dict[str, bool]:
    """항목 7 의 매핑 여부 — 화면이 `미확정 (D-516)` 을 결정하는 근거."""
    cmap = column_map()
    return {f: bool(cmap.get(f)) for f in FIELDS}
