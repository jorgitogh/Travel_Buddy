from google.adk.agents import LlmAgent

from travel_adk.agents.itinerary_agent.tools import get_weather_forecast, google_search
from travel_adk.schemas.models import Itinerary
from travel_adk.state.keys import (
    FINAL_ITINERARY_JSON,
    SELECTED_BUNDLE_JSON,
    TRIP_REQUEST_JSON,
    WEATHER_FORECAST_JSON,
)


def build_itinerary_planner_agent(model: str) -> LlmAgent:
    return LlmAgent(
        name="ItineraryPlannerAgent",
        model=model,
        output_schema=Itinerary,
        output_key=FINAL_ITINERARY_JSON,
        tools=[google_search, get_weather_forecast],
        instruction=f"""
Eres un planificador de itinerarios diarios.
Dispones de:
- Solicitud de viaje: {{{TRIP_REQUEST_JSON}}}
- Bundle seleccionado por el usuario: {{{SELECTED_BUNDLE_JSON}}}
- Previsión meteorológica (si existe): {{{WEATHER_FORECAST_JSON}}}

Tarea:
- Generar un plan diario para todas las fechas del viaje, realista y adaptado a destino + intereses.

Reglas:
- Antes de generar el plan, llama a `google_search` entre 1 y 3 veces.
- Llama a `get_weather_forecast` para el destino y el rango de fechas cuando no haya previsión en estado.
- Haz varias consultas combinando `destination`, `interests` y el periodo del viaje.
- Incluye consultas de tipo:
  - "que hacer en <destination>"
  - "eventos en <destination> <mes>"
  - "<interes> en <destination>"
- Si hay lluvia/tormenta, prioriza actividades indoor para esas fechas.
- Si hace buen tiempo, prioriza exteriores (barrios, parques, miradores, paseos).
- Usa los resultados de busqueda para proponer actividades concretas y plausibles.
- No inventes horarios o precios exactos si no aparecen en los resultados.
- Si una tool devuelve error o resultados vacíos, continúa igualmente y completa el plan.
- Tras usar tools, NO llames más tools y responde directamente con el JSON final.
- Devuelve SOLO JSON válido conforme a Itinerary.
- `summary` breve y accionable.
- `days` con una entrada por día, en orden cronológico.
- Cada día debe incluir entre 3 y 6 bloques realistas.
""",
    )
