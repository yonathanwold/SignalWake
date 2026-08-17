"""Small, deterministic GeoJSON primitives used by SQLite tests and import validation.

PostGIS is the production query engine. These helpers deliberately cover only the
Point, LineString, and Polygon shapes accepted by the Phase 2 importer so tests can
exercise the same boundary without a spatial database or network access.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any

SUPPORTED_GEOMETRIES = {"Point", "LineString", "Polygon"}
EARTH_RADIUS_KM = 6371.0088


class GeometryValidationError(ValueError):
    pass


def _coordinate(value: Any) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        raise GeometryValidationError("coordinate must contain longitude and latitude")
    try:
        longitude = float(value[0])
        latitude = float(value[1])
    except (TypeError, ValueError) as exc:
        raise GeometryValidationError("coordinate values must be numeric") from exc
    if not math.isfinite(longitude) or not math.isfinite(latitude):
        raise GeometryValidationError("coordinate values must be finite")
    if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
        raise GeometryValidationError("coordinate is outside WGS84 bounds")
    return longitude, latitude


def _line(value: Any, *, polygon: bool = False) -> list[tuple[float, float]]:
    if not isinstance(value, list) or len(value) < 2:
        raise GeometryValidationError("line must contain at least two coordinates")
    line = [_coordinate(point) for point in value]
    if polygon and line[0] != line[-1]:
        raise GeometryValidationError("polygon rings must be closed")
    return line


def validate_geometry(geometry: Any) -> dict[str, Any]:
    if not isinstance(geometry, dict) or geometry.get("type") not in SUPPORTED_GEOMETRIES:
        raise GeometryValidationError("geometry must be a Point, LineString, or Polygon")
    geometry_type = geometry["type"]
    coordinates = geometry.get("coordinates")
    if geometry_type == "Point":
        normalized: Any = list(_coordinate(coordinates))
    elif geometry_type == "LineString":
        normalized = [list(point) for point in _line(coordinates)]
    else:
        if not isinstance(coordinates, list) or not coordinates:
            raise GeometryValidationError("polygon must contain at least one ring")
        normalized = [list(map(list, _line(ring, polygon=True))) for ring in coordinates]
    return {"type": geometry_type, "coordinates": normalized}


def _points(geometry: dict[str, Any]) -> Iterable[tuple[float, float]]:
    geometry_type = geometry["type"]
    coordinates = geometry["coordinates"]
    if geometry_type == "Point":
        yield tuple(coordinates)
    elif geometry_type == "LineString":
        yield from (tuple(point) for point in coordinates)
    else:
        for ring in coordinates:
            yield from (tuple(point) for point in ring)


def geometry_bounds(geometry: dict[str, Any]) -> tuple[float, float, float, float]:
    points = list(_points(validate_geometry(geometry)))
    longitudes = [point[0] for point in points]
    latitudes = [point[1] for point in points]
    return min(longitudes), min(latitudes), max(longitudes), max(latitudes)


def geometry_centroid(geometry: dict[str, Any]) -> tuple[float, float]:
    normalized = validate_geometry(geometry)
    if normalized["type"] == "Point":
        return tuple(normalized["coordinates"])
    points = list(_points(normalized))
    return (
        sum(point[0] for point in points) / len(points),
        sum(point[1] for point in points) / len(points),
    )


def parse_bbox(value: str) -> tuple[float, float, float, float]:
    try:
        parts = [float(part.strip()) for part in value.split(",")]
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("bbox must be minLon,minLat,maxLon,maxLat") from exc
    if len(parts) != 4:
        raise ValueError("bbox must be minLon,minLat,maxLon,maxLat")
    min_lon, min_lat, max_lon, max_lat = parts
    if min_lon > max_lon or min_lat > max_lat:
        raise ValueError("bbox minimums must not exceed maximums")
    _coordinate((min_lon, min_lat))
    _coordinate((max_lon, max_lat))
    return min_lon, min_lat, max_lon, max_lat


def geometry_intersects_bbox(geometry: dict[str, Any], bbox: tuple[float, float, float, float]) -> bool:
    normalized = validate_geometry(geometry)
    min_lon, min_lat, max_lon, max_lat = bbox
    geometry_min_lon, geometry_min_lat, geometry_max_lon, geometry_max_lat = geometry_bounds(normalized)
    if geometry_max_lon < min_lon or geometry_min_lon > max_lon:
        return False
    if geometry_max_lat < min_lat or geometry_min_lat > max_lat:
        return False
    if _geometry_intersects_polygon(
        normalized,
        [[(min_lon, min_lat), (max_lon, min_lat), (max_lon, max_lat), (min_lon, max_lat), (min_lon, min_lat)]],
    ):
        return True
    if normalized["type"] == "Polygon":
        ring = [tuple(point) for point in normalized["coordinates"][0]]
        return any(
            _point_in_ring(corner, ring)
            for corner in (
                (min_lon, min_lat),
                (max_lon, min_lat),
                (max_lon, max_lat),
                (min_lon, max_lat),
            )
        )
    return False


def _segments(points: list[tuple[float, float]]) -> Iterable[tuple[tuple[float, float], tuple[float, float]]]:
    yield from zip(points, points[1:])


def _orientation(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on_segment(a: tuple[float, float], b: tuple[float, float], point: tuple[float, float]) -> bool:
    return (
        min(a[0], b[0]) - 1e-10 <= point[0] <= max(a[0], b[0]) + 1e-10
        and min(a[1], b[1]) - 1e-10 <= point[1] <= max(a[1], b[1]) + 1e-10
        and abs(_orientation(a, b, point)) < 1e-10
    )


def _segments_intersect(a, b, c, d) -> bool:
    first = _orientation(a, b, c)
    second = _orientation(a, b, d)
    third = _orientation(c, d, a)
    fourth = _orientation(c, d, b)
    if (first > 0) != (second > 0) and (third > 0) != (fourth > 0):
        return True
    return (
        abs(first) < 1e-10 and _on_segment(a, b, c)
        or abs(second) < 1e-10 and _on_segment(a, b, d)
        or abs(third) < 1e-10 and _on_segment(c, d, a)
        or abs(fourth) < 1e-10 and _on_segment(c, d, b)
    )


def _point_in_ring(point: tuple[float, float], ring: list[tuple[float, float]]) -> bool:
    inside = False
    for start, end in _segments(ring):
        if _on_segment(start, end, point):
            return True
        if (start[1] > point[1]) != (end[1] > point[1]):
            crossing = (end[0] - start[0]) * (point[1] - start[1]) / (end[1] - start[1]) + start[0]
            if point[0] < crossing:
                inside = not inside
    return inside


def _as_lines(geometry: dict[str, Any]) -> list[list[tuple[float, float]]]:
    if geometry["type"] == "Point":
        return []
    if geometry["type"] == "LineString":
        return [[tuple(point) for point in geometry["coordinates"]]]
    return [[tuple(point) for point in ring] for ring in geometry["coordinates"]]


def _geometry_intersects_polygon(geometry: dict[str, Any], polygon_rings: list[list[tuple[float, float]]]) -> bool:
    polygon_points = polygon_rings[0]
    if geometry["type"] == "Point":
        return _point_in_ring(tuple(geometry["coordinates"]), polygon_points)
    for line in _as_lines(geometry):
        if any(_segments_intersect(a, b, c, d) for a, b in _segments(line) for c, d in _segments(polygon_points)):
            return True
        if line and _point_in_ring(line[0], polygon_points):
            return True
    return False


def geometry_intersects(first: dict[str, Any], second: dict[str, Any]) -> bool:
    left = validate_geometry(first)
    right = validate_geometry(second)
    left_bounds = geometry_bounds(left)
    right_bounds = geometry_bounds(right)
    if (
        left_bounds[2] < right_bounds[0]
        or right_bounds[2] < left_bounds[0]
        or left_bounds[3] < right_bounds[1]
        or right_bounds[3] < left_bounds[1]
    ):
        return False
    if right["type"] == "Polygon" and _geometry_intersects_polygon(left, _as_lines(right)):
        return True
    if left["type"] == "Polygon" and _geometry_intersects_polygon(right, _as_lines(left)):
        return True
    if left["type"] == "Point" and right["type"] == "Point":
        return tuple(left["coordinates"]) == tuple(right["coordinates"])
    left_lines = _as_lines(left)
    right_lines = _as_lines(right)
    return any(_segments_intersect(a, b, c, d) for line in left_lines for a, b in _segments(line) for other in right_lines for c, d in _segments(other))


def _haversine_km(first: tuple[float, float], second: tuple[float, float]) -> float:
    lon1, lat1 = map(math.radians, first)
    lon2, lat2 = map(math.radians, second)
    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1
    value = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    return EARTH_RADIUS_KM * 2 * math.atan2(math.sqrt(value), math.sqrt(max(0.0, 1 - value)))


def distance_geometry_to_point_km(geometry: dict[str, Any], longitude: float, latitude: float) -> float:
    """Return a conservative WGS84 distance for the supported shapes."""

    target = _coordinate((longitude, latitude))
    normalized = validate_geometry(geometry)
    if normalized["type"] == "Point":
        return _haversine_km(tuple(normalized["coordinates"]), target)
    if normalized["type"] == "Polygon" and _point_in_ring(target, [tuple(point) for point in normalized["coordinates"][0]]):
        return 0.0
    candidates = [point for line in _as_lines(normalized) for point in line]
    for line in _as_lines(normalized):
        for start, end in _segments(line):
            mean_lat = math.radians((start[1] + end[1] + latitude) / 3)
            scale = math.cos(mean_lat)
            sx, sy = start[0] * scale, start[1]
            ex, ey = end[0] * scale, end[1]
            tx, ty = longitude * scale, latitude
            delta_x, delta_y = ex - sx, ey - sy
            denominator = delta_x * delta_x + delta_y * delta_y
            ratio = ((tx - sx) * delta_x + (ty - sy) * delta_y) / denominator if denominator else 0
            ratio = max(0.0, min(1.0, ratio))
            candidates.append((start[0] + ratio * (end[0] - start[0]), start[1] + ratio * (end[1] - start[1])))
    return min(_haversine_km(point, target) for point in candidates)
