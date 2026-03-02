import os
import re
from functools import lru_cache
from typing import Any, Dict, Optional

from travel_adk.config.settings import load_environment
from travel_adk.services.amadeus_http import get_amadeus_client

_IATA_RE = re.compile(r"^[A-Z]{3}$")


def _pick_location(items: Any, prefer: str) -> Optional[Dict[str, Any]]:
    if not isinstance(items, list):
        return None

    def pick(subtype: str) -> Optional[Dict[str, Any]]:
        for item in items:
            if item.get("subType") == subtype and item.get("iataCode"):
                return item
        return None

    if prefer.upper() == "AIRPORT":
        return pick("AIRPORT") or pick("CITY")
    return pick("CITY") or pick("AIRPORT")


def _resolve_with_amadeus_http(query: str, prefer: str) -> Optional[Dict[str, Any]]:
    load_environment()
    if not os.getenv("AMADEUS_CLIENT_ID") or not os.getenv("AMADEUS_CLIENT_SECRET"):
        return None

    try:
        client = get_amadeus_client()
        payload = client.get(
            "/v1/reference-data/locations",
            params={"keyword": query, "subType": "CITY,AIRPORT"},
        )
        chosen = _pick_location(payload.get("data", []), prefer)
        if not chosen:
            return None

        return {
            "query": query,
            "iata": chosen.get("iataCode"),
            "subType": chosen.get("subType"),
            "name": chosen.get("name"),
            "source": "amadeus_http",
        }
    except Exception:
        return None


def _resolve_with_airportsdata(query: str) -> Optional[Dict[str, Any]]:
    try:
        import airportsdata  # type: ignore

        airports = airportsdata.load("IATA")
        q = (query or "").strip()
        if not q:
            return None

        if _IATA_RE.match(q.upper()):
            airport = airports.get(q.upper())
            if airport:
                return {
                    "query": query,
                    "iata": airport.get("iata"),
                    "subType": "AIRPORT",
                    "name": airport.get("name"),
                    "source": "airportsdata",
                }

        q_lower = q.lower()
        matches = [
            a for a in airports.values() if a.get("iata") and (a.get("city") or "").lower() == q_lower
        ]
        # Evita elegir aeropuertos ambiguos por orden alfabético.
        if len(matches) == 1:
            a = matches[0]
            return {
                "query": query,
                "iata": a.get("iata"),
                "subType": "AIRPORT",
                "name": a.get("name"),
                "source": "airportsdata",
            }
    except Exception:
        return None

    return None


@lru_cache(maxsize=1024)
def resolve_iata_code(city: str, prefer: str = "CITY") -> Dict[str, Any]:
    load_environment()
    q = (city or "").strip()
    if not q:
        return {"query": city, "iata": None, "subType": None, "name": None, "source": None}

    amadeus_result = _resolve_with_amadeus_http(q, prefer)
    if amadeus_result:
        return amadeus_result

    airportdata_result = _resolve_with_airportsdata(q)
    if airportdata_result:
        return airportdata_result

    return {"query": q, "iata": None, "subType": None, "name": None, "source": None}
