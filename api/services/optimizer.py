from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Candidate:
    station_id: int
    name: str
    city: str
    state: str
    latitude: float
    longitude: float
    price: Decimal
    mile_marker: float
    offset_miles: float


def optimize_stops(candidates, total_miles, max_range_miles=500.0, mpg=10.0):
    """Find minimum-cost sequence of stations on a linear route.

    Each driving leg must be <= max_range_miles. Fuel consumed on a leg is priced
    at the departure station's price. For the first leg, the first selected station's
    price is used, so the estimate accounts for all route miles and assumes refueling
    at that price for the initial leg too. This explicit accounting convention avoids
    pretending the supplied data contains a start-tank fuel price.
    """
    if total_miles <= 0:
        return [], 0.0
    stations = sorted(candidates, key=lambda s: (s.mile_marker, float(s.price)))
    # Several dataset rows can describe the same physical stop with different price
    # records. Avoid zero-distance hops by retaining the cheapest candidate within 0.1 mi.
    deduped = []
    for station in stations:
        if deduped and abs(deduped[-1].mile_marker - station.mile_marker) <= 0.1:
            if float(station.price) < float(deduped[-1].price):
                deduped[-1] = station
        else:
            deduped.append(station)
    stations = deduped
    if not stations:
        raise ValueError("No geocoded fuel stations were found near this route")
    if total_miles <= max_range_miles:
        # No intermediate stop is required; estimate consumption at the cheapest
        # station price available along the corridor.
        return [], round((total_miles / mpg) * min(float(s.price) for s in stations), 2)
    # Ignore duplicate station records at effectively the same route position.
    nodes = []
    for station in stations:
        if 0 < station.mile_marker < total_miles and station.offset_miles <= 15:
            if not nodes or abs(nodes[-1].mile_marker - station.mile_marker) > 0.1 or nodes[-1].station_id != station.station_id:
                nodes.append(station)
    if not nodes:
        raise ValueError("No geocoded fuel stations were found near this route")

    # Dynamic programming: dp[j] is the minimum cost to reach node j. The destination
    # is a final node with no fuel price; the origin is node zero.
    positions = [0.0] + [s.mile_marker for s in nodes] + [float(total_miles)]
    n = len(positions)
    inf = float("inf")
    dp = [inf] * n
    prev = [None] * n
    dp[0] = 0.0
    for j in range(1, n):
        for i in range(j - 1, -1, -1):
            distance = positions[j] - positions[i]
            if distance > max_range_miles:
                break
            if dp[i] == inf:
                continue
            if i == 0:
                # Initial leg cost is priced using the station reached at j, or the
                # last reachable station when j is the destination.
                if j == n - 1:
                    continue
                price = float(nodes[j - 1].price)
            else:
                price = float(nodes[i - 1].price)
            cost = dp[i] + (distance / mpg) * price
            if cost < dp[j]:
                dp[j], prev[j] = cost, i
    if dp[-1] == inf:
        raise ValueError("Cannot complete route within the 500-mile range; station coverage is insufficient")
    path = []
    cursor = n - 1
    while cursor not in (None, 0):
        parent = prev[cursor]
        if parent is None:
            raise ValueError("Unable to reconstruct optimized fuel stops")
        if cursor != n - 1:
            path.append(nodes[cursor - 1])
        cursor = parent
    path.reverse()
    # The first station on the path is a required fuel stop; subsequent stations are
    # chosen by the minimum-cost dynamic program. Return only actual selected stations.
    return path, round(dp[-1], 2)
