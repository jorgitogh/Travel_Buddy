from __future__ import annotations

import asyncio
import html
import json
import os
from datetime import date, timedelta
from typing import Any, Dict, List, Optional
from uuid import uuid4

import streamlit as st

from travel_adk.agents.bundle_builder_agent.bundle_builder_agent import build_bundle_builder_agent
from travel_adk.agents.hotel_agent.hotel_agent import build_hotel_agent
from travel_adk.agents.itinerary_agent.itinerary_agent import build_itinerary_planner_agent
from travel_adk.agents.itinerary_agent.tools import get_weather_forecast
from travel_adk.agents.planner_agent.planner_agent import build_planner_agent
from travel_adk.config.settings import load_environment
from travel_adk.agents.transport_agent.transport_agent import build_transport_agent
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


def _normalize_interests(raw: str) -> List[str]:
    items = [x.strip().lower() for x in raw.split(",")]
    deduped: List[str] = []
    for item in items:
        if item and item not in deduped:
            deduped.append(item)
    return deduped


def _run_async(coro: Any) -> Any:
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


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


def _default_agent_model() -> str:
    return os.getenv("TRAVEL_AGENT_MODEL", os.getenv("ITINERARY_AGENT_MODEL", "gemini-2.5-flash"))


def _weather_icon(group: str) -> str:
    icons = {
        "sunny": "☀️",
        "cloudy": "⛅",
        "rain": "🌧️",
        "storm": "⛈️",
        "snow": "❄️",
        "fog": "🌫️",
        "neutral": "🧭",
    }
    return icons.get(group, "🧭")


def _weather_mood_class(group: str) -> str:
    classes = {
        "sunny": "mood-sunny",
        "cloudy": "mood-cloudy",
        "rain": "mood-rain",
        "storm": "mood-storm",
        "snow": "mood-snow",
        "fog": "mood-fog",
        "neutral": "mood-neutral",
    }
    return classes.get(group, "mood-neutral")


def _weather_summary(day_weather: Dict[str, Any]) -> str:
    if not day_weather:
        return "Sin previsión disponible"

    label = day_weather.get("weather_label") or "Variable"
    tmin = day_weather.get("temp_min_c")
    tmax = day_weather.get("temp_max_c")
    pop = day_weather.get("precipitation_probability_max")

    temp_bits: List[str] = []
    if tmin is not None:
        temp_bits.append(f"Min {round(float(tmin))}°C")
    if tmax is not None:
        temp_bits.append(f"Max {round(float(tmax))}°C")
    if pop is not None:
        temp_bits.append(f"Lluvia {round(float(pop))}%")

    if temp_bits:
        return f"{label} · {' · '.join(temp_bits)}"
    return label


def _weather_by_date(forecast: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    days = (forecast or {}).get("days", []) or []
    by_date: Dict[str, Dict[str, Any]] = {}
    for day in days:
        d = day.get("date")
        if d:
            by_date[str(d)] = day
    return by_date


def _fetch_weather_for_trip(trip: Dict[str, Any]) -> Dict[str, Any]:
    return get_weather_forecast(
        destination=str(trip.get("destination") or ""),
        start_date=str(trip.get("start_date") or ""),
        end_date=str(trip.get("end_date") or ""),
    )


def _ensure_google_llm_api_key() -> None:
    if os.getenv("GOOGLE_API_KEY"):
        return

    for alias in ("GEMINI_API_KEY", "GOOGLE_GENAI_API_KEY", "GOOGLE_AI_API_KEY"):
        value = os.getenv(alias, "").strip()
        if value:
            os.environ["GOOGLE_API_KEY"] = value
            return


async def _run_agent_step_async(
    *,
    agent: Any,
    output_key: str,
    prompt: str,
    state: Optional[Dict[str, Any]] = None,
    app_name: str = "TravelBuddyStreamlit",
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

    user_id = "streamlit_user"
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


def _run_core_agents(trip_form_input: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return _run_async(_run_core_agents_async(trip_form_input=trip_form_input))


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
        app_name="TravelBuddyStreamlit",
        agent=build_itinerary_planner_agent(model),
        session_service=session_service,
    )

    user_id = "streamlit_user"
    session_id = f"itinerary-{uuid4()}"
    await session_service.create_session(
        app_name="TravelBuddyStreamlit",
        user_id=user_id,
        session_id=session_id,
        state={
            TRIP_REQUEST_JSON: trip,
            SELECTED_BUNDLE_JSON: selected_bundle,
            WEATHER_FORECAST_JSON: weather_forecast or {},
        },
    )

    prompt = (
        "Genera el itinerario final en JSON usando el destino, intereses y fechas. "
        "Investiga con google_search antes de proponer actividades."
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
        app_name="TravelBuddyStreamlit",
        user_id=user_id,
        session_id=session_id,
    )
    state = (session.state if session else {}) or {}
    if FINAL_ITINERARY_JSON in state:
        return _coerce_state_payload(state[FINAL_ITINERARY_JSON])

    for event in reversed(events):
        actions = getattr(event, "actions", None)
        state_delta = getattr(actions, "state_delta", None) or {}
        if FINAL_ITINERARY_JSON in state_delta:
            return _coerce_state_payload(state_delta[FINAL_ITINERARY_JSON])

    last_error = ""
    for event in reversed(events):
        message = getattr(event, "error_message", None)
        if message:
            last_error = message
            break

    if last_error:
        raise RuntimeError(last_error)
    raise RuntimeError("No se obtuvo final_itinerary_json desde ItineraryPlannerAgent.")


def _generate_itinerary_with_agent(
    trip: Dict[str, Any],
    selected_bundle: Dict[str, Any],
    weather_forecast: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return _run_async(
        _generate_itinerary_with_agent_async(
            trip=trip,
            selected_bundle=selected_bundle,
            weather_forecast=weather_forecast,
        )
    )


def _init_state() -> Dict[str, Any]:
    if "flow_state" not in st.session_state:
        st.session_state["flow_state"] = {}
    return st.session_state["flow_state"]


st.set_page_config(page_title="Travel Buddy Flow Demo", layout="wide")
st.title("Travel Buddy - Demo de Flujo")
st.caption("Prueba rápida del flujo planner -> transport/hotel -> bundles -> selección -> itinerary.")
st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;600;700&family=Plus+Jakarta+Sans:wght@400;600;700&display=swap');

.weather-card {
  border-radius: 18px;
  padding: 16px 18px;
  margin: 10px 0;
  border: 1px solid rgba(255, 255, 255, 0.25);
  box-shadow: 0 14px 30px rgba(0, 0, 0, 0.12);
  color: #0f172a;
}

.weather-card .card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.weather-card .date {
  font-family: "Space Grotesk", sans-serif;
  font-weight: 700;
  letter-spacing: 0.2px;
  font-size: 1.02rem;
}

.weather-card .meteo {
  font-family: "Plus Jakarta Sans", sans-serif;
  font-weight: 600;
  font-size: 0.92rem;
  opacity: 0.9;
}

.weather-card .blocks {
  margin: 0;
  padding-left: 18px;
  font-family: "Plus Jakarta Sans", sans-serif;
}

.weather-card .blocks li {
  margin: 5px 0;
}

.mood-sunny {
  background: linear-gradient(135deg, #ffe8a3 0%, #ffd27f 45%, #ffc46d 100%);
}

.mood-cloudy {
  background: linear-gradient(135deg, #e7edf6 0%, #d8e0eb 45%, #c9d4e4 100%);
}

.mood-rain {
  background: linear-gradient(135deg, #c7d7f2 0%, #9eb8de 45%, #7f9bc9 100%);
}

.mood-storm {
  background: linear-gradient(135deg, #c2c8da 0%, #9ea9c5 45%, #7e8bad 100%);
}

.mood-snow {
  background: linear-gradient(135deg, #f2f6fb 0%, #e7effa 45%, #dbe8f7 100%);
}

.mood-fog {
  background: linear-gradient(135deg, #e8eaee 0%, #dadde3 45%, #c9ced7 100%);
}

.mood-neutral {
  background: linear-gradient(135deg, #f0ece8 0%, #e7ddd2 45%, #dccdbf 100%);
}
</style>
""",
    unsafe_allow_html=True,
)

flow_state = _init_state()

with st.form("trip_form"):
    col1, col2 = st.columns(2)
    with col1:
        origin = st.text_input("Origen", value="Madrid")
        start_date = st.date_input("Fecha inicio", value=date.today() + timedelta(days=20))
    with col2:
        destination = st.text_input("Destino", value="Barcelona")
        end_date = st.date_input("Fecha fin", value=date.today() + timedelta(days=23))

    transport_mode = st.radio("Transporte", options=["avion", "coche"], horizontal=True)
    interests_raw = st.text_input("Intereses (separados por coma)", value="gastronomia,museos")
    submitted = st.form_submit_button("Buscar opciones")

if submitted:
    flow_state.clear()

    if end_date <= start_date:
        st.error("La fecha de fin debe ser posterior a la de inicio (al menos 1 noche).")
    else:
        trip_form_input = {
            "origin": " ".join((origin or "").strip().split()),
            "destination": " ".join((destination or "").strip().split()),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "transport_mode": transport_mode,
            "interests": _normalize_interests(interests_raw),
        }

        with st.spinner("Ejecutando agentes: planner -> transport/hotel -> bundles..."):
            try:
                flow_state.update(_run_core_agents(trip_form_input=trip_form_input))
                weather = _fetch_weather_for_trip(flow_state[TRIP_REQUEST_JSON])
                flow_state[WEATHER_FORECAST_JSON] = weather
                if weather.get("warning") == "forecast_out_of_range":
                    st.info(
                        "La previsión de Open-Meteo solo llega a fechas cercanas. "
                        f"Disponible hasta {weather.get('forecast_supported_until')}."
                    )
                elif weather.get("error"):
                    detail = weather.get("message") or weather.get("error")
                    st.info(f"Previsión meteorológica no disponible: {detail}")
                st.success("Opciones generadas con agentes.")
            except Exception as exc:
                st.error(f"Error en flujo multiagente: {type(exc).__name__}: {exc}")

if flow_state:
    st.subheader("Estado del Flujo")
    for key in [
        TRIP_REQUEST_JSON,
        TRANSPORT_OPTIONS_JSON,
        HOTEL_OPTIONS_JSON,
        WEATHER_FORECAST_JSON,
        CANDIDATE_BUNDLES_JSON,
        SELECTED_BUNDLE_JSON,
        FINAL_ITINERARY_JSON,
    ]:
        if key in flow_state:
            with st.expander(key, expanded=key in {TRIP_REQUEST_JSON, CANDIDATE_BUNDLES_JSON}):
                st.json(flow_state[key])

bundles = (flow_state.get(CANDIDATE_BUNDLES_JSON) or {}).get("bundles", [])
if bundles:
    st.subheader("Selección de Bundle")
    bundle_ids = [b["bundle_id"] for b in bundles]
    by_id = {b["bundle_id"]: b for b in bundles}

    selected_bundle_id = st.selectbox(
        "Elige un bundle",
        options=bundle_ids,
        format_func=lambda bid: (
            f"{bid} - {by_id[bid]['label']} "
            f"({by_id[bid].get('total_estimated_cost_eur')} EUR aprox)"
        ),
    )

    if st.button("Generar itinerario"):
        selected_bundle = by_id[selected_bundle_id]
        flow_state[SELECTED_BUNDLE_JSON] = selected_bundle
        trip_data = flow_state[TRIP_REQUEST_JSON]

        if not os.getenv("SERPAPI_API_KEY"):
            st.info(
                "Falta SERPAPI_API_KEY: el agente generará "
                "itinerario sin resultados de búsqueda web."
            )

        with st.spinner("Generando itinerario realista con ItineraryAgent..."):
            try:
                flow_state[FINAL_ITINERARY_JSON] = _generate_itinerary_with_agent(
                    trip=trip_data,
                    selected_bundle=selected_bundle,
                    weather_forecast=flow_state.get(WEATHER_FORECAST_JSON),
                )
                st.success("Itinerario generado con ItineraryAgent.")
            except Exception as exc:
                st.error(f"Error en ItineraryAgent: {type(exc).__name__}: {exc}")

if FINAL_ITINERARY_JSON in flow_state:
    itinerary = flow_state[FINAL_ITINERARY_JSON]
    weather_map = _weather_by_date(flow_state.get(WEATHER_FORECAST_JSON) or {})
    st.subheader("Planning Final")
    st.write(itinerary.get("summary"))

    for day in itinerary.get("days", []):
        day_date = str(day.get("date") or "")
        weather_day = weather_map.get(day_date, {})
        weather_group = str(weather_day.get("weather_group") or "neutral")
        meteo_line = f"{_weather_icon(weather_group)} {_weather_summary(weather_day)}"

        blocks_html = "".join(f"<li>{html.escape(str(block))}</li>" for block in (day.get("blocks") or []))
        card_html = f"""
<div class="weather-card {_weather_mood_class(weather_group)}">
  <div class="card-header">
    <div class="date">{html.escape(day_date)}</div>
    <div class="meteo">{html.escape(meteo_line)}</div>
  </div>
  <ul class="blocks">{blocks_html}</ul>
</div>
"""
        st.markdown(card_html, unsafe_allow_html=True)
