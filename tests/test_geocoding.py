import json
from unittest.mock import Mock, patch

from src.geocoding import geocode_place, make_geocode_cache_key, update_missing_coordinates
from src.utils import (
    get_place_by_id,
    load_places,
    validate_coordinate_bounds,
    validate_places,
)


USER_AGENT = "NTHU-Smart-Campus-Navigator-Test/1.0"


def test_places_csv_can_be_loaded():
    df = load_places("data/places.csv")

    assert len(df) >= 10
    assert validate_places(df) is True
    assert get_place_by_id(df, "main_gate")["name"] == "NTHU Main Gate"


def test_geocode_cache_hit_does_not_call_api(tmp_path):
    cache_path = tmp_path / "geocode_cache.json"
    key = make_geocode_cache_key("清大總圖", "tw")
    cache_path.write_text(
        json.dumps(
            {
                "version": 1,
                "provider": "nominatim",
                "items": {
                    key: {
                        "success": True,
                        "latitude": 24.7947,
                        "longitude": 120.9945,
                        "display_name": "清大總圖",
                        "raw_response": {"lat": "24.7947", "lon": "120.9945"},
                        "source": "nominatim",
                        "error": None,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    with patch("src.geocoding.requests.get") as mock_get:
        result = geocode_place("清大總圖", cache_path, USER_AGENT, "tw", sleep_seconds=0)

    assert result["success"] is True
    assert result["from_cache"] is True
    mock_get.assert_not_called()


def test_geocode_api_response_parsing(tmp_path):
    cache_path = tmp_path / "geocode_cache.json"
    mock_response = Mock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = [
        {
            "lat": "24.7947",
            "lon": "120.9945",
            "display_name": "NTHU Library",
        }
    ]

    with patch("src.geocoding.requests.get", return_value=mock_response):
        result = geocode_place("NTHU Library", cache_path, USER_AGENT, "tw", sleep_seconds=0)

    assert result["success"] is True
    assert result["latitude"] == 24.7947
    assert result["longitude"] == 120.9945
    assert result["from_cache"] is False


def test_geocode_no_result_does_not_crash(tmp_path):
    cache_path = tmp_path / "geocode_cache.json"
    mock_response = Mock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = []

    with patch("src.geocoding.requests.get", return_value=mock_response):
        result = geocode_place("not a real campus place", cache_path, USER_AGENT, "tw", sleep_seconds=0)

    assert result["success"] is False
    assert "no results" in result["error"]


def test_manual_source_is_not_overwritten_by_geocoding(tmp_path):
    places_csv = tmp_path / "places.csv"
    cache_path = tmp_path / "geocode_cache.json"
    places_csv.write_text(
        "\n".join(
            [
                "id,name,display_name,category,latitude,longitude,source,notes",
                "manual_place,Manual Place,Manual Place,building,24.79,120.99,manual,",
            ]
        ),
        encoding="utf-8",
    )

    with patch("src.geocoding.geocode_place") as mock_geocode:
        summary = update_missing_coordinates(
            places_csv,
            cache_path,
            user_agent=USER_AGENT,
            sleep_seconds=0,
        )

    df = load_places(places_csv)
    place = get_place_by_id(df, "manual_place")
    assert place["latitude"] == "24.79"
    assert place["longitude"] == "120.99"
    assert summary["protected_skipped"] == 1
    mock_geocode.assert_not_called()


def test_verified_note_is_not_overwritten_by_geocoding(tmp_path):
    places_csv = tmp_path / "places.csv"
    cache_path = tmp_path / "geocode_cache.json"
    places_csv.write_text(
        "\n".join(
            [
                "id,name,display_name,category,latitude,longitude,source,notes",
                "verified_place,Verified Place,Verified Place,building,24.79,120.99,nominatim,verified",
            ]
        ),
        encoding="utf-8",
    )

    with patch("src.geocoding.geocode_place") as mock_geocode:
        summary = update_missing_coordinates(
            places_csv,
            cache_path,
            user_agent=USER_AGENT,
            sleep_seconds=0,
        )

    df = load_places(places_csv)
    place = get_place_by_id(df, "verified_place")
    assert place["latitude"] == "24.79"
    assert place["longitude"] == "120.99"
    assert summary["protected_skipped"] == 1
    mock_geocode.assert_not_called()


def test_coordinate_bounds_detects_outside_nthu_area():
    inside = {"latitude": "24.795", "longitude": "120.995"}
    outside = {"latitude": "25.033", "longitude": "121.565"}
    missing = {"latitude": "", "longitude": ""}

    assert validate_coordinate_bounds(inside) is True
    assert validate_coordinate_bounds(outside) is False
    assert validate_coordinate_bounds(missing) is True


def test_missing_coordinates_can_be_loaded_without_crashing(tmp_path):
    places_csv = tmp_path / "places.csv"
    places_csv.write_text(
        "\n".join(
            [
                "id,name,display_name,category,latitude,longitude,source,notes",
                "missing_place,Missing Place,Missing Place,building,,,nominatim,needs_geocoding",
            ]
        ),
        encoding="utf-8",
    )

    df = load_places(places_csv)
    place = get_place_by_id(df, "missing_place")
    assert place["latitude"] == ""
    assert place["longitude"] == ""
    assert validate_places(df) is True
