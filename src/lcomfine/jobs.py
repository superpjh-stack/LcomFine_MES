"""배치 — `uv run python -m lcomfine.jobs due-check` (Makefile `jobs-due-check`). 담당 개발1.

due-check  납기 D-3 이내(지난 납기 포함) 미출하 의뢰마다 `notify.emit("due_d3_unshipped")` → 영업부 · 생산부 (D-511).
           미출하 = 취소 아닌 의뢰의 확정 출하 수량(v_work_order_status.shipped_qty 합) < 의뢰 수량 — HOME-010 카드와 같은 조건.
           중복 방지 키 `due:<의뢰번호>:<YYYY-MM-DD>` — 같은 날 두 번 돌려도 부서마다 1행(D-522), 다음 날 다시 알린다.
           실행 시각은 미확정 (D-520) — 스케줄을 걸지 않고 수동으로 돌린다.
"""

from __future__ import annotations

import sys
from datetime import date

from .app import nav, notify
from .db import conn

DUE_DAYS = 3

_DUE_SQL = """
select r.request_no, r.due_date, r.qty, c.customer_code, i.item_code,
       coalesce((select sum(v.shipped_qty) from v_work_order_status v where v.request_id = r.id), 0) as shipped_qty
  from production_request r
  join customer c on c.id = r.customer_id
  join item i on i.id = r.item_id
 where r.status <> '취소' and r.due_date <= %s::date + %s
   and (%s::text[] is null or r.request_no = any(%s::text[]))
   and coalesce((select sum(v.shipped_qty) from v_work_order_status v where v.request_id = r.id), 0) < r.qty
 order by r.due_date, r.id
"""


def due_link(request_no: str) -> str:
    return f"{nav.path_of('TRK-020')}?request={request_no}"


def due_check(today: date | None = None, *, request_nos: list[str] | None = None) -> dict:
    """`request_nos` 를 주면 그 의뢰만 본다(테스트 · 수동 재발송). 반환 {"requests": 대상 의뢰 수, "created": 새 알림 행 수}. 한 트랜잭션 — 실패하면 아무 알림도 남지 않는다."""
    day = today or date.today()
    created = 0
    with conn.tx() as cur:
        cur.execute(_DUE_SQL, (day, DUE_DAYS, request_nos, request_nos))
        rows = cur.fetchall()
        for r in rows:
            left = (r["due_date"] - day).days
            when = f"D-{left}" if left >= 0 else f"{-left}일 지연"
            created += notify.emit(
                cur, "due_d3_unshipped", link=due_link(r["request_no"]),
                dedupe_key=f"due:{r['request_no']}:{day.isoformat()}",
                text=(f"납기 {when} 미출하 {r['request_no']} · {r['customer_code']} · {r['item_code']} · "
                      f"납기 {r['due_date']} · 출하 {r['shipped_qty']}/{r['qty']}"))
    return {"requests": len(rows), "created": created}


COMMANDS = {"due-check": due_check}


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args or args[0] not in COMMANDS:
        print(f"사용법: uv run python -m lcomfine.jobs {{{'|'.join(COMMANDS)}}}", file=sys.stderr)
        return 2
    out = COMMANDS[args[0]]()
    print(f"{args[0]}: 대상 의뢰 {out['requests']} · 새 알림 {out['created']}행 (실행 시각 미확정 D-520)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
