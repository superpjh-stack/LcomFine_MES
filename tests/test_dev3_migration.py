"""이관 배치 6명령 (B-MIG-01~06 · G-15) — 임시 폴더의 `(예시)` CSV 로 돌리고, 적재한 행과 실행 기록은 지운다.

파일 규격은 `contracts/migration-files.md`(코드 쪽 원본 `lcomfine.migration.files.SPECS`).
코드 접두 `T3M-` · 실행자 `T3M-…` — 끝나면 그 접두의 행이 하나도 남지 않는다.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from lcomfine import migration
from lcomfine.app import contracts
from lcomfine.db import conn
from lcomfine.migration import files

from test_dev3_support import cleanup, count, leftovers, one

P = "T3M-"
ROOT = Path(__file__).resolve().parents[1]

CLEAN = {
    "item.csv": "item_code,item_name,item_type,spec,unit,use_yn\n"
                f"{P}P01,제품 A (예시),제품,,m,Y\n"
                f"{P}R01,원재료 필름 (예시),원재료,,m,\n",
    "customer.csv": "customer_code,customer_name,note,use_yn\n"
                    f"{P}C01,고객 A (예시),,Y\n",
    "process.csv": "process_code,process_name,process_type,sort_no,use_yn\n"
                   f"{P}PR1,인쇄 (예시),인쇄,1,Y\n"
                   f"{P}PR2,슬리팅 (예시),슬리팅,2,Y\n",
    "equipment.csv": "equipment_code,equipment_name,process_code,note,use_yn\n"
                     f"{P}EQ1,인쇄기 1호 (예시),{P}PR1,,Y\n",
    "defect_code.csv": "defect_code,defect_name,defect_group,use_yn\n"
                       f"{P}D01,불량 유형 A (예시),,Y\n",
    "plate_spec.csv": "plate_code,plate_name,item_code,color_count,spec_note,use_yn\n"
                      f"{P}PL1,판 A (예시),{P}P01,4,,Y\n",
    "anilox.csv": "anilox_code,anilox_name,line_count,cell_volume,note,use_yn\n"
                  f"{P}AN1,아니록스 A (예시),,,,Y\n",
    "ink_formula.csv": "ink_code,ink_name,color_name,target_l,target_a,target_b,note,use_yn\n"
                       f"{P}INK1,잉크 A (예시),색 A (예시),,,,,Y\n",
    "ink_formula_component.csv": "ink_code,seq_no,component_name,ratio_pct\n"
                                 f"{P}INK1,1,성분 가 (예시),60\n"
                                 f"{P}INK1,2,성분 나 (예시),40\n",
    "job.csv": "job_no,item_code,customer_code,plate_code,anilox_code,ink_code,equipment_code,order_qty,qty_unit,due_date,status,note\n"
               f"{P}J001,{P}P01,{P}C01,{P}PL1,{P}AN1,{P}INK1,{P}EQ1,1000,m,2001-03-15,,(예시)\n"
               f"{P}J002,{P}P01,{P}C01,,,,,500,m,2001-03-20,완료,(예시)\n",
    "job_lot.csv": "lot_no,job_no,planned_roll_count,planned_length_m,note\n"
                   f"{P}L001,{P}J001,2,1000,(예시)\n",
}

# 오류 행을 섞은 것 — 그 행만 건너뛰고 나머지는 적재되어야 한다
DIRTY = {
    **CLEAN,
    "item.csv": CLEAN["item.csv"] + f"{P}P02,,제품,,m,Y\n" + f"{P}P03,제품 C (예시),반제품,,m,Y\n",
    "equipment.csv": CLEAN["equipment.csv"] + f"{P}EQ2,인쇄기 2호 (예시),{P}NOPE,,Y\n",
    "ink_formula_component.csv": CLEAN["ink_formula_component.csv"] + f"{P}INK1,3,성분 다 (예시),150\n",
    "job.csv": CLEAN["job.csv"] + f"{P}J003,{P}NOITEM,{P}C01,,,,,100,m,2001-03-21,,(예시)\n"
                                + f"{P}J004,{P}P01,{P}C01,,,,,100,m,2001/03/22,,(예시)\n"
                                + f"{P}J005,{P}P01,{P}C01,,,,,300,m,2001-03-23,,(예시)\n",
    "job_lot.csv": CLEAN["job_lot.csv"] + f"{P}L002,{P}J003,1,,(예시)\n",
}

TABLE_KEYS = {"item": "item_code", "customer": "customer_code", "process": "process_code", "equipment": "equipment_code",
              "defect_code": "defect_code", "plate_spec": "plate_code", "anilox": "anilox_code", "ink_formula": "ink_code",
              "job": "job_no", "job_lot": "lot_no"}


def write(folder: Path, content: dict[str, str]) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for name, text in content.items():
        (folder / name).write_text(text, encoding="utf-8")
    return folder


def loaded() -> dict[str, int]:
    out = {t: count(f"select count(*) as n from {t} where {k} like %s", (P + "%",)) for t, k in TABLE_KEYS.items()}
    out["ink_formula_component"] = count(
        """select count(*) as n from ink_formula_component c join ink_formula f on f.ink_formula_id = c.ink_formula_id
            where f.ink_code like %s""", (P + "%",))
    return out


def logs(by: str) -> list[dict]:
    return conn.q("select * from sys_migration_log where run_by = %s order by migration_log_id", (by,))


@pytest.fixture()
def clean_db():
    cleanup(P)
    yield
    cleanup(P)
    assert leftovers(P) == {}


def test_commands_match_contract():
    """`COMMANDS` 의 키 = function-list.md 의 `cli <명령>` 6개 (check_trace 가 이 dict 를 읽는다)."""
    batch = contracts.batch_functions()
    assert [f.method for f in batch] == ["cli"] * 6
    assert set(migration.COMMANDS) == {f.path for f in batch}
    assert migration.FUNCTION_IDS == {f.path: f.id for f in batch}
    assert all(callable(fn) for fn in migration.COMMANDS.values())
    assert len(files.SPECS) == 16 and {s.command for s in files.SPECS} == set(migration.COMMANDS) - {"validate", "report"}


@pytest.mark.fn("B-MIG-01")
def test_validate_checks_without_loading(tmp_path, capsys, clean_db):
    before = one("select count(*) as n from sys_migration_log")["n"]
    assert migration.COMMANDS["validate"](write(tmp_path / "clean", CLEAN)) == 0
    assert "판정: PASS" in capsys.readouterr().out
    assert set(loaded().values()) == {0}                                   # 적재하지 않는다
    assert one("select count(*) as n from sys_migration_log")["n"] == before   # 실행 기록도 쓰지 않는다

    assert migration.COMMANDS["validate"](write(tmp_path / "dirty", DIRTY)) == 1
    out = capsys.readouterr().out
    assert "판정: FAIL" in out
    assert "item_name: 필수값이 비어 있다" in out                           # 필수값
    assert "item_type: 제품 | 원재료 중 하나여야 한다" in out               # 형식
    assert f"process_code: 없는 코드 '{P}NOPE'" in out                      # 코드 참조
    assert f"item_code: 없는 코드 '{P}NOITEM'" in out
    assert "due_date: 날짜는 YYYY-MM-DD" in out
    assert f"job_no: 없는 코드 '{P}J003'" in out                            # 오류로 빠진 Job 을 가리키는 생산 LOT
    assert set(loaded().values()) == {0}

    # 파일 유무 · 열 이름
    broken = write(tmp_path / "broken", {k: v for k, v in CLEAN.items() if k != "customer.csv"})
    (broken / "item.csv").write_text("item_code,item_name,품목구분\nX,Y,제품\n", encoding="utf-8")
    assert migration.COMMANDS["validate"](broken) == 1
    out = capsys.readouterr().out
    assert "customer.csv 파일: 파일 없음" in out
    assert "필수 열이 없다 — item_type" in out and "규격에 없는 열 — 품목구분" in out


@pytest.mark.fn("B-MIG-02")
def test_load_master_is_idempotent_upsert(tmp_path, capsys, clean_db):
    folder, by = write(tmp_path, CLEAN), P + "master"
    assert migration.COMMANDS["load-master"](folder, by=by) == 0
    first = loaded()
    assert (first["item"], first["customer"], first["process"], first["equipment"], first["defect_code"]) == (2, 1, 2, 1, 1)
    row = one("select * from item where item_code = %s", (P + "R01",))
    assert (row["item_name"], row["item_type"], row["use_yn"], row["created_by"]) == ("원재료 필름 (예시)", "원재료", "Y", "migration")
    eq = one("""select p.process_code from equipment e join process p on p.process_id = e.process_id
                 where e.equipment_code = %s""", (P + "EQ1",))
    assert eq["process_code"] == P + "PR1"                                  # 코드 참조가 내부 키로 이어진다

    # 값을 바꿔 다시 돌린다 — 행 수는 그대로, 값은 갱신
    (folder / "item.csv").write_text(CLEAN["item.csv"].replace("제품 A (예시)", "제품 A 개정 (예시)"), encoding="utf-8")
    assert migration.COMMANDS["load-master"](folder, by=by) == 0
    assert loaded() == first
    assert one("select item_name, updated_by from item where item_code = %s", (P + "P01",)) == \
        {"item_name": "제품 A 개정 (예시)", "updated_by": "migration"}

    got = logs(by)                                                          # 실행 × 파일마다 한 줄
    assert len(got) == 10 and {g["command"] for g in got} == {"load-master"}
    item_logs = [g for g in got if g["source_file"] == "item.csv"]
    assert [(g["target"], g["read_count"], g["loaded_count"], g["error_count"]) for g in item_logs] == [("item", 2, 2, 0)] * 2
    assert all(g["finished_at"] is not None for g in got)
    assert "판정: PASS" in capsys.readouterr().out


def test_load_master_skips_bad_rows_and_reports_them(tmp_path, capsys, clean_db):
    by = P + "dirty"
    assert migration.COMMANDS["load-master"](write(tmp_path, DIRTY), by=by) == 1
    out = capsys.readouterr().out
    got = loaded()
    assert (got["item"], got["equipment"]) == (2, 1)                        # 오류 행만 빠졌다
    item_log = next(g for g in logs(by) if g["source_file"] == "item.csv")
    assert (item_log["read_count"], item_log["loaded_count"], item_log["error_count"]) == (4, 2, 2)
    assert "item_name: 필수값이 비어 있다" in item_log["error_detail"] and "4행" in item_log["error_detail"]
    eq_log = next(g for g in logs(by) if g["source_file"] == "equipment.csv")
    assert eq_log["error_count"] == 1 and "없는 코드" in eq_log["error_detail"]
    assert "판정: FAIL" in out and "item_type: 제품 | 원재료 중 하나여야 한다" in out


@pytest.mark.fn("B-MIG-03")
def test_load_print_std_is_idempotent_upsert(tmp_path, capsys, clean_db):
    folder, by = write(tmp_path, DIRTY), P + "print"
    migration.COMMANDS["load-master"](folder, by=by)
    assert migration.COMMANDS["load-print-std"](folder, by=by) == 1          # 비율 150 한 행이 오류
    first = loaded()
    assert (first["plate_spec"], first["anilox"], first["ink_formula"], first["ink_formula_component"]) == (1, 1, 1, 2)
    plate = one("""select p.color_count, i.item_code from plate_spec p join item i on i.item_id = p.item_id
                    where p.plate_code = %s""", (P + "PL1",))
    assert plate == {"color_count": 4, "item_code": P + "P01"}
    comp_log = [g for g in logs(by) if g["source_file"] == "ink_formula_component.csv"][-1]
    assert (comp_log["read_count"], comp_log["loaded_count"], comp_log["error_count"]) == (3, 2, 1)
    assert "ratio_pct: 100 이하여야 한다" in comp_log["error_detail"]

    migration.COMMANDS["load-print-std"](folder, by=by)                     # 다시 — 행 수 그대로
    assert loaded() == first
    capsys.readouterr()


@pytest.mark.fn("B-MIG-04")
def test_load_jobs_continues_past_unknown_codes(tmp_path, capsys, clean_db):
    folder, by = write(tmp_path, DIRTY), P + "jobs"
    migration.COMMANDS["load-master"](folder, by=by)
    migration.COMMANDS["load-print-std"](folder, by=by)
    assert migration.COMMANDS["load-jobs"](folder, by=by) == 1
    out = capsys.readouterr().out
    first = loaded()
    assert (first["job"], first["job_lot"]) == (3, 1)                       # J001 · J002 · J005 — 오류 행 뒤의 J005 도 들어갔다
    job = one("""select j.status, j.order_qty, j.due_date::text as due, i.item_code, c.customer_code, p.plate_code, e.equipment_code
                   from job j join item i on i.item_id = j.item_id join customer c on c.customer_id = j.customer_id
                   left join plate_spec p on p.plate_spec_id = j.plate_spec_id
                   left join equipment e on e.equipment_id = j.equipment_id
                  where j.job_no = %s""", (P + "J001",))
    assert (job["status"], int(job["order_qty"]), job["due"]) == ("등록", 1000, "2001-03-15")
    assert (job["item_code"], job["customer_code"], job["plate_code"], job["equipment_code"]) == (P + "P01", P + "C01", P + "PL1", P + "EQ1")
    assert one("select status from job where job_no = %s", (P + "J002",))["status"] == "완료"
    job_log = [g for g in logs(by) if g["source_file"] == "job.csv"][-1]
    assert (job_log["target"], job_log["read_count"], job_log["loaded_count"], job_log["error_count"]) == ("job", 5, 3, 2)
    assert f"item_code: 없는 코드 '{P}NOITEM'" in out and "due_date: 날짜는 YYYY-MM-DD" in out
    assert f"job_no: 없는 코드 '{P}J003'" in out                            # 생산 LOT 의 Job 이 적재되지 않았다

    migration.COMMANDS["load-jobs"](folder, by=by)                          # 다시 — 행 수 그대로
    assert loaded() == first
    capsys.readouterr()


@pytest.mark.fn("B-MIG-05")
def test_load_history_handles_empty_files_and_refuses_data(tmp_path, capsys, clean_db):
    """범위 미확정(D-01) — 규격과 빈 파일 처리까지. 데이터 행은 적재하지 않고 그 사실을 드러낸다."""
    by = P + "history"
    empty = write(tmp_path / "empty", {"material_lot.csv": "lot_no,item_code,supplier_name,supplier_lot_no,received_qty,qty_unit,received_at,insp_status\n"})
    targets = {"material_lot", "roll", "roll_genealogy", "inspection", "shipment"}
    assert migration.COMMANDS["load-history"](empty, by=by) == 0            # 없는 파일 · 빈 파일은 오류가 아니다
    out = capsys.readouterr().out
    assert "미확정 (D-01)" in out and "빈 파일" in out and "파일 없음 (선택)" in out
    got = logs(by)
    assert len(got) == 5 and {(g["read_count"], g["loaded_count"], g["error_count"]) for g in got} == {(0, 0, 0)}
    assert {g["target"] for g in got} == targets

    migration.COMMANDS["load-master"](write(tmp_path / "master", CLEAN), by=by)
    full = write(tmp_path / "full", {"material_lot.csv":
                 "lot_no,item_code,supplier_name,supplier_lot_no,received_qty,qty_unit,received_at,insp_status\n"
                 f"{P}ML1,{P}R01,공급처 (예시),,100,m,2001-03-01,합격\n"
                 f"{P}ML2,{P}R01,공급처 (예시),,-5,m,2001-03-01,합격\n"})
    assert migration.COMMANDS["load-history"](full, by=by) == 1
    out = capsys.readouterr().out
    assert "과거 이력 적재 범위 미확정 (D-01) — 2행을 적재하지 않았다" in out
    assert "received_qty: 0 보다 커야 한다" in out                          # 규격 검사는 한다
    assert count("select count(*) as n from material_lot where lot_no like %s", (P + "%",)) == 0
    last = [g for g in logs(by) if g["source_file"] == "material_lot.csv"][-1]
    assert (last["read_count"], last["loaded_count"]) == (2, 0) and "D-01" in last["error_detail"]


@pytest.mark.fn("B-MIG-06")
def test_report_compares_log_with_tables(tmp_path, capsys, clean_db):
    assert migration.COMMANDS["report"](None, by=P + "none") == 0
    assert "이관 실행 기록: 미수집" in capsys.readouterr().out

    folder, by = write(tmp_path / "clean", CLEAN), P + "report"
    for cmd in ("load-master", "load-print-std", "load-jobs", "load-history"):
        assert migration.COMMANDS[cmd](folder, by=by) == 0
        assert migration.COMMANDS[cmd](folder, by=by) == 0                  # 두 번 — 행 수 같다
    rows = loaded()
    capsys.readouterr()
    assert migration.COMMANDS["report"](folder, by=by) == 0
    out = capsys.readouterr().out
    assert "판정: PASS — 최신 실행 16건 · 오류 있는 실행 0 · 행 수 불일치 0 · 테이블에 없는 키 0" in out
    line = next(ln for ln in out.splitlines() if ln.startswith("load-master") and "item.csv" in ln)
    assert line.split()[3:7] == ["2", "2", "2", "0"]                        # 실행 2회 · 읽음 2 · 적재 2 · 오류 0
    key_line = next(ln for ln in out.splitlines() if ln.startswith("job.csv"))
    assert key_line.split()[2:5] == ["2", "2", "0"]                         # 파일의 키 2 · 테이블에 있음 2 · 없음 0
    assert loaded() == rows                                                 # 리포트는 쓰지 않는다
    assert len(logs(by)) == 32

    by2 = P + "report2"
    migration.COMMANDS["load-master"](write(tmp_path / "dirty", DIRTY), by=by2)
    capsys.readouterr()
    assert migration.COMMANDS["report"](None, by=by2) == 1                  # 최신 실행에 오류 행이 있다
    out = capsys.readouterr().out
    assert "오류 목록" in out and "item_name: 필수값이 비어 있다" in out and "판정: FAIL" in out

    conn.x("delete from item where item_code = %s", (P + "R01",))           # 적재한 행이 사라지면 키 대조가 잡는다
    assert migration.COMMANDS["report"](folder, by=by) == 1
    assert f"없는 키 ['{P}R01']" in capsys.readouterr().out


@pytest.mark.fn("B-MIG-01", "B-MIG-02", "B-MIG-06")
def test_cli_entrypoint(tmp_path, clean_db):
    """`python -m lcomfine.migration <명령> --dir <폴더>` — 종료코드와 출력."""
    folder = write(tmp_path, CLEAN)
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}

    def run(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-m", "lcomfine.migration", *args], cwd=ROOT, env=env,
                              capture_output=True, text=True, timeout=120)

    r = run("validate", "--dir", str(folder))
    assert r.returncode == 0 and "판정: PASS" in r.stdout, r.stdout + r.stderr
    r = run("load-master", "--dir", str(folder), "--by", P + "cli")
    assert r.returncode == 0 and "sys_migration_log 5줄" in r.stdout, r.stdout + r.stderr
    assert loaded()["item"] == 2
    r = run("report", "--by", P + "cli")
    assert r.returncode == 0 and "item.csv" in r.stdout, r.stdout + r.stderr
    r = run("load-master")                                                  # --dir 없음 → 사용법 오류
    assert r.returncode == 2 and "--dir" in r.stderr
    r = run("load-nothing", "--dir", str(folder))
    assert r.returncode == 2


def test_file_spec_doc_is_rendered_from_code():
    """`contracts/migration-files.md` §3 = `files.SPECS` 의 렌더본 (문서와 코드가 따로 놀지 않는다)."""
    doc = (ROOT / "contracts" / "migration-files.md").read_text(encoding="utf-8")
    block = doc[doc.index(files.DOC_BEGIN) + len(files.DOC_BEGIN):doc.index(files.DOC_END)].strip()
    assert block == files.render_markdown().strip()


@pytest.mark.fn("B-MIG-01")
def test_example_folder_passes_validation(capsys):
    """저장소의 `(예시)` 파일 한 벌(`migration/examples/`)은 규격을 지킨다. 검증은 쓰지 않는다."""
    folder = ROOT / "src" / "lcomfine" / "migration" / "examples"
    assert sorted(p.name for p in folder.glob("*.csv")) == sorted(s.filename for s in files.SPECS)
    results = migration.commands.check_folder(folder)
    assert [e.text() for r in results for e in r.errors] == []
    assert sum(len(r.rows) for r in results) > 0
    for r in results:                                   # 이름·비고에는 (예시) 를 붙였다 — 실데이터가 아니다
        for row in r.rows:
            labelled = [v for k, v in row.values.items() if (k.endswith("_name") or k == "note") and v]
            assert all("(예시)" in v for v in labelled), (r.spec.filename, row.values)
    capsys.readouterr()
