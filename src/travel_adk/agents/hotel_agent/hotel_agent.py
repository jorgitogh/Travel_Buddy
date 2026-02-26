from google.adk.agents import LlmAgent

from travel_adk.agents.hotel_agent.tools import search_hotels_from_trip
from travel_adk.schemas.models import HotelOptions, TripRequest
from travel_adk.state.keys import HOTEL_OPTIONS_JSON, TRIP_REQUEST_JSON


def build_hotel_agent(model: str) -> LlmAgent:
    return LlmAgent(
        name="HotelAgent",
        model=model,
        input_schema=TripRequest,
        output_schema=HotelOptions,
        output_key=HOTEL_OPTIONS_JSON,
        tools=[search_hotels_from_trip],
        instruction=f"""
Eres un agente de hoteles.
Recibirás la solicitud de viaje normalizada en:
{{{TRIP_REQUEST_JSON}}}

Tarea:
- Obtener opciones de hotel para el destino y las fechas de viaje usando la tool.

Reglas:
- Llama SIEMPRE a `search_hotels_from_trip` con:
  - destination = destination
  - destination_iata = destination_iata (si existe)
  - checkin_date = start_date
  - checkout_date = end_date
- No inventes hoteles, precios ni IDs.
- Devuelve SOLO un JSON válido conforme a HotelOptions.
""",
    )
