from google.adk.agents import LlmAgent

from travel_adk.schemas.models import Itinerary
from travel_adk.state.keys import FINAL_ITINERARY_JSON, SELECTED_BUNDLE_JSON, TRIP_REQUEST_JSON


def build_itinerary_planner_agent(model: str) -> LlmAgent:
    return LlmAgent(
        name="ItineraryPlannerAgent",
        model=model,
        output_schema=Itinerary,
        output_key=FINAL_ITINERARY_JSON,
        instruction=f"""
Eres un planificador de itinerarios diarios.
Dispones de:
- Solicitud de viaje: {{{TRIP_REQUEST_JSON}}}
- Bundle seleccionado por el usuario: {{{SELECTED_BUNDLE_JSON}}}

Tarea:
- Generar un plan diario para todas las fechas del viaje.

Reglas:
- Devuelve SOLO JSON válido conforme a Itinerary.
- `summary` breve y accionable.
- `days` con una entrada por día, en orden cronológico.
- Cada día debe incluir entre 3 y 6 bloques realistas.
""",
    )
