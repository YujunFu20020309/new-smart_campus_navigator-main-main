from unittest.mock import patch

import pandas as pd

from app import calculate_route_for_mode
from src.campus_graph import build_campus_graph, compute_campus_route, load_edges
from src.map_view import add_debug_node_markers, add_place_markers, create_base_map
from src.route_modes import LOCAL_GRAPH_MODE_ID
from src.utils import get_destination_places, load_places


def test_missing_visibility_columns_get_category_defaults(tmp_path):
    places_csv = tmp_path / "places.csv"
    places_csv.write_text(
        "\n".join(
            [
                "id,name,display_name,category,latitude,longitude,source,notes",
                "building_1,Building 1,Building 1,building,24.795,120.995,manual,verified",
                "node_1,Node 1,Node 1,intersection,24.796,120.996,manual,verified",
            ]
        ),
        encoding="utf-8",
    )

    places_df = load_places(places_csv)

    assert places_df.loc[places_df["id"] == "building_1", "is_destination"].iloc[0] == "1"
    assert places_df.loc[places_df["id"] == "building_1", "show_marker"].iloc[0] == "1"
    assert places_df.loc[places_df["id"] == "node_1", "is_destination"].iloc[0] == "0"
    assert places_df.loc[places_df["id"] == "node_1", "show_marker"].iloc[0] == "0"


def test_destination_list_only_contains_enabled_non_routing_nodes():
    places_df = load_places("data/places.csv")

    destinations = get_destination_places(places_df)

    assert destinations["is_destination"].eq("1").all()
    assert not destinations["category"].isin(["intersection", "road_node", "waypoint"]).any()
    assert "qinghua_avenue_1" not in destinations["id"].tolist()


def test_show_marker_zero_node_is_not_added_to_default_markers():
    places_df = pd.DataFrame(
        [
            {
                "id": "visible",
                "name": "Visible",
                "display_name": "Visible Marker",
                "category": "building",
                "latitude": "24.795",
                "longitude": "120.995",
                "source": "manual",
                "notes": "verified",
                "is_destination": "1",
                "show_marker": "1",
            },
            {
                "id": "hidden",
                "name": "Hidden",
                "display_name": "Hidden Node",
                "category": "intersection",
                "latitude": "24.796",
                "longitude": "120.996",
                "source": "manual",
                "notes": "verified",
                "is_destination": "0",
                "show_marker": "0",
            },
        ]
    )
    map_obj = create_base_map()

    add_place_markers(map_obj, places_df)
    html = map_obj.get_root().render()

    assert "Visible Marker" in html
    assert "Hidden Node" not in html


def test_debug_markers_show_hidden_internal_nodes():
    places_df = pd.DataFrame(
        [
            {
                "id": "hidden_node",
                "name": "Hidden",
                "display_name": "Hidden Debug Node",
                "category": "road_node",
                "latitude": "24.796",
                "longitude": "120.996",
                "source": "manual",
                "notes": "verified",
                "is_destination": "0",
                "show_marker": "0",
            }
        ]
    )
    map_obj = create_base_map()

    add_debug_node_markers(map_obj, places_df)
    html = map_obj.get_root().render()

    assert "hidden_node" in html
    assert "Hidden Debug Node" in html


def test_campus_edges_csv_can_be_loaded():
    edges_df = load_edges("data/campus_edges.csv")

    assert len(edges_df) >= 1
    assert {
        "from_id",
        "to_id",
        "distance_m",
        "stairs",
        "rain_friendly",
        "road_name",
        "description",
        "geometry",
    }.issubset(edges_df.columns)


def test_build_campus_graph_creates_networkx_graph():
    places_df = pd.DataFrame(
        [
            {
                "id": "main_gate",
                "name": "Main Gate",
                "display_name": "Main Gate",
                "category": "gate",
                "latitude": "24.795",
                "longitude": "120.995",
                "source": "manual",
                "notes": "verified",
            },
            {
                "id": "road_1",
                "name": "Road 1",
                "display_name": "Road 1",
                "category": "road_node",
                "latitude": "24.7951",
                "longitude": "120.9951",
                "source": "manual",
                "notes": "verified",
            },
        ]
    )
    edges_df = pd.DataFrame(
        [
            {
                "from_id": "main_gate",
                "to_id": "road_1",
                "distance_m": "20",
                "stairs": "0",
                "rain_friendly": "1",
                "road_name": "Connector",
                "description": "",
                "geometry": "",
            }
        ]
    )

    graph = build_campus_graph(places_df, edges_df)

    assert graph.has_node("main_gate")
    assert graph.has_node("road_1")
    assert graph.has_edge("main_gate", "road_1")
    assert graph.has_edge("road_1", "main_gate")
    assert graph.number_of_edges() == len(edges_df) * 2


def test_main_gate_to_engineering_1_route():
    places_df = load_places("data/places.csv")
    edges_df = load_edges("data/campus_edges.csv")

    try:
        graph = build_campus_graph(places_df, edges_df)
    except ValueError as exc:
        assert "Edge references unknown place id" in str(exc)
    else:
        route = compute_campus_route(graph, "main_gate", "engineering_1")
        assert route["source"] == "local_graph"


def test_no_path_returns_failure_without_crashing():
    places_df = pd.DataFrame(
        [
            {
                "id": "main_gate",
                "name": "Main Gate",
                "display_name": "Main Gate",
                "category": "gate",
                "latitude": "24.795",
                "longitude": "120.995",
                "source": "manual",
                "notes": "verified",
            },
            {
                "id": "road_1",
                "name": "Road 1",
                "display_name": "Road 1",
                "category": "road_node",
                "latitude": "24.7951",
                "longitude": "120.9951",
                "source": "manual",
                "notes": "verified",
            },
            {
                "id": "isolated",
                "name": "Isolated",
                "display_name": "Isolated",
                "category": "building",
                "latitude": "24.796",
                "longitude": "120.996",
                "source": "manual",
                "notes": "verified",
            },
        ]
    )
    edges_df = pd.DataFrame(
        [
            {
                "from_id": "main_gate",
                "to_id": "road_1",
                "distance_m": "20",
                "stairs": "0",
                "rain_friendly": "1",
                "road_name": "清華大道",
                "description": "",
                "geometry": "",
            }
        ]
    )
    graph = build_campus_graph(places_df, edges_df)

    route = compute_campus_route(graph, "main_gate", "isolated")

    assert route["success"] is False
    assert route["source"] == "local_graph"
    assert route["folium_coordinates"] == []


def test_local_graph_route_does_not_call_osrm(tmp_path):
    places_df = pd.DataFrame(
        [
            {
                "id": "start",
                "name": "Start",
                "display_name": "Start",
                "category": "building",
                "latitude": "24.795",
                "longitude": "120.995",
                "source": "manual",
                "notes": "verified",
            },
            {
                "id": "end",
                "name": "End",
                "display_name": "End",
                "category": "building",
                "latitude": "24.7951",
                "longitude": "120.9951",
                "source": "manual",
                "notes": "verified",
            },
        ]
    )
    edges_df = pd.DataFrame(
        [
            {
                "from_id": "start",
                "to_id": "end",
                "distance_m": "20",
                "stairs": "0",
                "rain_friendly": "1",
                "road_name": "Connector",
                "description": "",
                "geometry": "",
            }
        ]
    )

    with patch("app.get_osrm_route") as mock_osrm:
        route = calculate_route_for_mode(
            LOCAL_GRAPH_MODE_ID,
            places_df,
            edges_df,
            "start",
            "end",
            allow_live_osrm=False,
            route_cache_path=tmp_path / "route_cache.json",
        )

    assert route["success"] is True
    assert route["source"] == "local_graph"
    mock_osrm.assert_not_called()


def test_create_base_map_object_without_browser():
    map_obj = create_base_map()

    assert map_obj.location == [24.7959, 120.9936]
    assert "leaflet" in map_obj._repr_html_().lower()
