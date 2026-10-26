"""MGT-040 ERP 재무 회차 — 메모리 검증, 오류 제외, 교체 보존."""
import io
from datetime import date

import pytest
from openpyxl import Workbook

from lcomfine.db import conn
from test_dev1_common import XLSX, client


def book(headers, rows):
    wb=Workbook(); ws=wb.active; ws.append(headers)
    for row in rows: ws.append(row)
    buf=io.BytesIO(); wb.save(buf); return buf.getvalue()


@pytest.mark.fn("F-MGT-041")
@pytest.mark.fn("F-MGT-042")
@pytest.mark.fn("F-MGT-043")
def test_financial_upload_errors_excluded_and_round_replaced():
    customer=conn.q1("select customer_code from customer order by id limit 1")["customer_code"]
    item=conn.q1("select item_code from item order by id limit 1")["item_code"]
    headers=["기간","거래처 코드","품목 코드","수주매출","실제원가"]
    rows=[["2088-01",customer,item,1000,600],["2088-01","NO-CUSTOMER",item,500,300]]
    assert client("st").get("/mgt/financial-imports").status_code==200
    assert client("st").post("/mgt/financial-imports",data={"period_from":"2088-01-01","period_to":"2088-01-31"},files={"file":("f.xlsx",book(headers,rows),XLSX)}).status_code==403
    made=client("ac").post("/mgt/financial-imports",data={"period_from":"2088-01-01","period_to":"2088-01-31"},files={"file":("f.xlsx",book(headers,rows),XLSX)})
    assert made.status_code==200,made.text; batch1=made.json()["id"]
    assert made.json()["errors"]==1
    assert conn.q1("select count(*) n from financial_fact where batch_id=%s",(batch1,))["n"]==1
    assert client("ac").post(f"/mgt/financial-imports/{batch1}").status_code==200
    made2=client("ac").post("/mgt/financial-imports",data={"period_from":"2088-01-01","period_to":"2088-01-31"},files={"file":("f2.xlsx",book(headers,[["2088-01",customer,item,1200,700]]),XLSX)})
    batch2=made2.json()["id"]
    assert client("ac").post(f"/mgt/financial-imports/{batch2}").status_code==200
    statuses={r["id"]:r["status"] for r in conn.q("select id,status from financial_import_batch where id=any(%s)",([batch1,batch2],))}
    assert statuses=={batch1:"교체",batch2:"반영"}


def test_financial_formula_cell_is_error_not_executed():
    customer=conn.q1("select customer_code from customer order by id limit 1")["customer_code"]
    item=conn.q1("select item_code from item order by id limit 1")["item_code"]
    content=book(["기간","거래처 코드","품목 코드","수주매출"],[["2088-02",customer,item,"=1+1"]])
    made=client("ac").post("/mgt/financial-imports",data={"period_from":"2088-02-01","period_to":"2088-02-29"},files={"file":("formula.xlsx",content,XLSX)})
    assert made.status_code==200,made.text
    assert made.json()["errors"]==1
