# Architecture & terminology

This document explains how Spotter Fuel Optimizer works and what the main terms mean.

## Big picture

```
Client (Postman / curl)
        │
        ▼
Django REST API  ── validate request
        │
        ├── Photon / Nominatim     (geocode start & finish only)
        ├── OSRM  (1 call)         (driving route + GeoJSON)
        ├── SQLite FuelStation     (CSV prices + cached lat/lon)
        └── Optimizer (DP)         (cheap stops within 500 mi)
        │
        ▼
JSON: route map + stops + fuel cost
```

**Two timelines**

| When | What happens |
|---|---|
| **Setup (once)** | Import fuel CSV → geocode each unique City+State → save lat/lon in DB |
| **Each API request** | Geocode start/finish → **one** OSRM route → filter local stations → DP → JSON |

Stations are **never** geocoded on the live request path. That keeps the API fast and limits routing calls to one.

## Request pipeline (detail)

1. **Validate** — `OptimizeRouteSerializer` checks `start`, `finish`, `mpg`, `max_range_miles` (≤500), `station_corridor_miles`.
2. **Geocode endpoints** — turn place names into coordinates; reject non-US when Photon reports another country.
3. **Route** — one OSRM `driving` request with `geometries=geojson`.
4. **Candidate stations** — load geocoded `FuelStation` rows near the route (bounding box, then corridor distance).
5. **Optimize** — dynamic programming over mile markers; every hop ≤ max range; minimize estimated fuel cost.
6. **Respond** — distance, duration, GeoJSON, map URL, stops, gallons, total USD, `routing_api_calls: 1`.

## Why City+State geocoding?

The fuel-price CSV has prices and fields like `Address = I-44, EXIT 283`, but **no latitude/longitude**. Free street geocoders cannot match highway exits. We geocode each unique **City + State** from that same CSV once (Open-Meteo / Nominatim), store coordinates, and use them only for “near the route” screening. Fuel prices always come from the imported CSV.

## Key modules

| Path | Role |
|---|---|
| `api/views.py` | Orchestrates the optimize flow |
| `api/serializers.py` | Request validation |
| `api/models.py` | `FuelStation` table |
| `api/services/geocoding.py` | Start/finish + offline City+State |
| `api/services/routing.py` | OSRM + haversine + route projection |
| `api/services/optimizer.py` | Dynamic-programming stop selection |
| `api/management/commands/import_fuel_prices.py` | Load CSV |
| `api/management/commands/geocode_fuel_stations.py` | One-time station coords |

## Glossary

### Basics

| Term | Plain English | In this project |
|---|---|---|
| **API** | Programs talking over HTTP; request in, JSON out | `POST /api/v1/route/optimize/` |
| **Django** | Python web framework | `manage.py`, settings, migrations |
| **DRF** | Django REST Framework — JSON API toolkit | views + serializers |
| **Endpoint** | One URL + method | `/health/`, `/api/v1/route/optimize/` |
| **Serializer** | Validates request JSON | `OptimizeRouteSerializer` |
| **Model** | Python class ↔ DB table | `FuelStation` |
| **Migration** | Schema change script | `python manage.py migrate` |

### Data

| Term | Plain English | In this project |
|---|---|---|
| **CSV** | Spreadsheet-like text file | Fuel-price dataset under `data/` |
| **OPIS ID** | Vendor truck-stop id | Not unique alone; we keep distinct prices |
| **SQLite** | File-based database | `db.sqlite3` (local only; don’t commit) |

### Geography & routing

| Term | Plain English | In this project |
|---|---|---|
| **Geocoding** | Name/address → lat/lon | Start/finish live; stations offline |
| **Latitude / longitude** | Earth coordinates | Stored on each station |
| **Photon** | Free OSM geocoder | Primary for start/finish |
| **Nominatim** | Official OSM geocoder | Fallback if Photon fails |
| **Open-Meteo** | Free place geocoder | Offline City+State for stations |
| **OSRM** | Free driving router on OSM | Exactly **one** call per optimize |
| **GeoJSON / LineString** | Path as `[lon, lat]` points | `route.geometry` for maps |
| **Haversine** | Distance between two lat/lon points | Miles along the route |
| **Mile marker** | Distance from route start | `route_mile_marker` on stops |
| **Corridor** | Band around the route | `station_corridor_miles` (default 15) |
| **Offset** | Sideways distance to the path | `distance_from_route_miles` |
| **Bounding box** | Fast rectangular prefilter | Before exact corridor checks |

### Fuel logic

| Term | Plain English | In this project |
|---|---|---|
| **MPG** | Miles per gallon | Default **10** |
| **Max range** | How far before refueling | Cap **500** miles per hop |
| **Candidate** | Station near enough to consider | `candidate_station_count` |
| **Dynamic programming (DP)** | Systematic min-cost search over ordered stops | `optimize_stops()` |
| **Costing assumption** | How we price fuel without a start-tank price | Legs priced at departure stop; first stop prices the initial leg |

### Ops

| Term | Plain English | In this project |
|---|---|---|
| **Throttle** | Rate limit | 60 anonymous requests / minute |
| **HTTP 422** | Request understood but not processable | Bad places / no feasible stops |
| **HTTP 502** | Upstream provider failed | OSRM/geocoder outage |
| **Postman** | GUI for calling APIs | `postman_collection.json` |

## Costing assumption

Starting fuel level and the price of fuel already in the tank are unknown.  
Each driving leg is priced at the **departure** station’s price. For the first leg (origin → first stop), the **first selected station’s** price is used. That text is returned in `fuel.costing_assumption`.
