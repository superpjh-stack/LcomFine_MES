"""메인 = IA(정보 구조) 화면 (D-419) — 설명 글은 설계도에서 옮긴 것이고, 수는 계약 · DB 에서 센다.

`app/ia.py` 의 프로세스 표를 설계도(`tools/design_doc.processes()`)와 글자 단위로 대조한다 — 앱은 설계도를 읽지 않으므로 여기서 잡는다.
권한에 따른 숨김(카드 · 링크)은 `tests/test_dev1_home.py` 가 본다. 공통 시드가 들어 있어야 한다(`make db-reset`).
"""
import re
import sys
from pathlib import Path

import pytest

from lcomfine.app import contracts, ia, nav, numbering, rbac
from test_dev1_helpers import client

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import design_doc  # noqa: E402

pytestmark = pytest.mark.fn("F-SYS-05")


def test_process_table_is_the_design_doc_word_for_word():
    """설계도 §2 「프로세스별 입력과 출력」 10줄 = `ia.PROCESSES` (이름 · 주체 · 입력 · 쓰기 · 참조 · 출력물)."""
    doc = design_doc.processes()
    assert [p.code for p in ia.PROCESSES] == [f"P{i}" for i in range(1, 11)] == list(doc)
    for p in ia.PROCESSES:
        d = doc[p.code]
        assert (p.name, p.actor, p.inputs, list(p.writes), list(p.reads), p.outputs) == \
               (d["name"], d["actor"], d["inputs"], d["writes"], d["reads"], d["outputs"]), p.code
    assert [c for c, _ in ia.STORES][:8] == [f"D{i}" for i in range(1, 9)]
    assert [r[0] for r in ia.RELATIONS] == list(__import__("lcomfine.app.lineage", fromlist=["RELATIONS"]).RELATIONS)
    assert set(ia.CHANNEL_NOTES) == set(nav.CHANNELS) and len(ia.PEOPLE) == 4 and len(ia.OPEN_ITEMS) == 7


def test_menu_process_and_store_tables_come_from_contracts():
    """메뉴 ↔ 프로세스는 기능 계약의 프로세스 열에서, 저장소 ↔ 테이블은 db-schema 에서 — 둘 다 설계도의 쓰기 경계와 맞는다."""
    assert ia.processes_of_menu("BAS") == ["P1"] and ia.processes_of_menu("MAT") == ["P3", "P5"]
    assert ia.processes_of_menu("SYS") == ["공통"] and ia.processes_of_menu("SAL") == ["확장"]
    assert ia.processes_of_menu("TRC") == ["P9"] and ia.processes_of_menu("STA") == ["P10"]
    for p in ia.PROCESSES:                                   # 모든 프로세스에 대메뉴가 하나 이상 붙는다
        assert ia.menus_of_process(p.code, nav.MENUS), p.code
    stores = {s["code"]: s for s in ia.stores()}
    assert sum(len(s["tables"]) for c, s in stores.items() if c != "EXT") == 30
    assert [t.name for t in stores["D6"]["tables"]] == ["roll", "roll_genealogy"]
    for p in ia.PROCESSES:                                   # 쓰는 저장소 표기는 설계도 표와 같다
        for d in p.writes:
            assert p.code in stores[d]["writers"], (p.code, d)
    assert stores["EXT"]["writers"] == [] and [t.name for t in stores["EXT"]["tables"]] == ["sales_order"]
    steps = ia.process_steps([it["menu"] for it in nav.sidebar_items() if it["kind"] == "menu"])   # 좌측 메뉴 순서로 넘긴다
    assert [s["code"] for s in steps] == ["확장"] + [p.code for p in ia.PROCESSES]
    assert [m.code for m in steps[0]["menus"]] == ["SAL"] and [m.code for m in steps[5]["menus"]] == ["MAT", "POP"]   # P5 = 자재 투입 + POP
    assert [m.code for m in steps[1]["menus"]] == ["BAS", "PRT"] and [m.code for m in steps[10]["menus"]] == ["STA"]


def test_main_page_is_the_ia_screen():
    """관리자 메인 — 여섯 단(흐름 · 메뉴 · 데이터 · 계보 · 사용자 · 확인 필요)이 다 있고 수가 계약 · DB 와 맞는다."""
    html = client("admin").get("/").text
    for anchor in ("ia-flow", "ia-menus", "ia-data", "ia-lineage", "ia-users", "ia-open"):
        assert f'id="{anchor}"' in html, anchor
    assert re.findall(r'data-process="([^"]+)"', html) == ["확장"] + [p.code for p in ia.PROCESSES]
    for p in ia.PROCESSES:
        assert p.name in html and p.actor in html and p.inputs in html and p.outputs in html, p.code
    assert re.findall(r'data-store="([^"]+)"', html) == [c for c, _ in ia.STORES]
    for t in contracts.db_tables().values():                 # 테이블 31(설계도 30 + EXT 1)이 전부 보인다
        assert f"<code>{t.name}</code>" in html, t.name
    for rel, *_ in ia.RELATIONS:
        assert f"<code>{rel}</code>" in html, rel
    for kind in numbering.KINDS:                             # 채번 7종 — DB 의 형식 행으로 만든 모양
        row = numbering.rule(kind)
        assert f"<code>{row['prefix']}{row['date_format']}{'0' * (row['seq_digits'] - 1)}1</code>" in html, kind
    for r in rbac.roles():
        assert f"<b>{r.name}</b>" in html, r.code
    for person in ia.PEOPLE:
        assert person.name in html and person.gives in html and person.gets in html
    for c in nav.CHANNELS:
        assert f"<b>{c}</b> — {ia.CHANNEL_NOTES[c]}" in html, c
    for name, ask, now in ia.OPEN_ITEMS:
        assert name in html and ask in html and now in html, name
    assert ia.DONE_CRITERION in html and ia.SCOPE_OUT in html and ia.PROCESS_RULE in html
    # 카드의 중메뉴 줄에 계약의 기능명이 붙는다
    for f in contracts.functions_of("JOB-01"):
        assert f.name in html, f.id
    assert "F-SYS-" not in html.split('id="ia-flow"')[1].split('id="ia-menus"')[0]   # 흐름 띠는 기능 ID 가 아니라 이름으로 말한다


def test_flow_links_follow_the_permission_table():
    """현장 역할 — 흐름 띠는 P1~P10 이 전부 보이되, 열 수 없는 대메뉴(기준정보 관리 · LOT 추적 · 시스템 관리)는 링크가 아니다."""
    html = client("field").get("/").text
    assert re.findall(r'data-process="([^"]+)"', html) == ["확장"] + [p.code for p in ia.PROCESSES]
    flow = html.split('id="ia-flow"')[1].split('id="ia-menus"')[0]
    for m in nav.MENUS + nav.EXT_MENUS:
        linked = f'href="{m.screens[0].path}">{m.name}</a>' in flow
        assert linked == rbac.cell("FIELD", m.code).can_read, m.code
    assert "이 역할이 열 수 있는 메뉴 없음" in flow                 # P9 LOT 추적 — 현장은 없음
    # 역할 표에는 역할 4 가 다 나오고 (나) 표시는 하나
    assert html.count("(나)") == 1 and html.count('class="row-me"') == 1
