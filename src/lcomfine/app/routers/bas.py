"""BAS 기준정보 — 품목(BAS-010) · 거래처(BAS-020) · 창고·위치(BAS-030). 담당 개발1.

입력 검증은 `app.util.forms`에서 가져온다. 선택 목록·존재 확인은 `app.lookups`, DB 수정 헬퍼는 이 파일에 둔다.
입력 오류는 사람이 읽는 문장으로 422, 경로의 키가 없거나 숫자가 아니면 404 (api-contract.md §1).
「참조가 있으면 지우지 않고 사용 중지로 바꾼다」는 `remove_or_disable` 한 곳 — 그 테이블을 가리키는 FK 를 DB 카탈로그에서 읽어 확인한다.
"""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from ...db import conn
from .. import nav, rbac, templating
from ..util import audit, http
from ..lookups import (
    edit_row, exists_or_404, item_choice, items_for_select,
)
from ..util.forms import (
    BAS_QTY_MAX as QTY_MAX, BIGINT_MAX, NUL_REASON,
    bad, choice, day, integer, kv_lines, kv_text, like, need, pk, qty, ref_id, s, yn,
)

router = APIRouter()

# ── DB 조회·수정 헬퍼 ───────────────────────────────────────────────────


def referencing(cur, table: str, id_: int) -> list[str]:
    """그 행을 가리키는 FK(단일 열)가 있는 테이블 이름 목록 — DB 카탈로그에서 읽는다(목록을 코드에 적지 않는다)."""
    cur.execute(
        """select c.conrelid::regclass::text as tbl, a.attname as col
             from pg_constraint c
             join pg_attribute a on a.attrelid = c.conrelid and a.attnum = c.conkey[1]
            where c.contype = 'f' and c.confrelid = %s::regclass and array_length(c.conkey, 1) = 1
            order by 1, 2""", (table,))
    hits = []
    for fk in cur.fetchall():
        cur.execute(f'select 1 from {fk["tbl"]} where "{fk["col"]}" = %s limit 1', (id_,))
        if cur.fetchone():
            hits.append(fk["tbl"])
    return sorted(set(hits))


def remove_or_disable(cur, table: str, id_: int, user, *, extra_refs: list[str] | None = None) -> str:
    """참조가 있으면 `use_yn = 'N'`(사용 중지), 없으면 지운다. 반환 = 「사용 중지」 | 「삭제」."""
    refs = referencing(cur, table, id_) + list(extra_refs or [])
    if refs:
        cur.execute(f"update {table} set use_yn = 'N', updated_at = now(), updated_by = %s where id = %s",
                    (user.login_id, id_))
        return "사용 중지"
    cur.execute(f"delete from {table} where id = %s", (id_,))
    return "삭제"


# ── BAS-010 품목 관리 ───────────────────────────────────────────────────
ITEM_TYPES = ("제품", "원자재")


@router.get(nav.path_of("BAS-010"), response_class=HTMLResponse)
def items(request: Request, q: str | None = None, item_type: str | None = None, use: str | None = None,
          edit: str | None = None, user: rbac.User = rbac.require_screen("BAS-010")):
    """F-BAS-014 품목 조회 — 코드·이름·사용 여부로 검색."""
    rows = conn.q(
        """select id, item_code, item_name, item_type, spec, unit, note, use_yn, updated_at
             from item
            where (%(q)s::text is null or item_code ilike %(q)s or item_name ilike %(q)s)
              and (%(t)s::text is null or item_type = %(t)s)
              and (%(u)s::text is null or use_yn = %(u)s)
            order by item_code limit 1000""",
        {"q": like(q), "t": s(item_type, "구분"), "u": s(use, "사용 여부")})
    return templating.render(request, "bas/items.html",
                             {"rows": rows, "edit": edit_row("item", edit), "types": ITEM_TYPES,
                              "form": {"q": q or "", "item_type": item_type or "", "use": use or ""}},
                             screen_id="BAS-010")


@router.post("/bas/items")
def item_create(request: Request, item_code: str | None = Form(None), item_name: str | None = Form(None),
                item_type: str | None = Form(None), spec: str | None = Form(None), unit: str | None = Form(None),
                note: str | None = Form(None), user: rbac.User = rbac.require_fn("F-BAS-011")):
    code = need(item_code, "품목 코드")
    name = need(item_name, "품목명")
    typ = choice(item_type, "구분", ITEM_TYPES)
    with conn.tx() as cur:
        cur.execute("select 1 from item where item_code = %s", (code,))
        if cur.fetchone():
            raise bad("품목 코드", code, "이미 있는 품목 코드입니다")
        cur.execute("""insert into item (item_code, item_name, item_type, spec, unit, note, created_by)
                       values (%s, %s, %s, %s, %s, %s, %s) returning id""",
                    (code, name, typ, s(spec, "규격"), s(unit, "단위"), s(note, "비고"), user.login_id))
        new_id = cur.fetchone()["id"]
    resp = http.saved(request, "품목을 등록했습니다", back=nav.path_of("BAS-010"), data={"id": new_id})
    audit.log_change(request, user, "F-BAS-011", f"item:{code}", "품목 등록")
    return resp


@router.post("/bas/items/{id}")
def item_update(request: Request, id: str, item_code: str | None = Form(None), item_name: str | None = Form(None),
                item_type: str | None = Form(None), spec: str | None = Form(None), unit: str | None = Form(None),
                note: str | None = Form(None), use_yn: str | None = Form(None),
                user: rbac.User = rbac.require_fn("F-BAS-012")):
    iid = pk(id)
    name = need(item_name, "품목명")
    typ = choice(item_type, "구분", ITEM_TYPES)
    use = yn(use_yn)
    with conn.tx() as cur:
        row = exists_or_404(cur, "item", iid, "id, item_code")
        if s(item_code, "품목 코드") is not None and s(item_code, "품목 코드") != row["item_code"]:
            raise bad("품목 코드", "품목 코드는 바꾸지 않습니다", "품목 코드는 바꿀 수 없습니다")
        cur.execute("""update item set item_name = %s, item_type = %s, spec = %s, unit = %s, note = %s, use_yn = %s,
                              updated_at = now(), updated_by = %s where id = %s""",
                    (name, typ, s(spec, "규격"), s(unit, "단위"), s(note, "비고"), use, user.login_id, iid))
    resp = http.saved(request, "품목을 수정했습니다", back=nav.path_of("BAS-010"), data={"id": iid})
    audit.log_change(request, user, "F-BAS-012", f"item:{row['item_code']}", f"품목 수정 · 사용 {use}")
    return resp


@router.post("/bas/items/{id}/delete")
def item_delete(request: Request, id: str, user: rbac.User = rbac.require_fn("F-BAS-013")):
    iid = pk(id)
    with conn.tx() as cur:
        row = exists_or_404(cur, "item", iid, "id, item_code")
        done = remove_or_disable(cur, "item", iid, user)
    msg = "참조가 있어 지우지 않고 사용 중지로 바꿨습니다" if done == "사용 중지" else "품목을 삭제했습니다"
    resp = http.saved(request, msg, back=nav.path_of("BAS-010"), data={"id": iid, "result": done})
    audit.log_change(request, user, "F-BAS-013", f"item:{row['item_code']}", f"품목 {done}")
    return resp


# ── BAS-020 거래처 관리 ─────────────────────────────────────────────────
@router.get(nav.path_of("BAS-020"), response_class=HTMLResponse)
def customers(request: Request, q: str | None = None, use: str | None = None, edit: str | None = None,
              user: rbac.User = rbac.require_screen("BAS-020")):
    """F-BAS-024 거래처 조회."""
    rows = conn.q(
        """select id, customer_code, customer_name, contact_name, phone, address, note, use_yn
             from customer
            where (%(q)s::text is null or customer_code ilike %(q)s or customer_name ilike %(q)s)
              and (%(u)s::text is null or use_yn = %(u)s)
            order by customer_code limit 1000""", {"q": like(q), "u": s(use, "사용 여부")})
    return templating.render(request, "bas/customers.html",
                             {"rows": rows, "edit": edit_row("customer", edit),
                              "form": {"q": q or "", "use": use or ""}}, screen_id="BAS-020")


@router.post("/bas/customers")
def customer_create(request: Request, customer_code: str | None = Form(None), customer_name: str | None = Form(None),
                    contact_name: str | None = Form(None), phone: str | None = Form(None),
                    address: str | None = Form(None), note: str | None = Form(None),
                    user: rbac.User = rbac.require_fn("F-BAS-021")):
    code = need(customer_code, "거래처 코드")
    name = need(customer_name, "거래처명")
    with conn.tx() as cur:
        cur.execute("select 1 from customer where customer_code = %s", (code,))
        if cur.fetchone():
            raise bad("거래처 코드", code, "이미 있는 거래처 코드입니다")
        cur.execute("""insert into customer (customer_code, customer_name, contact_name, phone, address, note, created_by)
                       values (%s, %s, %s, %s, %s, %s, %s) returning id""",
                    (code, name, s(contact_name, "담당자"), s(phone, "연락처"), s(address, "주소"), s(note, "비고"), user.login_id))
        new_id = cur.fetchone()["id"]
    resp = http.saved(request, "거래처를 등록했습니다", back=nav.path_of("BAS-020"), data={"id": new_id})
    audit.log_change(request, user, "F-BAS-021", f"customer:{code}", "거래처 등록")
    return resp


@router.post("/bas/customers/{id}")
def customer_update(request: Request, id: str, customer_code: str | None = Form(None),
                    customer_name: str | None = Form(None), contact_name: str | None = Form(None),
                    phone: str | None = Form(None), address: str | None = Form(None), note: str | None = Form(None),
                    use_yn: str | None = Form(None), user: rbac.User = rbac.require_fn("F-BAS-022")):
    cid = pk(id)
    name = need(customer_name, "거래처명")
    use = yn(use_yn)
    with conn.tx() as cur:
        row = exists_or_404(cur, "customer", cid, "id, customer_code")
        if s(customer_code, "거래처 코드") is not None and s(customer_code, "거래처 코드") != row["customer_code"]:
            raise bad("거래처 코드", "거래처 코드는 바꾸지 않습니다", "거래처 코드는 바꿀 수 없습니다")
        cur.execute("""update customer set customer_name = %s, contact_name = %s, phone = %s, address = %s, note = %s,
                              use_yn = %s, updated_at = now(), updated_by = %s where id = %s""",
                    (name, s(contact_name, "담당자"), s(phone, "연락처"), s(address, "주소"), s(note, "비고"), use, user.login_id, cid))
    resp = http.saved(request, "거래처를 수정했습니다", back=nav.path_of("BAS-020"), data={"id": cid})
    audit.log_change(request, user, "F-BAS-022", f"customer:{row['customer_code']}", f"거래처 수정 · 사용 {use}")
    return resp


@router.post("/bas/customers/{id}/delete")
def customer_delete(request: Request, id: str, user: rbac.User = rbac.require_fn("F-BAS-023")):
    cid = pk(id)
    with conn.tx() as cur:
        row = exists_or_404(cur, "customer", cid, "id, customer_code")
        done = remove_or_disable(cur, "customer", cid, user)
    msg = "참조가 있어 지우지 않고 사용 중지로 바꿨습니다" if done == "사용 중지" else "거래처를 삭제했습니다"
    resp = http.saved(request, msg, back=nav.path_of("BAS-020"), data={"id": cid, "result": done})
    audit.log_change(request, user, "F-BAS-023", f"customer:{row['customer_code']}", f"거래처 {done}")
    return resp


# ── BAS-030 창고·위치 관리 ──────────────────────────────────────────────
#  한 화면 · 한 API 로 창고와 그 아래 위치를 같이 다룬다 — 폼의 `target` = warehouse(기본) | location.
TARGETS = ("warehouse", "location")


@router.get(nav.path_of("BAS-030"), response_class=HTMLResponse)
def warehouses(request: Request, edit: str | None = None, edit_location: str | None = None,
               user: rbac.User = rbac.require_screen("BAS-030")):
    """F-BAS-034 창고·위치 조회 — 창고 목록 · 위치(랙·구역) · 위치별 현재고."""
    whs = conn.q("""select w.id, w.warehouse_code, w.warehouse_name, w.note, w.use_yn,
                           (select count(*) from location l where l.warehouse_id = w.id) as location_count
                      from warehouse w order by w.warehouse_code""")
    locs = conn.q("""select l.id, l.warehouse_id, w.warehouse_code, l.location_code, l.location_name, l.use_yn,
                            coalesce((select sum(qty) from lot_stock s where s.location_id = l.id), 0) as stock_qty
                       from location l join warehouse w on w.id = l.warehouse_id
                      order by w.warehouse_code, l.location_code""")
    return templating.render(request, "bas/warehouses.html",
                             {"warehouses": whs, "locations": locs, "edit": edit_row("warehouse", edit),
                              "edit_location": edit_row("location", edit_location)}, screen_id="BAS-030")


@router.post("/bas/warehouses")
def warehouse_create(request: Request, target: str | None = Form(None), warehouse_code: str | None = Form(None),
                     warehouse_name: str | None = Form(None), note: str | None = Form(None),
                     warehouse_id: str | None = Form(None), location_code: str | None = Form(None),
                     location_name: str | None = Form(None), user: rbac.User = rbac.require_fn("F-BAS-031")):
    tgt = choice(target or "warehouse", "대상", TARGETS)
    with conn.tx() as cur:
        if tgt == "warehouse":
            code = need(warehouse_code, "창고 코드")
            name = need(warehouse_name, "창고명")
            cur.execute("select 1 from warehouse where warehouse_code = %s", (code,))
            if cur.fetchone():
                raise bad("창고 코드", code, "이미 있는 창고 코드입니다")
            cur.execute("insert into warehouse (warehouse_code, warehouse_name, note, created_by) "
                        "values (%s, %s, %s, %s) returning id", (code, name, s(note, "비고"), user.login_id))
            target_txt, msg = f"warehouse:{code}", "창고를 등록했습니다"
        else:
            wid = ref_id(warehouse_id, "창고")
            code = need(location_code, "위치 코드")
            name = need(location_name, "위치명")
            cur.execute("select warehouse_code, use_yn from warehouse where id = %s", (wid,))
            wh = cur.fetchone()
            if wh is None:
                raise bad("창고", "없는 창고입니다")
            if wh["use_yn"] != "Y":
                raise bad("창고", f"사용 중지 창고에는 위치를 둘 수 없습니다 ({wh['warehouse_code']})")
            cur.execute("select 1 from location where warehouse_id = %s and location_code = %s", (wid, code))
            if cur.fetchone():
                raise bad("위치 코드", code, "그 창고에 이미 있는 위치 코드입니다")
            cur.execute("insert into location (warehouse_id, location_code, location_name, created_by) "
                        "values (%s, %s, %s, %s) returning id", (wid, code, name, user.login_id))
            target_txt, msg = f"location:{wh['warehouse_code']}/{code}", "위치를 등록했습니다"
        new_id = cur.fetchone()["id"]
    resp = http.saved(request, msg, back=nav.path_of("BAS-030"), data={"id": new_id, "target": tgt})
    audit.log_change(request, user, "F-BAS-031", target_txt, msg)
    return resp


@router.post("/bas/warehouses/{id}")
def warehouse_update(request: Request, id: str, target: str | None = Form(None),
                     warehouse_code: str | None = Form(None), warehouse_name: str | None = Form(None),
                     note: str | None = Form(None), location_code: str | None = Form(None),
                     location_name: str | None = Form(None), use_yn: str | None = Form(None),
                     user: rbac.User = rbac.require_fn("F-BAS-032")):
    rid = pk(id)
    tgt = choice(target or "warehouse", "대상", TARGETS)
    use = yn(use_yn)
    with conn.tx() as cur:
        if tgt == "warehouse":
            row = exists_or_404(cur, "warehouse", rid, "id, warehouse_code")
            name = need(warehouse_name, "창고명")
            if s(warehouse_code, "창고 코드") is not None and s(warehouse_code, "창고 코드") != row["warehouse_code"]:
                raise bad("창고 코드", "코드는 바꾸지 않습니다", "창고 코드는 바꿀 수 없습니다")
            cur.execute("update warehouse set warehouse_name = %s, note = %s, use_yn = %s, updated_at = now(), "
                        "updated_by = %s where id = %s", (name, s(note, "비고"), use, user.login_id, rid))
            target_txt, msg = f"warehouse:{row['warehouse_code']}", "창고를 수정했습니다"
        else:
            row = exists_or_404(cur, "location", rid, "id, location_code")
            name = need(location_name, "위치명")
            if s(location_code, "위치 코드") is not None and s(location_code, "위치 코드") != row["location_code"]:
                raise bad("위치 코드", "코드는 바꾸지 않습니다", "위치 코드는 바꿀 수 없습니다")
            cur.execute("update location set location_name = %s, use_yn = %s, updated_at = now(), updated_by = %s "
                        "where id = %s", (name, use, user.login_id, rid))
            target_txt, msg = f"location:{row['location_code']}", "위치를 수정했습니다"
    resp = http.saved(request, msg, back=nav.path_of("BAS-030"), data={"id": rid, "target": tgt})
    audit.log_change(request, user, "F-BAS-032", target_txt, f"{msg} · 사용 {use}")
    return resp


def _stock_left(cur, location_ids: list[int]) -> bool:
    cur.execute("select 1 from lot_stock where location_id = any(%s) and qty > 0 limit 1", (location_ids,))
    return cur.fetchone() is not None


@router.post("/bas/warehouses/{id}/delete")
def warehouse_delete(request: Request, id: str, target: str | None = Form(None),
                     user: rbac.User = rbac.require_fn("F-BAS-033")):
    rid = pk(id)
    tgt = choice(target or "warehouse", "대상", TARGETS)
    with conn.tx() as cur:
        if tgt == "warehouse":
            row = exists_or_404(cur, "warehouse", rid, "id, warehouse_code")
            cur.execute("select id from location where warehouse_id = %s", (rid,))
            loc_ids = [r["id"] for r in cur.fetchall()]
            if loc_ids and _stock_left(cur, loc_ids):
                raise bad("창고", row["warehouse_code"], "재고가 남은 위치가 있는 창고는 삭제할 수 없습니다")
            done = remove_or_disable(cur, "warehouse", rid, user)
            if done == "사용 중지":
                cur.execute("update location set use_yn = 'N', updated_at = now(), updated_by = %s "
                            "where warehouse_id = %s", (user.login_id, rid))
            target_txt, what = f"warehouse:{row['warehouse_code']}", "창고"
        else:
            row = exists_or_404(cur, "location", rid, "id, location_code")
            if _stock_left(cur, [rid]):
                raise bad("위치", row["location_code"], "재고가 남은 위치는 삭제할 수 없습니다")
            done = remove_or_disable(cur, "location", rid, user)
            target_txt, what = f"location:{row['location_code']}", "위치"
    msg = "참조가 있어 지우지 않고 사용 중지로 바꿨습니다" if done == "사용 중지" else f"{what}를 삭제했습니다"
    resp = http.saved(request, msg, back=nav.path_of("BAS-030"), data={"id": rid, "target": tgt, "result": done})
    audit.log_change(request, user, "F-BAS-033", target_txt, f"{what} {done}")
    return resp
