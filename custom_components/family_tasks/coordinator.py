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
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .battery import LowBattery, async_compute_low_batteries
from .const import (
    CONF_BATTERY_WARNING_THRESHOLD,
    CONF_COMPLETION_BUTTON_ENTITY_ID,
    CONF_DEFAULT_ROTATION_STRATEGY,
    CONF_MEMBER_REWARDS_OPT_IN,
    CONF_TASK_CREATED_BY_MEMBER_ID,
    CONF_TASK_REQUIRES_CONFIRMATION,
    CONF_WEEKLY_WINNER_BONUS_ENABLED,
    CONF_WEEKLY_WINNER_BONUS_POINTS,
    COORDINATOR_UPDATE_INTERVAL,
    DEFAULT_BATTERY_WARNING_THRESHOLD,
    DEFAULT_OVERDUE_AFTER_MINUTES,
    DEFAULT_ROTATION_STRATEGY,
    DEFAULT_WEEKLY_WINNER_BONUS_ENABLED,
    DEFAULT_WEEKLY_WINNER_BONUS_POINTS,
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
    TASK_KIND_CHECKLIST,
    TASK_KIND_MANDATORY,
    TASK_KIND_STANDARD,
    TASK_STATUS_AWAITING_CONFIRMATION,
    TASK_STATUS_DONE,
    TASK_STATUS_IDLE,
    TASK_STATUS_OVERDUE,
    TASK_STATUS_PENDING,
    WEEKLY_BONUS_TASK_ID,
)
from .storage import (
    BatteryOverrideStorageCollection,
    ChecklistStateStore,
    CompletionLogStore,
    MemberStorageCollection,
    RewardRedemptionStorageCollection,
    TaskStorageCollection,
    TriggerStateStore,
    WeeklyBonusStateStore,
)

_LOGGER = logging.getLogger(__name__)

# WEEKLY_BONUS_TASK_ID now lives in const.py (v0.22) so storage.py's
# ws_list_member_weekly_completions can exclude it too, without an import
# cycle - see the constant's docstring there. Re-exported under its original
# name here since the rest of this module (and its docstrings) still refer to
# it as a coordinator-local concept.


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
    # Every member currently responsible for this occurrence. For every
    # rotation strategy except a "fixed" one with more than one member this
    # is just [assigned_member_id] (or [] if unassigned) - see
    # FamilyTasksCoordinator._assigned_member_ids. A fixed multi-assignee task
    # never actually rotates, so it's shared between all of them at once
    # instead of "belonging" to whichever one happens to sit at
    # rotation.current_index.
    assigned_member_ids: list[str] = field(default_factory=list)
    # v0.25: who may currently act on (complete) this occurrence - normally
    # identical to assigned_member_ids, but with two additions layered on
    # top, neither of which changes assigned_member_ids itself (that field
    # stays the "whose turn/responsibility is this" display value used for
    # the assignee label, per-member open-task counts, and new-task
    # notifications):
    # - every other active MEMBER_ROLE_CHILD member in the household, once
    #   this occurrence is TASK_STATUS_OVERDUE and at least one of its
    #   current assignees is itself a child - see the eligible_member_ids
    #   computation in _async_update_data. Lets a sibling step in on a
    #   sibling's overdue task instead of it just sitting there; whoever
    #   actually completes it is still credited individually (async_add_entry
    #   is always called with the acting member's own id), and since a task's
    #   completion is keyed by (task_id, period_key) rather than per-member,
    #   one sibling completing it resolves the occurrence for both - there is
    #   no separate "done" state per child to reconcile.
    # - a parent completing a task currently assigned to a child is *always*
    #   allowed (not only once overdue) - this needs no special entry here
    #   since async_complete_task never actually checked eligible_member_ids
    #   to begin with (see its docstring); a parent is simply never blocked
    #   server-side. eligible_member_ids only drives the card's UI (which
    #   "Erledigt" buttons/rows it shows), see canAct in
    #   family-tasks-card.js, which separately allows any non-child admin to
    #   act on a child-assigned task regardless of this list.
    eligible_member_ids: list[str] = field(default_factory=list)
    # Only populated for recurrence type "trigger" (see RECURRENCE_TRIGGER):
    # the bound sensor's current state/value and unit of measurement, so the
    # card can show e.g. "aktuell: 18.4 °C" alongside the trigger definition
    # instead of just the entity_id.
    trigger_sensor_value: str | None = None
    trigger_sensor_unit: str | None = None
    # Only populated for a TASK_KIND_CHECKLIST task: every sub-item with its
    # current checked state for this period, as dicts {id, name, checked} -
    # see FamilyTasksCoordinator.async_toggle_subtask.
    subtasks: list[dict] = field(default_factory=list)
    # standard / checklist / mandatory - see TASK_KINDS in const.py. Exposed
    # here (and as a sensor attribute) mainly so an automation can identify a
    # TASK_KIND_MANDATORY task without needing the raw stored task object.
    kind: str = TASK_KIND_STANDARD
    # v0.22: set only for a task a "child" member created for themselves (see
    # CONF_TASK_CREATED_BY_MEMBER_ID in const.py) - the card uses this to
    # hide such a task from everyone except the member it names.
    created_by_member_id: str | None = None


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
    # Current spendable balance for the reward system (v0.9): points_total
    # minus every "points_cost" this member has already redeemed (see
    # RewardRedemptionStorageCollection in storage.py) - never a separately
    # stored/mutated value, always computed fresh from history so it can
    # never drift out of sync. Drives the leaderboard card's balance display
    # and whether a given catalog reward is affordable (WS_API_REWARD_REDEEM
    # in const.py / ws_redeem_reward in storage.py re-derives the same thing
    # server-side before letting a redemption through).
    points_available: int = 0
    # v0.14: whether tick-based screen-time granting should currently be
    # active for this member - True unless they have at least one
    # TASK_KIND_MANDATORY task assigned that is currently TASK_STATUS_OVERDUE
    # (see the screen_time_paused_members computation in
    # FamilyTasksCoordinator._async_update_data). Exposed via a per-member
    # binary_sensor (see binary_sensor.py) for a household's own tick-granting
    # automation to gate on - this integration never grants screen time
    # itself, only this flag. Resumes automatically (no explicit "resume"
    # action) the moment none of their mandatory tasks are overdue anymore;
    # ticks missed while paused are never made up.
    screen_time_grant_active: bool = True


@dataclass(slots=True)
class FamilyTasksData:
    """Snapshot produced on every coordinator refresh."""

    tasks: dict[str, TaskStatusData] = field(default_factory=dict)
    members: dict[str, MemberSummaryData] = field(default_factory=dict)
    # v0.22: household-wide weekly-winner-bonus settings (see
    # CONF_WEEKLY_WINNER_BONUS_ENABLED/...POINTS in const.py), read fresh from
    # the config entry's options on every refresh. Exposed as sensor
    # attributes (see FamilyTasksMemberPointsSensor in sensor.py) purely so
    # the card can show "the weekly winner gets N bonus points" atop the
    # Bestenliste - there is no coordinator-level entity to attach this to
    # otherwise, so it rides along on every member's points sensor (the value
    # is identical on all of them, the card just reads it off whichever one).
    weekly_winner_bonus_enabled: bool = False
    weekly_winner_bonus_points: int = 0
    # v0.23: household-wide default rotation strategy for new tasks (see
    # CONF_DEFAULT_ROTATION_STRATEGY in const.py) - rides along here for the
    # same reason weekly_winner_bonus_enabled/...points do (no dedicated
    # entity to attach a plain options value to). The card reads this to
    # pre-select the right "Rotationstyp" when opening the "+ Aufgabe
    # hinzufügen" form instead of always defaulting to "Reihum".
    default_rotation_strategy: str = DEFAULT_ROTATION_STRATEGY


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
    """Combine a period's date with an optional time-of-day into a datetime.

    due_time is stored (and documented, see storage.py) as "HH:MM", but the
    card's due-time field has used the frontend's own `ha-time-input`
    component since v0.26 instead of a native `<input type="time">` (see
    CHANGELOG) - that component always reports a value with seconds
    ("HH:MM:SS"), and the card normalizes it back down to "HH:MM" before
    saving. Splitting on ":" and only looking at the first two parts (instead
    of the previous str.partition-based parsing, which put everything from
    the second ":" onward - including a "SS" suffix - into what it treated as
    the minutes component and passed to int()) keeps this tolerant of a
    "HH:MM:SS" value too, in case one ever reaches storage directly via the
    websocket API rather than through the card.
    """
    if due_time:
        hour_str, _, rest = due_time.partition(":")
        minute_str = rest.partition(":")[0]
        naive = datetime.combine(
            period_start,
            datetime.min.time().replace(hour=int(hour_str), minute=int(minute_str or 0)),
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
        checklist_state: ChecklistStateStore,
        reward_redemptions: RewardRedemptionStorageCollection,
        weekly_bonus_state: WeeklyBonusStateStore,
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
        self.checklist_state = checklist_state
        self.reward_redemptions = reward_redemptions
        self.weekly_bonus_state = weekly_bonus_state

    async def _async_update_data(self) -> FamilyTasksData:
        now = dt_util.utcnow()
        today = dt_util.now().date()

        # Moved up from further down (was only computed just before the
        # member-summaries loop) so _async_process_weekly_winner_bonus below
        # can use start_of_week too.
        local_now = dt_util.now()
        start_of_today = dt_util.as_utc(dt_util.start_of_local_day(local_now))
        start_of_week = start_of_today - timedelta(days=start_of_today.weekday())
        start_of_month = dt_util.as_utc(
            dt_util.start_of_local_day(local_now.replace(day=1))
        )

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

        # Also raised before the main loop, same reasoning: a bonus awarded
        # this refresh should already be reflected in this same refresh's
        # member_summaries below, not just after a second refresh.
        await self._async_process_weekly_winner_bonus(start_of_week)

        task_statuses: dict[str, TaskStatusData] = {}
        open_tasks_by_member: dict[str, int] = {}
        # Every member with at least one TASK_KIND_MANDATORY task currently
        # TASK_STATUS_OVERDUE and assigned to them - see
        # MemberSummaryData.screen_time_grant_active below.
        screen_time_paused_members: set[str] = set()

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
            assigned_member_ids = self._assigned_member_ids(rotation, member_ids)

            trigger_sensor_value: str | None = None
            trigger_sensor_unit: str | None = None
            if recurrence["type"] == RECURRENCE_TRIGGER:
                trigger_entity_id = (recurrence.get("trigger") or {}).get("entity_id")
                if trigger_entity_id:
                    trigger_entity_state = self.hass.states.get(trigger_entity_id)
                    if trigger_entity_state is not None:
                        trigger_sensor_value = trigger_entity_state.state
                        trigger_sensor_unit = trigger_entity_state.attributes.get(
                            "unit_of_measurement"
                        )

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
                        assigned_member_ids=assigned_member_ids,
                        # Nothing open yet, so no occurrence can be overdue -
                        # eligible_member_ids is just assigned_member_ids,
                        # same as every other idle/non-overdue occurrence.
                        eligible_member_ids=assigned_member_ids,
                        trigger_sensor_value=trigger_sensor_value,
                        trigger_sensor_unit=trigger_sensor_unit,
                        kind=task.get("kind", TASK_KIND_STANDARD),
                        created_by_member_id=task.get(CONF_TASK_CREATED_BY_MEMBER_ID),
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

            # v0.25: once this occurrence is overdue and at least one current
            # assignee is a child, every other active child in the household
            # also becomes eligible to step in and complete it - see
            # eligible_member_ids on TaskStatusData for the full reasoning.
            # Deliberately keyed off "any assignee is a child" rather than
            # "every assignee is a child" so a mixed fixed assignment (e.g. a
            # parent + a child sharing a task) still opens up to the other
            # children too, not just to the household's parents (who could
            # already act on it regardless, per async_complete_task).
            eligible_member_ids = list(assigned_member_ids)
            if status == TASK_STATUS_OVERDUE and any(
                self._member_role(mid) == MEMBER_ROLE_CHILD for mid in assigned_member_ids
            ):
                for other_id, other_member in self.members.data.items():
                    if (
                        other_id not in eligible_member_ids
                        and other_member.get("active", True)
                        and self._member_role(other_id) == MEMBER_ROLE_CHILD
                    ):
                        eligible_member_ids.append(other_id)

            subtasks_status: list[dict] = []
            if task.get("kind") == TASK_KIND_CHECKLIST:
                checked_ids = self.checklist_state.checked_ids(task_id, period_key)
                subtasks_status = [
                    {"id": s["id"], "name": s["name"], "checked": s["id"] in checked_ids}
                    for s in task.get("subtasks", [])
                ]

            if status not in (TASK_STATUS_DONE, TASK_STATUS_IDLE):
                for member_id in assigned_member_ids:
                    open_tasks_by_member[member_id] = open_tasks_by_member.get(member_id, 0) + 1

            if task.get("kind") == TASK_KIND_MANDATORY and status == TASK_STATUS_OVERDUE:
                # See MemberSummaryData.screen_time_grant_active: an overdue
                # mandatory task pauses tick-based screen-time granting for
                # exactly whoever it's currently assigned to, not the whole
                # household.
                screen_time_paused_members.update(assigned_member_ids)

            task_statuses[task_id] = TaskStatusData(
                task_id=task_id,
                name=task["name"],
                icon=task.get("icon"),
                points=task.get("points", 0),
                status=status,
                period_key=period_key,
                due_at=due_at,
                assigned_member_id=assigned_member_id,
                assigned_member_ids=assigned_member_ids,
                eligible_member_ids=eligible_member_ids,
                kind=task.get("kind", TASK_KIND_STANDARD),
                last_completed_by=last_entry.get("completed_by_member_id")
                if last_entry
                else None,
                last_completed_at=dt_util.parse_datetime(last_entry["completed_at"])
                if last_entry
                else None,
                battery_entities=battery_entities,
                trigger_sensor_value=trigger_sensor_value,
                trigger_sensor_unit=trigger_sensor_unit,
                subtasks=subtasks_status,
                created_by_member_id=task.get(CONF_TASK_CREATED_BY_MEMBER_ID),
            )

        # Total points already redeemed for a catalog reward (v0.9), per
        # member - subtracted from points_total below so a member's
        # "available" balance reflects past purchases. See
        # RewardRedemptionStorageCollection in storage.py / _available_points
        # in storage.py, which computes the same thing independently for
        # server-side validation when a redemption is actually attempted.
        redeemed_points: dict[str, int] = {}
        for redemption in self.reward_redemptions.data.values():
            redeemed_member_id = redemption.get("member_id")
            if redeemed_member_id:
                redeemed_points[redeemed_member_id] = redeemed_points.get(
                    redeemed_member_id, 0
                ) + redemption.get("points_cost", 0)

        member_summaries: dict[str, MemberSummaryData] = {}
        for member_id, member in self.members.data.items():
            points_total = self.completions.points_since(
                member_id, datetime.min.replace(tzinfo=dt_util.UTC)
            )
            member_summaries[member_id] = MemberSummaryData(
                member_id=member_id,
                name=member["name"],
                person_entity_id=member.get("person_entity_id"),
                points_today=self.completions.points_since(member_id, start_of_today),
                points_week=self.completions.points_since(member_id, start_of_week),
                points_month=self.completions.points_since(member_id, start_of_month),
                points_total=points_total,
                points_available=points_total - redeemed_points.get(member_id, 0),
                open_tasks=open_tasks_by_member.get(member_id, 0),
                screen_time_grant_active=member_id not in screen_time_paused_members,
            )

        weekly_winner_bonus_enabled = False
        weekly_winner_bonus_points = 0
        # Household-wide default rotation strategy (see
        # CONF_DEFAULT_ROTATION_STRATEGY in const.py) - read fresh from the
        # config entry's options every refresh, same pattern as the weekly-
        # winner-bonus settings right below. Previously this option was only
        # ever written by the options flow and never actually read anywhere,
        # so the card's "+ Aufgabe hinzufügen" form always pre-selected
        # "Reihum" regardless of what a household had configured here - see
        # default_rotation_strategy below and FamilyTasksMemberPointsSensor in
        # sensor.py for how it now reaches the card.
        default_rotation_strategy = DEFAULT_ROTATION_STRATEGY
        if self.config_entry:
            weekly_winner_bonus_enabled = bool(
                self.config_entry.options.get(
                    CONF_WEEKLY_WINNER_BONUS_ENABLED, DEFAULT_WEEKLY_WINNER_BONUS_ENABLED
                )
            )
            weekly_winner_bonus_points = self.config_entry.options.get(
                CONF_WEEKLY_WINNER_BONUS_POINTS, DEFAULT_WEEKLY_WINNER_BONUS_POINTS
            )
            default_rotation_strategy = self.config_entry.options.get(
                CONF_DEFAULT_ROTATION_STRATEGY, DEFAULT_ROTATION_STRATEGY
            )

        return FamilyTasksData(
            tasks=task_statuses,
            members=member_summaries,
            weekly_winner_bonus_enabled=weekly_winner_bonus_enabled,
            weekly_winner_bonus_points=weekly_winner_bonus_points,
            default_rotation_strategy=default_rotation_strategy,
        )

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

        ``member_id`` should be who *actually* completed the task whenever
        that's known (see _async_register_services in __init__.py, which
        resolves it from the calling service call's Context via
        storage.async_member_id_for_context before landing here). Left as
        ``None``, this falls back to ``_assigned_member_id`` - fine for a
        task with a single assignee or a rotation that only ever has one
        "current" member, but for a "fixed" rotation shared by several
        members (see _assigned_member_ids) that fallback always resolves to
        member_ids[0], regardless of which of the assignees actually did it -
        so a caller that *can* identify the acting member (any real user
        action) should always pass it explicitly instead of relying on the
        fallback.
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
            task_name=task.get("name"),
        )

        await self._async_advance_rotation(task_id, task, rotation, member_ids, index)
        if task["recurrence"]["type"] == RECURRENCE_TRIGGER:
            await self.trigger_state.async_clear(task_id)
        await self._async_press_completion_button(task)
        if task["recurrence"]["type"] == RECURRENCE_ONCE:
            # A single, never-repeating occurrence stays permanently resolved
            # the moment it's done - see RECURRENCE_ONCE in const.py - so
            # there is nothing left for it to do sitting around forever
            # showing "Erledigt". Deleting it also lets a battery-alert task
            # (also RECURRENCE_ONCE, see _async_raise_battery_alerts) raise a
            # fresh one the next time that battery goes low again, same as
            # before this cleanup - see _async_raise_battery_alerts's
            # open_alert_entities check, which only looks at tasks still in
            # self.tasks.data.
            await self.checklist_state.async_clear(task_id)
            await self.tasks.async_delete_item(task_id)
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

    def _assigned_member_ids(self, rotation: dict, member_ids: list[str]) -> list[str]:
        """Return every member currently responsible for a task's occurrence.

        Mirrors _assigned_member_id, but a "fixed" rotation with more than
        one member returns all of them instead of just member_ids[0]: a
        fixed multi-assignee task never actually rotates, so it's shared
        between exactly those people rather than "belonging" to one of them
        at a time (see the "Nur eigene Aufgaben" card filter, and the task
        card's assignee display, both of which need this same list instead
        of a single id).
        """
        if not member_ids:
            return []
        strategy = rotation.get("strategy", ROTATION_STRATEGY_ROUND_ROBIN)
        if strategy == ROTATION_STRATEGY_FIXED and len(member_ids) > 1:
            return list(member_ids)
        single = self._assigned_member_id(rotation, member_ids)
        return [single] if single else []

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
                task_name=original_task.get("name"),
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
            await self._async_press_completion_button(original_task)
            if original_task["recurrence"]["type"] == RECURRENCE_ONCE:
                # Same cleanup as the non-confirmation path in
                # async_complete_task - see the comment there.
                await self.checklist_state.async_clear(original_task_id)
                await self.tasks.async_delete_item(original_task_id)

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

    def _points_earned_in_range(
        self, member_id: str, start: datetime, end: datetime
    ) -> int:
        """Sum a member's awarded points within [start, end), for ranking purposes.

        Like CompletionLogStore.points_since, but bounded on both ends and
        deliberately excluding WEEKLY_BONUS_TASK_ID entries - a previous
        weekly-winner bonus is real, spendable points (see
        MemberSummaryData.points_total/points_available, which do include
        it), but must not itself count towards *this* determination, per
        CONF_WEEKLY_WINNER_BONUS_ENABLED in const.py. Excluding by task_id
        rather than by date range is deliberate: a bonus entry's
        "completed_at" timestamp falls at the moment it was awarded (this
        week), even though period_key names the week it was awarded *for*
        (last week) - filtering on task_id sidesteps that mismatch entirely.
        """
        total = 0
        for entry in self.completions.entries:
            if (
                entry["completed_by_member_id"] != member_id
                or entry["skipped"]
                or entry["task_id"] == WEEKLY_BONUS_TASK_ID
            ):
                continue
            completed_at = dt_util.parse_datetime(entry["completed_at"])
            if start <= completed_at < end:
                total += entry["points_awarded"]
        return total

    async def _async_process_weekly_winner_bonus(self, start_of_week: datetime) -> None:
        """Award bonus points to the previous week's point leader(s), once.

        See CONF_WEEKLY_WINNER_BONUS_ENABLED/CONF_WEEKLY_WINNER_BONUS_POINTS
        in const.py: off unless a parent turns it on and sets a bonus > 0.
        Runs on every refresh but only actually does anything the first time
        a refresh happens after a calendar week ends (Monday 00:00 local,
        i.e. "mit Ablauf des Sonntags") - self.weekly_bonus_state tracks the
        last week already processed so this never double-awards, and never
        chains through more than the single most-recently-completed week
        even if the feature was off (or Home Assistant was down) for a
        while - only ever "the week that just ended", never older ones.

        Eligibility mirrors the leaderboard: only members who participate in
        the reward system (CONF_MEMBER_REWARDS_OPT_IN) and are active. Ties
        split the bonus evenly (floor division) rather than each tied member
        getting the full amount; nobody wins with 0 points. The awarded
        points are logged via the normal completion log (so they show up in
        points_total/points_week/points_available/history like any other
        points) under the internal WEEKLY_BONUS_TASK_ID sentinel, which
        _points_earned_in_range excludes so this bonus never counts towards
        determining a *future* week's winner.
        """
        if not self.config_entry:
            return
        options = self.config_entry.options
        if not options.get(
            CONF_WEEKLY_WINNER_BONUS_ENABLED, DEFAULT_WEEKLY_WINNER_BONUS_ENABLED
        ):
            return
        bonus_points = options.get(
            CONF_WEEKLY_WINNER_BONUS_POINTS, DEFAULT_WEEKLY_WINNER_BONUS_POINTS
        )
        if bonus_points <= 0:
            return

        previous_week_start = start_of_week - timedelta(days=7)
        period_key = previous_week_start.date().isoformat()
        if self.weekly_bonus_state.last_awarded_week() == period_key:
            return

        candidates = {
            member_id: self._points_earned_in_range(
                member_id, previous_week_start, start_of_week
            )
            for member_id, member in self.members.data.items()
            if member.get(CONF_MEMBER_REWARDS_OPT_IN, True) and member.get("active", True)
        }
        max_points = max(candidates.values(), default=0)
        if max_points > 0:
            winners = [m for m, p in candidates.items() if p == max_points]
            share = bonus_points // len(winners)
            if share > 0:
                for winner_id in winners:
                    await self.completions.async_add_entry(
                        task_id=WEEKLY_BONUS_TASK_ID,
                        period_key=period_key,
                        member_id=winner_id,
                        points_awarded=share,
                    )
                _LOGGER.debug(
                    "Awarded %s weekly-winner bonus points each to %s for week %s",
                    share,
                    winners,
                    period_key,
                )

        await self.weekly_bonus_state.async_set_last_awarded_week(period_key)

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

    async def _async_press_completion_button(self, task: dict) -> None:
        """Press a task's optional completion button, if it has one.

        See CONF_COMPLETION_BUTTON_ENTITY_ID in const.py - mainly meant for
        "trigger" tasks that mirror a device's own state (e.g. pressing a
        vacuum's "resume cleaning" button once its "needs emptying" task is
        completed). Best-effort: a missing/unavailable button shouldn't
        prevent the task itself from being marked done.
        """
        entity_id = task.get(CONF_COMPLETION_BUTTON_ENTITY_ID)
        if not entity_id:
            return
        try:
            await self.hass.services.async_call(
                "button", "press", {ATTR_ENTITY_ID: entity_id}, blocking=False
            )
        except HomeAssistantError as err:
            _LOGGER.warning("Failed to press completion button %s: %s", entity_id, err)

    async def async_toggle_subtask(
        self, task_id: str, subtask_id: str, member_id: str | None = None
    ) -> None:
        """Check/uncheck one sub-item of a TASK_KIND_CHECKLIST task.

        Mirrors async_handle_sensor_trigger: the "is this task now done"
        decision is made right here, immediately after the toggle, instead of
        as a side effect of _async_update_data being polled - that keeps the
        refresh loop a pure read of current state, with side effects (points,
        rotation, parent confirmation, once-task cleanup) only ever
        triggered by an explicit action, same as async_complete_task itself
        (which this delegates to once every sub-item is checked - ``member_id``
        is passed through unchanged so a checklist task shared between
        several fixed assignees still attributes completion/confirmation to
        whoever actually checked the last box, not just member_ids[0]; see
        async_complete_task's docstring).
        """
        if task_id not in self.tasks.data:
            raise HomeAssistantError(f"Unknown task_id '{task_id}'")

        task = self.tasks.data[task_id]
        if task.get("kind") != TASK_KIND_CHECKLIST:
            raise HomeAssistantError(f"Task '{task_id}' is not a checklist task")

        subtasks = task.get("subtasks", [])
        if not any(s["id"] == subtask_id for s in subtasks):
            raise HomeAssistantError(f"Unknown subtask_id '{subtask_id}' for task '{task_id}'")

        period_key = self._current_period_key(task_id, task)
        if period_key is None:
            raise HomeAssistantError(f"Task '{task_id}' has no open occurrence right now")

        if self.completions.get_last_entry(task_id, period_key) is not None:
            # Already resolved for this period - nothing left to toggle.
            return

        checked = await self.checklist_state.async_toggle(task_id, period_key, subtask_id)

        if subtasks and all(s["id"] in checked for s in subtasks):
            await self.async_complete_task(task_id, member_id)
        else:
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
