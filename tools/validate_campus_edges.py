"""Report campus edge data issues without modifying project CSV files."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.campus_graph import (  # noqa: E402
    MAX_SHORT_CONNECTOR_M,
    ensure_edge_control_columns,
    is_destination_like,
)
from src.data_admin import load_edges_for_editing, load_places_for_editing  # noqa: E402
from src.utils import parse_coordinate  # noqa: E402


DEFAULT_PLACES_PATH = PROJECT_ROOT / "data" / "places.csv"
DEFAULT_EDGES_PATH = PROJECT_ROOT / "data" / "campus_edges.csv"


def _parse_geometry(value: Any) -> tuple[list[list[float]], str | None]:
    if str(value or "").strip() == "":
        return [], None
    try:
        payload = json.loads(str(value))
    except json.JSONDecodeError:
        return [], "geometry contains invalid JSON"
    if not isinstance(payload, list) or not payload:
        return [], "geometry must be a non-empty list"

    coordinates: list[list[float]] = []
    for point in payload:
        if not isinstance(point, list) or len(point) != 2:
            return [], "geometry must use [[lon, lat], [lon, lat], ...] format"
        try:
            first = float(point[0])
            second = float(point[1])
        except (TypeError, ValueError):
            return [], "geometry coordinates must be numeric"
        if first < 30 and second > 100:
            return [], "geometry coordinate order appears reversed; expected [lon, lat]"
        if not -180 <= first <= 180 or not -90 <= second <= 90:
            return [], "geometry contains coordinates outside valid [lon, lat] ranges"
        coordinates.append([first, second])
    return coordinates, None


def validate_edges_data(places_df, edges_df) -> list[str]:
    """Return human-readable campus edge data quality issues."""
    issues: list[str] = []
    edges_df = ensure_edge_control_columns(edges_df)
    places = {
        str(row["id"]).strip(): row
        for _, row in places_df.iterrows()
    }

    for index, edge in edges_df.iterrows():
        row_number = index + 2
        from_id = str(edge.get("from_id", "")).strip()
        to_id = str(edge.get("to_id", "")).strip()
        label = f"row {row_number} ({from_id} -> {to_id})"
        from_node = places.get(from_id)
        to_node = places.get(to_id)

        if from_node is None:
            issues.append(f"{label}: from_id does not exist in places.csv")
        if to_node is None:
            issues.append(f"{label}: to_id does not exist in places.csv")
        if from_id and from_id == to_id:
            issues.append(f"{label}: from_id and to_id are the same")

        try:
            distance_m = float(edge.get("distance_m", 0))
        except (TypeError, ValueError):
            distance_m = 0.0
            issues.append(f"{label}: distance_m is invalid")

        geometry, geometry_error = _parse_geometry(edge.get("geometry", ""))
        if geometry_error:
            issues.append(f"{label}: {geometry_error}")

        if from_node is not None and to_node is not None:
            if (
                is_destination_like(from_node)
                and is_destination_like(to_node)
                and distance_m > MAX_SHORT_CONNECTOR_M
            ):
                issues.append(f"{label}: long destination-like to destination-like edge")

            if (
                not geometry
                and geometry_error is None
                and distance_m > MAX_SHORT_CONNECTOR_M
            ):
                description = str(edge.get("description", "")).lower()
                verified = str(edge.get("verified", "0")).strip().lower() in {
                    "1",
                    "true",
                    "yes",
                    "y",
                }
                if (
                    not verified
                    and "verified_straight" not in description
                    and "straight_ok" not in description
                ):
                    issues.append(f"{label}: unsafe long edge has empty geometry")

            for endpoint_name, node in (("from_id", from_node), ("to_id", to_node)):
                if (
                    parse_coordinate(node.get("latitude")) is None
                    or parse_coordinate(node.get("longitude")) is None
                ):
                    issues.append(f"{label}: {endpoint_name} endpoint is missing coordinates")

    return issues


def validate_campus_edge_files(
    places_path: str | Path = DEFAULT_PLACES_PATH,
    edges_path: str | Path = DEFAULT_EDGES_PATH,
) -> list[str]:
    """Load project CSV files and return edge quality issues."""
    return validate_edges_data(
        load_places_for_editing(places_path),
        load_edges_for_editing(edges_path),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate campus_edges.csv without editing it.")
    parser.add_argument("--places", default=str(DEFAULT_PLACES_PATH))
    parser.add_argument("--edges", default=str(DEFAULT_EDGES_PATH))
    args = parser.parse_args()

    issues = validate_campus_edge_files(args.places, args.edges)
    if issues:
        print(f"Found {len(issues)} campus edge issue(s):")
        for issue in issues:
            print(f"- {issue}")
    else:
        print("No campus edge issues found.")


if __name__ == "__main__":
    main()
