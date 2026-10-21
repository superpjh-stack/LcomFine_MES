# tests/test_arch_notify.py — 알림 9종 (D-511 · D-522 · D-523) — 실제 DB `lcomfine_db` · 시드 뒤
# 트랜잭션 안의 검사는 끝에 예외로 롤백한다. `unread` 는 자체 연결로 읽으므로 커밋한 뒤 finally 에서 지운다.
import uuid
from dataclasses import replace

import pytest

from lcomfine.app import notify, rbac
from lcomfine.db import conn


class _Rollback(Exception):
    pass


def _key() -> str:
    return f"test:{uuid.uuid4().hex}"


def test_events_nine():
    assert notify.EVENTS == {
        "request_created": ("PR", "DS"), "order_issued": ("PR",), "material_received": ("PR",),
        "product_received": ("PR",), "judged": ("SH", "SL"), "shipment_ordered": ("SH",),
        "shipment_confirmed": ("SL", "AC"), "erp_upload_error": ("AC",), "due_d3_unshipped": ("SL", "PR"),
    }


def test_emit_fans_out_per_dept_and_dedupes():
    key = _key()
    with pytest.raises(_Rollback):
        with conn.tx() as cur:
            assert notify.emit(cur, "request_created", link="/wo/requests", dedupe_key=key, text="의뢰 등록 (예시)") == 2
            assert notify.emit(cur, "request_created", link="/wo/requests", dedupe_key=key, text="의뢰 등록 (예시)") == 0
            cur.execute("select to_role, event_key, message, handled_at from notification where dedupe_key = %s "
                        "order by to_role", (key,))
            rows = cur.fetchall()
            assert [r["to_role"] for r in rows] == ["DS", "PR"]
            assert all(r["event_key"] == "request_created" and r["handled_at"] is None for r in rows)
            raise _Rollback
    assert conn.q1("select count(*) as n from notification where dedupe_key = %s", (key,))["n"] == 0


def test_unknown_event_raises():
    with pytest.raises(_Rollback):
        with conn.tx() as cur:
            with pytest.raises(KeyError):
                notify.emit(cur, "report_draft", link="/", dedupe_key=_key(), text="x")
            raise _Rollback


@pytest.mark.fn("F-HOME-022")
def test_handle_marks_handled_for_whole_dept():
    key = _key()
    sl = rbac.load_user("sl")
    with pytest.raises(_Rollback):
        with conn.tx() as cur:
            notify.emit(cur, "judged", link="/qc/product", dedupe_key=key, text="판정 완료 (예시)")
            cur.execute("select id, to_role from notification where dedupe_key = %s", (key,))
            ids = {r["to_role"]: r["id"] for r in cur.fetchall()}
            with pytest.raises(LookupError):        # 다른 부서의 알림
                notify.handle(cur, ids["SH"], sl)
            with pytest.raises(LookupError):        # 없는 ID
                notify.handle(cur, -1, sl)
            notify.handle(cur, ids["SL"], sl)
            notify.handle(cur, ids["SL"], replace(sl, login_id="other"))   # 이미 처리 — 그대로
            cur.execute("select to_role, handled_by from notification where dedupe_key = %s order by to_role", (key,))
            assert [(r["to_role"], r["handled_by"]) for r in cur.fetchall()] == [("SH", None), ("SL", "sl")]
            raise _Rollback


def test_handle_by_link_closes_dept_rows():
    k1, k2 = _key(), _key()
    pr = rbac.load_user("pr")
    with pytest.raises(_Rollback):
        with conn.tx() as cur:
            notify.emit(cur, "order_issued", link="/mat/issues?wo=X", dedupe_key=k1, text="지시 발행 (예시)")
            notify.emit(cur, "material_received", link="/mat/issues?wo=X", dedupe_key=k2, text="입고 (예시)")
            notify.emit(cur, "request_created", link="/mat/issues?wo=X", dedupe_key=_key(), text="의뢰 (예시)")
            assert notify.handle_by_link(cur, "/mat/issues?wo=X", pr) == 3   # PR 행 3 — DS 행은 그대로
            cur.execute("select count(*) as n from notification where link = %s and handled_at is null", ("/mat/issues?wo=X",))
            assert cur.fetchone()["n"] == 1
            raise _Rollback


def test_unread_dept_and_setting():
    key = _key()
    ac = rbac.load_user("ac")
    try:
        with conn.tx() as cur:
            notify.emit(cur, "erp_upload_error", link="/col/uploads", dedupe_key=key, text="업로드 오류 (예시)")
        mine = [n for n in notify.unread(ac) if n["dedupe_key"] == key]
        assert len(mine) == 1 and mine[0]["link"] == "/col/uploads" and mine[0]["event_key"] == "erp_upload_error"
        assert not [n for n in notify.unread(rbac.load_user("sl")) if n["dedupe_key"] == key]
        conn.x("insert into notification_setting (user_id, event_key, enabled, created_by) values (%s, %s, false, 'test')",
               (ac.id, "erp_upload_error"))
        assert not [n for n in notify.unread(ac) if n["dedupe_key"] == key]
    finally:
        conn.x("delete from notification_setting where user_id = %s and created_by = 'test'", (ac.id,))
        conn.x("delete from notification where dedupe_key = %s", (key,))
