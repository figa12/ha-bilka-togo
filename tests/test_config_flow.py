"""Tests for the setup screen and for setting up the integration."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bilka_togo.api import (
    Account,
    BilkaAuthError,
    BilkaError,
    BilkaNoPickupStore,
)
from custom_components.bilka_togo.const import DOMAIN
from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

LOGIN = {CONF_EMAIL: "hjem@example.dk", CONF_PASSWORD: "hemmelig"}
ACCOUNT = Account(user_id="372513", store_id="1652", store_name="Bilka Skalborg")


def bilka(account=ACCOUNT, error=None):
    """Patch the client both the flow and setup create, answering account() as given."""
    client = AsyncMock()
    client.account.side_effect = error
    client.account.return_value = account
    return client


@pytest.fixture
def client():
    fake = bilka()
    with (
        patch("custom_components.bilka_togo.config_flow.create_client", return_value=fake),
        patch("custom_components.bilka_togo.create_client", return_value=fake),
    ):
        yield fake


async def test_sign_in_creates_an_entry_named_after_the_store(hass: HomeAssistant, client) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(result["flow_id"], LOGIN)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Bilka To Go (Bilka Skalborg)"
    assert result["data"] == LOGIN
    assert result["result"].unique_id == "372513"


@pytest.mark.parametrize(
    ("error", "shown"),
    [
        (BilkaAuthError("refused"), "invalid_auth"),
        (BilkaNoPickupStore("none"), "no_pickup_store"),
        (BilkaError("odd answer"), "cannot_connect"),
        (TimeoutError(), "cannot_connect"),
    ],
)
async def test_a_failed_sign_in_shows_why_and_can_be_retried(
    hass: HomeAssistant, client, error, shown
) -> None:
    client.account.side_effect = error
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], LOGIN)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": shown}

    client.account.side_effect = None
    result = await hass.config_entries.flow.async_configure(result["flow_id"], LOGIN)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_the_same_account_cannot_be_added_twice(hass: HomeAssistant, client) -> None:
    MockConfigEntry(domain=DOMAIN, unique_id="372513", data=LOGIN).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], LOGIN)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_setup_learns_the_store_and_unloads(hass: HomeAssistant, client) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id="372513", data=LOGIN)
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.client is client

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_a_reauth_updates_only_the_password(hass: HomeAssistant, client) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id="372513", data=LOGIN)
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "ny-hemmelig"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data == {CONF_EMAIL: "hjem@example.dk", CONF_PASSWORD: "ny-hemmelig"}


async def test_reauth_refuses_a_different_account(hass: HomeAssistant, client) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id="372513", data=LOGIN)
    entry.add_to_hass(hass)
    client.account.return_value = Account(user_id="999", store_id="1652", store_name="Bilka Skalborg")

    result = await entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "andens"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_account"
    assert entry.data[CONF_PASSWORD] == "hemmelig"
