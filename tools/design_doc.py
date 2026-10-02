"""설계도(정본 HTML) 파서 — 검사 도구들이 기대값을 **설계도에서 직접** 끌어오는 한 곳.

정본 `엘컴화인_MES_설계도 복사본.html` 은 읽기만 한다. 앱은 이 파일을 읽지 않는다(검사 도구만 읽는다).
세는 방법은 goal.md §9 의 정규식과 같다.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESIGN_HTML = ROOT / "엘컴화인_MES_설계도 복사본.html"

MENU_RE = re.compile(r'<div class="ia-menu[^"]*"><h4>(.*?) <span>(\d+)</span></h4><ul>(.*?)</ul>')
CELL_RE = re.compile(r'<td(?: class="([wn])")?>(입력[^<]*|조회|없음)</td>')


def html() -> str:
    if not DESIGN_HTML.exists():
        raise SystemExit(f"정본 없음: {DESIGN_HTML}")
    return DESIGN_HTML.read_text(encoding="utf-8")


def _section(h: str, sec_id: str, next_id: str | None) -> str:
    a = h.index(f'id="{sec_id}"')
    b = h.index(f'id="{next_id}"', a) if next_id else len(h)
    return h[a:b]


def ia(h: str | None = None) -> dict:
    """§5 IA 구성도 → {root: (대메뉴 수, 중메뉴 수), groups: [{name, menus: [{name, count, subs}]}]}."""
    h = h or html()
    sec = _section(h, "ia", "access")
    m = re.search(r"대메뉴 (\d+) · 중메뉴 (\d+)", sec)
    groups = []
    for part in sec.split('<div class="ia-group">')[1:]:
        g = re.search(r'<p class="ia-gname">(.*?)</p>', part)
        menus = [{"name": name, "count": int(n), "subs": re.findall(r"<li>(.*?)</li>", lis)}
                 for name, n, lis in MENU_RE.findall(part)]
        groups.append({"name": g.group(1) if g else "", "menus": menus})
    return {"root": (int(m.group(1)), int(m.group(2))) if m else (0, 0), "groups": groups}


def access(h: str | None = None) -> dict:
    """§6 역할과 채널 → {roles: [4], rows: [{menu, cells: [4], channels: [..]}]}. 칸 글자는 설계도 그대로."""
    h = h or html()
    sec = _section(h, "access", "open")
    head = re.search(r"<thead><tr>(.*?)</tr></thead>", sec, re.S).group(1)
    cols = re.findall(r"<th>(.*?)</th>", head)
    rows = []
    for tr in re.findall(r"<tr>(.*?)</tr>", sec.split("<tbody>")[1].split("</tbody>")[0], re.S):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr)
        rows.append({"menu": tds[0], "cells": tds[1:5], "channels": [c.strip() for c in tds[5].split(",")]})
    return {"roles": cols[1:5], "rows": rows}


def access_counts(h: str | None = None) -> dict[str, int]:
    """goal.md §9 와 같은 방법 — 권한 칸 48 = 입력 19 · 조회 24 · 없음 5."""
    h = h or html()
    cells = CELL_RE.findall(_section(h, "access", "open"))
    return {"전체": len(cells), "입력": sum(c[0] == "w" for c in cells), "조회": sum(c[1] == "조회" for c in cells),
            "없음": sum(c[0] == "n" for c in cells)}


def processes(h: str | None = None) -> dict[str, dict]:
    """§2 「프로세스별 입력과 출력」 표 → {P1: {name, actor, inputs, writes: [D..], reads: [D..], outputs}}."""
    h = h or html()
    sec = _section(h, "dfd", "lineage")
    body = sec.split("<tbody>")[1].split("</tbody>")[0]
    out: dict[str, dict] = {}
    for tr in re.findall(r"<tr>(.*?)</tr>", body, re.S):
        tds = re.findall(r"<td>(.*?)</td>", tr)
        code, name = tds[0].split(" ", 1)
        out[code] = {"name": name, "actor": tds[1], "inputs": tds[2],
                     "writes": re.findall(r"D\d", tds[3]), "reads": re.findall(r"D\d", tds[4]), "outputs": tds[5]}
    return out


def lineage_arrows(h: str | None = None) -> int:
    """§3 그림의 「계보 선: 부모 → 자식」 화살표 수 (= roll_genealogy 예시 행 수, G-06)."""
    h = h or html()
    sec = _section(h, "lineage", "arch")
    block = sec[sec.index("<!-- 계보 선: 부모 → 자식 -->"): sec.index("<!-- 관계 이름")]
    return len(re.findall(r"<path ", block))
