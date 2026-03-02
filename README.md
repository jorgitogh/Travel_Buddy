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
- `GET /api/health`: healthcheck.
