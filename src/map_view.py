"""Folium map construction helpers."""

from __future__ import annotations

from typing import Any

import folium
import pandas as pd

from .utils import (
    ensure_place_visibility_columns,
    format_distance,
    format_duration,
    get_marker_places,
    is_enabled_flag,
    parse_coordinate,
    place_has_coordinates,
)


NTHU_CENTER_LAT = 24.7959
NTHU_CENTER_LON = 120.9936


def _place_value(place: dict[str, Any] | pd.Series, key: str, default: Any = "") -> Any:
    value = place.get(key, default)
    return default if value is None else value


def create_base_map(
    center_lat: float = NTHU_CENTER_LAT,
    center_lon: float = NTHU_CENTER_LON,
    zoom_start: int = 16,
) -> folium.Map:
    """Create a Folium map centered near the NTHU campus."""
    return folium.Map(
        location=[center_lat, center_lon],
        zoom_start=zoom_start,
        tiles="OpenStreetMap",
        control_scale=True,
    )


def add_place_markers(map_obj: folium.Map, places_df: pd.DataFrame) -> folium.Map:
    """Add regular markers for show_marker=1 places with usable coordinates."""
    group = folium.FeatureGroup(name="Campus places", show=True)
    for _, row in get_marker_places(places_df).iterrows():
        lat = parse_coordinate(row.get("latitude"))
        lon = parse_coordinate(row.get("longitude"))
        if lat is None or lon is None:
            continue

        popup_html = (
            f"<b>{row.get('display_name', row.get('name', 'Unknown'))}</b><br>"
            f"Category: {row.get('category', '')}"
        )
        folium.Marker(
            location=[lat, lon],
            popup=folium.Popup(popup_html, max_width=280),
            tooltip=row.get("display_name", row.get("name", "")),
            icon=folium.Icon(color="blue", icon="info-sign"),
        ).add_to(group)
    group.add_to(map_obj)
    return map_obj


def add_debug_node_markers(map_obj: folium.Map, places_df: pd.DataFrame) -> folium.Map:
    """Add hidden internal graph nodes as compact debug CircleMarkers."""
    group = folium.FeatureGroup(name="Debug internal nodes", show=True)
    places = ensure_place_visibility_columns(places_df)
    hidden_places = places[~places["show_marker"].map(is_enabled_flag)]
    for _, row in hidden_places.iterrows():
        lat = parse_coordinate(row.get("latitude"))
        lon = parse_coordinate(row.get("longitude"))
        if lat is None or lon is None:
            continue

        popup_html = (
            f"<b>{row.get('id', '')}</b><br>"
            f"{row.get('display_name', row.get('name', ''))}<br>"
            f"Category: {row.get('category', '')}<br>"
            f"Latitude: {lat}<br>Longitude: {lon}"
        )
        folium.CircleMarker(
            location=[lat, lon],
            radius=5,
            color="#c2410c",
            weight=2,
            fill=True,
            fill_color="#fb923c",
            fill_opacity=0.8,
            popup=folium.Popup(popup_html, max_width=320),
            tooltip=f"Debug node: {row.get('id', '')}",
        ).add_to(group)
    group.add_to(map_obj)
    return map_obj


def add_start_end_markers(
    map_obj: folium.Map,
    start_place: dict[str, Any] | pd.Series,
    end_place: dict[str, Any] | pd.Series,
) -> folium.Map:
    """Add distinct start and end markers."""
    marker_specs = [
        ("Start", start_place, "green", "play"),
        ("End", end_place, "red", "flag"),
    ]
    for label, place, color, icon in marker_specs:
        if not place_has_coordinates(place):
            continue
        lat = parse_coordinate(place.get("latitude"))
        lon = parse_coordinate(place.get("longitude"))
        name = _place_value(place, "display_name", _place_value(place, "name", ""))
        folium.Marker(
            location=[lat, lon],
            popup=folium.Popup(f"<b>{label}</b><br>{name}", max_width=280),
            tooltip=f"{label}: {name}",
            icon=folium.Icon(color=color, icon=icon),
        ).add_to(map_obj)
    return map_obj


def add_route_polyline(
    map_obj: folium.Map,
    folium_coordinates: list[list[float]],
    tooltip_text: str,
    *,
    color: str = "#2563eb",
    weight: int = 6,
    opacity: float = 0.88,
    dash_array: str | None = None,
    layer_name: str | None = None,
) -> bool:
    """Draw a route polyline. Return False when no coordinates are provided."""
    if not folium_coordinates:
        return False

    target = map_obj
    if layer_name:
        target = folium.FeatureGroup(name=layer_name, show=True)
        target.add_to(map_obj)

    folium.PolyLine(
        locations=folium_coordinates,
        color=color,
        weight=weight,
        opacity=opacity,
        dash_array=dash_array,
        tooltip=tooltip_text,
    ).add_to(target)
    return True


def build_route_map(
    places_df: pd.DataFrame,
    start_place: dict[str, Any] | pd.Series | None = None,
    end_place: dict[str, Any] | pd.Series | None = None,
    route_result: dict[str, Any] | None = None,
    show_debug_nodes: bool = False,
) -> folium.Map:
    """Build a complete map with places, optional route, and start/end markers."""
    center_lat = NTHU_CENTER_LAT
    center_lon = NTHU_CENTER_LON
    route_coordinates = []
    if route_result and route_result.get("mode") == "compare":
        for route_key in ("osrm", "campus"):
            candidate = route_result.get(route_key) or {}
            if candidate.get("success") and candidate.get("folium_coordinates"):
                center_lat, center_lon = candidate["folium_coordinates"][0]
                break
    elif route_result and route_result.get("success"):
        route_coordinates = route_result.get("folium_coordinates", [])
        if route_coordinates:
            center_lat, center_lon = route_coordinates[0]
    elif start_place is not None and place_has_coordinates(start_place):
        center_lat = parse_coordinate(start_place.get("latitude")) or NTHU_CENTER_LAT
        center_lon = parse_coordinate(start_place.get("longitude")) or NTHU_CENTER_LON

    map_obj = create_base_map(center_lat, center_lon)
    add_place_markers(map_obj, places_df)
    if show_debug_nodes:
        add_debug_node_markers(map_obj, places_df)

    if start_place is not None and end_place is not None:
        add_start_end_markers(map_obj, start_place, end_place)

    if route_result and route_result.get("mode") == "compare":
        osrm_route = route_result.get("osrm") or {}
        campus_route = route_result.get("campus") or {}
        if osrm_route.get("success"):
            add_route_polyline(
                map_obj,
                osrm_route.get("folium_coordinates", []),
                (
                    f"OSRM route; Distance: {format_distance(osrm_route.get('distance_m'))}; "
                    f"Time: {format_duration(osrm_route.get('duration_s'))}"
                ),
                color="#2563eb",
                weight=8,
                opacity=0.65,
                layer_name="OSRM route",
            )
        if campus_route.get("success"):
            add_route_polyline(
                map_obj,
                campus_route.get("folium_coordinates", []),
                (
                    f"Campus route; Distance: {format_distance(campus_route.get('distance_m'))}; "
                    f"Time: {format_duration(campus_route.get('duration_s'))}"
                ),
                color="#ea580c",
                weight=6,
                opacity=0.95,
                dash_array="10 8",
                layer_name="Campus route",
            )
    elif route_result and route_result.get("success"):
        tooltip = (
            f"Distance: {format_distance(route_result.get('distance_m'))}; "
            f"Walking time: {format_duration(route_result.get('duration_s'))}"
        )
        add_route_polyline(map_obj, route_coordinates, tooltip)

    folium.LayerControl(collapsed=True).add_to(map_obj)
    return map_obj
