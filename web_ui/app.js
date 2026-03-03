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
  calendarExport: document.querySelector("#calendar-export"),
  roadRouteSection: document.querySelector("#road-route-section"),
  roadRouteView: document.querySelector("#road-route-view"),
  roadRouteSummary: document.querySelector("#road-route-summary"),
  roadRouteWarnings: document.querySelector("#road-route-warnings"),
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

// ─── Calendar Export (RFC 5545) ──────────────────────────────────────────────

/**
 * Escapes special characters in iCalendar property values per RFC 5545 §3.3.11.
 */
function escapeICSValue(str) {
  return String(str || "")
    .replace(/\\/g, "\\\\")
    .replace(/;/g, "\\;")
    .replace(/,/g, "\\,")
    .replace(/\n|\r\n/g, "\\n")
    .replace(/\r/g, "");
}

/**
 * Folds long iCalendar lines per RFC 5545 §3.1:
 * lines MUST NOT be longer than 75 octets, folded with CRLF + single SPACE.
 */
function foldICSLine(line) {
  const encoder = new TextEncoder();
  if (encoder.encode(line).length <= 75) return line;

  const result = [];
  let current = "";
  let byteCount = 0;

  for (const char of line) {
    const charLen = encoder.encode(char).length;
    if (byteCount + charLen > 75) {
      result.push(current);
      current = " " + char;
      byteCount = 1 + charLen;
    } else {
      current += char;
      byteCount += charLen;
    }
  }
  if (current) result.push(current);
  return result.join("\r\n");
}

/**
 * Returns a DTSTAMP-format UTC timestamp string (e.g. 20260303T120000Z).
 */
function nowDTSTAMP() {
  return new Date().toISOString().replace(/[-:]/g, "").split(".")[0] + "Z";
}

/**
 * Parses an ISO date string and returns the next day in YYYYMMDD format.
 */
function nextDayCompact(isoDate) {
  const d = new Date(isoDate + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() + 1);
  return d.toISOString().slice(0, 10).replace(/-/g, "");
}

/**
 * Generates a fully RFC 5545–compliant VCALENDAR string with one VEVENT per
 * itinerary day. Uses DATE (all-day) events so no timezone handling is needed.
 */
function generateICS(itinerary, tripRequest) {
  const destination = escapeICSValue(tripRequest?.destination || "Destino");
  const dtstamp = nowDTSTAMP();
  const prodId = "-//Travel Buddy//Travel Buddy 1.0//ES";

  const header = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    `PRODID:${prodId}`,
    "CALSCALE:GREGORIAN",
    "METHOD:PUBLISH",
    `X-WR-CALNAME:Viaje a ${destination}`,
    "X-WR-CALDESC:Itinerario generado por Travel Buddy",
  ];

  const events = (itinerary?.days || []).flatMap((day, idx) => {
    const dateCompact = (day.date || "").replace(/-/g, "");
    if (!dateCompact) return [];

    const dtend = nextDayCompact(day.date);
    const summary = escapeICSValue(`Día ${idx + 1} en ${destination}`);
    const blocks = (day.blocks || []).join("\n");
    const description = escapeICSValue(blocks);
    const uid = `travelbuddy-${dateCompact}-${idx}@local`;
    const location = escapeICSValue(tripRequest?.destination || "");

    return [
      "BEGIN:VEVENT",
      foldICSLine(`UID:${uid}`),
      `DTSTAMP:${dtstamp}`,
      `DTSTART;VALUE=DATE:${dateCompact}`,
      `DTEND;VALUE=DATE:${dtend}`,
      foldICSLine(`SUMMARY:${summary}`),
      foldICSLine(`DESCRIPTION:${description}`),
      ...(location ? [foldICSLine(`LOCATION:${location}`)] : []),
      "TRANSP:TRANSPARENT",
      "END:VEVENT",
    ];
  });

  const footer = ["END:VCALENDAR"];

  return [...header, ...events, ...footer].join("\r\n");
}

/**
 * Triggers a browser download of an .ics file.
 */
function downloadICS(itinerary, tripRequest) {
  const content = generateICS(itinerary, tripRequest);
  const blob = new Blob([content], { type: "text/calendar;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const destination = (tripRequest?.destination || "viaje").toLowerCase().replace(/\s+/g, "-");
  const a = document.createElement("a");
  a.href = url;
  a.download = `itinerario-${destination}.ics`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

/**
 * Opens one Google Calendar "Add Event" tab per itinerary day.
 * Staggered with 700 ms delay to reduce popup-blocker interference.
 * Falls back to a single overview event if the browser blocks popups.
 */
function openGoogleCalendarEvents(itinerary, tripRequest) {
  const destination = tripRequest?.destination || "Destino";
  const days = itinerary?.days || [];
  if (!days.length) return;

  let blocked = false;

  days.forEach((day, idx) => {
    setTimeout(() => {
      const dateCompact = (day.date || "").replace(/-/g, "");
      const dtend = nextDayCompact(day.date);
      const title = `Día ${idx + 1} en ${destination}`;
      const details = (day.blocks || []).join("\n");

      const params = new URLSearchParams({
        action: "TEMPLATE",
        text: title,
        dates: `${dateCompact}/${dtend}`,
        details,
        sf: "true",
        output: "xml",
      });

      const win = window.open(
        `https://www.google.com/calendar/render?${params.toString()}`,
        "_blank"
      );

      if (!win && !blocked) {
        blocked = true;
        addMessage(
          "El navegador bloqueó las ventanas emergentes. Permite ventanas emergentes para este sitio y vuelve a intentarlo, o usa la opción iCalendar para importar manualmente.",
          "error"
        );
      }
    }, idx * 700);
  });

  if (days.length > 1) {
    addMessage(
      `Se abrirán ${days.length} pestañas de Google Calendar, una por día. Si el navegador las bloquea, permite las ventanas emergentes e inténtalo de nuevo.`,
      "info"
    );
  }
}

function renderCalendarExport() {
  if (!refs.calendarExport) return;
  refs.calendarExport.classList.remove("hidden");
}

function hideCalendarExport() {
  if (!refs.calendarExport) return;
  refs.calendarExport.classList.add("hidden");
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function setDefaultDates() {
  const start = new Date();
  start.setDate(start.getDate() + 9);
  const end = new Date();
  end.setDate(end.getDate() + 12);

  document.querySelector("#start_date").value = formatDate(start);
  document.querySelector("#end_date").value = formatDate(end);
}

function formatDate(value) {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
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
      <p class="bundle-row"><strong>Transporte:</strong> ${escapeHtml(
        `${transport.mode || "n/a"} · ${transport.provider || "sin proveedor"} · ${transport.currency || "EUR"}`
      )}</p>
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
      updateGmapsLink();
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
  renderCalendarExport();
}

// ─── Road route ──────────────────────────────────────────────────────────────

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

// ─── Fuel estimation ─────────────────────────────────────────────────────────
// Static assumptions (European averages, adjustable here):
const FUEL_L_PER_100KM = 7.0;   // litres per 100 km (mixed urban+highway)
const FUEL_PRICE_EUR_L  = 1.65; // € per litre (Eurostat EU avg, 2024)

/**
 * Returns a fuel estimation object for a given road distance.
 * All math is static/deterministic — no external calls.
 */
function estimateFuel(distanceKm) {
  if (typeof distanceKm !== "number" || distanceKm <= 0) return null;
  const litres     = (distanceKm / 100) * FUEL_L_PER_100KM;
  const costEur    = litres * FUEL_PRICE_EUR_L;
  return {
    litres:        Math.round(litres  * 10) / 10,   // 1 decimal
    costEur:       Math.round(costEur * 100) / 100, // 2 decimals
    lPer100km:     FUEL_L_PER_100KM,
    pricePerLitre: FUEL_PRICE_EUR_L,
  };
}

/**
 * Builds and updates the Google Maps deep-link using the road route data
 * already stored in state.roadRoute.data. Safe to call at any time;
 * does nothing if there is no route data yet.
 */
function updateGmapsLink(routeData) {
  const data     = routeData || state.roadRoute.data;
  const gmapsDiv  = document.querySelector("#road-route-gmaps");
  const gmapsLink = document.querySelector("#road-route-gmaps-link");

  if (!gmapsDiv || !gmapsLink || !data?.origin_point) {
    if (gmapsDiv) gmapsDiv.classList.add("hidden");
    return;
  }

  const orig = `${data.origin_point.lat},${data.origin_point.lon}`;

  const hotelId    = state.selectedBundle?.hotel_id;
  const hotels     = state.options?.hotel_options?.hotels || [];
  const hotel      = hotels.find((h) => String(h.id) === String(hotelId));
  const hotelQuery = [hotel?.name, hotel?.area || state.options?.trip_request?.destination]
    .filter(Boolean)
    .join(", ");

  const dest = hotelQuery
    ? encodeURIComponent(hotelQuery)
    : data.destination_point
      ? `${data.destination_point.lat},${data.destination_point.lon}`
      : null;

  if (!dest) {
    gmapsDiv.classList.add("hidden");
    return;
  }

  gmapsLink.href  = `https://www.google.com/maps/dir/?api=1&origin=${orig}&destination=${dest}&travelmode=driving`;
  gmapsLink.title = hotelQuery ? `Ir a ${hotelQuery}` : "Abrir ruta en Google Maps";
  gmapsDiv.classList.remove("hidden");
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

  // Google Maps deep-link — updated here and again when a bundle is selected
  updateGmapsLink(data);

  if (data.reachable_by_car) {
    const source = data.route_source === "osrm" ? "OSRM" : "estimación";
    refs.roadRouteSummary.textContent =
      `Ruta en coche: ${formatDistance(data.distance_km)} · ${formatMinutes(data.duration_min)} (${source})`;

    // Fuel estimation
    const fuel = estimateFuel(data.distance_km);
    const fuelEl = document.querySelector("#road-route-fuel");
    if (fuelEl && fuel) {
      fuelEl.innerHTML = `
        <div class="fuel-grid">
          <div class="fuel-stat">
            <span class="fuel-stat-icon">⛽</span>
            <div>
              <p class="fuel-stat-label">Combustible estimado</p>
              <p class="fuel-stat-value">${fuel.litres} L</p>
            </div>
          </div>
          <div class="fuel-stat">
            <span class="fuel-stat-icon">💶</span>
            <div>
              <p class="fuel-stat-label">Coste aproximado</p>
              <p class="fuel-stat-value">${new Intl.NumberFormat("es-ES", { style: "currency", currency: "EUR" }).format(fuel.costEur)}</p>
            </div>
          </div>
          <div class="fuel-stat fuel-stat--wide">
            <span class="fuel-stat-icon">📐</span>
            <div>
              <p class="fuel-stat-label">Cálculo</p>
              <p class="fuel-stat-meta">${formatDistance(data.distance_km)} × ${fuel.lPer100km} L/100 km = <strong>${fuel.litres} L</strong> · ${fuel.lPer100km} L × ${fuel.pricePerLitre} €/L = <strong>${new Intl.NumberFormat("es-ES", { style: "currency", currency: "EUR" }).format(fuel.costEur)}</strong></p>
              <p class="fuel-stat-disclaimer">Consumo medio estimado (${fuel.lPer100km} L/100 km) · Precio referencia ${fuel.pricePerLitre} €/L</p>
            </div>
          </div>
        </div>
      `;
      fuelEl.classList.remove("hidden");
    }
  } else {
    const direct = typeof data.direct_distance_km === "number"
      ? `Distancia en línea recta: ${formatDistance(data.direct_distance_km)}.`
      : "";
    refs.roadRouteSummary.textContent =
      `No hay ruta en coche disponible entre origen y destino. ${direct}`.trim();

    const fuelEl = document.querySelector("#road-route-fuel");
    if (fuelEl) fuelEl.classList.add("hidden");
  }
  renderRoadRouteWarnings(data.warnings || []);
}

function resetRoadRouteView() {
  state.roadRoute.data = null;
  refs.roadRouteSection.classList.add("hidden");
  refs.roadRouteSummary.textContent = "";
  refs.roadRouteWarnings.innerHTML = "";
  const fuelEl = document.querySelector("#road-route-fuel");
  if (fuelEl) fuelEl.classList.add("hidden");
  const gmapsDiv = document.querySelector("#road-route-gmaps");
  if (gmapsDiv) gmapsDiv.classList.add("hidden");
  clearRoadRouteLayers();
}

async function maybeLoadRoadRouteForCar() {
  const trip = state.options?.trip_request || {};
  const mode = String(trip.transport_mode || "").toLowerCase();
  if (mode !== "coche") {
    resetRoadRouteView();
    return;
  }

  const origin = String(trip.origin || "").trim();
  const destination = String(trip.destination || "").trim();
  if (!origin || !destination) {
    refs.roadRouteSection.classList.add("hidden");
    return;
  }

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

// ─── Network ─────────────────────────────────────────────────────────────────

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

// ─── Event handlers ───────────────────────────────────────────────────────────

async function onSubmitTrip(event) {
  event.preventDefault();
  clearMessages();

  state.options = null;
  state.selectedBundle = null;
  state.selectedBundleId = "";
  state.itinerary = null;
  resetRoadRouteView();
  hideCalendarExport();

  refs.metricsSection.classList.add("hidden");
  refs.bundlesSection.classList.add("hidden");
  refs.budgetFilter.classList.add("hidden");
  refs.itinerarySection.classList.add("hidden");
  refs.bundlesGrid.innerHTML = "";
  refs.itineraryDays.innerHTML = "";
  refs.generateButton.disabled = true;
  setStep("options");

  const payload = {
    origin: document.querySelector("#origin").value.trim(),
    destination: document.querySelector("#destination").value.trim(),
    start_date: document.querySelector("#start_date").value,
    end_date: document.querySelector("#end_date").value,
    transport_mode: document.querySelector('input[name="transport_mode"]:checked').value,
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
  hideCalendarExport();

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
    addMessage(`No se pudo generar itinerario: ${error.message}`, "error");
  } finally {
    setLoading(refs.generateButton, false);
  }
}

// ─── Bootstrap ───────────────────────────────────────────────────────────────

function bootstrap() {
  setDefaultDates();
  setStep("options");
  refs.form.addEventListener("submit", onSubmitTrip);
  refs.generateButton.addEventListener("click", onGenerateItinerary);
  refs.budgetMin.addEventListener("input", () => onBudgetSliderChange("min"));
  refs.budgetMax.addEventListener("input", () => onBudgetSliderChange("max"));

  // Calendar export buttons
  document.querySelector("#cal-google")?.addEventListener("click", () => {
    const itinerary = state.itinerary?.final_itinerary;
    const trip = state.options?.trip_request;
    if (!itinerary) return;
    openGoogleCalendarEvents(itinerary, trip);
  });

  document.querySelector("#cal-outlook")?.addEventListener("click", () => {
    const itinerary = state.itinerary?.final_itinerary;
    const trip = state.options?.trip_request;
    if (!itinerary) return;
    downloadICS(itinerary, trip);
  });

  document.querySelector("#cal-ical")?.addEventListener("click", () => {
    const itinerary = state.itinerary?.final_itinerary;
    const trip = state.options?.trip_request;
    if (!itinerary) return;
    downloadICS(itinerary, trip);
  });
}

bootstrap();