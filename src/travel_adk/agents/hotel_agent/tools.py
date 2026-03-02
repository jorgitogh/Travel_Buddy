import re
from datetime import date
from typing import Any, Dict, List, Optional

from travel_adk.services.amadeus_http import get_amadeus_client

_IATA_RE = re.compile(r"^[A-Z]{3}$")


def _normalize_city_code(city_code: str) -> str:
    code = (city_code or "").strip().upper()
    if not _IATA_RE.match(code):
        return ""
    return code


def hotel_list_by_city(
    city_code: str,
    radius_km: Optional[int] = None,
    chain_codes: Optional[str] = None,
    hotel_source: str = "ALL",
    limit: int = 40,
) -> List[Dict[str, Any]]:
    client = get_amadeus_client()

    code = _normalize_city_code(city_code)
    if not code:
        return []

    params: Dict[str, Any] = {
        "cityCode": code,
        "hotelSource": hotel_source,
    }
    if radius_km is not None:
        params["radius"] = radius_km
        params["radiusUnit"] = "KM"
    if chain_codes:
        params["chainCodes"] = chain_codes

    data = client.get("/v1/reference-data/locations/hotels/by-city", params=params)
    hotels = data.get("data", []) or []
    return hotels[:limit]


def hotel_offers_v3(
    hotel_ids: List[str],
    checkin_date: str,
    checkout_date: str,
    adults: int = 1,
) -> List[Dict[str, Any]]:
    client = get_amadeus_client()

    params = {
        "hotelIds": ",".join(hotel_ids),
        "adults": adults,
        "checkInDate": checkin_date,
        "checkOutDate": checkout_date,
    }

    payload = client.get("/v3/shopping/hotel-offers", params=params)
    return payload.get("data", []) or []


def search_hotels(
    city_code: str,
    checkin_date: str,
    checkout_date: str,
    adults: int = 1,
    limit: int = 5,
    radius_km: Optional[int] = 10,
) -> List[Dict[str, Any]]:
    code = _normalize_city_code(city_code)
    if not code:
        return []

    hotels = hotel_list_by_city(city_code=code, radius_km=radius_km, limit=50)

    id_to_meta: Dict[str, Dict[str, Any]] = {}
    hotel_ids: List[str] = []
    for h in hotels:
        hid = h.get("hotelId")
        if not hid:
            continue
        hotel_ids.append(hid)
        id_to_meta[hid] = {
            "id": hid,
            "name": h.get("name"),
            "geoCode": h.get("geoCode"),
            "address": h.get("address"),
        }

    if not hotel_ids:
        return []

    # Hotel Offers v3 admite hasta 20 IDs por llamada.
    # Recorremos todos los lotes para evitar falsos vacíos cuando
    # el primer bloque no tiene disponibilidad.
    best_by_hotel_id: Dict[str, Dict[str, Any]] = {}
    for i in range(0, len(hotel_ids), 20):
        batch_ids = hotel_ids[i : i + 20]
        if not batch_ids:
            continue

        try:
            offers = hotel_offers_v3(
                hotel_ids=batch_ids,
                checkin_date=checkin_date,
                checkout_date=checkout_date,
                adults=adults,
            )
        except Exception:
            continue

        for item in offers:
            hotel = item.get("hotel", {}) or {}
            hid = hotel.get("hotelId") or hotel.get("id")
            if not hid:
                continue

            meta = id_to_meta.get(hid, {"id": hid, "name": hotel.get("name")})
            first_offer = (item.get("offers") or [None])[0] or {}
            price = first_offer.get("price", {}) or {}
            total = price.get("total")
            currency = price.get("currency")

            row = {
                "id": meta.get("id"),
                "name": meta.get("name"),
                "area": (meta.get("address") or {}).get("cityName"),
                "checkin_date": checkin_date,
                "checkout_date": checkout_date,
                "price_total": float(total) if total else None,
                "currency": currency or "EUR",
                "estimated": total is None,
                "deep_link": None,
                "notes": "Amadeus Hotel List + Hotel Search v3",
            }

            current = best_by_hotel_id.get(hid)
            if current is None:
                best_by_hotel_id[hid] = row
                continue

            current_price = current.get("price_total")
            new_price = row.get("price_total")
            if current_price is None or (new_price is not None and new_price < current_price):
                best_by_hotel_id[hid] = row

    results = list(best_by_hotel_id.values())

    results.sort(key=lambda x: (x["price_total"] is None, x["price_total"] or 10**12))
    return results[:limit]


def search_hotels_from_trip(
    destination: str,
    checkin_date: str,
    checkout_date: str,
    destination_iata: Optional[str] = None,
    adults: int = 1,
    limit: int = 5,
    radius_km: Optional[int] = 10,
) -> Dict[str, List[Dict[str, Any]]]:
    try:
        start = date.fromisoformat(checkin_date)
        end = date.fromisoformat(checkout_date)
        if end <= start:
            return {"hotels": []}
    except Exception:
        return {"hotels": []}

    code = ""
    if destination:
        try:
            from travel_adk.agents.planner_agent.tools import resolve_iata_code

            resolved = resolve_iata_code(destination, prefer="CITY")
            code = _normalize_city_code((resolved or {}).get("iata") or "")
        except Exception:
            code = ""

    if not code:
        code = _normalize_city_code(destination_iata or "")

    if not code:
        return {"hotels": []}

    hotels = search_hotels(
        city_code=code,
        checkin_date=checkin_date,
        checkout_date=checkout_date,
        adults=adults,
        limit=limit,
        radius_km=radius_km,
    )
    return {"hotels": hotels}
