# tests/test_qa1_screens.py — QA1 G-02 · G-03 · G-19 (tools/check_screens.py 의 검사를 그대로 부른다 · W2 COL · W3 RPT · W4 DOC 가 범위에 든다 — COL 표식은 test_qa1_col.py · RPT 는 test_qa1_rpt.py · DOC 는 test_qa1_doc.py)
# 기대값은 계약(function-list.md · permission-matrix.md · api-contract.md)에서 끌어온다. 시드 계정 8 로 로그인만 하고 아무것도 쓰지 않는다
# (쓰기 403 전수는 빈 본문 · 없는 경로 키로만 두드린다 — W 부서도 404/422 로 끝나 행이 생기지 않는다).
import pytest

from tools import check_screens as cs


@pytest.fixture(scope="module")
def world():
    app, clients = cs.app_and_clients()
    return app, clients


def _assert_rows(rep: cs.Report, gate: str | None = None) -> None:
    bad = [(g, item, actual) for g, item, ok, actual in rep.rows if not ok and (gate is None or g == gate)]
    if not bad:
        return
    details = dict(rep.details)
    lines = []
    for g, item, actual in bad:
        lines.append(f"{g} {item} — {actual}")
        lines += [f"    - {b}" for b in details.get(f"{g} {item}", [])[:25]]
    pytest.fail("\n".join(lines))


@pytest.mark.fn("F-HOME-011", "F-HOME-021", "F-HOME-032", "F-BAS-014", "F-BAS-024", "F-BAS-034",
                "F-STD-014", "F-STD-024", "F-STD-034", "F-STD-043", "F-STD-053", "F-STD-064",
                "F-WO-013", "F-WO-023", "F-WO-032", "F-WO-041", "F-MAT-013", "F-MAT-023", "F-MAT-033", "F-MAT-041",
                "F-PRD-013", "F-PRD-021", "F-PRD-031", "F-PRD-041", "F-INS-013", "F-INS-021", "F-INS-031", "F-INS-041",
                "F-QC-013", "F-QC-023", "F-QC-031", "F-INV-011", "F-INV-023", "F-INV-032", "F-SHP-013", "F-SHP-022", "F-SHP-031",
                "F-TRK-011", "F-TRK-021", "F-TRK-031", "F-LOT-011", "F-LOT-021", "F-PRP-011", "F-PRP-021", "F-PRP-031",
                "F-SYS-014", "F-SYS-022", "F-SYS-032", "F-SYS-041")
def test_g03_g19_screens_67_x_8_200_403_and_sentence(world):
    """화면 67 × 부서 8: 칸 W/R → 200 · 칸 없음 → 403(브라우저 · JSON) + 문장 「이 화면을 볼 권한이 없습니다」(api-contract §1)
    · 범위(W1~W4) 화면 67 placeholder 0 (W4 DOC 2 포함) · 메뉴 = 권한 칸 · DB sys_permission = 계약 260 칸."""
    app, clients = world
    rep = cs.Report()
    cs.check_screens(app, clients, rep)
    _assert_rows(rep)
    assert not rep.defects, "\n".join(rep.defects)       # [403 문장] — 기능 문장이 화면 GET 에 나온 것


def test_g02_w1_functions_route_and_marks(world):
    """범위 기능 136(W1 109 + W2 COL 11 + W3 RPT 10 + W4 DOC 6) — API 열의 메서드 · 경로가 라우트에 글자 그대로 · @pytest.mark.fn 표식 1건 이상 (G-02)."""
    app, _ = world
    rep = cs.Report()
    cs.check_functions(app, rep)
    _assert_rows(rep, "G-02")


@pytest.mark.fn("F-HOME-022", "F-HOME-031", "F-BAS-011", "F-BAS-012", "F-BAS-013", "F-BAS-021", "F-BAS-022", "F-BAS-023",
                "F-BAS-031", "F-BAS-032", "F-BAS-033", "F-STD-011", "F-STD-012", "F-STD-013", "F-STD-021", "F-STD-022", "F-STD-023",
                "F-STD-031", "F-STD-032", "F-STD-033", "F-STD-041", "F-STD-042", "F-STD-051", "F-STD-052", "F-STD-061", "F-STD-062",
                "F-STD-063", "F-WO-011", "F-WO-012", "F-WO-021", "F-WO-022", "F-WO-031", "F-MAT-011", "F-MAT-012", "F-MAT-021",
                "F-MAT-022", "F-MAT-031", "F-MAT-032", "F-PRD-011", "F-PRD-012", "F-INS-011", "F-INS-012", "F-QC-011", "F-QC-012",
                "F-QC-021", "F-QC-022", "F-INV-021", "F-INV-022", "F-INV-031", "F-SHP-011", "F-SHP-012", "F-SHP-021", "F-SHP-023",
                "F-SYS-011", "F-SYS-012", "F-SYS-013", "F-SYS-021", "F-SYS-031")
def test_g19_write_routes_require_fn_static(world):
    """쓰기 라우트 63(W1 58 + COL 4 + RPT 1) 의 의존성이 require_fn(<그 기능 ID>) 하나다 · 조회 라우트 67 은 require_screen(화면) 또는 require_fn(기능) (정적 · G-19)."""
    app, _ = world
    rep = cs.Report()
    cs.check_functions(app, rep)
    _assert_rows(rep, "G-19")


@pytest.mark.fn("F-HOME-022")
def test_g19_write_58_x_8_403_sweep(world):
    """쓰기 63 × 계정 8 POST(빈 본문 · 없는 경로 키): 칸 R · 없음 → 403 「이 기능을 실행할 권한이 없습니다」 · W 부서는 401/403/5xx 아님 (COL 4 = 회계부 · 전산 관리자 W)
    · 권한 예외 F-HOME-022 · F-RPT-132 는 칸 R 부서가 통과 · F-RPT-132 는 칸 없는 5 부서 403 (api-contract §4)."""
    _, clients = world
    rep = cs.Report()
    cs.check_writes(clients, rep)
    _assert_rows(rep)
