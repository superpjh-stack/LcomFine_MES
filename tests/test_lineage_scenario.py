"""G-06 · G-07 — 설계도 §3 계보 예시를 **화면이 부르는 것과 같은 엔드포인트**로 만들고 양방향으로 추적한다.

    원재료 LOT ①② → 인쇄 Roll ①②(같은 Job · LOT①은 두 롤에, LOT②는 Roll②에만) → 후가공 Roll(splice 2:1)
    → 슬리팅 Roll ①②③(1:3) → 출하 LOT(슬리팅 ①② 출하, ③ 재고)

    `roll_genealogy` **정확히 10행** = 투입 3 + splice 2 + 슬리팅 3 + 출하 2  (설계도 그림의 화살표 10개)

조작 순서 = 화면 순서 (contracts/db-schema.md §3.2):
    입고 2(F-MAT-01) → 입고검사 합격 2(F-MAT-03) → 작업 시작(F-POP-01) → 투입 스캔(F-MAT-07) → 작업 종료(F-POP-02) ×2
    → splice(F-RLL-02) → 슬리팅(F-RLL-04) → 출하 등록 · 롤 스캔 2

전제 데이터(품목·고객·설비·Job)는 개발1 의 화면이 만드는 것이라 `World` 가 SQL 로 넣는다(test_dev2_helpers.py).

※ **출하 2행** — 출하 엔드포인트는 개발3 소유다(F-SHP-01 `POST /shp/shipments` · F-SHP-02 `POST /shp/shipments/{shipment_no}/rolls`).
  아래 `_ship()` 은 **그 API 를 부른다**(개발3 의 `routers/shp.py` 가 등록된 뒤에 함수 직접 호출에서 API 호출로 바꿨다).
  그래서 예시의 10행은 전부 화면이 부르는 엔드포인트로 만들어진다. 개발3 이 폼 필드 이름(`job_no` · `ship_date` · `roll_no`)을
  바꾸면 고칠 곳은 `_ship()` 한 곳이다. 임의 계보 테스트(G-07)는 추적이 대상이라 출하 화살표를 `lineage.ship_roll` 로 직접 만든다.

테스트가 만든 행은 전부 지운다 — 픽스처·테스트의 `finally` 가 `World.cleanup()` 을 부르고 남은 행이 0 인지 확인한다.
"""
import random
from collections import deque
from datetime import date

import pytest

from lcomfine.app import lineage, nav
from lcomfine.db import conn

from test_dev2_helpers import (TEST_BY, World, client, finish, inspect, ok, receive, scan_input, slit, splice, start)


def _ship(w: World, roll_nos: list[str]) -> tuple[int, str]:
    """출하 등록(F-SHP-01) + 롤 스캔(F-SHP-02) — 개발3 의 API 를 화면과 같은 폼 필드로 부른다."""
    c = client("field")
    path = nav.path_of("SHP-01")
    shipment_no = ok(c.post(path, data={"job_no": w.job_no, "ship_date": date.today().isoformat()}), "출하 등록")["shipment_no"]
    for roll_no in roll_nos:
        ok(c.post(f"{path}/{shipment_no}/rolls", data={"roll_no": roll_no}), "출하 롤 스캔")
    return conn.q1("select shipment_id from shipment where shipment_no = %s", (shipment_no,))["shipment_id"], shipment_no


# ── 설계도 §3 예시 ──────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def example():
    w = World()
    try:
        lot1, lot2 = receive(w), receive(w)                               # 입고 2
        inspect(lot1, "합격")                                             # 입고검사 합격 2 (품질)
        inspect(lot2, "합격")
        work1 = start(w)                                                  # 인쇄 Roll ① — LOT ①
        scan_input(work1, lot1)
        p1 = finish(work1)
        work2 = start(w)                                                  # 인쇄 Roll ② — LOT ① · ②
        scan_input(work2, lot1)
        scan_input(work2, lot2)
        p2 = finish(work2)
        f = splice([p1, p2])                                              # 후가공 Roll — splice 2:1
        s1, s2, s3 = slit(f, 3)                                           # 슬리팅 Roll ①②③ — 1:3
        shipment_id, shipment_no = _ship(w, [s1, s2])                     # 출하 LOT — 슬리팅 ①② (③ 은 재고)
        yield {"w": w, "lots": [lot1, lot2], "p": [p1, p2], "f": f, "s": [s1, s2, s3],
               "shipment_id": shipment_id, "shipment_no": shipment_no}
    finally:
        w.cleanup()
        assert w.leftovers() == 0


@pytest.mark.fn("F-MAT-01", "F-MAT-03", "F-POP-01", "F-MAT-07", "F-POP-02", "F-RLL-02", "F-RLL-04")
def test_g06_example_is_exactly_10_rows(example):
    """G-06 — `roll_genealogy` 정확히 10행: 투입 3 + splice 2 + 슬리팅 3 + 출하 2."""
    e = example
    rows = e["w"].genealogy()
    by_relation: dict[str, int] = {}
    for r in rows:
        by_relation[r["relation"]] = by_relation.get(r["relation"], 0) + 1
    assert by_relation == {"투입": 3, "splice": 2, "슬리팅": 3, "출하": 2}
    assert len(rows) == 10
    (lot1, lot2), (p1, p2), f, (s1, s2, s3), ship = e["lots"], e["p"], e["f"], e["s"], e["shipment_no"]
    assert {(r["parent_no"], r["child_no"], r["relation"]) for r in rows} == {
        (lot1, p1, "투입"), (lot1, p2, "투입"), (lot2, p2, "투입"),
        (p1, f, "splice"), (p2, f, "splice"),
        (f, s1, "슬리팅"), (f, s2, "슬리팅"), (f, s3, "슬리팅"),
        (s1, ship, "출하"), (s2, ship, "출하"),
    }


def test_g06_rolls_and_states(example):
    """롤 6개(인쇄 2 · 후가공 1 · 슬리팅 3) — 상태는 저장하지 않고 계보에서 나온다: ③ 만 재고."""
    e = example
    rolls = {r["roll_no"]: r for r in conn.q(
        "select roll_no, process_type, state from v_roll_state where job_id = %s", (e["w"].job_id,))}
    assert len(rolls) == 6
    assert [rolls[n]["process_type"] for n in e["p"] + [e["f"]] + e["s"]] == ["인쇄", "인쇄", "후가공", "슬리팅", "슬리팅", "슬리팅"]
    assert {n: rolls[n]["state"] for n in rolls} == {
        e["p"][0]: "소진", e["p"][1]: "소진", e["f"]: "소진", e["s"][0]: "출하", e["s"][1]: "출하", e["s"][2]: "재고"}
    # 번호는 채번 한 곳에서 나온다 — 여섯 롤 번호가 서로 다르고 전부 스캔으로 찾힌다
    assert all(lineage.resolve(n).kind == lineage.ROLL for n in rolls)


def test_g07_backward_reaches_both_material_lots(example):
    """G-07 역방향 — 출하 LOT → 원재료 LOT ①·② 둘 다."""
    e = example
    node = lineage.resolve(e["shipment_no"])
    assert node is not None and node.kind == lineage.SHIPMENT and node.id == e["shipment_id"]
    t = lineage.trace_backward(node.ref)
    assert t.direction == "backward" and t.start.no == e["shipment_no"]
    assert {n.no for n in t.material_lots()} == set(e["lots"])
    assert len(t.edges) == 9                                              # 10행 중 재고 ③ 으로 가는 슬리팅 한 줄만 빠진다
    assert len({x.genealogy_id for x in t.edges}) == 9                    # 화살표 중복 없음
    assert e["s"][2] not in {n.no for n in t.nodes()}
    assert [x.depth for x in t.edges] == sorted(x.depth for x in t.edges)  # 가까운 순서
    assert {x.relation for x in t.edges if x.depth == 1} == {"출하"} and max(x.depth for x in t.edges) == 4
    # 롤에서 시작해도 된다 — 재고로 남은 슬리팅 ③ 도 두 LOT 에 닿는다
    t3 = lineage.trace_backward(lineage.resolve(e["s"][2]).ref)
    assert {n.no for n in t3.material_lots()} == set(e["lots"]) and len(t3.edges) == 6


def test_g07_forward_reaches_shipment_and_leaves_stock(example):
    """G-07 정방향 — 원재료 LOT ① → 인쇄 ①② → 후가공 → 슬리팅 ①②③ → 출하 LOT, ③ 은 '재고'."""
    e = example
    node = lineage.resolve(e["lots"][0])
    assert node is not None and node.kind == lineage.MATERIAL_LOT
    t = lineage.trace_forward(node.ref)
    assert {n.no for n in t.rolls()} == set(e["p"] + [e["f"]] + e["s"])
    assert [n.no for n in t.shipments()] == [e["shipment_no"]]
    assert [n.no for n in t.stock_rolls()] == [e["s"][2]] and t.stock_rolls()[0].state == "재고"
    assert len(t.edges) == 9                                              # LOT ② 의 투입 한 줄만 빠진다
    assert e["lots"][1] not in {n.no for n in t.nodes()}
    by_depth: dict[int, set] = {}
    for x in t.edges:
        by_depth.setdefault(x.depth, set()).add(x.relation)
    assert by_depth == {1: {"투입"}, 2: {"splice"}, 3: {"슬리팅"}, 4: {"출하"}}
    # LOT ② 에서 시작하면 인쇄 ① 은 지나가지 않는다
    t2 = lineage.trace_forward(lineage.resolve(e["lots"][1]).ref)
    assert e["p"][0] not in {n.no for n in t2.nodes()} and e["p"][1] in {n.no for n in t2.nodes()}
    assert [n.no for n in t2.shipments()] == [e["shipment_no"]]


@pytest.mark.fn("F-RLL-06")
def test_scanned_roll_opens_history_with_one_step(example):
    """롤 이력 화면(F-RLL-06) — 후가공 롤을 스캔하면 부모 2(splice) · 자식 3(슬리팅)이 한 단계씩 보인다."""
    e = example
    r = client("field").get(nav.path_of("RLL-03"), params={"no": e["f"]})
    assert r.status_code == 200
    assert all(n in r.text for n in e["p"] + e["s"])
    assert {x.parent.no for x in lineage.parents_of(lineage.resolve(e["f"]).ref)} == set(e["p"])
    assert {x.child.no for x in lineage.children_of(lineage.resolve(e["f"]).ref)} == set(e["s"])


def test_g07_consumed_and_shipped_rolls_cannot_be_reused(example):
    """이미 소진·출하된 롤은 재사용 불가(422) — 화면이 부르는 엔드포인트로 확인한다. 계보는 10행 그대로."""
    e = example
    c = client("field")
    for roll_no, word in ((e["f"], "소진"), (e["p"][0], "소진"), (e["s"][0], "출하")):
        for path, data in ((nav.path_of("RLL-02"), {"roll_no": roll_no, "count": "2"}),
                           (nav.path_of("RLL-01"), {"roll_no": roll_no})):
            r = c.post(path, data=data)
            assert r.status_code == 422 and r.json()["code"] == "validation_error", (roll_no, path, r.text)
            assert word in r.json()["message"] + str(r.json()["fields"]), r.text
    r = c.post(nav.path_of("RLL-01") + "/splice", data={"roll_no": [e["s"][2], e["s"][0]]})   # 재고 ③ + 출하된 ①
    assert r.status_code == 422
    r = c.post(f"{nav.path_of('SHP-01')}/{e['shipment_no']}/rolls", data={"roll_no": e["s"][0]})   # 이미 출하된 롤 재출하 (개발3 API → lineage.ship_roll)
    assert r.status_code == 422 and "이미 출하된 롤" in r.json()["message"], r.text
    r = c.post(f"{nav.path_of('SHP-01')}/{e['shipment_no']}/rolls", data={"roll_no": e["f"]})      # 소진된 롤 출하
    assert r.status_code == 422 and "소진" in r.json()["message"], r.text
    assert len(e["w"].genealogy()) == 10
    assert lineage.roll_state(e["w"].roll_id(e["s"][2])) == "재고"       # ③ 은 여전히 재고 (splice 가 통째로 롤백됐다)


# ── G-07: 분기 5단 이상 임의 계보 ───────────────────────────────────────
def _reach(adj: dict, start) -> dict:
    """출발점에서 화살표를 따라 닿는 노드 → 최단 거리(화살표 수). 추적 모듈과 무관한 넓이 우선 탐색."""
    dist, queue = {start: 0}, deque([start])
    while queue:
        cur = queue.popleft()
        for nxt in adj.get(cur, ()):
            if nxt not in dist:
                dist[nxt] = dist[cur] + 1
                queue.append(nxt)
    return dist


@pytest.mark.parametrize("seed", [11, 23, 47])
def test_g07_random_branching_genealogy_at_least_5_levels(seed):
    """임의 계보(슬리팅 1:N · splice N:1 · 후가공 1:1 을 섞어 6단 이상)에서 양방향 추적이 넓이 우선 탐색과 같은가.

    깊이·분기 수를 가정하지 않는다는 것의 확인이다. 인쇄 롤은 API 로, 그 아래 단은 `lineage` 쓰기 함수로 만든다.
    """
    rnd = random.Random(seed)
    w = World()
    try:
        lots = [w.good_lot() for _ in range(3)]
        edges: set[tuple[str, str]] = set()          # (부모 번호, 자식 번호) — 테스트가 따로 적어 두는 정답
        depth: dict[str, int] = {}                   # 롤 번호 → 원재료 LOT 에서 몇 단째인가 (가장 긴 길)
        stock: list[str] = []
        for _ in range(3):                           # 1단: 인쇄 롤 3개, 저마다 LOT 1~3개 투입
            used = rnd.sample(lots, rnd.randint(1, 3))
            roll_no = w.print_roll(used)
            edges.update((lot, roll_no) for lot in used)
            depth[roll_no] = 1
            stock.append(roll_no)

        def make(parents: list[str], kind: str, n: int = 1) -> list[str]:
            with conn.tx() as cur:
                if kind == "slit":
                    made = lineage.slit_roll(cur, parent_roll_id=w.roll_id(parents[0]), count=n, by=TEST_BY)
                else:
                    made = [lineage.make_finishing_roll(cur, parent_roll_ids=[w.roll_id(p) for p in parents], by=TEST_BY)]
            out = [m["roll_no"] for m in made]
            for p in parents:
                stock.remove(p)
                edges.update((p, c) for c in out)
            for c in out:
                depth[c] = max(depth[p] for p in parents) + 1
                stock.append(c)
            return out

        for level in range(6):                       # 2~7단: 매 단마다 가장 깊은 롤은 반드시 이어 간다
            deepest = max(stock, key=lambda r: depth[r])
            make([deepest], "slit", rnd.randint(2, 3)) if level % 2 == 0 else make([deepest], "finish")
            for _ in range(rnd.randint(1, 2)):       # 거기에 임의의 분기·합류를 더한다
                op = rnd.choice(["slit", "splice", "finish"])
                if op == "splice" and len(stock) >= 2:
                    make(rnd.sample(stock, rnd.randint(2, min(3, len(stock)))), "splice")
                elif op == "slit":
                    make([rnd.choice(stock)], "slit", rnd.randint(2, 4))
                else:
                    make([rnd.choice(stock)], "finish")
        assert max(depth.values()) >= 6, "계보가 5단 이상으로 깊어지지 않았다"

        shipment_id, shipment_no = w.new_shipment("RND")
        shipped = rnd.sample(stock, max(1, len(stock) // 2))
        for roll_no in shipped:
            with conn.tx() as cur:
                lineage.ship_roll(cur, shipment_id=shipment_id, roll_id=w.roll_id(roll_no), by=TEST_BY)
            edges.add((roll_no, shipment_no))
            stock.remove(roll_no)

        assert len(w.genealogy()) == len(edges)       # 화살표 하나 = 한 줄, 더도 덜도 없다
        down: dict[str, set] = {}
        up: dict[str, set] = {}
        for p, c in edges:
            down.setdefault(p, set()).add(c)
            up.setdefault(c, set()).add(p)

        def check(start_no: str, adj: dict, trace: lineage.Trace) -> dict:
            want = _reach(adj, start_no)
            assert {n.no for n in trace.nodes()} == set(want), f"seed {seed} · {start_no}"
            want_edges = {(p, c) for p, c in edges if p in want and c in want}
            got_edges = {(x.parent.no, x.child.no) for x in trace.edges}
            assert got_edges == want_edges and len(trace.edges) == len(want_edges)
            for x in trace.edges:                     # depth = 출발점에서 그 화살표까지의 최단 거리
                near = x.parent.no if adj is down else x.child.no
                assert x.depth == want[near] + 1
            return want

        for lot in lots:                              # 정방향: 원재료 LOT → 출하 LOT · 재고 롤
            t = lineage.trace_forward(lineage.resolve(lot).ref)
            want = check(lot, down, t)
            assert {n.no for n in t.shipments()} == ({shipment_no} & set(want))
            assert {n.no for n in t.stock_rolls()} == {r for r in stock if r in want}
        t = lineage.trace_backward(lineage.resolve(shipment_no).ref)   # 역방향: 출하 LOT → 원재료 LOT
        want = check(shipment_no, up, t)
        assert {n.no for n in t.material_lots()} == {lot for lot in lots if lot in want}
        assert t.material_lots(), "출하 LOT 에서 원재료 LOT 에 닿지 못했다"
        for roll_no in rnd.sample(sorted(depth), 5):  # 가운데 롤에서 시작해도 양쪽 다 맞는다
            ref = lineage.resolve(roll_no).ref
            check(roll_no, down, lineage.trace_forward(ref))
            check(roll_no, up, lineage.trace_backward(ref))
    finally:
        w.cleanup()
        assert w.leftovers() == 0
