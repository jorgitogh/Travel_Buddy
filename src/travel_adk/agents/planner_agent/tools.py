import os
from functools import lru_cache
from typing import Any, Dict, Optional


def _amadeus_client():
    from amadeus import Client  # type: ignore
    return Client(
        client_id=os.getenv("AMADEUS_CLIENT_ID"),
        client_secret=os.getenv("AMADEUS_CLIENT_SECRET"),
    )

@lru_cache(maxsize=1024)
def resolve_iata_code(city: str, prefer: str = "CITY") -> Dict[str, Any]:
    q = (city or "").strip()
    if not q:
        return {"query": city, "iata": None, "subType": None, "name": None, "source": None}


    try:
        if os.getenv("AMADEUS_CLIENT_ID") and os.getenv("AMADEUS_CLIENT_SECRET"):
            amadeus = _amadeus_client()
            resp = amadeus.reference_data.locations.get(keyword=q, subType="CITY,AIRPORT")
            data = getattr(resp, "data", []) or []

            def pick(items, subtype):
                for it in items:
                    if it.get("subType") == subtype and it.get("iataCode"):
                        return it
                return None

            if prefer.upper() == "AIRPORT":
                chosen = pick(data, "AIRPORT") or pick(data, "CITY")
            else:
                chosen = pick(data, "CITY") or pick(data, "AIRPORT")

            if chosen:
                return {
                    "query": q,
                    "iata": chosen.get("iataCode"),
                    "subType": chosen.get("subType"),
                    "name": chosen.get("name"),
                    "source": "amadeus",
                }
    except Exception:
        pass

    try:
        import airportsdata # type: ignore
        airports = airportsdata.load("IATA") 

        q_lower = q.lower()
        matches = [
            a for a in airports.values()
            if a.get("iata") and (a.get("city") or "").lower() == q_lower
        ]

        if matches:
            a = matches[0]
            return {
                "query": q,
                "iata": a.get("iata"),
                "subType": "AIRPORT",
                "name": a.get("name"),
                "source": "airportsdata",
            }
    except Exception:
        pass

    return {"query": q, "iata": None, "subType": None, "name": None, "source": None}