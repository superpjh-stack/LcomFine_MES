"""그래프 중심 경영 Cockpit의 읽기 모델과 핵심 마크업 계약."""
from datetime import date

import pytest

from lcomfine.app import dashboard
from test_dev1_common import client


@pytest.mark.fn("F-RPT-081")
def test_executive_cockpit_read_model_has_scoreboard_flow_and_causes():
    data = dashboard.summary((date(2026, 10, 1), date(2026, 10, 27)))
    executive = data["executive"]
    assert len(executive["hero_kpis"]) == 4
    assert {k["key"] for k in executive["hero_kpis"]} == {
        "overall_attainment", "order_amount", "shipment_amount", "profit"
    }
    assert set(executive["attainment"]) >= {"value", "available", "contributors"}
    assert len(executive["flow"]) == 7
    assert [s["key"] for s in executive["flow"]] == [
        "orders", "production_queue", "production", "inspection", "finished_stock", "shipment", "collection"
    ]
    for stage in executive["flow"]:
        assert set(stage) >= {"key", "label", "value", "secondary", "conversion", "dwell", "risk_count", "status", "href"}
    assert len(executive["risks"]) <= 5
    assert set(executive["causes"]) == {"cumulative", "due_forecast", "quality_pareto"}


@pytest.mark.fn("F-RPT-081")
def test_summary_renders_graph_first_cockpit_landmarks():
    response = client("ex").get("/rpt/summary", params={"tab": "monthly", "asof": "2026-10-27"})
    assert response.status_code == 200, response.text
    html = response.text
    assert 'data-cockpit="executive"' in html
    assert 'data-cockpit-hero' in html
    assert 'data-executive-kpi-strip' in html
    strip = html.split('data-executive-kpi-strip', 1)[1].split('data-executive-risks', 1)[0]
    assert strip.count('data-executive-metric=') == 4
    assert 'data-attainment-ring' in strip
    assert 'data-attainment-ring' in html
    assert 'data-executive-risks' in html
    assert 'data-process-flow' in html
    assert html.count('data-flow-stage=') == 7
    assert 'data-cause-chart="cumulative"' in html
    assert 'data-cause-chart="due_forecast"' in html
    assert 'data-cause-chart="quality_pareto"' in html


@pytest.mark.fn("F-RPT-081")
def test_cockpit_distinguishes_linked_and_unavailable_financial_values():
    data = dashboard.summary((date(1975, 1, 1), date(1975, 1, 31)))
    money = {k["key"]: k for k in data["executive"]["hero_kpis"]}
    assert money["order_amount"]["availability"] == "연계 전"
    assert money["shipment_amount"]["availability"] == "연계 전"
    assert money["profit"]["value"] is None
    assert money["profit"]["availability"] == "연계 전"
