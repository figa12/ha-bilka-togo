"""Bilka To Go: a household shopping list that feeds Bilka To Go orders."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.storage import Store

from .api import BilkaAuthError, BilkaClient, BilkaError
from .const import DOMAIN
from .shopping_list import ShoppingList

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.TODO]
STORAGE_VERSION = 1
SAVE_DELAY = 1

type BilkaConfigEntry = ConfigEntry[BilkaData]


@dataclass
class BilkaData:
    """What the integration keeps while it runs."""

    client: BilkaClient
    shopping_list: ShoppingList
    store: Store[dict[str, Any]]
    # Known items and previously chosen products, written by transfers (not built yet).
    # Kept as stored so nothing written later is lost by this version.
    memory: dict[str, Any] = field(default_factory=dict)

    @callback
    def save(self) -> None:
        """Save soon; changes made in quick succession are written once."""
        self.store.async_delay_save(self._as_data, SAVE_DELAY)

    async def async_save_now(self) -> None:
        """Write at once, so a reload never reads the file before a pending save lands."""
        await self.store.async_save(self._as_data())

    def _as_data(self) -> dict[str, Any]:
        return {"items": self.shopping_list.as_data(), "memory": self.memory}


def create_client(hass: HomeAssistant, email: str, password: str) -> BilkaClient:
    """A client on a session of its own.

    Bilka keeps the signed-in session in a cookie, so the client must not share Home
    Assistant's common session and its cookie jar.
    """
    return BilkaClient(async_create_clientsession(hass), email, password)


async def async_setup_entry(hass: HomeAssistant, entry: BilkaConfigEntry) -> bool:
    """Load the shopping list, and sign in to Bilka if it answers.

    The shopping list never depends on Bilka: adding items from the kitchen must keep working
    while Bilka is down or the password has changed. Bilka is only needed to transfer.
    """
    store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
    stored = await store.async_load() or {}
    client = create_client(hass, entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD])

    try:
        await client.account()
    except BilkaAuthError as err:
        _LOGGER.warning("Bilka refused the stored login, asking for it again: %s", err)
        entry.async_start_reauth(hass)
    except (BilkaError, aiohttp.ClientError, TimeoutError) as err:
        # The store is looked up again the first time Bilka is needed.
        _LOGGER.warning("Bilka To Go is unreachable, the shopping list works without it: %s", err)

    entry.runtime_data = BilkaData(
        client=client,
        shopping_list=ShoppingList.from_data(stored.get("items", [])),
        store=store,
        memory=stored.get("memory", {}),
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: BilkaConfigEntry) -> bool:
    """Unload a config entry, writing the shopping list first."""
    await entry.runtime_data.async_save_now()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: BilkaConfigEntry) -> None:
    """Delete the stored shopping list when the integration is removed."""
    await Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}").async_remove()
