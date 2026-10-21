"""STD 인쇄 기준 — 제조사양기준서 · 표준관리 · 판관리 · 시안등록 · 표준견본서 · 예외제품관리. 담당 개발1.

- 사양 · 견본서 · 표준의 항목은 양식을 받은 적이 없어 `항목=값` 줄(jsonb)로 사람이 적는 그대로 둔다(항목 이름을 정하지 않는다).
- STD-020 표준 · STD-060 예외제품의 적용 규칙은 미확정 (D-519) — 등록 · 조회만 하고 다른 화면에 적용하지 않는다.
- 시안 이미지는 DB(`artwork.image`)에 두고 목록에서 data URI 로 그린다(계약 밖 이미지 전용 경로를 만들지 않는다).
"""

from __future__ import annotations

import base64

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse
from psycopg.types.json import Jsonb

from ...db import conn
from .. import nav, rbac, templating
from ..util import audit, http
from .bas import (bad, day, edit_row, exists_or_404, integer, item_choice, items_for_select, kv_lines, kv_text,
                  like, need, pk, ref_id, remove_or_disable, s, yn)

router = APIRouter()

DISABLED_MSG = "참조가 있어 지우지 않고 사용 중지로 바꿨습니다"


def _saved(request, user, fn_id: str, screen_id: str, msg: str, target: str, detail: str = "", data=None):
    resp = http.saved(request, msg, back=nav.path_of(screen_id), data=data)
    audit.log_change(request, user, fn_id, target, detail or msg)
    return resp


# ── STD-010 제조사양기준서 ──────────────────────────────────────────────
@router.get(nav.path_of("STD-010"), response_class=HTMLResponse)
def spec_sheets(request: Request, item: str | None = None, q: str | None = None, use: str | None = None,
                edit: str | None = None, user: rbac.User = rbac.require_screen("STD-010")):
    """F-STD-014 — 제품별 사양 목록. 생산지시서를 만들 때 이 사양을 불러온다(사용 중지 사양은 불러오지 않는다)."""
    rows = conn.q(
        """select s.id, s.item_id, i.item_code, i.item_name, s.revision, s.title, s.content, s.note, s.use_yn,
                  (select count(*) from work_order w where w.spec_sheet_id = s.id) as order_count
             from spec_sheet s join item i on i.id = s.item_id
            where (%(item)s::bigint is null or s.item_id = %(item)s)
              and (%(q)s::text is null or s.title ilike %(q)s or i.item_code ilike %(q)s or i.item_name ilike %(q)s)
              and (%(u)s::text is null or s.use_yn = %(u)s)
            order by i.item_code, s.revision desc limit 1000""",
        {"item": ref_id(item, "제품", required=False), "q": like(q), "u": s(use, "사용 여부")})
    ed = edit_row("spec_sheet", edit)
    return templating.render(request, "std/spec_sheets.html",
                             {"rows": rows, "edit": ed, "edit_content": kv_lines(ed["content"]) if ed else "",
                              "items": items_for_select(), "form": {"item": item or "", "q": q or "", "use": use or ""}},
                             screen_id="STD-010")


@router.post("/std/spec-sheets")
def spec_sheet_create(request: Request, item_id: str | None = Form(None), revision: str | None = Form(None),
                      title: str | None = Form(None), content: str | None = Form(None), note: str | None = Form(None),
                      user: rbac.User = rbac.require_fn("F-STD-011")):
    iid = ref_id(item_id, "제품")
    ttl = need(title, "제목")
    body = kv_text(content, "사양 항목")
    rev = integer(revision, "개정 차수", minimum=1)
    with conn.tx() as cur:
        it = item_choice(cur, iid, "제품")
        if rev is None:
            cur.execute("select coalesce(max(revision), 0) + 1 as r from spec_sheet where item_id = %s", (iid,))
            rev = cur.fetchone()["r"]
        cur.execute("select 1 from spec_sheet where item_id = %s and revision = %s", (iid, rev))
        if cur.fetchone():
            raise bad("개정 차수", str(rev), f"그 제품에 이미 있는 개정 차수입니다 ({it['item_code']} · {rev})")
        cur.execute("""insert into spec_sheet (item_id, revision, title, content, note, created_by)
                       values (%s, %s, %s, %s, %s, %s) returning id""",
                    (iid, rev, ttl, Jsonb(body), s(note, "비고"), user.login_id))
        new_id = cur.fetchone()["id"]
    return _saved(request, user, "F-STD-011", "STD-010", "제조사양기준서를 등록했습니다",
                  f"spec_sheet:{it['item_code']}#{rev}", data={"id": new_id, "revision": rev})


@router.post("/std/spec-sheets/{id}")
def spec_sheet_update(request: Request, id: str, title: str | None = Form(None), content: str | None = Form(None),
                      note: str | None = Form(None), use_yn: str | None = Form(None),
                      user: rbac.User = rbac.require_fn("F-STD-012")):
    sid = pk(id)
    ttl = need(title, "제목")
    body = kv_text(content, "사양 항목")
    use = yn(use_yn)
    with conn.tx() as cur:
        row = exists_or_404(cur, "spec_sheet", sid, "id, item_id, revision")
        cur.execute("""update spec_sheet set title = %s, content = %s, note = %s, use_yn = %s, updated_at = now(),
                              updated_by = %s where id = %s""",
                    (ttl, Jsonb(body), s(note, "비고"), use, user.login_id, sid))
    return _saved(request, user, "F-STD-012", "STD-010", "제조사양기준서를 수정했습니다",
                  f"spec_sheet:{sid}#{row['revision']}", f"사양 수정 · 사용 {use}", data={"id": sid})


@router.post("/std/spec-sheets/{id}/delete")
def spec_sheet_delete(request: Request, id: str, user: rbac.User = rbac.require_fn("F-STD-013")):
    sid = pk(id)
    with conn.tx() as cur:
        exists_or_404(cur, "spec_sheet", sid, "id")
        done = remove_or_disable(cur, "spec_sheet", sid, user)
    return _saved(request, user, "F-STD-013", "STD-010", DISABLED_MSG if done == "사용 중지" else "사양을 삭제했습니다",
                  f"spec_sheet:{sid}", f"사양 {done}", data={"id": sid, "result": done})


# ── STD-020 표준관리 (적용 규칙 미확정 D-519) ───────────────────────────
@router.get(nav.path_of("STD-020"), response_class=HTMLResponse)
def standards(request: Request, q: str | None = None, use: str | None = None, edit: str | None = None,
              user: rbac.User = rbac.require_screen("STD-020")):
    """F-STD-024 — 표준 조건 목록."""
    rows = conn.q("""select id, standard_code, standard_name, content, note, use_yn from standard
                      where (%(q)s::text is null or standard_code ilike %(q)s or standard_name ilike %(q)s)
                        and (%(u)s::text is null or use_yn = %(u)s)
                      order by standard_code limit 1000""", {"q": like(q), "u": s(use, "사용 여부")})
    ed = edit_row("standard", edit)
    return templating.render(request, "std/standards.html",
                             {"rows": rows, "edit": ed, "edit_content": kv_lines(ed["content"]) if ed else "",
                              "form": {"q": q or "", "use": use or ""}}, screen_id="STD-020")


@router.post("/std/standards")
def standard_create(request: Request, standard_code: str | None = Form(None), standard_name: str | None = Form(None),
                    content: str | None = Form(None), note: str | None = Form(None),
                    user: rbac.User = rbac.require_fn("F-STD-021")):
    code = need(standard_code, "표준 코드")
    name = need(standard_name, "표준명")
    body = kv_text(content, "조건 항목")
    with conn.tx() as cur:
        cur.execute("select 1 from standard where standard_code = %s", (code,))
        if cur.fetchone():
            raise bad("표준 코드", code, "이미 있는 표준 코드입니다")
        cur.execute("""insert into standard (standard_code, standard_name, content, note, created_by)
                       values (%s, %s, %s, %s, %s) returning id""", (code, name, Jsonb(body), s(note, "비고"), user.login_id))
        new_id = cur.fetchone()["id"]
    return _saved(request, user, "F-STD-021", "STD-020", "표준을 등록했습니다", f"standard:{code}", data={"id": new_id})


@router.post("/std/standards/{id}")
def standard_update(request: Request, id: str, standard_code: str | None = Form(None),
                    standard_name: str | None = Form(None), content: str | None = Form(None),
                    note: str | None = Form(None), use_yn: str | None = Form(None),
                    user: rbac.User = rbac.require_fn("F-STD-022")):
    sid = pk(id)
    name = need(standard_name, "표준명")
    body = kv_text(content, "조건 항목")
    use = yn(use_yn)
    with conn.tx() as cur:
        row = exists_or_404(cur, "standard", sid, "id, standard_code")
        if s(standard_code, "표준 코드") is not None and s(standard_code, "표준 코드") != row["standard_code"]:
            raise bad("표준 코드", "코드는 바꾸지 않습니다", "표준 코드는 바꿀 수 없습니다")
        cur.execute("""update standard set standard_name = %s, content = %s, note = %s, use_yn = %s, updated_at = now(),
                              updated_by = %s where id = %s""", (name, Jsonb(body), s(note, "비고"), use, user.login_id, sid))
    return _saved(request, user, "F-STD-022", "STD-020", "표준을 수정했습니다", f"standard:{row['standard_code']}",
                  f"표준 수정 · 사용 {use}", data={"id": sid})


@router.post("/std/standards/{id}/delete")
def standard_delete(request: Request, id: str, user: rbac.User = rbac.require_fn("F-STD-023")):
    sid = pk(id)
    with conn.tx() as cur:
        row = exists_or_404(cur, "standard", sid, "id, standard_code")
        done = remove_or_disable(cur, "standard", sid, user)
    return _saved(request, user, "F-STD-023", "STD-020", DISABLED_MSG if done == "사용 중지" else "표준을 삭제했습니다",
                  f"standard:{row['standard_code']}", f"표준 {done}", data={"id": sid, "result": done})


# ── STD-030 판관리 (판 + 사용 이력) ─────────────────────────────────────
def _usage(cur, plate_id: int, used_on, work_order_no: str | None, usage_note: str | None, user) -> str | None:
    """사용 이력 한 행 — 사용일이 있을 때만. 지시번호는 사용자가 입력한 값이라 없으면 422."""
    if used_on is None:
        if s(work_order_no, "지시번호") or s(usage_note, "사용 비고"):
            raise bad("사용일", "필수 항목입니다", "사용 이력을 남기려면 사용일을 입력해 주세요")
        return None
    wo_id = None
    if s(work_order_no, "지시번호"):
        cur.execute("select id from work_order where work_order_no = %s", (s(work_order_no, "지시번호"),))
        hit = cur.fetchone()
        if hit is None:
            raise bad("지시번호", s(work_order_no, "지시번호"), "없는 지시번호입니다")
        wo_id = hit["id"]
    cur.execute("insert into plate_usage (plate_id, work_order_id, used_on, note, created_by) values (%s, %s, %s, %s, %s)",
                (plate_id, wo_id, used_on, s(usage_note, "사용 비고"), user.login_id))
    return f" · 사용 이력 {used_on}"


@router.get(nav.path_of("STD-030"), response_class=HTMLResponse)
def plates(request: Request, q: str | None = None, use: str | None = None, edit: str | None = None,
           plate: str | None = None, user: rbac.User = rbac.require_screen("STD-030")):
    """F-STD-034 — 판 목록 · 판 등록·사용 이력."""
    rows = conn.q(
        """select p.id, p.plate_code, p.plate_name, p.item_id, i.item_code, i.item_name, p.made_on, p.storage, p.note,
                  p.use_yn, (select count(*) from plate_usage u where u.plate_id = p.id) as usage_count,
                  (select max(used_on) from plate_usage u where u.plate_id = p.id) as last_used_on
             from plate p left join item i on i.id = p.item_id
            where (%(q)s::text is null or p.plate_code ilike %(q)s or p.plate_name ilike %(q)s)
              and (%(u)s::text is null or p.use_yn = %(u)s)
            order by p.plate_code limit 1000""", {"q": like(q), "u": s(use, "사용 여부")})
    pid = pk(plate) if plate else None
    usage = conn.q(
        """select u.id, p.plate_code, u.used_on, w.work_order_no, u.note, u.created_by
             from plate_usage u join plate p on p.id = u.plate_id left join work_order w on w.id = u.work_order_id
            where (%(p)s::bigint is null or u.plate_id = %(p)s)
            order by u.used_on desc, u.id desc limit 200""", {"p": pid})
    return templating.render(request, "std/plates.html",
                             {"rows": rows, "usage": usage, "edit": edit_row("plate", edit), "plate_id": pid,
                              "items": items_for_select(), "form": {"q": q or "", "use": use or ""}},
                             screen_id="STD-030")


@router.post("/std/plates")
def plate_create(request: Request, plate_code: str | None = Form(None), plate_name: str | None = Form(None),
                 item_id: str | None = Form(None), made_on: str | None = Form(None), storage: str | None = Form(None),
                 note: str | None = Form(None), used_on: str | None = Form(None),
                 work_order_no: str | None = Form(None), usage_note: str | None = Form(None),
                 user: rbac.User = rbac.require_fn("F-STD-031")):
    code = need(plate_code, "판 코드")
    name = need(plate_name, "판 이름")
    iid = ref_id(item_id, "제품", required=False)
    made = day(made_on, "제작일", required=False)
    used = day(used_on, "사용일", required=False)
    with conn.tx() as cur:
        item_choice(cur, iid, "제품")
        cur.execute("select 1 from plate where plate_code = %s", (code,))
        if cur.fetchone():
            raise bad("판 코드", code, "이미 있는 판 코드입니다")
        cur.execute("""insert into plate (plate_code, plate_name, item_id, made_on, storage, note, created_by)
                       values (%s, %s, %s, %s, %s, %s, %s) returning id""",
                    (code, name, iid, made, s(storage, "보관 위치"), s(note, "비고"), user.login_id))
        new_id = cur.fetchone()["id"]
        extra = _usage(cur, new_id, used, work_order_no, usage_note, user) or ""
    return _saved(request, user, "F-STD-031", "STD-030", "판을 등록했습니다", f"plate:{code}", "판 등록" + extra,
                  data={"id": new_id})


@router.post("/std/plates/{id}")
def plate_update(request: Request, id: str, plate_code: str | None = Form(None), plate_name: str | None = Form(None),
                 item_id: str | None = Form(None), made_on: str | None = Form(None), storage: str | None = Form(None),
                 note: str | None = Form(None), use_yn: str | None = Form(None), used_on: str | None = Form(None),
                 work_order_no: str | None = Form(None), usage_note: str | None = Form(None),
                 user: rbac.User = rbac.require_fn("F-STD-032")):
    pid = pk(id)
    name = need(plate_name, "판 이름")
    iid = ref_id(item_id, "제품", required=False)
    made = day(made_on, "제작일", required=False)
    used = day(used_on, "사용일", required=False)
    use = yn(use_yn)
    with conn.tx() as cur:
        row = exists_or_404(cur, "plate", pid, "id, plate_code, item_id")
        if s(plate_code, "판 코드") is not None and s(plate_code, "판 코드") != row["plate_code"]:
            raise bad("판 코드", "코드는 바꾸지 않습니다", "판 코드는 바꿀 수 없습니다")
        item_choice(cur, iid, "제품", allow_inactive_id=row["item_id"])
        cur.execute("""update plate set plate_name = %s, item_id = %s, made_on = %s, storage = %s, note = %s, use_yn = %s,
                              updated_at = now(), updated_by = %s where id = %s""",
                    (name, iid, made, s(storage, "보관 위치"), s(note, "비고"), use, user.login_id, pid))
        extra = _usage(cur, pid, used, work_order_no, usage_note, user) or ""
    return _saved(request, user, "F-STD-032", "STD-030", "판을 수정했습니다", f"plate:{row['plate_code']}",
                  f"판 수정 · 사용 {use}{extra}", data={"id": pid})


@router.post("/std/plates/{id}/delete")
def plate_delete(request: Request, id: str, user: rbac.User = rbac.require_fn("F-STD-033")):
    pid = pk(id)
    with conn.tx() as cur:
        row = exists_or_404(cur, "plate", pid, "id, plate_code")
        done = remove_or_disable(cur, "plate", pid, user)
    return _saved(request, user, "F-STD-033", "STD-030", DISABLED_MSG if done == "사용 중지" else "판을 삭제했습니다",
                  f"plate:{row['plate_code']}", f"판 {done}", data={"id": pid, "result": done})


# ── STD-040 시안등록 ────────────────────────────────────────────────────
#: 받는 이미지 형식 — 파일 머리 바이트로 확인한다(형식 이름만 믿지 않는다). 크기 상한은 가설 D-602
IMAGE_MAGIC: dict[str, tuple[bytes, ...]] = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/gif": (b"GIF87a", b"GIF89a"),
    "image/webp": (b"RIFF",),
}
IMAGE_MAX_BYTES = 5 * 1024 * 1024


async def _image(file: UploadFile | None, *, required: bool) -> tuple[str, str, bytes] | None:
    if file is None or not (file.filename or "").strip():
        if required:
            raise bad("시안 이미지", "필수 항목입니다", "필수 항목을 입력해 주세요 — 시안 이미지")
        return None
    data = await file.read()
    if not data:
        raise bad("시안 이미지", "빈 파일입니다", "이미지 형식 오류 — 빈 파일입니다")
    if len(data) > IMAGE_MAX_BYTES:
        raise bad("시안 이미지", f"{IMAGE_MAX_BYTES // (1024 * 1024)}MB 이하만 올릴 수 있습니다 (D-602)")
    ctype = (file.content_type or "").lower()
    heads = IMAGE_MAGIC.get(ctype)
    if heads is None or not any(data.startswith(h) for h in heads) or (ctype == "image/webp" and data[8:12] != b"WEBP"):
        raise bad("시안 이미지", f"PNG · JPEG · GIF · WEBP 이미지가 아닙니다 ({ctype or '형식 없음'})", "이미지 형식 오류")
    return file.filename.strip(), ctype, data


def data_uri(content_type: str, image: bytes | memoryview | None) -> str | None:
    if image is None:
        return None
    return f"data:{content_type};base64,{base64.b64encode(bytes(image)).decode('ascii')}"


@router.get(nav.path_of("STD-040"), response_class=HTMLResponse)
def artworks(request: Request, item: str | None = None, use: str | None = None, edit: str | None = None,
             user: rbac.User = rbac.require_screen("STD-040")):
    """F-STD-043 — 제품별 시안 목록. 시안 이미지를 제품에 연결해 작업지시와 함께 볼 수 있게 한다."""
    rows = conn.q(
        """select a.id, a.item_id, i.item_code, i.item_name, a.title, a.version, a.file_name, a.content_type, a.image,
                  a.note, a.use_yn, a.updated_at, a.created_at
             from artwork a join item i on i.id = a.item_id
            where (%(item)s::bigint is null or a.item_id = %(item)s) and (%(u)s::text is null or a.use_yn = %(u)s)
            order by i.item_code, a.version desc limit 200""",
        {"item": ref_id(item, "제품", required=False), "u": s(use, "사용 여부")})
    for r in rows:
        r["src"] = data_uri(r["content_type"], r.pop("image"))
    ed = edit_row("artwork", edit)
    if ed:
        ed.pop("image", None)
    return templating.render(request, "std/artworks.html",
                             {"rows": rows, "edit": ed, "items": items_for_select(),
                              "form": {"item": item or "", "use": use or ""}}, screen_id="STD-040")


@router.post("/std/artworks")
async def artwork_create(request: Request, item_id: str | None = Form(None), title: str | None = Form(None),
                         note: str | None = Form(None), image: UploadFile | None = File(None),
                         user: rbac.User = rbac.require_fn("F-STD-041")):
    iid = ref_id(item_id, "제품")
    ttl = need(title, "시안 이름")
    file_name, ctype, data = await _image(image, required=True)
    with conn.tx() as cur:
        it = item_choice(cur, iid, "제품")
        cur.execute("select coalesce(max(version), 0) + 1 as v from artwork where item_id = %s", (iid,))
        ver = cur.fetchone()["v"]
        cur.execute("""insert into artwork (item_id, title, version, file_name, content_type, image, note, created_by)
                       values (%s, %s, %s, %s, %s, %s, %s, %s) returning id""",
                    (iid, ttl, ver, file_name, ctype, data, s(note, "비고"), user.login_id))
        new_id = cur.fetchone()["id"]
    return _saved(request, user, "F-STD-041", "STD-040", "시안을 등록했습니다", f"artwork:{it['item_code']}#{ver}",
                  data={"id": new_id, "version": ver})


@router.post("/std/artworks/{id}")
async def artwork_update(request: Request, id: str, title: str | None = Form(None), note: str | None = Form(None),
                         use_yn: str | None = Form(None), image: UploadFile | None = File(None),
                         user: rbac.User = rbac.require_fn("F-STD-042")):
    aid = pk(id)
    ttl = need(title, "시안 이름")
    use = yn(use_yn)
    new_image = await _image(image, required=False)
    with conn.tx() as cur:
        row = exists_or_404(cur, "artwork", aid, "id, item_id, version")
        cur.execute("update artwork set title = %s, note = %s, use_yn = %s, updated_at = now(), updated_by = %s "
                    "where id = %s", (ttl, s(note, "비고"), use, user.login_id, aid))
        if new_image:
            cur.execute("update artwork set file_name = %s, content_type = %s, image = %s where id = %s",
                        (*new_image, aid))
    return _saved(request, user, "F-STD-042", "STD-040", "시안을 수정했습니다", f"artwork:{aid}#{row['version']}",
                  f"시안 수정 · 사용 {use}" + (" · 이미지 교체" if new_image else ""), data={"id": aid})


# ── STD-050 표준견본서 ──────────────────────────────────────────────────
@router.get(nav.path_of("STD-050"), response_class=HTMLResponse)
def sample_sheets(request: Request, item: str | None = None, use: str | None = None, edit: str | None = None,
                  user: rbac.User = rbac.require_screen("STD-050")):
    """F-STD-053 — 제품별 견본서 목록."""
    rows = conn.q(
        """select s.id, s.item_id, i.item_code, i.item_name, s.title, s.content, s.issued_on, s.note, s.use_yn
             from sample_sheet s join item i on i.id = s.item_id
            where (%(item)s::bigint is null or s.item_id = %(item)s) and (%(u)s::text is null or s.use_yn = %(u)s)
            order by i.item_code, s.id desc limit 1000""",
        {"item": ref_id(item, "제품", required=False), "u": s(use, "사용 여부")})
    ed = edit_row("sample_sheet", edit)
    return templating.render(request, "std/sample_sheets.html",
                             {"rows": rows, "edit": ed, "edit_content": kv_lines(ed["content"]) if ed else "",
                              "items": items_for_select(), "form": {"item": item or "", "use": use or ""}},
                             screen_id="STD-050")


@router.post("/std/sample-sheets")
def sample_sheet_create(request: Request, item_id: str | None = Form(None), title: str | None = Form(None),
                        content: str | None = Form(None), issued_on: str | None = Form(None),
                        note: str | None = Form(None), user: rbac.User = rbac.require_fn("F-STD-051")):
    iid = ref_id(item_id, "제품")
    ttl = need(title, "제목")
    body = kv_text(content, "견본서 항목")
    issued = day(issued_on, "작성일", required=False)
    with conn.tx() as cur:
        it = item_choice(cur, iid, "제품")
        cur.execute("""insert into sample_sheet (item_id, title, content, issued_on, note, created_by)
                       values (%s, %s, %s, %s, %s, %s) returning id""",
                    (iid, ttl, Jsonb(body), issued, s(note, "비고"), user.login_id))
        new_id = cur.fetchone()["id"]
    return _saved(request, user, "F-STD-051", "STD-050", "표준견본서를 등록했습니다",
                  f"sample_sheet:{it['item_code']}#{new_id}", data={"id": new_id})


@router.post("/std/sample-sheets/{id}")
def sample_sheet_update(request: Request, id: str, title: str | None = Form(None), content: str | None = Form(None),
                        issued_on: str | None = Form(None), note: str | None = Form(None),
                        use_yn: str | None = Form(None), user: rbac.User = rbac.require_fn("F-STD-052")):
    sid = pk(id)
    ttl = need(title, "제목")
    body = kv_text(content, "견본서 항목")
    issued = day(issued_on, "작성일", required=False)
    use = yn(use_yn)
    with conn.tx() as cur:
        exists_or_404(cur, "sample_sheet", sid, "id")
        cur.execute("""update sample_sheet set title = %s, content = %s, issued_on = %s, note = %s, use_yn = %s,
                              updated_at = now(), updated_by = %s where id = %s""",
                    (ttl, Jsonb(body), issued, s(note, "비고"), use, user.login_id, sid))
    return _saved(request, user, "F-STD-052", "STD-050", "표준견본서를 수정했습니다", f"sample_sheet:{sid}",
                  f"견본서 수정 · 사용 {use}", data={"id": sid})


@router.get("/std/sample-sheets/{id}/print", response_class=HTMLResponse)
def sample_sheet_print(request: Request, id: str, user: rbac.User = rbac.require_fn("F-STD-054")):
    """F-STD-054 — 견본서 한 건을 출력 양식으로 연다."""
    row = conn.q1("""select s.*, i.item_code, i.item_name, i.spec, i.unit
                       from sample_sheet s join item i on i.id = s.item_id where s.id = %s""", (pk(id),))
    if row is None:
        raise http.not_found()
    return templating.render(request, "std/sample_sheet_print.html", {"row": row, "page_title": "표준견본서 출력"},
                             screen_id="STD-050")


# ── STD-060 예외제품관리 (적용 규칙 미확정 D-519) ───────────────────────
@router.get(nav.path_of("STD-060"), response_class=HTMLResponse)
def exception_items(request: Request, use: str | None = None, edit: str | None = None,
                    user: rbac.User = rbac.require_screen("STD-060")):
    """F-STD-064 — 예외 제품 목록."""
    rows = conn.q("""select e.id, e.item_id, i.item_code, i.item_name, e.reason, e.note, e.use_yn, e.updated_at
                       from exception_item e join item i on i.id = e.item_id
                      where (%(u)s::text is null or e.use_yn = %(u)s)
                      order by i.item_code""", {"u": s(use, "사용 여부")})
    return templating.render(request, "std/exception_items.html",
                             {"rows": rows, "edit": edit_row("exception_item", edit), "items": items_for_select(),
                              "form": {"use": use or ""}}, screen_id="STD-060")


@router.post("/std/exception-items")
def exception_item_create(request: Request, item_id: str | None = Form(None), reason: str | None = Form(None),
                          note: str | None = Form(None), user: rbac.User = rbac.require_fn("F-STD-061")):
    iid = ref_id(item_id, "제품")
    why = need(reason, "예외 사유")
    with conn.tx() as cur:
        it = item_choice(cur, iid, "제품")
        cur.execute("select 1 from exception_item where item_id = %s", (iid,))
        if cur.fetchone():
            raise bad("제품", it["item_code"], "이미 예외로 지정된 제품입니다")
        cur.execute("insert into exception_item (item_id, reason, note, created_by) values (%s, %s, %s, %s) returning id",
                    (iid, why, s(note, "비고"), user.login_id))
        new_id = cur.fetchone()["id"]
    return _saved(request, user, "F-STD-061", "STD-060", "예외제품을 지정했습니다", f"exception_item:{it['item_code']}",
                  data={"id": new_id})


@router.post("/std/exception-items/{id}")
def exception_item_update(request: Request, id: str, reason: str | None = Form(None), note: str | None = Form(None),
                          use_yn: str | None = Form(None), user: rbac.User = rbac.require_fn("F-STD-062")):
    eid = pk(id)
    why = need(reason, "예외 사유")
    use = yn(use_yn)
    with conn.tx() as cur:
        exists_or_404(cur, "exception_item", eid, "id")
        cur.execute("update exception_item set reason = %s, note = %s, use_yn = %s, updated_at = now(), updated_by = %s "
                    "where id = %s", (why, s(note, "비고"), use, user.login_id, eid))
    return _saved(request, user, "F-STD-062", "STD-060", "예외제품을 수정했습니다", f"exception_item:{eid}",
                  f"예외제품 수정 · 사용 {use}", data={"id": eid})


@router.post("/std/exception-items/{id}/delete")
def exception_item_delete(request: Request, id: str, user: rbac.User = rbac.require_fn("F-STD-063")):
    eid = pk(id)
    with conn.tx() as cur:
        exists_or_404(cur, "exception_item", eid, "id")
        done = remove_or_disable(cur, "exception_item", eid, user)
    return _saved(request, user, "F-STD-063", "STD-060",
                  DISABLED_MSG if done == "사용 중지" else "예외제품 지정을 삭제했습니다",
                  f"exception_item:{eid}", f"예외제품 {done}", data={"id": eid, "result": done})

