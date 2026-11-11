"""Switch platform for the Family Tasks integration.

Currently just the one, household-wide "Urlaubsmodus" switch (v0.32) - see
CONF_TASK_VACATION_BEHAVIOR/CONF_VACATION_MODE_DEFAULT in const.py and
VacationModeStateStore in storage.py. Unlike the per-task/per-member sensors
and buttons elsewhere in this integration, this is a single static entity,
not one dynamically created per collection item - so there is no
"known ids"/async_prune_stale_entities dance here, just one entity added once.
"""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity, SwitchDeviceClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import FamilyTasksConfigEntry
from .const import DOMAIN, MANUFACTURER
from .coordinator import FamilyTasksCoordinator


def _device_info(entry: FamilyTasksConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer=MANUFACTURER,
    )


class FamilyTasksVacationModeSwitch(
    CoordinatorEntity[FamilyTasksCoordinator], SwitchEntity
):
    """On/off switch for the household-wide "Urlaubsmodus".

    This entity - not the CONF_VACATION_MODE_DEFAULT config option, which
    only ever seeds its *initial* value - is the actual source of truth (see
    VacationModeStateStore in storage.py): toggle it from a dashboard,
    automation, or voice assistant, the same way any other switch works, so
    it can be wired into a household's existing "we're away" automation
    instead of being locked inside this integration's own UI. While on, any
    task with CONF_TASK_VACATION_BEHAVIOR="pause" is skipped entirely by the
    coordinator (see the vacation-mode handling in
    FamilyTasksCoordinator._async_update_data); a task left at the default
    "show" is unaffected.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:beach"
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_translation_key = "vacation_mode"

    def __init__(
        self, coordinator: FamilyTasksCoordinator, entry: FamilyTasksConfigEntry
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_vacation_mode"
        self._attr_device_info = _device_info(entry)

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.vacation_mode_active

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_set_vacation_mode(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_set_vacation_mode(False)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FamilyTasksConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the single, static Urlaubsmodus switch."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities([FamilyTasksVacationModeSwitch(coordinator, entry)])
