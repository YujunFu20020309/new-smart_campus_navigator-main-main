from unittest.mock import patch

import pandas as pd

from app import calculate_route_for_mode
from src.data_admin import EDGE_COLUMNS, PLACE_COLUMNS
from src.route_modes import LOCAL_GRAPH_MODE_ID


def _place(place_id, latitude, longitude):
    return {
        "id": place_id,
        "name": place_id,
        "display_name": place_id,
        "category": "building",
        "latitude": str(latitude),
        "longitude": str(longitude),
        "source": "manual",
        "notes": "verified",
        "is_destination": "1",
        "show_marker": "1",
    }


def _edge(from_id, to_id, distance_m=20):
    return {
        "from_id": from_id,
        "to_id": to_id,
        "distance_m": str(distance_m),
        "stairs": "0",
        "rain_friendly": "1",
        "road_name": "Test",
        "description": "",
        "geometry": "",
        "routing_source": "manual",
        "ignore_osrm": "0",
        "verified": "0",
        "enabled": "1",
    }


def _places():
    return pd.DataFrame(
        [
            _place("start", 24.795, 120.995),
            _place("end", 24.796, 120.996),
            _place("isolated", 24.797, 120.997),
        ],
        columns=PLACE_COLUMNS,
    )


def _osrm_success():
    return {
        "success": True,
        "distance_m": 125,
        "duration_s": 100,
        "osrm_duration_s": 20,
        "geometry_geojson": {"type": "LineString", "coordinates": []},
        "folium_coordinates": [[24.795, 120.995], [24.796, 120.996]],
        "source": "osrm",
        "error": None,
        "cache_hit": True,
        "profile": "foot",
    }


def test_local_no_path_uses_osrm_fallback_without_mutating_data(tmp_path):
    places = _places()
    edges = pd.DataFrame([_edge("start", "isolated")], columns=EDGE_COLUMNS)
    original_place_ids = places["id"].tolist()
    original_edges = edges.copy(deep=True)

    with patch("app.get_osrm_route", return_value=_osrm_success()) as mock_osrm:
        route = calculate_route_for_mode(
            LOCAL_GRAPH_MODE_ID,
            places,
            edges,
            "start",
            "end",
            allow_live_osrm=True,
            route_cache_path=tmp_path / "route_cache.json",
        )

    assert route["success"] is True
    assert route["source"] == "osrm_fallback"
    assert route["fallback_from"] == "local_graph"
    assert "No path" in route["local_error"]
    assert route["mode"] == LOCAL_GRAPH_MODE_ID
    assert route["path_ids"] == []
    assert route["path_names"] == []
    assert places["id"].tolist() == original_place_ids
    pd.testing.assert_frame_equal(edges, original_edges)
    mock_osrm.assert_called_once()
    assert mock_osrm.call_args.kwargs["profile"] == "foot"


def test_build_graph_failure_uses_osrm_fallback(tmp_path):
    places = _places()
    edges = pd.DataFrame([_edge("start", "missing_node")], columns=EDGE_COLUMNS)

    with patch("app.get_osrm_route", return_value=_osrm_success()) as mock_osrm:
        route = calculate_route_for_mode(
            LOCAL_GRAPH_MODE_ID,
            places,
            edges,
            "start",
            "end",
            allow_live_osrm=True,
            route_cache_path=tmp_path / "route_cache.json",
        )

    assert route["success"] is True
    assert route["source"] == "osrm_fallback"
    assert "Failed to build campus graph: ValueError:" in route["local_error"]
    mock_osrm.assert_called_once()


def test_osrm_fallback_failure_contains_both_errors(tmp_path):
    places = _places()
    edges = pd.DataFrame([_edge("start", "isolated")], columns=EDGE_COLUMNS)
    osrm_failure = {"success": False, "error": "OSRM unavailable"}

    with patch("app.get_osrm_route", return_value=osrm_failure):
        route = calculate_route_for_mode(
            LOCAL_GRAPH_MODE_ID,
            places,
            edges,
            "start",
            "end",
            allow_live_osrm=True,
            route_cache_path=tmp_path / "route_cache.json",
        )

    assert route["success"] is False
    assert route["source"] == "osrm_fallback"
    assert "Local graph error:" in route["error"]
    assert "No path" in route["error"]
    assert "OSRM fallback error: OSRM unavailable" in route["error"]
