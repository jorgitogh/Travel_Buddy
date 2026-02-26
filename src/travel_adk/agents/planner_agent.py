from google.adk.agents import LlmAgent
from travel_adk.schemas.models import TripFormInput, TripRequest
from travel_adk.state.keys import TRIP_REQUEST_JSON

def build_planner_agent(model: str) -> LlmAgent:
    return LlmAgent(
        name="PlannerAgent",
        model=model,
        input_schema=TripFormInput,
        output_schema=TripRequest,
        output_key=TRIP_REQUEST_JSON,
        instruction="""
Eres un normalizador de inputs de viaje.
Te llegará un JSON con: origin, destination, start_date, end_date, transport_mode, interests.

Devuelve SOLO un JSON válido con los mismos campos (mismo formato), aplicando:
- strip() y capitalización razonable en ciudades
- interests en minúsculas, sin duplicados
No inventes datos. No añadas texto fuera del JSON.
""",
    )