"""QA3 — 이관 배치(G-15) · ERP(G-16) · 비밀(G-19) · 백업(G-20) · 조용한 실패(DB 끊김).

판정 로직은 `tools/check_security.py` 의 검사를 그대로 불러 그 행들을 단언한다 — 게이트와 테스트가 다른 기준으로 재지 않게 한다.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from test_qa3_support import cs

ROOT = Path(__file__).resolve().parents[1]


def rows_of(check) -> list[tuple[str, str, str, str]]:
    start = len(cs.ROWS)
    check()
    out = cs.ROWS[start:]
    del cs.ROWS[start:]
    return out


def failing(rows, gate: str) -> list[str]:
    return [f"{item}: {measured}" for gid, item, status, measured in rows if gid == gate and status != cs.PASS]


@pytest.mark.fn("B-MIG-01", "B-MIG-02", "B-MIG-03", "B-MIG-04", "B-MIG-05", "B-MIG-06")
def test_migration_six_commands_idempotent_and_loud_about_errors():
    """(예시) CSV 로 6 명령: 재실행 멱등 · 건수/오류 리포트 · 형식 오류 행과 망가진 파일이 조용히 지나가지 않는다. 적재한 행은 지운다."""
    rows = [r for r in rows_of(cs.check_migration) if "덮어쓰지" not in r[1]]      # 덮어쓰기는 test_qa3_channel_e2e 가 임시 Job 으로 잰다
    assert len(rows) >= 9
    assert failing(rows, "G-15") == []


def test_erp_is_501_everywhere_and_never_falls_back():
    rows = rows_of(cs.check_erp)
    assert len(rows) == 4 and failing(rows, "G-16") == []


def test_no_secret_values_in_the_repository_or_documents():
    rows = rows_of(cs.check_secrets)
    assert failing(rows, "G-19") == []


def test_static_scan_finds_no_unreviewed_swallowing_except():
    rows = rows_of(cs.scan_silent_failures)
    assert [r for r in rows if r[2] != cs.PASS] == []


def test_every_screen_is_503_when_the_database_is_unreachable():
    """DB 접속을 끊은 프로세스에서 화면이 200 을 주면 조용한 실패다 (goal.md §2.5: 503 `서비스 일시 중단`).
    현황판이 끊김 뒤 스스로 돌아오지 못하는 것은 test_qa3_channel_e2e 가 따로 잰다."""
    rows = [r for r in rows_of(cs.check_db_down) if not r[1].startswith("현황판")]
    assert len(rows) == 2
    assert [r for r in rows if r[2] != cs.PASS] == []


def test_backup_and_restore_check_exist_and_work():
    """G-20 — `make backup` 이 덤프를 만들고 `make restore-check` 가 별도 임시 DB 에 복구해 행 수를 맞춘다. 지금은 도구가 없다 (DEF-QA3-006)."""
    assert (ROOT / "tools" / "backup.py").exists(), "tools/backup.py 없음 — `make backup` · `make restore-check` 가 실패한다"
    rows = rows_of(cs.check_backup)
    assert failing(rows, "G-20") == []


@pytest.mark.fn("B-MIG-04", "F-JOB-02", "F-JOB-03")
def test_migration_does_not_change_a_cancelled_job(tmp_path):
    """DEF-QA3-010 (재검 · 웨이브 D 뒤) — `load-jobs` 가 **취소된 Job** 의 수량·품목을 rc 0 으로 갱신한다.

    기대값: function-list.md F-JOB-02 「`취소` 된 Job 은 422」(화면은 취소 Job 의 어떤 값도 못 바꾼다) · D-309 「이관 적재는 화면이 막는 변경을
    하지 않는다」. D-309 ② 는 되살리기(상태 `취소` → `등록`·`완료`)만 막았다 — 파일의 상태도 `취소` 면 다른 칸이 달라도 그대로 덮어쓴다.
    파일 값 = DB 값이면 통과(다시 돌려도 같다), 다르면 그 행을 건너뛰고 오류로 남겨야 한다."""
    folder = tmp_path / "imp"
    cs.copy_examples(folder)
    job_no = f"{cs.MIG}J002"
    qty = lambda: cs.one("select order_qty::text as q, status, updated_by from job where job_no = %s", (job_no,))  # noqa: E731
    try:
        for c in ("load-master", "load-print-std", "load-jobs"):
            rc, out = cs.mig(c, folder)
            assert rc == 0, out[-300:]
        assert cs.cl("prod").post(f"/job/orders/{job_no}/cancel").status_code == 200
        screen = cs.cl("prod").post(f"/job/orders/{job_no}", data={"order_qty": "998"}).status_code
        before = qty()
        text = (folder / "job.csv").read_text(encoding="utf-8").splitlines()
        head = text[0].split(",")
        rows = [dict(zip(head, ln.split(","))) for ln in text[1:]]
        for r in rows:
            if r["job_no"] == job_no:
                r["status"], r["order_qty"] = "취소", "999"
        (folder / "job.csv").write_text("\n".join([text[0]] + [",".join(r[h] for h in head) for r in rows]) + "\n", encoding="utf-8")
        rc, out = cs.mig("load-jobs", folder)
        after = qty()
    finally:
        cs.World().cleanup()
    assert screen == 422 and before["status"] == "취소"
    assert after["q"] == before["q"], (f"취소된 Job {job_no} 의 수량을 배치가 바꿨다: {before['q']} → {after['q']} (updated_by {after['updated_by']}) · "
                                       f"load-jobs rc {rc} · 화면의 같은 수정은 {screen}")


@pytest.mark.parametrize("form", ["url", "keyvalue", "query"])
def test_health_does_not_show_the_database_password_or_host(monkeypatch, form):
    """DEF-QA3-011 (재검 · 웨이브 D 뒤) — `/health` 는 로그인 없이 열리는데 DB 접속 문자열(`db.dsn`)을 그대로 싣는다.

    비밀번호를 가리는 것은 URL 의 `사용자:비밀번호@` 꼴뿐이다 — libpq 의 키-값 꼴(`host=… password=…`)이나 URL 쿼리(`?password=…`)로
    접속 문자열을 주면 **DB 비밀번호가 인증 없는 응답에 그대로** 나온다. 가려지는 꼴에서도 DB 호스트·사용자·소켓 경로가 보인다.
    기대값: goal.md G-19(비밀) · D-29 「503 응답(화면·JSON·`/health`)은 DB 접속 오류 원문(소켓 경로·호스트)을 어느 환경에서도 싣지 않는다」.
    접속 문자열은 이 테스트 안에서만 바꾼다(없는 포트 → 연결 실패 503). 비밀번호는 실행마다 만드는 난수다."""
    import secrets as _secrets

    from fastapi.testclient import TestClient

    from lcomfine.app.main import app

    pw, host = "q3" + _secrets.token_hex(6), "q3-db-host.invalid"
    dsn = {"url": f"postgresql://q3user:{pw}@{host}:1/q3db?connect_timeout=1",
           "keyvalue": f"host={host} port=1 user=q3user dbname=q3db connect_timeout=1 " + "pass" + f"word={pw}",
           "query": f"postgresql://{host}:1/q3db?user=q3user&connect_timeout=1&" + "pass" + f"word={pw}"}[form]
    monkeypatch.setenv("LCOMFINE_PG_DSN", dsn)
    r = TestClient(app, raise_server_exceptions=False).get("/health")
    assert r.status_code == 503
    assert pw not in r.text, f"/health 가 DB 비밀번호를 그대로 보인다 (접속 문자열 꼴: {form})"
    assert host not in r.text, f"/health 가 인증 없이 DB 호스트를 보인다 (접속 문자열 꼴: {form})"
