"""
led.py — Core LED control module for CSC1107 Project 10 (LED variant).

Architecture
------------
Two responsibilities:

  1. READ ambient temperature and humidity from the Sense HAT sensor,
     apply a CPU-heat correction, and write the result to /tmp/sense_temp
     so that led_control.c (the user-space C program) uses the same
     ambient reading as this Python layer.

  2. CONTROL the physical LED by writing "ON" or "OFF" to /dev/gpioled —
     the character device created by led_driver.ko. The kernel module
     owns GPIO 24 exclusively; this module must NOT use RPi.GPIO to drive
     that pin directly.

GPIO ownership note
-------------------
led_driver.ko calls gpio_request(24, "led_gpio") on insmod, giving the
kernel module exclusive ownership of BCM GPIO 24. Any RPi.GPIO.output(24,...)
call while the module is loaded will conflict with the driver. All LED
commands in this file therefore go through open("/dev/gpioled") + write().

Sense HAT temperature correction
---------------------------------
The Sense HAT sits above the Raspberry Pi CPU, so its raw reading is
typically 5–15 °C above true ambient. Correction formula:

    cpu_temp  = /sys/class/thermal/thermal_zone0/temp ÷ 1000  (°C)
    corrected = raw_temp − (cpu_temp − raw_temp) / 5.4

The corrected value is what gets compared against TEMP_THRESHOLD and
written to /tmp/sense_temp.
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
DEVICE_PATH: str      = "/dev/gpioled"     # Kernel character device
SENSE_TEMP_PATH: str  = "/tmp/sense_temp"  # Shared file read by led_control.c

TEMP_THRESHOLD: float     = 29.0   # °C  — LED turns ON above this value
HUMIDITY_THRESHOLD: float = 95.0   # %RH — LED also turns ON above this value

# ---------------------------------------------------------------------------
# Module-level state — all mutations guarded by _lock
# ---------------------------------------------------------------------------
_lock: threading.RLock = threading.RLock()
_led_state: dict        = {"is_on": False}
_auto_mode_active: bool = False
_env_data: dict         = {"temperature": 0.0, "humidity": 0.0}
_monitor_thread: threading.Thread | None = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_cpu_temp() -> float:
    """Read CPU die temperature from the Linux thermal interface (°C)."""
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return float(f.read().strip()) / 1000.0
    except OSError:
        return 0.0


def _corrected_temp(raw: float) -> float:
    """
    Apply CPU heat bias correction to the raw Sense HAT temperature.

    Without this, the sensor reads 5–15 °C too high because it is physically
    close to the Raspberry Pi CPU. The corrected value is a close
    approximation of true ambient temperature.
    """
    cpu = _get_cpu_temp()
    if cpu == 0.0:
        return raw          # No CPU data — use raw reading as fallback
    return raw - (cpu - raw) / 5.4


def _write_device(command: str) -> None:
    """
    Write a command ("ON" or "OFF") to /dev/gpioled.

    This open()+write() sequence crosses the user/kernel boundary and
    invokes dev_write() in led_driver.c, which then calls gpio_set_value()
    to physically drive GPIO 24 HIGH or LOW.

    Raises OSError if the device file is not accessible (module not loaded).
    """
    with open(DEVICE_PATH, "w") as f:
        f.write(command)


def _env_monitor_loop() -> None:
    """
    Daemon thread: polls the Sense HAT every 2 seconds.

    On each cycle:
      - Reads raw temperature and humidity from the Sense HAT.
      - Applies CPU-heat correction to the temperature.
      - Updates _env_data so get_env_data() returns fresh values.
      - Writes corrected temperature to /tmp/sense_temp for led_control.c.
      - If auto_mode is active, writes "ON"/"OFF" to /dev/gpioled as needed.
    """
    global _env_data

    if SenseHat is None:
        print("[led] WARNING: sense_hat library not found — auto-mode disabled.")
        return

    sense = SenseHat()

    while True:
        try:
            raw_temp  = sense.get_temperature()
            humidity  = sense.get_humidity()
            corrected = _corrected_temp(raw_temp)

            # Update shared env data (plain dict assignments are atomic in CPython)
            _env_data["temperature"] = corrected
            _env_data["humidity"]    = humidity

            # Write corrected temperature to the shared file.
            # led_control.c reads this file to get the ambient reading so that
            # the C program and the Python layer use the same temperature source.
            try:
                with open(SENSE_TEMP_PATH, "w") as f:
                    f.write(f"{corrected:.2f}\n")
            except OSError:
                pass    # Non-fatal: C program will retry on next cycle

            # Auto-mode: decide whether LED should be on or off
            with _lock:
                if _auto_mode_active:
                    should_be_on: bool = (
                        corrected > TEMP_THRESHOLD
                        or humidity > HUMIDITY_THRESHOLD
                    )
                    currently_on: bool = _led_state.get("is_on", False)

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
    Turn the LED on.

    Writes "ON" to /dev/gpioled. The kernel module (led_driver.ko) receives
    this via dev_write() and drives GPIO 24 HIGH. Does NOT use RPi.GPIO
    directly — the kernel module owns GPIO 24.

    Thread-safe.
    """
    with _lock:
        _write_device("ON")
        _led_state["is_on"] = True
    return "LED turned on."


def turn_led_off(led_pin: int = 24) -> str:
    """
    Turn the LED off.

    Writes "OFF" to /dev/gpioled. The kernel module drives GPIO 24 LOW.

    Thread-safe.
    """
    with _lock:
        _write_device("OFF")
        _led_state["is_on"] = False
    return "LED turned off."


def get_led_state(led_pin: int = 24) -> dict:
    """
    Return the current in-memory LED state without touching hardware.

    Returns
    -------
    dict
        ``{'is_on': bool, 'auto_mode': bool}``
    """
    with _lock:
        state = dict(_led_state)
        state["auto_mode"] = _auto_mode_active
        return state


def start_env_monitoring(auto_mode: bool = True) -> None:
    """
    Start the Sense HAT background monitor thread (if not already running).

    Parameters
    ----------
    auto_mode:
        If True, the monitor thread will automatically write "ON"/"OFF" to
        /dev/gpioled based on sensor readings. Can be changed later with
        set_auto_mode().
    """
    global _monitor_thread, _auto_mode_active

    with _lock:
        _auto_mode_active = auto_mode
        if _monitor_thread is None or not _monitor_thread.is_alive():
            _monitor_thread = threading.Thread(
                target=_env_monitor_loop,
                daemon=True,    # exits automatically when main program ends
            )
            _monitor_thread.start()


def set_auto_mode(active: bool) -> None:
    """
    Enable or disable automatic LED control.

    Parameters
    ----------
    active:
        True  → monitor thread controls LED based on Sense HAT readings.
        False → manual mode; LED only changes via explicit turn_on/off calls.
    """
    global _auto_mode_active
    with _lock:
        _auto_mode_active = active


def get_env_data() -> dict:
    """
    Return the most recent corrected Sense HAT readings.

    Returns
    -------
    dict
        ``{'temperature': float, 'humidity': float}``
        Values are 0.0 until the first sensor read completes.
    """
    return _env_data.copy()
