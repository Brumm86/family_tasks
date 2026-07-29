"""Sensor-based triggers for the Family Tasks integration.

Most tasks recur on a calendar (daily/weekly/interval_days), but some are
better described by a sensor condition than by a schedule: "take out the
trash once the bin sensor reports it's full", "water the plants once the
soil moisture sensor goes dry". Tasks with recurrence type ``"trigger"`` (see
``storage.RECURRENCE_TRIGGER``) carry a nested trigger definition modeled on
Home Assistant's own automation triggers:

- ``{"kind": "state", "entity_id": ..., "to_state": "on"}`` - a binary_sensor
  (or any entity) reaching a given state.
- ``{"kind": "numeric_state", "entity_id": ..., "above": ..., "below": ...}``
  - a numeric sensor crossing a threshold.

``TaskTriggerListener`` subscribes to state-change events for every entity
referenced this way and, on the edge transition into a matching condition,
asks the coordinator to open a new occurrence for that task.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.exceptions import ConditionError
from homeassistant.helpers import condition
from homeassistant.helpers.event import async_track_state_change_event

from .const import RECURRENCE_TRIGGER, TASK_TRIGGER_STATE

if TYPE_CHECKING:
    from .coordinator import FamilyTasksCoordinator
    from .storage import TaskStorageCollection

_LOGGER = logging.getLogger(__name__)

_UNAVAILABLE_STATES = ("unknown", "unavailable", None)


def _matches(hass: HomeAssistant, trigger: dict, state: State | None) -> bool:
    """Return whether a sensor state satisfies a task's trigger definition."""
    if state is None or state.state in _UNAVAILABLE_STATES:
        return False
    try:
        if trigger["kind"] == TASK_TRIGGER_STATE:
            return condition.state(hass, state, trigger["to_state"])
        return condition.async_numeric_state(
            hass, state, below=trigger.get("below"), above=trigger.get("above")
        )
    except ConditionError:
        # e.g. a numeric_state trigger against a non-numeric sensor value.
        return False


class TaskTriggerListener:
    """Wires sensor state changes to `FamilyTasksCoordinator.async_handle_sensor_trigger`."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: FamilyTasksCoordinator,
        tasks: TaskStorageCollection,
    ) -> None:
        self._hass = hass
        self._coordinator = coordinator
        self._tasks = tasks
        self._unsub_state: CALLBACK_TYPE | None = None
        self._subscribed_entities: set[str] = set()

    @callback
    def async_setup(self) -> None:
        """Subscribe to the entities referenced by the current trigger tasks."""
        self._async_resubscribe()

    async def async_on_tasks_changed(self, _change_set: object) -> None:
        """Re-evaluate subscriptions after a task was created/edited/deleted.

        Registered as a `collection.ChangeSetListener`, which must be
        awaitable, even though resubscribing itself is synchronous.
        """
        self._async_resubscribe()

    @callback
    def async_unload(self) -> None:
        """Tear down the state-change subscription."""
        if self._unsub_state is not None:
            self._unsub_state()
            self._unsub_state = None
        self._subscribed_entities = set()

    @callback
    def _async_resubscribe(self) -> None:
        entities = {
            task["recurrence"]["trigger"]["entity_id"]
            for task in self._tasks.data.values()
            if task["recurrence"]["type"] == RECURRENCE_TRIGGER
            and task["recurrence"].get("trigger")
        }
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
        entity_id = event.data["entity_id"]
        old_state = event.data["old_state"]
        new_state = event.data["new_state"]

        for task_id, task in self._tasks.data.items():
            if not task.get("enabled", True):
                continue
            recurrence = task["recurrence"]
            if recurrence["type"] != RECURRENCE_TRIGGER:
                continue
            trigger = recurrence.get("trigger")
            if not trigger or trigger["entity_id"] != entity_id:
                continue

            # Edge-triggered: only fire on the transition *into* a matching
            # condition, not on every update while it keeps matching (e.g. a
            # numeric sensor hovering above a threshold, or unrelated
            # attribute changes on an already-matching binary_sensor).
            if _matches(self._hass, trigger, new_state) and not _matches(
                self._hass, trigger, old_state
            ):
                _LOGGER.debug(
                    "Sensor trigger fired for task %s via %s", task_id, entity_id
                )
                self._hass.async_create_task(
                    self._coordinator.async_handle_sensor_trigger(task_id)
                )
