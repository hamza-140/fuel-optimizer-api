import math
import requests
from django.conf import settings

EARTH_RADIUS_MILES = 3958.7613


def haversine_miles(a, b):
    lat1, lon1 = a
    lat2, lon2 = b
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat, dlon = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(min(1, math.sqrt(h)))


def get_route(start, finish):
    # OSRM expects longitude,latitude and can return GeoJSON in a single request.
    coords = f"{start[1]},{start[0]};{finish[1]},{finish[0]}"
    response = requests.get(
        f"{settings.OSRM_BASE_URL}/route/v1/driving/{coords}",
        params={"overview": "full", "geometries": "geojson", "steps": "false"},
        headers={"User-Agent": settings.GEOCODER_USER_AGENT}, timeout=25,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") != "Ok" or not payload.get("routes"):
        raise ValueError("Routing provider could not find a driving route for these locations")
    route = payload["routes"][0]
    return {
        "distance_miles": route["distance"] / 1609.344,
        "duration_seconds": route["duration"],
        "geometry": route["geometry"],
    }


def _project_to_segment(point, a, b):
    """Approximate local planar projection; returns fraction and perpendicular miles."""
    lat0 = math.radians((point[0] + a[0] + b[0]) / 3)
    scale_x = math.cos(lat0)
    px, py = point[1] * scale_x, point[0]
    ax, ay = a[1] * scale_x, a[0]
    bx, by = b[1] * scale_x, b[0]
    dx, dy = bx - ax, by - ay
    denom = dx * dx + dy * dy
    t = 0 if denom == 0 else max(0.0, min(1.0, ((px-ax)*dx + (py-ay)*dy) / denom))
    qx, qy = ax + t*dx, ay + t*dy
    cross = haversine_miles(point, (qy, qx / scale_x if scale_x else qx))
    return t, cross


def locate_station_on_route(station_point, route_coordinates, cumulative_miles):
    """Return along-route mile marker and distance from route for a station."""
    best = (float("inf"), None)
    for i in range(len(route_coordinates) - 1):
        a = (route_coordinates[i][1], route_coordinates[i][0])
        b = (route_coordinates[i + 1][1], route_coordinates[i + 1][0])
        t, offset = _project_to_segment(station_point, a, b)
        if offset < best[0]:
            segment = haversine_miles(a, b)
            best = (offset, cumulative_miles[i] + t * segment)
    return best[1], best[0]


def route_cumulative_miles(geometry):
    coords = geometry["coordinates"]
    cumulative = [0.0]
    for i in range(1, len(coords)):
        a = (coords[i-1][1], coords[i-1][0])
        b = (coords[i][1], coords[i][0])
        cumulative.append(cumulative[-1] + haversine_miles(a, b))
    return cumulative
