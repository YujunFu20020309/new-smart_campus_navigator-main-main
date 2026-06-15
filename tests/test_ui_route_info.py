from contextlib import nullcontext
from unittest.mock import Mock, patch

from src.ui_route_info import render_gps_campus_snap_debug


def _snap_failure():
    return {
        "success": False,
        "source": "gps_campus_graph",
        "error": "technical snap error",
        "fallback_reason": "snap_distance_exceeded",
        "snap_failure_reason": "max_distance_exceeded",
        "snapped_start_id": "reachable_far",
        "snapped_start_name": "Reachable Far Node",
        "snap_distance_m": 452.4,
        "snap_limit_m": 250.0,
        "snapped_start_latitude": 24.7999,
        "snapped_start_longitude": 120.9937,
    }


def test_gps_campus_snap_debug_is_hidden_when_debug_is_disabled():
    with patch("src.ui_route_info.st") as streamlit:
        rendered = render_gps_campus_snap_debug(
            _snap_failure(),
            end_id="destination",
            enabled=False,
        )

    assert rendered is False
    streamlit.expander.assert_not_called()
    streamlit.write.assert_not_called()
    streamlit.code.assert_not_called()


def test_gps_campus_snap_debug_shows_diagnostics_when_enabled():
    streamlit = Mock()
    streamlit.expander.return_value = nullcontext()

    with patch("src.ui_route_info.st", streamlit):
        rendered = render_gps_campus_snap_debug(
            _snap_failure(),
            end_id="destination",
            enabled=True,
        )

    assert rendered is True
    streamlit.expander.assert_called_once_with("GPS Campus Snap Debug")
    debug_text = "\n".join(call.args[0] for call in streamlit.write.call_args_list)
    assert "reachable_far" in debug_text
    assert "Reachable Far Node" in debug_text
    assert "452.4" in debug_text
    assert "250.0" in debug_text
    assert "destination" in debug_text
    streamlit.code.assert_called_once_with("technical snap error")
