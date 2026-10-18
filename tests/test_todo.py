"""The shopping list through Home Assistant's to-do services, as Assist and cards use it."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
import voluptuous as vol
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bilka_togo.api import Account, BilkaAuthError
from custom_components.bilka_togo.const import DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er

LOGIN = {CONF_EMAIL: "hjem@example.dk", CONF_PASSWORD: "hemmelig"}


@pytest.fixture
def client():
    fake = AsyncMock()
    fake.account.return_value = Account("100001", "1000", "Bilka Eksempelby")
    with (
        patch("custom_components.bilka_togo.create_client", return_value=fake),
        patch("custom_components.bilka_togo.config_flow.create_client", return_value=fake),
    ):
        yield fake


@pytest.fixture
async def entry(hass: HomeAssistant, client) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, unique_id="100001", data=LOGIN)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


@pytest.fixture
def entity_id(hass: HomeAssistant, entry) -> str:
    return er.async_get(hass).async_get_entity_id("todo", DOMAIN, f"{entry.entry_id}_shopping_list")


async def add(hass, entity_id, item, description=None):
    data = {"entity_id": entity_id, "item": item}
    if description is not None:
        data["description"] = description
    await hass.services.async_call("todo", "add_item", data, blocking=True)


async def items(hass, entity_id):
    result = await hass.services.async_call(
        "todo", "get_items", {"entity_id": entity_id}, blocking=True, return_response=True
    )
    return [(i["summary"], i.get("description")) for i in result[entity_id]["items"]]


async def test_named_shopping_list_and_counts_items(hass: HomeAssistant, entity_id) -> None:
    assert entity_id == "todo.bilka_to_go_shopping_list"
    await add(hass, entity_id, "mælk")
    await add(hass, entity_id, "brød")
    assert hass.states.get(entity_id).state == "2"


async def test_adding_the_same_item_joins_amounts(hass: HomeAssistant, entity_id) -> None:
    """However an item arrives (card, Assist, app), the list never holds it twice."""
    await add(hass, entity_id, "mælk", "1 l")
    await add(hass, entity_id, "Mælk ", "2")
    await add(hass, entity_id, "MÆLK")
    assert await items(hass, entity_id) == [("mælk", "1 l, 2")]


async def test_ticking_off_removes_the_item(hass: HomeAssistant, entity_id) -> None:
    """There is no "bought" state: a ticked item is simply no longer needed."""
    await add(hass, entity_id, "panodil")
    await add(hass, entity_id, "mælk")
    await hass.services.async_call(
        "todo", "update_item", {"entity_id": entity_id, "item": "panodil", "status": "completed"}, blocking=True
    )
    assert await items(hass, entity_id) == [("mælk", None)]


async def test_remove_item(hass: HomeAssistant, entity_id) -> None:
    await add(hass, entity_id, "panodil")
    await hass.services.async_call("todo", "remove_item", {"entity_id": entity_id, "item": "panodil"}, blocking=True)
    assert await items(hass, entity_id) == []


async def test_renaming_onto_another_item_merges(hass: HomeAssistant, entity_id) -> None:
    await add(hass, entity_id, "mælk", "1 l")
    await add(hass, entity_id, "letmælk", "2")
    await hass.services.async_call(
        "todo", "update_item", {"entity_id": entity_id, "item": "letmælk", "rename": "mælk"}, blocking=True
    )
    assert await items(hass, entity_id) == [("mælk", "1 l, 2")]


@pytest.mark.parametrize("name", ["", "   "])
async def test_an_empty_name_is_refused(hass: HomeAssistant, entity_id, name) -> None:
    """Home Assistant's own schema refuses some blanks first; the list refuses the rest."""
    with pytest.raises((ServiceValidationError, vol.Invalid)):
        await add(hass, entity_id, name)
    assert await items(hass, entity_id) == []


async def test_the_list_survives_a_reload_straight_after_a_change(
    hass: HomeAssistant, entry, entity_id
) -> None:
    """A reload (as after re-entering the password) must not lose an item added just before."""
    await add(hass, entity_id, "mælk", "2")
    await add(hass, entity_id, "brød")
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert await items(hass, entity_id) == [("mælk", "2"), ("brød", None)]


async def test_the_list_works_while_bilka_is_down(hass: HomeAssistant, client) -> None:
    """Adding from the kitchen must not depend on Bilka answering."""
    client.account.side_effect = TimeoutError()
    entry = MockConfigEntry(domain=DOMAIN, unique_id="100001", data=LOGIN)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.LOADED
    await add(hass, "todo.bilka_to_go_shopping_list", "mælk")
    assert await items(hass, "todo.bilka_to_go_shopping_list") == [("mælk", None)]


async def test_a_refused_password_keeps_the_list_and_asks_again(hass: HomeAssistant, client) -> None:
    client.account.side_effect = BilkaAuthError("refused")
    entry = MockConfigEntry(domain=DOMAIN, unique_id="100001", data=LOGIN)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    [flow] = hass.config_entries.flow.async_progress()
    assert flow["context"]["source"] == "reauth"
