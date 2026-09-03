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

v0.34: a trigger definition may also carry ``"auto_complete_on_normalize":
True`` (see ``TASK_TRIGGER_STATE_SCHEMA``/``TASK_TRIGGER_NUMERIC_STATE_SCHEMA``
in storage.py). When set, the *reverse* edge - the sensor transitioning back
out of the matching condition it was opened for, e.g. "Mülleimer leeren"'s
bin sensor reporting empty again - asks the coordinator to complete that
open occurrence automatically instead of waiting for someone to press
"Erledigt" by hand. Off by default; a task with no "trigger" or without the
flag behaves exactly as before.

v0.42: a "numeric_state" trigger may also carry ``"buffer_minutes"`` (> 0) -
a numeric sensor like a soil-moisture probe can wobble right around its
threshold, so a plain edge-trigger would open (and, with
auto_complete_on_normalize, immediately re-close) an occurrence every time
it does. When set, entering the matching condition doesn't open an
occurrence right away - it starts a debounce timer instead (see
``TaskTriggerListener._pending_open_timers`` below), and the occurrence only
actually opens once the value has stayed continuously on the matching side
of the threshold for that whole duration. Leaving the condition again before
the timer fires cancels it - "der Wert muss dauerhaft unter/über der
Schwelle bleiben, bevor die Aufgabe erstellt wird" - so a value that
oscillates in and out never accumulates partial credit toward the buffer;
each new entry starts the buffer over. 0 (the default) keeps the pre-v0.42
behavior of firing on the first matching edge. Not offered for a "state"
trigger.
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
from homeassistant.helpers.event import async_call_later, async_track_state_change_event

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
        # v0.42: pending "buffer_minutes" debounce timers, keyed by task_id -
        # see the module docstring's "Sicherheitspuffer" section and
        # _async_on_state_changed below. Only ever holds an entry for a task
        # that's currently mid-buffer (waiting to see if the matching
        # condition holds); cancelled and removed the moment the condition
        # breaks again, the timer actually fires, or the listener unloads.
        self._pending_open_timers: dict[str, CALLBACK_TYPE] = {}

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
        # v0.42: also drop every still-pending "buffer_minutes" debounce
        # timer - nothing should fire after this listener is gone.
        for cancel in self._pending_open_timers.values():
            cancel()
        self._pending_open_timers = {}

    @callback
    def _async_cancel_pending_open(self, task_id: str) -> None:
        """Cancel task_id's pending buffer_minutes timer, if any (v0.42)."""
        cancel = self._pending_open_timers.pop(task_id, None)
        if cancel is not None:
            cancel()

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

            # Edge-triggered: only fire on the transition *into* (or, for
            # auto-complete, back *out of* - see the module docstring) a
            # matching condition, not on every update while it keeps
            # matching (e.g. a numeric sensor hovering above a threshold, or
            # unrelated attribute changes on an already-matching
            # binary_sensor).
            now_matches = _matches(self._hass, trigger, new_state)
            was_matching = _matches(self._hass, trigger, old_state)

            if now_matches and not was_matching:
                # v0.42: "buffer_minutes" (numeric_state triggers only - see
                # TASK_TRIGGER_NUMERIC_STATE_SCHEMA in storage.py) delays the
                # actual open by that many minutes instead of firing on this
                # very edge, and only if the condition is *still* matching
                # once the delay elapses (re-verified in
                # _async_fire_buffered_open below) - see the module
                # docstring. 0/absent (every "state" trigger, and a
                # numeric_state one that never set a buffer) keeps firing
                # immediately, unchanged from before v0.42.
                buffer_minutes = trigger.get("buffer_minutes", 0)
                if buffer_minutes:
                    _LOGGER.debug(
                        "Sensor trigger for task %s via %s matched - "
                        "starting %s-minute buffer before opening",
                        task_id,
                        entity_id,
                        buffer_minutes,
                    )
                    # Restart, not stack: a task that flickered out and back
                    # in already had its old timer cancelled by the
                    # was_matching branch below, so this only ever replaces
                    # an already-cancelled/nonexistent entry - defensive
                    # cancel here regardless, in case of a second matching
                    # state-change event without an intervening non-matching
                    # one (e.g. an attribute-only update on the same value).
                    self._async_cancel_pending_open(task_id)
                    self._pending_open_timers[task_id] = async_call_later(
                        self._hass,
                        buffer_minutes * 60,
                        self._make_buffered_open_callback(task_id, entity_id, trigger),
                    )
                else:
                    _LOGGER.debug(
                        "Sensor trigger fired for task %s via %s", task_id, entity_id
                    )
                    self._hass.async_create_task(
                        self._coordinator.async_handle_sensor_trigger(task_id)
                    )
            elif was_matching and not now_matches:
                # v0.42: the condition broke before any pending buffer timer
                # fired - the streak is over, so it must not open once the
                # original duration elapses; a later re-entry starts a fresh
                # buffer from zero (see _async_cancel_pending_open).
                self._async_cancel_pending_open(task_id)
                if trigger.get("auto_complete_on_normalize", False):
                    _LOGGER.debug(
                        "Sensor normalized for task %s via %s, auto-completing",
                        task_id,
                        entity_id,
                    )
                    self._hass.async_create_task(
                        self._coordinator.async_handle_sensor_normalized(task_id)
                    )

    def _make_buffered_open_callback(self, task_id: str, entity_id: str, trigger: dict):
        """Build the async_call_later callback for task_id's buffer timer (v0.42).

        Captures task_id/entity_id/trigger by value (as arguments, not by
        closing over the loop variables in _async_on_state_changed, which
        would all share the *last* iteration's values by the time any timer
        actually fires).
        """

        @callback
        def _fire(_now) -> None:
            self._pending_open_timers.pop(task_id, None)
            # Re-verify rather than trusting the buffer alone: the entity
            # could have been removed/gone unavailable during the wait, or -
            # belt and braces - some update this listener didn't see as a
            # clean was_matching/now_matches transition. async_handle_sensor_
            # trigger itself is also a no-op for a task_id no longer in
            # storage (deleted mid-buffer) or one that already has an open
            # occurrence.
            current_state = self._hass.states.get(entity_id)
            if not _matches(self._hass, trigger, current_state):
                _LOGGER.debug(
                    "Buffer for task %s via %s elapsed but condition no "
                    "longer matches - not opening",
                    task_id,
                    entity_id,
                )
                return
            _LOGGER.debug(
                "Buffer for task %s via %s elapsed, still matching - opening",
                task_id,
                entity_id,
            )
            self._hass.async_create_task(
                self._coordinator.async_handle_sensor_trigger(task_id)
            )

        return _fire
