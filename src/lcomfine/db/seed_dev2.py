"""개발2 시드 — 원재료 LOT 의 화면 시연용 최소 행. **두 번 돌려도 행 수가 같다**(G-09).

    uv run python -m lcomfine.db.seed_dev2

- 넣는 것: 원재료 LOT 4건(입고검사 합격 2 · 대기 1 · 불합격 1). 입고·입고검사·원재료 LOT 화면이 비어 있지 않게 하고,
  자재 투입 스캔에서 「합격만 투입된다」를 바로 해 볼 수 있게 한다.
- 품목은 개발1 시드의 원재료 품목(`EX-RM-…`)을 쓴다. 그 품목이 없으면 **실패한다**(`seed_dev1` 을 먼저 돌린다) — 품목을 여기서 지어내지 않는다.
- LOT 번호는 `numbering.next('MAT_LOT')` 가 낸다(시드가 번호를 지어내지 않는다). 이미 넣었는지는 공급사 LOT 번호(`EX-SL-…`)로 본다 —
  있으면 건드리지 않는다(화면에서 고친 판정을 시드가 되돌리지 않는다).
- 회사 실데이터는 없다. 공급처·비고에는 `(예시)` 를 붙이고, 입고 수량은 자리만 채운 예시 값이다.
- 작업 실적·롤·계보·조색 기록은 넣지 않는다 — Job 이 있어야 하고(개발1 시드는 Job 을 넣지 않는다) 화면 조작으로 만드는 것이 이 시스템의 본 흐름이다.
"""

from __future__ import annotations

from ..app import numbering
from ..app.util.screen import example
from . import conn

SEEDED_BY = "seed"

# (공급사 LOT 번호 = 멱등 키, 원재료 품목 코드(개발1 시드), 입고 수량(예시), 입고검사 결과)
MATERIAL_LOTS: list[tuple[str, str, str, str]] = [
    ("EX-SL-01", "EX-RM-01", "1000", "합격"),
    ("EX-SL-02", "EX-RM-01", "1000", "대기"),
    ("EX-SL-03", "EX-RM-02", "1000", "합격"),
    ("EX-SL-04", "EX-RM-02", "1000", "불합격"),
]


def seed_material_lots() -> int:
    """없는 것만 넣는다. 넣은 건수를 돌려준다."""
    made = 0
    for supplier_lot_no, item_code, qty, result in MATERIAL_LOTS:
        with conn.tx() as cur:
            cur.execute("select 1 from material_lot where supplier_lot_no = %s and received_by = %s",
                        (supplier_lot_no, SEEDED_BY))
            if cur.fetchone():
                continue
            cur.execute("select item_id, unit from item where item_code = %s and item_type = '원재료'", (item_code,))
            item = cur.fetchone()
            if item is None:
                raise SystemExit(f"seed_dev2: 원재료 품목 {item_code} 가 없다 — `uv run python -m lcomfine.db.seed_dev1` 을 먼저 돌린다")
            inspected = result != "대기"
            cur.execute(
                """insert into material_lot (lot_no, item_id, supplier_name, supplier_lot_no, received_qty, qty_unit,
                                             received_by, insp_status, insp_at, insp_by, insp_note, note)
                   values (%s, %s, %s, %s, %s, %s, %s, %s, case when %s then now() end, %s, %s, %s)""",
                (numbering.next(numbering.MAT_LOT, cur=cur), item["item_id"], example("공급처 A"), supplier_lot_no, qty,
                 item["unit"] or "m", SEEDED_BY, result, inspected, SEEDED_BY if inspected else None,
                 example(f"입고검사 {result}") if inspected else None, example("시연용 원재료 LOT")))
            made += 1
    return made


def main() -> int:
    made = seed_material_lots()
    by_status = {r["insp_status"]: r["n"] for r in conn.q(
        "select insp_status, count(*) as n from material_lot where received_by = %s group by insp_status", (SEEDED_BY,))}
    print(f"개발2 시드 — 원재료 LOT 새로 {made}건 · 시드 LOT 합계 "
          + " · ".join(f"{k} {by_status.get(k, 0)}" for k in ("합격", "대기", "불합격")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
