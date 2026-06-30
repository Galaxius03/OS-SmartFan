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
 *   updateLed()         — dot colour, state label, auto-mode badge
 *   updateHistoryChart()— SVG polyline chart for last 20 readings
 *   sendCommand()       — POSTs to /api/led/* for manual control buttons
 *   setIndicator()      — updates the topbar connection chip
 *
 * Note: Humidity has been removed. The Sense HAT humidity sensor produces
 * unreliable readings (>100% RH) due to CPU heat proximity. LED control
 * is based solely on corrected ambient temperature.
 */

"use strict";

/* ── Constants ────────────────────────────────────────────────────────────── */

// Polling rate of API
const POLL_INTERVAL_MS = 3000;

//Temperature gauge range for led.py
const GAUGE_MIN = 20;
const GAUGE_MAX = 50;

// Temperature threshold for LED control in Celsius to light up
const TEMP_THRESHOLD = 29;

// Max no. of data points stored in the history chart, older points are dropped
const HISTORY_MAX = 20;

// Element references 
const el = {
  lastUpdated:     document.getElementById("last-updated"),
  indicatorSensor: document.getElementById("indicator-sensor"),
  indicatorLed:    document.getElementById("indicator-led"),

  // Temperature card
  gaugeArc:        document.getElementById("gauge-arc"),
  gaugeLabel:      document.getElementById("gauge-label"),
  tempValue:       document.getElementById("temp-value"),
  tempStatus:      document.getElementById("temp-status"),

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

// Array to store past temperature readings for history chart
const tempHistory = [];

// Helper functions

// removes all existing status classes and adds new one if provided
function setStatusClass(element, level) {
  if (!element) return;
  element.classList.remove("status-ok", "status-warn", "status-danger");
  if (level) element.classList.add(level);
}

// updates topbar connection indicator
function setIndicator(element, label, isConnected) {
  if (!element) return;
  element.textContent = `${label}: ${isConnected ? "Connected" : "Disconnected"}`;
  setStatusClass(element, isConnected ? "status-ok" : "status-danger");
}

// Temperature gauge arc geometry display on dashboard
/**
 * updateGaugeArc — draws the coloured semicircle arc proportional to temperature.
 *
 * Gauge geometry:
 *   Centre (cx, cy) = (100, 100), radius r = 80
 *   Start point     = (20, 100)  → 9 o'clock (coldest, 20°C)
 *   End point       = (180, 100) → 3 o'clock (hottest, 50°C)
 *   Arc sweeps clockwise through the top as temperature rises.
 *
 * @param {number} temp — corrected temperature in °C
 */
function updateGaugeArc(temp) {
  const cx = 100, cy = 100, r = 80;

  const pct = Math.max(0, Math.min(1, (temp - GAUGE_MIN) / (GAUGE_MAX - GAUGE_MIN)));
  const angleRad = Math.PI * (1 - pct);
  const ex = cx + r * Math.cos(angleRad);
  const ey = cy - r * Math.sin(angleRad);

  let color;
  if (temp >= TEMP_THRESHOLD + 10) {
    color = "var(--danger)";
  } else if (temp >= TEMP_THRESHOLD) {
    color = "var(--warn)";
  } else {
    color = "var(--ok)";
  }

  if (pct <= 0) {
    el.gaugeArc.setAttribute("d", "");
  } else {
    el.gaugeArc.setAttribute(
      "d",
      `M 20 100 A ${r} ${r} 0 0 1 ${ex.toFixed(2)} ${ey.toFixed(2)}`
    );
  }

  el.gaugeArc.setAttribute("stroke", color);
  el.gaugeLabel.textContent = temp.toFixed(1);
  el.gaugeLabel.setAttribute("fill", color);
}


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
 * updateLed — refresh the LED status card.
 * @param {boolean|null} isOn     — true if LED is on
 * @param {boolean|null} autoMode — true if auto-mode is active
 */
function updateLed(isOn, autoMode) {
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
    ? "Auto-mode: enabled (temperature-controlled)"
    : "Auto-mode: disabled (manual override)";
}

/* ── Temperature history chart ────────────────────────────────────────────── */

/**
 * updateHistoryChart — redraws the SVG polyline from tempHistory[].
 */
function updateHistoryChart() {
  const W = 600, H = 160;
  const PADDING = { top: 10, bottom: 10 };
  const plotH = H - PADDING.top - PADDING.bottom;

  if (tempHistory.length < 2) return;

  function tempToY(t) {
    const clamped = Math.max(GAUGE_MIN, Math.min(GAUGE_MAX, t));
    const frac    = (clamped - GAUGE_MIN) / (GAUGE_MAX - GAUGE_MIN);
    return PADDING.top + plotH * (1 - frac);
  }

  function idxToX(i) {
    return (i / (HISTORY_MAX - 1)) * W;
  }

  const points = tempHistory
    .map((t, i) => `${idxToX(i).toFixed(1)},${tempToY(t).toFixed(1)}`)
    .join(" ");

  el.historyLine.setAttribute("points", points);

  const firstX = idxToX(0).toFixed(1);
  const lastX  = idxToX(tempHistory.length - 1).toFixed(1);
  const bottom = (H - PADDING.bottom).toFixed(1);
  el.historyFill.setAttribute(
    "points",
    `${firstX},${bottom} ${points} ${lastX},${bottom}`
  );

  const thresholdY = tempToY(TEMP_THRESHOLD).toFixed(1);
  el.thresholdLine.setAttribute("y1", thresholdY);
  el.thresholdLine.setAttribute("y2", thresholdY);
}

/* ── API polling ──────────────────────────────────────────────────────────── */

/**
 * refreshData — fetch /api/status and update all dashboard cards.
 * Called immediately on load then every POLL_INTERVAL_MS milliseconds.
 */
async function refreshData() {
  try {
    const response = await fetch("/api/status");

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const data = await response.json();

    const now = new Date();
    el.lastUpdated.textContent = `Last updated: ${now.toLocaleTimeString("en-US", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    })}`;

    // Extract values — temperature only, humidity removed
    const temp     = data?.environment?.temperature ?? null;
    const isOn     = data?.led?.is_on              ?? null;
    const autoMode = data?.led?.auto_mode           ?? null;

    // Update cards
    updateTemperature(temp);
    updateLed(isOn, autoMode);

    // Append to history and redraw chart
    if (temp !== null && Number.isFinite(temp)) {
      tempHistory.push(temp);
      if (tempHistory.length > HISTORY_MAX) tempHistory.shift();
      updateHistoryChart();
    }

    // Update topbar indicators
    setIndicator(el.indicatorSensor, "Sense HAT", temp !== null);
    setIndicator(el.indicatorLed,    "LED Driver", isOn !== null);

  } catch (error) {
    el.lastUpdated.textContent = "Last updated: connection error";
    setIndicator(el.indicatorSensor, "Sense HAT", false);
    setIndicator(el.indicatorLed,    "LED Driver", false);
    console.error("Dashboard fetch error:", error);
  }
}

/* ── Manual control buttons ───────────────────────────────────────────────── */

/**
 * sendCommand — POST to an /api/led/* endpoint and show feedback.
 * @param {string} endpoint  — e.g. "/api/led/on"
 * @param {object} [body={}] — optional JSON body
 */
async function sendCommand(endpoint, body = {}) {
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

    await refreshData();

  } catch (err) {
    el.controlsFeedback.textContent = "✗ Command failed — check server";
    setStatusClass(el.controlsFeedback, "status-danger");
  } finally {
    document.querySelectorAll(".btn").forEach((b) => (b.disabled = false));
  }
}

/* ── Boot ─────────────────────────────────────────────────────────────────── */

refreshData();
setInterval(refreshData, POLL_INTERVAL_MS);