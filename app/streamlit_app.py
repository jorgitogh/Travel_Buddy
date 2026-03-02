from __future__ import annotations

import asyncio
import json
import os
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import uuid4

import streamlit as st

from travel_adk.agents.itinerary_agent.itinerary_agent import build_itinerary_planner_agent
from travel_adk.config.settings import load_environment
from travel_adk.agents.hotel_agent.tools import search_hotels_from_trip
from travel_adk.agents.planner_agent.tools import resolve_iata_code
from travel_adk.agents.transport_agent.tools import search_transport_options_from_trip
from travel_adk.state.keys import (
    CANDIDATE_BUNDLES_JSON,
    FINAL_ITINERARY_JSON,
    HOTEL_OPTIONS_JSON,
    SELECTED_BUNDLE_JSON,
    TRANSPORT_OPTIONS_JSON,
    TRIP_REQUEST_JSON,
)

load_environment()


def _normalize_interests(raw: str) -> List[str]:
    items = [x.strip().lower() for x in raw.split(",")]
    deduped: List[str] = []
    for item in items:
        if item and item not in deduped:
            deduped.append(item)
    return deduped


def _normalize_trip_request(
    origin: str,
    destination: str,
    start_date: date,
    end_date: date,
    transport_mode: str,
    interests_raw: str,
) -> Dict[str, Any]:
    origin_clean = " ".join((origin or "").strip().split())
    destination_clean = " ".join((destination or "").strip().split())
    interests = _normalize_interests(interests_raw)

    origin_iata: Optional[str] = None
    destination_iata: Optional[str] = None
    if transport_mode == "avion":
        origin_iata = (resolve_iata_code(origin_clean, prefer="AIRPORT") or {}).get("iata")
        destination_iata = (resolve_iata_code(destination_clean, prefer="AIRPORT") or {}).get("iata")

    return {
        "origin": origin_clean,
        "destination": destination_clean,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "transport_mode": transport_mode,
        "interests": interests,
        "origin_iata": origin_iata,
        "destination_iata": destination_iata,
    }


def _run_async(coro: Any) -> Any:
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


async def _maps_distance_matrix(origin: str, destination: str) -> Dict[str, Any]:
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    params = StdioServerParameters(
        command="npx",
        args=["-y", "@modelcontextprotocol/server-google-maps"],
        env={"GOOGLE_MAPS_API_KEY": os.getenv("GOOGLE_MAPS_API_KEY", "")},
    )

    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool(
                name="maps_distance_matrix",
                arguments={
                    "origins": [origin],
                    "destinations": [destination],
                    "mode": "driving",
                    "units": "metric",
                },
            )
            content = getattr(result, "content", []) or []
            for block in content:
                text = getattr(block, "text", None)
                if text:
                    return json.loads(text)
    return {}


def _build_car_transports(
    trip: Dict[str, Any],
    fuel_consumption_l_100km: float,
    fuel_price_eur_l: float,
) -> Dict[str, List[Dict[str, Any]]]:
    notes = "Ruta en coche sin estimación de distancia."
    departure_iso = f"{trip['start_date']}T08:00:00"
    arrival_iso: Optional[str] = None
    total_price: Optional[float] = None

    if os.getenv("GOOGLE_MAPS_API_KEY"):
        try:
            matrix = _run_async(_maps_distance_matrix(trip["origin"], trip["destination"]))
            elem = (((matrix.get("results") or [{}])[0].get("elements") or [{}])[0]) or {}
            distance_m = ((elem.get("distance") or {}).get("value")) or 0
            duration_s = ((elem.get("duration") or {}).get("value")) or 0

            if duration_s:
                departure_dt = datetime.fromisoformat(departure_iso)
                arrival_dt = departure_dt + timedelta(seconds=int(duration_s))
                arrival_iso = arrival_dt.isoformat(timespec="minutes")

            distance_km = round(float(distance_m) / 1000, 1) if distance_m else None
            duration_h = round(float(duration_s) / 3600, 1) if duration_s else None
            if distance_km:
                liters = round(distance_km * fuel_consumption_l_100km / 100.0, 2)
                one_way_cost = round(liters * fuel_price_eur_l, 2)
                round_trip_cost = round(one_way_cost * 2, 2)
                total_price = round_trip_cost
                notes = (
                    f"Ruta coche: {distance_km} km, {duration_h} h aprox (Google Maps MCP). "
                    f"Consumo {fuel_consumption_l_100km} L/100km, combustible {fuel_price_eur_l} €/L, "
                    f"coste estimado ida+vuelta: {round_trip_cost} €."
                )
            else:
                notes = f"Ruta coche: distancia no disponible, {duration_h} h aprox (Google Maps MCP)."
        except Exception as exc:
            notes = f"Sin datos MCP ({type(exc).__name__}). Ruta en coche estimada."

    return {
        "transports": [
            {
                "id": "C1",
                "mode": "coche",
                "provider": "google_maps_mcp",
                "departure_date": departure_iso,
                "arrival_date": arrival_iso,
                "total_price": total_price,
                "currency": "EUR",
                "notes": notes,
            }
        ]
    }


def _search_transport(
    trip: Dict[str, Any],
    fuel_consumption_l_100km: float,
    fuel_price_eur_l: float,
) -> Dict[str, List[Dict[str, Any]]]:
    if trip["transport_mode"] == "avion":
        return search_transport_options_from_trip(
            origin=trip["origin"],
            destination=trip["destination"],
            departure_date=trip["start_date"],
            return_date=trip["end_date"],
            origin_iata=trip.get("origin_iata"),
            destination_iata=trip.get("destination_iata"),
            limit=5,
        )
    return _build_car_transports(
        trip=trip,
        fuel_consumption_l_100km=fuel_consumption_l_100km,
        fuel_price_eur_l=fuel_price_eur_l,
    )


def _search_hotels(trip: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    return search_hotels_from_trip(
        destination=trip["destination"],
        destination_iata=trip.get("destination_iata"),
        checkin_date=trip["start_date"],
        checkout_date=trip["end_date"],
        limit=5,
    )


def _bundle_cost(transport: Dict[str, Any], hotel: Dict[str, Any]) -> Optional[float]:
    t_price = transport.get("total_price")
    h_price = hotel.get("price_total")
    if t_price is None and h_price is None:
        return None
    return float(t_price or 0.0) + float(h_price or 0.0)


def _build_bundles(transports: List[Dict[str, Any]], hotels: List[Dict[str, Any]]) -> Dict[str, Any]:
    labels = ["Económico", "Equilibrado", "Cómodo", "Céntrico", "Mejor valor"]
    if not transports or not hotels:
        return {"bundles": []}

    ranked: List[Dict[str, Any]] = []
    for t in transports[:5]:
        for h in hotels[:5]:
            ranked.append(
                {
                    "transport": t,
                    "hotel": h,
                    "total": _bundle_cost(t, h),
                }
            )

    ranked.sort(key=lambda x: (x["total"] is None, x["total"] or 10**12))

    bundles: List[Dict[str, Any]] = []
    for idx, item in enumerate(ranked[:5], start=1):
        t = item["transport"]
        h = item["hotel"]
        bundles.append(
            {
                "bundle_id": f"B{idx}",
                "label": labels[(idx - 1) % len(labels)],
                "transport_id": t.get("id"),
                "hotel_id": h.get("id"),
                "total_estimated_cost_eur": item["total"],
                "pros": [
                    f"Transporte: {t.get('mode')}",
                    f"Hotel: {h.get('name') or h.get('id')}",
                ],
                "cons": [
                    "Precio de coche puede ser aproximado." if t.get("mode") == "coche" else "Sujeto a cambios de tarifa.",
                ],
            }
        )
    return {"bundles": bundles}


def _build_itinerary(trip: Dict[str, Any], selected_bundle: Dict[str, Any]) -> Dict[str, Any]:
    start = date.fromisoformat(trip["start_date"])
    end = date.fromisoformat(trip["end_date"])
    interests = trip.get("interests") or ["paseo"]

    days: List[Dict[str, Any]] = []
    current = start
    idx = 0
    while current <= end:
        interest = interests[idx % len(interests)]
        days.append(
            {
                "date": current.isoformat(),
                "blocks": [
                    "Desayuno y planificación del día",
                    f"Actividad principal: {interest}",
                    "Comida local",
                    "Paseo de tarde y descanso",
                ],
            }
        )
        idx += 1
        current += timedelta(days=1)

    return {
        "summary": (
            f"Itinerario generado para {trip['destination']} con bundle {selected_bundle.get('bundle_id')} "
            f"({selected_bundle.get('label')})."
        ),
        "days": days,
    }


def _coerce_itinerary_payload(raw: Any) -> Dict[str, Any]:
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

    raise ValueError(f"Formato de itinerario no soportado: {type(raw).__name__}")


def _ensure_google_llm_api_key() -> None:
    """
    Normaliza distintos nombres de variable al formato esperado por google-genai:
    GOOGLE_API_KEY.
    """
    if os.getenv("GOOGLE_API_KEY"):
        return

    for alias in ("GEMINI_API_KEY", "GOOGLE_GENAI_API_KEY", "GOOGLE_AI_API_KEY"):
        value = os.getenv(alias, "").strip()
        if value:
            os.environ["GOOGLE_API_KEY"] = value
            return


async def _generate_itinerary_with_agent_async(
    trip: Dict[str, Any],
    selected_bundle: Dict[str, Any],
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

    model = os.getenv("ITINERARY_AGENT_MODEL", "gemini-2.5-flash")
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
        return _coerce_itinerary_payload(state[FINAL_ITINERARY_JSON])

    for event in reversed(events):
        actions = getattr(event, "actions", None)
        state_delta = getattr(actions, "state_delta", None) or {}
        if FINAL_ITINERARY_JSON in state_delta:
            return _coerce_itinerary_payload(state_delta[FINAL_ITINERARY_JSON])

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
) -> Dict[str, Any]:
    return _run_async(_generate_itinerary_with_agent_async(trip=trip, selected_bundle=selected_bundle))


def _init_state() -> Dict[str, Any]:
    if "flow_state" not in st.session_state:
        st.session_state["flow_state"] = {}
    return st.session_state["flow_state"]


st.set_page_config(page_title="Travel Buddy Flow Demo", layout="wide")
st.title("Travel Buddy - Demo de Flujo")
st.caption("Prueba rápida del flujo planner -> transport/hotel -> bundles -> selección -> itinerary.")

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
    fuel_consumption_l_100km = st.number_input(
        "Consumo coche (L/100km)",
        min_value=3.0,
        max_value=20.0,
        value=6.8,
        step=0.1,
        disabled=transport_mode != "coche",
    )
    fuel_price_eur_l = st.number_input(
        "Precio combustible (€/L)",
        min_value=0.5,
        max_value=3.5,
        value=1.65,
        step=0.01,
        disabled=transport_mode != "coche",
    )
    submitted = st.form_submit_button("Buscar opciones")

if submitted:
    flow_state.clear()

    if end_date <= start_date:
        st.error("La fecha de fin debe ser posterior a la de inicio (al menos 1 noche).")
    else:
        trip_request = _normalize_trip_request(
            origin=origin,
            destination=destination,
            start_date=start_date,
            end_date=end_date,
            transport_mode=transport_mode,
            interests_raw=interests_raw,
        )
        flow_state[TRIP_REQUEST_JSON] = trip_request

        with st.spinner("Consultando transporte y hoteles..."):
            try:
                transport_options = _search_transport(
                    trip_request,
                    fuel_consumption_l_100km=fuel_consumption_l_100km,
                    fuel_price_eur_l=fuel_price_eur_l,
                )
            except Exception as exc:
                transport_options = {"transports": []}
                st.warning(f"Transporte sin datos: {type(exc).__name__}: {exc}")

            try:
                hotel_options = _search_hotels(trip_request)
            except Exception as exc:
                hotel_options = {"hotels": []}
                st.warning(f"Hoteles sin datos: {type(exc).__name__}: {exc}")

        flow_state[TRANSPORT_OPTIONS_JSON] = transport_options
        flow_state[HOTEL_OPTIONS_JSON] = hotel_options

        bundles = _build_bundles(
            transports=transport_options.get("transports", []),
            hotels=hotel_options.get("hotels", []),
        )
        flow_state[CANDIDATE_BUNDLES_JSON] = bundles

if flow_state:
    st.subheader("Estado del Flujo")
    for key in [
        TRIP_REQUEST_JSON,
        TRANSPORT_OPTIONS_JSON,
        HOTEL_OPTIONS_JSON,
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
                )
                st.success("Itinerario generado con ItineraryAgent.")
            except Exception as exc:
                flow_state[FINAL_ITINERARY_JSON] = _build_itinerary(
                    trip=trip_data,
                    selected_bundle=selected_bundle,
                )
                st.warning(
                    "No se pudo usar ItineraryAgent; se usa plan básico local. "
                    f"Detalle: {type(exc).__name__}: {exc}"
                )

if FINAL_ITINERARY_JSON in flow_state:
    itinerary = flow_state[FINAL_ITINERARY_JSON]
    st.subheader("Planning Final")
    st.write(itinerary.get("summary"))

    for day in itinerary.get("days", []):
        with st.container(border=True):
            st.markdown(f"**{day.get('date')}**")
            for block in day.get("blocks", []):
                st.write(f"- {block}")
