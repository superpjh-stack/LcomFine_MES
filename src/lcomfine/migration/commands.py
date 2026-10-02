"""이관 배치 6명령 — B-MIG-01~06 (`contracts/function-list.md` · D-23 · D-303).

    validate         B-MIG-01  Import 파일 검증      적재하지 않는다. 오류가 있으면 종료코드 1
    load-master      B-MIG-02  기준정보 적재         item · customer · process · equipment · defect_code
    load-print-std   B-MIG-03  인쇄 기준 적재        plate_spec · anilox · ink_formula · ink_formula_component
    load-jobs        B-MIG-04  작업지시 적재         job · job_lot
    load-history     B-MIG-05  과거 이력 적재        범위 미확정(D-01) — 규격 검사와 빈 파일 처리까지. 데이터 행은 적재하지 않는다
    report           B-MIG-06  이관 결과 리포트      sys_migration_log ↔ 대상 테이블 행 수

- 적재는 업무 코드 기준 upsert — 다시 돌려도 행 수가 같다(G-15).
- 실행 × 파일마다 `sys_migration_log` 한 줄(읽은 수 · 적재 수 · 오류 수 · 오류 내용). `validate` · `report` 는 아무 테이블에도 쓰지 않는다.
- 형식이 틀리거나 참조 코드가 없는 행은 **그 행만** 건너뛰고 오류 목록에 남긴다. 오류가 하나라도 있으면 종료코드 1.
- 오류를 삼키지 않는다. 예상하지 못한 예외(DB 연결 실패 등)는 그대로 올라간다.
"""

from __future__ import annotations

import getpass
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import psycopg

from ..db import conn
from . import files
from .files import FileResult, FileSpec, RowError

#: 적재한 행의 created_by · updated_by
LOADED_BY = "migration"
DECISION_HISTORY = "D-01"
NOT_COLLECTED = "미수집"
#: 로그·화면에 낱낱이 적는 오류 줄 수의 상한 (나머지는 "외 n건" 으로 센다 — 숨기지 않는다)
MAX_ERROR_LINES = 100


def _run_by(by: str | None) -> str:
    return by or getpass.getuser()


def _error_text(errors: list[RowError]) -> str | None:
    if not errors:
        return None
    lines = [e.text() for e in errors[:MAX_ERROR_LINES]]
    if len(errors) > MAX_ERROR_LINES:
        lines.append(f"… 외 {len(errors) - MAX_ERROR_LINES}건")
    return "\n".join(lines)


# ── 코드 참조 ───────────────────────────────────────────────────────────
def _db_codes(cur, ref: str) -> dict[str, int]:
    """참조 대상의 {업무 코드: 내부 키} — DB 에 지금 있는 것."""
    table, code_col, id_col = files.REFS[ref]
    cur.execute(f"select {code_col} as code, {id_col} as id from {table}")
    return {r["code"]: r["id"] for r in cur.fetchall()}


def _check_refs(res: FileResult, codes_of) -> None:
    """참조 코드가 없는 행을 오류로 돌린다. `codes_of(ref)` 는 쓸 수 있는 코드의 모음."""
    ref_cols = [c for c in res.spec.cols if c.ref]
    if not ref_cols:
        return
    kept = []
    for row in res.rows:
        bad = [f"{c.name}: 없는 코드 {row.values[c.name]!r}" for c in ref_cols
               if row.values[c.name] is not None and row.values[c.name] not in codes_of(c.ref)]
        if bad:
            res.fail(row.line, row.key_text(res.spec), " · ".join(bad))
        else:
            kept.append(row)
    res.rows = kept


# ── B-MIG-01 validate ───────────────────────────────────────────────────
def check_folder(directory: Path) -> list[FileResult]:
    """폴더의 파일 16개를 읽어 파일 유무 · 열 이름 · 필수값 · 형식 · 코드 참조를 검사한다. **쓰지 않는다.**

    코드 참조는 "DB 에 이미 있는 코드" 또는 "같은 폴더의 앞선 파일에서 검사를 통과한 코드" 면 통과다.
    """
    results: list[FileResult] = []
    passed: dict[str, set] = {}                 # 파일 이름 → 검사를 통과한 업무 키(첫 열)
    db_cache: dict[str, set[str]] = {}

    def codes_of(ref: str) -> set:
        if ref not in db_cache:
            table, code_col, _ = files.REFS[ref]
            db_cache[ref] = {r["code"] for r in conn.q(f"select {code_col} as code from {table}")}
        return db_cache[ref] | passed.get(ref, set())

    for spec in files.SPECS:
        res = files.read(spec, directory)
        if not res.exists:
            if spec.required:
                res.fail(0, "", "파일 없음")
        elif not res.file_broken:
            _check_refs(res, codes_of)
        passed[spec.name] = {row.values[spec.key[0]] for row in res.rows}
        results.append(res)
    return results


def validate(directory: Path, *, by: str | None = None) -> int:
    """B-MIG-01 Import 파일 검증. 적재하지 않는다. 오류가 있으면 종료코드 1."""
    results = check_folder(Path(directory))
    print(f"Import 파일 검증 — {directory}  (적재하지 않는다)")
    print(f"{'파일':<28}{'명령':<16}{'상태':<10}{'읽은 행':>8}{'통과':>8}{'오류':>8}")
    for res in results:
        state = "있음" if res.exists else ("없음" if res.spec.required else "없음(선택)")
        print(f"{res.spec.filename:<28}{res.spec.command:<16}{state:<10}{res.read_count:>8}{len(res.rows):>8}{len(res.errors):>8}")
    total = sum(len(r.errors) for r in results)
    if total:
        print(f"\n오류 {total}건")
        for res in results:
            for e in res.errors:
                print(f"  {res.spec.filename} {e.text()}")
    history = [r for r in results if not r.spec.loadable and r.read_count]
    if history:
        print(f"\n과거 이력 파일에 데이터가 있다 — 적재 범위 미확정 ({DECISION_HISTORY}). `load-history` 는 이 행들을 적재하지 않는다:")
        for res in history:
            print(f"  {res.spec.filename} {res.read_count}행")
    print(f"\n판정: {'FAIL' if total else 'PASS'} — 파일 {sum(r.exists for r in results)}/{len(results)} · 오류 {total}건")
    return 1 if total else 0


# ── B-MIG-02~05 적재 ────────────────────────────────────────────────────
@dataclass
class LoadResult:
    spec: FileSpec
    exists: bool
    read_count: int = 0
    loaded_count: int = 0
    inserted: int = 0
    updated: int = 0
    errors: list[RowError] = field(default_factory=list)
    note: str = ""


def _upsert_sql(spec: FileSpec) -> str:
    cols = [c.column for c in spec.cols]
    key_cols = [spec.col(k).column for k in spec.key]
    insert_cols = cols + (["created_by"] if spec.audit else [])
    updates = [f"{c} = excluded.{c}" for c in cols if c not in key_cols]
    if spec.audit:
        updates += ["updated_at = now()", "updated_by = excluded.created_by"]
    return (f"insert into {spec.table} ({', '.join(insert_cols)}) values ({', '.join(['%s'] * len(insert_cols))}) "
            f"on conflict ({', '.join(key_cols)}) do update set {', '.join(updates)} "
            f"returning (xmax = 0) as inserted")


def _write_log(command: str, spec: FileSpec, result: LoadResult, started: datetime, by: str | None) -> None:
    detail = _error_text(result.errors)
    if result.note:
        detail = f"{result.note}\n{detail}" if detail else result.note
    conn.x("""insert into sys_migration_log (command, target, source_file, read_count, loaded_count, error_count,
                                             error_detail, started_at, finished_at, run_by)
              values (%s, %s, %s, %s, %s, %s, %s, %s, now(), %s)""",
           (command, spec.table, spec.filename, result.read_count, result.loaded_count, len(result.errors),
            detail, started, _run_by(by)))


def _load_file(command: str, spec: FileSpec, directory: Path, by: str | None) -> LoadResult:
    """파일 하나를 업무 키 기준 upsert 한다. 통과한 행은 한 트랜잭션, 행 하나의 DB 제약 위반은 그 행만 되돌린다."""
    started = datetime.now().astimezone()
    res = files.read(spec, directory)
    out = LoadResult(spec, res.exists, read_count=res.read_count)
    if not res.exists:
        out.errors.append(RowError(0, "", "파일 없음"))
    elif not res.file_broken:
        sql = _upsert_sql(spec)
        with conn.tx() as cur:
            ids = {c.ref: _db_codes(cur, c.ref) for c in spec.cols if c.ref}
            _check_refs(res, lambda ref: ids[ref])
            for row in res.rows:
                params = [ids[c.ref][row.values[c.name]] if c.ref and row.values[c.name] is not None
                          else row.values[c.name] for c in spec.cols]
                if spec.audit:
                    params.append(LOADED_BY)
                try:
                    with cur.connection.transaction():        # 세이브포인트 — 이 행만 되돌린다
                        cur.execute(sql, params)
                        inserted = cur.fetchone()["inserted"]
                except (psycopg.errors.IntegrityError, psycopg.errors.DataError) as exc:
                    reason = (getattr(exc.diag, "message_primary", None) or str(exc)).strip()
                    res.fail(row.line, row.key_text(spec), f"DB 제약 위반 — {reason}")
                    continue
                out.loaded_count += 1
                out.inserted += inserted
                out.updated += not inserted
    out.errors = list(res.errors) if res.exists else out.errors
    _write_log(command, spec, out, started, by)
    return out


def _print_load(command: str, title: str, directory: Path, results: list[LoadResult]) -> int:
    print(f"{title} ({command}) — {directory}")
    print(f"{'파일':<28}{'대상 테이블':<24}{'읽음':>6}{'적재':>6}{'신규':>6}{'갱신':>6}{'오류':>6}")
    for r in results:
        print(f"{r.spec.filename:<28}{r.spec.table:<24}{r.read_count:>6}{r.loaded_count:>6}{r.inserted:>6}{r.updated:>6}{len(r.errors):>6}"
              + (f"  {r.note}" if r.note else ""))
    total = sum(len(r.errors) for r in results)
    if total:
        print(f"\n오류 {total}건 — 그 행은 적재하지 않았다")
        for r in results:
            for e in r.errors:
                print(f"  {r.spec.filename} {e.text()}")
    print(f"\n판정: {'FAIL' if total else 'PASS'} — 읽음 {sum(r.read_count for r in results)} · "
          f"적재 {sum(r.loaded_count for r in results)} · 오류 {total} · sys_migration_log {len(results)}줄")
    return 1 if total else 0


def run_load(command: str, directory: Path, by: str | None = None) -> list[LoadResult]:
    return [_load_file(command, spec, Path(directory), by) for spec in files.specs_of(command)]


def load_master(directory: Path, *, by: str | None = None) -> int:
    """B-MIG-02 기준정보 적재 — 품목 · 고객 · 공정 · 설비 · 불량코드를 코드 기준 upsert."""
    return _print_load(files.MASTER, "기준정보 적재", directory, run_load(files.MASTER, directory, by))


def load_print_std(directory: Path, *, by: str | None = None) -> int:
    """B-MIG-03 인쇄 기준 적재 — 판사양 · 아니록스 · 잉크조성(+ 조성 행)을 코드 기준 upsert."""
    return _print_load(files.PRINT_STD, "인쇄 기준 적재", directory, run_load(files.PRINT_STD, directory, by))


def load_jobs(directory: Path, *, by: str | None = None) -> int:
    """B-MIG-04 작업지시 적재 — Job 과 생산 LOT 을 번호 기준 upsert. 없는 품목·고객 코드는 그 행만 오류로 남기고 계속한다."""
    return _print_load(files.JOBS, "작업지시 적재", directory, run_load(files.JOBS, directory, by))


def run_history(directory: Path, by: str | None = None) -> list[LoadResult]:
    """과거 이력 — 범위 미확정(D-01). 파일이 없거나 비어 있으면 0건으로 기록하고, 데이터 행이 있으면 **적재하지 않고** 오류로 남긴다."""
    results = []
    for spec in files.specs_of(files.HISTORY):
        started = datetime.now().astimezone()
        res = files.read(spec, Path(directory))
        out = LoadResult(spec, res.exists, read_count=res.read_count)
        if not res.exists:
            out.note = "파일 없음 (선택) — 적재할 것이 없다"
        elif res.file_broken:
            out.errors = list(res.errors)
        elif res.read_count == 0:
            out.note = "빈 파일 — 적재할 것이 없다"
        else:
            out.errors = list(res.errors)
            out.errors.append(RowError(0, "", f"과거 이력 적재 범위 미확정 ({DECISION_HISTORY}) — "
                                              f"{res.read_count}행을 적재하지 않았다"))
        _write_log(files.HISTORY, spec, out, started, by)
        results.append(out)
    return results


def load_history(directory: Path, *, by: str | None = None) -> int:
    """B-MIG-05 과거 이력 적재 — 규격과 빈 파일 처리까지(D-01 · D-23). 데이터 행이 있으면 종료코드 1."""
    rc = _print_load(files.HISTORY, f"과거 이력 적재 — 범위 미확정 ({DECISION_HISTORY})", directory,
                     run_history(directory, by))
    print(f"과거 이력의 적재 범위(어느 테이블까지 · 계보 포함 여부)는 기존 MES 를 확인한 뒤 정한다 — 미확정 ({DECISION_HISTORY})")
    return rc


# ── B-MIG-06 report ─────────────────────────────────────────────────────
_TABLES = {s.table for s in files.SPECS}


def _table_count(table: str) -> int:
    if table not in _TABLES:
        raise ValueError(f"이관 대상이 아닌 테이블: {table!r}")
    return conn.q1(f"select count(*) as n from {table}")["n"]


def build_report(directory: Path | None = None, by: str | None = None) -> dict:
    """`sys_migration_log` 의 (명령, 파일)별 **최신 실행**과 대상 테이블의 현재 행 수를 대조한다. 쓰지 않는다.

    대조 — 테이블 행 수 ≥ 그 실행의 적재 수 면 `OK`(화면에서 만든 행이 더 있을 수 있다), 모자라면 `불일치`.
    폴더를 주면 파일의 업무 키가 테이블에 실제로 있는지도 낱낱이 본다(적재 가능한 파일만).
    """
    logs = conn.q(
        """select l.*, n.runs
             from sys_migration_log l
             join (select command, source_file, max(migration_log_id) as last_id, count(*)::int as runs
                     from sys_migration_log
                    where (%(by)s::text is null or run_by = %(by)s::text)
                    group by command, source_file) n on n.last_id = l.migration_log_id
            order by l.migration_log_id""", {"by": by})
    rows = []
    for g in logs:
        count = _table_count(g["target"])
        rows.append({**g, "table_count": count, "match": count >= g["loaded_count"]})
    keys = []
    if directory is not None:
        for spec in files.SPECS:
            if not spec.loadable:
                continue
            res = files.read(spec, Path(directory))
            if not res.exists or res.file_broken:
                continue
            code_col = files.REFS[spec.name][1] if spec.name in files.REFS else None
            if code_col is None:              # 복합 키(잉크조성 행)는 키 대조에서 뺀다 — 행 수 대조만
                continue
            have = {r["code"] for r in conn.q(f"select {code_col} as code from {spec.table}")}
            file_keys = [row.values[spec.key[0]] for row in res.rows]
            missing = [k for k in file_keys if k not in have]
            keys.append({"file": spec.filename, "table": spec.table, "file_keys": len(file_keys),
                         "in_table": len(file_keys) - len(missing), "missing": missing})
    return {"logs": rows, "keys": keys}


def report(directory: Path | None = None, *, by: str | None = None) -> int:
    """B-MIG-06 이관 결과 리포트. 최신 실행에 오류 행이 있거나 대조가 어긋나면 종료코드 1."""
    rep = build_report(directory, by)
    print("이관 결과 리포트 — sys_migration_log 의 (명령, 파일)별 최신 실행 ↔ 대상 테이블 행 수" + (f" · 실행자 {by}" if by else ""))
    if not rep["logs"]:
        print(f"이관 실행 기록: {NOT_COLLECTED} — 적재 명령을 아직 돌리지 않았다")
        return 0
    print(f"{'명령':<16}{'파일':<28}{'대상 테이블':<24}{'실행':>5}{'읽음':>6}{'적재':>6}{'오류':>6}{'테이블 행':>10}  {'대조':<6}{'끝난 시각'}")
    for g in rep["logs"]:
        print(f"{g['command']:<16}{g['source_file'] or '-':<28}{g['target'] or '-':<24}{g['runs']:>5}{g['read_count']:>6}"
              f"{g['loaded_count']:>6}{g['error_count']:>6}{g['table_count']:>10}  {'OK' if g['match'] else '불일치':<6}"
              f"{g['finished_at']:%Y-%m-%d %H:%M:%S}")
    with_errors = [g for g in rep["logs"] if g["error_count"]]
    notes = [g for g in rep["logs"] if not g["error_count"] and g["error_detail"]]
    if with_errors:
        print(f"\n오류 목록 — 최신 실행 {len(with_errors)}건에 오류 행 {sum(g['error_count'] for g in with_errors)}개")
        for g in with_errors:
            for line in (g["error_detail"] or "").splitlines():
                print(f"  {g['command']} {g['source_file']} {line}")
    if notes:
        print("\n참고")
        for g in notes:
            print(f"  {g['command']} {g['source_file']} {g['error_detail']}")
    missing_total = 0
    if rep["keys"]:
        print(f"\n파일 ↔ 테이블 업무 키 대조 — {directory}")
        print(f"{'파일':<28}{'대상 테이블':<24}{'파일의 키':>10}{'테이블에 있음':>14}{'없음':>6}")
        for k in rep["keys"]:
            missing_total += len(k["missing"])
            print(f"{k['file']:<28}{k['table']:<24}{k['file_keys']:>10}{k['in_table']:>14}{len(k['missing']):>6}"
                  + (f"  없는 키 {k['missing'][:10]}" if k["missing"] else ""))
    mismatched = [g for g in rep["logs"] if not g["match"]]
    bad = bool(with_errors or mismatched or missing_total)
    print(f"\n판정: {'FAIL' if bad else 'PASS'} — 최신 실행 {len(rep['logs'])}건 · 오류 있는 실행 {len(with_errors)} · "
          f"행 수 불일치 {len(mismatched)} · 테이블에 없는 키 {missing_total}")
    return 1 if bad else 0
