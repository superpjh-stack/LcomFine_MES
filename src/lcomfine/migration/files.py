"""표준 Import 파일 규격과 리더 — `contracts/migration-files.md` 의 코드 쪽 원본 (D-23 · D-303).

기존 MES 의 접근 경로가 미정(D-01)이라 파일로 받는다. **접근 경로가 정해지면 이 파일의 리더만 바꾼다.**

- 파일은 UTF-8 CSV(BOM 허용), 첫 줄이 열 이름. 열 순서는 자유. 규격에 없는 열·빠진 필수 열은 그 파일 전체의 오류다.
- 값 형식이 틀린 행은 **건너뛰고 오류 목록에 남긴다**(조용히 고쳐 넣지 않는다).
- 여기서는 DB 에 쓰지 않는다. 읽고 검사해서 `FileResult` 를 만들 뿐이다.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

TEXT, INT, DECIMAL, DATE, CHOICE, YN = "text", "int", "decimal", "date", "choice", "yn"


@dataclass(frozen=True)
class Col:
    name: str                         # CSV 열 이름
    kind: str = TEXT
    required: bool = False
    choices: tuple[str, ...] = ()
    ref: str | None = None            # 코드 참조 — REFS 의 키 (예: "item" → item.item_code)
    to: str | None = None             # 적재할 테이블 컬럼 (기본 = 열 이름. 참조 열이면 그 FK 컬럼)
    default: str | None = None        # 비어 있을 때의 값
    positive: bool = False            # 0 보다 커야 한다
    maximum: Decimal | None = None
    desc: str = ""

    @property
    def column(self) -> str:
        return self.to or self.name


@dataclass(frozen=True)
class FileSpec:
    name: str                         # item
    command: str                      # 이 파일을 적재하는 명령
    table: str                        # 대상 테이블
    key: tuple[str, ...]              # 업무 키(CSV 열 이름) — upsert 기준
    cols: tuple[Col, ...]
    audit: bool = True                # created_by · updated_at · updated_by 컬럼이 있는 테이블인가
    required: bool = True             # 폴더에 꼭 있어야 하는 파일인가 (과거 이력은 선택)
    loadable: bool = True             # 적재까지 하는가 (과거 이력은 D-01 이 풀릴 때까지 규격·검사만)
    desc: str = ""

    @property
    def filename(self) -> str:
        return f"{self.name}.csv"

    def col(self, name: str) -> Col:
        return next(c for c in self.cols if c.name == name)


#: 코드 참조 — 참조 이름 → (테이블, 코드 컬럼, 내부 키 컬럼)
REFS: dict[str, tuple[str, str, str]] = {
    "item": ("item", "item_code", "item_id"),
    "customer": ("customer", "customer_code", "customer_id"),
    "process": ("process", "process_code", "process_id"),
    "equipment": ("equipment", "equipment_code", "equipment_id"),
    "defect_code": ("defect_code", "defect_code", "defect_code_id"),
    "plate_spec": ("plate_spec", "plate_code", "plate_spec_id"),
    "anilox": ("anilox", "anilox_code", "anilox_id"),
    "ink_formula": ("ink_formula", "ink_code", "ink_formula_id"),
    "job": ("job", "job_no", "job_id"),
    "job_lot": ("job_lot", "lot_no", "job_lot_id"),
    "material_lot": ("material_lot", "lot_no", "material_lot_id"),
    "roll": ("roll", "roll_no", "roll_id"),
    "shipment": ("shipment", "shipment_no", "shipment_id"),
}

_USE = Col("use_yn", YN, default="Y", desc="사용 여부 Y|N (비우면 Y)")
_HUNDRED = Decimal(100)

MASTER, PRINT_STD, JOBS, HISTORY = "load-master", "load-print-std", "load-jobs", "load-history"

#: 파일 16개 — 적재 순서대로(앞 파일의 코드를 뒤 파일이 참조한다)
SPECS: tuple[FileSpec, ...] = (
    # ── B-MIG-02 기준정보 (D1) ──
    FileSpec("item", MASTER, "item", ("item_code",), (
        Col("item_code", required=True, desc="품목 코드"),
        Col("item_name", required=True, desc="품목명"),
        Col("item_type", CHOICE, required=True, choices=("제품", "원재료"), desc="구분"),
        Col("spec", desc="규격 (글자 그대로)"),
        Col("unit", desc="단위"),
        _USE), desc="품목"),
    FileSpec("customer", MASTER, "customer", ("customer_code",), (
        Col("customer_code", required=True, desc="고객 코드"),
        Col("customer_name", required=True, desc="고객명"),
        Col("note", desc="비고"),
        _USE), desc="고객"),
    FileSpec("process", MASTER, "process", ("process_code",), (
        Col("process_code", required=True, desc="공정 코드"),
        Col("process_name", required=True, desc="공정명"),
        Col("process_type", CHOICE, required=True, choices=("인쇄", "후가공", "슬리팅", "기타"), desc="공정 구분"),
        Col("sort_no", INT, desc="표시 순서"),
        _USE), desc="공정"),
    FileSpec("equipment", MASTER, "equipment", ("equipment_code",), (
        Col("equipment_code", required=True, desc="설비 코드"),
        Col("equipment_name", required=True, desc="설비명"),
        Col("process_code", ref="process", to="process_id", desc="이 설비가 속한 공정의 코드"),
        Col("note", desc="비고"),
        _USE), desc="설비 (기준정보까지 — 상태·수집값은 받지 않는다)"),
    FileSpec("defect_code", MASTER, "defect_code", ("defect_code",), (
        Col("defect_code", required=True, desc="불량 코드"),
        Col("defect_name", required=True, desc="불량명 (불량 유형)"),
        Col("defect_group", desc="분류"),
        _USE), desc="불량코드"),
    # ── B-MIG-03 인쇄 기준 (D1) ──
    FileSpec("plate_spec", PRINT_STD, "plate_spec", ("plate_code",), (
        Col("plate_code", required=True, desc="판 코드"),
        Col("plate_name", required=True, desc="판명"),
        Col("item_code", ref="item", to="item_id", desc="대상 품목(제품)의 코드"),
        Col("color_count", INT, positive=True, desc="도수"),
        Col("spec_note", desc="사양 메모"),
        _USE), desc="판사양"),
    FileSpec("anilox", PRINT_STD, "anilox", ("anilox_code",), (
        Col("anilox_code", required=True, desc="아니록스 코드"),
        Col("anilox_name", required=True, desc="명칭"),
        Col("line_count", DECIMAL, desc="선수"),
        Col("cell_volume", DECIMAL, desc="셀 용적"),
        Col("note", desc="비고"),
        _USE), desc="아니록스"),
    FileSpec("ink_formula", PRINT_STD, "ink_formula", ("ink_code",), (
        Col("ink_code", required=True, desc="잉크 코드"),
        Col("ink_name", required=True, desc="잉크명"),
        Col("color_name", desc="색 이름"),
        Col("target_l", DECIMAL, desc="기준 색상값 L"),
        Col("target_a", DECIMAL, desc="기준 색상값 a"),
        Col("target_b", DECIMAL, desc="기준 색상값 b"),
        Col("note", desc="비고"),
        _USE), desc="잉크조성"),
    FileSpec("ink_formula_component", PRINT_STD, "ink_formula_component", ("ink_code", "seq_no"), (
        Col("ink_code", required=True, ref="ink_formula", to="ink_formula_id", desc="잉크 코드"),
        Col("seq_no", INT, required=True, positive=True, desc="행 순번"),
        Col("component_name", required=True, desc="성분명"),
        Col("ratio_pct", DECIMAL, required=True, positive=True, maximum=_HUNDRED, desc="비율 (%) — 0 초과 100 이하"),
    ), audit=False, desc="잉크조성의 조성 행"),
    # ── B-MIG-04 작업지시 (D2) ──
    FileSpec("job", JOBS, "job", ("job_no",), (
        Col("job_no", required=True, desc="작업지시 번호 (기존 MES 의 번호 그대로)"),
        Col("item_code", required=True, ref="item", to="item_id", desc="품목(제품) 코드"),
        Col("customer_code", required=True, ref="customer", to="customer_id", desc="고객 코드"),
        Col("plate_code", ref="plate_spec", to="plate_spec_id", desc="판 코드"),
        Col("anilox_code", ref="anilox", to="anilox_id", desc="아니록스 코드"),
        Col("ink_code", ref="ink_formula", to="ink_formula_id", desc="잉크 코드"),
        Col("equipment_code", ref="equipment", to="equipment_id", desc="계획 설비 코드"),
        Col("order_qty", DECIMAL, required=True, positive=True, desc="지시 수량 — 0 초과"),
        Col("qty_unit", required=True, desc="수량 단위"),
        Col("due_date", DATE, required=True, desc="납기 YYYY-MM-DD"),
        Col("status", CHOICE, choices=("등록", "완료", "취소"), default="등록", desc="상태 (비우면 등록)"),
        Col("note", desc="비고"),
    ), desc="작업지시(Job)"),
    FileSpec("job_lot", JOBS, "job_lot", ("lot_no",), (
        Col("lot_no", required=True, desc="생산 LOT 번호"),
        Col("job_no", required=True, ref="job", to="job_id", desc="작업지시 번호"),
        Col("planned_roll_count", INT, positive=True, desc="계획 롤 수"),
        Col("planned_length_m", DECIMAL, desc="계획 길이 (m)"),
        Col("note", desc="비고"),
    ), desc="생산 LOT (Job-Lot-Roll 매핑의 Lot 단)"),
    # ── B-MIG-05 과거 이력 (D3~D8) — 범위 미확정(D-01). 규격과 빈 파일 처리까지. 있으면 형식만 검사하고 적재하지 않는다 ──
    FileSpec("material_lot", HISTORY, "material_lot", ("lot_no",), (
        Col("lot_no", required=True, desc="원재료 LOT 번호"),
        Col("item_code", required=True, ref="item", to="item_id", desc="원재료 품목 코드"),
        Col("supplier_name", desc="공급처"),
        Col("supplier_lot_no", desc="공급사 LOT 번호"),
        Col("received_qty", DECIMAL, required=True, positive=True, desc="입고 수량"),
        Col("qty_unit", required=True, desc="수량 단위"),
        Col("received_at", DATE, required=True, desc="입고일 YYYY-MM-DD"),
        Col("insp_status", CHOICE, required=True, choices=("대기", "합격", "불합격"), desc="입고검사 결과"),
    ), required=False, loadable=False, desc="원재료 LOT"),
    FileSpec("roll", HISTORY, "roll", ("roll_no",), (
        Col("roll_no", required=True, desc="롤 번호"),
        Col("process_type", CHOICE, required=True, choices=("인쇄", "후가공", "슬리팅"), desc="공정 구분"),
        Col("job_no", required=True, ref="job", to="job_id", desc="작업지시 번호"),
        Col("lot_no", ref="job_lot", to="job_lot_id", desc="생산 LOT 번호"),
        Col("equipment_code", ref="equipment", to="equipment_id", desc="설비 코드"),
        Col("length_m", DECIMAL, desc="길이 (m)"),
        Col("width_mm", DECIMAL, positive=True, desc="폭 (mm)"),
        Col("slit_seq", INT, positive=True, desc="슬리팅 분할 순번"),
        Col("produced_at", DATE, required=True, desc="생산일 YYYY-MM-DD"),
    ), required=False, loadable=False, desc="롤"),
    FileSpec("roll_genealogy", HISTORY, "roll_genealogy", ("parent_no", "child_no"), (
        Col("parent_no", required=True, desc="부모 번호 — 원재료 LOT 번호 또는 롤 번호"),
        Col("child_no", required=True, desc="자식 번호 — 롤 번호 또는 출하 LOT 번호"),
        Col("relation", CHOICE, required=True, choices=("투입", "후가공", "splice", "슬리팅", "출하"), desc="관계"),
        Col("qty", DECIMAL, desc="넘어간 양"),
    ), audit=False, required=False, loadable=False, desc="계보 (화살표 하나 = 한 줄)"),
    FileSpec("inspection", HISTORY, "inspection", ("roll_no", "inspected_at"), (
        Col("roll_no", required=True, ref="roll", to="roll_id", desc="검사한 롤 번호"),
        Col("delta_e", DECIMAL, desc="ΔE — 0 이상"),
        Col("result", CHOICE, required=True, choices=("합격", "불합격"), desc="판정"),
        Col("inspected_at", DATE, required=True, desc="검사일 YYYY-MM-DD"),
        Col("note", desc="비고"),
    ), audit=False, required=False, loadable=False, desc="검사 결과"),
    FileSpec("shipment", HISTORY, "shipment", ("shipment_no",), (
        Col("shipment_no", required=True, desc="출하 LOT 번호"),
        Col("job_no", required=True, ref="job", to="job_id", desc="작업지시 번호"),
        Col("customer_code", required=True, ref="customer", to="customer_id", desc="고객 코드"),
        Col("ship_date", DATE, required=True, desc="출하일 YYYY-MM-DD"),
        Col("status", CHOICE, required=True, choices=("등록", "승인", "취소"), desc="상태"),
        Col("coa_no", desc="COA 번호"),
    ), audit=False, required=False, loadable=False, desc="출하 LOT"),
)

SPEC_BY_NAME: dict[str, FileSpec] = {s.name: s for s in SPECS}


def specs_of(command: str) -> list[FileSpec]:
    return [s for s in SPECS if s.command == command]


# ── 읽기 ────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class RowError:
    line: int            # 파일의 줄 번호 (머리 줄이 1). 파일 전체의 오류는 0
    key: str             # 업무 키 값 (알 수 있을 때)
    reason: str

    def text(self) -> str:
        where = f"{self.line}행" if self.line else "파일"
        return f"{where}{' [' + self.key + ']' if self.key else ''}: {self.reason}"


@dataclass
class Row:
    line: int
    values: dict                      # CSV 열 이름 → 형 변환된 값 (비어 있으면 None)

    def key(self, spec: FileSpec) -> tuple:
        return tuple(self.values[k] for k in spec.key)

    def key_text(self, spec: FileSpec) -> str:
        return "/".join(str(self.values[k]) for k in spec.key)


@dataclass
class FileResult:
    spec: FileSpec
    path: Path
    exists: bool = True
    read_count: int = 0                                  # 읽은 데이터 행 수 (머리 줄·빈 줄 제외)
    rows: list[Row] = field(default_factory=list)        # 형식 검사를 통과한 행
    errors: list[RowError] = field(default_factory=list)

    @property
    def file_broken(self) -> bool:
        """파일 전체를 못 쓰는 오류(인코딩 · 머리 줄)가 있는가."""
        return any(e.line == 0 for e in self.errors)

    def fail(self, line: int, key: str, reason: str) -> None:
        self.errors.append(RowError(line, key, reason))


def _convert(col: Col, raw: str | None):
    """한 칸을 그 열의 형으로 바꾼다. 틀리면 ValueError(사유)."""
    text = (raw or "").strip()
    if text == "":
        text = col.default or ""
    if text == "":
        if col.required:
            raise ValueError("필수값이 비어 있다")
        return None
    if col.kind == TEXT:
        return text
    if col.kind == YN:
        if text not in ("Y", "N"):
            raise ValueError(f"Y 또는 N 이어야 한다 — {text!r}")
        return text
    if col.kind == CHOICE:
        if text not in col.choices:
            raise ValueError(f"{' | '.join(col.choices)} 중 하나여야 한다 — {text!r}")
        return text
    if col.kind == DATE:
        try:
            return date.fromisoformat(text)
        except ValueError:
            raise ValueError(f"날짜는 YYYY-MM-DD — {text!r}") from None
    if col.kind == INT:
        try:
            value = int(text)
        except ValueError:
            raise ValueError(f"정수가 아니다 — {text!r}") from None
    else:
        try:
            value = Decimal(text)
        except InvalidOperation:
            raise ValueError(f"숫자가 아니다 — {text!r}") from None
        if not value.is_finite():
            raise ValueError(f"숫자가 아니다 — {text!r}")
    if col.positive and value <= 0:
        raise ValueError(f"0 보다 커야 한다 — {text}")
    if col.maximum is not None and value > col.maximum:
        raise ValueError(f"{col.maximum} 이하여야 한다 — {text}")
    return value


def read(spec: FileSpec, directory: Path) -> FileResult:
    """Import 폴더에서 그 규격의 파일을 읽어 형식을 검사한다. DB 는 보지 않는다(코드 참조는 `commands` 가 본다)."""
    path = Path(directory) / spec.filename
    res = FileResult(spec, path)
    if not path.is_file():
        res.exists = False
        return res
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        res.fail(0, "", f"UTF-8 로 읽을 수 없다 ({exc.reason})")
        return res
    reader = csv.reader(io.StringIO(text, newline=""))   # 따옴표 안의 줄바꿈을 한 칸으로 읽는다
    header = next(reader, None)
    if header is None or not any(h.strip() for h in header):
        res.fail(0, "", "머리 줄(열 이름)이 없다")
        return res
    header = [h.strip() for h in header]
    known = {c.name for c in spec.cols}
    missing = [c.name for c in spec.cols if c.required and c.name not in header]
    unknown = [h for h in header if h not in known]
    duplicated = sorted({h for h in header if header.count(h) > 1})
    if missing:
        res.fail(0, "", f"필수 열이 없다 — {', '.join(missing)}")
    if unknown:
        res.fail(0, "", f"규격에 없는 열 — {', '.join(unknown)}")
    if duplicated:
        res.fail(0, "", f"열 이름 중복 — {', '.join(duplicated)}")
    if res.file_broken:
        return res

    seen: dict[tuple, int] = {}
    for cells in reader:
        line = reader.line_num
        if not any(c.strip() for c in cells):
            continue                                   # 빈 줄
        res.read_count += 1
        if len(cells) != len(header):
            res.fail(line, "", f"칸 수 {len(cells)} ≠ 열 수 {len(header)}")
            continue
        raw = dict(zip(header, cells))
        values, reasons = {}, []
        for col in spec.cols:
            try:
                values[col.name] = _convert(col, raw.get(col.name))
            except ValueError as exc:
                reasons.append(f"{col.name}: {exc}")
        key_text = "/".join((raw.get(k) or "").strip() for k in spec.key)
        if reasons:
            res.fail(line, key_text, " · ".join(reasons))
            continue
        row = Row(line, values)
        if row.key(spec) in seen:
            res.fail(line, key_text, f"파일 안에서 업무 키 중복 ({seen[row.key(spec)]}행과 같다)")
            continue
        seen[row.key(spec)] = line
        res.rows.append(row)
    return res


# ── 규격 문서 (contracts/migration-files.md §3 의 렌더본) ───────────────
_KIND_LABEL = {TEXT: "글자", INT: "정수", DECIMAL: "숫자", DATE: "날짜 YYYY-MM-DD", CHOICE: "선택", YN: "Y / N"}
DOC_BEGIN, DOC_END = "<!-- BEGIN:generated files -->", "<!-- END:generated files -->"


def render_markdown() -> str:
    """`SPECS` 를 `contracts/migration-files.md` §3 의 표로 찍는다. 문서의 그 블록은 손으로 고치지 않는다."""
    out: list[str] = []
    for s in SPECS:
        flags = [f"명령 `{s.command}`", f"업무 키 `{' + '.join(s.key)}`", "필수 파일" if s.required else "선택 파일"]
        if not s.loadable:
            flags.append("**적재 보류 (D-01)**")
        out += [f"### `{s.filename}` → `{s.table}` — {s.desc}", "", " · ".join(flags), "",
                "| 열 | 필수 | 형식 | 적재 컬럼 | 설명 |", "|---|---|---|---|---|"]
        for c in s.cols:
            kind = _KIND_LABEL[c.kind] + (f" `{' / '.join(c.choices)}`" if c.choices else "")
            rule = []
            if c.positive:
                rule.append("0 초과")
            if c.maximum is not None:
                rule.append(f"{c.maximum} 이하")
            if c.default:
                rule.append(f"비우면 `{c.default}`")
            ref = f"`{c.column}` ← `{REFS[c.ref][0]}.{REFS[c.ref][1]}`" if c.ref else f"`{c.column}`"
            desc = c.desc.replace("|", "/")
            out.append(f"| `{c.name}` | {'Y' if c.required else ''} | {kind}{' · ' + ' · '.join(rule) if rule else ''} | {ref} | {desc} |")
        out.append("")
    return "\n".join(out).rstrip() + "\n"
