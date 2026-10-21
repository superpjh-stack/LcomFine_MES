# tests/test_qa1_errors.py — QA1 G-02 오류 계약 (api-contract §1 · §2 · §3 · goal §2.7) — tools/check_screens.py 의 사례를 그대로 돈다.
# QA1 세계(접두 `QA1-…-`)를 화면이 부르는 HTTP 로 만들고(admin), 쓰기 기능 58 마다 누락 422 · 없는 경로 키 404 · 미확정 501 · NUL · 자릿수 · 음수 422
# 를 두드린 뒤 지운다. 테스트는 JSON 쪽으로 판정한다(api-contract §2 — TestClient 기본 Accept */*).
import pytest

from tools import check_screens as cs


@pytest.fixture(scope="module")
def lab():
    app, clients = cs.app_and_clients()
    w = cs.World(clients)
    try:
        w.build()
        assert not w.failed_steps(), "QA1 세계 만들기 실패:\n" + "\n".join(w.failed_steps())
        assert "qa1" in w.clients, "QA1 사용자(영업부) 로그인 실패"
        results = cs.run_cases(w, cs.cases(w))
        html = cs.world_html(w)
        yield {"world": w, "clients": clients, "results": results, "html": html}
    finally:
        w.cleanup()
    assert not w.leftovers(), f"정리 후 남은 QA1 행 {w.leftovers()}"


def _fmt(x: dict) -> str:
    return f"{x['fid']} {x['label']} — [{x['login']}] POST {x['path']} {x['data']} → {x['status']} {x['message']!r} {x['why']}".strip()


def _bad(results, pred) -> list[str]:
    return [_fmt(x) for x in results if pred(x) and not x["ok"]]


def _covered(results, pred, at_least: int) -> None:
    n = sum(1 for x in results if pred(x))
    assert n >= at_least, f"사례가 {n} 뿐이다 (기대 ≥ {at_least}) — 검사기 사례가 줄었다"


@pytest.mark.fn("F-BAS-011", "F-BAS-021", "F-BAS-031", "F-STD-011", "F-STD-021", "F-STD-031", "F-STD-041", "F-STD-051", "F-STD-061",
                "F-WO-011", "F-WO-021", "F-MAT-011", "F-MAT-021", "F-MAT-031", "F-PRD-011", "F-INS-011", "F-QC-011", "F-QC-021",
                "F-INV-021", "F-INV-031", "F-SHP-011", "F-SYS-011", "F-SYS-021", "F-SYS-031", "F-HOME-031")
def test_missing_required_is_422_with_fields(lab):
    """필수값 누락(빈 본문) → 422 `validation_error` + 사람이 읽는 message + 항목별 fields (api-contract §1)."""
    res = lab["results"]
    pred = lambda x: x["label"].startswith("누락")  # noqa: E731
    _covered(res, pred, 45)        # 2026-10-21 실측 47 (쓰기 58 중 경로 키만 받는 처리 · 삭제 11 은 빈 본문이 404 다)
    assert not _bad(res, pred), "\n".join(_bad(res, pred))


@pytest.mark.fn("F-HOME-022", "F-BAS-012", "F-BAS-013", "F-BAS-022", "F-BAS-023", "F-BAS-032", "F-BAS-033", "F-STD-012", "F-STD-013",
                "F-STD-022", "F-STD-023", "F-STD-032", "F-STD-033", "F-STD-042", "F-STD-052", "F-STD-062", "F-STD-063",
                "F-WO-012", "F-WO-022", "F-WO-031", "F-MAT-012", "F-MAT-022", "F-MAT-032", "F-PRD-012", "F-INS-012", "F-QC-012", "F-QC-022",
                "F-INV-022", "F-SHP-012", "F-SHP-021", "F-SHP-023", "F-SYS-012", "F-SYS-013")
def test_path_key_not_found_is_404(lab):
    """경로의 키가 없거나(999999999) 숫자가 아니면(abc) → 404 `not_found` — 화면마다 같다 (api-contract §1 「422 와 404 의 경계」)."""
    res = lab["results"]
    pred = lambda x: x["expect"] == 404  # noqa: E731
    _covered(res, pred, 60)
    assert not _bad(res, pred), "\n".join(_bad(res, pred))


@pytest.mark.fn("F-WO-021", "F-SYS-031")
def test_user_typed_missing_id_follows_contract(lab):
    """본문의 없는 ID — 계약이 404 로 적은 곳(F-WO-021 「없는 의뢰 404」 · F-SYS-031 `id`)은 404, 사용자가 입력한 없는 LOT 번호는 422."""
    res = lab["results"]
    pred = lambda x: x["fid"] in ("F-WO-021", "F-SYS-031") and x["expect"] == 404 and "경로" not in x["label"]  # noqa: E731
    _covered(res, pred, 2)
    assert not _bad(res, pred), "\n".join(_bad(res, pred))
    lot = lambda x: "없는 LOT 번호" in x["label"]  # noqa: E731
    _covered(res, lot, 4)
    assert not _bad(res, lot), "\n".join(_bad(res, lot))


@pytest.mark.fn("F-HOME-031")
def test_undecided_is_501_with_decision(lab):
    """사람이 정하지 않은 연계(메일 · 메신저) → 501 `undecided` · message 에 `미확정 (D-518)` (api-contract §1 · D-518)."""
    res = lab["results"]
    pred = lambda x: x["expect"] == 501  # noqa: E731
    _covered(res, pred, 1)
    assert not _bad(res, pred), "\n".join(_bad(res, pred))


@pytest.mark.fn("F-HOME-031")
def test_home_030_ruling_24(lab):
    """HOME-030 저장 (Ruling 24 · D-526): 자기 부서(영업부)가 받는 이벤트만 — 다른 부서 이벤트 구독 422 「다른 부서…」 · 부서 기본 알림 끄기 422
    「끌 수 없…」 · 전부 켠 채 저장 200 · 누락 422 · NUL 이벤트 키 422."""
    res = lab["results"]
    pred = lambda x: x["fid"] == "F-HOME-031"  # noqa: E731
    _covered(res, pred, 6)
    assert not _bad(res, pred), "\n".join(_bad(res, pred))


@pytest.mark.fn("F-WO-011", "F-WO-021", "F-MAT-011", "F-MAT-021", "F-MAT-031", "F-PRD-011", "F-INS-011", "F-INV-021", "F-INV-031",
                "F-SHP-011", "F-SHP-023", "F-STD-011", "F-SYS-031")
def test_out_of_range_numbers_and_bad_dates_are_422(lab):
    """DB 가 담을 수 없는 값 — 자릿수 초과 · integer 초과 · 음수 · 0 · 형식이 틀린 날짜 → 422, 500 아님 (api-contract §3)."""
    res = lab["results"]
    pred = lambda x: any(k in x["label"] for k in ("자릿수", "초과", "음수", "수량 0", "형식 오류"))  # noqa: E731
    _covered(res, pred, 30)
    assert not _bad(res, pred), "\n".join(_bad(res, pred))


def test_no_case_returns_500(lab):
    """사례 어디서도 5xx(501 제외)가 나오지 않는다 — 입력값 오류는 500 이 아니다 (goal §2.5 · api-contract §3)."""
    s500 = [_fmt(x) for x in lab["results"] if cs.server_error(x["status"])]
    assert not s500, "\n".join(s500)


@pytest.mark.fn("F-BAS-011", "F-BAS-021", "F-WO-011", "F-MAT-011", "F-QC-011", "F-INV-031", "F-SHP-011", "F-SHP-023", "F-SYS-011")
def test_nul_input_is_422_and_names_the_field(lab):
    """NUL(0x00) 이 든 글자 → 422 이고 **어느 항목인지 짚는다** — api-contract §3 「사람이 읽을 문장(어느 항목이 …)은 라우터가 먼저 검사해서 준다 —
    핸들러는 마지막 방어선」. fields 가 「입력」 한 줄뿐이면 결함(경미)."""
    res = lab["results"]
    pred = lambda x: "NUL" in x["label"]  # noqa: E731
    _covered(res, pred, 25)
    assert not _bad(res, pred), "\n".join(_bad(res, pred))
    generic = [_fmt(x) for x in res if pred(x) and x["generic_db_422"]]
    assert not generic, "항목을 짚지 않는 NUL 422:\n" + "\n".join(generic)


def test_screen_get_query_inputs_nul_and_bad_date_not_500(lab):
    """W1 화면의 GET 조회 칸 전부에 NUL · 틀린 날짜 → 500 0 · 틀린 날짜를 200 으로 받아들인 칸 0 (api-contract §2 「422 (브라우저 GET)」)."""
    rep = cs.Report()
    gets = cs.check_get_inputs(lab["clients"], lab["html"], rep)
    assert gets, "조회 칸을 하나도 찾지 못했다"
    s500 = [x for x in gets if cs.server_error(x["status"])]
    bad_date_200 = [x for x in gets if x["tag"] == "틀린 날짜" and x["status"] == 200]
    assert not s500, f"500: {s500}"
    assert not bad_date_200, f"틀린 날짜를 200 으로 받은 칸: {bad_date_200}"
