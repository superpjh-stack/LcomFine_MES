"""출력 어댑터 — 라벨 3종(원재료 LOT · 인쇄 롤 · 롤)과 바코드 (G-14 · decisions.md D-04).

담당 **개발2**. 아키텍트가 만든 것은 시그니처뿐이다.

프린터 규격이 미정이므로 지금의 어댑터는 **브라우저 인쇄**다. 규격이 정해지면 `render_label` 만 바꾼다 —
화면·라우터는 `Label` 을 만들어 넘길 뿐 출력 방식을 모른다.
바코드는 인라인 SVG 로 그린다(외부 CDN·이미지 0). 스캐너가 읽은 값은 그 번호 글자 그대로여야 한다 —
라벨의 바코드를 POP 스캔칸에 넣으면 그 LOT/롤이 열린다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from markupsafe import Markup

MATERIAL_LOT_LABEL, PRINT_ROLL_LABEL, ROLL_LABEL = "원재료 LOT 라벨", "인쇄 롤 라벨", "롤 라벨"

_TODO = "미구현 — 담당 개발2 (app/printing.py)"


@dataclass(frozen=True)
class Label:
    kind: str                                   # 원재료 LOT 라벨 | 인쇄 롤 라벨 | 롤 라벨
    number: str                                 # 바코드로 찍는 번호 (lot_no · roll_no)
    lines: list[tuple[str, str]] = field(default_factory=list)   # (항목명, 값) — 품목·Job·길이 등


def barcode_svg(value: str, *, height: int = 48, show_text: bool = True) -> Markup:
    """번호를 Code 128 인라인 SVG 로 그린다. 작업지시서·COA 도 이 함수를 쓴다. 빈 값은 ValueError."""
    raise NotImplementedError(_TODO)


def material_lot_label(lot_no: str) -> Label:
    """원재료 LOT 라벨 내용(F-MAT-06). 없는 LOT 은 422."""
    raise NotImplementedError(_TODO)


def roll_label(roll_no: str) -> Label:
    """롤 라벨 내용. 인쇄 롤이면 kind 가 `인쇄 롤 라벨`(F-POP-08), 후가공·슬리팅 롤이면 `롤 라벨`(F-RLL-07). 없는 롤은 422."""
    raise NotImplementedError(_TODO)


def render_label(label: Label) -> Markup:
    """라벨 한 장의 인쇄용 HTML 조각(바코드 SVG + 번호 + 항목). **출력 방식이 바뀌면 여기만 고친다.**"""
    raise NotImplementedError(_TODO)
