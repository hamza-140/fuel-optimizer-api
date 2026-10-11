from django.test import SimpleTestCase

from api.serializers import OptimizeRouteSerializer


class OptimizeRouteSerializerTests(SimpleTestCase):
    def test_defaults_applied(self):
        serializer = OptimizeRouteSerializer(
            data={"start": "New York, NY, USA", "finish": "Chicago, IL, USA"}
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        data = serializer.validated_data
        self.assertEqual(data["max_range_miles"], 500)
        self.assertEqual(data["mpg"], 10)
        self.assertEqual(data["station_corridor_miles"], 15)

    def test_requires_start_and_finish(self):
        serializer = OptimizeRouteSerializer(data={})
        self.assertFalse(serializer.is_valid())
        self.assertIn("start", serializer.errors)
        self.assertIn("finish", serializer.errors)

    def test_rejects_max_range_above_500(self):
        serializer = OptimizeRouteSerializer(
            data={
                "start": "A",
                "finish": "B",
                "max_range_miles": 600,
            }
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("max_range_miles", serializer.errors)

    def test_rejects_max_range_below_minimum(self):
        serializer = OptimizeRouteSerializer(
            data={
                "start": "A",
                "finish": "B",
                "max_range_miles": 10,
            }
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("max_range_miles", serializer.errors)

    def test_rejects_invalid_mpg(self):
        serializer = OptimizeRouteSerializer(
            data={
                "start": "A",
                "finish": "B",
                "mpg": 0,
            }
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("mpg", serializer.errors)

    def test_rejects_corridor_out_of_bounds(self):
        serializer = OptimizeRouteSerializer(
            data={
                "start": "A",
                "finish": "B",
                "station_corridor_miles": 100,
            }
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("station_corridor_miles", serializer.errors)
