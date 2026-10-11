import tempfile
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase

from api.models import FuelStation


CSV_HEADER = (
    "OPIS Truckstop ID,Truckstop Name,Address,City,State,Rack ID,Retail Price\n"
)


class ImportFuelPricesCommandTests(TestCase):
    def test_imports_us_rows_and_skips_canada(self):
        content = CSV_HEADER + "\n".join(
            [
                "1,Stop A,I-80 EXIT 1,Youngstown,OH,10,3.199",
                "2,Stop B,Hwy 1,Toronto,ON,11,3.099",
                "3,Stop C,I-90 EXIT 2,Toledo,OH,12,2.999",
                "1,Stop A,I-80 EXIT 1,Youngstown,OH,10,3.199",  # exact duplicate key
            ]
        )
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as handle:
            handle.write(content)
            path = Path(handle.name)

        try:
            call_command("import_fuel_prices", str(path), "--replace")
        finally:
            path.unlink(missing_ok=True)

        self.assertEqual(FuelStation.objects.count(), 2)
        states = set(FuelStation.objects.values_list("state", flat=True))
        self.assertEqual(states, {"OH"})
        self.assertTrue(FuelStation.objects.filter(name="Stop A", city="Youngstown").exists())
        self.assertFalse(FuelStation.objects.filter(state="ON").exists())

    def test_preserves_distinct_prices_for_same_opis_id(self):
        content = CSV_HEADER + "\n".join(
            [
                "9,Pilot,I-70 EXIT 1,Columbus,OH,1,3.100",
                "9,Pilot,I-70 EXIT 1,Columbus,OH,1,3.250",
            ]
        )
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as handle:
            handle.write(content)
            path = Path(handle.name)

        try:
            call_command("import_fuel_prices", str(path), "--replace")
        finally:
            path.unlink(missing_ok=True)

        self.assertEqual(FuelStation.objects.filter(opis_id="9").count(), 2)
