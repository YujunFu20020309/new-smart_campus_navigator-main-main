import json
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd
import pytest

from app import calculate_route_for_mode
from src.campus_graph import build_campus_graph
from src.forced_routes import (
    add_forced_route_rule,
    delete_forced_route_rule,
    get_manual_edge_geometry,
    load_forced_route_rules,
    match_forced_route_rule,
    merge_geometries,
    route_with_forced_rule,
    save_forced_route_rules,
    update_forced_route_rule,
)
from src.route_modes import CAMPUS_MODE_ID, LOCAL_GRAPH_MODE_ID, RAIN_MODE_ID
from src.utils import get_place_by_id, load_places
from src.campus_graph import load_edges


RULE_PATH = Path("data/forced_route_rules.json")
FORWARD_STARTS = [
    "main_gate",
    "engineering_building_i",
    "main_library",
    "motor_parking_exit",
]
FORWARD_ENDS = ["delta_building", "eecs_building"]
LAKESIDE_ENDS = ["shui_mu_student_center", "feng_yun_building"]
ALL_RED_BRIDGE_ROUTES = [
    (
        start_id,
        end_id,
        "forward",
        [start_id, "red_bridge_right", "red_bridge_left", end_id],
    )
    for start_id in FORWARD_STARTS
    for end_id in FORWARD_ENDS
] + [
    (
        start_id,
        end_id,
        "backward",
        [start_id, "red_bridge_left", "red_bridge_right", end_id],
    )
    for start_id in FORWARD_ENDS
    for end_id in FORWARD_STARTS
]


def _mock_osrm_route(start_lat, start_lon, end_lat, end_lon, **_kwargs):
    return {
        "success": True,
        "distance_m": 100.0,
        "duration_s": 80.0,
        "osrm_duration_s": 20.0,
        "folium_coordinates": [
            [float(start_lat), float(start_lon)],
            [float(end_lat), float(end_lon)],
        ],
        "source": "osrm",
        "error": None,
        "cache_hit": True,
    }


def test_default_red_bridge_rule_content():
    rules = load_forced_route_rules(RULE_PATH)

    rule = rules[0]
    assert rule["id"] == "red_bridge_rule"
    assert rule["enabled"] is True
    assert rule["bidirectional"] is True
    assert rule["from_place_ids"] == FORWARD_STARTS
    assert rule["to_place_ids"] == FORWARD_ENDS
    assert [segment["type"] for segment in rule["forward_segments"]] == [
        "osrm",
        "manual",
        "straight",
    ]


def test_default_lakeside_rule_content():
    rules = load_forced_route_rules(RULE_PATH)
    rule = next(rule for rule in rules if rule["id"] == "lakeside_rule")

    assert rule["name"] == "Lakeside 強制路線"
    assert rule["enabled"] is True
    assert rule["bidirectional"] is True
    assert rule["from_place_ids"] == FORWARD_STARTS
    assert rule["to_place_ids"] == LAKESIDE_ENDS
    assert [segment["type"] for segment in rule["forward_segments"]] == [
        "osrm",
        "manual",
        "straight",
    ]


@pytest.mark.parametrize("start_id", FORWARD_STARTS)
@pytest.mark.parametrize("end_id", FORWARD_ENDS)
def test_all_forward_red_bridge_pairs_match(start_id, end_id):
    match = match_forced_route_rule(start_id, end_id, path=RULE_PATH)

    assert match is not None
    assert match["rule"]["id"] == "red_bridge_rule"
    assert match["direction"] == "forward"


@pytest.mark.parametrize("start_id", FORWARD_ENDS)
@pytest.mark.parametrize("end_id", FORWARD_STARTS)
def test_all_backward_red_bridge_pairs_match(start_id, end_id):
    match = match_forced_route_rule(start_id, end_id, path=RULE_PATH)

    assert match is not None
    assert match["rule"]["id"] == "red_bridge_rule"
    assert match["direction"] == "backward"


def test_disabled_rule_does_not_match():
    rules = [
        {
            "id": "disabled",
            "enabled": False,
            "bidirectional": True,
            "from_place_ids": ["a"],
            "to_place_ids": ["b"],
            "forward_segments": [],
        }
    ]

    assert match_forced_route_rule("a", "b", rules) is None


def test_campus_mode_does_not_match_rain_only_rule():
    rules = [
        {
            "id": "rain_only",
            "enabled": True,
            "bidirectional": True,
            "modes": [RAIN_MODE_ID],
            "from_place_ids": ["a"],
            "to_place_ids": ["b"],
            "forward_segments": [],
        }
    ]

    assert match_forced_route_rule("a", "b", rules, mode_id=CAMPUS_MODE_ID) is None


def test_rain_mode_matches_rain_only_rule():
    rules = [
        {
            "id": "rain_only",
            "enabled": True,
            "bidirectional": True,
            "modes": [RAIN_MODE_ID],
            "from_place_ids": ["a"],
            "to_place_ids": ["b"],
            "forward_segments": [],
        }
    ]

    match = match_forced_route_rule("a", "b", rules, mode_id=RAIN_MODE_ID)

    assert match is not None
    assert match["rule"]["id"] == "rain_only"
    assert match["direction"] == "forward"


def test_unscoped_campus_forced_routes_still_match_with_mode_id():
    match = match_forced_route_rule(
        "main_gate",
        "delta_building",
        path=RULE_PATH,
        mode_id=CAMPUS_MODE_ID,
    )

    assert match is not None
    assert match["rule"]["id"] == "red_bridge_rule"
    assert "modes" not in match["rule"]


def test_rule_crud_round_trip(tmp_path):
    path = tmp_path / "rules.json"
    save_forced_route_rules([], path)
    rule = {
        "id": "test_rule",
        "name": "Test",
        "enabled": True,
        "from_place_ids": ["a"],
        "to_place_ids": ["b"],
        "forward_segments": [],
    }

    add_forced_route_rule(rule, path)
    assert load_forced_route_rules(path)[0]["id"] == "test_rule"

    update_forced_route_rule("test_rule", {**rule, "enabled": False}, path)
    assert load_forced_route_rules(path)[0]["enabled"] is False

    assert delete_forced_route_rule("test_rule", path) is True
    assert load_forced_route_rules(path) == []


def test_merge_geometries_removes_adjacent_duplicate():
    merged = merge_geometries(
        [
            [[120.0, 24.0], [120.1, 24.1]],
            [[120.1, 24.1], [120.2, 24.2]],
        ]
    )

    assert merged == [[120.0, 24.0], [120.1, 24.1], [120.2, 24.2]]


def test_manual_edge_can_reverse_empty_geometry_from_places():
    places_df = load_places("data/places.csv")
    edges_df = load_edges("data/campus_edges.csv")

    result = get_manual_edge_geometry(
        "red_bridge_left",
        "red_bridge_right",
        places_df,
        edges_df,
    )

    assert result["reversed"] is True
    assert result["geometry"][0] == [120.99277, 24.795467]
    assert result["geometry"][-1] == [120.993118, 24.795409]


@pytest.mark.parametrize(
    ("start_id", "end_id", "direction", "expected_path"),
    ALL_RED_BRIDGE_ROUTES,
)
def test_all_required_routes_use_hybrid_forced_red_bridge_route(
    start_id,
    end_id,
    direction,
    expected_path,
):
    places_df = load_places("data/places.csv")
    edges_df = load_edges("data/campus_edges.csv")
    matched = match_forced_route_rule(start_id, end_id, path=RULE_PATH)

    mock_osrm = Mock(side_effect=_mock_osrm_route)
    route = route_with_forced_rule(
        get_place_by_id(places_df, start_id),
        get_place_by_id(places_df, end_id),
        matched,
        places_df=places_df,
        edges_df=edges_df,
        osrm_router=mock_osrm,
    )

    assert route["success"] is True
    assert route["source"] == "hybrid_forced_route"
    assert route["direction"] == direction
    assert route["path_ids"] == expected_path
    assert [120.993118, 24.795409] in route["geometry"]
    assert [120.99277, 24.795467] in route["geometry"]
    assert route["folium_coordinates"][0][0] < 30
    assert route["geometry"][0][0] > 100
    assert mock_osrm.call_count == 1
    assert mock_osrm.call_args.kwargs["profile"] == "foot"
    assert route["duration_s"] >= route["distance_m"] / 1.4


@pytest.mark.parametrize(
    ("start_id", "end_id", "direction", "expected_path"),
    [
        (
            start_id,
            end_id,
            "forward",
            [start_id, "xuesi_load", "fengyun_load", end_id],
        )
        for start_id in FORWARD_STARTS
        for end_id in LAKESIDE_ENDS
    ]
    + [
        (
            start_id,
            end_id,
            "backward",
            [start_id, "fengyun_load", "xuesi_load", end_id],
        )
        for start_id in LAKESIDE_ENDS
        for end_id in FORWARD_STARTS
    ],
)
def test_all_required_lakeside_routes_use_hybrid_forced_route(
    start_id,
    end_id,
    direction,
    expected_path,
):
    places_df = load_places("data/places.csv")
    edges_df = load_edges("data/campus_edges.csv")
    matched = match_forced_route_rule(start_id, end_id, path=RULE_PATH)
    mock_osrm = Mock(side_effect=_mock_osrm_route)

    route = route_with_forced_rule(
        get_place_by_id(places_df, start_id),
        get_place_by_id(places_df, end_id),
        matched,
        places_df=places_df,
        edges_df=edges_df,
        osrm_router=mock_osrm,
    )

    assert route["success"] is True
    assert route["source"] == "hybrid_forced_route"
    assert route["direction"] == direction
    assert route["path_ids"] == expected_path
    assert [120.995387, 24.79463] in route["geometry"]
    assert [120.993995, 24.792491] in route["geometry"]
    assert mock_osrm.call_count == 1
    assert mock_osrm.call_args.kwargs["profile"] == "foot"
    assert route["duration_s"] >= route["distance_m"] / 1.4
    assert all(segment["duration_s"] > 0 for segment in route["edge_segments"])


def test_main_route_flow_prioritizes_forced_rule(tmp_path):
    places_df = load_places("data/places.csv")
    edges_df = load_edges("data/campus_edges.csv")

    with patch("app.get_osrm_route", side_effect=_mock_osrm_route) as mock_osrm:
        route = calculate_route_for_mode(
            LOCAL_GRAPH_MODE_ID,
            places_df,
            edges_df,
            "main_gate",
            "delta_building",
            allow_live_osrm=True,
            route_cache_path=tmp_path / "route_cache.json",
        )

    assert route["source"] == "hybrid_forced_route"
    assert route["rule_id"] == "red_bridge_rule"
    assert mock_osrm.call_count == 1


def test_campus_graph_defaults_to_bidirectional_and_reverses_geometry():
    places_df = pd.DataFrame(
        [
            {
                "id": "a",
                "name": "A",
                "display_name": "A",
                "category": "road_node",
                "latitude": "24.0",
                "longitude": "120.0",
                "source": "manual",
                "notes": "verified",
            },
            {
                "id": "b",
                "name": "B",
                "display_name": "B",
                "category": "road_node",
                "latitude": "24.1",
                "longitude": "120.1",
                "source": "manual",
                "notes": "verified",
            },
        ]
    )
    edges_df = pd.DataFrame(
        [
            {
                "from_id": "a",
                "to_id": "b",
                "distance_m": "20",
                "stairs": "0",
                "rain_friendly": "1",
                "road_name": "Test",
                "description": "",
                "geometry": json.dumps([[120.0, 24.0], [120.1, 24.1]]),
            }
        ]
    )

    graph = build_campus_graph(places_df, edges_df)

    assert graph.has_edge("a", "b")
    assert graph.has_edge("b", "a")
    assert graph["b"]["a"]["geometry"] == [[24.1, 120.1], [24.0, 120.0]]


@pytest.mark.parametrize(
    "control",
    [{"one_way": "1"}, {"bidirectional": "0"}],
)
def test_explicit_one_way_edge_is_not_reversed(control):
    places_df = pd.DataFrame(
        [
            {
                "id": node_id,
                "name": node_id,
                "display_name": node_id,
                "category": "road_node",
                "latitude": "24.0",
                "longitude": "120.0",
                "source": "manual",
                "notes": "verified",
            }
            for node_id in ("a", "b")
        ]
    )
    edge = {
        "from_id": "a",
        "to_id": "b",
        "distance_m": "20",
        "stairs": "0",
        "rain_friendly": "1",
        "road_name": "Test",
        "description": "",
        "geometry": "",
        **control,
    }

    graph = build_campus_graph(places_df, pd.DataFrame([edge]))

    assert graph.has_edge("a", "b")
    assert not graph.has_edge("b", "a")
