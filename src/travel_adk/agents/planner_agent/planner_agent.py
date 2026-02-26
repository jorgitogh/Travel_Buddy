from google.adk.agents import LlmAgent
from travel_adk.schemas.models import TripFormInput, TripRequest
from travel_adk.state.keys import TRIP_REQUEST_JSON
from travel_adk.tools.iata_tools import resolve_iata_code

def build_planner_agent(model: str) -> LlmAgent:
    return LlmAgent(
        name="PlannerAgent",
        model=model,
        input_schema=TripFormInput,
        output_schema=TripRequest,
        output_key=TRIP_REQUEST_JSON,
        tools=[resolve_iata_code],
        instruction="""
Eres un normalizador de inputs de viaje.
Te llegará un JSON con: origin, destination, start_date, end_date, transport_mode, interests.

Reglas de normalización:
- strip() y capitalización razonable en origin/destination
- interests en minúsculas, sin duplicados

IATA:
- Si transport_mode == "avion", llama SIEMPRE a:
  - resolve_iata_code(origin)
  - resolve_iata_code(destination)
  y rellena origin_iata y destination_iata con el campo "iata" devuelto.
- Si no hay iata, usa null.
- Si transport_mode == "coche", deja origin_iata y destination_iata como null.

Devuelve SOLO un JSON válido conforme a TripRequest. No añadas texto fuera del JSON.
""",
    )