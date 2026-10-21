"""LOT 추적 — LOT-010 정방향 추적 · LOT-020 역방향 추적 (개발2).

`trace` 결과를 그리기만 한다 — 어떤 테이블에도 쓰지 않는다(G-05). 입력한 번호가 없으면 화면을 422 로 다시 그린다(입력칸 유지).
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .. import nav, rbac, templating, trace
from .inv import qs

router = APIRouter()


@router.get(nav.path_of("LOT-010"), response_class=HTMLResponse)
def forward(request: Request, user: rbac.User = rbac.require_screen("LOT-010")):
    f = {"lot_no": qs(request, "lot_no")}
    result, error = None, None
    if f["lot_no"]:
        try:
            result = trace.forward(f["lot_no"])
        except trace.NotFound:
            error = f"없는 원자재 LOT 번호입니다: {f['lot_no'][:60]}"
    return templating.render(request, "lot/forward.html", {"f": f, "r": result, "error": error},
                             screen_id="LOT-010", status_code=422 if error else 200)


@router.get(nav.path_of("LOT-020"), response_class=HTMLResponse)
def backward(request: Request, user: rbac.User = rbac.require_screen("LOT-020")):
    f = {"shipment_no": qs(request, "shipment_no"), "product_lot_no": qs(request, "product_lot_no")}
    result, error = None, None
    if f["shipment_no"] and f["product_lot_no"]:
        error = "출하 번호와 제품 LOT 번호 중 하나만 입력하세요"
    elif f["shipment_no"] or f["product_lot_no"]:
        try:
            result = trace.backward(shipment_no=f["shipment_no"] or None, product_lot_no=f["product_lot_no"] or None)
        except trace.NotFound:
            error = (f"없는 출하 번호입니다: {f['shipment_no'][:60]}" if f["shipment_no"]
                     else f"없는 제품 LOT 번호입니다: {f['product_lot_no'][:60]}")
    return templating.render(request, "lot/backward.html", {"f": f, "r": result, "error": error},
                             screen_id="LOT-020", status_code=422 if error else 200)
