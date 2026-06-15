"""OSRM Route API client with cache and coordinate conversion helpers."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests

from .geo_utils import resolve_walking_duration_s
from .utils import ensure_parent_dir


DEFAULT_OSRM_BASE_URL = "https://router.project-osrm.org"
WALKING_PROFILE = "foot"
WALKING_TRANSPORT_MODE = "walking"
ROUTE_CACHE_VERSION = 2


def normalize_profile(profile: str | None = None) -> str:
    """Force every OSRM request to use the walking profile."""
    print("Walking mode only")
    return WALKING_PROFILE


def make_route_cache_key(
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
    profile: str = "foot",
) -> str:
    """Create a stable cache key with rounded coordinates."""
    normalized_profile = normalize_profile(profile)
    return (
        f"{normalized_profile}:walking-v{ROUTE_CACHE_VERSION}:"
        f"{float(start_lat):.5f},{float(start_lon):.5f}->"
        f"{float(end_lat):.5f},{float(end_lon):.5f}"
    )


def convert_geojson_to_folium_coordinates(
    geojson_coordinates: list[list[float]],
) -> list[list[float]]:
    """Convert OSRM GeoJSON [lon, lat] pairs to Folium [lat, lon] pairs."""
    folium_coordinates: list[list[float]] = []
    for coordinate in geojson_coordinates:
        if len(coordinate) < 2:
            continue
        lon, lat = coordinate[0], coordinate[1]
        folium_coordinates.append([lat, lon])
    return folium_coordinates


def _empty_cache() -> dict[str, Any]:
    return {
        "version": ROUTE_CACHE_VERSION,
        "provider": "osrm",
        "profile": WALKING_PROFILE,
        "transport_mode": WALKING_TRANSPORT_MODE,
        "routes": {},
        "sample_routes_to_generate": [],
    }


def _load_cache(cache_path: str | Path) -> dict[str, Any]:
    path = Path(cache_path)
    if not path.exists():
        return _empty_cache()
    try:
        with path.open("r", encoding="utf-8") as file:
            cache = json.load(file)
    except (OSError, json.JSONDecodeError):
        return _empty_cache()
    if not isinstance(cache, dict):
        return _empty_cache()
    if (
        cache.get("version") != ROUTE_CACHE_VERSION
        or cache.get("provider") != "osrm"
        or cache.get("profile") != WALKING_PROFILE
        or cache.get("transport_mode") != WALKING_TRANSPORT_MODE
    ):
        return _empty_cache()
    cache.setdefault("routes", {})
    cache.setdefault("sample_routes_to_generate", [])
    return cache


def _save_cache(cache_path: str | Path, cache: dict[str, Any]) -> None:
    ensure_parent_dir(cache_path)
    with Path(cache_path).open("w", encoding="utf-8") as file:
        json.dump(cache, file, ensure_ascii=False, indent=2)


def _build_osrm_url(
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
    profile: str,
    base_url: str,
) -> tuple[str, str, dict[str, str]]:
    coordinates = f"{start_lon:.6f},{start_lat:.6f};{end_lon:.6f},{end_lat:.6f}"
    url = f"{base_url.rstrip('/')}/route/v1/{profile}/{coordinates}"
    params = {
        "overview": "full",
        "geometries": "geojson",
        "steps": "false",
    }
    return url, f"{url}?{urlencode(params)}", params


def _failure(
    error: str,
    *,
    osrm_url: str | None = None,
    profile: str | None = None,
    cache_key: str | None = None,
) -> dict[str, Any]:
    return {
        "success": False,
        "distance_m": None,
        "duration_s": None,
        "osrm_duration_s": None,
        "geometry_geojson": None,
        "folium_coordinates": [],
        "source": "osrm",
        "error": error,
        "cache_hit": False,
        "osrm_url": osrm_url,
        "profile": profile,
        "transport_mode": WALKING_TRANSPORT_MODE,
        "cache_key": cache_key,
    }


def _success(
    distance_m: float,
    osrm_duration_s: float,
    geometry_geojson: dict[str, Any],
    folium_coordinates: list[list[float]],
    *,
    cache_hit: bool,
    osrm_url: str,
    profile: str,
    cache_key: str,
) -> dict[str, Any]:
    duration_s, duration_source = resolve_walking_duration_s(distance_m, osrm_duration_s)
    return {
        "success": True,
        "distance_m": distance_m,
        "duration_s": duration_s,
        "osrm_duration_s": osrm_duration_s,
        "duration_source": duration_source,
        "geometry_geojson": geometry_geojson,
        "folium_coordinates": folium_coordinates,
        "source": "osrm",
        "error": None,
        "cache_hit": cache_hit,
        "osrm_url": osrm_url,
        "profile": profile,
        "transport_mode": WALKING_TRANSPORT_MODE,
        "cache_key": cache_key,
    }


def _is_walking_cache_entry(entry: dict[str, Any]) -> bool:
    osrm_url = str(entry.get("osrm_url") or "").lower()
    return (
        entry.get("success") is True
        and entry.get("profile") == WALKING_PROFILE
        and entry.get("transport_mode") == WALKING_TRANSPORT_MODE
        and "/route/v1/foot/" in osrm_url
        and "/driving/" not in osrm_url
        and "/bike/" not in osrm_url
        and "/bicycle/" not in osrm_url
    )


def get_osrm_route(
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
    profile: str = "foot",
    cache_path: str | Path = "data/route_cache.json",
    *,
    allow_network: bool = True,
    osrm_base_url: str | None = None,
    timeout: float = 10.0,
    ignore_cache: bool = False,
    persist_cache: bool = True,
) -> dict[str, Any]:
    """Fetch a route from OSRM, returning cached data when available."""
    normalized_profile = normalize_profile(profile)

    try:
        start_lat_f = float(start_lat)
        start_lon_f = float(start_lon)
        end_lat_f = float(end_lat)
        end_lon_f = float(end_lon)
    except (TypeError, ValueError):
        return _failure("Invalid coordinate input", profile=normalized_profile)

    base_url = (osrm_base_url or os.getenv("OSRM_BASE_URL") or DEFAULT_OSRM_BASE_URL).rstrip("/")
    url, osrm_url, params = _build_osrm_url(
        start_lat_f,
        start_lon_f,
        end_lat_f,
        end_lon_f,
        normalized_profile,
        base_url,
    )

    cache_key = make_route_cache_key(
        start_lat_f,
        start_lon_f,
        end_lat_f,
        end_lon_f,
        normalized_profile,
    )
    cache = _load_cache(cache_path) if persist_cache else _empty_cache()
    if persist_cache:
        cached = cache["routes"].get(cache_key)
        if isinstance(cached, dict) and _is_walking_cache_entry(cached) and not ignore_cache:
            result = dict(cached)
            result.setdefault("osrm_duration_s", result.get("duration_s"))
            result["duration_s"], result["duration_source"] = resolve_walking_duration_s(
                result.get("distance_m") or 0,
                result.get("osrm_duration_s"),
            )
            result["cache_hit"] = True
            result.setdefault("source", "osrm")
            result.setdefault("error", None)
            result.setdefault("osrm_url", osrm_url)
            result.setdefault("profile", normalized_profile)
            result.setdefault("transport_mode", WALKING_TRANSPORT_MODE)
            result.setdefault("cache_key", cache_key)
            return result

    if not allow_network:
        return _failure(
            "route_not_cached_demo_mode: Route is not in route_cache.json. "
            "Enable live OSRM to generate it.",
            osrm_url=osrm_url,
            profile=normalized_profile,
            cache_key=cache_key,
        )

    try:
        response = requests.get(url, params=params, timeout=timeout)
    except requests.exceptions.Timeout:
        return _failure(
            "OSRM request timed out",
            osrm_url=osrm_url,
            profile=normalized_profile,
            cache_key=cache_key,
        )
    except requests.exceptions.RequestException as exc:
        return _failure(
            f"OSRM network error: {exc}",
            osrm_url=osrm_url,
            profile=normalized_profile,
            cache_key=cache_key,
        )

    if response.status_code != 200:
        return _failure(
            f"OSRM returned HTTP {response.status_code}: {response.text[:200]}",
            osrm_url=osrm_url,
            profile=normalized_profile,
            cache_key=cache_key,
        )

    try:
        payload = response.json()
    except ValueError:
        return _failure(
            "OSRM returned invalid JSON",
            osrm_url=osrm_url,
            profile=normalized_profile,
            cache_key=cache_key,
        )

    routes = payload.get("routes") if isinstance(payload, dict) else None
    if not routes:
        return _failure(
            "OSRM returned no routes",
            osrm_url=osrm_url,
            profile=normalized_profile,
            cache_key=cache_key,
        )

    route = routes[0]
    geometry = route.get("geometry")
    if not isinstance(geometry, dict) or geometry.get("type") != "LineString":
        return _failure(
            "OSRM route geometry is missing or not a LineString",
            osrm_url=osrm_url,
            profile=normalized_profile,
            cache_key=cache_key,
        )

    geojson_coordinates = geometry.get("coordinates")
    if not isinstance(geojson_coordinates, list) or not geojson_coordinates:
        return _failure(
            "OSRM route geometry coordinates are empty",
            osrm_url=osrm_url,
            profile=normalized_profile,
            cache_key=cache_key,
        )

    folium_coordinates = convert_geojson_to_folium_coordinates(geojson_coordinates)
    if not folium_coordinates:
        return _failure(
            "Converted Folium route coordinates are empty",
            osrm_url=osrm_url,
            profile=normalized_profile,
            cache_key=cache_key,
        )

    result = _success(
        distance_m=float(route.get("distance", 0)),
        osrm_duration_s=float(route.get("duration", 0)),
        geometry_geojson=geometry,
        folium_coordinates=folium_coordinates,
        cache_hit=False,
        osrm_url=osrm_url,
        profile=normalized_profile,
        cache_key=cache_key,
    )

    if persist_cache:
        cache["routes"][cache_key] = {
            **result,
            "cache_hit": False,
            "cached_at": datetime.now(timezone.utc).isoformat(),
        }
        _save_cache(cache_path, cache)
    return result
