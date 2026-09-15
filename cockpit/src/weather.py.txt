"""
Local weather for the morning hero.

The cockpit greets whoever opens it, so the reading has to follow the person
rather than the bank: the location comes from the request's public IP, and the
forecast from Open-Meteo (no key, no account). Both calls are cached and both
fail soft — a cockpit that cannot reach the internet still renders, it just
drops the weather chip.
"""

import os

import requests
import streamlit as st
from dotenv import load_dotenv

# The hero can render before anything else pulls in src.config, so the
# location override has to load its own environment.
load_dotenv()

# Location providers, tried in order. ipapi.co is HTTPS but aggressively rate
# limits; ipwho.is is the HTTPS fallback; ip-api.com is HTTP-only and last.
_LOCATION_PROVIDERS = (
    ("https://ipapi.co/json/", "city", "country_name", "latitude", "longitude"),
    ("https://ipwho.is/", "city", "country", "latitude", "longitude"),
    ("http://ip-api.com/json/", "city", "country", "lat", "lon"),
)

_OPEN_METEO = "https://api.open-meteo.com/v1/forecast"

_REQUEST_TIMEOUT = 4.0

# WMO weather codes → the glyph and label shown in the hero chip.
_WMO_CODES = {
    0: ("☀", "Clear"),
    1: ("☀", "Mainly clear"),
    2: ("⛅", "Partly cloudy"),
    3: ("☁", "Overcast"),
    45: ("≡", "Fog"),
    48: ("≡", "Rime fog"),
    51: ("◌", "Light drizzle"),
    53: ("◌", "Drizzle"),
    55: ("◌", "Dense drizzle"),
    56: ("◌", "Freezing drizzle"),
    57: ("◌", "Freezing drizzle"),
    61: ("☂", "Light rain"),
    63: ("☂", "Rain"),
    65: ("☂", "Heavy rain"),
    66: ("☂", "Freezing rain"),
    67: ("☂", "Freezing rain"),
    71: ("❄", "Light snow"),
    73: ("❄", "Snow"),
    75: ("❄", "Heavy snow"),
    77: ("❄", "Snow grains"),
    80: ("☂", "Rain showers"),
    81: ("☂", "Rain showers"),
    82: ("☂", "Violent showers"),
    85: ("❄", "Snow showers"),
    86: ("❄", "Snow showers"),
    95: ("⚡", "Thunderstorm"),
    96: ("⚡", "Thunderstorm, hail"),
    99: ("⚡", "Thunderstorm, hail"),
}


def describe_code(code):
    """Map a WMO weather code to its (glyph, label) pair."""
    return _WMO_CODES.get(int(code), ("◍", "Unsettled"))


def _configured_location():
    """
    An explicit override, as ``COCKPIT_LOCATION="Milan,45.46,9.19"``.

    Useful when the cockpit runs behind a VPN or in a data centre, where the
    public IP says nothing about where the CFO actually is.
    """
    raw = os.getenv("COCKPIT_LOCATION", "").strip()
    if not raw:
        return None

    parts = [part.strip() for part in raw.split(",")]
    if len(parts) != 3:
        return None

    try:
        return {"city": parts[0], "country": "", "lat": float(parts[1]), "lon": float(parts[2])}
    except ValueError:
        return None


@st.cache_data(ttl=6 * 60 * 60, show_spinner=False)
def resolve_location():
    """Geolocate the viewer from their public IP. Returns None when offline."""
    override = _configured_location()
    if override is not None:
        return override

    for url, city_key, country_key, lat_key, lon_key in _LOCATION_PROVIDERS:
        try:
            response = requests.get(url, timeout=_REQUEST_TIMEOUT)
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError):
            continue

        latitude = payload.get(lat_key)
        longitude = payload.get(lon_key)
        if latitude is None or longitude is None:
            continue

        try:
            return {
                "city": str(payload.get(city_key) or "").strip(),
                "country": str(payload.get(country_key) or "").strip(),
                "lat": float(latitude),
                "lon": float(longitude),
            }
        except (TypeError, ValueError):
            continue

    return None


@st.cache_data(ttl=30 * 60, show_spinner=False)
def fetch_conditions(latitude, longitude):
    """Current temperature, day range and condition code for one point."""
    try:
        response = requests.get(
            _OPEN_METEO,
            params={
                "latitude": latitude,
                "longitude": longitude,
                "current": "temperature_2m,weather_code",
                "daily": "temperature_2m_max,temperature_2m_min",
                "forecast_days": 1,
                "timezone": "auto",
            },
            timeout=_REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        return None

    current = payload.get("current") or {}
    daily = payload.get("daily") or {}

    if current.get("temperature_2m") is None:
        return None

    def first(series):
        values = daily.get(series) or []
        return values[0] if values else None

    glyph, label = describe_code(current.get("weather_code", -1))

    return {
        "temperature_c": float(current["temperature_2m"]),
        "high_c": first("temperature_2m_max"),
        "low_c": first("temperature_2m_min"),
        "glyph": glyph,
        "label": label,
    }


def get_local_weather():
    """
    The hero's weather reading, or None when it cannot be established.

    Callers render nothing rather than a placeholder: a wrong temperature next
    to certified financials reads worse than no temperature at all.
    """
    location = resolve_location()
    if location is None:
        return None

    conditions = fetch_conditions(location["lat"], location["lon"])
    if conditions is None:
        return None

    place = location["city"] or location["country"] or "Current location"

    return {**conditions, "place": place, "country": location["country"]}