const state = {
  options: null,
  selectedBundleId: "",
  selectedBundle: null,
  itinerary: null,
  budgetFilter: {
    enabled: false,
    minBound: 0,
    maxBound: 0,
    minValue: 0,
    maxValue: 0,
  },
  roadRoute: {
    data: null,
    map: null,
    layerGroup: null,
  },
};

const refs = {
  form: document.querySelector("#trip-form"),
  submitButton: document.querySelector("#submit-trip"),
  generateButton: document.querySelector("#generate-itinerary"),
  bundlesSection: document.querySelector("#bundles-section"),
  bundlesGrid: document.querySelector("#bundles-grid"),
  budgetFilter: document.querySelector("#budget-filter"),
  budgetMin: document.querySelector("#budget-min"),
  budgetMax: document.querySelector("#budget-max"),
  budgetRangeValue: document.querySelector("#budget-range-value"),
  budgetVisibleCount: document.querySelector("#budget-visible-count"),
  metricsSection: document.querySelector("#metrics-section"),
  itinerarySection: document.querySelector("#itinerary-section"),
  itinerarySummary: document.querySelector("#itinerary-summary"),
  itineraryDays: document.querySelector("#itinerary-days"),
  exportJsonButton: document.querySelector("#export-json-btn"),
  exportIcsButton: document.querySelector("#export-ics-btn"),
  googleCalendarButton: document.querySelector("#google-calendar-btn"),
  roadRouteSection: document.querySelector("#road-route-section"),
  roadRouteView: document.querySelector("#road-route-view"),
  roadRouteSummary: document.querySelector("#road-route-summary"),
  roadRouteWarnings: document.querySelector("#road-route-warnings"),
  roadRouteGoogleMaps: document.querySelector("#road-route-google-maps"),
  messages: document.querySelector("#messages"),
  metricTransports: document.querySelector("#metric-transports"),
  metricHotels: document.querySelector("#metric-hotels"),
  metricBundles: document.querySelector("#metric-bundles"),
  metricWeather: document.querySelector("#metric-weather"),
};

const WEATHER_ICON = {
  sunny: "☀️",
  cloudy: "⛅",
  rain: "🌧️",
  storm: "⛈️",
  snow: "❄️",
  fog: "🌫️",
  neutral: "🧭",
};

function setDefaultDates() {
  const start = new Date();
  start.setDate(start.getDate() + 20);
  const end = new Date();
  end.setDate(end.getDate() + 23);

  document.querySelector("#start_date").value = formatDate(start);
  document.querySelector("#end_date").value = formatDate(end);
}

function formatDate(value) {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function parseIsoDateLocal(value) {
  if (!value || typeof value !== "string") {
    return null;
  }
  const parts = value.split("-");
  if (parts.length !== 3) {
    return null;
  }
  const year = Number(parts[0]);
  const month = Number(parts[1]);
  const day = Number(parts[2]);
  if (!year || !month || !day) {
    return null;
  }
  return new Date(year, month - 1, day, 0, 0, 0, 0);
}

function compactDate(dateValue) {
  const year = dateValue.getFullYear();
  const month = String(dateValue.getMonth() + 1).padStart(2, "0");
  const day = String(dateValue.getDate()).padStart(2, "0");
  const hours = String(dateValue.getHours()).padStart(2, "0");
  const minutes = String(dateValue.getMinutes()).padStart(2, "0");
  const seconds = String(dateValue.getSeconds()).padStart(2, "0");
  return `${year}${month}${day}T${hours}${minutes}${seconds}`;
}

function safeFileToken(value) {
  return String(value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-zA-Z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .toLowerCase();
}

function downloadTextFile(content, filename, mimeType) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function formatPrice(value) {
  if (typeof value !== "number") {
    return "Precio no disponible";
  }
  return new Intl.NumberFormat("es-ES", {
    style: "currency",
    currency: "EUR",
    maximumFractionDigits: 2,
  }).format(value);
}

function formatBudgetValue(value) {
  return new Intl.NumberFormat("es-ES", {
    style: "currency",
    currency: "EUR",
    maximumFractionDigits: 0,
  }).format(value);
}

function formatDistance(valueKm) {
  if (typeof valueKm !== "number" || Number.isNaN(valueKm)) {
    return "--";
  }
  return `${valueKm.toFixed(1)} km`;
}

function formatMinutes(valueMin) {
  if (typeof valueMin !== "number" || Number.isNaN(valueMin)) {
    return "--";
  }
  const rounded = Math.round(valueMin);
  if (rounded < 60) {
    return `${rounded} min`;
  }
  const hours = Math.floor(rounded / 60);
  const mins = rounded % 60;
  if (!mins) {
    return `${hours} h`;
  }
  return `${hours} h ${mins} min`;
}

function transportModeLabel(transport) {
  const mode = String(transport?.mode || "").toLowerCase();
  if (mode === "avion") {
    return "✈️ Avión";
  }
  if (mode === "coche") {
    return "🚗 Coche";
  }
  return "🧭 Transporte";
}

function transportProviderLabel(transport) {
  const mode = String(transport?.mode || "").toLowerCase();
  const providerRaw = String(transport?.provider || "sin proveedor").trim();
  const provider = providerRaw.toLowerCase();

  if (mode !== "coche") {
    return providerRaw;
  }
  if (provider.includes("eficiente") || provider.includes("eco")) {
    return `🚗 ${providerRaw}`;
  }
  if (provider.includes("estándar") || provider.includes("estandar")) {
    return `🚙 ${providerRaw}`;
  }
  if (provider.includes("suv") || provider.includes("grande")) {
    return `🚘 ${providerRaw}`;
  }
  if (provider.includes("van") || provider.includes("familiar")) {
    return `🚐 ${providerRaw}`;
  }
  if (provider.includes("premium")) {
    return `🏎️ ${providerRaw}`;
  }
  return `🚙 ${providerRaw}`;
}

function normalizeWeatherMap(weatherForecast) {
  const days = (weatherForecast && weatherForecast.days) || [];
  const map = new Map();
  days.forEach((item) => {
    if (item.date) {
      map.set(String(item.date), item);
    }
  });
  return map;
}

function weatherSummary(dayWeather) {
  if (!dayWeather) {
    return "Sin previsión disponible";
  }

  const label = dayWeather.weather_label || "Variable";
  const parts = [];
  if (typeof dayWeather.temp_min_c === "number") {
    parts.push(`Min ${Math.round(dayWeather.temp_min_c)}°C`);
  }
  if (typeof dayWeather.temp_max_c === "number") {
    parts.push(`Max ${Math.round(dayWeather.temp_max_c)}°C`);
  }
  if (typeof dayWeather.precipitation_probability_max === "number") {
    parts.push(`Lluvia ${Math.round(dayWeather.precipitation_probability_max)}%`);
  }

  if (parts.length > 0) {
    return `${label} · ${parts.join(" · ")}`;
  }
  return label;
}

function googleMapsDirectionsUrl(origin, destination) {
  const url = new URL("https://www.google.com/maps/dir/");
  url.searchParams.set("api", "1");
  url.searchParams.set("origin", origin);
  url.searchParams.set("destination", destination);
  url.searchParams.set("travelmode", "driving");
  return url.toString();
}

function buildGoogleMapsPoint(point, fallback) {
  if (
    point &&
    typeof point.lat === "number" &&
    Number.isFinite(point.lat) &&
    typeof point.lon === "number" &&
    Number.isFinite(point.lon)
  ) {
    return `${point.lat},${point.lon}`;
  }
  return fallback;
}

function setRoadRouteGoogleMapsLink(origin, destination) {
  const hasBoth = Boolean(origin && destination);
  if (!hasBoth) {
    refs.roadRouteGoogleMaps.classList.add("hidden");
    refs.roadRouteGoogleMaps.href = "#";
    return;
  }
  refs.roadRouteGoogleMaps.href = googleMapsDirectionsUrl(origin, destination);
  refs.roadRouteGoogleMaps.classList.remove("hidden");
}

function setRoadRouteGoogleMapsLinkFromRouteData(data, fallbackOrigin, fallbackDestination) {
  const originPoint = buildGoogleMapsPoint(data?.origin_point, fallbackOrigin);
  const destinationPoint = buildGoogleMapsPoint(data?.destination_point, fallbackDestination);
  setRoadRouteGoogleMapsLink(originPoint, destinationPoint);
}

function getItineraryContext() {
  const itinerary = state.itinerary?.final_itinerary || null;
  const trip = state.options?.trip_request || {};
  return {
    itinerary,
    destination: String(trip.destination || "").trim(),
  };
}

function buildDayEventsFromItinerary(itinerary, destination) {
  const events = [];
  (itinerary?.days || []).forEach((day, dayIndex) => {
    const base = parseIsoDateLocal(String(day.date || ""));
    if (!base) {
      return;
    }
    const dayBlocks = (day.blocks || []).map((block) => String(block || "").trim()).filter(Boolean);
    const start = new Date(base);
    start.setHours(9, 0, 0, 0);
    const end = new Date(base);
    end.setHours(19, 0, 0, 0);
    const details =
      dayBlocks.length > 0
        ? dayBlocks.map((block, idx) => `${idx + 1}. ${block}`).join("\n")
        : "Plan de viaje sin bloques detallados.";
    events.push({
      title: `Itinerario ${destination || "viaje"} - ${String(day.date || dayIndex + 1)}`,
      description: details,
      location: destination || "",
      start,
      end,
    });
  });
  return events;
}

function escapeIcsText(value) {
  return String(value || "")
    .replace(/\\/g, "\\\\")
    .replace(/\n/g, "\\n")
    .replace(/;/g, "\\;")
    .replace(/,/g, "\\,");
}

function buildIcsCalendar(events) {
  const now = compactDate(new Date());
  const lines = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//Travel Buddy//Itinerary//ES",
    "CALSCALE:GREGORIAN",
    "METHOD:PUBLISH",
    "X-WR-CALNAME:Travel Buddy Itinerario",
  ];

  events.forEach((event, idx) => {
    lines.push("BEGIN:VEVENT");
    lines.push(`UID:${now}-${idx}@travel-buddy.local`);
    lines.push(`DTSTAMP:${now}`);
    lines.push(`DTSTART:${compactDate(event.start)}`);
    lines.push(`DTEND:${compactDate(event.end)}`);
    lines.push(`SUMMARY:${escapeIcsText(event.title)}`);
    lines.push(`DESCRIPTION:${escapeIcsText(event.description)}`);
    if (event.location) {
      lines.push(`LOCATION:${escapeIcsText(event.location)}`);
    }
    lines.push("END:VEVENT");
  });

  lines.push("END:VCALENDAR");
  return `${lines.join("\r\n")}\r\n`;
}

function setItineraryActionsEnabled(enabled) {
  refs.exportJsonButton.disabled = !enabled;
  refs.exportIcsButton.disabled = !enabled;
  refs.googleCalendarButton.disabled = !enabled;
}

function onExportItineraryJson() {
  const { itinerary, destination } = getItineraryContext();
  if (!itinerary) {
    addMessage("Primero genera un itinerario para poder exportarlo.", "error");
    return;
  }
  const payload = {
    generated_at: new Date().toISOString(),
    trip_request: state.options?.trip_request || {},
    selected_bundle: state.selectedBundle || {},
    final_itinerary: itinerary,
  };
  const dateToken = formatDate(new Date());
  const destinationToken = safeFileToken(destination) || "destino";
  const filename = `itinerario-${destinationToken}-${dateToken}.json`;
  downloadTextFile(JSON.stringify(payload, null, 2), filename, "application/json;charset=utf-8");
  addMessage("Itinerario exportado en JSON.", "info");
}

function onExportItineraryIcs() {
  const { itinerary, destination } = getItineraryContext();
  if (!itinerary) {
    addMessage("Primero genera un itinerario para poder exportarlo.", "error");
    return;
  }
  const events = buildDayEventsFromItinerary(itinerary, destination);
  if (events.length === 0) {
    addMessage("No hay días válidos para exportar a calendario.", "error");
    return;
  }
  const content = buildIcsCalendar(events);
  const dateToken = formatDate(new Date());
  const destinationToken = safeFileToken(destination) || "destino";
  const filename = `itinerario-${destinationToken}-${dateToken}.ics`;
  downloadTextFile(content, filename, "text/calendar;charset=utf-8");
  addMessage("Archivo .ics generado. Puedes importarlo en Google Calendar.", "info");
}

function onOpenGoogleCalendar() {
  const { itinerary, destination } = getItineraryContext();
  if (!itinerary) {
    addMessage("Primero genera un itinerario para enviar a Google Calendar.", "error");
    return;
  }
  const events = buildDayEventsFromItinerary(itinerary, destination);
  if (events.length === 0) {
    addMessage("No hay días válidos para enviar a Google Calendar.", "error");
    return;
  }

  const maxTabs = 10;
  const selectedEvents = events.slice(0, maxTabs);
  selectedEvents.forEach((event) => {
    const url = new URL("https://calendar.google.com/calendar/render");
    url.searchParams.set("action", "TEMPLATE");
    url.searchParams.set("text", event.title);
    url.searchParams.set("dates", `${compactDate(event.start)}/${compactDate(event.end)}`);
    url.searchParams.set("details", event.description);
    if (event.location) {
      url.searchParams.set("location", event.location);
    }
    window.open(url.toString(), "_blank", "noopener");
  });

  if (events.length > maxTabs) {
    addMessage(`Se abrieron ${maxTabs} días en Google Calendar (límite por seguridad).`, "info");
  } else {
    addMessage(`Se abrieron ${events.length} días en Google Calendar.`, "info");
  }
}

function setStep(stepName) {
  document.querySelectorAll(".step-pill").forEach((el) => el.classList.remove("active"));
  const active = document.querySelector(`.step-pill[data-step="${stepName}"]`);
  if (active) {
    active.classList.add("active");
  }
}

function clearMessages() {
  refs.messages.innerHTML = "";
}

function addMessage(message, level = "info") {
  const div = document.createElement("div");
  div.className = `msg ${level}`;
  div.textContent = message;
  refs.messages.appendChild(div);
}

function setLoading(button, isLoading, loadingText) {
  if (isLoading) {
    button.dataset.originalText = button.textContent;
    button.textContent = loadingText;
    button.disabled = true;
    return;
  }

  button.textContent = button.dataset.originalText || button.textContent;
  button.disabled = false;
}

function getTransportAndHotelMaps() {
  const transportItems = (state.options?.transport_options?.transports || []).map((item) => [
    String(item.id),
    item,
  ]);
  const hotelItems = (state.options?.hotel_options?.hotels || []).map((item) => [String(item.id), item]);
  return {
    transportById: new Map(transportItems),
    hotelById: new Map(hotelItems),
  };
}

function setupBudgetFilter() {
  const bundles = state.options?.candidate_bundles?.bundles || [];
  const prices = bundles
    .map((bundle) => bundle.total_estimated_cost_eur)
    .filter((value) => typeof value === "number");

  if (prices.length === 0) {
    state.budgetFilter = {
      enabled: false,
      minBound: 0,
      maxBound: 0,
      minValue: 0,
      maxValue: 0,
    };
    refs.budgetFilter.classList.add("hidden");
    return;
  }

  const minBound = Math.floor(Math.min(...prices));
  const maxBound = Math.ceil(Math.max(...prices));
  const step = maxBound - minBound > 200 ? 25 : 10;

  state.budgetFilter = {
    enabled: true,
    minBound,
    maxBound,
    minValue: minBound,
    maxValue: maxBound,
  };

  refs.budgetMin.min = String(minBound);
  refs.budgetMin.max = String(maxBound);
  refs.budgetMin.step = String(step);
  refs.budgetMin.value = String(minBound);

  refs.budgetMax.min = String(minBound);
  refs.budgetMax.max = String(maxBound);
  refs.budgetMax.step = String(step);
  refs.budgetMax.value = String(maxBound);

  refs.budgetFilter.classList.remove("hidden");
  syncBudgetFilterSummary(prices.length, prices.length);
}

function syncBudgetFilterSummary(visibleCount, totalCount) {
  if (!state.budgetFilter.enabled) {
    return;
  }
  refs.budgetRangeValue.textContent = `${formatBudgetValue(state.budgetFilter.minValue)} - ${formatBudgetValue(
    state.budgetFilter.maxValue
  )}`;
  refs.budgetVisibleCount.textContent = `${visibleCount} de ${totalCount} bundles en rango`;
}

function onBudgetSliderChange(which) {
  if (!state.budgetFilter.enabled) {
    return;
  }

  const rawMin = Number(refs.budgetMin.value);
  const rawMax = Number(refs.budgetMax.value);
  let minValue = rawMin;
  let maxValue = rawMax;

  if (which === "min" && rawMin > rawMax) {
    maxValue = rawMin;
    refs.budgetMax.value = String(maxValue);
  } else if (which === "max" && rawMax < rawMin) {
    minValue = rawMax;
    refs.budgetMin.value = String(minValue);
  }

  state.budgetFilter.minValue = minValue;
  state.budgetFilter.maxValue = maxValue;
  renderBundles();
}

function renderMetrics() {
  const transports = state.options?.transport_options?.transports || [];
  const hotels = state.options?.hotel_options?.hotels || [];
  const bundles = state.options?.candidate_bundles?.bundles || [];
  const weatherDays = state.options?.weather_forecast?.days || [];

  refs.metricTransports.textContent = String(transports.length);
  refs.metricHotels.textContent = String(hotels.length);
  refs.metricBundles.textContent = String(bundles.length);
  refs.metricWeather.textContent = String(weatherDays.length);
  refs.metricsSection.classList.remove("hidden");
}

function renderBundles() {
  const bundles = state.options?.candidate_bundles?.bundles || [];
  const { transportById, hotelById } = getTransportAndHotelMaps();
  const filterEnabled = state.budgetFilter.enabled;
  const filteredBundles = bundles.filter((bundle) => {
    const total = bundle.total_estimated_cost_eur;
    if (typeof total !== "number") {
      return true;
    }
    if (!filterEnabled) {
      return true;
    }
    return total >= state.budgetFilter.minValue && total <= state.budgetFilter.maxValue;
  });

  const selectedInRange = filteredBundles.some(
    (bundle) => String(bundle.bundle_id || "") === state.selectedBundleId
  );
  if (!selectedInRange) {
    state.selectedBundleId = "";
    state.selectedBundle = null;
  }

  refs.bundlesGrid.innerHTML = "";
  refs.generateButton.disabled = !state.selectedBundle || !selectedInRange;

  if (filterEnabled) {
    const pricedTotal = bundles.filter((bundle) => typeof bundle.total_estimated_cost_eur === "number").length;
    const pricedVisible = filteredBundles.filter(
      (bundle) => typeof bundle.total_estimated_cost_eur === "number"
    ).length;
    syncBudgetFilterSummary(pricedVisible, pricedTotal);
  }

  filteredBundles.forEach((bundle) => {
    const bundleId = String(bundle.bundle_id || "");
    const transport = transportById.get(String(bundle.transport_id || "")) || {};
    const hotel = hotelById.get(String(bundle.hotel_id || "")) || {};
    const isSelected = bundleId === state.selectedBundleId;

    const card = document.createElement("article");
    card.className = `bundle-card${isSelected ? " selected" : ""}`;
    const transportLine = `${transportModeLabel(transport)} · ${transportProviderLabel(transport)} · ${
      transport.currency || "EUR"
    }`;

    const tags = (bundle.pros || [])
      .slice(0, 3)
      .map((pro) => `<span class="bundle-tag">${escapeHtml(String(pro))}</span>`)
      .join("");

    card.innerHTML = `
      <div class="bundle-top">
        <div>
          <p class="bundle-id">${escapeHtml(bundleId)}${isSelected ? " · Seleccionado" : ""}</p>
          <p class="bundle-title">${escapeHtml(bundle.label || "Bundle")}</p>
        </div>
        <span class="bundle-price">${formatPrice(bundle.total_estimated_cost_eur)}</span>
      </div>
      <p class="bundle-row"><strong>Transporte:</strong> ${escapeHtml(transportLine)}</p>
      <p class="bundle-row"><strong>Hotel:</strong> ${escapeHtml(hotel.name || String(bundle.hotel_id || "Hotel"))}</p>
      <div class="bundle-tags">${tags}</div>
      <button class="bundle-action" type="button">${isSelected ? "Seleccionado" : "Seleccionar bundle"}</button>
    `;

    const actionButton = card.querySelector(".bundle-action");
    actionButton.addEventListener("click", () => {
      state.selectedBundleId = bundleId;
      state.selectedBundle = bundle;
      setStep("bundle");
      renderBundles();
    });

    refs.bundlesGrid.appendChild(card);
  });

  if (filteredBundles.length === 0) {
    refs.bundlesGrid.innerHTML = `
      <div class="bundles-empty">
        No hay bundles dentro de este rango de presupuesto. Ajusta los sliders para ver más opciones.
      </div>
    `;
  }

  refs.bundlesSection.classList.remove("hidden");
}

function renderItinerary() {
  const itinerary = state.itinerary?.final_itinerary;
  if (!itinerary) {
    return;
  }

  refs.itinerarySummary.textContent = itinerary.summary || "";
  refs.itineraryDays.innerHTML = "";

  const weatherMap = normalizeWeatherMap(state.options?.weather_forecast || {});

  (itinerary.days || []).forEach((day) => {
    const dayWeather = weatherMap.get(String(day.date || ""));
    const weatherGroup = dayWeather?.weather_group || "neutral";
    const icon = WEATHER_ICON[weatherGroup] || WEATHER_ICON.neutral;

    const card = document.createElement("article");
    card.className = `day-card mood-${weatherGroup}`;
    card.innerHTML = `
      <div class="day-head">
        <p class="day-date">${escapeHtml(String(day.date || ""))}</p>
        <p class="day-weather">${escapeHtml(`${icon} ${weatherSummary(dayWeather)}`)}</p>
      </div>
      <ul class="day-list">
        ${(day.blocks || []).map((block) => `<li>${escapeHtml(String(block))}</li>`).join("")}
      </ul>
    `;

    refs.itineraryDays.appendChild(card);
  });

  refs.itinerarySection.classList.remove("hidden");
  setItineraryActionsEnabled(true);
}

function ensureRoadRouteMap() {
  if (state.roadRoute.map || typeof window.L === "undefined") {
    return;
  }

  state.roadRoute.map = window.L.map(refs.roadRouteView, {
    zoomControl: true,
  }).setView([40.4168, -3.7038], 6);

  window.L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(state.roadRoute.map);

  state.roadRoute.layerGroup = window.L.layerGroup().addTo(state.roadRoute.map);
}

function clearRoadRouteLayers() {
  if (!state.roadRoute.layerGroup) {
    return;
  }
  state.roadRoute.layerGroup.clearLayers();
}

function renderRoadRouteWarnings(warnings) {
  refs.roadRouteWarnings.innerHTML = "";
  (warnings || []).forEach((warning) => {
    const item = document.createElement("div");
    item.className = "road-route-warning";
    item.textContent = warning;
    refs.roadRouteWarnings.appendChild(item);
  });
}

function renderRoadRouteData(data) {
  ensureRoadRouteMap();
  clearRoadRouteLayers();

  if (!state.roadRoute.map || !state.roadRoute.layerGroup) {
    refs.roadRouteSummary.textContent = "No se pudo inicializar Leaflet en este navegador.";
    return;
  }

  const boundsPoints = [];
  const origin = data.origin_point || null;
  const destination = data.destination_point || null;

  if (origin && typeof origin.lat === "number" && typeof origin.lon === "number") {
    const marker = window.L.marker([origin.lat, origin.lon]).bindPopup(
      `<strong>Origen</strong><br/>${escapeHtml(origin.label || data.origin || "")}`
    );
    marker.addTo(state.roadRoute.layerGroup);
    boundsPoints.push([origin.lat, origin.lon]);
  }

  if (destination && typeof destination.lat === "number" && typeof destination.lon === "number") {
    const marker = window.L.marker([destination.lat, destination.lon]).bindPopup(
      `<strong>Destino</strong><br/>${escapeHtml(destination.label || data.destination || "")}`
    );
    marker.addTo(state.roadRoute.layerGroup);
    boundsPoints.push([destination.lat, destination.lon]);
  }

  const path = (data.path || []).filter((item) => Array.isArray(item) && item.length === 2);
  if (path.length >= 2) {
    window.L.polyline(path, {
      color: "#0f5fd4",
      weight: 4,
      opacity: 0.78,
    }).addTo(state.roadRoute.layerGroup);
    boundsPoints.push(...path);
  }

  if (boundsPoints.length > 0) {
    const bounds = window.L.latLngBounds(boundsPoints);
    state.roadRoute.map.fitBounds(bounds.pad(0.2));
  }

  state.roadRoute.map.invalidateSize();
  if (data.reachable_by_car) {
    refs.roadRouteSummary.textContent =
      `Ruta en coche: ${formatDistance(data.distance_km)} · ${formatMinutes(data.duration_min)} ` +
      `(${data.route_source === "osrm" ? "OSRM" : "estimación"})`;
  } else {
    const direct = typeof data.direct_distance_km === "number" ? `Distancia en línea recta: ${formatDistance(data.direct_distance_km)}.` : "";
    refs.roadRouteSummary.textContent = `No hay ruta en coche disponible entre origen y destino. ${direct}`.trim();
  }
  renderRoadRouteWarnings(data.warnings || []);
  setRoadRouteGoogleMapsLinkFromRouteData(data, data.origin || "", data.destination || "");
}

function resetRoadRouteView() {
  state.roadRoute.data = null;
  refs.roadRouteSection.classList.add("hidden");
  refs.roadRouteSummary.textContent = "";
  refs.roadRouteWarnings.innerHTML = "";
  setRoadRouteGoogleMapsLink("", "");
  clearRoadRouteLayers();
}

async function maybeLoadRoadRouteForCar() {
  const trip = state.options?.trip_request || {};
  const hasCarTransport = (state.options?.transport_options?.transports || []).some(
    (item) => String(item?.mode || "").toLowerCase() === "coche"
  );
  if (!hasCarTransport) {
    resetRoadRouteView();
    return;
  }

  const origin = String(trip.origin || "").trim();
  const destination = String(trip.destination || "").trim();
  if (!origin || !destination) {
    refs.roadRouteSection.classList.add("hidden");
    setRoadRouteGoogleMapsLink("", "");
    return;
  }

  setRoadRouteGoogleMapsLink(origin, destination);
  refs.roadRouteSection.classList.remove("hidden");
  refs.roadRouteSummary.textContent = "Calculando ruta en coche...";
  renderRoadRouteWarnings([]);

  try {
    const data = await postJson("/api/road-route", { origin, destination });
    state.roadRoute.data = data;
    renderRoadRouteData(data);
    if (!data.reachable_by_car) {
      addMessage(
        "Seguridad: no se ha encontrado ruta en coche entre origen y destino. Revisa el trayecto o cambia el modo de transporte.",
        "error"
      );
    }
  } catch (error) {
    refs.roadRouteSummary.textContent = "No se pudo calcular la ruta en coche.";
    renderRoadRouteWarnings([String(error?.message || error)]);
  }
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  let data = null;
  try {
    data = await response.json();
  } catch {
    data = null;
  }

  if (!response.ok) {
    const detail = data?.detail || `Error HTTP ${response.status}`;
    throw new Error(detail);
  }
  return data;
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function onSubmitTrip(event) {
  event.preventDefault();
  clearMessages();

  state.options = null;
  state.selectedBundle = null;
  state.selectedBundleId = "";
  state.itinerary = null;
  resetRoadRouteView();

  refs.metricsSection.classList.add("hidden");
  refs.bundlesSection.classList.add("hidden");
  refs.budgetFilter.classList.add("hidden");
  refs.itinerarySection.classList.add("hidden");
  refs.bundlesGrid.innerHTML = "";
  refs.itineraryDays.innerHTML = "";
  refs.generateButton.disabled = true;
  setItineraryActionsEnabled(false);
  setStep("options");

  const payload = {
    origin: document.querySelector("#origin").value.trim(),
    destination: document.querySelector("#destination").value.trim(),
    start_date: document.querySelector("#start_date").value,
    end_date: document.querySelector("#end_date").value,
    interests: document.querySelector("#interests").value,
  };

  setLoading(refs.submitButton, true, "Buscando...");
  try {
    const data = await postJson("/api/options", payload);
    state.options = data;
    setupBudgetFilter();
    renderMetrics();
    renderBundles();
    await maybeLoadRoadRouteForCar();
    (data.notices || []).forEach((note) => addMessage(note, "info"));
    if ((data.candidate_bundles?.bundles || []).length === 0) {
      addMessage("No se encontraron bundles con los datos indicados.", "error");
    } else {
      addMessage("Opciones generadas. Selecciona el bundle para crear itinerario.", "info");
    }
  } catch (error) {
    addMessage(`No se pudieron generar opciones: ${error.message}`, "error");
  } finally {
    setLoading(refs.submitButton, false);
  }
}

async function onGenerateItinerary() {
  clearMessages();
  if (!state.selectedBundle || !state.options?.trip_request) {
    addMessage("Selecciona un bundle antes de generar el itinerario.", "error");
    return;
  }

  setStep("itinerary");
  setLoading(refs.generateButton, true, "Generando itinerario...");
  try {
    const payload = {
      trip_request: state.options.trip_request,
      selected_bundle: state.selectedBundle,
      weather_forecast: state.options.weather_forecast || {},
    };
    const data = await postJson("/api/itinerary", payload);
    state.itinerary = data;
    renderItinerary();
    (data.notices || []).forEach((note) => addMessage(note, "info"));
    addMessage("Itinerario generado con ItineraryAgent.", "info");
  } catch (error) {
    setItineraryActionsEnabled(false);
    addMessage(`No se pudo generar itinerario: ${error.message}`, "error");
  } finally {
    setLoading(refs.generateButton, false);
  }
}

function bootstrap() {
  setDefaultDates();
  setStep("options");
  setItineraryActionsEnabled(false);
  refs.form.addEventListener("submit", onSubmitTrip);
  refs.generateButton.addEventListener("click", onGenerateItinerary);
  refs.exportJsonButton.addEventListener("click", onExportItineraryJson);
  refs.exportIcsButton.addEventListener("click", onExportItineraryIcs);
  refs.googleCalendarButton.addEventListener("click", onOpenGoogleCalendar);
  refs.budgetMin.addEventListener("input", () => onBudgetSliderChange("min"));
  refs.budgetMax.addEventListener("input", () => onBudgetSliderChange("max"));
}

bootstrap();
