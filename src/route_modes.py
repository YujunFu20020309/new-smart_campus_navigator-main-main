"""Route mode definitions for Safety MVP and future advanced modes."""

from __future__ import annotations

from typing import Any


CAMPUS_MODE_ID = "campus"
OSRM_MODE_ID = "osrm"
RAIN_MODE_ID = "rain_friendly"
COMPARE_MODE_ID = "compare"

# Backward-compatible names for existing imports. The values sent by the UI
# and route dispatcher are the explicit public mode IDs above.
LOCAL_GRAPH_MODE_ID = CAMPUS_MODE_ID
SAFETY_MODE_ID = OSRM_MODE_ID

ROUTE_MODES: dict[str, dict[str, Any]] = {
    OSRM_MODE_ID: {
        "label": "OSRM 路線",
        "description": "Safety MVP route from OSRM Route API.",
        "advanced": False,
        "source": "osrm",
    },
    CAMPUS_MODE_ID: {
        "label": "校園路線",
        "description": "Local campus road graph route for the course demo.",
        "advanced": False,
        "source": "local_graph",
    },
    RAIN_MODE_ID: {
        "label": "雨天路線",
        "description": "Rain route mode with rain-specific forced rules and OSRM fallback.",
        "advanced": False,
        "source": "rain_friendly",
    },
    COMPARE_MODE_ID: {
        "label": "路線比較",
        "description": "Compare independently calculated OSRM and campus routes.",
        "advanced": False,
        "source": "comparison",
    },
    "avoid_stairs": {
        "label": "避開樓梯模式",
        "description": "Advanced local graph mode planned for the next phase.",
        "advanced": True,
    },
}


def get_available_modes(*, include_advanced: bool = False) -> dict[str, dict[str, Any]]:
    """Return route modes that should be visible in the current phase."""
    if include_advanced:
        return dict(ROUTE_MODES)
    return {
        mode_id: config
        for mode_id, config in ROUTE_MODES.items()
        if not config.get("advanced", False)
    }


def get_route_mode_config(mode_id: str) -> dict[str, Any]:
    """Return one route mode configuration."""
    if mode_id not in ROUTE_MODES:
        raise KeyError(f"Unknown route mode: {mode_id}")
    return ROUTE_MODES[mode_id]


def is_advanced_mode(mode_id: str) -> bool:
    """Return True when a mode belongs to the future advanced phase."""
    return bool(get_route_mode_config(mode_id).get("advanced", False))
