"""Browser geolocation UI built with Streamlit Custom Components v2."""

from __future__ import annotations

from typing import Any

import streamlit as st


_GEOLOCATION_HTML = """
<div class="geolocation-root">
  <button type="button" data-testid="request-location">Use my current location</button>
  <span data-testid="location-status" role="status" aria-live="polite"></span>
</div>
"""

_GEOLOCATION_CSS = """
.geolocation-root {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-wrap: wrap;
}

button {
  border: 0;
  border-radius: var(--st-button-border-radius, 0.5rem);
  padding: 0.55rem 0.85rem;
  color: white;
  background: var(--st-primary-color);
  cursor: pointer;
  font: inherit;
}

button:disabled {
  cursor: wait;
  opacity: 0.65;
}

[data-testid="location-status"] {
  color: var(--st-text-color);
  font-size: 0.9rem;
}
"""

_GEOLOCATION_JS = """
export default function (component) {
  const { data, parentElement, setTriggerValue } = component
  const button = parentElement.querySelector('[data-testid="request-location"]')
  const status = parentElement.querySelector('[data-testid="location-status"]')
  if (!button || !status) return

  button.textContent = data?.button_label ?? "Use my current location"

  button.onclick = () => {
    if (!navigator.geolocation) {
      setTriggerValue("location", {
        status: "error",
        error_code: 0,
        error_message: "Browser geolocation is not supported.",
      })
      return
    }

    button.disabled = true
    status.textContent = data?.requesting_label ?? "Requesting browser location..."

    navigator.geolocation.getCurrentPosition(
      (position) => {
        const coords = position.coords
        setTriggerValue("location", {
          status: "success",
          latitude: coords.latitude,
          longitude: coords.longitude,
          accuracy_m: Number.isFinite(coords.accuracy) ? coords.accuracy : null,
          timestamp_ms: Number.isFinite(position.timestamp) ? position.timestamp : null,
        })
      },
      (error) => {
        setTriggerValue("location", {
          status: "error",
          error_code: Number.isFinite(error.code) ? error.code : 0,
          error_message: error.message || "Browser geolocation failed.",
        })
      },
      {
        enableHighAccuracy: true,
        timeout: data?.timeout_ms ?? 10000,
        maximumAge: data?.maximum_age_ms ?? 0,
      },
    )
  }
}
"""

_GEOLOCATION_COMPONENT = st.components.v2.component(
    "nthu_browser_geolocation",
    html=_GEOLOCATION_HTML,
    css=_GEOLOCATION_CSS,
    js=_GEOLOCATION_JS,
)


def request_browser_location(
    *,
    key: str = "browser_geolocation",
    button_label: str = "Use my current location",
    requesting_label: str = "Requesting browser location...",
    timeout_ms: int = 10_000,
    maximum_age_ms: int = 0,
) -> dict[str, Any] | None:
    """Render a geolocation button and return its latest one-shot event payload."""
    result = _GEOLOCATION_COMPONENT(
        key=key,
        data={
            "button_label": button_label,
            "requesting_label": requesting_label,
            "timeout_ms": timeout_ms,
            "maximum_age_ms": maximum_age_ms,
        },
        on_location_change=lambda: None,
    )
    payload = getattr(result, "location", None)
    return payload if isinstance(payload, dict) else None
