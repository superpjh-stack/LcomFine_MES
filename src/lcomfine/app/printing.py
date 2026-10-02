"""출력 어댑터 — 라벨 3종(원재료 LOT · 인쇄 롤 · 롤)과 바코드 (G-14 · decisions.md D-04).

담당 **개발2**. 사용법 공표는 `progress-dev2.md` §1.2.

프린터 규격이 미정이므로 지금의 어댑터는 **브라우저 인쇄**다. 규격이 정해지면 `render_label` 만 바꾼다 —
화면·라우터는 `Label` 을 만들어 넘길 뿐 출력 방식을 모른다.
바코드는 Code 128 을 이 파일에서 직접 만들어 인라인 SVG 로 그린다(외부 CDN·라이브러리·이미지 0).
스캐너가 읽은 값은 그 번호 글자 그대로여야 한다 — 라벨의 바코드를 POP 스캔칸에 넣으면 그 LOT/롤이 열린다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from markupsafe import Markup, escape

from ..db import conn
from .util import http, screen

MATERIAL_LOT_LABEL, PRINT_ROLL_LABEL, ROLL_LABEL = "원재료 LOT 라벨", "인쇄 롤 라벨", "롤 라벨"


@dataclass(frozen=True)
class Label:
    kind: str                                   # 원재료 LOT 라벨 | 인쇄 롤 라벨 | 롤 라벨
    number: str                                 # 바코드로 찍는 번호 (lot_no · roll_no)
    lines: list[tuple[str, str]] = field(default_factory=list)   # (항목명, 값) — 품목·Job·길이 등


# ── Code 128 ────────────────────────────────────────────────────────────
#: 심벌 값 0~105 의 막대·공백 폭(막대부터 번갈아 6개, 합 11 모듈). ISO/IEC 15417 의 표.
CODE128_WIDTHS: tuple[str, ...] = (
    "212222", "222122", "222221", "121223", "121322", "131222", "122213", "122312", "132212", "221213",
    "221312", "231212", "112232", "122132", "122231", "113222", "123122", "123221", "223211", "221132",
    "221231", "213212", "223112", "312131", "311222", "321122", "321221", "312212", "322112", "322211",
    "212123", "212321", "232121", "111323", "131123", "131321", "112313", "132113", "132311", "211313",
    "231113", "231311", "112133", "112331", "132131", "113123", "113321", "133121", "313121", "211331",
    "231131", "213113", "213311", "213131", "311123", "311321", "331121", "312113", "312311", "332111",
    "314111", "221411", "431111", "111224", "111422", "121124", "121421", "141122", "141221", "112214",
    "112412", "122114", "122411", "142112", "142211", "241211", "221114", "413111", "241112", "134111",
    "111242", "121142", "121241", "114212", "124112", "124211", "411212", "421112", "421211", "212141",
    "214121", "412121", "111143", "111341", "131141", "114113", "114311", "411113", "411311", "113141",
    "114131", "311141", "411131", "211412", "211214", "211232",
)
CODE128_STOP_WIDTHS = "2331112"            # 정지 심벌 — 13 모듈
START_B, START_C = 104, 105
CODE_B, CODE_C = 100, 99                   # 세트 C 안의 `B 로`, 세트 B 안의 `C 로`
QUIET_ZONE = 10                            # 좌우 여백(모듈) — 규격의 최소값
MODULE_PX = 2                              # 화면에서의 모듈 폭(px). 인쇄 때는 viewBox 비율대로 늘어난다


def _is_digit(ch: str) -> bool:
    return "0" <= ch <= "9"


def _digit_run(value: str, i: int) -> int:
    n = 0
    while i + n < len(value) and _is_digit(value[i + n]):
        n += 1
    return n


def code128_symbols(value: str) -> list[int]:
    """번호 → Code 128 심벌 값 목록 (시작 + 데이터 + 체크섬, 정지 제외).

    세트 B(ASCII 32~126)로 찍고, 숫자가 길게 이어지는 곳만 세트 C(두 자리 = 한 심벌)로 바꿔 폭을 줄인다.
    체크섬 = (시작 값 + Σ 위치 × 값) mod 103. 빈 값·세트 B 밖의 글자는 ValueError(조용히 지우거나 바꾸지 않는다).
    """
    if not isinstance(value, str) or value == "":
        raise ValueError("바코드로 찍을 값이 비어 있다")
    bad = sorted({ch for ch in value if not 32 <= ord(ch) <= 126})
    if bad:
        raise ValueError(f"Code 128(세트 B)로 찍을 수 없는 글자: {bad!r}")
    n = len(value)
    first_run = _digit_run(value, 0)
    in_c = first_run >= 4 or (first_run == n and n % 2 == 0)
    symbols = [START_C if in_c else START_B]
    i = 0
    while i < n:
        if in_c:
            if i + 1 < n and _is_digit(value[i]) and _is_digit(value[i + 1]):
                symbols.append(int(value[i:i + 2]))
                i += 2
            else:
                symbols.append(CODE_B)
                in_c = False
            continue
        run = _digit_run(value, i)
        if run >= 4 and (i + run == n or run >= 6):
            if run % 2 == 1:                       # 홀수면 한 자리는 B 로 찍고 나머지를 C 로
                symbols.append(ord(value[i]) - 32)
                i += 1
            symbols.append(CODE_C)
            in_c = True
            continue
        symbols.append(ord(value[i]) - 32)
        i += 1
    symbols.append((symbols[0] + sum(pos * v for pos, v in enumerate(symbols[1:], start=1))) % 103)
    return symbols


def code128_modules(value: str) -> str:
    """번호 → 모듈 문자열(`1` 막대 · `0` 공백). 시작 · 데이터 · 체크섬 · 정지. 좌우 여백은 포함하지 않는다."""
    out: list[str] = []
    for widths in [CODE128_WIDTHS[s] for s in code128_symbols(value)] + [CODE128_STOP_WIDTHS]:
        for k, w in enumerate(widths):
            out.append(("1" if k % 2 == 0 else "0") * int(w))
    return "".join(out)


def barcode_svg(value: str, *, height: int = 48, show_text: bool = True) -> Markup:
    """번호를 Code 128 인라인 SVG 로 그린다. 작업지시서·COA 도 이 함수를 쓴다. 빈 값은 ValueError.

    바코드가 담는 값은 `value` 글자 그대로다(앞뒤에 아무것도 붙이지 않는다). `height` 는 막대 높이(px),
    `show_text` 면 막대 아래에 번호를 사람이 읽는 글자로 찍는다. 돌려주는 값은 `Markup` — 템플릿에 `{{ … }}` 로 넣는다.
    """
    modules = code128_modules(value)
    height = max(8, int(height))
    m = MODULE_PX
    width = (len(modules) + 2 * QUIET_ZONE) * m     # 좌우 여백(quiet zone) 포함
    text_h = 16 if show_text else 0
    rects: list[str] = []
    x = 0
    while x < len(modules):                         # 이어진 막대 모듈을 사각형 하나로
        if modules[x] == "1":
            w = 1
            while x + w < len(modules) and modules[x + w] == "1":
                w += 1
            rects.append(f'<rect x="{(QUIET_ZONE + x) * m}" y="0" width="{w * m}" height="{height}"/>')
            x += w
        else:
            x += 1
    safe = escape(value)
    text = (f'<text x="{width / 2:g}" y="{height + 12}" text-anchor="middle" font-family="monospace" '
            f'font-size="12" fill="#000">{safe}</text>') if show_text else ""
    return Markup(
        f'<svg class="barcode" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="바코드 {safe}" '
        f'data-barcode="{safe}" data-symbology="code128" data-module="{m}" '
        f'viewBox="0 0 {width} {height + text_h}" width="{width}" height="{height + text_h}" '
        f'shape-rendering="crispEdges">'
        f'<rect class="bg" x="0" y="0" width="{width}" height="{height + text_h}" fill="#fff"/>'
        f'<g class="bars" fill="#000">{"".join(rects)}</g>{text}</svg>')


# ── 라벨 내용 (DB 에서 읽기만 한다) ─────────────────────────────────────
def material_lot_label(lot_no: str) -> Label:
    """원재료 LOT 라벨 내용(F-MAT-06). 없는 LOT 은 422."""
    r = conn.q1(
        """select m.lot_no, m.supplier_name, m.supplier_lot_no, m.received_qty, m.qty_unit, m.received_at, m.insp_status,
                  i.item_code, i.item_name
             from material_lot m join item i on i.item_id = m.item_id
            where m.lot_no = %s""", ((lot_no or "").strip(),))
    if r is None:
        raise http.validation_error("없는 원재료 LOT 입니다", fields=[{"name": "LOT 번호", "reason": str(lot_no)}])
    lines = [
        ("품목", f"{r['item_name']} [{r['item_code']}]"),
        ("입고일", screen.dt(r["received_at"], "%Y-%m-%d")),
        ("입고 수량", f"{screen.num(r['received_qty'], 3)} {screen.txt(r['qty_unit'], '')}".strip()),
        ("검사 상태", r["insp_status"]),
        ("공급처", screen.txt(r["supplier_name"])),
        ("공급사 LOT", screen.txt(r["supplier_lot_no"])),
    ]
    return Label(MATERIAL_LOT_LABEL, r["lot_no"], lines)


def roll_label(roll_no: str) -> Label:
    """롤 라벨 내용. 인쇄 롤이면 kind 가 `인쇄 롤 라벨`(F-POP-08), 후가공·슬리팅 롤이면 `롤 라벨`(F-RLL-07). 없는 롤은 422."""
    r = conn.q1(
        """select r.roll_no, r.process_type, r.length_m, r.width_mm, r.slit_seq, r.produced_at,
                  j.job_no, jl.lot_no as job_lot_no, i.item_code, i.item_name
             from roll r
             join job j on j.job_id = r.job_id
             join item i on i.item_id = j.item_id
             left join job_lot jl on jl.job_lot_id = r.job_lot_id
            where r.roll_no = %s""", ((roll_no or "").strip(),))
    if r is None:
        raise http.validation_error("없는 롤입니다", fields=[{"name": "롤 번호", "reason": str(roll_no)}])
    lines = [
        ("공정 구분", r["process_type"] + (f" (분할 {r['slit_seq']})" if r["slit_seq"] else "")),
        ("Job", r["job_no"]),
        ("생산 LOT", screen.txt(r["job_lot_no"])),
        ("품목", f"{r['item_name']} [{r['item_code']}]"),
        ("길이 (m)", screen.num(r["length_m"], 3)),
        ("폭 (mm)", screen.num(r["width_mm"], 2)),
        ("생산 일시", screen.dt(r["produced_at"])),
    ]
    return Label(PRINT_ROLL_LABEL if r["process_type"] == "인쇄" else ROLL_LABEL, r["roll_no"], lines)


# ── 출력 방식 (D-04: 지금은 브라우저 인쇄) ──────────────────────────────
_LABEL_STYLE = ("display:inline-block;box-sizing:border-box;width:92mm;min-height:56mm;margin:0 6px 6px 0;padding:4mm;"
                "border:1px solid #000;background:#fff;color:#000;vertical-align:top;break-inside:avoid;"
                "page-break-inside:avoid;font-size:12px;line-height:1.45")


def render_label(label: Label) -> Markup:
    """라벨 한 장의 인쇄용 HTML 조각(바코드 SVG + 번호 + 항목). **출력 방식이 바뀌면 여기만 고친다.**

    스타일은 조각 안에 들어 있다(공용 CSS 에 기대지 않는다). 여러 장을 이어 붙이면 장마다 잘리지 않게 나뉜다.
    """
    rows = "".join(
        f'<tr><th style="text-align:left;padding:1px 8px 1px 0;font-weight:600;white-space:nowrap">{escape(k)}</th>'
        f'<td style="padding:1px 0">{escape(v)}</td></tr>' for k, v in label.lines)
    return Markup(
        f'<section class="label" data-label-kind="{escape(label.kind)}" data-label-number="{escape(label.number)}" '
        f'style="{_LABEL_STYLE}">'
        f'<div style="font-size:13px;font-weight:700;border-bottom:1px solid #000;padding-bottom:2px;margin-bottom:4px">'
        f'{escape(label.kind)}</div>'
        f'<div style="text-align:center;margin:4px 0">{barcode_svg(label.number, height=52)}</div>'
        f'<table style="border-collapse:collapse;width:100%">{rows}</table>'
        f'</section>')
