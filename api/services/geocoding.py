import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from pathlib import Path
from threading import Lock

import requests
from django.conf import settings

# The assessment CSV has no latitude/longitude. Address values are usually highway
# exits ("I-44, EXIT 283"), which street geocoders cannot match. We geocode each
# unique City+State from that same CSV once via free public geocoders, then store
# coordinates on FuelStation so route requests never geocode stations live.
CITY_GEOCODE_CACHE = Path(settings.BASE_DIR) / "data" / "city_geocode_cache.json"
# Keep reading the older Photon cache filename if present (upgrade path).
LEGACY_PHOTON_CACHE = Path(settings.BASE_DIR) / "data" / "photon_city_cache.json"
OPEN_METEO_URL = "https://geocoding-api.open-meteo.com/v1/search"

STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire",
    "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee",
    "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
}


def _photon_place(query: str) -> tuple[float, float] | None:
    response = requests.get(
        f"{settings.PHOTON_BASE_URL}/api/",
        params={"q": query, "limit": 1, "lang": "en"},
        headers={"User-Agent": settings.GEOCODER_USER_AGENT},
        timeout=12,
    )
    response.raise_for_status()
    features = response.json().get("features", [])
    if not features:
        return None
    lon, lat = features[0]["geometry"]["coordinates"]
    props = features[0].get("properties", {})
    country = str(props.get("country", "")).lower()
    if country not in {"united states", "united states of america", "usa", "us"}:
        raise ValueError("Start and finish locations must resolve to the United States")
    return float(lat), float(lon)


def _nominatim_place(query: str) -> tuple[float, float] | None:
    response = requests.get(
        "https://nominatim.openstreetmap.org/search",
        params={"q": query, "format": "json", "limit": 1, "countrycodes": "us"},
        headers={"User-Agent": settings.GEOCODER_USER_AGENT},
        timeout=15,
    )
    response.raise_for_status()
    rows = response.json()
    if not rows:
        return None
    return float(rows[0]["lat"]), float(rows[0]["lon"])


@lru_cache(maxsize=512)
def geocode_place(query: str) -> tuple[float, float]:
    """Geocode start/finish via free Photon, with Nominatim fallback."""
    try:
        point = _photon_place(query)
        if point:
            return point
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError):
        point = None
    try:
        point = _nominatim_place(query)
    except requests.RequestException as exc:
        raise ValueError(f"Could not geocode location: {query}") from exc
    if not point:
        raise ValueError(f"Could not geocode location: {query}")
    return point


def _cache_key(city: str, state: str) -> str:
    return f"{city.strip().lower()}|{state.strip().upper()}"


def _load_city_cache() -> dict:
    for path in (CITY_GEOCODE_CACHE, LEGACY_PHOTON_CACHE):
        if not path.exists():
            continue
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
    return {}


def _save_city_cache(cache: dict) -> None:
    CITY_GEOCODE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    CITY_GEOCODE_CACHE.write_text(json.dumps(cache, indent=2, sort_keys=True), encoding="utf-8")


def geocode_city_state_open_meteo(city: str, state: str) -> tuple[float, float] | None:
    """Geocode City+State from the assessment CSV via free Open-Meteo geocoding."""
    state_code = state.strip().upper()
    state_name = STATE_NAMES.get(state_code, state)
    try:
        response = requests.get(
            OPEN_METEO_URL,
            params={
                "name": city.strip(),
                "admin1": state_name,
                "country": "United States",
                "count": 5,
                "language": "en",
                "format": "json",
            },
            headers={"User-Agent": settings.GEOCODER_USER_AGENT},
            timeout=15,
        )
        response.raise_for_status()
    except requests.RequestException:
        return None

    expected = state_name.lower()
    for row in response.json().get("results") or []:
        if str(row.get("country_code", "")).upper() != "US":
            continue
        admin1 = str(row.get("admin1", "")).lower()
        if admin1 and admin1 not in {expected, state_code.lower()}:
            continue
        return float(row["latitude"]), float(row["longitude"])
    return None


def geocode_city_state(city: str, state: str) -> tuple[float, float] | None:
    """Resolve City+State using free geocoders (Open-Meteo, then Nominatim)."""
    point = geocode_city_state_open_meteo(city, state)
    if point:
        return point
    state_code = state.strip().upper()
    state_name = STATE_NAMES.get(state_code, state)
    query = f"{city.strip()}, {state_name}, USA"
    try:
        return _nominatim_place(query)
    except requests.RequestException:
        return None


def resolve_station_coordinates(stations, progress_callback=None, workers=8):
    """Map stations to coordinates using CSV City+State + free geocoders.

    Unique City+State pairs are geocoded once, cached on disk, and applied to every
    station sharing that city/state. Live route requests do not geocode stations and
    still use one OSRM routing call.
    """
    cache = _load_city_cache()
    unique_pairs: dict[str, tuple[str, str]] = {}
    for station in stations:
        key = _cache_key(station.city, station.state)
        unique_pairs.setdefault(key, (station.city.strip(), station.state.strip().upper()))

    pending = [pair for key, pair in unique_pairs.items() if key not in cache or cache[key] is None]
    total = len(unique_pairs)
    done = total - len(pending)
    if progress_callback:
        progress_callback(
            f"City/state lookup: {done}/{total} already cached, {len(pending)} remaining"
        )

    lock = Lock()
    completed = 0

    def _work(pair: tuple[str, str]):
        city, state = pair
        return _cache_key(city, state), geocode_city_state(city, state)

    if pending:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futures = [pool.submit(_work, pair) for pair in pending]
            for future in as_completed(futures):
                key, point = future.result()
                with lock:
                    cache[key] = list(point) if point else None
                    completed += 1
                    if completed % 50 == 0 or completed == len(pending):
                        _save_city_cache(cache)
                        if progress_callback:
                            progress_callback(
                                f"Geocoded {done + completed}/{total} unique cities"
                            )
                        time.sleep(0.02)

    _save_city_cache(cache)

    results: dict[int, tuple[float, float]] = {}
    for station in stations:
        key = _cache_key(station.city, station.state)
        point = cache.get(key)
        if point:
            results[station.pk] = (float(point[0]), float(point[1]))
    return results
