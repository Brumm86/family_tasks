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

from .battery import LowBattery, async_compute_low_batteries
from .const import (
    CONF_BATTERY_WARNING_THRESHOLD,
    CONF_TASK_REQUIRES_CONFIRMATION,
    COORDINATOR_UPDATE_INTERVAL,
    DEFAULT_BATTERY_WARNING_THRESHOLD,
    DEFAULT_OVERDUE_AFTER_MINUTES,
    DOMAIN,
    MEMBER_ROLE_CHILD,
    MEMBER_ROLE_PARENT,
    RECURRENCE_BATTERY,
    RECURRENCE_CONFIRMATION,
    RECURRENCE_ONCE,
    RECURRENCE_TRIGGER,
    ROTATION_ONLY_CHILDREN,
    ROTATION_STRATEGY_FIXED,
    ROTATION_STRATEGY_LEAST_POINTS,
    ROTATION_STRATEGY_RANDOM,
    ROTATION_STRATEGY_ROUND_ROBIN,
    TASK_STATUS_AWAITING_CONFIRMATION,
    TASK_STATUS_DONE,
    TASK_STATUS_IDLE,
    TASK_STATUS_OVERDUE,
    TASK_STATUS_PENDING,
)
from .storage import (
    BatteryOverrideStorageCollection,
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
    status: str  # idle / pending / overdue / awaiting_confirmation / done
    period_key: str
    due_at: datetime | None
    assigned_member_id: str | None
    last_completed_by: str | None = None
    last_completed_at: datetime | None = None
    # Only populated for recurrence type "battery" (see RECURRENCE_BATTERY):
    # every currently monitored battery at/below its warning threshold, as
    # dicts {entity_id, name, level, threshold} - see battery.LowBattery.
    battery_entities: list[dict] = field(default_factory=list)


@dataclass(slots=True)
class MemberSummaryData:
    """Computed summary for a family member."""

    member_id: str
    name: str
    person_entity_id: str | None
    points_today: int
    points_week: int
    points_month: int
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

    if rtype == "daily" or rtype == RECURRENCE_BATTERY:
        # A battery task's period is daily, same as "daily" - but see
        # _async_update_data, which downgrades a due occurrence back to
        # TASK_STATUS_IDLE unless a monitored battery is currently low.
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

    if rtype == RECURRENCE_ONCE:
        # A single, never-repeating occurrence: the period is always the
        # task's anchor date itself, regardless of "today" - so once it's
        # completed/skipped for that date, the (task_id, period_key) pair
        # never comes up again and the task stays "done" for good.
        return date.fromisoformat(recurrence["anchor_date"])

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
        battery_overrides: BatteryOverrideStorageCollection,
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
        self.battery_overrides = battery_overrides

    async def _async_update_data(self) -> FamilyTasksData:
        now = dt_util.utcnow()
        today = dt_util.now().date()

        # Computed once per refresh and shared by every recurrence-"battery"
        # task below (see RECURRENCE_BATTERY in const.py) - which batteries
        # currently count as "low" doesn't depend on any single task.
        default_battery_threshold = DEFAULT_BATTERY_WARNING_THRESHOLD
        if self.config_entry:
            default_battery_threshold = self.config_entry.options.get(
                CONF_BATTERY_WARNING_THRESHOLD, DEFAULT_BATTERY_WARNING_THRESHOLD
            )
        low_batteries = async_compute_low_batteries(
            self.hass, self.battery_overrides, default_battery_threshold
        )
        # Raised *before* the main loop below so a newly-created alert task
        # is already reflected in this same refresh's task_statuses, instead
        # of only appearing after the change-set listener triggers a second
        # one (see _async_raise_battery_alerts).
        await self._async_raise_battery_alerts(low_batteries)

        task_statuses: dict[str, TaskStatusData] = {}
        open_tasks_by_member: dict[str, int] = {}

        # Original (task_id, period_key) occurrences that currently have an
        # open, not-yet-resolved parent confirmation task raised against them
        # (see RECURRENCE_CONFIRMATION in const.py / async_complete_task
        # below). Precomputed so the main loop below can flag those
        # occurrences as "awaiting_confirmation" regardless of which order
        # tasks happen to be iterated in.
        pending_confirmations: dict[tuple[str, str], str] = {}
        for confirmation_task_id, confirmation_task in self.tasks.data.items():
            confirms = confirmation_task.get("confirms")
            if confirms and self.trigger_state.get(confirmation_task_id) is not None:
                pending_confirmations[(confirms["task_id"], confirms["period_key"])] = (
                    confirmation_task_id
                )

        for task_id, task in self.tasks.data.items():
            if not task.get("enabled", True):
                continue

            recurrence = task["recurrence"]
            overdue_after = timedelta(
                minutes=task.get("overdue_after_minutes", DEFAULT_OVERDUE_AFTER_MINUTES)
            )

            rotation = task["rotation"]
            member_ids = rotation.get("member_ids") or []
            assigned_member_id = self._assigned_member_id(rotation, member_ids)

            if recurrence["type"] in (RECURRENCE_TRIGGER, RECURRENCE_CONFIRMATION):
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
            elif (task_id, period_key) in pending_confirmations:
                status = TASK_STATUS_AWAITING_CONFIRMATION
            elif now > due_at + overdue_after:
                status = TASK_STATUS_OVERDUE
            else:
                status = TASK_STATUS_PENDING

            battery_entities: list[dict] = []
            if recurrence["type"] == RECURRENCE_BATTERY:
                battery_entities = [low_battery.as_dict() for low_battery in low_batteries]
                if status in (TASK_STATUS_PENDING, TASK_STATUS_OVERDUE) and not battery_entities:
                    # Nothing to charge/swap right now - the task isn't
                    # "due", it's idle until a monitored battery drops to or
                    # below its warning threshold.
                    status = TASK_STATUS_IDLE

            if status not in (TASK_STATUS_DONE, TASK_STATUS_IDLE) and assigned_member_id:
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
                battery_entities=battery_entities,
            )

        local_now = dt_util.now()
        start_of_today = dt_util.as_utc(dt_util.start_of_local_day(local_now))
        start_of_week = start_of_today - timedelta(days=start_of_today.weekday())
        start_of_month = dt_util.as_utc(
            dt_util.start_of_local_day(local_now.replace(day=1))
        )

        member_summaries: dict[str, MemberSummaryData] = {}
        for member_id, member in self.members.data.items():
            member_summaries[member_id] = MemberSummaryData(
                member_id=member_id,
                name=member["name"],
                person_entity_id=member.get("person_entity_id"),
                points_today=self.completions.points_since(member_id, start_of_today),
                points_week=self.completions.points_since(member_id, start_of_week),
                points_month=self.completions.points_since(member_id, start_of_month),
                points_total=self.completions.points_since(
                    member_id, datetime.min.replace(tzinfo=dt_util.UTC)
                ),
                open_tasks=open_tasks_by_member.get(member_id, 0),
            )

        return FamilyTasksData(tasks=task_statuses, members=member_summaries)

    def _current_period_key(self, task_id: str, task: dict) -> str | None:
        """Return the id of the occurrence currently due, if any.

        For trigger-based (and confirmation) tasks this is ``None`` while
        idle (no sensor event / confirmation request has opened an occurrence
        yet); for calendar-based tasks there is always a current period.
        """
        if task["recurrence"]["type"] in (RECURRENCE_TRIGGER, RECURRENCE_CONFIRMATION):
            open_occurrence = self.trigger_state.get(task_id)
            return open_occurrence["period_key"] if open_occurrence else None
        return _current_period_date(task["recurrence"], dt_util.now().date()).isoformat()

    async def async_complete_task(
        self, task_id: str, member_id: str | None = None
    ) -> None:
        """Mark the current occurrence of a task as done and advance rotation.

        Two special cases:
        - If ``task_id`` is itself an auto-generated parent confirmation task
          (``task["confirms"]`` is set), completing it finalizes the child's
          original claim instead of logging a completion for itself.
        - If the member who would act on a normal task has role "child", the
          completion is not logged yet; instead a confirmation task is raised
          for the household's parents (see ``_async_request_confirmation``).
        """
        if task_id not in self.tasks.data:
            raise HomeAssistantError(f"Unknown task_id '{task_id}'")

        task = self.tasks.data[task_id]

        confirms = task.get("confirms")
        if confirms:
            await self._async_finalize_confirmation(task_id, confirms)
            await self.async_request_refresh()
            return

        period_key = self._current_period_key(task_id, task)
        if period_key is None:
            _LOGGER.debug("Task %s has no open occurrence to complete", task_id)
            return

        if self.completions.get_last_entry(task_id, period_key) is not None:
            _LOGGER.debug("Task %s already completed for period %s", task_id, period_key)
            return

        if self._has_open_confirmation(task_id, period_key):
            _LOGGER.debug(
                "Task %s already has an open parent confirmation for period %s",
                task_id,
                period_key,
            )
            return

        rotation = task["rotation"]
        member_ids = rotation.get("member_ids") or []
        index = rotation.get("current_index", 0) % len(member_ids) if member_ids else 0
        acting_member_id = member_id or self._assigned_member_id(rotation, member_ids)

        if acting_member_id and self._member_role(acting_member_id) == MEMBER_ROLE_CHILD:
            requires_confirmation = task.get(CONF_TASK_REQUIRES_CONFIRMATION)
            if requires_confirmation is None:
                # Legacy/default behavior: a task assigned to a child always
                # needs a parent's sign-off unless the task explicitly says
                # otherwise (see CONF_TASK_REQUIRES_CONFIRMATION in const.py -
                # only self-created child tasks currently set this to False).
                requires_confirmation = True
            if requires_confirmation:
                await self._async_request_confirmation(
                    task, task_id, period_key, acting_member_id
                )
                await self.async_request_refresh()
                return

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
        """Skip the current occurrence without awarding points or rotating.

        For an auto-generated parent confirmation task, skipping means the
        parent *rejects* the child's claim: the confirmation task is dropped
        without finalizing anything, so the original task falls back to its
        normal pending/overdue state and the child can complete it again.
        """
        if task_id not in self.tasks.data:
            raise HomeAssistantError(f"Unknown task_id '{task_id}'")

        task = self.tasks.data[task_id]

        if task.get("confirms"):
            await self.trigger_state.async_clear(task_id)
            await self.tasks.async_delete_item(task_id)
            await self.async_request_refresh()
            return

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

    def _member_role(self, member_id: str) -> str:
        member = self.members.data.get(member_id)
        return member.get("role", MEMBER_ROLE_PARENT) if member else MEMBER_ROLE_PARENT

    def _assigned_member_id(self, rotation: dict, member_ids: list[str]) -> str | None:
        """Return who a task's next/current occurrence is assigned to.

        For every strategy except "least_points" this is simply
        ``member_ids[current_index]``. "least_points" instead recomputes the
        assignee fresh every time from the completion log - see
        ``_member_with_least_points`` - so it always reflects the current
        point standings instead of a stored index.
        """
        if not member_ids:
            return None
        strategy = rotation.get("strategy", ROTATION_STRATEGY_ROUND_ROBIN)
        if strategy == ROTATION_STRATEGY_LEAST_POINTS:
            return self._member_with_least_points(
                member_ids, rotation.get(ROTATION_ONLY_CHILDREN, False)
            )
        index = rotation.get("current_index", 0) % len(member_ids)
        return member_ids[index]

    def _member_with_least_points(
        self, member_ids: list[str], only_children: bool
    ) -> str | None:
        """Pick whoever in member_ids currently has the fewest (all-time) points.

        If only_children is set, the comparison is narrowed to those
        candidates with role "child" - falling back to the full pool if none
        of them are children, so the strategy still assigns someone rather
        than silently picking nobody.
        """
        if not member_ids:
            return None
        candidates = member_ids
        if only_children:
            children = [m for m in member_ids if self._member_role(m) == MEMBER_ROLE_CHILD]
            if children:
                candidates = children
        since = datetime.min.replace(tzinfo=dt_util.UTC)
        return min(candidates, key=lambda m: self.completions.points_since(m, since))

    def _has_open_confirmation(self, task_id: str, period_key: str) -> bool:
        """Whether an unresolved parent confirmation is already open for this occurrence."""
        for confirmation_task_id, confirmation_task in self.tasks.data.items():
            confirms = confirmation_task.get("confirms")
            if (
                confirms
                and confirms["task_id"] == task_id
                and confirms["period_key"] == period_key
                and self.trigger_state.get(confirmation_task_id) is not None
            ):
                return True
        return False

    async def _async_request_confirmation(
        self, task: dict, task_id: str, period_key: str, child_member_id: str
    ) -> None:
        """Raise an auto-generated task for the household's parents.

        Completing it finalizes the child's claim (points + rotation);
        skipping it rejects the claim. See RECURRENCE_CONFIRMATION in
        const.py for why this reuses the trigger-task idle/open machinery.
        """
        child = self.members.data.get(child_member_id)
        child_name = child["name"] if child else child_member_id
        parent_ids = [
            mid
            for mid, member in self.members.data.items()
            if self._member_role(mid) == MEMBER_ROLE_PARENT and member.get("active", True)
        ]

        confirmation_payload: dict = {
            "name": f"Bestätigen: {task['name']} ({child_name})",
            "points": 0,
            "enabled": True,
            "recurrence": {"type": RECURRENCE_CONFIRMATION},
            "rotation": {"member_ids": parent_ids, "strategy": ROTATION_STRATEGY_FIXED},
            "confirms": {
                "task_id": task_id,
                "period_key": period_key,
                "member_id": child_member_id,
            },
        }
        if task.get("icon"):
            confirmation_payload["icon"] = task["icon"]

        confirmation_task = await self.tasks.async_create_item(confirmation_payload)
        await self.trigger_state.async_activate(
            confirmation_task["id"], triggered_at=dt_util.utcnow()
        )
        _LOGGER.debug(
            "Raised parent confirmation task %s for %s's completion of %s",
            confirmation_task["id"],
            child_name,
            task_id,
        )

    async def _async_finalize_confirmation(self, confirmation_task_id: str, confirms: dict) -> None:
        """A parent confirmed: log the child's completion, then drop the confirmation task."""
        original_task_id = confirms["task_id"]
        period_key = confirms["period_key"]
        child_member_id = confirms["member_id"]

        original_task = self.tasks.data.get(original_task_id)
        if original_task is not None and self.completions.get_last_entry(
            original_task_id, period_key
        ) is None:
            await self.completions.async_add_entry(
                task_id=original_task_id,
                period_key=period_key,
                member_id=child_member_id,
                points_awarded=original_task.get("points", 0),
            )
            rotation = original_task["rotation"]
            member_ids = rotation.get("member_ids") or []
            index = (
                rotation.get("current_index", 0) % len(member_ids) if member_ids else 0
            )
            await self._async_advance_rotation(
                original_task_id, original_task, rotation, member_ids, index
            )
            if original_task["recurrence"]["type"] == RECURRENCE_TRIGGER:
                await self.trigger_state.async_clear(original_task_id)

        await self.trigger_state.async_clear(confirmation_task_id)
        await self.tasks.async_delete_item(confirmation_task_id)

    async def _async_raise_battery_alerts(self, low_batteries: list[LowBattery]) -> None:
        """Auto-create a one-time task for every battery that just went low.

        Mirrors the parent-confirmation auto-task pattern above
        (_async_request_confirmation): rather than requiring an admin to set
        up and assign a dedicated "battery"-recurrence task (still supported,
        see RECURRENCE_BATTERY), every monitored battery currently at/below
        its warning threshold - or, for a binary_sensor, currently reporting
        low - raises its own RECURRENCE_ONCE task naming exactly that
        battery, assigned to every family member linked to a Home Assistant
        admin account.

        Tagged with "battery_alert" (mirrors "confirms" on parent-
        confirmation tasks) so a battery that stays low doesn't get a fresh
        task every refresh: only once a battery's previous alert task has
        been resolved (completed or skipped) does the next refresh raise a
        new one for it.
        """
        if not low_batteries:
            return

        open_alert_entities: set[str] = set()
        for task_id, task in self.tasks.data.items():
            alert = task.get("battery_alert")
            if not alert:
                continue
            anchor_date = task.get("recurrence", {}).get("anchor_date")
            if anchor_date and self.completions.get_last_entry(task_id, anchor_date) is None:
                open_alert_entities.add(alert["entity_id"])

        newly_low = [b for b in low_batteries if b.entity_id not in open_alert_entities]
        if not newly_low:
            return

        member_ids = await self._async_admin_member_ids()
        today = dt_util.now().date().isoformat()

        for battery in newly_low:
            if battery.level is not None:
                name = f"Batterie wechseln: {battery.name} ({battery.level:g}%)"
            else:
                name = f"Batterie prüfen: {battery.name}"
            payload: dict = {
                "name": name,
                "points": 0,
                "icon": "mdi:battery-alert",
                "enabled": True,
                "recurrence": {"type": RECURRENCE_ONCE, "anchor_date": today},
                "rotation": {"member_ids": member_ids, "strategy": ROTATION_STRATEGY_FIXED},
                "battery_alert": {"entity_id": battery.entity_id},
            }
            await self.tasks.async_create_item(payload)
            _LOGGER.debug("Raised battery alert task for %s", battery.entity_id)

    async def _async_admin_member_ids(self) -> list[str]:
        """Family members linked (via person_entity_id) to a HA admin account.

        Mirrors storage._member_id_for_user's person-entity lookup, just
        checked against every admin user instead of one specific caller -
        there is no notion of "admin" at the family-member level otherwise,
        only the underlying Home Assistant account.
        """
        try:
            users = await self.hass.auth.async_get_users()
        except AttributeError:
            return []
        admin_user_ids = {user.id for user in users if user.is_admin}
        if not admin_user_ids:
            return []
        member_ids: list[str] = []
        for member_id, member in self.members.data.items():
            person_entity_id = member.get("person_entity_id")
            if not person_entity_id:
                continue
            state = self.hass.states.get(person_entity_id)
            if state is not None and state.attributes.get("user_id") in admin_user_ids:
                member_ids.append(member_id)
        return member_ids

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
