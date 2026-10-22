"""RPT 대시보드(D-505) — RPT-010 수주 · RPT-020 생산 · RPT-030 품질 · RPT-040 재고·창고 · RPT-050 출하 · RPT-060 수금 · RPT-070 주문 흐름 ·
RPT-080 경영 요약 · RPT-130 데이터 질의 (개발3 · W3).

기능 10 (contracts/function-list.md):
  F-RPT-011 GET /rpt/orders        수주 리포트     F-RPT-051 GET /rpt/shipment     출하 리포트
  F-RPT-021 GET /rpt/production    생산 리포트     F-RPT-061 GET /rpt/collection   수금 리포트 (최근 업로드 기준일 명시)
  F-RPT-031 GET /rpt/quality       품질 리포트     F-RPT-071 GET /rpt/order-flow   주문 흐름 리포트 (병목 미확정 D-520)
  F-RPT-041 GET /rpt/inventory     재고·창고 리포트 F-RPT-081 GET /rpt/summary      경영 요약 (일일 · 주간 · 월간 탭 · 해설 없음)
  F-RPT-131 GET /rpt/query         데이터 질의 조회 (질문 입력 · 최근 질의)
  F-RPT-132 POST /rpt/query        질의 실행 (R 이상 · 권한 예외 · D-513) — 쓰는 테이블 data_query_log · sys_ai_call_log 만

대시보드 8 은 화면을 열 때 `dashboard` 가 집계한다(캐시 없음 · D-512) — 라우터는 조회 조건만 검사한다. 차트는 인라인 SVG + 같은 숫자의 표.
조회 조건 형식이 틀리면 화면을 422 로 다시 그린다(입력칸 유지). 어떤 업무 테이블에도 쓰지 않는다(G-05).
데이터 질의: AI 는 `ai` 뿐 · 검증 · 실행 · 로그는 `dataquery` 뿐. 키가 없거나 호출이 실패하면 그 문장을 화면에 그대로 보인다(G-17 · 조용한 실패 금지).
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from ...db import conn
from .. import dashboard, dataquery, nav, rbac, templating
from ..util import audit, http

router = APIRouter()

#: 경영 요약 탭 (정본 RPT-080 「일일 · 주간 · 월간」)
SUMMARY_TABS = ("daily", "weekly", "monthly")
SUMMARY_LABEL = {"daily": "일일", "weekly": "주간", "monthly": "월간"}
#: 기간 상한(일) — 일 · 월 구간 수가 화면에서 읽히는 범위
PERIOD_MAX_DAYS = 3 * 366


def _bad(label: str, reason: str, message: str | None = None) -> HTTPException:
    return http.validation_error(message or f"{label}: {reason}", fields=[{"name": label, "reason": reason}])


def _date(raw: str | None, label: str, default: date) -> date:
    text = (raw or "").strip()
    if not text:
        return default
    if "\x00" in text:
        raise _bad(label, "글자에 NUL(0x00)을 넣을 수 없습니다")
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise _bad(label, text[:40], f"{label} 형식이 올바르지 않습니다 (YYYY-MM-DD)") from None


def _period(date_from: str | None, date_to: str | None) -> tuple[date, date]:
    today = date.today()
    f = _date(date_from, "시작일", today.replace(day=1))
    t = _date(date_to, "종료일", today)
    if f > t:
        raise _bad("기간", f"{f} > {t}", "시작일이 종료일보다 늦습니다")
    if (t - f).days > PERIOD_MAX_DAYS:
        raise _bad("기간", f"{(t - f).days + 1}일", f"기간은 {PERIOD_MAX_DAYS}일까지 조회할 수 있습니다")
    return f, t


def _customer(raw: str | None) -> int | None:
    text = (raw or "").strip()
    if not text:
        return None
    if not text.isdigit() or len(text) > 18:
        raise _bad("거래처", text[:40], "거래처 값이 올바르지 않습니다")
    if conn.q1("select 1 from customer where id = %s", (int(text),)) is None:
        raise _bad("거래처", text, "없는 거래처입니다")
    return int(text)


def _render(request: Request, tpl: str, ctx: dict, screen_id: str, error: HTTPException | None = None) -> HTMLResponse:
    """조회 조건 오류(422)는 브라우저(`Accept: text/html`)에만 같은 화면 재렌더 — 그 밖(JSON · 테스트)은 계약 §2 대로
    `{code: validation_error, message, fields}` 422 를 그대로 올린다(DEF-QA1-007)."""
    if error is not None:
        if not http.wants_html(request):
            raise error
        ctx["notice"] = {"message": error.detail.get("message"), "fields": error.detail.get("fields") or []}
    return templating.render(request, tpl, ctx, screen_id=screen_id, status_code=422 if error is not None else 200)


def _customers() -> list[dict]:
    return conn.q("select id, customer_code, customer_name from customer order by customer_code")


def _dashboard(request: Request, screen_id: str, tpl: str, fn, *, date_from: str | None, date_to: str | None,
               customer: str | None, with_customer: bool) -> HTMLResponse:
    """대시보드 화면 하나 — 조건 검사(422 는 화면으로) → `dashboard.<fn>` → 렌더. 어디에도 쓰지 않는다."""
    form = {"date_from": date_from or "", "date_to": date_to or "", "customer": customer or ""}
    ctx: dict = {"form": form, "data": None, "notice": None, "with_customer": with_customer,
                 "customers": _customers() if with_customer else []}
    try:
        f, t = _period(date_from, date_to)
        cid = _customer(customer) if with_customer else None
    except HTTPException as exc:
        if exc.status_code != 422:
            raise
        return _render(request, tpl, ctx, screen_id, exc)
    form.update(date_from=f.isoformat(), date_to=t.isoformat())
    ctx["data"] = fn((f, t), cid) if with_customer else fn((f, t))
    return _render(request, tpl, ctx, screen_id)


@router.get(nav.path_of("RPT-010"), response_class=HTMLResponse)
def orders(request: Request, date_from: str | None = None, date_to: str | None = None, customer: str | None = None,
           user: rbac.User = rbac.require_screen("RPT-010")) -> HTMLResponse:
    """F-RPT-011 수주 리포트 — 기간 · 거래처 필터 · 미착수 = 의뢰는 있고 지시가 없는 건."""
    return _dashboard(request, "RPT-010", "rpt/orders.html", dashboard.orders, date_from=date_from, date_to=date_to,
                      customer=customer, with_customer=True)


@router.get(nav.path_of("RPT-020"), response_class=HTMLResponse)
def production(request: Request, date_from: str | None = None, date_to: str | None = None,
               user: rbac.User = rbac.require_screen("RPT-020")) -> HTMLResponse:
    """F-RPT-021 생산 리포트 — 기간 필터 · 로스율 미확정 (D-519) · 가동률 D-801."""
    return _dashboard(request, "RPT-020", "rpt/production.html", dashboard.production, date_from=date_from, date_to=date_to,
                      customer=None, with_customer=False)


@router.get(nav.path_of("RPT-030"), response_class=HTMLResponse)
def quality(request: Request, date_from: str | None = None, date_to: str | None = None,
            user: rbac.User = rbac.require_screen("RPT-030")) -> HTMLResponse:
    """F-RPT-031 품질 리포트 — 기간 필터 · 검사 로스율 미확정 (D-519)."""
    return _dashboard(request, "RPT-030", "rpt/quality.html", dashboard.quality, date_from=date_from, date_to=date_to,
                      customer=None, with_customer=False)


@router.get(nav.path_of("RPT-040"), response_class=HTMLResponse)
def inventory(request: Request, date_from: str | None = None, date_to: str | None = None,
              user: rbac.User = rbac.require_screen("RPT-040")) -> HTMLResponse:
    """F-RPT-041 재고·창고 리포트 — 기간 필터."""
    return _dashboard(request, "RPT-040", "rpt/inventory.html", dashboard.inventory, date_from=date_from, date_to=date_to,
                      customer=None, with_customer=False)


@router.get(nav.path_of("RPT-050"), response_class=HTMLResponse)
def shipment(request: Request, date_from: str | None = None, date_to: str | None = None, customer: str | None = None,
             user: rbac.User = rbac.require_screen("RPT-050")) -> HTMLResponse:
    """F-RPT-051 출하 리포트 — 기간 · 거래처 필터 · 납기 준수율은 의뢰번호 있는 출하만(D-804)."""
    return _dashboard(request, "RPT-050", "rpt/shipment.html", dashboard.shipment, date_from=date_from, date_to=date_to,
                      customer=customer, with_customer=True)


@router.get(nav.path_of("RPT-060"), response_class=HTMLResponse)
def collection(request: Request, date_from: str | None = None, date_to: str | None = None, customer: str | None = None,
               user: rbac.User = rbac.require_screen("RPT-060")) -> HTMLResponse:
    """F-RPT-061 수금 리포트 — 가장 최근 업로드 기준일을 명시한다(`asof`)."""
    return _dashboard(request, "RPT-060", "rpt/collection.html", dashboard.collection, date_from=date_from, date_to=date_to,
                      customer=customer, with_customer=True)


@router.get(nav.path_of("RPT-070"), response_class=HTMLResponse)
def order_flow(request: Request, date_from: str | None = None, date_to: str | None = None, customer: str | None = None,
               user: rbac.User = rbac.require_screen("RPT-070")) -> HTMLResponse:
    """F-RPT-071 주문 흐름 리포트 — 단계 소요일 · 병목 미확정 (D-520)."""
    return _dashboard(request, "RPT-070", "rpt/order_flow.html", dashboard.order_flow, date_from=date_from, date_to=date_to,
                      customer=customer, with_customer=True)


@router.get(nav.path_of("RPT-080"), response_class=HTMLResponse)
def summary(request: Request, tab: str | None = None, asof: str | None = None, customer: str | None = None,
            user: rbac.User = rbac.require_screen("RPT-080")) -> HTMLResponse:
    """F-RPT-081 경영 요약 — 탭 일일(기준일 하루) · 주간(기준일까지 7일) · 월간(기준일의 달 1일 ~ 기준일). 해설 문장 없음(D-505)."""
    tab_v = (tab or "daily").strip()
    form = {"tab": tab_v, "asof": asof or "", "customer": customer or ""}
    ctx: dict = {"form": form, "data": None, "notice": None, "tabs": [(k, SUMMARY_LABEL[k]) for k in SUMMARY_TABS],
                 "customers": _customers(), "with_customer": True}
    try:
        if tab_v not in SUMMARY_TABS:
            raise _bad("탭", tab_v[:40], "탭은 일일 · 주간 · 월간 중 하나입니다")
        t = _date(asof, "기준일", date.today())
        cid = _customer(customer)
    except HTTPException as exc:
        if exc.status_code != 422:
            raise
        return _render(request, "rpt/summary.html", ctx, "RPT-080", exc)
    f = {"daily": t, "weekly": t - timedelta(days=6), "monthly": t.replace(day=1)}[tab_v]
    form.update(asof=t.isoformat())
    ctx["data"] = dashboard.summary((f, t), cid)
    return _render(request, "rpt/summary.html", ctx, "RPT-080")


# ── RPT-130 데이터 질의 ─────────────────────────────────────────────────────────

def _query_ctx(user: rbac.User, question: str = "") -> dict:
    return {"form": {"question": question}, "result": None, "notice": None, "recent": dataquery.recent(user),
            "views": dataquery.allowed_views(user.role_code), "max_rows": dataquery.MAX_ROWS,
            "all_views": list(dataquery.VIEWS), "collection_roles": dataquery.COLLECTION_ROLES}


@router.get(nav.path_of("RPT-130"), response_class=HTMLResponse)
def query(request: Request, user: rbac.User = rbac.require_screen("RPT-130")) -> HTMLResponse:
    """F-RPT-131 데이터 질의 조회 — 질문 입력 · 이 부서가 질의할 수 있는 뷰 · 최근 질의(SQL · 결과 건수 · 거부 사유)."""
    return _render(request, "rpt/query.html", _query_ctx(user), "RPT-130")


@router.post(nav.path_of("RPT-130"))
def run_query(request: Request, question: str | None = Form(None), user: rbac.User = rbac.require_fn("F-RPT-132")):
    """F-RPT-132 질의 실행 — 질문 → SQL(`ai`) → 검증(D-513 · D-806) → 읽기 전용 실행 → `data_query_log`(거부 포함).

    거부 · AI 키 없음 · 호출 실패 · 실행 실패는 로그를 남긴 뒤 **422** 로 이유를 보인다(G-16 · G-17). 성공은 `http.saved` + `audit.log_change`;
    브라우저는 결과 표를 같은 화면에 바로 그린다(결과 행은 저장하지 않아 303 뒤에 다시 보일 수 없다 — D-806).
    """
    text = (question or "")
    if "\x00" in text:
        raise _bad("질문", "글자에 NUL(0x00)을 넣을 수 없습니다")
    text = text.strip()
    if not text:
        raise _bad("질문", "필수 항목입니다", "질문을 입력해 주세요")
    if len(text) > dataquery.QUESTION_MAX_CHARS:
        raise _bad("질문", f"{len(text)}자 — {dataquery.QUESTION_MAX_CHARS}자까지", f"질문: {dataquery.QUESTION_MAX_CHARS}자까지 입력할 수 있습니다")
    with conn.tx() as cur:
        result = dataquery.ask(cur, user, text)
    if not result["ok"]:
        fields = [{"name": "질의 번호", "reason": result["query_no"]}]
        if result["sql"]:
            fields.append({"name": "SQL", "reason": result["sql"][:500]})
        raise http.validation_error(result["error"], fields=fields)
    msg = f"질의 {result['query_no']} — {result['row_count']}행" + (f" (상한 {dataquery.MAX_ROWS}행에서 잘림)" if result["truncated"] else "")
    audit.log_change(request, user, "F-RPT-132", f"data_query_log:{result['query_no']}", f"데이터 질의 실행 · {result['row_count']}행")
    if http.wants_html(request):
        ctx = _query_ctx(user, text)
        ctx["result"] = result
        ctx["saved"] = msg
        return templating.render(request, "rpt/query.html", ctx, screen_id="RPT-130")
    return http.saved(request, msg, back=nav.path_of("RPT-130"),
                      data={"query_no": result["query_no"], "sql": result["sql"], "columns": result["columns"],
                            "rows": [{k: (v.isoformat() if hasattr(v, "isoformat") else (str(v) if v is not None and not isinstance(v, (int, float, bool, str)) else v))
                                      for k, v in r.items()} for r in result["rows"]],
                            "row_count": result["row_count"], "truncated": result["truncated"], "ms": result["ms"]})
