"""HOME 내 업무 — 내 할 일(HOME-010 · 메인 `/`) · 알림함(HOME-020) · 알림 설정(HOME-030). 담당 개발1.

내 할 일의 카드는 **저장하지 않고 질의로 센다**(스펙 §4.1). 카드 조건은 progress-dev1 §1.2 에 공표했다.
부서 = `user.role_code`. 카드 목록은 정본 HOME-010 logic 의 부서별 문장 그대로이고, 전산 관리자는 전 부서 카드를 본다(D-601).
카드의 링크는 그 화면을 볼 수 있는 사람에게만 걸린다(rbac.can) — 칸 없는 화면으로 보내지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from ...db import conn
from .. import nav, notify, rbac, templating
from ..util import audit, http, screen
from .bas import bad, pk

router = APIRouter()


@dataclass(frozen=True)
class Card:
    key: str
    title: str
    screen_id: str           # 누르면 여는 처리 화면
    query: str = ""          # 조건 (그 화면의 조회 인자)
    sql: str | None = None   # count 한 칸을 내는 SELECT. None = 아직 셀 수 없음(note 로 이유)
    note: str = ""


# 출하 수량 = v_work_order_status.shipped_qty 를 의뢰로 합한 값 (확정 출하만 — 뷰 정의)
_SHIPPED = "coalesce((select sum(v.shipped_qty) from v_work_order_status v where v.request_id = r.id), 0)"
_DUE_D3 = f"""select count(*) as n from production_request r
               where r.status <> '취소' and r.due_date <= current_date + 3 and {_SHIPPED} < r.qty"""
_ACTIVE_NO_ISSUE = """select count(*) as n from work_order w where w.status in ('발행', '진행')
                       and not exists (select 1 from material_issue_line l join material_issue i on i.id = l.issue_id
                                        and i.canceled_at is null where l.work_order_id = w.id)"""
_AVAILABLE_PRODUCT = """select count(distinct lot_id) as n from lot_stock
                         where lot_kind = '제품' and status = '가용' and qty - allocated_qty > 0"""

#: 부서 코드 → 카드 (정본 HOME-010 logic 의 부서별 대기 건)
CARDS: dict[str, tuple[Card, ...]] = {
    "SL": (
        Card("sl_confirm", "단가·납기 확인이 필요한 의뢰", "WO-010", "status=확인대기",
             "select count(*) as n from production_request where status = '확인대기'"),
        Card("sl_due_d3", "납기 D-3 미출하", "TRK-020", "bucket=D-3", _DUE_D3),
        Card("sl_ship_ready", "판정 끝난 출하 대기", "SHP-010", "", _AVAILABLE_PRODUCT, "가용 제품 LOT"),
    ),
    "PR": (
        Card("pr_wait_order", "지시 대기 의뢰", "WO-020", "",
             "select count(*) as n from production_request where status = '확정'"),
        Card("pr_wait_issue", "불출 대기 지시", "MAT-020", "", _ACTIVE_NO_ISSUE),
        Card("pr_incoming", "입고검사 대기 LOT", "QC-010", "status=검사대기",
             "select count(distinct lot_id) as n from lot_stock where lot_kind = '원자재' and status = '검사대기' and qty > 0"),
        Card("pr_product", "제품검사 대기 LOT", "QC-020", "status=검사대기",
             "select count(distinct lot_id) as n from lot_stock where lot_kind = '제품' and status = '검사대기' and qty > 0"),
        Card("pr_no_daily", "일보 미입력 지시", "PRD-010", "",
             """select count(*) as n from work_order w where w.status in ('발행', '진행')
                 and not exists (select 1 from production_daily d where d.work_order_id = w.id)"""),
    ),
    "SH": (
        Card("sh_wait_confirm", "출하 지시 대기", "SHP-020", "",
             "select count(*) as n from shipment_order where status = '지시'"),
        Card("sh_judged", "판정 완료 LOT", "SHP-010", "", _AVAILABLE_PRODUCT, "가용 제품 LOT"),
    ),
    "DS": (
        Card("ds_no_artwork", "시안 미등록 의뢰", "STD-040", "",
             """select count(*) as n from production_request r where r.status <> '취소'
                 and not exists (select 1 from artwork a where a.item_id = r.item_id and a.use_yn = 'Y')"""),
        Card("ds_plate", "판 준비 필요 지시", "STD-030", "",
             """select count(*) as n from work_order w where w.status in ('발행', '진행')
                 and not exists (select 1 from plate p where p.item_id = w.item_id and p.use_yn = 'Y')"""),
    ),
    "AC": (
        Card("ac_unmapped", "미매핑 ERP 거래처", "COL-030", "",
             """select count(distinct r.parsed->>'customer_code') as n
                  from erp_upload_row r join erp_upload_batch b on b.id = r.batch_id and b.status = '반영'
                 where r.parsed->>'customer_code' is not null
                   and not exists (select 1 from erp_customer_map m
                                    where m.erp_code = r.parsed->>'customer_code' and m.use_yn = 'Y')"""),
        Card("ac_errors", "업로드 오류 행", "COL-020", "",
             """select count(*) as n from erp_upload_row r join erp_upload_batch b on b.id = r.batch_id
                 where b.status = '반영' and r.error is not null"""),
        Card("ac_over90", "90일 초과 미수", "COL-060", "", None, "수금 집계(stats)는 W2 — 미수집"),
    ),
    "ST": (
        Card("st_report", "확정 대기 리포트", "RPT-080", "", None, "리포트 초안·검토 화면 없음 (D-505)"),
        Card("st_anomaly", "이상 요약", "RPT-080", "", None, "대시보드(W3)에서 본다 — 미수집"),
    ),
}
CARDS["EX"] = CARDS["ST"]   # 정본 「전략부·경영진」 한 줄


def cards_for(user: rbac.User) -> list[dict]:
    """그 사람 부서의 카드 — 전산 관리자는 전 부서(D-601). 건수는 지금 질의로 센다."""
    if user.role_code in CARDS:
        groups = [(user.role_name, CARDS[user.role_code])]
    else:
        seen, groups = set(), []
        for r in rbac.roles():
            cards = CARDS.get(r.code)
            if cards and id(cards) not in seen:
                seen.add(id(cards))
                name = "전략부·경영진" if r.code in ("ST", "EX") else r.name
                groups.append((name, cards))
    out = []
    for name, cards in groups:
        items = []
        for cd in cards:
            n = conn.q1(cd.sql)["n"] if cd.sql else None
            allowed = rbac.can(user, cd.screen_id)
            sc = nav.by_id(cd.screen_id)
            items.append({"title": cd.title, "count": n, "note": cd.note, "screen": sc,
                          "href": (sc.path + (f"?{cd.query}" if cd.query else "")) if allowed else None})
        out.append({"dept": name, "cards": items})
    return out


def due_soon() -> list[dict]:
    """납기 임박(D-7 이내)·지연 — 취소 아닌 의뢰 중 출하 수량이 의뢰 수량에 못 미친 것."""
    return conn.q(f"""select r.request_no, c.customer_name, i.item_code, i.item_name, r.qty, r.due_date, r.status,
                             (r.due_date - current_date) as d_day, {_SHIPPED} as shipped_qty
                        from production_request r join customer c on c.id = r.customer_id join item i on i.id = r.item_id
                       where r.status <> '취소' and r.due_date <= current_date + 7 and {_SHIPPED} < r.qty
                       order by r.due_date, r.id limit 50""")


@router.get(nav.path_of("HOME-010"), response_class=HTMLResponse)
def my_work(request: Request, user: rbac.User = rbac.require_screen("HOME-010")):
    """F-HOME-011 내 할 일 — 부서별 대기 카드 · 납기 임박·지연 · 오늘 처리한 건(자기 로그인의 변경 로그)."""
    today = conn.q("""select changed_at, function_id, screen_id, target, detail from sys_change_log
                       where login_id = %s and changed_at >= current_date order by id desc limit 100""",
                   (user.login_id,))
    for t in today:
        t["screen_name"] = nav.by_id(t["screen_id"]).name if t["screen_id"] else "-"
    return templating.render(request, "home/index.html",
                             {"groups": cards_for(user), "due": due_soon(), "today": today,
                              "can_due": rbac.can(user, "TRK-020"), "can_trk": rbac.can(user, "TRK-010")},
                             screen_id="HOME-010")


# ── HOME-020 알림함 ─────────────────────────────────────────────────────
@router.get(nav.path_of("HOME-020"), response_class=HTMLResponse)
def notifications(request: Request, user: rbac.User = rbac.require_screen("HOME-020")):
    """F-HOME-021 — 내 부서의 알림(안 읽음 = notify.unread · 처리됨 = 최근 50)."""
    unread = notify.unread(user)
    done = conn.q("""select id, event_key, link, message, created_at, handled_at, handled_by from notification
                      where to_role = %s and handled_at is not null order by handled_at desc, id desc limit 50""",
                  (user.role_code,))
    return templating.render(request, "home/notifications.html", {"unread_rows": unread, "done": done},
                             screen_id="HOME-020")


@router.post("/home/notifications/{id}/handle")
def notification_handle(request: Request, id: str, user: rbac.User = rbac.require_fn("F-HOME-022")):
    """F-HOME-022 — 자기 부서 알림 1행을 처리한다(notify.handle). 다른 부서 · 없는 ID 404 · 이미 처리 200."""
    nid = pk(id)
    with conn.tx() as cur:
        try:
            notify.handle(cur, nid, user)
        except LookupError:
            raise http.not_found("이 부서의 알림이 아닙니다") from None
    resp = http.saved(request, "알림을 처리했습니다", back=nav.path_of("HOME-020"), data={"id": nid})
    audit.log_change(request, user, "F-HOME-022", f"notification:{nid}", "알림 처리")
    return resp


# ── HOME-030 알림 설정 ──────────────────────────────────────────────────
#: 이벤트 키 → 화면에 보일 이름 (D-511 표의 정본 문장)
EVENT_NAMES: dict[str, str] = {
    "request_created": "의뢰 등록 → 생산부·디자인실",
    "order_issued": "지시 발행 → 생산부(불출 준비)",
    "material_received": "원자재 입고 → 생산부(입고검사)",
    "product_received": "제품 입고 → 생산부(제품검사)",
    "judged": "판정 완료 → 출하실·영업부",
    "shipment_ordered": "출하 지시 → 출하실",
    "shipment_confirmed": "출하 확정 → 영업부·회계부",
    "erp_upload_error": "ERP 업로드 오류·미매핑 → 회계부",
    "due_d3_unshipped": "납기 D-3 미출하 → 영업부·생산부",
}


def _settings(user: rbac.User) -> list[dict]:
    """자기 부서가 수신하는 이벤트만 — 다른 부서 이벤트 구독은 범위 밖(D-511 · Ruling 24). 부서 기본 알림은 끌 수 없다."""
    return [{"key": key, "name": EVENT_NAMES.get(key, key)} for key, roles in notify.EVENTS.items()
            if user.role_code in roles]


def _mine(user: rbac.User) -> set[str]:
    return {key for key, roles in notify.EVENTS.items() if user.role_code in roles}


@router.get(nav.path_of("HOME-030"), response_class=HTMLResponse)
def notification_settings(request: Request, user: rbac.User = rbac.require_screen("HOME-030")):
    """F-HOME-032 — 부서 기본 알림과 개인 추가 알림을 나눠 보인다 · 메일·메신저 칸은 미확정 (D-518)."""
    return templating.render(request, "home/notification_settings.html",
                             {"events": _settings(user), "mail_undecided": screen.undecided("D-518")},
                             screen_id="HOME-030")


@router.post("/home/notification-settings")
def notification_settings_save(request: Request, events: list[str] = Form([]), enabled: list[str] = Form([]),
                               mail: str | None = Form(None), messenger: str | None = Form(None),
                               user: rbac.User = rbac.require_fn("F-HOME-031")):
    """F-HOME-031 — 자기 부서가 수신하는 이벤트만 다룬다(Ruling 24 · D-511). 부서 기본 알림을 끄려 하면 422 ·
    다른 부서 이벤트는 저장하지 않고 422 · 메일·메신저는 저장하지 않는다(501 D-518).

    폼: `events` = 화면에 보인 이벤트 키 전부(hidden) · `enabled` = 켜진 이벤트 키."""
    if mail or messenger:
        raise http.undecided("D-518", "알림 메일·메신저 연동")
    if not events:
        raise bad("받을 알림 종류", "필수 항목입니다", "필수 항목을 입력해 주세요 — 받을 알림 종류")
    keys = set(events) | set(enabled)
    unknown = sorted(keys - set(notify.EVENTS))
    if unknown:
        raise bad("받을 알림 종류", f"없는 알림 종류입니다: {', '.join(unknown)}")
    mine = _mine(user)
    foreign = sorted(keys - mine)
    if foreign:
        raise bad("받을 알림 종류",
                  f"다른 부서로 가는 알림은 구독할 수 없습니다 — 범위 밖 (D-511): {', '.join(EVENT_NAMES[k] for k in foreign)}",
                  "다른 부서로 가는 알림은 구독할 수 없습니다 — 범위 밖 (D-511)")
    on = set(enabled)
    defaults_off = [k for k in dict.fromkeys(events) if k not in on]
    if defaults_off:
        raise bad("받을 알림 종류", f"부서 기본 알림은 끌 수 없습니다: {', '.join(EVENT_NAMES[k] for k in defaults_off)}",
                  "부서 기본 알림은 끌 수 없습니다")
    with conn.tx() as cur:
        # 범위 밖이 된 행(다른 부서 이벤트 구독)이 남아 있으면 지운다 — 이 화면이 보이는 것만 저장 상태로 둔다
        cur.execute("delete from notification_setting where user_id = %s and not (event_key = any(%s))",
                    (user.id, sorted(mine)))
        removed = cur.rowcount
    resp = http.saved(request, "알림 설정을 저장했습니다 — 부서 기본 알림은 전부 켜져 있습니다", back=nav.path_of("HOME-030"),
                      data={"department_on": sorted(k for k in events if k in mine), "removed_out_of_scope": removed})
    audit.log_change(request, user, "F-HOME-031", f"notification_setting:{user.login_id}",
                     f"부서 기본 알림 {len(set(events))}종 확인 · 범위 밖 행 {removed} 삭제")
    return resp
