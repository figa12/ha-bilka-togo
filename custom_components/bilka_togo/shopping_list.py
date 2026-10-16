"""The shopping list's rules, kept free of Home Assistant so they can be tested on their own.

See CONTEXT.md: an item names what is wanted, never a product. Two items are the same item
when their names match ignoring capitals and spaces, so the list never holds one twice. An
item's amount is a free-text hint kept apart from its name. An item leaves the list by a move
or a remove; there is no "bought" state.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import uuid


def item_key(name: str) -> str:
    """What makes two item names the same item."""
    return " ".join(name.split()).casefold()


def _tidy(text: str | None) -> str | None:
    text = " ".join((text or "").split())
    return text or None


def _join_amounts(first: str | None, second: str | None) -> str | None:
    """Keep both hints rather than guess what they add up to.

    "1 l" then "2" becomes "1 l, 2", and "2" twice becomes "2, 2": two people may each want
    two. The person transferring decides what it means.
    """
    if not first or not second:
        return first or second
    return f"{first}, {second}"


@dataclass(slots=True)
class Item:
    """One entry on the shopping list."""

    uid: str
    name: str
    amount: str | None = None


class ShoppingList:
    """The household's single running list, in its own order."""

    def __init__(self, items: list[Item] | None = None) -> None:
        self._items: list[Item] = list(items or [])

    @property
    def items(self) -> list[Item]:
        return list(self._items)

    def get(self, uid: str) -> Item | None:
        """The item with this uid, if it is still on the list."""
        return next((item for item in self._items if item.uid == uid), None)

    def find(self, name: str) -> Item | None:
        """The item with this name, if it is on the list."""
        key = item_key(name)
        return next((item for item in self._items if item_key(item.name) == key), None)

    def add(self, name: str, amount: str | None = None) -> Item:
        """Add an item, or join its amount onto the same item already on the list."""
        name, amount = self._valid_name(name), _tidy(amount)
        if existing := self.find(name):
            existing.amount = _join_amounts(existing.amount, amount)
            return existing
        item = Item(uid=uuid.uuid4().hex, name=name, amount=amount)
        self._items.append(item)
        return item

    def update(self, uid: str, name: str, amount: str | None) -> Item:
        """Change an item's name or amount.

        Renaming it to another item's name merges the two: the other item keeps its place and
        gains this one's amount.
        """
        item = self._get(uid)
        name, amount = self._valid_name(name), _tidy(amount)
        other = self.find(name)
        if other is not None and other.uid != uid:
            other.amount = _join_amounts(other.amount, amount)
            self._items.remove(item)
            return other
        item.name, item.amount = name, amount
        return item

    def remove(self, uids: list[str]) -> None:
        """Remove items that are no longer needed."""
        gone = set(uids)
        self._items = [item for item in self._items if item.uid not in gone]

    def move(self, uid: str, previous_uid: str | None) -> None:
        """Place an item right after another, or first."""
        item = self._get(uid)
        self._items.remove(item)
        index = 0 if previous_uid is None else self._items.index(self._get(previous_uid)) + 1
        self._items.insert(index, item)

    def as_data(self) -> list[dict[str, str | None]]:
        return [asdict(item) for item in self._items]

    @classmethod
    def from_data(cls, data: list[dict[str, str | None]]) -> ShoppingList:
        return cls([Item(**entry) for entry in data])

    def _get(self, uid: str) -> Item:
        for item in self._items:
            if item.uid == uid:
                return item
        raise KeyError(uid)

    @staticmethod
    def _valid_name(name: str) -> str:
        if not (tidy := _tidy(name)):
            raise ValueError("An item needs a name")
        return tidy
