"""개발3 시드 — 품질 검사(D7) · 출하(D8). **넣는 행이 없다.** 두 번 돌려도 행 수가 같다(G-09).

    uv run python -m lcomfine.db.seed_dev3

왜 비어 있는가
  · 검사 결과와 출하는 **롤**을 가리킨다. 롤은 현장 실행(작업 종료 · 후가공 · 슬리팅)에서만 생기고, 롤·Job·출하 LOT·COA 의
    번호는 `numbering` 만 만든다 — 시드가 번호와 계보를 지어내지 않는다(개발1 시드도 Job 을 넣지 않는다).
  · 그래서 새 DB 의 품질·출하·추적·실적 화면은 `미수집` 으로 열린다(G-11). 데이터는 화면 흐름으로 만든다:
    작업지시 → 입고·입고검사 → 작업 실적 → (후가공·슬리팅) → **검사 결과 → 출하 등록 → 롤 스캔 → 승인 → COA**.
  · 개발3 의 기준 데이터는 없다. 불량코드·채번 형식은 개발1 시드, 권한 표는 공통 시드가 넣는다.

대신 이 시드는 개발3 화면이 기대는 **앞 시드의 행이 있는지** 확인해 알려 준다(없으면 무엇이 `미확정`/`미수집` 으로 보이는지).
확인은 읽기만 한다 — 어떤 테이블에도 쓰지 않는다.
"""

from __future__ import annotations

from . import conn

#: 개발3 화면이 쓰는 테이블 (D7 · D8) — 시드는 여기에 행을 넣지 않는다
OWN_TABLES: tuple[str, ...] = ("inspection", "inspection_defect", "shipment")


def counts() -> dict[str, int]:
    return {t: conn.q1(f"select count(*) as n from {t}")["n"] for t in OWN_TABLES}


def prerequisites() -> list[tuple[str, bool, str]]:
    """(무엇, 있는가, 없을 때 화면에서 보이는 것). 읽기만 한다."""
    kinds = {r["seq_kind"] for r in conn.q("select seq_kind from sys_number_rule where seq_kind in ('SHIPMENT', 'COA')")}
    defects = conn.q1("select count(*) as n from defect_code where use_yn = 'Y'")["n"]
    cells = conn.q1("select count(*) as n from sys_permission where menu_code in ('QUA', 'SHP', 'TRC', 'STA')")["n"]
    return [
        ("채번 형식 SHIPMENT · COA (개발1 시드)", kinds == {"SHIPMENT", "COA"},
         "출하 등록·승인이 500 — 채번 형식 미확정 (D-05)"),
        (f"불량코드 {defects}건 (개발1 시드)", defects > 0, "검사 결과 등록의 불량 유형 선택칸이 미수집"),
        (f"권한 표 QUA · SHP · TRC · STA {cells}칸 (공통 시드)", cells == 16, "권한 칸이 없는 역할은 403"),
    ]


def main() -> int:
    before = counts()
    checks = prerequisites()
    after = counts()
    print("개발3 시드 — 넣는 행 없음 (검사·출하는 롤이 있어야 하고, 롤과 번호는 화면 흐름과 채번이 만든다)")
    print("행 수 — " + " · ".join(f"{t} {n}" for t, n in after.items()) + f" (시드 전후 차이 {sum(after.values()) - sum(before.values())})")
    for what, ok, effect in checks:
        print(f"  {'있음' if ok else '없음'}  {what}" + ("" if ok else f" → {effect}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
