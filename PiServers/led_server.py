"""
led_server.py — Raspberry Pi Flask REST API server for CSC1107 Project 10.

API-only server. The web dashboard is served separately from a laptop by
dashboard_server.py, which proxies all API calls to this server.

This matches the architecture from the previous networking project:
  Pi runs the hardware servers → laptop runs the dashboard that calls them.

Endpoints:
  GET  /api/status   → current LED state + Sense HAT sensor readings
  POST /api/led/on   → manually turn LED on  (disables auto-mode)
  POST /api/led/off  → manually turn LED off (disables auto-mode)
  POST /api/led/auto → enable or disable auto-mode
                       body: {"active": true | false}

Run on Pi:
  python3 Sensors/led_server.py

Runs on port 5000. Must have led_driver.ko loaded first.
"""

from __future__ import annotations

import sys
from pathlib import Path

from flask import Flask, jsonify, request

# Ensure project root is on sys.path so Sensors package is importable
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from Sensors.led_controller import LedController


class LedApiServer:
    """
    Flask API server for the GPIO LED indicator.
    Serves JSON only — no HTML. The dashboard is served by dashboard_server.py
    running on the laptop.
    """

    def __init__(self) -> None:
        self.app = Flask(__name__)
        self.led_controller = LedController()

        # Sync state on startup — reset LED to off
        try:
            self.led_controller.turn_off()
        except Exception:
            pass    # /dev/gpioled may not exist yet, that's fine

        self.led_controller.start_auto()
        self._register_routes()

    def _register_routes(self) -> None:
        """Register all API URL rules."""
        self.app.add_url_rule(
            "/api/status",
            view_func=self.status,
            methods=["GET"],
        )
        self.app.add_url_rule(
            "/api/led/on",
            view_func=self.led_on,
            methods=["POST"],
        )
        self.app.add_url_rule(
            "/api/led/off",
            view_func=self.led_off,
            methods=["POST"],
        )
        self.app.add_url_rule(
            "/api/led/auto",
            view_func=self.led_auto,
            methods=["POST"],
        )

    @staticmethod
    def json_error(exc: Exception, status_code: int = 500):
        """Return a consistent JSON error response."""
        return jsonify({"ok": False, "error": str(exc)}), status_code

    def status(self):
        """
        GET /api/status
        Returns current LED state and latest Sense HAT sensor readings.
        Polled every 3 seconds by the dashboard JavaScript via the proxy.
        """
        try:
            return jsonify({
                "led": self.led_controller.get_state(),
                "environment": self.led_controller.get_env(),
            })
        except Exception as exc:
            return self.json_error(exc)

    def led_on(self):
        """
        POST /api/led/on
        Manually turn LED on. Disables auto-mode first so the sensor
        monitor does not immediately override the manual command.
        """
        self.led_controller.set_auto(False)
        try:
            return jsonify({
                "ok": True,
                "message": self.led_controller.turn_on(),
                "state": {"led": self.led_controller.get_state()},
            })
        except Exception as exc:
            return self.json_error(exc)

    def led_off(self):
        """
        POST /api/led/off
        Manually turn LED off. Disables auto-mode to keep it off.
        """
        self.led_controller.set_auto(False)
        try:
            return jsonify({
                "ok": True,
                "message": self.led_controller.turn_off(),
                "state": {"led": self.led_controller.get_state()},
            })
        except Exception as exc:
            return self.json_error(exc)

    def led_auto(self):
        """
        POST /api/led/auto
        Enable or disable automatic LED control based on sensor readings.
        Request body (JSON): {"active": true | false}
        """
        payload = request.get_json(silent=True) or {}
        active = payload.get("active")

        if not isinstance(active, bool):
            return jsonify({
                "ok": False,
                "error": "Missing boolean 'active' in JSON body.",
            }), 400

        try:
            self.led_controller.set_auto(active)
            mode_label = "enabled" if active else "disabled"
            return jsonify({
                "ok": True,
                "message": f"LED automation {mode_label}.",
                "state": {"led": self.led_controller.get_state()},
            })
        except Exception as exc:
            return self.json_error(exc)


# ---------------------------------------------------------------------------
# Application entry point
# ---------------------------------------------------------------------------

server = LedApiServer()
app = server.app      # expose for WSGI servers if needed

if __name__ == "__main__":
    print("=" * 45)
    print("  LED API Server — CSC1107 Project 10")
    print("=" * 45)
    print("Running on  : http://0.0.0.0:5000")
    print("Dashboard   : open dashboard_server.py on laptop")
    print("Prereq      : sudo insmod led_driver.ko")
    print("=" * 45)
    # use_reloader=False prevents a second process spawning a duplicate
    # Sense HAT monitor thread
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
