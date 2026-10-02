"""bas 라우터 — 기준정보 관리 (기능 20) · 담당 개발1.

쓰는 저장소: D1 (`item` `customer` `process` `equipment` `defect_code`). 이 밖의 테이블에는 쓰지 않는다(G-05).

다섯 중메뉴가 전부 **마스터 4기능**(등록·수정·삭제·조회)이라 한 벌의 처리(`Master` + `register`)를 설정만 바꿔 다섯 번 건다.
인쇄 기준 관리(`prt.py`)도 같은 것을 쓴다. 규약은 여기 한 곳에 있다:

  · 조회  `GET <화면>` — `?code=` `?name=` `?use_yn=` 로 검색, `?edit=<id>` 로 수정 폼을 연다. 0건이면 `미수집`(G-11).
  · 등록  `POST <화면>` — 코드 중복·필수값 누락 422.
  · 수정  `POST <화면>/{id}` — 코드는 못 바꾼다(다른 코드를 보내면 422). 폼에 없는 항목은 그대로 둔다. 없는 ID 404.
  · 삭제  `POST <화면>/{id}/delete` — 다른 테이블이 참조하면 422 `사용 중이라 삭제할 수 없습니다`(D-21). 없는 ID 404.
  · 쓰기 성공 직후 `audit.log_change` (G-18). 권한은 `rbac.require_fn` — 조회 역할의 쓰기는 403.

담당 화면과 기능 (contracts/function-list.md)
  BAS-01 품목 관리 → /bas/items            F-BAS-01~04
  BAS-02 고객 관리 → /bas/customers        F-BAS-05~08
  BAS-03 공정 관리 → /bas/processes        F-BAS-09~12
  BAS-04 설비 관리 → /bas/equipment        F-BAS-13~16  (설비 상태·수집값은 받지 않는다, G-12)
  BAS-05 불량코드 관리 → /bas/defect-codes F-BAS-17~20
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from starlette.datastructures import FormData

from ...db import conn
from .. import nav, rbac, templating
from ..util import audit, http

router = APIRouter()

IN_USE = "사용 중이라 삭제할 수 없습니다"
LIST_LIMIT = 1000          # 서버는 상한만 건다 — 화면이 한 쪽씩 보인다(app.js)
USE_YN = (("Y", "사용"), ("N", "미사용"))
INT_MAX = 2_147_483_647

#: 참조하는 테이블의 화면 이름 (삭제 422 의 사유에 쓴다)
TABLE_LABEL = {
    "job": "작업지시", "job_lot": "생산 LOT", "material_lot": "원재료 LOT", "plate_spec": "판사양", "equipment": "설비",
    "work_result": "작업 실적", "work_scrap": "폐기 기록", "roll": "롤", "inspection_defect": "검사 불량",
    "color_record": "조색 기록", "shipment": "출하", "anilox": "아니록스", "ink_formula": "잉크조성",
}


# ── 폼 값 읽기 (계약: 필수값 누락·형식 오류는 422) ───────────────────────
async def form_data(request: Request) -> FormData:
    """HTML 폼 본문. 항목이 화면마다 달라 한꺼번에 받는다 — 검증은 `parse_*` 가 한다."""
    return await request.form()


def bad(message: str, name: str, reason: str) -> Exception:
    return http.validation_error(message, fields=[{"name": name, "reason": reason}])


def text_of(form: FormData, key: str, label: str, *, required: bool = False, max_len: int = 500) -> str | None:
    """글자 항목. 앞뒤 공백을 떼고, 비면 None(필수면 422)."""
    raw = form.get(key)
    value = raw.strip() if isinstance(raw, str) else ""
    if "\x00" in value:
        raise bad("입력값을 확인해 주세요", label, "쓸 수 없는 글자가 들어 있습니다")
    if len(value) > max_len:
        raise bad("입력값을 확인해 주세요", label, f"{max_len}자를 넘습니다")
    if not value:
        if required:
            raise bad("필수값이 빠졌습니다", label, "필수값입니다")
        return None
    return value


def int_of(form: FormData, key: str, label: str, *, required: bool = False, positive: bool = False) -> int | None:
    value = text_of(form, key, label, required=required, max_len=20)
    if value is None:
        return None
    try:
        number = int(value)
    except ValueError:
        raise bad("입력값을 확인해 주세요", label, f"정수가 아닙니다: {value}") from None
    if abs(number) > INT_MAX:
        raise bad("입력값을 확인해 주세요", label, "값이 너무 큽니다")
    if positive and number <= 0:
        raise bad("입력값을 확인해 주세요", label, "0 보다 커야 합니다")
    return number


def decimal_of(form: FormData, key: str, label: str, *, required: bool = False, positive: bool = False,
               non_negative: bool = False, int_digits: int = 11, scale: int = 3) -> Decimal | None:
    """숫자 항목. `int_digits` = 정수부 자릿수 상한(컬럼 numeric(p,s) 의 p−s), `scale` = 소수 자릿수."""
    value = text_of(form, key, label, required=required, max_len=40)
    if value is None:
        return None
    try:
        number = Decimal(value.replace(",", ""))
    except InvalidOperation:
        raise bad("입력값을 확인해 주세요", label, f"숫자가 아닙니다: {value}") from None
    if not number.is_finite():
        raise bad("입력값을 확인해 주세요", label, f"숫자가 아닙니다: {value}")
    number = round(number, scale)
    if abs(number) >= Decimal(10) ** int_digits:
        raise bad("입력값을 확인해 주세요", label, "값이 너무 큽니다")
    if positive and number <= 0:
        raise bad("입력값을 확인해 주세요", label, "0 보다 커야 합니다")
    if non_negative and number < 0:
        raise bad("입력값을 확인해 주세요", label, "0 이상이어야 합니다")
    return number


def id_of_path(raw: str) -> int:
    """경로의 `{id}`. 숫자가 아니거나 범위를 벗어나면 그런 대상은 없다 → 404."""
    if not raw.isascii() or not raw.isdigit() or len(raw) > 18:
        raise http.not_found()
    return int(raw)


def contains(column: str) -> str:
    """부분 일치 조건(대소문자 무시). `%`·`_` 를 와일드카드로 보지 않는다."""
    return f"position(lower(%s) in lower({column})) > 0"


# ── 참조 검사 (삭제 422) ────────────────────────────────────────────────
def references_to(table: str, pk: str, row_id: int) -> list[str]:
    """`table.pk = row_id` 를 가리키는 다른 테이블들. FK 는 DB 카탈로그에서 읽는다 — 스키마에 참조가 늘어도 여기를 고치지 않는다.
    자식 행이 함께 지워지는 FK(`on delete cascade`)는 참조로 보지 않는다."""
    fks = conn.q(
        """select c.conrelid::regclass::text as ref_table, a.attname as ref_column
             from pg_constraint c
             join pg_attribute a on a.attrelid = c.conrelid and a.attnum = c.conkey[1]
             join pg_attribute pa on pa.attrelid = c.confrelid and pa.attnum = c.confkey[1]
            where c.contype = 'f' and c.confrelid = %s::regclass and c.confdeltype <> 'c'
              and array_length(c.conkey, 1) = 1 and pa.attname = %s
            order by 1, 2""", (table, pk))
    used: list[str] = []
    for fk in fks:
        hit = conn.q1(f'select 1 as hit from "{fk["ref_table"]}" where "{fk["ref_column"]}" = %s limit 1', (row_id,))
        if hit and fk["ref_table"] not in used:
            used.append(fk["ref_table"])
    return used


def assert_unused(table: str, pk: str, row_id: int) -> None:
    used = references_to(table, pk, row_id)
    if used:
        raise http.validation_error(IN_USE, fields=[{"name": TABLE_LABEL.get(t, t), "reason": "이 항목을 쓰고 있습니다"}
                                                    for t in used])


# ── 마스터 4기능 ────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Field:
    """코드·이름 밖의 입력 항목 하나 (= 컬럼 하나)."""
    name: str                                   # 컬럼명 = 폼 이름
    label: str
    kind: str = "text"                          # text | int | decimal | choice | ref
    required: bool = False
    choices: tuple[str, ...] = ()               # kind=choice — 허용 값
    ref: tuple[str, str, str, str] | None = None  # kind=ref — (테이블, pk, 코드 컬럼, 이름 컬럼)
    ref_where: str = ""                         # kind=ref — 선택 목록에 거는 조건 (예: item_type = '제품')
    positive: bool = False
    int_digits: int = 11                        # kind=decimal — 정수부 자릿수 상한
    scale: int = 3
    step: str = ""                              # 숫자 입력칸의 step

    def parse(self, form: FormData) -> Any:
        if self.kind == "int":
            return int_of(form, self.name, self.label, required=self.required, positive=self.positive)
        if self.kind == "decimal":
            return decimal_of(form, self.name, self.label, required=self.required, positive=self.positive,
                              int_digits=self.int_digits, scale=self.scale)
        if self.kind == "choice":
            value = text_of(form, self.name, self.label, required=self.required)
            if value is not None and value not in self.choices:
                raise bad("입력값을 확인해 주세요", self.label, f"{' · '.join(self.choices)} 중 하나여야 합니다: {value}")
            return value
        if self.kind == "ref":
            ref_id = int_of(form, self.name, self.label, required=self.required)
            if ref_id is not None:
                table, pk, _code, _name = self.ref
                if conn.q1(f"select 1 as hit from {table} where {pk} = %s", (ref_id,)) is None:
                    raise bad("입력값을 확인해 주세요", self.label, "없는 항목입니다")
            return ref_id
        return text_of(form, self.name, self.label, required=self.required)

    def options(self) -> list[tuple[Any, str]]:
        """선택칸의 목록. ref 는 사용 중(`use_yn='Y'`)인 행만 고르게 한다."""
        if self.kind == "choice":
            return [(c, c) for c in self.choices]
        if self.kind == "ref":
            table, pk, code, name = self.ref
            where = f"use_yn = 'Y'{' and ' + self.ref_where if self.ref_where else ''}"
            return [(r["id"], f'{r["code"]} · {r["name"]}') for r in conn.q(
                f"select {pk} as id, {code} as code, {name} as name from {table} where {where} order by {code}")]
        return []

    def options_with(self, current: Any) -> list[tuple[Any, str]]:
        """수정 폼의 선택 목록 — 지금 값이 `미사용` 이 된 항목이어도 목록에 남긴다(저장할 때 빠지지 않게)."""
        opts = self.options()
        if self.kind == "ref" and current is not None and all(v != current for v, _ in opts):
            table, pk, code, name = self.ref
            row = conn.q1(f"select {code} as code, {name} as name from {table} where {pk} = %s", (current,))
            if row:
                opts.append((current, f'{row["code"]} · {row["name"]} (미사용)'))
        return opts


@dataclass(frozen=True)
class Master:
    screen_id: str
    label: str                                  # 품목 · 고객 · …
    table: str
    pk: str
    code_col: str
    code_label: str
    name_col: str
    name_label: str
    fields: tuple[Field, ...]
    fn_create: str
    fn_update: str
    fn_delete: str
    fn_read: str
    list_sql: str                               # `{where}` 자리에 검색 조건. 반드시 id · code · name · use_yn 을 낸다
    columns: tuple[tuple[str, str], ...]        # 목록의 (머리글, 행의 키) — 코드·이름·사용 여부 사이에 들어간다
    template: str = "bas/master.html"
    notes: tuple[str, ...] = ()
    # 자식 행이 있는 마스터(잉크조성)용 갈고리
    parse_extra: Callable[[FormData], Any] | None = None      # 폼 → 자식 값. 검증 실패는 422. None 을 돌려주면 "건드리지 않는다"
    save_extra: Callable[[Any, int, Any], None] | None = None  # (cur, id, 자식 값)
    load_extra: Callable[[int], Any] | None = None             # 수정 폼에 실어 줄 자식 값

    @property
    def path(self) -> str:
        return nav.path_of(self.screen_id)

    def target(self, code: str) -> str:
        return f"{self.table}:{code}"


def _rows(m: Master, code: str, name: str, use_yn: str) -> list[dict]:
    where, params = ["true"], []
    if code.strip():
        where.append(contains(f"t.{m.code_col}"))
        params.append(code.strip())
    if name.strip():
        where.append(contains(f"t.{m.name_col}"))
        params.append(name.strip())
    if use_yn in ("Y", "N"):
        where.append("t.use_yn = %s")
        params.append(use_yn)
    return conn.q(m.list_sql.format(where=" and ".join(where)) + f" limit {LIST_LIMIT + 1}", params)


def _get(m: Master, row_id: int) -> dict:
    row = conn.q1(f"select * from {m.table} where {m.pk} = %s", (row_id,))
    if row is None:
        raise http.not_found()
    return row


def register(r: APIRouter, m: Master) -> None:
    """마스터 한 개의 4기능을 라우터에 건다. 경로는 `function-list.md` 의 API 열과 같다."""

    @r.get(m.path, response_class=HTMLResponse, name=f"{m.table}_list")
    def list_view(request: Request, code: str = "", name: str = "", use_yn: str = "", edit: str = "",
                  user: rbac.User = rbac.require_fn(m.fn_read)) -> HTMLResponse:
        rows = _rows(m, code, name, use_yn)
        capped = len(rows) > LIST_LIMIT
        editing, extra = None, None
        if edit:
            editing = _get(m, id_of_path(edit))
            extra = m.load_extra(editing[m.pk]) if m.load_extra else None
        return templating.render(request, m.template, {
            "m": m, "rows": rows[:LIST_LIMIT], "capped": capped, "limit": LIST_LIMIT,
            "f": {"code": code, "name": name, "use_yn": use_yn},
            "editing": editing, "extra": extra,
            "options": {fd.name: fd.options_with(editing[fd.name] if editing else None)
                        for fd in m.fields if fd.kind in ("choice", "ref")},
            "use_yn_options": USE_YN,
            "can": {"create": user.can(m.fn_create), "update": user.can(m.fn_update), "delete": user.can(m.fn_delete)},
        }, screen_id=m.screen_id)

    @r.post(m.path, name=f"{m.table}_create")
    def create(request: Request, user: rbac.User = rbac.require_fn(m.fn_create), form: FormData = Depends(form_data)):
        code = text_of(form, m.code_col, m.code_label, required=True, max_len=50)
        name = text_of(form, m.name_col, m.name_label, required=True, max_len=200)
        values = {fd.name: fd.parse(form) for fd in m.fields}
        extra = m.parse_extra(form) if m.parse_extra else None
        if conn.q1(f"select 1 as hit from {m.table} where {m.code_col} = %s", (code,)):
            raise bad(f"이미 있는 {m.code_label}입니다", m.code_label, code)
        cols = [m.code_col, m.name_col, *values, "created_by"]
        with conn.tx() as cur:
            cur.execute(f"insert into {m.table} ({', '.join(cols)}) values ({', '.join(['%s'] * len(cols))}) "
                        f"returning {m.pk} as id", [code, name, *values.values(), user.login_id])
            new_id = cur.fetchone()["id"]
            if m.save_extra and extra is not None:
                m.save_extra(cur, new_id, extra)
        audit.log_change(request, user, m.fn_create, m.target(code), f"{m.label} 등록")
        return http.saved(request, f"{m.label}을(를) 등록했습니다", back=m.path, data={"id": new_id, "code": code})

    @r.post(m.path + "/{id}", name=f"{m.table}_update")
    def update(request: Request, id: str, user: rbac.User = rbac.require_fn(m.fn_update),  # noqa: A002 — 계약의 경로 이름
               form: FormData = Depends(form_data)):
        row = _get(m, id_of_path(id))
        sent_code = text_of(form, m.code_col, m.code_label, max_len=50)
        if sent_code is not None and sent_code != row[m.code_col]:
            raise bad(f"{m.code_label}는 바꿀 수 없습니다", m.code_label, f"{row[m.code_col]} → {sent_code}")
        sets: dict[str, Any] = {}
        if m.name_col in form:
            sets[m.name_col] = text_of(form, m.name_col, m.name_label, required=True, max_len=200)
        for fd in m.fields:
            if fd.name in form:                       # 폼에 없는 항목은 그대로 둔다
                sets[fd.name] = fd.parse(form)
        if "use_yn" in form:
            use_yn = text_of(form, "use_yn", "사용 여부", required=True)
            if use_yn not in ("Y", "N"):
                raise bad("입력값을 확인해 주세요", "사용 여부", f"Y 또는 N 이어야 합니다: {use_yn}")
            sets["use_yn"] = use_yn
        extra = m.parse_extra(form) if m.parse_extra else None
        if not sets and extra is None:
            raise http.validation_error("바꿀 값이 없습니다")
        with conn.tx() as cur:
            assign = ", ".join(f"{c} = %s" for c in sets)
            cur.execute(f"update {m.table} set {assign + ', ' if assign else ''}updated_at = now(), updated_by = %s "
                        f"where {m.pk} = %s", [*sets.values(), user.login_id, row[m.pk]])
            if m.save_extra and extra is not None:
                m.save_extra(cur, row[m.pk], extra)
        audit.log_change(request, user, m.fn_update, m.target(row[m.code_col]), f"{m.label} 수정")
        return http.saved(request, f"{m.label}을(를) 수정했습니다", back=m.path,
                          data={"id": row[m.pk], "code": row[m.code_col]})

    @r.post(m.path + "/{id}/delete", name=f"{m.table}_delete")
    def delete(request: Request, id: str, user: rbac.User = rbac.require_fn(m.fn_delete)):  # noqa: A002
        row = _get(m, id_of_path(id))
        assert_unused(m.table, m.pk, row[m.pk])
        conn.x(f"delete from {m.table} where {m.pk} = %s", (row[m.pk],))
        audit.log_change(request, user, m.fn_delete, m.target(row[m.code_col]), f"{m.label} 삭제")
        return http.saved(request, f"{m.label}을(를) 삭제했습니다", back=m.path,
                          data={"id": row[m.pk], "code": row[m.code_col]})


# ── 기준정보 5종 ────────────────────────────────────────────────────────
ITEM = Master(
    screen_id="BAS-01", label="품목", table="item", pk="item_id",
    code_col="item_code", code_label="품목 코드", name_col="item_name", name_label="품목명",
    fields=(
        Field("item_type", "구분", kind="choice", required=True, choices=("제품", "원재료")),
        Field("spec", "규격"),
        Field("unit", "단위"),
    ),
    fn_create="F-BAS-01", fn_update="F-BAS-02", fn_delete="F-BAS-03", fn_read="F-BAS-04",
    list_sql="""select t.item_id as id, t.item_code as code, t.item_name as name, t.item_type, t.spec, t.unit, t.use_yn
                  from item t where {where} order by t.item_code""",
    columns=(("구분", "item_type"), ("규격", "spec"), ("단위", "unit")),
    notes=("규격은 받은 글자 그대로 적는다 — 값을 지어내지 않는다(D-18).",
           "작업지시·원재료 LOT·판사양이 쓰는 품목은 지울 수 없다. 그때는 수정에서 사용 여부를 `미사용` 으로 바꾼다(D-21)."),
)

CUSTOMER = Master(
    screen_id="BAS-02", label="고객", table="customer", pk="customer_id",
    code_col="customer_code", code_label="고객 코드", name_col="customer_name", name_label="고객명",
    fields=(Field("note", "비고"),),
    fn_create="F-BAS-05", fn_update="F-BAS-06", fn_delete="F-BAS-07", fn_read="F-BAS-08",
    list_sql="""select t.customer_id as id, t.customer_code as code, t.customer_name as name, t.note, t.use_yn
                  from customer t where {where} order by t.customer_code""",
    columns=(("비고", "note"),),
    notes=("작업지시·출하가 쓰는 고객은 지울 수 없다. 그때는 사용 여부를 `미사용` 으로 바꾼다(D-21).",),
)

PROCESS = Master(
    screen_id="BAS-03", label="공정", table="process", pk="process_id",
    code_col="process_code", code_label="공정 코드", name_col="process_name", name_label="공정명",
    fields=(
        Field("process_type", "공정 구분", kind="choice", required=True, choices=("인쇄", "후가공", "슬리팅", "기타")),
        Field("sort_no", "순서", kind="int"),
    ),
    fn_create="F-BAS-09", fn_update="F-BAS-10", fn_delete="F-BAS-11", fn_read="F-BAS-12",
    list_sql="""select t.process_id as id, t.process_code as code, t.process_name as name, t.process_type, t.sort_no, t.use_yn
                  from process t where {where} order by t.sort_no nulls last, t.process_code""",
    columns=(("공정 구분", "process_type"), ("순서", "sort_no")),
    notes=("설비·작업 실적이 쓰는 공정은 지울 수 없다(D-21).",),
)

EQUIPMENT = Master(
    screen_id="BAS-04", label="설비", table="equipment", pk="equipment_id",
    code_col="equipment_code", code_label="설비 코드", name_col="equipment_name", name_label="설비명",
    fields=(
        Field("process_id", "공정", kind="ref", ref=("process", "process_id", "process_code", "process_name")),
        Field("note", "비고"),
    ),
    fn_create="F-BAS-13", fn_update="F-BAS-14", fn_delete="F-BAS-15", fn_read="F-BAS-16",
    list_sql="""select t.equipment_id as id, t.equipment_code as code, t.equipment_name as name, t.note, t.use_yn,
                       p.process_code || ' · ' || p.process_name as process
                  from equipment t left join process p on p.process_id = t.process_id
                 where {where} order by t.equipment_code""",
    columns=(("공정", "process"), ("비고", "note")),
    notes=("설비는 기준정보까지다. 설비 상태·수집값은 받지 않는다(G-12).",
           "작업지시·작업 실적·롤이 쓰는 설비는 지울 수 없다(D-21)."),
)

DEFECT_CODE = Master(
    screen_id="BAS-05", label="불량코드", table="defect_code", pk="defect_code_id",
    code_col="defect_code", code_label="불량 코드", name_col="defect_name", name_label="불량명 (불량 유형)",
    fields=(Field("defect_group", "분류"),),
    fn_create="F-BAS-17", fn_update="F-BAS-18", fn_delete="F-BAS-19", fn_read="F-BAS-20",
    list_sql="""select t.defect_code_id as id, t.defect_code as code, t.defect_name as name, t.defect_group, t.use_yn
                  from defect_code t where {where} order by t.defect_code""",
    columns=(("분류", "defect_group"),),
    notes=("검사 불량·폐기 기록이 쓰는 불량코드는 지울 수 없다(D-21).",),
)

MASTERS: tuple[Master, ...] = (ITEM, CUSTOMER, PROCESS, EQUIPMENT, DEFECT_CODE)
for _m in MASTERS:
    register(router, _m)
