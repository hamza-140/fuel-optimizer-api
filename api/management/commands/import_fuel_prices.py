import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from api.models import FuelStation

US_STATES = set(
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO "
    "MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split()
)


class Command(BaseCommand):
    help = "Import the assessment fuel-price CSV. Latitude/longitude are optional columns if supplied."

    def add_arguments(self, parser):
        parser.add_argument("csv_path", nargs="?", default="data/fuel-prices-for-be-assessment.csv")
        parser.add_argument(
            "--replace",
            action="store_true",
            help="Delete existing stations before importing (faster clean reload).",
        )

    def handle(self, *args, **opts):
        path = Path(opts["csv_path"])
        if not path.exists():
            raise CommandError(f"CSV not found: {path}")

        if opts["replace"]:
            deleted, _ = FuelStation.objects.all().delete()
            self.stdout.write(f"Removed {deleted} existing station rows.")

        created = skipped = 0
        batch = []
        seen = set()
        with path.open(newline="", encoding="utf-8-sig") as file:
            reader = csv.DictReader(file)
            required = {
                "OPIS Truckstop ID",
                "Truckstop Name",
                "Address",
                "City",
                "State",
                "Rack ID",
                "Retail Price",
            }
            if not required.issubset(set(reader.fieldnames or [])):
                raise CommandError(f"CSV must include columns: {', '.join(sorted(required))}")
            for row in reader:
                try:
                    state = str(row["State"]).strip().upper()
                    # Canadian provinces/territories are excluded; assessment is USA-only.
                    if state not in US_STATES:
                        skipped += 1
                        continue
                    price = Decimal(str(row["Retail Price"]).strip())
                    lat = float(row["Latitude"]) if row.get("Latitude") else None
                    lon = float(row["Longitude"]) if row.get("Longitude") else None
                    payload = {
                        "opis_id": str(row["OPIS Truckstop ID"]).strip(),
                        "name": str(row["Truckstop Name"]).strip(),
                        "address": str(row["Address"]).strip(),
                        "city": str(row["City"]).strip(),
                        "state": state,
                        "rack_id": str(row["Rack ID"]).strip(),
                        "price_per_gallon": price,
                        "latitude": lat,
                        "longitude": lon,
                    }
                    # Preserve distinct price records; OPIS ID alone is not unique.
                    key = (
                        payload["opis_id"],
                        payload["name"],
                        payload["city"],
                        payload["state"],
                        payload["rack_id"],
                        str(payload["price_per_gallon"]),
                    )
                    if key in seen:
                        skipped += 1
                        continue
                    seen.add(key)
                    batch.append(FuelStation(**payload))
                    if len(batch) >= 500:
                        FuelStation.objects.bulk_create(batch, ignore_conflicts=True)
                        created += len(batch)
                        batch = []
                except (InvalidOperation, ValueError, TypeError):
                    skipped += 1
        if batch:
            FuelStation.objects.bulk_create(batch, ignore_conflicts=True)
            created += len(batch)

        self.stdout.write(
            self.style.SUCCESS(f"Import complete. Created≈{created}, skipped={skipped}")
        )
        self.stdout.write(
            self.style.WARNING(
                "The supplied CSV has no coordinates. Run geocode_fuel_stations before route optimization."
            )
        )
