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
