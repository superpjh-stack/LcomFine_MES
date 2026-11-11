from datetime import datetime, timezone

from lcomfine.app.gallus_ems430 import collection_plan, parse_snapshot, sample_payload, sample_snapshot


def test_gallus_collection_plan_declares_transport_and_sensor_boundary():
    plan = collection_plan()
    assert plan["machine"] == "Gallus EMS430"
    assert plan["plc"] == "B&R X20 시리즈"
    assert plan["external_transport"] == "Ethernet TCP/IP"
    assert {x["key"] for x in plan["fields"]} >= {
        "print_speed", "web_tension", "impression_setting", "uv_power",
        "ink_viscosity", "ink_temperature", "drying_temperature",
    }
    assert "Register 주소" in plan["pending"]


def test_gallus_snapshot_is_read_only_and_keeps_station_registers():
    received = datetime(2026, 11, 6, 9, 0, tzinfo=timezone.utc)
    result = parse_snapshot({
        "print_speed": "120.5",
        "web_tension": 18,
        "uv_power": "80",
        "stations": [{"station": "U01", "color": "C", "registers": {"R100": 42}}],
        "unknown_register": 7,
    }, received_at=received)
    assert result["values"]["print_speed"] == 120.5
    assert result["values"]["impression_setting"] is None
    assert result["stations"][0]["registers"] == {"R100": 42}
    assert result["raw_keys"][-1] == "web_tension"
    assert result["read_only"] is True


def test_gallus_sample_is_explicit_and_has_four_station_records():
    sample = sample_payload()
    assert sample["machine"].endswith("(샘플)")
    assert sample["transport"].endswith("(샘플)")
    assert len(sample["stations"]) == 4
    result = parse_snapshot(sample)
    assert result["values"]["print_speed"] == 128.4
    assert result["values"]["ink_temperature"] is None
    assert result["read_only"] is True


def test_gallus_sample_snapshot_is_normalized():
    snapshot = sample_snapshot()
    assert snapshot["values"]["uv_power"] == 78.0
    assert snapshot["stations"][3]["color"] == "Black"
