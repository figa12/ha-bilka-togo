"""What transfers remember, and how previously chosen products are ordered.

Kept free of Home Assistant so it can be tested on its own. See CONTEXT.md for the words:
a known item is a name that has had a product chosen for it in a transfer; previously chosen
is the set of products picked for an item, which only shrinks when someone forgets one; the
preference order decides which of them is shown first.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .api import Product
from .shopping_list import item_key


class Memory:
    """Known items and their previously chosen products, as stored.

    Stored shape: {"known": {<item key>: {"name": str, "moves": int,
    "chosen": {<product id>: {"count": int, "times": int, "last": iso}}}}}
    """

    def __init__(self, data: dict[str, Any]) -> None:
        # Edited in place, so the caller's stored dict is what gets saved.
        self._data = data
        self._known: dict[str, Any] = data.setdefault("known", {})

    def record_move(self, item_name: str, product_id: str, count: int, when: datetime) -> None:
        """Remember that a product was chosen for an item, and how many."""
        known = self._known.setdefault(item_key(item_name), {"moves": 0, "chosen": {}})
        known["name"] = " ".join(item_name.split())
        known["moves"] += 1
        chosen = known["chosen"].setdefault(product_id, {"times": 0})
        chosen.update(count=count, times=chosen["times"] + 1, last=when.isoformat())

    def known_items(self) -> list[str]:
        """Known item names, the most often transferred first."""
        ranked = sorted(self._known.values(), key=lambda k: (-k["moves"], k["name"].casefold()))
        return [known["name"] for known in ranked]

    def previously_chosen(self, item_name: str) -> dict[str, dict[str, Any]]:
        """The products chosen for an item before, by product id."""
        return dict((self._known.get(item_key(item_name)) or {}).get("chosen", {}))

    def forget(self, item_name: str, product_id: str) -> bool:
        """Take a product out of an item's previously chosen. Returns whether it was there."""
        known = self._known.get(item_key(item_name))
        if not known or product_id not in known["chosen"]:
            return False
        del known["chosen"][product_id]
        return True


def preference_order(products: list[Product]) -> list[Product]:
    """Organic with a price cut, then any price cut, then organic, then the rest.

    Cheapest per unit within each group, so a 1 l and a 2 l carton compare fairly. A multibuy
    never counts as a price cut: it only saves money if the group is filled.
    """

    def group(product: Product) -> int:
        if product.price_cut:
            return 0 if product.organic else 1
        return 2 if product.organic else 3

    return sorted(products, key=lambda p: (group(p), p.unit_price or p.price, p.price))


def suggested_count(amount: str | None) -> int | None:
    """An amount that is a plain number suggests the count; anything else is left to a person."""
    amount = (amount or "").strip()
    return int(amount) if amount.isdigit() and 0 < int(amount) < 100 else None
