from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pandas as pd

from src.campus_graph import build_campus_graph, compute_campus_route
from src.forced_routes import match_forced_route_rule, route_with_forced_rule
from src.route_modes import CAMPUS_MODE_ID, COMPARE_MODE_ID, OSRM_MODE_ID, RAIN_MODE_ID
from src.routing_osrm import get_osrm_route
from src.utils import get_place_by_id, parse_coordinate, place_has_coordinates


def route_failure(source: str, mode: str, error: str) -> dict[str, Any]:
    return {
        "success": False,
        "distance_m": None,
        "duration_s": None,
        "cost": None,
        "folium_coordinates": [],
        "path_ids": [],
        "path_names": [],
        "edge_segments": [],
        "source": source,
        "mode": mode,
        "error": error,
        "cache_hit": False,
    }


def get_campus_route_features(campus_route: dict[str, Any]) -> list[str]:
    """Describe campus-only route features used by one campus result."""
    if not campus_route.get("success"):
        return []

    features: list[str] = []
    path_ids = {str(node_id).lower() for node_id in campus_route.get("path_ids", [])}
    edge_segments = campus_route.get("edge_segments", [])
    searchable_text = " ".join(
        [
            str(campus_route.get("rule_id", "")),
            str(campus_route.get("rule_name", "")),
            *path_ids,
            *[
                " ".join(
                    [
                        str(segment.get("from_id", "")),
                        str(segment.get("to_id", "")),
                        str(segment.get("road_name", "")),
                    ]
                )
                for segment in edge_segments
            ],
        ]
    ).lower()

    if any(
        segment.get("type") in {"manual", "straight"}
        or str(segment.get("routing_source", "")).lower() == "manual"
        for segment in edge_segments
    ):
        features.append("自訂道路")
    if "red_bridge" in searchable_text or "小紅橋" in searchable_text:
        features.append("小紅橋")
    if "lakeside" in searchable_text:
        features.append("Lakeside")
    if "xuesi_load" in searchable_text:
        features.append("xuesi_load")
    if "fengyun_load" in searchable_text:
        features.append("fengyun_load")
    if campus_route.get("source") == "osrm_fallback":
        features.append("OSRM fallback")
    return features


def _numeric_difference(
    campus_route: dict[str, Any],
    osrm_route: dict[str, Any],
    key: str,
) -> float | None:
    if not campus_route.get("success") or not osrm_route.get("success"):
        return None
    campus_value = campus_route.get(key)
    osrm_value = osrm_route.get(key)
    if campus_value is None or osrm_value is None:
        return None
    return float(campus_value) - float(osrm_value)


def build_route_comparison(
    osrm_route: dict[str, Any],
    campus_route: dict[str, Any],
) -> dict[str, Any]:
    """Build a comparison without modifying either independently calculated route."""
    distance_difference = _numeric_difference(campus_route, osrm_route, "distance_m")
    duration_difference = _numeric_difference(campus_route, osrm_route, "duration_s")
    features = get_campus_route_features(campus_route)
    custom_features = [feature for feature in features if feature != "OSRM fallback"]

    if not osrm_route.get("success") and not campus_route.get("success"):
        summary = "OSRM 路線與校園路線皆無法生成。"
    elif not osrm_route.get("success"):
        summary = "OSRM 路線無法生成；目前僅顯示校園路線。"
    elif not campus_route.get("success"):
        summary = "校園路線無法生成；目前僅顯示 OSRM 路線。"
    else:
        distance_m = abs(distance_difference or 0)
        duration_s = abs(duration_difference or 0)
        if distance_difference == 0:
            distance_summary = "與 OSRM 距離相同"
        else:
            distance_text = "少" if (distance_difference or 0) < 0 else "多"
            distance_summary = f"比 OSRM {distance_text} {distance_m:.0f} 公尺"
        if duration_difference == 0:
            duration_summary = "預估時間相同"
        else:
            duration_text = "快" if (duration_difference or 0) < 0 else "慢"
            duration_summary = f"預估{duration_text} {duration_s / 60:.1f} 分鐘"
        summary = (
            f"校園路線{distance_summary}，"
            f"{duration_summary}。"
        )
        if custom_features and (distance_difference or 0) > 0:
            summary += " 校園路線雖較長，但使用較符合校園行走習慣的自訂路段。"
        if "OSRM fallback" in features:
            summary += " 校園路線包含 OSRM fallback，代表自訂路網目前尚未完整覆蓋。"

    return {
        "distance_m": {
            "osrm": osrm_route.get("distance_m") if osrm_route.get("success") else None,
            "campus": campus_route.get("distance_m") if campus_route.get("success") else None,
            "campus_minus_osrm": distance_difference,
        },
        "duration_s": {
            "osrm": osrm_route.get("duration_s") if osrm_route.get("success") else None,
            "campus": campus_route.get("duration_s") if campus_route.get("success") else None,
            "campus_minus_osrm": duration_difference,
        },
        "route_type": {
            "osrm": "OSRM 官方路線",
            "campus": "校園自訂路線",
        },
        "route_features": features,
        "readable_summary": summary,
    }


def get_osrm_route_for_places(
    places_df: pd.DataFrame,
    start_id: str,
    end_id: str,
    *,
    allow_live_osrm: bool,
    route_cache_path: str | Path,
    osrm_profile: str = "foot",
    ignore_osrm_cache: bool = False,
    osrm_router: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return the unmodified OSRM route for two places."""
    osrm_router = get_osrm_route if osrm_router is None else osrm_router
    try:
        start_place = get_place_by_id(places_df, start_id)
        end_place = get_place_by_id(places_df, end_id)
    except KeyError as exc:
        return route_failure("osrm", OSRM_MODE_ID, str(exc))

    if not place_has_coordinates(start_place):
        return route_failure("osrm", OSRM_MODE_ID, "Start place is missing coordinates.")
    if not place_has_coordinates(end_place):
        return route_failure("osrm", OSRM_MODE_ID, "End place is missing coordinates.")

    return osrm_router(
        parse_coordinate(start_place["latitude"]),
        parse_coordinate(start_place["longitude"]),
        parse_coordinate(end_place["latitude"]),
        parse_coordinate(end_place["longitude"]),
        profile="foot",
        cache_path=route_cache_path,
        allow_network=allow_live_osrm or ignore_osrm_cache,
        ignore_cache=ignore_osrm_cache,
    )


def get_campus_route(
    places_df: pd.DataFrame,
    edges_df: pd.DataFrame | None,
    start_id: str,
    end_id: str,
    *,
    allow_live_osrm: bool,
    forced_rules_path: str | Path,
    route_cache_path: str | Path,
    osrm_profile: str = "foot",
    ignore_osrm_cache: bool = False,
    match_rule_func: Callable[..., dict[str, Any] | None] | None = None,
    forced_route_func: Callable[..., dict[str, Any]] | None = None,
    campus_graph_builder: Callable[..., Any] | None = None,
    campus_route_computer: Callable[..., dict[str, Any]] | None = None,
    osrm_router: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Use campus rules and Dijkstra, with OSRM only as a campus fallback."""
    match_rule_func = match_forced_route_rule if match_rule_func is None else match_rule_func
    forced_route_func = route_with_forced_rule if forced_route_func is None else forced_route_func
    campus_graph_builder = build_campus_graph if campus_graph_builder is None else campus_graph_builder
    campus_route_computer = (
        compute_campus_route if campus_route_computer is None else campus_route_computer
    )
    osrm_router = get_osrm_route if osrm_router is None else osrm_router

    try:
        matched_rule = match_rule_func(
            start_id,
            end_id,
            path=forced_rules_path,
            mode_id=CAMPUS_MODE_ID,
        )
    except ValueError as exc:
        return route_failure("hybrid_forced_route", CAMPUS_MODE_ID, str(exc))

    if matched_rule is not None:
        if edges_df is None:
            return route_failure(
                "hybrid_forced_route",
                CAMPUS_MODE_ID,
                "A forced route rule matched, but campus_edges.csv is not available.",
            )
        try:
            start_place = get_place_by_id(places_df, start_id)
            end_place = get_place_by_id(places_df, end_id)
        except KeyError as exc:
            return route_failure("hybrid_forced_route", CAMPUS_MODE_ID, str(exc))
        forced_route = forced_route_func(
            start_place,
            end_place,
            matched_rule,
            places_df=places_df,
            edges_df=edges_df,
            osrm_router=osrm_router,
            route_cache_path=route_cache_path,
            osrm_profile="foot",
            allow_network=allow_live_osrm or ignore_osrm_cache,
            ignore_cache=ignore_osrm_cache,
        )
        forced_route["mode"] = CAMPUS_MODE_ID
        return forced_route

    local_error = ""
    if edges_df is None:
        local_error = "campus_edges.csv is not available."
    else:
        print("[Using Campus Dijkstra]")
        try:
            graph = campus_graph_builder(places_df, edges_df)
        except Exception as exc:
            local_error = (
                f"Failed to build campus graph: {type(exc).__name__}: {repr(exc)}"
            )
        else:
            local_route = campus_route_computer(graph, start_id, end_id, mode=CAMPUS_MODE_ID)
            if local_route.get("success"):
                return local_route
            local_error = str(local_route.get("error") or "Local graph route failed.")

    print("[Using OSRM fallback inside campus mode]")
    try:
        start_place = get_place_by_id(places_df, start_id)
        end_place = get_place_by_id(places_df, end_id)
    except KeyError as exc:
        osrm_error = f"OSRM fallback place lookup failed: {exc}"
    else:
        if not place_has_coordinates(start_place):
            osrm_error = "OSRM fallback start place is missing coordinates."
        elif not place_has_coordinates(end_place):
            osrm_error = "OSRM fallback end place is missing coordinates."
        else:
            osrm_result = osrm_router(
                parse_coordinate(start_place["latitude"]),
                parse_coordinate(start_place["longitude"]),
                parse_coordinate(end_place["latitude"]),
                parse_coordinate(end_place["longitude"]),
                profile="foot",
                cache_path=route_cache_path,
                allow_network=allow_live_osrm or ignore_osrm_cache,
                ignore_cache=ignore_osrm_cache,
            )
            if osrm_result.get("success"):
                return {
                    **osrm_result,
                    "source": "osrm_fallback",
                    "fallback_from": "local_graph",
                    "local_error": local_error,
                    "mode": CAMPUS_MODE_ID,
                    "path_ids": [],
                    "path_names": [],
                    "edge_segments": [],
                }
            osrm_error = str(osrm_result.get("error") or "OSRM fallback failed.")

    failure = route_failure(
        "osrm_fallback",
        CAMPUS_MODE_ID,
        f"Local graph error: {local_error}; "
        f"OSRM fallback error: {osrm_error}",
    )
    failure.update(
        {
            "fallback_from": "local_graph",
            "local_error": local_error,
            "osrm_error": osrm_error,
        }
    )
    return failure


def _forced_rule_uses_manual_segments(matched_rule: dict[str, Any]) -> bool:
    return any(
        str(segment.get("type", "")).strip().lower() == "manual"
        for segment in matched_rule.get("rule", {}).get("forward_segments", [])
    )


def get_rain_route(
    places_df: pd.DataFrame,
    edges_df: pd.DataFrame | None,
    start_id: str,
    end_id: str,
    *,
    allow_live_osrm: bool,
    forced_rules_path: str | Path,
    route_cache_path: str | Path,
    osrm_profile: str = "foot",
    ignore_osrm_cache: bool = False,
    match_rule_func: Callable[..., dict[str, Any] | None] | None = None,
    forced_route_func: Callable[..., dict[str, Any]] | None = None,
    osrm_route_for_places_func: Callable[..., dict[str, Any]] | None = None,
    osrm_router: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Use rain-specific forced rules, otherwise fall back to pure OSRM walking."""
    match_rule_func = match_forced_route_rule if match_rule_func is None else match_rule_func
    forced_route_func = route_with_forced_rule if forced_route_func is None else forced_route_func
    osrm_router = get_osrm_route if osrm_router is None else osrm_router

    try:
        matched_rule = match_rule_func(
            start_id,
            end_id,
            path=forced_rules_path,
            mode_id=RAIN_MODE_ID,
        )
    except ValueError as exc:
        return route_failure("hybrid_forced_route", RAIN_MODE_ID, str(exc))

    if matched_rule is not None:
        if edges_df is None and _forced_rule_uses_manual_segments(matched_rule):
            return route_failure(
                "hybrid_forced_route",
                RAIN_MODE_ID,
                "A rain forced route rule matched, but campus_edges.csv is not available.",
            )
        try:
            start_place = get_place_by_id(places_df, start_id)
            end_place = get_place_by_id(places_df, end_id)
        except KeyError as exc:
            return route_failure("hybrid_forced_route", RAIN_MODE_ID, str(exc))
        forced_route = forced_route_func(
            start_place,
            end_place,
            matched_rule,
            places_df=places_df,
            edges_df=edges_df if edges_df is not None else pd.DataFrame(),
            osrm_router=osrm_router,
            route_cache_path=route_cache_path,
            osrm_profile="foot",
            allow_network=allow_live_osrm or ignore_osrm_cache,
            ignore_cache=ignore_osrm_cache,
        )
        forced_route["mode"] = RAIN_MODE_ID
        return forced_route

    print("[Rain Mode] no forced rule; using OSRM walking fallback")
    if osrm_route_for_places_func is None:
        osrm_result = get_osrm_route_for_places(
            places_df,
            start_id,
            end_id,
            allow_live_osrm=allow_live_osrm,
            route_cache_path=route_cache_path,
            osrm_profile=osrm_profile,
            ignore_osrm_cache=ignore_osrm_cache,
            osrm_router=osrm_router,
        )
    else:
        osrm_result = osrm_route_for_places_func(
            places_df,
            start_id,
            end_id,
            allow_live_osrm=allow_live_osrm,
            route_cache_path=route_cache_path,
            osrm_profile=osrm_profile,
            ignore_osrm_cache=ignore_osrm_cache,
        )
    osrm_result["mode"] = RAIN_MODE_ID
    return osrm_result


def calculate_route_for_mode(
    mode_id: str,
    places_df: pd.DataFrame,
    edges_df: pd.DataFrame | None,
    start_id: str,
    end_id: str,
    *,
    allow_live_osrm: bool,
    forced_rules_path: str | Path,
    route_cache_path: str | Path,
    osrm_profile: str = "foot",
    ignore_osrm_cache: bool = False,
    osrm_route_for_places_func: Callable[..., dict[str, Any]] | None = None,
    campus_route_func: Callable[..., dict[str, Any]] | None = None,
    rain_route_func: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Dispatch to completely separate OSRM and campus route pipelines."""
    osrm_route_for_places_func = (
        get_osrm_route_for_places
        if osrm_route_for_places_func is None
        else osrm_route_for_places_func
    )
    campus_route_func = get_campus_route if campus_route_func is None else campus_route_func
    rain_route_func = get_rain_route if rain_route_func is None else rain_route_func

    osrm_profile = "foot"
    print("[Route Mode]", mode_id)

    if mode_id == OSRM_MODE_ID:
        print("[Using OSRM only]")
        return osrm_route_for_places_func(
            places_df,
            start_id,
            end_id,
            allow_live_osrm=allow_live_osrm,
            route_cache_path=route_cache_path,
            osrm_profile=osrm_profile,
            ignore_osrm_cache=ignore_osrm_cache,
        )

    if mode_id == CAMPUS_MODE_ID:
        return campus_route_func(
            places_df,
            edges_df,
            start_id,
            end_id,
            allow_live_osrm=allow_live_osrm,
            forced_rules_path=forced_rules_path,
            route_cache_path=route_cache_path,
            osrm_profile=osrm_profile,
            ignore_osrm_cache=ignore_osrm_cache,
        )

    if mode_id == RAIN_MODE_ID:
        return rain_route_func(
            places_df,
            edges_df,
            start_id,
            end_id,
            allow_live_osrm=allow_live_osrm,
            forced_rules_path=forced_rules_path,
            route_cache_path=route_cache_path,
            osrm_profile=osrm_profile,
            ignore_osrm_cache=ignore_osrm_cache,
        )

    if mode_id == COMPARE_MODE_ID:
        print("[Compare Mode] calculating OSRM route")
        try:
            osrm_route = osrm_route_for_places_func(
                places_df,
                start_id,
                end_id,
                allow_live_osrm=allow_live_osrm,
                route_cache_path=route_cache_path,
                osrm_profile=osrm_profile,
                ignore_osrm_cache=ignore_osrm_cache,
            )
        except Exception as exc:
            osrm_route = route_failure(
                "osrm",
                OSRM_MODE_ID,
                f"OSRM route calculation failed: {type(exc).__name__}: {exc}",
            )

        print("[Compare Mode] calculating Campus route")
        try:
            campus_route = campus_route_func(
                places_df,
                edges_df,
                start_id,
                end_id,
                allow_live_osrm=allow_live_osrm,
                forced_rules_path=forced_rules_path,
                route_cache_path=route_cache_path,
                osrm_profile=osrm_profile,
                ignore_osrm_cache=ignore_osrm_cache,
            )
        except Exception as exc:
            campus_route = route_failure(
                "campus",
                CAMPUS_MODE_ID,
                f"Campus route calculation failed: {type(exc).__name__}: {exc}",
            )

        comparison = build_route_comparison(osrm_route, campus_route)
        print("[Compare Result]", comparison)
        success = bool(osrm_route.get("success") or campus_route.get("success"))
        errors = [
            str(route.get("error"))
            for route in (osrm_route, campus_route)
            if not route.get("success") and route.get("error")
        ]
        return {
            "success": success,
            "mode": COMPARE_MODE_ID,
            "source": "comparison",
            "osrm": osrm_route,
            "campus": campus_route,
            "comparison": comparison,
            "error": None if success else "; ".join(errors) or "Both routes failed.",
        }

    return route_failure("unknown", mode_id, f"Unknown route mode: {mode_id}")
