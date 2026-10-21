#!/usr/bin/env python
"""수용 게이트 G-01~G-24 판정표 (goal.md §2) — `make gate` · `make gate-full`.

루프가 매 회전 부르는 것. **판정은 실제 명령의 출력으로만 한다.**

  · 게이트마다 판정 도구가 정해져 있다(`OWNER` — goal.md §2 의 「판정 명령」 열). 도구를 돌려 그 출력의
    `G-nn  항목  PASS|FAIL|WARN|BLOCKED|미검증  실측` 행을 읽는다. 한 게이트의 행이 여럿이면 가장 나쁜 것이 판정이다.
  · 도구 파일이 아직 없으면(QA 가 만든다) 그 게이트는 `미작성` 이고 **FAIL 로 센다**(게이트를 낮추지 않는다).
  · 도구가 그 게이트의 행을 찍지 않았으면 `미검증` — 통과가 아니다.
  · G-21 의 비밀 스캔은 이 파일이 바로 잰다(추적 파일의 비밀 값 · 키 패턴 · `.env` gitignore · 시드 `(예시)`).
    시드 멱등(2회 실행 행 수 diff 0)은 `--run-seeds`(`make gate-full`)에서만 잰다. check_security(QA3)가 생기면 그 행도 합친다.
  · G-23 백업 · 복구는 `--run-seeds`(`make gate-full`)에서만 돈다(덤프 파일 · 임시 DB 를 만든다 — 운영 DB 는 그대로).
  · G-24 는 `docker compose config` 가 성립하는지와 환경변수 전달까지만 잰다 — 실제 기동 · `/health` 는 아직 재지 않았으므로 `미검증`.
  · `decisions.md` 에 `상태: 차단` 으로 올라온 D-번호가 본문에서 언급한 게이트는, 판정이 미검증 · WARN 일 때 `BLOCKED` 로 나온다.

    uv run python tools/gate.py               # 읽기 전용 판정표 (시드 · 스키마를 돌리지 않는다)   `make gate`
    uv run python tools/gate.py --run-seeds   # + 시드 1회 더(멱등 diff) · 백업/복구 검증            `make gate-full` — 종료 판정은 이것으로

종료코드 = PASS 도 BLOCKED 도 아닌 게이트 수(FAIL · 미작성 · 미검증 · WARN) + 빌드 전제(pytest · /health) 실패 1.
`--strict` 는 예전 호환용이다(지금은 늘 엄격하다).
"""

from __future__ import annotations

import warnings

warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient`")

import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

PASS, FAIL, WARN, BLOCKED, UNVERIFIED, MISSING = "PASS", "FAIL", "WARN", "BLOCKED", "미검증", "미작성"
#: 나쁜 순서 — 한 게이트에 판정이 여럿이면 앞의 것이 이긴다
SEVERITY = (FAIL, MISSING, BLOCKED, WARN, UNVERIFIED, PASS)
RUN_SEEDS = "--run-seeds" in sys.argv

#: goal.md §2 표 그대로 (게이트 · 항목)
GATES: list[tuple[str, str]] = [
    ("G-01", "정본(ia.json + overrides) ↔ nav.py"),
    ("G-02", "기능 목록 ↔ 라우트 ↔ 테스트 표식 · 고아 0"),
    ("G-03", "화면 응답 — 67 + 공통 200 · placeholder 0 · 403"),
    ("G-04", "스키마 계약 ↔ 실제 DB"),
    ("G-05", "쓰기 경계"),
    ("G-06", "E2E 흐름 1건"),
    ("G-07", "역추적"),
    ("G-08", "정방향 추적"),
    ("G-09", "차단 규칙"),
    ("G-10", "가용 재계산"),
    ("G-11", "알림 9종"),
    ("G-12", "회차 교체"),
    ("G-13", "오류 행 · 미매핑"),
    ("G-14", "출하 대비 수금"),
    ("G-15", "대시보드 8 수치"),
    ("G-16", "데이터 질의 검증"),
    ("G-17", "키 없음"),
    ("G-18", "SSO 토큰"),
    ("G-19", "권한 403 전수"),
    ("G-20", "세션 상태"),
    ("G-21", "비밀 · 시드 멱등"),
    ("G-22", "변경 감사 로그"),
    ("G-23", "백업 · 복구"),
    ("G-24", "Docker · health"),
]

#: 게이트 → 판정 도구 (goal.md §2 「판정 명령」 · task-9 addendum §B)
OWNER: dict[str, str] = {
    "G-01": "check_trace", "G-02": "check_trace", "G-03": "check_routes", "G-04": "check_schema",
    **{f"G-{i:02d}": "check_data" for i in range(5, 16)},
    **{f"G-{i:02d}": "check_security" for i in range(16, 23)},
    "G-23": "backup", "G-24": "docker",
}
QA_TOOL = {"check_data": "QA2", "check_security": "QA3", "check_screens": "QA1"}
#: 세 번째 QA 검사기 — 있으면 그 출력의 행이 어느 게이트든 판정에 합쳐진다(낮추기만 한다 — 다른 도구의 FAIL 을 PASS 로 덮지 못한다)
EXTRA_TOOLS = ("check_screens",)
#: 비밀 — `.env` 에만 있어야 하는 값
SECRET_KEYS = ("LCOMFINE_SESSION_SECRET", "LCOMFINE_SEED_PASSWORD", "LCOMFINE_DB_PASSWORD", "LCOMFINE_SSO_SECRET",
               "LCOMFINE_OPENAI_API_KEY")
COMPOSE_KEYS = ("LCOMFINE_OPENAI_API_KEY", "LCOMFINE_OPENAI_MODEL", "LCOMFINE_DOC_SSO_URL", "LCOMFINE_SSO_SECRET")
#: 키 패턴 — OpenAI 형 키 · 비밀 키에 값이 붙은 줄 (`.env.example` 은 빈 값이라 빼고 본다)
KEY_RE = re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{16,}")
ASSIGN_RE = re.compile(r"\b(" + "|".join(SECRET_KEYS) + r")=(?![\s$<`'\"]|$)\S+")

_STATUS = "PASS|FAIL|WARN|INVALID|BLOCKED|미검증|미작성|차단"
_ROW_RE = re.compile(r"^\s*G-?(\d{2})[a-d]?\s+(.*?)\s{2,}(" + _STATUS + r")(?=\s|$)\s*(.*)$")


def run(cmd: list[str], timeout: int = 600) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, f"timeout {timeout}s"
    except FileNotFoundError as exc:
        return 127, str(exc)


def last_line(out: str) -> str:
    lines = [ln for ln in out.strip().splitlines() if ln.strip()]
    return lines[-1][:140] if lines else "출력 없음"


def tool(name: str) -> Path | None:
    p = TOOLS / f"{name}.py"
    return p if p.exists() else None


def worst(statuses: list[str]) -> str:
    for s in SEVERITY:
        if s in statuses:
            return s
    return UNVERIFIED


def per_gate(output: str) -> dict[str, tuple[str, str]]:
    """검사기 출력 → {G-nn: (판정, 실측)}. 한 게이트에 행이 여럿이면 합친다(가장 나쁜 것). 실측 칸에는 통과 못한 항목을 적는다."""
    raw: dict[str, list[tuple[str, str, str]]] = {}
    for ln in output.splitlines():
        m = _ROW_RE.match(ln)
        if m:
            st = {"INVALID": FAIL, "차단": BLOCKED}.get(m.group(3), m.group(3))
            raw.setdefault(f"G-{m.group(1)}", []).append((m.group(2).strip(), st, (m.group(4) or "").strip()))
    out: dict[str, tuple[str, str]] = {}
    for gid, items in raw.items():
        st = worst([s for _, s, _ in items])
        if st == PASS:
            detail = f"검사 {len(items)} 전부 PASS"
        else:
            bad = [f"{item}: {d}" for item, s, d in items if s != PASS]
            detail = f"검사 {len(items)} · 통과 못한 {len(bad)} — " + " / ".join(bad)
        out[gid] = (st, detail)
    return out


def tool_verdicts(code: int, output: str) -> dict[str, tuple[str, str]]:
    """도구 출력의 게이트별 판정 + 종료코드 반영.

    검사기는 FAIL 이 있으면 0 이 아닌 코드로 끝나는 것이 정상이다 — 그때 PASS 행은 그대로 둔다.
    그러나 **종료코드가 0 이 아닌데 FAIL 행이 하나도 없거나, traceback 을 찍었거나, 읽을 행이 없으면** 도구가 깨진 것이다:
    그 도구의 PASS 판정은 FAIL 로 내리고 실측에 「도구 종료코드 N」 을 붙인다(찍다 만 PASS 가 통과로 보이지 않게).
    """
    got = per_gate(output)
    if code == 0:
        return got
    crashed = "Traceback (most recent call last)" in output or not got or all(st != FAIL for st, _ in got.values())
    if not crashed:
        return got
    return {gid: ((FAIL if st == PASS else st), f"{m} · 도구 종료코드 {code}" + (" (traceback)" if "Traceback" in output else ""))
            for gid, (st, m) in got.items()}


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


# ── G-21 비밀 스캔 ──
def secret_scan() -> tuple[str, str]:
    """저장소에 들어갈 파일(추적 + 미추적·미무시)에 비밀 값 · 키 패턴이 있는가 · `.env` 가 gitignore 이고 추적되지 않는가."""
    values = [v for v in (os.environ.get(k) for k in SECRET_KEYS) if v and len(v) >= 8]
    _, listed = run(["git", "ls-files", "-co", "--exclude-standard"])
    files = [f for f in listed.splitlines() if f.strip()]
    value_hits, pattern_hits = [], []
    for rel in files:
        try:
            data = (ROOT / rel).read_bytes()
        except OSError:
            continue
        if any(v.encode() in data for v in values):
            value_hits.append(rel)
        if rel == ".env.example":
            continue
        text = data.decode("utf-8", errors="ignore")
        for i, ln in enumerate(text.splitlines(), 1):
            if KEY_RE.search(ln) or ASSIGN_RE.search(ln):
                pattern_hits.append(f"{rel}:{i}")
    ex = ROOT / ".env.example"
    ex_vals = [ln for ln in (ex.read_text(encoding="utf-8").splitlines() if ex.exists() else []) if ASSIGN_RE.search(ln) or KEY_RE.search(ln)]
    ignored = run(["git", "check-ignore", "-q", ".env"])[0] == 0
    tracked = bool(run(["git", "ls-files", ".env"])[1].strip())
    ok = not value_hits and not pattern_hits and not ex_vals and ignored and not tracked
    measured = (f"파일 {len(files)} · 비밀 값이 든 파일 {len(value_hits)}{' ' + str(value_hits[:3]) if value_hits else ''}"
                f" · 키 패턴 줄 {len(pattern_hits)}{' ' + str(pattern_hits[:3]) if pattern_hits else ''}"
                f" · .env.example 비밀 값 {len(ex_vals)} · .env gitignore {'됨' if ignored else '안 됨'} · .env 추적 {'됨' if tracked else '안 됨'}")
    return (PASS if ok else FAIL), measured


def seed_examples() -> tuple[str, str]:
    from lcomfine.db import conn

    users = conn.q("select user_name from sys_user where created_by = 'seed'")
    rules = conn.q("select note from sys_number_rule")
    bad_u = sum(1 for u in users if "(예시)" not in (u["user_name"] or ""))
    bad_r = sum(1 for r in rules if "(예시)" not in (r["note"] or ""))
    ok = users and rules and not bad_u and not bad_r
    return (PASS if ok else FAIL), f"시드 계정 {len(users)} 중 (예시) 없음 {bad_u} · 채번 {len(rules)} 중 (예시) 없음 {bad_r}"


def seed_idempotence() -> tuple[str, str]:
    from lcomfine.app.settings import get_settings
    from lcomfine.db import seed

    if not get_settings().seed_password:
        return FAIL, "LCOMFINE_SEED_PASSWORD 미설정 — 시드를 돌릴 수 없다"
    before = seed.table_counts()
    c, o = run(["uv", "run", "python", "-m", "lcomfine.db.seed"])
    after = seed.table_counts()
    diff = {k: (before.get(k), after.get(k)) for k in sorted(set(before) | set(after)) if before.get(k) != after.get(k)}
    if c == 0 and not diff:
        return PASS, f"시드 재실행 rc=0 · 행 수 diff 0 (테이블 {len(after)} · 행 {sum(after.values())})"
    return FAIL, f"시드 재실행 rc={c} · 달라진 테이블 {len(diff)} {dict(list(diff.items())[:3])} · {last_line(o) if c else ''}".strip()


def docker_compose() -> tuple[str, str]:
    code, out = run(["docker", "compose", "config", "-q"], timeout=120)
    if code == 127:
        return UNVERIFIED, "docker 명령 없음 — compose 검증 불가"
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    missing = [k for k in COMPOSE_KEYS if f"{k}:" not in text]
    if code != 0 or missing:
        return FAIL, f"docker compose config rc={code} {'' if code == 0 else last_line(out)} · 환경변수 빠짐 {missing or 0}"
    return UNVERIFIED, (f"docker compose config 성립 · 환경변수 {len(COMPOSE_KEYS)} 전달 — 컨테이너 기동 · /health 200 은 아직 재지 않음"
                        " (`docker compose up -d --build` → `curl localhost:8020/health`)")


def backup_restore() -> tuple[str, str]:
    c1, o1 = run(["uv", "run", "python", str(TOOLS / "backup.py"), "backup"], timeout=900)
    if c1 != 0:
        return FAIL, f"backup rc={c1} — {last_line(o1)}"
    c2, o2 = run(["uv", "run", "python", str(TOOLS / "backup.py"), "restore-check"], timeout=1800)
    verdict = next((ln.strip() for ln in o2.splitlines() if ln.startswith("판정:")), last_line(o2))
    return (PASS if c2 == 0 and verdict.startswith("판정: PASS") else FAIL), f"backup rc=0 · restore-check rc={c2} — {verdict}"


def build_precondition() -> tuple[bool, str]:
    """빌드 조건 — `uv run pytest -q` 전건 통과 · `/health` 200 (goal.md §2 「모든 게이트의 전제」)."""
    code, out = run(["uv", "run", "pytest", "-q"], timeout=1800)
    mp, mf, me = re.search(r"(\d+) passed", out), re.search(r"(\d+) failed", out), re.search(r"(\d+) error", out)
    n_pass = int(mp.group(1)) if mp else 0
    n_fail = (int(mf.group(1)) if mf else 0) + (int(me.group(1)) if me else 0)
    try:
        from fastapi.testclient import TestClient

        from lcomfine.app.main import app

        health: object = TestClient(app).get("/health").status_code
    except Exception as exc:  # noqa: BLE001 — 앱이 안 뜨면 그 사실이 실측이다
        health = type(exc).__name__
    ok = code == 0 and n_fail == 0 and n_pass > 0 and health == 200
    return ok, f"pytest passed {n_pass} · failed {n_fail} (rc={code}) · /health {health}"


def main() -> int:
    from lcomfine.app.settings import get_settings   # .env 를 읽는다 (os.environ 에 채운다)

    get_settings()
    found: dict[str, list[tuple[str, str, str]]] = {gid: [] for gid, _ in GATES}   # gid → [(출처, 판정, 실측)]

    def put(gid: str, source: str, status: str, measured: str) -> None:
        found[gid].append((source, status, measured))

    # ── 도구별로 한 번씩 돌린다 ──
    outputs: dict[str, tuple[int, str]] = {}
    for name in sorted({v for v in OWNER.values() if v not in ("backup", "docker")} | set(EXTRA_TOOLS)):
        t = tool(name)
        if t is not None:
            outputs[name] = run(["uv", "run", "python", str(t)], timeout=1800)

    for gid, _ in GATES:
        owner = OWNER[gid]
        if owner in ("backup", "docker"):
            continue
        if owner not in outputs:
            if gid == "G-21":     # 비밀 스캔은 아래에서 바로 잰다 — check_security 의 몫은 아직 없다고 적기만 한다
                continue
            put(gid, owner, MISSING, f"tools/{owner}.py 없음 — {QA_TOOL.get(owner, '?')} 가 만든다")
            continue
        code, out = outputs[owner]
        got = tool_verdicts(code, out).get(gid)
        if got is None:
            put(gid, owner, UNVERIFIED, f"{owner} 출력에 {gid} 판정 행 없음 (rc={code}) — {last_line(out)}")
        else:
            put(gid, owner, *got)
    for name in EXTRA_TOOLS:
        if name in outputs:
            for gid, got in tool_verdicts(*outputs[name]).items():
                if gid in found:
                    put(gid, name, *got)

    # ── G-21 비밀 · 시드 멱등 ──
    put("G-21", "비밀 스캔", *secret_scan())
    try:
        put("G-21", "시드 (예시)", *seed_examples())
    except Exception as exc:  # noqa: BLE001 — DB 가 없으면 그 사실이 실측이다
        put("G-21", "시드 (예시)", FAIL, f"DB 조회 실패 — {type(exc).__name__}")
    if RUN_SEEDS:
        put("G-21", "시드 멱등", *seed_idempotence())
    else:
        found["G-21"].append(("시드 멱등", "", "시드 멱등 미측정 — 이 실행에서는 시드를 돌리지 않았다 (`make gate-full`)"))
    if "check_security" not in outputs:
        found["G-21"].append(("check_security", "", "부분 — check_security 미작성 (tools/check_security.py 없음 · QA3) — 생기면 그 G-21 PASS 행이 있어야 PASS"))

    # ── G-23 백업 · 복구 ──
    if not tool("backup"):
        put("G-23", "backup", MISSING, "tools/backup.py 없음")
    elif RUN_SEEDS:
        put("G-23", "backup", *backup_restore())
    else:
        put("G-23", "backup", UNVERIFIED, "이 실행에서는 덤프 · 복구를 돌리지 않았다 — `make gate-full` (또는 `make backup && make restore-check`)")

    # ── G-24 Docker ──
    put("G-24", "docker", *docker_compose())

    # ── 빌드 전제 ──
    build_ok, build_measured = build_precondition()

    # ── 합치기 · 차단 반영 ──
    blocked = blocked_gates()
    result: dict[str, tuple[str, str]] = {}
    for gid, _ in GATES:
        items = [x for x in found[gid] if x[1]]
        notes = [f"{src}: {m}" for src, st, m in found[gid] if not st]
        if not items:
            result[gid] = (UNVERIFIED, " · ".join(notes) or "판정 없음")
            continue
        st = worst([s for _, s, _ in items])
        if len(items) == 1:
            measured = items[0][2]
        else:
            measured = " / ".join(f"[{src} {s}] {m}" for src, s, m in items)
        if notes:
            measured += " · " + " · ".join(notes)
        if st in (UNVERIFIED, WARN) and gid in blocked:
            st, measured = BLOCKED, f"{measured} — 차단 {blocked[gid]}"
        result[gid] = (st, measured)

    print(f"게이트 판정 — 엘컴화인 MES · {datetime.now().strftime('%Y-%m-%d %H:%M')}"
          + (" · 시드 재실행 · 백업/복구 포함 (gate-full)" if RUN_SEEDS else " · 읽기 전용 (gate)"))
    print(f"빌드 전제  {'PASS' if build_ok else 'FAIL'}  {build_measured}")
    print()
    w = max(len(item) for _, item in GATES)
    for gid, item in GATES:
        st, measured = result[gid]
        print(f"{gid}  {item:<{w}}  {st}  {measured}")
    print()
    n = {s: sum(1 for g, _ in GATES if result[g][0] == s) for s in SEVERITY}
    not_ok = sum(1 for g, _ in GATES if result[g][0] not in (PASS, BLOCKED))
    rc = not_ok + (0 if build_ok else 1)
    print(f"PASS {n[PASS]} · FAIL {n[FAIL]} · 미작성 {n[MISSING]} · 미검증 {n[UNVERIFIED]} · WARN {n[WARN]} · BLOCKED {n[BLOCKED]}"
          f" / 전체 {len(GATES)} · 통과 못한 게이트 {not_ok} · 빌드 전제 {'PASS' if build_ok else 'FAIL'} → 종료코드 {rc}")
    print("※ 미작성 · 미검증 · WARN 은 통과가 아니다(FAIL 로 센다). BLOCKED 는 decisions.md 에 D-번호와 사유가 있어야 종료 조건(goal.md §4.4)을 만족한다.")
    return min(rc, 125)


if __name__ == "__main__":
    raise SystemExit(main())
