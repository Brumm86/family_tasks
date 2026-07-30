"""Battery discovery and low-battery aggregation for the Family Tasks integration.

A task with recurrence type "battery" (see ``RECURRENCE_BATTERY`` in
const.py) does not track a single sensor the way a "trigger" task does.
Instead it aggregates *every* battery-level entity Home Assistant knows
about into one task: it becomes due the moment any monitored battery is at
or below its warning threshold, and stays idle otherwise. Which batteries
count, and at what level, is exposed on the task status sensor's
"battery_entities" attribute (see ``coordinator.TaskStatusData``) so the
household can see at a glance what needs charging/swapping - no per-battery
task needed.

Two knobs, both editable through the card:
  - a household-wide default warning threshold (config entry option, see
    ``CONF_BATTERY_WARNING_THRESHOLD``), and
  - per-entity overrides (``storage.BatteryOverrideStorageCollection``):
    exclude a battery from monitoring entirely, or give it its own
    threshold.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import STATE_ON
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    callback,
)
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event

if TYPE_CHECKING:
    from .coordinator import FamilyTasksCoordinator
    from .storage import BatteryOverrideStorageCollection

_LOGGER = logging.getLogger(__name__)

_UNAVAILABLE_STATES = ("unknown", "unavailable")


@dataclass(slots=True)
class LowBattery:
    """A single monitored battery currently at/below its warning threshold."""

    entity_id: str
    name: str
    # None for binary_sensor "low battery" entities, which report on/off
    # rather than a percentage - see async_compute_low_batteries.
    level: float | None
    threshold: float | None

    def as_dict(self) -> dict:
        """Return a JSON/attribute-friendly representation."""
        return {
            "entity_id": self.entity_id,
            "name": self.name,
            "level": self.level,
            "threshold": self.threshold,
        }


@callback
def async_discover_battery_entity_ids(hass: HomeAssistant) -> set[str]:
    """Return every entity_id Home Assistant reports as a battery-level entity.

    Mirrors how Home Assistant itself identifies batteries: a ``sensor``
    with device_class "battery" (a numeric percentage) or a
    ``binary_sensor`` with device_class "battery" (a low-battery boolean,
    "on" = low). Entities disabled in the registry are skipped, same as
    everywhere else in HA.
    """
    registry = er.async_get(hass)
    entity_ids: set[str] = set()
    for entity_entry in registry.entities.values():
        if entity_entry.disabled:
            continue
        device_class = entity_entry.device_class or entity_entry.original_device_class
        if entity_entry.domain == "sensor" and device_class == SensorDeviceClass.BATTERY:
            entity_ids.add(entity_entry.entity_id)
        elif (
            entity_entry.domain == "binary_sensor"
            and device_class == BinarySensorDeviceClass.BATTERY
        ):
            entity_ids.add(entity_entry.entity_id)
    return entity_ids


@callback
def async_compute_low_batteries(
    hass: HomeAssistant,
    overrides: BatteryOverrideStorageCollection,
    default_threshold: float,
) -> list[LowBattery]:
    """Return every monitored battery currently at/below its warning threshold.

    A battery counts as "low" if:
      - it isn't excluded via a BatteryOverrideStorageCollection item, and
      - it's a numeric sensor.* battery whose current value is <= its
        threshold (the entity's override, or the household-wide default), or
      - it's a binary_sensor.* battery currently reporting "on" (HA's own
        convention for "battery low"), which has no percentage/threshold of
        its own.
    """
    overrides_by_entity = {item["entity_id"]: item for item in overrides.data.values()}
    low: list[LowBattery] = []

    for entity_id in async_discover_battery_entity_ids(hass):
        override = overrides_by_entity.get(entity_id, {})
        if override.get("excluded", False):
            continue

        state = hass.states.get(entity_id)
        if state is None or state.state in _UNAVAILABLE_STATES:
            continue

        name = state.attributes.get("friendly_name", entity_id)

        if entity_id.startswith("binary_sensor."):
            if state.state == STATE_ON:
                low.append(
                    LowBattery(entity_id=entity_id, name=name, level=None, threshold=None)
                )
            continue

        try:
            level = float(state.state)
        except ValueError:
            continue

        threshold = override.get("threshold")
        if threshold is None:
            threshold = default_threshold
        if level <= threshold:
            low.append(
                LowBattery(entity_id=entity_id, name=name, level=level, threshold=threshold)
            )

    low.sort(key=lambda battery: (battery.level if battery.level is not None else -1.0, battery.name))
    return low


class BatteryStateListener:
    """Requests a coordinator refresh when a monitored battery's state changes.

    The coordinator otherwise only recomputes on its poll interval (see
    COORDINATOR_UPDATE_INTERVAL) or after a task/member/override edit;
    without this, a battery task would take up to that long to reflect a
    battery that just dropped below its threshold. Resubscribes after every
    coordinator refresh so newly added battery entities are picked up
    automatically, mirroring how trigger.TaskTriggerListener resubscribes
    after every task change.
    """

    def __init__(self, hass: HomeAssistant, coordinator: FamilyTasksCoordinator) -> None:
        self._hass = hass
        self._coordinator = coordinator
        self._unsub_state: CALLBACK_TYPE | None = None
        self._subscribed_entities: set[str] = set()

    @callback
    def async_setup(self) -> None:
        """Subscribe to the currently discovered battery entities."""
        self.async_resubscribe()

    @callback
    def async_unload(self) -> None:
        """Tear down the state-change subscription."""
        if self._unsub_state is not None:
            self._unsub_state()
            self._unsub_state = None
        self._subscribed_entities = set()

    @callback
    def async_resubscribe(self) -> None:
        """Re-derive the set of battery entities to watch, if it changed.

        Registered as a coordinator listener (called with no arguments after
        every refresh), so this doubles as picking up newly added/removed
        battery entities without a dedicated entity-registry subscription.
        """
        entities = async_discover_battery_entity_ids(self._hass)
        if entities == self._subscribed_entities:
            return

        if self._unsub_state is not None:
            self._unsub_state()
            self._unsub_state = None

        self._subscribed_entities = entities
        if entities:
            self._unsub_state = async_track_state_change_event(
                self._hass, list(entities), self._async_on_state_changed
            )

    @callback
    def _async_on_state_changed(self, event: Event[EventStateChangedData]) -> None:
        _LOGGER.debug(
            "Battery entity %s changed state, requesting refresh", event.data["entity_id"]
        )
        self._hass.async_create_task(self._coordinator.async_request_refresh())
