"""Config flow for Fröling Connect."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import FroelingAuthError, FroelingConnectClient
from .const import DOMAIN, LOGGER

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class FroelingConnectConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Fröling Connect."""

    VERSION = 1

    async def _validate(self, username: str, password: str) -> tuple[str | None, int | None]:
        """Try to log in. Returns (error, user_id)."""
        client = FroelingConnectClient(async_get_clientsession(self.hass), username, password)
        try:
            await client.login()
        except FroelingAuthError:
            return "invalid_auth", None
        except Exception:
            LOGGER.exception("Unexpected error validating Fröling Connect credentials")
            return "unknown", None
        return None, client.user_id

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            error, user_id = await self._validate(user_input[CONF_USERNAME], user_input[CONF_PASSWORD])
            if error is None:
                await self.async_set_unique_id(str(user_id))
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=user_input[CONF_USERNAME], data=user_input)
            errors["base"] = error

        return self.async_show_form(step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors)

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        reauth_entry = self._get_reauth_entry()
        if user_input is not None:
            error, _ = await self._validate(reauth_entry.data[CONF_USERNAME], user_input[CONF_PASSWORD])
            if error is None:
                return self.async_update_reload_and_abort(
                    reauth_entry, data={**reauth_entry.data, CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            errors=errors,
            description_placeholders={"username": reauth_entry.data[CONF_USERNAME]},
        )
