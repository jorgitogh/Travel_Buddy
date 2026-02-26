from google.adk.agents import LlmAgent
from travel_adk.schemas.models import CandidateBundles
from travel_adk.state.keys import (
    TRANSPORT_OPTIONS_JSON,
    HOTEL_OPTIONS_JSON,
    CANDIDATE_BUNDLES_JSON,
)

def build_bundle_builder_agent(model: str) -> LlmAgent:
    return LlmAgent(
        name="BundleBuilderAgent",
        model=model,
        output_schema=CandidateBundles,
        output_key=CANDIDATE_BUNDLES_JSON,
        instruction=f"""
Te doy opciones de transporte y hotel (JSON). Crea 3 a 5 "bundles" combinando 1 transporte + 1 hotel.

TRANSPORTE:
{{{TRANSPORT_OPTIONS_JSON}}}

HOTELES:
{{{HOTEL_OPTIONS_JSON}}}

Reglas:
- No inventes IDs: `transport_id` debe salir de `transports[].id` y `hotel_id` de `hotels[].id`.
- Genera bundle_id únicos tipo "B1", "B2"...
- Etiquetas sugeridas: Económico, Equilibrado, Cómodo, Céntrico, Mejor valor
- Pros/cons cortos.
Devuelve SOLO el JSON final, sin texto extra.
""",
    )
