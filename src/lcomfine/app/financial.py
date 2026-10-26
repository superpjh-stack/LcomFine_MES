"""ERP 재무 엑셀을 메모리에서 검증하고 회차로 보존한다."""
from __future__ import annotations

import io
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from openpyxl import load_workbook

from .erp_upload import MAX_BYTES, UploadError

FIELDS = {"기간":"period_month","거래처 코드":"customer_code","품목 코드":"item_code",
          "수주매출":"order_amount","출하매출":"shipment_amount","표준원가":"standard_cost","실제원가":"actual_cost"}
REQUIRED = ("기간","거래처 코드","품목 코드")
AMOUNTS = ("수주매출","출하매출","표준원가","실제원가")


def _month(v) -> date:
    if isinstance(v,(date,datetime)): return date(v.year,v.month,1)
    raw=str(v or "").strip()
    try:
        d=date.fromisoformat(raw+"-01" if len(raw)==7 else raw)
        return date(d.year,d.month,1)
    except ValueError: raise ValueError("YYYY-MM 형식이어야 합니다") from None


def _amount(v):
    if v in (None,""): return None
    try: out=Decimal(str(v).replace(",","")).quantize(Decimal("0.01"))
    except InvalidOperation: raise ValueError("숫자여야 합니다") from None
    if not out.is_finite() or abs(out)>=Decimal("1e14"): raise ValueError("금액 범위를 넘었습니다")
    return out


def parse(file: bytes, cur) -> dict:
    if not file: raise UploadError("파일","빈 파일입니다")
    if len(file)>MAX_BYTES: raise UploadError("파일","20MB 이하만 올릴 수 있습니다")
    try: wb=load_workbook(io.BytesIO(file),read_only=True,data_only=False)
    except Exception as exc: raise UploadError("파일",f"엑셀(.xlsx) 파일이 아닙니다 [{type(exc).__name__}]") from None
    try:
        ws=wb.worksheets[0]; rows=ws.iter_rows(); head=next(rows,None)
        headers=[str(c.value or "").strip() for c in (head or [])]
        missing=[h for h in REQUIRED if h not in headers]
        active=[h for h in AMOUNTS if h in headers]
        if missing: raise UploadError("열",f"필수 열이 없습니다: {', '.join(missing)}")
        if not active: raise UploadError("열","금액 열이 하나 이상 필요합니다")
        indexes={h:headers.index(h) for h in headers if h in FIELDS}; validated=[]
        for row_no,cells in enumerate(rows,2):
            if not any(c.value not in (None,"") for c in cells): continue
            raw={h:(cells[i].value if i<len(cells) else None) for h,i in indexes.items()}; errors=[]; parsed={}
            for h,val in raw.items():
                if indexes[h] < len(cells) and cells[indexes[h]].data_type == "f": errors.append(f"{h}: 수식 셀은 허용하지 않습니다"); continue
                try:
                    if h=="기간": parsed["period_month"]=_month(val)
                    elif h in AMOUNTS: parsed[FIELDS[h]]=_amount(val)
                    else: parsed[FIELDS[h]]=str(val or "").strip()
                except ValueError as exc: errors.append(f"{h}: {exc}")
            if not parsed.get("customer_code"): errors.append("거래처 코드: 필수 항목입니다")
            if not parsed.get("item_code"): errors.append("품목 코드: 필수 항목입니다")
            cur.execute("select id from customer where customer_code=%s",(parsed.get("customer_code"),)); customer=cur.fetchone()
            cur.execute("select id from item where item_code=%s",(parsed.get("item_code"),)); item=cur.fetchone()
            if not customer: errors.append("거래처 코드: MES 매핑 없음")
            if not item: errors.append("품목 코드: MES 매핑 없음")
            parsed["customer_id"]=customer["id"] if customer else None; parsed["item_id"]=item["id"] if item else None
            if not any(parsed.get(FIELDS[h]) is not None for h in active): errors.append("금액: 값이 하나 이상 필요합니다")
            validated.append({"row_no":row_no,"raw":raw,"parsed":parsed,"error":" · ".join(errors) or None})
        if not validated: raise UploadError("파일","데이터 행이 없습니다")
        return {"fields":[FIELDS[h] for h in active],"rows":validated}
    finally: wb.close()


def stage(cur, period_from, period_to, parsed: dict, user, source_name: str) -> int:
    cur.execute("select id from financial_import_batch where period_from=%s and period_to=%s for update",(period_from,period_to))
    cur.fetchall()
    cur.execute("select coalesce(max(round_no),0)+1 n from financial_import_batch where period_from=%s and period_to=%s",(period_from,period_to))
    round_no=cur.fetchone()["n"]
    errors=sum(1 for r in parsed["rows"] if r["error"])
    cur.execute("""insert into financial_import_batch(period_from,period_to,round_no,status,source_name,fields,row_count,error_count,created_by)
                   values (%s,%s,%s,'검증',%s,%s::jsonb,%s,%s,%s) returning id""",
                (period_from,period_to,round_no,source_name,__import__('json').dumps(parsed["fields"]),len(parsed["rows"]),errors,user.login_id))
    batch_id=cur.fetchone()["id"]
    for r in parsed["rows"]:
        if r["error"]: continue
        p=r["parsed"]
        cur.execute("""insert into financial_fact(batch_id,row_no,period_month,customer_id,item_id,order_amount,shipment_amount,standard_cost,actual_cost,raw,created_by)
                       values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)""",
                    (batch_id,r["row_no"],p["period_month"],p["customer_id"],p["item_id"],p.get("order_amount"),p.get("shipment_amount"),p.get("standard_cost"),p.get("actual_cost"),__import__('json').dumps({k:str(v) if v is not None else None for k,v in r["raw"].items()},ensure_ascii=False),user.login_id))
    return batch_id


def apply(cur,batch_id:int,user) -> int|None:
    cur.execute("select * from financial_import_batch where id=%s for update",(batch_id,)); batch=cur.fetchone()
    if batch is None: raise LookupError(batch_id)
    if batch["status"]!="검증": raise ValueError("검증 상태 회차만 반영할 수 있습니다")
    cur.execute("select id from financial_import_batch where period_from=%s and period_to=%s and status='반영' for update",(batch["period_from"],batch["period_to"])); old=cur.fetchone()
    if old: cur.execute("update financial_import_batch set status='교체',replaced_by=%s,updated_at=now(),updated_by=%s where id=%s",(batch_id,user.login_id,old["id"]))
    cur.execute("update financial_import_batch set status='반영',applied_at=now(),updated_at=now(),updated_by=%s where id=%s",(user.login_id,batch_id))
    return old["id"] if old else None


def totals(period_from,period_to,customer_id=None):
    from ..db import conn
    row=conn.q1("""select sum(f.order_amount) order_amount,sum(f.shipment_amount) shipment_amount,sum(f.standard_cost) standard_cost,sum(f.actual_cost) actual_cost
                    from financial_fact f join financial_import_batch b on b.id=f.batch_id and b.status='반영'
                   where f.period_month between date_trunc('month',%s::date)::date and date_trunc('month',%s::date)::date
                     and (%s::bigint is null or f.customer_id=%s)""",(period_from,period_to,customer_id,customer_id))
    return row or {}
