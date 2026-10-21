"""PRP 생산 보고서 — PRP-010 월별 가동률 · PRP-020 기계별통계 · PRP-030 생산완료집계 (개발3).

기능 3 (contracts/function-list.md) — 전부 조회 · **읽기만**(어떤 업무 테이블에도 쓰지 않는다 · G-05). 집계 SQL 은 `stats` 뿐.
  F-PRP-011 GET /prp/utilization   연·월 → 설비별 가동률 (산식 가설 D-801)
  F-PRP-021 GET /prp/machines      기간 → 설비별 생산 · 양품 · 로스 수량 (로스율 미확정 D-519)
  F-PRP-031 GET /prp/completion    기간 · 거래처 → 제품 입고 기준 완료 수량 집계
조회 조건 형식이 틀리면 화면을 422 로 다시 그린다(입력칸 유지).
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from ...db import conn
from .. import nav, rbac, stats, templating
from ..util import http

router = APIRouter()


def _date(raw: str | None, label: str, default: date) -> date:
    text = (raw or "").strip()
    if not text:
        return default
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise http.validation_error(f"{label} 형식이 올바르지 않습니다 (YYYY-MM-DD)",
                                    fields=[{"name": label, "reason": text[:40]}]) from None


def _int(raw: str | None, label: str, default: int | None, lo: int, hi: int) -> int | None:
    text = (raw or "").strip()
    if not text:
        return default
    if not text.isdigit() or not (lo <= int(text) <= hi):
        raise http.validation_error(f"{label} 값이 올바르지 않습니다 ({lo}~{hi})", fields=[{"name": label, "reason": text[:40]}])
    return int(text)


def _period(date_from: str | None, date_to: str | None) -> tuple[date, date]:
    today = date.today()
    f = _date(date_from, "시작일", today.replace(day=1))
    t = _date(date_to, "종료일", today)
    if f > t:
        raise http.validation_error("시작일이 종료일보다 늦습니다", fields=[{"name": "기간", "reason": f"{f} > {t}"}])
    return f, t


def _render(request: Request, tpl: str, ctx: dict, screen_id: str, error: HTTPException | None = None) -> HTMLResponse:
    if error is not None:
        ctx["notice"] = {"message": error.detail.get("message"), "fields": error.detail.get("fields") or []}
    return templating.render(request, tpl, ctx, screen_id=screen_id, status_code=422 if error is not None else 200)


@router.get(nav.path_of("PRP-010"), response_class=HTMLResponse)
def utilization(request: Request, year: str | None = None, month: str | None = None,
                user: rbac.User = rbac.require_fn("F-PRP-011")) -> HTMLResponse:
    """F-PRP-011 월별 가동률 — 설비별 가동 · 정지 분과 가동률(D-801). 일보가 없는 설비는 `미수집`."""
    today = date.today()
    form = {"year": year or str(today.year), "month": month or str(today.month)}
    ctx: dict = {"form": form, "data": None, "notice": None, "series": []}
    try:
        y = _int(year, "연도", today.year, 2000, 2100)
        m = _int(month, "월", today.month, 1, 12)
    except HTTPException as exc:   # 조회 조건 오류(422)만 화면으로 되그린다
        if exc.status_code != 422:
            raise
        return _render(request, "prp/utilization.html", ctx, "PRP-010", exc)
    data = stats.utilization(y, m)
    ctx["data"] = data
    ctx["series"] = [{"label": r["equipment_name"] or r["equipment_code"], "value": r["rate"]} for r in data["rows"]]
    return _render(request, "prp/utilization.html", ctx, "PRP-010")


@router.get(nav.path_of("PRP-020"), response_class=HTMLResponse)
def machines(request: Request, date_from: str | None = None, date_to: str | None = None,
             user: rbac.User = rbac.require_fn("F-PRP-021")) -> HTMLResponse:
    """F-PRP-021 기계별통계 — 설비별 생산 · 양품 · 로스 수량. 로스율은 `미확정 (D-519)` 와 원 수량을 함께 보인다."""
    form = {"date_from": date_from or "", "date_to": date_to or ""}
    ctx: dict = {"form": form, "rows": [], "notice": None, "series": [], "loss_decision": stats.LOSS_RATE_DECISION}
    try:
        f, t = _period(date_from, date_to)
    except HTTPException as exc:
        if exc.status_code != 422:
            raise
        return _render(request, "prp/machines.html", ctx, "PRP-020", exc)
    form.update(date_from=f.isoformat(), date_to=t.isoformat())
    rows = stats.machine_stats(f, t)
    ctx["rows"] = rows
    ctx["series"] = [{"label": r["equipment_name"] or r["equipment_code"], "value": r["good_qty"]} for r in rows]
    return _render(request, "prp/machines.html", ctx, "PRP-020")


@router.get(nav.path_of("PRP-030"), response_class=HTMLResponse)
def completion(request: Request, date_from: str | None = None, date_to: str | None = None,
               customer: str | None = None, user: rbac.User = rbac.require_fn("F-PRP-031")) -> HTMLResponse:
    """F-PRP-031 생산완료집계 — 제품 입고(취소 제외) 기준 거래처 · 제품별 완료 수량 · 월별 추이."""
    form = {"date_from": date_from or "", "date_to": date_to or "", "customer": customer or ""}
    ctx: dict = {"form": form, "data": None, "notice": None, "series": [],
                 "customers": conn.q("select id, customer_code, customer_name from customer order by customer_code")}
    try:
        f, t = _period(date_from, date_to)
        cid = _int(customer, "거래처", None, 1, 10**17)
    except HTTPException as exc:
        if exc.status_code != 422:
            raise
        return _render(request, "prp/completion.html", ctx, "PRP-030", exc)
    form.update(date_from=f.isoformat(), date_to=t.isoformat())
    data = stats.completion(f, t, cid)
    ctx["data"] = data
    ctx["series"] = [{"label": r["ym"], "value": r["qty"]} for r in data["monthly"]]
    return _render(request, "prp/completion.html", ctx, "PRP-030")
