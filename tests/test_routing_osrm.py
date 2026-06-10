import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from src.routing_osrm import (
    ROUTE_CACHE_VERSION,
    WALKING_TRANSPORT_MODE,
    convert_geojson_to_folium_coordinates,
    get_osrm_route,
    make_route_cache_key,
    normalize_profile,
)


def test_osrm_coordinate_order_and_geojson_conversion(tmp_path):
    cache_path = tmp_path / "route_cache.json"
    mock_response = Mock(status_code=200, text="")
    mock_response.json.return_value = {
        "routes": [
            {
                "distance": 123.4,
                "duration": 100.0,
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[2.0, 1.0], [4.0, 3.0]],
                },
            }
        ]
    }

    with patch("src.routing_osrm.requests.get", return_value=mock_response) as mock_get:
        result = get_osrm_route(1.0, 2.0, 3.0, 4.0, cache_path=cache_path)

    called_url = mock_get.call_args.args[0]
    called_params = mock_get.call_args.kwargs["params"]
    assert "/2.000000,1.000000;4.000000,3.000000" in called_url
    assert called_params["overview"] == "full"
    assert called_params["geometries"] == "geojson"
    assert result["success"] is True
    assert result["duration_s"] == 100.0
    assert result["osrm_duration_s"] == 100.0
    assert result["duration_source"] == "osrm_foot"
    assert result["folium_coordinates"] == [[1.0, 2.0], [3.0, 4.0]]
    assert "2.000000,1.000000;4.000000,3.000000" in result["osrm_url"]
    assert result["profile"] == "foot"
    assert result["transport_mode"] == "walking"
    assert "/route/v1/foot/" in called_url
    assert "/driving/" not in called_url


def test_convert_geojson_to_folium_coordinates():
    assert convert_geojson_to_folium_coordinates([[120.0, 24.0], [121.0, 25.0]]) == [
        [24.0, 120.0],
        [25.0, 121.0],
    ]


def test_route_cache_hit_does_not_call_api(tmp_path):
    cache_path = tmp_path / "route_cache.json"
    key = make_route_cache_key(1.0, 2.0, 3.0, 4.0, "foot")
    cached_result = {
        "success": True,
        "distance_m": 10,
        "duration_s": 20,
        "geometry_geojson": {"type": "LineString", "coordinates": [[2.0, 1.0], [4.0, 3.0]]},
        "folium_coordinates": [[1.0, 2.0], [3.0, 4.0]],
        "source": "osrm",
        "error": None,
        "cache_hit": False,
        "profile": "foot",
        "transport_mode": WALKING_TRANSPORT_MODE,
        "osrm_url": "https://example.test/route/v1/foot/2,1;4,3",
    }
    cache_path.write_text(
        json.dumps(
            {
                "version": ROUTE_CACHE_VERSION,
                "provider": "osrm",
                "profile": "foot",
                "transport_mode": WALKING_TRANSPORT_MODE,
                "routes": {key: cached_result},
            }
        ),
        encoding="utf-8",
    )

    with patch("src.routing_osrm.requests.get") as mock_get:
        result = get_osrm_route(1.0, 2.0, 3.0, 4.0, cache_path=cache_path)

    assert result["success"] is True
    assert result["cache_hit"] is True
    assert result["duration_s"] == 20
    assert result["osrm_duration_s"] == 20
    assert result["osrm_url"] is not None
    mock_get.assert_not_called()


def test_ignore_cache_calls_api_and_updates_cache(tmp_path):
    cache_path = tmp_path / "route_cache.json"
    key = make_route_cache_key(1.0, 2.0, 3.0, 4.0, "foot")
    cached_result = {
        "success": True,
        "distance_m": 10,
        "duration_s": 20,
        "geometry_geojson": {"type": "LineString", "coordinates": [[2.0, 1.0], [4.0, 3.0]]},
        "folium_coordinates": [[1.0, 2.0], [3.0, 4.0]],
        "source": "osrm",
        "error": None,
        "cache_hit": False,
        "profile": "foot",
        "transport_mode": WALKING_TRANSPORT_MODE,
        "osrm_url": "https://example.test/route/v1/foot/2,1;4,3",
    }
    cache_path.write_text(
        json.dumps(
            {
                "version": ROUTE_CACHE_VERSION,
                "provider": "osrm",
                "profile": "foot",
                "transport_mode": WALKING_TRANSPORT_MODE,
                "routes": {key: cached_result},
            }
        ),
        encoding="utf-8",
    )
    mock_response = Mock(status_code=200, text="")
    mock_response.json.return_value = {
        "routes": [
            {
                "distance": 999,
                "duration": 111,
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[2.0, 1.0], [4.0, 3.0]],
                },
            }
        ]
    }

    with patch("src.routing_osrm.requests.get", return_value=mock_response) as mock_get:
        result = get_osrm_route(
            1.0,
            2.0,
            3.0,
            4.0,
            cache_path=cache_path,
            ignore_cache=True,
        )

    assert result["success"] is True
    assert result["cache_hit"] is False
    assert result["distance_m"] == 999
    mock_get.assert_called_once()

    saved_cache = json.loads(cache_path.read_text(encoding="utf-8"))
    assert saved_cache["routes"][key]["distance_m"] == 999


def test_osrm_failure_does_not_crash(tmp_path):
    cache_path = tmp_path / "route_cache.json"
    mock_response = Mock(status_code=500, text="server error")

    with patch("src.routing_osrm.requests.get", return_value=mock_response):
        result = get_osrm_route(1.0, 2.0, 3.0, 4.0, cache_path=cache_path)

    assert result["success"] is False
    assert "HTTP 500" in result["error"]


@pytest.mark.parametrize("requested_profile", ["foot", "walk", "walking", "car", "bike", None])
def test_all_requested_profiles_are_forced_to_walking(requested_profile):
    assert normalize_profile(requested_profile) == "foot"
    assert make_route_cache_key(1.0, 2.0, 3.0, 4.0, requested_profile).startswith("foot:")


def test_get_osrm_route_ignores_car_profile_and_calls_foot(tmp_path):
    mock_response = Mock(status_code=200, text="")
    mock_response.json.return_value = {
        "routes": [
            {
                "distance": 10,
                "duration": 2,
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[120.1, 24.1], [120.2, 24.2]],
                },
            }
        ]
    }

    with patch("src.routing_osrm.requests.get", return_value=mock_response) as mock_get:
        result = get_osrm_route(
            24.1,
            120.1,
            24.2,
            120.2,
            profile="car",
            cache_path=tmp_path / "cache.json",
        )

    assert "/route/v1/foot/" in mock_get.call_args.args[0]
    assert "/driving/" not in mock_get.call_args.args[0]
    assert result["profile"] == "foot"


def test_implausibly_fast_osrm_duration_falls_back_to_walking_time(tmp_path):
    mock_response = Mock(status_code=200, text="")
    mock_response.json.return_value = {
        "routes": [
            {
                "distance": 1128.6,
                "duration": 154.6,
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[120.1, 24.1], [120.2, 24.2]],
                },
            }
        ]
    }

    with patch("src.routing_osrm.requests.get", return_value=mock_response):
        result = get_osrm_route(
            24.1,
            120.1,
            24.2,
            120.2,
            cache_path=tmp_path / "cache.json",
        )

    assert result["distance_m"] == 1128.6
    assert result["osrm_duration_s"] == 154.6
    assert 13 * 60 < result["duration_s"] < 15 * 60
    assert result["duration_source"] == "walking_speed_fallback"


def test_legacy_or_non_walking_cache_is_ignored(tmp_path):
    cache_path = tmp_path / "route_cache.json"
    old_key = "foot:1.00000,2.00000->3.00000,4.00000"
    cache_path.write_text(
        json.dumps(
            {
                "version": 1,
                "provider": "osrm",
                "routes": {
                    old_key: {
                        "success": True,
                        "distance_m": 1128.6,
                        "duration_s": 154.6,
                        "profile": "bike",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    with patch("src.routing_osrm.requests.get") as mock_get:
        result = get_osrm_route(
            1.0,
            2.0,
            3.0,
            4.0,
            cache_path=cache_path,
            allow_network=False,
        )

    assert result["success"] is False
    assert "route_not_cached_demo_mode" in result["error"]
    mock_get.assert_not_called()


def test_project_route_cache_contains_only_walking_v2_entries():
    cache = json.loads(Path("data/route_cache.json").read_text(encoding="utf-8"))

    assert cache["version"] == ROUTE_CACHE_VERSION
    assert cache["profile"] == "foot"
    assert cache["transport_mode"] == WALKING_TRANSPORT_MODE
    for key, route in cache["routes"].items():
        assert key.startswith("foot:walking-v2:")
        assert route["profile"] == "foot"
        assert route["transport_mode"] == WALKING_TRANSPORT_MODE
        assert "/route/v1/foot/" in route["osrm_url"]
        assert "/driving/" not in route["osrm_url"]
        assert "/bike/" not in route["osrm_url"]
