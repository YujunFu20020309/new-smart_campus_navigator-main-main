"""Pure helpers for validating and classifying browser geolocation results."""

from __future__ import annotations

import math
from typing import Any, Mapping

from src.geo_utils import haversine_distance_m


NTHU_CENTER_LAT = 24.7959
NTHU_CENTER_LON = 120.9936
DEFAULT_NTHU_NEARBY_RADIUS_M = 2_000.0
DEFAULT_LOW_ACCURACY_THRESHOLD_M = 100.0


def _finite_float(value: Any, field_name: str) -> float:
    if value is None or isinstance(value, bool):
        raise ValueError(f"{field_name} is missing or invalid.")
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be numeric.") from None
    if not math.isfinite(parsed):
        raise ValueError(f"{field_name} must be finite.")
    return parsed


def validate_coordinates(latitude: Any, longitude: Any) -> tuple[float, float]:
    """Return finite latitude/longitude floats or raise a user-safe ValueError."""
    lat = _finite_float(latitude, "latitude")
    lon = _finite_float(longitude, "longitude")
    if not -90.0 <= lat <= 90.0:
        raise ValueError("latitude must be between -90 and 90.")
    if not -180.0 <= lon <= 180.0:
        raise ValueError("longitude must be between -180 and 180.")
    return lat, lon


def normalize_accuracy(value: Any) -> float | None:
    """Return a non-negative finite accuracy radius in metres when available."""
    if value is None or isinstance(value, bool):
        return None
    try:
        accuracy = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(accuracy) or accuracy < 0:
        return None
    return accuracy


def _normalize_timestamp_ms(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(timestamp) or timestamp < 0:
        return None
    return timestamp


def normalize_geolocation_payload(payload: Any) -> dict[str, Any]:
    """Normalize a Components v2 geolocation event into one stable structure."""
    if not isinstance(payload, Mapping):
        return {
            "success": False,
            "latitude": None,
            "longitude": None,
            "accuracy_m": None,
            "timestamp_ms": None,
            "error_code": 0,
            "error_message": "Browser geolocation returned an invalid payload.",
        }

    status = str(payload.get("status") or "").strip().lower()
    if status == "success":
        try:
            latitude, longitude = validate_coordinates(
                payload.get("latitude"),
                payload.get("longitude"),
            )
        except ValueError as exc:
            return {
                "success": False,
                "latitude": None,
                "longitude": None,
                "accuracy_m": None,
                "timestamp_ms": None,
                "error_code": 0,
                "error_message": str(exc),
            }
        return {
            "success": True,
            "latitude": latitude,
            "longitude": longitude,
            "accuracy_m": normalize_accuracy(payload.get("accuracy_m")),
            "timestamp_ms": _normalize_timestamp_ms(payload.get("timestamp_ms")),
            "error_code": None,
            "error_message": None,
        }

    error_code = payload.get("error_code", 0)
    try:
        error_code = int(error_code)
    except (TypeError, ValueError):
        error_code = 0
    error_message = str(
        payload.get("error_message") or "Browser geolocation failed."
    ).strip()
    return {
        "success": False,
        "latitude": None,
        "longitude": None,
        "accuracy_m": None,
        "timestamp_ms": None,
        "error_code": error_code,
        "error_message": error_message,
    }


def merge_geolocation_payload(
    previous_location: Mapping[str, Any] | None,
    payload: Any,
) -> dict[str, Any]:
    """Merge one browser result while preserving a prior valid location on failure."""
    normalized = normalize_geolocation_payload(payload)
    if normalized["success"]:
        return {
            "location": {
                "latitude": normalized["latitude"],
                "longitude": normalized["longitude"],
                "accuracy_m": normalized["accuracy_m"],
                "timestamp_ms": normalized["timestamp_ms"],
                "location_stale": False,
            },
            "error": None,
            "updated": True,
        }

    preserved = dict(previous_location) if isinstance(previous_location, Mapping) else None
    if preserved is not None:
        preserved["location_stale"] = True
    return {
        "location": preserved,
        "error": normalized,
        "updated": False,
    }


def is_near_nthu(
    latitude: Any,
    longitude: Any,
    *,
    max_distance_m: float = DEFAULT_NTHU_NEARBY_RADIUS_M,
) -> bool:
    """Return whether a valid coordinate is within the configured NTHU radius."""
    try:
        lat, lon = validate_coordinates(latitude, longitude)
        radius = _finite_float(max_distance_m, "max_distance_m")
    except ValueError:
        return False
    if radius < 0:
        return False
    return haversine_distance_m(lat, lon, NTHU_CENTER_LAT, NTHU_CENTER_LON) <= radius


def is_low_accuracy(
    accuracy_m: Any,
    *,
    threshold_m: float = DEFAULT_LOW_ACCURACY_THRESHOLD_M,
) -> bool:
    """Return True when an available accuracy radius exceeds the warning threshold."""
    accuracy = normalize_accuracy(accuracy_m)
    try:
        threshold = _finite_float(threshold_m, "threshold_m")
    except ValueError:
        return False
    return accuracy is not None and threshold >= 0 and accuracy > threshold


def location_signature(
    latitude: Any,
    longitude: Any,
    *,
    decimals: int = 5,
) -> str:
    """Return a rounded, session-only signature used to invalidate stale routes."""
    lat, lon = validate_coordinates(latitude, longitude)
    if decimals < 0:
        raise ValueError("decimals must be non-negative.")
    return f"gps:{lat:.{decimals}f},{lon:.{decimals}f}"
