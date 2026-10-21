#!/usr/bin/env python
"""G-03 화면 응답 — `make check-routes`. 서버를 띄우지 않고 TestClient 로 앱을 직접 부른다.

  1. 부서 8 시드 계정(`sl pr sh ds ac st ex admin` · 비밀번호 `LCOMFINE_SEED_PASSWORD`)이 전부 로그인된다
  2. 공통 — `/login`(미로그인) · `/error` · `/health` 200, 참고 `/ia`(로그인) 200
  3. 화면 67 × 칸 있는 부서 → 200 (placeholder 포함)
  4. 화면 67 × 칸 없는 부서 → 403 (기대값은 정본 추출 `design_doc.effective()` 의 화면별 roles — DB 권한 표가 아니다)
  5. 미로그인 화면 GET — 브라우저 303 → /login, 그 밖 401
  6. placeholder 0 — 수는 `/health` 의 `placeholders` 에서 읽고, 화면 표식(`class="tag"` + `미구현`)과 맞춰 본다
  7. 라우터 import 실패 0

출력 행 형식: `G-03  항목  PASS|FAIL  실측` (tools/gate.py 가 읽는다). 종료코드: 0 = 전부 PASS, 1 = 하나라도 FAIL.
"""

from __future__ import annotations

import warnings

warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient`")

import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from lcomfine.app.settings import get_settings  # noqa: E402 — .env 를 먼저 읽는다

G = "G-03"
PLACEHOLDER_MARKS = ('class="tag"', "미구현")
HTML = {"accept": "text/html"}


def is_placeholder(html: str) -> bool:
    return all(m in html for m in PLACEHOLDER_MARKS)


def main() -> int:
    rows: list[tuple[str, bool, str]] = []
    details: list[tuple[str, list[str]]] = []

    def add(item: str, ok: bool, actual: str, bad: list[str] | None = None) -> None:
        rows.append((item, bool(ok), actual))
        if bad:
            details.append((item, bad))

    pw = get_settings().seed_password
    if not pw:
        print(f"{G}  부서 8 로그인  FAIL  LCOMFINE_SEED_PASSWORD 미설정 — `make setup` 으로 .env 를 만든다")
        return 1

    from fastapi.testclient import TestClient

    from lcomfine.app import nav
    from lcomfine.app.main import app
    from lcomfine.db.seed import USERS
    from tools import design_doc

    e = design_doc.effective()
    roles_of = {s["id"]: s["roles"] for m in e["menus"] for s in m["screens"]}
    depts = [r["id"] for r in e["roles"]]
    login_of = {code: login_id for login_id, _name, code in USERS}

    # ── 7. 라우터 import ──
    errs = list(app.state.include_errors)
    add("라우터 import 실패 0", not errs, f"실패 {len(errs)}", errs)

    # ── 1. 부서 8 로그인 ──
    clients: dict[str, TestClient] = {}
    bad = []
    for code in depts:
        login_id = login_of.get(code)
        if login_id is None:
            bad.append(f"{code}: 시드 계정 없음")
            continue
        c = TestClient(app, raise_server_exceptions=False)
        r = c.post("/login", data={"login_id": login_id, "password": pw}, follow_redirects=False)
        if r.status_code != 303:
            bad.append(f"{code}({login_id}) 로그인 {r.status_code}")
            continue
        clients[code] = c
    add(f"부서 {len(depts)} 로그인 ({' '.join(login_of.get(c, '?') for c in depts)})", len(clients) == len(depts) == 8,
        f"{len(clients)}/{len(depts)}", bad)
    if not clients:
        print(f"{G}  부서 8 로그인  FAIL  로그인 0 — 시드를 먼저 돌린다 (`make db-seed`)")
        return 1
    any_client = clients.get("ADM") or next(iter(clients.values()))

    # ── 2. 공통 ──
    anon = TestClient(app, raise_server_exceptions=False)
    common = {
        "/login (미로그인)": anon.get("/login").status_code,
        "/error": anon.get("/error").status_code,
        "/health": anon.get("/health").status_code,
        "/ia (로그인)": any_client.get("/ia").status_code,
    }
    bad = [f"{k} → {v}" for k, v in common.items() if v != 200]
    add("공통 /login · /error · /health · 참고 /ia → 200", not bad, " · ".join(f"{k} {v}" for k, v in common.items()), bad)

    # ── 3·4. 화면 67 × 부서 8 ──
    ok200, n200, ok403, n403 = 0, 0, 0, 0
    bad200, bad403 = [], []
    marked: set[str] = set()
    for s in nav.SCREENS:
        allowed = roles_of.get(s.screen_id)
        if allowed is None:
            bad200.append(f"{s.screen_id}: 정본에 없는 화면")
            continue
        for code, c in clients.items():
            r = c.get(s.path, headers=HTML, follow_redirects=False)
            if code in allowed:
                n200 += 1
                if r.status_code == 200:
                    ok200 += 1
                    if is_placeholder(r.text):
                        marked.add(s.screen_id)
                else:
                    bad200.append(f"{code} {s.screen_id} {s.path} → {r.status_code}")
            else:
                n403 += 1
                if r.status_code == 403:
                    ok403 += 1
                else:
                    bad403.append(f"{code} {s.screen_id} {s.path} → {r.status_code}")
    add(f"화면 {len(nav.SCREENS)} × 칸 있는 부서 → 200", n200 > 0 and ok200 == n200 and not bad200, f"{ok200}/{n200}", bad200)
    add(f"화면 {len(nav.SCREENS)} × 칸 없는 부서 → 403", n403 > 0 and ok403 == n403, f"{ok403}/{n403}", bad403)

    # ── 5. 미로그인 ──
    s0 = nav.SCREENS[1] if len(nav.SCREENS) > 1 else nav.SCREENS[0]
    r_html = anon.get(s0.path, headers=HTML, follow_redirects=False)
    r_api = anon.get(s0.path, follow_redirects=False)
    ok = r_html.status_code == 303 and r_html.headers.get("location", "").startswith("/login") and r_api.status_code == 401
    add("미로그인 화면 GET — 브라우저 303 /login · 그 밖 401", ok,
        f"{s0.path} 브라우저 {r_html.status_code} → {r_html.headers.get('location', '-')} · 그 밖 {r_api.status_code}")

    # ── 6. placeholder ──
    health = anon.get("/health").json()
    n_ph = health.get("placeholders")
    ph_paths = set(app.state.placeholder_paths)
    by_owner = Counter(s.owner for s in nav.SCREENS if s.path in ph_paths)
    owners = " · ".join(f"{k} {v}" for k, v in sorted(by_owner.items()))
    consistent = n_ph == len(ph_paths) and marked <= {s.screen_id for s in nav.SCREENS if s.path in ph_paths}
    add("placeholder 0", n_ph == 0 and consistent,
        f"placeholder {n_ph}" + (f" ({owners})" if owners else "") + ("" if consistent else f" · /health {n_ph} ≠ 라우트 {len(ph_paths)} 또는 표식 {len(marked)}"))

    w = max(len(i) for i, _, _ in rows)
    print("G-03 화면 응답 (tools/check_routes.py) — 기대값은 정본 추출(ia.json + overrides)의 화면별 부서 칸")
    print("-" * 100)
    for item, ok, actual in rows:
        print(f"{G}  {item:<{w}}  {'PASS' if ok else 'FAIL'}  {actual}")
    print("-" * 100)
    for item, bad in details:
        print(f"[{item}] {len(bad)}")
        for b in bad[:40]:
            print(f"    - {b}")
        if len(bad) > 40:
            print(f"    … 외 {len(bad) - 40}")
    n_fail = sum(1 for _, ok, _ in rows if not ok)
    print(f"{G} 판정: {'PASS' if n_fail == 0 else 'FAIL'} (검사 {len(rows)} · 실패 {n_fail})")
    return 1 if n_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
