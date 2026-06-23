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
     owns GPIO 24 exclusively via direct BCM2711 register access.

State sync
----------
LED state is read directly from /dev/gpioled (the kernel module) rather
than from an in-memory shadow variable. This prevents stale state bugs
where the dashboard shows ON even though the physical LED is OFF (which
happens when the kernel module is reloaded or led_control.c changes the
state independently of this Python layer).

Sense HAT temperature correction
---------------------------------
The Sense HAT sits above the Raspberry Pi CPU, so its raw reading is
typically 5-15 degrees C above true ambient. Correction formula:

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
DEVICE_PATH: str      = "/dev/gpioled"     # Kernel character device
SENSE_TEMP_PATH: str  = "/tmp/sense_temp"  # Shared file read by led_control.c

TEMP_THRESHOLD: float     = 29.0   # degrees C — LED turns ON above this
HUMIDITY_THRESHOLD: float = 95.0   # %RH      — LED also turns ON above this

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

    This is the ground truth — it avoids stale in-memory state bugs where
    the dashboard shows ON even though the physical LED is OFF. This can
    happen when the kernel module is reloaded, or when led_control.c sends
    commands independently of this Python layer.

    Returns True if kernel reports LED:ON, False if LED:OFF or on any error.
    Falls back to in-memory state if the device file cannot be read.
    """
    try:
        with open(DEVICE_PATH, "r") as f:
            content = f.read().strip()
            return content == "LED:ON"
    except Exception:
        # Device not available — fall back to last known in-memory state
        return _led_state.get("is_on", False)


def _write_device(command: str) -> None:
    """
    Write a command ("ON" or "OFF") to /dev/gpioled.

    This open()+write() sequence crosses the user/kernel boundary and
    invokes dev_write() in led_driver.c, which then writes directly to
    the BCM2711 GPIO registers via ioremap to drive GPIO 24 HIGH or LOW.

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
      - If auto_mode is active, reads actual kernel state (not in-memory
        shadow) and writes ON/OFF to /dev/gpioled as needed.
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

            _env_data["temperature"] = corrected
            _env_data["humidity"]    = humidity

            # Write corrected temperature to shared file for led_control.c
            try:
                with open(SENSE_TEMP_PATH, "w") as f:
                    f.write(f"{corrected:.2f}\n")
            except OSError:
                pass

            with _lock:
                if _auto_mode_active:
                    should_be_on: bool = (
                        corrected > TEMP_THRESHOLD
                        or humidity > HUMIDITY_THRESHOLD
                    )

                    # Read ground truth from kernel — not in-memory shadow.
                    # This ensures auto-mode reacts to the real physical state
                    # even if led_control.c or a module reload changed it.
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

    The kernel module (led_driver.ko) receives this via dev_write() and
    writes directly to the BCM2711 GPIO registers to drive GPIO 24 HIGH.
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
    Return the current LED state by reading directly from /dev/gpioled.

    Uses the kernel module as the source of truth rather than the
    in-memory shadow — this fixes the dashboard showing stale state
    after module reloads or external state changes from led_control.c.

    Returns
    -------
    dict
        {'is_on': bool, 'auto_mode': bool}
    """
    with _lock:
        # Read ground truth from kernel module
        is_on = _read_kernel_state()
        # Keep in-memory state in sync
        _led_state["is_on"] = is_on
        return {"is_on": is_on, "auto_mode": _auto_mode_active}


def start_env_monitoring(auto_mode: bool = True) -> None:
    """
    Start the Sense HAT background monitor thread (if not already running).

    Parameters
    ----------
    auto_mode:
        If True, the monitor thread will automatically write ON/OFF to
        /dev/gpioled based on sensor readings.
    """
    global _monitor_thread, _auto_mode_active

    with _lock:
        _auto_mode_active = auto_mode
        if _monitor_thread is None or not _monitor_thread.is_alive():
            _monitor_thread = threading.Thread(
                target=_env_monitor_loop,
                daemon=True,
            )
            _monitor_thread.start()


def set_auto_mode(active: bool) -> None:
    """
    Enable or disable automatic LED control.

    Parameters
    ----------
    active:
        True  → monitor thread controls LED based on Sense HAT readings.
        False → manual mode; LED only changes via explicit on/off calls.
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
        {'temperature': float, 'humidity': float}
        Values are 0.0 until the first sensor read completes.
    """
    return _env_data.copy()