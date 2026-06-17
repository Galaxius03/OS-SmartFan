"""
led_controller.py — Controller class wrapping led.py.

Thin layer between led_server.py (Flask) and the low-level led.py module.
LED commands route through /dev/gpioled (kernel module), not RPi.GPIO.
"""

from __future__ import annotations

from Sensors.led import (
    get_env_data,
    get_led_state,
    set_auto_mode,
    start_env_monitoring,
    turn_led_off,
    turn_led_on,
)


class LedController:
    """
    High-level controller for the GPIO LED indicator.

    All LED commands are routed through /dev/gpioled — the character device
    created by led_driver.ko. The kernel module owns GPIO 24 and is the
    single point of hardware control.

    Example usage
    -------------
    >>> ctrl = LedController()
    >>> ctrl.start_auto()          # start Sense HAT monitoring
    >>> ctrl.get_state()
    {'is_on': False, 'auto_mode': True}
    >>> ctrl.turn_on()
    'LED turned on.'
    """

    def __init__(self, led_pin: int = 24) -> None:
        # led_pin kept for API compatibility; GPIO is managed by the kernel module
        self.led_pin = led_pin

    # ------------------------------------------------------------------
    # Manual control
    # ------------------------------------------------------------------

    def turn_on(self) -> str:
        """Turn LED on by writing 'ON' to /dev/gpioled."""
        return turn_led_on(self.led_pin)

    def turn_off(self) -> str:
        """Turn LED off by writing 'OFF' to /dev/gpioled."""
        return turn_led_off(self.led_pin)

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    def get_state(self) -> dict:
        """Return current LED state: {'is_on': bool, 'auto_mode': bool}."""
        return get_led_state(self.led_pin)

    def get_env(self) -> dict:
        """Return latest corrected Sense HAT readings: {'temperature', 'humidity'}."""
        return get_env_data()

    # ------------------------------------------------------------------
    # Auto-mode
    # ------------------------------------------------------------------

    def start_auto(self) -> None:
        """
        Start the Sense HAT background monitor and enable auto-mode.

        The monitor polls the sensor every 2 seconds and writes "ON"/"OFF"
        to /dev/gpioled automatically when the temperature or humidity
        crosses the threshold defined in led.py.
        """
        start_env_monitoring(auto_mode=True)

    def set_auto(self, active: bool) -> None:
        """Enable (True) or disable (False) automatic LED control."""
        set_auto_mode(active)
