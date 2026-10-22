"""업무별 유스케이스 10 — 공통 참고 페이지 `/guide/usecases` 의 데이터 한 곳 (D-530 · 아키텍트).

정본 화면(66)이 아니다 — nav 화면 · 권한 칸 · 기능 목록에 넣지 않는다(`/ia` 와 같은 공통 페이지 · G-01~G-03 기대값 불변).
읽기만 한다. 어떤 업무 표에도 쓰지 않는다.

**여기에 적는 것**: 단계마다 화면 ID · 기능 ID · 그림의 부서 줄 · 하는 일 · 결과(상태 변화) · 알림 이벤트 키,
그리고 막히는 경우(라우터가 실제로 내는 422 문장 · 그 문장이 있는 소스 파일).
**여기서 계산하는 것**(손으로 적지 않는다): 화면 이름 · 메뉴 · 경로(`nav`) · 하는 부서 = 그 화면의 W 칸 · 조회 부서 = R 칸
(운영값 `sys_permission` — `rbac.level`) · 알림 수신 부서(`notify.EVENTS`) · 링크 여부(지금 사용자가 그 화면을 볼 수 있는가).
`tests/test_arch_usecases.py` 가 기능 ↔ 화면 · W 칸 ↔ 계약 · 알림 emit 위치 · 막힘 문장을 소스에서 대조한다.
화면 · 권한 · 알림이 바뀌면 이 페이지가 함께 따라가고, 맞지 않게 되면 그 테스트가 떨어진다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import contracts, nav, notify, rbac

PATH = "/guide/usecases"
TITLE = "업무별 유스케이스"

#: 그림에서 줄을 두지 않는 부서 — 전산 관리자는 W 칸이 있는 모든 화면을 대신 처리할 수 있어 줄마다 겹친다(표에는 나온다)
LANELESS = ("ADM",)
#: 화면이 아닌 단계(배치)의 줄
BATCH = "BATCH"
BATCH_NAME = "배치(시스템)"
BATCH_TITLE = "납기 D-3 점검"

#: 알림 이벤트의 짧은 이름 — D-511 표의 정본 문장 앞부분. 키 집합은 notify.EVENTS 와 같아야 한다(테스트)
EVENT_LABEL: dict[str, str] = {
    "request_created": "의뢰 등록",
    "order_issued": "지시 발행",
    "material_received": "원자재 입고",
    "product_received": "제품 입고",
    "judged": "판정 완료",
    "shipment_ordered": "출하 지시",
    "shipment_confirmed": "출하 확정",
    "erp_upload_error": "ERP 업로드 오류·미매핑",
    "due_d3_unshipped": "납기 D-3 미출하",
}


#: 알림이 여는 화면(알림 link 의 경로) — 라우터 · 배치의 link 식에서 정적으로 대조한다(테스트)
EVENT_SCREEN: dict[str, str] = {
    "request_created": "WO-010",
    "order_issued": "MAT-020",
    "material_received": "QC-010",
    "product_received": "QC-020",
    "judged": "SHP-010",
    "shipment_ordered": "SHP-020",
    "shipment_confirmed": "SHP-030",
    "erp_upload_error": "COL-020",
    "due_d3_unshipped": "TRK-020",
}


@dataclass(frozen=True)
class Step:
    screen_id: str | None        # None = 화면이 아닌 단계(배치)
    fn: str | None               # 기능 ID (contracts/function-list.md) — 배치는 None
    lane: str                    # 그림의 부서 줄(부서 코드 · BATCH). 쓰기 단계는 W 칸 부서, 조회 단계는 R 이상 부서여야 한다
    does: str                    # 하는 일
    result: str                  # 결과 — 상태 변화
    event: str | None = None     # 이 단계가 쓰기 트랜잭션 안에서 내는 알림 (notify.EVENTS 키)
    emit_in: str | None = None   # emit 하는 소스(src/lcomfine 기준). 없으면 그 화면의 라우터 `app/routers/<module>.py`
    optional: bool = False       # 필요할 때만 하는 단계
    handoff: bool = True         # 다음 단계가 이 알림을 받고 하는 일인가 — 그림에서 다음 카드로 가는 화살표가 점선 + 알림 이름
    command: str = ""            # 배치 명령
    undecided: tuple[tuple[str, str], ...] = ()   # (D 번호, 뜻) — 정해지지 않은 것


@dataclass(frozen=True)
class Block:
    text: str        # 막히는 경우 — 업무 말
    message: str     # 라우터가 실제로 내는 422 문장(그대로의 일부 · 소스에서 대조한다)
    src: str         # 그 문장이 있는 파일(src/lcomfine 기준)


@dataclass(frozen=True)
class UseCase:
    no: int
    title: str
    purpose: str
    start: str
    stages: tuple[int, int]      # 업무 흐름 7단계(nav.FLOW) 중 걸리는 구간 (처음, 끝) — 0 부터
    steps: tuple[Step, ...]
    blocks: tuple[Block, ...]
    checks: tuple[str, ...]      # 확인 화면(대시보드 · 조회)
    notes: tuple[str, ...] = ()
    undecided: tuple[tuple[str, str], ...] = field(default=())

    @property
    def anchor(self) -> str:
        return f"uc-{self.no}"


R_WO, R_MAT, R_INV, R_QC = "app/routers/wo.py", "app/routers/mat.py", "app/routers/inv.py", "app/routers/qc.py"
R_PRD, R_INS, R_SHP, R_COL = "app/routers/prd.py", "app/routers/ins.py", "app/routers/shp.py", "app/routers/col.py"
ERP = "app/erp_upload.py"

USECASES: tuple[UseCase, ...] = (
    UseCase(
        1, "수주 → 생산지시",
        "거래처 발주를 생산의뢰로 받고, 생산부가 그 의뢰로 생산지시서를 작성해 설비 순서에 올린다.",
        "거래처 발주를 받았다. 거래처 · 제품이 기준정보에 사용 중으로 있다.",
        (0, 1),
        (
            Step("WO-010", "F-WO-011", "SL", "거래처 · 제품 · 수량 · 납기로 생산의뢰를 등록한다",
                 "의뢰번호 자동 · 의뢰 상태 확인대기", event="request_created"),
            Step("STD-040", "F-STD-041", "DS", "의뢰 알림을 받고 그 제품의 시안을 등록한다",
                 "제품별 시안 버전 — 지시서에서 불러온다", optional=True),
            Step("WO-020", "F-WO-021", "PR", "의뢰를 골라 제조사양기준서 · 시안 · 설비 · 지시 수량으로 생산지시서를 작성한다",
                 "지시번호 자동 · 지시 발행 · 의뢰 확인대기/확정 → 지시완료 · 의뢰 등록 알림 닫힘", event="order_issued",
                 handoff=False),
            Step("WO-030", "F-WO-031", "PR", "설비별 대기 지시의 순서를 앞뒤로 옮긴다",
                 "설비 대기열 순서 바뀜(발행 · 진행 지시만)", optional=True),
        ),
        (
            Block("취소된 의뢰로는 지시서를 만들 수 없다", "의뢰로는 지시서를 만들 수 없습니다", R_WO),
            Block("의뢰 상태를 손으로 지시완료로 바꿀 수 없다 — 지시서를 작성하면 바뀐다", "지시완료는 생산지시서를 작성하면 바뀝니다", R_WO),
            Block("지시가 있는 의뢰는 거래처 · 제품을 바꿀 수 없다", "지시가 있는 의뢰의 거래처·제품은 바꿀 수 없습니다", R_WO),
            Block("취소되지 않은 지시가 있는 의뢰는 다른 상태(취소 포함)로 바꿀 수 없다", "건이 있는 의뢰는", R_WO),
            Block("사용 중지 거래처는 의뢰에 고를 수 없다", "사용 중지 거래처는 고를 수 없습니다", R_WO),
            Block("다른 제품의 사양 · 시안은 지시서에 붙일 수 없다", "그 제품의 사양이 아닙니다", R_WO),
            Block("설비가 없는 지시는 순서를 정할 수 없다", "설비가 없는 지시는 순서를 정할 수 없습니다", R_WO),
        ),
        ("WO-040", "TRK-010", "RPT-010"),
    ),
    UseCase(
        2, "원자재 입고 → 입고검사",
        "공급사에서 들어온 원자재를 LOT 으로 입고하고, 입고검사 판정으로 쓸 수 있는 LOT(가용)과 막을 LOT(보류)을 가른다.",
        "공급사 원자재가 들어왔다. 원자재 품목과 창고 · 위치가 기준정보에 있다.",
        (2, 2),
        (
            Step("MAT-010", "F-MAT-011", "PR", "공급사 · 입고일과 LOT 행(품목 · 수량 · 위치 · 공급사 LOT)을 등록한다",
                 "원자재 LOT 번호 자동 · 재고 상태 검사대기", event="material_received"),
            Step("QC-010", "F-QC-011", "PR", "입고 알림을 눌러 연 입고검사에서 검사 항목과 합격 · 불합격을 판정한다",
                 "합격 → 가용 · 불합격 → 보류 · 입고 알림 닫힘"),
            Step("QC-010", "F-QC-012", "PR", "판정을 다시 한다(재판정)",
                 "판정 새 차수 행 · 재고 상태 다시 바뀜(보류 → 가용 등)", optional=True),
        ),
        (
            Block("원자재가 아닌 품목은 입고할 수 없다", "품목이 아닙니다: ", R_MAT),
            Block("사용 중지 품목은 입고에 고를 수 없다", "사용 중지 품목은 고를 수 없습니다", R_MAT),
            Block("이미 판정한 LOT 은 판정이 아니라 재판정한다", "이미 판정한 LOT 은 재판정합니다", R_QC),
            Block("판정이 없는 LOT 은 재판정할 수 없다", "먼저 판정합니다", R_QC),
            Block("합격 · 불합격 중 하나를 골라야 한다", "합격 또는 불합격을 고르세요", R_QC),
            Block("이미 불출 · 이동 · 분할 · 할당된 LOT 은 입고 수량을 고치거나 취소할 수 없다", "{why} — 취소할 수 없습니다", R_MAT),
        ),
        ("QC-030", "INV-010", "MAT-040"),
    ),
    UseCase(
        3, "자재 불출(가용 LOT · 분할)",
        "발행된 생산지시에 입고검사를 통과한 원자재 LOT 을 필요한 만큼 내준다. 한 LOT 을 나눠 써야 하면 먼저 분할한다.",
        "생산지시가 발행됐다(지시 발행 알림). 쓸 원자재 LOT 이 입고검사 합격(가용)이다.",
        (2, 2),
        (
            Step("HOME-020", "F-HOME-021", "PR", "「지시 발행」 알림을 눌러 그 지시의 불출 화면을 연다",
                 "알림이 가리키는 화면으로 이동"),
            Step("INV-020", "F-INV-021", "PR", "한 LOT 의 일부를 나눠 다른 위치로 옮긴다(분할)",
                 "새 LOT 번호(원 번호 + 분할 순번) · 원 LOT 재고 감소 · 재고 상태는 원 LOT 그대로", optional=True),
            Step("MAT-020", "F-MAT-021", "PR", "지시를 고르고 가용 LOT · 위치 · 수량을 골라 불출한다",
                 "LOT 재고 감소 · 이동 기록(불출) · 지시 발행 알림 닫힘"),
        ),
        (
            Block("검사대기 LOT 은 불출할 수 없다 — 입고검사 합격 뒤 불출한다", "검사대기 LOT 은 불출할 수 없습니다", R_MAT),
            Block("보류(입고검사 불합격) LOT 은 불출할 수 없다", "보류(입고검사 불합격) LOT 은 불출할 수 없습니다", R_MAT),
            Block("가용 수량(현재고 − 할당)을 넘게 불출할 수 없다", "의 가용 수량", R_MAT),
            Block("여러 위치에 있는 LOT 은 위치를 골라야 한다", "여러 위치에 있습니다 — 위치를 고르세요", R_MAT),
            Block("취소 · 완료된 지시에는 불출할 수 없다", "된 지시입니다:", R_INV),
            Block("분할 · 이동도 가용 수량을 넘을 수 없다", "을(를) 넘습니다 (현재고", R_INV),
            Block("불출한 LOT 을 바꾸려면 취소 뒤 다시 불출한다", "LOT 을 바꾸려면 취소 뒤 다시 불출", R_MAT),
        ),
        ("MAT-040", "INV-010", "LOT-010"),
    ),
    UseCase(
        4, "생산일보 · 검사일보",
        "불출을 받은 지시를 설비에서 생산하며 하루 단위로 생산 · 검사 수량을 남기고, 끝나면 지시를 완료로 닫는다.",
        "불출이 끝난 지시(발행 · 진행)를 설비에서 생산한다.",
        (3, 3),
        (
            Step("PRD-010", "F-PRD-011", "PR", "지시 · 일자 · 설비별 생산 · 양품 · 로스 수량과 가동 · 정지 시간을 적는다",
                 "생산일보 1행(지시 · 일자 · 설비마다 하나)"),
            Step("INS-010", "F-INS-011", "PR", "검사 수량 · 불량 수량과 불량유형별 수량을 적는다",
                 "검사일보 1행(지시 · 일자마다 하나)"),
            Step("WO-020", "F-WO-022", "PR", "생산지시서의 상태를 진행 · 완료로 고친다",
                 "지시 발행 → 진행 → 완료 — 완료 지시는 불출 · 일보 · 제품 입고 대상에서 빠진다"),
        ),
        (
            Block("같은 지시 · 일자 · 설비의 생산일보는 하나 — 있는 행을 고친다", "일보가 이미 있습니다 — 그 행을 고칩니다", R_PRD),
            Block("같은 지시 · 일자의 검사일보는 하나 — 있는 행을 고친다", "검사일보가 이미 있습니다 — 그 행을 고칩니다", R_INS),
            Block("불량유형별 수량의 합은 불량 수량과 같아야 한다", "과 불량 수량", R_INS),
            Block("불량 수량은 검사 수량을 넘을 수 없다", "이 검사 수량", R_INS),
            Block("사용 중지 설비로는 일보를 쓸 수 없다", "사용 중지된 설비입니다", R_PRD),
            Block("취소 · 완료된 지시에는 일보를 쓸 수 없다", "된 지시입니다:", R_INV),
        ),
        ("PRD-030", "INS-030", "PRD-040", "PRP-010"),
        undecided=(("D-519", "생산 · 검사 로스율 산식"),),
    ),
    UseCase(
        5, "제품 입고 → 제품검사 판정(재판정 포함)",
        "생산이 끝난 제품을 제품 LOT 으로 입고하고, 제품검사 판정으로 출하할 수 있는 LOT 을 정한다. 판정은 출하실 · 영업부에 알림으로 넘어간다.",
        "생산일보 완료 수량이 있는 지시(발행 · 진행)다.",
        (4, 4),
        (
            Step("MAT-030", "F-MAT-031", "PR", "지시를 고르고 수량(비우면 일보 완료 수량) · 입고 위치로 제품 입고를 등록한다",
                 "제품 LOT 번호 자동 · 재고 상태 검사대기", event="product_received"),
            Step("QC-020", "F-QC-021", "PR", "제품 입고 알림을 눌러 연 제품검사에서 합격 · 불합격을 판정한다",
                 "합격 → 가용(출하 지시 가능) · 불합격 → 보류 · 제품 입고 알림 닫힘", event="judged"),
            Step("QC-020", "F-QC-022", "PR", "판정을 다시 한다(재판정)",
                 "판정 새 차수 행 · 재고 상태 다시 바뀜 · 이미 확정된 출하는 바꾸지 않는다(반품 · 정정은 출하 확정 화면)",
                 event="judged", optional=True),
        ),
        (
            Block("일보 완료 수량이 없으면 수량을 직접 넣어야 한다", "생산일보 완료 수량(기존 입고 제외)이 없습니다", R_MAT),
            Block("이미 판정한 LOT 은 판정이 아니라 재판정한다", "이미 판정한 LOT 은 재판정합니다", R_QC),
            Block("판정이 없는 LOT 은 재판정할 수 없다", "먼저 판정합니다", R_QC),
            Block("취소된 제품 입고는 고칠 수 없다", "취소된 입고는 고칠 수 없습니다", R_MAT),
        ),
        ("QC-030", "INV-010", "RPT-030"),
    ),
    UseCase(
        6, "출하 지시 → 출하 확정(반품 · 정정 포함)",
        "판정 합격 LOT 을 출하 지시에 할당하고, 출하실이 확정하면 재고가 빠지고 영업부 · 회계부에 알림이 간다. 확정 뒤 바뀐 것은 반품 · 정정 행으로 남긴다.",
        "판정 완료 알림을 받았다. 출하할 제품 LOT 이 가용이다.",
        (5, 5),
        (
            Step("SHP-010", "F-SHP-011", "SL", "생산의뢰 번호(있으면) · 거래처 · 납기와 가용 LOT · 수량을 골라 출하 지시를 등록한다",
                 "출하 번호 자동 · 상태 지시 · LOT 할당량 증가(가용 = 현재고 − 할당) · 판정 알림 닫힘", event="shipment_ordered"),
            Step("SHP-020", "F-SHP-021", "SH", "출하 지시 알림을 눌러 연 출하 확정에서 확정한다",
                 "상태 지시 → 확정 · 현재고와 할당 함께 감소 · 이동 기록(출하) · 출하 지시 알림 닫힘", event="shipment_confirmed"),
            Step("SHP-020", "F-SHP-023", "SH", "확정된 출하에 반품 · 정정 행을 남긴다(구분 · 수량 · 사유)",
                 "반품은 음수로 저장 · 재고는 바뀌지 않는다", optional=True),
        ),
        (
            Block("가용 LOT 만 할당할 수 있다(검사대기 · 보류 불가)", "가용 LOT 만 할당할 수 있습니다", R_SHP),
            Block("가용 수량을 넘게 할당할 수 없다", "가용 수량을 넘는 할당입니다", R_SHP),
            Block("생산의뢰의 거래처와 다른 거래처로 출하 지시할 수 없다", "생산의뢰의 거래처와 다른 거래처입니다", R_SHP),
            Block("검사 미판정 · 불합격 LOT 이 있으면 출하 확정할 수 없다", "검사 미판정·불합격 LOT 는 출하 확정을 막습니다", R_SHP),
            Block("이미 확정 · 취소된 출하는 다시 확정할 수 없다", "된 출하입니다", R_SHP),
            Block("확정 · 취소된 출하 지시는 고칠 수 없다 — 확정 뒤 정정은 반품 · 정정으로", "된 출하는 고칠 수 없습니다", R_SHP),
            Block("반품 · 정정은 확정된 출하에만 남길 수 있다", "확정된 출하만 반품·정정을 등록할 수 있습니다", R_SHP),
            Block("반품 누계는 출하 수량을 넘을 수 없다", "반품 수량이 출하 수량을 넘습니다", R_SHP),
        ),
        ("SHP-030", "INV-010", "TRK-010", "RPT-050"),
        notes=("확정 전에는 출하 지시 화면에서 할당 줄을 고친다 — 이전 할당을 풀고 새로 잡으며, 줄을 모두 지우면 지시 취소 · 할당 해제(알림 없음).",
               "반품 · 정정의 재고 반영 방식은 가설(D-515) — 지금은 행만 남기고 재고는 바꾸지 않는다."),
    ),
    UseCase(
        7, "ERP 수금 업로드 · 거래처 매핑 → 수금 · 미수 조회",
        "회계부가 ERP 수금현황 엑셀을 회차로 올리고, 처음 보는 ERP 거래처코드를 MES 거래처에 매핑해 수금 · 미수를 거래처별로 본다.",
        "회계부가 ERP 에서 수금현황 엑셀(.xlsx)을 받았다.",
        (6, 6),
        (
            Step("COL-010", "F-COL-011", "AC", "엑셀을 올려 열 매핑을 저장 · 미리보고 기준 기간으로 반영한다",
                 "새 회차 반영 · 같은 기준 기간의 이전 회차는 교체(행 보존) · 오류 · 미매핑 행은 반영에서 빠짐",
                 event="erp_upload_error", emit_in=ERP),
            Step("COL-020", "F-COL-021", "AC", "오류 알림을 눌러 그 회차의 오류 · 미매핑 행을 본다",
                 "회차별 반영 · 교체 구분과 오류 행 확인"),
            Step("COL-030", "F-COL-031", "AC", "미매핑 ERP 거래처코드를 MES 거래처에 매핑한다",
                 "그 코드의 반영 회차 행을 다시 해석 · 오류가 없어지면 오류 알림 닫힘"),
            Step("COL-050", "F-COL-051", "SL", "거래처별 매출 · 수금 · 미수 잔액을 본다",
                 "기준일(ERP 업로드 기준일) 기준 미수 — 읽기만",
                 undecided=(("D-516", "ERP 매출액 · 잔액 열 구성"),)),
        ),
        (
            Block("파일 없이 업로드할 수 없다", "ERP 엑셀 파일을 올려 주세요", R_COL),
            Block("엑셀(.xlsx)이 아니면 읽지 않는다", "엑셀(.xlsx) 파일이 아닙니다", ERP),
            Block("열 매핑을 저장하기 전에는 반영할 수 없다", "열 매핑이 없습니다 — 먼저 열 매핑을 저장해 주세요", ERP),
            Block("기준 기간의 시작일이 종료일보다 늦을 수 없다", "기준 기간의 시작일이 종료일보다 늦습니다", R_COL),
            Block("같은 ERP 거래처코드는 한 번만 매핑한다", "이미 있는 ERP 거래처코드입니다", R_COL),
        ),
        ("COL-040", "COL-060", "COL-070", "RPT-060"),
        notes=("MES 는 수금 금액을 고치지 않는다 — 수금 데이터는 회차 교체(다시 올리기)로만 바뀐다.",),
    ),
    UseCase(
        8, "클레임 대응 — 출하에서 원자재 LOT 까지 역추적 · 원자재에서 출하까지 정방향",
        "거래처 클레임이 들어오면 출하 1건에서 원자재 LOT 까지 거슬러 올라가 원인을 찾고, 같은 원자재 LOT 이 들어간 다른 출하 범위를 본다.",
        "거래처 클레임 — 출하 번호 또는 제품 LOT 번호를 받았다.",
        (1, 5),
        (
            Step("SHP-030", "F-SHP-031", "SL", "출하 번호 · 거래처로 확정 출하와 반품 · 정정 행을 찾는다",
                 "확정 출하 · 제품 LOT 확인 — 읽기만"),
            Step("LOT-020", "F-LOT-021", "SL", "출하 번호(또는 제품 LOT)로 역방향 추적한다",
                 "제품 LOT → 생산지시 → 불출 → 원자재 LOT 계보 — 읽기만"),
            Step("QC-030", "F-QC-031", "PR", "그 원자재 · 제품 LOT 의 판정 · 재판정 이력을 본다",
                 "판정 차수 · 이전 판정 확인 — 읽기만"),
            Step("LOT-010", "F-LOT-011", "PR", "원자재 LOT 으로 정방향 추적해 같은 LOT 이 들어간 지시 · 제품 LOT · 출하를 본다",
                 "영향 범위(지시 · 제품 LOT · 거래처) — 읽기만"),
            Step("QC-020", "F-QC-022", "PR", "남은 재고 LOT 을 재판정한다",
                 "불합격 → 보류(출하 확정 불가) · 이미 확정된 출하는 그대로", event="judged", optional=True,
                 handoff=False),
            Step("SHP-020", "F-SHP-023", "SH", "나간 수량은 반품 행으로 남긴다",
                 "반품 행(음수) · 재고는 바뀌지 않는다", optional=True),
        ),
        (
            Block("판정이 없는 LOT 은 재판정할 수 없다", "먼저 판정합니다", R_QC),
            Block("반품 · 정정은 확정된 출하에만 남길 수 있다", "확정된 출하만 반품·정정을 등록할 수 있습니다", R_SHP),
            Block("그 출하에 없는 LOT 으로 반품할 수 없다", "이 출하에 없는 LOT 입니다", R_SHP),
            Block("반품 누계는 출하 수량을 넘을 수 없다", "반품 수량이 출하 수량을 넘습니다", R_SHP),
        ),
        ("LOT-020", "LOT-010", "QC-030", "RPT-030"),
        notes=("추적은 읽기만 한다 — 결과를 따로 쌓지 않는다. 정방향 추적은 영업부 칸이 없어 생산부 · 출하실이 본다.",),
    ),
    UseCase(
        9, "납기 임박 · 지연 대응",
        "납기 3일 안(지난 납기 포함)인데 다 나가지 않은 의뢰를 배치가 알리면, 영업부 · 생산부가 진행을 보고 순서 · 출하를 앞당긴다.",
        "배치 due-check 를 돌린다(지금은 수동 실행).",
        (0, 5),
        (
            Step(None, None, BATCH, "취소 아닌 의뢰 중 납기 D-3 이내(지난 납기 포함)이고 확정 출하가 의뢰 수량보다 적은 의뢰를 찾는다",
                 "의뢰마다 · 하루마다 알림 1건", event="due_d3_unshipped", emit_in="jobs.py",
                 command="uv run python -m lcomfine.jobs due-check",
                 undecided=(("D-520", "배치를 하루 언제 돌릴지"),)),
            Step("HOME-020", "F-HOME-021", "SL", "「납기 D-3 미출하」 알림을 눌러 납기 현황을 연다",
                 "알림이 가리키는 의뢰의 납기 현황으로 이동"),
            Step("TRK-020", "F-TRK-021", "SL", "납기 구분(완료 · 지연 완료 · 지연 · D-3 · D-7 · 여유)과 준수율을 본다",
                 "임박 · 지연 의뢰 확인 — 읽기만"),
            Step("TRK-010", "F-TRK-011", "PR", "의뢰의 단계별 수량(지시 · 생산 · 검사 · 입고 · 출하)으로 어디서 멈췄는지 본다",
                 "지금 단계 · 남은 수량 확인 — 읽기만"),
            Step("WO-030", "F-WO-031", "PR", "급한 지시를 설비 대기열 앞으로 옮긴다",
                 "설비 대기열 순서 바뀜", optional=True),
            Step("SHP-010", "F-SHP-011", "SL", "가용 재고가 있으면 출하 지시를 등록한다",
                 "할당 · 출하 지시 알림 → 출하실", event="shipment_ordered", optional=True),
        ),
        (
            Block("완료 · 취소된 지시는 순서를 옮길 수 없다", "지시는 순서를 옮길 수 없습니다", R_WO),
            Block("설비가 없는 지시는 순서를 정할 수 없다", "설비가 없는 지시는 순서를 정할 수 없습니다", R_WO),
            Block("맨 앞 · 맨 뒤 지시는 더 옮길 수 없다", "이미 맨 앞입니다", R_WO),
            Block("취소된 생산의뢰로는 출하 지시할 수 없다", "취소된 생산의뢰입니다", R_SHP),
        ),
        ("TRK-020", "TRK-010", "RPT-070", "RPT-050"),
        undecided=(("D-520", "주문 흐름 병목 기준일 · 배치 시각"),),
    ),
    UseCase(
        10, "재고 이동 · 실사 조정",
        "LOT 재고를 다른 위치로 옮기고, 실사에서 장부와 실물이 다르면 실사 수량으로 맞추고 사유를 남긴다.",
        "창고 위치를 옮기거나 정기 실사를 했다.",
        (2, 5),
        (
            Step("INV-010", "F-INV-011", "PR", "LOT · 위치별 현재고와 상태(검사대기 · 가용 · 보류 · 할당)를 본다",
                 "가용 수량 = 현재고 − 출하 지시 할당 — 읽기만"),
            Step("INV-020", "F-INV-021", "PR", "LOT 재고를 다른 위치로 옮긴다",
                 "출발 위치 감소 · 도착 위치 증가 · 재고 상태 그대로 · 이동 기록(이동)"),
            Step("INV-030", "F-INV-031", "PR", "위치의 실사 수량과 차이 사유를 남긴다",
                 "장부 수량 → 실사 수량 · 조정 기록(장부 · 실사 · 차이)"),
            Step("RPT-040", "F-RPT-041", "ST", "재고 변동 · 장기 체류 LOT · 실사 차이를 대시보드로 본다",
                 "기간별 입고 · 불출 · 실사 차이 — 읽기만"),
        ),
        (
            Block("출발 위치와 같은 위치로는 이동할 수 없다(같은 위치에서 나누려면 분할)", "출발 위치와 같습니다", R_INV),
            Block("가용 수량(현재고 − 할당)을 넘게 옮길 수 없다", "을(를) 넘습니다 (현재고", R_INV),
            Block("출하 지시 할당량보다 작게 실사 조정할 수 없다 — 할당을 먼저 고친다", "보다 작게 조정할 수 없습니다", R_INV),
            Block("그 위치에 재고 행이 없는 LOT 은 조정할 수 없다", "의 재고 행이", R_INV),
            Block("불출 · 출하 · 분할 행은 재고 이동 화면에서 고치지 않는다", "위치 이동 행만 고칩니다", R_INV),
        ),
        ("INV-010", "INV-030", "RPT-040", "MAT-040"),
    ),
)


# ── 계산 (nav · 권한 칸 · notify) ─────────────────────────────────────────

def _role_names() -> dict[str, str]:
    """부서 코드 → 이름(운영값 sys_role). 없으면 계약의 이름."""
    names = {code: name for name, code in contracts.ROLE_CODES.items()}
    for r in rbac.roles():
        names[r.code] = r.name
    return names


def role_order() -> list[str]:
    return list(contracts.ROLE_CODES.values())


def doers(screen_id: str) -> list[str]:
    """그 화면의 W 칸 부서(부서 순서)."""
    return [c for c in role_order() if rbac.level(c, screen_id) == rbac.LEVEL_W]


def readers(screen_id: str) -> list[str]:
    """그 화면의 R 칸 부서(W 제외 · 조회만)."""
    return [c for c in role_order() if rbac.level(c, screen_id) == rbac.LEVEL_R]


def is_write(step: Step) -> bool:
    return bool(step.fn) and contracts.function(step.fn).is_write


def emit_source(step: Step) -> str | None:
    """그 단계의 알림을 내는 소스 파일(src/lcomfine 기준)."""
    if not step.event:
        return None
    if step.emit_in:
        return step.emit_in
    return f"app/routers/{nav.by_id(step.screen_id).module}.py"


def _screen_ref(screen_id: str, user) -> dict:
    sc = nav.by_id(screen_id)
    return {"screen_id": sc.screen_id, "name": sc.name, "menu": sc.menu, "path": sc.path,
            "visible": rbac.can(user, sc.screen_id, rbac.LEVEL_R)}


def _lanes(uc: UseCase) -> list[str]:
    """그림의 줄 — 단계 부서 ∪ 알림 수신 부서(전산 관리자 제외), 부서 순서. 배치가 있으면 맨 위."""
    used = {s.lane for s in uc.steps}
    for s in uc.steps:
        if s.event:
            used.update(notify.recipients(s.event))
    lanes = [BATCH] if BATCH in used else []
    return lanes + [c for c in role_order() if c in used and c not in LANELESS]


# 그림 치수(px) — 템플릿은 이 값을 그대로 쓴다
LANE_LABEL_W, COL_W, COL_GAP, CARD_H, LANE_H, CARD_TOP = 100, 138, 30, 56, 112, 26
PILL_H = 24


def _split_name(name: str, limit: int = 9) -> list[str]:
    """카드 안 화면 이름 — 길면 띄어쓰기에서 두 줄로."""
    if len(name) <= limit or " " not in name:
        return [name]
    words = name.split(" ")
    cut = min(range(1, len(words)), key=lambda i: max(len(" ".join(words[:i])), len(" ".join(words[i:]))))
    return [" ".join(words[:cut]), " ".join(words[cut:])]


def _pill_w(text: str) -> int:
    return max(84, 11 * len(text) + 18)


def swimlane(uc: UseCase, user, names: dict[str, str]) -> dict:
    """스윔레인 그림의 좌표 — 가로 = 단계 순서, 세로 = 부서 줄.
    단계 사이 화살표는 실선, 알림을 받고 다음 단계로 넘어가면 점선 + 알림 이름(다음 카드 위).
    다음 단계가 아닌 수신 부서에는 「○○ 알림」 표(그 단계 열 · 그 부서 줄)로 점선을 긋는다."""
    lanes = _lanes(uc)
    lane_y = {code: i * LANE_H for i, code in enumerate(lanes)}
    pitch = COL_W + COL_GAP
    cards = []
    for i, s in enumerate(uc.steps):
        x = LANE_LABEL_W + i * pitch
        y = lane_y[s.lane] + CARD_TOP
        if s.screen_id:
            ref = _screen_ref(s.screen_id, user)
            title, sub = ref["name"], ref["menu"]
        else:
            ref = {"visible": False, "path": ""}
            title, sub = BATCH_TITLE, BATCH_NAME
        cards.append({"n": i + 1, "x": x, "y": y, "cx": x + COL_W / 2, "lines": _split_name(title), "sub": sub,
                      "title": title, "href": ref["path"] if ref["visible"] else "",
                      "locked": bool(s.screen_id) and not ref["visible"], "optional": s.optional, "lane": s.lane})
    arrows, pills = [], []
    for i, s in enumerate(uc.steps):
        a = cards[i]
        nxt = cards[i + 1] if i + 1 < len(cards) else None
        recips = list(notify.recipients(s.event)) if s.event else []
        label = EVENT_LABEL.get(s.event or "", "")
        handed = bool(nxt and s.event and s.handoff and nxt["lane"] in recips)
        if nxt:
            arrow = {"d": _path(a, nxt), "dashed": handed}
            if handed:
                arrow.update(label=f"{label} 알림", lx=nxt["x"], ly=nxt["y"] - 7)
            arrows.append(arrow)
        for r in recips:
            if r in LANELESS or (handed and r == nxt["lane"]):
                continue
            text = f"{label} 알림"
            w = _pill_w(text)
            if r == a["lane"]:          # 자기 줄로 오는 알림 — 카드 바로 아래
                px, py = a["cx"] - w / 2, a["y"] + CARD_H + 4
                d = f"M{a['cx']:.0f},{a['y'] + CARD_H:.0f} L{a['cx']:.0f},{py - 1:.0f}"
            else:
                px, py = a["cx"] - w / 2, lane_y[r] + CARD_TOP + (CARD_H - PILL_H) / 2
                down = py > a["y"]
                d = (f"M{a['cx']:.0f},{a['y'] + CARD_H if down else a['y']:.0f} "
                     f"L{a['cx']:.0f},{py - 1 if down else py + PILL_H + 1:.0f}")
            pills.append({"x": px, "y": py, "w": w, "h": PILL_H, "text": text, "to": names.get(r, r)})
            arrows.append({"d": d, "dashed": True})
    width = LANE_LABEL_W + len(uc.steps) * pitch - COL_GAP + 12
    return {"lanes": [{"code": c, "name": BATCH_NAME if c == BATCH else names.get(c, c), "y": lane_y[c]} for c in lanes],
            "cards": cards, "arrows": arrows, "pills": pills, "width": width, "height": len(lanes) * LANE_H,
            "col_w": COL_W, "card_h": CARD_H, "lane_h": LANE_H, "pill_h": PILL_H}


def _path(a: dict, b: dict) -> str:
    x1, y1 = a["x"] + COL_W, a["y"] + CARD_H / 2
    x2, y2 = b["x"], b["y"] + CARD_H / 2
    if abs(y1 - y2) < 1:
        return f"M{x1:.0f},{y1:.0f} L{x2 - 2:.0f},{y2:.0f}"
    mx = (x1 + x2) / 2
    return f"M{x1:.0f},{y1:.0f} C{mx:.0f},{y1:.0f} {mx:.0f},{y2:.0f} {x2 - 2:.0f},{y2:.0f}"


def _step_view(s: Step, user, names: dict[str, str]) -> dict:
    out = {"step": s, "screen": _screen_ref(s.screen_id, user) if s.screen_id else None,
           "write": is_write(s), "fn_name": contracts.function(s.fn).name if s.fn else "",
           "lane_name": BATCH_NAME if s.lane == BATCH else names.get(s.lane, s.lane)}
    if s.screen_id:
        w, r = doers(s.screen_id), readers(s.screen_id)
        out["doer_codes"] = w if out["write"] else []                         # 쓰기 단계 = 그 화면의 W 칸
        out["viewer_codes"] = r if out["write"] else [c for c in role_order() if c in w or c in r]   # 조회 단계 = R 이상
    else:
        out["doer_codes"], out["viewer_codes"] = [], []
    out["doers"] = [names[c] for c in out["doer_codes"]]
    out["viewers"] = [names[c] for c in out["viewer_codes"]]
    out["event_label"] = EVENT_LABEL.get(s.event or "", "")
    out["event_screen"] = _screen_ref(EVENT_SCREEN[s.event], user) if s.event else None
    out["recipients"] = [names[c] for c in notify.recipients(s.event)] if s.event else []
    return out


def involvement(uc: UseCase) -> dict[str, str]:
    """부서 코드 → 'W'(등록 · 처리 — 쓰기 단계 화면의 W 칸) · 'R'(조회 단계 화면의 R 이상 · 알림 수신만).
    확인 화면(대시보드 · 조회)은 세지 않는다 — 관여 없는 부서는 빠진다."""
    out: dict[str, str] = {}
    for s in uc.steps:
        if s.event:
            for r in notify.recipients(s.event):
                out.setdefault(r, "R")
        if not s.screen_id:
            continue
        if is_write(s):
            for c in doers(s.screen_id):
                out[c] = "W"
        for c in doers(s.screen_id) + readers(s.screen_id):
            out.setdefault(c, "R")
    return out


def page(user) -> dict:
    """템플릿 컨텍스트 — 흐름 지도 · 유스케이스 × 부서 표 · 유스케이스 10."""
    names = _role_names()
    order = role_order()
    flow = [_screen_ref(sid, user) for sid in nav.FLOW]
    ucs = []
    for i, uc in enumerate(USECASES):
        inv = involvement(uc)
        undecided = list(uc.undecided)
        for s in uc.steps:
            undecided += [u for u in s.undecided if u not in undecided]
        ucs.append({
            "uc": uc, "anchor": uc.anchor, "next": USECASES[i + 1] if i + 1 < len(USECASES) else None,
            "steps": [_step_view(s, user, names) for s in uc.steps],
            "swim": swimlane(uc, user, names),
            "depts": [{"code": c, "name": names[c], "level": inv[c]} for c in order if c in inv],
            "involve": inv, "blocks": uc.blocks, "undecided": undecided,
            "checks": [_screen_ref(sid, user) for sid in uc.checks],
            "events": sorted({s.event for s in uc.steps if s.event}, key=list(notify.EVENTS).index),
        })
    return {"flow_map": flow, "usecases": ucs, "roles": [{"code": c, "name": names[c]} for c in order],
            "event_label": EVENT_LABEL, "laneless": [names[c] for c in LANELESS]}
