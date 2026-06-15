from unittest.mock import patch

import pytest

from app import (
    ROUTE_RESULT_VERSION,
    build_route_comparison,
    calculate_route_for_mode,
    load_campus_edges_for_mode,
    route_matches_selection,
)
from src.campus_graph import load_edges
from src.map_view import build_route_map
from src.route_modes import (
    CAMPUS_MODE_ID,
    COMPARE_MODE_ID,
    OSRM_MODE_ID,
    RAIN_MODE_ID,
    get_available_modes,
)
from src.utils import get_place_by_id, load_places


OSRM_RESULT = {
    "success": True,
    "distance_m": 321.0,
    "duration_s": 123.0,
    "osrm_duration_s": 123.0,
    "geometry_geojson": {
        "type": "LineString",
        "coordinates": [[120.0, 24.0], [120.1, 24.1]],
    },
    "folium_coordinates": [[24.0, 120.0], [24.1, 120.1]],
    "source": "osrm",
    "error": None,
    "cache_hit": False,
}


def test_public_route_mode_ids_are_explicit():
    assert OSRM_MODE_ID == "osrm"
    assert CAMPUS_MODE_ID == "campus"
    assert RAIN_MODE_ID == "rain_friendly"
    assert COMPARE_MODE_ID == "compare"
    assert list(get_available_modes()) == [
        OSRM_MODE_ID,
        CAMPUS_MODE_ID,
        RAIN_MODE_ID,
        COMPARE_MODE_ID,
    ]
    assert [mode["label"] for mode in get_available_modes().values()] == [
        "OSRM 路線",
        "校園路線",
        "雨天路線",
        "路線比較",
    ]


def test_stale_route_session_state_is_not_reused():
    stale_state = {
        "start_id": "a",
        "end_id": "b",
        "mode_id": OSRM_MODE_ID,
        "route_result_version": ROUTE_RESULT_VERSION - 1,
        "result": {"success": True},
    }

    assert route_matches_selection(stale_state, "a", "b", OSRM_MODE_ID) is False


def test_route_session_state_requires_matching_start_signature():
    route_state = {
        "start_id": "__current_location__",
        "start_signature": "gps:24.79590,120.99360",
        "end_id": "eecs_building",
        "mode_id": OSRM_MODE_ID,
        "route_result_version": ROUTE_RESULT_VERSION,
        "result": {"success": True},
    }

    assert route_matches_selection(
        route_state,
        "__current_location__",
        "eecs_building",
        OSRM_MODE_ID,
        start_signature="gps:24.79590,120.99360",
    ) is True
    assert route_matches_selection(
        route_state,
        "__current_location__",
        "eecs_building",
        OSRM_MODE_ID,
        start_signature="gps:24.79592,120.99360",
    ) is False


def test_osrm_mode_does_not_load_campus_edges():
    with patch("app.load_edges_cached") as load_edges:
        edges_df, error = load_campus_edges_for_mode(OSRM_MODE_ID)

    assert edges_df is None
    assert error is None
    load_edges.assert_not_called()


def test_compare_mode_loads_campus_edges_for_its_independent_campus_route():
    campus_edges = object()
    with patch("app.load_edges_cached", return_value=campus_edges) as load_edges:
        edges_df, error = load_campus_edges_for_mode(COMPARE_MODE_ID)

    assert edges_df is campus_edges
    assert error is None
    load_edges.assert_called_once()


def test_rain_mode_loads_campus_edges_for_forced_manual_segments():
    campus_edges = object()
    with patch("app.load_edges_cached", return_value=campus_edges) as load_edges:
        edges_df, error = load_campus_edges_for_mode(RAIN_MODE_ID)

    assert edges_df is campus_edges
    assert error is None
    load_edges.assert_called_once()


@pytest.mark.parametrize(
    "end_id",
    [
        "eecs_building",
        "shui_mu_student_center",
    ],
)
def test_osrm_mode_skips_all_campus_routing_for_required_scenarios(
    end_id,
    capsys,
):
    places_df = load_places("data/places.csv")

    with (
        patch("app.match_forced_route_rule") as match_forced_rule,
        patch("app.route_with_forced_rule") as forced_route,
        patch("app.build_campus_graph") as build_graph,
        patch("app.compute_campus_route") as dijkstra,
        patch("app.get_osrm_route", return_value=OSRM_RESULT) as osrm_route,
    ):
        route = calculate_route_for_mode(
            OSRM_MODE_ID,
            places_df,
            object(),
            "main_gate",
            end_id,
            allow_live_osrm=True,
            route_cache_path="data/route_cache.json",
            osrm_profile="car",
        )

    assert route is OSRM_RESULT
    assert route["source"] == "osrm"
    match_forced_rule.assert_not_called()
    forced_route.assert_not_called()
    build_graph.assert_not_called()
    dijkstra.assert_not_called()
    osrm_route.assert_called_once()

    logs = capsys.readouterr().out
    assert "[Route Mode] osrm" in logs
    assert "[Using OSRM only]" in logs
    assert "[Using Campus Dijkstra]" not in logs
    assert "[Using OSRM fallback inside campus mode]" not in logs
    assert osrm_route.call_args.kwargs["profile"] == "foot"


@pytest.mark.parametrize(
    "end_id,rule_id",
    [
        ("eecs_building", "red_bridge_rule"),
        ("shui_mu_student_center", "lakeside_rule"),
    ],
)
def test_campus_mode_allows_special_rules_for_required_scenarios(
    end_id,
    rule_id,
):
    places_df = load_places("data/places.csv")
    matched_rule = {"rule": {"id": rule_id}, "direction": "forward"}
    campus_result = {
        "success": True,
        "source": "hybrid_forced_route",
        "rule_id": rule_id,
    }

    with (
        patch("app.match_forced_route_rule", return_value=matched_rule) as match_forced_rule,
        patch("app.route_with_forced_rule", return_value=campus_result) as forced_route,
        patch("app.get_osrm_route") as osrm_route,
    ):
        route = calculate_route_for_mode(
            CAMPUS_MODE_ID,
            places_df,
            object(),
            "main_gate",
            end_id,
            allow_live_osrm=True,
            route_cache_path="data/route_cache.json",
        )

    assert route["source"] == "hybrid_forced_route"
    assert route["mode"] == CAMPUS_MODE_ID
    match_forced_rule.assert_called_once()
    forced_route.assert_called_once()
    osrm_route.assert_not_called()


def test_rain_mode_uses_rain_forced_rule_when_matched():
    places_df = load_places("data/places.csv")
    matched_rule = {"rule": {"id": "rain_rule"}, "direction": "forward"}
    rain_result = {
        "success": True,
        "source": "hybrid_forced_route",
        "rule_id": "rain_rule",
    }

    with (
        patch("app.match_forced_route_rule", return_value=matched_rule) as match_forced_rule,
        patch("app.route_with_forced_rule", return_value=rain_result) as forced_route,
        patch("app.build_campus_graph") as build_graph,
        patch("app.compute_campus_route") as dijkstra,
        patch("app.get_osrm_route_for_places") as get_osrm,
    ):
        route = calculate_route_for_mode(
            RAIN_MODE_ID,
            places_df,
            object(),
            "main_gate",
            "main_library",
            allow_live_osrm=True,
            route_cache_path="data/route_cache.json",
        )

    assert route["source"] == "hybrid_forced_route"
    assert route["mode"] == RAIN_MODE_ID
    match_forced_rule.assert_called_once()
    assert match_forced_rule.call_args.kwargs["mode_id"] == RAIN_MODE_ID
    forced_route.assert_called_once()
    build_graph.assert_not_called()
    dijkstra.assert_not_called()
    get_osrm.assert_not_called()


def test_rain_mode_uses_osrm_when_no_rain_forced_rule_matches(capsys):
    places_df = load_places("data/places.csv")
    osrm_result = {**OSRM_RESULT}

    with (
        patch("app.match_forced_route_rule", return_value=None) as match_forced_rule,
        patch("app.route_with_forced_rule") as forced_route,
        patch("app.build_campus_graph") as build_graph,
        patch("app.compute_campus_route") as dijkstra,
        patch("app.get_osrm_route_for_places", return_value=osrm_result) as get_osrm,
    ):
        route = calculate_route_for_mode(
            RAIN_MODE_ID,
            places_df,
            object(),
            "main_gate",
            "main_library",
            allow_live_osrm=True,
            route_cache_path="data/route_cache.json",
        )

    assert route is osrm_result
    assert route["source"] == "osrm"
    assert route["mode"] == RAIN_MODE_ID
    assert match_forced_rule.call_args.kwargs["mode_id"] == RAIN_MODE_ID
    forced_route.assert_not_called()
    build_graph.assert_not_called()
    dijkstra.assert_not_called()
    get_osrm.assert_called_once()

    logs = capsys.readouterr().out
    assert "[Route Mode] rain_friendly" in logs
    assert "[Rain Mode] no forced rule; using OSRM walking fallback" in logs
    assert "[Using Campus Dijkstra]" not in logs
    assert "[Using OSRM fallback inside campus mode]" not in logs


def test_campus_mode_uses_dijkstra_without_osrm_when_local_route_succeeds(capsys):
    places_df = load_places("data/places.csv")
    graph = object()
    campus_result = {
        "success": True,
        "source": "local_graph",
        "mode": CAMPUS_MODE_ID,
    }

    with (
        patch("app.match_forced_route_rule", return_value=None),
        patch("app.build_campus_graph", return_value=graph) as build_graph,
        patch("app.compute_campus_route", return_value=campus_result) as dijkstra,
        patch("app.get_osrm_route") as osrm_route,
    ):
        route = calculate_route_for_mode(
            CAMPUS_MODE_ID,
            places_df,
            object(),
            "main_gate",
            "eecs_building",
            allow_live_osrm=True,
            route_cache_path="data/route_cache.json",
        )

    assert route is campus_result
    build_graph.assert_called_once()
    dijkstra.assert_called_once_with(
        graph,
        "main_gate",
        "eecs_building",
        mode=CAMPUS_MODE_ID,
    )
    osrm_route.assert_not_called()

    logs = capsys.readouterr().out
    assert "[Route Mode] campus" in logs
    assert "[Using Campus Dijkstra]" in logs
    assert "[Using OSRM fallback inside campus mode]" not in logs


def test_campus_mode_uses_osrm_fallback_only_after_dijkstra_failure(capsys):
    places_df = load_places("data/places.csv")

    with (
        patch("app.match_forced_route_rule", return_value=None),
        patch("app.build_campus_graph", return_value=object()),
        patch(
            "app.compute_campus_route",
            return_value={"success": False, "error": "No path"},
        ),
        patch("app.get_osrm_route", return_value=OSRM_RESULT) as osrm_route,
    ):
        route = calculate_route_for_mode(
            CAMPUS_MODE_ID,
            places_df,
            object(),
            "main_gate",
            "eecs_building",
            allow_live_osrm=True,
            route_cache_path="data/route_cache.json",
        )

    assert route["source"] == "osrm_fallback"
    assert route["fallback_from"] == "local_graph"
    assert route["local_error"] == "No path"
    osrm_route.assert_called_once()

    logs = capsys.readouterr().out
    assert "[Route Mode] campus" in logs
    assert "[Using Campus Dijkstra]" in logs
    assert "[Using OSRM fallback inside campus mode]" in logs
    assert "[Using OSRM only]" not in logs


def test_build_route_comparison_includes_differences_and_special_features():
    osrm_route = {**OSRM_RESULT, "distance_m": 500.0, "duration_s": 400.0}
    campus_route = {
        "success": True,
        "source": "hybrid_forced_route",
        "rule_id": "lakeside_rule",
        "rule_name": "Lakeside 強制路線",
        "distance_m": 420.0,
        "duration_s": 300.0,
        "path_ids": ["main_gate", "xuesi_load", "fengyun_load", "shui_mu_student_center"],
        "edge_segments": [{"type": "manual", "from_id": "xuesi_load", "to_id": "fengyun_load"}],
    }

    comparison = build_route_comparison(osrm_route, campus_route)

    assert comparison["distance_m"]["campus_minus_osrm"] == -80.0
    assert comparison["duration_s"]["campus_minus_osrm"] == -100.0
    assert comparison["route_type"]["osrm"] == "OSRM 官方路線"
    assert comparison["route_type"]["campus"] == "校園自訂路線"
    assert comparison["route_features"] == [
        "自訂道路",
        "Lakeside",
        "xuesi_load",
        "fengyun_load",
    ]
    assert "少 80 公尺" in comparison["readable_summary"]


def test_build_route_comparison_marks_campus_osrm_fallback():
    comparison = build_route_comparison(
        OSRM_RESULT,
        {
            **OSRM_RESULT,
            "source": "osrm_fallback",
            "mode": CAMPUS_MODE_ID,
        },
    )

    assert comparison["route_features"] == ["OSRM fallback"]
    assert "自訂路網目前尚未完整覆蓋" in comparison["readable_summary"]


def test_compare_mode_calls_independent_route_pipelines_and_keeps_results_separate(capsys):
    places_df = load_places("data/places.csv")
    osrm_route = {**OSRM_RESULT}
    campus_route = {
        "success": True,
        "source": "hybrid_forced_route",
        "distance_m": 250.0,
        "duration_s": 200.0,
        "path_ids": ["main_gate", "red_bridge_right", "red_bridge_left", "eecs_building"],
        "edge_segments": [{"type": "manual"}],
    }

    with (
        patch("app.get_osrm_route_for_places", return_value=osrm_route) as get_osrm,
        patch("app.get_campus_route", return_value=campus_route) as get_campus,
    ):
        result = calculate_route_for_mode(
            COMPARE_MODE_ID,
            places_df,
            object(),
            "main_gate",
            "eecs_building",
            allow_live_osrm=True,
            route_cache_path="data/route_cache.json",
        )

    assert result["success"] is True
    assert result["mode"] == COMPARE_MODE_ID
    assert result["osrm"] is osrm_route
    assert result["campus"] is campus_route
    assert result["osrm"]["source"] == "osrm"
    assert result["campus"]["source"] == "hybrid_forced_route"
    assert "小紅橋" in result["comparison"]["route_features"]
    get_osrm.assert_called_once()
    get_campus.assert_called_once()

    logs = capsys.readouterr().out
    assert "[Route Mode] compare" in logs
    assert "[Compare Mode] calculating OSRM route" in logs
    assert "[Compare Mode] calculating Campus route" in logs
    assert "[Compare Result]" in logs


@pytest.mark.parametrize(
    "osrm_success,campus_success",
    [
        (True, False),
        (False, True),
        (False, False),
    ],
)
def test_compare_mode_preserves_successful_route_when_other_route_fails(
    osrm_success,
    campus_success,
):
    places_df = load_places("data/places.csv")
    osrm_route = (
        OSRM_RESULT
        if osrm_success
        else {"success": False, "source": "osrm", "error": "OSRM unavailable"}
    )
    campus_route = (
        {
            "success": True,
            "source": "local_graph",
            "distance_m": 200.0,
            "duration_s": 160.0,
            "folium_coordinates": [[24.0, 120.0], [24.2, 120.2]],
        }
        if campus_success
        else {"success": False, "source": "campus", "error": "No campus path"}
    )

    with (
        patch("app.get_osrm_route_for_places", return_value=osrm_route),
        patch("app.get_campus_route", return_value=campus_route),
    ):
        result = calculate_route_for_mode(
            COMPARE_MODE_ID,
            places_df,
            object(),
            "main_gate",
            "eecs_building",
            allow_live_osrm=True,
            route_cache_path="data/route_cache.json",
        )

    assert result["success"] is (osrm_success or campus_success)
    assert result["osrm"] is osrm_route
    assert result["campus"] is campus_route
    assert bool(result["error"]) is not (osrm_success or campus_success)


def test_compare_mode_keeps_pure_osrm_separate_from_campus_fallback():
    places_df = load_places("data/places.csv")
    pure_osrm = {**OSRM_RESULT, "distance_m": 321.0}
    campus_fallback = {
        **OSRM_RESULT,
        "source": "osrm_fallback",
        "mode": CAMPUS_MODE_ID,
        "distance_m": 654.0,
        "fallback_from": "local_graph",
    }

    with (
        patch("app.get_osrm_route_for_places", return_value=pure_osrm),
        patch("app.get_campus_route", return_value=campus_fallback),
    ):
        result = calculate_route_for_mode(
            COMPARE_MODE_ID,
            places_df,
            object(),
            "main_gate",
            "shui_mu_student_center",
            allow_live_osrm=True,
            route_cache_path="data/route_cache.json",
        )

    assert result["osrm"]["source"] == "osrm"
    assert result["osrm"]["distance_m"] == 321.0
    assert result["campus"]["source"] == "osrm_fallback"
    assert result["campus"]["distance_m"] == 654.0
    assert result["comparison"]["distance_m"]["campus_minus_osrm"] == 333.0


@pytest.mark.parametrize(
    "end_id,expected_features",
    [
        ("eecs_building", {"自訂道路", "小紅橋"}),
        (
            "shui_mu_student_center",
            {"自訂道路", "Lakeside", "xuesi_load", "fengyun_load"},
        ),
    ],
)
def test_compare_mode_required_scenarios_keep_pure_osrm_and_campus_special_rules(
    end_id,
    expected_features,
):
    places_df = load_places("data/places.csv")
    edges_df = load_edges("data/campus_edges.csv")

    with patch("app.get_osrm_route", return_value=OSRM_RESULT) as osrm_router:
        result = calculate_route_for_mode(
            COMPARE_MODE_ID,
            places_df,
            edges_df,
            "main_gate",
            end_id,
            allow_live_osrm=True,
            route_cache_path="data/route_cache.json",
        )

    assert result["osrm"]["source"] == "osrm"
    assert result["osrm"]["folium_coordinates"] == OSRM_RESULT["folium_coordinates"]
    assert result["campus"]["source"] == "hybrid_forced_route"
    assert expected_features.issubset(set(result["comparison"]["route_features"]))
    assert osrm_router.call_count == 2


def test_compare_map_draws_two_distinct_route_styles():
    places_df = load_places("data/places.csv")
    route_result = {
        "success": True,
        "mode": COMPARE_MODE_ID,
        "osrm": OSRM_RESULT,
        "campus": {
            "success": True,
            "source": "local_graph",
            "distance_m": 200.0,
            "duration_s": 160.0,
            "folium_coordinates": [[24.0, 120.0], [24.2, 120.2]],
        },
    }
    map_obj = build_route_map(
        places_df,
        get_place_by_id(places_df, "main_gate"),
        get_place_by_id(places_df, "eecs_building"),
        route_result,
    )

    html = map_obj.get_root().render()
    assert "OSRM route" in html
    assert "Campus route" in html
    assert "#2563eb" in html
    assert "#ea580c" in html
    assert "10 8" in html
