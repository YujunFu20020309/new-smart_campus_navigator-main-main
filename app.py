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
    append_edge,
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
    LOCAL_GRAPH_MODE_ID,
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
from src.ui_forced_routes import (
    FORCED_RULE_MODE_OPTIONS as _FORCED_RULE_MODE_OPTIONS,
    _apply_forced_rule_modes as _ui_apply_forced_rule_modes,
    _forced_rule_modes_label as _ui_forced_rule_modes_label,
    _forced_rule_modes_selection as _ui_forced_rule_modes_selection,
    _segments_frame as _ui_segments_frame,
    _segments_from_editor as _ui_segments_from_editor,
    render_forced_route_rules_sidebar as _render_forced_route_rules_sidebar,
)
from src.ui_pending_places import (
    PENDING_PLACE_FORM_KEYS as _PENDING_PLACE_FORM_KEYS,
    _clear_pending_place_form_state as _ui_clear_pending_place_form_state,
    _last_clicked_location as _ui_last_clicked_location,
    render_pending_place_review_form as _render_pending_place_review_form,
)
from src.ui_route_info import (
    coordinate_delta,
    render_compare_route_info,
    render_route_info_panel,
)
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


def _truthy_setting(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "on"}


def is_public_site_mode() -> bool:
    public_site = os.getenv("PUBLIC_SITE")
    if public_site is None:
        try:
            public_site = st.secrets["PUBLIC_SITE"]
        except Exception:
            public_site = None
    return _truthy_setting(public_site)


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


PENDING_PLACE_FORM_KEYS = _PENDING_PLACE_FORM_KEYS
_last_clicked_location = _ui_last_clicked_location
_clear_pending_place_form_state = _ui_clear_pending_place_form_state


def _on_pending_place_added() -> None:
    load_places_cached.clear()
    load_edges_cached.clear()
    st.session_state.pop("route_state", None)


def render_pending_place_review_form(places_df: pd.DataFrame) -> None:
    _render_pending_place_review_form(
        places_df,
        pending_csv_path=MANUAL_PLACES_PENDING_CSV,
        on_pending_place_added=_on_pending_place_added,
    )


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


_segments_from_editor = _ui_segments_from_editor
_segments_frame = _ui_segments_frame
FORCED_RULE_MODE_OPTIONS = _FORCED_RULE_MODE_OPTIONS
_forced_rule_modes_selection = _ui_forced_rule_modes_selection
_apply_forced_rule_modes = _ui_apply_forced_rule_modes
_forced_rule_modes_label = _ui_forced_rule_modes_label


def _on_forced_rules_changed() -> None:
    st.session_state.pop("route_state", None)


def render_forced_route_rules_sidebar(
    places_df: pd.DataFrame,
    *,
    forced_rules_path: str | Path = FORCED_RULES_PATH,
    on_rules_changed=None,
) -> None:
    _render_forced_route_rules_sidebar(
        places_df=places_df,
        forced_rules_path=forced_rules_path,
        on_rules_changed=on_rules_changed or _on_forced_rules_changed,
    )


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
        public_site_mode = is_public_site_mode()
        demo_mode = st.toggle("Demo mode", value=True)
        if public_site_mode:
            allow_live_osrm = True
        else:
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
        mode_options = list(route_modes.keys())
        if public_site_mode:
            default_mode_index = (
                mode_options.index(LOCAL_GRAPH_MODE_ID)
                if LOCAL_GRAPH_MODE_ID in mode_options
                else 0
            )
        else:
            default_mode_index = 0
        selected_mode = st.selectbox(
            "路線模式",
            options=mode_options,
            index=default_mode_index,
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
            render_forced_route_rules_sidebar(
                places_df=places_df,
                forced_rules_path=FORCED_RULES_PATH,
                on_rules_changed=_on_forced_rules_changed,
            )

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
        render_route_info_panel(
            places_df=places_df,
            start_id=start_id,
            end_id=end_id,
            labels=labels,
            start_place=start_place,
            end_place=end_place,
            active_route=active_route,
            selected_mode=selected_mode,
            mode_labels={
                mode_id: route_mode["label"]
                for mode_id, route_mode in route_modes.items()
            },
            add_place_mode=add_place_mode,
            pending_place_renderer=render_pending_place_review_form,
            osrm_profile=osrm_profile,
            demo_mode=demo_mode,
            allow_live_osrm=allow_live_osrm,
        )


if __name__ == "__main__":
    main()
