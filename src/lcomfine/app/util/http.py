"""오류 규약 — `contracts/api-contract.md` · `goal.md` §2.5.

| 상황 | status | code | 메시지 |
|---|---|---|---|
| 필수값 누락 · 코드 중복 · 없는 LOT/롤 스캔 · 재출하 · 자기 자신을 부모로 하는 계보 | 422 | validation_error | 항목별 사유 |
| 인증 실패 | 401 | unauthorized | 로그인이 필요합니다 (브라우저 GET 은 /login 303) |
| 권한 없음 | 403 | forbidden | 접근 권한이 없습니다 |
| 대상 없음 (경로의 키) | 404 | not_found | 대상을 찾을 수 없습니다 |
| DB 연결 실패 | 503 | db_unavailable | 서비스 일시 중단 |
| ERP 연계 · 미확정 연계 | 501 | undecided | 미확정 (D-nn) |
| 처리되지 않은 예외 | 500 | internal_error | 예상하지 못한 오류 |

**조용한 실패 금지.** 오류를 잡아 기본값으로 대체하지 않는다. 여기 정의된 예외로 올린다.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

# code → (status, 기본 메시지)
ERRORS: dict[str, tuple[int, str]] = {
    "validation_error": (422, "입력값을 확인해 주세요"),
    "unauthorized": (401, "로그인이 필요합니다"),
    "forbidden": (403, "접근 권한이 없습니다"),
    "not_found": (404, "대상을 찾을 수 없습니다"),
    "db_unavailable": (503, "서비스 일시 중단"),
    "undecided": (501, "미확정"),
    "internal_error": (500, "예상하지 못한 오류"),
}

#: 화면 전환 뒤 한 번만 보이는 알림 (쓰기 성공 · 입력 검증 실패)
FLASH_KEY = "flash"


def flash(request, title: str, message: str, *, fields: list[dict] | None = None, kind: str = "info") -> None:
    """다음 화면에서 한 번만 뜨는 알림을 세션에 넣는다."""
    if not hasattr(request, "session"):
        return
    request.session[FLASH_KEY] = {"title": title, "message": message, "kind": kind, "fields": fields or []}


def pop_flash(request) -> dict | None:
    if not hasattr(request, "session"):
        return None
    return request.session.pop(FLASH_KEY, None)


def wants_html(request) -> bool:
    return "text/html" in (request.headers.get("accept") or "")


def saved(request, message: str = "저장했습니다", *, back: str | None = None, data: dict | None = None):
    """쓰기 성공 규약(D-21). 브라우저(HTML)는 알림을 남기고 원래 화면으로 303, 그 밖(JSON·테스트)은 200 JSON.

        return http.saved(request, "품목을 등록했습니다", data={"item_id": new_id})
    """
    from fastapi.responses import JSONResponse, RedirectResponse  # noqa

    if not wants_html(request):
        return JSONResponse({"ok": True, "message": message, **(data or {})})
    flash(request, "알림", message, kind="ok")
    return RedirectResponse(back or request.headers.get("referer") or "/", status_code=303)


def err(status: int, code: str, message: str, **extra: Any) -> HTTPException:
    """계약대로 HTTPException 을 만든다. detail 은 항상 code·message 를 가진 dict."""
    detail: dict[str, Any] = {"code": code, "message": message}
    detail.update({k: v for k, v in extra.items() if v is not None})
    return HTTPException(status_code=status, detail=detail)


def _by_code(code: str, message: str | None = None, **extra: Any) -> HTTPException:
    status, default = ERRORS[code]
    return err(status, code, message or default, **extra)


def validation_error(message: str | None = None, *, fields: list[dict] | None = None) -> HTTPException:
    """422. `fields` 는 [{'name':..., 'reason':...}] — 항목별 사유.

        raise http.validation_error("이미 출하된 롤입니다", fields=[{"name": "롤 번호", "reason": roll_no}])
    """
    return _by_code("validation_error", message, fields=fields or [])


def unauthorized(message: str | None = None) -> HTTPException:
    return _by_code("unauthorized", message)


def forbidden(message: str | None = None, **extra: Any) -> HTTPException:
    """403. `extra` 로 거부 사유를 덧붙인다 — 예 `function_id="F-SHP-05"`."""
    return _by_code("forbidden", message, **extra)


def not_found(message: str | None = None) -> HTTPException:
    return _by_code("not_found", message)


def db_unavailable(message: str | None = None, *, reason: str | None = None) -> HTTPException:
    return _by_code("db_unavailable", message, reason=reason)


def undecided(decision: str, what: str = "") -> HTTPException:
    """501 — 사람이 아직 정하지 않은 연계. `undecided("D-02", "ERP 연계")` → `ERP 연계 미확정 (D-02)`. 조용한 폴백 금지."""
    label = f"{what} 미확정 ({decision})" if what else f"미확정 ({decision})"
    return _by_code("undecided", label, decision=decision)


def status_message(status: int) -> str:
    for _code, (st, msg) in ERRORS.items():
        if st == status:
            return msg
    return "오류가 발생했습니다"


def code_for_status(status: int) -> str:
    for code, (st, _msg) in ERRORS.items():
        if st == status:
            return code
    return "error"


# ── 보안 헤더 ──
SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
    "Referrer-Policy": "same-origin",
    "Cache-Control": "no-store",
}
