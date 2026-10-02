"""데이터 이관 배치 — 기존 설치형 MES 의 1회 이관 (설계도 2안 · decisions.md D-01 · D-23). 담당 개발3.

    uv run python -m lcomfine.migration <명령> --dir <Import 폴더> [--by <실행자>]

화면이 아니라 명령이다. 기존 MES 의 접근 경로가 미정이라 **표준 Import 파일**(UTF-8 CSV)로 받는다 —
파일 규격은 `contracts/migration-files.md`, 코드 쪽 원본은 `migration/files.py` 의 `SPECS` 다.

`COMMANDS` 의 키는 `contracts/function-list.md` 의 `cli <명령>` 과 같은 글자다(`tools/check_trace.py` 가 이 dict 를 읽는다).
값은 `(directory, *, by=None) -> int` — 0 = 오류 없음, 1 = 오류가 있다(목록은 출력과 `sys_migration_log` 에 남는다).
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path

from .commands import load_history, load_jobs, load_master, load_print_std, report, validate

#: 명령 → (기능 ID, 함수). 순서 = 이관 순서
_TABLE: tuple[tuple[str, str, Callable[..., int]], ...] = (
    ("validate", "B-MIG-01", validate),
    ("load-master", "B-MIG-02", load_master),
    ("load-print-std", "B-MIG-03", load_print_std),
    ("load-jobs", "B-MIG-04", load_jobs),
    ("load-history", "B-MIG-05", load_history),
    ("report", "B-MIG-06", report),
)

COMMANDS: dict[str, Callable[..., int]] = {name: fn for name, _fid, fn in _TABLE}
FUNCTION_IDS: dict[str, str] = {name: fid for name, fid, _fn in _TABLE}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m lcomfine.migration",
        description="엘컴화인 MES 데이터 이관 배치 (B-MIG-01~06). 파일 규격: contracts/migration-files.md")
    parser.add_argument("command", choices=list(COMMANDS),
                        help=" · ".join(f"{name}({fid})" for name, fid, _ in _TABLE))
    parser.add_argument("--dir", dest="directory", type=Path, default=None,
                        help="Import 폴더. report 만 생략할 수 있다(생략하면 파일 ↔ 테이블 키 대조를 건너뛴다)")
    parser.add_argument("--by", default=None,
                        help="적재 명령: sys_migration_log.run_by 에 적을 실행자(기본 OS 계정). report: 그 실행자의 기록만 본다")
    args = parser.parse_args(argv)
    if args.command != "report":
        if args.directory is None:
            parser.error(f"{args.command} 는 --dir <Import 폴더> 가 필요하다")
        if not args.directory.is_dir():
            parser.error(f"Import 폴더가 없다: {args.directory}")
    elif args.directory is not None and not args.directory.is_dir():
        parser.error(f"Import 폴더가 없다: {args.directory}")
    return COMMANDS[args.command](args.directory, by=args.by)
