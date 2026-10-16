"""Client for Bilka To Go's unofficial web API.

Bilka publishes no API. This talks to the same endpoints bilkatogo.dk's own frontend uses:

- Product search goes to Bilka's Algolia index with the public search key embedded in the
  site. It needs no login.
- Login is SAP Gigya (accounts.login, then accounts.getJWT), exchanged for a Bilka session at
  api.bilkatogo.dk/api/auth/LoginJWT. Every basket call then sends the JWT in a `jwt_token`
  header alongside the session cookie.
- The basket is read with Cart and changed with ChangeLineCount, whose `count` sets a line's
  quantity rather than adding to it.

Prices are integers in øre, as Bilka returns them. Nothing here imports Home Assistant, so it
can be tested on its own.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import aiohttp

GIGYA_URL = "https://accounts.eu1.gigya.com"
GIGYA_API_KEY = "3_tA6BbV434FQqN73HnUG1KA3qFv8KiG4OqLu9eWPh7sKRqRizH5Vfv5Larmgrb4I2"
BILKA_API = "https://api.bilkatogo.dk/api"
ALGOLIA_URL = "https://f9vbjlr1bk-dsn.algolia.net/1/indexes/*/queries"
ALGOLIA_APP_ID = "F9VBJLR1BK"
ALGOLIA_SEARCH_KEY = "1deaf41c87e729779f7695c00f190cc9"
ALGOLIA_INDEX = "prod_BILKATOGO_PRODUCTS"

# The header name must stay lowercase. The API answers "Missing jwt_token" to `Jwt_token`.
JWT_HEADER = "jwt_token"
# Gigya JWTs are asked for with a 24 h lifetime. Signing in again an hour early means a
# transfer never runs into an expiring session halfway through.
SESSION_LIFETIME = 23 * 3600
TIMEOUT = aiohttp.ClientTimeout(total=30)

# The index returns only objectID unless the fields are named.
ALGOLIA_FIELDS = json.dumps(
    [
        "objectID",
        "name",
        "brand",
        "subBrand",
        "price",
        "netcontent",
        "unitOfMeasurePrice",
        "unitOfMeasurePriceUnits",
        "properties",
        "images",
        "storeData",
    ]
)

_MULTIBUY_COUNT = re.compile(r"(\d+)\s+for\b", re.IGNORECASE)
_ORGANIC_WORD = re.compile(r"\bøko(logi|logisk)?\b", re.IGNORECASE)


class BilkaError(Exception):
    """Bilka answered in a way the client does not understand."""


class BilkaAuthError(BilkaError):
    """The credentials were refused, or Bilka did not accept the session."""


class BilkaNoPickupStore(BilkaError):
    """The account has not chosen a store to pick up from."""


@dataclass(frozen=True, slots=True)
class Account:
    """The signed-in Bilka account and the store it picks up from."""

    user_id: str
    store_id: str
    store_name: str


@dataclass(frozen=True, slots=True)
class Multibuy:
    """An offer that only saves money when enough units from one group are bought."""

    group: str
    description: str
    units: int | None
    total_price: int | None


@dataclass(frozen=True, slots=True)
class Product:
    """A Bilka product, priced for one store."""

    id: str
    name: str
    brand: str
    size: str
    price: int
    normal_price: int
    unit_price: int | None
    unit_price_unit: str
    organic: bool
    multibuy: Multibuy | None
    in_stock: bool
    image: str | None

    @property
    def price_cut(self) -> bool:
        """Whether the store sells each unit below its normal price."""
        return self.price < self.normal_price


@dataclass(frozen=True, slots=True)
class BasketLine:
    """One line of the basket."""

    product_id: str
    name: str
    count: int
    unit_price: int
    multibuy_group: str | None
    service: bool


@dataclass(frozen=True, slots=True)
class Basket:
    """The basket on the household's Bilka account."""

    lines: tuple[BasketLine, ...]
    total: int
    minimum_left: int

    @property
    def products(self) -> tuple[BasketLine, ...]:
        """The product lines, leaving out Bilka's service lines such as packing."""
        return tuple(line for line in self.lines if not line.service)

    def count_of(self, product_id: str) -> int:
        """How many of a product the basket holds."""
        return sum(line.count for line in self.products if line.product_id == product_id)

    def multibuy_count(self, group: str) -> int:
        """How many units from a multibuy group the basket holds."""
        return sum(line.count for line in self.products if line.multibuy_group == group)


class BilkaClient:
    """Searches Bilka's range and reads and changes the household's basket."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        email: str,
        password: str,
        store_id: str | None = None,
    ) -> None:
        """Use a session of its own: the Bilka session lives in the cookie jar.

        Without a store id, the first search asks Bilka which store the account picks up
        from.
        """
        self._session = session
        self._email = email
        self._password = password
        self.store_id = str(store_id) if store_id else None
        self._jwt: str | None = None
        self._signed_in_at = 0.0

    async def account(self) -> Account:
        """Read who is signed in and which store the account picks up from.

        Searches are priced for that store from then on.
        """
        body = await self._bilka("shop/v6/Cart", {"extra": "deliveryAddress"})
        pickup = body.get("deliveryAddress") or {}
        if not pickup.get("sid"):
            raise BilkaNoPickupStore("The account has no pickup store chosen")
        self.store_id = str(pickup["sid"])
        return Account(
            user_id=str(body["uid"]),
            store_id=self.store_id,
            store_name=pickup.get("name") or f"Bilka {self.store_id}",
        )

    async def login(self) -> None:
        """Sign in with Gigya and open a Bilka session."""
        login = await self._gigya(
            "accounts.login", {"loginID": self._email, "password": self._password}
        )
        login_token = (login.get("sessionInfo") or {}).get("cookieValue")
        if not login_token:
            raise BilkaAuthError("Gigya returned no login token")

        jwt = (
            await self._gigya(
                "accounts.getJWT", {"login_token": login_token, "expiration": "86400"}
            )
        ).get("id_token")
        if not jwt:
            raise BilkaAuthError("Gigya returned no JWT")

        async with self._session.post(
            f"{BILKA_API}/auth/LoginJWT",
            params={"u": "w"},
            headers={JWT_HEADER: jwt},
            timeout=TIMEOUT,
        ) as response:
            body = await _json(response)
        if response.status != 200 or not _signed_in(body):
            raise BilkaAuthError(f"Bilka refused the session: {body.get('msg')!r}")

        self._jwt = jwt
        self._signed_in_at = time.monotonic()

    async def search(
        self, query: str, *, limit: int = 30, offers_only: bool = False
    ) -> list[Product]:
        """Search the store's range, in Bilka's own relevance order."""
        filters = f"isInAssortmentIn:{self.store_id} AND nonsearchable:false"
        if offers_only:
            filters += f" AND isInOffer:{self.store_id}"
        hits = await self._algolia(
            {"query": query, "hitsPerPage": limit, "filters": filters}
        )
        return [product for hit in hits if (product := self._product(hit))]

    async def products(self, product_ids: list[str]) -> list[Product]:
        """Look up products by id, as the store prices them today.

        Products the store no longer sells are left out, which is how previously chosen
        products that Bilka dropped disappear.
        """
        if not product_ids:
            return []
        ids = " OR ".join(f"objectID:{product_id}" for product_id in product_ids)
        hits = await self._algolia(
            {
                "query": "",
                "hitsPerPage": len(product_ids),
                "filters": f"({ids}) AND isInAssortmentIn:{self.store_id}",
            }
        )
        return [product for hit in hits if (product := self._product(hit))]

    async def basket(self) -> Basket:
        """Read the basket."""
        return _basket(await self._bilka("shop/v6/Cart"))

    async def set_count(self, product_id: str, count: int) -> None:
        """Set how many of a product the basket holds; 0 removes the line."""
        await self._bilka(
            "shop/v6/ChangeLineCount",
            {"productId": product_id, "count": str(count), "fullCart": "0"},
        )

    async def add(self, product_id: str, count: int) -> int:
        """Add units of a product on top of what the basket already holds.

        Bilka only offers setting a line's count, so this reads the basket first. Returns the
        line's new count.
        """
        new_count = (await self.basket()).count_of(product_id) + count
        await self.set_count(product_id, new_count)
        return new_count

    async def empty_basket(self) -> None:
        """Remove every product line, leaving service lines such as packing alone."""
        for line in (await self.basket()).products:
            await self.set_count(line.product_id, 0)

    async def _bilka(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        """Call the basket API as the signed-in household, signing in when needed."""
        if not self._jwt or time.monotonic() - self._signed_in_at > SESSION_LIFETIME:
            await self.login()
        body = await self._bilka_once(path, params)
        if not _signed_in(body):
            # Bilka can drop a session early. It then answers as the anonymous user rather
            # than with an error, so a single fresh sign-in is tried before giving up.
            await self.login()
            body = await self._bilka_once(path, params)
            if not _signed_in(body):
                raise BilkaAuthError("Bilka answered as the anonymous user")
        return body

    async def _bilka_once(self, path: str, params: dict[str, str] | None) -> dict[str, Any]:
        async with self._session.get(
            f"{BILKA_API}/{path}",
            params={"u": "w", **(params or {})},
            headers={JWT_HEADER: self._jwt or ""},
            timeout=TIMEOUT,
        ) as response:
            if response.status >= 500:
                raise BilkaError(f"{path} answered {response.status}")
            return await _json(response)

    async def _gigya(self, method: str, data: dict[str, str]) -> dict[str, Any]:
        async with self._session.post(
            f"{GIGYA_URL}/{method}",
            data={"apiKey": GIGYA_API_KEY, **data},
            timeout=TIMEOUT,
        ) as response:
            body = await _json(response)
        if body.get("errorCode") != 0:
            raise BilkaAuthError(
                f"{method} failed: {body.get('errorMessage') or body.get('errorCode')}"
            )
        return body

    async def _algolia(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        if not self.store_id:
            # Bilka may have been unreachable when Home Assistant started.
            await self.account()
        query = "&".join(
            f"{key}={quote(str(value), safe='')}"
            for key, value in {
                **params,
                "attributesToRetrieve": ALGOLIA_FIELDS,
                "attributesToHighlight": "[]",
            }.items()
        )
        async with self._session.post(
            ALGOLIA_URL,
            headers={
                "X-Algolia-Application-Id": ALGOLIA_APP_ID,
                "X-Algolia-API-Key": ALGOLIA_SEARCH_KEY,
            },
            data=json.dumps({"requests": [{"indexName": ALGOLIA_INDEX, "params": query}]}),
            timeout=TIMEOUT,
        ) as response:
            if response.status != 200:
                raise BilkaError(f"Search answered {response.status}")
            body = await _json(response)
        try:
            return body["results"][0]["hits"]
        except (KeyError, IndexError) as err:
            raise BilkaError("Search returned no results list") from err

    def _product(self, hit: dict[str, Any]) -> Product | None:
        """Read a search hit as the store prices it, or None if the store has no data."""
        store = (hit.get("storeData") or {}).get(self.store_id)
        if not store or not hit.get("name"):
            return None
        normal_price = int(hit.get("price") or 0)
        price = int(store.get("price") or normal_price)
        images = hit.get("images") or []
        return Product(
            id=str(hit["objectID"]),
            name=hit["name"],
            brand=hit.get("brand") or "",
            size=hit.get("netcontent") or "",
            price=price,
            normal_price=max(normal_price, price),
            unit_price=store.get("unitsOfMeasureShowPrice") or hit.get("unitOfMeasurePrice"),
            unit_price_unit=store.get("unitsOfMeasurePriceUnit")
            or hit.get("unitOfMeasurePriceUnits")
            or "",
            organic=_organic(hit),
            multibuy=_multibuy(store),
            in_stock=bool(store.get("inStock")),
            image=images[0] if images else None,
        )


def _organic(hit: dict[str, Any]) -> bool:
    """Whether a product is organic.

    Bilka's "Økologisk" property is missing from some organic products (Friland Økologi's
    hamburgerryg øko has none), so the name and brand are read as well.
    """
    if "Økologisk" in (hit.get("properties") or []):
        return True
    return any(
        _ORGANIC_WORD.search(hit.get(field) or "") for field in ("name", "brand", "subBrand")
    )


def _multibuy(store: dict[str, Any]) -> Multibuy | None:
    group = store.get("multipromo")
    if not group:
        return None
    description = store.get("offerDescription") or ""
    units = _MULTIBUY_COUNT.search(description)
    total = store.get("multiPromoPrice")
    return Multibuy(
        group=str(group),
        description=description,
        units=int(units.group(1)) if units else None,
        total_price=int(total) if str(total).isdigit() else None,
    )


def _basket(body: dict[str, Any]) -> Basket:
    lines = []
    for section in body.get("lines") or []:
        service = section.get("headline") == "Services"
        for line in section.get("lines") or []:
            for order_line in line.get("orderlines") or []:
                product = order_line.get("product") or {}
                lines.append(
                    BasketLine(
                        product_id=str(product.get("objectID")),
                        name=product.get("name") or "",
                        count=int(order_line.get("quantity") or 0),
                        unit_price=int(order_line.get("unitprice") or 0),
                        multibuy_group=str(product["multipromo"])
                        if product.get("multipromo")
                        else None,
                        service=service,
                    )
                )
    stat = body.get("stat") or {}
    return Basket(
        lines=tuple(lines),
        total=int(stat.get("prod_price") or 0),
        minimum_left=int(stat.get("minimum_left") or 0),
    )


def _signed_in(body: dict[str, Any]) -> bool:
    return body.get("uid") not in (None, -1, "-1")


async def _json(response: aiohttp.ClientResponse) -> dict[str, Any]:
    try:
        body = await response.json(content_type=None)
    except (aiohttp.ContentTypeError, json.JSONDecodeError) as err:
        raise BilkaError(f"{response.url.path} did not answer with JSON") from err
    if not isinstance(body, dict):
        raise BilkaError(f"{response.url.path} answered with {type(body).__name__}")
    return body
