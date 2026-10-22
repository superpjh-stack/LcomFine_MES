"""메뉴 단일 소스 — 묶음 8 · 대메뉴 17 · 화면 66 + 공통 2 (로그인 · 오류).

정본은 `docs/엘컴화인_MES_기획서_2026-10-21.html` 이다. 이름과 순서는 정본 그대로이며,
`tools/check_trace.py` 게이트가 `contracts/ia.json` + overrides (`tools/design_doc.effective()`) 와 글자 단위로 대조한다.
이름을 여기서 바꾸면 게이트가 떨어진다. 앱은 정본이나 ia.json 을 런타임에 읽지 않는다 — 이 파일이 정적 코드다.

이 파일이 정하는 것(정본에 없음 — D-507): 경로(slug) · 담당 개발. 화면 ID · 이름 · 유형은 정본 그대로 옮겼다.
경로는 이 파일이 유일한 출처다. 개발자는 `nav.path_of('BAS-010')` 로 쓴다. 문자열로 다시 적지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass

SYSTEM_NAME = "엘컴화인 MES"


@dataclass(frozen=True)
class Screen:
    screen_id: str            # 화면 ID (예 BAS-010) 또는 공통 화면 키(login · error)
    name: str                 # 화면명 — 정본 글자 그대로
    menu_code: str            # 대메뉴 코드 (공통 화면은 "")
    menu: str                 # 대메뉴명
    bundle: str               # 묶음 키 (s0~s7)
    module: str               # 라우터 모듈 (src/lcomfine/app/routers/<module>.py)
    slug: str
    path: str
    owner: str                # 담당
    kind: str                 # 정본 유형 (조회 · 등록 · 목록·등록 · 리포트 · 처리 · 설정 · 등록·출력 · 출력 · SSO)
    common: bool = False


@dataclass(frozen=True)
class Menu:
    code: str                 # HOME · BAS · STD · WO · MAT · PRD · INS · QC · INV · SHP · COL · TRK · LOT · PRP · RPT · DOC · SYS
    name: str
    bundle: str               # 묶음 키
    module: str
    owner: str
    screens: tuple[Screen, ...]


# (키, 이름, 설명) — 정본 순서
BUNDLES: tuple[tuple[str, str, str], ...] = (
    ('s0', '⓪ 내 업무', '로그인하면 처음 보는 곳: 내 부서가 처리할 일과 알림'),
    ('s1', '① 기준', '품목·거래처·창고, 제품별 인쇄 사양'),
    ('s2', '② 수주·지시', '생산의뢰(수주) → 생산지시 → 순서·진행'),
    ('s3', '③ 자재·생산', '원자재 입고 → 불출 → 생산 → 공정 검사 → 제품 입고'),
    ('s4', '④ 품질·재고', '입고·제품 검사 판정, LOT 재고'),
    ('s5', '⑤ 출하·수금', '출하 지시·확정 → ERP 수금 확인'),
    ('s6', '⑥ 추적·분석', '통합 조회, LOT 추적, 생산 보고서, 대시보드'),
    ('s7', '⑦ 지원', '문서관리(SSO), 시스템'),
)

FLOW_IDS: tuple[str, ...] = ('WO-010', 'WO-020', 'MAT-020', 'PRD-010', 'MAT-030', 'SHP-020', 'COL-010')

# (묶음 키, 코드, 대메뉴명, 담당, [(화면 ID, 화면명, 유형, slug)]) — 정본 순서
_SPEC: list[tuple[str, str, str, str, list[tuple[str, str, str, str]]]] = [
    ('s0', 'HOME', '내 업무', '개발1', [
        ('HOME-010', '내 할 일', '조회', ''),
        ('HOME-020', '알림함', '조회', 'notifications'),
        ('HOME-030', '알림 설정', '설정', 'notification-settings'),
    ]),
    ('s1', 'BAS', '기준정보', '개발1', [
        ('BAS-010', '품목 관리', '목록·등록', 'items'),
        ('BAS-020', '거래처 관리', '목록·등록', 'customers'),
        ('BAS-030', '창고·위치 관리', '목록·등록', 'warehouses'),
    ]),
    ('s1', 'STD', '인쇄 기준', '개발1', [
        ('STD-010', '제조사양기준서', '목록·등록', 'spec-sheets'),
        ('STD-020', '표준관리', '목록·등록', 'standards'),
        ('STD-030', '판관리', '목록·등록', 'plates'),
        ('STD-040', '시안등록', '등록', 'artworks'),
        ('STD-050', '표준견본서', '등록·출력', 'sample-sheets'),
        ('STD-060', '예외제품관리', '목록·등록', 'exception-items'),
    ]),
    ('s2', 'WO', '작업지시', '개발1', [
        ('WO-010', '생산의뢰서', '등록', 'requests'),
        ('WO-020', '생산지시서', '등록·출력', 'orders'),
        ('WO-030', '생산순서관리', '처리', 'sequence'),
        ('WO-040', '공정상태', '조회', 'status'),
    ]),
    ('s3', 'MAT', '자재·입고', '개발2', [
        ('MAT-010', '원자재 입고', '등록', 'receipts'),
        ('MAT-020', '불출', '등록', 'issues'),
        ('MAT-030', '제품 입고', '등록', 'product-receipts'),
        ('MAT-040', '입고·불출 내역', '조회', 'history'),
    ]),
    ('s3', 'PRD', '생산일보', '개발2', [
        ('PRD-010', '생산일보', '등록', 'daily'),
        ('PRD-020', '생산일보출력', '출력', 'daily/print'),
        ('PRD-030', '생산일보현황', '조회', 'status'),
        ('PRD-040', '생산지시서 대비 생산 로스율', '리포트', 'loss-rate'),
    ]),
    ('s3', 'INS', '검사일보', '개발2', [
        ('INS-010', '검사일보', '등록', 'daily'),
        ('INS-020', '검사일보출력', '출력', 'daily/print'),
        ('INS-030', '검사일보현황', '조회', 'status'),
        ('INS-040', '생산지시서 대비 검사 로스율', '리포트', 'loss-rate'),
    ]),
    ('s4', 'QC', '품질 검사', '개발2', [
        ('QC-010', '입고검사', '등록', 'incoming'),
        ('QC-020', '제품검사 판정', '등록', 'product'),
        ('QC-030', '검사 이력', '조회', 'history'),
    ]),
    ('s4', 'INV', '재고', '개발2', [
        ('INV-010', 'LOT별 재고 조회', '조회', 'stock'),
        ('INV-020', '재고 이동', '등록', 'moves'),
        ('INV-030', '재고 조정·실사', '등록', 'adjustments'),
    ]),
    ('s5', 'SHP', '출하', '개발3', [
        ('SHP-010', '출하 지시', '등록', 'orders'),
        ('SHP-020', '출하 확정', '처리', 'confirm'),
        ('SHP-030', '출하 이력', '조회', 'history'),
    ]),
    ('s5', 'COL', '수금리포트', '개발3', [
        ('COL-010', 'ERP 수금현황 업로드', '등록', 'uploads'),
        ('COL-020', '업로드 이력', '조회', 'upload-history'),
        ('COL-030', '거래처 코드 매핑', '목록·등록', 'customer-map'),
        ('COL-040', '수금 현황 조회', '조회', 'collections'),
        ('COL-050', '거래처별 미수 조회', '조회', 'receivables'),
        ('COL-060', '미수 연령 조회', '조회', 'aging'),
        ('COL-070', '출하 대비 수금 조회', '조회', 'shipment-vs-collection'),
    ]),
    ('s6', 'TRK', '통합 조회', '개발1', [
        ('TRK-010', '주문 진행 조회', '조회', 'orders'),
        ('TRK-020', '납기 현황', '조회', 'due'),
        ('TRK-030', '거래처 종합 조회', '조회', 'customers'),
    ]),
    ('s6', 'LOT', 'LOT 추적', '개발2', [
        ('LOT-010', '정방향 추적', '조회', 'forward'),
        ('LOT-020', '역방향 추적', '조회', 'backward'),
    ]),
    ('s6', 'PRP', '생산 보고서', '개발3', [
        ('PRP-010', '월별 가동률', '리포트', 'utilization'),
        ('PRP-020', '기계별통계', '리포트', 'machines'),
        ('PRP-030', '생산완료집계', '리포트', 'completion'),
    ]),
    ('s6', 'RPT', '대시보드', '개발3', [
        ('RPT-010', '수주 리포트', '리포트', 'orders'),
        ('RPT-020', '생산 리포트', '리포트', 'production'),
        ('RPT-030', '품질 리포트', '리포트', 'quality'),
        ('RPT-040', '재고·창고 리포트', '리포트', 'inventory'),
        ('RPT-050', '출하 리포트', '리포트', 'shipment'),
        ('RPT-060', '수금 리포트', '리포트', 'collection'),
        ('RPT-070', '주문 흐름 리포트', '리포트', 'order-flow'),
        ('RPT-080', '경영 요약', '리포트', 'summary'),
    ]),
    ('s7', 'DOC', '문서관리', '개발1', [
        ('DOC-010', '문서관리 바로가기', '외부 연계(SSO)', 'go'),
        ('DOC-020', '문서관리 계정 매핑', '목록·등록', 'account-map'),
    ]),
    ('s7', 'SYS', '시스템', '개발1', [
        ('SYS-010', '사용자 관리', '목록·등록', 'users'),
        ('SYS-020', '역할·권한', '설정', 'roles'),
        ('SYS-030', '공통코드', '설정', 'codes'),
        ('SYS-040', '로그', '조회', 'logs'),
    ]),
]


def _build() -> tuple[Menu, ...]:
    menus: list[Menu] = []
    for bundle, code, name, owner, subs in _SPEC:
        module = code.lower()
        screens = tuple(
            Screen(screen_id=sid, name=sname, menu_code=code, menu=name, bundle=bundle, module=module, slug=slug,
                   path=f"/{module}/{slug}" if slug else "/", owner=owner, kind=kind)
            for sid, sname, kind, slug in subs
        )
        menus.append(Menu(code=code, name=name, bundle=bundle, module=module, owner=owner, screens=screens))
    return tuple(menus)


MENUS: tuple[Menu, ...] = _build()
SCREENS: tuple[Screen, ...] = tuple(s for m in MENUS for s in m.screens)

# ── 공통 화면 2 — 권한 표 밖 ──
COMMON: tuple[Screen, ...] = (
    Screen("login", "로그인", "", "공통", "", "home", "login", "/login", "아키텍트", "조회", common=True),
    Screen("error", "오류", "", "공통", "", "home", "error", "/error", "아키텍트", "조회", common=True),
)

ALL: tuple[Screen, ...] = SCREENS + COMMON

#: main.py 가 include 하는 라우터 모듈 순서 (대메뉴 순서)
MODULES: tuple[str, ...] = tuple(m.module for m in MENUS)
MODULE_OWNER: dict[str, str] = {m.module: m.owner for m in MENUS}

_BY_ID: dict[str, Screen] = {s.screen_id: s for s in ALL}
_BY_PATH: dict[str, Screen] = {s.path: s for s in ALL}
_MENU_BY_CODE: dict[str, Menu] = {m.code: m for m in MENUS}


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


def screens_of(module: str) -> list[Screen]:
    return [s for s in SCREENS if s.module == module]


def menu_tree() -> list[dict]:
    """정본 순서의 묶음 > 대메뉴 > 화면. [{bundle: (키, 이름, 설명), menus: [Menu, ...]}, ...]"""
    return [{"bundle": b, "menus": [m for m in MENUS if m.bundle == b[0]]} for b in BUNDLES]


def sidebar_items() -> list[dict]:
    """좌측 메뉴 렌더링용 — `menu_tree()` 와 같은 순서·모양."""
    return menu_tree()


#: 정본 업무 흐름 7 단계 (화면 ID)
FLOW: tuple[str, ...] = FLOW_IDS


def validate() -> None:
    ids = [s.screen_id for s in ALL]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        raise ValueError(f"화면 ID 중복: {dup}")
    paths = [s.path for s in ALL]
    dup = sorted({p for p in paths if paths.count(p) > 1})
    if dup:
        raise ValueError(f"경로 중복: {dup}")
    for s in SCREENS:
        if any(c.isspace() or c.isupper() for c in s.slug):
            raise ValueError(f"{s.screen_id} 의 slug 에 공백·대문자가 있다: {s.slug!r}")
    for m in MENUS:
        if not m.screens:
            raise ValueError(f"대메뉴 {m.code} 에 화면이 없다")
    for f in FLOW:
        if f not in {s.screen_id for s in SCREENS}:
            raise ValueError(f"FLOW 의 {f} 는 SCREENS 에 없다")


validate()
