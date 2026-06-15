from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pandas as pd
import streamlit as st

from src.route_modes import CAMPUS_MODE_ID, COMPARE_MODE_ID, OSRM_MODE_ID, RAIN_MODE_ID
from src.utils import format_distance, format_duration, parse_coordinate


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


def coordinate_delta(point: list[float], place: dict[str, Any]) -> str:
    """Return a compact delta between a route point and a place coordinate."""
    lat = parse_coordinate(place.get("latitude"))
    lon = parse_coordinate(place.get("longitude"))
    if lat is None or lon is None or len(point) < 2:
        return "N/A"
    return f"lat Δ={abs(point[0] - lat):.6f}, lon Δ={abs(point[1] - lon):.6f}"


def render_active_route_summary(active_route: dict[str, Any] | None) -> None:
    if active_route and active_route.get("success"):
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
        elif active_route.get("source") == "gps_campus_graph":
            st.write("資料來源：實驗性 GPS connector + campus graph")
            st.write(
                f"接入節點：{active_route.get('snapped_start_name') or active_route.get('snapped_start_id')}"
            )
            st.write(f"直線 snap 距離：{format_distance(active_route.get('snap_distance_m'))}")
            st.write(f"OSRM connector：{format_distance(active_route.get('connector_distance_m'))}")
            st.write(f"校園 graph：{format_distance(active_route.get('campus_distance_m'))}")
            if active_route.get("warning"):
                st.warning(active_route["warning"])
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
        st.error(active_route.get("user_message") or active_route["error"])
    else:
        st.info("請選擇起點與終點後按下「計算路線」。")


def render_gps_campus_snap_debug(
    active_route: dict[str, Any] | None,
    *,
    end_id: str,
    enabled: bool,
) -> bool:
    """Render detailed snap failure metadata only under the existing debug flag."""
    if not (
        enabled
        and active_route
        and active_route.get("source") == "gps_campus_graph"
        and not active_route.get("success")
    ):
        return False

    with st.expander("GPS Campus Snap Debug"):
        st.write(f"fallback_reason：{active_route.get('fallback_reason')}")
        st.write(f"snap_failure_reason：{active_route.get('snap_failure_reason')}")
        st.write(f"nearest node id：{active_route.get('snapped_start_id')}")
        st.write(f"nearest node name：{active_route.get('snapped_start_name')}")
        st.write(f"snap distance_m：{active_route.get('snap_distance_m')}")
        st.write(f"snap limit_m：{active_route.get('snap_limit_m')}")
        st.write(
            "nearest node coordinate："
            f"lat={active_route.get('snapped_start_latitude')}, "
            f"lon={active_route.get('snapped_start_longitude')}"
        )
        st.write(f"destination id：{end_id}")
        st.code(active_route.get("error") or "No technical error detail")
    return True


def render_osrm_debug(
    *,
    start_id: str,
    end_id: str,
    labels: dict[str, str],
    start_place: dict[str, Any],
    end_place: dict[str, Any],
    active_route: dict[str, Any] | None,
    selected_mode: str,
    osrm_profile: str,
) -> None:
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


def render_mode_caption(
    *,
    selected_mode: str,
    active_route: dict[str, Any] | None,
) -> None:
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


def render_route_info_panel(
    *,
    places_df: pd.DataFrame,
    start_id: str,
    end_id: str,
    labels: dict[str, str],
    start_place: dict[str, Any],
    end_place: dict[str, Any],
    active_route: dict[str, Any] | None,
    selected_mode: str,
    mode_labels: dict[str, str],
    add_place_mode: bool,
    pending_place_renderer: Callable[[pd.DataFrame], None],
    osrm_profile: str,
    demo_mode: bool,
    allow_live_osrm: bool,
    debug_enabled: bool = False,
) -> None:
    st.markdown("### 路線資訊")
    st.write(f"起點：{labels[start_id]}")
    if start_place.get("source") == "browser_geolocation":
        accuracy = parse_coordinate(start_place.get("accuracy_m"))
        if accuracy is not None:
            st.write(f"定位精確度：約 {accuracy:.0f} 公尺")
        if start_place.get("location_stale"):
            st.warning("目前顯示的是先前取得的位置，可能已過期。")
    st.write(f"終點：{labels[end_id]}")
    st.write(f"模式：{mode_labels[selected_mode]}")

    if add_place_mode:
        pending_place_renderer(places_df)
        st.divider()

    if active_route and active_route.get("mode") == COMPARE_MODE_ID:
        render_compare_route_info(active_route)
    else:
        render_active_route_summary(active_route)

    render_gps_campus_snap_debug(
        active_route,
        end_id=end_id,
        enabled=debug_enabled,
    )

    render_osrm_debug(
        start_id=start_id,
        end_id=end_id,
        labels=labels,
        start_place=start_place,
        end_place=end_place,
        active_route=active_route,
        selected_mode=selected_mode,
        osrm_profile=osrm_profile,
    )
    render_mode_caption(selected_mode=selected_mode, active_route=active_route)
