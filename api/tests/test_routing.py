from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from api.services.routing import (
    get_route,
    haversine_miles,
    locate_station_on_route,
    route_cumulative_miles,
)


class RoutingHelpersTests(SimpleTestCase):
    def test_haversine_zero_for_same_point(self):
        self.assertEqual(haversine_miles((40.0, -74.0), (40.0, -74.0)), 0.0)

    def test_haversine_nyc_to_philly_roughly_80_miles(self):
        miles = haversine_miles((40.7128, -74.0060), (39.9526, -75.1652))
        self.assertGreater(miles, 70)
        self.assertLess(miles, 100)

    def test_route_cumulative_miles_is_monotonic(self):
        geometry = {
            "type": "LineString",
            "coordinates": [
                [-74.0, 40.0],
                [-74.5, 40.5],
                [-75.0, 41.0],
            ],
        }
        cumulative = route_cumulative_miles(geometry)
        self.assertEqual(len(cumulative), 3)
        self.assertEqual(cumulative[0], 0.0)
        self.assertGreater(cumulative[1], cumulative[0])
        self.assertGreater(cumulative[2], cumulative[1])

    def test_locate_station_on_route_near_midpoint(self):
        coords = [[-74.0, 40.0], [-75.0, 40.0], [-76.0, 40.0]]
        cumulative = [0.0, 50.0, 100.0]
        # Point slightly north of the middle segment
        marker, offset = locate_station_on_route((40.05, -75.0), coords, cumulative)
        self.assertIsNotNone(marker)
        self.assertGreater(marker, 40)
        self.assertLess(marker, 60)
        self.assertLess(offset, 10)

    @patch("api.services.routing.requests.get")
    def test_get_route_parses_osrm_payload(self, mock_get):
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "code": "Ok",
            "routes": [
                {
                    "distance": 160934.4,  # 100 miles in meters
                    "duration": 7200,
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[-74.0, 40.7], [-87.6, 41.9]],
                    },
                }
            ],
        }
        mock_get.return_value = mock_response

        route = get_route((40.7, -74.0), (41.9, -87.6))
        self.assertAlmostEqual(route["distance_miles"], 100.0, places=1)
        self.assertEqual(route["duration_seconds"], 7200)
        self.assertEqual(route["geometry"]["type"], "LineString")
        self.assertEqual(mock_get.call_count, 1)

    @patch("api.services.routing.requests.get")
    def test_get_route_raises_when_osrm_has_no_route(self, mock_get):
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"code": "NoRoute", "routes": []}
        mock_get.return_value = mock_response

        with self.assertRaises(ValueError):
            get_route((40.7, -74.0), (41.9, -87.6))
