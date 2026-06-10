"""NetworkX campus road graph routing helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import networkx as nx
import pandas as pd

from .geo_utils import estimate_walking_duration_s, haversine_distance_m
from .utils import get_place_by_id, parse_coordinate, validate_places


REQUIRED_EDGE_COLUMNS = [
    "from_id",
    "to_id",
    "distance_m",
    "stairs",
    "rain_friendly",
    "road_name",
    "description",
    "geometry",
    "routing_source",
    "ignore_osrm",
    "verified",
    "enabled",
]
EDGE_COLUMN_DEFAULTS = {
    "routing_source": "manual",
    "ignore_osrm": "0",
    "verified": "0",
    "enabled": "1",
}

ROAD_NODE_CATEGORIES = {"intersection", "road_node", "waypoint"}
DESTINATION_LIKE_CATEGORIES = {"building", "gate", "landmark"}
MAX_SHORT_CONNECTOR_M = 30.0


def load_edges(edges_csv: str | Path) -> pd.DataFrame:
    """Load campus_edges.csv and validate required columns."""
    path = Path(edges_csv)
    if not path.exists():
        raise FileNotFoundError(f"Campus edges CSV not found: {path}")
    df = ensure_edge_control_columns(pd.read_csv(path, dtype=str, keep_default_na=False))
    validate_campus_edges(df)
    return df.fillna("")


def load_campus_edges(csv_path: str | Path) -> pd.DataFrame:
    """Backward-compatible alias for load_edges."""
    return load_edges(csv_path)


def validate_campus_edges(df: pd.DataFrame) -> bool:
    """Validate campus_edges.csv columns."""
    missing = [column for column in REQUIRED_EDGE_COLUMNS if column not in df.columns]
    if missing:
        raise ValueError(f"campus_edges.csv missing required columns: {', '.join(missing)}")
    return True


def ensure_edge_control_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add/fill optional routing control columns for legacy campus edge CSV files."""
    result = df.copy().fillna("")
    for column, default in EDGE_COLUMN_DEFAULTS.items():
        if column not in result.columns:
            result[column] = default
        else:
            blank = result[column].astype(str).str.strip().eq("")
            result.loc[blank, column] = default
    return result


def _to_flag(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def edge_is_bidirectional(edge_data: dict[str, Any] | pd.Series) -> bool:
    """Return whether an edge should be usable in both directions.

    Legacy campus_edges.csv rows are bidirectional by default. Explicit
    one_way=1 or bidirectional=0 makes an edge one-way.
    """
    if "one_way" in edge_data and _to_flag(edge_data.get("one_way")):
        return False
    if "bidirectional" in edge_data:
        value = str(edge_data.get("bidirectional", "")).strip().lower()
        if value in {"0", "false", "no", "n"}:
            return False
    return True


def _to_distance(value: Any) -> float:
    try:
        distance = float(value)
    except (TypeError, ValueError):
        distance = 0.0
    return max(distance, 0.0)


def is_road_node(row: dict[str, Any] | pd.Series) -> bool:
    """Return True for internal intersection, road_node, and waypoint nodes."""
    return str(row.get("category", "")).strip().lower() in ROAD_NODE_CATEGORIES


def is_destination_like(row: dict[str, Any] | pd.Series) -> bool:
    """Return True for building, gate, and landmark nodes."""
    return str(row.get("category", "")).strip().lower() in DESTINATION_LIKE_CATEGORIES


def is_safe_straight_edge(
    from_node: dict[str, Any] | pd.Series,
    to_node: dict[str, Any] | pd.Series,
    edge_data: dict[str, Any] | pd.Series,
) -> bool:
    """Return True when an edge may safely use a direct fallback line."""
    if edge_data.get("geometry"):
        return True
    if _to_distance(edge_data.get("distance_m")) <= MAX_SHORT_CONNECTOR_M:
        return True
    if _to_flag(edge_data.get("verified")):
        return True
    description = str(edge_data.get("description", "")).strip().lower()
    return "verified_straight" in description or "straight_ok" in description


def _parse_geometry(value: Any) -> list[list[float]]:
    """Parse stored [lon, lat] geometry into internal/Folium [lat, lon] points."""
    if value is None or str(value).strip() == "":
        return []
    try:
        payload = json.loads(str(value))
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []

    coordinates: list[list[float]] = []
    for point in payload:
        if not isinstance(point, list) or len(point) < 2:
            continue
        lon = parse_coordinate(point[0])
        lat = parse_coordinate(point[1])
        if lat is not None and lon is not None:
            coordinates.append([lat, lon])
    return coordinates


def _edge_cost(edge_data: dict[str, Any], mode: str) -> float:
    distance = float(edge_data.get("distance_m", 0.0))
    if mode == "avoid_stairs":
        return distance + (500.0 if edge_data.get("stairs") else 0.0)
    if mode == "rain_friendly":
        return distance * (0.85 if edge_data.get("rain_friendly") else 1.25)
    return distance


def _folium_polyline_distance_m(points: list[list[float]]) -> float:
    return sum(
        haversine_distance_m(start[0], start[1], end[0], end[1])
        for start, end in zip(points, points[1:])
    )


def _actual_edge_distance_m(
    graph: nx.Graph,
    from_id: str,
    to_id: str,
    *,
    stored_distance_m: float,
    geometry: list[list[float]],
    routing_source: str,
) -> float:
    """Use OSRM distance for OSRM edges and Haversine distance for custom lines."""
    if routing_source == "osrm" and stored_distance_m > 0:
        return stored_distance_m
    if len(geometry) >= 2:
        return _folium_polyline_distance_m(geometry)

    start_lat = parse_coordinate(graph.nodes[from_id].get("latitude"))
    start_lon = parse_coordinate(graph.nodes[from_id].get("longitude"))
    end_lat = parse_coordinate(graph.nodes[to_id].get("latitude"))
    end_lon = parse_coordinate(graph.nodes[to_id].get("longitude"))
    if None not in (start_lat, start_lon, end_lat, end_lon):
        return haversine_distance_m(start_lat, start_lon, end_lat, end_lon)
    return stored_distance_m


def _weight_for_mode(mode: str) -> Callable[[str, str, dict[str, Any]], float]:
    return lambda _u, _v, edge_data: _edge_cost(edge_data, mode)


def build_campus_graph(places_df: pd.DataFrame, edges_df: pd.DataFrame) -> nx.DiGraph:
    """Build a directed graph whose legacy enabled campus edges default to two-way."""
    validate_places(places_df)
    edges_df = ensure_edge_control_columns(edges_df)
    validate_campus_edges(edges_df)

    graph = nx.DiGraph()
    place_ids = set(places_df["id"].astype(str))

    for _, row in places_df.iterrows():
        place_id = str(row["id"])
        node_attrs = row.to_dict()
        node_attrs["latitude"] = parse_coordinate(row.get("latitude"))
        node_attrs["longitude"] = parse_coordinate(row.get("longitude"))
        graph.add_node(place_id, **node_attrs)

    for _, row in edges_df.iterrows():
        from_id = str(row.get("from_id", "")).strip()
        to_id = str(row.get("to_id", "")).strip()
        if not from_id or not to_id:
            continue
        if from_id not in place_ids or to_id not in place_ids:
            raise ValueError(f"Edge references unknown place id: {from_id} -> {to_id}")
        if not _to_flag(row.get("enabled")):
            continue

        stored_distance_m = _to_distance(row.get("distance_m"))
        geometry = _parse_geometry(row.get("geometry"))
        routing_source = str(row.get("routing_source", "manual")).strip().lower() or "manual"
        distance_m = _actual_edge_distance_m(
            graph,
            from_id,
            to_id,
            stored_distance_m=stored_distance_m,
            geometry=geometry,
            routing_source=routing_source,
        )
        stairs = _to_flag(row.get("stairs"))
        rain_friendly = _to_flag(row.get("rain_friendly"))
        edge_attrs = {
            "distance_m": distance_m,
            "stairs": stairs,
            "rain_friendly": rain_friendly,
            "road_name": row.get("road_name", ""),
            "description": row.get("description", ""),
            "geometry": geometry,
            "routing_source": routing_source,
            "ignore_osrm": _to_flag(row.get("ignore_osrm")),
            "verified": _to_flag(row.get("verified")),
            "enabled": _to_flag(row.get("enabled")),
        }
        graph.add_edge(from_id, to_id, **edge_attrs)
        if edge_is_bidirectional(row):
            reverse_attrs = dict(edge_attrs)
            reverse_attrs["geometry"] = list(reversed(edge_attrs["geometry"]))
            graph.add_edge(to_id, from_id, **reverse_attrs)
            print("Campus edge treated as bidirectional:", from_id, to_id)

    graph.graph["places_df"] = places_df.copy()
    return graph


def _failure(error: str, mode: str = "campus") -> dict[str, Any]:
    return {
        "success": False,
        "distance_m": None,
        "duration_s": None,
        "cost": None,
        "folium_coordinates": [],
        "path_ids": [],
        "path_names": [],
        "edge_segments": [],
        "source": "local_graph",
        "mode": mode,
        "error": error,
    }


def compute_campus_route(
    graph: nx.Graph,
    start_id: str,
    end_id: str,
    mode: str = "campus",
) -> dict[str, Any]:
    """Compute the global minimum-cost local route using NetworkX weighted shortest path.

    Conceptually this is Dijkstra-style routing: places.csv supplies nodes,
    campus_edges.csv supplies traversable edges, and distance_m/mode cost supplies
    edge weights. It minimizes total route cost from start_id to end_id; it is not
    greedy and does not choose the next node merely because it is closer to the goal.
    """
    if start_id == end_id:
        return _failure("Start and end are the same.", mode)
    if start_id not in graph:
        return _failure(f"Start node not found: {start_id}", mode)
    if end_id not in graph:
        return _failure(f"End node not found: {end_id}", mode)

    weight = _weight_for_mode(mode)
    try:
        path = nx.shortest_path(graph, source=start_id, target=end_id, weight=weight)
        cost = nx.shortest_path_length(graph, source=start_id, target=end_id, weight=weight)
    except (nx.NetworkXNoPath, nx.NodeNotFound) as exc:
        return _failure(str(exc), mode)

    places_df = graph.graph.get("places_df")
    if not isinstance(places_df, pd.DataFrame):
        places_df = pd.DataFrame([graph.nodes[node_id] for node_id in graph.nodes])
    return path_to_route_result(path, graph, places_df, mode=mode, cost=float(cost))


def _node_coordinate(graph: nx.Graph, node_id: str) -> list[float] | None:
    lat = parse_coordinate(graph.nodes[node_id].get("latitude"))
    lon = parse_coordinate(graph.nodes[node_id].get("longitude"))
    if lat is None or lon is None:
        return None
    return [lat, lon]


def _append_coordinates(
    target: list[list[float]],
    segment: list[list[float]],
) -> None:
    for point in segment:
        if not target or target[-1] != point:
            target.append(point)


def path_to_route_result(
    path: list[str],
    graph: nx.Graph,
    places_df: pd.DataFrame,
    *,
    mode: str = "campus",
    cost: float | None = None,
) -> dict[str, Any]:
    """Convert a graph path into a route_result compatible with map_view."""
    if not path:
        return _failure("Empty path.", mode)

    distance_m = 0.0
    route_cost = 0.0 if cost is None else float(cost)
    folium_coordinates: list[list[float]] = []
    edge_segments: list[dict[str, Any]] = []

    for node_id in path:
        if node_id not in graph:
            return _failure(f"Path node not found in graph: {node_id}", mode)

    for from_id, to_id in zip(path, path[1:]):
        edge_data = graph.get_edge_data(from_id, to_id)
        if not edge_data:
            return _failure(f"Path edge not found: {from_id} -> {to_id}", mode)
        distance_m += float(edge_data.get("distance_m", 0.0))
        if cost is None:
            route_cost += _edge_cost(edge_data, mode)

        geometry = edge_data.get("geometry") or []
        if geometry:
            segment = geometry
        else:
            if not is_safe_straight_edge(
                graph.nodes[from_id],
                graph.nodes[to_id],
                edge_data,
            ):
                return _failure(
                    "Edge missing geometry and unsafe to draw as straight line: "
                    f"{from_id} -> {to_id}",
                    mode,
                )
            from_coordinate = _node_coordinate(graph, from_id)
            to_coordinate = _node_coordinate(graph, to_id)
            if from_coordinate is None or to_coordinate is None:
                return _failure(f"Missing coordinates for path segment: {from_id} -> {to_id}", mode)
            segment = [from_coordinate, to_coordinate]
        _append_coordinates(folium_coordinates, segment)
        edge_segments.append(
            {
                "from_id": from_id,
                "to_id": to_id,
                "road_name": edge_data.get("road_name", ""),
                "routing_source": edge_data.get("routing_source", "manual"),
                "ignore_osrm": bool(edge_data.get("ignore_osrm")),
                "verified": bool(edge_data.get("verified")),
                "distance_m": float(edge_data.get("distance_m", 0.0)),
                "geometry_point_count": len(edge_data.get("geometry") or []),
            }
        )

    if len(path) == 1:
        coordinate = _node_coordinate(graph, path[0])
        if coordinate:
            folium_coordinates.append(coordinate)

    try:
        path_names = [
            get_place_by_id(places_df, node_id).get("display_name")
            or get_place_by_id(places_df, node_id).get("name")
            or node_id
            for node_id in path
        ]
    except KeyError:
        path_names = path[:]

    return {
        "success": True,
        "distance_m": distance_m,
        "duration_s": estimate_walking_duration_s(distance_m),
        "duration_source": "walking_speed_estimate",
        "cost": route_cost,
        "folium_coordinates": folium_coordinates,
        "path_ids": path,
        "path_names": path_names,
        "edge_segments": edge_segments,
        "source": "local_graph",
        "mode": mode,
        "error": None,
    }


def calculate_shortest_path(
    graph: nx.Graph,
    start_id: str,
    end_id: str,
    *,
    weight: str = "distance_m",
) -> dict[str, Any]:
    """Backward-compatible shortest path helper."""
    try:
        path = nx.shortest_path(graph, source=start_id, target=end_id, weight=weight)
        distance = nx.shortest_path_length(graph, source=start_id, target=end_id, weight=weight)
    except (nx.NetworkXNoPath, nx.NodeNotFound) as exc:
        return {"success": False, "path": [], "distance_m": None, "error": str(exc)}
    return {"success": True, "path": path, "distance_m": distance, "error": None}


def is_graph_ready(graph: nx.Graph) -> bool:
    """Return True when the graph has at least one node and one edge."""
    return graph.number_of_nodes() > 0 and graph.number_of_edges() > 0
