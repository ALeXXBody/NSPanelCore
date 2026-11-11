"""Config flow for NSPanel Core.

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
        manager = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id)
        current = manager.config.settings if manager else None

        if user_input is not None:
            if manager:
                manager.apply_settings(user_input)
            return self.async_create_entry(title="", data={})

        schema = vol.Schema(
            {
                vol.Required(
                    "manager_address",
                    default=current.manager_address if current else "core",
                ): str,
                vol.Required(
                    "color_temp_min",
                    default=current.color_temp_min if current else 2700,
                ): int,
                vol.Required(
                    "color_temp_max",
                    default=current.color_temp_max if current else 6500,
                ): int,
                vol.Required(
                    "date_format",
                    default=current.date_format if current else "%d/%m",
                ): str,
                vol.Optional(
                    "location_latitude",
                    default=current.location_latitude if current else "",
                ): str,
                vol.Optional(
                    "location_longitude",
                    default=current.location_longitude if current else "",
                ): str,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
