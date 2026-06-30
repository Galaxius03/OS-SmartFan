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

    def __init__(self, led_pin: int = 24) -> None:
        # led_pin kept for API compatibility; GPIO is managed by the kernel module
        self.led_pin = led_pin

    # Manual mode
    def turn_on(self) -> str:
        # Turn LED ON by wrting ON to /dev/gpioled
        return turn_led_on(self.led_pin)

    def turn_off(self) -> str:
        # Turn LED off by writing OFF to /dev/gpioled
        return turn_led_off(self.led_pin)

    # State queries
    def get_state(self) -> dict:
        # Returns current LED state in boolean form for is_on and auto_mode
        return get_led_state(self.led_pin)

    def get_env(self) -> dict:
        # Returns latest corrected Sense HAT readings for temperature only
        return get_env_data()

    # Automatic mode (sensing mode)
    def start_auto(self) -> None:
        start_env_monitoring(auto_mode=True)

    def set_auto(self, active: bool) -> None:
        # Enables / disables automatic LED control
        set_auto_mode(active)
