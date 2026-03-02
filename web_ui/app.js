const state = {
  options: null,
  selectedBundleId: "",
  selectedBundle: null,
  itinerary: null,
};

const refs = {
  form: document.querySelector("#trip-form"),
  submitButton: document.querySelector("#submit-trip"),
  generateButton: document.querySelector("#generate-itinerary"),
  bundlesSection: document.querySelector("#bundles-section"),
  bundlesGrid: document.querySelector("#bundles-grid"),
  metricsSection: document.querySelector("#metrics-section"),
  itinerarySection: document.querySelector("#itinerary-section"),
  itinerarySummary: document.querySelector("#itinerary-summary"),
  itineraryDays: document.querySelector("#itinerary-days"),
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

  refs.bundlesGrid.innerHTML = "";
  refs.generateButton.disabled = !state.selectedBundle;

  bundles.forEach((bundle) => {
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
    });

    refs.bundlesGrid.appendChild(card);
  });

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

  refs.metricsSection.classList.add("hidden");
  refs.bundlesSection.classList.add("hidden");
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
    renderMetrics();
    renderBundles();
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
    addMessage(`No se pudo generar itinerario: ${error.message}`, "error");
  } finally {
    setLoading(refs.generateButton, false);
  }
}

function bootstrap() {
  setDefaultDates();
  setStep("options");
  refs.form.addEventListener("submit", onSubmitTrip);
  refs.generateButton.addEventListener("click", onGenerateItinerary);
}

bootstrap();
