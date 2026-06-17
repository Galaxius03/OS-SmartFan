"""
app.py — Laptop-side dashboard server for CSC1107 Project 10.

Serves the thermal monitoring web dashboard and proxies all API calls
to the Raspberry Pi LED server (PiServers/led_server.py) running on the Pi.

Architecture (matches previous networking project pattern):
  Browser  →  http://localhost:8080          →  app.py (laptop)
  laptop   →  http://<PI_IP>:5000/api/*     →  led_server.py (Pi)

The browser's JavaScript uses relative paths (/api/status etc.), so it
always calls this proxy server — never the Pi directly. This avoids CORS
issues and keeps the Pi IP in one place (PI_BASE_URL below).

Run:
  cd Dashboard
  pip3 install -r requirements.txt
  python app.py

Then open: http://localhost:8080

Requirements:
  - PiServers/led_server.py must be running on the Pi (port 5000)
  - led_driver.ko must be loaded on the Pi
  - Both devices must be on the same network
  - Optional: set PI_URL env var to override the default raspberrypi.local
    e.g. export PI_URL=http://192.168.1.100:5000
"""

import requests
from flask import Flask, jsonify, render_template, request

# ---------------------------------------------------------------------------
# Configuration
# PI_BASE_URL defaults to raspberrypi.local which works automatically on
# most networks without knowing the Pi's IP address.
#
# To override (e.g. Pi has a different hostname or static IP), set the
# PI_URL environment variable before running:
#
#   macOS/Linux:  export PI_URL=http://192.168.1.100:5000
#   Windows:      set PI_URL=http://192.168.1.100:5000
# ---------------------------------------------------------------------------
import os
PI_BASE_URL = os.getenv("PI_URL", "http://raspberrypi.local:5000")

TIMEOUT_S = 5   # seconds to wait for Pi response before timing out

# ---------------------------------------------------------------------------
# Flask app — serves templates/ and static/ relative to this file
# ---------------------------------------------------------------------------
app = Flask(__name__,
            template_folder="templates",
            static_folder="static")

# ---------------------------------------------------------------------------
# Proxy helpers
# ---------------------------------------------------------------------------

def proxy_get(path: str):
    """
    Forward a GET request to the Pi's API and return its JSON response.
    Returns 503 if the Pi is unreachable (e.g. not on the same network).
    """
    try:
        resp = requests.get(f"{PI_BASE_URL}{path}", timeout=TIMEOUT_S)
        return jsonify(resp.json()), resp.status_code
    except requests.exceptions.ConnectionError:
        return jsonify({
            "ok": False,
            "error": f"Cannot reach Pi at {PI_BASE_URL} — is led_server.py running?",
        }), 503
    except requests.exceptions.Timeout:
        return jsonify({"ok": False, "error": "Pi request timed out"}), 504


def proxy_post(path: str, json_body: dict = None):
    """
    Forward a POST request to the Pi's API and return its JSON response.
    Passes through any JSON body supplied by the browser.
    """
    try:
        resp = requests.post(
            f"{PI_BASE_URL}{path}",
            json=json_body,
            timeout=TIMEOUT_S,
        )
        return jsonify(resp.json()), resp.status_code
    except requests.exceptions.ConnectionError:
        return jsonify({
            "ok": False,
            "error": f"Cannot reach Pi at {PI_BASE_URL} — is led_server.py running?",
        }), 503
    except requests.exceptions.Timeout:
        return jsonify({"ok": False, "error": "Pi request timed out"}), 504

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def dashboard():
    """Serve the thermal monitoring dashboard HTML page."""
    return render_template("index.html")


@app.route("/api/status")
def status():
    """
    Proxy GET /api/status → Pi.
    Called every 3 seconds by the dashboard JavaScript (app.js).
    Returns LED state + Sense HAT temperature and humidity.
    """
    return proxy_get("/api/status")


@app.route("/api/led/on", methods=["POST"])
def led_on():
    """Proxy POST /api/led/on → Pi. Turns LED on, disables auto-mode."""
    return proxy_post("/api/led/on")


@app.route("/api/led/off", methods=["POST"])
def led_off():
    """Proxy POST /api/led/off → Pi. Turns LED off, disables auto-mode."""
    return proxy_post("/api/led/off")


@app.route("/api/led/auto", methods=["POST"])
def led_auto():
    """
    Proxy POST /api/led/auto → Pi.
    Body: {"active": true | false}
    Enables or disables temperature-based automatic LED control.
    """
    payload = request.get_json(silent=True) or {}
    return proxy_post("/api/led/auto", json_body=payload)

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 50)
    print("  Thermal Monitor Dashboard — CSC1107 Project 10")
    print("=" * 50)
    print(f"Pi API URL  : {PI_BASE_URL}")
    print(f"Dashboard   : http://localhost:8080")
    print(f"")
    print(f"If dashboard shows 'Cannot reach Pi', check:")
    print(f"  1. Pi hostname is 'raspberrypi' (or set PI_URL env var)")
    print(f"  2. led_server.py is running on the Pi (PiServers/)")
    print(f"  3. Both devices are on the same network")
    print("=" * 50)
    app.run(host="0.0.0.0", port=8080, debug=True)
