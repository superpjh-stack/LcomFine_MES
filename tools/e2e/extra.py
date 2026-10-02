"""QA3 — 브라우저 추가 실측: 로그아웃 · 권한 없음 화면 · 현황판이 서버 재기동/DB 끊김 뒤 스스로 돌아오는가 · DB 끊김 화면.

    uv run --with playwright python tools/e2e/extra.py

포트 8023 의 서버를 **이 스크립트가 직접** 띄우고 내린다(이미 떠 있으면 먼저 내린다 — QA3 전용 포트).
DB 끊김은 그 서버 프로세스의 LCOMFINE_PG_DSN 만 잘못된 값으로 준다. PostgreSQL 은 건드리지 않는다.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import BASE, OUT, ROOT, Session  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402
from probe import server_up  # noqa: E402

BAD_DSN = "postgresql:///lcomfine_db?host=/nonexistent-q3-socket&connect_timeout=2"


def kill_8023() -> None:
    out = subprocess.run(["lsof", "-ti", "tcp:8023", "-sTCP:LISTEN"], capture_output=True, text=True).stdout.split()
    for pid in out:
        os.kill(int(pid), signal.SIGTERM)
    for _ in range(20):
        if not server_up():
            return
        time.sleep(0.3)


def start(dsn: str | None = None) -> subprocess.Popen:
    env = dict(os.environ)
    if dsn:
        env["LCOMFINE_PG_DSN"] = dsn
    p = subprocess.Popen(["uv", "run", "uvicorn", "lcomfine.app.main:app", "--app-dir", "src", "--port", "8023"],
                         cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(40):
        try:
            import urllib.request
            urllib.request.urlopen(BASE + "/login", timeout=2)
            return p
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    raise RuntimeError("서버가 뜨지 않는다")


def stamp(page) -> str | None:
    try:
        return page.inner_text("#refreshed-at", timeout=1500)
    except Exception:  # noqa: BLE001 — 현황판이 아닌 화면(오류 화면)이다
        return None


def main() -> None:
    res: dict = {}
    kill_8023()
    srv = start()
    with sync_playwright() as p:
        b = p.chromium.launch()
        # (1) 로그아웃
        s = Session(b, "prod")
        s.login()
        with s.page.expect_navigation():
            s.page.click("form[action='/logout'] button")
        after = s.page.url.replace(BASE, "")
        s.goto("/job/orders")
        res["logout"] = {"after_click": after, "then_open_screen": s.page.url.replace(BASE, "")}
        s.close()
        # (2) 권한 없음 — 현장 계정: 메뉴 숨김 + 403 화면
        f = Session(b, "field")
        f.login()
        menu = f.page.inner_text("nav.side")
        st = f.goto("/trc/trace")
        f.shot("17-권한없음-현장계정-LOT추적403.png")
        res["forbidden"] = {"http": st, "message": "접근 권한이 없습니다" in f.text(),
                            "menu_hidden": [m for m in ("기준정보 관리", "LOT 추적", "시스템 관리") if m not in menu],
                            "menu_shown_wrongly": [m for m in ("기준정보 관리", "LOT 추적", "시스템 관리") if m in menu]}
        f.close()

        # (3) 현황판 — 서버가 잠깐 내려갔다 올라오면 스스로 돌아오는가
        bd = Session(b, "prod", device="board", viewport={"width": 1600, "height": 900})
        bd.login()
        bd.goto("/sta/board?device=board")
        first = stamp(bd.page)
        srv.terminate(); srv.wait()
        t0 = time.time()
        while time.time() - t0 < 40 and stamp(bd.page) is not None:     # 새로고침이 실패할 때까지
            bd.page.wait_for_timeout(1000)
        down_url, down_stamp = bd.page.url, stamp(bd.page)
        bd.shot("18-현황판-서버내려감.png")
        srv = start()
        t1 = time.time()
        back = None
        while time.time() - t1 < 75:
            bd.page.wait_for_timeout(1000)
            if stamp(bd.page) is not None and stamp(bd.page) != first:
                back = round(time.time() - t1, 1)
                break
        bd.shot("18-현황판-서버복구75초뒤.png")
        res["board_server_restart"] = {"first_stamp": first, "while_down": {"url": down_url, "stamp": down_stamp},
                                       "recovered_without_touch": back is not None, "seconds": back, "url_after": bd.page.url,
                                       "waited_after_restart_s": round(time.time() - t1, 1)}

        # (4) DB 끊김 — 로그인해 둔 세션(같은 세션 비밀)으로 서버만 잘못된 DSN 으로 다시 띄운다
        bd.goto("/sta/board?device=board")            # 현황판을 다시 정상으로
        ad = Session(b, "admin")
        ad.login()
        srv.terminate(); srv.wait()
        srv = start(BAD_DSN)
        st = ad.goto("/bas/items")
        ad.shot("19-DB끊김-품목관리-503.png")
        res["db_down"] = {"/bas/items": st, "message": "서비스 일시 중단" in ad.text()}
        st2 = ad.goto("/trc/trace/backward?no=S000")
        res["db_down"]["/trc/trace/backward"] = st2
        t2 = time.time()
        while time.time() - t2 < 40 and stamp(bd.page) is not None:
            bd.page.wait_for_timeout(1000)
        res["board_db_down"] = {"turned_to_error_page": stamp(bd.page) is None, "text": bd.text()[:60].replace("\n", " ")}
        bd.shot("19-DB끊김-현황판.png")
        srv.terminate(); srv.wait()
        srv = start()                                  # DB 가 돌아왔다
        t3 = time.time()
        back = None
        while time.time() - t3 < 75:
            bd.page.wait_for_timeout(1000)
            if stamp(bd.page) is not None:
                back = round(time.time() - t3, 1)
                break
        bd.shot("19-DB복구75초뒤-현황판.png")
        res["board_db_down"].update({"recovered_without_touch": back is not None, "seconds": back, "waited_s": round(time.time() - t3, 1)})
        st3 = ad.goto("/bas/items")
        res["db_down"]["after_recovery"] = st3
        b.close()
    (OUT / "_extra.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=1))
    print("서버(8023)는 띄운 채로 둔다 pid", srv.pid)


main()
