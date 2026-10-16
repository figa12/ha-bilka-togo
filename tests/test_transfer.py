"""Memory of transfers and the preference order, as CONTEXT.md states them."""

from datetime import UTC, datetime

import pytest

from custom_components.bilka_togo.api import Multibuy, Product
from custom_components.bilka_togo.transfer import Memory, preference_order, suggested_count

NOW = datetime(2026, 10, 18, 19, 0, tzinfo=UTC)


def product(pid, *, price, normal=None, organic=False, unit=None, multibuy=None):
    return Product(
        id=pid, name=pid, brand="", size="1 l", price=price, normal_price=normal or price,
        unit_price=unit, unit_price_unit="L.", organic=organic, multibuy=multibuy,
        in_stock=True, image=None,
    )


def test_preference_order_is_cut_and_organic_then_cut_then_organic_then_rest():
    """The example from the design: no organic milk on offer this week gives B, A, C, D."""
    a = product("A arla øko", price=1405, organic=True)
    b = product("B salling cut", price=895, normal=1105)
    c = product("C tjele øko", price=1595, organic=True)
    d = product("D arla", price=1260)
    assert [p.id for p in preference_order([d, c, a, b])] == [b.id, a.id, c.id, d.id]

    e = product("E øko cut", price=1300, normal=1500, organic=True)
    assert preference_order([d, c, a, b, e])[0] is e


def test_cheapest_per_unit_wins_within_a_group():
    small = product("1 l", price=1405, unit=1405, organic=True)
    big = product("2 l", price=2500, unit=1250, organic=True)
    assert [p.id for p in preference_order([small, big])] == ["2 l", "1 l"]


def test_a_multibuy_never_counts_as_on_offer():
    mix = product("mix", price=7000, multibuy=Multibuy("2660", "Mix 5 for 300,00", 5, 30000))
    organic = product("øko", price=7500, organic=True)
    assert [p.id for p in preference_order([mix, organic])] == ["øko", "mix"]


def test_memory_grows_per_item_and_remembers_the_last_count():
    stored = {}
    memory = Memory(stored)
    memory.record_move("mælk", "19683", 6, NOW)
    memory.record_move("Mælk ", "84120", 4, NOW)
    memory.record_move("mælk", "19683", 8, NOW)
    chosen = memory.previously_chosen("MÆLK")
    assert set(chosen) == {"19683", "84120"}
    assert chosen["19683"]["count"] == 8
    assert chosen["19683"]["times"] == 2
    assert stored["known"]  # edits the stored dict in place, so it is what gets saved


def test_known_items_most_transferred_first():
    memory = Memory({})
    memory.record_move("brød", "1", 1, NOW)
    for _ in range(3):
        memory.record_move("mælk", "2", 1, NOW)
    memory.record_move("æg", "3", 1, NOW)
    assert memory.known_items() == ["mælk", "brød", "æg"]


def test_only_a_move_makes_a_known_item():
    """Typing a name on the wall display never makes it a suggestion; a transfer does."""
    assert Memory({}).known_items() == []


def test_forget_takes_one_product_out():
    memory = Memory({})
    memory.record_move("mælk", "19683", 6, NOW)
    memory.record_move("mælk", "81420", 2, NOW)
    assert memory.forget("mælk", "81420") is True
    assert set(memory.previously_chosen("mælk")) == {"19683"}
    assert memory.forget("mælk", "81420") is False
    assert memory.known_items() == ["mælk"]  # still a known item


@pytest.mark.parametrize(
    ("amount", "count"),
    [("2", 2), (" 6 ", 6), ("6 l", None), ("2, 2", None), ("ekstra til fredag", None), (None, None), ("0", None)],
)
def test_suggested_count_only_from_a_plain_number(amount, count):
    assert suggested_count(amount) == count
