# tests/test_qa1_doc.py — QA1 W4 문서 SSO (DOC-010 문서관리 바로가기 · DOC-020 문서관리 계정 매핑 · 기능 6).
# tools/check_screens.py 의 W4 몫을 그대로 돈다: QA1 세계(접두 `QA1-…-`)에 사용자 5(DA 생산부 · DB 출하실 · DC 회계부 · DD 디자인·개발실 · DE 전략부)를
# SYS-010 HTTP 로 만들고 DA · DC 를 DOC-020 으로 잇는다 → F-DOC-011 의 주소 없음 422 `미확정 (D-517)` · 성공(가짜 주소 · `fake_sso()` 안에서만 · 외부 전송 0)
# JSON 200(토큰 없음 · jti) · 브라우저 200 자동 POST 폼(hidden 토큰 · data-auto-submit · method post) · 변경 로그 1행 · SSO 로그 · 매핑 없음 · 사용 중지 · 비활성 거부 ·
# F-DOC-021~023 의 누락 · NUL · 1:1 · 엑셀(아닌 파일 · 헤더 · 오류 행 하나 → 전체 거부) · 404 · DOC-010 · DOC-020 의 정본 L3 · logic 을 확인하고 자기 행만 지운다.
# 기대값은 계약(function-list.md F-DOC-011 · 012 · 021~024 · api-contract.md §2 F-DOC-011 예외 · §4 권한 예외 · permission-matrix DOC 칸 9 ·
# ia.json DOC-010 · DOC-020 · decisions.md D-514 · D-517 · D-610 · D-611)에서 끌어온다. 고치지 않는다 — 결함 테스트는 실패 상태로 둔다(xfail · skip 없음).
import pytest

from tools import check_screens as cs

DOC_ALL = ("F-DOC-011", "F-DOC-012", "F-DOC-021", "F-DOC-022", "F-DOC-023", "F-DOC-024")
DOC_WRITES = ("F-DOC-011", "F-DOC-021", "F-DOC-022", "F-DOC-023")


@pytest.fixture(scope="module")
def lab():
    app, clients = cs.app_and_clients()
    w = cs.World(clients)
    try:
        w.build()
        assert not w.failed_steps(), "QA1 세계 만들기 실패:\n" + "\n".join(w.failed_steps())
        for k in ("docDA", "docDB", "docDC"):
            assert k in w.clients, f"QA1 DOC 사용자 세션이 없다 — {k}"
        results = cs.run_cases(w, [c for c in cs.cases(w) if c.fid.startswith("F-DOC-")])
        rep = cs.Report()
        contract = cs.check_doc_contract(w, rep)          # 가짜 SSO 주소는 함수 안에서만 · 되돌림
        yield {"app": app, "world": w, "clients": clients, "results": results, "contract": contract, "rep": rep}
    finally:
        w.cleanup()
    assert not w.leftovers(), f"정리 후 남은 QA1 행 {w.leftovers()}"


def _items(contract, *keys) -> list[dict]:
    out = [x for x in contract if any(k in x["item"] for k in keys)]
    assert out, f"계약 문장 항목이 없다 — {keys}"
    return out


def _assert_items(contract, *keys) -> None:
    bad = [f"{x['item']} — {x['actual']}" for x in _items(contract, *keys) if not x["ok"]]
    assert not bad, "\n".join(bad)


def _rows(rep: cs.Report) -> None:
    bad = [(g, item, actual) for g, item, ok, actual in rep.rows if not ok]
    if bad:
        details = dict(rep.details)
        lines = []
        for g, item, actual in bad:
            lines.append(f"{g} {item} — {actual}")
            lines += [f"    - {b}" for b in details.get(f"{g} {item}", [])[:25]]
        pytest.fail("\n".join(lines))


# ── G-02 · G-19 — 기능 6 ↔ 라우트 ↔ 표식 · require_fn / require_screen (정적) ───────────────────────────────

@pytest.mark.fn(*DOC_ALL)
def test_g02_doc_6_functions_route_marks_and_deps(lab):
    """범위 기능 134(W1~W4 · LATER_MENUS 비움): API 가 라우트에 글자 그대로 · 표식 · 쓰기 66(DOC 4) 은 require_fn(<그 기능 ID>) 하나 ·
    조회 68(DOC 2) 는 require_screen(화면). DOC 6 의 메서드 · 경로 · 권한 예외는 function-list 그대로."""
    from lcomfine.app import contracts

    assert cs.LATER_MENUS == ()
    rep = cs.Report()
    cs.check_functions(lab["app"], rep)
    _rows(rep)
    doc = {f.id: f for f in cs.w1_functions() if f.menu_code == "DOC"}
    assert sorted(doc) == sorted(DOC_ALL)
    assert {f.id for f in doc.values() if f.is_write} == set(DOC_WRITES)
    assert [(doc[i].method, doc[i].path) for i in DOC_ALL] == [
        ("POST", "/doc/go"), ("GET", "/doc/go"), ("POST", "/doc/account-map"), ("POST", "/doc/account-map/{id}"),
        ("POST", "/doc/account-map/{id}/delete"), ("GET", "/doc/account-map")]
    assert contracts.function("F-DOC-011").permission_exception
    assert not any(contracts.function(i).permission_exception for i in DOC_ALL if i != "F-DOC-011")


# ── G-03 · G-19 — DOC 2 × 8 계정 200/403 · 메뉴 · 쓰기 × 8 ───────────────────────────────────────────────

@pytest.mark.fn("F-DOC-012", "F-DOC-024")
def test_g03_g19_doc_2_x_8_200_403_and_menu(lab):
    """DOC-010 은 8 부서 모두 R → 200 · 메뉴에 있음(「문서관리 접근」 칸) · DOC-020 은 ADM 만 W → 200, 나머지 7 → 403 「이 화면을 볼 권한이 없습니다」
    (브라우저 · JSON) · 메뉴에 없음 · placeholder 0. 기대값 = permission-matrix(DOC-010 8 · DOC-020 1 = 9 칸)."""
    from lcomfine.app import contracts, nav

    cells = {(sid, rc): lv for sid, rc, lv in contracts.permission_cells()}
    assert {rc for (sid, rc) in cells if sid == "DOC-010"} == set(cs.CODE_OF.values())
    assert {(rc, lv) for (sid, rc), lv in cells.items() if sid == "DOC-020"} == {("ADM", "W")}
    assert not ({nav.path_of("DOC-010"), nav.path_of("DOC-020")} & set(lab["app"].state.placeholder_paths))
    bad = []
    for lid, c in lab["clients"].items():
        rc = cs.CODE_OF[lid]
        menu = cs.parse(c.get("/", headers=cs.HTML).text).menu
        for sid in ("DOC-010", "DOC-020"):
            path = nav.path_of(sid)
            rb = c.get(path, headers=cs.HTML, follow_redirects=False)
            rj = c.get(path, follow_redirects=False)
            if (sid, rc) in cells:
                if rb.status_code != 200 or sid not in menu:
                    bad.append(f"{lid} {sid} 칸 {cells[(sid, rc)]} → {rb.status_code} · 메뉴 {sid in menu}")
            elif not (rb.status_code == 403 and rj.status_code == 403 and cs.jget(rj, "message") == "이 화면을 볼 권한이 없습니다"
                      and sid not in menu):
                bad.append(f"{lid} {sid} 칸 없음 → 브라우저 {rb.status_code} · JSON {rj.status_code} {cs.jget(rj, 'message')!r} · 메뉴 {sid in menu}")
    assert not bad, "\n".join(bad)


@pytest.mark.fn(*DOC_WRITES)
def test_g19_doc_writes_x_8_and_permission_exception(lab):
    """쓰기 4 × 계정 8 (빈 본문 · 없는 경로 키): F-DOC-011 은 권한 예외 — 칸 R 8 부서 전부 통과(주소 없음 → 422 · 5xx 0) ·
    F-DOC-021~023 은 ADM 만 통과(422/404), 나머지 7 → 403 「이 기능을 실행할 권한이 없습니다」. 칸이 없으면 F-DOC-011 도 403(api-contract §4 —
    정본은 칸 없는 부서가 없어 `rbac.level` 을 프로세스 안에서 잠깐 바꿔 흉내 낸다)."""
    from lcomfine.app import contracts

    bad = []
    for fid in DOC_WRITES:
        f = contracts.function(fid)
        path = cs.fill(f.path, cs.NOID)
        for lid, c in lab["clients"].items():
            r = c.post(path, data={}, follow_redirects=False)
            allowed = fid == "F-DOC-011" or lid == "admin"
            if allowed and (r.status_code in (401, 403) or r.status_code >= 500):
                bad.append(f"{fid} {lid} POST {path} → {r.status_code} (권한 통과 기대)")
            if not allowed and not (r.status_code == 403 and cs.jget(r, "message") == "이 기능을 실행할 권한이 없습니다"):
                bad.append(f"{fid} {lid} POST {path} → {r.status_code} {cs.jget(r, 'message')!r} (403 기대)")
    assert not bad, "\n".join(bad)
    item, ok, actual = cs.doc_exception_denied(lab["clients"])
    assert ok, f"{item} — {actual}"


# ── 오류 계약 — 쓰기 4 (api-contract §1 · §2 예외 · §3 · D-611) ─────────────────────────────────────────

@pytest.mark.fn(*DOC_WRITES)
def test_doc_error_contract_cases(lab):
    """F-DOC-011 주소 없음 422 「미확정 (D-517) — 토큰을 발급하지 않았습니다」 · F-DOC-021 누락 · NUL · 201자 · 없는 사용자 · 1:1(사용자 · 계정 ID) ·
    엑셀 아닌 파일 · 빈 파일 · 헤더 틀림 · 행 0 · 5MB 초과 · zip · 5,001행 · 오류 행 하나 → 전체 거부 · F-DOC-022 누락 · NUL · 사용 여부 · 1:1 · 사용자 변경 ·
    404 · F-DOC-023 404 — 전부 계약 상태 · 모양(422 code · message · fields / 404 not_found) · 5xx 0 · 422 가 항목을 짚음(「입력」 한 줄 아님)."""
    res = lab["results"]
    assert {x["fid"] for x in res} == set(DOC_WRITES)
    bad = [f"{x['fid']} {x['label']} — [{x['login']}] POST {x['path']} → {x['status']} {x['message']!r} {x['why']}" for x in res if not x["ok"]]
    assert not bad, "\n".join(bad)
    assert not [x for x in res if cs.server_error(x["status"])]
    assert not [x for x in res if x["generic_db_422"]]
    assert sum(1 for x in res if x["expect"] == 404) == 4 and sum(1 for x in res if x["expect"] == 422) >= 24


@pytest.mark.fn("F-DOC-011", "F-DOC-012")
def test_doc_go_without_url_is_422_d517_and_guide(lab):
    """주소(`LCOMFINE_DOC_SSO_URL`) 없음 — GET 안내 `미확정 (D-517)` · 토큰 칸 없음 · POST JSON 422 fields `SSO 설정` · 브라우저 303 → /doc/go ·
    토큰 0행 · SSO 로그 실패 (계약 §2 예외 · D-610 — 501 아님)."""
    _assert_items(lab["contract"], "주소 없음 GET", "주소 없음 POST", "주소 없음 경우")


@pytest.mark.fn("F-DOC-011")
def test_doc_go_success_json_no_token_and_browser_auto_post_form(lab):
    """가짜 주소 · `fake_sso()` 안에서만: JSON 200 `{ok, jti, ttl_seconds 60, method POST}` · 토큰 글자 없음 · sso_token 1행 · `sys_change_log` 1행 ·
    브라우저 200 자동 POST 폼(action = 주소 · method post · data-auto-submit · hidden token 1 · 「문서관리 열기」) · 토큰이 주소 · 로그에 없음 ·
    `sso.consume` 통과 → 재사용 거부 · app.js 자동 제출 보조 · 설정 되돌림."""
    _assert_items(lab["contract"], "F-DOC-011 JSON 성공", "F-DOC-011 브라우저 성공", "static/app.js", "가짜 SSO 주소 되돌림")


@pytest.mark.fn("F-DOC-011", "F-DOC-012", "F-DOC-022")
def test_doc_go_refused_unmapped_disabled_inactive(lab):
    """「계정 매핑이 없거나 비활성 사용자면 토큰을 발급하지 않고 "관리자에게 계정 연결을 요청하세요"」 — 매핑 없음(GET 안내 · POST 422 `계정 매핑`) ·
    사용 중지 매핑(F-DOC-022 use_yn N → 422 · 미연결 목록 비고) · 비활성(SYS-010 중지 → 그 세션 401 · sso.refusal 비활성) — 토큰 0."""
    _assert_items(lab["contract"], "계정 매핑이 없으면", "사용 중지(use_yn N)", "비활성으로 바꾸면")


# ── 계약 문장 — DOC-010 · DOC-020 (정본 L3 · logic · 사람 판정은 outputs/qa1-기능계약.md W4-4) ──────────────

@pytest.mark.fn("F-DOC-012")
def test_doc_010_l3_logic_text_and_sso_log(lab):
    """DOC-010: 매핑 있는 사용자 GET 200 · POST 폼 target=_blank(새 창) · 연결된 계정 ID · GET 은 발급 안 함 · 서명 · 60초 · 한 번만 · POST ·
    검증 실패 시 문서관리 로그인 화면에서 직접 로그인 · 문서별 권한 · SAML/OIDC `미확정 (D-517)` · SSO 호출 로그(SYS-040 SSO 탭)."""
    _assert_items(lab["contract"], "DOC-010 바로가기 — 매핑", "DOC-010 logic — 서명", "로그인된 상태", "SSO 호출(사용자")


@pytest.mark.fn("F-DOC-012")
def test_doc_010_menu_click_opens_new_window(lab):
    """DEF-QA1-010 — 정본 L3 「메뉴 클릭 → 새 창」 · F-DOC-011 「메뉴를 누르면 … 토큰을 발급 … 새 창으로 … 연다」.
    지금: 좌측 메뉴 `<a href="/doc/go">`(같은 창) → 안내 화면 → 「문서관리 열기 (새 창)」 단추를 한 번 더 눌러야 발급된다.
    해소(아키텍트 판정 = 정본대로): 메뉴 링크 target=_blank · 준비됐을 때 진입 폼 data-auto-submit · 준비 안 됐을 때(매핑 없음 · 주소 없음) 자동 제출 없음."""
    _assert_items(lab["contract"], "(DEF-QA1-010) — 메뉴 링크")


@pytest.mark.fn("F-DOC-024")
def test_doc_020_l3_logic_and_edit_404(lab):
    """DOC-020: 「MES 사용자 ↔ 문서관리 계정 ID」 표 · 「미연결 사용자 목록」(매핑 없는 QA1 사용자 있음 · 매핑된 사용자 없음) · 「엑셀 일괄 등록」 multipart 폼 ·
    1:1 · 사번 동일 방식 `미확정 (D-517)` · 매핑 필수 · `?edit=` 없는 매핑 / abc 404."""
    _assert_items(lab["contract"], "DOC-020 L3", "DOC-020 logic 「1:1」", "F-DOC-024 `?edit=`")


@pytest.mark.fn("F-DOC-021")
def test_doc_021_bulk_one_bad_row_rejects_all_then_good_file(lab):
    """엑셀 일괄(D-611): 오류 행 하나(없는 사번 · 빈 줄 · 다른 열) → 422 fields `4행` · 0행 등록 → 정상 2행(열 순서 바뀜) → 200 count 2 · 변경 로그 1행."""
    _assert_items(lab["contract"], "F-DOC-021 엑셀 — 오류 행 하나", "F-DOC-021 엑셀 — 정상")


@pytest.mark.fn("F-DOC-022", "F-DOC-023")
def test_doc_022_update_and_023_delete_or_disable(lab):
    """F-DOC-022 수정 → 계정 ID 바뀜 · 변경 로그 1 · F-DOC-023 발급 기록 없음 → 삭제 · 있음 → 사용 중지(active false) · 변경 로그 각 1."""
    _assert_items(lab["contract"], "F-DOC-022 수정", "F-DOC-023 삭제")


def test_doc_contract_row_and_no_other_misses(lab):
    """check_doc_contract 의 G-02 행 — 어긋남 0 (DEF-QA1-010 해소 뒤)."""
    bad = [x["item"] for x in lab["contract"] if not x["ok"]]
    assert not bad, "\n".join(bad)
    assert len(lab["contract"]) >= 21
