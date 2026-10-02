"""메뉴 단일 소스 — 묶음 4 · 대메뉴 12 · 중메뉴 32 + 공통 3 (메인 · 로그인 · 오류).

**이름과 순서는 설계도 §5 IA 구성도 그대로다.** `tools/check_trace.py` 가 설계도의 `.ia-menu` 를 파싱해
이 파일과 글자 단위로 대조한다(G-01). 이름을 여기서 바꾸면 게이트가 떨어진다.

이 파일이 정하는 것(설계도에 없음 — 가설 D-08·D-19·D-22):
  · 대메뉴 코드(= 라우터 모듈 = 권한 표의 `menu_code`)  · 중메뉴 화면 ID · 경로  · 담당 개발  · 중메뉴별 채널

**경로는 이 파일이 유일한 출처다.** 개발자는 `nav.path_of('BAS-01')` 로 쓴다. 문자열로 다시 적지 않는다.
`contracts/screen-map.md` §1 은 이 파일의 렌더본이다(`make contracts`).
"""

from __future__ import annotations

from dataclasses import dataclass

SYSTEM_NAME = "엘컴화인 MES"

# ── 채널 4 (설계도 §4 · §6 「주로 쓰는 채널」 표기 그대로) ──
WEB, POP, MOBILE, BOARD = "관리자 Web", "현장 POP", "모바일", "현황판"
CHANNELS: tuple[str, ...] = (WEB, POP, MOBILE, BOARD)
#: `?device=` 값 → 채널명 (D-19)
DEVICE_CHANNEL: dict[str, str] = {"web": WEB, "pop": POP, "mobile": MOBILE, "board": BOARD}

# ── 묶음 4 (설계도 `.ia-gname` 순서) ──
GROUPS: tuple[str, ...] = ("기준 · 지시", "현장 실행", "품질 · 출하", "조회 · 관리")


@dataclass(frozen=True)
class Screen:
    screen_id: str            # 중메뉴 화면 ID (예 BAS-01) 또는 공통 화면 키(home · login · error)
    name: str                 # 중메뉴명 — 설계도 `<li>` 글자 그대로
    menu_code: str            # 대메뉴 코드 = 라우터 모듈 대문자 = sys_permission.menu_code
    menu: str                 # 대메뉴명 — 설계도 `<h4>` 글자 그대로
    group: str                # 묶음
    module: str               # 라우터 모듈 (src/lcomfine/app/routers/<module>.py)
    slug: str
    path: str
    owner: str                # 담당 (D-22)
    channels: tuple[str, ...]
    common: bool = False


@dataclass(frozen=True)
class Menu:
    code: str                 # BAS · PRT · JOB · POP · MAT · CLR · RLL · QUA · SHP · TRC · STA · SYS
    name: str
    group: str
    fn_count: int             # 설계도 `<h4><span>` 의 기능 수 (2안 기준)
    module: str
    owner: str
    channels: tuple[str, ...]  # 설계도 §6 「주로 쓰는 채널」
    screens: tuple[Screen, ...]


# (묶음, 코드, 대메뉴명, 기능 수, 담당, 대메뉴 채널, [(중메뉴명, 슬러그, 중메뉴 채널)])
_SPEC: list[tuple[str, str, str, int, str, tuple[str, ...], list[tuple[str, str, tuple[str, ...]]]]] = [
    ("기준 · 지시", "BAS", "기준정보 관리", 20, "개발1", (WEB,), [
        ("품목 관리", "items", (WEB,)),
        ("고객 관리", "customers", (WEB,)),
        ("공정 관리", "processes", (WEB,)),
        ("설비 관리", "equipment", (WEB,)),
        ("불량코드 관리", "defect-codes", (WEB,)),
    ]),
    ("기준 · 지시", "PRT", "인쇄 기준 관리", 12, "개발1", (WEB,), [
        ("판사양 관리", "plates", (WEB,)),
        ("아니록스 관리", "anilox", (WEB,)),
        ("잉크조성 관리", "inks", (WEB,)),
    ]),
    ("기준 · 지시", "JOB", "작업지시 관리", 7, "개발1", (WEB,), [
        ("작업지시", "orders", (WEB,)),
        ("Job-Lot-Roll 매핑", "mapping", (WEB,)),
    ]),
    ("현장 실행", "POP", "생산 실적 (POP)", 8, "개발2", (POP,), [
        ("작업 실적", "work", (POP,)),
        ("정지 · 폐기", "stops", (POP,)),
        ("롤 라벨", "roll-labels", (POP,)),
    ]),
    ("현장 실행", "MAT", "자재 · 입고", 8, "개발2", (POP, WEB), [
        ("입고", "receipts", (POP, WEB)),
        ("입고검사", "inspections", (POP, WEB)),
        ("원재료 LOT", "lots", (WEB, POP)),
        ("자재 투입", "inputs", (POP,)),
    ]),
    ("현장 실행", "CLR", "조색 기록", 5, "개발2", (POP,), [
        ("조색 기록", "records", (POP,)),
    ]),
    ("현장 실행", "RLL", "후가공 · 슬리팅 롤 이력", 7, "개발2", (POP,), [
        ("후가공", "finishing", (POP,)),
        ("슬리팅", "slitting", (POP,)),
        ("롤 이력", "history", (POP,)),
    ]),
    ("품질 · 출하", "QUA", "품질 검사 기록", 6, "개발3", (WEB, POP), [
        ("검사 결과", "inspections", (WEB, POP)),
        ("불량 집계", "defect-stats", (WEB,)),
    ]),
    ("품질 · 출하", "SHP", "출하", 7, "개발3", (POP, WEB), [
        ("출하", "shipments", (POP, WEB)),
        ("출하 승인", "approvals", (WEB,)),
        ("COA", "coa", (WEB,)),
    ]),
    ("조회 · 관리", "TRC", "LOT 추적", 3, "개발3", (WEB, MOBILE), [
        ("추적 (정방향, 역방향, LOT 검색)", "trace", (WEB, MOBILE)),
    ]),
    ("조회 · 관리", "STA", "실적 현황", 4, "개발3", (WEB, BOARD, MOBILE), [
        ("집계 (생산, 품질, 납기)", "summary", (WEB, MOBILE)),
        ("현황판", "board", (BOARD,)),
    ]),
    ("조회 · 관리", "SYS", "시스템 관리", 7, "개발1", (WEB,), [
        ("사용자", "users", (WEB,)),
        ("권한", "permissions", (WEB,)),
        ("로그", "logs", (WEB,)),
    ]),
]


def _build() -> list[Menu]:
    menus: list[Menu] = []
    for group, code, name, fn_count, owner, channels, subs in _SPEC:
        module = code.lower()
        screens = tuple(
            Screen(screen_id=f"{code}-{i:02d}", name=sub, menu_code=code, menu=name, group=group, module=module,
                   slug=slug, path=f"/{module}/{slug}", owner=owner, channels=sub_channels)
            for i, (sub, slug, sub_channels) in enumerate(subs, start=1)
        )
        menus.append(Menu(code=code, name=name, group=group, fn_count=fn_count, module=module, owner=owner,
                          channels=channels, screens=screens))
    return menus


MENUS: list[Menu] = _build()
SCREENS: list[Screen] = [s for m in MENUS for s in m.screens]

# ── 공통 화면 3 (goal.md G-03 "공통(로그인·메인·오류)") — 권한 표 밖. 로그인한 누구나 메인을 연다 ──
COMMON: list[Screen] = [
    Screen("home", "메인", "", "공통", "공통", "home", "", "/", "개발1", CHANNELS, common=True),
    Screen("login", "로그인", "", "공통", "공통", "home", "login", "/login", "아키텍트", CHANNELS, common=True),
    Screen("error", "오류", "", "공통", "공통", "home", "error", "/error", "아키텍트", CHANNELS, common=True),
]

ALL: list[Screen] = COMMON + SCREENS

#: main.py 가 include 하는 라우터 모듈 순서
MODULES: list[str] = ["home"] + [m.module for m in MENUS]
MODULE_OWNER: dict[str, str] = {"home": "개발1", **{m.module: m.owner for m in MENUS}}

_BY_ID: dict[str, Screen] = {s.screen_id: s for s in ALL}
_BY_PATH: dict[str, Screen] = {s.path: s for s in ALL}
_MENU_BY_CODE: dict[str, Menu] = {m.code: m for m in MENUS}
_MENU_BY_NAME: dict[str, Menu] = {m.name: m for m in MENUS}


def by_id(screen_id: str) -> Screen:
    if screen_id not in _BY_ID:
        raise KeyError(f"nav 에 없는 화면 ID: {screen_id}")
    return _BY_ID[screen_id]


def by_path(path: str) -> Screen | None:
    return _BY_PATH.get(path)


def path_of(screen_id: str) -> str:
    """개발자는 경로를 문자열로 적는 대신 이 함수를 쓴다."""
    return by_id(screen_id).path


def menu(code: str) -> Menu:
    if code not in _MENU_BY_CODE:
        raise KeyError(f"nav 에 없는 대메뉴 코드: {code}")
    return _MENU_BY_CODE[code]


def menu_by_name(name: str) -> Menu:
    if name not in _MENU_BY_NAME:
        raise KeyError(f"nav 에 없는 대메뉴명: {name}")
    return _MENU_BY_NAME[name]


def screens_of(module: str) -> list[Screen]:
    return [s for s in SCREENS if s.module == module]


def screen_by_names(menu_name: str, screen_name: str) -> Screen:
    """(대메뉴명, 중메뉴명) → 화면. `function-list.md` 의 두 열을 화면에 잇는 데 쓴다."""
    for s in menu_by_name(menu_name).screens:
        if s.name == screen_name:
            return s
    raise KeyError(f"nav 에 없는 중메뉴: {menu_name} > {screen_name}")


def menu_tree() -> list[dict]:
    """좌측 메뉴 렌더링용 — 묶음 4 > 대메뉴 > 중메뉴. 권한에 따른 숨김은 `rbac.visible_menu` 가 한다."""
    return [{"group": g, "menus": [m for m in MENUS if m.group == g]} for g in GROUPS]


def _selfcheck() -> None:
    if len(GROUPS) != 4 or len(MENUS) != 12 or len(SCREENS) != 32:
        raise AssertionError(f"묶음 4 · 대메뉴 12 · 중메뉴 32 이어야 한다 — 실제 {len(GROUPS)} · {len(MENUS)} · {len(SCREENS)}")
    if sum(m.fn_count for m in MENUS) != 94:
        raise AssertionError(f"화면 기능 합은 94 이어야 한다 — 실제 {sum(m.fn_count for m in MENUS)}")
    paths = [s.path for s in ALL]
    dup = sorted({p for p in paths if paths.count(p) > 1})
    if dup:
        raise AssertionError(f"경로 중복: {dup}")
    if {m.group for m in MENUS} != set(GROUPS):
        raise AssertionError("대메뉴가 없는 묶음이 있다")
    for m in MENUS:
        for s in m.screens:
            if not set(s.channels) <= set(CHANNELS):
                raise AssertionError(f"{s.screen_id} 의 채널이 4채널 밖이다: {s.channels}")


_selfcheck()
