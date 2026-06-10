import pandas as pd
import pytest

from src.campus_graph import build_campus_graph, compute_campus_route
from src.data_admin import EDGE_COLUMNS, PLACE_COLUMNS, append_edge, save_edges, save_places
from tools.validate_campus_edges import validate_edges_data


def _place(place_id, category, latitude, longitude):
    return {
        "id": place_id,
        "name": place_id,
        "display_name": place_id,
        "category": category,
        "latitude": str(latitude),
        "longitude": str(longitude),
        "source": "manual",
        "notes": "verified",
        "is_destination": "1" if category == "building" else "0",
        "show_marker": "1" if category == "building" else "0",
    }


def _edge(from_id, to_id, distance_m, geometry="", description="", **changes):
    edge = {
        "from_id": from_id,
        "to_id": to_id,
        "distance_m": str(distance_m),
        "stairs": "0",
        "rain_friendly": "1",
        "road_name": "Test Road",
        "description": description,
        "geometry": geometry,
        "routing_source": "manual",
        "ignore_osrm": "0",
        "verified": "0",
        "enabled": "1",
    }
    edge.update(changes)
    return edge


def _frame(rows, columns):
    return pd.DataFrame(rows, columns=columns)


def test_missing_long_geometry_fails():
    places = _frame(
        [
            _place("building_a", "building", 24.795, 120.995),
            _place("building_b", "building", 24.796, 120.996),
        ],
        PLACE_COLUMNS,
    )
    edges = _frame([_edge("building_a", "building_b", 100)], EDGE_COLUMNS)

    route = compute_campus_route(build_campus_graph(places, edges), "building_a", "building_b")

    assert route["success"] is False
    assert route["folium_coordinates"] == []
    assert route["error"] == (
        "Edge missing geometry and unsafe to draw as straight line: "
        "building_a -> building_b"
    )


def test_short_connector_can_draw_straight():
    places = _frame(
        [
            _place("building_a", "building", 24.795, 120.995),
            _place("road_1", "road_node", 24.7951, 120.9951),
        ],
        PLACE_COLUMNS,
    )
    edges = _frame([_edge("building_a", "road_1", 30)], EDGE_COLUMNS)

    route = compute_campus_route(build_campus_graph(places, edges), "building_a", "road_1")

    assert route["success"] is True
    assert route["folium_coordinates"] == [[24.795, 120.995], [24.7951, 120.9951]]


def test_hidden_nodes_are_used_and_route_does_not_generate_nodes():
    places = _frame(
        [
            _place("building_a", "building", 24.795, 120.995),
            _place("road_1", "road_node", 24.7951, 120.9951),
            _place("intersection_1", "intersection", 24.7955, 120.9955),
            _place("building_b", "building", 24.7956, 120.9956),
        ],
        PLACE_COLUMNS,
    )
    edges = _frame(
        [
            _edge("building_a", "road_1", 20),
            _edge("road_1", "intersection_1", 80, verified="1"),
            _edge("intersection_1", "building_b", 20),
        ],
        EDGE_COLUMNS,
    )
    original_ids = set(places["id"])
    graph = build_campus_graph(places, edges)

    route = compute_campus_route(graph, "building_a", "building_b")

    assert route["success"] is True
    assert route["path_ids"] == [
        "building_a",
        "road_1",
        "intersection_1",
        "building_b",
    ]
    assert set(places["id"]) == original_ids
    assert set(graph.nodes) == original_ids


def test_geometry_coordinate_order_rejects_lat_lon(tmp_path):
    places_path = tmp_path / "places.csv"
    edges_path = tmp_path / "campus_edges.csv"
    places = _frame(
        [
            _place("road_1", "road_node", 24.795, 120.995),
            _place("road_2", "road_node", 24.796, 120.996),
        ],
        PLACE_COLUMNS,
    )
    save_places(places_path, places)
    save_edges(edges_path, _frame([], EDGE_COLUMNS))

    with pytest.raises(ValueError, match="longitude, latitude"):
        append_edge(
            edges_path,
            places,
            _edge("road_1", "road_2", 50, geometry="[[24.795,120.995],[24.796,120.996]]"),
        )


def test_validate_edges_reports_unsafe_edges():
    places = _frame(
        [
            _place("building_a", "building", 24.795, 120.995),
            _place("road_1", "road_node", 24.796, 120.996),
        ],
        PLACE_COLUMNS,
    )
    edges = _frame([_edge("building_a", "road_1", 100)], EDGE_COLUMNS)

    issues = validate_edges_data(places, edges)

    assert any("unsafe long edge has empty geometry" in issue for issue in issues)


def test_verified_manual_edge_can_be_used_without_osrm():
    places = _frame(
        [
            _place("building_a", "building", 24.795, 120.995),
            _place("building_b", "building", 24.796, 120.996),
        ],
        PLACE_COLUMNS,
    )
    edges = _frame(
        [
            _edge(
                "building_a",
                "building_b",
                80,
                routing_source="manual",
                ignore_osrm="1",
                verified="1",
            )
        ],
        EDGE_COLUMNS,
    )

    route = compute_campus_route(build_campus_graph(places, edges), "building_a", "building_b")

    assert route["success"] is True
    assert route["edge_segments"][0]["routing_source"] == "manual"
    assert route["edge_segments"][0]["ignore_osrm"] is True
    assert route["edge_segments"][0]["verified"] is True


def test_disabled_edge_is_not_added_to_graph():
    places = _frame(
        [
            _place("a", "road_node", 24.795, 120.995),
            _place("b", "road_node", 24.796, 120.996),
        ],
        PLACE_COLUMNS,
    )
    edges = _frame([_edge("a", "b", 20, enabled="0")], EDGE_COLUMNS)

    graph = build_campus_graph(places, edges)

    assert set(graph.nodes) == {"a", "b"}
    assert not graph.has_edge("a", "b")


def test_unknown_edge_endpoint_is_rejected_without_creating_node():
    places = _frame([_place("a", "road_node", 24.795, 120.995)], PLACE_COLUMNS)
    edges = _frame([_edge("a", "generated_node", 20, enabled="0")], EDGE_COLUMNS)

    with pytest.raises(ValueError, match="unknown place id"):
        build_campus_graph(places, edges)

    assert set(places["id"]) == {"a"}


def test_dijkstra_can_start_farther_from_destination_for_shorter_total_path():
    places = _frame(
        [
            _place("start", "road_node", 24.795, 120.995),
            _place("near_goal", "road_node", 24.7959, 120.9959),
            _place("farther_first", "road_node", 24.794, 120.994),
            _place("goal", "road_node", 24.796, 120.996),
        ],
        PLACE_COLUMNS,
    )
    edges = _frame(
        [
            _edge("start", "near_goal", 5, verified="1", routing_source="osrm"),
            _edge("near_goal", "goal", 100, verified="1", routing_source="osrm"),
            _edge("start", "farther_first", 20, verified="1", routing_source="osrm"),
            _edge("farther_first", "goal", 20, verified="1", routing_source="osrm"),
        ],
        EDGE_COLUMNS,
    )

    route = compute_campus_route(build_campus_graph(places, edges), "start", "goal")

    assert route["success"] is True
    assert route["path_ids"] == ["start", "farther_first", "goal"]
    assert route["distance_m"] == 40


def test_manual_geometry_distance_uses_haversine_not_stored_distance():
    places = _frame(
        [
            _place("a", "road_node", 24.795, 120.995),
            _place("b", "road_node", 24.796, 120.995),
        ],
        PLACE_COLUMNS,
    )
    edges = _frame(
        [
            _edge(
                "a",
                "b",
                1,
                geometry="[[120.995,24.795],[120.995,24.796]]",
            )
        ],
        EDGE_COLUMNS,
    )

    route = compute_campus_route(build_campus_graph(places, edges), "a", "b")

    assert 110 < route["distance_m"] < 112


def test_verified_straight_distance_uses_haversine_not_stored_distance():
    places = _frame(
        [
            _place("a", "road_node", 24.795, 120.995),
            _place("b", "road_node", 24.796, 120.995),
        ],
        PLACE_COLUMNS,
    )
    edges = _frame([_edge("a", "b", 1, verified="1")], EDGE_COLUMNS)

    route = compute_campus_route(build_campus_graph(places, edges), "a", "b")

    assert 110 < route["distance_m"] < 112
    assert route["duration_s"] == pytest.approx(route["distance_m"] / 1.4)
