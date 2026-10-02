#!/usr/bin/env python
"""수용 게이트 G-01~G-22 판정표 (goal.md §2) — `make gate`.

루프가 매 회전 부르는 것. **판정은 실제 명령의 출력으로만 한다.**

  · 검사기가 있으면 돌려서 그 출력의 `G-nn  항목  PASS|FAIL|WARN|BLOCKED|미검증  실측` 행을 읽는다.
  · QA 소유 검사기(`check_data` `check_security` `check_screens`)가 아직 없으면 그 게이트는 `미검증` 이다.
    여기서 대신 잴 수 있는 사실(스텁 여부·파일 유무·행 수)은 재서 실측 칸에 적는다 — 재 보니 안 되는 것은 `FAIL`.
  · **통과한 것처럼 보이게 하지 않는다.** 검사기 없이 PASS 를 주지 않는다(검사기가 있는 G-01~G-04 와 G-21 만 PASS 가 나올 수 있다).
  · G-22(브라우저 한 바퀴)는 QA3 의 리포트 `outputs/qa3-채널보안.md` 에 적힌 `G-22  …  PASS|FAIL  …` 행을 읽는다. 없으면 `미검증`.
  · `decisions.md` 에 `상태: 차단` 으로 올라온 D-번호가 언급한 게이트는, 실측이 PASS/FAIL 이 아닐 때 `BLOCKED` 로 나온다.

    uv run python tools/gate.py               # 읽기 전용 판정표. 종료코드 0 (판정은 출력으로 한다 — D-24)
    uv run python tools/gate.py --run-seeds   # + 시드를 한 번 더 돌려 G-09(행 수 diff 0)를 잰다  (`make gate-full`)
    uv run python tools/gate.py --strict      # FAIL·미검증이 하나라도 있으면 종료코드 1
"""

from __future__ import annotations

import warnings

warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient`")

import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(TOOLS))

PASS, FAIL, WARN, BLOCKED, UNVERIFIED = "PASS", "FAIL", "WARN", "BLOCKED", "미검증"

GATES: list[tuple[str, str]] = [
    ("G-01", "메뉴 — 묶음 4 · 대메뉴 12 · 중메뉴 32 (nav = 설계도)"),
    ("G-02", "기능 — 94 + 이관 6 · 계약 = API = 테스트 · 고아 0"),
    ("G-03", "화면 — 중메뉴 32 + 공통 3 전부 200 · placeholder 0"),
    ("G-04", "저장소 — D1~D8 ↔ 계약 ↔ 실제 DB"),
    ("G-05", "쓰기 경계 — 프로세스별 쓰는 저장소 · P9·P10 쓰기 0"),
    ("G-06", "계보 재현 — §3 예시 roll_genealogy 10행 (API)"),
    ("G-07", "추적 — 역방향·정방향 재귀 조회 · 분기 5단 이상"),
    ("G-08", "키 연결 — 롤 번호 → 지시·조색·실적·검사·출하 · 채번 한 곳"),
    ("G-09", "시드 멱등 — 2회 실행 행 수 diff 0 · (예시) 표기"),
    ("G-10", "집계 — 생산·품질·납기 = 독립 SQL 재계산"),
    ("G-11", "빈 화면 — 미수집 / 미확정 (D-nn)"),
    ("G-12", "범위 밖 0 — PLC 수집 · 비전 · AI 없음"),
    ("G-13", "4채널 — POP 스캔 · 모바일 390px · 현황판 새로고침"),
    ("G-14", "출력물 5종 — 작업지시서 · 라벨 3 · COA · 바코드"),
    ("G-15", "이관 배치 6 — Import 파일 · 멱등 · 리포트"),
    ("G-16", "ERP — 어댑터 + 501 명시 · 조용한 폴백 0"),
    ("G-17", "RBAC — 48칸 (입력 19 · 조회 24 · 없음 5) · 괄호 조건 2"),
    ("G-18", "접근 로그 — 로그인 · 조회 · 변경 · 로그 화면"),
    ("G-19", "비밀 — 저장소·문서에 비밀 값 없음"),
    ("G-20", "백업 — make backup · restore-check"),
    ("G-21", "빌드 — pytest 전건 · check-routes · /health 200"),
    ("G-22", "브라우저 한 바퀴 — outputs/e2e 캡처"),
]

_STATUS = "PASS|FAIL|WARN|INVALID|BLOCKED|미검증|차단"
_ROW_RE = re.compile(r"^\s*G-?(\d{2})[a-d]?\s+(.*?)\s{2,}(" + _STATUS + r")(?=\s|$)\s*(.*)$")


def run(cmd: list[str], timeout: int = 600) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, f"timeout {timeout}s"
    except FileNotFoundError as exc:
        return 127, str(exc)


def tool(name: str) -> Path | None:
    p = TOOLS / f"{name}.py"
    return p if p.exists() else None


def per_gate(output: str) -> dict[str, tuple[str, str]]:
    """검사기 출력 → {G-nn: (판정, 실측)}. 한 게이트에 행이 여럿이면 합친다:
    FAIL 이 하나라도 있으면 FAIL > BLOCKED > WARN > 미검증 > PASS. 실측 칸에는 FAIL 한 항목을 먼저 적는다."""
    raw: dict[str, list[tuple[str, str, str]]] = {}
    for ln in output.splitlines():
        m = _ROW_RE.match(ln)
        if m:
            raw.setdefault(f"G-{m.group(1)}", []).append((m.group(2).strip(), m.group(3), (m.group(4) or "").strip()))
    out: dict[str, tuple[str, str]] = {}
    for gid, items in raw.items():
        sts = [st for _, st, _ in items]
        if any(st in ("FAIL", "INVALID") for st in sts):
            st = FAIL
        elif any(st in ("BLOCKED", "차단") for st in sts):
            st = BLOCKED
        elif WARN in sts:
            st = WARN
        elif UNVERIFIED in sts:
            st = UNVERIFIED
        else:
            st = PASS
        if st == PASS:
            detail = f"검사 {len(items)} 전부 PASS"
        else:
            bad = [f"{item}: {d}" for item, s, d in items if s != PASS]
            detail = f"검사 {len(items)} · 통과 못한 {len(bad)} — " + " / ".join(bad)
        out[gid] = (st, detail)
    return out


def blocked_gates() -> dict[str, str]:
    """decisions.md 의 `상태: 차단` 항목이 본문에서 언급한 게이트 → {G-nn: D-nn}."""
    path = ROOT / "decisions.md"
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    cur, blocked, body = None, False, []

    def flush() -> None:
        if cur and blocked:
            for m in re.finditer(r"\bG-(\d{2})\b", "\n".join(body)):
                out.setdefault(f"G-{m.group(1)}", cur)

    for ln in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^## (D-\d+)\b(.*)$", ln)
        if m:
            flush()
            cur, body, blocked = m.group(1), [m.group(2)], "상태: 차단" in m.group(2)
            continue
        body.append(ln)
    flush()
    return out


def is_stub(call) -> str | None:
    """공용 모듈이 아직 스텁인가. 스텁이면 그 사유 문자열, 아니면 None. (다른 예외는 '스텁 아님' 으로 본다 — 판정은 QA 검사기가 한다)"""
    try:
        call()
    except NotImplementedError as exc:
        return str(exc)
    except Exception:  # noqa: BLE001 — 구현은 됐고 인자가 틀렸을 뿐이다
        return None
    return None


def secret_hits() -> tuple[int, int, bool]:
    """저장소에 들어갈 파일(추적 + 미추적·미무시)에 비밀 값이 글자 그대로 있는가 → (찾은 파일 수, 검사한 파일 수, .env 무시 여부)."""
    import os

    values = [v for v in (os.environ.get("LCOMFINE_SEED_PASSWORD"), os.environ.get("LCOMFINE_SESSION_SECRET")) if v]
    _, listed = run(["git", "ls-files", "-co", "--exclude-standard"])
    files = [ROOT / f for f in listed.splitlines() if f.strip()]
    hits = 0
    for f in files:
        try:
            data = f.read_bytes()
        except OSError:
            continue
        if any(v.encode() in data for v in values):
            hits += 1
    code, _ = run(["git", "check-ignore", "-q", ".env"])
    return hits, len(files), code == 0


def main() -> int:
    from lcomfine.app.settings import get_settings   # .env 를 읽는다

    result: dict[str, tuple[str, str]] = {}

    def put(gid: str, status: str, measured: str) -> None:
        result[gid] = (status, measured)

    seed_pw = bool(get_settings().seed_password)

    # ── G-01 · G-02  check_trace ──
    code, out = run(["uv", "run", "python", str(TOOLS / "check_trace.py")])
    got = per_gate(out)
    for gid in ("G-01", "G-02"):
        put(gid, *got.get(gid, (FAIL, f"check_trace 출력에 {gid} 행 없음 (rc={code}) {out.strip().splitlines()[-1:] or ''}")))

    # ── G-03  check_routes ──
    code_routes, routes_out = run(["uv", "run", "python", str(TOOLS / "check_routes.py")])
    m200 = re.search(r"\[HTTP 200\]\s*(\d+)\s*/\s*(\d+)", routes_out)
    mph = re.search(r"\[placeholder\]\s*잔여\s*(\d+)\s*건(?: — (.*))?", routes_out)
    mrb = re.search(r"\[RBAC\].*위반\s*(\d+)", routes_out)
    n_ph = int(mph.group(1)) if mph else -1
    n_viol = int(mrb.group(1)) if mrb else -1
    if m200:
        all200 = m200.group(1) == m200.group(2)
        put("G-03", PASS if (all200 and n_ph == 0) else FAIL,
            f"HTTP 200 {m200.group(1)}/{m200.group(2)} · placeholder {n_ph}" + (f" ({mph.group(2)})" if mph and mph.group(2) else ""))
    else:
        put("G-03", FAIL, f"check_routes 측정 실패 (rc={code_routes}) — {(routes_out.strip().splitlines() or ['출력 없음'])[-1][:120]}")

    # ── G-04  check_schema ──
    code, out = run(["uv", "run", "python", str(TOOLS / "check_schema.py")])
    put("G-04", *per_gate(out).get("G-04", (FAIL, f"check_schema 출력에 G-04 행 없음 (rc={code})")))

    # ── 자체 실측: 검사기가 없어도 잴 수 있는 사실 ──
    from lcomfine.app import lineage, numbering, printing, stats
    from lcomfine.db import conn

    def count(table: str) -> int:
        return conn.q1(f"select count(*) as n from {table}")["n"]

    put("G-05", UNVERIFIED, "tools/check_data.py 없음 (QA2) — 쓰기 라우터 0개")
    scenario = ROOT / "tests" / "test_lineage_scenario.py"
    if not scenario.exists():
        put("G-06", FAIL, f"tests/test_lineage_scenario.py 없음 (개발2 R1) · roll_genealogy {count('roll_genealogy')}행")
    else:
        c, o = run(["uv", "run", "pytest", "-q", str(scenario)])
        put("G-06", UNVERIFIED if c == 0 else FAIL,
            f"test_lineage_scenario {'통과' if c == 0 else '실패'} — {(o.strip().splitlines() or [''])[-1][:80]} · check_data(QA2) 대기")
    stub = is_stub(lambda: lineage.trace_backward((lineage.ROLL, 0)))
    put("G-07", FAIL if stub else UNVERIFIED, f"app/lineage.py 스텁 — {stub}" if stub else "tools/check_data.py 없음 (QA2)")
    stub = is_stub(lambda: numbering.rule(numbering.JOB))
    put("G-08", FAIL if stub else UNVERIFIED,
        f"app/numbering.py 스텁 — {stub} · sys_number_rule {count('sys_number_rule')}행" if stub else "tools/check_data.py 없음 (QA2)")
    if "--run-seeds" in sys.argv:
        if not seed_pw:
            put("G-09", FAIL, "LCOMFINE_SEED_PASSWORD 미설정 — 시드를 돌릴 수 없다")
        else:
            from lcomfine.db import seed

            before = seed.table_counts()
            c, o = run(["uv", "run", "python", "-m", "lcomfine.db.seed"])
            after = seed.table_counts()
            diff = {k: (before.get(k), after.get(k)) for k in sorted(set(before) | set(after)) if before.get(k) != after.get(k)}
            ok = c == 0 and not diff
            put("G-09", UNVERIFIED if ok else FAIL,
                (f"시드 재실행 행 수 diff 0 (테이블 {len(after)} · 행 {sum(after.values())}) — (예시) 표기 검사는 check_data(QA2) 대기" if ok
                 else f"시드 재실행 rc={c} · 달라진 테이블 {diff}"))
    else:
        put("G-09", UNVERIFIED, "이 실행에서는 시드를 돌리지 않았다 — `make gate-full`")
    stub = is_stub(lambda: stats.production(datetime.now().date(), datetime.now().date()))
    put("G-10", FAIL if stub else UNVERIFIED, f"app/stats.py 스텁 — {stub}" if stub else "tools/check_data.py 없음 (QA2)")
    put("G-11", UNVERIFIED, "tools/check_data.py 없음 (QA2)")
    put("G-12", UNVERIFIED, "tools/check_data.py 없음 (QA2)")
    put("G-13", UNVERIFIED, "tools/check_security.py 없음 (QA3) — 채널 레이아웃 훅(body.ch-*)만 있다")
    stub = is_stub(lambda: printing.barcode_svg("X"))
    put("G-14", FAIL if stub else UNVERIFIED, f"app/printing.py 스텁 — {stub}" if stub else "tools/check_security.py 없음 (QA3)")
    put("G-15", UNVERIFIED if (ROOT / "src" / "lcomfine" / "migration").exists() else FAIL,
        "tools/check_security.py 없음 (QA3)" if (ROOT / "src" / "lcomfine" / "migration").exists() else "src/lcomfine/migration 없음 (개발3) · 파일 규격 contracts/migration-files.md 없음")

    # G-16 · G-17: 재 본 사실은 적되, 판정은 QA3 검사기가 한다
    try:
        from fastapi.testclient import TestClient

        import design_doc
        from lcomfine.app import nav, rbac
        from lcomfine.app.main import app

        cl = TestClient(app, raise_server_exceptions=False)
        logged = seed_pw and cl.post("/login", data={"login_id": "admin", "password": get_settings().seed_password},
                                     follow_redirects=False).status_code == 303
        r = cl.get("/erp/status") if logged else None
        fact = f"/erp/status → {r.status_code} `{r.json().get('message')}`" if r is not None else "관리자 로그인 실패 — 재지 못함"
        put("G-16", FAIL if (r is not None and r.status_code != 501) else UNVERIFIED,
            f"자체 실측 {fact} · 조용한 폴백 검사는 check_security(QA3) 대기")

        access = design_doc.access()
        role_code = {x.name: x.code for x in rbac.roles()}
        diff = []
        for row in access["rows"]:
            menu = nav.menu_by_name(row["menu"])
            for role_name, text in zip(access["roles"], row["cells"]):
                have = rbac.cell(role_code.get(role_name, ""), menu.code).label
                if have != text:
                    diff.append(f"{row['menu']}×{role_name}: DB {have} ≠ 설계도 {text}")
        cnt = rbac.counts()
        ok17 = not diff and n_viol == 0
        put("G-17", UNVERIFIED if ok17 else FAIL,
            (f"자체 실측 DB 권한 표 {cnt['전체']}칸 = 설계도 §6 (입력 {cnt['입력']} · 조회 {cnt['조회']} · 없음 {cnt['없음']}) · "
             f"없음 칸 403 위반 {n_viol} · 쓰기 403 전수는 쓰기 API 가 생긴 뒤 check_security(QA3)·QA1") if ok17
            else f"DB ≠ 설계도 {len(diff)}칸 {diff[:2]} · 없음 칸 403 위반 {n_viol}")

        kinds = {x["log_type"]: x["n"] for x in conn.q("select log_type, count(*) as n from sys_access_log group by log_type")}
        fact = " · ".join(f"{k} {kinds.get(k, 0)}" for k in ("로그인", "조회", "변경", "오류"))
        log_ph = nav.path_of("SYS-03") in app.state.placeholder_paths
        put("G-18", FAIL if log_ph else UNVERIFIED,
            f"sys_access_log {fact} · " + ("로그 화면(SYS-03) placeholder — 조회 불가" if log_ph else "check_security(QA3) 대기"))
    except Exception as exc:  # noqa: BLE001 — 앱이 안 뜨면 그 사실이 실측이다
        for gid in ("G-16", "G-17", "G-18"):
            put(gid, FAIL, f"앱 기동 실패 — {type(exc).__name__}: {str(exc)[:100]}")

    hits, n_files, env_ignored = secret_hits()
    put("G-19", FAIL if (hits or not env_ignored) else UNVERIFIED,
        f"자체 실측 저장소 대상 파일 {n_files}개 중 비밀 값이 든 파일 {hits} · .env gitignore {'됨' if env_ignored else '안 됨'} · check_security(QA3) 대기")
    put("G-20", UNVERIFIED if tool("backup") else FAIL,
        "tools/check_security.py 없음 (QA3)" if tool("backup") else "tools/backup.py 없음 — `make backup` · `make restore-check` 미구현")

    # ── QA 검사기가 있으면 그 판정이 우선한다 ──
    extra = ["--run-seeds"] if "--run-seeds" in sys.argv else []
    for name, gids in (("check_data", [f"G-{i:02d}" for i in range(5, 13)]),
                       ("check_security", [f"G-{i:02d}" for i in range(13, 21)]),
                       ("check_screens", ["G-02", "G-03", "G-17"])):
        t = tool(name)
        if not t:
            continue
        code, out = run(["uv", "run", "python", str(t), *(extra if name == "check_data" else [])], timeout=1200)
        got = per_gate(out)
        for gid in gids:
            if gid in got:
                # 이미 FAIL 로 잰 것을 검사기의 PASS 가 덮지 못한다 (G-02·G-03·G-17 은 두 검사기가 다 PASS 여야 한다)
                if name == "check_screens" and result.get(gid, ("", ""))[0] == FAIL:
                    continue
                put(gid, *got[gid])
            elif name != "check_screens":
                put(gid, UNVERIFIED, f"{name} 출력에 {gid} 판정 행 없음 (rc={code})")

    # ── G-21 빌드 ──
    code, out = run(["uv", "run", "pytest", "-q"], timeout=1800)
    mp, mf, me = re.search(r"(\d+) passed", out), re.search(r"(\d+) failed", out), re.search(r"(\d+) error", out)
    n_pass = int(mp.group(1)) if mp else 0
    n_fail = (int(mf.group(1)) if mf else 0) + (int(me.group(1)) if me else 0)
    try:
        from fastapi.testclient import TestClient

        from lcomfine.app.main import app

        health = TestClient(app).get("/health").status_code
    except Exception as exc:  # noqa: BLE001
        health = f"{type(exc).__name__}"
    ok21 = code == 0 and n_fail == 0 and n_pass > 0 and code_routes == 0 and health == 200
    put("G-21", PASS if ok21 else FAIL,
        f"pytest passed {n_pass} · failed {n_fail} · check-routes {'PASS' if code_routes == 0 else 'FAIL'} · /health {health}")

    # ── G-22 브라우저 한 바퀴 — 사람이 보는 것과 같은 조작이라 검사기가 아니라 QA3 의 리포트가 판정한다.
    #    리포트의 `G-22  항목  PASS|FAIL  실측` 행(검사기 행과 같은 형식)을 읽는다. 리포트나 그 행이 없으면 미검증이다 —
    #    캡처 파일이 있다는 것만으로 PASS 를 주지 않는다.
    e2e = ROOT / "outputs" / "e2e"
    shots = [p for p in e2e.glob("*") if p.is_file()] if e2e.exists() else []
    report = ROOT / "outputs" / "qa3-채널보안.md"
    row = per_gate(report.read_text(encoding="utf-8")).get("G-22") if report.exists() else None
    if row is None:
        put("G-22", UNVERIFIED, f"outputs/e2e 파일 {len(shots)}개 — " + (
            f"`{report.relative_to(ROOT)}` 에 `G-22  …  PASS|FAIL  …` 판정 행이 없다" if report.exists()
            else f"`{report.relative_to(ROOT)}` 없음 — 브라우저 한 바퀴는 QA3 가 돌고 그 리포트에 판정을 적는다"))
    else:
        put("G-22", row[0], f"{row[1]} · 출처 {report.relative_to(ROOT)} · outputs/e2e 파일 {len(shots)}개")

    # ── 차단 반영 · 출력 ──
    blocked = blocked_gates()
    for gid, (st, measured) in list(result.items()):
        if st not in (PASS, FAIL) and gid in blocked:
            result[gid] = (BLOCKED, f"{measured} — 차단 {blocked[gid]}")

    print(f"게이트 판정 — 엘컴화인 MES · {datetime.now().strftime('%Y-%m-%d %H:%M')}"
          + (" · 시드 재실행 포함" if "--run-seeds" in sys.argv else ""))
    print()
    w = max(len(item) for _, item in GATES)
    for gid, item in GATES:
        st, measured = result.get(gid, (UNVERIFIED, "판정 없음"))
        print(f"{gid}  {item:<{w}}  {st}  {measured}")
    print()
    n = {s: sum(1 for g, _ in GATES if result.get(g, (UNVERIFIED, ""))[0] == s) for s in (PASS, FAIL, WARN, BLOCKED, UNVERIFIED)}
    print(f"PASS {n[PASS]} · FAIL {n[FAIL]} · WARN {n[WARN]} · BLOCKED {n[BLOCKED]} · 미검증 {n[UNVERIFIED]} / 전체 {len(GATES)}")
    print("※ WARN·미검증은 통과가 아니다. BLOCKED 는 decisions.md 에 D-번호와 사유가 있어야 종료 조건(goal.md §4.4)을 만족한다.")
    if "--strict" in sys.argv:
        return 0 if n[PASS] + n[BLOCKED] == len(GATES) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
