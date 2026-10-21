#!/usr/bin/env python
"""기능 목록 초안 생성기 (D-508) — **한 번만** 쓴다. 그 뒤로는 `contracts/function-list.md` 가 원본이다.

  --draft [경로]   정본(`design_doc.effective()`)의 화면 유형을 규칙 A 로 전개한 §2 표 초안을 찍는다.
                   경로를 주지 않으면 stdout. `contracts/function-list.md` 로는 **절대 쓰지 않는다** —
                   아키텍트가 초안의 계약 문장(정본 logic 을 `·` 로 이은 것)을 기능별로 손질해 옮긴다.
  --summary        `contracts/function-list.md` 를 읽어 대메뉴별 기능 수 표(§3)를 stdout 에 찍는다.

    uv run python tools/gen_function_list.py --draft /tmp/draft.md
    uv run python tools/gen_function_list.py --summary
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from tools import design_doc  # noqa: E402

FUNCTION_LIST = ROOT / "contracts" / "function-list.md"

# 규칙 A — (기능 유형, API 꼴). {p} = nav.path_of(화면 ID)
EXPANSION: dict[str, list[tuple[str, str]]] = {
    "조회": [("조회", "GET {p}")],
    "리포트": [("조회", "GET {p}")],
    "출력": [("조회", "GET {p}")],
    "등록": [("등록", "POST {p}"), ("수정", "POST {p}/{{id}}"), ("조회", "GET {p}")],
    "목록·등록": [("등록", "POST {p}"), ("수정", "POST {p}/{{id}}"), ("삭제", "POST {p}/{{id}}/delete"), ("조회", "GET {p}")],
    "등록·출력": [("등록", "POST {p}"), ("수정", "POST {p}/{{id}}"), ("조회", "GET {p}"), ("출력", "GET {p}/{{id}}/print")],
    "처리": [("처리", "POST {p}/{{id}}/{verb}"), ("조회", "GET {p}")],
    "설정": [("저장", "POST {p}"), ("조회", "GET {p}")],
    "외부 연계(SSO)": [("진입", "POST {p}"), ("조회", "GET {p}")],
}
EXTRA = {                                              # 유형 예외 (D-508 · D-511 · D-513 · D-515)
    "RPT-130": [("처리", "POST {p}")],                 # 질의 실행
    "SHP-020": [("처리", "POST {p}/{{id}}/adjust")],   # 반품·정정 등록
    "HOME-020": [("처리", "POST {p}/{{id}}/handle")],  # 알림 처리
}
VERBS = {"WO-030": "move", "SHP-020": "confirm"}       # 처리 화면의 동사 (addendum §A)
NO_EDIT = {"INV-030", "COL-010"}                       # 정본 logic 이 수정을 막는 등록 화면 — 「수정 없음」
WRITE_KINDS = {"등록", "수정", "삭제", "처리", "저장", "진입"}

# 쓰는 테이블 (스펙 §4.1 · addendum §B) — 쓰기 기능 초안에 화면 단위로 붙인다. 손질에서 기능별로 줄인다.
TABLES: dict[str, list[str]] = {
    "HOME-030": ["notification_setting"],
    "BAS-010": ["item"], "BAS-020": ["customer"], "BAS-030": ["warehouse", "location"],
    "STD-010": ["spec_sheet"], "STD-020": ["standard"], "STD-030": ["plate", "plate_usage"], "STD-040": ["artwork"],
    "STD-050": ["sample_sheet"], "STD-060": ["exception_item"],
    "WO-010": ["production_request", "notification"], "WO-020": ["work_order", "notification"], "WO-030": ["work_sequence"],
    "MAT-010": ["material_receipt", "material_lot", "lot_stock", "notification"],
    "MAT-020": ["material_issue", "material_issue_line", "lot_stock", "stock_move"],
    "MAT-030": ["product_receipt", "product_lot", "lot_stock", "notification"],
    "PRD-010": ["production_daily"], "INS-010": ["inspection_daily"],
    "QC-010": ["incoming_inspection", "lot_stock"], "QC-020": ["product_inspection", "lot_stock", "notification"],
    "INV-020": ["stock_move", "lot_stock"], "INV-030": ["stock_adjust", "lot_stock"],
    "SHP-010": ["shipment_order", "shipment_line", "lot_stock", "notification"],
    "SHP-020": ["shipment_order", "lot_stock", "stock_move", "notification"],
    "COL-010": ["erp_upload_batch", "erp_upload_row", "erp_column_map", "notification"],
    "COL-030": ["erp_customer_map", "erp_upload_row"],
    "RPT-130": ["data_query_log", "sys_ai_call_log"],
    "DOC-010": ["sso_token", "sys_access_log"], "DOC-020": ["doc_account_map"],
    "SYS-010": ["sys_user"], "SYS-020": ["sys_role", "sys_permission"], "SYS-030": ["sys_common_code"],
}

HEADER = "| ID | 대메뉴 | 화면 ID | 기능명 | 유형 | 쓰는 테이블 | 권한 | API | 담당 | 계약 |"


def draft_rows() -> list[str]:
    from lcomfine.app import nav

    e = design_doc.effective()
    names = {r["id"]: r["name"] for r in e["roles"]}
    order = [r["id"] for r in e["roles"]]
    rows = [HEADER, "|---|---|---|---|---|---|---|---|---|---|"]
    for m in e["menus"]:
        for s in m["screens"]:
            p = nav.path_of(s["id"])
            plan = [k for k in EXPANSION[s["type"]] if not (s["id"] in NO_EDIT and k[0] == "수정")]
            plan = plan + EXTRA.get(s["id"], [])          # 유형 예외 3 — 화면 끝에 더한다
            head, num = s["id"].split("-")
            w = [names[r] for r in sorted((r for r, v in s["roles"].items() if v == "W"), key=order.index)]
            draft = " · ".join(s["logic"])
            for i, (kind, api) in enumerate(plan, start=1):
                path = api.format(p="" if p == "/" else p, verb=VERBS.get(s["id"], ""))
                if path.endswith(" "):                   # HOME-010 = "/"
                    path += "/"
                write = kind in WRITE_KINDS
                rows.append("| " + " | ".join([
                    f"F-{head}-{num[:2]}{i}", m["code"], s["id"], f"{s['name']} {kind}", kind,
                    ", ".join(TABLES.get(s["id"], [])) if write else "-",
                    ("·".join(w) or "R 이상(권한 예외)") if write else "R 이상",
                    f"`{path}`", nav.by_id(s["id"]).owner, draft,
                ]) + " |")
    return rows


def summary() -> str:
    sys.path.insert(0, str(ROOT / "src"))
    from lcomfine.app import contracts, nav

    fns = contracts.functions()
    out = ["| 대메뉴 | 이름 | 화면 | 기능 | 쓰기 | 읽기 | 담당 |", "|---|---|---|---|---|---|---|"]
    for m in nav.MENUS:
        mine = [f for f in fns if f.menu_code == m.code]
        nw = sum(1 for f in mine if f.is_write)
        out.append(f"| {m.code} | {m.name} | {len(m.screens)} | {len(mine)} | {nw} | {len(mine) - nw} | {m.owner} |")
    nw = sum(1 for f in fns if f.is_write)
    out.append(f"| **합계** | | **{len(nav.SCREENS)}** | **{len(fns)}** | **{nw}** | **{len(fns) - nw}** | |")
    kinds = Counter(f.kind for f in fns)
    out += ["", "유형별: " + " · ".join(f"{k} {kinds[k]}" for k in
                                        ["등록", "수정", "삭제", "처리", "저장", "진입", "조회", "출력"] if kinds[k])]
    return "\n".join(out)


def main(argv: list[str]) -> int:
    if "--summary" in argv:
        print(summary())
        return 0
    if "--draft" in argv:
        rest = argv[argv.index("--draft") + 1:]
        text = "\n".join(draft_rows()) + "\n"
        if not rest:
            sys.stdout.write(text)
            return 0
        target = Path(rest[0]).resolve()
        if target == FUNCTION_LIST.resolve():
            print(f"{FUNCTION_LIST.relative_to(ROOT)} 는 원본이다 — 초안으로 덮어쓰지 않는다. 다른 경로를 준다.")
            return 1
        target.write_text(text, encoding="utf-8")
        print(f"초안: {target} ({len(text.splitlines()) - 2} 줄)")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
