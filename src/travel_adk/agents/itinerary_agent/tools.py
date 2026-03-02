import os
import time
from datetime import date, timedelta
from typing import Any, Dict, List

import requests
import urllib3

from travel_adk.config.settings import load_environment


def _normalize_query(query: str) -> str:
    return " ".join((query or "").strip().split())


def _weather_label_and_group(code: int) -> Dict[str, str]:
    mapping: Dict[int, Dict[str, str]] = {
        0: {"label": "Despejado", "group": "sunny"},
        1: {"label": "Poco nuboso", "group": "sunny"},
        2: {"label": "Parcialmente nuboso", "group": "cloudy"},
        3: {"label": "Cubierto", "group": "cloudy"},
        45: {"label": "Niebla", "group": "fog"},
        48: {"label": "Niebla con escarcha", "group": "fog"},
        51: {"label": "Llovizna ligera", "group": "rain"},
        53: {"label": "Llovizna moderada", "group": "rain"},
        55: {"label": "Llovizna densa", "group": "rain"},
        56: {"label": "Llovizna helada ligera", "group": "rain"},
        57: {"label": "Llovizna helada densa", "group": "rain"},
        61: {"label": "Lluvia ligera", "group": "rain"},
        63: {"label": "Lluvia moderada", "group": "rain"},
        65: {"label": "Lluvia fuerte", "group": "rain"},
        66: {"label": "Lluvia helada ligera", "group": "rain"},
        67: {"label": "Lluvia helada fuerte", "group": "rain"},
        71: {"label": "Nieve ligera", "group": "snow"},
        73: {"label": "Nieve moderada", "group": "snow"},
        75: {"label": "Nieve intensa", "group": "snow"},
        77: {"label": "Granizo fino", "group": "snow"},
        80: {"label": "Chubascos ligeros", "group": "rain"},
        81: {"label": "Chubascos moderados", "group": "rain"},
        82: {"label": "Chubascos violentos", "group": "storm"},
        85: {"label": "Nevadas ligeras", "group": "snow"},
        86: {"label": "Nevadas intensas", "group": "snow"},
        95: {"label": "Tormenta", "group": "storm"},
        96: {"label": "Tormenta con granizo ligero", "group": "storm"},
        99: {"label": "Tormenta con granizo fuerte", "group": "storm"},
    }
    return mapping.get(code, {"label": "Variable", "group": "neutral"})


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _request_json_with_retries(
    url: str,
    params: Dict[str, Any],
    timeout_s: float,
    verify_ssl: bool,
    max_retries: int,
) -> Dict[str, Any]:
    headers = {"User-Agent": "TravelBuddy/1.0 (+weather-open-meteo)"}
    last_exc: Exception | None = None

    if not verify_ssl:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    for attempt in range(max_retries + 1):
        try:
            resp = requests.get(
                url,
                params=params,
                timeout=timeout_s,
                verify=verify_ssl,
                headers=headers,
            )
            resp.raise_for_status()
            return resp.json() or {}
        except requests.exceptions.RequestException as exc:
            last_exc = exc
            if attempt < max_retries:
                time.sleep(0.5 * (2**attempt))
                continue
            raise

    if last_exc:
        raise last_exc
    return {}


def get_weather_forecast(
    destination: str,
    start_date: str,
    end_date: str,
    language: str = "es",
) -> Dict[str, Any]:
    load_environment()

    city = _normalize_query(destination)
    if not city:
        return {"destination": destination, "source": "open-meteo", "days": [], "error": "empty_destination"}

    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except Exception:
        return {
            "destination": city,
            "source": "open-meteo",
            "days": [],
            "error": "invalid_date_format",
        }

    if end < start:
        return {
            "destination": city,
            "source": "open-meteo",
            "days": [],
            "error": "invalid_date_range",
        }

    timeout_s_raw = os.getenv("OPEN_METEO_TIMEOUT_S", "12").strip()
    try:
        timeout_s = max(2.0, min(float(timeout_s_raw), 60.0))
    except Exception:
        timeout_s = 12.0

    retries_raw = os.getenv("OPEN_METEO_MAX_RETRIES", "2").strip()
    try:
        max_retries = max(0, min(int(retries_raw), 5))
    except Exception:
        max_retries = 2

    verify_ssl = _env_bool("OPEN_METEO_VERIFY_SSL", True)

    try:
        geocode_payload = _request_json_with_retries(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city, "count": 1, "language": language, "format": "json"},
            timeout_s=timeout_s,
            verify_ssl=verify_ssl,
            max_retries=max_retries,
        )
        places = geocode_payload.get("results", []) or []
        if not places:
            return {
                "destination": city,
                "source": "open-meteo",
                "days": [],
                "error": "destination_not_found",
            }

        place = places[0]
        latitude = place.get("latitude")
        longitude = place.get("longitude")
        timezone = place.get("timezone") or "auto"
        resolved_name = place.get("name") or city
        country = place.get("country")

        today = date.today()
        max_supported_end = today + timedelta(days=16)
        range_start = max(start, today)
        range_end = min(end, max_supported_end)
        if range_start > range_end:
            return {
                "destination": resolved_name,
                "country": country,
                "latitude": latitude,
                "longitude": longitude,
                "timezone": timezone,
                "requested_start_date": start.isoformat(),
                "requested_end_date": end.isoformat(),
                "forecast_supported_until": max_supported_end.isoformat(),
                "source": "open-meteo",
                "days": [],
                "warning": "forecast_out_of_range",
            }

        forecast_payload = _request_json_with_retries(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": latitude,
                "longitude": longitude,
                "timezone": timezone,
                "start_date": range_start.isoformat(),
                "end_date": range_end.isoformat(),
                "daily": (
                    "weather_code,temperature_2m_max,temperature_2m_min,"
                    "precipitation_probability_max,precipitation_sum"
                ),
            },
            timeout_s=timeout_s,
            verify_ssl=verify_ssl,
            max_retries=max_retries,
        )
        daily = forecast_payload.get("daily", {}) or {}

        times = daily.get("time", []) or []
        weather_codes = daily.get("weather_code", []) or []
        tmax = daily.get("temperature_2m_max", []) or []
        tmin = daily.get("temperature_2m_min", []) or []
        pop = daily.get("precipitation_probability_max", []) or []
        precip = daily.get("precipitation_sum", []) or []

        days: List[Dict[str, Any]] = []
        for i, d in enumerate(times):
            code = int(weather_codes[i]) if i < len(weather_codes) and weather_codes[i] is not None else -1
            label_info = _weather_label_and_group(code)
            days.append(
                {
                    "date": d,
                    "weather_code": code,
                    "weather_label": label_info["label"],
                    "weather_group": label_info["group"],
                    "temp_max_c": tmax[i] if i < len(tmax) else None,
                    "temp_min_c": tmin[i] if i < len(tmin) else None,
                    "precipitation_probability_max": pop[i] if i < len(pop) else None,
                    "precipitation_sum_mm": precip[i] if i < len(precip) else None,
                }
            )

        return {
            "destination": resolved_name,
            "country": country,
            "latitude": latitude,
            "longitude": longitude,
            "timezone": forecast_payload.get("timezone") or timezone,
            "requested_start_date": start.isoformat(),
            "requested_end_date": end.isoformat(),
            "forecast_start_date": range_start.isoformat(),
            "forecast_end_date": range_end.isoformat(),
            "forecast_supported_until": max_supported_end.isoformat(),
            "partial_coverage": (range_start != start) or (range_end != end),
            "source": "open-meteo",
            "days": days,
        }
    except requests.exceptions.SSLError as exc:
        mode_hint = (
            "Puedes probar OPEN_METEO_VERIFY_SSL=0 temporalmente para demo "
            "(no recomendado para producción)."
        )
        return {
            "destination": city,
            "source": "open-meteo",
            "days": [],
            "error": "ssl_error",
            "message": f"{type(exc).__name__}: {exc}. {mode_hint}",
        }
    except Exception as exc:
        return {
            "destination": city,
            "source": "open-meteo",
            "days": [],
            "error": f"request_failed: {type(exc).__name__}: {exc}",
        }


def google_search(
    query: str,
    num_results: int = 3,
    language: str = "es",
    country: str = "es",
) -> Dict[str, Any]:
    load_environment()

    q = _normalize_query(query)
    if not q:
        return {
            "query": query,
            "source": "serpapi_google",
            "results": [],
            "error": "empty_query",
        }

    api_key = os.getenv("SERPAPI_API_KEY", "").strip()
    if not api_key:
        return {
            "query": q,
            "source": "serpapi_google",
            "results": [],
            "error": "missing SERPAPI_API_KEY",
        }

    try:
        n = int(num_results)
    except Exception:
        n = 3
    n = max(1, min(n, 5))

    timeout_s_raw = os.getenv("SERPAPI_TIMEOUT_S", "12").strip()
    try:
        timeout_s = max(2.0, min(float(timeout_s_raw), 60.0))
    except Exception:
        timeout_s = 12.0

    params = {
        "engine": "google",
        "api_key": api_key,
        "q": q,
        "num": n,
        "hl": language,
        "gl": country,
    }

    try:
        response = requests.get(
            "https://serpapi.com/search.json",
            params=params,
            timeout=timeout_s,
        )
    except Exception as exc:
        return {
            "query": q,
            "source": "serpapi_google",
            "results": [],
            "error": f"request_failed: {type(exc).__name__}: {exc}",
        }

    if not (200 <= response.status_code < 300):
        return {
            "query": q,
            "source": "serpapi_google",
            "results": [],
            "error": f"http_{response.status_code}",
            "message": response.text[:500],
        }

    payload = response.json() or {}
    api_error = payload.get("error")
    if api_error:
        return {
            "query": q,
            "source": "serpapi_google",
            "results": [],
            "error": f"api_error: {api_error}",
        }

    items = payload.get("organic_results", []) or []

    results: List[Dict[str, Any]] = []
    for item in items:
        link = item.get("link")
        if not link:
            continue
        results.append(
            {
                "title": item.get("title"),
                "url": link,
                "snippet": item.get("snippet"),
            }
        )

    return {
        "query": q,
        "source": "serpapi_google",
        "results": results,
    }
