"""sta 라우터 — 실적 현황 (기능 4) · 담당 개발3 · 프로세스 P10.

**어떤 테이블에도 쓰지 않는다**(G-05). 이 파일에는 SQL 이 한 줄도 없다 — 집계 SQL 은 전부 `app/stats.py` 한 곳에 있고
(G-10), 집계 결과를 저장하지 않는다. 집계 화면과 현황판은 **같은 함수**에서 값을 받는다.
행이 없으면 `미수집` 을 보여 준다(G-11). 분모가 0 인 비율은 `-` 다(0% 로 지어내지 않는다).

  STA-01 집계 (생산, 품질, 납기) → /sta/summary            화면 GET — 세 집계를 한 화면에
      F-STA-01 생산 집계 조회 [조회] GET /sta/summary/production   `stats.production`
      F-STA-02 품질 집계 조회 [조회] GET /sta/summary/quality      `stats.quality`
      F-STA-03 납기 집계 조회 [조회] GET /sta/summary/delivery     `stats.delivery`
  STA-02 현황판 → /sta/board
      F-STA-04 현황판 [조회] GET /sta/board                        `stats.board` — `?device=board` 면 자동 새로고침(D-19)
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .. import nav, rbac, stats, templating

router = APIRouter()

PRODUCTION, QUALITY, DELIVERY = "production", "quality", "delivery"
#: 집계 종류 → (이름, 기능 ID, 기간이 가리키는 날짜)
KINDS: dict[str, tuple[str, str, str]] = {
    PRODUCTION: ("생산", "F-STA-01", "작업 종료일"),
    QUALITY: ("품질", "F-STA-02", "검사일"),
    DELIVERY: ("납기", "F-STA-03", "납기"),
}


def _section(kind: str, d1: date, d2: date, item_id: int | None) -> dict:
    rows = {PRODUCTION: stats.production, QUALITY: stats.quality, DELIVERY: stats.delivery}[kind](d1, d2, item_id)
    return {"kind": kind, "rows": rows, "total": stats.totals(kind, rows)}


def _summary(request: Request, kinds: tuple[str, ...], date_from: str, date_to: str, item_id: str) -> HTMLResponse:
    d1, d2 = stats.period(date_from, date_to)
    item = stats.parse_item(item_id)
    return templating.render(request, "sta/summary.html", {
        "sections": [_section(k, d1, d2, item) for k in kinds], "kinds": KINDS, "shown": kinds,
        "date_from": d1, "date_to": d2, "item_id": item, "items": stats.item_options(), "today": date.today(),
    }, screen_id="STA-01")


@router.get(nav.path_of("STA-01"), response_class=HTMLResponse)                     # 화면 GET (조회 기능이 아닌 중메뉴) — 셋 다
def summary(request: Request, date_from: str = "", date_to: str = "", item_id: str = "",
            user: rbac.User = rbac.require_screen("STA-01")) -> HTMLResponse:
    return _summary(request, (PRODUCTION, QUALITY, DELIVERY), date_from, date_to, item_id)


@router.get(nav.path_of("STA-01") + "/production", response_class=HTMLResponse)     # F-STA-01 생산 집계 조회
def production(request: Request, date_from: str = "", date_to: str = "", item_id: str = "",
               user: rbac.User = rbac.require_fn("F-STA-01")) -> HTMLResponse:
    return _summary(request, (PRODUCTION,), date_from, date_to, item_id)


@router.get(nav.path_of("STA-01") + "/quality", response_class=HTMLResponse)        # F-STA-02 품질 집계 조회
def quality(request: Request, date_from: str = "", date_to: str = "", item_id: str = "",
            user: rbac.User = rbac.require_fn("F-STA-02")) -> HTMLResponse:
    return _summary(request, (QUALITY,), date_from, date_to, item_id)


@router.get(nav.path_of("STA-01") + "/delivery", response_class=HTMLResponse)       # F-STA-03 납기 집계 조회
def delivery(request: Request, date_from: str = "", date_to: str = "", item_id: str = "",
             user: rbac.User = rbac.require_fn("F-STA-03")) -> HTMLResponse:
    return _summary(request, (DELIVERY,), date_from, date_to, item_id)


@router.get(nav.path_of("STA-02"), response_class=HTMLResponse)                     # F-STA-04 현황판 = 화면 GET
def board(request: Request, user: rbac.User = rbac.require_fn("F-STA-04")) -> HTMLResponse:
    return templating.render(request, "sta/board.html", {"board": stats.board()}, screen_id="STA-02")
