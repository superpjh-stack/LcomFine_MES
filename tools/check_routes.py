#!/usr/bin/env python
"""화면 라우트 검사 (G-03 · G-21 의 일부 · G-17 의 일부) — `make check-routes`.

  1. 중메뉴 32 화면 + 공통 3(메인·로그인·오류)이 전부 HTTP 200 인가 (관리자로 로그인한 상태)
  2. `_placeholder` 가 몇 건 남았는가 (0 이어야 G-03 PASS)
  3. 권한 표에서 `없음` 인 칸의 화면은 403 이고 메뉴에서 숨겨지는가 (설계도 §6 기준 5칸)
  4. 미로그인 — 브라우저 GET 은 /login 303, 그 밖은 401

판정은 이 출력으로만 한다. 종료코드: 0 = 전부 200 · placeholder 0 · 권한 위반 0, 그 밖은 1.
"""

from __future__ import annotations

import warnings

warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient`")

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from lcomfine.app.settings import get_settings  # noqa: E402 — .env 를 먼저 읽는다

if not get_settings().seed_password:
    sys.exit("LCOMFINE_SEED_PASSWORD 미설정 — 시드 계정으로 로그인할 수 없어 화면 검사를 할 수 없다 (`make setup` 으로 .env 를 만든다)")

from fastapi.testclient import TestClient  # noqa: E402

import design_doc  # noqa: E402
from lcomfine.app import nav  # noqa: E402
from lcomfine.app.main import app  # noqa: E402
from lcomfine.db import conn  # noqa: E402
from lcomfine.db.seed import USERS as SEED_USERS  # noqa: E402 — 시드 계정 (D-20): admin · prod · qc · field

PLACEHOLDER_MARKS = ('class="tag"', "미구현")
ADMIN = "admin"


def is_placeholder(html: str) -> bool:
    return all(m in html for m in PLACEHOLDER_MARKS)


def login(client: TestClient, login_id: str) -> bool:
    r = client.post("/login", data={"login_id": login_id, "password": get_settings().seed_password}, follow_redirects=False)
    return r.status_code == 303


def main() -> int:
    fails: list[str] = []
    if app.state.include_errors:
        fails.extend(f"라우터 임포트 실패 — {e}" for e in app.state.include_errors)

    # ── 4. 미로그인 ──
    anon = TestClient(app, raise_server_exceptions=False)
    r_html = anon.get(nav.SCREENS[0].path, headers={"accept": "text/html"}, follow_redirects=False)
    r_api = anon.get(nav.SCREENS[0].path)
    print(f"[미로그인] 브라우저 GET {r_html.status_code} → {r_html.headers.get('location', '-')} · 그 밖 {r_api.status_code}")
    if r_html.status_code != 303 or r_api.status_code != 401:
        fails.append(f"미로그인 기대 303/401, 실제 {r_html.status_code}/{r_api.status_code}")

    # ── 1·2. HTTP 200 · placeholder ──
    client = TestClient(app, raise_server_exceptions=False)
    if not login(client, ADMIN):
        print("[FAIL] 관리자(admin) 로그인 실패 — 공통 시드를 먼저 돌린다 (`make db-seed`)")
        return 1
    ok = 0
    placeholders: list[str] = []
    for s in nav.COMMON + nav.SCREENS:
        resp = client.get(s.path)
        if resp.status_code != 200:
            fails.append(f"{s.screen_id} {s.path} → HTTP {resp.status_code}")
            continue
        ok += 1
        if is_placeholder(resp.text):
            placeholders.append(f"{s.screen_id} {s.path} ({s.owner})")
    total = len(nav.COMMON) + len(nav.SCREENS)
    print(f"[HTTP 200] {ok} / {total}  (중메뉴 {len(nav.SCREENS)} + 공통 {len(nav.COMMON)})")
    by_owner: dict[str, int] = {}
    for p in placeholders:
        owner = p.rsplit("(", 1)[1].rstrip(")")
        by_owner[owner] = by_owner.get(owner, 0) + 1
    print(f"[placeholder] 잔여 {len(placeholders)} 건" + (" — " + " · ".join(f"{k} {v}" for k, v in sorted(by_owner.items())) if by_owner else ""))
    for p in placeholders:
        print(f"    {p}")

    # ── 3. 권한 없음 = 403 + 메뉴 숨김 (기대값은 설계도 §6) ──
    access = design_doc.access()
    role_code = {r["role_name"]: r["role_code"] for r in conn.q("select role_code, role_name from sys_role")}
    # 역할마다 **시드 계정**으로 로그인한다(D-20). DB 에서 "그 역할의 아무 계정" 을 고르면 다른 사람이 만든 계정
    # (비밀번호가 시드 비밀번호가 아니다)이 끼었을 때 로그인이 안 되어 거짓 FAIL 이 난다.
    login_of = {code: login_id for login_id, _name, code in SEED_USERS}
    checked, bad = 0, []
    clients: dict[str, TestClient] = {}
    for row in access["rows"]:
        menu = nav.menu_by_name(row["menu"])
        for role_name, cell in zip(access["roles"], row["cells"]):
            code = role_code.get(role_name)
            if code is None or code not in login_of:
                bad.append(f"{role_name}: 역할 또는 계정 없음")
                continue
            c = clients.get(code)
            if c is None:
                c = TestClient(app, raise_server_exceptions=False)
                if not login(c, login_of[code]):
                    bad.append(f"{role_name}({login_of[code]}) 로그인 실패")
                clients[code] = c
            want = 403 if cell == "없음" else 200
            for s in menu.screens:
                got = c.get(s.path).status_code
                checked += 1
                if got != want:
                    bad.append(f"{role_name} → {s.screen_id} {s.path} 기대 {want}, 실제 {got}")
            if cell == "없음":
                home = c.get("/").text
                shown = [s.path for s in menu.screens if f'href="{s.path}"' in home]
                if shown:
                    bad.append(f"{role_name}: `없음` 인 {menu.name} 이 메뉴에 보인다 {shown[:2]}")
    n_none = sum(cell == "없음" for row in access["rows"] for cell in row["cells"])
    print(f"[RBAC] 역할 4 × 화면 32 = {checked} 건 조회 검사 (없음 {n_none}칸 → 403 + 메뉴 숨김) · 위반 {len(bad)}")
    for b in bad:
        print(f"    {b}")
    fails.extend(bad)

    print()
    if fails:
        print(f"FAIL — {len(fails)} 건")
        for f in fails:
            print(f"  - {f}")
        return 1
    if placeholders:
        print(f"FAIL(placeholder) — 전 화면 200 이나 placeholder {len(placeholders)} 건 남음 (G-03 미충족)")
        return 1
    print(f"PASS — 중메뉴 {len(nav.SCREENS)} + 공통 {len(nav.COMMON)} 전부 200 · placeholder 0 · 권한 위반 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
