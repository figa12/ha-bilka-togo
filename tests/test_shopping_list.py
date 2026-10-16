"""The shopping list's rules, as CONTEXT.md states them."""

import pytest

from custom_components.bilka_togo.shopping_list import ShoppingList


def names(shopping_list):
    return [(item.name, item.amount) for item in shopping_list.items]


def test_the_same_item_is_never_on_the_list_twice():
    """Capitals and spaces do not make a different item."""
    shopping_list = ShoppingList()
    shopping_list.add("mælk")
    shopping_list.add("Mælk ")
    shopping_list.add("  MÆLK")
    assert names(shopping_list) == [("mælk", None)]


def test_different_names_are_different_items():
    shopping_list = ShoppingList()
    shopping_list.add("mælk")
    shopping_list.add("letmælk")
    shopping_list.add("mælk til kakao")
    assert [name for name, _ in names(shopping_list)] == ["mælk", "letmælk", "mælk til kakao"]


@pytest.mark.parametrize(
    ("first", "second", "joined"),
    [
        (None, "2", "2"),
        ("1 l", None, "1 l"),
        ("1 l", "2", "1 l, 2"),
        ("2", "2", "2, 2"),  # two people may each want two
        (None, None, None),
    ],
)
def test_adding_an_item_again_joins_the_amounts(first, second, joined):
    shopping_list = ShoppingList()
    shopping_list.add("mælk", first)
    shopping_list.add("mælk", second)
    assert names(shopping_list) == [("mælk", joined)]


def test_amount_is_kept_apart_from_the_name():
    shopping_list = ShoppingList()
    shopping_list.add(" kød ", "  2 aftener ")
    assert names(shopping_list) == [("kød", "2 aftener")]


@pytest.mark.parametrize("name", ["", "   "])
def test_an_item_needs_a_name(name):
    with pytest.raises(ValueError):
        ShoppingList().add(name)


def test_renaming_onto_another_item_merges_into_it():
    shopping_list = ShoppingList()
    shopping_list.add("mælk", "1 l")
    letmaelk = shopping_list.add("letmælk", "2")
    shopping_list.add("brød")
    shopping_list.update(letmaelk.uid, "Mælk", "2")
    assert names(shopping_list) == [("mælk", "1 l, 2"), ("brød", None)]


def test_updating_changes_name_and_amount_in_place():
    shopping_list = ShoppingList()
    item = shopping_list.add("mælk")
    shopping_list.add("brød")
    shopping_list.update(item.uid, "letmælk", "6 l")
    assert names(shopping_list) == [("letmælk", "6 l"), ("brød", None)]


def test_remove_and_move():
    shopping_list = ShoppingList()
    a, b, c = (shopping_list.add(name) for name in ("a", "b", "c"))
    shopping_list.move(c.uid, None)
    assert [n for n, _ in names(shopping_list)] == ["c", "a", "b"]
    shopping_list.move(c.uid, b.uid)
    assert [n for n, _ in names(shopping_list)] == ["a", "b", "c"]
    shopping_list.remove([a.uid, c.uid])
    assert [n for n, _ in names(shopping_list)] == ["b"]


def test_survives_being_stored():
    shopping_list = ShoppingList()
    shopping_list.add("mælk", "2")
    shopping_list.add("brød")
    again = ShoppingList.from_data(shopping_list.as_data())
    assert names(again) == names(shopping_list)
    assert [i.uid for i in again.items] == [i.uid for i in shopping_list.items]
