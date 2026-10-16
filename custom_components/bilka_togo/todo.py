"""The shopping list as a Home Assistant to-do list.

Being an ordinary to-do list means Assist, the companion app's to-do panel and the standard
to-do card all work on it. The rules in shopping_list.py hold however an item arrives.
"""

from __future__ import annotations

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BilkaConfigEntry, BilkaData
from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BilkaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the shopping list."""
    async_add_entities([ShoppingListEntity(entry.runtime_data, entry.entry_id)])


class ShoppingListEntity(TodoListEntity):
    """The household's shopping list."""

    _attr_has_entity_name = True
    _attr_translation_key = "shopping_list"
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
        | TodoListEntityFeature.MOVE_TODO_ITEM
        | TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM
    )

    def __init__(self, data: BilkaData, entry_id: str) -> None:
        self._data = data
        self._attr_unique_id = f"{entry_id}_shopping_list"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name="Bilka To Go",
            manufacturer="Bilka",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def todo_items(self) -> list[TodoItem]:
        """The items, with the amount shown as the description."""
        return [
            TodoItem(
                uid=item.uid,
                summary=item.name,
                description=item.amount,
                status=TodoItemStatus.NEEDS_ACTION,
            )
            for item in self._data.shopping_list.items
        ]

    async def async_create_todo_item(self, item: TodoItem) -> None:
        """Add an item; one already on the list gains the new amount instead."""
        try:
            self._data.shopping_list.add(item.summary or "", item.description)
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err
        await self._changed()

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Rename or change an item's amount. Ticking it off removes it."""
        if item.status == TodoItemStatus.COMPLETED:
            # There is no "bought" state: ticking an item off in a standard to-do card or the
            # companion app means it is no longer needed.
            self._data.shopping_list.remove([item.uid])
        else:
            try:
                self._data.shopping_list.update(item.uid, item.summary or "", item.description)
            except ValueError as err:
                raise ServiceValidationError(str(err)) from err
            except KeyError as err:
                raise ServiceValidationError(f"No item {item.uid}") from err
        await self._changed()

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        """Remove items."""
        self._data.shopping_list.remove(uids)
        await self._changed()

    async def async_move_todo_item(self, uid: str, previous_uid: str | None = None) -> None:
        """Reorder the list."""
        try:
            self._data.shopping_list.move(uid, previous_uid)
        except KeyError as err:
            raise ServiceValidationError(f"No item {err}") from err
        await self._changed()

    async def async_added_to_hass(self) -> None:
        """Follow changes made outside this entity, such as moves during a transfer."""
        self.async_on_remove(self._data.async_add_listener(self.async_write_ha_state))

    async def _changed(self) -> None:
        self._data.changed()
