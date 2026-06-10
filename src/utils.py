"""Shared data loading and formatting helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


REQUIRED_PLACE_COLUMNS = [
    "id",
    "name",
    "display_name",
    "category",
    "latitude",
    "longitude",
    "source",
    "notes",
]

NTHU_LAT_MIN = 24.78
NTHU_LAT_MAX = 24.81
NTHU_LON_MIN = 120.98
NTHU_LON_MAX = 121.02

DESTINATION_CATEGORIES = {"building", "gate", "landmark"}
ROUTING_NODE_CATEGORIES = {"intersection", "road_node", "waypoint"}


def is_blank(value: Any) -> bool:
    """Return True when a CSV value should be treated as missing."""
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except TypeError:
        pass
    return str(value).strip().lower() in {"", "nan", "none", "null"}


def parse_coordinate(value: Any) -> float | None:
    """Convert a coordinate field to float, or None when it is blank/invalid."""
    if is_blank(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_places(csv_path: str | Path) -> pd.DataFrame:
    """Load places.csv and validate that required columns exist."""
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"Places CSV not found: {path}")

    try:
        df = pd.read_csv(
            path,
            dtype=str,
            keep_default_na=False,
            encoding="utf-8-sig",
        ).fillna("")
    except UnicodeDecodeError:
        # Windows spreadsheet editors in Taiwan commonly save CSV files as CP950.
        df = pd.read_csv(
            path,
            dtype=str,
            keep_default_na=False,
            encoding="cp950",
        ).fillna("")
    validate_places(df)
    return ensure_place_visibility_columns(df)


def validate_places(df: pd.DataFrame) -> bool:
    """Validate required places.csv columns and unique non-empty place ids."""
    missing = [column for column in REQUIRED_PLACE_COLUMNS if column not in df.columns]
    if missing:
        raise ValueError(f"places.csv missing required columns: {', '.join(missing)}")

    if df["id"].astype(str).str.strip().eq("").any():
        raise ValueError("places.csv contains an empty id")

    duplicated = df["id"][df["id"].duplicated()].tolist()
    if duplicated:
        raise ValueError(f"places.csv contains duplicate ids: {duplicated}")

    return True


def get_place_by_id(df: pd.DataFrame, place_id: str) -> dict[str, Any]:
    """Return one place row as a dict by id."""
    matches = df[df["id"].astype(str) == str(place_id)]
    if matches.empty:
        raise KeyError(f"Place id not found: {place_id}")
    return matches.iloc[0].to_dict()


def place_has_coordinates(place: dict[str, Any] | pd.Series) -> bool:
    """Return True when both latitude and longitude are usable floats."""
    return (
        parse_coordinate(place.get("latitude")) is not None
        and parse_coordinate(place.get("longitude")) is not None
    )


def _default_visibility_flag(category: Any) -> str:
    """Return the default destination/marker flag for a place category."""
    return "1" if str(category).strip().lower() in DESTINATION_CATEGORIES else "0"


def ensure_place_visibility_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add/fill is_destination and show_marker using category-based defaults."""
    result = df.copy()
    for column in ("is_destination", "show_marker"):
        if column not in result.columns:
            result[column] = result["category"].map(_default_visibility_flag)
        else:
            blank_mask = result[column].map(is_blank)
            result.loc[blank_mask, column] = result.loc[blank_mask, "category"].map(
                _default_visibility_flag
            )
    return result.fillna("")


def is_enabled_flag(value: Any) -> bool:
    """Return True for CSV boolean values such as 1, true, or yes."""
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def get_destination_places(df: pd.DataFrame) -> pd.DataFrame:
    """Return user-selectable destinations, excluding internal routing nodes."""
    places = ensure_place_visibility_columns(df)
    categories = places["category"].astype(str).str.strip().str.lower()
    enabled = places["is_destination"].map(is_enabled_flag)
    return places[enabled & ~categories.isin(ROUTING_NODE_CATEGORIES)].copy()


def get_marker_places(df: pd.DataFrame) -> pd.DataFrame:
    """Return places whose regular map markers should be displayed."""
    places = ensure_place_visibility_columns(df)
    return places[places["show_marker"].map(is_enabled_flag)].copy()


def is_manual_source(place: dict[str, Any] | pd.Series) -> bool:
    """Return True when a place uses manually maintained coordinates."""
    return str(place.get("source", "")).strip().lower() == "manual"


def notes_include_verified(place: dict[str, Any] | pd.Series) -> bool:
    """Return True when notes contain a standalone verified token."""
    notes = "" if is_blank(place.get("notes")) else str(place.get("notes"))
    tokens = [token.strip().lower() for token in notes.replace(",", ";").split(";")]
    return any(
        token == "verified" or token.startswith("verified:")
        for token in tokens
    )


def is_geocoding_protected(place: dict[str, Any] | pd.Series) -> bool:
    """Return True when Nominatim should not update this place."""
    return is_manual_source(place) or notes_include_verified(place)


def validate_coordinate_bounds(
    place: dict[str, Any] | pd.Series,
    *,
    lat_min: float = NTHU_LAT_MIN,
    lat_max: float = NTHU_LAT_MAX,
    lon_min: float = NTHU_LON_MIN,
    lon_max: float = NTHU_LON_MAX,
) -> bool:
    """Return True when coordinates are blank or inside the NTHU bounding box."""
    lat = parse_coordinate(place.get("latitude"))
    lon = parse_coordinate(place.get("longitude"))
    if lat is None or lon is None:
        return True
    return lat_min <= lat <= lat_max and lon_min <= lon <= lon_max


def append_note(existing_notes: Any, new_note: str) -> str:
    """Append a note token without duplicating it."""
    notes = "" if is_blank(existing_notes) else str(existing_notes)
    tokens = [token for token in notes.split(";") if token]
    if new_note not in tokens:
        tokens.append(new_note)
    return ";".join(tokens)


def format_distance(distance_m: float | int | None) -> str:
    """Format meters as a compact m/km string."""
    if distance_m is None:
        return "N/A"
    meters = float(distance_m)
    return f"{meters:,.0f} m ({meters / 1000:.2f} km)"


def format_duration(duration_s: float | int | None) -> str:
    """Format seconds as minutes."""
    if duration_s is None:
        return "N/A"
    return f"{float(duration_s) / 60:.1f} min"


def ensure_parent_dir(path: str | Path) -> None:
    """Create a file's parent directory when needed."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
