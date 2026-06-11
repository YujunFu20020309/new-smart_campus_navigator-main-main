from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import streamlit as st

from src.data_admin import sanitize_place_id
from src.forced_routes import (
    add_forced_route_rule,
    delete_forced_route_rule,
    load_forced_route_rules,
    save_forced_route_rules,
    update_forced_route_rule,
)
from src.route_modes import CAMPUS_MODE_ID, RAIN_MODE_ID


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


def render_forced_route_rules_sidebar(
    places_df: pd.DataFrame,
    *,
    forced_rules_path: str | Path,
    on_rules_changed: Callable[[], None] | None = None,
) -> None:
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
            rules = load_forced_route_rules(forced_rules_path)
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
                        forced_rules_path,
                    )
                    if on_rules_changed is not None:
                        on_rules_changed()
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
                            forced_rules_path,
                        )
                        if on_rules_changed is not None:
                            on_rules_changed()
                        st.success("強制路線規則已儲存。")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"儲存規則失敗：{type(exc).__name__}: {exc}")
                if st.button("刪除選取規則", type="secondary", use_container_width=True):
                    delete_forced_route_rule(selected_rule_id, forced_rules_path)
                    if on_rules_changed is not None:
                        on_rules_changed()
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
                        save_forced_route_rules(payload, forced_rules_path)
                        if on_rules_changed is not None:
                            on_rules_changed()
                        st.success("規則已匯入。")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"匯入規則失敗：{type(exc).__name__}: {exc}")
