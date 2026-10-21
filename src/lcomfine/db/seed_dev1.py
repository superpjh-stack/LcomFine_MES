"""개발1 시드 — 기준정보(품목 · 거래처 · 창고 · 위치) 최소 한 벌. 전부 `(예시)` · 멱등(코드로 upsert — 두 번 돌려도 행 수 같다).

회사 실데이터(고객명 · 품목명 · 규격)는 받은 적이 없어 지어내지 않는다 — 이름은 「제품 A (예시)」 같은 중립 이름, 규격은 비운다.
공통 시드(`seed.py`) 다음에 돈다: `uv run python -c "from lcomfine.db import seed_dev1; seed_dev1.run()"`.
"""

from __future__ import annotations

from ..app.util.screen import example
from . import conn

BY = "seed_dev1"

ITEMS: list[tuple[str, str, str]] = [
    ("EX-P01", "제품 A", "제품"), ("EX-P02", "제품 B", "제품"),
    ("EX-M01", "원자재 A", "원자재"), ("EX-M02", "원자재 B", "원자재"),
]
CUSTOMERS: list[tuple[str, str]] = [("EX-C01", "거래처 A"), ("EX-C02", "거래처 B")]
WAREHOUSES: list[tuple[str, str, list[tuple[str, str]]]] = [
    ("EX-W01", "창고 1", [("L01", "위치 1"), ("L02", "위치 2")]),
]


def run() -> dict[str, int]:
    with conn.tx() as cur:
        for code, name, typ in ITEMS:
            cur.execute("""insert into item (item_code, item_name, item_type, created_by) values (%s, %s, %s, %s)
                           on conflict (item_code) do update set item_name = excluded.item_name""",
                        (code, example(name), typ, BY))
        for code, name in CUSTOMERS:
            cur.execute("""insert into customer (customer_code, customer_name, created_by) values (%s, %s, %s)
                           on conflict (customer_code) do update set customer_name = excluded.customer_name""",
                        (code, example(name), BY))
        for code, name, locs in WAREHOUSES:
            cur.execute("""insert into warehouse (warehouse_code, warehouse_name, created_by) values (%s, %s, %s)
                           on conflict (warehouse_code) do update set warehouse_name = excluded.warehouse_name
                           returning id""", (code, example(name), BY))
            wid = cur.fetchone()["id"]
            for lcode, lname in locs:
                cur.execute("""insert into location (warehouse_id, location_code, location_name, created_by)
                               values (%s, %s, %s, %s)
                               on conflict (warehouse_id, location_code) do update set location_name = excluded.location_name""",
                            (wid, lcode, example(lname), BY))
    return {"item": len(ITEMS), "customer": len(CUSTOMERS), "warehouse": len(WAREHOUSES),
            "location": sum(len(w[2]) for w in WAREHOUSES)}


def main() -> int:
    """`seed.py` 의 DEV_SEEDS 규약 — 0 = 성공."""
    print("seed_dev1:", run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
