import os
from typing import Any, Dict, List

import requests

from travel_adk.config.settings import load_environment


def _normalize_query(query: str) -> str:
    return " ".join((query or "").strip().split())


def google_search(
    query: str,
    num_results: int = 5,
    language: str = "es",
    country: str = "es",
) -> Dict[str, Any]:
    """
    Busca en Google usando SerpAPI y devuelve resultados resumidos.

    Requiere:
    - SERPAPI_API_KEY
    """
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
        n = 5
    n = max(1, min(n, 10))

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
