from __future__ import annotations

import asyncio
import json
import os
from datetime import date
from pathlib import Path
from time import monotonic
from typing import Any, Dict, List, Optional
from uuid import uuid4

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

from travel_adk.agents.hotel_agent.hotel_agent import build_hotel_agent
from travel_adk.agents.itinerary_agent.itinerary_agent import build_itinerary_planner_agent
from travel_adk.agents.itinerary_agent.tools import get_weather_forecast
from travel_adk.agents.planner_agent.planner_agent import build_planner_agent
from travel_adk.agents.transport_agent.transport_agent import build_transport_agent
from travel_adk.agents.transport_agent.tools import search_transport_options_from_trip
from travel_adk.config.settings import load_environment
from travel_adk.state.keys import (
    CANDIDATE_BUNDLES_JSON,
    FINAL_ITINERARY_JSON,
    HOTEL_OPTIONS_JSON,
    SELECTED_BUNDLE_JSON,
    TRANSPORT_OPTIONS_JSON,
    TRIP_REQUEST_JSON,
    WEATHER_FORECAST_JSON,
)

load_environment()

_OPTIONS_CACHE_TTL_S = max(0, int(os.getenv("TRAVEL_OPTIONS_CACHE_TTL_S", "900")))
_ITINERARY_CACHE_TTL_S = max(0, int(os.getenv("TRAVEL_ITINERARY_CACHE_TTL_S", "1800")))
_ROAD_ROUTE_CACHE_TTL_S = max(0, int(os.getenv("TRAVEL_ROAD_ROUTE_CACHE_TTL_S", "86400")))
_CACHE_MAX_ITEMS = max(16, int(os.getenv("TRAVEL_CACHE_MAX_ITEMS", "128")))
_MAP_TIMEOUT_S = max(
    2.0,
    min(float(os.getenv("MAP_TIMEOUT_S", os.getenv("DAY_MAP_TIMEOUT_S", "10"))), 30.0),
)
_NOMINATIM_SEARCH_URL = os.getenv("NOMINATIM_SEARCH_URL", "https://nominatim.openstreetmap.org/search")
_OSRM_BASE_URL = os.getenv("OSRM_BASE_URL", "https://router.project-osrm.org/route/v1")

_options_cache: Dict[str, tuple[float, Dict[str, Any]]] = {}
_itinerary_cache: Dict[str, tuple[float, Dict[str, Any]]] = {}
_road_route_cache: Dict[str, tuple[float, Dict[str, Any]]] = {}
_options_cache_lock = asyncio.Lock()
_itinerary_cache_lock = asyncio.Lock()
_road_route_cache_lock = asyncio.Lock()


def _read_float_env(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except Exception:
        return default
    return max(minimum, min(value, maximum))


def _stable_json_key(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _cache_get(cache: Dict[str, tuple[float, Dict[str, Any]]], key: str) -> Optional[Dict[str, Any]]:
    item = cache.get(key)
    if not item:
        return None
    expires_at, value = item
    if expires_at < monotonic():
        cache.pop(key, None)
        return None
    return value


def _cache_set(cache: Dict[str, tuple[float, Dict[str, Any]]], key: str, value: Dict[str, Any], ttl_s: int) -> None:
    if ttl_s <= 0:
        return

    cache[key] = (monotonic() + ttl_s, value)
    if len(cache) <= _CACHE_MAX_ITEMS:
        return

    now = monotonic()
    for cache_key, (expires_at, _) in list(cache.items()):
        if expires_at < now:
            cache.pop(cache_key, None)

    if len(cache) <= _CACHE_MAX_ITEMS:
        return

    overflow = len(cache) - _CACHE_MAX_ITEMS
    if overflow <= 0:
        return
    oldest = sorted(cache.items(), key=lambda x: x[1][0])[:overflow]
    for cache_key, _ in oldest:
        cache.pop(cache_key, None)


def _normalize_interests(raw: str | List[str]) -> List[str]:
    items: List[str] = []
    if isinstance(raw, str):
        items = [x.strip().lower() for x in raw.split(",")]
    else:
        items = [str(x).strip().lower() for x in raw]

    deduped: List[str] = []
    for item in items:
        if item and item not in deduped:
            deduped.append(item)
    return deduped


def _coerce_state_payload(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw

    if hasattr(raw, "model_dump"):
        dumped = raw.model_dump()
        if isinstance(dumped, dict):
            return dumped

    if isinstance(raw, str):
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed

    raise ValueError(f"Formato de payload no soportado: {type(raw).__name__}")


def _extract_itinerary_candidate(raw: Any) -> Optional[Dict[str, Any]]:
    candidate = raw
    if not isinstance(candidate, dict):
        return None

    if FINAL_ITINERARY_JSON in candidate and isinstance(candidate[FINAL_ITINERARY_JSON], dict):
        candidate = candidate[FINAL_ITINERARY_JSON]

    if isinstance(candidate.get("summary"), str) and isinstance(candidate.get("days"), list):
        return candidate
    return None


def _parse_itinerary_from_text(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None

    raw = text.strip()
    candidates = [raw]

    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        candidates.append("\n".join(lines).strip())

    decoder = json.JSONDecoder()
    expanded: List[str] = list(candidates)
    for item in candidates:
        for idx, ch in enumerate(item):
            if ch != "{":
                continue
            try:
                obj, _ = decoder.raw_decode(item[idx:])
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                expanded.append(json.dumps(obj, ensure_ascii=False))
                break

    for item in expanded:
        if not item:
            continue
        try:
            parsed = json.loads(item)
        except Exception:
            continue
        itinerary = _extract_itinerary_candidate(parsed)
        if itinerary:
            return itinerary
    return None


def _extract_itinerary_from_events(events: List[Any]) -> Optional[Dict[str, Any]]:
    text_chunks: List[str] = []

    for event in events:
        content = getattr(event, "content", None)
        parts = getattr(content, "parts", None) or []
        for part in parts:
            text = getattr(part, "text", None)
            if isinstance(text, str) and text.strip():
                text_chunks.append(text)

            function_response = getattr(part, "function_response", None)
            if function_response is None:
                continue

            response_payload = None
            if isinstance(function_response, dict):
                response_payload = function_response.get("response", function_response)
            else:
                response_payload = getattr(function_response, "response", None)

            itinerary = _extract_itinerary_candidate(response_payload)
            if itinerary:
                return itinerary

    for text in reversed(text_chunks):
        itinerary = _parse_itinerary_from_text(text)
        if itinerary:
            return itinerary

    if text_chunks:
        tail = "\n".join(text_chunks[-5:])
        itinerary = _parse_itinerary_from_text(tail)
        if itinerary:
            return itinerary

    return None


def _event_part_types(events: List[Any]) -> List[str]:
    types_seen: List[str] = []
    for event in events[-8:]:
        content = getattr(event, "content", None)
        parts = getattr(content, "parts", None) or []
        for part in parts:
            part_type = "unknown"
            if getattr(part, "function_call", None) is not None:
                part_type = "function_call"
            elif getattr(part, "function_response", None) is not None:
                part_type = "function_response"
            elif getattr(part, "text", None):
                part_type = "text"
            elif getattr(part, "executable_code", None) is not None:
                part_type = "executable_code"
            elif getattr(part, "code_execution_result", None) is not None:
                part_type = "code_execution_result"
            types_seen.append(part_type)
    return types_seen


def _default_agent_model() -> str:
    return os.getenv("TRAVEL_AGENT_MODEL", os.getenv("ITINERARY_AGENT_MODEL", "gemini-2.5-flash"))


def _ensure_google_llm_api_key() -> None:
    if os.getenv("GOOGLE_API_KEY"):
        return

    for alias in ("GEMINI_API_KEY", "GOOGLE_GENAI_API_KEY", "GOOGLE_AI_API_KEY"):
        value = os.getenv(alias, "").strip()
        if value:
            os.environ["GOOGLE_API_KEY"] = value
            return


def _fetch_weather_for_trip(trip: Dict[str, Any]) -> Dict[str, Any]:
    return get_weather_forecast(
        destination=str(trip.get("destination") or ""),
        start_date=str(trip.get("start_date") or ""),
        end_date=str(trip.get("end_date") or ""),
    )


def _geocode_place(query: str) -> Optional[Dict[str, Any]]:
    q = " ".join(str(query or "").strip().split())
    if not q:
        return None

    try:
        resp = requests.get(
            _NOMINATIM_SEARCH_URL,
            params={
                "q": q,
                "format": "jsonv2",
                "limit": 1,
                "addressdetails": 0,
            },
            headers={
                "User-Agent": "TravelBuddy/1.0 (+road-route)",
                "Accept-Language": "es",
            },
            timeout=_MAP_TIMEOUT_S,
        )
        if not (200 <= resp.status_code < 300):
            return None

        payload = resp.json() or []
        if not payload:
            return None

        item = payload[0]
        return {
            "query": q,
            "label": str(item.get("display_name") or q),
            "lat": float(item.get("lat")),
            "lon": float(item.get("lon")),
        }
    except Exception:
        return None


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    from math import asin, cos, radians, sin, sqrt

    r = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    c = 2 * asin(sqrt(a))
    return r * c


def _route_points_osrm(points: List[Dict[str, Any]], mode: str) -> Optional[Dict[str, Any]]:
    if len(points) < 2:
        return None

    profile = "driving" if mode == "driving" else "walking"
    coords = ";".join(f"{float(p['lon'])},{float(p['lat'])}" for p in points)
    url = f"{_OSRM_BASE_URL}/{profile}/{coords}"

    try:
        resp = requests.get(
            url,
            params={
                "overview": "full",
                "geometries": "geojson",
                "steps": "false",
            },
            headers={"User-Agent": "TravelBuddy/1.0 (+road-route)"},
            timeout=_MAP_TIMEOUT_S,
        )
        if not (200 <= resp.status_code < 300):
            return None
        payload = resp.json() or {}
        routes = payload.get("routes", []) or []
        if not routes:
            return None

        route = routes[0]
        legs_payload = route.get("legs", []) or []
        legs: List[Dict[str, Any]] = []
        for idx, leg in enumerate(legs_payload):
            distance_km = round(float(leg.get("distance", 0.0)) / 1000.0, 2)
            duration_min = round(float(leg.get("duration", 0.0)) / 60.0, 1)
            legs.append(
                {
                    "from_idx": idx,
                    "to_idx": idx + 1,
                    "distance_km": distance_km,
                    "duration_min": duration_min,
                }
            )

        geometry = route.get("geometry", {}) or {}
        coordinates = geometry.get("coordinates", []) or []
        path = [[float(lat), float(lon)] for lon, lat in coordinates if len([lon, lat]) == 2]

        return {
            "path": path,
            "legs": legs,
            "total_distance_km": round(float(route.get("distance", 0.0)) / 1000.0, 2),
            "total_duration_min": round(float(route.get("duration", 0.0)) / 60.0, 1),
            "source": "osrm",
        }
    except Exception:
        return None


def _number_or_none(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except Exception:
        return default
    return max(minimum, min(value, maximum))


async def _build_car_transport_options_async(trip_request: Dict[str, Any]) -> tuple[List[Dict[str, Any]], List[str]]:
    origin = str(trip_request.get("origin") or "").strip()
    destination = str(trip_request.get("destination") or "").strip()
    start_date = str(trip_request.get("start_date") or "")
    end_date = str(trip_request.get("end_date") or "")
    notices: List[str] = []
    options: List[Dict[str, Any]] = []

    if not origin or not destination:
        notices.append("No se pudo estimar coche: faltan origen/destino.")
        return options, notices

    origin_geo, destination_geo = await asyncio.gather(
        asyncio.to_thread(_geocode_place, origin),
        asyncio.to_thread(_geocode_place, destination),
    )
    if not origin_geo or not destination_geo:
        notices.append("No se pudo geolocalizar origen/destino para estimar trayecto en coche.")
        return options, notices

    route = await asyncio.to_thread(_route_points_osrm, [origin_geo, destination_geo], "driving")
    has_valid_road_route = route is not None
    if route:
        one_way_km = float(route.get("total_distance_km", 0.0))
        one_way_min = float(route.get("total_duration_min", 0.0))
    else:
        notices.append(
            "No se pudo calcular ruta por carretera con OSRM; se usa distancia en línea recta para estimación de gasolina."
        )
        one_way_km = _haversine_km(
            float(origin_geo["lat"]),
            float(origin_geo["lon"]),
            float(destination_geo["lat"]),
            float(destination_geo["lon"]),
        )
        one_way_min = (one_way_km / 70.0) * 60.0

    fuel_price_eur_l = _read_float_env("CAR_FUEL_PRICE_EUR_PER_L", default=1.65, minimum=0.6, maximum=5.0)
    roundtrip_factor = _read_float_env("CAR_ROUNDTRIP_MULTIPLIER", default=2.0, minimum=1.0, maximum=2.5)
    max_cars = _int_env("TRAVEL_MAX_CAR_OPTIONS", default=3, minimum=1, maximum=5)

    profile_consumptions: List[tuple[str, str, float]] = [
        (
            "C1",
            "Coche eficiente",
            _read_float_env("CAR_FUEL_L_PER_100KM_ECO", default=5.4, minimum=3.0, maximum=25.0),
        ),
        (
            "C2",
            "Coche estándar",
            _read_float_env(
                "CAR_FUEL_L_PER_100KM_STANDARD",
                default=_read_float_env("CAR_FUEL_L_PER_100KM", default=6.8, minimum=3.0, maximum=25.0),
                minimum=3.0,
                maximum=25.0,
            ),
        ),
        (
            "C3",
            "SUV / grande",
            _read_float_env("CAR_FUEL_L_PER_100KM_SUV", default=8.9, minimum=3.0, maximum=25.0),
        ),
        (
            "C4",
            "Van / familiar",
            _read_float_env("CAR_FUEL_L_PER_100KM_VAN", default=9.8, minimum=3.0, maximum=25.0),
        ),
        (
            "C5",
            "Premium",
            _read_float_env("CAR_FUEL_L_PER_100KM_PREMIUM", default=10.8, minimum=3.0, maximum=25.0),
        ),
    ][:max_cars]

    roundtrip_km = one_way_km * roundtrip_factor
    roundtrip_h = (one_way_min * roundtrip_factor) / 60.0
    route_note = "Ruta validada por carretera." if has_valid_road_route else "Ruta no validada; estimación en línea recta."

    for option_id, label, liters_per_100_km in profile_consumptions:
        fuel_liters = (roundtrip_km / 100.0) * liters_per_100_km
        fuel_total_eur = round(fuel_liters * fuel_price_eur_l, 2)
        options.append(
            {
                "id": option_id,
                "mode": "coche",
                "provider": label,
                "departure_date": start_date,
                "arrival_date": end_date,
                "total_price": fuel_total_eur,
                "currency": "EUR",
                "notes": (
                    f"Ida/vuelta aprox: {roundtrip_km:.1f} km, {roundtrip_h:.1f} h. "
                    f"Consumo {liters_per_100_km:.1f}L/100km, combustible {fuel_price_eur_l:.2f} €/L. {route_note}"
                ),
            }
        )

    return options, notices


def _select_hotels_for_bundles(hotel_options: Dict[str, Any]) -> List[Dict[str, Any]]:
    hotels = (hotel_options or {}).get("hotels", []) or []
    if not hotels:
        return []
    max_hotels = _int_env("TRAVEL_MAX_HOTELS_FOR_BUNDLES", default=3, minimum=1, maximum=6)
    return sorted(
        hotels,
        key=lambda hotel: (
            _number_or_none(hotel.get("price_total")) is None,
            _number_or_none(hotel.get("price_total")) or 10**12,
        ),
    )[:max_hotels]


def _build_dual_mode_bundles(
    transport_options: Dict[str, Any],
    hotel_options: Dict[str, Any],
) -> tuple[Dict[str, Any], List[str]]:
    notices: List[str] = []
    bundles: List[Dict[str, Any]] = []

    hotels = _select_hotels_for_bundles(hotel_options)
    if not hotels:
        notices.append("No se encontraron hoteles para construir bundles comparables (coche vs avión).")
        return {"bundles": []}, notices

    transports = (transport_options or {}).get("transports", []) or []

    def _pick_transports(mode: str, max_items: int) -> List[Dict[str, Any]]:
        mode_items = [x for x in transports if str(x.get("mode") or "").lower() == mode]
        if not mode_items:
            return []
        return sorted(
            mode_items,
            key=lambda item: (
                _number_or_none(item.get("total_price")) is None,
                _number_or_none(item.get("total_price")) or 10**12,
            ),
        )[:max_items]

    max_car_bundles = _int_env("TRAVEL_MAX_CAR_BUNDLES", default=3, minimum=1, maximum=5)
    max_flight_bundles = _int_env("TRAVEL_MAX_FLIGHT_BUNDLES", default=3, minimum=1, maximum=5)
    car_items = _pick_transports("coche", max_car_bundles)
    flight_items = _pick_transports("avion", max_flight_bundles)

    if not car_items:
        notices.append("No se pudo generar opción de coche; solo se mostrará vuelo + hotel.")
    if not flight_items:
        notices.append("No se encontraron vuelos; solo se mostrará coche + hotel.")

    def _bundle_total(transport: Dict[str, Any], hotel_price: Optional[float]) -> Optional[float]:
        transport_price = _number_or_none(transport.get("total_price"))
        if transport_price is None or hotel_price is None:
            return None
        return round(transport_price + hotel_price, 2)

    def _build_mode_candidates(
        *,
        mode_items: List[Dict[str, Any]],
        label_prefix: str,
        pros: List[str],
        cons: List[str],
        max_bundles: int,
    ) -> List[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []
        for transport in mode_items:
            for hotel in hotels:
                hotel_id = str(hotel.get("id") or "")
                hotel_name = str(hotel.get("name") or hotel_id or "Hotel")
                hotel_price = _number_or_none(hotel.get("price_total"))
                total = _bundle_total(transport, hotel_price)
                candidates.append(
                    {
                        "transport_id": str(transport.get("id") or ""),
                        "hotel_id": hotel_id,
                        "hotel_name": hotel_name,
                        "total_estimated_cost_eur": total,
                        "pros": [*pros, f"Hotel: {hotel_name}"],
                        "cons": cons,
                    }
                )
        candidates.sort(
            key=lambda item: (
                _number_or_none(item.get("total_estimated_cost_eur")) is None,
                _number_or_none(item.get("total_estimated_cost_eur")) or 10**12,
            )
        )
        trimmed = candidates[:max_bundles]
        for idx, item in enumerate(trimmed, start=1):
            item["label"] = f"{label_prefix} · Opción {idx} · {item['hotel_name']}"
        return trimmed

    car_candidates = _build_mode_candidates(
        mode_items=car_items,
        label_prefix="Road Trip + Hotel",
        pros=[
            "Más flexibilidad de horarios y paradas",
            "Incluye estimación de gasolina",
        ],
        cons=[
            "Más horas de desplazamiento",
        ],
        max_bundles=max_car_bundles,
    )
    flight_candidates = _build_mode_candidates(
        mode_items=flight_items,
        label_prefix="Vuelo + Hotel",
        pros=[
            "Menor tiempo de viaje",
            "Comparación directa con opción de coche",
        ],
        cons=[
            "Menos flexibilidad de cambios en ruta",
        ],
        max_bundles=max_flight_bundles,
    )

    bundle_counter = 1
    for candidate in [*car_candidates, *flight_candidates]:
        bundles.append(
            {
                "bundle_id": f"B{bundle_counter}",
                "label": candidate["label"],
                "transport_id": candidate["transport_id"],
                "hotel_id": candidate["hotel_id"],
                "total_estimated_cost_eur": candidate["total_estimated_cost_eur"],
                "pros": candidate["pros"],
                "cons": candidate["cons"],
            }
        )
        bundle_counter += 1

    return {"bundles": bundles}, notices


async def _ensure_min_flight_options_async(
    *,
    trip_request: Dict[str, Any],
    current_flights: List[Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], Optional[str]]:
    min_flights = _int_env("TRAVEL_MIN_FLIGHT_OPTIONS", default=2, minimum=1, maximum=5)
    if len(current_flights) >= min_flights:
        return current_flights, None

    fallback_limit = max(
        _int_env("TRAVEL_MAX_FLIGHT_BUNDLES", default=3, minimum=1, maximum=5),
        min_flights,
    )
    fallback_raw = await asyncio.to_thread(
        search_transport_options_from_trip,
        origin=str(trip_request.get("origin") or ""),
        destination=str(trip_request.get("destination") or ""),
        departure_date=str(trip_request.get("start_date") or ""),
        return_date=str(trip_request.get("end_date") or ""),
        origin_iata=trip_request.get("origin_iata"),
        destination_iata=trip_request.get("destination_iata"),
        limit=fallback_limit,
    )
    fallback_flights = (fallback_raw or {}).get("transports", []) or []
    fallback_flights = [x for x in fallback_flights if str(x.get("mode") or "").lower() == "avion"]
    if not fallback_flights:
        return current_flights, "No se encontraron más vuelos en fallback directo de Amadeus."

    merged: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for item in [*current_flights, *fallback_flights]:
        item_id = str(item.get("id") or "").strip()
        key = item_id or json.dumps(item, ensure_ascii=False, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)

    if len(merged) > len(current_flights):
        return merged, f"Se ampliaron opciones de vuelo con fallback directo de Amadeus (total: {len(merged)})."
    return merged, None


class TripOptionsRequest(BaseModel):
    origin: str
    destination: str
    start_date: date
    end_date: date
    interests: str | List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_dates(self) -> "TripOptionsRequest":
        if self.end_date <= self.start_date:
            raise ValueError("La fecha de fin debe ser posterior a la de inicio.")
        return self

    def to_trip_form_input(self) -> Dict[str, Any]:
        return {
            "origin": " ".join(self.origin.strip().split()),
            "destination": " ".join(self.destination.strip().split()),
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "transport_mode": "avion",
            "interests": _normalize_interests(self.interests),
        }


class TripOptionsResponse(BaseModel):
    trip_request: Dict[str, Any]
    transport_options: Dict[str, Any]
    hotel_options: Dict[str, Any]
    candidate_bundles: Dict[str, Any]
    weather_forecast: Dict[str, Any] = Field(default_factory=dict)
    notices: List[str] = Field(default_factory=list)


class GenerateItineraryRequest(BaseModel):
    trip_request: Dict[str, Any]
    selected_bundle: Dict[str, Any]
    weather_forecast: Dict[str, Any] = Field(default_factory=dict)


class GenerateItineraryResponse(BaseModel):
    final_itinerary: Dict[str, Any]
    notices: List[str] = Field(default_factory=list)


class RoadRouteRequest(BaseModel):
    origin: str
    destination: str


class RoadRoutePoint(BaseModel):
    label: str
    lat: float
    lon: float


class RoadRouteResponse(BaseModel):
    origin: str
    destination: str
    origin_point: Optional[RoadRoutePoint] = None
    destination_point: Optional[RoadRoutePoint] = None
    reachable_by_car: bool = False
    path: List[List[float]] = Field(default_factory=list)
    distance_km: Optional[float] = None
    duration_min: Optional[float] = None
    direct_distance_km: Optional[float] = None
    warnings: List[str] = Field(default_factory=list)
    route_source: str = "none"


async def _run_agent_step_async(
    *,
    agent: Any,
    output_key: str,
    prompt: str,
    state: Optional[Dict[str, Any]] = None,
    app_name: str = "TravelBuddyApi",
) -> Dict[str, Any]:
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    session_service = InMemorySessionService()
    runner = Runner(
        app_name=app_name,
        agent=agent,
        session_service=session_service,
    )

    user_id = "api_user"
    session_id = f"{getattr(agent, 'name', 'agent')}-{uuid4()}"

    await session_service.create_session(
        app_name=app_name,
        user_id=user_id,
        session_id=session_id,
        state=state or {},
    )

    content = types.Content(role="user", parts=[types.Part.from_text(text=prompt)])

    events: List[Any] = []
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=content,
    ):
        events.append(event)

    session = await session_service.get_session(
        app_name=app_name,
        user_id=user_id,
        session_id=session_id,
    )
    session_state = (session.state if session else {}) or {}
    if output_key in session_state:
        return _coerce_state_payload(session_state[output_key])

    for event in reversed(events):
        actions = getattr(event, "actions", None)
        state_delta = getattr(actions, "state_delta", None) or {}
        if output_key in state_delta:
            return _coerce_state_payload(state_delta[output_key])

    last_error = ""
    for event in reversed(events):
        message = getattr(event, "error_message", None)
        if message:
            last_error = message
            break

    if last_error:
        raise RuntimeError(last_error)
    raise RuntimeError(f"No se obtuvo {output_key} desde {getattr(agent, 'name', 'agent')}.")


async def _run_core_agents_async(
    trip_form_input: Dict[str, Any],
) -> Dict[str, Any]:
    _ensure_google_llm_api_key()
    if not os.getenv("GOOGLE_API_KEY"):
        raise ValueError(
            "Falta clave LLM para ejecutar agentes "
            "(usa GOOGLE_API_KEY, GEMINI_API_KEY o GOOGLE_GENAI_API_KEY)."
        )

    model = _default_agent_model()

    planner_prompt = (
        "Normaliza esta solicitud de viaje y devuelve SOLO JSON valido conforme a TripRequest.\n"
        f"{json.dumps(trip_form_input, ensure_ascii=False)}"
    )
    trip_request = await _run_agent_step_async(
        agent=build_planner_agent(model),
        output_key=TRIP_REQUEST_JSON,
        prompt=planner_prompt,
    )

    flight_trip_request = dict(trip_request)
    flight_trip_request["transport_mode"] = "avion"

    transport_state = {TRIP_REQUEST_JSON: flight_trip_request}
    hotel_state = {TRIP_REQUEST_JSON: trip_request}
    weather_task = asyncio.to_thread(_fetch_weather_for_trip, trip_request)
    car_transport_task = _build_car_transport_options_async(trip_request)

    transport_task = _run_agent_step_async(
        agent=build_transport_agent(
            model,
            enable_maps_mcp=False,
        ),
        output_key=TRANSPORT_OPTIONS_JSON,
        prompt=(
            "Genera opciones de transporte usando trip_request_json. "
            "Devuelve idealmente entre 3 y 5 vuelos distintos cuando haya disponibilidad "
            "(si hay menos, devuelve todos los disponibles). "
            "Devuelve SOLO JSON valido."
        ),
        state=transport_state,
    )
    hotel_task = _run_agent_step_async(
        agent=build_hotel_agent(model),
        output_key=HOTEL_OPTIONS_JSON,
        prompt="Genera opciones de hotel usando trip_request_json. Devuelve SOLO JSON valido.",
        state=hotel_state,
    )
    flight_transport_options, hotel_options, weather_forecast, car_transport_result = await asyncio.gather(
        transport_task,
        hotel_task,
        weather_task,
        car_transport_task,
    )
    car_transports, car_notices = car_transport_result
    flight_transports = (flight_transport_options or {}).get("transports", []) or []
    # Dejar solo vuelos en la parte aérea por seguridad, por si el agente mezcla modos.
    flight_transports = [x for x in flight_transports if str(x.get("mode") or "").lower() == "avion"]
    flight_transports, flight_fallback_notice = await _ensure_min_flight_options_async(
        trip_request=flight_trip_request,
        current_flights=flight_transports,
    )
    extra_notices: List[str] = []
    if flight_fallback_notice:
        extra_notices.append(flight_fallback_notice)
    transport_options = {
        "transports": [*car_transports, *flight_transports],
    }
    bundle_options, bundle_notices = _build_dual_mode_bundles(transport_options, hotel_options)

    return {
        TRIP_REQUEST_JSON: trip_request,
        TRANSPORT_OPTIONS_JSON: transport_options,
        HOTEL_OPTIONS_JSON: hotel_options,
        CANDIDATE_BUNDLES_JSON: bundle_options,
        WEATHER_FORECAST_JSON: weather_forecast or {},
        "_notices": [*car_notices, *bundle_notices, *extra_notices],
    }


async def _generate_itinerary_with_agent_async(
    trip: Dict[str, Any],
    selected_bundle: Dict[str, Any],
    weather_forecast: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    _ensure_google_llm_api_key()
    if not os.getenv("GOOGLE_API_KEY"):
        raise ValueError(
            "Falta clave LLM para ItineraryPlannerAgent "
            "(usa GOOGLE_API_KEY, GEMINI_API_KEY o GOOGLE_GENAI_API_KEY)."
        )

    model = _default_agent_model()
    session_service = InMemorySessionService()
    runner = Runner(
        app_name="TravelBuddyApi",
        agent=build_itinerary_planner_agent(model),
        session_service=session_service,
    )

    user_id = "api_user"
    session_id = f"itinerary-{uuid4()}"
    await session_service.create_session(
        app_name="TravelBuddyApi",
        user_id=user_id,
        session_id=session_id,
        state={
            TRIP_REQUEST_JSON: trip,
            SELECTED_BUNDLE_JSON: selected_bundle,
            WEATHER_FORECAST_JSON: weather_forecast or {},
        },
    )

    async def _run_turn(prompt_text: str) -> List[Any]:
        content = types.Content(role="user", parts=[types.Part.from_text(text=prompt_text)])
        turn_events: List[Any] = []
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=content,
        ):
            turn_events.append(event)
        return turn_events

    async def _extract_result_from_state() -> Optional[Dict[str, Any]]:
        session = await session_service.get_session(
            app_name="TravelBuddyApi",
            user_id=user_id,
            session_id=session_id,
        )
        state = (session.state if session else {}) or {}
        if FINAL_ITINERARY_JSON not in state:
            return None
        return _coerce_state_payload(state[FINAL_ITINERARY_JSON])

    def _extract_result_from_events(local_events: List[Any]) -> Optional[Dict[str, Any]]:
        for event in reversed(local_events):
            actions = getattr(event, "actions", None)
            state_delta = getattr(actions, "state_delta", None) or {}
            if FINAL_ITINERARY_JSON in state_delta:
                return _coerce_state_payload(state_delta[FINAL_ITINERARY_JSON])
        return _extract_itinerary_from_events(local_events)

    events: List[Any] = []
    events.extend(
        await _run_turn(
            "Genera el itinerario final en JSON usando el destino, intereses y fechas. "
            "Investiga con google_search antes de proponer actividades."
        )
    )

    from_state = await _extract_result_from_state()
    if from_state:
        return from_state
    from_events = _extract_result_from_events(events)
    if from_events:
        return from_events

    part_types = _event_part_types(events)
    if "function_call" in part_types and "text" not in part_types:
        # A veces el modelo se queda en ciclo de herramientas; hacemos un turno de cierre forzado.
        events.extend(
            await _run_turn(
                "No llames más herramientas. "
                "Usa solo el contexto ya disponible y devuelve AHORA solo JSON válido "
                "con schema Itinerary: {summary: str, days: [{date: str, blocks: [str]}]}."
            )
        )

        from_state = await _extract_result_from_state()
        if from_state:
            return from_state
        from_events = _extract_result_from_events(events)
        if from_events:
            return from_events

    last_error = ""
    for event in reversed(events):
        message = getattr(event, "error_message", None)
        if message:
            last_error = message
            break

    if last_error:
        raise RuntimeError(last_error)
    raise RuntimeError(
        "No se obtuvo final_itinerary_json desde ItineraryPlannerAgent. "
        f"Partes observadas: {_event_part_types(events)}"
    )


app = FastAPI(
    title="Travel Buddy API",
    description="API local para generar bundles e itinerarios usando agentes ADK.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def healthcheck() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/favicon.ico", include_in_schema=False)
async def favicon_redirect() -> RedirectResponse:
    return RedirectResponse(url="/favicon.svg")


@app.post("/api/options", response_model=TripOptionsResponse)
async def generate_options(payload: TripOptionsRequest) -> TripOptionsResponse:
    trip_form_input = payload.to_trip_form_input()
    cache_key = _stable_json_key(trip_form_input)

    if _OPTIONS_CACHE_TTL_S > 0:
        async with _options_cache_lock:
            cached = _cache_get(_options_cache, cache_key)
        if cached:
            return TripOptionsResponse(**cached)

    try:
        flow_state = await _run_core_agents_async(trip_form_input=trip_form_input)
        weather = flow_state.get(WEATHER_FORECAST_JSON) or {}

        notices: List[str] = []
        notices.extend(flow_state.get("_notices", []) or [])
        if weather.get("warning") == "forecast_out_of_range":
            notices.append(
                "La previsión de Open-Meteo solo llega a fechas cercanas. "
                f"Disponible hasta {weather.get('forecast_supported_until')}."
            )
        elif weather.get("error"):
            detail = weather.get("message") or weather.get("error")
            notices.append(f"Previsión meteorológica no disponible: {detail}")

        response = TripOptionsResponse(
            trip_request=flow_state[TRIP_REQUEST_JSON],
            transport_options=flow_state[TRANSPORT_OPTIONS_JSON],
            hotel_options=flow_state[HOTEL_OPTIONS_JSON],
            candidate_bundles=flow_state[CANDIDATE_BUNDLES_JSON],
            weather_forecast=weather,
            notices=notices,
        )
        if _OPTIONS_CACHE_TTL_S > 0:
            async with _options_cache_lock:
                _cache_set(_options_cache, cache_key, response.model_dump(), _OPTIONS_CACHE_TTL_S)
        return response
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc


@app.post("/api/itinerary", response_model=GenerateItineraryResponse)
async def generate_itinerary(payload: GenerateItineraryRequest) -> GenerateItineraryResponse:
    request_payload = payload.model_dump()
    cache_key = _stable_json_key(request_payload)

    if _ITINERARY_CACHE_TTL_S > 0:
        async with _itinerary_cache_lock:
            cached = _cache_get(_itinerary_cache, cache_key)
        if cached:
            return GenerateItineraryResponse(**cached)

    notices: List[str] = []
    if not os.getenv("SERPAPI_API_KEY"):
        notices.append("Falta SERPAPI_API_KEY: el itinerario se generará sin búsqueda web.")

    try:
        itinerary = await _generate_itinerary_with_agent_async(
            trip=payload.trip_request,
            selected_bundle=payload.selected_bundle,
            weather_forecast=payload.weather_forecast,
        )
        response = GenerateItineraryResponse(final_itinerary=itinerary, notices=notices)
        if _ITINERARY_CACHE_TTL_S > 0:
            async with _itinerary_cache_lock:
                _cache_set(_itinerary_cache, cache_key, response.model_dump(), _ITINERARY_CACHE_TTL_S)
        return response
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc


@app.post("/api/road-route", response_model=RoadRouteResponse)
async def generate_road_route(payload: RoadRouteRequest) -> RoadRouteResponse:
    origin = " ".join(str(payload.origin or "").strip().split())
    destination = " ".join(str(payload.destination or "").strip().split())
    if not origin or not destination:
        raise HTTPException(status_code=400, detail="origin y destination son obligatorios.")

    cache_key = _stable_json_key({"origin": origin, "destination": destination, "mode": "driving"})
    if _ROAD_ROUTE_CACHE_TTL_S > 0:
        async with _road_route_cache_lock:
            cached = _cache_get(_road_route_cache, cache_key)
        if cached:
            return RoadRouteResponse(**cached)

    origin_geo, destination_geo = await asyncio.gather(
        asyncio.to_thread(_geocode_place, origin),
        asyncio.to_thread(_geocode_place, destination),
    )

    warnings: List[str] = []
    if not origin_geo:
        warnings.append(f"No se pudo geolocalizar el origen: {origin}.")
    if not destination_geo:
        warnings.append(f"No se pudo geolocalizar el destino: {destination}.")

    if not origin_geo or not destination_geo:
        response = RoadRouteResponse(
            origin=origin,
            destination=destination,
            reachable_by_car=False,
            warnings=warnings,
            route_source="none",
        )
        if _ROAD_ROUTE_CACHE_TTL_S > 0:
            async with _road_route_cache_lock:
                _cache_set(_road_route_cache, cache_key, response.model_dump(), _ROAD_ROUTE_CACHE_TTL_S)
        return response

    route = await asyncio.to_thread(_route_points_osrm, [origin_geo, destination_geo], "driving")
    direct_distance_km = round(
        _haversine_km(
            float(origin_geo["lat"]),
            float(origin_geo["lon"]),
            float(destination_geo["lat"]),
            float(destination_geo["lon"]),
        ),
        2,
    )

    if not route:
        warnings.append(
            "No existe una ruta en coche disponible entre origen y destino con el motor de rutas actual."
        )
        response = RoadRouteResponse(
            origin=origin,
            destination=destination,
            origin_point=RoadRoutePoint(
                label=str(origin_geo["label"]),
                lat=float(origin_geo["lat"]),
                lon=float(origin_geo["lon"]),
            ),
            destination_point=RoadRoutePoint(
                label=str(destination_geo["label"]),
                lat=float(destination_geo["lat"]),
                lon=float(destination_geo["lon"]),
            ),
            reachable_by_car=False,
            direct_distance_km=direct_distance_km,
            warnings=warnings,
            route_source="none",
        )
        if _ROAD_ROUTE_CACHE_TTL_S > 0:
            async with _road_route_cache_lock:
                _cache_set(_road_route_cache, cache_key, response.model_dump(), _ROAD_ROUTE_CACHE_TTL_S)
        return response

    response = RoadRouteResponse(
        origin=origin,
        destination=destination,
        origin_point=RoadRoutePoint(
            label=str(origin_geo["label"]),
            lat=float(origin_geo["lat"]),
            lon=float(origin_geo["lon"]),
        ),
        destination_point=RoadRoutePoint(
            label=str(destination_geo["label"]),
            lat=float(destination_geo["lat"]),
            lon=float(destination_geo["lon"]),
        ),
        reachable_by_car=True,
        path=route["path"],
        distance_km=float(route["total_distance_km"]),
        duration_min=float(route["total_duration_min"]),
        direct_distance_km=direct_distance_km,
        warnings=warnings,
        route_source=str(route.get("source") or "osrm"),
    )
    if _ROAD_ROUTE_CACHE_TTL_S > 0:
        async with _road_route_cache_lock:
            _cache_set(_road_route_cache, cache_key, response.model_dump(), _ROAD_ROUTE_CACHE_TTL_S)
    return response


FRONTEND_DIR = Path(__file__).resolve().parents[3] / "web_ui"

if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="ui")
else:
    @app.get("/", include_in_schema=False)
    async def root_missing() -> Dict[str, str]:
        return {"status": "ok", "message": "Frontend local no encontrado. Usa /docs o /api/health."}
