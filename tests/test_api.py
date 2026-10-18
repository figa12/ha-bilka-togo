"""Tests for the Bilka client, against recorded shapes of Bilka's answers."""

from __future__ import annotations

import json

import pytest

from custom_components.bilka_togo.api import (
    BilkaAuthError,
    BilkaClient,
    BilkaError,
    BilkaNoPickupStore,
)

from .fake_session import FakeSession

STORE = "1000"
SIGNED_IN = {"uid": 100001}
ANONYMOUS = {"uid": -1}


def hit(object_id, name, *, price, store=None, brand="", properties=()):
    """A search hit as Bilka's index returns it."""
    return {
        "objectID": object_id,
        "name": name,
        "brand": brand,
        "price": price,
        "netcontent": "1 l",
        "properties": list(properties),
        "images": [f"https://img/{object_id}"],
        "storeData": {STORE: {"price": price, "inStock": True, **(store or {})}},
    }


def search_answer(*hits):
    return {"results": [{"hits": list(hits)}]}


def cart(*lines, uid=100001):
    """A Cart answer holding the packing line and the given (id, count, multipromo) products."""
    products = [
        {
            "orderlines": [
                {
                    "quantity": count,
                    "unitprice": 1105,
                    "product": {"objectID": int(pid), "name": f"P{pid}", "multipromo": promo},
                }
            ]
        }
        for pid, count, promo in lines
    ]
    packing = {
        "orderlines": [
            {"quantity": 1, "unitprice": 3900, "product": {"objectID": 81474, "name": "Pakkeservice"}}
        ]
    }
    return {
        "uid": uid,
        "lines": [
            {"headline": "Services", "lines": [packing]},
            {"headline": "Mejeri & køl", "lines": products},
        ],
        "stat": {"prod_price": 1105 * sum(count for _, count, _ in lines), "minimum_left": 0},
    }


def sign_in(session, *, refused=False):
    session.answer("POST", "accounts.login$", {"errorCode": 0, "sessionInfo": {"cookieValue": "lt"}})
    session.answer("POST", "accounts.getJWT$", {"errorCode": 0, "id_token": "jwt"})
    session.answer("POST", "/auth/LoginJWT$", ANONYMOUS if refused else SIGNED_IN, status=401 if refused else 200)


@pytest.fixture
def session():
    return FakeSession()


@pytest.fixture
def client(session):
    return BilkaClient(session, "a@b.dk", "secret", STORE)


async def test_search_prices_for_the_store_not_globally(client, session):
    """A price cut only one store has must be seen: the global price says nothing."""
    session.answer("POST", "algolia", search_answer(hit("171945", "Kyllingebrystfilet", price=19900, store={"price": 16900})))
    [product] = await client.search("kyllingebryst")
    assert (product.price, product.normal_price, product.price_cut) == (16900, 19900, True)


async def test_search_skips_products_the_store_has_no_data_for(client, session):
    elsewhere = hit("1", "Elsewhere", price=100)
    elsewhere["storeData"] = {"1651": {"price": 100}}
    session.answer("POST", "algolia", search_answer(elsewhere))
    assert await client.search("x") == []


@pytest.mark.parametrize(
    ("name", "brand", "properties", "organic"),
    [
        ("Letmælk 1,5% fedt øko", "Arla ØKO", ["Økologisk"], True),
        ("Hamburgerryg i skiver øko", "Friland Økologi", [], True),  # Bilka's tag is missing
        ("Kakaomælk", "Friland Økologi", [], True),
        ("Letmælk 1,5% fedt", "Salling", [], False),
        ("Økonomipakke", "Salling", [], False),
    ],
)
async def test_organic(client, session, name, brand, properties, organic):
    session.answer("POST", "algolia", search_answer(hit("1", name, price=100, brand=brand, properties=properties)))
    [product] = await client.search(name)
    assert product.organic is organic


async def test_multibuy_is_read_but_is_not_a_price_cut(client, session):
    mix = hit(
        "166142",
        "Hakket oksekød",
        price=7000,
        store={"multipromo": "2660", "offerDescription": "Mix 5 for 300,00", "multiPromoPrice": "30000"},
    )
    session.answer("POST", "algolia", search_answer(mix))
    [product] = await client.search("kød")
    assert product.price_cut is False
    assert (product.multibuy.group, product.multibuy.units, product.multibuy.total_price) == ("2660", 5, 30000)


async def test_search_names_the_fields_and_filters_to_the_store(client, session):
    session.answer("POST", "algolia", search_answer())
    await client.search("mælk", offers_only=True)
    [call] = session.to("algolia")
    params = json.loads(call.data)["requests"][0]["params"]
    assert "storeData" in params  # without named fields the index returns only ids
    assert "isInAssortmentIn%3A1000" in params
    assert "isInOffer%3A1000" in params


async def test_products_by_id_asks_only_for_those_ids(client, session):
    session.answer("POST", "algolia", search_answer(hit("84120", "Letmælk", price=1105)))
    [product] = await client.products(["84120", "1"])
    assert product.id == "84120"
    params = json.loads(session.to("algolia")[0].data)["requests"][0]["params"]
    assert "objectID%3A84120%20OR%20objectID%3A1" in params


async def test_basket_separates_service_lines(client, session):
    sign_in(session)
    session.answer("GET", "/shop/v6/Cart$", cart(("84120", 2, 0), ("166142", 1, 2660)))
    basket = await client.basket()
    assert [line.name for line in basket.products] == ["P84120", "P166142"]
    assert basket.count_of("81474") == 0  # packing is never an item
    assert basket.count_of("84120") == 2
    assert basket.multibuy_count("2660") == 1


async def test_add_increases_the_existing_count(client, session):
    """ChangeLineCount sets a count, so adding 6 to 2 has to send 8."""
    sign_in(session)
    session.answer("GET", "/shop/v6/Cart$", cart(("84120", 2, 0)))
    session.answer("GET", "ChangeLineCount$", SIGNED_IN)
    assert await client.add("84120", 6) == 8
    [change] = session.to("ChangeLineCount")
    assert change.params["count"] == "8"


async def test_jwt_header_name_stays_lowercase(client, session):
    sign_in(session)
    session.answer("GET", "/shop/v6/Cart$", cart())
    await client.basket()
    assert "jwt_token" in session.to("/shop/v6/Cart")[0].headers
    assert "jwt_token" in session.to("LoginJWT")[0].headers


async def test_signs_in_only_once_for_several_calls(client, session):
    sign_in(session)
    session.answer("GET", "/shop/v6/Cart$", cart(), repeat=True)
    await client.basket()
    await client.basket()
    assert len(session.to("LoginJWT")) == 1


async def test_anonymous_answer_triggers_one_fresh_sign_in(client, session):
    """Bilka answers a dropped session as the anonymous user, not with an error."""
    sign_in(session)
    session.answer("GET", "/shop/v6/Cart$", cart(uid=-1))
    sign_in(session)
    session.answer("GET", "/shop/v6/Cart$", cart(("84120", 1, 0)))
    assert (await client.basket()).count_of("84120") == 1


async def test_still_anonymous_after_a_fresh_sign_in_raises(client, session):
    sign_in(session)
    session.answer("GET", "/shop/v6/Cart$", cart(uid=-1))
    sign_in(session)
    session.answer("GET", "/shop/v6/Cart$", cart(uid=-1))
    with pytest.raises(BilkaAuthError):
        await client.basket()


async def test_refused_password_raises(client, session):
    session.answer("POST", "accounts.login$", {"errorCode": 403042, "errorMessage": "Invalid LoginID"})
    with pytest.raises(BilkaAuthError, match="Invalid LoginID"):
        await client.login()


async def test_refused_session_raises(client, session):
    sign_in(session, refused=True)
    with pytest.raises(BilkaAuthError):
        await client.login()


async def test_empty_basket_leaves_packing_alone(client, session):
    sign_in(session)
    session.answer("GET", "/shop/v6/Cart$", cart(("84120", 2, 0), ("19683", 1, 0)))
    session.answer("GET", "ChangeLineCount$", SIGNED_IN, repeat=True)
    await client.empty_basket()
    changed = sorted((call.params["productId"], call.params["count"]) for call in session.to("ChangeLineCount"))
    assert changed == [("19683", "0"), ("84120", "0")]


async def test_account_reads_the_pickup_store_and_prices_searches_for_it(session):
    """The store follows the account's own pickup setting rather than being configured."""
    client = BilkaClient(session, "a@b.dk", "secret")
    sign_in(session)
    session.answer("GET", "/shop/v6/Cart$", {**cart(), "deliveryAddress": {"sid": "1000", "name": "Bilka Eksempelby"}})
    account = await client.account()
    assert (account.user_id, account.store_id, account.store_name) == ("100001", "1000", "Bilka Eksempelby")
    assert session.to("/shop/v6/Cart")[0].params["extra"] == "deliveryAddress"

    session.answer("POST", "algolia", search_answer())
    await client.search("mælk")
    assert "isInAssortmentIn%3A1000" in json.loads(session.to("algolia")[0].data)["requests"][0]["params"]


async def test_account_without_a_pickup_store_raises(session):
    client = BilkaClient(session, "a@b.dk", "secret")
    sign_in(session)
    session.answer("GET", "/shop/v6/Cart$", {**cart(), "deliveryAddress": {"sid": None}})
    with pytest.raises(BilkaNoPickupStore):
        await client.account()


async def test_search_before_the_store_is_known_asks_bilka_first(session):
    """Bilka may have been down at startup; the first search then learns the store."""
    client = BilkaClient(session, "a@b.dk", "secret")
    sign_in(session)
    session.answer("GET", "/shop/v6/Cart$", {**cart(), "deliveryAddress": {"sid": "1000", "name": "Bilka Eksempelby"}})
    session.answer("POST", "algolia", search_answer())
    await client.search("mælk")
    assert client.store_id == "1000"
