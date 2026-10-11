from decimal import Decimal

from django.test import SimpleTestCase

from api.services.optimizer import Candidate, optimize_stops


def station(sid, marker, price, offset=1.0):
    return Candidate(
        sid,
        f"Station {sid}",
        "Test City",
        "TX",
        31.0,
        -97.0,
        Decimal(str(price)),
        marker,
        offset,
    )


class OptimizeStopsTests(SimpleTestCase):
    def test_finds_minimum_cost_feasible_chain(self):
        candidates = [
            station(1, 200, 4.0),
            station(2, 300, 2.0),
            station(3, 450, 3.0),
            station(4, 700, 2.5),
        ]
        stops, cost = optimize_stops(candidates, 900, 500, 10)
        self.assertEqual([s.station_id for s in stops], [2, 4])
        self.assertEqual(cost, 190.0)
        markers = [0.0] + [s.mile_marker for s in stops] + [900.0]
        self.assertTrue(all(b - a <= 500 for a, b in zip(markers, markers[1:])))

    def test_short_route_does_not_require_intermediate_stop(self):
        stops, cost = optimize_stops([station(1, 100, 3.0)], 250, 500, 10)
        self.assertEqual(stops, [])
        self.assertEqual(cost, 75.0)

    def test_short_route_uses_cheapest_corridor_price(self):
        stops, cost = optimize_stops(
            [station(1, 50, 4.0), station(2, 100, 2.5), station(3, 150, 3.0)],
            200,
            500,
            10,
        )
        self.assertEqual(stops, [])
        self.assertEqual(cost, 50.0)  # 200/10 * 2.5

    def test_fails_when_no_station_coverage(self):
        with self.assertRaises(ValueError):
            optimize_stops([], 800, 500, 10)

    def test_fails_when_available_stations_cannot_bridge_range(self):
        with self.assertRaises(ValueError):
            optimize_stops([station(1, 200, 3.0)], 800, 500, 10)

    def test_zero_distance_route_returns_zero_cost(self):
        stops, cost = optimize_stops([station(1, 10, 3.0)], 0, 500, 10)
        self.assertEqual(stops, [])
        self.assertEqual(cost, 0.0)

    def test_dedupes_near_identical_mile_markers_keeping_cheapest(self):
        candidates = [
            station(1, 300.00, 4.0),
            station(2, 300.05, 2.0),  # same spot, cheaper
            station(3, 700, 2.5),
        ]
        stops, cost = optimize_stops(candidates, 900, 500, 10)
        self.assertEqual([s.station_id for s in stops], [2, 3])
        self.assertEqual(cost, 190.0)

    def test_ignores_stations_outside_default_offset_cap_in_dp(self):
        # offset > 15 is dropped from DP nodes on long routes
        far = station(1, 300, 1.0, offset=20.0)
        near = station(2, 310, 3.0, offset=2.0)
        far_end = station(3, 700, 2.5, offset=1.0)
        with self.assertRaises(ValueError):
            # only the far-offset station around mile 300 cannot bridge the route
            optimize_stops([far, far_end], 900, 500, 10)
        stops, _ = optimize_stops([far, near, far_end], 900, 500, 10)
        self.assertEqual([s.station_id for s in stops], [2, 3])

    def test_stop_spacing_never_exceeds_max_range(self):
        candidates = [station(i, mile, 3.0) for i, mile in enumerate((100, 250, 400, 550, 700), start=1)]
        stops, _ = optimize_stops(candidates, 900, 500, 10)
        markers = [0.0] + [s.mile_marker for s in stops] + [900.0]
        self.assertTrue(all(b - a <= 500 for a, b in zip(markers, markers[1:])))
        self.assertGreaterEqual(len(stops), 1)
