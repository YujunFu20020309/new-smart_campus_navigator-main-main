import json

import pandas as pd
import pytest

from src.campus_graph import build_campus_graph
from src.data_admin import (
    EDGE_COLUMNS,
    PENDING_PLACE_COLUMNS,
    PLACE_COLUMNS,
    append_edge,
    append_pending_place,
    append_place,
    load_edges_for_editing,
    load_pending_places,
    load_places_for_editing,
    save_edges,
    save_places,
    sanitize_place_id,
)


def _places_df():
    return pd.DataFrame(
        [
            {
                "id": "node_a",
                "name": "Node A",
                "display_name": "Node A",
                "category": "intersection",
                "latitude": "24.795",
                "longitude": "120.995",
                "source": "manual",
                "notes": "verified",
                "is_destination": "0",
                "show_marker": "0",
            }
        ],
        columns=PLACE_COLUMNS,
    )


def _edges_df():
    return pd.DataFrame([], columns=EDGE_COLUMNS)


def _new_place():
    return {
        "id": "node_b",
        "name": "Node B",
        "display_name": "Node B",
        "category": "road_node",
        "latitude": "24.796",
        "longitude": "120.996",
        "source": "manual",
        "notes": "manual_added",
        "is_destination": False,
        "show_marker": False,
    }


def _pending_place(**changes):
    place = {
        "id": "new_library",
        "name": "New Library",
        "display_name": "New Library",
        "category": "library",
        "latitude": "24.796",
        "longitude": "120.996",
        "is_destination": True,
        "show_marker": True,
        "type": "candidate",
    }
    place.update(changes)
    return place


def _new_edge(**changes):
    edge = {
        "from_id": "node_a",
        "to_id": "node_b",
        "distance_m": 50,
        "stairs": False,
        "rain_friendly": True,
        "road_name": "Test Road",
        "description": "Test edge",
        "geometry": "",
    }
    edge.update(changes)
    return edge


def test_sanitize_place_id():
    assert sanitize_place_id("  New Campus Node 42! ") == "new_campus_node_42"


def test_append_place_adds_valid_place_and_rejects_duplicate(tmp_path):
    path = tmp_path / "places.csv"
    save_places(path, _places_df())

    append_place(path, _new_place())
    loaded = load_places_for_editing(path)
    assert "node_b" in loaded["id"].tolist()

    with pytest.raises(ValueError, match="already exists"):
        append_place(path, _new_place())


def test_append_pending_place_does_not_modify_places_csv(tmp_path):
    places_path = tmp_path / "places.csv"
    pending_path = tmp_path / "manual_places_pending.csv"
    save_places(places_path, _places_df())
    official_places = load_places_for_editing(places_path)
    before = places_path.read_bytes()

    append_pending_place(pending_path, official_places, _pending_place())

    assert places_path.read_bytes() == before
    assert pending_path.exists()


def test_pending_place_csv_uses_expected_columns_and_fixed_review_fields(tmp_path):
    places_path = tmp_path / "places.csv"
    pending_path = tmp_path / "manual_places_pending.csv"
    save_places(places_path, _places_df())
    official_places = load_places_for_editing(places_path)

    append_pending_place(
        pending_path,
        official_places,
        _pending_place(notes="user supplied note", source="manual"),
    )
    pending = load_pending_places(pending_path)

    assert list(pending.columns) == PENDING_PLACE_COLUMNS
    assert pending.loc[0, "id"] == "new_library"
    assert pending.loc[0, "source"] == "manual_ui_pending"
    assert pending.loc[0, "notes"] == "pending_review"
    assert pending.loc[0, "type"] == "candidate"
    assert pending.loc[0, "is_destination"] == "1"
    assert pending.loc[0, "show_marker"] == "1"


def test_pending_place_rejects_duplicate_ids(tmp_path):
    places_path = tmp_path / "places.csv"
    pending_path = tmp_path / "manual_places_pending.csv"
    save_places(places_path, _places_df())
    official_places = load_places_for_editing(places_path)

    with pytest.raises(ValueError, match="places.csv"):
        append_pending_place(pending_path, official_places, _pending_place(id="node_a"))

    append_pending_place(pending_path, official_places, _pending_place())
    with pytest.raises(ValueError, match="pending"):
        append_pending_place(pending_path, official_places, _pending_place())


def test_pending_place_rejects_out_of_bounds_coordinates(tmp_path):
    places_path = tmp_path / "places.csv"
    pending_path = tmp_path / "manual_places_pending.csv"
    save_places(places_path, _places_df())
    official_places = load_places_for_editing(places_path)

    with pytest.raises(ValueError, match="outside"):
        append_pending_place(
            pending_path,
            official_places,
            _pending_place(latitude="25.0", longitude="121.5"),
        )


def test_append_edge_validates_ids_geometry_and_accepts_blank(tmp_path):
    places_path = tmp_path / "places.csv"
    edges_path = tmp_path / "campus_edges.csv"
    save_places(places_path, _places_df())
    append_place(places_path, _new_place())
    places_df = load_places_for_editing(places_path)
    save_edges(edges_path, _edges_df())

    append_edge(edges_path, places_df, _new_edge())
    loaded = load_edges_for_editing(edges_path)
    assert loaded.iloc[0]["geometry"] == ""

    with pytest.raises(ValueError, match="does not exist"):
        append_edge(edges_path, places_df, _new_edge(from_id="missing"))
    with pytest.raises(ValueError, match="valid JSON"):
        append_edge(edges_path, places_df, _new_edge(geometry="not-json"))


def test_save_reload_and_build_graph_with_new_data(tmp_path):
    places_path = tmp_path / "places.csv"
    edges_path = tmp_path / "campus_edges.csv"
    save_places(places_path, _places_df())
    append_place(places_path, _new_place())
    places_df = load_places_for_editing(places_path)
    save_edges(edges_path, _edges_df())
    append_edge(
        edges_path,
        places_df,
        _new_edge(geometry=json.dumps([[120.995, 24.795], [120.996, 24.796]])),
    )

    loaded_places = load_places_for_editing(places_path)
    loaded_edges = load_edges_for_editing(edges_path)
    graph = build_campus_graph(loaded_places, loaded_edges)

    assert list(loaded_places.columns) == PLACE_COLUMNS
    assert list(loaded_edges.columns) == EDGE_COLUMNS
    assert graph.has_edge("node_a", "node_b")
    assert graph["node_a"]["node_b"]["geometry"] == [
        [24.795, 120.995],
        [24.796, 120.996],
    ]


def test_legacy_edges_get_control_column_defaults(tmp_path):
    path = tmp_path / "campus_edges.csv"
    pd.DataFrame(
        [
            {
                "from_id": "node_a",
                "to_id": "node_b",
                "distance_m": "10",
                "stairs": "0",
                "rain_friendly": "1",
                "road_name": "Test",
                "description": "",
                "geometry": "",
            }
        ]
    ).to_csv(path, index=False)

    loaded = load_edges_for_editing(path)

    assert loaded.loc[0, "routing_source"] == "manual"
    assert loaded.loc[0, "ignore_osrm"] == "0"
    assert loaded.loc[0, "verified"] == "0"
    assert loaded.loc[0, "enabled"] == "1"


def test_append_edge_zero_distance_is_auto_calculated(tmp_path):
    places_path = tmp_path / "places.csv"
    edges_path = tmp_path / "campus_edges.csv"
    save_places(places_path, _places_df())
    append_place(places_path, _new_place())
    places_df = load_places_for_editing(places_path)
    save_edges(edges_path, _edges_df())

    append_edge(edges_path, places_df, _new_edge(distance_m=0))
    loaded = load_edges_for_editing(edges_path)

    assert float(loaded.loc[0, "distance_m"]) > 0


def test_append_edge_blank_distance_is_auto_calculated(tmp_path):
    places_path = tmp_path / "places.csv"
    edges_path = tmp_path / "campus_edges.csv"
    save_places(places_path, _places_df())
    append_place(places_path, _new_place())
    places_df = load_places_for_editing(places_path)
    save_edges(edges_path, _edges_df())

    append_edge(edges_path, places_df, _new_edge(distance_m=""))
    loaded = load_edges_for_editing(edges_path)

    assert float(loaded.loc[0, "distance_m"]) > 0


def test_append_edge_zero_distance_uses_geometry_polyline(tmp_path):
    places_path = tmp_path / "places.csv"
    edges_path = tmp_path / "campus_edges.csv"
    save_places(places_path, _places_df())
    append_place(places_path, _new_place())
    places_df = load_places_for_editing(places_path)
    save_edges(edges_path, _edges_df())
    geometry = json.dumps([[120.995, 24.795], [120.995, 24.7955], [120.995, 24.796]])

    append_edge(edges_path, places_df, _new_edge(distance_m=0, geometry=geometry))
    loaded = load_edges_for_editing(edges_path)

    assert 110 < float(loaded.loc[0, "distance_m"]) < 112
