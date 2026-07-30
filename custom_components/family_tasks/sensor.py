"""Sensor platform for the Family Tasks integration."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.const import EntityCategory
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


class FamilyTasksTaskStatusSensor(
    CoordinatorEntity[FamilyTasksCoordinator], SensorEntity
):
    """Represents the current-period status of one recurring task."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: FamilyTasksCoordinator, entry: FamilyTasksConfigEntry, task_id: str
    ) -> None:
        super().__init__(coordinator)
        self._task_id = task_id
        self._attr_unique_id = f"{entry.entry_id}_task_{task_id}_status"
        self._attr_device_info = _device_info(entry)
        self._attr_translation_key = "task_status"

    @property
    def available(self) -> bool:
        return super().available and self._task_id in self.coordinator.data.tasks

    @property
    def _task(self):
        return self.coordinator.data.tasks[self._task_id]

    @property
    def name(self) -> str:
        return self._task.name

    @property
    def icon(self) -> str | None:
        return self._task.icon

    @property
    def native_value(self) -> str:
        return self._task.status

    @property
    def extra_state_attributes(self) -> dict:
        task = self._task
        return {
            "task_id": task.task_id,
            "assigned_member_id": task.assigned_member_id,
            "due_at": task.due_at.isoformat() if task.due_at else None,
            "points": task.points,
            "period_key": task.period_key,
            "last_completed_by": task.last_completed_by,
            "last_completed_at": task.last_completed_at.isoformat()
            if task.last_completed_at
            else None,
        }


class FamilyTasksMemberPointsSensor(
    CoordinatorEntity[FamilyTasksCoordinator], SensorEntity
):
    """Points earned by a family member (today/week/total as attributes)."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:trophy-outline"
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(
        self, coordinator: FamilyTasksCoordinator, entry: FamilyTasksConfigEntry, member_id: str
    ) -> None:
        super().__init__(coordinator)
        self._member_id = member_id
        self._attr_unique_id = f"{entry.entry_id}_member_{member_id}_points"
        self._attr_device_info = _device_info(entry)
        self._attr_translation_key = "member_points"

    @property
    def available(self) -> bool:
        return super().available and self._member_id in self.coordinator.data.members

    @property
    def _member(self):
        return self.coordinator.data.members[self._member_id]

    @property
    def name(self) -> str:
        return f"{self._member.name} Punkte"

    @property
    def native_value(self) -> int:
        return self._member.points_total

    @property
    def extra_state_attributes(self) -> dict:
        member = self._member
        return {
            "member_id": member.member_id,
            "points_today": member.points_today,
            "points_week": member.points_week,
            "points_month": member.points_month,
            "person_entity_id": member.person_entity_id,
        }


class FamilyTasksMemberOpenTasksSensor(
    CoordinatorEntity[FamilyTasksCoordinator], SensorEntity
):
    """Number of currently open (pending/overdue) tasks assigned to a member."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:format-list-checks"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, coordinator: FamilyTasksCoordinator, entry: FamilyTasksConfigEntry, member_id: str
    ) -> None:
        super().__init__(coordinator)
        self._member_id = member_id
        self._attr_unique_id = f"{entry.entry_id}_member_{member_id}_open_tasks"
        self._attr_device_info = _device_info(entry)
        self._attr_translation_key = "member_open_tasks"

    @property
    def available(self) -> bool:
        return super().available and self._member_id in self.coordinator.data.members

    @property
    def name(self) -> str:
        return f"{self.coordinator.data.members[self._member_id].name} offene Aufgaben"

    @property
    def native_value(self) -> int:
        return self.coordinator.data.members[self._member_id].open_tasks

    @property
    def extra_state_attributes(self) -> dict:
        return {"member_id": self._member_id}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FamilyTasksConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Family Tasks sensors, dynamically tracking tasks/members."""
    coordinator = entry.runtime_data.coordinator

    known_tasks: set[str] = set()
    known_members: set[str] = set()

    @callback
    def _async_add_new_entities() -> None:
        new_tasks = set(coordinator.data.tasks) - known_tasks
        new_members = set(coordinator.data.members) - known_members

        entities: list[SensorEntity] = []
        for task_id in new_tasks:
            entities.append(FamilyTasksTaskStatusSensor(coordinator, entry, task_id))
        for member_id in new_members:
            entities.append(
                FamilyTasksMemberPointsSensor(coordinator, entry, member_id)
            )
            entities.append(
                FamilyTasksMemberOpenTasksSensor(coordinator, entry, member_id)
            )

        known_tasks.update(new_tasks)
        known_members.update(new_members)

        if entities:
            async_add_entities(entities)

        async_prune_stale_entities(
            hass,
            entry,
            platform="sensor",
            valid_unique_ids={
                f"{entry.entry_id}_task_{tid}_status" for tid in coordinator.data.tasks
            }
            | {
                f"{entry.entry_id}_member_{mid}_points" for mid in coordinator.data.members
            }
            | {
                f"{entry.entry_id}_member_{mid}_open_tasks"
                for mid in coordinator.data.members
            },
        )
        known_tasks.intersection_update(coordinator.data.tasks)
        known_members.intersection_update(coordinator.data.members)

    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_entities))
    _async_add_new_entities()
