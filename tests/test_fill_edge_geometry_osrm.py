import json
from unittest.mock import Mock

import pandas as pd

from tools.fill_edge_geometry_osrm import (
    fetch_osrm_edge_route,
    fill_edge_geometries,
)


def _write_places(path):
    pd.DataFrame(
        [
            {
                "id": "a",
                "name": "A",
                "display_name": "A",
                "category": "intersection",
                "latitude": "24.1",
                "longitude": "120.1",
                "source": "manual",
                "notes": "verified",
            },
            {
                "id": "b",
                "name": "B",
                "display_name": "B",
                "category": "intersection",
                "latitude": "24.2",
                "longitude": "120.2",
                "source": "manual",
                "notes": "verified",
            },
        ]
    ).to_csv(path, index=False)


def _write_edges(path):
    pd.DataFrame(
        [
            {
                "from_id": "a",
                "to_id": "b",
                "distance_m": "100",
                "stairs": "0",
                "rain_friendly": "1",
                "road_name": "Test Road",
                "description": "",
                "geometry": "",
            }
        ]
    ).to_csv(path, index=False)


def test_fetch_osrm_edge_route_converts_coordinates():
    response = Mock()
    response.json.return_value = {
        "routes": [
            {
                "distance": 123.4,
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[120.1, 24.1], [120.2, 24.2]],
                },
            }
        ]
    }
    session = Mock()
    session.get.return_value = response

    coordinates, distance = fetch_osrm_edge_route(
        24.1,
        120.1,
        24.2,
        120.2,
        session=session,
    )

    called_url = session.get.call_args.args[0]
    assert "/120.100000,24.100000;120.200000,24.200000" in called_url
    assert "/route/v1/foot/" in called_url
    assert "/driving/" not in called_url
    assert session.get.call_args.kwargs["params"] == {
        "overview": "full",
        "geometries": "geojson",
    }
    assert coordinates == [[120.1, 24.1], [120.2, 24.2]]
    assert distance == 123.4


def test_fill_edge_geometries_writes_new_file_and_updates_distance(tmp_path):
    places_path = tmp_path / "places.csv"
    edges_path = tmp_path / "campus_edges.csv"
    output_path = tmp_path / "campus_edges_filled.csv"
    _write_places(places_path)
    _write_edges(edges_path)

    response = Mock()
    response.json.return_value = {
        "routes": [
            {
                "distance": 222.5,
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[120.1, 24.1], [120.2, 24.2]],
                },
            }
        ]
    }
    session = Mock()
    session.get.return_value = response

    filled, failed = fill_edge_geometries(
        places_path,
        edges_path,
        output_path,
        sleep_seconds=0,
        session=session,
    )

    result = pd.read_csv(output_path)
    assert filled == 1
    assert failed == 0
    assert set(pd.read_csv(places_path)["id"]) == {"a", "b"}
    assert len(result) == 1
    assert result.loc[0, "from_id"] == "a"
    assert result.loc[0, "to_id"] == "b"
    assert edges_path.read_text(encoding="utf-8").endswith('Test Road,,\n')
    assert result.loc[0, "distance_m"] == 222.5
    assert json.loads(result.loc[0, "geometry"]) == [[120.1, 24.1], [120.2, 24.2]]


def test_fill_edge_geometries_continues_after_osrm_failure(tmp_path):
    places_path = tmp_path / "places.csv"
    edges_path = tmp_path / "campus_edges.csv"
    output_path = tmp_path / "campus_edges_filled.csv"
    _write_places(places_path)
    _write_edges(edges_path)
    edges_df = pd.read_csv(edges_path)
    edges_df = pd.concat([edges_df, edges_df], ignore_index=True)
    edges_df.to_csv(edges_path, index=False)

    failed_response = Mock()
    failed_response.raise_for_status.side_effect = ValueError("bad response")
    successful_response = Mock()
    successful_response.json.return_value = {
        "routes": [
            {
                "distance": 100,
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[120.1, 24.1], [120.2, 24.2]],
                },
            }
        ]
    }
    session = Mock()
    session.get.side_effect = [failed_response, successful_response]

    filled, failed = fill_edge_geometries(
        places_path,
        edges_path,
        output_path,
        sleep_seconds=0,
        session=session,
    )

    assert filled == 1
    assert failed == 1
    assert output_path.exists()


def test_fill_edge_geometries_rejects_unreasonably_long_osrm_route(tmp_path):
    places_path = tmp_path / "places.csv"
    edges_path = tmp_path / "campus_edges.csv"
    output_path = tmp_path / "campus_edges_filled.csv"
    _write_places(places_path)
    _write_edges(edges_path)

    response = Mock()
    response.json.return_value = {
        "routes": [
            {
                "distance": 1000,
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[120.1, 24.1], [120.2, 24.2]],
                },
            }
        ]
    }
    session = Mock()
    session.get.return_value = response

    filled, failed = fill_edge_geometries(
        places_path,
        edges_path,
        output_path,
        sleep_seconds=0,
        session=session,
    )

    result = pd.read_csv(output_path, keep_default_na=False)
    assert filled == 0
    assert failed == 1
    assert result.loc[0, "geometry"] == ""
    assert float(result.loc[0, "distance_m"]) == 100


def test_ignore_osrm_edge_is_skipped_without_api_call(tmp_path):
    places_path = tmp_path / "places.csv"
    edges_path = tmp_path / "campus_edges.csv"
    output_path = tmp_path / "campus_edges_filled.csv"
    _write_places(places_path)
    _write_edges(edges_path)
    edges = pd.read_csv(edges_path)
    edges["ignore_osrm"] = "1"
    edges["routing_source"] = "manual"
    edges["verified"] = "1"
    edges["enabled"] = "1"
    edges.to_csv(edges_path, index=False)
    session = Mock()

    filled, failed = fill_edge_geometries(
        places_path,
        edges_path,
        output_path,
        sleep_seconds=0,
        session=session,
    )

    assert filled == 0
    assert failed == 0
    session.get.assert_not_called()
    assert output_path.exists()
