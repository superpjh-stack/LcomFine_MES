"""개발3 시드 — ERP 엑셀 열 매핑 한 벌 `(예시)` (D-516 차단 · D-802).

열 구성은 사람이 정하지 않았다. 매핑 값(엑셀 열 이름)은 정본 COL-010 logic 문장의 낱말
「거래처코드, 일자, 매출액, 수금액, 수단, 어음 만기」 + 잔액(정본 COL-050 「매출(청구)액과 잔액 열」)을 그대로 쓴다 —
지어낸 열 이름이 아니라 정본 문장에서 베낀 것이고, 실제 ERP 파일의 열 이름이 다르면 COL-010 열 매핑에서 바꾼다(그러면 시드는 다시 덮지 않는다).
멱등: 이미 행이 있으면 건드리지 않는다(`on conflict do nothing`). 수금 행 · 거래처 매핑은 시드하지 않는다 — 회사 실데이터를 지어내지 않는다.
"""

from __future__ import annotations

from ..app import erp_upload
from . import conn

SEEDED_BY = "seed"

#: MES 항목 → 정본 문장의 열 낱말 (D-516 가설 · D-802)
COLUMN_MAP: dict[str, str] = {
    "customer_code": "거래처코드",
    "txn_date": "일자",
    "sales_amount": "매출액",
    "collected_amount": "수금액",
    "balance_amount": "잔액",
    "method": "수단",
    "bill_due_date": "어음 만기",
}


def seed_column_map() -> int:
    assert set(COLUMN_MAP) == set(erp_upload.FIELDS), "FIELDS 와 시드 매핑의 항목이 다르다"
    n = 0
    for field, column_name in COLUMN_MAP.items():
        n += conn.x("""insert into erp_column_map (field, column_name, created_by) values (%s, %s, %s)
                       on conflict (field) do nothing""", (field, column_name, SEEDED_BY))
    return n


def main() -> int:
    n = seed_column_map()
    total = conn.q1("select count(*) as n from erp_column_map")["n"]
    print(f"seed_dev3: erp_column_map 새 행 {n} · 전체 {total} (D-516 가설 매핑 · 시드)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
