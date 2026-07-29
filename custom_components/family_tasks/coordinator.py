"""DataUpdateCoordinator for the Family Tasks integration.

There is no external API to poll. The coordinator's job is to periodically
(and on-demand after a completion) recompute derived, time-dependent state
from the stored task/member definitions and the completion log: which
occurrence of each recurring task is currently due, who it is assigned to,
whether it is overdue, and each member's point totals.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    COORDINATOR_UPDATE_INTERVAL,
    DEFAULT_OVERDUE_AFTER_MINUTES,
    DOMAIN,
    RECURRENCE_TRIGGER,
    ROTATION_STRATEGY_FIXED,
    ROTATION_STRATEGY_RANDOM,
    ROTATION_STRATEGY_ROUND_ROBIN,
    TASK_STATUS_DONE,
    TASK_STATUS_IDLE,
    TASK_STATUS_OVERDUE,
    TASK_STATUS_PENDING,
)
from .storage import (
    CompletionLogStore,
    MemberStorageCollection,
    TaskStorageCollection,
    TriggerStateStore,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class TaskStatusData:
    """Computed, current-period status of a single recurring task."""

    task_id: str
    name: str
    icon: str | None
    points: int
    status: str  # pending / overdue / done
    period_key: str
    due_at: datetime | None
    assigned_member_id: str | None
    last_completed_by: str | None = None
    last_completed_at: datetime | None = None


@dataclass(slots=True)
class MemberSummaryData:
    """Computed summary for a family member."""

    member_id: str
    name: str
    person_entity_id: str | None
    points_today: int
    points_week: int
    points_total: int
    open_tasks: int


@dataclass(slots=True)
class FamilyTasksData:
    """Snapshot produced on every coordinator refresh."""

    tasks: dict[str, TaskStatusData] = field(default_factory=dict)
    members: dict[str, MemberSummaryData] = field(default_factory=dict)


def _current_period_date(recurrence: dict, today: date) -> date:
    """Return the date identifying the current occurrence's period."""
    rtype = recurrence["type"]

    if rtype == "daily":
        return today

    if rtype == "weekly":
        weekdays = recurrence.get("weekdays") or [0]
        for offset in range(7):
            candidate = today - timedelta(days=offset)
            if candidate.weekday() in weekdays:
                return candidate
        return today

    if rtype == "interval_days":
        anchor = date.fromisoformat(recurrence["anchor_date"])
        interval = max(1, recurrence.get("interval", 1))
        delta_days = (today - anchor).days
        period_index = delta_days // interval if delta_days >= 0 else 0
        return anchor + timedelta(days=period_index * interval)

    return today


def _due_at(period_start: date, due_time: str | None) -> datetime:
    """Combine a period's date with an optional time-of-day into a datetime."""
    if due_time:
        hour, _, minute = due_time.partition(":")
        naive = datetime.combine(
            period_start, datetime.min.time().replace(hour=int(hour), minute=int(minute or 0))
        )
    else:
        naive = datetime.combine(period_start, datetime.max.time().replace(microsecond=0))
    # as_utc treats a naive datetime as being in the configured local time zone.
    return dt_util.as_utc(naive)


class FamilyTasksCoordinator(DataUpdateCoordinator[FamilyTasksData]):
    """Coordinates computed task/member state for one config entry."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        tasks: TaskStorageCollection,
        members: MemberStorageCollection,
        completions: CompletionLogStore,
        trigger_state: TriggerStateStore,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=COORDINATOR_UPDATE_INTERVAL,
        )
        self.tasks = tasks
        self.members = members
        self.completions = completions
        self.trigger_state = trigger_state

    async def _async_update_data(self) -> FamilyTasksData:
        now = dt_util.utcnow()
        today = dt_util.now().date()

        task_statuses: dict[str, TaskStatusData] = {}
        open_tasks_by_member: dict[str, int] = {}

        for task_id, task in self.tasks.data.items():
            if not task.get("enabled", True):
                continue

            recurrence = task["recurrence"]
            overdue_after = timedelta(
                minutes=task.get("overdue_after_minutes", DEFAULT_OVERDUE_AFTER_MINUTES)
            )

            rotation = task["rotation"]
            member_ids = rotation.get("member_ids") or []
            assigned_member_id = None
            if member_ids:
                index = rotation.get("current_index", 0) % len(member_ids)
                assigned_member_id = member_ids[index]

            if recurrence["type"] == RECURRENCE_TRIGGER:
                open_occurrence = self.trigger_state.get(task_id)
                if open_occurrence is None:
                    # Never triggered yet (or resolved and waiting for the
                    # next trigger event): nothing due, not counted as open.
                    task_statuses[task_id] = TaskStatusData(
                        task_id=task_id,
                        name=task["name"],
                        icon=task.get("icon"),
                        points=task.get("points", 0),
                        status=TASK_STATUS_IDLE,
                        period_key="",
                        due_at=None,
                        assigned_member_id=assigned_member_id,
                    )
                    continue
                period_key = open_occurrence["period_key"]
                due_at = dt_util.parse_datetime(open_occurrence["triggered_at"])
            else:
                period_start = _current_period_date(recurrence, today)
                period_key = period_start.isoformat()
                due_at = _due_at(period_start, task.get("due_time"))

            last_entry = self.completions.get_last_entry(task_id, period_key)
            if last_entry is not None:
                status = TASK_STATUS_DONE
            elif now > due_at + overdue_after:
                status = TASK_STATUS_OVERDUE
            else:
                status = TASK_STATUS_PENDING

            if status != TASK_STATUS_DONE and assigned_member_id:
                open_tasks_by_member[assigned_member_id] = (
                    open_tasks_by_member.get(assigned_member_id, 0) + 1
                )

            task_statuses[task_id] = TaskStatusData(
                task_id=task_id,
                name=task["name"],
                icon=task.get("icon"),
                points=task.get("points", 0),
                status=status,
                period_key=period_key,
                due_at=due_at,
                assigned_member_id=assigned_member_id,
                last_completed_by=last_entry.get("completed_by_member_id")
                if last_entry
                else None,
                last_completed_at=dt_util.parse_datetime(last_entry["completed_at"])
                if last_entry
                else None,
            )

        start_of_today = dt_util.as_utc(
            dt_util.start_of_local_day(dt_util.now())
        )
        start_of_week = start_of_today - timedelta(days=start_of_today.weekday())

        member_summaries: dict[str, MemberSummaryData] = {}
        for member_id, member in self.members.data.items():
            member_summaries[member_id] = MemberSummaryData(
                member_id=member_id,
                name=member["name"],
                person_entity_id=member.get("person_entity_id"),
                points_today=self.completions.points_since(member_id, start_of_today),
                points_week=self.completions.points_since(member_id, start_of_week),
                points_total=self.completions.points_since(
                    member_id, datetime.min.replace(tzinfo=dt_util.UTC)
                ),
                open_tasks=open_tasks_by_member.get(member_id, 0),
            )

        return FamilyTasksData(tasks=task_statuses, members=member_summaries)

    def _current_period_key(self, task_id: str, task: dict) -> str | None:
        """Return the id of the occurrence currently due, if any.

        For trigger-based tasks this is ``None`` while idle (no sensor event
        has opened an occurrence yet); for calendar-based tasks there is
        always a current period.
        """
        if task["recurrence"]["type"] == RECURRENCE_TRIGGER:
            open_occurrence = self.trigger_state.get(task_id)
            return open_occurrence["period_key"] if open_occurrence else None
        return _current_period_date(task["recurrence"], dt_util.now().date()).isoformat()

    async def async_complete_task(
        self, task_id: str, member_id: str | None = None
    ) -> None:
        """Mark the current occurrence of a task as done and advance rotation."""
        if task_id not in self.tasks.data:
            raise HomeAssistantError(f"Unknown task_id '{task_id}'")

        task = self.tasks.data[task_id]
        period_key = self._current_period_key(task_id, task)
        if period_key is None:
            _LOGGER.debug("Task %s has no open occurrence to complete", task_id)
            return

        if self.completions.get_last_entry(task_id, period_key) is not None:
            _LOGGER.debug("Task %s already completed for period %s", task_id, period_key)
            return

        rotation = task["rotation"]
        member_ids = rotation.get("member_ids") or []
        index = rotation.get("current_index", 0) % len(member_ids) if member_ids else 0
        acting_member_id = member_id or (member_ids[index] if member_ids else None)

        await self.completions.async_add_entry(
            task_id=task_id,
            period_key=period_key,
            member_id=acting_member_id,
            points_awarded=task.get("points", 0),
        )

        await self._async_advance_rotation(task_id, task, rotation, member_ids, index)
        if task["recurrence"]["type"] == RECURRENCE_TRIGGER:
            await self.trigger_state.async_clear(task_id)
        await self.async_request_refresh()

    async def async_skip_task(self, task_id: str) -> None:
        """Skip the current occurrence without awarding points or rotating."""
        if task_id not in self.tasks.data:
            raise HomeAssistantError(f"Unknown task_id '{task_id}'")

        task = self.tasks.data[task_id]
        period_key = self._current_period_key(task_id, task)
        if period_key is None:
            _LOGGER.debug("Task %s has no open occurrence to skip", task_id)
            return

        if self.completions.get_last_entry(task_id, period_key) is not None:
            return

        await self.completions.async_add_entry(
            task_id=task_id,
            period_key=period_key,
            member_id=None,
            points_awarded=0,
            skipped=True,
        )
        if task["recurrence"]["type"] == RECURRENCE_TRIGGER:
            await self.trigger_state.async_clear(task_id)
        await self.async_request_refresh()

    async def async_handle_sensor_trigger(self, task_id: str) -> None:
        """Open a new occurrence for a trigger-based task, unless one is open.

        Called by :class:`~.trigger.TaskTriggerListener` when a bound
        sensor's state satisfies the task's trigger condition. If an
        occurrence is already open (triggered but not yet completed/skipped),
        this is a no-op so a bouncing/still-matching sensor doesn't keep
        creating new occurrences.
        """
        if task_id not in self.tasks.data:
            return
        if self.trigger_state.get(task_id) is not None:
            _LOGGER.debug("Task %s already has an open trigger occurrence", task_id)
            return
        await self.trigger_state.async_activate(task_id, triggered_at=dt_util.utcnow())
        await self.async_request_refresh()

    async def _async_advance_rotation(
        self,
        task_id: str,
        task: dict,
        rotation: dict,
        member_ids: list[str],
        current_index: int,
    ) -> None:
        """Persist the next rotation index, if the strategy calls for it."""
        if not member_ids or len(member_ids) < 2:
            return

        strategy = rotation.get("strategy", ROTATION_STRATEGY_ROUND_ROBIN)
        if strategy == ROTATION_STRATEGY_ROUND_ROBIN:
            new_index = (current_index + 1) % len(member_ids)
        elif strategy == ROTATION_STRATEGY_RANDOM:
            new_index = random.randrange(len(member_ids))
        elif strategy == ROTATION_STRATEGY_FIXED:
            return
        else:
            return

        await self.tasks.async_update_item(
            task_id, {"rotation": {**rotation, "current_index": new_index}}
        )
