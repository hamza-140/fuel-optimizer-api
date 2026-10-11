from unittest.mock import MagicMock, patch

import requests
from django.test import SimpleTestCase

from api.services import geocoding


class GeocodePlaceTests(SimpleTestCase):
    def setUp(self):
        geocoding.geocode_place.cache_clear()

    @patch("api.services.geocoding._nominatim_place")
    @patch("api.services.geocoding._photon_place")
    def test_uses_photon_when_available(self, mock_photon, mock_nominatim):
        mock_photon.return_value = (40.7, -74.0)
        result = geocoding.geocode_place("New York, NY, USA")
        self.assertEqual(result, (40.7, -74.0))
        mock_photon.assert_called_once()
        mock_nominatim.assert_not_called()

    @patch("api.services.geocoding._nominatim_place")
    @patch("api.services.geocoding._photon_place")
    def test_falls_back_to_nominatim_when_photon_fails(self, mock_photon, mock_nominatim):
        mock_photon.side_effect = requests.ConnectionError("down")
        mock_nominatim.return_value = (41.8, -87.6)
        result = geocoding.geocode_place("Chicago, IL, USA")
        self.assertEqual(result, (41.8, -87.6))
        mock_nominatim.assert_called_once()

    @patch("api.services.geocoding._nominatim_place")
    @patch("api.services.geocoding._photon_place")
    def test_raises_when_both_geocoders_miss(self, mock_photon, mock_nominatim):
        mock_photon.return_value = None
        mock_nominatim.return_value = None
        with self.assertRaises(ValueError):
            geocoding.geocode_place("Nowhereville, ZZ, USA")

    @patch("api.services.geocoding.requests.get")
    def test_photon_rejects_non_us_country(self, mock_get):
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "features": [
                {
                    "geometry": {"coordinates": [-79.4, 43.7]},
                    "properties": {"country": "Canada"},
                }
            ]
        }
        mock_get.return_value = mock_response
        with self.assertRaises(ValueError) as ctx:
            geocoding._photon_place("Toronto, ON")
        self.assertIn("United States", str(ctx.exception))


class OpenMeteoCityGeocodeTests(SimpleTestCase):
    @patch("api.services.geocoding.requests.get")
    def test_open_meteo_matches_admin1_state(self, mock_get):
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "results": [
                {
                    "latitude": 39.96,
                    "longitude": -82.99,
                    "country_code": "US",
                    "admin1": "Ohio",
                    "name": "Columbus",
                }
            ]
        }
        mock_get.return_value = mock_response
        point = geocoding.geocode_city_state_open_meteo("Columbus", "OH")
        self.assertEqual(point, (39.96, -82.99))

    @patch("api.services.geocoding.requests.get")
    def test_open_meteo_skips_wrong_state(self, mock_get):
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "results": [
                {
                    "latitude": 32.46,
                    "longitude": -84.99,
                    "country_code": "US",
                    "admin1": "Georgia",
                    "name": "Columbus",
                }
            ]
        }
        mock_get.return_value = mock_response
        point = geocoding.geocode_city_state_open_meteo("Columbus", "OH")
        self.assertIsNone(point)


class ResolveStationCoordinatesTests(SimpleTestCase):
    @patch("api.services.geocoding._save_city_cache")
    @patch("api.services.geocoding._load_city_cache", return_value={})
    @patch("api.services.geocoding.geocode_city_state")
    def test_applies_unique_city_state_to_all_stations(self, mock_geocode, _load, _save):
        mock_geocode.return_value = (40.0, -75.0)

        class FakeStation:
            def __init__(self, pk, city, state):
                self.pk = pk
                self.city = city
                self.state = state

        stations = [
            FakeStation(1, "Reading", "PA"),
            FakeStation(2, "Reading", "PA"),
            FakeStation(3, "Harrisburg", "PA"),
        ]
        # Second unique city also resolves
        mock_geocode.side_effect = lambda city, state: {
            ("Reading", "PA"): (40.3, -75.9),
            ("Harrisburg", "PA"): (40.2, -76.8),
        }[(city, state)]

        results = geocoding.resolve_station_coordinates(stations, workers=1)
        self.assertEqual(results[1], (40.3, -75.9))
        self.assertEqual(results[2], (40.3, -75.9))
        self.assertEqual(results[3], (40.2, -76.8))
        self.assertEqual(mock_geocode.call_count, 2)
