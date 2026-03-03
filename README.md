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
- `CAR_FUEL_L_PER_100KM` (default `6.8`): consumo estimado para bundle de coche.
- `CAR_FUEL_L_PER_100KM_ECO` (default `5.4`): consumo opción coche eficiente.
- `CAR_FUEL_L_PER_100KM_STANDARD` (default `6.8`): consumo opción coche estándar.
- `CAR_FUEL_L_PER_100KM_SUV` (default `8.9`): consumo opción coche SUV.
- `CAR_FUEL_L_PER_100KM_VAN` (default `9.8`): consumo opción coche van.
- `CAR_FUEL_L_PER_100KM_PREMIUM` (default `10.8`): consumo opción coche premium.
- `CAR_FUEL_PRICE_EUR_PER_L` (default `1.65`): precio gasolina para bundle de coche.
- `CAR_ROUNDTRIP_MULTIPLIER` (default `2.0`): factor de ida/vuelta para coste en coche.
- `TRAVEL_MAX_CAR_OPTIONS` (default `3`): número máximo de opciones de coche generadas.
- `TRAVEL_MAX_CAR_BUNDLES` (default `3`): número máximo de bundles de coche mostrados.
- `TRAVEL_MAX_FLIGHT_BUNDLES` (default `3`): número máximo de bundles de vuelo mostrados.
- `TRAVEL_MIN_FLIGHT_OPTIONS` (default `2`): mínimo de opciones de vuelo a intentar (usa fallback directo Amadeus si el agente trae menos).
- `TRAVEL_MAX_HOTELS_FOR_BUNDLES` (default `3`): número de hoteles a combinar con cada modo para crear bundles.
- `NOMINATIM_SEARCH_URL`: endpoint de geocoding (OpenStreetMap).
- `OSRM_BASE_URL`: endpoint base de ruteo OSRM.
