# Fuel Stops Optimizer

A Django REST API that plans cost-effective fuel stops for a US road trip.

Given a **start** and **finish** location, the API:

1. Builds a driving route with [OSRM](https://project-osrm.org/)
2. Selects fuel stops from a local price dataset
3. Enforces a configurable maximum range between stops (default **500 miles**)
4. Estimates total fuel cost at a configurable MPG (default **10**)
5. Returns route geometry, stop details, and an OpenStreetMap directions link

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

pip install -r requirements.txt
cp .env.example .env

python manage.py migrate
python manage.py import_fuel_prices data/fuel-prices-for-be-assessment.csv
python manage.py geocode_fuel_stations
python manage.py runserver
```

Useful commands:

- Re-import prices: `python manage.py import_fuel_prices data/fuel-prices-for-be-assessment.csv --replace`
- Re-geocode stations: `python manage.py geocode_fuel_stations --reset`
- Run tests: `python manage.py test api.tests`

City/state geocode results are cached in `data/city_geocode_cache.json` so the setup step is resumable.

## API

### `GET /health/`

```json
{"status": "ok"}
```

### `POST /api/v1/route/optimize/`

**Request**

```json
{
  "start": "New York, NY, USA",
  "finish": "Chicago, IL, USA",
  "max_range_miles": 500,
  "mpg": 10,
  "station_corridor_miles": 15
}
```

| Field | Default | Notes |
|---|---|---|
| `start`, `finish` | required | US locations |
| `max_range_miles` | `500` | Min 50, max 500 |
| `mpg` | `10` | Miles per gallon |
| `station_corridor_miles` | `15` | Max distance a station may sit from the route (1–50) |

**Example response** (New York → Chicago; geometry shortened):

```json
{
  "start": {"query": "New York, NY, USA", "latitude": 40.7127281, "longitude": -74.0060152},
  "finish": {"query": "Chicago, IL, USA", "latitude": 41.8755616, "longitude": -87.6244212},
  "route": {
    "distance_miles": 790.57,
    "duration_minutes": 890.8,
    "geometry": {"type": "LineString", "coordinates": [[-74.005737, 40.712118], "..."]},
    "map_url": "https://www.openstreetmap.org/directions?engine=fossgis_osrm_car&route=..."
  },
  "vehicle": {
    "max_range_miles": 500,
    "mpg": 10,
    "estimated_gallons_consumed": 79.06
  },
  "fuel": {
    "estimated_total_cost_usd": 240.66,
    "currency": "USD",
    "costing_assumption": "Fuel for each route leg is priced at the departure stop; the initial leg uses the first selected station's price.",
    "stops": [
      {
        "sequence": 1,
        "name": "SHEETZ #639",
        "city": "Youngstown",
        "state": "OH",
        "price_per_gallon_usd": 3.059,
        "route_mile_marker": 390.34,
        "distance_from_route_miles": 3.68
      },
      {
        "sequence": 2,
        "name": "S&G #88",
        "city": "Toledo",
        "state": "OH",
        "price_per_gallon_usd": 3.009,
        "route_mile_marker": 554.81,
        "distance_from_route_miles": 6.43
      }
    ]
  },
  "meta": {
    "routing_provider": "OSRM / OpenStreetMap",
    "routing_api_calls": 1,
    "candidate_station_count": 327
  }
}
```

Error responses:

- **400** — invalid request body
- **422** — place cannot be resolved, or no feasible stop chain within range
- **502** — upstream routing or geocoding failure

## How it works

```
Client
  → Django REST (validate)
  → Photon / Nominatim (start + finish only)
  → OSRM once (route GeoJSON)
  → Local FuelStation rows (pre-geocoded)
  → Corridor filter + dynamic-programming optimizer
  → JSON response (route, stops, cost, map_url)
```

### Station coordinates

The fuel-price CSV includes names, cities, states, and retail prices, but **no latitude/longitude**. Many addresses are highway exits that street geocoders cannot resolve reliably.

Setup therefore:

1. Imports stations and prices from the CSV
2. Geocodes each unique **City + State** once ([Open-Meteo](https://open-meteo.com/en/docs/geocoding-api), Nominatim fallback)
3. Stores coordinates locally so optimize requests never geocode stations

Coordinates are city-level approximations used for corridor screening, not driveway-precision pins. Prices always come from the CSV.

### Optimizer

1. Project geocoded stations onto the route; keep those within `station_corridor_miles`
2. Sort by mile marker; drop near-duplicate positions (keep the cheapest)
3. Use dynamic programming: only hops ≤ `max_range_miles`, minimize estimated fuel cost
4. Price each driving leg at the **departure** stop; the first selected station prices the initial leg (returned in `fuel.costing_assumption`)

### Performance

- One OSRM call per optimize request
- Station geocoding is offline / one-time
- Bounding-box prefilter + route vertex downsampling before corridor checks
- In-process cache for repeated start/finish strings

More detail: [`ARCHITECTURE.md`](ARCHITECTURE.md). Dataset notes: [`DATASET_ANALYSIS.md`](DATASET_ANALYSIS.md).

## Try it

Import [`postman_collection.json`](postman_collection.json), or:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/route/optimize/ \
  -H 'Content-Type: application/json' \
  -d '{"start":"New York, NY, USA","finish":"Chicago, IL, USA"}'
```

## Project layout

```
api/
  models.py
  views.py
  serializers.py
  services/
    geocoding.py
    routing.py
    optimizer.py
  management/commands/
    import_fuel_prices.py
    geocode_fuel_stations.py
  tests/
data/
  fuel-prices-for-be-assessment.csv
  city_geocode_cache.json
config/
postman_collection.json
```

## Attribution

- Routing: [OSRM](https://project-osrm.org/docs/v5.24.0/api/)
- Start/finish geocoding: [Photon](https://github.com/komoot/photon), [Nominatim](https://nominatim.org/) fallback
- Station City+State geocoding: [Open-Meteo Geocoding API](https://open-meteo.com/en/docs/geocoding-api), Nominatim fallback
- Map data: © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors

Public demo endpoints for these services may rate-limit; treat them as best-effort for local development.
