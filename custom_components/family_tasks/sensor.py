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
            # Every member currently responsible for this occurrence - for a
            # "fixed" rotation with more than one member this lists all of
            # them (see FamilyTasksCoordinator._assigned_member_ids); for
            # everything else it's just [assigned_member_id].
            "assigned_member_ids": task.assigned_member_ids,
            # v0.25: who may currently act on (complete) this occurrence -
            # assigned_member_ids plus, once overdue and assigned to a child,
            # every other active child in the household (see
            # eligible_member_ids in coordinator.py). The card uses this
            # instead of assigned_member_ids for the "own tasks" filter and
            # the "Erledigt" button so a sibling can step in on an overdue
            # task instead of just watching it sit there.
            "eligible_member_ids": task.eligible_member_ids,
            "due_at": task.due_at.isoformat() if task.due_at else None,
            # v0.27: due_at plus the task's Karenzzeit - the clock moment
            # this occurrence flips from pending to overdue, shown by the
            # card as "Zu erledigen bis HH:MM" - see TaskStatusData.
            # deadline_at in coordinator.py.
            "deadline_at": task.deadline_at.isoformat() if task.deadline_at else None,
            # v0.27: "Annehmen" reservation state - see ClaimStateStore in
            # storage.py / TaskStatusData.claimed_by_member_id/
            # claim_expires_at/claimable in coordinator.py. While
            # claimed_by_member_id is set, eligible_member_ids above is
            # already narrowed down to just that member.
            "claimed_by_member_id": task.claimed_by_member_id,
            "claim_expires_at": task.claim_expires_at.isoformat()
            if task.claim_expires_at
            else None,
            "claimable": task.claimable,
            "points": task.points,
            "period_key": task.period_key,
            "last_completed_by": task.last_completed_by,
            "last_completed_at": task.last_completed_at.isoformat()
            if task.last_completed_at
            else None,
            # Only non-empty for recurrence type "battery" (see
            # RECURRENCE_BATTERY in const.py): every currently monitored
            # battery at/below its warning threshold, so the card can list
            # exactly which ones need charging/swapping.
            "battery_entities": task.battery_entities,
            # Only set for recurrence type "trigger": the bound sensor's
            # current state/value and unit, so the card can show it
            # alongside the trigger definition.
            "trigger_sensor_value": task.trigger_sensor_value,
            "trigger_sensor_unit": task.trigger_sensor_unit,
            # Only non-empty for a TASK_KIND_CHECKLIST task: every sub-item
            # with its current checked state, as {id, name, checked}.
            "subtasks": task.subtasks,
            # standard / checklist / mandatory (v0.14) - see TASK_KINDS in
            # const.py, lets an automation identify a "Pflichtaufgabe"
            # without needing the raw stored task object.
            "kind": task.kind,
            # v0.22: only set for a task a "child" member created for
            # themselves - see CONF_TASK_CREATED_BY_MEMBER_ID in const.py.
            # The card uses this to hide such a task from everyone except the
            # member it names.
            "created_by_member_id": task.created_by_member_id,
            # v0.32: "show"/"pause" - see CONF_TASK_VACATION_BEHAVIOR in
            # const.py. Lets the card's task-edit form pre-fill the current
            # choice.
            "vacation_behavior": task.vacation_behavior,
            # v0.32: a parent's note from the last time this task's claim was
            # rejected, and when - both None once the child has retried. See
            # async_skip_task in coordinator.py.
            "last_rejection_note": task.last_rejection_note,
            "last_rejection_at": task.last_rejection_at.isoformat()
            if task.last_rejection_at
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
            # v0.36: this member's current "Münzen" balance - also the
            # native state of the dedicated FamilyTasksMemberCoinsSensor
            # below, repeated here (same "rides along" pattern as the other
            # options-derived attributes on this sensor) purely so the card
            # can read a member's balance off the same points-sensor lookup
            # it already does for everything else on the "Wochenfortschritt"
            # bar, without a second sensor lookup keyed differently. See
            # MemberSummaryData.coins_available in coordinator.py.
            "coins_available": member.coins_available,
            # v0.36: how many minutes to add to the household's Handyzeit
            # blueprint's own configured per-tick increment for this member
            # right now (negative = reduce it) - see
            # PROGRESS_BAND_TICK_ADJUSTMENT_MINUTES in const.py and
            # MemberSummaryData.screen_time_tick_adjustment_minutes in
            # coordinator.py. Meant to be read by the blueprint's optional
            # screen_time_tick_adjustment_source_entity input via
            # state_attr(...), not by the card.
            "screen_time_tick_adjustment_minutes": member.screen_time_tick_adjustment_minutes,
            # v0.36: household-wide Meilensteinbonus coin amounts, identical
            # on every member's points sensor - see
            # FamilyTasksData.milestone_150_bonus_coins/... in coordinator.py
            # for why this rides along here instead of living on a dedicated
            # entity. Drives the two fixed 150%/200% threshold markers (and
            # their bonus labels) the card draws on each "Wochenfortschritt"
            # progress bar. Replaces the pre-v0.36 configurable-threshold
            # milestone_bonus_enabled/milestone_1_*/milestone_2_* attributes
            # entirely.
            "milestone_150_bonus_coins": self.coordinator.data.milestone_150_bonus_coins,
            "milestone_200_bonus_coins": self.coordinator.data.milestone_200_bonus_coins,
            # v0.32: the absolute point value each fixed checkpoint above
            # works out to this week, computed once server-side (round(),
            # same as the awarding logic itself uses) - see
            # FamilyTasksData.milestone_150_threshold_points in
            # coordinator.py. The card shows these directly instead of
            # recomputing percent -> points itself, so it can never disagree
            # with the backend on a borderline .5 rounding case. Also the
            # per-week target each Streak-Bonus tier below is judged against.
            "milestone_150_threshold_points": self.coordinator.data.milestone_150_threshold_points,
            "milestone_200_threshold_points": self.coordinator.data.milestone_200_threshold_points,
            # v0.36: household-wide Streak-Bonus coin amounts, one per tier
            # (see CONF_STREAK_150_BONUS_COINS/CONF_STREAK_200_BONUS_COINS in
            # const.py) - same "rides along, identical on every member's
            # points sensor" reasoning as the Meilensteinbonus attributes
            # above. Replaces the pre-v0.36 single configurable-threshold
            # streak_bonus_enabled/...threshold_points/...points attributes
            # entirely.
            "streak_150_bonus_coins": self.coordinator.data.streak_150_bonus_coins,
            "streak_200_bonus_coins": self.coordinator.data.streak_200_bonus_coins,
            "streak_bonus_required_weeks": self.coordinator.data.streak_bonus_required_weeks,
            # v0.32: this member's current consecutive-week streak length,
            # one per fixed tier since v0.36 - see
            # MemberSummaryData.streak_weeks_150/streak_weeks_200 in
            # coordinator.py.
            "streak_weeks_150": member.streak_weeks_150,
            "streak_weeks_200": member.streak_weeks_200,
            # v0.23: household-wide default rotation strategy (see
            # CONF_DEFAULT_ROTATION_STRATEGY in const.py), identical on every
            # member's points sensor - same "rides along, no dedicated
            # entity" reasoning as the Meilensteinbonus attributes above. The
            # card reads this to pre-select "Rotationstyp" when opening the
            # "+ Aufgabe hinzufügen" form.
            "default_rotation_strategy": self.coordinator.data.default_rotation_strategy,
            # v0.29: household-wide weekly point goal (see
            # CONF_WEEKLY_PROGRESS_GOAL_POINTS in const.py), identical on
            # every member's points sensor - same "rides along, no dedicated
            # entity" reasoning as the attributes above. Drives the card's
            # "Wochenfortschritt" progress-bar target; 0 means no goal is
            # configured (every earned point is immediately spendable).
            "weekly_progress_goal_points": self.coordinator.data.weekly_progress_goal_points,
            # v0.32: whether Urlaubsmodus is currently on - also the native
            # on/off state of switch.FamilyTasksVacationModeSwitch, repeated
            # here purely so the card can read it off this same per-refresh
            # snapshot without separately looking up that entity by id.
            "vacation_mode_active": self.coordinator.data.vacation_mode_active,
        }


class FamilyTasksMemberCoinsSensor(
    CoordinatorEntity[FamilyTasksCoordinator], SensorEntity
):
    """A member's current "Münzen" (coins) balance for the reward shop.

    v0.36: the reward shop's currency, entirely separate from points now -
    see MemberSummaryData.coins_available in coordinator.py. Unlike the
    Meilenstein-/Streak-Bonus settings and screen_time_tick_adjustment_minutes
    (which ride along on FamilyTasksMemberPointsSensor as plain attributes,
    since they're just options values or a single number with nowhere else
    to attach), the coin balance itself is a primary, user-facing figure a
    household will want to see at a glance and put on a dashboard directly -
    it gets its own dedicated entity instead.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:hand-coin-outline"
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(
        self, coordinator: FamilyTasksCoordinator, entry: FamilyTasksConfigEntry, member_id: str
    ) -> None:
        super().__init__(coordinator)
        self._member_id = member_id
        self._attr_unique_id = f"{entry.entry_id}_member_{member_id}_coins"
        self._attr_device_info = _device_info(entry)
        self._attr_translation_key = "member_coins"

    @property
    def available(self) -> bool:
        return super().available and self._member_id in self.coordinator.data.members

    @property
    def _member(self):
        return self.coordinator.data.members[self._member_id]

    @property
    def name(self) -> str:
        return f"{self._member.name} Münzen"

    @property
    def native_value(self) -> int:
        return self._member.coins_available

    @property
    def extra_state_attributes(self) -> dict:
        return {"member_id": self._member_id}


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
        # v0.33: which task ids "exist" for entity add/prune purposes is
        # decided from coordinator.tasks.data (the actual configured task
        # storage collection) rather than coordinator.data.tasks (the
        # *current refresh's computed status snapshot*, which omits a task
        # entirely while it's disabled or paused for Urlaubsmodus - see
        # CONF_TASK_VACATION_BEHAVIOR/vacation_mode_active in
        # _async_update_data). Using the latter here used to mean a task's
        # status sensor got deleted via async_prune_stale_entities the
        # moment it was paused (not merely marked unavailable), and then
        # never recreated for as long as it stayed paused, since it was also
        # never "new" again from this loop's point of view - the entity
        # simply vanished from the registry, and the card's per-task
        # websocket data (which lists the task regardless of its sensor)
        # then fell back to displaying it as a plain, unassigned "offen"
        # occurrence instead of hiding it. self._task_id in
        # self.coordinator.data.tasks (the `available` property above)
        # already handles marking such a sensor unavailable while paused -
        # that's the only thing that should change on pause/resume, not
        # whether the entity exists at all.
        new_tasks = set(coordinator.tasks.data) - known_tasks
        new_members = set(coordinator.data.members) - known_members

        entities: list[SensorEntity] = []
        for task_id in new_tasks:
            entities.append(FamilyTasksTaskStatusSensor(coordinator, entry, task_id))
        for member_id in new_members:
            entities.append(
                FamilyTasksMemberPointsSensor(coordinator, entry, member_id)
            )
            entities.append(
                FamilyTasksMemberCoinsSensor(coordinator, entry, member_id)
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
                f"{entry.entry_id}_task_{tid}_status" for tid in coordinator.tasks.data
            }
            | {
                f"{entry.entry_id}_member_{mid}_points" for mid in coordinator.data.members
            }
            | {
                f"{entry.entry_id}_member_{mid}_coins" for mid in coordinator.data.members
            }
            | {
                f"{entry.entry_id}_member_{mid}_open_tasks"
                for mid in coordinator.data.members
            },
        )
        known_tasks.intersection_update(coordinator.tasks.data)
        known_members.intersection_update(coordinator.data.members)

    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_entities))
    _async_add_new_entities()
