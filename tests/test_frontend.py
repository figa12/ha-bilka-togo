"""The cards are served by the integration and loaded on every dashboard."""

import pytest

from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.bilka_togo.const import DOMAIN


@pytest.mark.parametrize("card", ["bilka-shopping-list-card", "bilka-transfer-card"])
async def test_the_card_is_served_and_loaded(hass: HomeAssistant, hass_client, card) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    [url] = [u for u in hass.data[DATA_EXTRA_MODULE_URL].urls if f"/{card}.js" in u]
    assert "?v=" in url  # a content hash, so a changed card is fetched again

    response = await (await hass_client()).get(url)
    assert response.status == 200
    text = await response.text()
    assert f'customElements.define("{card}"' in text
    # Defined only once Home Assistant's own registry is in place; defined any earlier, the card
    # is invisible to Home Assistant and shows as "Configuration error".
    assert 'customElements.whenDefined("home-assistant")' in text
