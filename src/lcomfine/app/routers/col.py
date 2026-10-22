"""COL 수금리포트 — COL-010 ERP 수금현황 업로드 · COL-020 업로드 이력 · COL-030 거래처 코드 매핑 · COL-040 수금 현황 조회 ·
COL-050 거래처별 미수 조회 · COL-060 미수 연령 조회 · COL-070 출하 대비 수금 조회 (개발3 · W2).

기능 11 (contracts/function-list.md):
  F-COL-011 POST /col/uploads                    ERP 수금현황 업로드 — action = apply(반영 · 기본) · preview(검증 미리보기 · 쓰지 않음) · map(열 매핑 저장)
  F-COL-012 GET  /col/uploads                    업로드 결과 조회 (화면) — 열 매핑 · 반영 회차의 건수·오류 건 · 오류 행(빨간색)
  F-COL-021 GET  /col/upload-history             업로드 이력 조회 (화면) — 회차 목록 · 반영/교체 구분 · `?batch=` 회차별 오류 행
  F-COL-031 POST /col/customer-map               거래처 코드 매핑 등록 — 그 코드의 반영 회차 행 재해석(`erp_upload.remap`)
  F-COL-032 POST /col/customer-map/{id}          거래처 코드 매핑 수정 — 사용 재개면 재해석
  F-COL-033 POST /col/customer-map/{id}/delete   거래처 코드 매핑 삭제 — 참조(업로드 행)가 있으면 사용 중지
  F-COL-034 GET  /col/customer-map               거래처 코드 매핑 조회 (화면) — 매핑 목록 · 미매핑 코드 목록
  F-COL-041 GET  /col/collections                수금 현황 조회 (화면) — 기간 · 거래처 · 수단 · 어음 만기 · `?format=xlsx`
  F-COL-051 GET  /col/receivables                거래처별 미수 조회 (화면) — 기준일 · 매출 · 수금 · 잔액 (열 미매핑 → 미확정 D-516)
  F-COL-061 GET  /col/aging                      미수 연령 조회 (화면) — 30 · 60 · 90 · 90 초과
  F-COL-071 GET  /col/shipment-vs-collection     출하 대비 수금 조회 (화면) — 월 · 거래처 · MES 출하 ↔ ERP 매출·수금 (G-14)

쓰기 경계: `erp_upload_batch` · `erp_upload_row` · `erp_column_map` · `erp_customer_map` + `notification`(notify). 엑셀 처리는 `erp_upload` 뿐,
집계 SQL 은 `stats` 뿐. **MES 는 수금 금액을 고치지 않는다** — 수금 데이터는 회차 교체(재업로드)로만 바뀐다(수정 엔드포인트 없음).
열 구성은 미확정(D-516 차단) — 열 매핑 화면이 흡수한다. 이 라우터의 가설은 D-802~D-804.
"""

from __future__ import annotations

import io
from datetime import date

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from openpyxl import Workbook

from ...db import conn
from .. import erp_upload, nav, rbac, stats, templating
from ..util import audit, http

router = APIRouter()

P_UPLOADS = nav.path_of("COL-010")          # /col/uploads
P_HISTORY = nav.path_of("COL-020")          # /col/upload-history
P_MAP = nav.path_of("COL-030")              # /col/customer-map
P_COLLECTIONS = nav.path_of("COL-040")      # /col/collections
P_RECEIVABLES = nav.path_of("COL-050")      # /col/receivables
P_AGING = nav.path_of("COL-060")            # /col/aging
P_SHIP_VS_COL = nav.path_of("COL-070")      # /col/shipment-vs-collection

UPLOAD_ACTIONS = ("apply", "preview", "map")
#: 화면에 보이는 미리보기 · 오류 행 수 상한 (전부 저장은 된다)
PREVIEW_LIMIT = 300


# ── 입력 검사 (사람이 읽는 문장 · 항목 이름을 짚는다 — 422) ─────────────────────

def _path_id(raw: str) -> int:
    """경로의 키 — 숫자가 아니면 「그런 대상이 없다」 404 (api-contract §1)."""
    if not raw.isdigit() or len(raw) > 18:
        raise http.not_found()
    return int(raw)


def _bad(label: str, reason: str, message: str | None = None) -> HTTPException:
    return http.validation_error(message or f"{label}: {reason}", fields=[{"name": label, "reason": reason}])


def _text(raw: str | None, label: str, limit: int = 200, *, required: bool = False) -> str | None:
    """글자 입력 — NUL · 길이 초과 · 필수 누락은 422 로 항목 이름을 짚는다(api-contract §3 · DEF-QA1-003)."""
    if raw is not None and "\x00" in raw:
        raise _bad(label, "글자에 NUL(0x00)을 넣을 수 없습니다")
    text = (raw or "").strip()
    if not text:
        if required:
            raise _bad(label, "필수 항목입니다", f"{label}을(를) 입력해 주세요")
        return None
    if len(text) > limit:
        raise _bad(label, f"{len(text)}자 — {limit}자까지", f"{label}: {limit}자까지 입력할 수 있습니다")
    return text


def _date(raw: str | None, label: str, default: date | None = None, *, required: bool = False) -> date | None:
    text = (raw or "").strip()
    if not text:
        if required:
            raise _bad(label, "필수 항목입니다", f"{label}을(를) 입력해 주세요")
        return default
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise _bad(label, text[:40], f"{label} 형식이 올바르지 않습니다 (YYYY-MM-DD)") from None


def _opt_id(raw: str | None, label: str, *, required: bool = False) -> int | None:
    text = (raw or "").strip()
    if not text:
        if required:
            raise _bad(label, "필수 항목입니다", f"{label}을(를) 골라 주세요")
        return None
    if not text.isdigit() or len(text) > 18:
        raise _bad(label, text[:40], f"{label} 값이 올바르지 않습니다")
    return int(text)


def _ym(raw: str | None, label: str, default: str) -> str:
    text = (raw or "").strip() or default
    ok = len(text) == 7 and text[4] == "-" and text[:4].isdigit() and text[5:].isdigit() and 1 <= int(text[5:]) <= 12
    if not ok:
        raise _bad(label, text[:40], f"{label} 형식이 올바르지 않습니다 (YYYY-MM)")
    return text


def _period(date_from: str | None, date_to: str | None, default_from: date, default_to: date) -> tuple[date, date]:
    f = _date(date_from, "시작일", default_from)
    t = _date(date_to, "종료일", default_to)
    if f > t:
        raise _bad("기간", f"{f} > {t}", "시작일이 종료일보다 늦습니다")
    return f, t


def _upload_error(exc: erp_upload.UploadError) -> HTTPException:
    return http.validation_error(exc.message, fields=[{"name": exc.field, "reason": exc.reason}])


def _render(request: Request, tpl: str, ctx: dict, screen_id: str, error: HTTPException | None = None) -> HTMLResponse:
    """조회 조건이 틀린 GET 은 화면을 422 로 다시 그린다(입력칸 유지) — 그 밖은 200."""
    if error is not None:
        ctx["notice"] = {"message": error.detail.get("message"), "fields": error.detail.get("fields") or []}
    return templating.render(request, tpl, ctx, screen_id=screen_id, status_code=422 if error is not None else 200)


def _saved(request, user, fn_id: str, screen_id: str, msg: str, target: str, detail: str = "", data=None):
    resp = http.saved(request, msg, back=nav.path_of(screen_id), data=data)
    audit.log_change(request, user, fn_id, target, detail or msg)
    return resp


def _customers() -> list[dict]:
    return conn.q("select id, customer_code, customer_name, use_yn from customer order by customer_code")


def _methods() -> list[dict]:
    """수금수단 — 공통코드(그룹 수금수단) ∪ 반영 행에 나온 수단 글자 (코드 값은 받은 적이 없다 · 시드는 `(예시)`)."""
    return conn.q(
        """select code as method, code_name from sys_common_code where group_code = '수금수단' and use_yn = 'Y'
           union
           select distinct u.parsed ->> 'method', null
             from erp_upload_row u join erp_upload_batch b on b.id = u.batch_id and b.status = '반영'
            where u.error is null and coalesce(u.parsed ->> 'method', '') <> ''
              and not exists (select 1 from sys_common_code c where c.group_code = '수금수단' and c.code = u.parsed ->> 'method')
           order by 1""")


# ── 회차 · 행 조회 (화면용) ───────────────────────────────────────────────

_BATCH_SQL = """
select b.id, b.batch_no, b.period_from, b.period_to, b.round_no, b.status, b.replaced_by, b.source_file, b.row_count,
       b.error_count, b.row_count - b.error_count as applied_count, b.uploaded_at, b.created_by, b.updated_at, b.updated_by,
       r.batch_no as replaced_by_no,
       (select count(*) from erp_upload_row u where u.batch_id = b.id and u.error like %(unmapped)s) as unmapped_count
  from erp_upload_batch b left join erp_upload_batch r on r.id = b.replaced_by
"""


def _batches(where: str = "true", params: dict | None = None, limit: int = 500) -> list[dict]:
    p = {"unmapped": f"%{erp_upload.UNMAPPED_PREFIX}%", **(params or {})}
    return conn.q(f"{_BATCH_SQL} where {where} order by b.period_to desc, b.period_from desc, b.round_no desc limit {int(limit)}", p)


def _batch(batch_id: int) -> dict:
    rows = _batches("b.id = %(id)s", {"id": batch_id}, 1)
    if not rows:
        raise http.not_found()
    return rows[0]


def _error_rows(batch_id: int, limit: int = PREVIEW_LIMIT) -> list[dict]:
    return conn.q("""select row_no, raw, parsed, error, updated_at from erp_upload_row
                      where batch_id = %s and error is not null order by row_no limit %s""", (batch_id, limit))


def _preview_items(validated: list[dict], cmap: dict[str, str]) -> list[dict]:
    """화면 미리보기 행 — 항목 7 을 매핑된 열 값으로 보인다. 오류 행이 먼저."""
    items = []
    for r in sorted(validated, key=lambda r: (r["error"] is None, r["row_no"])):
        items.append({"row_no": r["row_no"], "error": r["error"],
                      "cells": {f: (r["raw"].get(col) if col else None) for f, col in
                                ((f, cmap.get(f)) for f in erp_upload.FIELDS)}})
    return items[:PREVIEW_LIMIT]


# ── COL-010 ERP 수금현황 업로드 ──────────────────────────────────────────

def _uploads_ctx(batch_id: int | None = None) -> dict:
    cmap = erp_upload.column_map()
    live = _batches("b.status = '반영'")
    shown = _batch(batch_id) if batch_id is not None else (
        max(live, key=lambda b: (b["uploaded_at"], b["id"])) if live else None)
    return {"fields": erp_upload.FIELDS, "cmap": cmap, "required": erp_upload.REQUIRED_FIELDS,
            "amount_fields": erp_upload.AMOUNT_FIELDS, "live": live, "shown": shown,
            "error_rows": _error_rows(shown["id"]) if shown else [], "unmapped": erp_upload.unmapped_codes(),
            "preview": None, "headers": [], "form": {"period_from": "", "period_to": ""}, "notice": None,
            "decision": erp_upload.DECISION, "asof": stats.erp_asof(), "limit": PREVIEW_LIMIT}


@router.get(P_UPLOADS, response_class=HTMLResponse)
def uploads(request: Request, batch: str | None = None, user: rbac.User = rbac.require_screen("COL-010")) -> HTMLResponse:
    """F-COL-012 업로드 결과 조회 — 열 매핑 · 반영 회차(기간마다 하나)의 건수·오류 건 · 가장 최근 회차(또는 `?batch=`)의 오류 행."""
    bid = _path_id(batch) if batch else None
    return templating.render(request, "col/uploads.html", _uploads_ctx(bid), screen_id="COL-010")


async def _file_bytes(file: UploadFile | None) -> tuple[str, bytes]:
    if file is None or not (file.filename or "").strip():
        raise _bad("파일", "필수 항목입니다", "ERP 엑셀 파일을 올려 주세요")
    data = await file.read()
    if not data:
        raise _bad("파일", "빈 파일입니다")
    if len(data) > erp_upload.MAX_BYTES:
        raise _bad("파일", f"{erp_upload.MAX_BYTES // (1024 * 1024)}MB 이하만 올릴 수 있습니다")
    return file.filename.strip()[:200], data


@router.post(P_UPLOADS)
async def upload(request: Request, action: str | None = Form(None), period_from: str | None = Form(None),
                 period_to: str | None = Form(None), file: UploadFile | None = File(None),
                 user: rbac.User = rbac.require_fn("F-COL-011")):
    """F-COL-011 ERP 수금현황 업로드.

    action=map     열 매핑 저장(`map_<항목>` 폼 칸 · 처음 한 번 · 다시 저장하면 바꾼다) — `erp_column_map`
    action=preview 파일을 읽어 지금 매핑으로 검증만 한다 — 아무것도 쓰지 않는다(HTML 은 미리보기 화면, JSON 은 건수 · 행)
    action=apply   (기본) 검증 뒤 새 회차로 반영. 같은 기준 기간의 이전 회차는 `교체`(행 보존 · G-12). 오류 행은 error 를 적고
                   반영에서 뺀다(G-13). 오류 · 미매핑이 있으면 같은 트랜잭션에서 `erp_upload_error` → 회계부(D-511).
    """
    act = (action or "apply").strip()
    if act not in UPLOAD_ACTIONS:
        raise _bad("동작", act[:20], "모르는 동작입니다 (apply · preview · map)")
    if act == "map":
        form = await request.form()
        mapping = {f: _text(form.get(f"map_{f}"), f"열 매핑 — {label}", 200) for f, label in erp_upload.FIELDS.items()}
        try:
            with conn.tx() as cur:
                n = erp_upload.save_column_map(cur, mapping, user)
        except erp_upload.UploadError as exc:
            raise _upload_error(exc) from None
        kept = {f: c for f, c in mapping.items() if c}
        return _saved(request, user, "F-COL-011", "COL-010", f"열 매핑을 저장했습니다 — 항목 {len(kept)}개 (바뀐 항목 {n})",
                      "erp_column_map:*", "열 매핑 저장 · " + " · ".join(f"{erp_upload.FIELDS[f]}←{c}" for f, c in kept.items()),
                      data={"changed": n, "mapping": kept})
    name, data = await _file_bytes(file)
    try:
        headers, rows = erp_upload._sheet(data)
    except erp_upload.UploadError as exc:
        raise _upload_error(exc) from None
    cmap = erp_upload.column_map()
    try:
        erp_upload.check_map(cmap, headers)
    except erp_upload.UploadError as exc:
        if act == "preview" and http.wants_html(request):   # 매핑이 없거나 어긋나면 열 이름을 보여 매핑부터 받는다
            ctx = _uploads_ctx()
            ctx["headers"] = headers
            ctx["form"] = {"period_from": period_from or "", "period_to": period_to or ""}
            return _render(request, "col/uploads.html", ctx, "COL-010", _upload_error(exc))
        raise _upload_error(exc) from None
    validated = erp_upload.validate(rows, cmap)
    errors = sum(1 for r in validated if r["error"])
    if act == "preview":
        if http.wants_html(request):
            ctx = _uploads_ctx()
            ctx.update(headers=headers, form={"period_from": period_from or "", "period_to": period_to or ""},
                       preview={"file": name, "rows": len(validated), "errors": errors, "items": _preview_items(validated, cmap)})
            return templating.render(request, "col/uploads.html", ctx, screen_id="COL-010")
        return http.saved(request, f"미리보기 — 반영하지 않았습니다 · {len(validated)}행 · 오류 {errors}행",
                          data={"applied": False, "file": name, "rows": len(validated), "errors": errors,
                                "items": [{"row_no": r["row_no"], "error": r["error"], "parsed": r["parsed"]}
                                          for r in validated[:PREVIEW_LIMIT]]})
    f = _date(period_from, "기준 기간 시작", required=True)
    t = _date(period_to, "기준 기간 끝", required=True)
    if f > t:
        raise _bad("기준 기간", f"{f} > {t}", "기준 기간의 시작일이 종료일보다 늦습니다")
    if not validated:
        raise _bad("파일", "읽은 데이터 행이 없습니다 (열 이름 행만 있음)")
    previous = conn.q1("select batch_no from erp_upload_batch where period_from = %s and period_to = %s and status = '반영'", (f, t))
    try:
        with conn.tx() as cur:
            new_id = erp_upload.apply(cur, f, t, validated, user, source_file=name)
            cur.execute("select batch_no, round_no from erp_upload_batch where id = %s", (new_id,))
            b = cur.fetchone()
    except erp_upload.UploadError as exc:
        raise _upload_error(exc) from None
    msg = f"회차 {b['batch_no']} 를 반영했습니다 — {len(validated)}행 중 반영 {len(validated) - errors} · 오류·미매핑 {errors}"
    if previous:
        msg += f" · 이전 회차 {previous['batch_no']} 는 교체로 남습니다"
    return _saved(request, user, "F-COL-011", "COL-010", msg, f"erp_upload_batch:{b['batch_no']}",
                  f"ERP 업로드 {f}~{t} {b['round_no']}회차 · {name} · {len(validated)}행 · 오류 {errors}"
                  + (f" · 교체 {previous['batch_no']}" if previous else ""),
                  data={"id": new_id, "batch_no": b["batch_no"], "round_no": b["round_no"], "rows": len(validated),
                        "errors": errors, "replaced": previous["batch_no"] if previous else None})


# ── COL-020 업로드 이력 ───────────────────────────────────────────────────

@router.get(P_HISTORY, response_class=HTMLResponse)
def history(request: Request, batch: str | None = None, status: str | None = None,
            user: rbac.User = rbac.require_screen("COL-020")) -> HTMLResponse:
    """F-COL-021 업로드 이력 조회 — 회차 목록(기간 · 건수 · 오류 건 · 올린 사람) · 반영/교체 구분 · `?batch=` 회차별 오류 행."""
    ctx: dict = {"rows": [], "shown": None, "error_rows": [], "form": {"status": status or ""}, "notice": None,
                 "fields": erp_upload.FIELDS, "cmap": erp_upload.column_map(), "limit": PREVIEW_LIMIT}
    if status and status not in ("반영", "교체"):
        return _render(request, "col/history.html", ctx, "COL-020", _bad("상태", status[:20], "상태 값이 올바르지 않습니다 (반영 · 교체)"))
    ctx["rows"] = _batches("(%(s)s::text is null or b.status = %(s)s::text)", {"s": status or None})
    if batch:
        bid = _path_id(batch)
        ctx["shown"] = _batch(bid)
        ctx["error_rows"] = _error_rows(bid)
    return templating.render(request, "col/history.html", ctx, screen_id="COL-020")


# ── COL-030 거래처 코드 매핑 ──────────────────────────────────────────────

_MAP_SQL = """
select m.id, m.erp_code, m.erp_name, m.customer_id, m.use_yn, m.created_at, m.created_by, m.updated_at, m.updated_by,
       c.customer_code, c.customer_name,
       (select count(*) from erp_upload_row u where u.parsed ->> 'customer_code' = m.erp_code) as row_refs
  from erp_customer_map m join customer c on c.id = m.customer_id
"""


@router.get(P_MAP, response_class=HTMLResponse)
def customer_map(request: Request, q: str | None = None, use: str | None = None, edit: str | None = None,
                 code: str | None = None, user: rbac.User = rbac.require_screen("COL-030")) -> HTMLResponse:
    """F-COL-034 거래처 코드 매핑 조회 — 매핑 목록(ERP 코드 ↔ MES 거래처) · 미매핑 코드 목록(반영 회차에서 처음 보는 코드).
    `?code=` 는 미매핑 코드를 등록 폼에 채운다 · `?edit=` 는 수정 폼."""
    ctx: dict = {"rows": [], "unmapped": erp_upload.unmapped_codes(), "customers": _customers(), "edit": None,
                 "prefill_code": (code or "").strip()[:100], "form": {"q": q or "", "use": use or ""}, "notice": None}
    try:
        qq = _text(q, "검색어", 100)
        if use and use not in ("Y", "N"):
            raise _bad("사용 여부", use[:10], "사용 여부 값이 올바르지 않습니다 (Y · N)")
    except HTTPException as exc:
        if exc.status_code != 422:
            raise
        return _render(request, "col/customer_map.html", ctx, "COL-030", exc)
    ctx["rows"] = conn.q(
        f"""{_MAP_SQL}
            where (%(q)s::text is null or m.erp_code ilike %(like)s or m.erp_name ilike %(like)s
                   or c.customer_code ilike %(like)s or c.customer_name ilike %(like)s)
              and (%(u)s::text is null or m.use_yn = %(u)s::text)
            order by m.use_yn desc, m.erp_code limit 1000""",
        {"q": qq, "like": f"%{qq}%" if qq else None, "u": use or None})
    if edit:
        row = conn.q1(f"{_MAP_SQL} where m.id = %s", (_path_id(edit),))
        if row is None:
            raise http.not_found()
        ctx["edit"] = row
    return templating.render(request, "col/customer_map.html", ctx, screen_id="COL-030")


_NO_REMAP = {"reviewed": 0, "changed": 0, "applied": 0, "still_error": 0}


def _remap(cur, erp_code: str, user) -> dict:
    """그 코드의 반영 회차 행 재해석. 열 매핑이 아직 없으면 재해석할 반영 행도 없다 — 0."""
    if not erp_upload.column_map_in(cur):
        return dict(_NO_REMAP)
    try:
        return erp_upload.remap(cur, erp_code=erp_code, user=user)
    except erp_upload.UploadError:
        return dict(_NO_REMAP)


def _remap_text(rm: dict) -> str:
    """사람이 읽는 수 — 「다시 해석 N · 그중 반영 M」. 미매핑 외 오류(날짜 · 금액)가 남은 행은 반영에 들지 않는다(DEF-QA2-004)."""
    text = f"다시 해석한 행 {rm['reviewed']} · 그중 반영 {rm['applied']}"
    if rm["still_error"]:
        text += f" · 다른 오류로 여전히 제외 {rm['still_error']}"
    return text


def _remap_data(rm: dict) -> dict:
    return {"reinterpreted": rm["reviewed"], "applied": rm["applied"], "still_error": rm["still_error"], "remapped": rm["applied"]}


def _customer_choice(cur, customer_id: int) -> dict:
    cur.execute("select id, customer_code, customer_name, use_yn from customer where id = %s", (customer_id,))
    c = cur.fetchone()
    if c is None:
        raise _bad("MES 거래처", str(customer_id), "없는 거래처입니다")
    return c


@router.post(P_MAP)
def customer_map_create(request: Request, erp_code: str | None = Form(None), erp_name: str | None = Form(None),
                        customer_id: str | None = Form(None), user: rbac.User = rbac.require_fn("F-COL-031")):
    """F-COL-031 거래처 코드 매핑 등록 — ERP 코드 하나에 MES 거래처 하나(중복 422). 등록하면 그 코드의 반영 회차 행을 다시 해석한다."""
    code = _text(erp_code, "ERP 거래처코드", 100, required=True)
    name = _text(erp_name, "ERP 거래처명", 200)
    cid = _opt_id(customer_id, "MES 거래처", required=True)
    with conn.tx() as cur:
        c = _customer_choice(cur, cid)
        cur.execute("select id, use_yn from erp_customer_map where erp_code = %s", (code,))
        dup = cur.fetchone()
        if dup is not None:
            raise _bad("ERP 거래처코드", code, "이미 있는 ERP 거래처코드입니다"
                       + (" — 사용 중지된 매핑입니다. 수정에서 사용 재개하세요" if dup["use_yn"] == "N" else ""))
        cur.execute("""insert into erp_customer_map (erp_code, erp_name, customer_id, created_by) values (%s, %s, %s, %s)
                       returning id""", (code, name, cid, user.login_id))
        new_id = cur.fetchone()["id"]
        rm = _remap(cur, code, user)
    return _saved(request, user, "F-COL-031", "COL-030",
                  f"ERP 거래처코드 {code} ↔ {c['customer_code']} 매핑을 등록했습니다 — {_remap_text(rm)}",
                  f"erp_customer_map:{code}", f"매핑 등록 {code} → {c['customer_code']} · {_remap_text(rm)}",
                  data={"id": new_id, **_remap_data(rm)})


@router.post(P_MAP + "/{id}")
def customer_map_update(request: Request, id: str, erp_name: str | None = Form(None), customer_id: str | None = Form(None),
                        use_yn: str | None = Form(None), user: rbac.User = rbac.require_fn("F-COL-032")):
    """F-COL-032 거래처 코드 매핑 수정 — ERP 거래처명 · MES 거래처 · 사용 여부. ERP 코드는 바꾸지 않는다(키). 사용 중이면 재해석."""
    mid = _path_id(id)
    name = _text(erp_name, "ERP 거래처명", 200)
    cid = _opt_id(customer_id, "MES 거래처", required=True)
    use = (use_yn or "Y").strip()
    if use not in ("Y", "N"):
        raise _bad("사용 여부", use[:10], "사용 여부 값이 올바르지 않습니다 (Y · N)")
    with conn.tx() as cur:
        cur.execute("select id, erp_code from erp_customer_map where id = %s for update", (mid,))
        m = cur.fetchone()
        if m is None:
            raise http.not_found()
        c = _customer_choice(cur, cid)
        cur.execute("""update erp_customer_map set erp_name = %s, customer_id = %s, use_yn = %s, updated_at = now(), updated_by = %s
                        where id = %s""", (name, cid, use, user.login_id, mid))
        rm = _remap(cur, m["erp_code"], user) if use == "Y" else _NO_REMAP
    return _saved(request, user, "F-COL-032", "COL-030",
                  f"매핑 {m['erp_code']} 를 고쳤습니다 — {c['customer_code']} · 사용 {use} · {_remap_text(rm)}",
                  f"erp_customer_map:{m['erp_code']}", f"매핑 수정 → {c['customer_code']} · use {use} · {_remap_text(rm)}",
                  data={"id": mid, **_remap_data(rm), "use_yn": use})


@router.post(P_MAP + "/{id}/delete")
def customer_map_delete(request: Request, id: str, user: rbac.User = rbac.require_fn("F-COL-033")):
    """F-COL-033 거래처 코드 매핑 삭제 — 업로드 행이 그 코드를 참조하면 지우지 않고 사용 중지(use_yn = N). 행은 건드리지 않는다."""
    mid = _path_id(id)
    with conn.tx() as cur:
        cur.execute("select id, erp_code, use_yn from erp_customer_map where id = %s for update", (mid,))
        m = cur.fetchone()
        if m is None:
            raise http.not_found()
        cur.execute("select count(*) as n from erp_upload_row where parsed ->> 'customer_code' = %s", (m["erp_code"],))
        refs = cur.fetchone()["n"]
        if refs:
            cur.execute("update erp_customer_map set use_yn = 'N', updated_at = now(), updated_by = %s where id = %s",
                        (user.login_id, mid))
            msg, detail = (f"매핑 {m['erp_code']} 는 업로드 행 {refs}건이 참조해 지우지 않고 사용 중지로 바꿨습니다",
                           f"매핑 사용 중지(참조 {refs}행)")
        else:
            cur.execute("delete from erp_customer_map where id = %s", (mid,))
            msg, detail = f"매핑 {m['erp_code']} 를 지웠습니다", "매핑 삭제"
    return _saved(request, user, "F-COL-033", "COL-030", msg, f"erp_customer_map:{m['erp_code']}", detail,
                  data={"id": mid, "disabled": bool(refs), "refs": refs})


# ── COL-040 수금 현황 조회 ────────────────────────────────────────────────

def _xlsx_text_cell(ws, row_no: int, col_no: int, value) -> None:
    """글자는 **문자열 셀로 고정**한다 — ERP 행의 원문이 `=CMD|…`, `=HYPERLINK(…)`, `+`, `-`, `@` 로 시작해도 수식이 되지 않는다
    (DEF-QA3-004 · openpyxl 은 `=` 로 시작하는 글자를 수식 셀(data_type f)로 쓴다). 날짜는 ISO 글자, 수는 그대로."""
    cell = ws.cell(row=row_no, column=col_no, value=(value.isoformat() if isinstance(value, date) else value))
    if isinstance(cell.value, str):
        cell.data_type = "s"


def _xlsx(headers: list[str], rows: list[list], filename: str) -> Response:
    """엑셀(.xlsx) 내려받기 — 화면과 같은 숫자. 정본 COL-040 「엑셀」. 모든 글자 셀은 문자열(수식 셀 0 — DEF-QA3-004).
    다른 xlsx 내려받기를 만들면 같은 `_xlsx_text_cell` 을 쓴다."""
    wb = Workbook()
    ws = wb.active
    ws.title = "수금 현황"
    for j, h in enumerate(headers, start=1):
        _xlsx_text_cell(ws, 1, j, h)
    for i, r in enumerate(rows, start=2):
        for j, v in enumerate(r, start=1):
            _xlsx_text_cell(ws, i, j, v)
    buf = io.BytesIO()
    wb.save(buf)
    return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get(P_COLLECTIONS)
def collections(request: Request, date_from: str | None = None, date_to: str | None = None, customer: str | None = None,
                method: str | None = None, format: str | None = None, user: rbac.User = rbac.require_screen("COL-040")):
    """F-COL-041 수금 현황 조회 — 기간 · 거래처 · 수단 · 일자별 목록 · 어음 만기 도래 여부 · `?format=xlsx` 엑셀."""
    asof = stats.erp_asof()
    anchor = asof or date.today()
    form = {"date_from": date_from or "", "date_to": date_to or "", "customer": customer or "", "method": method or ""}
    ctx: dict = {"form": form, "data": None, "customers": _customers(), "methods": _methods(), "notice": None,
                 "fields": erp_upload.FIELDS, "decision": erp_upload.DECISION}
    try:
        f, t = _period(date_from, date_to, anchor.replace(day=1), anchor)
        cid = _opt_id(customer, "거래처")
        m = _text(method, "수단", 100)
        if format and format != "xlsx":
            raise _bad("형식", format[:20], "모르는 형식입니다 (xlsx)")
    except HTTPException as exc:
        if exc.status_code != 422:
            raise
        return _render(request, "col/collections.html", ctx, "COL-040", exc)
    form.update(date_from=f.isoformat(), date_to=t.isoformat())
    data = stats.collections(f, t, cid, m)
    if format == "xlsx":
        heads = ["일자", "ERP 거래처코드", "MES 거래처 코드", "거래처", "매출액", "수금액", "잔액", "수단", "어음 만기", "만기 도래", "회차"]
        body = [[r["txn_date"], r["erp_code"], r["customer_code"], r["customer_name"], r["sales_amount"], r["collected_amount"],
                 r["balance_amount"], r["method"], r["bill_due_date"], r["bill_due"], r["batch_no"]] for r in data["rows"]]
        return _xlsx(heads, body, f"collections-{f.isoformat()}-{t.isoformat()}.xlsx")
    ctx["data"] = data
    ctx["series"] = [{"label": r["method"] or "(수단 없음)", "value": r["collected_amount"]} for r in data["by_method"]]
    return templating.render(request, "col/collections.html", ctx, screen_id="COL-040")


# ── COL-050 거래처별 미수 조회 ────────────────────────────────────────────

@router.get(P_RECEIVABLES, response_class=HTMLResponse)
def receivables(request: Request, asof: str | None = None, show_zero: str | None = None,
                user: rbac.User = rbac.require_screen("COL-050")) -> HTMLResponse:
    """F-COL-051 거래처별 미수 조회 — 기준일 · 매출 · 수금 · 미수 잔액. 매출액 열이 매핑되지 않으면 `미확정 (D-516)`. 미수 0 은 기본 숨김."""
    erp_asof = stats.erp_asof()
    form = {"asof": asof or "", "show_zero": "1" if show_zero else ""}
    ctx: dict = {"form": form, "data": None, "notice": None, "erp_asof": erp_asof, "decision": erp_upload.DECISION}
    try:
        d = _date(asof, "기준일", erp_asof or date.today())
    except HTTPException as exc:
        if exc.status_code != 422:
            raise
        return _render(request, "col/receivables.html", ctx, "COL-050", exc)
    form["asof"] = d.isoformat()
    data = stats.receivables(d, include_zero=bool(show_zero))
    ctx["data"] = data
    ctx["series"] = [] if data["undecided"] else [{"label": r["customer_code"], "value": r["receivable_amount"]} for r in data["rows"][:30]]
    return templating.render(request, "col/receivables.html", ctx, screen_id="COL-050")


# ── COL-060 미수 연령 조회 ────────────────────────────────────────────────

@router.get(P_AGING, response_class=HTMLResponse)
def aging(request: Request, asof: str | None = None, user: rbac.User = rbac.require_screen("COL-060")) -> HTMLResponse:
    """F-COL-061 미수 연령 조회 — 기준일 · 매출일 경과일 30 · 60 · 90 · 90 초과 구간 금액(가설 D-803). 매출 열 미매핑 → `미확정 (D-516)`."""
    erp_asof = stats.erp_asof()
    form = {"asof": asof or ""}
    ctx: dict = {"form": form, "data": None, "notice": None, "erp_asof": erp_asof, "decision": erp_upload.DECISION}
    try:
        d = _date(asof, "기준일", erp_asof or date.today())
    except HTTPException as exc:
        if exc.status_code != 422:
            raise
        return _render(request, "col/aging.html", ctx, "COL-060", exc)
    form["asof"] = d.isoformat()
    data = stats.aging(d)
    ctx["data"] = data
    ctx["series"] = [] if data["undecided"] else [{"label": b, "value": data["totals"][b]["net"]} for b in data["buckets"]]
    return templating.render(request, "col/aging.html", ctx, screen_id="COL-060")


# ── COL-070 출하 대비 수금 조회 ──────────────────────────────────────────

def _default_months() -> tuple[str, str]:
    anchor = stats.erp_asof() or date.today()
    y, m = anchor.year, anchor.month
    start_y, start_m = (y, m - 5) if m > 5 else (y - 1, m + 7)
    return f"{start_y:04d}-{start_m:02d}", f"{y:04d}-{m:02d}"


@router.get(P_SHIP_VS_COL, response_class=HTMLResponse)
def shipment_vs_collection(request: Request, ym_from: str | None = None, ym_to: str | None = None, customer: str | None = None,
                           user: rbac.User = rbac.require_screen("COL-070")) -> HTMLResponse:
    """F-COL-071 출하 대비 수금 조회 — 월 · 거래처별 MES 출하 건수·수량과 ERP 매출·수금을 나란히(독립 집계 · 건 단위 짝짓기 없음 · G-14)."""
    d_from, d_to = _default_months()
    form = {"ym_from": ym_from or "", "ym_to": ym_to or "", "customer": customer or ""}
    ctx: dict = {"form": form, "data": None, "customers": _customers(), "notice": None, "decision": erp_upload.DECISION}
    try:
        yf = _ym(ym_from, "시작 월", d_from)
        yt = _ym(ym_to, "끝 월", d_to)
        if yf > yt:
            raise _bad("기간", f"{yf} > {yt}", "시작 월이 끝 월보다 늦습니다")
        if (int(yt[:4]) - int(yf[:4])) * 12 + int(yt[5:]) - int(yf[5:]) >= 36:
            raise _bad("기간", f"{yf} ~ {yt}", "한 번에 36개월까지 볼 수 있습니다")
        cid = _opt_id(customer, "거래처")
    except HTTPException as exc:
        if exc.status_code != 422:
            raise
        return _render(request, "col/shipment_vs_collection.html", ctx, "COL-070", exc)
    form.update(ym_from=yf, ym_to=yt)
    data = stats.shipment_vs_collection(yf, yt, cid)
    ctx["data"] = data
    ctx["series_ship"] = [{"label": m["ym"], "value": m["shipped_qty"]} for m in data["monthly"]]
    ctx["series_coll"] = [{"label": m["ym"], "value": m["collected_amount"]} for m in data["monthly"]]
    return templating.render(request, "col/shipment_vs_collection.html", ctx, screen_id="COL-070")
