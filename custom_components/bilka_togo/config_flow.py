"""The setup screen: sign in with the household's Bilka account."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from . import create_client
from .api import Account, BilkaAuthError, BilkaError, BilkaNoPickupStore
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

EMAIL = TextSelector(TextSelectorConfig(type=TextSelectorType.EMAIL, autocomplete="email"))
PASSWORD = TextSelector(
    TextSelectorConfig(type=TextSelectorType.PASSWORD, autocomplete="current-password")
)


class BilkaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Sign in once; the account's own pickup store decides where prices come from."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the Bilka login."""
        errors: dict[str, str] = {}
        if user_input is not None:
            account, errors = await self._sign_in(
                user_input[CONF_EMAIL], user_input[CONF_PASSWORD]
            )
            if account:
                await self.async_set_unique_id(account.user_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Bilka To Go ({account.store_name})", data=user_input
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {vol.Required(CONF_EMAIL): EMAIL, vol.Required(CONF_PASSWORD): PASSWORD}
                ),
                user_input,
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Bilka refused the stored password."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the password again, for the same account."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            account, errors = await self._sign_in(
                entry.data[CONF_EMAIL], user_input[CONF_PASSWORD]
            )
            if account:
                await self.async_set_unique_id(account.user_id)
                self._abort_if_unique_id_mismatch(reason="wrong_account")
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): PASSWORD}),
            description_placeholders={"email": entry.data[CONF_EMAIL]},
            errors=errors,
        )

    async def _sign_in(
        self, email: str, password: str
    ) -> tuple[Account | None, dict[str, str]]:
        client = create_client(self.hass, email, password)
        try:
            return await client.account(), {}
        except BilkaAuthError:
            return None, {"base": "invalid_auth"}
        except BilkaNoPickupStore:
            return None, {"base": "no_pickup_store"}
        except BilkaError as err:
            _LOGGER.warning("Bilka answered unexpectedly: %s", err)
            return None, {"base": "cannot_connect"}
        except (aiohttp.ClientError, TimeoutError):
            return None, {"base": "cannot_connect"}
