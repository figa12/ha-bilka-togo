"""Bilka To Go: a household shopping list that feeds Bilka To Go orders."""

from __future__ import annotations

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import BilkaAuthError, BilkaClient, BilkaError

PLATFORMS: list[Platform] = []

type BilkaConfigEntry = ConfigEntry[BilkaClient]


def create_client(hass: HomeAssistant, email: str, password: str) -> BilkaClient:
    """A client on a session of its own.

    Bilka keeps the signed-in session in a cookie, so the client must not share Home
    Assistant's common session and its cookie jar.
    """
    return BilkaClient(async_create_clientsession(hass), email, password)


async def async_setup_entry(hass: HomeAssistant, entry: BilkaConfigEntry) -> bool:
    """Sign in and learn which store the account picks up from."""
    client = create_client(hass, entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD])
    try:
        await client.account()
    except BilkaAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except (BilkaError, aiohttp.ClientError, TimeoutError) as err:
        raise ConfigEntryNotReady(str(err)) from err

    entry.runtime_data = client
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: BilkaConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
