"""조색 기록 (CLR · 기능 5) — 등록 · 배합비 · 수정 · 삭제 · 조회. 화면이 부르는 엔드포인트로 검증한다.

권한: 품질·현장 = 입력 · 관리자·생산 = 조회 (설계도 §6). 색상값은 L·a·b (가설 컬럼 D-18).
"""
import pytest

from lcomfine.app import nav

from test_dev2_helpers import World, change_logs, client, count, err, ok, one

REC = nav.path_of("CLR-01")


@pytest.fixture(scope="module")
def w():
    world = World()
    try:
        yield world
    finally:
        world.cleanup()
        assert world.leftovers() == 0


def _new(w, who="qc", **data) -> dict:
    return ok(client(who).post(REC, data={"job_no": w.job_no, "color_name": "색 A (예시)", **data}))


def _mix(record_id: int) -> list[tuple[str, float]]:
    from lcomfine.db import conn
    return [(r["component_name"], float(r["ratio_pct"])) for r in conn.q(
        "select component_name, ratio_pct from color_record_mix where color_record_id = %s order by seq_no", (record_id,))]


@pytest.mark.fn("F-CLR-01")
def test_create_color_record_with_next_sequence(w):
    first = _new(w, color_l="52.31", color_a="-3.2", color_b="14", ink_code=w.ink_code, note="1차 (예시)")
    row = one("select * from color_record where color_record_id = %s", (first["id"],))
    assert row["job_id"] == w.job_id and row["seq_no"] == 1 and first["seq_no"] == 1
    assert (float(row["color_l"]), float(row["color_a"]), float(row["color_b"])) == (52.31, -3.2, 14.0)
    assert row["ink_formula_id"] == w.ink_id and row["recorded_by"] == "qc"
    assert change_logs("F-CLR-01", f"color_record:{w.job_no}/색 A (예시)/1") == 1
    assert _new(w, who="field")["seq_no"] == 2                                   # 재조색 — 차수를 비우면 다음 차수
    assert _new(w, seq_no="7")["seq_no"] == 7                                    # 차수를 주면 그 차수
    assert _new(w, color_name="색 B (예시)")["seq_no"] == 1                      # 색마다 따로 센다
    assert one("select color_l from color_record where color_record_id = %s", (_new(w, color_name="색 C (예시)")["id"],))["color_l"] is None


@pytest.mark.fn("F-CLR-01")
def test_create_validation_is_422(w):
    c = client("qc")
    assert err(c.post(REC, data={"job_no": "J000000-000", "color_name": "x"}))["message"] == "없는 Job 번호입니다"   # 없는 Job 422
    assert err(c.post(REC, data={"color_name": "x"}))["fields"][0]["name"] == "Job 번호"
    assert err(c.post(REC, data={"job_no": w.job_no}))["fields"][0]["name"] == "색 이름"
    assert err(c.post(REC, data={"job_no": w.job_no, "color_name": "x", "color_l": "밝음"}))["fields"][0]["name"] == "색상값 L"
    assert err(c.post(REC, data={"job_no": w.job_no, "color_name": "x", "seq_no": "0"}))["fields"][0]["name"] == "차수"
    assert err(c.post(REC, data={"job_no": w.job_no, "color_name": "x", "ink_code": "없는잉크"}))["fields"][0]["name"] == "기준 잉크조성"
    made = _new(w, color_name="중복 (예시)", seq_no="3")
    assert made["seq_no"] == 3
    assert "이미 있는 차수" in err(c.post(REC, data={"job_no": w.job_no, "color_name": "중복 (예시)", "seq_no": "3"}))["message"]


@pytest.mark.fn("F-CLR-02")
def test_mix_is_replaced_as_a_whole_and_must_sum_to_100(w):
    c = client("field")
    rid = _new(w, color_name="배합 (예시)")["id"]
    body = ok(c.post(f"{REC}/{rid}/mix", data={"component_name": ["성분 1 (예시)", "성분 2 (예시)", ""],
                                               "ratio_pct": ["60", "40", ""]}))      # 화면의 빈 행은 건너뛴다
    assert body["rows"] == 2 and _mix(rid) == [("성분 1 (예시)", 60.0), ("성분 2 (예시)", 40.0)]
    assert change_logs("F-CLR-02", f"color_record:{w.job_no}/배합 (예시)/1") == 1
    ok(c.post(f"{REC}/{rid}/mix", data={"component_name": ["가", "나", "다"], "ratio_pct": ["33.3", "33.3", "33.4"]}))
    assert _mix(rid) == [("가", 33.3), ("나", 33.3), ("다", 33.4)]                 # 통째로 바뀐다
    for names, ratios, name in ((["가", "나"], ["60", "30"], "배합비 합"),            # 합 90
                                (["가", "나"], ["60", "50"], "배합비 합"),            # 합 110
                                ([], [], "배합비 합"),                                # 빈 배합
                                (["가", ""], ["50", "50"], "2행 성분"),
                                (["가", "나"], ["100", "0"], "2행 비율"),
                                (["가"], ["백"], "1행 비율")):
        assert err(c.post(f"{REC}/{rid}/mix", data={"component_name": names, "ratio_pct": ratios}))["fields"][0]["name"] == name
    assert _mix(rid) == [("가", 33.3), ("나", 33.3), ("다", 33.4)]                 # 실패하면 그대로
    err(c.post(f"{REC}/999999999/mix", data={"component_name": ["가"], "ratio_pct": ["100"]}), 404)


@pytest.mark.fn("F-CLR-03")
def test_update_color_values_but_not_job(w):
    c = client("qc")
    rid = _new(w, color_name="수정 전 (예시)", color_l="10")["id"]
    ok(c.post(f"{REC}/{rid}", data={"color_name": "수정 후 (예시)", "color_l": "11.5", "color_a": "1", "color_b": "2",
                                    "note": "보정 (예시)", "job_no": "J000000-000"}))    # Job 은 받지 않는다 (못 바꾼다)
    row = one("select * from color_record where color_record_id = %s", (rid,))
    assert row["color_name"] == "수정 후 (예시)" and float(row["color_l"]) == 11.5 and row["note"] == "보정 (예시)"
    assert row["job_id"] == w.job_id and row["seq_no"] == 1 and row["updated_by"] == "qc" and row["updated_at"] is not None
    assert change_logs("F-CLR-03", f"color_record:{w.job_no}/수정 전 (예시)/1") == 1
    assert err(c.post(f"{REC}/{rid}", data={"color_l": "1"}))["fields"][0]["name"] == "색 이름"
    other = _new(w, color_name="다른 색 (예시)")["id"]
    assert "같은 차수" in err(c.post(f"{REC}/{other}", data={"color_name": "수정 후 (예시)"}))["message"]
    err(c.post(f"{REC}/999999999", data={"color_name": "x"}), 404)
    err(c.post(f"{REC}/abc", data={"color_name": "x"}), 404)


@pytest.mark.fn("F-CLR-04")
def test_delete_removes_record_and_mix(w):
    c = client("field")
    rid = _new(w, color_name="삭제 (예시)")["id"]
    ok(c.post(f"{REC}/{rid}/mix", data={"component_name": ["가"], "ratio_pct": ["100"]}))
    ok(c.post(f"{REC}/{rid}/delete"))
    assert count("select count(*) as n from color_record where color_record_id = %s", (rid,)) == 0
    assert count("select count(*) as n from color_record_mix where color_record_id = %s", (rid,)) == 0
    assert change_logs("F-CLR-04", f"color_record:{w.job_no}/삭제 (예시)/1") == 1
    err(c.post(f"{REC}/{rid}/delete"), 404)


@pytest.mark.fn("F-CLR-05")
def test_list_by_job_in_sequence_order_with_mix(w):
    job_id, job_no = w.new_job("CLR")
    c = client("qc")
    assert "미수집" in c.get(REC, params={"job_no": job_no}).text                   # 0건이면 미수집
    ids = [ok(c.post(REC, data={"job_no": job_no, "color_name": "조회 색 (예시)", "color_l": str(50 + n)}))["id"] for n in range(3)]
    ok(c.post(f"{REC}/{ids[1]}/mix", data={"component_name": ["조회 성분 (예시)"], "ratio_pct": ["100"]}))
    r = client("admin").get(REC, params={"job_no": job_no})                         # 관리자 = 조회
    assert r.status_code == 200 and r.text.count("조회 색 (예시)") >= 3
    assert r.text.index("50.00") < r.text.index("51.00") < r.text.index("52.00")    # 차수 순
    assert "조회 성분 (예시) 100.000%" in r.text
    assert "조회 색 (예시)" not in client("admin").get(REC, params={"job_no": w.job_no, "date_to": "2000-01-01"}).text
    r = c.get(REC, params={"job_no": job_no, "edit": ids[1]})                       # 한 건을 열면 수정·배합비 칸
    assert f'action="{REC}/{ids[1]}/mix"' in r.text and 'value="조회 성분 (예시)"' in r.text
    err(c.get(REC, params={"edit": "999999999"}), 404)
    assert "없는 Job 번호입니다" in c.get(REC, params={"job_no": "J000000-000"}).text


@pytest.mark.parametrize("who", ["admin", "prod"])
def test_read_only_roles_cannot_write(w, who):
    """관리자·생산 × 조색 기록 = 조회 → 쓰기 403."""
    rid = _new(w, color_name=f"권한 {who} (예시)")["id"]
    c = client(who)
    err(c.post(REC, data={"job_no": w.job_no, "color_name": "x"}), 403)
    err(c.post(f"{REC}/{rid}", data={"color_name": "x"}), 403)
    err(c.post(f"{REC}/{rid}/mix", data={"component_name": ["가"], "ratio_pct": ["100"]}), 403)
    err(c.post(f"{REC}/{rid}/delete"), 403)
    assert one("select color_name from color_record where color_record_id = %s", (rid,))["color_name"] == f"권한 {who} (예시)"
    assert c.get(REC).status_code == 200


def test_anonymous_is_401():
    err(client().post(REC, data={}), 401)
    err(client().post(f"{REC}/1/delete"), 401)
