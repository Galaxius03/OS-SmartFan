/**
 * app.js — Thermal Monitor Dashboard
 * CSC1107 Project 10, GPIO Smart Fan Controller (LED Variant)
 *
 * Polls /api/status every 3 seconds and updates all dashboard cards.
 * Matches the setInterval / DOM-update pattern from the previous networking project.
 *
 * Key functions:
 *   refreshData()       — fetches /api/status and dispatches to update helpers
 *   updateTemperature() — gauge arc, value text, status colour
 *   updateHumidity()    — progress bar and value text
 *   updateLed()         — dot colour, state label, auto-mode badge
 *   updateHistory()     — SVG polyline chart for last 20 readings
 *   sendCommand()       — POSTs to /api/led/* for manual control buttons
 *   setIndicator()      — updates the topbar connection chip (same as previous project)
 */

"use strict";

/* ── Constants ────────────────────────────────────────────────────────────── */

/** How often to poll the API, in milliseconds. */
const POLL_INTERVAL_MS = 3000;

/** Temperature range for the gauge arc (°C). */
const GAUGE_MIN = 20;
const GAUGE_MAX = 50;

/** Threshold that triggers the LED (must match TEMP_THRESHOLD in led.py). */
const TEMP_THRESHOLD = 29;

/** Maximum number of data points kept in the history chart. */
const HISTORY_MAX = 20;

/* ── Element references (same pattern as previous project's ids object) ───── */
const el = {
  lastUpdated:     document.getElementById("last-updated"),
  indicatorSensor: document.getElementById("indicator-sensor"),
  indicatorLed:    document.getElementById("indicator-led"),

  // Temperature card
  gaugeArc:        document.getElementById("gauge-arc"),
  gaugeLabel:      document.getElementById("gauge-label"),
  tempValue:       document.getElementById("temp-value"),
  tempStatus:      document.getElementById("temp-status"),

  // Humidity card
  humidityValue:   document.getElementById("humidity-value"),
  humidityStatus:  document.getElementById("humidity-status"),
  humidityBar:     document.getElementById("humidity-bar"),

  // LED card
  ledDot:          document.getElementById("led-dot"),
  ledValue:        document.getElementById("led-value"),
  ledMode:         document.getElementById("led-mode"),

  // Controls card
  controlsFeedback: document.getElementById("controls-feedback"),

  // History chart
  historyLine:     document.getElementById("history-line"),
  historyFill:     document.getElementById("history-fill"),
  thresholdLine:   document.getElementById("threshold-line"),
};

/* ── State ────────────────────────────────────────────────────────────────── */

/** Rolling array of the last HISTORY_MAX temperature readings. */
const tempHistory = [];

/* ── Helpers: status colour classes ──────────────────────────────────────── */

/**
 * setStatusClass — remove all status classes then apply the given one.
 * Mirrors the same helper from the previous project's app.js.
 */
function setStatusClass(element, level) {
  if (!element) return;
  element.classList.remove("status-ok", "status-warn", "status-danger");
  if (level) element.classList.add(level);
}

/**
 * setIndicator — update a topbar chip label and colour.
 * Mirrors indicatorConnectionState() from the previous project.
 */
function setIndicator(element, label, isConnected) {
  if (!element) return;
  element.textContent = `${label}: ${isConnected ? "Connected" : "Disconnected"}`;
  setStatusClass(element, isConnected ? "status-ok" : "status-danger");
}

/* ── Temperature gauge (SVG arc) ─────────────────────────────────────────── */

/**
 * updateGaugeArc — draws the coloured semicircle arc proportional to temperature.
 *
 * Gauge geometry:
 *   Centre (cx, cy) = (100, 100), radius r = 80
 *   Start point     = (cx - r, cy) = (20, 100)  → 9 o'clock (coldest)
 *   End point       = (cx + r, cy) = (180, 100) → 3 o'clock (hottest)
 *   Arc sweeps clockwise through the top (12 o'clock) as temperature rises.
 *
 * SVG arc formula:
 *   angle_rad = π × (1 - pct)          — maps 0% → π (left) to 100% → 0 (right)
 *   ex = cx + r × cos(angle_rad)
 *   ey = cy − r × sin(angle_rad)       — subtract because SVG y-axis is inverted
 *   sweep-flag = 1 (clockwise through the top)
 *   large-arc-flag = 0 (arc ≤ 180° for all percentages)
 *
 * @param {number} temp — corrected temperature in °C
 */
function updateGaugeArc(temp) {
  const cx = 100, cy = 100, r = 80;

  // Clamp percentage to [0, 1]
  const pct = Math.max(0, Math.min(1, (temp - GAUGE_MIN) / (GAUGE_MAX - GAUGE_MIN)));

  const angleRad = Math.PI * (1 - pct);
  const ex = cx + r * Math.cos(angleRad);
  const ey = cy - r * Math.sin(angleRad);   // SVG y is inverted

  // Choose arc colour based on temperature zone
  let color;
  if (temp >= TEMP_THRESHOLD + 10) {
    color = "var(--danger)";  // very hot
  } else if (temp >= TEMP_THRESHOLD) {
    color = "var(--warn)";    // warm / LED should be on
  } else {
    color = "var(--ok)";      // cool / LED should be off
  }

  if (pct <= 0) {
    // No arc at minimum — clear the path
    el.gaugeArc.setAttribute("d", "");
  } else {
    // M = move to start, A = arc command
    el.gaugeArc.setAttribute(
      "d",
      `M 20 100 A ${r} ${r} 0 0 1 ${ex.toFixed(2)} ${ey.toFixed(2)}`
    );
  }

  el.gaugeArc.setAttribute("stroke", color);
  el.gaugeLabel.textContent = temp.toFixed(1);
  el.gaugeLabel.setAttribute("fill", color);
}

/* ── Card update functions ────────────────────────────────────────────────── */

/**
 * updateTemperature — refresh the temperature card.
 * @param {number|null} temp — corrected temperature in °C, or null if unavailable
 */
function updateTemperature(temp) {
  if (temp === null || !Number.isFinite(temp)) {
    el.gaugeArc.setAttribute("d", "");
    el.gaugeLabel.textContent = "--";
    el.tempValue.textContent  = "-- °C";
    el.tempStatus.textContent = "No sensor data";
    setStatusClass(el.tempValue, "status-danger");
    return;
  }

  updateGaugeArc(temp);

  el.tempValue.textContent = `${temp.toFixed(1)} °C`;

  // Status text and colour
  if (temp >= TEMP_THRESHOLD + 10) {
    el.tempStatus.textContent = "Hot — LED should be ON";
    setStatusClass(el.tempValue, "status-danger");
  } else if (temp >= TEMP_THRESHOLD) {
    el.tempStatus.textContent = "Warm — LED should be ON";
    setStatusClass(el.tempValue, "status-warn");
  } else {
    el.tempStatus.textContent = "Cool — LED should be OFF";
    setStatusClass(el.tempValue, "status-ok");
  }
}

/**
 * updateHumidity — refresh the humidity card with progress bar.
 * @param {number|null} humidity — relative humidity in %, or null if unavailable
 */
function updateHumidity(humidity) {
  if (humidity === null || !Number.isFinite(humidity)) {
    el.humidityValue.textContent  = "-- %";
    el.humidityStatus.textContent = "No sensor data";
    el.humidityBar.style.width    = "0%";
    setStatusClass(el.humidityValue, "status-danger");
    return;
  }

  el.humidityValue.textContent = `${humidity.toFixed(1)} %`;
  el.humidityBar.style.width   = `${Math.min(100, humidity).toFixed(1)}%`;

  if (humidity >= 95) {
    el.humidityStatus.textContent   = "High humidity — auto-trigger active";
    el.humidityBar.style.background = "var(--danger)";
    setStatusClass(el.humidityValue, "status-danger");
  } else if (humidity >= 75) {
    el.humidityStatus.textContent   = "Moderate — within normal range";
    el.humidityBar.style.background = "var(--warn)";
    setStatusClass(el.humidityValue, "status-warn");
  } else {
    el.humidityStatus.textContent   = "Comfortable";
    el.humidityBar.style.background = "var(--ok)";
    setStatusClass(el.humidityValue, "status-ok");
  }
}

/**
 * updateLed — refresh the LED status card.
 * @param {boolean|null} isOn      — true if LED is on
 * @param {boolean|null} autoMode  — true if auto-mode is active
 */
function updateLed(isOn, autoMode) {
  // Remove previous state classes from dot
  el.ledDot.classList.remove("on", "off");

  if (isOn === null) {
    el.ledValue.textContent = "--";
    el.ledMode.textContent  = "Auto-mode: --";
    setStatusClass(el.ledValue, null);
    return;
  }

  if (isOn) {
    el.ledDot.classList.add("on");
    el.ledValue.textContent = "LED ON";
    setStatusClass(el.ledValue, "status-ok");
  } else {
    el.ledDot.classList.add("off");
    el.ledValue.textContent = "LED OFF";
    setStatusClass(el.ledValue, "status-warn");
  }

  el.ledMode.textContent = autoMode
    ? "Auto-mode: enabled (sensor-controlled)"
    : "Auto-mode: disabled (manual override)";
}

/* ── Temperature history chart ────────────────────────────────────────────── */

/**
 * updateHistoryChart — redraws the SVG polyline from tempHistory[].
 *
 * Chart geometry (matches SVG viewBox="0 0 600 160"):
 *   Width:  600 px (scales automatically via preserveAspectRatio="none")
 *   Height: 160 px
 *   Y range: GAUGE_MIN to GAUGE_MAX
 *   X range: 0 to HISTORY_MAX points, equally spaced
 */
function updateHistoryChart() {
  const W = 600, H = 160;
  const PADDING = { top: 10, bottom: 10 };
  const plotH = H - PADDING.top - PADDING.bottom;

  if (tempHistory.length < 2) return;

  // Map a temperature value to an SVG y coordinate
  function tempToY(t) {
    const clamped = Math.max(GAUGE_MIN, Math.min(GAUGE_MAX, t));
    const frac    = (clamped - GAUGE_MIN) / (GAUGE_MAX - GAUGE_MIN);
    return PADDING.top + plotH * (1 - frac);   // invert: high temp → low y
  }

  // Map a history index to an SVG x coordinate
  function idxToX(i) {
    return (i / (HISTORY_MAX - 1)) * W;
  }

  // Build the polyline points string
  const points = tempHistory
    .map((t, i) => `${idxToX(i).toFixed(1)},${tempToY(t).toFixed(1)}`)
    .join(" ");

  el.historyLine.setAttribute("points", points);

  // Build the filled polygon (close the shape at the bottom)
  const firstX = idxToX(0).toFixed(1);
  const lastX  = idxToX(tempHistory.length - 1).toFixed(1);
  const bottom = (H - PADDING.bottom).toFixed(1);
  el.historyFill.setAttribute(
    "points",
    `${firstX},${bottom} ${points} ${lastX},${bottom}`
  );

  // Position the threshold line
  const thresholdY = tempToY(TEMP_THRESHOLD).toFixed(1);
  el.thresholdLine.setAttribute("y1", thresholdY);
  el.thresholdLine.setAttribute("y2", thresholdY);
}

/* ── API polling ──────────────────────────────────────────────────────────── */

/**
 * refreshData — fetch /api/status and update all dashboard cards.
 * Called immediately and then every POLL_INTERVAL_MS milliseconds.
 */
async function refreshData() {
  try {
    const response = await fetch("/api/status");

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const data = await response.json();

    // Timestamp (same pattern as previous project)
    const now = new Date();
    el.lastUpdated.textContent = `Last updated: ${now.toLocaleTimeString("en-US", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    })}`;

    // Extract values from the API response
    const temp     = data?.environment?.temperature ?? null;
    const humidity = data?.environment?.humidity    ?? null;
    const isOn     = data?.led?.is_on              ?? null;
    const autoMode = data?.led?.auto_mode           ?? null;

    // Update each card
    updateTemperature(temp);
    updateHumidity(humidity);
    updateLed(isOn, autoMode);

    // Append to history and redraw chart
    if (temp !== null && Number.isFinite(temp)) {
      tempHistory.push(temp);
      if (tempHistory.length > HISTORY_MAX) tempHistory.shift();
      updateHistoryChart();
    }

    // Mark both indicators as connected
    setIndicator(el.indicatorSensor, "Sense HAT", true);
    setIndicator(el.indicatorLed,    "LED Driver", isOn !== null);

  } catch (error) {
    // Connection lost — mark both chips as disconnected (same as previous project)
    el.lastUpdated.textContent = "Last updated: connection error";
    setIndicator(el.indicatorSensor, "Sense HAT", false);
    setIndicator(el.indicatorLed,    "LED Driver", false);
    console.error("Dashboard fetch error:", error);
  }
}

/* ── Manual control buttons ───────────────────────────────────────────────── */

/**
 * sendCommand — POST to an /api/led/* endpoint and show feedback.
 * Called from onclick handlers on the control buttons in index.html.
 *
 * @param {string} endpoint  — e.g. "/api/led/on"
 * @param {object} [body={}] — optional JSON body, e.g. { active: true }
 */
async function sendCommand(endpoint, body = {}) {
  // Disable all buttons during the request to prevent double-sends
  document.querySelectorAll(".btn").forEach((b) => (b.disabled = true));
  el.controlsFeedback.textContent = "Sending…";
  setStatusClass(el.controlsFeedback, null);

  try {
    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    const data = await response.json();

    if (data.ok) {
      el.controlsFeedback.textContent = `✓ ${data.message}`;
      setStatusClass(el.controlsFeedback, "status-ok");
    } else {
      el.controlsFeedback.textContent = `✗ ${data.error}`;
      setStatusClass(el.controlsFeedback, "status-danger");
    }

    // Immediately refresh so the LED card reflects the new state
    await refreshData();

  } catch (err) {
    el.controlsFeedback.textContent = "✗ Command failed — check server";
    setStatusClass(el.controlsFeedback, "status-danger");
  } finally {
    // Re-enable buttons regardless of success/failure
    document.querySelectorAll(".btn").forEach((b) => (b.disabled = false));
  }
}

/* ── Boot ─────────────────────────────────────────────────────────────────── */

// Fetch once immediately so the dashboard is not blank on load
refreshData();

// Then poll every 3 seconds (same interval as the previous networking project)
setInterval(refreshData, POLL_INTERVAL_MS);
