from unittest.mock import Mock, patch

import folium

from src.map_view import add_start_end_markers
from src.route_service import (
    get_osrm_route_for_places,
    get_osrm_route_from_coordinates,
)
from src.routing_osrm import get_osrm_route
from src.utils import load_places


def _osrm_response():
    response = Mock(status_code=200, text="")
    response.json.return_value = {
        "routes": [
            {
                "distance": 250.0,
                "duration": 200.0,
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [120.9936, 24.7959],
                        [120.992131, 24.795218],
                    ],
                },
            }
        ]
    }
    return response


def test_gps_adapter_uses_lat_lon_order_and_destination_coordinates():
    places = load_places("data/places.csv")
    router = Mock(return_value={"success": True, "source": "osrm"})

    result = get_osrm_route_from_coordinates(
        places,
        24.7959,
        120.9936,
        "eecs_building",
        allow_live_osrm=True,
        route_cache_path="unused.json",
        osrm_router=router,
    )

    assert result["success"] is True
    assert result["gps_origin"] is True
    router.assert_called_once_with(
        24.7959,
        120.9936,
        24.795218,
        120.992131,
        profile="foot",
        cache_path="unused.json",
        allow_network=True,
        ignore_cache=False,
        persist_cache=False,
    )


def test_gps_origin_route_does_not_create_persistent_cache(tmp_path):
    places = load_places("data/places.csv")
    cache_path = tmp_path / "route_cache.json"

    with patch("src.routing_osrm.requests.get", return_value=_osrm_response()):
        result = get_osrm_route_from_coordinates(
            places,
            24.7959,
            120.9936,
            "eecs_building",
            allow_live_osrm=True,
            route_cache_path=cache_path,
            osrm_router=get_osrm_route,
        )

    assert result["success"] is True
    assert result["cache_hit"] is False
    assert cache_path.exists() is False


def test_gps_origin_requires_live_osrm_and_does_not_call_router():
    places = load_places("data/places.csv")
    router = Mock()

    result = get_osrm_route_from_coordinates(
        places,
        24.7959,
        120.9936,
        "eecs_building",
        allow_live_osrm=False,
        route_cache_path="unused.json",
        osrm_router=router,
    )

    assert result["success"] is False
    assert "gps_live_osrm_required" in result["error"]
    router.assert_not_called()


def test_gps_origin_route_does_not_read_existing_persistent_cache(tmp_path):
    places = load_places("data/places.csv")
    cache_path = tmp_path / "route_cache.json"
    cache_path.write_text("not valid json and must remain untouched", encoding="utf-8")

    with patch("src.routing_osrm.requests.get", return_value=_osrm_response()) as request:
        result = get_osrm_route_from_coordinates(
            places,
            24.7959,
            120.9936,
            "eecs_building",
            allow_live_osrm=True,
            route_cache_path=cache_path,
            osrm_router=get_osrm_route,
        )

    assert result["success"] is True
    request.assert_called_once()
    assert cache_path.read_text(encoding="utf-8") == "not valid json and must remain untouched"


def test_selected_place_osrm_keeps_existing_persistent_cache_behavior():
    places = load_places("data/places.csv")
    router = Mock(return_value={"success": True, "source": "osrm"})

    result = get_osrm_route_for_places(
        places,
        "main_gate",
        "eecs_building",
        allow_live_osrm=True,
        route_cache_path="route_cache.json",
        osrm_router=router,
    )

    assert result["success"] is True
    assert "persist_cache" not in router.call_args.kwargs
    assert router.call_args.args == (24.796153, 120.996694, 24.795218, 120.992131)


def test_current_location_marker_includes_accuracy_circle():
    map_obj = folium.Map(location=[24.7959, 120.9936])
    start = {
        "display_name": "My current location",
        "latitude": 24.7959,
        "longitude": 120.9936,
        "accuracy_m": 25,
        "source": "browser_geolocation",
    }
    end = {
        "display_name": "Destination",
        "latitude": 24.795218,
        "longitude": 120.992131,
        "source": "manual",
    }

    add_start_end_markers(map_obj, start, end)
    html = map_obj.get_root().render()

    assert "My current location" in html
    assert "Location accuracy: about 25 m" in html
