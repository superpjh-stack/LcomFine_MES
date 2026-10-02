"""clr 라우터 — 조색 기록 (기능 5) · 담당 개발2.

쓰는 저장소: D4 (`color_record` `color_record_mix`). 이 밖의 테이블에는 쓰지 않는다(G-05). Job(D2)은 참조만 한다.
색상값은 L·a·b 로 받는다(가설 컬럼, D-18). 규격 값은 받은 적이 없어 화면이 기본값을 채우지 않는다.

  CLR-01 조색 기록 → /clr/records
      F-CLR-01 조색 기록 등록 [등록] POST /clr/records
      F-CLR-02 배합비 등록 [등록] POST /clr/records/{id}/mix
      F-CLR-03 조색 기록 수정 [수정] POST /clr/records/{id}
      F-CLR-04 조색 기록 삭제 [삭제] POST /clr/records/{id}/delete
      F-CLR-05 조색 기록 조회 [조회] GET /clr/records
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from ...db import conn
from .. import nav, rbac, templating
from ..util import audit, http
from .pop import (INT8_MAX, LAB, LIST_LIMIT, RATIO, back_to, bad, date_of, decimal_of, find_job, int_of, job_of, path_id,
                  text_of)

router = APIRouter()

PATH = nav.path_of("CLR-01")
MIX_TOTAL = Decimal("100")
#: 합을 어떻게 세는지 — 422 의 사유와 화면 안내에 같은 문장을 쓴다 (D-209: 판정은 저장되는 값으로)
MIX_RULE = "비율은 소수 셋째 자리까지 저장한다(넘는 자리는 반올림) · 합은 저장되는 값으로 센다"
MIX_BLANK_ROWS = 3          # 배합비 입력 화면의 빈 행 수


def _record(record_id: int) -> dict:
    """경로의 조색 기록 — 없으면 404."""
    row = conn.q1(
        """select c.color_record_id, c.job_id, c.ink_formula_id, c.color_name, c.seq_no, c.color_l, c.color_a, c.color_b,
                  c.note, c.recorded_at, c.recorded_by, j.job_no, k.ink_code
             from color_record c join job j on j.job_id = c.job_id
             left join ink_formula k on k.ink_formula_id = c.ink_formula_id
            where c.color_record_id = %s""", (record_id,))
    if row is None:
        raise http.not_found()
    return row


def _lab(color_l: str, color_a: str, color_b: str) -> tuple:
    return (decimal_of(color_l, "색상값 L", digits=LAB), decimal_of(color_a, "색상값 a", digits=LAB),
            decimal_of(color_b, "색상값 b", digits=LAB))


def _target(r: dict) -> str:
    return f"color_record:{r['job_no']}/{r['color_name']}/{r['seq_no']}"


@router.get(PATH, response_class=HTMLResponse)                            # F-CLR-05 조색 기록 조회
def record_list(request: Request, job_no: str = "", date_from: str = "", date_to: str = "", edit: str = "",
                user: rbac.User = rbac.require_fn("F-CLR-05")):
    """Job 번호·기간으로 검색. 차수 순으로 색상값과 배합비를 보여 준다. `?edit=<id>` 는 그 기록의 수정·배합비 칸을 연다."""
    d1, d2 = date_of(date_from, "기록일(부터)"), date_of(date_to, "기록일(까지)")
    where, params = [], []
    if job_no.strip():
        where.append("j.job_no = any(%s)")
        params.append(sorted({job_no.strip(), job_no.strip().upper()}))
    if d1:
        where.append("c.recorded_at::date >= %s")
        params.append(d1)
    if d2:
        where.append("c.recorded_at::date <= %s")
        params.append(d2)
    rows = conn.q(f"""
        select c.color_record_id, c.color_name, c.seq_no, c.color_l, c.color_a, c.color_b, c.note, c.recorded_at,
               c.recorded_by, j.job_no, k.ink_code, k.ink_name
          from color_record c join job j on j.job_id = c.job_id
          left join ink_formula k on k.ink_formula_id = c.ink_formula_id
          {('where ' + ' and '.join(where)) if where else ''}
         order by j.job_no, c.color_name, c.seq_no limit {LIST_LIMIT}""", params)
    mixes: dict[int, list[dict]] = {}
    if rows:
        for m in conn.q("""select color_record_id, seq_no, component_name, ratio_pct from color_record_mix
                            where color_record_id = any(%s) order by color_record_id, seq_no""",
                        ([r["color_record_id"] for r in rows],)):
            mixes.setdefault(m["color_record_id"], []).append(m)
    editing, editing_mix = None, []
    edit_id = int_of(edit, "조색 기록", maximum=INT8_MAX)
    if edit_id is not None:
        editing = _record(edit_id)
        editing_mix = conn.q("""select seq_no, component_name, ratio_pct from color_record_mix
                                 where color_record_id = %s order by seq_no""", (edit_id,))
    job = find_job(job_no) if job_no.strip() else None
    ink_options = [(r["ink_code"], f"{r['ink_name']} [{r['ink_code']}]") for r in conn.q(
        "select ink_code, ink_name from ink_formula where use_yn = 'Y' order by ink_code")]
    return templating.render(
        request, "clr/records.html",
        {"rows": rows, "mixes": mixes, "editing": editing, "editing_mix": editing_mix, "blank_rows": MIX_BLANK_ROWS,
         "f": {"job_no": job_no.strip(), "date_from": date_from, "date_to": date_to}, "job": job,
         "ink_options": ink_options,
         "can": {"create": user.can("F-CLR-01"), "mix": user.can("F-CLR-02"), "update": user.can("F-CLR-03"),
                 "delete": user.can("F-CLR-04")}},
        screen_id="CLR-01")


@router.post(PATH)                                                        # F-CLR-01 조색 기록 등록
def record_create(request: Request, job_no: str = Form(""), color_name: str = Form(""), seq_no: str = Form(""),
                  color_l: str = Form(""), color_a: str = Form(""), color_b: str = Form(""), ink_code: str = Form(""),
                  note: str = Form(""), user: rbac.User = rbac.require_fn("F-CLR-01")):
    """Job·색 이름·차수·색상값(L·a·b)·기준 잉크조성 → `color_record` 한 행. 차수를 비우면 그 Job·색의 다음 차수."""
    job = job_of(job_no)
    name = text_of(color_name, "색 이름", required=True, max_len=100)
    seq = int_of(seq_no, "차수", minimum=1)
    lab = _lab(color_l, color_a, color_b)
    ink_id = None
    code = text_of(ink_code, "기준 잉크조성")
    if code:
        ink = conn.q1("select ink_formula_id from ink_formula where ink_code = %s", (code,))
        if ink is None:
            raise bad("없는 잉크 코드입니다", "기준 잉크조성", code)
        ink_id = ink["ink_formula_id"]
    with conn.tx() as cur:
        if seq is None:
            cur.execute("select coalesce(max(seq_no), 0) + 1 as n from color_record where job_id = %s and color_name = %s",
                        (job["job_id"], name))
            seq = cur.fetchone()["n"]
        else:
            cur.execute("select 1 from color_record where job_id = %s and color_name = %s and seq_no = %s",
                        (job["job_id"], name, seq))
            if cur.fetchone():
                raise bad("이미 있는 차수입니다", "차수", f"{job['job_no']} · {name} · {seq}차")
        cur.execute(
            """insert into color_record (job_id, ink_formula_id, color_name, seq_no, color_l, color_a, color_b, note, recorded_by)
               values (%s, %s, %s, %s, %s, %s, %s, %s, %s) returning color_record_id""",
            (job["job_id"], ink_id, name, seq, *lab, text_of(note, "비고"), user.login_id))
        record_id = cur.fetchone()["color_record_id"]
    audit.log_change(request, user, "F-CLR-01", f"color_record:{job['job_no']}/{name}/{seq}", "조색 기록 등록")
    return http.saved(request, f"조색 기록을 등록했습니다 — {job['job_no']} · {name} · {seq}차",
                      back=back_to(request, f"{PATH}?job_no={job['job_no']}&edit={record_id}#form"),
                      data={"id": record_id, "job_no": job["job_no"], "color_name": name, "seq_no": seq})


@router.post(PATH + "/{id}/mix")                                          # F-CLR-02 배합비 등록
def mix_replace(request: Request, id: str, component_name: list[str] = Form(default=[]),  # noqa: A002 — 계약의 경로 이름
                ratio_pct: list[str] = Form(default=[]), user: rbac.User = rbac.require_fn("F-CLR-02")):
    """그 조색 기록의 배합비 행(성분·비율)을 **통째로** 바꿔 넣는다. 비율 합이 100 이 아니면 422.

    합은 **저장되는 값**(소수 셋째 자리 — 넘는 자리는 반올림, D-209)으로 센다. 그래서 `33.3333 + 33.3333 + 33.3334` 는 99.999 다 —
    사유에 그 규칙과, 반올림된 행의 「입력 → 저장되는 값」 을 함께 보인다(왜 100 이 아닌지 사용자가 알 수 있게)."""
    rec = _record(path_id(id))
    if len(component_name) != len(ratio_pct):
        raise bad("성분과 비율의 개수가 다릅니다", "배합비", f"성분 {len(component_name)} · 비율 {len(ratio_pct)}")
    mix: list[tuple[str, Decimal]] = []
    rounded: list[dict] = []                            # 소수 셋째 자리를 넘어 반올림된 행 — 합이 어긋났을 때 사유에 보인다
    for n, (comp, ratio) in enumerate(zip(component_name, ratio_pct), start=1):
        if not (comp or "").strip() and not (ratio or "").strip():
            continue                                    # 화면의 빈 행
        name = text_of(comp, f"{n}행 성분", required=True, max_len=100)
        pct = decimal_of(ratio, f"{n}행 비율", required=True, positive=True, digits=RATIO)
        if pct > MIX_TOTAL:
            raise bad("비율은 100 이하여야 합니다", f"{n}행 비율", str(pct))
        typed = ratio.strip().replace(",", "")
        if Decimal(typed) != pct:                       # `decimal_of` 가 담기는 값으로 바꿔 돌려줬다 (D-209)
            rounded.append({"name": f"{n}행 비율", "reason": f"입력 {typed[:40]} → 저장되는 값 {pct}"})
        mix.append((name, pct))
    total = sum((p for _, p in mix), Decimal("0"))
    if total != MIX_TOTAL:
        raise http.validation_error("배합비의 합이 100 이 아닙니다", fields=[
            {"name": "배합비 합", "reason": f"{total} (행 {len(mix)}개) — {MIX_RULE}"}, *rounded])
    with conn.tx() as cur:
        cur.execute("delete from color_record_mix where color_record_id = %s", (rec["color_record_id"],))
        for seq, (name, pct) in enumerate(mix, start=1):
            cur.execute("""insert into color_record_mix (color_record_id, seq_no, component_name, ratio_pct)
                           values (%s, %s, %s, %s)""", (rec["color_record_id"], seq, name, pct))
    audit.log_change(request, user, "F-CLR-02", _target(rec), f"배합비 {len(mix)}행")
    return http.saved(request, f"배합비를 저장했습니다 — {len(mix)}행 · 합 100",
                      data={"id": rec["color_record_id"], "rows": len(mix)})


@router.post(PATH + "/{id}/delete")                                       # F-CLR-04 조색 기록 삭제
def record_delete(request: Request, id: str, user: rbac.User = rbac.require_fn("F-CLR-04")):  # noqa: A002
    """조색 기록과 그 배합비 행을 지운다."""
    rec = _record(path_id(id))
    with conn.tx() as cur:
        cur.execute("delete from color_record_mix where color_record_id = %s", (rec["color_record_id"],))
        cur.execute("delete from color_record where color_record_id = %s", (rec["color_record_id"],))
    audit.log_change(request, user, "F-CLR-04", _target(rec), "조색 기록 삭제")
    return http.saved(request, "조색 기록을 삭제했습니다", back=back_to(request, f"{PATH}?job_no={rec['job_no']}"),
                      data={"id": rec["color_record_id"]})


@router.post(PATH + "/{id}")                                              # F-CLR-03 조색 기록 수정
def record_update(request: Request, id: str, color_name: str = Form(""), color_l: str = Form(""),  # noqa: A002
                  color_a: str = Form(""), color_b: str = Form(""), note: str = Form(""),
                  user: rbac.User = rbac.require_fn("F-CLR-03")):
    """색상값·색 이름·비고를 고친다. Job 과 차수는 못 바꾼다."""
    rec = _record(path_id(id))
    name = text_of(color_name, "색 이름", required=True, max_len=100)
    lab = _lab(color_l, color_a, color_b)
    with conn.tx() as cur:
        cur.execute("""select 1 from color_record
                        where job_id = %s and color_name = %s and seq_no = %s and color_record_id <> %s""",
                    (rec["job_id"], name, rec["seq_no"], rec["color_record_id"]))
        if cur.fetchone():
            raise bad("그 색 이름에 같은 차수가 이미 있습니다", "색 이름", f"{name} · {rec['seq_no']}차")
        cur.execute("""update color_record
                          set color_name = %s, color_l = %s, color_a = %s, color_b = %s, note = %s,
                              updated_at = now(), updated_by = %s
                        where color_record_id = %s""",
                    (name, *lab, text_of(note, "비고"), user.login_id, rec["color_record_id"]))
    audit.log_change(request, user, "F-CLR-03", _target(rec), "조색 기록 수정")
    return http.saved(request, "조색 기록을 수정했습니다", data={"id": rec["color_record_id"]})
