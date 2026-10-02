"""ERP 연계 어댑터 — 연계 범위·방식 미정 (decisions.md D-02 · G-16).

담당 **개발3**. 지금의 어댑터는 `UndecidedErp` 하나다 — 무엇을 부르든 **501 `ERP 연계 미확정 (D-02)`** 를 올린다.
빈 목록이나 "성공" 을 돌려주는 조용한 폴백을 두지 않는다. 연계가 정해지면 `ErpAdapter` 를 구현한 클래스를
하나 더 만들고 `adapter()` 가 그것을 돌려주게 한다 — 부르는 쪽은 바뀌지 않는다.
"""

from __future__ import annotations

from typing import Protocol

from .util import http

DECISION = "D-02"


class ErpAdapter(Protocol):
    def status(self) -> dict:
        """연계 상태."""

    def send(self, kind: str, payload: dict) -> dict:
        """MES → ERP 로 한 건을 보낸다 (kind 예: 출하 실적)."""

    def receive(self, kind: str) -> list[dict]:
        """ERP → MES 로 받아 온다 (kind 예: 수주)."""


class UndecidedErp:
    """연계가 정해지기 전의 어댑터 — 전부 501."""

    def status(self) -> dict:
        raise http.undecided(DECISION, "ERP 연계")

    def send(self, kind: str, payload: dict) -> dict:
        raise http.undecided(DECISION, "ERP 연계")

    def receive(self, kind: str) -> list[dict]:
        raise http.undecided(DECISION, "ERP 연계")


def adapter() -> ErpAdapter:
    return UndecidedErp()
