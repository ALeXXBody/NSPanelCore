"""Config flow for NSPanel Core (parity port of the v1 flow).

The integration uses Home Assistant's own MQTT broker connection — there is
no connection setup needed. The flow simply creates the entry; rooms, lights,
panels and settings are managed from the integration's options afterwards.
"""

from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN, DEFAULT_NAME

STEP_USER_SCHEMA = vol.Schema({vol.Required("name", default=DEFAULT_NAME): str})


class NSPanelCoreConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the initial setup flow."""

    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            # Only one instance of the hub makes sense.
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=user_input.get("name", DEFAULT_NAME), data={})

        return self.async_show_form(step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return NSPanelCoreOptionsFlow(config_entry)


class NSPanelCoreOptionsFlow(config_entries.OptionsFlow):
    """Options: global settings."""

    def __init__(self, config_entry) -> None:
        self.entry = config_entry

    async def async_step_init(self, user_input: dict | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        data = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id) or {}
        core = data.get("core")
        current = core.config.settings if core else None

        if user_input is not None:
            if core:
                # Live-update the fields the v2 core consumes directly.
                core.config.manager_address = user_input.get("manager_address", core.config.manager_address)
                core.config.manager_port = user_input.get("manager_port", core.config.manager_port)
                # Persist the rest as settings (consumed as features port).
                from .models import Settings

                settings_fields = {f for f in Settings.__dataclass_fields__}
                core.config.settings = Settings(
                    **{k: v for k, v in user_input.items() if k in settings_fields}
                )
            clean = {k: v for k, v in (user_input or {}).items()}
            self.hass.config_entries.async_update_entry(self.entry, options=clean)
            return self.async_create_entry(title="", data=clean)

        def d(name, fallback):
            if current is not None:
                return getattr(current, name, fallback)
            return (self.entry.options or {}).get(name, fallback)

        schema = vol.Schema(
            {
                vol.Required("manager_address", default=d("manager_address", "core")): str,
                vol.Required("manager_port", default=d("manager_port", 8000)): int,
                vol.Required("color_temp_min", default=d("color_temp_min", 2700)): int,
                vol.Required("color_temp_max", default=d("color_temp_max", 6500)): int,
                vol.Required("date_format", default=d("date_format", "%d/%m")): str,
                vol.Optional("location_latitude", default=d("location_latitude", "")): str,
                vol.Optional("location_longitude", default=d("location_longitude", "")): str,
                vol.Optional("weather_entity", default=d("weather_entity", "")): str,
                vol.Optional("weather_update_interval", default=d("weather_update_interval", 30)): int,
                vol.Optional("precipitation_format", default=d("precipitation_format", "mm")): str,
                vol.Optional("wind_speed_format", default=d("wind_speed_format", "kmh")): str,
                vol.Optional("use_fahrenheit", default=d("use_fahrenheit", False)): bool,
                vol.Optional("reverse_color_temp", default=d("reverse_color_temp", False)): bool,
                vol.Optional("clock_us_style", default=d("clock_us_style", False)): bool,
                vol.Optional("optimistic_mode", default=d("optimistic_mode", False)): bool,
                vol.Optional("turn_on_behaviour", default=d("turn_on_behaviour", "color_temp")): str,
                vol.Optional("light_turn_on_brightness", default=d("light_turn_on_brightness", 0)): int,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
