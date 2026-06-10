"""Geographic distance, walking-time, and friendly geometry input helpers."""

from __future__ import annotations

import math
from typing import Any


DEFAULT_WALKING_SPEED_MPS = 1.4


def estimate_walking_duration_s(
    distance_m: float | int,
    walking_speed_mps: float = DEFAULT_WALKING_SPEED_MPS,
) -> float:
    """Estimate walking duration from distance using a configurable walking speed."""
    distance = float(distance_m)
    speed = float(walking_speed_mps)
    if distance < 0:
        raise ValueError("distance_m must be non-negative.")
    if speed <= 0:
        raise ValueError("walking_speed_mps must be positive.")
    return distance / speed


def resolve_walking_duration_s(
    distance_m: float | int,
    osrm_duration_s: float | int | None = None,
) -> tuple[float, str]:
    """Use a plausible OSRM foot duration, otherwise estimate at walking speed."""
    distance = float(distance_m)
    estimated = estimate_walking_duration_s(distance)
    try:
        duration = float(osrm_duration_s) if osrm_duration_s is not None else 0.0
    except (TypeError, ValueError):
        duration = 0.0

    if duration > 0 and duration >= estimated:
        return duration, "osrm_foot"
    return estimated, "walking_speed_fallback"


def haversine_distance_m(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    """Return the great-circle distance between two latitude/longitude points."""
    radius_m = 6_371_000.0
    lat1_r = math.radians(float(lat1))
    lat2_r = math.radians(float(lat2))
    delta_lat = math.radians(float(lat2) - float(lat1))
    delta_lon = math.radians(float(lon2) - float(lon1))
    value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(delta_lon / 2) ** 2
    )
    return radius_m * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def polyline_distance_m(points: list[list[float]]) -> float:
    """Return the total haversine distance across adjacent [lon, lat] points."""
    total = 0.0
    for start, end in zip(points, points[1:]):
        if len(start) != 2 or len(end) != 2:
            raise ValueError("Polyline points must use [longitude, latitude] format.")
        total += haversine_distance_m(start[1], start[0], end[1], end[0])
    return total


def parse_geometry_points_text(text: Any) -> list[list[float]]:
    """Parse one longitude,latitude point per line into a coordinate list."""
    if text is None or str(text).strip() == "":
        return []

    points: list[list[float]] = []
    for line_number, raw_line in enumerate(str(text).splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 2:
            raise ValueError(f"第 {line_number} 行格式錯誤，請使用 longitude,latitude。")
        try:
            first = float(parts[0])
            second = float(parts[1])
        except ValueError:
            raise ValueError(f"第 {line_number} 行座標必須是數字。") from None
        if first < 30 and second > 100:
            raise ValueError("座標順序疑似反了，請使用 longitude,latitude")
        if not 110 <= first <= 130 or not 20 <= second <= 30:
            raise ValueError(
                f"第 {line_number} 行不像台灣附近座標，請確認 longitude 約為 120、latitude 約為 24。"
            )
        points.append([first, second])
    return points
