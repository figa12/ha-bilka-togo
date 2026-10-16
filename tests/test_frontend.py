"""The cards are served by the integration and loaded on every dashboard."""

from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.bilka_togo.const import DOMAIN


async def test_the_card_is_served_and_loaded(hass: HomeAssistant, hass_client) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    [url] = [u for u in hass.data[DATA_EXTRA_MODULE_URL].urls if "bilka-shopping-list-card" in u]
    assert "?v=" in url  # a content hash, so a changed card is fetched again

    response = await (await hass_client()).get(url)
    assert response.status == 200
    assert "customElements.define(\"bilka-shopping-list-card\"" in await response.text()
