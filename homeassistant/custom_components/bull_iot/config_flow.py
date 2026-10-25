"""Config flow for Bull IoT: username/password form with live validation."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, OptionsFlow, ConfigFlow
from homeassistant.core import callback

from .client import AuthenticationError, BullCloudClient
from .const import (
    CONF_MQTT_ENABLED,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    DEFAULT_MQTT_ENABLED,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)


class CannotConnect(Exception):
    """Error to indicate we cannot connect."""


async def _validate_credentials(hass, username: str, password: str) -> None:
    """Try a real login; raises AuthenticationError on bad credentials."""
    client = BullCloudClient()
    try:
        await hass.async_add_executor_job(client.login, username, password)
    except AuthenticationError:
        raise
    except Exception as err:  # noqa: BLE001
        raise CannotConnect from err
    finally:
        await hass.async_add_executor_job(client.close)


class BullConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Bull IoT."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return BullOptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Handle the initial step: ask for credentials."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await _validate_credentials(
                    self.hass, user_input[CONF_USERNAME], user_input[CONF_PASSWORD]
                )
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"

            if not errors:
                await self.async_set_unique_id(user_input[CONF_USERNAME])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input[CONF_USERNAME], data=user_input
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Handle re-authentication when stored credentials stop working."""
        self.reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Confirm reauth dialog: re-enter credentials."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await _validate_credentials(
                    self.hass, user_input[CONF_USERNAME], user_input[CONF_PASSWORD]
                )
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"

            if not errors:
                return self.async_update_reload_and_abort(
                    self.reauth_entry,
                    data=user_input,
                    reason="reauth_successful",
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_USERNAME,
                        default=self.reauth_entry.data.get(CONF_USERNAME, ""),
                    ): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
            description_placeholders={
                "username": self.reauth_entry.data.get(CONF_USERNAME, "")
            },
        )


class BullOptionsFlow(OptionsFlow):
    """Options flow: polling interval and MQTT push toggle."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        opts = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=opts.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): vol.All(vol.Coerce(int), vol.Range(min=15, max=3600)),
                vol.Required(
                    CONF_MQTT_ENABLED,
                    default=opts.get(CONF_MQTT_ENABLED, DEFAULT_MQTT_ENABLED),
                ): bool,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
