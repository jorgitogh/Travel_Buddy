import os
from typing import Any, List

from google.adk.agents import LlmAgent

from travel_adk.agents.transport_agent.tools import search_transport_options_from_trip
from travel_adk.schemas.models import TransportOptions, TripRequest
from travel_adk.state.keys import TRANSPORT_OPTIONS_JSON, TRIP_REQUEST_JSON


def _build_google_maps_mcp_tools() -> List[Any]:
    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not api_key:
        return []

    try:
        from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
        from mcp import StdioServerParameters
        try:
            from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset as MCPToolSet
        except Exception:
            from google.adk.tools.mcp_tool.mcp_toolset import MCPToolSet  # type: ignore
    except Exception:
        return []

    return [
        MCPToolSet(
            connection_params=StdioConnectionParams(
                server_params=StdioServerParameters(
                    command="npx",
                    args=["-y", "@modelcontextprotocol/server-google-maps"],
                    env={"GOOGLE_MAPS_API_KEY": api_key},
                ),
            ),
            tool_filter=["maps_distance_matrix", "maps_directions"],
        )
    ]


def build_transport_agent(model: str) -> LlmAgent:
    tools: List[Any] = [search_transport_options_from_trip]
    tools.extend(_build_google_maps_mcp_tools())

    return LlmAgent(
        name="TransportAgent",
        model=model,
        input_schema=TripRequest,
        output_schema=TransportOptions,
        output_key=TRANSPORT_OPTIONS_JSON,
        tools=tools,
        instruction=f"""
Eres un agente de transporte.
Recibirás la solicitud de viaje normalizada en:
{{{TRIP_REQUEST_JSON}}}

Tarea:
- Obtener opciones de transporte para el trayecto solicitado según `transport_mode`.

Reglas:
- Si `transport_mode == "avion"`:
  - Usa SIEMPRE `search_transport_options_from_trip` con:
    - origin = origin
    - destination = destination
    - departure_date = start_date
    - return_date = end_date
    - origin_iata = origin_iata (si existe)
    - destination_iata = destination_iata (si existe)
  - Devuelve transportes con `mode = "avion"`.

- Si `transport_mode == "coche"`:
  - NO llames a la tool de vuelos.
  - Usa MCP de Google Maps (`maps_distance_matrix` y/o `maps_directions`) para estimar ruta y duración.
  - Devuelve transportes con `mode = "coche"` e IDs tipo `C1`, `C2`...
  - Si no hay precio real, usa `total_price = null` y explica distancia/duración en `notes`.

- No inventes datos: usa solo resultados de tools.
- Devuelve SOLO JSON válido conforme a TransportOptions.
""",
    )
