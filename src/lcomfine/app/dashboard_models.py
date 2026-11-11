"""대시보드의 DB 비의존 계산·화면 데이터 구성.

원천 조회는 dashboard.py가 수행한다. 이 모듈은 SQL·권한·렌더링을 다루지 않는다.
기존 반올림, 0/미수집 구분, 목표 방향별 달성률, KPI 키·단위·표시 순서를 보존한다.
종합 달성률과 개별 목표 판정은 기존 산식이 달라 임의로 통합하지 않는다.
enrich_executive는 기존처럼 전달된 데이터에 전기·증감을 붙여 같은 객체를 반환한다.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

DAY_BUCKET_MAX_DAYS = 31


def _bucket(f: date, t: date) -> tuple[str, str]:
    """(구간 종류, to_char 형식). 31일 이하 = 일 · 그 밖 = 월 (D-805)."""
    return ("day", "YYYY-MM-DD") if (t - f).days < DAY_BUCKET_MAX_DAYS else ("month", "YYYY-MM")


def _labels(f: date, t: date, bucket: str) -> list[str]:
    out: list[str] = []
    if bucket == "day":
        d = f
        while d <= t:
            out.append(d.isoformat())
            d += timedelta(days=1)
        return out
    y, m = f.year, f.month
    while date(y, m, 1) <= t:
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _series(labels: list[str], rows: list[dict], key: str, value: str) -> list[dict]:
    """구간 라벨 전부에 값을 붙인다 — 행이 없는 구간은 None(미수집 · 0 으로 지어내지 않는다)."""
    got = {r[key]: r[value] for r in rows}
    return [{"label": lb, "value": got.get(lb)} for lb in labels]


def _kpi(key: str, label: str, value, *, digits: int = 0, unit: str = "", text: str | None = None, note: str = "") -> dict:
    return {"key": key, "label": label, "value": value, "digits": digits, "unit": unit, "text": text, "note": note}


def _n(v):
    """0 · None → None(미수집). 그 밖 그대로."""
    return None if v is None or v == 0 else v


def _avg_days(vals: list[int]) -> Decimal | None:
    if not vals:
        return None
    return (Decimal(sum(vals)) / Decimal(len(vals))).quantize(Decimal("0.1"))


def _base(f: date, t: date, bucket: str, customer_id: int | None) -> dict:
    return {"kpis": [], "series": {}, "tables": {}, "asof": None, "period": (f, t), "bucket": bucket,
            "customer_id": customer_id, "notes": []}


def enrich_executive(data: dict, previous: dict | None = None) -> dict:
    """Cockpit Hero KPI에 전기·증감을 붙인다. 원 데이터와 재무 가용 상태는 바꾸지 않는다."""
    current = data.get("executive", {}).get("hero_kpis", [])
    before = {k["key"]: k for k in (previous or {}).get("executive", {}).get("hero_kpis", [])}
    for kpi in current:
        old = before.get(kpi["key"], {}).get("value")
        value = kpi.get("value")
        kpi["previous"] = old
        kpi["delta"] = value - old if value is not None and old is not None else None
    return data


def target_attainment(rows: list[dict], actuals: dict[str, Decimal | None]) -> dict:
    """조회 순서를 유지하며 중복 목표·미수집·0 분모를 처리한다."""
    seen: set[str] = set()
    contributors = []
    for row in rows:
        key = row["metric_key"]
        if key in seen or actuals.get(key) is None:
            continue
        seen.add(key)
        actual = actuals[key]
        target = row["target_value"]
        attainment = None
        if row["direction"] == "높을수록 좋음" and target not in (None, 0):
            attainment = actual / target * Decimal("100")
        elif row["direction"] == "낮을수록 좋음" and actual not in (None, 0):
            attainment = target / actual * Decimal("100")
        elif row["direction"] == "범위 내 정상" and row["range_min"] is not None and row["range_max"] is not None:
            attainment = Decimal("100") if row["range_min"] <= actual <= row["range_max"] else Decimal("0")
        if attainment is not None:
            contributors.append({"key": key, "label": row["metric_name"], "value": actual, "target": target,
                                 "attainment": attainment.quantize(Decimal("0.1"))})
    value = None if not contributors else (sum((c["attainment"] for c in contributors), Decimal(0)) /
                                            Decimal(len(contributors))).quantize(Decimal("0.1"))
    return {"value": value, "available": bool(contributors), "contributors": contributors}


def build_executive(data: dict[str, dict], attainment: dict, money: dict,
                    risks: list[dict], due_forecast: list[dict]) -> dict:
    def value(screen: str, key: str):
        return next((k["value"] for k in data[screen]["kpis"] if k["key"] == key), None)

    order_qty = value("RPT-010", "qty")
    production_orders = value("RPT-020", "work_orders")
    order_count = value("RPT-010", "requests")
    queue_count = value("RPT-010", "not_started")
    inspections = value("RPT-030", "judgements")
    finished = value("RPT-040", "product_receipts")
    shipments = value("RPT-050", "shipments")
    collected = value("RPT-060", "collected")
    order_amount, shipment_amount, actual_cost = money.get("order_amount"), money.get("shipment_amount"), money.get("actual_cost")
    profit = shipment_amount - actual_cost if shipment_amount is not None and actual_cost is not None else None

    hero = [
        {**_kpi("overall_attainment", "목표 종합 달성률", attainment["value"], digits=1, unit="%"),
         "availability": "수집" if attainment["available"] else "목표 없음",
         "status": "정상" if attainment["value"] is not None and attainment["value"] >= 100 else ("주의" if attainment["value"] is not None else "목표 없음")},
        {**_kpi("order_amount", "수주 매출", order_amount, unit="원"), "availability": "수집" if order_amount is not None else "연계 전", "status": "연계 전" if order_amount is None else "정상"},
        {**_kpi("shipment_amount", "출하 매출", shipment_amount, unit="원"), "availability": "수집" if shipment_amount is not None else "연계 전", "status": "연계 전" if shipment_amount is None else "정상"},
        {**_kpi("profit", "예상 이익", profit, unit="원"), "availability": "수집" if profit is not None else "연계 전", "status": "연계 전" if profit is None else ("정상" if profit >= 0 else "위험")},
    ]

    risk_by_screen: dict[str, int] = {}
    for r in risks:
        risk_by_screen[r["source_screen"]] = risk_by_screen.get(r["source_screen"], 0) + 1

    flow_specs = [
        ("orders", "수주", order_count, order_qty, "RPT-010", "/rpt/orders"),
        ("production_queue", "생산대기", queue_count, None, "RPT-010", "/rpt/orders"),
        ("production", "생산", production_orders, value("RPT-020", "good_qty"), "RPT-020", "/rpt/production"),
        ("inspection", "검사", inspections, value("RPT-030", "inspected_qty"), "RPT-030", "/rpt/quality"),
        ("finished_stock", "제품재고", finished, value("RPT-040", "product_receipt_qty"), "RPT-040", "/rpt/inventory"),
        ("shipment", "출하", shipments, value("RPT-050", "qty"), "RPT-050", "/rpt/shipment"),
        ("collection", "수금", collected, None, "RPT-060", "/rpt/collection"),
    ]
    dwell_map = {s["stage"]: s["avg_days"] for s in data["RPT-070"]["tables"].get("stages", [])}
    dwell_keys = [None, "의뢰 → 지시", "지시 → 생산 완료", None, "생산 완료 → 제품 입고", "제품 입고 → 출하", None]
    conversion_values = [
        None,
        None,
        (Decimal(value("RPT-020", "good_qty")) / Decimal(order_qty) * 100).quantize(Decimal("0.1")) if order_qty not in (None, 0) and value("RPT-020", "good_qty") is not None else None,
        (Decimal(value("RPT-030", "inspected_qty")) / Decimal(value("RPT-020", "good_qty")) * 100).quantize(Decimal("0.1")) if value("RPT-020", "good_qty") not in (None, 0) and value("RPT-030", "inspected_qty") is not None else None,
        (Decimal(value("RPT-040", "product_receipt_qty")) / Decimal(value("RPT-030", "inspected_qty")) * 100).quantize(Decimal("0.1")) if value("RPT-030", "inspected_qty") not in (None, 0) and value("RPT-040", "product_receipt_qty") is not None else None,
        (Decimal(value("RPT-050", "qty")) / Decimal(value("RPT-040", "product_receipt_qty")) * 100).quantize(Decimal("0.1")) if value("RPT-040", "product_receipt_qty") not in (None, 0) and value("RPT-050", "qty") is not None else None,
        (Decimal(collected) / Decimal(shipment_amount) * 100).quantize(Decimal("0.1")) if shipment_amount not in (None, 0) and collected is not None else None,
    ]
    flow = []
    for idx, (key, label, stage_value, secondary, screen, href) in enumerate(flow_specs):
        conversion = conversion_values[idx]
        count = risk_by_screen.get(screen, 0)
        status = "위험" if any(r["severity"] == "위험" and r["source_screen"] == screen for r in risks) else ("주의" if count else ("미수집" if stage_value is None else "정상"))
        flow.append({"key": key, "label": label, "value": stage_value, "secondary": secondary, "conversion": conversion,
                     "dwell": dwell_map.get(dwell_keys[idx]) if dwell_keys[idx] else None, "risk_count": count,
                     "status": status, "href": href})

    raw_cumulative = {"수주": data["RPT-010"]["series"].get("qty", []),
                      "출하": data["RPT-050"]["series"].get("qty", []),
                      "수금": data["RPT-060"]["series"].get("collected", [])}
    labels = list(dict.fromkeys(p["label"] for rows in raw_cumulative.values() for p in rows))
    running = {key: Decimal(0) for key in raw_cumulative}
    lookup = {key: {p["label"]: p.get("value") for p in rows} for key, rows in raw_cumulative.items()}
    cumulative = []
    for label in labels:
        parts = []
        for key in raw_cumulative:
            point = lookup[key].get(label)
            if point is not None:
                running[key] += Decimal(point)
            parts.append({"label": key, "value": running[key] if point is not None or running[key] else None})
        cumulative.append({"label": label, "parts": parts})
    return {"hero_kpis": hero, "attainment": attainment, "risks": risks, "flow": flow,
            "causes": {"cumulative": cumulative, "due_forecast": due_forecast,
                       "quality_pareto": data["RPT-030"]["series"].get("defects", [])}}

