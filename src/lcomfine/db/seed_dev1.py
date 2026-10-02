"""개발1 시드 — 채번 형식 6행 + 기준정보·인쇄 기준의 화면 시연용 최소 행. **두 번 돌려도 행 수가 같다**(G-09).

    uv run python -m lcomfine.db.seed_dev1

- 채번 형식(`sys_number_rule`)은 **가설**이다(D-05 · D-101). 이미 있는 행은 건드리지 않는다 — 운영에서 바꾼 형식을 시드가 되돌리면 안 된다.
- 회사 실데이터(고객명·품목명·규격값)는 받은 적이 없다. 이름에는 전부 `(예시)` 를 붙이고, 규격 숫자(도수·선수·셀 용적·기준 색상값)는 비워 둔다.
  잉크조성의 조성 행은 비율이 필수 컬럼이라 자리만 채운 예시 값이다(성분명에 `(예시)`).
- 이미 있는 코드는 건드리지 않는다(`on conflict do nothing`) — 화면에서 고친 값을 시드가 되돌리지 않는다.
- 작업지시(Job)는 넣지 않는다 — Job 번호는 `numbering.next('JOB')` 만 만들고, 시드가 번호를 지어내지 않는다.
"""

from __future__ import annotations

from ..app.util.screen import example
from . import conn

SEEDED_BY = "seed"

# 채번 가설 형식 (D-101) — (종류, 접두, 날짜 형식(to_char), 일련번호 자릿수, 비고). 공표: progress-dev1.md §1
#   번호 = prefix + to_char(now, date_format) + 일련번호. 날짜가 바뀌면 1 부터. 영문 대문자·숫자·`-` 만(바코드).
NUMBER_RULES: list[tuple[str, str, str, int, str]] = [
    ("JOB",      "J", "YYMMDD-", 3, "작업지시 번호 — 가설 (D-05 · D-101). 예 J261003-001"),
    ("JOB_LOT",  "L", "YYMMDD-", 3, "생산 LOT 번호 — 가설 (D-05 · D-101). 예 L261003-001"),
    ("MAT_LOT",  "M", "YYMMDD-", 3, "원재료 LOT 번호 — 가설 (D-05 · D-101). 예 M261003-001"),
    ("ROLL",     "R", "YYMMDD-", 4, "롤 번호 — 가설 (D-05 · D-101). 예 R261003-0001"),
    ("SHIPMENT", "S", "YYMMDD-", 3, "출하 LOT 번호 — 가설 (D-05 · D-101). 예 S261003-001"),
    ("COA",      "C", "YYMMDD-", 3, "COA 번호 — 가설 (D-05 · D-101). 예 C261003-001"),
]

# (코드, 이름, 구분, 단위) — 규격은 받은 적이 없어 비운다
ITEMS = [
    ("EX-FG-01", "제품 A", "제품", "m"),
    ("EX-FG-02", "제품 B", "제품", "m"),
    ("EX-RM-01", "원단 A", "원재료", "m"),
    ("EX-RM-02", "원단 B", "원재료", "m"),
    ("EX-RM-03", "잉크 원료 A", "원재료", "kg"),
]
CUSTOMERS = [("EX-CU-01", "고객 A"), ("EX-CU-02", "고객 B")]
# (코드, 이름, 공정 구분, 순서)
PROCESSES = [
    ("EX-PR-10", "인쇄", "인쇄", 10),
    ("EX-PR-20", "후가공", "후가공", 20),
    ("EX-PR-30", "슬리팅", "슬리팅", 30),
]
# (코드, 이름, 공정 코드)
EQUIPMENT = [
    ("EX-EQ-01", "인쇄기 1호", "EX-PR-10"),
    ("EX-EQ-02", "후가공기 1호", "EX-PR-20"),
    ("EX-EQ-03", "슬리터 1호", "EX-PR-30"),
]
# (코드, 불량명, 분류)
DEFECT_CODES = [
    ("EX-DF-01", "색차", "인쇄"),
    ("EX-DF-02", "핀홀", "인쇄"),
    ("EX-DF-03", "주름", "후가공"),
    ("EX-DF-04", "폭 불량", "슬리팅"),
]
# (코드, 판명, 품목 코드)
PLATES = [("EX-PL-01", "판 A", "EX-FG-01"), ("EX-PL-02", "판 B", "EX-FG-02")]
ANILOX = [("EX-AN-01", "아니록스 A"), ("EX-AN-02", "아니록스 B")]
# (코드, 잉크명, 색 이름, [(성분명, 비율)])
INKS = [
    ("EX-INK-01", "잉크 A", "색 A", [("성분 1", "60"), ("성분 2", "40")]),
    ("EX-INK-02", "잉크 B", "색 B", [("성분 1", "100")]),
]


def seed_number_rules() -> None:
    for kind, prefix, date_format, digits, note in NUMBER_RULES:
        conn.x("""insert into sys_number_rule (seq_kind, prefix, date_format, seq_digits, note, updated_at, updated_by)
                  values (%s, %s, %s, %s, %s, now(), %s)
                  on conflict (seq_kind) do nothing""",
               (kind, prefix, date_format, digits, note, SEEDED_BY))


def seed_master() -> None:
    with conn.tx() as cur:
        for code, name, item_type, unit in ITEMS:
            cur.execute("""insert into item (item_code, item_name, item_type, unit, created_by)
                           values (%s, %s, %s, %s, %s) on conflict (item_code) do nothing""",
                        (code, example(name), item_type, unit, SEEDED_BY))
        for code, name in CUSTOMERS:
            cur.execute("""insert into customer (customer_code, customer_name, created_by)
                           values (%s, %s, %s) on conflict (customer_code) do nothing""",
                        (code, example(name), SEEDED_BY))
        for code, name, ptype, sort_no in PROCESSES:
            cur.execute("""insert into process (process_code, process_name, process_type, sort_no, created_by)
                           values (%s, %s, %s, %s, %s) on conflict (process_code) do nothing""",
                        (code, example(name), ptype, sort_no, SEEDED_BY))
        for code, name, process_code in EQUIPMENT:
            cur.execute("""insert into equipment (equipment_code, equipment_name, process_id, created_by)
                           values (%s, %s, (select process_id from process where process_code = %s), %s)
                           on conflict (equipment_code) do nothing""",
                        (code, example(name), process_code, SEEDED_BY))
        for code, name, group in DEFECT_CODES:
            cur.execute("""insert into defect_code (defect_code, defect_name, defect_group, created_by)
                           values (%s, %s, %s, %s) on conflict (defect_code) do nothing""",
                        (code, example(name), group, SEEDED_BY))


def seed_print_standard() -> None:
    with conn.tx() as cur:
        for code, name, item_code in PLATES:
            cur.execute("""insert into plate_spec (plate_code, plate_name, item_id, created_by)
                           values (%s, %s, (select item_id from item where item_code = %s), %s)
                           on conflict (plate_code) do nothing""",
                        (code, example(name), item_code, SEEDED_BY))
        for code, name in ANILOX:
            cur.execute("""insert into anilox (anilox_code, anilox_name, created_by)
                           values (%s, %s, %s) on conflict (anilox_code) do nothing""",
                        (code, example(name), SEEDED_BY))
        for code, name, color, components in INKS:
            cur.execute("""insert into ink_formula (ink_code, ink_name, color_name, created_by)
                           values (%s, %s, %s, %s) on conflict (ink_code) do nothing
                           returning ink_formula_id""",
                        (code, example(name), example(color), SEEDED_BY))
            row = cur.fetchone()
            if row is None:        # 이미 있는 잉크조성 — 조성 행도 그대로 둔다
                continue
            for seq_no, (component, ratio) in enumerate(components, start=1):
                cur.execute("""insert into ink_formula_component (ink_formula_id, seq_no, component_name, ratio_pct)
                               values (%s, %s, %s, %s)""",
                            (row["ink_formula_id"], seq_no, example(component), ratio))


TABLES = ("sys_number_rule", "item", "customer", "process", "equipment", "defect_code",
          "plate_spec", "anilox", "ink_formula", "ink_formula_component")


def counts() -> dict[str, int]:
    return {t: conn.q1(f"select count(*) as n from {t}")["n"] for t in TABLES}


def main() -> int:
    seed_number_rules()
    seed_master()
    seed_print_standard()
    print("개발1 시드 — " + " · ".join(f"{k} {v}" for k, v in counts().items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
