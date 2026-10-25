"""Config flow for Bull IoT: username/password form with live validation."""

from __future__ import annotations

from typing import Any

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback

from .client import AuthenticationError, BullCloudClient
from .const import (
    CONF_FAMILY_IDS,
    CONF_MQTT_ENABLED,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    DEFAULT_MQTT_ENABLED,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    LEGACY_CONF_FAMILY_IDS,
    mask_account,
)


class CannotConnect(Exception):
    """Error to indicate we cannot connect."""


async def _validate_credentials(
    hass, username: str, password: str
) -> tuple[str, list[dict]]:
    """Validate credentials and return account identity plus family metadata."""
    client = BullCloudClient()
    try:
        await hass.async_add_executor_job(client.login, username, password)
        families = await hass.async_add_executor_job(client.get_families)
        return str(client.openid), families
    except AuthenticationError:
        raise
    except Exception as err:
        raise CannotConnect from err
    finally:
        await hass.async_add_executor_job(client.close)


class BullConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Bull IoT."""

    VERSION = 2

    def __init__(self) -> None:
        self._pending_data: dict[str, Any] = {}
        self._families: list[dict] = []

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return BullOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Handle the initial step: ask for credentials."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                openid, self._families = await _validate_credentials(
                    self.hass, user_input[CONF_USERNAME], user_input[CONF_PASSWORD]
                )
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"

            if not errors:
                await self.async_set_unique_id(openid)
                self._abort_if_unique_id_configured()
                self._pending_data = dict(user_input)
                return await self.async_step_select_family()

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

    async def async_step_select_family(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Select only the MosHome families this entry should import."""
        errors: dict[str, str] = {}
        if user_input is not None:
            selected = [int(value) for value in user_input[CONF_FAMILY_IDS]]
            if selected:
                data = {
                    **self._pending_data,
                    CONF_FAMILY_IDS: selected,
                    CONF_MQTT_ENABLED: user_input[CONF_MQTT_ENABLED],
                }
                return self.async_create_entry(
                    title=mask_account(self._pending_data[CONF_USERNAME]),
                    data=data,
                )
            errors["base"] = "no_family_selected"

        options = {
            str(family["familyId"]): (
                f"{family.get('familyName') or family['familyId']} "
                f"({family.get('deviceCount', 0)} 台设备)"
            )
            for family in self._families
        }
        return self.async_show_form(
            step_id="select_family",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_FAMILY_IDS): cv.multi_select(options),
                    vol.Required(CONF_MQTT_ENABLED, default=DEFAULT_MQTT_ENABLED): bool,
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Handle re-authentication when stored credentials stop working."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Confirm reauth dialog: re-enter credentials."""
        reauth_entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                openid, _families = await _validate_credentials(
                    self.hass, user_input[CONF_USERNAME], user_input[CONF_PASSWORD]
                )
                if reauth_entry.unique_id and openid != reauth_entry.unique_id:
                    errors["base"] = "wrong_account"
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"

            if not errors:
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data_updates=user_input,
                    reason="reauth_successful",
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_USERNAME,
                        default=reauth_entry.data.get(CONF_USERNAME, ""),
                    ): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
            description_placeholders={
                "username": reauth_entry.data.get(CONF_USERNAME, "")
            },
        )


class BullOptionsFlow(OptionsFlow):
    """Options flow: polling interval and MQTT push toggle."""

    def __init__(self) -> None:
        self._families: list[dict] = []

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input[CONF_FAMILY_IDS]:
                errors["base"] = "no_family_selected"
            else:
                user_input[CONF_FAMILY_IDS] = [
                    int(value) for value in user_input[CONF_FAMILY_IDS]
                ]
                return self.async_create_entry(title="", data=user_input)

        if not self._families:
            try:
                openid, self._families = await _validate_credentials(
                    self.hass,
                    self.config_entry.data[CONF_USERNAME],
                    self.config_entry.data[CONF_PASSWORD],
                )
                if (
                    self.config_entry.unique_id
                    and openid != self.config_entry.unique_id
                ):
                    errors["base"] = "wrong_account"
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"

        family_options = {
            str(family["familyId"]): (
                f"{family.get('familyName') or family['familyId']} "
                f"({family.get('deviceCount', 0)} 台设备)"
            )
            for family in self._families
        }
        current_family_ids = self.config_entry.options.get(
            CONF_FAMILY_IDS,
            self.config_entry.data.get(
                CONF_FAMILY_IDS,
                self.config_entry.data.get(LEGACY_CONF_FAMILY_IDS, []),
            ),
        )
        if not family_options:
            family_options = {
                str(family_id): str(family_id) for family_id in current_family_ids
            }

        opts = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_FAMILY_IDS,
                    default=[str(value) for value in current_family_ids],
                ): cv.multi_select(family_options),
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=opts.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): vol.All(vol.Coerce(int), vol.Range(min=15, max=3600)),
                vol.Required(
                    CONF_MQTT_ENABLED,
                    default=opts.get(
                        CONF_MQTT_ENABLED,
                        self.config_entry.data.get(
                            CONF_MQTT_ENABLED, DEFAULT_MQTT_ENABLED
                        ),
                    ),
                ): bool,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
