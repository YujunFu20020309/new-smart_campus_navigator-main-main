from unittest.mock import Mock, patch

import networkx as nx
import pandas as pd

from src.campus_graph import find_nearest_reachable_node
from src.route_modes import CAMPUS_MODE_ID
from src.route_service import get_campus_route, get_gps_campus_route
from src.routing_osrm import get_osrm_route


GPS_LAT = 24.7959
GPS_LON = 120.9936


def _graph_node(latitude, longitude, name):
    return {
        "latitude": latitude,
        "longitude": longitude,
        "name": name,
        "display_name": name,
    }


def _connector_response():
    response = Mock(status_code=200, text="")
    response.json.return_value = {
        "routes": [
            {
                "distance": 18.0,
                "duration": 20.0,
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [GPS_LON, GPS_LAT],
                        [120.9937, 24.7960],
                    ],
                },
            }
        ]
    }
    return response


def _service_graph():
    graph = nx.DiGraph()
    graph.add_node("snap", **_graph_node(24.7960, 120.9937, "Snap Node"))
    graph.add_node("destination", **_graph_node(24.7962, 120.9939, "Destination"))
    graph.add_edge("snap", "destination", distance_m=30.0)
    return graph


def _campus_route_result():
    return {
        "success": True,
        "distance_m": 30.0,
        "duration_s": 25.0,
        "cost": 30.0,
        "folium_coordinates": [
            [24.7960, 120.9937],
            [24.7962, 120.9939],
        ],
        "path_ids": ["snap", "destination"],
        "path_names": ["Snap Node", "Destination"],
        "edge_segments": [{"from_id": "snap", "to_id": "destination"}],
        "source": "local_graph",
        "mode": CAMPUS_MODE_ID,
        "error": None,
    }


def test_nearest_reachable_node_skips_disconnected_nearest_node():
    graph = nx.DiGraph()
    graph.add_node("disconnected", **_graph_node(GPS_LAT, GPS_LON, "Disconnected"))
    graph.add_node("reachable", **_graph_node(24.7960, 120.9937, "Reachable"))
    graph.add_node("destination", **_graph_node(24.7962, 120.9939, "Destination"))
    graph.add_edge("reachable", "destination")

    result = find_nearest_reachable_node(
        graph,
        GPS_LAT,
        GPS_LON,
        "destination",
    )

    assert result["success"] is True
    assert result["node_id"] == "reachable"


def test_nearest_reachable_node_ignores_missing_invalid_and_nonfinite_coordinates():
    graph = nx.DiGraph()
    graph.add_node("missing", **_graph_node(None, None, "Missing"))
    graph.add_node("invalid", **_graph_node("north", "east", "Invalid"))
    graph.add_node("nonfinite", **_graph_node(float("nan"), GPS_LON, "Nonfinite"))
    graph.add_node("valid", **_graph_node(24.7960, 120.9937, "Valid"))
    graph.add_node("destination", **_graph_node(24.7962, 120.9939, "Destination"))
    for node_id in ("missing", "invalid", "nonfinite", "valid"):
        graph.add_edge(node_id, "destination")

    result = find_nearest_reachable_node(
        graph,
        GPS_LAT,
        GPS_LON,
        "destination",
    )

    assert result["success"] is True
    assert result["node_id"] == "valid"


def test_nearest_reachable_node_uses_node_id_for_deterministic_tie_breaking():
    graph = nx.DiGraph()
    graph.add_node("node_b", **_graph_node(24.7960, 120.9937, "B"))
    graph.add_node("node_a", **_graph_node(24.7960, 120.9937, "A"))
    graph.add_node("destination", **_graph_node(24.7962, 120.9939, "Destination"))
    graph.add_edge("node_b", "destination")
    graph.add_edge("node_a", "destination")

    result = find_nearest_reachable_node(
        graph,
        GPS_LAT,
        GPS_LON,
        "destination",
    )

    assert result["node_id"] == "node_a"


def test_nearest_reachable_node_enforces_max_snap_distance():
    graph = nx.DiGraph()
    graph.add_node("far", **_graph_node(24.7990, 120.9936, "Far"))
    graph.add_node("destination", **_graph_node(24.8000, 120.9936, "Destination"))
    graph.add_edge("far", "destination")

    result = find_nearest_reachable_node(
        graph,
        GPS_LAT,
        GPS_LON,
        "destination",
        max_distance_m=250,
    )

    assert result["success"] is False
    assert result["node_id"] == "far"
    assert result["node_name"] == "Far"
    assert result["distance_m"] > 250
    assert result["max_distance_m"] == 250
    assert result["failure_reason"] == "max_distance_exceeded"
    assert "250 m snap limit" in result["error"]


def test_gps_campus_route_fails_gracefully_when_no_reachable_node_exists():
    graph = _service_graph()
    snapper = Mock(
        return_value={
            "success": False,
            "error": "No reachable campus graph node has valid coordinates.",
        }
    )
    router = Mock()

    result = get_gps_campus_route(
        pd.DataFrame(),
        pd.DataFrame(),
        GPS_LAT,
        GPS_LON,
        "destination",
        accuracy_m=15,
        allow_live_osrm=True,
        route_cache_path="unused.json",
        campus_graph_builder=Mock(return_value=graph),
        reachable_node_finder=snapper,
        osrm_router=router,
    )

    assert result["success"] is False
    assert result["fallback_reason"] == "campus_snap_failed"
    assert result["suggested_mode"] == "osrm"
    assert "Use OSRM mode instead" in result["error"]
    router.assert_not_called()


def test_gps_campus_route_exposes_clear_snap_distance_metadata():
    graph = _service_graph()
    snapper = Mock(
        return_value={
            "success": False,
            "node_id": "reachable_far",
            "node_name": "Reachable Far Node",
            "latitude": 24.7999,
            "longitude": 120.9937,
            "distance_m": 452.4,
            "max_distance_m": 250.0,
            "failure_reason": "max_distance_exceeded",
            "error": (
                "Nearest reachable campus graph node is 452 m away, "
                "exceeding the 250 m snap limit."
            ),
        }
    )
    router = Mock()

    result = get_gps_campus_route(
        pd.DataFrame(),
        pd.DataFrame(),
        GPS_LAT,
        GPS_LON,
        "destination",
        accuracy_m=15,
        allow_live_osrm=True,
        route_cache_path="unused.json",
        campus_graph_builder=Mock(return_value=graph),
        reachable_node_finder=snapper,
        osrm_router=router,
    )

    assert result["success"] is False
    assert result["fallback_reason"] == "snap_distance_exceeded"
    assert result["snap_failure_reason"] == "max_distance_exceeded"
    assert result["snapped_start_id"] == "reachable_far"
    assert result["snapped_start_name"] == "Reachable Far Node"
    assert result["snap_distance_m"] == 452.4
    assert result["snap_limit_m"] == 250.0
    assert "Reachable Far Node" in result["user_message"]
    assert "reachable_far" in result["user_message"]
    assert "452 公尺" in result["user_message"]
    assert "250 公尺" in result["user_message"]
    assert "OSRM" in result["user_message"]
    assert "節點與路段" in result["user_message"]
    router.assert_not_called()


def test_gps_campus_route_blocks_low_accuracy_before_snapping():
    graph_builder = Mock()

    result = get_gps_campus_route(
        pd.DataFrame(),
        pd.DataFrame(),
        GPS_LAT,
        GPS_LON,
        "destination",
        accuracy_m=150,
        allow_live_osrm=True,
        route_cache_path="unused.json",
        campus_graph_builder=graph_builder,
    )

    assert result["success"] is False
    assert result["fallback_reason"] == "gps_accuracy_too_low"
    assert result["suggested_mode"] == "osrm"
    graph_builder.assert_not_called()


def test_gps_campus_route_uses_uncached_connector_and_merges_geometry():
    graph = _service_graph()
    snapper = Mock(
        return_value={
            "success": True,
            "node_id": "snap",
            "node_name": "Snap Node",
            "latitude": 24.7960,
            "longitude": 120.9937,
            "distance_m": 15.0,
            "error": None,
        }
    )
    router = Mock(
        return_value={
            "success": True,
            "distance_m": 18.0,
            "duration_s": 20.0,
            "folium_coordinates": [
                [GPS_LAT, GPS_LON],
                [24.7960, 120.9937],
            ],
            "error": None,
        }
    )
    campus_router = Mock(return_value=_campus_route_result())

    with patch("src.route_service.match_forced_route_rule") as forced_match:
        result = get_gps_campus_route(
            pd.DataFrame(),
            pd.DataFrame(),
            GPS_LAT,
            GPS_LON,
            "destination",
            accuracy_m=15,
            allow_live_osrm=True,
            route_cache_path="route_cache.json",
            campus_graph_builder=Mock(return_value=graph),
            reachable_node_finder=snapper,
            campus_route_computer=campus_router,
            osrm_router=router,
        )

    assert result["success"] is True
    assert result["snapped_start_id"] == "snap"
    assert result["snapped_start_name"] == "Snap Node"
    assert result["snap_distance_m"] == 15.0
    assert result["connector_distance_m"] == 18.0
    assert result["campus_distance_m"] == 30.0
    assert result["distance_m"] == 48.0
    assert result["folium_coordinates"] == [
        [GPS_LAT, GPS_LON],
        [24.7960, 120.9937],
        [24.7962, 120.9939],
    ]
    router.assert_called_once_with(
        GPS_LAT,
        GPS_LON,
        24.7960,
        120.9937,
        profile="foot",
        cache_path="route_cache.json",
        allow_network=True,
        ignore_cache=True,
        persist_cache=False,
    )
    campus_router.assert_called_once_with(
        graph,
        "snap",
        "destination",
        mode=CAMPUS_MODE_ID,
    )
    forced_match.assert_not_called()


def test_gps_campus_connector_does_not_read_or_write_persistent_cache(tmp_path):
    graph = _service_graph()
    cache_path = tmp_path / "route_cache.json"
    cache_path.write_text("must remain untouched", encoding="utf-8")
    snapper = Mock(
        return_value={
            "success": True,
            "node_id": "snap",
            "node_name": "Snap Node",
            "latitude": 24.7960,
            "longitude": 120.9937,
            "distance_m": 15.0,
            "error": None,
        }
    )

    with patch("src.routing_osrm.requests.get", return_value=_connector_response()):
        result = get_gps_campus_route(
            pd.DataFrame(),
            pd.DataFrame(),
            GPS_LAT,
            GPS_LON,
            "destination",
            accuracy_m=15,
            allow_live_osrm=True,
            route_cache_path=cache_path,
            campus_graph_builder=Mock(return_value=graph),
            reachable_node_finder=snapper,
            campus_route_computer=Mock(return_value=_campus_route_result()),
            osrm_router=get_osrm_route,
        )

    assert result["success"] is True
    assert cache_path.read_text(encoding="utf-8") == "must remain untouched"


def test_existing_selected_place_campus_route_still_uses_original_pipeline():
    expected = {"success": True, "source": "local_graph", "mode": CAMPUS_MODE_ID}
    graph = object()
    route_computer = Mock(return_value=expected)

    result = get_campus_route(
        pd.DataFrame(),
        pd.DataFrame(),
        "start",
        "destination",
        allow_live_osrm=True,
        forced_rules_path="rules.json",
        route_cache_path="route_cache.json",
        match_rule_func=Mock(return_value=None),
        campus_graph_builder=Mock(return_value=graph),
        campus_route_computer=route_computer,
    )

    assert result is expected
    route_computer.assert_called_once_with(
        graph,
        "start",
        "destination",
        mode=CAMPUS_MODE_ID,
    )
