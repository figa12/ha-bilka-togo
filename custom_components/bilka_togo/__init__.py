"""Bilka To Go: a household shopping list that feeds Bilka To Go orders."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
import hashlib
import logging
from pathlib import Path
from typing import Any

import aiohttp

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType
import homeassistant.helpers.config_validation as cv

from .api import BilkaAuthError, BilkaClient, BilkaError
from .const import DOMAIN
from .services import async_setup_services
from .shopping_list import ShoppingList
from .transfer import Memory

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.TODO]
CARDS = Path(__file__).parent / "frontend"
CARDS_URL = f"/{DOMAIN}/frontend"
STORAGE_VERSION = 1
SAVE_DELAY = 1

type BilkaConfigEntry = ConfigEntry[BilkaData]


@dataclass
class BilkaData:
    """What the integration keeps while it runs."""

    client: BilkaClient
    shopping_list: ShoppingList
    store: Store[dict[str, Any]]
    # Known items and previously chosen products, as stored; `memory` edits it in place.
    stored_memory: dict[str, Any] = field(default_factory=dict)
    # One basket change at a time: adding reads the count before setting it.
    basket_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _listeners: list[Callable[[], None]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.memory = Memory(self.stored_memory)

    @callback
    def changed(self) -> None:
        """Save soon and tell the shopping list entity, after any change."""
        self.store.async_delay_save(self._as_data, SAVE_DELAY)
        for listener in list(self._listeners):
            listener()

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Be told about changes; returns the function that stops it."""
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    async def async_save_now(self) -> None:
        """Write at once, so a reload never reads the file before a pending save lands."""
        await self.store.async_save(self._as_data())

    def _as_data(self) -> dict[str, Any]:
        return {"items": self.shopping_list.as_data(), "memory": self.stored_memory}


CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the actions, and serve the cards so no dashboard resource is needed."""
    async_setup_services(hass)
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARDS_URL, str(CARDS), cache_headers=False)]
    )
    for card in await hass.async_add_executor_job(_card_versions):
        add_extra_js_url(hass, card)
    return True


def _card_versions() -> list[str]:
    """Each card's URL with a hash of its content, so browsers fetch it again when it changes."""
    return [
        f"{CARDS_URL}/{card.name}?v={hashlib.sha256(card.read_bytes()).hexdigest()[:10]}"
        for card in sorted(CARDS.glob("*.js"))
    ]


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
        stored_memory=stored.get("memory", {}),
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
