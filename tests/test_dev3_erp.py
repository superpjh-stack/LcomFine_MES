"""ERP 연계 (G-16 · D-02) — 연계 범위·방식이 정해지지 않았다. 어댑터는 무엇을 부르든 501 `ERP 연계 미확정 (D-02)` 이다.

조용한 폴백(빈 목록 · "성공")이 없는지를 본다. `/erp/{kind}` 라우트는 아키텍트의 `main.py` 에 있고 이 어댑터를 부른다.
"""
import inspect

import pytest
from fastapi import HTTPException

from lcomfine.app import erp

from test_dev3_support import client


def test_adapter_raises_501_for_every_call():
    adapter = erp.adapter()
    assert isinstance(adapter, erp.UndecidedErp) and erp.DECISION == "D-02"
    for call in (adapter.status, lambda: adapter.send("출하 실적", {"shipment_no": "(예시)"}), lambda: adapter.receive("수주")):
        with pytest.raises(HTTPException) as caught:
            call()
        assert caught.value.status_code == 501
        assert caught.value.detail == {"code": "undecided", "message": "ERP 연계 미확정 (D-02)", "decision": "D-02"}


def test_adapter_has_no_silent_fallback():
    """오류를 잡아 기본값을 돌려주는 코드가 없다 — `except` 도, 값을 돌려주는 `return` 도 `adapter()` 하나뿐이다."""
    src = inspect.getsource(erp)
    assert "except" not in src and "try:" not in src
    returns = [ln.strip() for ln in src.splitlines() if ln.strip().startswith("return")]
    assert returns == ["return UndecidedErp()"]
    for name in ("status", "send", "receive"):                    # 어댑터 인터페이스 세 가지가 전부 구현돼 있다
        assert callable(getattr(erp.UndecidedErp, name)) and name in erp.ErpAdapter.__dict__


@pytest.mark.parametrize("method, path", [("GET", "/erp/status"), ("GET", "/erp/orders"), ("POST", "/erp/shipments")])
def test_erp_endpoints_answer_501_not_empty_success(method, path):
    r = client("admin").request(method, path)
    assert r.status_code == 501
    assert r.json() == {"code": "undecided", "message": "ERP 연계 미확정 (D-02)", "decision": "D-02"}
    assert client().request(method, path).status_code == 401      # 로그인 없이는 501 도 아니다
    page = client("prod").request(method, path, headers={"accept": "text/html"})
    assert page.status_code == 501 and "ERP 연계 미확정 (D-02)" in page.text   # 브라우저에도 그대로 보인다
