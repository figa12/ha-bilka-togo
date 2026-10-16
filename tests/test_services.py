"""The transfer actions, through Home Assistant, with a stand-in for Bilka."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bilka_togo.api import (
    Account,
    Basket,
    BasketLine,
    BilkaAuthError,
    Multibuy,
    Product,
)
from custom_components.bilka_togo.const import DOMAIN
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

LIST = "todo.bilka_to_go_shopping_list"
PACKING = BasketLine("81474", "Pakkeservice", 1, 3900, None, True)


def product(pid, *, price, normal=None, organic=False, multibuy=None):
    return Product(
        id=pid, name=f"P{pid}", brand="", size="1 l", price=price, normal_price=normal or price,
        unit_price=price, unit_price_unit="L.", organic=organic, multibuy=multibuy,
        in_stock=True, image=None,
    )


class FakeBilka:
    """Holds a basket the way Bilka does: counts are set, the packing line always there."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.catalogue: dict[str, Product] = {}
        self.account = AsyncMock(return_value=Account("372513", "1652", "Bilka Skalborg"))
        self.fail: Exception | None = None

    async def basket(self) -> Basket:
        self._maybe_fail()
        groups = {pid: p.multibuy.group for pid, p in self.catalogue.items() if p.multibuy}
        lines = [PACKING] + [
            BasketLine(pid, f"P{pid}", n, 1000, groups.get(pid), False) for pid, n in self.counts.items()
        ]
        return Basket(tuple(lines), total=sum(self.counts.values()) * 1000, minimum_left=0)

    async def add(self, pid: str, count: int) -> int:
        self._maybe_fail()
        self.counts[pid] = self.counts.get(pid, 0) + count
        return self.counts[pid]

    async def products(self, ids: list[str]) -> list[Product]:
        return [self.catalogue[i] for i in ids if i in self.catalogue]

    async def search(self, query, *, limit=30, offers_only=False):
        self._maybe_fail()
        found = [p for p in self.catalogue.values() if query in p.name.lower() or query == "*"]
        return [p for p in found if p.price_cut or p.multibuy or not offers_only][:limit]

    async def empty_basket(self) -> None:
        self.counts.clear()

    def _maybe_fail(self):
        if self.fail:
            raise self.fail


@pytest.fixture
async def bilka(hass: HomeAssistant) -> FakeBilka:
    fake = FakeBilka()
    with patch("custom_components.bilka_togo.create_client", return_value=fake):
        entry = MockConfigEntry(domain=DOMAIN, unique_id="372513", data={CONF_EMAIL: "a@b.dk", CONF_PASSWORD: "x"})
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        yield fake


async def call(hass, action, **data):
    return await hass.services.async_call(DOMAIN, action, data, blocking=True, return_response=True)


async def add(hass, name, amount=None):
    data = {"entity_id": LIST, "item": name}
    if amount:
        data["description"] = amount
    await hass.services.async_call("todo", "add_item", data, blocking=True)


async def uid_of(hass, name):
    transfer = await call(hass, "get_transfer")
    return next(item["uid"] for item in transfer["items"] if item["name"] == name)


async def test_a_move_puts_the_line_in_the_basket_and_takes_the_item_off(hass, bilka) -> None:
    bilka.catalogue["19683"] = product("19683", price=1405, organic=True)
    await add(hass, "mælk", "2")
    await add(hass, "panodil")

    result = await call(hass, "move", item=await uid_of(hass, "mælk"), product_id="19683", count=6)

    assert result["count"] == 6
    assert result["basket"] == {"lines": 1, "units": 6, "total": 6000, "minimum_left": 0}
    assert hass.states.get(LIST).state == "1"  # only panodil is left
    assert (await call(hass, "known_items"))["items"] == ["mælk"]


async def test_a_move_increases_a_product_already_in_the_basket(hass, bilka) -> None:
    bilka.counts["19683"] = 2  # Pia put two in from the Bilka app
    await add(hass, "mælk")
    result = await call(hass, "move", item=await uid_of(hass, "mælk"), product_id="19683", count=6)
    assert result["count"] == 8


async def test_previously_chosen_come_back_in_preference_order(hass, bilka) -> None:
    bilka.catalogue.update(
        A=product("A", price=1405, organic=True),
        B=product("B", price=895, normal=1105),
        D=product("D", price=1260),
    )
    for pid in ("D", "A", "B"):
        await add(hass, "mælk")
        await call(hass, "move", item=await uid_of(hass, "mælk"), product_id=pid, count=3)

    await add(hass, "mælk", "4")
    [item] = (await call(hass, "get_transfer"))["items"]
    assert [p["id"] for p in item["previously_chosen"]] == ["B", "A", "D"]
    assert item["suggested_count"] == 4
    assert item["previously_chosen"][0]["last_count"] == 3


async def test_products_bilka_no_longer_sells_drop_out(hass, bilka) -> None:
    bilka.catalogue["A"] = product("A", price=1405)
    await add(hass, "mælk")
    await call(hass, "move", item=await uid_of(hass, "mælk"), product_id="A", count=1)
    del bilka.catalogue["A"]
    await add(hass, "mælk")
    [item] = (await call(hass, "get_transfer"))["items"]
    assert item["previously_chosen"] == []


async def test_forget_removes_a_product_from_previously_chosen(hass, bilka) -> None:
    bilka.catalogue.update(A=product("A", price=1), B=product("B", price=2))
    for pid in ("A", "B"):
        await add(hass, "mælk")
        await call(hass, "move", item=await uid_of(hass, "mælk"), product_id=pid, count=1)
    assert (await call(hass, "forget", item="Mælk", product_id="B"))["forgotten"] is True
    await add(hass, "mælk")
    [item] = (await call(hass, "get_transfer"))["items"]
    assert [p["id"] for p in item["previously_chosen"]] == ["A"]


async def test_search_reports_offers_and_multibuy_progress(hass, bilka) -> None:
    mix = Multibuy("2660", "Mix 5 for 300,00", 5, 30000)
    bilka.catalogue.update(
        k1=product("k1", price=7000, multibuy=mix),
        k2=product("k2", price=6900, normal=9900),
        k3=product("k3", price=5000, organic=True),
    )
    bilka.counts["k1"] = 2
    products = (await call(hass, "search", query="*", offers_only=True))["products"]
    by_id = {p["id"]: p for p in products}
    assert set(by_id) == {"k1", "k2"}
    assert by_id["k1"]["multibuy"]["in_basket"] == 2
    assert by_id["k1"]["price_cut"] is False
    assert by_id["k2"]["price_cut"] is True

    organic = (await call(hass, "search", query="*", organic_only=True))["products"]
    assert [p["id"] for p in organic] == ["k3"]


async def test_a_failed_move_leaves_the_item_on_the_list(hass, bilka) -> None:
    await add(hass, "mælk")
    uid = await uid_of(hass, "mælk")
    bilka.fail = TimeoutError()
    with pytest.raises(HomeAssistantError):
        await call(hass, "move", item=uid, product_id="19683", count=1)
    assert hass.states.get(LIST).state == "1"
    assert (await call(hass, "known_items"))["items"] == []


async def test_a_refused_login_during_a_transfer_asks_to_sign_in_again(hass, bilka) -> None:
    bilka.fail = BilkaAuthError("refused")
    with pytest.raises(HomeAssistantError):
        await call(hass, "get_transfer")
    [flow] = hass.config_entries.flow.async_progress()
    assert flow["context"]["source"] == "reauth"


async def test_moving_an_item_already_gone_is_refused(hass, bilka) -> None:
    with pytest.raises(ServiceValidationError):
        await call(hass, "move", item="nope", product_id="1", count=1)


async def test_empty_basket_keeps_the_packing_line(hass, bilka) -> None:
    bilka.counts.update({"1": 2, "2": 1})
    result = await call(hass, "empty_basket")
    assert result["basket"]["lines"] == 0


async def test_moves_survive_a_reload(hass, bilka) -> None:
    bilka.catalogue["A"] = product("A", price=1)
    await add(hass, "mælk")
    await call(hass, "move", item=await uid_of(hass, "mælk"), product_id="A", count=2)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    with patch("custom_components.bilka_togo.create_client", return_value=bilka):
        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
    assert (await call(hass, "known_items"))["items"] == ["mælk"]
