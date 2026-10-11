from django.core.management.base import BaseCommand
from django.db.models import Q
from api.models import FuelStation
from api.services.geocoding import resolve_station_coordinates


class Command(BaseCommand):
    help = (
        "One-time geocode of stations from the assessment CSV using free geocoders "
        "(Open-Meteo, Nominatim fallback). Uses each row's City+State because the CSV "
        "has no lat/lon and Address is usually a highway exit. Coordinates are stored "
        "locally so route requests do not geocode stations."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Clear existing station coordinates before geocoding again.",
        )
        parser.add_argument(
            "--workers",
            type=int,
            default=8,
            help="Concurrent City+State geocode requests (default 8).",
        )

    def handle(self, *args, **opts):
        if opts["reset"]:
            cleared = FuelStation.objects.update(latitude=None, longitude=None)
            self.stdout.write(f"Cleared coordinates on {cleared} stations.")

        stations = list(
            FuelStation.objects.filter(Q(latitude__isnull=True) | Q(longitude__isnull=True)).order_by("pk")
        )
        if not stations:
            self.stdout.write(self.style.SUCCESS("All stations already have coordinates."))
            return

        self.stdout.write(
            f"Geocoding {len(stations)} stations from CSV City+State via free geocoders..."
        )
        results = resolve_station_coordinates(
            stations,
            progress_callback=lambda msg: (self.stdout.write(msg), self.stdout.flush()),
            workers=opts["workers"],
        )

        updated = 0
        batch = []
        for station in stations:
            point = results.get(station.pk)
            if not point:
                continue
            station.latitude, station.longitude = point
            batch.append(station)
            if len(batch) >= 500:
                FuelStation.objects.bulk_update(batch, ["latitude", "longitude"])
                updated += len(batch)
                batch = []
        if batch:
            FuelStation.objects.bulk_update(batch, ["latitude", "longitude"])
            updated += len(batch)

        missing = len(stations) - updated
        self.stdout.write(self.style.SUCCESS(f"Coordinates added for {updated}/{len(stations)} stations."))
        if missing:
            self.stdout.write(self.style.WARNING(f"{missing} stations still lack coordinates."))
        self.stdout.write(
            self.style.WARNING(
                "CSV has no lat/lon. Coordinates are City+State locations from free geocoders, "
                "not exact truck-stop entrances."
            )
        )
