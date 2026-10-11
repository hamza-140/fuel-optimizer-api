from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from api.models import FuelStation


class HealthEndpointTests(TestCase):
    def test_health_ok(self):
        client = APIClient()
        response = client.get("/health/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})


class OptimizeRouteEndpointTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        # Stations along a simple east→west corridor near lat 40
        FuelStation.objects.create(
            opis_id="1",
            name="Cheap Mid",
            address="I-80 EXIT 1",
            city="Youngstown",
            state="OH",
            rack_id="1",
            price_per_gallon=Decimal("3.000000"),
            latitude=41.1,
            longitude=-80.65,
        )
        FuelStation.objects.create(
            opis_id="2",
            name="Cheap West",
            address="I-80 EXIT 2",
            city="Toledo",
            state="OH",
            rack_id="2",
            price_per_gallon=Decimal("2.900000"),
            latitude=41.65,
            longitude=-83.55,
        )
        FuelStation.objects.create(
            opis_id="3",
            name="No Coords",
            address="Somewhere",
            city="Hidden",
            state="OH",
            rack_id="3",
            price_per_gallon=Decimal("1.000000"),
            latitude=None,
            longitude=None,
        )

    def _fake_route(self):
        # ~700 mile-ish polyline from NYC area toward Chicago area
        return {
            "distance_miles": 700.0,
            "duration_seconds": 36000,
            "geometry": {
                "type": "LineString",
                "coordinates": [
                    [-74.00, 40.70],
                    [-80.65, 41.10],
                    [-83.55, 41.65],
                    [-87.60, 41.90],
                ],
            },
        }

    @patch("api.views.get_route")
    @patch("api.views.geocode_place")
    def test_optimize_returns_stops_cost_and_one_routing_call(self, mock_geocode, mock_route):
        mock_geocode.side_effect = [(40.70, -74.00), (41.90, -87.60)]
        mock_route.return_value = self._fake_route()

        response = self.client.post(
            "/api/v1/route/optimize/",
            {
                "start": "New York, NY, USA",
                "finish": "Chicago, IL, USA",
                "max_range_miles": 500,
                "mpg": 10,
                "station_corridor_miles": 50,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["meta"]["routing_api_calls"], 1)
        self.assertEqual(mock_route.call_count, 1)
        self.assertEqual(mock_geocode.call_count, 2)
        self.assertIn("geometry", body["route"])
        self.assertEqual(body["route"]["geometry"]["type"], "LineString")
        self.assertIn("map_url", body["route"])
        self.assertGreater(body["fuel"]["estimated_total_cost_usd"], 0)
        self.assertEqual(body["vehicle"]["estimated_gallons_consumed"], 70.0)
        self.assertGreaterEqual(body["meta"]["candidate_station_count"], 1)
        self.assertGreaterEqual(len(body["fuel"]["stops"]), 1)
        self.assertNotIn("No Coords", [s["name"] for s in body["fuel"]["stops"]])
        self.assertIn("costing_assumption", body["fuel"])

    @patch("api.views.get_route")
    @patch("api.views.geocode_place")
    def test_optimize_short_route_may_have_zero_stops(self, mock_geocode, mock_route):
        mock_geocode.side_effect = [(40.70, -74.00), (40.75, -74.10)]
        mock_route.return_value = {
            "distance_miles": 20.0,
            "duration_seconds": 1800,
            "geometry": {
                "type": "LineString",
                "coordinates": [[-74.00, 40.70], [-74.10, 40.75]],
            },
        }
        # Put a station near the short route so cost can be estimated
        FuelStation.objects.create(
            opis_id="10",
            name="Local",
            address="Main",
            city="Hoboken",
            state="NJ",
            rack_id="10",
            price_per_gallon=Decimal("3.500000"),
            latitude=40.72,
            longitude=-74.05,
        )
        response = self.client.post(
            "/api/v1/route/optimize/",
            {"start": "Newark, NJ, USA", "finish": "Jersey City, NJ, USA"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["fuel"]["stops"], [])
        self.assertEqual(body["fuel"]["estimated_total_cost_usd"], 7.0)  # 20/10 * 3.5

    def test_missing_fields_return_400(self):
        response = self.client.post("/api/v1/route/optimize/", {}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_max_range_over_cap_returns_400(self):
        response = self.client.post(
            "/api/v1/route/optimize/",
            {"start": "A", "finish": "B", "max_range_miles": 999},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    @patch("api.views.geocode_place", side_effect=ValueError("Could not geocode location: X"))
    def test_geocode_failure_returns_422(self, _mock_geocode):
        response = self.client.post(
            "/api/v1/route/optimize/",
            {"start": "X", "finish": "Y"},
            format="json",
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("error", response.json())

    @patch("api.views.get_route", side_effect=RuntimeError("OSRM blew up"))
    @patch("api.views.geocode_place", side_effect=[(40.7, -74.0), (41.9, -87.6)])
    def test_upstream_failure_returns_502(self, _geo, _route):
        response = self.client.post(
            "/api/v1/route/optimize/",
            {"start": "New York, NY, USA", "finish": "Chicago, IL, USA"},
            format="json",
        )
        self.assertEqual(response.status_code, 502)
        body = response.json()
        self.assertEqual(body["error"], "Route calculation failed")
        self.assertIn("detail", body)

    @patch("api.views.get_route")
    @patch("api.views.geocode_place")
    def test_insufficient_coverage_returns_422(self, mock_geocode, mock_route):
        mock_geocode.side_effect = [(40.70, -74.00), (41.90, -87.60)]
        mock_route.return_value = {
            "distance_miles": 800.0,
            "duration_seconds": 40000,
            "geometry": {
                "type": "LineString",
                "coordinates": [[-74.0, 40.7], [-87.6, 41.9]],
            },
        }
        FuelStation.objects.all().delete()
        response = self.client.post(
            "/api/v1/route/optimize/",
            {"start": "New York, NY, USA", "finish": "Chicago, IL, USA"},
            format="json",
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("error", response.json())
