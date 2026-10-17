"""The actions behind a transfer, which the transfer card calls.

A transfer is a series of moves with no final confirmation (CONTEXT.md, ADR 0001):
- get_transfer: the basket summary, and each item with its previously chosen products in
  preference order.
- search: Bilka's range for something new, in Bilka's own order.
- move: one item becomes a basket line and leaves the shopping list, all at once.
- forget: take a product out of an item's previously chosen, or forget a known item whole.
- empty_basket: remove every product line, never the packing line.
- known_items: the names suggested while adding on the wall display.

Removing an item is the to-do list's own remove_item; it never touches Bilka.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
import homeassistant.helpers.config_validation as cv
from homeassistant.util import dt as dt_util

from .api import Basket, BilkaAuthError, BilkaError, Product
from .const import DOMAIN
from .transfer import preference_order, suggested_count

if TYPE_CHECKING:
    from . import BilkaConfigEntry, BilkaData

SEARCH_SCHEMA = vol.Schema(
    {
        vol.Required("query"): vol.All(cv.string, vol.Length(min=1)),
        vol.Optional("offers_only", default=False): cv.boolean,
        vol.Optional("organic_only", default=False): cv.boolean,
    }
)
MOVE_SCHEMA = vol.Schema(
    {
        vol.Required("item"): cv.string,
        vol.Required("product_id"): cv.string,
        vol.Required("count"): vol.All(vol.Coerce(int), vol.Range(min=1, max=99)),
    }
)
FORGET_SCHEMA = vol.Schema({vol.Required("item"): cv.string, vol.Optional("product_id"): cv.string})

# Search asks for more than it shows when filtering for organic here, since Bilka's own
# organic tag is unreliable and the filter has to read names too.
SEARCH_LIMIT = 30
ORGANIC_SEARCH_LIMIT = 100


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the transfer actions."""

    async def get_transfer(call: ServiceCall) -> ServiceResponse:
        entry = _entry(hass)
        data = entry.runtime_data
        items = data.shopping_list.items
        chosen = {item.uid: data.memory.previously_chosen(item.name) for item in items}
        ids = sorted({pid for products in chosen.values() for pid in products})
        async with _bilka(hass, entry):
            basket, products = await asyncio.gather(
                data.client.basket(), data.client.products(ids)
            )
        by_id = {product.id: product for product in products}
        return {
            "basket": _basket(basket),
            "items": [
                {
                    "uid": item.uid,
                    "name": item.name,
                    "amount": item.amount,
                    "suggested_count": suggested_count(item.amount),
                    # Products Bilka no longer sells are missing from by_id, so they drop out.
                    "previously_chosen": [
                        _product(product, basket, chosen[item.uid][product.id]["count"])
                        for product in preference_order(
                            [by_id[pid] for pid in chosen[item.uid] if pid in by_id]
                        )
                    ],
                }
                for item in items
            ],
        }

    async def search(call: ServiceCall) -> ServiceResponse:
        entry = _entry(hass)
        client = entry.runtime_data.client
        organic_only = call.data["organic_only"]
        async with _bilka(hass, entry):
            products, basket = await asyncio.gather(
                client.search(
                    call.data["query"],
                    limit=ORGANIC_SEARCH_LIMIT if organic_only else SEARCH_LIMIT,
                    offers_only=call.data["offers_only"],
                ),
                client.basket(),
            )
        if organic_only:
            products = [product for product in products if product.organic][:SEARCH_LIMIT]
        return {"products": [_product(product, basket) for product in products]}

    async def move(call: ServiceCall) -> ServiceResponse:
        entry = _entry(hass)
        data = entry.runtime_data
        async with data.basket_lock:
            if (item := data.shopping_list.get(call.data["item"])) is None:
                raise ServiceValidationError(
                    translation_domain=DOMAIN, translation_key="item_not_on_list"
                )
            async with _bilka(hass, entry):
                count = await data.client.add(call.data["product_id"], call.data["count"])
                basket = await data.client.basket()
            # Only once Bilka has the line does the item leave the list, so a failed move
            # leaves everything as it was.
            data.memory.record_move(
                item.name, call.data["product_id"], call.data["count"], dt_util.utcnow()
            )
            data.shopping_list.remove([item.uid])
            data.changed()
        return {"count": count, "basket": _basket(basket)}

    async def forget(call: ServiceCall) -> ServiceResponse:
        data = _entry(hass).runtime_data
        forgotten = data.memory.forget(call.data["item"], call.data.get("product_id"))
        if forgotten:
            data.changed()
        return {"forgotten": forgotten}

    async def empty_basket(call: ServiceCall) -> ServiceResponse:
        entry = _entry(hass)
        data = entry.runtime_data
        async with data.basket_lock, _bilka(hass, entry):
            await data.client.empty_basket()
            basket = await data.client.basket()
        return {"basket": _basket(basket)}

    async def known_items(call: ServiceCall) -> ServiceResponse:
        return {"items": _entry(hass).runtime_data.memory.known_items()}

    for name, handler, schema in (
        ("get_transfer", get_transfer, None),
        ("search", search, SEARCH_SCHEMA),
        ("move", move, MOVE_SCHEMA),
        ("forget", forget, FORGET_SCHEMA),
        ("empty_basket", empty_basket, None),
        ("known_items", known_items, None),
    ):
        hass.services.async_register(
            DOMAIN, name, handler, schema=schema, supports_response=SupportsResponse.ONLY
        )


def _entry(hass: HomeAssistant) -> BilkaConfigEntry:
    """The household's Bilka entry; there is one."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED:
            return entry
    raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_loaded")


@asynccontextmanager
async def _bilka(hass: HomeAssistant, entry: BilkaConfigEntry) -> AsyncIterator[None]:
    """Turn Bilka's failures into errors the card can show."""
    try:
        yield
    except BilkaAuthError as err:
        entry.async_start_reauth(hass)
        raise HomeAssistantError(translation_domain=DOMAIN, translation_key="auth_failed") from err
    except (BilkaError, aiohttp.ClientError, TimeoutError) as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="bilka_unreachable"
        ) from err


def _basket(basket: Basket) -> dict[str, Any]:
    """The summary bar: product lines only, never the packing line."""
    return {
        "lines": len(basket.products),
        "units": sum(line.count for line in basket.products),
        "total": basket.total,
        "minimum_left": basket.minimum_left,
    }


def _product(product: Product, basket: Basket, last_count: int | None = None) -> dict[str, Any]:
    """A product tile. Prices are in øre, as Bilka gives them."""
    multibuy = product.multibuy
    return {
        "id": product.id,
        "name": product.name,
        "brand": product.brand,
        "size": product.size,
        "price": product.price,
        "normal_price": product.normal_price,
        "price_cut": product.price_cut,
        "organic": product.organic,
        "unit_price": product.unit_price,
        "unit_price_unit": product.unit_price_unit,
        "image": product.image,
        "in_stock": product.in_stock,
        "in_basket": basket.count_of(product.id),
        "last_count": last_count,
        "multibuy": None
        if multibuy is None
        else {
            "description": multibuy.description,
            "units": multibuy.units,
            "total_price": multibuy.total_price,
            "in_basket": basket.multibuy_count(multibuy.group),
        },
    }
