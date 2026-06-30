from __future__ import annotations
import sys
from pathlib import Path
from flask import Flask, jsonify, request


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from Sensors.led_controller import LedController


class LedApiServer:
    def __init__(self) -> None:
        self.app = Flask(__name__)
        self.led_controller = LedController()

        # sync state on startup and set state to OFF
        try:
            self.led_controller.turn_off()
        except Exception:
            pass   

        self.led_controller.start_auto()
        self._register_routes()

    def _register_routes(self) -> None:
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
        return jsonify({"ok": False, "error": str(exc)}), status_code

     ## GET /api/status which returns current LED state and latest SenseHAT readings, polled every 3 seconds
    def status(self):
        try:
            return jsonify({
                "led": self.led_controller.get_state(),
                "environment": self.led_controller.get_env(),
            })
        except Exception as exc:
            return self.json_error(exc)

    ## POST /api/led/on
    ## Manually turns LED on, while disabling automode at the same time
    ## prevents sensor monitor from overriding the manual mode
    def led_on(self): 
        self.led_controller.set_auto(False)
        try:
            return jsonify({
                "ok": True,
                "message": self.led_controller.turn_on(),
                "state": {"led": self.led_controller.get_state()},
            })
        except Exception as exc:
            return self.json_error(exc)

    ## POIST /api/led/off
    ## Manually turns LED off, disables automode at the same time
    def led_off(self):
        self.led_controller.set_auto(False)
        try:
            return jsonify({
                "ok": True,
                "message": self.led_controller.turn_off(),
                "state": {"led": self.led_controller.get_state()},
            })
        except Exception as exc:
            return self.json_error(exc)

    ## POST /api/led/auto
    ## Enables/disables auto LED control based on sensor readings
    def led_auto(self):
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

server = LedApiServer()
app = server.app      

if __name__ == "__main__":
    print("=" * 45)
    print("  LED API Server — CSC1107 Project 10")
    print("=" * 45)
    print("Running on  : http://0.0.0.0:5000")
    print("Dashboard   : open dashboard_server.py on laptop")
    print("Prereq      : sudo insmod led_driver.ko")
    print("=" * 45)
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
