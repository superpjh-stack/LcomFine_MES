#!/usr/bin/env python
"""권한 매트릭스 렌더 — `contracts/permission-matrix.md` 를 정본에서 매번 다시 찍는다 (D-508 · goal.md §6).

원본 = `contracts/ia.json` + `contracts/ia-overrides.json` (`tools/design_doc.effective()` 의 화면별 roles).
이 파일이 찍은 표를 `lcomfine.app.contracts.permission_cells()` 가 읽고, 시드가 `sys_permission` 257행으로 넣는다.

    uv run python tools/gen_permissions.py           # 다시 찍기
    uv run python tools/gen_permissions.py --check   # 찍은 결과가 파일과 다르면 종료 코드 1
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import design_doc  # noqa: E402

OUT = ROOT / "contracts" / "permission-matrix.md"


def render() -> str:
    e = design_doc.effective()
    roles = e["roles"]
    screens = [s for m in e["menus"] for s in m["screens"]]
    n_w = sum(1 for s in screens for v in s["roles"].values() if v == "W")
    n_r = sum(1 for s in screens for v in s["roles"].values() if v == "R")
    lines = [
        f"# 권한 매트릭스 — 화면 {len(screens)} × 부서 {len(roles)}",
        "",
        "> **생성 파일 · 손으로 고치지 않는다 · 원본 = ia.json + ia-overrides.json** (`uv run python tools/gen_permissions.py`).",
        "> 칸 값: `W` 처리(쓰기 기능 실행) · `R` 조회(화면 열기) · `·` 권한 없음(메뉴 숨김 · 403).",
        "> 이 표는 **기본값**이다 — 운영값은 DB `sys_permission`(시드 = 이 표)이고 SYS-020 역할·권한 화면이 바꾼다.",
        "> 앱은 이 파일을 `contracts.permission_cells()` 로만 읽는다. 코드에 부서 · 칸을 박지 않는다.",
        "",
        "| 화면 ID | 화면 | " + " | ".join(r["name"] for r in roles) + " |",
        "|---|---|" + "---|" * len(roles),
    ]
    for s in screens:
        cells = [s["roles"].get(r["id"], "·") for r in roles]
        lines.append(f"| {s['id']} | {s['name']} | " + " | ".join(cells) + " |")
    lines += [
        "",
        f"합계: W {n_w} · R {n_r} · 칸 {n_w + n_r} (부서 {len(roles)} × 화면 {len(screens)} = {len(roles) * len(screens)} 중).",
        "",
    ]
    return "\n".join(lines)


def main(check: bool = False) -> int:
    new = render()
    old = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
    if check:
        if new != old:
            print(f"{OUT.relative_to(ROOT)} 가 원본과 다르다 — `uv run python tools/gen_permissions.py` 로 다시 찍는다")
            return 1
        print("권한 매트릭스 = 원본")
        return 0
    if new != old:
        OUT.write_text(new, encoding="utf-8")
        print(f"다시 찍음: {OUT.relative_to(ROOT)}")
    else:
        print("변경 없음")
    return 0


if __name__ == "__main__":
    sys.exit(main("--check" in sys.argv))
