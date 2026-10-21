"""정본(기획서 2026-10-21) 추출기 — 화면 구조(IA)를 `contracts/ia.json` 으로 옮기는 한 곳.

정본 `docs/엘컴화인_MES_기획서_2026-10-21.html` 은 읽기만 한다. 앱은 이 파일을 읽지 않는다.
정본은 바깥 쪽 하나에 `<iframe srcdoc>` 두 개를 담는다.
  - `f-ia`    화면 구조: 스크립트의 `1. 역할` ~ `4. 상태` 사이(ROLES · BUNDLES · ORDER · IA · 정렬 ·
              mapRoles · SELF_GRANTS · ADM R · FLOW)를 잘라 node 로 평가한다.
  - `f-guide` 부서 간 업무 변화: `const IA_DATA = [...];` 가 유효 권한을 JSON 으로 들고 있다(대조용).
`effective()` 는 `contracts/ia-overrides.json`(사람이 정한 결정)을 그 위에 얹는다.

    uv run python tools/design_doc.py          # contracts/ia.json 다시 쓰기
    uv run python tools/design_doc.py --check  # 낡았으면 종료 코드 1
"""

from __future__ import annotations

import copy
import html
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLANNING_HTML = ROOT / "docs" / "엘컴화인_MES_기획서_2026-10-21.html"
IA_JSON = ROOT / "contracts" / "ia.json"
OVERRIDES_JSON = ROOT / "contracts" / "ia-overrides.json"

START_MARK = "1. 역할"
END_MARK = "4. 상태"

# 평가한 IA 를 brief 의 모양으로 내보낸다 (정본 순서 그대로, 없는 목록은 [] — orig 는 있을 때만)
_EMIT_JS = r"""
const out = {
  roles: ROLES.map(r => ({id: r.id, name: r.name})),
  bundles: BUNDLES.map(b => ({key: b.key, name: b.name, desc: b.desc})),
  order: ORDER,
  menus: IA.map(l => ({
    code: l.code, name: l.name, kind: l.kind, opt: l.opt ?? null, bundle: l.bundle,
    screens: l.screens.map(s => {
      const o = {id: s.id, name: s.name, type: s.type, st: s.st};
      if (s.orig !== undefined) o.orig = s.orig;
      o.roles = s.roles;
      o.l3 = s.l3 || []; o.logic = s.logic || []; o.links = s.links || [];
      return o;
    }),
    data: l.data || [], batch: l.batch || []
  })),
  flow: FLOW.map(f => { const o = {id: f.id, step: f.step, sub: f.sub}; if (f.ext !== undefined) o.ext = f.ext; return o; }),
  self_grants: SELF_GRANTS
};
process.stdout.write(JSON.stringify(out));
"""


def _srcdoc(frame_id: str) -> str:
    if not PLANNING_HTML.exists():
        raise SystemExit(f"정본 없음: {PLANNING_HTML}")
    outer = PLANNING_HTML.read_text(encoding="utf-8")
    m = re.search(r'<iframe id="' + re.escape(frame_id) + r'"[^>]*?\ssrcdoc="([^"]*)"', outer)
    if not m:
        raise SystemExit(f"정본에 iframe#{frame_id} srcdoc 이 없습니다")
    return html.unescape(m.group(1))


def _banner_start(src: str, mark: str) -> int:
    """`/* ====\n   <mark>\n   ==== */` 배너 주석의 시작 위치."""
    i = src.find(mark)
    if i < 0:
        raise SystemExit(f"정본 화면 구조 스크립트에 표지 「{mark}」 가 없습니다")
    j = src.rfind("/*", 0, i)
    if j < 0:
        raise SystemExit(f"표지 「{mark}」 앞에 주석 시작이 없습니다")
    return j


def _ia_script() -> str:
    doc = _srcdoc("f-ia")
    a = _banner_start(doc, START_MARK)
    b = _banner_start(doc[a + 1 :], END_MARK) + a + 1
    return doc[a:b]


def _node(js: str) -> str:
    node = shutil.which("node")
    if not node:
        raise SystemExit("node 가 필요합니다")
    res = subprocess.run([node, "-e", js], capture_output=True, text=True, encoding="utf-8")
    if res.returncode != 0:
        raise SystemExit(f"node 평가 실패:\n{res.stderr}")
    return res.stdout


def load() -> dict:
    """정본 1쪽의 화면 구조. 화면 roles 는 mapRoles + SELF_GRANTS + ADM R 적용 뒤의 유효 권한."""
    return json.loads(_node(_ia_script() + _EMIT_JS))


def roles_from_guide() -> dict:
    """정본 2쪽 IA_DATA 의 화면별 유효 권한 {screen_id: {dept: level}}."""
    doc = _srcdoc("f-guide")
    m = re.search(r"const IA_DATA = (\[.*?\]);\s*\n", doc, re.S)
    if not m:
        raise SystemExit("정본 2쪽에 const IA_DATA = [...]; 가 없습니다")
    data = json.loads(m.group(1))
    return {s["id"]: s["roles"] for menu in data for s in menu["screens"]}


def overrides() -> dict:
    return json.loads(OVERRIDES_JSON.read_text(encoding="utf-8"))


def effective(d: dict | None = None) -> dict:
    """정본 위에 ia-overrides.json(화면 제거 · 대메뉴 이름 변경)을 얹은 것."""
    e = copy.deepcopy(d if d is not None else load())
    ov = overrides()
    codes = {m["code"] for m in e["menus"]}
    ids = {s["id"] for m in e["menus"] for s in m["screens"]}
    for code in ov.get("rename_menu", {}):
        if code not in codes:
            raise SystemExit(f"ia-overrides: 없는 대메뉴 {code}")
    for sid in ov.get("remove_screens", {}):
        if sid not in ids:
            raise SystemExit(f"ia-overrides: 없는 화면 {sid}")
    removed = set(ov.get("remove_screens", {}))
    for m in e["menus"]:
        if m["code"] in ov.get("rename_menu", {}):
            m["name"] = ov["rename_menu"][m["code"]]["name"]
        m["screens"] = [s for s in m["screens"] if s["id"] not in removed]
        for s in m["screens"]:
            s["links"] = [x for x in s["links"] if x not in removed]
    e["flow"] = [f for f in e["flow"] if f["id"] not in removed]
    e["self_grants"] = [g for g in e["self_grants"] if g[0] not in removed]
    return e


def counts(d: dict) -> dict:
    screens = [s for m in d["menus"] for s in m["screens"]]
    levels = [v for s in screens for v in s["roles"].values()]
    return {
        "bundles": len(d["bundles"]),
        "menus": len(d["menus"]),
        "screens": len(screens),
        "roles": len(d["roles"]),
        "cells_w": levels.count("W"),
        "cells_r": levels.count("R"),
    }


def _render(d: dict) -> str:
    return json.dumps(d, ensure_ascii=False, indent=2) + "\n"


def write_json(check: bool = False) -> bool:
    """check=False: contracts/ia.json 을 load() 로 다시 쓰고 True. check=True: 같은지만 본다."""
    text = _render(load())
    if check:
        return IA_JSON.exists() and IA_JSON.read_text(encoding="utf-8") == text
    IA_JSON.write_text(text, encoding="utf-8")
    return True


if __name__ == "__main__":
    if "--check" in sys.argv[1:]:
        if not write_json(check=True):
            print(f"낡음: {IA_JSON.relative_to(ROOT)} — uv run python tools/design_doc.py 로 다시 쓰십시오")
            sys.exit(1)
        print(f"최신: {IA_JSON.relative_to(ROOT)}")
    else:
        write_json()
        print(f"썼음: {IA_JSON.relative_to(ROOT)} {counts(json.loads(IA_JSON.read_text(encoding='utf-8')))}")
