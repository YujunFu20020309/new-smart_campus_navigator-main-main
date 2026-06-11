"""Validated CSV editing helpers for the Streamlit data administration UI."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

from .campus_graph import (
    EDGE_COLUMN_DEFAULTS,
    REQUIRED_EDGE_COLUMNS,
    ensure_edge_control_columns,
    validate_campus_edges,
)
from .geo_utils import haversine_distance_m, polyline_distance_m
from .utils import (
    REQUIRED_PLACE_COLUMNS,
    ensure_place_visibility_columns,
    ensure_parent_dir,
    is_blank,
    is_enabled_flag,
    parse_coordinate,
    validate_coordinate_bounds,
    validate_places,
)


PLACE_COLUMNS = [
    *REQUIRED_PLACE_COLUMNS,
    "is_destination",
    "show_marker",
]
PENDING_PLACE_COLUMNS = [
    "id",
    "name",
    "display_name",
    "category",
    "latitude",
    "longitude",
    "source",
    "notes",
    "is_destination",
    "show_marker",
    "type",
]
PENDING_PLACE_CATEGORY_OPTIONS = [
    "building",
    "gate",
    "library",
    "cafeteria",
    "dorm",
    "landmark",
]
PENDING_PLACE_SOURCE = "manual_ui_pending"
PENDING_PLACE_NOTES = "pending_review"
EDGE_COLUMNS = list(REQUIRED_EDGE_COLUMNS)
CSV_ENCODINGS = ("utf-8-sig", "utf-8", "big5", "cp950")


def _read_csv_with_fallback(path: str | Path) -> pd.DataFrame:
    csv_path = Path(path)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    last_error: UnicodeDecodeError | None = None
    for encoding in CSV_ENCODINGS:
        try:
            return pd.read_csv(
                csv_path,
                dtype=str,
                keep_default_na=False,
                encoding=encoding,
            ).fillna("")
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    raise ValueError(f"Unable to read CSV: {csv_path}")


def _ordered_frame(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    result = df.copy().fillna("")
    for column in columns:
        if column not in result.columns:
            result[column] = ""
    return result.loc[:, columns]


def load_places_for_editing(path: str | Path) -> pd.DataFrame:
    """Load places.csv with common Traditional Chinese CSV encoding fallbacks."""
    places_df = ensure_place_visibility_columns(_read_csv_with_fallback(path))
    validate_places(places_df)
    return _ordered_frame(places_df, PLACE_COLUMNS)


def load_pending_places(path: str | Path) -> pd.DataFrame:
    """Load pending manual places, returning an empty frame when absent."""
    pending_path = Path(path)
    if not pending_path.exists():
        return pd.DataFrame(columns=PENDING_PLACE_COLUMNS)
    return _ordered_frame(_read_csv_with_fallback(pending_path), PENDING_PLACE_COLUMNS)


def load_edges_for_editing(path: str | Path) -> pd.DataFrame:
    """Load campus_edges.csv with common Traditional Chinese CSV encoding fallbacks."""
    edges_df = ensure_edge_control_columns(_read_csv_with_fallback(path))
    validate_campus_edges(edges_df)
    return _ordered_frame(edges_df, EDGE_COLUMNS)


def save_places(path: str | Path, df: pd.DataFrame) -> None:
    """Save places.csv as UTF-8 with BOM and the canonical column order."""
    places_df = ensure_place_visibility_columns(_ordered_frame(df, PLACE_COLUMNS))
    places_df["is_destination"] = places_df["is_destination"].map(_flag)
    places_df["show_marker"] = places_df["show_marker"].map(_flag)
    validate_places(places_df)
    ensure_parent_dir(path)
    places_df.to_csv(path, index=False, encoding="utf-8-sig")


def save_pending_places(path: str | Path, df: pd.DataFrame) -> None:
    """Save pending places without touching the verified places.csv file."""
    pending_df = _ordered_frame(df, PENDING_PLACE_COLUMNS)
    pending_df["is_destination"] = pending_df["is_destination"].map(_flag)
    pending_df["show_marker"] = pending_df["show_marker"].map(_flag)
    ensure_parent_dir(path)
    pending_df.to_csv(path, index=False, encoding="utf-8-sig")


def save_edges(path: str | Path, df: pd.DataFrame) -> None:
    """Save campus_edges.csv as UTF-8 with BOM and the canonical column order."""
    edges_df = ensure_edge_control_columns(_ordered_frame(df, EDGE_COLUMNS))
    validate_campus_edges(edges_df)
    for index, row in edges_df.iterrows():
        edges_df.at[index, "distance_m"] = _normalize_distance(row.get("distance_m"))
        edges_df.at[index, "stairs"] = _flag(row.get("stairs"))
        edges_df.at[index, "rain_friendly"] = _flag(row.get("rain_friendly"))
        edges_df.at[index, "ignore_osrm"] = _flag(row.get("ignore_osrm"))
        edges_df.at[index, "verified"] = _flag(row.get("verified"))
        edges_df.at[index, "enabled"] = _flag(row.get("enabled"))
        edges_df.at[index, "routing_source"] = (
            str(row.get("routing_source", "")).strip()
            or EDGE_COLUMN_DEFAULTS["routing_source"]
        )
        edges_df.at[index, "geometry"] = _normalize_geometry(
            row.get("geometry"),
            row_number=index + 2,
        )
    ensure_parent_dir(path)
    edges_df.to_csv(path, index=False, encoding="utf-8-sig")


def sanitize_place_id(text: Any) -> str:
    """Convert text into a lowercase ASCII id containing letters, digits, and underscores."""
    value = re.sub(r"\s+", "_", str(text or "").strip().lower())
    value = re.sub(r"[^a-z0-9_]", "", value)
    return re.sub(r"_+", "_", value).strip("_")


def _flag(value: Any) -> str:
    return "1" if is_enabled_flag(value) else "0"


def append_place(path: str | Path, place_dict: dict[str, Any]) -> pd.DataFrame:
    """Validate and append one persistent place row."""
    places_df = load_places_for_editing(path)
    place_id = sanitize_place_id(place_dict.get("id"))
    if not place_id:
        raise ValueError("Place id cannot be blank.")
    if place_id in set(places_df["id"].astype(str)):
        raise ValueError(f"Place id already exists: {place_id}")

    row = {column: place_dict.get(column, "") for column in PLACE_COLUMNS}
    row["id"] = place_id
    for coordinate in ("latitude", "longitude"):
        try:
            row[coordinate] = str(float(row[coordinate]))
        except (TypeError, ValueError):
            raise ValueError(f"{coordinate} must be a valid number.") from None
    row["is_destination"] = _flag(row["is_destination"])
    row["show_marker"] = _flag(row["show_marker"])

    updated = pd.concat([places_df, pd.DataFrame([row])], ignore_index=True)
    save_places(path, updated)
    return updated


def append_pending_place(
    pending_path: str | Path,
    official_places_df: pd.DataFrame,
    place_dict: dict[str, Any],
) -> pd.DataFrame:
    """Validate and append one map-clicked place to the pending review CSV."""
    pending_df = load_pending_places(pending_path)
    place_id = sanitize_place_id(place_dict.get("id"))
    if not place_id:
        raise ValueError("Place id cannot be blank.")

    official_ids = set(official_places_df["id"].astype(str))
    pending_ids = set(pending_df["id"].astype(str))
    if place_id in official_ids:
        raise ValueError(f"Place id already exists in places.csv: {place_id}")
    if place_id in pending_ids:
        raise ValueError(f"Place id already exists in pending places: {place_id}")

    category = str(place_dict.get("category", "")).strip().lower()
    if category not in PENDING_PLACE_CATEGORY_OPTIONS:
        allowed = ", ".join(PENDING_PLACE_CATEGORY_OPTIONS)
        raise ValueError(f"category must be one of: {allowed}")

    latitude = parse_coordinate(place_dict.get("latitude"))
    longitude = parse_coordinate(place_dict.get("longitude"))
    if latitude is None or longitude is None:
        raise ValueError("latitude and longitude are required.")

    row = {column: place_dict.get(column, "") for column in PENDING_PLACE_COLUMNS}
    row.update(
        {
            "id": place_id,
            "category": category,
            "latitude": str(float(latitude)),
            "longitude": str(float(longitude)),
            "source": PENDING_PLACE_SOURCE,
            "notes": PENDING_PLACE_NOTES,
            "is_destination": _flag(row.get("is_destination")),
            "show_marker": _flag(row.get("show_marker")),
        }
    )
    if not validate_coordinate_bounds(row):
        raise ValueError("Coordinates are outside the expected NTHU campus bounds.")

    updated = pd.concat([pending_df, pd.DataFrame([row])], ignore_index=True)
    save_pending_places(pending_path, updated)
    return updated


def _normalize_distance(value: Any) -> str:
    try:
        distance = float(value)
    except (TypeError, ValueError):
        raise ValueError("distance_m must be a valid number.") from None
    if distance < 0:
        raise ValueError("distance_m must be non-negative.")
    return str(distance)


def _normalize_geometry(value: Any, *, row_number: int | None = None) -> str:
    if is_blank(value):
        return ""
    try:
        geometry = json.loads(str(value))
    except json.JSONDecodeError as exc:
        prefix = f"Row {row_number}: " if row_number is not None else ""
        raise ValueError(f"{prefix}geometry must be valid JSON.") from exc
    if not isinstance(geometry, list) or not geometry:
        raise ValueError("geometry must be a non-empty JSON list of [lon, lat] points.")

    normalized: list[list[float]] = []
    for point in geometry:
        if not isinstance(point, list) or len(point) != 2:
            raise ValueError("geometry must use [[lon, lat], [lon, lat], ...] format.")
        try:
            longitude = float(point[0])
            latitude = float(point[1])
        except (TypeError, ValueError):
            raise ValueError("geometry coordinates must be numeric.") from None
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise ValueError(
                "geometry must use [longitude, latitude] order with valid coordinate ranges."
            )
        normalized.append([longitude, latitude])
    return json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))


def append_edge(
    path: str | Path,
    places_df: pd.DataFrame,
    edge_dict: dict[str, Any],
) -> pd.DataFrame:
    """Validate and append one persistent campus graph edge."""
    edges_df = load_edges_for_editing(path)
    place_ids = set(places_df["id"].astype(str))
    from_id = str(edge_dict.get("from_id", "")).strip()
    to_id = str(edge_dict.get("to_id", "")).strip()
    if from_id not in place_ids:
        raise ValueError(f"from_id does not exist in places.csv: {from_id}")
    if to_id not in place_ids:
        raise ValueError(f"to_id does not exist in places.csv: {to_id}")

    row = {column: edge_dict.get(column, "") for column in EDGE_COLUMNS}
    for column, default in EDGE_COLUMN_DEFAULTS.items():
        if column not in edge_dict or is_blank(edge_dict.get(column)):
            row[column] = default
    row["from_id"] = from_id
    row["to_id"] = to_id
    row["geometry"] = _normalize_geometry(row["geometry"])
    manual_distance = (
        "0.0" if is_blank(row["distance_m"]) else _normalize_distance(row["distance_m"])
    )
    routing_source = (
        str(row.get("routing_source", "")).strip().lower()
        or EDGE_COLUMN_DEFAULTS["routing_source"]
    )
    if row["geometry"] and routing_source != "osrm":
        row["distance_m"] = str(polyline_distance_m(json.loads(row["geometry"])))
    elif float(manual_distance) > 0:
        row["distance_m"] = manual_distance
    else:
        from_place = places_df[places_df["id"].astype(str) == from_id].iloc[0]
        to_place = places_df[places_df["id"].astype(str) == to_id].iloc[0]
        from_lat = parse_coordinate(from_place.get("latitude"))
        from_lon = parse_coordinate(from_place.get("longitude"))
        to_lat = parse_coordinate(to_place.get("latitude"))
        to_lon = parse_coordinate(to_place.get("longitude"))
        if None in (from_lat, from_lon, to_lat, to_lon):
            raise ValueError("Cannot auto-calculate distance because endpoint coordinates are missing.")
        row["distance_m"] = str(haversine_distance_m(from_lat, from_lon, to_lat, to_lon))
    row["stairs"] = _flag(row["stairs"])
    row["rain_friendly"] = _flag(row["rain_friendly"])
    row["ignore_osrm"] = _flag(row["ignore_osrm"])
    row["verified"] = _flag(row["verified"])
    row["enabled"] = _flag(row["enabled"])
    row["routing_source"] = routing_source

    updated = pd.concat([edges_df, pd.DataFrame([row])], ignore_index=True)
    save_edges(path, updated)
    return updated
