import math

import pytest

from src.user_location import (
    is_low_accuracy,
    is_near_nthu,
    location_signature,
    merge_geolocation_payload,
    normalize_accuracy,
    normalize_geolocation_payload,
    validate_coordinates,
)


def test_validate_coordinates_accepts_valid_numeric_values():
    assert validate_coordinates("24.7959", 120.9936) == (24.7959, 120.9936)


@pytest.mark.parametrize(
    "latitude,longitude",
    [
        (None, 120.99),
        (24.79, None),
        ("north", 120.99),
        (24.79, "east"),
        (math.nan, 120.99),
        (24.79, math.inf),
        (90.1, 120.99),
        (-90.1, 120.99),
        (24.79, 180.1),
        (24.79, -180.1),
    ],
)
def test_validate_coordinates_rejects_invalid_values(latitude, longitude):
    with pytest.raises(ValueError):
        validate_coordinates(latitude, longitude)


def test_accuracy_normalization_and_warning_classification():
    assert normalize_accuracy("12.5") == 12.5
    assert normalize_accuracy(None) is None
    assert normalize_accuracy("bad") is None
    assert normalize_accuracy(-1) is None
    assert normalize_accuracy(math.inf) is None
    assert is_low_accuracy(100) is False
    assert is_low_accuracy(100.1) is True
    assert is_low_accuracy(None) is False


def test_normalize_successful_geolocation_payload():
    result = normalize_geolocation_payload(
        {
            "status": "success",
            "latitude": 24.7959,
            "longitude": 120.9936,
            "accuracy_m": 15,
            "timestamp_ms": 1_718_000_000_000,
        }
    )

    assert result == {
        "success": True,
        "latitude": 24.7959,
        "longitude": 120.9936,
        "accuracy_m": 15.0,
        "timestamp_ms": 1_718_000_000_000.0,
        "error_code": None,
        "error_message": None,
    }


def test_normalize_error_payload_keeps_browser_error_details():
    result = normalize_geolocation_payload(
        {"status": "error", "error_code": 1, "error_message": "Permission denied"}
    )

    assert result["success"] is False
    assert result["error_code"] == 1
    assert result["error_message"] == "Permission denied"


def test_failed_refresh_preserves_previous_location_and_marks_it_stale():
    previous = {
        "latitude": 24.7959,
        "longitude": 120.9936,
        "accuracy_m": 15.0,
        "timestamp_ms": 1_718_000_000_000.0,
        "location_stale": False,
    }

    merged = merge_geolocation_payload(
        previous,
        {"status": "error", "error_code": 3, "error_message": "Timeout"},
    )

    assert merged["updated"] is False
    assert merged["location"]["latitude"] == 24.7959
    assert merged["location"]["location_stale"] is True
    assert merged["error"]["error_code"] == 3
    assert previous["location_stale"] is False


def test_nthu_proximity_check():
    assert is_near_nthu(24.7959, 120.9936) is True
    assert is_near_nthu(25.0330, 121.5654) is False
    assert is_near_nthu("bad", 120.9936) is False


def test_location_signature_changes_after_movement():
    original = location_signature(24.79590, 120.99360)
    same_rounded_location = location_signature(24.795901, 120.993601)
    moved_location = location_signature(24.79592, 120.99360)

    assert original == same_rounded_location
    assert original != moved_location
