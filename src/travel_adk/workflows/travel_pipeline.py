from typing import Any, List

from google.adk.agents import LlmAgent, ParallelAgent, SequentialAgent

from travel_adk.agents.bundle_builder_agent.bundle_builder_agent import (
    build_bundle_builder_agent,
)
from travel_adk.agents.hotel_agent.hotel_agent import build_hotel_agent
from travel_adk.agents.itinerary_agent.itinerary_agent import build_itinerary_planner_agent
from travel_adk.agents.planner_agent.planner_agent import build_planner_agent
from travel_adk.agents.transport_agent.transport_agent import build_transport_agent
from travel_adk.schemas.models import Bundle, Itinerary
from travel_adk.state.keys import (
    CANDIDATE_BUNDLES_JSON,
    FINAL_ITINERARY_JSON,
    SELECTED_BUNDLE_JSON,
)


def _build_parallel(name: str, agents: List[Any]) -> Any:
    try:
        return ParallelAgent(name=name, sub_agents=agents)
    except TypeError:
        return ParallelAgent(name=name, agents=agents)


def _build_sequential(name: str, agents: List[Any]) -> Any:
    try:
        return SequentialAgent(name=name, sub_agents=agents)
    except TypeError:
        return SequentialAgent(name=name, agents=agents)


def build_human_selection_gate_agent(model: str) -> LlmAgent:
    return LlmAgent(
        name="HumanSelectionGateAgent",
        model=model,
        output_schema=Bundle,
        output_key=SELECTED_BUNDLE_JSON,
        instruction=f"""
Eres un agente HITL de selección de bundle.
Dispones de los bundles candidatos en:
{{{CANDIDATE_BUNDLES_JSON}}}

Reglas:
- El usuario debe indicar explícitamente el bundle (ejemplo: "B2").
- Devuelve EXACTAMENTE el bundle elegido por el usuario.
- No inventes bundle_id ni campos.
- Devuelve SOLO JSON válido conforme a Bundle.
""",
    )


def build_optional_reviewer_agent(model: str) -> LlmAgent:
    return LlmAgent(
        name="OptionalReviewerAgent",
        model=model,
        output_schema=Itinerary,
        output_key=FINAL_ITINERARY_JSON,
        instruction=f"""
Eres un revisor final de calidad.
Revisa el itinerario en {{{FINAL_ITINERARY_JSON}}} y mejóralo solo si detectas huecos.

Reglas:
- Mantén coherencia de fechas y actividades.
- No inventes reservas concretas.
- Devuelve SOLO JSON válido conforme a Itinerary.
""",
    )


def build_travel_pipeline(model: str, include_reviewer: bool = False) -> Any:
    input_planner_agent = build_planner_agent(model)
    transport_agent = build_transport_agent(model)
    hotel_agent = build_hotel_agent(model)
    bundle_builder_agent = build_bundle_builder_agent(model)
    human_selection_gate_agent = build_human_selection_gate_agent(model)
    itinerary_planner_agent = build_itinerary_planner_agent(model)

    graph: List[Any] = [
        input_planner_agent,
        _build_parallel(
            name="SearchParallelAgent",
            agents=[transport_agent, hotel_agent],
        ),
        bundle_builder_agent,
        human_selection_gate_agent,
        itinerary_planner_agent,
    ]

    if include_reviewer:
        graph.append(build_optional_reviewer_agent(model))

    return _build_sequential(name="TravelPipelineAgent", agents=graph)
