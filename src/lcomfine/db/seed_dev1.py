"""개발1 시드 — 기준정보(품목 · 거래처 · 창고 · 위치) 최소 한 벌 + 공통코드 그룹 3 보장 + 시드 계정 8 의 문서관리 계정 매핑(W4). 전부 `(예시)` · 멱등(코드로 upsert — 두 번 돌려도 행 수 같다).

공통코드(SYS-030 · F-SYS-031 「설비 · 불량유형 · 수금수단 코드를 여기서 관리한다」)의 기본 행은 공통 시드 `seed.py` 의 `COMMON_CODES`(아키텍트) 가 넣는다.
여기서는 **그룹마다 사용 중(`use_yn = 'Y'`) 코드가 하나는 있는지**만 보고, 비어 있는 그룹에만 `(예시)` 코드 하나를 더한다 —
다른 라우터(WO · PRD · INS · COL · INV)가 그룹 글자 `설비` · `불량유형` · `수금수단` 으로 읽기 때문에 빈 그룹은 선택지가 없는 화면이 된다.

회사 실데이터(고객명 · 품목명 · 규격)는 받은 적이 없어 지어내지 않는다 — 이름은 「제품 A (예시)」 같은 중립 이름, 규격은 비운다.
공통 시드(`seed.py`) 다음에 돈다: `uv run python -c "from lcomfine.db import seed_dev1; seed_dev1.run()"`.
"""

from __future__ import annotations

from ..app.util.screen import example
from . import conn, seed

BY = "seed_dev1"

ITEMS: list[tuple[str, str, str]] = [
    ("EX-P01", "제품 A", "제품"), ("EX-P02", "제품 B", "제품"),
    ("EX-M01", "원자재 A", "원자재"), ("EX-M02", "원자재 B", "원자재"),
]
CUSTOMERS: list[tuple[str, str]] = [("EX-C01", "거래처 A"), ("EX-C02", "거래처 B")]
WAREHOUSES: list[tuple[str, str, list[tuple[str, str]]]] = [
    ("EX-W01", "창고 1", [("L01", "위치 1"), ("L02", "위치 2")]),
]
#: 공통코드 그룹 3 (routers/sys.py CODE_GROUPS 와 같은 글자) → 그룹이 비어 있을 때만 넣는 (예시) 코드
CODE_GROUP_FALLBACK: dict[str, tuple[str, str]] = {
    "설비": ("EX-EQ", "설비"), "불량유형": ("EX-DF", "불량유형"), "수금수단": ("EX-PM", "수금수단"),
}


def doc_account(login_id: str) -> str:
    """시드 계정의 (예시) 문서관리 계정 ID."""
    return example(f"doc-{login_id}")


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
        added = 0
        for sort_no, (group, (code, name)) in enumerate(CODE_GROUP_FALLBACK.items(), 1):
            cur.execute("select 1 from sys_common_code where group_code = %s and use_yn = 'Y' limit 1", (group,))
            if cur.fetchone() is None:
                cur.execute("""insert into sys_common_code (group_code, code, code_name, sort_no, created_by)
                               values (%s, %s, %s, %s, %s) on conflict (group_code, code) do nothing""",
                            (group, code, example(name), 100 + sort_no, BY))
                added += cur.rowcount
        cur.execute("select count(distinct group_code) as n from sys_common_code where use_yn = 'Y'")
        groups = cur.fetchone()["n"]
        # DOC-020 — 시드 계정 8 의 문서관리 계정 매핑 `doc-<login_id> (예시)` (계정 ID 는 받은 적이 없다 · D-517).
        # 멱등: 그 사용자에게 매핑이 이미 있으면(관리자가 바꾼 것 포함) 건드리지 않는다.
        doc_added = 0
        for login_id, _name, _role in seed.USERS:
            cur.execute("""insert into doc_account_map (user_id, account_id, created_by)
                           select u.user_id, %s, %s from sys_user u
                            where u.login_id = %s
                              and not exists (select 1 from doc_account_map m where m.user_id = u.user_id)
                              and not exists (select 1 from doc_account_map m where m.account_id = %s)""",
                        (doc_account(login_id), BY, login_id, doc_account(login_id)))
            doc_added += cur.rowcount
        cur.execute("select count(*) as n from doc_account_map m join sys_user u on u.user_id = m.user_id "
                    "where u.login_id = any(%s)", ([u[0] for u in seed.USERS],))
        doc_maps = cur.fetchone()["n"]
    return {"item": len(ITEMS), "customer": len(CUSTOMERS), "warehouse": len(WAREHOUSES),
            "location": sum(len(w[2]) for w in WAREHOUSES), "code_group": groups, "code_added": added,
            "doc_map": doc_maps, "doc_map_added": doc_added}


def main() -> int:
    """`seed.py` 의 DEV_SEEDS 규약 — 0 = 성공."""
    print("seed_dev1:", run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
