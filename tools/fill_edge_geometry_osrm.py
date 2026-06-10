"""Fill blank campus edge geometry fields with OSRM walking routes."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.campus_graph import load_edges  # noqa: E402
from src.routing_osrm import DEFAULT_OSRM_BASE_URL  # noqa: E402
from src.utils import load_places, parse_coordinate  # noqa: E402


DEFAULT_PLACES_PATH = PROJECT_ROOT / "data" / "places.csv"
DEFAULT_EDGES_PATH = PROJECT_ROOT / "data" / "campus_edges.csv"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data" / "campus_edges_filled.csv"


def _straight_line_distance_m(
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
) -> float:
    """Return the haversine distance between two coordinates in meters."""
    radius_m = 6_371_000.0
    lat1 = math.radians(start_lat)
    lat2 = math.radians(end_lat)
    delta_lat = math.radians(end_lat - start_lat)
    delta_lon = math.radians(end_lon - start_lon)
    value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    return radius_m * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def _route_is_unreasonably_long(
    osrm_distance_m: float,
    original_distance_m: float,
    straight_distance_m: float,
) -> bool:
    """Return True when OSRM appears to route far beyond the intended single edge."""
    exceeds_original = (
        original_distance_m > 0
        and osrm_distance_m > original_distance_m * 3
    )
    exceeds_straight = (
        straight_distance_m > 0
        and osrm_distance_m > straight_distance_m * 5
    )
    return exceeds_original or exceeds_straight


def fetch_osrm_edge_route(
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
    *,
    base_url: str = DEFAULT_OSRM_BASE_URL,
    profile: str = "foot",
    timeout: float = 15.0,
    session: Any = requests,
) -> tuple[list[list[float]], float]:
    """Fetch one edge route and return stored [lon, lat] geometry and distance."""
    profile = "foot"
    print("Walking mode only")
    coordinates = (
        f"{start_lon:.6f},{start_lat:.6f};"
        f"{end_lon:.6f},{end_lat:.6f}"
    )
    url = f"{base_url.rstrip('/')}/route/v1/{profile}/{coordinates}"
    response = session.get(
        url,
        params={"overview": "full", "geometries": "geojson"},
        timeout=timeout,
    )
    response.raise_for_status()

    payload = response.json()
    routes = payload.get("routes") if isinstance(payload, dict) else None
    if not routes:
        raise ValueError("OSRM returned no routes")

    route = routes[0]
    geometry = route.get("geometry")
    coordinates_geojson = geometry.get("coordinates") if isinstance(geometry, dict) else None
    if not isinstance(coordinates_geojson, list) or not coordinates_geojson:
        raise ValueError("OSRM returned empty route geometry")

    coordinates = [[float(point[0]), float(point[1])] for point in coordinates_geojson]
    return coordinates, float(route.get("distance", 0.0))


def fill_edge_geometries(
    places_path: str | Path = DEFAULT_PLACES_PATH,
    edges_path: str | Path = DEFAULT_EDGES_PATH,
    output_path: str | Path = DEFAULT_OUTPUT_PATH,
    *,
    base_url: str | None = None,
    profile: str = "foot",
    timeout: float = 15.0,
    sleep_seconds: float = 1.0,
    session: Any = requests,
) -> tuple[int, int]:
    """Fill blank edge geometries, save a new CSV, and return success/failure counts."""
    places_df = load_places(places_path)
    edges_df = load_edges(edges_path)
    original_columns = list(edges_df.columns)
    original_place_ids = set(places_df["id"].astype(str))
    original_endpoints = edges_df[["from_id", "to_id"]].copy()
    original_row_count = len(edges_df)
    places_by_id = places_df.set_index("id", drop=False)
    osrm_base_url = base_url or os.getenv("OSRM_BASE_URL") or DEFAULT_OSRM_BASE_URL

    filled_count = 0
    failed_count = 0

    for index, edge in edges_df.iterrows():
        if str(edge.get("ignore_osrm", "0")).strip().lower() in {"1", "true", "yes", "y"}:
            print(f"Skipped edge (ignore_osrm=1): {edge.get('from_id')} -> {edge.get('to_id')}")
            continue
        if str(edge.get("geometry", "")).strip():
            if str(edge.get("verified", "0")).strip().lower() in {"1", "true", "yes", "y"}:
                print(f"Skipped verified edge with geometry: {edge.get('from_id')} -> {edge.get('to_id')}")
            continue

        from_id = str(edge.get("from_id", "")).strip()
        to_id = str(edge.get("to_id", "")).strip()
        edge_label = f"{from_id} -> {to_id}"
        request_attempted = False

        try:
            if from_id not in places_by_id.index or to_id not in places_by_id.index:
                raise ValueError("place id not found in places.csv")

            from_place = places_by_id.loc[from_id]
            to_place = places_by_id.loc[to_id]
            start_lat = parse_coordinate(from_place.get("latitude"))
            start_lon = parse_coordinate(from_place.get("longitude"))
            end_lat = parse_coordinate(to_place.get("latitude"))
            end_lon = parse_coordinate(to_place.get("longitude"))
            if None in (start_lat, start_lon, end_lat, end_lon):
                raise ValueError("missing or invalid endpoint coordinates")

            request_attempted = True
            coordinates, distance_m = fetch_osrm_edge_route(
                start_lat,
                start_lon,
                end_lat,
                end_lon,
                base_url=osrm_base_url,
                profile=profile,
                timeout=timeout,
                session=session,
            )
            original_distance_m = float(edge.get("distance_m") or 0)
            straight_distance_m = _straight_line_distance_m(
                start_lat,
                start_lon,
                end_lat,
                end_lon,
            )
            if _route_is_unreasonably_long(
                distance_m,
                original_distance_m,
                straight_distance_m,
            ):
                raise ValueError(
                    "OSRM route is unreasonably long for this edge "
                    f"(osrm={distance_m:.1f} m, original={original_distance_m:.1f} m, "
                    f"straight={straight_distance_m:.1f} m)"
                )
            edges_df.at[index, "geometry"] = json.dumps(
                coordinates,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            edges_df.at[index, "distance_m"] = str(distance_m)
            filled_count += 1
            print(f"Filled edge: {edge_label} ({distance_m:.1f} m)")
        except Exception as exc:
            # A malformed response or one bad edge must not stop the remaining work.
            failed_count += 1
            prefix = (
                "Warning for manual edge"
                if str(edge.get("routing_source", "manual")).strip().lower() == "manual"
                else "Failed edge"
            )
            print(f"{prefix}: {edge_label}: {exc}")
        finally:
            if request_attempted and sleep_seconds > 0:
                time.sleep(sleep_seconds)

    if set(places_df["id"].astype(str)) != original_place_ids:
        raise RuntimeError("Place ids changed during geometry fill; refusing to write output.")
    if len(edges_df) != original_row_count:
        raise RuntimeError("Edge row count changed during geometry fill; refusing to write output.")
    if not edges_df[["from_id", "to_id"]].equals(original_endpoints):
        raise RuntimeError("Edge topology changed during geometry fill; refusing to write output.")

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    edges_df.loc[:, original_columns].to_csv(destination, index=False, encoding="utf-8-sig")
    print(
        f"Finished: {filled_count} filled, {failed_count} failed. "
        f"Output: {destination}"
    )
    return filled_count, failed_count


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(
        description="Fill blank campus edge geometry fields using OSRM.",
    )
    parser.add_argument("--places", default=str(DEFAULT_PLACES_PATH))
    parser.add_argument("--edges", default=str(DEFAULT_EDGES_PATH))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--sleep-seconds", type=float, default=1.0)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument(
        "--base-url",
        default=os.getenv("OSRM_BASE_URL") or DEFAULT_OSRM_BASE_URL,
    )
    return parser


def main() -> None:
    """Run the geometry filling command."""
    args = build_parser().parse_args()
    fill_edge_geometries(
        args.places,
        args.edges,
        args.output,
        base_url=args.base_url,
        profile="foot",
        timeout=args.timeout,
        sleep_seconds=max(args.sleep_seconds, 0.0),
    )


if __name__ == "__main__":
    main()
