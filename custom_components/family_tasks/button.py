"""Button platform for the Family Tasks integration."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import FamilyTasksConfigEntry
from .const import DOMAIN, MANUFACTURER
from .coordinator import FamilyTasksCoordinator
from .entity_registry_helpers import async_prune_stale_entities


def _device_info(entry: FamilyTasksConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer=MANUFACTURER,
    )


class FamilyTasksCompleteTaskButton(
    CoordinatorEntity[FamilyTasksCoordinator], ButtonEntity
):
    """Button to mark the current occurrence of a task as done."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:check-circle-outline"

    def __init__(
        self, coordinator: FamilyTasksCoordinator, entry: FamilyTasksConfigEntry, task_id: str
    ) -> None:
        super().__init__(coordinator)
        self._task_id = task_id
        self._attr_unique_id = f"{entry.entry_id}_task_{task_id}_complete"
        self._attr_device_info = _device_info(entry)
        self._attr_translation_key = "complete_task"

    @property
    def available(self) -> bool:
        return super().available and self._task_id in self.coordinator.data.tasks

    @property
    def name(self) -> str:
        task = self.coordinator.data.tasks.get(self._task_id)
        return f"{task.name} erledigt" if task else "erledigt"

    async def async_press(self) -> None:
        """Mark the task's current occurrence as completed."""
        await self.coordinator.async_complete_task(self._task_id)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FamilyTasksConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Family Tasks buttons, dynamically tracking tasks."""
    coordinator = entry.runtime_data.coordinator
    known_tasks: set[str] = set()

    @callback
    def _async_add_new_entities() -> None:
        new_tasks = set(coordinator.data.tasks) - known_tasks
        known_tasks.update(new_tasks)

        if new_tasks:
            async_add_entities(
                FamilyTasksCompleteTaskButton(coordinator, entry, task_id)
                for task_id in new_tasks
            )

        async_prune_stale_entities(
            hass,
            entry,
            platform="button",
            valid_unique_ids={
                f"{entry.entry_id}_task_{tid}_complete" for tid in coordinator.data.tasks
            },
        )
        known_tasks.intersection_update(coordinator.data.tasks)

    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_entities))
    _async_add_new_entities()
