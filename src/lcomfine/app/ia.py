"""IA(정보 구조) 설명 — 메인 화면(`/`)이 보여 주는 설계도 요약. 담당 개발1 (D-419).

여기 글은 전부 **설계도(그림 1~5 · 표 3)에서 옮긴 것**이다 — 앱은 설계도 파일을 읽지 않으므로 글자를 여기에 둔다.
설계도와 어긋나면 `tests/test_dev1_ia.py` 가 잡는다(프로세스 표는 `tools/design_doc.processes()` 와 글자 단위로 대조).
메뉴 ↔ 프로세스, 저장소 ↔ 테이블은 적지 않고 계약(`contracts`)에서 센다 — 같은 목록을 두 곳에 두지 않는다.
설계도에 없는 것(확장 · 결정 번호)은 그렇게 표시한다. 어떤 테이블에도 쓰지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import contracts, nav

# ── 설계도 §2 「프로세스별 입력과 출력」 표 — 글자 그대로 ───────────────────────────────────────────
@dataclass(frozen=True)
class Process:
    code: str                 # P1~P10
    name: str
    actor: str                # 입력 주체
    inputs: str               # 입력
    writes: tuple[str, ...]   # 쓰는 저장소
    reads: tuple[str, ...]    # 참조
    outputs: str              # 출력물


PROCESSES: tuple[Process, ...] = (
    Process("P1", "기준정보 · 인쇄 기준", "생산관리자", "품목, 고객, 공정, 설비, 불량코드, 판사양, 아니록스, 잉크조성", ("D1",), (), "없음"),
    Process("P2", "작업지시", "생산관리자", "Job 등록, Job-Lot-Roll 매핑", ("D2",), ("D1",), "작업지시서"),
    Process("P3", "자재 입고", "자재 담당, 품질 담당", "입고 등록, 입고검사 결과", ("D3",), ("D1",), "원재료 LOT 라벨"),
    Process("P4", "조색 기록", "현장 작업자", "색상값, 배합비", ("D4",), ("D2",), "없음"),
    Process("P5", "생산 실적 (인쇄)", "현장 작업자", "작업 시작·종료, 정지, 폐기, 자재 투입 스캔", ("D5", "D6"), ("D2", "D3"), "인쇄 롤 라벨"),
    Process("P6", "후가공 · 슬리팅", "현장 작업자", "가공 실적, 슬리팅 분할, splice", ("D6",), ("D2", "D6"), "롤 라벨"),
    Process("P7", "품질 검사", "품질 담당", "ΔE, 불량 유형·위치, 불량 롤 번호", ("D7",), ("D6",), "불량 유형별 집계"),
    Process("P8", "출하", "출하 담당", "출하 등록, 출하 승인, 롤 스캔", ("D8",), ("D6", "D7"), "COA"),
    Process("P9", "LOT 추적", "생산관리자, 품질 담당", "LOT 번호 또는 롤 번호", (), ("D3", "D5", "D6", "D7", "D8"), "정방향·역방향 추적 결과"),
    Process("P10", "실적 현황", "생산관리자", "기간, 품목", (), ("D2", "D5", "D7", "D8"), "생산·품질·납기 집계, 현황판"),
)
PROCESS_BY_CODE: dict[str, Process] = {p.code: p for p in PROCESSES}

#: 설계도 §2 그림의 원칙 문장
PROCESS_RULE = ("프로세스끼리는 직접 주고받지 않는다. 각자 자기 저장소에 쓰고, 다음 공정은 Job-Lot-Roll 키로 앞 저장소를 참조한다. "
                "그래서 어느 공정에서 시작해도 앞뒤를 따라갈 수 있다. 인쇄(P5)는 생산 실적과 인쇄 롤을 함께 만들기 때문에 D5 와 D6 두 곳에 쓴다.")

# ── 설계도 §2 저장소 여덟 + 공통 · 확장 ───────────────────────────────────────────────────────────
STORES: tuple[tuple[str, str], ...] = (
    ("D1", "기준정보"), ("D2", "작업지시"), ("D3", "원재료 LOT"), ("D4", "조색 기록"),
    ("D5", "생산 실적"), ("D6", "Roll·계보"), ("D7", "품질 검사"), ("D8", "출하"),
    ("SYS", "공통 (로그인 · 권한 · 접근 로그 · 채번 · 이관 기록)"),
    ("EXT", "확장 — 설계도 밖 (영업관리 · D-418)"),
)

# ── 설계도 §1 DFD — 사람 넷이 넣는 것과 받는 것 ─────────────────────────────────────────────────
@dataclass(frozen=True)
class Person:
    name: str
    area: str                 # 그림의 묶음 이름
    gives: str                # 넣는 데이터 (화살표 윗줄)
    gets: str                 # 받는 데이터 (아랫줄)


PEOPLE: tuple[Person, ...] = (
    Person("생산관리자", "기준 · 지시 · 현황", "기준정보, 인쇄 기준, 작업지시", "실적 현황, LOT 추적 결과"),
    Person("현장 작업자", "POP · 스마트패드", "시작·종료, 정지·폐기, 롤 스캔", "작업지시, 롤 라벨"),
    Person("품질 담당", "입고검사 · 검사 · 조색", "입고검사·검사 결과, 조색 기록", "검사 이력, 불량 집계"),
    Person("자재 · 출하 담당", "입고 · 출하", "입고 등록, 출하 등록·승인", "원재료 LOT 라벨, COA"),
)
#: 설계도 §1 바깥 — 시스템 둘, 장치 하나
OUTSIDE: tuple[tuple[str, str], ...] = (
    ("라벨 프린터", "LOT · 롤 라벨을 찍는다 — 보유 여부 · 규격 확인 필요"),
    ("ERP", "연계 방식 · 범위 확인 필요 (미확정)"),
    ("기존 설치형 MES", "2안: 기준정보 · 작업지시 · 과거 이력을 1회 이관하고 종료 (이관 배치 6 · B-MIG-01~06)"),
)
#: 설계도 §4 채널 — 같은 앱, 같은 DB, 레이아웃만 다르다
CHANNEL_NOTES: dict[str, str] = {
    nav.WEB: "PC 브라우저",
    nav.POP: "스마트패드 · 바코드 스캐너 연결",
    nav.MOBILE: "조회 중심",
    nav.BOARD: "현장 대형 화면 · 자동 새로고침",
}
ROLE_NOTE = "설계도 §6 은 기획서의 계정 구분(관리자 · 생산 · 품질 · 현장)을 대메뉴에 대입한 제안안이다. 실제 권한은 권한 표(시스템 관리 > 권한)의 지금 값이다."

# ── 설계도 §3 Job-Lot-Roll 계보 ────────────────────────────────────────────────────────────────
LINEAGE_TEXT = ("롤 하나가 만들어질 때마다 어떤 롤이나 원재료 LOT 에서 나왔는지를 계보(roll_genealogy)에 부모 → 자식 한 줄씩 기록한다. "
                "화살표 하나가 한 행이다. 추적은 이 기록을 따라가는 조회일 뿐이다 — 정방향은 원재료 LOT 에서 출하 롤까지, 역방향은 출하 롤에서 원재료 LOT 까지.")
DONE_CRITERION = "완료 기준: 실제 생산 LOT 으로 출하 롤 하나에서 원재료 LOT 까지 거슬러 올라갈 수 있어야 한다."
#: (관계 이름 = roll_genealogy.relation, 부모 → 자식, 만드는 프로세스, 설명)
RELATIONS: tuple[tuple[str, str, str, str], ...] = (
    ("투입", "원재료 LOT → 인쇄 롤", "P5", "자재 투입 스캔 — 원재료 LOT 하나가 인쇄 롤 여럿에 들어갈 수 있다"),
    ("후가공", "인쇄 롤 → 후가공 롤", "P6", "1:1 가공"),
    ("splice", "인쇄 롤 N → 후가공 롤 1", "P6", "여러 롤을 하나로 잇는다 (N:1)"),
    ("슬리팅", "후가공 롤 1 → 슬리팅 롤 N", "P6", "하나를 여럿으로 나눈다 (1:N)"),
    ("출하", "롤 → 출하 LOT", "P8", "롤 스캔으로 출하에 묶는다 — 출하 기능이 계보에 쓰는 유일한 행 (D-12)"),
)

# ── 설계도 §0 · §4 범위와 구성 ───────────────────────────────────────────────────────────────
SYSTEM_TEXT = "웹 애플리케이션 하나와 DB 하나로 구성하고, 화면은 네 채널로 열리지만 뒤에서는 같은 애플리케이션과 같은 DB 를 쓴다. 바깥과 닿는 곳은 라벨 프린터 · ERP · 기존 MES 뿐이다."
SCOPE_OUT = "설비 PLC 실시간 수집, 비전 검사 연동, AI 분석은 범위 밖이다 — 메뉴 · 엔드포인트 · 테이블 어디에도 없다. 설비는 기준정보(설비 관리)까지."

# ── 설계도 §7 확인 필요 — 정해지면 그림의 점선과 「확인 필요」가 사라진다 ──────────────────────────
OPEN_ITEMS: tuple[tuple[str, str, str], ...] = (
    ("1안 / 2안 판정", "기존 MES 의 실제 사용 메뉴와 데이터 접근 경로.", "이 시스템은 2안(전체 개발 · 1회 이관) 기준으로 만든다"),
    ("ERP 연계", "연계할 데이터와 방식.", "미확정 — 공용 모듈 erp 는 경계만 둔다"),
    ("운영 환경", "사내 서버인지 클라우드인지. 정해지면 물리 구성도를 추가한다.", "미확정 — Docker 이미지로 어디든 올릴 수 있게 둔다 (D-31)"),
    ("현장 장치", "바코드 스캐너와 라벨 프린터의 보유 여부와 규격, 롤 바코드 사용 여부.", "미수집"),
    ("채번 규칙", "작업지시 번호와 LOT 번호의 현재 규칙. Job-Lot-Roll 키 설계의 전제다.", "가설 — 형식은 채번 규칙 행(sys_number_rule)이라 규칙을 받으면 행만 바꾼다 (D-05)"),
    ("역할 구분", "관리자, 생산, 품질, 현장 네 역할로 충분한지, 자재와 출하를 따로 둘지.", "미확정 (D-06) — 영업 역할도 같은 물음 (D-418)"),
    ("범위 경계", "LOT 추적과 실적 현황을 이 프로젝트에 둘지. 설비 자동 수집과 AI 분석은 범위 밖으로 두었다.", "둘 다 넣었다 — 어떤 테이블에도 쓰지 않는 조회 (P9 · P10)"),
)

# ── 설계도 밖 확장 (D-418) — 설계도에는 없는 것 ───────────────────────────────────────────────────
EXT_STEP_NAME = "수주"
EXT_TEXT = "영업관리(수주)는 설계도에 없다 — 사람 요청으로 더한 확장이다(D-418). 수주 → 작업지시 앞단이며, 쓰는 저장소는 EXT(테이블 sales_order) 하나다."


# ── 계약에서 세는 것 ──────────────────────────────────────────────────────────────────────────
def processes_of_menu(menu_code: str) -> list[str]:
    """그 대메뉴의 기능이 속한 프로세스(P1~P10 · 공통 · 확장) — `function-list.md` · `extension-list.md` 의 프로세스 열."""
    seen = {f.process for f in contracts.functions_of_menu(menu_code)}
    return sorted(seen, key=lambda p: (int(p[1:]) if p[0] == "P" and p[1:].isdigit() else 99, p))


def menus_of_process(process: str, menus: list[nav.Menu]) -> list[nav.Menu]:
    """`menus` 가운데 그 프로세스의 기능을 가진 대메뉴 — 넘긴 순서(좌측 메뉴 순서)를 지킨다."""
    return [m for m in menus if process in processes_of_menu(m.code)]


def stores() -> list[dict]:
    """저장소 → (쓰는 프로세스 · 테이블). 테이블은 `db-schema.md` §4(`contracts.db_tables`)에서, 쓰는 프로세스는 설계도 표에서."""
    out = []
    for code, name in STORES:
        writers = [p.code for p in PROCESSES if code in p.writes]
        out.append({"code": code, "name": name, "writers": writers, "tables": contracts.tables_of_store(code)})
    return out


def process_steps(menus: list[nav.Menu]) -> list[dict]:
    """흐름 띠 — 확장(수주)이 맨 앞, 그다음 P1~P10. 각 단계에 그 프로세스를 가진 대메뉴(권한에 따라 걸러진 `menus`)를 붙인다."""
    steps: list[dict] = []
    ext = [m for m in menus if m.ext]
    if nav.EXT_MENUS:
        steps.append({"code": "확장", "name": EXT_STEP_NAME, "actor": "영업", "writes": ("EXT",), "reads": (), "menus": ext, "ext": True})
    for p in PROCESSES:
        steps.append({"code": p.code, "name": p.name, "actor": p.actor, "writes": p.writes, "reads": p.reads,
                      "menus": menus_of_process(p.code, menus), "ext": False})
    return steps
