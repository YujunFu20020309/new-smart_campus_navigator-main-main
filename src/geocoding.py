"""Nominatim geocoding with local JSON cache protection."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from .utils import (
    append_note,
    ensure_parent_dir,
    is_blank,
    is_geocoding_protected,
    load_places,
)


NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
DEFAULT_USER_AGENT = (
    "NTHU-Smart-Campus-Navigator/1.0 "
    "(course-demo; contact: local-demo@example.com)"
)


def make_geocode_cache_key(query: str, country_codes: str | list[str] | None = None) -> str:
    """Build a stable cache key for a Nominatim query."""
    normalized_query = " ".join(str(query).strip().lower().split())
    if isinstance(country_codes, list):
        country_part = ",".join(sorted(code.lower() for code in country_codes))
    else:
        country_part = "" if country_codes is None else str(country_codes).lower()
    return f"{normalized_query}|country={country_part}"


def _empty_cache() -> dict[str, Any]:
    return {"version": 1, "provider": "nominatim", "items": {}}


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
    cache.setdefault("version", 1)
    cache.setdefault("provider", "nominatim")
    cache.setdefault("items", {})
    return cache


def _save_cache(cache_path: str | Path, cache: dict[str, Any]) -> None:
    ensure_parent_dir(cache_path)
    with Path(cache_path).open("w", encoding="utf-8") as file:
        json.dump(cache, file, ensure_ascii=False, indent=2)


def _failure(error: str, *, source: str = "nominatim", from_cache: bool = False) -> dict[str, Any]:
    return {
        "success": False,
        "latitude": None,
        "longitude": None,
        "display_name": None,
        "raw_response": None,
        "source": source,
        "from_cache": from_cache,
        "error": error,
    }


def _validate_user_agent(user_agent: str) -> None:
    if is_blank(user_agent) or "python-requests" in str(user_agent).lower():
        raise ValueError("A specific Nominatim User-Agent is required.")


def geocode_place(
    query: str,
    cache_path: str | Path,
    user_agent: str,
    country_codes: str | list[str] | None = None,
    *,
    sleep_seconds: float = 1.0,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """Geocode one place with Nominatim, using cache before any API call."""
    _validate_user_agent(user_agent)
    if is_blank(query):
        return _failure("empty query")

    cache = _load_cache(cache_path)
    cache_key = make_geocode_cache_key(query, country_codes)
    cached = cache["items"].get(cache_key)
    if isinstance(cached, dict):
        result = dict(cached)
        result["from_cache"] = True
        result.setdefault("source", "cache")
        result.setdefault("error", None)
        return result

    params: dict[str, Any] = {
        "q": query,
        "format": "jsonv2",
        "limit": 1,
        "addressdetails": 1,
    }
    if country_codes:
        params["countrycodes"] = (
            ",".join(country_codes) if isinstance(country_codes, list) else country_codes
        )

    headers = {"User-Agent": user_agent}

    try:
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)
        response = requests.get(NOMINATIM_URL, params=params, headers=headers, timeout=timeout)
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)
        response.raise_for_status()
        payload = response.json()
    except requests.exceptions.Timeout:
        return _failure("Nominatim request timed out")
    except requests.exceptions.RequestException as exc:
        return _failure(f"Nominatim network error: {exc}")
    except ValueError:
        return _failure("Nominatim returned invalid JSON")

    if not isinstance(payload, list) or not payload:
        result = _failure("Nominatim returned no results")
        cache["items"][cache_key] = {
            **result,
            "cached_at": datetime.now(timezone.utc).isoformat(),
        }
        _save_cache(cache_path, cache)
        return result

    item = payload[0]
    try:
        latitude = float(item["lat"])
        longitude = float(item["lon"])
    except (KeyError, TypeError, ValueError):
        return _failure("Nominatim response missing valid lat/lon")

    result = {
        "success": True,
        "latitude": latitude,
        "longitude": longitude,
        "display_name": item.get("display_name"),
        "raw_response": item,
        "source": "nominatim",
        "from_cache": False,
        "error": None,
    }
    cache["items"][cache_key] = {
        **result,
        "cached_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_cache(cache_path, cache)
    return result


def update_missing_coordinates(
    places_csv: str | Path,
    cache_path: str | Path,
    *,
    user_agent: str = DEFAULT_USER_AGENT,
    country_codes: str | list[str] | None = "tw",
    sleep_seconds: float = 1.0,
) -> dict[str, Any]:
    """Fill blank latitude/longitude rows in places.csv by querying Nominatim."""
    df = load_places(places_csv)
    updated = 0
    failed = 0
    protected_skipped = 0
    skipped = 0
    failures: list[str] = []

    for index, row in df.iterrows():
        if is_geocoding_protected(row):
            protected_skipped += 1
            skipped += 1
            continue

        has_lat = not is_blank(row.get("latitude"))
        has_lon = not is_blank(row.get("longitude"))
        if has_lat and has_lon:
            skipped += 1
            continue

        query = row.get("name") or row.get("display_name")
        result = geocode_place(
            str(query),
            cache_path,
            user_agent,
            country_codes,
            sleep_seconds=sleep_seconds,
        )
        if result["success"]:
            df.at[index, "latitude"] = result["latitude"]
            df.at[index, "longitude"] = result["longitude"]
            df.at[index, "source"] = "nominatim"
            df.at[index, "notes"] = append_note(row.get("notes"), "geocoded_by_nominatim")
            updated += 1
        else:
            df.at[index, "notes"] = append_note(row.get("notes"), "geocoding_failed")
            failures.append(f"{row.get('id')}: {result['error']}")
            failed += 1

    df.to_csv(places_csv, index=False)
    return {
        "updated": updated,
        "failed": failed,
        "protected_skipped": protected_skipped,
        "skipped": skipped,
        "failures": failures,
    }
