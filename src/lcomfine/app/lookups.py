"""기준정보·생산·재고의 공용 선택 목록과 존재·상태 검증.

라우터를 import하지 않는다. DB 변경·트랜잭션 시작·커밋은 하지 않는다.
exists_or_404는 호출자 커서의 SELECT FOR UPDATE를 그대로 유지한다.
item_choice는 호출자 커서, 나머지 목록 함수는 기존 conn.q/q1 조회를 사용한다.
조회 정책·오류 문구는 기존 BAS/INV 계약을 보존한다.
"""
from __future__ import annotations

from ..db import conn
from .util import http
from .util.forms import _bad, bad, id_in, pk, text_in


def exists_or_404(cur, table: str, id_: int, cols: str = "*") -> dict:
    cur.execute(f"select {cols} from {table} where id = %s for update", (id_,))   # table 은 이 파일들의 상수뿐
    row = cur.fetchone()
    if row is None:
        raise http.not_found()
    return row


def item_choice(cur, item_id: int | None, label: str = "제품", *, item_type: str | None = "제품",
                allow_inactive_id: int | None = None) -> dict | None:
    """폼에서 고른 품목 — 없으면 422 · 사용 중지 품목은 고를 수 없다(BAS-010). `allow_inactive_id` 는 원래 값 그대로 둘 때."""
    if item_id is None:
        return None
    cur.execute("select id, item_code, item_name, item_type, use_yn from item where id = %s", (item_id,))
    row = cur.fetchone()
    if row is None:
        raise bad(label, "없는 품목입니다")
    if item_type and row["item_type"] != item_type:
        raise bad(label, f"{item_type} 품목이 아닙니다 ({row['item_code']})")
    if row["use_yn"] != "Y" and row["id"] != allow_inactive_id:
        raise bad(label, f"사용 중지 품목은 고를 수 없습니다 ({row['item_code']})")
    return row


def items_for_select(item_type: str | None = "제품") -> list[dict]:
    """선택 목록 — 사용 중인 품목만(사용 중지 품목은 고를 수 없다)."""
    if item_type:
        return conn.q("select id, item_code, item_name from item where use_yn = 'Y' and item_type = %s "
                      "order by item_code", (item_type,))
    return conn.q("select id, item_code, item_name, item_type from item where use_yn = 'Y' order by item_code")


def edit_row(table: str, edit: str | None) -> dict | None:
    """목록 화면의 `?edit=<id>` — 고칠 행. 숫자가 아니거나 없으면 404."""
    if edit is None or edit == "":
        return None
    row = conn.q1(f"select * from {table} where id = %s", (pk(edit),))
    if row is None:
        raise http.not_found()
    return row


def locations() -> list[dict]:
    """사용 중인 위치 (선택 목록)."""
    return conn.q("""select l.id, l.location_code, l.location_name, w.warehouse_code, w.warehouse_name
                       from location l join warehouse w on w.id = l.warehouse_id
                      where l.use_yn = 'Y' and w.use_yn = 'Y'
                      order by w.warehouse_code, l.location_code""")


def location_in(value: str | None, name: str = "위치", *, required: bool = True) -> dict | None:
    lid = id_in(value, name, required=required)
    if lid is None:
        return None
    row = conn.q1("""select l.id, l.location_code, l.use_yn, w.use_yn as wh_use
                       from location l join warehouse w on w.id = l.warehouse_id where l.id = %s""", (lid,))
    if row is None:
        raise _bad(name, f"없는 위치입니다: {lid}")
    if row["use_yn"] != "Y" or row["wh_use"] != "Y":
        raise _bad(name, f"사용 중지된 위치입니다: {row['location_code']}")
    return row


def open_work_orders() -> list[dict]:
    """불출 · 제품 입고 · 일보에서 고르는 지시 (취소 · 완료 제외)."""
    return conn.q("""select w.id, w.work_order_no, w.qty, w.status, w.equipment_code, i.item_code, i.item_name,
                            r.request_no
                       from work_order w join item i on i.id = w.item_id
                       join production_request r on r.id = w.request_id
                      where w.status in ('발행', '진행')
                      order by w.work_order_no desc""")


def work_order_in(wo_id: str | None, wo_no: str | None = None, name: str = "작업지시") -> dict:
    """지시 — 목록에서 고른 id 또는 직접 입력한 번호. 없거나 취소 · 완료면 422."""
    wid = id_in(wo_id, name, required=False)
    no = text_in(wo_no, f"{name} 번호")
    if wid is None and no is None:
        raise _bad(name, "필수 선택입니다", "작업지시를 고르세요")
    if wid is not None:
        row = conn.q1("select id, work_order_no, item_id, qty, status from work_order where id = %s", (wid,))
    else:
        row = conn.q1("select id, work_order_no, item_id, qty, status from work_order where work_order_no = %s", (no,))
    if row is None:
        raise _bad(name, f"없는 작업지시입니다: {wid if wid is not None else no}")
    if row["status"] in ("취소", "완료"):
        raise _bad(name, f"{row['status']}된 지시입니다: {row['work_order_no']}")
    return row


def equipments() -> list[dict]:
    return conn.q("""select code, code_name from sys_common_code where group_code = '설비' and use_yn = 'Y'
                      order by sort_no, code""")


def lot_by_no(kind: str, lot_no: str | None, name: str = "LOT 번호") -> dict:
    """입력한 LOT 번호 — 없으면 422 (사용자 입력). kind = 원자재 | 제품."""
    no = text_in(lot_no, name, required=True)
    table = "material_lot" if kind == "원자재" else "product_lot"
    row = conn.q1(f"select * from {table} where lot_no = %s", (no,))
    if row is None:
        raise _bad(name, f"없는 {kind} LOT 번호입니다: {no}")
    if row.get("canceled_at"):
        raise _bad(name, f"취소된 LOT 입니다: {no}")
    return row
