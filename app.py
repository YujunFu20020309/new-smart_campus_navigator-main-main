from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from src.campus_graph import build_campus_graph, compute_campus_route, load_edges
from src.data_admin import (
    EDGE_COLUMNS,
    PENDING_PLACE_CATEGORY_OPTIONS,
    append_edge,
    append_pending_place,
    append_place,
    sanitize_place_id,
    save_edges,
    save_places,
)
from src.geocoding import DEFAULT_USER_AGENT, update_missing_coordinates
from src.forced_routes import (
    add_forced_route_rule,
    delete_forced_route_rule,
    load_forced_route_rules,
    match_forced_route_rule,
    route_with_forced_rule,
    save_forced_route_rules,
    update_forced_route_rule,
)
from src.geo_utils import (
    haversine_distance_m,
    parse_geometry_points_text,
    polyline_distance_m,
)
from src.map_view import build_route_map
from src.route_modes import (
    CAMPUS_MODE_ID,
    COMPARE_MODE_ID,
    OSRM_MODE_ID,
    RAIN_MODE_ID,
    get_available_modes,
)
from src.route_service import (
    _forced_rule_uses_manual_segments as _route_forced_rule_uses_manual_segments,
    _numeric_difference as _route_numeric_difference,
    build_route_comparison as _build_route_comparison,
    calculate_route_for_mode as _calculate_route_for_mode,
    get_campus_route as _get_campus_route,
    get_campus_route_features as _get_campus_route_features,
    get_osrm_route_for_places as _get_osrm_route_for_places,
    get_rain_route as _get_rain_route,
    route_failure as _route_failure,
)
from src.routing_osrm import get_osrm_route
from src.utils import (
    format_distance,
    format_duration,
    get_destination_places,
    get_place_by_id,
    load_places,
    parse_coordinate,
    place_has_coordinates,
    validate_coordinate_bounds,
)
from tools.fill_edge_geometry_osrm import fetch_osrm_edge_route


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
PLACES_CSV = DATA_DIR / "places.csv"
EDGES_CSV = DATA_DIR / "campus_edges.csv"
ROUTE_CACHE_PATH = DATA_DIR / "route_cache.json"
GEOCODE_CACHE_PATH = DATA_DIR / "geocode_cache.json"
FORCED_RULES_PATH = DATA_DIR / "forced_route_rules.json"
MANUAL_PLACES_PENDING_CSV = DATA_DIR / "manual_places_pending.csv"
ROUTE_RESULT_VERSION = 2


@st.cache_data(show_spinner=False)
def load_places_cached(csv_path: str) -> pd.DataFrame:
    return load_places(csv_path)


@st.cache_data(show_spinner=False)
def load_edges_cached(csv_path: str) -> pd.DataFrame:
    return load_edges(csv_path)


def load_campus_edges_for_mode(
    mode_id: str,
    csv_path: str | Path = EDGES_CSV,
) -> tuple[pd.DataFrame | None, str | None]:
    """Load campus edges only when a mode may need campus edge data."""
    if mode_id not in {CAMPUS_MODE_ID, COMPARE_MODE_ID, RAIN_MODE_ID}:
        return None, None

    try:
        return load_edges_cached(str(csv_path)), None
    except Exception as exc:
        return None, str(exc)


def place_label_map(places_df: pd.DataFrame) -> dict[str, str]:
    return {
        row["id"]: row.get("display_name") or row.get("name") or row["id"]
        for _, row in places_df.iterrows()
    }


def route_matches_selection(
    route_state: dict[str, Any] | None,
    start_id: str,
    end_id: str,
    mode_id: str,
) -> bool:
    return (
        isinstance(route_state, dict)
        and route_state.get("start_id") == start_id
        and route_state.get("end_id") == end_id
        and route_state.get("mode_id") == mode_id
        and route_state.get("route_result_version") == ROUTE_RESULT_VERSION
    )


route_failure = _route_failure
get_campus_route_features = _get_campus_route_features
_numeric_difference = _route_numeric_difference
build_route_comparison = _build_route_comparison
_forced_rule_uses_manual_segments = _route_forced_rule_uses_manual_segments


def get_osrm_route_for_places(
    places_df: pd.DataFrame,
    start_id: str,
    end_id: str,
    *,
    allow_live_osrm: bool,
    route_cache_path: str | Path,
    osrm_profile: str = "foot",
    ignore_osrm_cache: bool = False,
) -> dict[str, Any]:
    return _get_osrm_route_for_places(
        places_df,
        start_id,
        end_id,
        allow_live_osrm=allow_live_osrm,
        route_cache_path=route_cache_path,
        osrm_profile=osrm_profile,
        ignore_osrm_cache=ignore_osrm_cache,
        osrm_router=get_osrm_route,
    )


def get_campus_route(
    places_df: pd.DataFrame,
    edges_df: pd.DataFrame | None,
    start_id: str,
    end_id: str,
    *,
    allow_live_osrm: bool,
    route_cache_path: str | Path,
    osrm_profile: str = "foot",
    ignore_osrm_cache: bool = False,
    forced_rules_path: str | Path = FORCED_RULES_PATH,
) -> dict[str, Any]:
    return _get_campus_route(
        places_df,
        edges_df,
        start_id,
        end_id,
        allow_live_osrm=allow_live_osrm,
        forced_rules_path=forced_rules_path,
        route_cache_path=route_cache_path,
        osrm_profile=osrm_profile,
        ignore_osrm_cache=ignore_osrm_cache,
        match_rule_func=match_forced_route_rule,
        forced_route_func=route_with_forced_rule,
        campus_graph_builder=build_campus_graph,
        campus_route_computer=compute_campus_route,
        osrm_router=get_osrm_route,
    )


def get_rain_route(
    places_df: pd.DataFrame,
    edges_df: pd.DataFrame | None,
    start_id: str,
    end_id: str,
    *,
    allow_live_osrm: bool,
    route_cache_path: str | Path,
    osrm_profile: str = "foot",
    ignore_osrm_cache: bool = False,
    forced_rules_path: str | Path = FORCED_RULES_PATH,
) -> dict[str, Any]:
    return _get_rain_route(
        places_df,
        edges_df,
        start_id,
        end_id,
        allow_live_osrm=allow_live_osrm,
        forced_rules_path=forced_rules_path,
        route_cache_path=route_cache_path,
        osrm_profile=osrm_profile,
        ignore_osrm_cache=ignore_osrm_cache,
        match_rule_func=match_forced_route_rule,
        forced_route_func=route_with_forced_rule,
        osrm_route_for_places_func=get_osrm_route_for_places,
        osrm_router=get_osrm_route,
    )


def calculate_route_for_mode(
    mode_id: str,
    places_df: pd.DataFrame,
    edges_df: pd.DataFrame | None,
    start_id: str,
    end_id: str,
    *,
    allow_live_osrm: bool,
    route_cache_path: str | Path,
    osrm_profile: str = "foot",
    ignore_osrm_cache: bool = False,
    forced_rules_path: str | Path = FORCED_RULES_PATH,
) -> dict[str, Any]:
    return _calculate_route_for_mode(
        mode_id,
        places_df,
        edges_df,
        start_id,
        end_id,
        allow_live_osrm=allow_live_osrm,
        forced_rules_path=forced_rules_path,
        route_cache_path=route_cache_path,
        osrm_profile=osrm_profile,
        ignore_osrm_cache=ignore_osrm_cache,
        osrm_route_for_places_func=get_osrm_route_for_places,
        campus_route_func=get_campus_route,
        rain_route_func=get_rain_route,
    )


def render_compare_route_info(compare_result: dict[str, Any]) -> None:
    """Render independently calculated OSRM and campus route comparison cards."""
    osrm_route = compare_result.get("osrm") or {}
    campus_route = compare_result.get("campus") or {}
    comparison = compare_result.get("comparison") or {}

    st.markdown("#### OSRM 路線")
    if osrm_route.get("success"):
        st.write(f"- 距離：{format_distance(osrm_route.get('distance_m'))}")
        st.write(f"- 時間：{format_duration(osrm_route.get('duration_s'))}")
        st.write("- 來源：OSRM")
    else:
        st.warning(f"OSRM 路線無法生成：{osrm_route.get('error', '未知錯誤')}")

    st.markdown("#### 校園路線")
    if campus_route.get("success"):
        campus_source_labels = {
            "local_graph": "campus_edges + Dijkstra",
            "hybrid_forced_route": "校園特殊規則",
            "osrm_fallback": "Campus 內部 OSRM fallback",
        }
        st.write(f"- 距離：{format_distance(campus_route.get('distance_m'))}")
        st.write(f"- 時間：{format_duration(campus_route.get('duration_s'))}")
        st.write(
            f"- 來源："
            f"{campus_source_labels.get(campus_route.get('source'), campus_route.get('source', 'campus'))}"
        )
        features = comparison.get("route_features") or []
        st.write(f"- 使用特殊路段：{' / '.join(features) if features else '無'}")
    else:
        st.warning(f"Campus 路線無法生成：{campus_route.get('error', '未知錯誤')}")

    st.markdown("#### 比較")
    st.write(comparison.get("readable_summary") or "尚無可用比較結果。")
    distance_difference = (comparison.get("distance_m") or {}).get("campus_minus_osrm")
    duration_difference = (comparison.get("duration_s") or {}).get("campus_minus_osrm")
    if distance_difference is not None:
        st.write(f"- Campus - OSRM 距離差：{distance_difference:+.0f} 公尺")
    if duration_difference is not None:
        st.write(f"- Campus - OSRM 時間差：{duration_difference:+.0f} 秒")


def data_quality_lists(places_df: pd.DataFrame, labels: dict[str, str]) -> tuple[list[str], list[str]]:
    missing_coordinates: list[str] = []
    out_of_bounds: list[str] = []
    for _, row in places_df.iterrows():
        label = labels.get(row["id"], row["id"])
        if not place_has_coordinates(row):
            missing_coordinates.append(label)
        elif not validate_coordinate_bounds(row):
            out_of_bounds.append(label)
    return missing_coordinates, out_of_bounds


PENDING_PLACE_FORM_KEYS = [
    "pending_place_id",
    "pending_place_name",
    "pending_place_display_name",
    "pending_place_category",
    "pending_place_type",
    "pending_place_is_destination",
    "pending_place_show_marker",
    "pending_place_notes",
    "pending_place_manual_latitude",
    "pending_place_manual_longitude",
    "pending_place_use_manual_coordinates",
]


def _last_clicked_location(map_data: dict[str, Any] | None) -> dict[str, float] | None:
    if not isinstance(map_data, dict):
        return None
    clicked = map_data.get("last_clicked") or map_data.get("last_object_clicked")
    if not isinstance(clicked, dict):
        return None
    latitude = parse_coordinate(clicked.get("lat") or clicked.get("latitude"))
    longitude = parse_coordinate(
        clicked.get("lng") or clicked.get("lon") or clicked.get("longitude")
    )
    if latitude is None or longitude is None:
        return None
    return {"latitude": latitude, "longitude": longitude}


def _clear_pending_place_form_state() -> None:
    for key in PENDING_PLACE_FORM_KEYS:
        st.session_state.pop(key, None)
    st.session_state.pop("pending_clicked_location", None)


def render_pending_place_review_form(places_df: pd.DataFrame) -> None:
    """Render the map-click pending-place form without writing places.csv."""
    success_message = st.session_state.pop("pending_place_success", None)
    if success_message:
        st.success(success_message)
        st.info("這只是 pending 待審核資料，尚未加入正式 places.csv。")

    st.markdown("### 新增地點模式")
    location = st.session_state.get("pending_clicked_location")
    if not location:
        st.info("請先在地圖上點選新增地點的位置。")
        return

    clicked_latitude = float(location["latitude"])
    clicked_longitude = float(location["longitude"])
    st.write(f"latitude：{clicked_latitude:.6f}")
    st.write(f"longitude：{clicked_longitude:.6f}")

    with st.form("pending_place_review_form"):
        place_id = st.text_input("id", key="pending_place_id")
        name = st.text_input("name", key="pending_place_name")
        display_name = st.text_input("display_name", key="pending_place_display_name")
        category = st.selectbox(
            "category",
            PENDING_PLACE_CATEGORY_OPTIONS,
            key="pending_place_category",
        )
        place_type = st.text_input("type", key="pending_place_type")
        is_destination = st.checkbox(
            "is_destination",
            value=True,
            key="pending_place_is_destination",
        )
        show_marker = st.checkbox(
            "show_marker",
            value=True,
            key="pending_place_show_marker",
        )
        st.text_input(
            "notes",
            value="pending_review",
            disabled=True,
            key="pending_place_notes",
        )
        use_manual_coordinates = st.checkbox(
            "進階手動修正座標",
            value=False,
            key="pending_place_use_manual_coordinates",
        )
        latitude = clicked_latitude
        longitude = clicked_longitude
        if use_manual_coordinates:
            latitude = st.number_input(
                "latitude",
                value=clicked_latitude,
                format="%.6f",
                key="pending_place_manual_latitude",
            )
            longitude = st.number_input(
                "longitude",
                value=clicked_longitude,
                format="%.6f",
                key="pending_place_manual_longitude",
            )
        else:
            st.caption("latitude / longitude 會使用剛剛地圖點選的位置。")

        submitted = st.form_submit_button("加入待審核地點", use_container_width=True)

    if submitted:
        try:
            append_pending_place(
                MANUAL_PLACES_PENDING_CSV,
                places_df,
                {
                    "id": place_id,
                    "name": name,
                    "display_name": display_name,
                    "category": category,
                    "latitude": latitude,
                    "longitude": longitude,
                    "is_destination": is_destination,
                    "show_marker": show_marker,
                    "type": place_type,
                },
            )
            _clear_pending_place_form_state()
            load_places_cached.clear()
            load_edges_cached.clear()
            st.session_state.pop("route_state", None)
            st.session_state["pending_place_success"] = (
                f"已加入待審核地點：{sanitize_place_id(place_id)}"
            )
            st.rerun()
        except Exception as exc:
            st.error(f"加入待審核地點失敗：{type(exc).__name__}: {exc}")


def coordinate_delta(point: list[float], place: dict[str, Any]) -> str:
    """Return a compact delta between a route point and a place coordinate."""
    lat = parse_coordinate(place.get("latitude"))
    lon = parse_coordinate(place.get("longitude"))
    if lat is None or lon is None or len(point) < 2:
        return "N/A"
    return f"lat Δ={abs(point[0] - lat):.6f}, lon Δ={abs(point[1] - lon):.6f}"


def prepare_edge_draft(
    places_df: pd.DataFrame,
    from_id: str,
    to_id: str,
    geometry_points_text: str,
    *,
    auto_include_endpoints: bool,
    auto_calculate_distance: bool,
    manual_distance_m: float,
) -> tuple[list[list[float]], float]:
    """Prepare friendly geometry input and a preview/save distance for one edge."""
    user_points = parse_geometry_points_text(geometry_points_text)
    from_place = get_place_by_id(places_df, from_id)
    to_place = get_place_by_id(places_df, to_id)
    from_coordinate = [
        parse_coordinate(from_place.get("longitude")),
        parse_coordinate(from_place.get("latitude")),
    ]
    to_coordinate = [
        parse_coordinate(to_place.get("longitude")),
        parse_coordinate(to_place.get("latitude")),
    ]
    if None in (*from_coordinate, *to_coordinate):
        raise ValueError("起點或終點缺少有效座標，無法自動計算距離。")

    geometry_points = user_points
    if user_points and auto_include_endpoints:
        geometry_points = [from_coordinate, *user_points, to_coordinate]

    if auto_calculate_distance:
        distance_m = (
            polyline_distance_m(geometry_points)
            if geometry_points
            else haversine_distance_m(*from_coordinate, *to_coordinate)
        )
    else:
        distance_m = float(manual_distance_m)
    return geometry_points, distance_m


def _segments_from_editor(segments_df: pd.DataFrame) -> list[dict[str, str]]:
    """Normalize and order editable forced-route segment rows."""
    if segments_df is None or segments_df.empty:
        return []
    frame = segments_df.copy().fillna("")
    if "order" not in frame.columns:
        frame["order"] = range(1, len(frame) + 1)
    frame["_order"] = pd.to_numeric(frame["order"], errors="coerce").fillna(999999)
    frame = frame.sort_values("_order", kind="stable")
    segments: list[dict[str, str]] = []
    for _, row in frame.iterrows():
        segment_type = str(row.get("type", "")).strip().lower()
        from_id = str(row.get("from", "")).strip()
        to_id = str(row.get("to", "")).strip()
        if not segment_type and not from_id and not to_id:
            continue
        if segment_type not in {"osrm", "manual", "straight"}:
            raise ValueError("Segment type 必須是 osrm、manual 或 straight。")
        if not from_id or not to_id:
            raise ValueError("每個 segment 都必須選擇 from 與 to。")
        segments.append({"type": segment_type, "from": from_id, "to": to_id})
    if not segments:
        raise ValueError("規則至少需要一個 segment。")
    return segments


def _segments_frame(rule: dict[str, Any] | None = None) -> pd.DataFrame:
    segments = (rule or {}).get("forward_segments", [])
    return pd.DataFrame(
        [
            {
                "order": index,
                "type": segment.get("type", ""),
                "from": segment.get("from", ""),
                "to": segment.get("to", ""),
            }
            for index, segment in enumerate(segments, start=1)
        ],
        columns=["order", "type", "from", "to"],
    )


FORCED_RULE_MODE_OPTIONS = {
    "全部模式": None,
    "校園路線": [CAMPUS_MODE_ID],
    "雨天路線": [RAIN_MODE_ID],
}


def _forced_rule_modes_selection(rule: dict[str, Any]) -> str:
    raw_modes = rule.get("modes", [])
    if isinstance(raw_modes, str):
        modes = [raw_modes]
    else:
        modes = [str(mode) for mode in raw_modes]
    for label, mode_ids in FORCED_RULE_MODE_OPTIONS.items():
        if mode_ids == modes:
            return label
    return "全部模式"


def _apply_forced_rule_modes(
    payload: dict[str, Any],
    mode_selection: str,
) -> dict[str, Any]:
    mode_ids = FORCED_RULE_MODE_OPTIONS.get(mode_selection)
    if mode_ids is None:
        payload.pop("modes", None)
    else:
        payload["modes"] = mode_ids
    return payload


def _forced_rule_modes_label(rule: dict[str, Any]) -> str:
    mode_labels = {
        CAMPUS_MODE_ID: "校園路線",
        RAIN_MODE_ID: "雨天路線",
    }
    raw_modes = rule.get("modes", [])
    if isinstance(raw_modes, str):
        raw_modes = [raw_modes]
    return "、".join(
        mode_labels.get(str(mode), str(mode))
        for mode in raw_modes
    )


def render_forced_route_rules_sidebar(places_df: pd.DataFrame) -> None:
    """Render persistent Python/JSON forced-route rule management controls."""
    all_place_ids = places_df["id"].astype(str).tolist()
    endpoint_options = ["start", "end", *all_place_ids]
    segment_columns = {
        "order": st.column_config.NumberColumn("順序", min_value=1, step=1),
        "type": st.column_config.SelectboxColumn(
            "type",
            options=["osrm", "manual", "straight"],
            required=True,
        ),
        "from": st.column_config.SelectboxColumn(
            "from",
            options=endpoint_options,
            required=True,
        ),
        "to": st.column_config.SelectboxColumn(
            "to",
            options=endpoint_options,
            required=True,
        ),
    }

    with st.expander("強制路線規則 / 自創道路"):
        try:
            rules = load_forced_route_rules(FORCED_RULES_PATH)
        except Exception as exc:
            st.error(f"讀取規則失敗：{type(exc).__name__}: {exc}")
            rules = []

        view_tab, add_tab, edit_tab, transfer_tab = st.tabs(
            ["查看", "新增", "編輯/刪除", "匯入/匯出"]
        )

        with view_tab:
            if not rules:
                st.info("目前沒有強制路線規則。")
            for rule in rules:
                st.markdown(
                    f"**{rule.get('name', rule.get('id'))}** "
                    f"({'啟用' if rule.get('enabled') else '停用'})"
                )
                st.caption(
                    f"id={rule.get('id')}｜雙向={bool(rule.get('bidirectional'))}｜"
                    f"segments={len(rule.get('forward_segments', []))}"
                )
                if rule.get("modes"):
                    st.caption(f"適用模式：{_forced_rule_modes_label(rule)}")

        with add_tab:
            with st.form("forced_rule_add_form"):
                rule_id = st.text_input("規則 ID")
                rule_name = st.text_input("規則名稱")
                enabled = st.checkbox("啟用規則", value=True)
                bidirectional = st.checkbox("雙向規則", value=True)
                mode_selection = st.selectbox(
                    "適用模式",
                    options=list(FORCED_RULE_MODE_OPTIONS.keys()),
                    index=0,
                )
                from_ids = st.multiselect("from_place_ids", all_place_ids)
                to_ids = st.multiselect("to_place_ids", all_place_ids)
                new_segments = st.data_editor(
                    pd.DataFrame(
                        [
                            {"order": 1, "type": "osrm", "from": "start", "to": "end"}
                        ]
                    ),
                    column_config=segment_columns,
                    num_rows="dynamic",
                    hide_index=True,
                    key="forced_rule_add_segments",
                    use_container_width=True,
                )
                add_submitted = st.form_submit_button("新增規則", use_container_width=True)
            if add_submitted:
                try:
                    payload = _apply_forced_rule_modes(
                        {
                            "id": sanitize_place_id(rule_id),
                            "name": rule_name,
                            "enabled": enabled,
                            "bidirectional": bidirectional,
                            "from_place_ids": from_ids,
                            "to_place_ids": to_ids,
                            "forward_segments": _segments_from_editor(new_segments),
                        },
                        mode_selection,
                    )
                    add_forced_route_rule(
                        payload,
                        FORCED_RULES_PATH,
                    )
                    st.session_state.pop("route_state", None)
                    st.success("強制路線規則已新增。")
                    st.rerun()
                except Exception as exc:
                    st.error(f"新增規則失敗：{type(exc).__name__}: {exc}")

        with edit_tab:
            if rules:
                selected_rule_id = st.selectbox(
                    "選擇規則",
                    [str(rule.get("id")) for rule in rules],
                    format_func=lambda rule_id: next(
                        (
                            str(rule.get("name") or rule_id)
                            for rule in rules
                            if rule.get("id") == rule_id
                        ),
                        rule_id,
                    ),
                )
                selected_rule = next(
                    rule for rule in rules if rule.get("id") == selected_rule_id
                )
                with st.form("forced_rule_edit_form"):
                    edit_name = st.text_input(
                        "規則名稱",
                        value=str(selected_rule.get("name", "")),
                    )
                    edit_enabled = st.checkbox(
                        "啟用規則",
                        value=bool(selected_rule.get("enabled")),
                    )
                    edit_bidirectional = st.checkbox(
                        "雙向規則",
                        value=bool(selected_rule.get("bidirectional")),
                    )
                    edit_mode_selection = st.selectbox(
                        "適用模式",
                        options=list(FORCED_RULE_MODE_OPTIONS.keys()),
                        index=list(FORCED_RULE_MODE_OPTIONS.keys()).index(
                            _forced_rule_modes_selection(selected_rule)
                        ),
                    )
                    edit_from_ids = st.multiselect(
                        "from_place_ids",
                        all_place_ids,
                        default=[
                            item
                            for item in selected_rule.get("from_place_ids", [])
                            if item in all_place_ids
                        ],
                    )
                    edit_to_ids = st.multiselect(
                        "to_place_ids",
                        all_place_ids,
                        default=[
                            item
                            for item in selected_rule.get("to_place_ids", [])
                            if item in all_place_ids
                        ],
                    )
                    edited_segments = st.data_editor(
                        _segments_frame(selected_rule),
                        column_config=segment_columns,
                        num_rows="dynamic",
                        hide_index=True,
                        key=f"forced_rule_edit_segments_{selected_rule_id}",
                        use_container_width=True,
                    )
                    save_submitted = st.form_submit_button(
                        "儲存規則",
                        use_container_width=True,
                    )
                if save_submitted:
                    try:
                        payload = _apply_forced_rule_modes(
                            {
                                **selected_rule,
                                "name": edit_name,
                                "enabled": edit_enabled,
                                "bidirectional": edit_bidirectional,
                                "from_place_ids": edit_from_ids,
                                "to_place_ids": edit_to_ids,
                                "forward_segments": _segments_from_editor(edited_segments),
                            },
                            edit_mode_selection,
                        )
                        update_forced_route_rule(
                            selected_rule_id,
                            payload,
                            FORCED_RULES_PATH,
                        )
                        st.session_state.pop("route_state", None)
                        st.success("強制路線規則已儲存。")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"儲存規則失敗：{type(exc).__name__}: {exc}")
                if st.button("刪除選取規則", type="secondary", use_container_width=True):
                    delete_forced_route_rule(selected_rule_id, FORCED_RULES_PATH)
                    st.session_state.pop("route_state", None)
                    st.rerun()

        with transfer_tab:
            export_payload = json.dumps(
                {"rules": rules},
                ensure_ascii=False,
                indent=2,
            )
            st.download_button(
                "匯出 forced_route_rules.json",
                data=export_payload,
                file_name="forced_route_rules.json",
                mime="application/json",
                use_container_width=True,
            )
            uploaded = st.file_uploader("匯入 forced_route_rules.json", type=["json"])
            if st.button("套用匯入規則", use_container_width=True):
                if uploaded is None:
                    st.error("請先選擇 JSON 檔案。")
                else:
                    try:
                        payload = json.loads(uploaded.getvalue().decode("utf-8-sig"))
                        save_forced_route_rules(payload, FORCED_RULES_PATH)
                        st.session_state.pop("route_state", None)
                        st.success("規則已匯入。")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"匯入規則失敗：{type(exc).__name__}: {exc}")


def _finish_admin_write(message: str, *, clear_places: bool, clear_edges: bool) -> None:
    if clear_places:
        load_places_cached.clear()
    if clear_edges:
        load_edges_cached.clear()
    st.session_state.pop("route_state", None)
    st.session_state["data_admin_success"] = message
    st.rerun()


def render_data_admin_sidebar(
    places_df: pd.DataFrame,
    edges_df: pd.DataFrame | None,
) -> None:
    """Render persistent places/edges editing controls in the current sidebar."""
    with st.expander("資料維護 / 新增地點與路網"):
        success_message = st.session_state.pop("data_admin_success", None)
        if success_message:
            st.success(success_message)

        place_tab, edge_tab, edit_tab = st.tabs(["新增地點", "新增路段", "編輯表格"])

        with place_tab:
            with st.form("data_admin_add_place"):
                place_id_input = st.text_input("id", help="留空時會由英文 name 自動產生。")
                name = st.text_input("name")
                display_name = st.text_input("display_name")
                category = st.selectbox(
                    "category",
                    ["building", "gate", "landmark", "intersection", "road_node", "waypoint"],
                )
                latitude = st.text_input("latitude")
                longitude = st.text_input("longitude")
                is_destination = st.checkbox("is_destination", value=True)
                show_marker = st.checkbox("show_marker", value=True)
                notes = st.text_input("notes", value="manual_added")
                add_place_submitted = st.form_submit_button("新增地點", use_container_width=True)

            if add_place_submitted:
                try:
                    place_id = sanitize_place_id(place_id_input or name)
                    append_place(
                        PLACES_CSV,
                        {
                            "id": place_id,
                            "name": name,
                            "display_name": display_name,
                            "category": category,
                            "latitude": latitude,
                            "longitude": longitude,
                            "source": "manual",
                            "notes": notes,
                            "is_destination": is_destination,
                            "show_marker": show_marker,
                        },
                    )
                    _finish_admin_write(
                        f"已新增地點：{place_id}",
                        clear_places=True,
                        clear_edges=False,
                    )
                except Exception as exc:
                    st.error(f"新增地點失敗：{type(exc).__name__}: {exc}")

        with edge_tab:
            all_place_ids = places_df["id"].astype(str).tolist()
            with st.form("data_admin_add_edge"):
                from_id = st.selectbox("from_id", all_place_ids, key="admin_edge_from")
                to_id = st.selectbox(
                    "to_id",
                    all_place_ids,
                    index=1 if len(all_place_ids) > 1 else 0,
                    key="admin_edge_to",
                )
                auto_calculate_distance = st.checkbox("自動計算距離", value=True)
                manual_distance_m = 0.0
                if not auto_calculate_distance:
                    manual_distance_m = st.number_input(
                        "distance_m",
                        min_value=0.0,
                        value=0.0,
                    )
                stairs = st.checkbox("stairs")
                rain_friendly = st.checkbox("rain_friendly", value=True)
                road_name = st.text_input("road_name")
                description = st.text_input("description")
                routing_source = st.selectbox(
                    "routing_source",
                    ["manual", "osrm", "estimated"],
                    index=0,
                )
                verified = st.checkbox("人工確認可走", value=False)
                ignore_osrm = st.checkbox("無視 OSRM", value=False)
                enabled = st.checkbox("啟用", value=True)
                geometry_points_text = st.text_area(
                    "geometry_points_text",
                    help=(
                        "可空白；若要讓此路段線條彎曲，請每行輸入一個座標，"
                        "格式為 longitude,latitude。"
                    ),
                    placeholder=(
                        "120.9966,24.7964\n"
                        "120.9957,24.7962\n"
                        "120.9950,24.7959"
                    ),
                )
                auto_include_endpoints = st.checkbox("自動包含 from/to 座標", value=True)
                auto_fill_geometry = st.checkbox(
                    "使用 OSRM 補此 edge geometry",
                    help="只補這一條既有 edge，不會新增節點或其他 edge。",
                )

                draft_geometry: list[list[float]] = []
                draft_distance = 0.0
                try:
                    draft_geometry, draft_distance = prepare_edge_draft(
                        places_df,
                        from_id,
                        to_id,
                        geometry_points_text,
                        auto_include_endpoints=auto_include_endpoints,
                        auto_calculate_distance=auto_calculate_distance,
                        manual_distance_m=manual_distance_m,
                    )
                    st.caption(
                        f"Preview：{from_id} → {to_id}｜"
                        f"距離 {draft_distance:.1f} m｜"
                        f"geometry 點數 {len(draft_geometry)}｜"
                        f"長直線 edge：{'是' if draft_distance > 30 and not draft_geometry else '否'}"
                    )
                    if draft_distance > 30 and not draft_geometry:
                        st.warning(
                            "此 edge 較長，若 geometry 空白可能畫成直線，"
                            "建議新增更多 hidden nodes 或填入 geometry。"
                        )
                except Exception as exc:
                    st.error(f"路段預覽失敗：{exc}")
                add_edge_submitted = st.form_submit_button("新增路段", use_container_width=True)

            if add_edge_submitted:
                if from_id == to_id:
                    st.error("新增路段失敗：from_id 與 to_id 不可相同。")
                else:
                    try:
                        geometry_points, distance_m = prepare_edge_draft(
                            places_df,
                            from_id,
                            to_id,
                            geometry_points_text,
                            auto_include_endpoints=auto_include_endpoints,
                            auto_calculate_distance=auto_calculate_distance,
                            manual_distance_m=manual_distance_m,
                        )
                        edge_payload = {
                            "from_id": from_id,
                            "to_id": to_id,
                            "distance_m": distance_m,
                            "stairs": stairs,
                            "rain_friendly": rain_friendly,
                            "road_name": road_name,
                            "description": description,
                            "routing_source": routing_source,
                            "verified": verified,
                            "ignore_osrm": ignore_osrm,
                            "enabled": enabled,
                            "geometry": (
                                json.dumps(geometry_points, ensure_ascii=False, separators=(",", ":"))
                                if geometry_points
                                else ""
                            ),
                        }
                        if auto_fill_geometry and not ignore_osrm:
                            from_place = get_place_by_id(places_df, from_id)
                            to_place = get_place_by_id(places_df, to_id)
                            if not place_has_coordinates(from_place) or not place_has_coordinates(to_place):
                                raise ValueError("OSRM 自動補線需要起終點都有有效座標。")
                            route_geometry, route_distance = fetch_osrm_edge_route(
                                parse_coordinate(from_place["latitude"]),
                                parse_coordinate(from_place["longitude"]),
                                parse_coordinate(to_place["latitude"]),
                                parse_coordinate(to_place["longitude"]),
                            )
                            edge_payload["geometry"] = json.dumps(
                                route_geometry,
                                ensure_ascii=False,
                                separators=(",", ":"),
                            )
                            edge_payload["distance_m"] = route_distance
                            edge_payload["routing_source"] = "osrm"

                        append_edge(EDGES_CSV, places_df, edge_payload)
                        suffix = "；已依 ignore_osrm 略過自動補線" if auto_fill_geometry and ignore_osrm else ""
                        _finish_admin_write(
                            f"已新增路段：{from_id} → {to_id}{suffix}",
                            clear_places=False,
                            clear_edges=True,
                        )
                    except Exception as exc:
                        if auto_fill_geometry:
                            st.error(
                                "OSRM 自動補 geometry 或新增路段失敗："
                                f"{type(exc).__name__}: {exc}。"
                                "可取消 auto_fill_geometry 後改用手動 geometry。"
                            )
                        else:
                            st.error(f"新增路段失敗：{type(exc).__name__}: {exc}")

        with edit_tab:
            with st.container(border=True):
                st.markdown("**編輯 places.csv**")
                edited_places = st.data_editor(
                    places_df,
                    key="data_admin_places_editor",
                    hide_index=True,
                    num_rows="dynamic",
                    use_container_width=True,
                )
                if st.button("儲存 places.csv", use_container_width=True):
                    try:
                        save_places(PLACES_CSV, edited_places)
                        _finish_admin_write(
                            "已儲存 places.csv",
                            clear_places=True,
                            clear_edges=False,
                        )
                    except Exception as exc:
                        st.error(f"儲存 places.csv 失敗：{type(exc).__name__}: {exc}")

            with st.container(border=True):
                st.markdown("**編輯 campus_edges.csv**")
                editable_edges = (
                    edges_df if edges_df is not None else pd.DataFrame(columns=EDGE_COLUMNS)
                )
                edited_edges = st.data_editor(
                    editable_edges,
                    key="data_admin_edges_editor",
                    hide_index=True,
                    num_rows="dynamic",
                    use_container_width=True,
                )
                if st.button("儲存 campus_edges.csv", use_container_width=True):
                    try:
                        save_edges(EDGES_CSV, edited_edges)
                        _finish_admin_write(
                            "已儲存 campus_edges.csv",
                            clear_places=False,
                            clear_edges=True,
                        )
                    except Exception as exc:
                        st.error(f"儲存 campus_edges.csv 失敗：{type(exc).__name__}: {exc}")


def main() -> None:
    st.set_page_config(
        page_title="NTHU Smart Campus Navigator",
        page_icon="N",
        layout="wide",
    )

    st.title("NTHU Smart Campus Navigator")
    st.subheader("清大校園智慧導航系統")
    st.caption("Safety MVP plus a simplified local campus road graph for demo routing.")

    try:
        places_df = load_places_cached(str(PLACES_CSV))
    except Exception as exc:
        st.error(f"無法讀取 places.csv：{exc}")
        return

    labels = place_label_map(places_df)
    destination_places_df = get_destination_places(places_df)
    place_ids = destination_places_df["id"].astype(str).tolist()
    if len(place_ids) < 2:
        st.error("places.csv 至少需要兩個 is_destination=1 的地點才能計算路線。")
        return

    missing_coordinates, out_of_bounds = data_quality_lists(places_df, labels)

    with st.sidebar:
        st.markdown("### 專案狀態")
        st.write("目前版本：Safety MVP + Local Graph")
        demo_mode = st.toggle("Demo mode", value=True)
        allow_live_osrm = st.checkbox(
            "OSRM 快取不存在時允許呼叫 OSRM",
            value=not demo_mode,
            help="影響 OSRM 基本路線，以及校園道路路線最後一層 OSRM fallback。",
        )
        osrm_profile = "foot"
        st.caption("OSRM 模式：walking（固定）")
        ignore_osrm_cache = st.checkbox(
            "忽略快取，重新呼叫 OSRM",
            value=False,
            help="勾選後即使 route_cache.json 有舊資料，也會重新呼叫 OSRM，成功後更新快取。",
        )
        add_place_mode = st.toggle(
            "新增地點模式",
            value=False,
            help="在地圖上點選座標後，只會寫入 manual_places_pending.csv 待審核清單。",
        )

        st.divider()
        route_modes = get_available_modes()
        selected_mode = st.selectbox(
            "路線模式",
            options=list(route_modes.keys()),
            index=0,
            format_func=lambda mode_id: route_modes[mode_id]["label"],
        )
        show_debug_nodes = False
        if selected_mode == CAMPUS_MODE_ID:
            show_debug_nodes = st.checkbox("Debug：顯示隱藏路網節點", value=False)

        edges_df, edges_error = load_campus_edges_for_mode(selected_mode)

        st.divider()
        st.markdown("### 地點資料檢查")
        st.write(f"總地點數：{len(places_df)}")
        st.write(f"缺少座標：{len(missing_coordinates)}")
        st.write(f"超出清大範圍：{len(out_of_bounds)}")
        if edges_error:
            st.warning(f"campus_edges.csv 讀取失敗：{edges_error}")

        if missing_coordinates:
            with st.expander("缺座標地點"):
                for name in missing_coordinates:
                    st.write(name)
        if out_of_bounds:
            st.warning("有地點座標超出清大校園範圍，請人工檢查 places.csv。")
            with st.expander("超出範圍地點"):
                for name in out_of_bounds:
                    st.write(name)

        if st.button("補齊缺失座標", type="secondary"):
            if not missing_coordinates:
                st.info("目前 places.csv 沒有缺座標地點，不需要呼叫 Nominatim。")
            else:
                user_agent = os.getenv("NOMINATIM_USER_AGENT", DEFAULT_USER_AGENT)
                with st.spinner("正在使用 Nominatim 補齊缺失座標..."):
                    summary = update_missing_coordinates(
                        PLACES_CSV,
                        GEOCODE_CACHE_PATH,
                        user_agent=user_agent,
                        country_codes="tw",
                    )
                load_places_cached.clear()
                st.success(
                    "座標更新完成："
                    f"updated={summary['updated']}, "
                    f"failed={summary['failed']}, "
                    f"protected_skipped={summary.get('protected_skipped', 0)}, "
                    f"skipped={summary['skipped']}"
                )
                if summary["failures"]:
                    st.warning("部分地點查詢失敗：" + "；".join(summary["failures"]))
                st.rerun()

        st.divider()
        if selected_mode == CAMPUS_MODE_ID:
            render_data_admin_sidebar(places_df, edges_df)
        if selected_mode in {CAMPUS_MODE_ID, RAIN_MODE_ID}:
            render_forced_route_rules_sidebar(places_df)

    controls = st.columns(3)
    with controls[0]:
        start_id = st.selectbox(
            "起點",
            options=place_ids,
            index=0,
            format_func=lambda place_id: labels.get(place_id, place_id),
        )
    with controls[1]:
        default_end_index = place_ids.index("engineering_1") if "engineering_1" in place_ids else 1
        end_id = st.selectbox(
            "終點",
            options=place_ids,
            index=default_end_index,
            format_func=lambda place_id: labels.get(place_id, place_id),
        )
    with controls[2]:
        st.write("")
        st.write("")
        calculate_route = st.button("計算路線", type="primary", use_container_width=True)

    start_place = get_place_by_id(places_df, start_id)
    end_place = get_place_by_id(places_df, end_id)

    if start_id == end_id:
        st.warning("起點與終點相同，請選擇不同地點。")

    if out_of_bounds:
        st.warning("偵測到部分座標超出清大校園範圍，地圖仍可顯示，但建議先人工修正。")

    if calculate_route:
        if start_id == end_id:
            st.warning("起點與終點相同，因此不計算路線。")
        else:
            with st.spinner("正在計算路線..."):
                route_result = calculate_route_for_mode(
                    selected_mode,
                    places_df,
                    edges_df,
                    start_id,
                    end_id,
                    allow_live_osrm=allow_live_osrm,
                    forced_rules_path=FORCED_RULES_PATH,
                    route_cache_path=ROUTE_CACHE_PATH,
                    osrm_profile=osrm_profile,
                    ignore_osrm_cache=ignore_osrm_cache,
                )
            st.session_state["route_state"] = {
                "start_id": start_id,
                "end_id": end_id,
                "mode_id": selected_mode,
                "route_result_version": ROUTE_RESULT_VERSION,
                "result": route_result,
            }

            if route_result["success"]:
                st.success("路線計算完成。")
            elif "route_not_cached_demo_mode" in str(route_result["error"]):
                st.warning(
                    "Demo mode 找不到這組 OSRM 路線快取。若現場網路可用，請勾選"
                    "「OSRM 快取不存在時允許呼叫 OSRM」後重新計算。"
                )
            else:
                st.error(f"路線查詢失敗：{route_result['error']}")

    route_state = st.session_state.get("route_state")
    active_route = None
    if route_matches_selection(route_state, start_id, end_id, selected_mode):
        active_route = route_state.get("result")

    map_obj = build_route_map(
        places_df,
        start_place,
        end_place,
        active_route,
        show_debug_nodes=show_debug_nodes,
    )

    map_col, info_col = st.columns([2.1, 1])
    with map_col:
        map_data = st_folium(
            map_obj,
            width=900,
            height=560,
            returned_objects=(
                ["last_clicked", "last_object_clicked"] if add_place_mode else []
            ),
            key="campus_map_add_place" if add_place_mode else "campus_map_route",
        )

    if add_place_mode:
        clicked_location = _last_clicked_location(map_data)
        if clicked_location is not None:
            st.session_state["pending_clicked_location"] = clicked_location

    with info_col:
        st.markdown("### 路線資訊")
        st.write(f"起點：{labels[start_id]}")
        st.write(f"終點：{labels[end_id]}")
        st.write(f"模式：{route_modes[selected_mode]['label']}")

        if add_place_mode:
            render_pending_place_review_form(places_df)
            st.divider()

        if active_route and active_route.get("mode") == COMPARE_MODE_ID:
            render_compare_route_info(active_route)
        elif active_route and active_route.get("success"):
            st.metric("總距離", format_distance(active_route.get("distance_m")))
            st.metric("步行估計時間", format_duration(active_route.get("duration_s")))
            if active_route.get("source") == "osrm_fallback":
                st.write("資料來源：OSRM fallback")
                st.warning(
                    "本地校園路網目前沒有可用路線，因此自動使用 OSRM 補足。"
                    "此路線可能不符合校園內部實際可走小路；若要固定校園路線，"
                    "請新增 hidden nodes 與 campus_edges。"
                )
                st.write(f"本地路網錯誤：{active_route.get('local_error', '')}")
            elif active_route.get("source") == "hybrid_forced_route":
                st.write("資料來源：hybrid_forced_route")
                st.write(f"強制規則：{active_route.get('rule_name', '')}")
                st.write(f"方向：{active_route.get('direction', '')}")
            else:
                st.write(f"資料來源：{active_route.get('source', '')}")
            if active_route.get("source") in {
                "osrm",
                "osrm_fallback",
                "hybrid_forced_route",
            }:
                st.write(f"本次使用快取：{'是' if active_route.get('cache_hit') else '否'}")
            if active_route.get("path_names"):
                st.markdown("經過地點")
                for name in active_route["path_names"]:
                    st.write(f"- {name}")
            if active_route.get("source") == "local_graph" and active_route.get("path_ids"):
                st.markdown("Path IDs")
                st.code(" → ".join(active_route["path_ids"]))
            if (
                active_route.get("source") == "hybrid_forced_route"
                and active_route.get("path_ids")
            ):
                st.markdown("強制路線 Path IDs")
                st.code(" → ".join(active_route["path_ids"]))
                st.markdown("強制路線分段")
                for segment in active_route.get("edge_segments", []):
                    st.write(
                        f"- {segment['from_id']} → {segment['to_id']} | "
                        f"type={segment.get('type')} | "
                        f"distance_m={segment.get('distance_m')} | "
                        f"manual_reversed={segment.get('manual_reversed', False)}"
                    )
            if active_route.get("source") == "local_graph" and active_route.get("edge_segments"):
                st.markdown("路段資訊")
                for segment in active_route["edge_segments"]:
                    st.write(
                        f"- {segment['from_id']} → {segment['to_id']} | "
                        f"{segment.get('road_name') or '(未命名)'} | "
                        f"source={segment.get('routing_source')} | "
                        f"ignore_osrm={int(bool(segment.get('ignore_osrm')))} | "
                        f"verified={int(bool(segment.get('verified')))} | "
                        f"distance_m={segment.get('distance_m')} | "
                        f"geometry_points={segment.get('geometry_point_count', 0)}"
                    )
        elif active_route and active_route.get("error"):
            st.error(active_route["error"])
        else:
            st.info("請選擇起點與終點後按下「計算路線」。")

        if selected_mode in {OSRM_MODE_ID, RAIN_MODE_ID, COMPARE_MODE_ID} or (
            active_route and active_route.get("source") == "osrm_fallback"
        ):
            with st.expander("OSRM Debug"):
                st.write(f"起點 id：{start_id}")
                st.write(f"起點名稱：{labels[start_id]}")
                st.write(
                    f"起點座標：lat={parse_coordinate(start_place.get('latitude'))}, "
                    f"lon={parse_coordinate(start_place.get('longitude'))}"
                )
                st.write(f"終點 id：{end_id}")
                st.write(f"終點名稱：{labels[end_id]}")
                st.write(
                    f"終點座標：lat={parse_coordinate(end_place.get('latitude'))}, "
                    f"lon={parse_coordinate(end_place.get('longitude'))}"
                )

                debug_route = active_route if isinstance(active_route, dict) else {}
                if selected_mode == COMPARE_MODE_ID:
                    debug_route = debug_route.get("osrm") or {}
                st.write(f"目前 profile：{debug_route.get('profile') or osrm_profile}")
                st.write(f"是否使用 cache：{'是' if debug_route.get('cache_hit') else '否'}")
                st.write("實際送出的 OSRM URL：")
                st.code(debug_route.get("osrm_url") or "尚未計算 OSRM 路線")

                if debug_route:
                    st.write(f"OSRM distance_m：{debug_route.get('distance_m')}")
                    st.write(f"OSRM 原始時間：{format_duration(debug_route.get('osrm_duration_s'))}")
                    st.write(f"畫面使用時間來源：{debug_route.get('duration_source') or 'walking'}")
                    if debug_route.get("source") == "osrm_fallback":
                        st.write(f"Local graph error：{debug_route.get('local_error')}")
                    coordinates = debug_route.get("folium_coordinates") or []
                    if coordinates:
                        first_point = coordinates[0]
                        last_point = coordinates[-1]
                        st.write(f"route geometry 第一點 [lat, lon]：{first_point}")
                        st.write(f"route geometry 最後一點 [lat, lon]：{last_point}")
                        st.write(f"第一點接近起點：{coordinate_delta(first_point, start_place)}")
                        st.write(f"最後一點接近終點：{coordinate_delta(last_point, end_place)}")
                    else:
                        st.write("route geometry：無 folium_coordinates")

        if selected_mode == CAMPUS_MODE_ID:
            if active_route and active_route.get("source") == "osrm_fallback":
                st.caption("校園道路路線已先嘗試本地 graph；本次因本地路線失敗而使用 OSRM fallback。")
            else:
                st.caption("校園道路路線優先使用本地 campus_edges.csv；只有本地路線失敗才使用 OSRM fallback。")
        elif selected_mode == OSRM_MODE_ID:
            st.caption("OSRM 基本路線使用 OpenStreetMap 公共路網與 OSRM Route API。")
        elif selected_mode == RAIN_MODE_ID:
            st.caption("雨天路線會先套用雨天專用強制規則；沒有符合規則時使用純 OSRM walking 路線。")
        else:
            st.caption("路線比較會獨立計算純 OSRM 路線與校園路線，再同時顯示與比較。")


if __name__ == "__main__":
    main()
