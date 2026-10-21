# tests/test_dev2_prd.py — PRD 생산일보 · INS 검사일보 (등록 · 수정 · 조회 · 출력 · 현황 · 로스율 미확정 D-519)
import pytest

from lcomfine.db import conn
from tests.test_dev2_world import pr, sh, sl, world  # noqa: F401 — 픽스처

H = {"accept": "text/html"}


@pytest.mark.fn("F-PRD-011")
def test_daily_register_unique_per_wo_date_equipment(world, pr, sl):
    did = world.daily(pr, 40)
    row = conn.q1("select work_order_id, equipment_code, good_qty, loss_qty from production_daily where id = %s", (did,))
    assert row["work_order_id"] == world.wo and row["equipment_code"] == "EQ01" and int(row["good_qty"]) == 40
    r = pr.post("/prd/daily", data={"work_order_id": str(world.wo), "work_date": "2026-10-20", "equipment_code": "EQ01",
                                    "produced_qty": "1", "good_qty": "1"})
    assert r.status_code == 422 and "이미 있습니다" in r.json()["message"]
    world.daily(pr, 10, eq="EQ02")                                  # 설비가 다르면 다른 행
    bad = {"work_order_id": str(world.wo), "work_date": "2026-10-21", "produced_qty": "1", "good_qty": "1"}
    assert pr.post("/prd/daily", data={**bad, "equipment_code": "EQ-없음"}).status_code == 422
    assert pr.post("/prd/daily", data={**bad, "equipment_code": "EQ01", "work_date": ""}).status_code == 422
    assert pr.post("/prd/daily", data={**bad, "equipment_code": "EQ01", "good_qty": "x"}).status_code == 422
    assert sl.post("/prd/daily", data={**bad, "equipment_code": "EQ01"}).status_code == 403


@pytest.mark.fn("F-PRD-012")
def test_daily_update(world, pr):
    did = world.daily(pr, 40)
    assert pr.post(f"/prd/daily/{did}", data={"good_qty": "42", "run_minutes": "300"}).status_code == 200
    row = conn.q1("select good_qty, run_minutes, work_date from production_daily where id = %s", (did,))
    assert int(row["good_qty"]) == 42 and row["run_minutes"] == 300 and str(row["work_date"]) == "2026-10-20"
    assert pr.post(f"/prd/daily/{did}", data={}).status_code == 422
    assert pr.post("/prd/daily/999999999", data={"good_qty": "1"}).status_code == 404


@pytest.mark.fn("F-PRD-013")
def test_daily_list(world, pr):
    world.daily(pr, 33)
    r = pr.get("/prd/daily", params={"date": "2026-10-20", "wo": world.wo_no}, headers=H)
    assert r.status_code == 200 and world.wo_no in r.text


@pytest.mark.fn("F-PRD-021")
def test_daily_print(world, pr):
    world.daily(pr, 33)
    r = pr.get("/prd/daily/print", params={"date": "2026-10-20"}, headers=H)
    assert r.status_code == 200 and "생산일보" in r.text and world.wo_no in r.text and "print-sheet" in r.text
    assert pr.get("/prd/daily/print", params={"date": "2026-02-31"}).status_code == 422


@pytest.mark.fn("F-PRD-031")
def test_status(world, pr):
    world.daily(pr, 33)
    world.daily(pr, 7, day="2026-10-21")
    r = pr.get("/prd/status", params={"from": "2026-10-20", "to": "2026-10-21", "item": world.p + "FG"}, headers=H)
    assert r.status_code == 200 and r.text.count(world.wo_no) == 2 and "양품 합" in r.text


@pytest.mark.fn("F-PRD-041")
def test_loss_rate_is_undecided_with_raw_qty(world, pr):
    world.daily(pr, 33)
    r = pr.get("/prd/loss-rate", params={"wo": world.wo_no}, headers=H)
    assert r.status_code == 200 and "미확정 (D-519)" in r.text and world.wo_no in r.text and ">38<" in r.text  # 생산 = 33 + 5
    assert "%" not in r.text.split(world.wo_no, 1)[1].split("</tr>")[0]                                  # 비율을 지어내지 않는다


@pytest.mark.fn("F-INS-011")
def test_ins_daily_register(world, pr, sl):
    r = pr.post("/ins/daily", data={"work_order_id": str(world.wo), "work_date": "2026-10-20", "inspected_qty": "100",
                                    "defect_code": ["DF01", "DF02"], "defect_code_qty": ["3", "2"]})
    assert r.status_code == 200, r.text
    row = conn.q1("select defect_qty, defects from inspection_daily where id = %s", (r.json()["daily_id"],))
    assert int(row["defect_qty"]) == 5 and row["defects"] == {"DF01": "3", "DF02": "2"}
    base = {"work_order_id": str(world.wo), "work_date": "2026-10-20", "inspected_qty": "10"}
    assert pr.post("/ins/daily", data=base).status_code == 422                                  # 지시 × 일자 중복
    assert pr.post("/ins/daily", data={**base, "work_date": "2026-10-21", "defect_qty": "11"}).status_code == 422
    assert pr.post("/ins/daily", data={**base, "work_date": "2026-10-22", "defect_code": ["DFX"],
                                       "defect_code_qty": ["1"]}).status_code == 422
    assert sl.post("/ins/daily", data=base).status_code == 403


@pytest.mark.fn("F-INS-012")
def test_ins_daily_update(world, pr):
    did = pr.post("/ins/daily", data={"work_order_id": str(world.wo), "work_date": "2026-10-20", "inspected_qty": "100",
                                      "defect_qty": "4"}).json()["daily_id"]
    assert pr.post(f"/ins/daily/{did}", data={"inspected_qty": "120", "defect_qty": "6"}).status_code == 200
    row = conn.q1("select inspected_qty, defect_qty from inspection_daily where id = %s", (did,))
    assert (int(row["inspected_qty"]), int(row["defect_qty"])) == (120, 6)
    assert pr.post(f"/ins/daily/{did}", data={"inspected_qty": "5"}).status_code == 422          # 불량 > 검사
    assert pr.post("/ins/daily/999999999", data={"inspected_qty": "1"}).status_code == 404


def _ins(world, pr, day="2026-10-20"):
    pr.post("/ins/daily", data={"work_order_id": str(world.wo), "work_date": day, "inspected_qty": "100",
                                "defect_code": ["DF01"], "defect_code_qty": ["7"]})


@pytest.mark.fn("F-INS-013")
def test_ins_daily_list(world, pr):
    _ins(world, pr)
    r = pr.get("/ins/daily", params={"wo": world.wo_no}, headers=H)
    assert r.status_code == 200 and world.wo_no in r.text and "DF01 7" in r.text


@pytest.mark.fn("F-INS-021")
def test_ins_daily_print(world, pr):
    _ins(world, pr)
    r = pr.get("/ins/daily/print", params={"date": "2026-10-20"}, headers=H)
    assert r.status_code == 200 and "검사일보" in r.text and world.wo_no in r.text


@pytest.mark.fn("F-INS-031")
def test_ins_status(world, pr):
    _ins(world, pr)
    _ins(world, pr, "2026-10-21")
    r = pr.get("/ins/status", params={"from": "2026-10-20", "item": world.p + "FG"}, headers=H)
    assert r.status_code == 200 and r.text.count(world.wo_no) == 2


@pytest.mark.fn("F-INS-041")
def test_ins_loss_rate_is_undecided(world, pr):
    _ins(world, pr)
    r = pr.get("/ins/loss-rate", params={"wo": world.wo_no}, headers=H)
    assert r.status_code == 200 and "미확정 (D-519)" in r.text and world.wo_no in r.text
