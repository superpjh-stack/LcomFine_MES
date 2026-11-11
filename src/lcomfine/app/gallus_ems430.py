"""Gallus EMS430 / B&R X20 Ethernet 수집 어댑터의 명세·파서.

EMS430의 외부 연동은 Ethernet TCP/IP로 알려져 있지만, 실제 TCP 프레임,
포트, Register 주소와 바이트 순서는 장비 설정/업체 명세가 필요하다.
따라서 이 모듈은 임의의 프레임을 보내지 않고 수집 항목의 정규 모델과
명세가 도착했을 때 사용할 읽기 전용 payload 파서를 먼저 제공한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class GallusField:
    key: str
    label: str
    unit: str
    availability: str
    source: str


FIELDS: tuple[GallusField, ...] = (
    GallusField("print_speed", "인쇄 속도", "m/min", "수집 가능", "설비 관리값"),
    GallusField("web_tension", "원단 장력", "N", "수집 가능", "설비 관리값"),
    GallusField("impression_setting", "인압 설정값", "", "수집 가능", "설비 설정값"),
    GallusField("uv_power", "UV 출력값", "%", "수집 가능", "설비 관리값"),
    GallusField("ink_viscosity", "잉크 점도", "", "센서 필요", "별도 센서/추가 연동"),
    GallusField("ink_temperature", "잉크 온도", "°C", "센서 필요", "별도 센서/추가 연동"),
    GallusField("drying_temperature", "건조 온도", "°C", "센서 필요", "별도 센서/추가 연동"),
)


def collection_plan() -> dict:
    """Gallus EMS430 파일럿 범위를 화면·설정에서 재사용할 수 있는 형태로 반환."""
    return {
        "machine": "Gallus EMS430",
        "plc": "B&R X20 시리즈",
        "internal_network": "POWERLINK",
        "io_network": "X2X Link",
        "external_transport": "Ethernet TCP/IP",
        "mode": "읽기 전용",
        "fields": [field.__dict__ for field in FIELDS],
        "station_registers": "인쇄 스테이션(색상 유닛)별 Register 확장 가능",
        "pending": ("TCP 포트", "프레임 형식", "Register 주소", "바이트 순서", "폴링 주기"),
    }


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_snapshot(payload: dict[str, Any], *, received_at: datetime | None = None) -> dict:
    """명세 확정 후 TCP adapter가 넘길 snapshot을 공통 모델로 정규화.

    payload는 필드 key와 선택적인 ``stations`` 배열을 가진다고 가정한다.
    알 수 없는 값은 버리지 않고 raw_keys만 기록하며, 자동 보정하지 않는다.
    """
    stations = payload.get("stations") or []
    normalized_stations = []
    if isinstance(stations, list):
        for station in stations:
            if not isinstance(station, dict):
                continue
            normalized_stations.append({
                "station": str(station.get("station", "")),
                "color": str(station.get("color", "")),
                "registers": station.get("registers") if isinstance(station.get("registers"), dict) else {},
            })
    values = {field.key: _number(payload.get(field.key)) for field in FIELDS}
    return {
        "machine": "Gallus EMS430",
        "plc": "B&R X20",
        "transport": "Ethernet TCP/IP",
        "received_at": (received_at or datetime.now()).isoformat(),
        "values": values,
        "stations": normalized_stations,
        "raw_keys": sorted(str(key) for key in payload),
        "read_only": True,
    }


def sample_payload() -> dict[str, Any]:
    """개발·화면 검증용 결정적 샘플. 실제 장비 데이터로 표시하지 않는다."""
    return {
        "machine": "Gallus EMS430 (샘플)",
        "transport": "Ethernet TCP/IP (샘플)",
        "captured_at": "2026-11-07T10:30:00+09:00",
        "print_speed": 128.4,
        "web_tension": 18.6,
        "impression_setting": 42.0,
        "uv_power": 78.0,
        "ink_viscosity": None,
        "ink_temperature": None,
        "drying_temperature": None,
        "stations": [
            {"station": "U01", "color": "Cyan", "registers": {"R100": 0.12, "R101": 98.4}},
            {"station": "U02", "color": "Magenta", "registers": {"R100": 0.09, "R101": 97.8}},
            {"station": "U03", "color": "Yellow", "registers": {"R100": 0.14, "R101": 98.1}},
            {"station": "U04", "color": "Black", "registers": {"R100": 0.11, "R101": 98.7}},
        ],
    }


def sample_snapshot() -> dict:
    """샘플 payload를 공통 Snapshot으로 변환한다."""
    return parse_snapshot(sample_payload())
