import re
from typing import Any, Dict, List, Optional

from travel_adk.services.amadeus_http import get_amadeus_client

_IATA_RE = re.compile(r"^[A-Z]{3}$")


def _normalize_iata(code: str) -> str:
    c = (code or "").strip().upper()
    return c if _IATA_RE.match(c) else ""


# ── Capa base: llama directamente a la API ────────────────────────────────────

def flight_offers_v2(
    origin: str,
    destination: str,
    departure_date: str,
    adults: int = 1,
    return_date: Optional[str] = None,
    travel_class: Optional[str] = None,   # ECONOMY | PREMIUM_ECONOMY | BUSINESS | FIRST
    max_results: int = 10,
    non_stop: bool = False,
    currency_code: str = "EUR",
) -> List[Dict[str, Any]]:
    """Llama a /v2/shopping/flight-offers y devuelve la lista raw de ofertas."""
    client = get_amadeus_client()

    params: Dict[str, Any] = {
        "originLocationCode": origin,
        "destinationLocationCode": destination,
        "departureDate": departure_date,
        "adults": adults,
        "max": max_results,
        "nonStop": str(non_stop).lower(),
        "currencyCode": currency_code,
    }
    if return_date:
        params["returnDate"] = return_date
    if travel_class:
        params["travelClass"] = travel_class

    payload = client.get("/v2/shopping/flight-offers", params=params)
    return payload.get("data", []) or []


# ── Capa alta: formatea y devuelve lo que el agente necesita ──────────────────

def search_flights(
    origin: str,
    destination: str,
    departure_date: str,
    adults: int = 1,
    return_date: Optional[str] = None,
    travel_class: Optional[str] = None,
    non_stop: bool = False,
    currency_code: str = "EUR",
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """
    Busca vuelos entre dos aeropuertos/ciudades IATA.

    Args:
        origin:          Código IATA de origen  (ej. "MAD")
        destination:     Código IATA de destino (ej. "JFK")
        departure_date:  Fecha de salida en formato YYYY-MM-DD
        adults:          Número de pasajeros adultos
        return_date:     Fecha de vuelta YYYY-MM-DD (None = solo ida)
        travel_class:    ECONOMY | PREMIUM_ECONOMY | BUSINESS | FIRST
        non_stop:        Si True, solo vuelos directos
        currency_code:   Divisa para los precios (default EUR)
        limit:           Máximo de resultados a devolver

    Returns:
        Lista de dicts con los vuelos disponibles, ordenados por precio.
    """
    orig = _normalize_iata(origin)
    dest = _normalize_iata(destination)
    if not orig or not dest:
        return []

    raw_offers = flight_offers_v2(
        origin=orig,
        destination=dest,
        departure_date=departure_date,
        adults=adults,
        return_date=return_date,
        travel_class=travel_class,
        max_results=min(limit * 3, 30),   # pedimos más de los necesarios para poder filtrar
        non_stop=non_stop,
        currency_code=currency_code,
    )

    results: List[Dict[str, Any]] = []
    for offer in raw_offers:
        price_block = offer.get("price", {}) or {}
        total = price_block.get("grandTotal") or price_block.get("total")
        currency = price_block.get("currency", currency_code)

        itineraries = offer.get("itineraries", []) or []

        # --- vuelo de ida ---
        outbound = itineraries[0] if itineraries else {}
        out_segments = outbound.get("segments", []) or []
        out_dep = (out_segments[0].get("departure", {}) if out_segments else {})
        out_arr = (out_segments[-1].get("arrival", {}) if out_segments else {})
        out_stops = len(out_segments) - 1

        # --- vuelo de vuelta (si es round-trip) ---
        inbound_info: Optional[Dict[str, Any]] = None
        if return_date and len(itineraries) > 1:
            inbound = itineraries[1]
            in_segments = inbound.get("segments", []) or []
            in_dep = (in_segments[0].get("departure", {}) if in_segments else {})
            in_arr = (in_segments[-1].get("arrival", {}) if in_segments else {})
            inbound_info = {
                "departure_airport": in_dep.get("iataCode"),
                "departure_time": in_dep.get("at"),
                "arrival_airport": in_arr.get("iataCode"),
                "arrival_time": in_arr.get("at"),
                "stops": len(in_segments) - 1,
                "duration": inbound.get("duration"),
            }

        # carrier del primer segmento
        carrier = out_segments[0].get("carrierCode") if out_segments else None
        flight_number = (
            f"{carrier}{out_segments[0].get('number', '')}" if carrier else None
        )

        results.append({
            "offer_id": offer.get("id"),
            "origin": orig,
            "destination": dest,
            "departure_date": departure_date,
            "return_date": return_date,
            "travel_class": (
                offer.get("travelerPricings", [{}])[0]
                .get("fareDetailsBySegment", [{}])[0]
                .get("cabin")
            ) or travel_class or "ECONOMY",
            "carrier": carrier,
            "flight_number": flight_number,
            "outbound": {
                "departure_airport": out_dep.get("iataCode"),
                "departure_time": out_dep.get("at"),
                "arrival_airport": out_arr.get("iataCode"),
                "arrival_time": out_arr.get("at"),
                "stops": out_stops,
                "duration": outbound.get("duration"),
            },
            "inbound": inbound_info,
            "price_total": float(total) if total else None,
            "currency": currency,
            "seats_available": offer.get("numberOfBookableSeats"),
            "estimated": total is None,
            "notes": "Amadeus Flight Offers v2",
        })

    results.sort(key=lambda x: (x["price_total"] is None, x["price_total"] or 10**12))
    return results[:limit]


def search_flights_from_trip(
    origin: str,
    destination: str,
    departure_date: str,
    adults: int = 1,
    return_date: Optional[str] = None,
    origin_iata: Optional[str] = None,
    destination_iata: Optional[str] = None,
    travel_class: Optional[str] = None,
    non_stop: bool = False,
    currency_code: str = "EUR",
    limit: int = 5,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Punto de entrada para el TransportSelectionAgent.
    Acepta nombres de ciudad o códigos IATA y devuelve {"flights": [...]}.
    """
    orig_code = _normalize_iata(origin_iata or origin)
    dest_code = _normalize_iata(destination_iata or destination)

    # Si los parámetros llegan como nombre de ciudad en vez de IATA, resolvemos
    if not orig_code and origin:
        try:
            from travel_adk.agents.planner_agent.tools import resolve_iata_code
            resolved = resolve_iata_code(origin, prefer="AIRPORT")
            orig_code = _normalize_iata((resolved or {}).get("iata") or "")
        except Exception:
            orig_code = ""

    if not dest_code and destination:
        try:
            from travel_adk.agents.planner_agent.tools import resolve_iata_code
            resolved = resolve_iata_code(destination, prefer="AIRPORT")
            dest_code = _normalize_iata((resolved or {}).get("iata") or "")
        except Exception:
            dest_code = ""

    if not orig_code or not dest_code:
        return {"flights": []}

    flights = search_flights(
        origin=orig_code,
        destination=dest_code,
        departure_date=departure_date,
        adults=adults,
        return_date=return_date,
        travel_class=travel_class,
        non_stop=non_stop,
        currency_code=currency_code,
        limit=limit,
    )
    return {"flights": flights}