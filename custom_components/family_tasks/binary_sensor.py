"""Binary sensor platform for the Family Tasks integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
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


class FamilyTasksScreenTimeGrantSensor(
    CoordinatorEntity[FamilyTasksCoordinator], BinarySensorEntity
):
    """Whether tick-based screen-time granting should currently be active.

    See MemberSummaryData.screen_time_grant_active in coordinator.py: "on"
    unless this member currently has at least one TASK_KIND_MANDATORY
    ("Pflichtaufgabe") task assigned to them that is TASK_STATUS_OVERDUE.
    This integration never grants screen time itself - a household's own
    tick-based automation (running on its own schedule, independent of this
    integration) is expected to check this entity's state before applying
    the next tick, and simply skip it while "off". Turns back "on" by itself
    the moment the mandatory task is no longer overdue (completed, or once a
    parent confirms it for a "child" assignee) - ticks missed while paused
    are never made up, this only ever gates whether the *next* one may grant
    anything.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:cellphone-check"

    def __init__(
        self, coordinator: FamilyTasksCoordinator, entry: FamilyTasksConfigEntry, member_id: str
    ) -> None:
        super().__init__(coordinator)
        self._member_id = member_id
        self._attr_unique_id = f"{entry.entry_id}_member_{member_id}_screen_time_grant_active"
        self._attr_device_info = _device_info(entry)
        self._attr_translation_key = "screen_time_grant_active"

    @property
    def available(self) -> bool:
        return super().available and self._member_id in self.coordinator.data.members

    @property
    def _member(self):
        return self.coordinator.data.members[self._member_id]

    @property
    def name(self) -> str:
        return f"{self._member.name} Handyzeitgewährung aktiv"

    @property
    def icon(self) -> str:
        return "mdi:cellphone-check" if self.is_on else "mdi:cellphone-lock"

    @property
    def is_on(self) -> bool:
        return self._member.screen_time_grant_active

    @property
    def extra_state_attributes(self) -> dict:
        return {"member_id": self._member_id}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FamilyTasksConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Family Tasks binary sensors, dynamically tracking members."""
    coordinator = entry.runtime_data.coordinator
    known_members: set[str] = set()

    @callback
    def _async_add_new_entities() -> None:
        new_members = set(coordinator.data.members) - known_members
        known_members.update(new_members)

        if new_members:
            async_add_entities(
                FamilyTasksScreenTimeGrantSensor(coordinator, entry, member_id)
                for member_id in new_members
            )

        async_prune_stale_entities(
            hass,
            entry,
            platform="binary_sensor",
            valid_unique_ids={
                f"{entry.entry_id}_member_{mid}_screen_time_grant_active"
                for mid in coordinator.data.members
            },
        )
        known_members.intersection_update(coordinator.data.members)

    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_entities))
    _async_add_new_entities()
