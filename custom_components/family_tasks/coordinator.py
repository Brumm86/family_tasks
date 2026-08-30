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

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .battery import LowBattery, async_compute_low_batteries
from .const import (
    CLAIM_PENALTY_POINTS,
    CLAIM_RESERVATION_MINUTES,
    COIN_REASON_MILESTONE_150,
    COIN_REASON_MILESTONE_200,
    COIN_REASON_STREAK_150,
    COIN_REASON_STREAK_200,
    COIN_REASON_WEEKLY_CONVERSION,
    CONF_BATTERY_ALERT_AUTO_COMPLETE_ON_RECOVERY,
    CONF_BATTERY_WARNING_THRESHOLD,
    CONF_COMPLETION_BUTTON_ENTITY_ID,
    CONF_DEFAULT_ROTATION_STRATEGY,
    CONF_MEMBER_NOTIFY_SERVICE,
    CONF_MEMBER_PAUSED,
    CONF_MEMBER_REWARDS_OPT_IN,
    CONF_MILESTONE_150_BONUS_COINS,
    CONF_MILESTONE_200_BONUS_COINS,
    CONF_STREAK_150_BONUS_COINS,
    CONF_STREAK_200_BONUS_COINS,
    CONF_STREAK_BONUS_REQUIRED_WEEKS,
    CONF_TASK_CREATED_BY_MEMBER_ID,
    CONF_TASK_REQUIRES_CONFIRMATION,
    CONF_TASK_VACATION_BEHAVIOR,
    CONF_WEEKLY_PROGRESS_GOAL_POINTS,
    CONFIRMATION_REJECTION_PENALTY_POINTS,
    COORDINATOR_UPDATE_INTERVAL,
    DEFAULT_BATTERY_ALERT_AUTO_COMPLETE_ON_RECOVERY,
    DEFAULT_BATTERY_WARNING_THRESHOLD,
    DEFAULT_MILESTONE_150_BONUS_COINS,
    DEFAULT_MILESTONE_200_BONUS_COINS,
    DEFAULT_OVERDUE_AFTER_MINUTES,
    DEFAULT_ROTATION_STRATEGY,
    DEFAULT_STREAK_150_BONUS_COINS,
    DEFAULT_STREAK_200_BONUS_COINS,
    DEFAULT_STREAK_BONUS_REQUIRED_WEEKS,
    DEFAULT_WEEKLY_PROGRESS_GOAL_POINTS,
    DOMAIN,
    EVENT_TASK_REJECTED,
    MANUAL_POINTS_TASK_ID,
    MEMBER_ROLE_CHILD,
    MEMBER_ROLE_PARENT,
    PROGRESS_BAND_TICK_ADJUSTMENT_MINUTES,
    RECURRENCE_BATTERY,
    RECURRENCE_CONFIRMATION,
    RECURRENCE_ONCE,
    RECURRENCE_TRIGGER,
    ROTATION_ONLY_CHILDREN,
    ROTATION_STRATEGY_FIXED,
    ROTATION_STRATEGY_LEAST_POINTS,
    ROTATION_STRATEGY_RANDOM,
    ROTATION_STRATEGY_ROUND_ROBIN,
    TASK_KIND_MANDATORY,
    TASK_KIND_STANDARD,
    TASK_STATUS_AWAITING_CONFIRMATION,
    TASK_STATUS_DONE,
    TASK_STATUS_IDLE,
    TASK_STATUS_OVERDUE,
    TASK_STATUS_PENDING,
    TASK_STATUS_UPCOMING,
    VACATION_BEHAVIOR_PAUSE,
    VACATION_BEHAVIOR_SHOW,
)
from .storage import (
    BatteryOverrideStorageCollection,
    ChecklistStateStore,
    ClaimStateStore,
    CoinLedgerStore,
    CoinSystemStateStore,
    CompletionLogStore,
    MemberStorageCollection,
    MilestoneBonusStateStore,
    RewardRedemptionStorageCollection,
    StreakBonusStateStore,
    TaskStorageCollection,
    TriggerStateStore,
    VacationModeStateStore,
    WeeklyCoinConversionStateStore,
    coins_from_task_points,
)

_LOGGER = logging.getLogger(__name__)

# v0.36: MILESTONE_BONUS_1_TASK_ID/MILESTONE_BONUS_2_TASK_ID/
# POINTS_CORRECTION_TASK_ID/STREAK_BONUS_TASK_ID are retired (the coin-bonus
# system below credits CoinLedgerStore directly instead of logging a
# completion-log entry) but still live in const.py so storage.py's
# ws_list_member_weekly_completions can keep excluding old entries under
# those sentinels from a household's pre-v0.36 history - see the constants'
# docstrings there. Nothing in this module needs them directly any more.


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
    # v0.27: the actual clock moment this occurrence flips from pending to
    # TASK_STATUS_OVERDUE (see the `now > deadline_at` check and
    # _deadline_at() in _async_update_data) - since v0.39 usually the task's
    # own absolute "Überfällig ab" time-of-day (task["overdue_time"]) on the
    # period's date, falling back to the legacy Karenzzeit *duration*
    # (overdue_after_minutes) added to due_at for a task that predates that
    # field. Exposed as a real timestamp so the card can show each task's
    # "Zu erledigen bis HH:MM" without working it out by hand. None wherever
    # due_at itself is None (recurrence "trigger"/"confirmation" with no open
    # occurrence yet).
    deadline_at: datetime | None = None
    # v0.27: "Annehmen" reservation state - see ClaimStateStore in storage.py
    # and FamilyTasksCoordinator.async_claim_task/_async_expire_claim. While
    # claimed_by_member_id is set, eligible_member_ids above is narrowed down
    # to exactly that one member (see the claim handling in
    # _async_update_data) - nobody else may claim or complete the occurrence
    # until claim_expires_at passes, at which point the claimant loses
    # CLAIM_PENALTY_POINTS and the next refresh finds no active claim again,
    # reopening it for the normal eligible_member_ids set. Both None
    # whenever there is no active claim.
    claimed_by_member_id: str | None = None
    claim_expires_at: datetime | None = None
    # Whether "Annehmen" should be offered at all right now - true only when
    # nobody has already claimed this occurrence *and* more than one member
    # is currently eligible to act on it (see eligible_member_ids); claiming
    # a task only one person could ever do anyway would reserve nothing.
    claimable: bool = False
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
    # - v0.30: every active MEMBER_ROLE_CHILD member, for the entire time an
    #   "Aufgabenpool" occurrence is pending or overdue (not just once
    #   overdue) - see is_pool_task in _async_update_data. Such an occurrence
    #   starts with assigned_member_ids always empty (no fixed assignee, no
    #   rotation), so without this nobody would ever be eligible to claim or
    #   complete it at all.
    eligible_member_ids: list[str] = field(default_factory=list)
    # Only populated for recurrence type "trigger" (see RECURRENCE_TRIGGER):
    # the bound sensor's current state/value and unit of measurement, so the
    # card can show e.g. "aktuell: 18.4 °C" alongside the trigger definition
    # instead of just the entity_id.
    trigger_sensor_value: str | None = None
    trigger_sensor_unit: str | None = None
    # Only populated for a task that has a checklist (task["subtasks"] is
    # non-empty - see const.py's "Task kinds / checklists" section; no longer
    # tied to a "kind" of its own since v0.39): every sub-item with its
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
    # v0.32: "show"/"pause" - what this task does while the household-wide
    # Urlaubsmodus switch is on, see CONF_TASK_VACATION_BEHAVIOR in const.py.
    # Exposed so the card's task-edit form can pre-fill the current choice.
    vacation_behavior: str = VACATION_BEHAVIOR_SHOW
    # v0.32: a parent's free-text note left the last time this task's claim
    # was rejected ("Ablehnen"), and when - see async_skip_task in
    # coordinator.py. Both None once the child has acted on the task again
    # (a fresh completion or confirmation request clears them).
    last_rejection_note: str | None = None
    last_rejection_at: datetime | None = None


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
    # v0.36: current balance in the new reward-shop currency, "Münzen" -
    # replaces the old points_available entirely (the point shop no longer
    # exists; points now only ever drive the weekly-progress bar, see
    # points_week below). Two components, summed: storage.coins_from_task_points
    # (task points earned *beyond* CONF_WEEKLY_PROGRESS_GOAL_POINTS in a
    # calendar week, for every week since CoinSystemStateStore.started_at -
    # the v0.36 upgrade cutover, so nobody's historical points retroactively
    # convert) plus FamilyTasksCoordinator.coin_ledger's own balance (manual
    # milestone/streak coin bonuses credited, and past reward redemptions
    # debited - see CoinLedgerStore in storage.py). Never a separately
    # stored/mutated value itself, always computed fresh from history so it
    # can never drift out of sync - same "recompute, don't store" pattern the
    # old points_available used. Drives the reward-shop balance display and
    # whether a given catalog reward is affordable (WS_API_REWARD_REDEEM in
    # const.py / ws_redeem_reward in storage.py re-derives the same thing
    # server-side before letting a redemption through).
    coins_available: int = 0
    # v0.14: whether tick-based screen-time granting should currently be
    # active for this member - True unless they have at least one
    # TASK_KIND_MANDATORY task assigned whose deadline (due_at +
    # overdue_after_minutes) has passed and that isn't TASK_STATUS_DONE yet
    # (see the screen_time_paused_members computation in
    # FamilyTasksCoordinator._async_update_data). Exposed via a per-member
    # binary_sensor (see binary_sensor.py) for a household's own tick-granting
    # automation to gate on - this integration never grants screen time
    # itself, only this flag. Resumes automatically (no explicit "resume"
    # action) the moment none of their mandatory tasks are overdue anymore;
    # ticks missed while paused are never made up.
    # v0.34: this also covers a mandatory task a child has already marked
    # done but that's still TASK_STATUS_AWAITING_CONFIRMATION past its
    # deadline - a child's own completion claim doesn't lift the pause by
    # itself, only an actual parent confirmation (or a task that needed none
    # to begin with) does.
    screen_time_grant_active: bool = True
    # v0.36: how many minutes to ADD to the household's Handyzeit blueprint's
    # own configured per-tick increment (a negative number reduces it, 0
    # leaves it unchanged) - see PROGRESS_BAND_TICK_ADJUSTMENT_MINUTES in
    # const.py and FamilyTasksCoordinator._screen_time_tick_adjustment_minutes.
    # Banded on this member's current-week progress percent against
    # CONF_WEEKLY_PROGRESS_GOAL_POINTS: -2 at the 0% band (no progress at all
    # yet this week), -1 at the 50% band, 0 from the 100% band up. Exposed as
    # a plain attribute on FamilyTasksMemberPointsSensor (see sensor.py, same
    # "no dedicated entity for a single number" reasoning as the other
    # options-derived attributes on FamilyTasksData below) rather than a new
    # entity, for the blueprint's optional
    # screen_time_tick_adjustment_source_entity input to read via
    # state_attr(...) and apply only to its "plus_tick" trigger path.
    screen_time_tick_adjustment_minutes: int = 0
    # v0.32: current consecutive-week bonus streak length, one counter per
    # fixed coin-bonus tier (v0.36: was a single counter tied to the
    # then-configurable CONF_STREAK_BONUS_THRESHOLD_POINTS; now there are two
    # independent streaks, one for maintaining the 150% weekly-progress
    # checkpoint and one for the 200% checkpoint - see
    # CONF_STREAK_150_BONUS_COINS/CONF_STREAK_200_BONUS_COINS in const.py and
    # FamilyTasksCoordinator._async_process_streak_coin_bonus). 0 whenever the
    # relevant tier's bonus is unconfigured (bonus coins <= 0) or the member
    # hasn't reached that checkpoint in their most recently judged week.
    streak_weeks_150: int = 0
    streak_weeks_200: int = 0


@dataclass(slots=True)
class FamilyTasksData:
    """Snapshot produced on every coordinator refresh."""

    tasks: dict[str, TaskStatusData] = field(default_factory=dict)
    members: dict[str, MemberSummaryData] = field(default_factory=dict)
    # v0.36: household-wide Meilensteinbonus coin amounts (see
    # CONF_MILESTONE_150_BONUS_COINS/CONF_MILESTONE_200_BONUS_COINS in
    # const.py), read fresh from the config entry's options on every refresh.
    # Replaces v0.30's configurable-threshold milestone_bonus_enabled/
    # milestone_1_*/milestone_2_* fields entirely - the two checkpoints are
    # now the fixed 150%/200% weekly-progress bands (PROGRESS_THRESHOLD_PERCENTS
    # in const.py) rather than a household-chosen percent, and the bonus
    # itself is coins credited to CoinLedgerStore rather than points logged
    # to the completion log (see
    # FamilyTasksCoordinator._async_process_milestone_coin_bonus). A tier is
    # off exactly when its bonus is <= 0. Exposed as sensor attributes (see
    # FamilyTasksMemberPointsSensor in sensor.py) purely so the card can draw
    # the two fixed threshold markers on each member's "Wochenfortschritt"
    # progress bar and label them with their bonus - there is no
    # coordinator-level entity to attach this to otherwise, so it rides along
    # on every member's points sensor (the value is identical on all of them,
    # the card just reads it off whichever one).
    milestone_150_bonus_coins: int = DEFAULT_MILESTONE_150_BONUS_COINS
    milestone_200_bonus_coins: int = DEFAULT_MILESTONE_200_BONUS_COINS
    # v0.32: the *absolute* point value each fixed 150%/200% checkpoint above
    # works out to this week (round(weekly_progress_goal_points * percent /
    # 100), the exact same computation
    # FamilyTasksCoordinator._async_process_milestone_coin_bonus itself
    # awards against, and also the per-week target the streak-bonus tiers
    # below judge against - see streak_150_bonus_coins/streak_200_bonus_coins)
    # - computed once, here, in Python and exposed so the card can show/label
    # the markers with these numbers directly instead of recomputing
    # percent -> points itself in JS. Python's round() (banker's rounding)
    # and JS's Math.round() (always rounds .5 up) can disagree on an exact
    # .5 - recomputing independently in the card could then show a marker at
    # a slightly different point value than the one the backend actually
    # awards at. 0 whenever weekly_progress_goal_points is 0 (nothing to take
    # a percentage of).
    milestone_150_threshold_points: int = 0
    milestone_200_threshold_points: int = 0
    # v0.23: household-wide default rotation strategy for new tasks (see
    # CONF_DEFAULT_ROTATION_STRATEGY in const.py) - rides along here for the
    # same reason the milestone-bonus settings above do (no dedicated entity
    # to attach a plain options value to). The card reads this to pre-select
    # the right "Rotationstyp" when opening the "+ Aufgabe hinzufügen" form
    # instead of always defaulting to "Reihum".
    default_rotation_strategy: str = DEFAULT_ROTATION_STRATEGY
    # v0.29: household-wide weekly point goal (see
    # CONF_WEEKLY_PROGRESS_GOAL_POINTS in const.py) backing the card's
    # "Wochenfortschritt" progress bars - rides along here for the same
    # reason default_rotation_strategy does (no dedicated entity to attach a
    # plain options value to). 0 means the goal/surplus mechanic is off; the
    # card then renders each bar as a plain "points earned this week" tally
    # with no target to reach.
    weekly_progress_goal_points: int = DEFAULT_WEEKLY_PROGRESS_GOAL_POINTS
    # v0.36: household-wide Streak-Bonus coin amounts, one per fixed tier
    # (see CONF_STREAK_150_BONUS_COINS/CONF_STREAK_200_BONUS_COINS/
    # CONF_STREAK_BONUS_REQUIRED_WEEKS in const.py) - rides along here for
    # the same "no dedicated entity for a plain options value" reason the
    # milestone/weekly-goal settings above do. Replaces v0.32's single
    # configurable-threshold streak_bonus_enabled/...threshold_points/
    # ...points fields entirely: "maintaining" a fixed checkpoint (150% or
    # 200%, milestone_150_threshold_points/milestone_200_threshold_points
    # above) for more than streak_bonus_required_weeks consecutive weeks now
    # earns its own coin bonus each further week the streak holds - see
    # FamilyTasksCoordinator._async_process_streak_coin_bonus. A tier is off
    # exactly when its bonus is <= 0.
    streak_150_bonus_coins: int = DEFAULT_STREAK_150_BONUS_COINS
    streak_200_bonus_coins: int = DEFAULT_STREAK_200_BONUS_COINS
    streak_bonus_required_weeks: int = DEFAULT_STREAK_BONUS_REQUIRED_WEEKS
    # v0.32: whether the household-wide Urlaubsmodus switch
    # (switch.FamilyTasksVacationModeSwitch) is currently on - rides along
    # here (not a dedicated attribute on the switch's own entity state, which
    # already exposes it as its native on/off state) purely so the card can
    # read it off the same per-refresh snapshot as everything else, without
    # having to separately track the switch entity's state too. See
    # VacationModeStateStore in storage.py.
    vacation_mode_active: bool = False
    # v0.38: how many "Aufgabenpool" occurrences are currently unclaimed and
    # actionable - see pool_tasks_open in _async_update_data for exactly
    # which occurrences count (matches the card's own
    # _renderTaskPoolSection). Unlike the options-derived fields above this
    # is a primary, at-a-glance household figure, so it gets its own
    # dedicated entity (FamilyTasksPoolTasksSensor in sensor.py) rather than
    # riding along as a plain attribute somewhere.
    pool_tasks_open: int = 0


def _current_period_date(
    recurrence: dict, today: date, created_at: date | None = None
) -> date | None:
    """Return the date identifying the current occurrence's period.

    ``created_at`` (v0.39): the date the task itself was created, if known -
    ``None`` for a task saved before this field existed. Only affects a
    "weekly" recurrence: without it, a task created e.g. on a Sunday for a
    Monday-only schedule would resolve to *last* Monday (the most recent
    matching weekday) - a date before the task ever existed - and show up
    immediately as overdue, even though it has never actually had a chance
    to be completed. See the v0.39 CHANGELOG entry.

    v0.40: the "weekly" branch is now the only one that can return ``None`` -
    see its own comment below for when and why. Every other recurrence type
    always resolves to a concrete date, exactly as before.
    """
    rtype = recurrence["type"]

    if rtype == "daily" or rtype == RECURRENCE_BATTERY:
        # A battery task's period is daily, same as "daily" - but see
        # _async_update_data, which downgrades a due occurrence back to
        # TASK_STATUS_IDLE unless a monitored battery is currently low.
        return today

    if rtype == "weekly":
        # v0.40: bounded to the *current* calendar week (Monday-Sunday) -
        # same window _pool_period_date already uses, but, unlike that one,
        # this never reaches beyond it. Previously (v0.39) a task too new to
        # have had a chance at any of its configured weekdays yet searched
        # forward *unbounded*, which could land on a date days away while
        # still being reported as TASK_STATUS_PENDING ("offen") - there was
        # no separate "not due yet" status for a weekly task, so the card
        # showed it as already open. _async_update_data now treats a future
        # date returned from here as TASK_STATUS_UPCOMING instead (visible
        # with its weekday, not completable yet - "Es sollen immer alle
        # bereits vorhersehbaren Aufgaben der jeweils laufenden Woche
        # angezeigt werden"), and ``None`` (nothing left to show *this*
        # week) as idle, same as an untriggered sensor task - it starts
        # appearing again once its weekday actually falls within a week it
        # existed for.
        weekdays = recurrence.get("weekdays") or [0]
        week_start = today - timedelta(days=today.weekday())

        # Prefer the most recent matching weekday within this week
        # (Monday..today) - once its day has arrived this stays "the"
        # occurrence for the rest of the week (pending, then overdue) even
        # after a *later* matching weekday in the same week would otherwise
        # take over, exactly like the old unbounded backward search did
        # within the current week.
        latest_so_far: date | None = None
        for offset in range(today.weekday() + 1):
            candidate = week_start + timedelta(days=offset)
            if candidate.weekday() in weekdays and (
                created_at is None or candidate >= created_at
            ):
                latest_so_far = candidate
        if latest_so_far is not None:
            return latest_so_far

        # Nothing this week has happened yet (or every match so far predates
        # created_at) - look forward to the earliest still-upcoming matching
        # weekday, but only through the *end of this same week*. Beyond that
        # there is nothing "already foreseeable" about it yet - it simply
        # isn't shown at all until the week it falls in actually starts.
        for offset in range(today.weekday() + 1, 7):
            candidate = week_start + timedelta(days=offset)
            if candidate.weekday() in weekdays and (
                created_at is None or candidate >= created_at
            ):
                return candidate
        return None

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


def _pool_period_date(recurrence: dict, today: date, created_at: date | None = None) -> date:
    """Like _current_period_date, but for an "Aufgabenpool" task (see below).

    v0.40: _current_period_date's own "weekly" backward search is now
    bounded to the current calendar week too (see its docstring) - both
    functions agree on which matching weekday within *this* week is "the"
    current occurrence. They still differ once nothing has happened yet
    this week: _current_period_date only looks forward through the
    *remaining* days of this same week and returns ``None`` if that finds
    nothing (surfaced by _async_update_data as TASK_STATUS_UPCOMING while
    still within the week, or as idle/not-shown otherwise - "a normally
    assigned/rotated task only needs to be seen once its own week starts",
    not weeks ahead), while this function keeps reaching into the following
    week(s) as needed and never returns ``None`` - an Aufgabenpool
    occurrence (see the "Aufgabenpool" section in _async_update_data: nobody
    is assigned and there is no rotation) has no other way of ever being
    noticed at all except by showing up here, so it must always resolve to
    *some* upcoming date for a child to see and reserve, however far out
    that ends up being for a brand-new task.

    Normally bounded to the *current* calendar week (Monday-Sunday, the same
    boundary start_of_week uses): prefers the most recent matching weekday
    within this week if one has already occurred (today included), and
    otherwise looks *forward* to the earliest still-upcoming matching
    weekday. ``created_at`` (v0.39, see _current_period_date) excludes any
    candidate before the task's own creation date from that backward search
    - a task created on, say, a Sunday for a Monday-only schedule then has
    no matching weekday left *this* week at all (Monday already happened
    before it existed, and there are no more matching days before Sunday,
    the last day of the week), so the forward search below is no longer
    bounded to the rest of the current week either in that case, and instead
    looks into the following week(s) as needed.
    """
    if recurrence["type"] != "weekly":
        return _current_period_date(recurrence, today, created_at)

    weekdays = recurrence.get("weekdays") or [0]
    week_start = today - timedelta(days=today.weekday())

    latest_so_far: date | None = None
    for offset in range(today.weekday() + 1):  # Monday of this week .. today
        candidate = week_start + timedelta(days=offset)
        if candidate.weekday() in weekdays and (created_at is None or candidate >= created_at):
            latest_so_far = candidate
    if latest_so_far is not None:
        return latest_so_far

    search_from = max(today, created_at) if created_at else today
    for offset in range(1, 15):  # up to two weeks out - a weekly match is always within 7
        candidate = search_from + timedelta(days=offset)
        if candidate.weekday() in weekdays and (created_at is None or candidate >= created_at):
            return candidate

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


def _deadline_at(due_at: datetime, period_start: date, task: dict) -> datetime:
    """Return the datetime after which an occurrence counts as overdue.

    v0.39: the card's task form now sets an absolute "Überfällig ab"
    time-of-day (``task["overdue_time"]``, same "HH:MM" shape as
    ``due_time``) instead of a "Karenzzeit" grace-period *duration*
    (``task["overdue_after_minutes"]``) - see the CHANGELOG entry. A task
    saved before this version (or never re-saved since) has no
    ``overdue_time`` at all, so it keeps behaving exactly as before:
    ``due_at`` plus its stored (or the default) grace-period duration.

    If a stored ``overdue_time`` would land *before* ``due_at`` on the same
    date (e.g. due at 20:00 but "overdue_time" is 08:00 - not achievable via
    the card's own form, which only offers a time on/after due_time, but
    reachable via the websocket API directly, or a due_time edited after the
    fact), the deadline rolls to the next day instead of claiming an
    occurrence was already overdue before it was even due.
    """
    overdue_time = task.get("overdue_time")
    if overdue_time:
        deadline = _due_at(period_start, overdue_time)
        if deadline < due_at:
            deadline += timedelta(days=1)
        return deadline
    overdue_after = timedelta(
        minutes=task.get("overdue_after_minutes", DEFAULT_OVERDUE_AFTER_MINUTES)
    )
    return due_at + overdue_after


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
        milestone_bonus_state: MilestoneBonusStateStore,
        claim_state: ClaimStateStore,
        streak_bonus_state: StreakBonusStateStore,
        vacation_mode_state: VacationModeStateStore,
        coin_ledger: CoinLedgerStore,
        coin_system_state: CoinSystemStateStore,
        weekly_coin_conversion_state: WeeklyCoinConversionStateStore,
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
        self.milestone_bonus_state = milestone_bonus_state
        self.claim_state = claim_state
        self.streak_bonus_state = streak_bonus_state
        self.vacation_mode_state = vacation_mode_state
        # v0.36: see CoinLedgerStore/CoinSystemStateStore in storage.py.
        self.coin_ledger = coin_ledger
        self.coin_system_state = coin_system_state
        # v0.37: see WeeklyCoinConversionStateStore in storage.py.
        self.weekly_coin_conversion_state = weekly_coin_conversion_state

    async def _async_update_data(self) -> FamilyTasksData:
        now = dt_util.utcnow()
        today = dt_util.now().date()

        # Moved up from further down (was only computed just before the
        # member-summaries loop) so _async_process_milestone_coin_bonus/
        # _async_process_streak_coin_bonus below can use start_of_week and
        # weekly_progress_goal_points too.
        local_now = dt_util.now()
        start_of_today = dt_util.as_utc(dt_util.start_of_local_day(local_now))
        start_of_week = start_of_today - timedelta(days=start_of_today.weekday())
        start_of_month = dt_util.as_utc(
            dt_util.start_of_local_day(local_now.replace(day=1))
        )
        weekly_progress_goal_points = DEFAULT_WEEKLY_PROGRESS_GOAL_POINTS
        if self.config_entry:
            weekly_progress_goal_points = self.config_entry.options.get(
                CONF_WEEKLY_PROGRESS_GOAL_POINTS, DEFAULT_WEEKLY_PROGRESS_GOAL_POINTS
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

        # Also raised before the main loop, same reasoning: a coin bonus
        # credited this refresh should already be reflected in this same
        # refresh's member_summaries below, not just after a second refresh.
        # v0.36: the old _async_correct_negative_balances one-time fixup is
        # gone along with points_available itself - a member's coin balance
        # can never go negative from a redemption (ws_redeem_reward in
        # storage.py validates against it up front, same as before), so there
        # is nothing left for it to correct.
        await self._async_process_milestone_coin_bonus(start_of_week, weekly_progress_goal_points)
        await self._async_process_streak_coin_bonus(start_of_week, weekly_progress_goal_points)
        # v0.37: finalize every fully-elapsed week's "points beyond the
        # weekly goal" surplus into a durable coin-ledger credit - see
        # WeeklyCoinConversionStateStore and
        # _async_process_weekly_coin_conversion below for why this replaces
        # recomputing that surplus live from the (bounded) completion log for
        # every past week on every refresh.
        await self._async_process_weekly_coin_conversion(start_of_week, weekly_progress_goal_points)

        # v0.32: household-wide Urlaubsmodus - see VacationModeStateStore in
        # storage.py. Read once per refresh, same pattern as
        # weekly_progress_goal_points above; consulted below to skip any task
        # whose CONF_TASK_VACATION_BEHAVIOR is "pause" while it's on.
        vacation_mode_active = self.vacation_mode_state.is_active

        task_statuses: dict[str, TaskStatusData] = {}
        open_tasks_by_member: dict[str, int] = {}
        # v0.38: how many "Aufgabenpool" occurrences (is_pool_task below) are
        # currently unclaimed and actionable - backs
        # FamilyTasksData.pool_tasks_open / the dedicated
        # FamilyTasksPoolTasksSensor (sensor.py). Mirrors exactly which ids
        # the card's own _renderTaskPoolSection (family-tasks-card.js) would
        # show: incremented below for a pool task that is neither claimed
        # (claimed_by_member_id) nor TASK_STATUS_DONE nor - the one
        # recurrence-specific case, see _isPoolTask/_renderTaskPoolSection -
        # a "trigger" pool task still TASK_STATUS_IDLE (nothing open yet).
        pool_tasks_open = 0
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
            # v0.32: paused for the duration of Urlaubsmodus - treated exactly
            # like "enabled: false" above (no status entry at all, not due,
            # not shown), except conditional on the household-wide switch
            # instead of permanent. A task left at the default "show"
            # (VACATION_BEHAVIOR_SHOW) is completely unaffected.
            if (
                vacation_mode_active
                and task.get(CONF_TASK_VACATION_BEHAVIOR, VACATION_BEHAVIOR_SHOW)
                == VACATION_BEHAVIOR_PAUSE
            ):
                continue

            recurrence = task["recurrence"]
            # v0.39: the date this task definition was created, if known -
            # every period-date/overdue computation below treats a task
            # saved before this field existed exactly like before (see
            # _current_period_date/_pool_period_date).
            created_date = self._task_created_date(task)

            rotation = task["rotation"]
            member_ids = rotation.get("member_ids") or []
            # v0.37: a member marked "paused" (CONF_MEMBER_PAUSED - away for
            # a while, see that constant's docstring in const.py) shouldn't
            # receive new task assignments for the duration. If *every*
            # current assignee of a fixed/rotating task is paused, treat the
            # whole task exactly like a household-wide Urlaubsmodus-paused
            # one above: skipped entirely, no status entry, not due - there
            # is nobody around to act on it anyway. member_ids being empty
            # (an Aufgabenpool task, see is_pool_task below) never matches
            # here (all() of an empty rotation.member_ids would otherwise be
            # vacuously true) - a pool task stays governed purely by which
            # *other*, non-paused members are eligible to claim it, handled
            # separately below.
            if member_ids and all(self._member_paused(mid) for mid in member_ids):
                continue
            # For a *partially* paused rotation/fixed assignment, the
            # non-paused subset stands in for member_ids when picking who
            # this occurrence actually belongs to - round-robin/least-points
            # rotate only among whoever's actually around, and a fixed
            # multi-assignee task is carried solely by its non-paused
            # members. Falls back to the full member_ids (the branch above
            # already ruled out "every assignee paused") only in the
            # impossible case that filtering left nothing.
            rotation_member_ids = [
                mid for mid in member_ids if not self._member_paused(mid)
            ] or member_ids
            assigned_member_id = self._assigned_member_id(rotation, rotation_member_ids)
            assigned_member_ids = self._assigned_member_ids(rotation, rotation_member_ids)
            # v0.30: "Aufgabenpool" - a task with no fixed assignee(s) *and*
            # no rotation at all (member_ids empty either way, regardless of
            # "strategy" - see ROTATION_SCHEMA in storage.py). Nobody is
            # responsible for it by default; instead any active child may
            # reserve ("Annehmen") it via the existing claim mechanism - see
            # the eligible_member_ids/_pool_period_date handling below and
            # the card's "Aufgabenpool" section (family-tasks-card.js), which
            # shows these regardless of the normal due/filter settings.
            # Excludes an auto-generated parent-confirmation task (see
            # RECURRENCE_CONFIRMATION in const.py) even in the degenerate
            # case of a household with no active parent at all (member_ids
            # would then also be empty there) - that task is never something
            # a child should see offered up for "Annehmen".
            is_pool_task = not member_ids and not task.get("confirms")

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
                # A trigger/confirmation occurrence's "period" is whenever it
                # was actually triggered, not a calendar period_start - use
                # that same date as the reference day for combining with an
                # absolute overdue_time below (see _deadline_at).
                period_start = dt_util.as_local(due_at).date()
            else:
                period_start = (
                    _pool_period_date(recurrence, today, created_date)
                    if is_pool_task
                    else _current_period_date(recurrence, today, created_date)
                )
                # v0.40: only reachable for a non-pool "weekly" task whose
                # configured weekday(s) don't fall within the current week
                # at all for it yet (see _current_period_date) - e.g. a
                # brand-new task created after its only weekday already
                # passed this week. Nothing to show, act on, or claim this
                # week; treated exactly like an untriggered sensor task
                # until its weekday actually falls within a week it existed
                # for.
                if period_start is None:
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
                        eligible_member_ids=assigned_member_ids,
                        kind=task.get("kind", TASK_KIND_STANDARD),
                        created_by_member_id=task.get(CONF_TASK_CREATED_BY_MEMBER_ID),
                    )
                    continue
                period_key = period_start.isoformat()
                due_at = _due_at(period_start, task.get("due_time"))

            deadline_at = _deadline_at(due_at, period_start, task)

            last_entry = self.completions.get_last_entry(task_id, period_key)
            if last_entry is not None:
                status = TASK_STATUS_DONE
            elif (task_id, period_key) in pending_confirmations:
                status = TASK_STATUS_AWAITING_CONFIRMATION
            elif (
                not is_pool_task
                and recurrence["type"] == "weekly"
                and period_start > today
            ):
                # v0.40: this week's occurrence is already known (see
                # _current_period_date) but its day hasn't arrived yet -
                # "Es sollen immer alle bereits vorhersehbaren Aufgaben der
                # jeweils laufenden Woche angezeigt werden. Die Aufgaben
                # sollen bis zur Fälligkeit mit einem grünen Label
                # dargestellt werden." Never reached for an Aufgabenpool
                # task (is_pool_task) - _pool_period_date already returns
                # future dates *by design* so a pool occurrence can be
                # reserved from the start of the week, and it stays
                # TASK_STATUS_PENDING/claimable for that entire window, not
                # TASK_STATUS_UPCOMING. Deliberately scoped to "weekly" only
                # - a future-dated "once"/"interval_days" occurrence (e.g. a
                # one-time task someone scheduled for next month) keeps its
                # pre-v0.40 behavior (immediately PENDING/completable) rather
                # than silently gaining a green "weekday" label that
                # wouldn't even mean much for a non-recurring date, and a
                # "daily"/"battery" period_start is never in the future to
                # begin with (see _current_period_date).
                status = TASK_STATUS_UPCOMING
            elif now > deadline_at:
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
                        # v0.37: a paused member isn't offered someone else's
                        # overdue task either - see CONF_MEMBER_PAUSED.
                        and not self._member_paused(other_id)
                        and self._member_role(other_id) == MEMBER_ROLE_CHILD
                    ):
                        eligible_member_ids.append(other_id)

            # v0.30: an Aufgabenpool task (is_pool_task, see above) starts
            # with nobody assigned at all - assigned_member_ids is always
            # empty, so the overdue-only expansion just above never triggers
            # for it. Every active member is eligible for as long as it's
            # actionable (pending or overdue), not just once overdue -
            # letting a member reserve ("Annehmen") it from the very start of
            # the week, before it's even due, is the entire point of the
            # pool - see _pool_period_date.
            #
            # v0.33: this used to only add active *children* - a parent could
            # never claim ("sich melden") a pool task, and (since canAct in
            # the card, and claimable in general, are both keyed off
            # eligible_member_ids) could not complete one directly either
            # unless it happened to also be assigned to a child (which a pool
            # task, by definition, never is - see is_pool_task above). Every
            # active member, parent or child, is now eligible - a parent can
            # both claim and complete an Aufgabenpool occurrence without
            # anyone claiming it first, exactly like they always could for a
            # task assigned to a child.
            if is_pool_task and status in (TASK_STATUS_PENDING, TASK_STATUS_OVERDUE):
                for other_id, other_member in self.members.data.items():
                    if (
                        other_id not in eligible_member_ids
                        and other_member.get("active", True)
                        # v0.37: a paused member isn't offered pool work
                        # either - see CONF_MEMBER_PAUSED.
                        and not self._member_paused(other_id)
                    ):
                        eligible_member_ids.append(other_id)

            # v0.27: "Annehmen" reservation - see ClaimStateStore in
            # storage.py, CLAIM_RESERVATION_MINUTES/CLAIM_PENALTY_POINTS in
            # const.py, and claimed_by_member_id/claim_expires_at/claimable on
            # TaskStatusData. "claimable" reflects the *pre-claim*
            # eligible_member_ids (more than one possible actor right now) -
            # claiming a task only one person could ever act on anyway would
            # reserve nothing, so it's not offered there at all. A checklist
            # has no single "erledigt" action to reserve (it completes
            # sub-item by sub-item), and an auto-generated parent-
            # confirmation task ("confirms" set) isn't a chore to claim
            # either, so neither ever qualifies.
            claimed_by_member_id: str | None = None
            claim_expires_at: datetime | None = None
            claimable = (
                not task.get("confirms")
                and not task.get("subtasks")
                and status in (TASK_STATUS_PENDING, TASK_STATUS_OVERDUE)
                and len(eligible_member_ids) > 1
            )
            claim_entry = self.claim_state.get(task_id, period_key)
            if claim_entry is not None:
                claimed_at = dt_util.parse_datetime(claim_entry["claimed_at"])
                expires_at = claimed_at + timedelta(minutes=CLAIM_RESERVATION_MINUTES)
                if status in (TASK_STATUS_DONE, TASK_STATUS_AWAITING_CONFIRMATION):
                    # Done, or acted on in time and now just waiting on a
                    # parent's sign-off (async_complete_task already clears
                    # the claim itself the moment that happens - this is only
                    # a defensive fallback for whatever briefly hasn't caught
                    # up yet) - either way the claimant held up their end, so
                    # there is nothing left to expire/penalize. A parent
                    # taking a while to confirm must never itself cost the
                    # child a point via this path - see the separate,
                    # explicit-"Ablehnen" penalty in async_skip_task instead.
                    await self.claim_state.async_clear(task_id)
                elif now >= expires_at:
                    # Reservation ran out with the occurrence still not done
                    # - the claimant loses CLAIM_PENALTY_POINTS and it
                    # reopens for everyone in eligible_member_ids again (left
                    # untouched above) - see _async_expire_claim.
                    await self._async_expire_claim(task_id, task, claim_entry["member_id"])
                else:
                    claimed_by_member_id = claim_entry["member_id"]
                    claim_expires_at = expires_at
                    # Nobody but the claimant may act on - or claim - this
                    # occurrence while the reservation is active; see
                    # async_complete_task/async_claim_task, which enforce
                    # this server-side too, not just via what the card shows.
                    eligible_member_ids = [claimed_by_member_id]
                    claimable = False

            # v0.32: once a child reserves ("Annehmen") an Aufgabenpool
            # occurrence, it is firmly theirs for as long as the reservation
            # holds - not just in terms of who *may* complete it
            # (eligible_member_ids above already narrows to just them), but
            # also in terms of how the occurrence displays: assigned_member_id/
            # assigned_member_ids feed the card's assignee label and per-
            # member open-task counts, and the card's "Aufgabenpool" section
            # (_isClaimedPoolTask in family-tasks-card.js) now reads
            # claimed_by_member_id to move a claimed occurrence out of that
            # section and into the claimant's normal task list instead of
            # leaving it looking unclaimed there. Only while the claim is
            # actually active - an expired/never-claimed pool occurrence is
            # untouched.
            if is_pool_task and claimed_by_member_id:
                assigned_member_id = claimed_by_member_id
                assigned_member_ids = [claimed_by_member_id]

            # v0.38: count this occurrence towards pool_tasks_open (see its
            # declaration above) under exactly the same conditions the
            # card's own _renderTaskPoolSection uses to decide whether to
            # show it in the "Aufgabenpool" section: an unclaimed pool task,
            # not already done, and - the one recurrence-specific exception,
            # see _isPoolTask/_renderTaskPoolSection in
            # family-tasks-card.js - not a still-"idle" "trigger" task (its
            # sensor hasn't opened an occurrence yet, so there is nothing to
            # "Annehmen"). Every other pool task has no "due" concept of its
            # own and counts here for the entire week, matching the card.
            if (
                is_pool_task
                and not claimed_by_member_id
                and status != TASK_STATUS_DONE
                and not (recurrence["type"] == RECURRENCE_TRIGGER and status == TASK_STATUS_IDLE)
            ):
                pool_tasks_open += 1

            subtasks_status: list[dict] = []
            if task.get("subtasks"):
                checked_ids = self.checklist_state.checked_ids(task_id, period_key)
                subtasks_status = [
                    {"id": s["id"], "name": s["name"], "checked": s["id"] in checked_ids}
                    for s in task.get("subtasks", [])
                ]

            # v0.40: TASK_STATUS_UPCOMING is deliberately excluded here too -
            # FamilyTasksMemberOpenTasksSensor documents itself as "currently
            # open (pending/overdue)", and a task that isn't due yet (just
            # previewed with its weekday, not completable) isn't that.
            if status not in (TASK_STATUS_DONE, TASK_STATUS_IDLE, TASK_STATUS_UPCOMING):
                for member_id in assigned_member_ids:
                    open_tasks_by_member[member_id] = open_tasks_by_member.get(member_id, 0) + 1

            # v0.34: pausing must survive a child's own completion claim,
            # not just resolve the instant TASK_STATUS_OVERDUE is computed.
            # Once a child marks an overdue mandatory task done, its status
            # becomes TASK_STATUS_AWAITING_CONFIRMATION (see the elif chain
            # above) rather than staying TASK_STATUS_OVERDUE - a plain
            # `status == TASK_STATUS_OVERDUE` check would then read as
            # "resolved" and resume screen time before a parent has actually
            # signed off, even though nothing about the task is done yet as
            # far as the household's points/history are concerned. due_at
            # (computed further up, independently of completion/confirmation
            # state - see the RECURRENCE_TRIGGER/RECURRENCE_CONFIRMATION
            # branch above and _due_at for calendar-based tasks) still
            # reflects the *original* occurrence's deadline regardless of
            # status, so re-deriving "is this occurrence past its deadline"
            # from due_at directly - instead of trusting the OVERDUE status
            # label alone - keeps the pause active through
            # AWAITING_CONFIRMATION too. TASK_STATUS_DONE (a parent actually
            # confirmed it, or it needed no confirmation to begin with) and
            # TASK_STATUS_IDLE (nothing open at all, e.g. an untriggered
            # "trigger"-recurrence mandatory task) are the only statuses that
            # still lift the pause.
            if (
                task.get("kind") == TASK_KIND_MANDATORY
                and status not in (TASK_STATUS_DONE, TASK_STATUS_IDLE)
                and due_at is not None
                and now > deadline_at
            ):
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
                deadline_at=deadline_at,
                assigned_member_id=assigned_member_id,
                assigned_member_ids=assigned_member_ids,
                eligible_member_ids=eligible_member_ids,
                claimed_by_member_id=claimed_by_member_id,
                claim_expires_at=claim_expires_at,
                claimable=claimable,
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
                vacation_behavior=task.get(CONF_TASK_VACATION_BEHAVIOR, VACATION_BEHAVIOR_SHOW),
                last_rejection_note=task.get("last_rejection_note"),
                last_rejection_at=dt_util.parse_datetime(task["last_rejection_at"])
                if task.get("last_rejection_at")
                else None,
            )

        member_summaries: dict[str, MemberSummaryData] = {}
        for member_id, member in self.members.data.items():
            points_total = self.completions.points_since(
                member_id, datetime.min.replace(tzinfo=dt_util.UTC)
            )
            points_week = self.completions.points_since(member_id, start_of_week)
            # v0.36: coins_available replaces the old spendable_points minus
            # redeemed_points computation entirely - self.coin_ledger.balance
            # nets out every bonus credit *and* every past redemption debit
            # on its own (see ws_redeem_reward in storage.py, which appends
            # the debit at redemption time) - see
            # MemberSummaryData.coins_available's docstring.
            #
            # v0.37: coins_from_task_points here is now scoped to *only* the
            # still-open current week (since=max(coin_system_state.started_at,
            # start_of_week), rather than the full history since started_at)
            # - every fully-elapsed week's surplus has already been finalized
            # into self.coin_ledger by _async_process_weekly_coin_conversion
            # above, so counting it again here would double it. The current
            # week's own surplus isn't in the ledger yet (it can't be judged
            # until the week is over - see that method), so it's still
            # computed live from the completion log, same as before; unlike
            # a past week, there's no risk of *this* week's completions
            # having already aged out of that log by the time this runs.
            coins_available = coins_from_task_points(
                self.completions,
                member_id,
                weekly_progress_goal_points,
                max(self.coin_system_state.started_at, start_of_week),
            ) + self.coin_ledger.balance(member_id)
            member_summaries[member_id] = MemberSummaryData(
                member_id=member_id,
                name=member["name"],
                person_entity_id=member.get("person_entity_id"),
                points_today=self.completions.points_since(member_id, start_of_today),
                points_week=points_week,
                points_month=self.completions.points_since(member_id, start_of_month),
                points_total=points_total,
                coins_available=coins_available,
                open_tasks=open_tasks_by_member.get(member_id, 0),
                screen_time_grant_active=member_id not in screen_time_paused_members,
                screen_time_tick_adjustment_minutes=self._screen_time_tick_adjustment_minutes(
                    points_week, weekly_progress_goal_points
                ),
                streak_weeks_150=(self.streak_bonus_state.get(member_id, "150") or {}).get(
                    "streak_count", 0
                ),
                streak_weeks_200=(self.streak_bonus_state.get(member_id, "200") or {}).get(
                    "streak_count", 0
                ),
            )

        milestone_150_bonus_coins = DEFAULT_MILESTONE_150_BONUS_COINS
        milestone_200_bonus_coins = DEFAULT_MILESTONE_200_BONUS_COINS
        # Household-wide default rotation strategy (see
        # CONF_DEFAULT_ROTATION_STRATEGY in const.py) - read fresh from the
        # config entry's options every refresh, same pattern as the
        # Meilensteinbonus settings right below. Previously this option was
        # only ever written by the options flow and never actually read
        # anywhere, so the card's "+ Aufgabe hinzufügen" form always
        # pre-selected "Reihum" regardless of what a household had configured
        # here - see default_rotation_strategy below and
        # FamilyTasksMemberPointsSensor in sensor.py for how it now reaches
        # the card.
        default_rotation_strategy = DEFAULT_ROTATION_STRATEGY
        streak_150_bonus_coins = DEFAULT_STREAK_150_BONUS_COINS
        streak_200_bonus_coins = DEFAULT_STREAK_200_BONUS_COINS
        streak_bonus_required_weeks = DEFAULT_STREAK_BONUS_REQUIRED_WEEKS
        if self.config_entry:
            options = self.config_entry.options
            milestone_150_bonus_coins = options.get(
                CONF_MILESTONE_150_BONUS_COINS, DEFAULT_MILESTONE_150_BONUS_COINS
            )
            milestone_200_bonus_coins = options.get(
                CONF_MILESTONE_200_BONUS_COINS, DEFAULT_MILESTONE_200_BONUS_COINS
            )
            default_rotation_strategy = options.get(
                CONF_DEFAULT_ROTATION_STRATEGY, DEFAULT_ROTATION_STRATEGY
            )
            streak_150_bonus_coins = options.get(
                CONF_STREAK_150_BONUS_COINS, DEFAULT_STREAK_150_BONUS_COINS
            )
            streak_200_bonus_coins = options.get(
                CONF_STREAK_200_BONUS_COINS, DEFAULT_STREAK_200_BONUS_COINS
            )
            streak_bonus_required_weeks = options.get(
                CONF_STREAK_BONUS_REQUIRED_WEEKS, DEFAULT_STREAK_BONUS_REQUIRED_WEEKS
            )

        # See FamilyTasksData.milestone_150_threshold_points's docstring -
        # the exact same round() the awarding logic
        # (_async_process_milestone_coin_bonus) uses, computed once here too
        # so the card never has to redo it (and risk disagreeing on a .5
        # case).
        milestone_150_threshold_points = (
            round(weekly_progress_goal_points * 150 / 100)
            if weekly_progress_goal_points > 0
            else 0
        )
        milestone_200_threshold_points = (
            round(weekly_progress_goal_points * 200 / 100)
            if weekly_progress_goal_points > 0
            else 0
        )

        return FamilyTasksData(
            tasks=task_statuses,
            members=member_summaries,
            milestone_150_bonus_coins=milestone_150_bonus_coins,
            milestone_200_bonus_coins=milestone_200_bonus_coins,
            milestone_150_threshold_points=milestone_150_threshold_points,
            milestone_200_threshold_points=milestone_200_threshold_points,
            default_rotation_strategy=default_rotation_strategy,
            weekly_progress_goal_points=weekly_progress_goal_points,
            streak_150_bonus_coins=streak_150_bonus_coins,
            streak_200_bonus_coins=streak_200_bonus_coins,
            streak_bonus_required_weeks=streak_bonus_required_weeks,
            vacation_mode_active=vacation_mode_active,
            pool_tasks_open=pool_tasks_open,
        )

    def _current_period_key(self, task_id: str, task: dict) -> str | None:
        """Return the id of the occurrence currently due, if any.

        For trigger-based (and confirmation) tasks this is ``None`` while
        idle (no sensor event / confirmation request has opened an occurrence
        yet). For calendar-based tasks there is *usually* a current period,
        except - v0.40 - a non-pool "weekly" task with nothing foreseeable
        yet this week (see _current_period_date): ``None`` there too, same
        as an untriggered sensor task, since TASK_STATUS_UPCOMING/idle both
        mean "nothing to claim/complete/skip/toggle right now" either way.

        v0.30: an Aufgabenpool task (no fixed assignee(s), no rotation - see
        is_pool_task in _async_update_data) uses _pool_period_date instead of
        _current_period_date, exactly like _async_update_data itself does -
        this must stay in lockstep with that computation, since every
        claim/complete/skip/release/toggle-subtask call site below resolves
        "the current occurrence" through this method. Using the wrong one
        here would let a claim/completion be recorded against a different
        period_key than the one the last refresh actually showed the card.
        v0.40: now also passes the task's own created_at (_task_created_date)
        through to that computation for the same reason - before this, a
        brand-new task's "current occurrence" here could silently disagree
        with what _async_update_data had just displayed for it.
        """
        if task["recurrence"]["type"] in (RECURRENCE_TRIGGER, RECURRENCE_CONFIRMATION):
            open_occurrence = self.trigger_state.get(task_id)
            return open_occurrence["period_key"] if open_occurrence else None
        is_pool_task = not (task["rotation"].get("member_ids") or [])
        period_date_fn = _pool_period_date if is_pool_task else _current_period_date
        period_start = period_date_fn(
            task["recurrence"], dt_util.now().date(), self._task_created_date(task)
        )
        return period_start.isoformat() if period_start is not None else None

    def _task_created_date(self, task: dict) -> date | None:
        """The local date a task definition was created, if known.

        v0.39: set by TaskStorageCollection._process_create_data in
        storage.py - a task saved before this field existed has none, and
        every period-date/overdue computation treats that exactly like
        before (see _current_period_date/_pool_period_date).
        """
        created_at_raw = task.get("created_at")
        if not created_at_raw:
            return None
        parsed_created_at = dt_util.parse_datetime(created_at_raw)
        if parsed_created_at is None:
            return None
        return dt_util.as_local(parsed_created_at).date()

    async def async_complete_task(
        self, task_id: str, member_id: str | None = None, *, skip_confirmation: bool = False
    ) -> None:
        """Mark the current occurrence of a task as done and advance rotation.

        Two special cases:
        - If ``task_id`` is itself an auto-generated parent confirmation task
          (``task["confirms"]`` is set), completing it finalizes the child's
          original claim instead of logging a completion for itself.
        - If the member who would act on a normal task has role "child", the
          completion is not logged yet; instead a confirmation task is raised
          for the household's parents (see ``_async_request_confirmation``) -
          unless ``skip_confirmation`` is set (see below).

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

        ``skip_confirmation`` (v0.34): bypasses the child-assignee parent-
        confirmation step entirely, regardless of the task's own
        ``requires_confirmation`` setting - the completion is logged (and
        points awarded/rotation advanced) exactly as it would be for a
        "parent"-role assignee. Used by ``async_handle_sensor_normalized``,
        for a "trigger" task whose bound sensor's own state change is the
        proof the task was actually done, and (v0.35) by
        ``_async_raise_battery_alerts`` when
        ``CONF_BATTERY_ALERT_AUTO_COMPLETE_ON_RECOVERY`` is on, for an
        auto-generated battery-alert task whose battery recovered - in both
        cases there is nothing left for a parent to attest to that the
        sensor/battery state hasn't already confirmed. Never set for a real
        user action (a claimed "Erledigt" tap is always the child's own
        self-report and still needs sign-off).
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

        # v0.40: server-side half of "Diese Aufgaben sollen erst am Tag
        # ihrer Fälligkeit erledigt werden können" - the card already hides/
        # disables the "Erledigt" button for TASK_STATUS_UPCOMING (see
        # disableComplete in family-tasks-card.js), this is the same rule
        # enforced here too, same "silent no-op" pattern as every other
        # guard clause in this method. Read off the last refresh's own
        # status for this task rather than recomputing it - self.data always
        # reflects at most COORDINATOR_UPDATE_INTERVAL-old state, same
        # staleness async_claim_task's eligible_member_ids read above has.
        current_status = self.data.tasks.get(task_id) if self.data else None
        if current_status is not None and current_status.status == TASK_STATUS_UPCOMING:
            _LOGGER.debug(
                "Task %s is not due until %s yet - ignoring early completion",
                task_id,
                current_status.due_at,
            )
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

        # v0.27: an active "Annehmen" reservation (see ClaimStateStore in
        # storage.py) blocks completion by anyone but the claimant - the
        # card never shows the "Erledigt" button to anyone else while
        # claimed_by_member_id is set (see eligible_member_ids in
        # _async_update_data), this is the server-side half of that same
        # rule. A None member_id (unresolvable acting member) never matches
        # an active claim either, same as it never matches anyone's id.
        claim_entry = self.claim_state.get(task_id, period_key)
        if claim_entry is not None and claim_entry["member_id"] != member_id:
            _LOGGER.debug(
                "Task %s is reserved by %s - ignoring completion by %s",
                task_id,
                claim_entry["member_id"],
                member_id,
            )
            return

        rotation = task["rotation"]
        member_ids = rotation.get("member_ids") or []
        index = rotation.get("current_index", 0) % len(member_ids) if member_ids else 0
        acting_member_id = member_id or self._assigned_member_id(rotation, member_ids)

        if (
            acting_member_id
            and not skip_confirmation
            and self._member_role(acting_member_id) == MEMBER_ROLE_CHILD
        ):
            requires_confirmation = task.get(CONF_TASK_REQUIRES_CONFIRMATION)
            if requires_confirmation is None:
                # Legacy/default behavior: a task assigned to a child always
                # needs a parent's sign-off unless the task explicitly says
                # otherwise (see CONF_TASK_REQUIRES_CONFIRMATION in const.py -
                # only self-created child tasks currently set this to False).
                requires_confirmation = True
            if requires_confirmation:
                # v0.27: the child *did* act in time - clear any active claim
                # right away (same reasoning as the direct-completion path
                # below) so a parent taking a while to confirm never counts
                # as the reservation itself lapsing (see the AWAITING_
                # CONFIRMATION handling in _async_update_data, which treats a
                # still-present claim here defensively the same way, but
                # this is the normal path).
                await self.claim_state.async_clear(task_id)
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
        # v0.27: done in time - drop the now-moot claim (if any) right away
        # instead of waiting for _async_update_data's DONE-status cleanup on
        # the next refresh, so a stale "reserved" state can't briefly show
        # for anyone reading coordinator data before that refresh happens.
        await self.claim_state.async_clear(task_id)

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

    async def async_skip_task(self, task_id: str, note: str | None = None) -> None:
        """Skip the current occurrence without awarding points or rotating.

        For an auto-generated parent confirmation task, skipping means the
        parent *rejects* the child's claim: the confirmation task is dropped
        without finalizing anything, so the original task falls back to its
        normal pending/overdue state and the child can complete it again.

        ``note`` (v0.32) only applies to that rejection case - see ATTR_NOTE
        in const.py: an optional explanation a parent leaves for why the
        completion wasn't accepted (e.g. "Bett noch nicht gemacht"). Stored
        on the deduction's completion-log entry for the permanent record,
        *and* written onto the original task as "last_rejection_note"/
        "last_rejection_at" so the card can show it to the child right on the
        task itself (see TaskStatusData.last_rejection_note/...at, cleared
        again the next time the child retries - see
        _async_request_confirmation above). The child is also notified live,
        the same way a new task assignment is - see _async_notify_rejection.
        """
        if task_id not in self.tasks.data:
            raise HomeAssistantError(f"Unknown task_id '{task_id}'")

        task = self.tasks.data[task_id]

        confirms = task.get("confirms")
        if confirms:
            # v0.27: a parent explicitly rejecting a child's claimed
            # completion costs that child CONFIRMATION_REJECTION_PENALTY_POINTS
            # point(s), logged the same way a manual points/award adjustment
            # is (see const.py) - "Sollten Eltern die Aufgabenerledigung nicht
            # freigeben, verliert das Kind ebenfalls einen Punkt." The
            # confirmation task's own name ("Bestätigen: <Aufgabe> (<Kind>)",
            # see _async_request_confirmation) already identifies which task
            # and child this was for, so it's reused as-is here.
            await self.completions.async_add_entry(
                task_id=MANUAL_POINTS_TASK_ID,
                period_key=dt_util.utcnow().date().isoformat(),
                member_id=confirms["member_id"],
                points_awarded=-CONFIRMATION_REJECTION_PENALTY_POINTS,
                task_name=f"Nicht freigegeben: {task.get('name', 'Aufgabe')}",
                note=note,
            )
            original_task_id = confirms.get("task_id")
            original_task_name = task.get("name", "Aufgabe")
            if original_task_id and original_task_id in self.tasks.data:
                original_task_name = self.tasks.data[original_task_id].get(
                    "name", original_task_name
                )
                await self.tasks.async_update_item(
                    original_task_id,
                    {
                        "last_rejection_note": note,
                        "last_rejection_at": dt_util.utcnow().isoformat(),
                    },
                )
            await self._async_notify_rejection(confirms["member_id"], original_task_name, note)
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

    async def _async_notify_rejection(
        self, member_id: str, task_name: str, note: str | None
    ) -> None:
        """Best-effort notify a child that a parent rejected their completion.

        Mirrors __init__._async_notify_member's two-channel pattern (the
        member's own configured notify.* service, else a
        persistent_notification fallback) in miniature - duplicated here
        rather than imported, since __init__.py already imports from
        coordinator.py and importing back the other way would be circular.
        Also fires EVENT_TASK_REJECTED, same extension-point reasoning as
        EVENT_TASK_ASSIGNED.
        """
        member = self.members.data.get(member_id)
        if not member:
            return
        title = "Family Tasks"
        message = f"Nicht freigegeben: {task_name}"
        if note:
            message += f" – {note}"

        notify_service = member.get(CONF_MEMBER_NOTIFY_SERVICE)
        if notify_service:
            try:
                await self.hass.services.async_call(
                    "notify",
                    notify_service,
                    {"title": title, "message": message},
                    blocking=False,
                )
            except HomeAssistantError as err:
                _LOGGER.warning(
                    "Failed to call notify.%s for %s: %s", notify_service, member_id, err
                )
        else:
            try:
                persistent_notification.async_create(
                    self.hass,
                    message,
                    title=title,
                    notification_id=f"{DOMAIN}_rejection_{member_id}_{dt_util.utcnow().timestamp()}",
                )
            except Exception as err:  # noqa: BLE001 - best-effort, must never block the rejection
                _LOGGER.warning(
                    "Failed to raise persistent notification for %s: %s", member_id, err
                )

        self.hass.bus.async_fire(
            EVENT_TASK_REJECTED,
            {
                "member_id": member_id,
                "member_name": member.get("name"),
                "task_name": task_name,
                "note": note,
            },
        )

    async def async_claim_task(self, task_id: str, member_id: str | None) -> None:
        """Reserve a task's current occurrence for CLAIM_RESERVATION_MINUTES.

        Only lets ``member_id`` claim an occurrence they were actually
        computed as eligible for on the last refresh (see eligible_member_ids
        in _async_update_data), and only while nobody else already has it
        claimed. See CLAIM_RESERVATION_MINUTES/CLAIM_PENALTY_POINTS in
        const.py for what happens if the reservation then lapses unfinished.

        Every failure case here is a silent no-op rather than a raised error
        (mirroring the guard clauses in async_complete_task above) - an
        unresolvable member_id, an already-open claim, an ineligible member,
        or a task/period the card would never have offered "Annehmen" for to
        begin with only happen via a race between two people or direct API
        use, not anything a normal click can trigger.
        """
        if task_id not in self.tasks.data:
            raise HomeAssistantError(f"Unknown task_id '{task_id}'")
        if member_id is None:
            _LOGGER.debug("Cannot claim task %s: no resolvable member_id", task_id)
            return

        task = self.tasks.data[task_id]
        if task.get("confirms") or task.get("subtasks"):
            return

        period_key = self._current_period_key(task_id, task)
        if period_key is None:
            return
        if self.completions.get_last_entry(task_id, period_key) is not None:
            return
        if self.claim_state.get(task_id, period_key) is not None:
            _LOGGER.debug("Task %s is already claimed", task_id)
            return

        # Reuses the eligible_member_ids the last coordinator refresh already
        # computed (see _async_update_data) rather than recomputing rotation/
        # overdue-sibling eligibility here from scratch - self.data always
        # reflects at most COORDINATOR_UPDATE_INTERVAL-old state, same
        # staleness any other read of coordinator.data already has between
        # refreshes.
        status_data = self.data.tasks.get(task_id) if self.data else None
        eligible_ids = status_data.eligible_member_ids if status_data else []
        if len(eligible_ids) < 2 or member_id not in eligible_ids:
            _LOGGER.debug(
                "Member %s cannot claim task %s (not eligible, or nobody to reserve it against)",
                member_id,
                task_id,
            )
            return

        await self.claim_state.async_claim(
            task_id, period_key, member_id, claimed_at=dt_util.utcnow()
        )
        await self.async_request_refresh()

    async def async_release_task(self, task_id: str, member_id: str | None) -> None:
        """Give back an active "Annehmen" reservation before it expires, no penalty.

        Only the claimant themself may release their own claim - anyone else
        "releasing" it would defeat the point of reserving it in the first
        place. See async_claim_task above.
        """
        if task_id not in self.tasks.data:
            raise HomeAssistantError(f"Unknown task_id '{task_id}'")

        task = self.tasks.data[task_id]
        period_key = self._current_period_key(task_id, task)
        if period_key is None:
            return

        claim_entry = self.claim_state.get(task_id, period_key)
        if claim_entry is None:
            return
        if member_id is None or claim_entry["member_id"] != member_id:
            _LOGGER.debug(
                "Task %s's claim belongs to %s, not %s - ignoring release",
                task_id,
                claim_entry["member_id"],
                member_id,
            )
            return

        await self.claim_state.async_clear(task_id)
        await self.async_request_refresh()

    async def _async_expire_claim(self, task_id: str, task: dict, member_id: str) -> None:
        """A claim's CLAIM_RESERVATION_MINUTES ran out before completion.

        Deducts CLAIM_PENALTY_POINTS from the claimant - logged the same way
        ws_award_points logs a manual adjustment, under MANUAL_POINTS_TASK_ID
        (see const.py), so it counts toward points_total/points_week (and
        thus coins_available, v0.36) exactly like any other award/deduction -
        and drops the claim. The
        caller (_async_update_data) doesn't restore claimed_by_member_id or
        the narrowed eligible_member_ids after calling this, so the
        occurrence is already back open to everyone in this same refresh.
        """
        await self.completions.async_add_entry(
            task_id=MANUAL_POINTS_TASK_ID,
            period_key=dt_util.utcnow().date().isoformat(),
            member_id=member_id,
            points_awarded=-CLAIM_PENALTY_POINTS,
            task_name=f"Reservierung abgelaufen: {task.get('name', 'Aufgabe')}",
        )
        await self.claim_state.async_clear(task_id)
        _LOGGER.debug(
            "Task %s's claim by %s expired unfinished - %s point(s) deducted",
            task_id,
            member_id,
            CLAIM_PENALTY_POINTS,
        )

    def _member_role(self, member_id: str) -> str:
        member = self.members.data.get(member_id)
        return member.get("role", MEMBER_ROLE_PARENT) if member else MEMBER_ROLE_PARENT

    def _member_paused(self, member_id: str) -> bool:
        """Whether a member is currently "paused" - see CONF_MEMBER_PAUSED in const.py."""
        member = self.members.data.get(member_id)
        return bool(member and member.get(CONF_MEMBER_PAUSED, False))

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
        # v0.32: the child has retried - any note left on a previous
        # rejection of this task no longer applies, see "last_rejection_note"/
        # "last_rejection_at" in storage.TASK_UPDATE_SCHEMA and
        # async_skip_task's "confirms" branch below.
        if task.get("last_rejection_note") or task.get("last_rejection_at"):
            await self.tasks.async_update_item(
                task_id, {"last_rejection_note": None, "last_rejection_at": None}
            )

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

        v0.35: if CONF_BATTERY_ALERT_AUTO_COMPLETE_ON_RECOVERY is on, an open
        alert task whose battery is no longer in ``low_batteries`` (it
        recovered - back above threshold, or a binary_sensor no longer
        reporting low) is completed automatically here instead of being left
        open for someone to complete/skip by hand. This runs before the
        "raise a new alert" step below, and regardless of whether any
        battery is currently low, so a household that goes from "one battery
        low" to "none low" in a single refresh still gets that task closed
        out.
        """
        open_alerts: dict[str, str] = {}  # entity_id -> task_id
        for task_id, task in self.tasks.data.items():
            alert = task.get("battery_alert")
            if not alert:
                continue
            anchor_date = task.get("recurrence", {}).get("anchor_date")
            if anchor_date and self.completions.get_last_entry(task_id, anchor_date) is None:
                open_alerts[alert["entity_id"]] = task_id

        low_entity_ids = {battery.entity_id for battery in low_batteries}

        auto_complete_on_recovery = DEFAULT_BATTERY_ALERT_AUTO_COMPLETE_ON_RECOVERY
        if self.config_entry:
            auto_complete_on_recovery = self.config_entry.options.get(
                CONF_BATTERY_ALERT_AUTO_COMPLETE_ON_RECOVERY,
                DEFAULT_BATTERY_ALERT_AUTO_COMPLETE_ON_RECOVERY,
            )
        if auto_complete_on_recovery:
            for entity_id, task_id in open_alerts.items():
                if entity_id in low_entity_ids:
                    continue
                _LOGGER.debug(
                    "Battery %s recovered, auto-completing alert task %s",
                    entity_id,
                    task_id,
                )
                # Scheduled as a separate task rather than awaited inline,
                # same as BatteryStateListener/TaskTriggerListener do for
                # their own coordinator calls - not just style: this method
                # runs *inside* _async_update_data, and async_complete_task
                # ends with await self.async_request_refresh(). Awaiting that
                # here directly would re-enter _async_update_data before this
                # call has returned whenever this refresh was itself invoked
                # via the coordinator's periodic interval timer (which calls
                # _async_refresh() directly, bypassing the request-refresh
                # debouncer's lock that would otherwise make such a
                # reentrant call a no-op) - harmless in the end (the task is
                # already gone from self.tasks.data by then, so the nested
                # refresh just does redundant work), but avoided entirely by
                # not awaiting it here. Same reasoning as
                # async_handle_sensor_normalized for skip_confirmation: the
                # battery's own state change is the proof no one still needs
                # to buy/charge a replacement, so this skips the parent-
                # confirmation step even for a child assignee - in practice
                # a battery-alert task is only ever assigned to admin-linked
                # members (see member_ids below) anyway, so that step would
                # never have applied here regardless.
                self.hass.async_create_task(
                    self.async_complete_task(task_id, skip_confirmation=True)
                )

        if not low_batteries:
            return

        newly_low = [b for b in low_batteries if b.entity_id not in open_alerts]
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

    def _screen_time_tick_adjustment_minutes(self, points_week: int, goal_points: int) -> int:
        """Per-tick minute adjustment for the household's Handyzeit blueprint.

        v0.36: see PROGRESS_BAND_TICK_ADJUSTMENT_MINUTES/PROGRESS_THRESHOLD_PERCENTS
        in const.py and MemberSummaryData.screen_time_tick_adjustment_minutes.
        Banded on this week's progress percent (points_week as a percentage
        of goal_points, the same basis every other weekly-progress figure
        uses) against the fixed 0%/50%/100% bands: -2 while at the 0% band
        (nothing earned this week yet), -1 once at least half the weekly
        goal has been reached, 0 from the full goal onward -
        PROGRESS_BAND_TICK_ADJUSTMENT_MINUTES has no entry above 100 because
        nothing beyond "leave the blueprint's own increment unchanged" ever
        applies once the goal itself is met. Always 0 (no adjustment) when
        goal_points itself is 0 - there is no goal to measure a percentage
        against, so the tick-based grant just runs at the blueprint's own
        configured pace, same as this feature being effectively off.
        """
        if goal_points <= 0:
            return 0
        percent = (points_week / goal_points) * 100
        adjustment = 0
        for band_percent in sorted(PROGRESS_BAND_TICK_ADJUSTMENT_MINUTES):
            if percent >= band_percent:
                adjustment = PROGRESS_BAND_TICK_ADJUSTMENT_MINUTES[band_percent]
        return adjustment

    async def _async_process_milestone_coin_bonus(
        self, start_of_week: datetime, goal_points: int
    ) -> None:
        """Credit "Meilensteinbonus" coins live, the moment a member crosses a checkpoint.

        v0.36: replaces the old configurable-threshold, points-based
        Meilensteinbonus entirely - see CONF_MILESTONE_150_BONUS_COINS/
        CONF_MILESTONE_200_BONUS_COINS in const.py. The two checkpoints are
        now fixed at 150%/200% of the weekly goal (PROGRESS_THRESHOLD_PERCENTS
        in const.py) rather than a household-chosen percent, and the reward
        is coins credited straight to CoinLedgerStore rather than points
        logged to the completion log - so, unlike the old bonus, this can
        never feed back into points_week/the weekly-progress percent it's
        itself judged against. A no-op if ``goal_points``
        (CONF_WEEKLY_PROGRESS_GOAL_POINTS) is 0 - both checkpoints are a
        percentage *of* the weekly goal, so without a goal there is nothing
        for them to be a percentage of.

        Every participating, active member who reaches 150% or 200% *during*
        the current week is credited that tier's bonus immediately, the
        first refresh after they cross it - so it shows up on their
        "Wochenfortschritt" progress bar right away rather than waiting for
        Monday. self.milestone_bonus_state (the same store the pre-v0.36
        version used, reinterpreted - see MilestoneBonusStateStore in
        storage.py) tracks, per member and per threshold slot (slot 1 =
        150%, slot 2 = 200%), whether this week's crossing has already been
        credited, so a refresh that runs again minutes later (nothing having
        changed) never double-credits; that tracking resets itself
        automatically once the calendar week rolls over.

        Eligibility mirrors the leaderboard: only members who participate in
        the reward system (CONF_MEMBER_REWARDS_OPT_IN) and are active.
        """
        if not self.config_entry or goal_points <= 0:
            return
        options = self.config_entry.options
        milestone_150_bonus_coins = options.get(
            CONF_MILESTONE_150_BONUS_COINS, DEFAULT_MILESTONE_150_BONUS_COINS
        )
        milestone_200_bonus_coins = options.get(
            CONF_MILESTONE_200_BONUS_COINS, DEFAULT_MILESTONE_200_BONUS_COINS
        )

        period_key = start_of_week.date().isoformat()
        tiers = (
            (1, COIN_REASON_MILESTONE_150, 150, milestone_150_bonus_coins),
            (2, COIN_REASON_MILESTONE_200, 200, milestone_200_bonus_coins),
        )

        for member_id, member in self.members.data.items():
            if (
                not member.get(CONF_MEMBER_REWARDS_OPT_IN, True)
                or not member.get("active", True)
                # v0.37: paused (temporarily away) is excluded here too -
                # see CONF_MEMBER_PAUSED.
                or member.get(CONF_MEMBER_PAUSED, False)
            ):
                continue
            points_week = self.completions.points_since(member_id, start_of_week)
            for threshold_index, coin_reason, percent, bonus_coins in tiers:
                if bonus_coins <= 0:
                    continue
                threshold_points = round(goal_points * percent / 100)
                if points_week < threshold_points:
                    continue
                if await self.milestone_bonus_state.async_has_awarded(
                    period_key, threshold_index, member_id
                ):
                    continue
                await self.coin_ledger.async_add_entry(
                    member_id=member_id,
                    amount=bonus_coins,
                    reason=coin_reason,
                    note=f"Meilensteinbonus: {percent}% des Wochenziels erreicht",
                )
                await self.milestone_bonus_state.async_mark_awarded(
                    period_key, threshold_index, member_id
                )
                _LOGGER.debug(
                    "Credited %s Meilensteinbonus coin(s) to %s for the %s%% checkpoint in week %s",
                    bonus_coins,
                    member_id,
                    percent,
                    period_key,
                )

    async def _async_process_streak_coin_bonus(
        self, start_of_week: datetime, goal_points: int
    ) -> None:
        """Credit "Streak-Bonus" coins for maintaining a checkpoint across weeks.

        See CONF_STREAK_150_BONUS_COINS/CONF_STREAK_200_BONUS_COINS/
        CONF_STREAK_BONUS_REQUIRED_WEEKS in const.py. v0.36: replaces the old
        single configurable-threshold, points-based Streak-Bonus entirely -
        there are now two independent streaks, one for the fixed 150%
        weekly-progress checkpoint and one for 200%
        (PROGRESS_THRESHOLD_PERCENTS in const.py), each processed exactly
        like the old single streak was (see
        _async_process_member_streak_tier): unlike the Meilensteinbonus
        above (credited live, mid-week), a streak can only be judged once a
        week has actually ended - so each tier catches its member up on
        every fully-elapsed calendar week since that tier's
        StreakBonusStateStore cursor last stopped, oldest first, judging
        each one against the tier's checkpoint and incrementing/resetting a
        per-tier streak counter. Once a tier's counter reaches
        streak_bonus_required_weeks, *every* further consecutive week that
        still meets that checkpoint credits the bonus again (rolling) - a
        maintained streak, not a one-off reward for first reaching it. A
        no-op if goal_points is 0 - both checkpoints are a percentage of the
        weekly goal.

        A brand-new member (or a tier's very first run) starts its cursor at
        "last week" rather than the beginning of time, so turning a bonus on
        doesn't retroactively grind through a household's entire history -
        same reasoning as the Meilensteinbonus only ever reacting to the
        current week.
        """
        if not self.config_entry or goal_points <= 0:
            return
        options = self.config_entry.options
        required_weeks = options.get(
            CONF_STREAK_BONUS_REQUIRED_WEEKS, DEFAULT_STREAK_BONUS_REQUIRED_WEEKS
        )
        if required_weeks <= 0:
            return
        streak_150_bonus_coins = options.get(
            CONF_STREAK_150_BONUS_COINS, DEFAULT_STREAK_150_BONUS_COINS
        )
        streak_200_bonus_coins = options.get(
            CONF_STREAK_200_BONUS_COINS, DEFAULT_STREAK_200_BONUS_COINS
        )
        tiers = (
            ("150", 150, streak_150_bonus_coins, COIN_REASON_STREAK_150),
            ("200", 200, streak_200_bonus_coins, COIN_REASON_STREAK_200),
        )

        for tier, percent, bonus_coins, coin_reason in tiers:
            if bonus_coins <= 0:
                continue
            target_points = round(goal_points * percent / 100)
            for member_id, member in self.members.data.items():
                if (
                    not member.get(CONF_MEMBER_REWARDS_OPT_IN, True)
                    or not member.get("active", True)
                    # v0.37: paused (temporarily away) is excluded here too -
                    # see CONF_MEMBER_PAUSED.
                    or member.get(CONF_MEMBER_PAUSED, False)
                ):
                    continue
                await self._async_process_member_streak_tier(
                    member_id,
                    tier,
                    start_of_week,
                    target_points,
                    required_weeks,
                    bonus_coins,
                    percent,
                    coin_reason,
                )

    async def _async_process_member_streak_tier(
        self,
        member_id: str,
        tier: str,
        start_of_week: datetime,
        target_points: int,
        required_weeks: int,
        bonus_coins: int,
        percent: int,
        coin_reason: str,
    ) -> None:
        """Catch up one member's Streak-Bonus cursor, for one tier, through every elapsed week."""
        state = self.streak_bonus_state.get(member_id, tier)
        if state and state.get("processed_through"):
            cursor = dt_util.parse_datetime(state["processed_through"]) or (
                start_of_week - timedelta(days=7)
            )
        else:
            cursor = start_of_week - timedelta(days=7)
        streak_count = state.get("streak_count", 0) if state else 0

        # Cap how many weeks a single refresh catches up on, in case a
        # household was offline for a very long time - the streak still
        # ends up correct, just spread across a few extra refreshes instead
        # of one long blocking loop.
        weeks_processed = 0
        while cursor < start_of_week and weeks_processed < 52:
            week_points = self.completions.points_between(
                member_id, cursor, cursor + timedelta(days=7)
            )
            if week_points >= target_points:
                streak_count += 1
            else:
                streak_count = 0
            if streak_count >= required_weeks:
                await self.coin_ledger.async_add_entry(
                    member_id=member_id,
                    amount=bonus_coins,
                    reason=coin_reason,
                    note=(
                        f"Streak-Bonus: {streak_count}. Woche in Folge "
                        f"über der {percent}%-Marke"
                    ),
                )
                _LOGGER.debug(
                    "Credited %s Streak-Bonus coin(s) to %s for tier %s, week of %s (streak %s)",
                    bonus_coins,
                    member_id,
                    tier,
                    dt_util.as_local(cursor).date().isoformat(),
                    streak_count,
                )
            cursor += timedelta(days=7)
            weeks_processed += 1

        if weeks_processed:
            await self.streak_bonus_state.async_set(member_id, tier, cursor, streak_count)

    async def _async_process_weekly_coin_conversion(
        self, start_of_week: datetime, goal_points: int
    ) -> None:
        """Finalize every member's fully-elapsed weeks into durable coin credits.

        See WeeklyCoinConversionStateStore/COIN_REASON_WEEKLY_CONVERSION in
        const.py for why this exists - in short, coins_from_task_points used
        to be recomputed live from CompletionLogStore for every week since
        the coin system started, which quietly lost old weeks' surplus once
        their completions aged out of that (intentionally bounded) log. Once
        a week is over, its surplus is credited here instead, exactly once,
        and lives in CoinLedgerStore (never pruned) from then on - only the
        still-open current week keeps being computed live (see
        coins_available in _async_update_data above).

        Unlike the Meilenstein-/Streak-coin bonuses, there is no
        enabled/amount check to gate this on - the base points-to-coins
        conversion always applies, the same as it unconditionally did before
        this method existed.
        """
        since = self.coin_system_state.started_at
        for member_id in self.members.data:
            await self._async_process_member_weekly_coin_conversion(
                member_id, start_of_week, goal_points, since
            )

    async def _async_process_member_weekly_coin_conversion(
        self,
        member_id: str,
        start_of_week: datetime,
        goal_points: int,
        since: datetime,
    ) -> None:
        """Catch up one member's weekly-coin-conversion cursor through every elapsed week.

        Weeks are walked Monday-to-Monday (local time), same boundary
        coins_from_task_points itself buckets by and start_of_week already
        uses - starting from whichever is later: the cursor's last processed
        week, or the calendar week ``since`` (the coin system's cutover
        instant) falls in. A week's own point total is clamped to not
        include anything before ``since`` (points_between(max(week_start,
        since), week_end)), same "a week straddling the cutover slightly
        undercounts" one-time edge case coins_from_task_points' docstring
        already accepts - everything *after* the cutover is unaffected.

        Each week's surplus (points beyond ``goal_points``, or the week's
        full total if no goal is configured - mirrors coins_from_task_points'
        two branches) is floored at 0 individually before being credited, so
        one week with more manual-deduction penalties than points earned can
        never eat into coins a *different*, already-finalized week legitimately
        earned - slightly more conservative than the pre-v0.37 lifetime-sum
        behaviour for the no-goal-configured case, and intentionally so.

        Capped at 104 weeks per refresh, same reasoning as
        _async_process_member_streak_tier's cap: a household offline for a
        very long time (or upgrading long after the coin system's cutover)
        still ends up correct, just caught up over a few extra refreshes
        instead of one long blocking loop.
        """
        local_since = dt_util.as_local(since)
        since_week_start = dt_util.as_utc(
            dt_util.start_of_local_day(local_since) - timedelta(days=local_since.weekday())
        )
        cursor = self.weekly_coin_conversion_state.processed_through(member_id)
        if cursor is None or cursor < since_week_start:
            cursor = since_week_start

        weeks_processed = 0
        while cursor < start_of_week and weeks_processed < 104:
            week_end = cursor + timedelta(days=7)
            week_points = self.completions.points_between(member_id, max(cursor, since), week_end)
            surplus = max(0, week_points - goal_points) if goal_points > 0 else max(0, week_points)
            if surplus > 0:
                await self.coin_ledger.async_add_entry(
                    member_id=member_id,
                    amount=surplus,
                    reason=COIN_REASON_WEEKLY_CONVERSION,
                    note=(
                        f"Wochenabschluss {dt_util.as_local(cursor).date().isoformat()}: "
                        f"{surplus} Punkt(e) in Münzen umgewandelt"
                    ),
                )
                _LOGGER.debug(
                    "Converted %s point(s) beyond the weekly goal to coin(s) for %s, "
                    "week of %s",
                    surplus,
                    member_id,
                    dt_util.as_local(cursor).date().isoformat(),
                )
            cursor = week_end
            weeks_processed += 1

        if weeks_processed:
            await self.weekly_coin_conversion_state.async_set(member_id, cursor)

    async def async_reset_points(self, member_id: str | None = None) -> None:
        """Reset stored *points* data - see SERVICE_RESET_POINTS in const.py.

        Clears the completion log (points_total/points_week/.../history),
        reward redemptions, the coin ledger (v0.36 - milestone/streak coin
        bonuses, weekly-conversion credits (v0.37), and past redemption
        debits alike, so coins_available is no longer reduced by past
        purchases either), and the Meilenstein-/Streak-Bonus/weekly-coin-
        conversion (v0.37) tracking state. Task and member *definitions* and
        the reward catalog itself are left completely untouched - this only
        ever resets *earned/spent points and coins*, never the household's
        setup. ``member_id`` left unset (None) resets every member at once;
        given, only that member's data is cleared.
        """
        await self.completions.async_reset(member_id)
        for redemption_id, redemption in list(self.reward_redemptions.data.items()):
            if member_id is None or redemption.get("member_id") == member_id:
                await self.reward_redemptions.async_delete_item(redemption_id)
        await self.coin_ledger.async_reset(member_id)
        await self.milestone_bonus_state.async_reset(member_id)
        await self.streak_bonus_state.async_reset(member_id)
        # v0.37: without this, a member whose completion history was just
        # wiped would keep a stale "already converted through <date>" cursor
        # pointing at weeks that no longer have any completions behind them,
        # instead of those weeks being (correctly, now that they're empty)
        # re-judged as contributing 0 coins next refresh.
        await self.weekly_coin_conversion_state.async_reset(member_id)
        _LOGGER.info("Reset points data for %s", member_id or "every member")
        await self.async_request_refresh()

    async def async_set_vacation_mode(self, is_active: bool) -> None:
        """Turn the household-wide Urlaubsmodus on/off - see switch.py."""
        await self.vacation_mode_state.async_set(is_active)
        await self.async_request_refresh()

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
        """Check/uncheck one sub-item of a task's checklist.

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
        if not task.get("subtasks"):
            raise HomeAssistantError(f"Task '{task_id}' has no checklist")

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

    async def async_handle_sensor_normalized(self, task_id: str) -> None:
        """Auto-complete a trigger task's open occurrence once its sensor normalizes.

        v0.34: called by :class:`~.trigger.TaskTriggerListener` when a task's
        trigger definition has its optional ``auto_complete_on_normalize``
        flag set (see ``TASK_TRIGGER_STATE_SCHEMA``/
        ``TASK_TRIGGER_NUMERIC_STATE_SCHEMA`` in storage.py) and the bound
        sensor transitions back out of the condition that opened the
        occurrence - e.g. "Mülleimer leeren" completing itself the moment
        the bin sensor reports empty again, instead of someone having to
        press "Erledigt" by hand.

        Delegates to :meth:`async_complete_task` with ``skip_confirmation``
        set - the sensor's own state change *is* the proof of completion, so
        even a task normally assigned to a "child" with
        ``requires_confirmation`` on is logged as done immediately, with no
        parent sign-off step raised for it. A no-op if there's no open
        occurrence to complete (the flag was only just turned on after the
        sensor had already normalized, or the occurrence was already
        completed/skipped by hand in the meantime) - mirrors the "already
        open" guard in async_handle_sensor_trigger above.
        """
        if task_id not in self.tasks.data:
            return
        if self.trigger_state.get(task_id) is None:
            _LOGGER.debug(
                "Task %s has no open trigger occurrence to auto-complete", task_id
            )
            return
        await self.async_complete_task(task_id, skip_confirmation=True)

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
