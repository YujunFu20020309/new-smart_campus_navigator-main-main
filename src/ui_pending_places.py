from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pandas as pd
import streamlit as st

from src.data_admin import (
    PENDING_PLACE_CATEGORY_OPTIONS,
    append_pending_place,
    sanitize_place_id,
)
from src.utils import parse_coordinate


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


def render_pending_place_review_form(
    places_df: pd.DataFrame,
    *,
    pending_csv_path: str | Path,
    on_pending_place_added: Callable[[], None] | None = None,
) -> None:
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
                pending_csv_path,
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
            if on_pending_place_added is not None:
                on_pending_place_added()
            st.session_state["pending_place_success"] = (
                f"已加入待審核地點：{sanitize_place_id(place_id)}"
            )
            st.rerun()
        except Exception as exc:
            st.error(f"加入待審核地點失敗：{type(exc).__name__}: {exc}")
