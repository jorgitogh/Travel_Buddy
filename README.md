# Travel Buddy

Proyecto de planificación de viajes con agentes ADK.

## Ejecutar app web (HTML + FastAPI)

```bash
source .venv/bin/activate
PYTHONPATH=src uvicorn travel_adk.api.main:app --reload --port 8000
```

Abre `http://localhost:8000`.

## Endpoints principales

- `POST /api/options`: genera trip request + transportes + hoteles + bundles + meteo.
- `POST /api/itinerary`: genera itinerario final a partir de bundle seleccionado.
- `POST /api/road-route`: geolocaliza origen/destino y calcula ruta en coche si existe.
- `GET /api/health`: healthcheck.

## Ajustes de rendimiento (opcionales)

- `TRAVEL_OPTIONS_CACHE_TTL_S` (default `900`): cachea resultados de `/api/options`.
- `TRAVEL_ITINERARY_CACHE_TTL_S` (default `1800`): cachea resultados de `/api/itinerary`.
- `TRAVEL_ROAD_ROUTE_CACHE_TTL_S` (default `86400`): cachea resultados de `/api/road-route`.
- `TRAVEL_CACHE_MAX_ITEMS` (default `128`): máximo de entradas en cache en memoria.
- `MAP_TIMEOUT_S` (default `10`): timeout de requests a servicios de mapa.
- `NOMINATIM_SEARCH_URL`: endpoint de geocoding (OpenStreetMap).
- `OSRM_BASE_URL`: endpoint base de ruteo OSRM.
