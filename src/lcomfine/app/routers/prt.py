"""prt 라우터 — 인쇄 기준 관리 (기능 12) · 담당 개발1.

쓰는 저장소: D1 (`plate_spec` `anilox` `ink_formula` `ink_formula_component`). 이 밖의 테이블에는 쓰지 않는다(G-05).

세 중메뉴 모두 마스터 4기능이다 — 처리는 `bas.py` 의 `Master` + `register` 한 벌을 그대로 쓴다(규약은 그 파일 머리말).
잉크조성만 자식 행(성분·비율)이 있어 갈고리 셋(`parse_extra` · `save_extra` · `load_extra`)을 건다.

규격 값(도수·선수·셀 용적·기준 색상값·조성 비율)은 받은 적이 없다 — 화면은 입력받은 값만 보여 주고 비어 있으면 `-` 다(D-18).

담당 화면과 기능 (contracts/function-list.md)
  PRT-01 판사양 관리 → /prt/plates     F-PRT-01~04
  PRT-02 아니록스 관리 → /prt/anilox   F-PRT-05~08
  PRT-03 잉크조성 관리 → /prt/inks     F-PRT-09~12  (수정하면 조성 행은 통째로 바꿔 넣는다)
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from fastapi import APIRouter
from starlette.datastructures import FormData

from ...db import conn
from .bas import Field, Master, bad, register

router = APIRouter()

COMPONENT_NAME, COMPONENT_RATIO = "component_name", "ratio_pct"
MAX_COMPONENTS = 50


# ── 잉크조성의 조성 행 (ink_formula_component) ───────────────────────────
def parse_components(form: FormData) -> list[tuple[str, Decimal]] | None:
    """폼의 `component_name` · `ratio_pct` (같은 순서로 여러 개) → [(성분명, 비율)].

    두 이름이 폼에 아예 없으면 None — 조성 행을 건드리지 않는다. 있으면 그 목록으로 **통째로** 바꾼다(빈 줄은 건너뛴다).
    비율은 0 초과 100 이하. 합이 100 인지는 따지지 않는다 — 계약에 그 문장이 없다(D-102).
    """
    if COMPONENT_NAME not in form and COMPONENT_RATIO not in form:
        return None
    names = [v.strip() if isinstance(v, str) else "" for v in form.getlist(COMPONENT_NAME)]
    ratios = [v.strip() if isinstance(v, str) else "" for v in form.getlist(COMPONENT_RATIO)]
    if len(names) != len(ratios):
        raise bad("조성 행을 확인해 주세요", "조성", "성분과 비율의 수가 다릅니다")
    rows: list[tuple[str, Decimal]] = []
    for i, (name, ratio) in enumerate(zip(names, ratios), start=1):
        if not name and not ratio:
            continue
        if not name or not ratio:
            raise bad("조성 행을 확인해 주세요", f"조성 {i}행", "성분과 비율을 함께 적습니다")
        if "\x00" in name or len(name) > 200:
            raise bad("조성 행을 확인해 주세요", f"조성 {i}행", "성분명을 확인합니다")
        try:
            value = Decimal(ratio.replace(",", ""))
        except InvalidOperation:
            raise bad("조성 행을 확인해 주세요", f"조성 {i}행", f"비율이 숫자가 아닙니다: {ratio}") from None
        if not value.is_finite() or round(value, 3) <= 0 or value > 100:
            raise bad("조성 행을 확인해 주세요", f"조성 {i}행", f"비율은 0 초과 100 이하입니다: {ratio}")
        rows.append((name, round(value, 3)))
    if len(rows) > MAX_COMPONENTS:
        raise bad("조성 행을 확인해 주세요", "조성", f"{MAX_COMPONENTS}행을 넘습니다")
    return rows


def save_components(cur, ink_formula_id: int, rows: list[tuple[str, Decimal]]) -> None:
    cur.execute("delete from ink_formula_component where ink_formula_id = %s", (ink_formula_id,))
    for seq_no, (name, ratio) in enumerate(rows, start=1):
        cur.execute("""insert into ink_formula_component (ink_formula_id, seq_no, component_name, ratio_pct)
                       values (%s, %s, %s, %s)""", (ink_formula_id, seq_no, name, ratio))


def load_components(ink_formula_id: int) -> list[dict]:
    return conn.q("""select seq_no, component_name, ratio_pct from ink_formula_component
                      where ink_formula_id = %s order by seq_no""", (ink_formula_id,))


# ── 인쇄 기준 3종 ───────────────────────────────────────────────────────
PLATE = Master(
    screen_id="PRT-01", label="판사양", table="plate_spec", pk="plate_spec_id",
    code_col="plate_code", code_label="판 코드", name_col="plate_name", name_label="판명",
    fields=(
        Field("item_id", "품목", kind="ref", ref=("item", "item_id", "item_code", "item_name"), ref_where="item_type = '제품'"),
        Field("color_count", "도수", kind="int", positive=True),
        Field("spec_note", "사양 메모", ),
    ),
    fn_create="F-PRT-01", fn_update="F-PRT-02", fn_delete="F-PRT-03", fn_read="F-PRT-04",
    list_sql="""select t.plate_spec_id as id, t.plate_code as code, t.plate_name as name, t.color_count, t.spec_note, t.use_yn,
                       i.item_code || ' · ' || i.item_name as item
                  from plate_spec t left join item i on i.item_id = t.item_id
                 where {where} order by t.plate_code""",
    columns=(("품목", "item"), ("도수", "color_count"), ("사양 메모", "spec_note")),
    notes=("도수는 구조만 정한 가설 컬럼이다 — 값은 입력받은 것만 보인다(D-18).",
           "작업지시가 쓰는 판사양은 지울 수 없다. 그때는 사용 여부를 `미사용` 으로 바꾼다(D-21)."),
)

ANILOX = Master(
    screen_id="PRT-02", label="아니록스", table="anilox", pk="anilox_id",
    code_col="anilox_code", code_label="아니록스 코드", name_col="anilox_name", name_label="명칭",
    fields=(
        Field("line_count", "선수", kind="decimal", positive=True, int_digits=8, scale=2, step="0.01"),
        Field("cell_volume", "셀 용적", kind="decimal", positive=True, int_digits=7, scale=3, step="0.001"),
        Field("note", "비고"),
    ),
    fn_create="F-PRT-05", fn_update="F-PRT-06", fn_delete="F-PRT-07", fn_read="F-PRT-08",
    list_sql="""select t.anilox_id as id, t.anilox_code as code, t.anilox_name as name, t.line_count, t.cell_volume,
                       t.note, t.use_yn
                  from anilox t where {where} order by t.anilox_code""",
    columns=(("선수", "line_count"), ("셀 용적", "cell_volume"), ("비고", "note")),
    notes=("선수·셀 용적은 구조만 정한 가설 컬럼이고 단위는 받은 적이 없다(D-18).",
           "작업지시가 쓰는 아니록스는 지울 수 없다(D-21)."),
)

INK = Master(
    screen_id="PRT-03", label="잉크조성", table="ink_formula", pk="ink_formula_id",
    code_col="ink_code", code_label="잉크 코드", name_col="ink_name", name_label="잉크명",
    fields=(
        Field("color_name", "색 이름"),
        Field("target_l", "기준 색상값 L", kind="decimal", int_digits=5, scale=2, step="0.01"),
        Field("target_a", "기준 색상값 a", kind="decimal", int_digits=5, scale=2, step="0.01"),
        Field("target_b", "기준 색상값 b", kind="decimal", int_digits=5, scale=2, step="0.01"),
        Field("note", "비고"),
    ),
    fn_create="F-PRT-09", fn_update="F-PRT-10", fn_delete="F-PRT-11", fn_read="F-PRT-12",
    list_sql="""select t.ink_formula_id as id, t.ink_code as code, t.ink_name as name, t.color_name,
                       t.target_l, t.target_a, t.target_b, t.note, t.use_yn,
                       (select string_agg(c.component_name || ' ' || trim(to_char(c.ratio_pct, 'FM990.###'), '.') || '%%',
                                          ' / ' order by c.seq_no)
                          from ink_formula_component c where c.ink_formula_id = t.ink_formula_id) as components
                  from ink_formula t where {where} order by t.ink_code""",
    columns=(("색 이름", "color_name"), ("L", "target_l"), ("a", "target_a"), ("b", "target_b"), ("조성 (성분 비율)", "components")),
    template="prt/inks.html",
    notes=("기준 색상값은 Lab 으로 가정한 가설 컬럼이다(D-18). 조성 행은 수정할 때 통째로 바꿔 넣는다.",
           "작업지시·조색 기록이 쓰는 잉크조성은 지울 수 없다(D-21)."),
    parse_extra=parse_components, save_extra=save_components, load_extra=load_components,
)

MASTERS: tuple[Master, ...] = (PLATE, ANILOX, INK)
for _m in MASTERS:
    register(router, _m)
