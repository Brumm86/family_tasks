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
            # Current spendable balance for the reward system (v0.9):
            # points_total minus everything this member has already redeemed
            # - see FamilyTasksCoordinator._async_update_data /
            # MemberSummaryData.points_available in coordinator.py. Drives
            # the leaderboard card's balance display and reward-affordability
            # check.
            "points_available": member.points_available,
            # v0.30: household-wide Meilensteinbonus settings, identical on
            # every member's points sensor - see
            # FamilyTasksData.milestone_bonus_enabled/... in coordinator.py
            # for why this rides along here instead of living on a dedicated
            # entity. Drives the two threshold markers (and their bonus
            # labels) the card draws on each "Wochenfortschritt" progress
            # bar. Replaces the pre-v0.30 weekly_winner_bonus_enabled/...points
            # attributes entirely.
            "milestone_bonus_enabled": self.coordinator.data.milestone_bonus_enabled,
            "milestone_1_threshold_percent": self.coordinator.data.milestone_1_threshold_percent,
            "milestone_1_bonus_points": self.coordinator.data.milestone_1_bonus_points,
            "milestone_2_threshold_percent": self.coordinator.data.milestone_2_threshold_percent,
            "milestone_2_bonus_points": self.coordinator.data.milestone_2_bonus_points,
            # v0.32: the absolute point value each threshold above works out
            # to this week, computed once server-side (round(), same as the
            # awarding logic itself uses) - see
            # FamilyTasksData.milestone_1_threshold_points in coordinator.py.
            # The card shows these directly instead of recomputing
            # threshold_percent -> points itself, so it can never disagree
            # with the backend on a borderline .5 rounding case.
            "milestone_1_threshold_points": self.coordinator.data.milestone_1_threshold_points,
            "milestone_2_threshold_points": self.coordinator.data.milestone_2_threshold_points,
            # v0.32: household-wide Streak-Bonus settings (see
            # CONF_STREAK_BONUS_ENABLED in const.py) - same "rides along,
            # identical on every member's points sensor" reasoning as the
            # Meilensteinbonus attributes above.
            "streak_bonus_enabled": self.coordinator.data.streak_bonus_enabled,
            "streak_bonus_threshold_points": self.coordinator.data.streak_bonus_threshold_points,
            "streak_bonus_required_weeks": self.coordinator.data.streak_bonus_required_weeks,
            "streak_bonus_points": self.coordinator.data.streak_bonus_points,
            "streak_bonus_target_points": self.coordinator.data.streak_bonus_target_points,
            # v0.32: this member's current consecutive-week streak length -
            # see MemberSummaryData.streak_weeks in coordinator.py.
            "streak_weeks": member.streak_weeks,
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
        new_tasks = set(coordinator.data.tasks) - known_tasks
        new_members = set(coordinator.data.members) - known_members

        entities: list[SensorEntity] = []
        for task_id in new_tasks:
            entities.append(FamilyTasksTaskStatusSensor(coordinator, entry, task_id))
        for member_id in new_members:
            entities.append(
                FamilyTasksMemberPointsSensor(coordinator, entry, member_id)
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
                f"{entry.entry_id}_task_{tid}_status" for tid in coordinator.data.tasks
            }
            | {
                f"{entry.entry_id}_member_{mid}_points" for mid in coordinator.data.members
            }
            | {
                f"{entry.entry_id}_member_{mid}_open_tasks"
                for mid in coordinator.data.members
            },
        )
        known_tasks.intersection_update(coordinator.data.tasks)
        known_members.intersection_update(coordinator.data.members)

    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_entities))
    _async_add_new_entities()
