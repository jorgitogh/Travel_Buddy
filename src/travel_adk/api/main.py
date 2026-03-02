from __future__ import annotations

import asyncio
import json
import os
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

from travel_adk.agents.bundle_builder_agent.bundle_builder_agent import build_bundle_builder_agent
from travel_adk.agents.hotel_agent.hotel_agent import build_hotel_agent
from travel_adk.agents.itinerary_agent.itinerary_agent import build_itinerary_planner_agent
from travel_adk.agents.itinerary_agent.tools import get_weather_forecast
from travel_adk.agents.planner_agent.planner_agent import build_planner_agent
from travel_adk.agents.transport_agent.transport_agent import build_transport_agent
from travel_adk.config.settings import load_environment
from travel_adk.state.keys import (
    CANDIDATE_BUNDLES_JSON,
    FINAL_ITINERARY_JSON,
    HOTEL_OPTIONS_JSON,
    SELECTED_BUNDLE_JSON,
    TRANSPORT_OPTIONS_JSON,
    TRIP_REQUEST_JSON,
    WEATHER_FORECAST_JSON,
)

load_environment()


def _normalize_interests(raw: str | List[str]) -> List[str]:
    items: List[str] = []
    if isinstance(raw, str):
        items = [x.strip().lower() for x in raw.split(",")]
    else:
        items = [str(x).strip().lower() for x in raw]

    deduped: List[str] = []
    for item in items:
        if item and item not in deduped:
            deduped.append(item)
    return deduped


def _coerce_state_payload(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw

    if hasattr(raw, "model_dump"):
        dumped = raw.model_dump()
        if isinstance(dumped, dict):
            return dumped

    if isinstance(raw, str):
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed

    raise ValueError(f"Formato de payload no soportado: {type(raw).__name__}")


def _extract_itinerary_candidate(raw: Any) -> Optional[Dict[str, Any]]:
    candidate = raw
    if not isinstance(candidate, dict):
        return None

    if FINAL_ITINERARY_JSON in candidate and isinstance(candidate[FINAL_ITINERARY_JSON], dict):
        candidate = candidate[FINAL_ITINERARY_JSON]

    if isinstance(candidate.get("summary"), str) and isinstance(candidate.get("days"), list):
        return candidate
    return None


def _parse_itinerary_from_text(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None

    raw = text.strip()
    candidates = [raw]

    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        candidates.append("\n".join(lines).strip())

    decoder = json.JSONDecoder()
    expanded: List[str] = list(candidates)
    for item in candidates:
        for idx, ch in enumerate(item):
            if ch != "{":
                continue
            try:
                obj, _ = decoder.raw_decode(item[idx:])
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                expanded.append(json.dumps(obj, ensure_ascii=False))
                break

    for item in expanded:
        if not item:
            continue
        try:
            parsed = json.loads(item)
        except Exception:
            continue
        itinerary = _extract_itinerary_candidate(parsed)
        if itinerary:
            return itinerary
    return None


def _extract_itinerary_from_events(events: List[Any]) -> Optional[Dict[str, Any]]:
    text_chunks: List[str] = []

    for event in events:
        content = getattr(event, "content", None)
        parts = getattr(content, "parts", None) or []
        for part in parts:
            text = getattr(part, "text", None)
            if isinstance(text, str) and text.strip():
                text_chunks.append(text)

            function_response = getattr(part, "function_response", None)
            if function_response is None:
                continue

            response_payload = None
            if isinstance(function_response, dict):
                response_payload = function_response.get("response", function_response)
            else:
                response_payload = getattr(function_response, "response", None)

            itinerary = _extract_itinerary_candidate(response_payload)
            if itinerary:
                return itinerary

    for text in reversed(text_chunks):
        itinerary = _parse_itinerary_from_text(text)
        if itinerary:
            return itinerary

    if text_chunks:
        tail = "\n".join(text_chunks[-5:])
        itinerary = _parse_itinerary_from_text(tail)
        if itinerary:
            return itinerary

    return None


def _event_part_types(events: List[Any]) -> List[str]:
    types_seen: List[str] = []
    for event in events[-8:]:
        content = getattr(event, "content", None)
        parts = getattr(content, "parts", None) or []
        for part in parts:
            part_type = "unknown"
            if getattr(part, "function_call", None) is not None:
                part_type = "function_call"
            elif getattr(part, "function_response", None) is not None:
                part_type = "function_response"
            elif getattr(part, "text", None):
                part_type = "text"
            elif getattr(part, "executable_code", None) is not None:
                part_type = "executable_code"
            elif getattr(part, "code_execution_result", None) is not None:
                part_type = "code_execution_result"
            types_seen.append(part_type)
    return types_seen


def _default_agent_model() -> str:
    return os.getenv("TRAVEL_AGENT_MODEL", os.getenv("ITINERARY_AGENT_MODEL", "gemini-2.5-flash"))


def _ensure_google_llm_api_key() -> None:
    if os.getenv("GOOGLE_API_KEY"):
        return

    for alias in ("GEMINI_API_KEY", "GOOGLE_GENAI_API_KEY", "GOOGLE_AI_API_KEY"):
        value = os.getenv(alias, "").strip()
        if value:
            os.environ["GOOGLE_API_KEY"] = value
            return


def _fetch_weather_for_trip(trip: Dict[str, Any]) -> Dict[str, Any]:
    return get_weather_forecast(
        destination=str(trip.get("destination") or ""),
        start_date=str(trip.get("start_date") or ""),
        end_date=str(trip.get("end_date") or ""),
    )


class TripOptionsRequest(BaseModel):
    origin: str
    destination: str
    start_date: date
    end_date: date
    transport_mode: Literal["avion", "coche"] = "avion"
    interests: str | List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_dates(self) -> "TripOptionsRequest":
        if self.end_date <= self.start_date:
            raise ValueError("La fecha de fin debe ser posterior a la de inicio.")
        return self

    def to_trip_form_input(self) -> Dict[str, Any]:
        return {
            "origin": " ".join(self.origin.strip().split()),
            "destination": " ".join(self.destination.strip().split()),
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "transport_mode": self.transport_mode,
            "interests": _normalize_interests(self.interests),
        }


class TripOptionsResponse(BaseModel):
    trip_request: Dict[str, Any]
    transport_options: Dict[str, Any]
    hotel_options: Dict[str, Any]
    candidate_bundles: Dict[str, Any]
    weather_forecast: Dict[str, Any] = Field(default_factory=dict)
    notices: List[str] = Field(default_factory=list)


class GenerateItineraryRequest(BaseModel):
    trip_request: Dict[str, Any]
    selected_bundle: Dict[str, Any]
    weather_forecast: Dict[str, Any] = Field(default_factory=dict)


class GenerateItineraryResponse(BaseModel):
    final_itinerary: Dict[str, Any]
    notices: List[str] = Field(default_factory=list)


async def _run_agent_step_async(
    *,
    agent: Any,
    output_key: str,
    prompt: str,
    state: Optional[Dict[str, Any]] = None,
    app_name: str = "TravelBuddyApi",
) -> Dict[str, Any]:
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    session_service = InMemorySessionService()
    runner = Runner(
        app_name=app_name,
        agent=agent,
        session_service=session_service,
    )

    user_id = "api_user"
    session_id = f"{getattr(agent, 'name', 'agent')}-{uuid4()}"

    await session_service.create_session(
        app_name=app_name,
        user_id=user_id,
        session_id=session_id,
        state=state or {},
    )

    content = types.Content(role="user", parts=[types.Part.from_text(text=prompt)])

    events: List[Any] = []
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=content,
    ):
        events.append(event)

    session = await session_service.get_session(
        app_name=app_name,
        user_id=user_id,
        session_id=session_id,
    )
    session_state = (session.state if session else {}) or {}
    if output_key in session_state:
        return _coerce_state_payload(session_state[output_key])

    for event in reversed(events):
        actions = getattr(event, "actions", None)
        state_delta = getattr(actions, "state_delta", None) or {}
        if output_key in state_delta:
            return _coerce_state_payload(state_delta[output_key])

    last_error = ""
    for event in reversed(events):
        message = getattr(event, "error_message", None)
        if message:
            last_error = message
            break

    if last_error:
        raise RuntimeError(last_error)
    raise RuntimeError(f"No se obtuvo {output_key} desde {getattr(agent, 'name', 'agent')}.")


async def _run_core_agents_async(
    trip_form_input: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:
    _ensure_google_llm_api_key()
    if not os.getenv("GOOGLE_API_KEY"):
        raise ValueError(
            "Falta clave LLM para ejecutar agentes "
            "(usa GOOGLE_API_KEY, GEMINI_API_KEY o GOOGLE_GENAI_API_KEY)."
        )

    model = _default_agent_model()

    planner_prompt = (
        "Normaliza esta solicitud de viaje y devuelve SOLO JSON valido conforme a TripRequest.\n"
        f"{json.dumps(trip_form_input, ensure_ascii=False)}"
    )
    trip_request = await _run_agent_step_async(
        agent=build_planner_agent(model),
        output_key=TRIP_REQUEST_JSON,
        prompt=planner_prompt,
    )

    transport_state = {TRIP_REQUEST_JSON: trip_request}
    hotel_state = {TRIP_REQUEST_JSON: trip_request}
    transport_mode = str(trip_request.get("transport_mode") or "").lower()

    transport_task = _run_agent_step_async(
        agent=build_transport_agent(
            model,
            enable_maps_mcp=(transport_mode == "coche"),
        ),
        output_key=TRANSPORT_OPTIONS_JSON,
        prompt="Genera opciones de transporte usando trip_request_json. Devuelve SOLO JSON valido.",
        state=transport_state,
    )
    hotel_task = _run_agent_step_async(
        agent=build_hotel_agent(model),
        output_key=HOTEL_OPTIONS_JSON,
        prompt="Genera opciones de hotel usando trip_request_json. Devuelve SOLO JSON valido.",
        state=hotel_state,
    )
    transport_options, hotel_options = await asyncio.gather(transport_task, hotel_task)

    bundle_options = await _run_agent_step_async(
        agent=build_bundle_builder_agent(model),
        output_key=CANDIDATE_BUNDLES_JSON,
        prompt=(
            "Combina transporte y hotel en 3-5 bundles. "
            "Usa solo IDs presentes en transport_options_json y hotel_options_json. Devuelve SOLO JSON."
        ),
        state={
            TRANSPORT_OPTIONS_JSON: transport_options,
            HOTEL_OPTIONS_JSON: hotel_options,
        },
    )

    return {
        TRIP_REQUEST_JSON: trip_request,
        TRANSPORT_OPTIONS_JSON: transport_options,
        HOTEL_OPTIONS_JSON: hotel_options,
        CANDIDATE_BUNDLES_JSON: bundle_options,
    }


async def _generate_itinerary_with_agent_async(
    trip: Dict[str, Any],
    selected_bundle: Dict[str, Any],
    weather_forecast: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    _ensure_google_llm_api_key()
    if not os.getenv("GOOGLE_API_KEY"):
        raise ValueError(
            "Falta clave LLM para ItineraryPlannerAgent "
            "(usa GOOGLE_API_KEY, GEMINI_API_KEY o GOOGLE_GENAI_API_KEY)."
        )

    model = _default_agent_model()
    session_service = InMemorySessionService()
    runner = Runner(
        app_name="TravelBuddyApi",
        agent=build_itinerary_planner_agent(model),
        session_service=session_service,
    )

    user_id = "api_user"
    session_id = f"itinerary-{uuid4()}"
    await session_service.create_session(
        app_name="TravelBuddyApi",
        user_id=user_id,
        session_id=session_id,
        state={
            TRIP_REQUEST_JSON: trip,
            SELECTED_BUNDLE_JSON: selected_bundle,
            WEATHER_FORECAST_JSON: weather_forecast or {},
        },
    )

    async def _run_turn(prompt_text: str) -> List[Any]:
        content = types.Content(role="user", parts=[types.Part.from_text(text=prompt_text)])
        turn_events: List[Any] = []
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=content,
        ):
            turn_events.append(event)
        return turn_events

    async def _extract_result_from_state() -> Optional[Dict[str, Any]]:
        session = await session_service.get_session(
            app_name="TravelBuddyApi",
            user_id=user_id,
            session_id=session_id,
        )
        state = (session.state if session else {}) or {}
        if FINAL_ITINERARY_JSON not in state:
            return None
        return _coerce_state_payload(state[FINAL_ITINERARY_JSON])

    def _extract_result_from_events(local_events: List[Any]) -> Optional[Dict[str, Any]]:
        for event in reversed(local_events):
            actions = getattr(event, "actions", None)
            state_delta = getattr(actions, "state_delta", None) or {}
            if FINAL_ITINERARY_JSON in state_delta:
                return _coerce_state_payload(state_delta[FINAL_ITINERARY_JSON])
        return _extract_itinerary_from_events(local_events)

    events: List[Any] = []
    events.extend(
        await _run_turn(
            "Genera el itinerario final en JSON usando el destino, intereses y fechas. "
            "Investiga con google_search antes de proponer actividades."
        )
    )

    from_state = await _extract_result_from_state()
    if from_state:
        return from_state
    from_events = _extract_result_from_events(events)
    if from_events:
        return from_events

    part_types = _event_part_types(events)
    if "function_call" in part_types and "text" not in part_types:
        # A veces el modelo se queda en ciclo de herramientas; hacemos un turno de cierre forzado.
        events.extend(
            await _run_turn(
                "No llames más herramientas. "
                "Usa solo el contexto ya disponible y devuelve AHORA solo JSON válido "
                "con schema Itinerary: {summary: str, days: [{date: str, blocks: [str]}]}."
            )
        )

        from_state = await _extract_result_from_state()
        if from_state:
            return from_state
        from_events = _extract_result_from_events(events)
        if from_events:
            return from_events

    last_error = ""
    for event in reversed(events):
        message = getattr(event, "error_message", None)
        if message:
            last_error = message
            break

    if last_error:
        raise RuntimeError(last_error)
    raise RuntimeError(
        "No se obtuvo final_itinerary_json desde ItineraryPlannerAgent. "
        f"Partes observadas: {_event_part_types(events)}"
    )


app = FastAPI(
    title="Travel Buddy API",
    description="API local para generar bundles e itinerarios usando agentes ADK.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def healthcheck() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/api/options", response_model=TripOptionsResponse)
async def generate_options(payload: TripOptionsRequest) -> TripOptionsResponse:
    try:
        flow_state = await _run_core_agents_async(trip_form_input=payload.to_trip_form_input())
        weather = _fetch_weather_for_trip(flow_state[TRIP_REQUEST_JSON])
        flow_state[WEATHER_FORECAST_JSON] = weather

        notices: List[str] = []
        if weather.get("warning") == "forecast_out_of_range":
            notices.append(
                "La previsión de Open-Meteo solo llega a fechas cercanas. "
                f"Disponible hasta {weather.get('forecast_supported_until')}."
            )
        elif weather.get("error"):
            detail = weather.get("message") or weather.get("error")
            notices.append(f"Previsión meteorológica no disponible: {detail}")

        return TripOptionsResponse(
            trip_request=flow_state[TRIP_REQUEST_JSON],
            transport_options=flow_state[TRANSPORT_OPTIONS_JSON],
            hotel_options=flow_state[HOTEL_OPTIONS_JSON],
            candidate_bundles=flow_state[CANDIDATE_BUNDLES_JSON],
            weather_forecast=flow_state[WEATHER_FORECAST_JSON],
            notices=notices,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc


@app.post("/api/itinerary", response_model=GenerateItineraryResponse)
async def generate_itinerary(payload: GenerateItineraryRequest) -> GenerateItineraryResponse:
    notices: List[str] = []
    if not os.getenv("SERPAPI_API_KEY"):
        notices.append("Falta SERPAPI_API_KEY: el itinerario se generará sin búsqueda web.")

    try:
        itinerary = await _generate_itinerary_with_agent_async(
            trip=payload.trip_request,
            selected_bundle=payload.selected_bundle,
            weather_forecast=payload.weather_forecast,
        )
        return GenerateItineraryResponse(final_itinerary=itinerary, notices=notices)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc


FRONTEND_DIR = Path(__file__).resolve().parents[3] / "web_ui"

if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="ui")
else:
    @app.get("/", include_in_schema=False)
    async def root_missing() -> Dict[str, str]:
        return {"status": "ok", "message": "Frontend local no encontrado. Usa /docs o /api/health."}
