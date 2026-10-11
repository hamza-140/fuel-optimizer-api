import math
from decimal import Decimal
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.response import Response
from rest_framework import status
from rest_framework.throttling import AnonRateThrottle
from .models import FuelStation
from .serializers import OptimizeRouteSerializer
from .services.geocoding import geocode_place
from .services.routing import get_route, route_cumulative_miles, locate_station_on_route
from .services.optimizer import Candidate, optimize_stops


@api_view(["GET"])
def health(request):
    return Response({"status": "ok"})


@api_view(["POST"])
@throttle_classes([AnonRateThrottle])
def optimize_route(request):
    serializer = OptimizeRouteSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    try:
        start = geocode_place(data["start"])
        finish = geocode_place(data["finish"])
        route = get_route(start, finish)  # one routing-provider call per request
        coords = route["geometry"]["coordinates"]
        cumulative = route_cumulative_miles(route["geometry"])
        # Candidate matching is bounded to at most ~600 route vertices. The complete
        # GeoJSON is still returned to clients; downsampling only accelerates proximity
        # screening against the station catalogue.
        stride = max(1, len(coords) // 600)
        sample_indices = list(range(0, len(coords), stride))
        if sample_indices[-1] != len(coords) - 1:
            sample_indices.append(len(coords) - 1)
        match_coords = [coords[i] for i in sample_indices]
        match_cumulative = [cumulative[i] for i in sample_indices]
        corridor = data["station_corridor_miles"]
        # Bounding-box prefilter keeps candidate checks fast without extra routing calls.
        lats = [c[1] for c in match_coords]
        lons = [c[0] for c in match_coords]
        pad_lat = corridor / 69.0 + 0.15
        mid_lat = sum(lats) / len(lats)
        pad_lon = corridor / max(1e-6, 69.0 * abs(math.cos(math.radians(mid_lat)))) + 0.15
        stations = (
            FuelStation.objects.exclude(latitude__isnull=True)
            .exclude(longitude__isnull=True)
            .filter(
                latitude__gte=min(lats) - pad_lat,
                latitude__lte=max(lats) + pad_lat,
                longitude__gte=min(lons) - pad_lon,
                longitude__lte=max(lons) + pad_lon,
            )
        )
        candidates = []
        for station in stations.iterator(chunk_size=1000):
            marker, offset = locate_station_on_route(
                (station.latitude, station.longitude), match_coords, match_cumulative
            )
            if marker is not None and 0 < marker < route["distance_miles"] and offset <= corridor:
                candidates.append(Candidate(
                    station_id=station.pk, name=station.name, city=station.city, state=station.state,
                    latitude=station.latitude, longitude=station.longitude,
                    price=Decimal(station.price_per_gallon), mile_marker=marker, offset_miles=offset,
                ))
        stops, total_cost = optimize_stops(
            candidates, route["distance_miles"], data["max_range_miles"], data["mpg"]
        )
        gallons = route["distance_miles"] / data["mpg"]
        return Response({
            "start": {"query": data["start"], "latitude": start[0], "longitude": start[1]},
            "finish": {"query": data["finish"], "latitude": finish[0], "longitude": finish[1]},
            "route": {
                "distance_miles": round(route["distance_miles"], 2),
                "duration_minutes": round(route["duration_seconds"] / 60, 1),
                "geometry": route["geometry"],
                "map_url": f"https://www.openstreetmap.org/directions?engine=fossgis_osrm_car&route={start[0]}%2C{start[1]}%3B{finish[0]}%2C{finish[1]}",
            },
            "vehicle": {"max_range_miles": data["max_range_miles"], "mpg": data["mpg"], "estimated_gallons_consumed": round(gallons, 2)},
            "fuel": {
                "estimated_total_cost_usd": round(total_cost, 2),
                "currency": "USD",
                "costing_assumption": "Fuel for each route leg is priced at the departure stop; the initial leg uses the first selected station's price.",
                "stops": [{
                    "sequence": i + 1, "station_id": s.station_id, "name": s.name,
                    "city": s.city, "state": s.state,
                    "latitude": s.latitude, "longitude": s.longitude,
                    "price_per_gallon_usd": round(float(s.price), 4),
                    "route_mile_marker": round(s.mile_marker, 2),
                    "distance_from_route_miles": round(s.offset_miles, 2),
                } for i, s in enumerate(stops)],
            },
            "meta": {"routing_provider": "OSRM / OpenStreetMap", "routing_api_calls": 1, "candidate_station_count": len(candidates)},
        })
    except ValueError as exc:
        return Response({"error": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
    except Exception as exc:
        # Avoid exposing upstream response bodies or internal details to clients.
        return Response({"error": "Route calculation failed", "detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
