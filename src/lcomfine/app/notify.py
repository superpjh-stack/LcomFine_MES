"""알림 — `notification` 에 쓰는 **한 곳** (D-511 · D-522 · D-523).

알림은 부서 단위로 간다. 이벤트 하나가 수신 부서마다 1행이 되고, `(dedupe_key, to_role)` 쌍으로 유일하다 —
같은 키로 두 번 emit 해도 부서마다 1행만 남는다. 한 사람이 처리하면 같은 부서의 다른 사람에게는 「처리됨」이다.

    emit(cur, event, *, link, dedupe_key, text) -> int   쓰기 트랜잭션의 커서 안에서 부른다 — 새로 넣은 행 수
    unread(user) -> list[dict]                           그 사람 부서의 미처리 알림(개인 설정으로 끈 이벤트는 숨김)
    handle(cur, notification_id, user) -> None           알림함에서 처리 (F-HOME-022). 다른 부서 · 없는 ID → LookupError
    handle_by_link(cur, link, user) -> int               알림을 눌러 연 화면에서 처리하면 닫힌다 — 처리한 행 수

「사용자 부서」 = `user.role_code`. 개인 설정(`notification_setting.enabled = false`)은 보이는 것만 숨긴다 — 발생은 한다.
"""

from __future__ import annotations

from ..db import conn

#: 이벤트 키 → 수신 부서 코드 (D-511 표 · 구성은 D-523). 이 표가 원본이다.
EVENTS: dict[str, tuple[str, ...]] = {
    "request_created": ("PR", "DS"),      # 의뢰 등록 → 생산부·디자인실
    "order_issued": ("PR",),              # 지시 발행 → 생산부(불출 준비)
    "material_received": ("PR",),         # 원자재 입고 → 생산부(입고검사)
    "product_received": ("PR",),          # 제품 입고 → 생산부(제품검사)
    "judged": ("SH", "SL"),               # 판정 완료 → 출하실·영업부
    "shipment_ordered": ("SH",),          # 출하 지시 → 출하실 (정본 영업부 흐름 문장 · D-523)
    "shipment_confirmed": ("SL", "AC"),   # 출하 확정 → 영업부·회계부
    "erp_upload_error": ("AC",),          # ERP 업로드 오류·미매핑 → 회계부
    "due_d3_unshipped": ("SL", "PR"),     # 납기 D-3 미출하 → 영업부·생산부
}


def recipients(event: str) -> tuple[str, ...]:
    """그 이벤트의 수신 부서. 모르는 이벤트는 KeyError — 조용히 무시하지 않는다."""
    if event not in EVENTS:
        raise KeyError(f"notify.EVENTS 에 없는 이벤트: {event!r} — {', '.join(EVENTS)} 중 하나 (D-511)")
    return EVENTS[event]


def emit(cur, event: str, *, link: str, dedupe_key: str, text: str) -> int:
    """수신 부서마다 `notification` 1행. 같은 (dedupe_key, 부서)는 무시한다(D-522). 반환 = 새로 넣은 행 수.
    자체 연결을 열지 않는다 — 업무 행과 함께 커밋 · 롤백된다."""
    n = 0
    for role_code in recipients(event):
        cur.execute(
            """insert into notification (event_key, to_role, link, dedupe_key, message)
               values (%s, %s, %s, %s, %s)
               on conflict (dedupe_key, to_role) do nothing""",
            (event, role_code, link, dedupe_key, text))
        n += cur.rowcount
    return n


def unread(user) -> list[dict]:
    """그 사람 부서의 미처리 알림 — 최신순. 개인 설정으로 끈 이벤트는 뺀다(행이 없으면 켜진 것)."""
    return conn.q(
        """select n.id, n.event_key, n.link, n.message, n.dedupe_key, n.created_at
             from notification n
            where n.to_role = %s and n.handled_at is null
              and not exists (select 1 from notification_setting s
                               where s.user_id = %s and s.event_key = n.event_key and not s.enabled)
            order by n.created_at desc, n.id desc""",
        (user.role_code, user.id))


def handle(cur, notification_id: int, user) -> None:
    """그 알림 1행을 처리한다. 사용자 부서의 행이 아니거나 없으면 LookupError(라우터가 404). 이미 처리된 행은 그대로 둔다."""
    cur.execute("select id, to_role, handled_at from notification where id = %s for update", (notification_id,))
    row = cur.fetchone()
    if row is None or row["to_role"] != user.role_code:
        raise LookupError(f"이 부서의 알림이 아닙니다: {notification_id}")
    if row["handled_at"] is not None:
        return
    cur.execute("update notification set handled_at = now(), handled_by = %s where id = %s",
                (user.login_id, notification_id))


def handle_by_link(cur, link: str, user) -> int:
    """같은 부서의 미처리 알림 중 `link` 가 같은 것을 전부 처리한다. 반환 = 처리한 행 수."""
    cur.execute(
        """update notification set handled_at = now(), handled_by = %s
            where to_role = %s and link = %s and handled_at is null""",
        (user.login_id, user.role_code, link))
    return cur.rowcount


def resolve_by_link(cur, link: str, user) -> int:
    """알림이 가리키던 **사실이 사라졌을 때**(ERP 회차가 교체됨 · 재해석으로 오류 0) `link` 가 같은 미처리 알림을 **수신 부서와 무관하게** 전부 닫는다.
    `handle_by_link` 는 「그 부서 사람이 처리 화면에서 처리했다」 — 이것은 「처리할 것이 없어졌다」 다(DEF-QA1-006 · D-802).
    닫은 사람(handled_by)은 사실을 바꾼 사용자. 반환 = 닫은 행 수."""
    cur.execute(
        """update notification set handled_at = now(), handled_by = %s
            where link = %s and handled_at is null""",
        (user.login_id, link))
    return cur.rowcount
