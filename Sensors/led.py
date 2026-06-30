"""
led.py — Core LED control module for CSC1107 Project 10 (LED variant).

Architecture
------------
Two responsibilities:

  1. READ ambient temperature from the Sense HAT sensor, apply a CPU-heat
     correction, and write the result to /tmp/sense_temp so that
     led_control.c uses the same reading as this Python layer.

  2. CONTROL the physical LED by writing "ON" or "OFF" to /dev/gpioled —
     the character device created by led_driver.ko. The kernel module
     owns GPIO 24 via direct BCM2711 register access.

Temperature only
----------------
Humidity is intentionally excluded. The Sense HAT humidity sensor is
located close to the Pi CPU and produces unreliable readings (often
above 100% RH) due to CPU heat interference. LED control is based
solely on the corrected ambient temperature reading.

State sync
----------
LED state is always read directly from /dev/gpioled (kernel module)
rather than an in-memory shadow. This prevents stale state bugs where
the dashboard shows ON even though the physical LED is OFF.

Sense HAT temperature correction
---------------------------------
    cpu_temp  = /sys/class/thermal/thermal_zone0/temp / 1000  (degrees C)
    corrected = raw_temp - (cpu_temp - raw_temp) / 5.4
"""

from __future__ import annotations

import threading
import time

try:
    from sense_hat import SenseHat
except ImportError:
    SenseHat = None

# ---------------------------------------------------------------------------
# Paths and thresholds
# ---------------------------------------------------------------------------
DEVICE_PATH: str     = "/dev/gpioled"     # Kernel character device
SENSE_TEMP_PATH: str = "/tmp/sense_temp"  # Shared file read by led_control.c

TEMP_THRESHOLD: float = 29.0   # degrees C — LED turns ON above this value

# ---------------------------------------------------------------------------
# Module-level state — all mutations guarded by _lock
# ---------------------------------------------------------------------------
_lock: threading.RLock = threading.RLock()
_led_state: dict        = {"is_on": False}
_auto_mode_active: bool = False
_env_data: dict         = {"temperature": 0.0}   # humidity removed
_monitor_thread: threading.Thread | None = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_cpu_temp() -> float:
    """Read CPU die temperature from the Linux thermal interface (degrees C)."""
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return float(f.read().strip()) / 1000.0
    except OSError:
        return 0.0


def _corrected_temp(raw: float) -> float:
    """
    Apply CPU heat bias correction to the raw Sense HAT temperature.

    Without this the sensor reads 5-15 degrees C too high because it
    is physically close to the Raspberry Pi CPU.
    """
    cpu = _get_cpu_temp()
    if cpu == 0.0:
        return raw
    return raw - (cpu - raw) / 5.4


def _read_kernel_state() -> bool:
    """
    Read the actual LED state directly from /dev/gpioled (kernel module).

    This is the ground truth — avoids stale in-memory state bugs where
    the dashboard shows ON even though the physical LED is OFF. This can
    happen when the kernel module is reloaded or when led_control.c sends
    commands independently of this Python layer.

    Returns True if kernel reports LED:ON, False otherwise.
    Falls back to in-memory state if the device cannot be read.
    """
    try:
        with open(DEVICE_PATH, "r") as f:
            return f.read().strip() == "LED:ON"
    except Exception:
        return _led_state.get("is_on", False)


def _write_device(command: str) -> None:
    """
    Write "ON" or "OFF" to /dev/gpioled.

    Crosses the user/kernel boundary and invokes dev_write() in
    led_driver.c, which writes to the BCM2711 GPIO registers via
    ioremap to drive GPIO 24 HIGH or LOW.
    """
    with open(DEVICE_PATH, "w") as f:
        f.write(command)


def _env_monitor_loop() -> None:
    """
    Daemon thread: polls Sense HAT temperature every 2 seconds.

    On each cycle:
      - Reads and corrects the Sense HAT temperature (humidity skipped).
      - Updates _env_data for the /api/status endpoint.
      - Writes corrected temperature to /tmp/sense_temp for led_control.c.
      - If auto-mode is active, reads actual kernel state and sends
        ON/OFF to /dev/gpioled based on temperature threshold only.
    """
    global _env_data

    if SenseHat is None:
        print("[led] WARNING: sense_hat library not found — auto-mode disabled.")
        return

    sense = SenseHat()

    while True:
        try:
            raw_temp  = sense.get_temperature()
            corrected = _corrected_temp(raw_temp)

            # Update shared env data — temperature only
            _env_data["temperature"] = corrected

            # Write corrected temperature to shared file for led_control.c
            try:
                with open(SENSE_TEMP_PATH, "w") as f:
                    f.write(f"{corrected:.2f}\n")
            except OSError:
                pass

            with _lock:
                if _auto_mode_active:
                    # LED on/off based on temperature threshold only
                    should_be_on: bool = corrected > TEMP_THRESHOLD

                    # Read ground truth from kernel — not in-memory shadow
                    currently_on: bool = _read_kernel_state()
                    _led_state["is_on"] = currently_on  # keep in sync

                    if should_be_on and not currently_on:
                        turn_led_on()
                    elif (not should_be_on) and currently_on:
                        turn_led_off()

        except Exception as exc:
            print(f"[led] Sensor read error: {exc}")

        time.sleep(2.0)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def turn_led_on(led_pin: int = 24) -> str:
    """
    Turn the LED on by writing "ON" to /dev/gpioled.
    The kernel module drives GPIO 24 HIGH via BCM2711 register access.
    Thread-safe.
    """
    with _lock:
        _write_device("ON")
        _led_state["is_on"] = True
    return "LED turned on."


def turn_led_off(led_pin: int = 24) -> str:
    """
    Turn the LED off by writing "OFF" to /dev/gpioled.
    The kernel module drives GPIO 24 LOW.
    Thread-safe.
    """
    with _lock:
        _write_device("OFF")
        _led_state["is_on"] = False
    return "LED turned off."


def get_led_state(led_pin: int = 24) -> dict:
    """
    Return current LED state by reading directly from /dev/gpioled.

    Uses the kernel module as source of truth — fixes the dashboard
    showing stale state after module reloads or external state changes.

    Returns {'is_on': bool, 'auto_mode': bool}
    """
    with _lock:
        is_on = _read_kernel_state()
        _led_state["is_on"] = is_on
        return {"is_on": is_on, "auto_mode": _auto_mode_active}


def _write_mode_file(active: bool) -> None:
    """Write auto-mode state to /tmp/led_auto_mode so led_control.c can read it."""
    try:
        with open("/tmp/led_auto_mode", "w") as f:
            f.write("1" if active else "0")
    except OSError:
        pass


def start_env_monitoring(auto_mode: bool = True) -> None:
    """
    Start the Sense HAT temperature monitor thread (if not already running).

    Parameters
    ----------
    auto_mode:
        If True, the monitor automatically controls the LED based on
        the corrected temperature threshold.
    """
    global _monitor_thread, _auto_mode_active

    with _lock:
        _auto_mode_active = auto_mode
        _write_mode_file(auto_mode)
        if _monitor_thread is None or not _monitor_thread.is_alive():
            _monitor_thread = threading.Thread(
                target=_env_monitor_loop,
                daemon=True,
            )
            _monitor_thread.start()


def set_auto_mode(active: bool) -> None:
    """
    Enable or disable automatic temperature-based LED control.

    Parameters
    ----------
    active:
        True  → monitor thread controls LED based on temperature.
        False → manual mode; LED only changes on explicit on/off calls.
    """
    global _auto_mode_active
    with _lock:
        _auto_mode_active = active
        _write_mode_file(active)


def get_env_data() -> dict:
    """
    Return the most recent corrected Sense HAT temperature reading.

    Returns {'temperature': float}
    Value is 0.0 until the first sensor read completes.
    """
    return _env_data.copy()