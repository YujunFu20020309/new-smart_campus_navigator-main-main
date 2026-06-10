import pytest

from src.geo_utils import (
    DEFAULT_WALKING_SPEED_MPS,
    estimate_walking_duration_s,
    haversine_distance_m,
    parse_geometry_points_text,
    polyline_distance_m,
    resolve_walking_duration_s,
)


def test_haversine_distance_m_basic():
    distance = haversine_distance_m(24.795, 120.995, 24.796, 120.995)

    assert 110 < distance < 112


def test_polyline_distance_m_basic():
    distance = polyline_distance_m(
        [[120.995, 24.795], [120.995, 24.796], [120.995, 24.797]]
    )

    assert 220 < distance < 224


def test_parse_geometry_points_text_accepts_lon_lat_lines():
    points = parse_geometry_points_text(
        "120.9966,24.7964\n\n120.9957, 24.7962\n"
    )

    assert points == [[120.9966, 24.7964], [120.9957, 24.7962]]


def test_parse_geometry_points_text_rejects_lat_lon():
    with pytest.raises(ValueError, match="座標順序疑似反了"):
        parse_geometry_points_text("24.7964,120.9966")


def test_estimate_walking_duration_uses_14_mps():
    assert DEFAULT_WALKING_SPEED_MPS == 1.4
    assert estimate_walking_duration_s(140) == 100


def test_one_kilometer_walking_time_is_not_below_ten_minutes():
    duration_s, source = resolve_walking_duration_s(1000, 120)

    assert duration_s >= 600
    assert source == "walking_speed_fallback"


def test_plausible_osrm_foot_duration_is_preserved():
    duration_s, source = resolve_walking_duration_s(1000, 720)

    assert duration_s == 720
    assert source == "osrm_foot"
