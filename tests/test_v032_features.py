"""Tests for the v0.32 features:

- ``reset_points`` service (FamilyTasksCoordinator.async_reset_points):
  clears the completion log, reward redemptions, and Meilenstein-/Streak-
  Bonus tracking, optionally scoped to one member.
- Urlaubsmodus (VacationModeStateStore / switch.py): a task with
  vacation_behavior="pause" is skipped entirely while active; "show" (the
  default) is unaffected.
- Streak-Bonus (CONF_STREAK_BONUS_ENABLED and friends): bonus points for
  consecutive already-elapsed weeks above weekly_progress_goal_points +
  streak_bonus_threshold_points - see
  FamilyTasksCoordinator._async_process_streak_bonus.
- Absolute Meilenstein threshold points (FamilyTasksData.
  milestone_1_threshold_points/...2_threshold_points) exposed alongside the
  existing percent-based settings, computed with the exact round() the
  awarding logic itself uses.
- Ablehnungsnotiz: async_skip_task's optional "note" is stored both on the
  rejection's completion-log entry and on the original task
  (last_rejection_note/...at), then cleared again once the child retries.
- A claimed Aufgabenpool occurrence is firmly attributed to its claimant
  (assigned_member_id/assigned_member_ids), not left looking unassigned.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from homeassistant.util import dt as dt_util

from custom_components.family_tasks.const import (
    CONF_STREAK_BONUS_ENABLED,
    CONF_STREAK_BONUS_POINTS,
    CONF_STREAK_BONUS_REQUIRED_WEEKS,
    CONF_STREAK_BONUS_THRESHOLD_POINTS,
    CONF_TASK_VACATION_BEHAVIOR,
    CONF_WEEKLY_PROGRESS_GOAL_POINTS,
    MANUAL_POINTS_TASK_ID,
    STREAK_BONUS_TASK_ID,
    TASK_STATUS_AWAITING_CONFIRMATION,
    TASK_STATUS_PENDING,
    VACATION_BEHAVIOR_PAUSE,
)


async def _add_task(runtime, *, member_ids, **overrides):
    payload = {
        "name": "Testaufgabe",
        "points": 5,
        "recurrence": {"type": "daily"},
        "rotation": {"member_ids": member_ids, "strategy": "fixed"},
    }
    payload.update(overrides)
    return await runtime.tasks.async_create_item(payload)


def _start_of_week_utc(offset_weeks: int = 0):
    """Mirror FamilyTasksCoordinator._async_update_data's start_of_week math."""
    local_now = dt_util.now()
    start_of_today = dt_util.as_utc(dt_util.start_of_local_day(local_now))
    start_of_week = start_of_today - timedelta(days=start_of_today.weekday())
    return start_of_week + timedelta(weeks=offset_weeks)


async def _refresh_at_utc(runtime, utc_dt) -> None:
    local_dt = dt_util.as_local(utc_dt)
    with (
        patch.object(dt_util, "now", return_value=local_dt),
        patch.object(dt_util, "utcnow", return_value=utc_dt),
    ):
        await runtime.coordinator.async_refresh()


async def _complete_at_utc(runtime, task_id, utc_dt, member_id=None) -> None:
    local_dt = dt_util.as_local(utc_dt)
    with (
        patch.object(dt_util, "now", return_value=local_dt),
        patch.object(dt_util, "utcnow", return_value=utc_dt),
    ):
        await runtime.coordinator.async_complete_task(task_id, member_id)


async def _add_points_at_utc(runtime, member_id, points, utc_dt) -> None:
    """Log a manual completion entry as if it happened at ``utc_dt``.

    Used by the Streak-Bonus tests below to backdate points into a specific
    already-elapsed calendar week without needing a real task/recurrence for
    each one.
    """
    with patch.object(dt_util, "utcnow", return_value=utc_dt):
        await runtime.completions.async_add_entry(
            task_id="manual_test",
            period_key=utc_dt.date().isoformat(),
            member_id=member_id,
            points_awarded=points,
        )


# --- reset_points -------------------------------------------------------------


async def test_reset_points_clears_history_for_one_member_only(
    hass, init_integration
) -> None:
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})
    ben = await runtime.members.async_create_item({"name": "Ben"})
    task_a = await _add_task(runtime, member_ids=[anna["id"]], points=10)
    task_b = await _add_task(runtime, member_ids=[ben["id"]], points=7)
    await runtime.coordinator.async_refresh()
    await runtime.coordinator.async_complete_task(task_a["id"])
    await runtime.coordinator.async_complete_task(task_b["id"])
    await runtime.coordinator.async_refresh()

    assert runtime.coordinator.data.members[anna["id"]].points_total == 10
    assert runtime.coordinator.data.members[ben["id"]].points_total == 7

    await runtime.coordinator.async_reset_points(anna["id"])
    await runtime.coordinator.async_refresh()

    assert runtime.coordinator.data.members[anna["id"]].points_total == 0
    assert runtime.coordinator.data.members[ben["id"]].points_total == 7


async def test_reset_points_without_member_id_resets_everyone(
    hass, init_integration
) -> None:
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})
    ben = await runtime.members.async_create_item({"name": "Ben"})
    task_a = await _add_task(runtime, member_ids=[anna["id"]], points=10)
    task_b = await _add_task(runtime, member_ids=[ben["id"]], points=7)
    await runtime.coordinator.async_refresh()
    await runtime.coordinator.async_complete_task(task_a["id"])
    await runtime.coordinator.async_complete_task(task_b["id"])

    reward = await runtime.rewards.async_create_item({"name": "Kino", "points_cost": 3})
    await runtime.reward_redemptions.async_create_item(
        {
            "member_id": anna["id"],
            "member_name": "Anna",
            "reward_id": reward["id"],
            "reward_name": "Kino",
            "points_cost": 3,
        }
    )
    await runtime.coordinator.async_refresh()

    await runtime.coordinator.async_reset_points()
    await runtime.coordinator.async_refresh()

    assert runtime.coordinator.data.members[anna["id"]].points_total == 0
    assert runtime.coordinator.data.members[ben["id"]].points_total == 0
    assert not runtime.reward_redemptions.data
    assert not runtime.completions.entries


async def test_reset_points_leaves_tasks_members_and_catalog_untouched(
    hass, init_integration
) -> None:
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})
    task = await _add_task(runtime, member_ids=[anna["id"]], points=10)
    reward = await runtime.rewards.async_create_item({"name": "Kino", "points_cost": 3})
    await runtime.coordinator.async_refresh()
    await runtime.coordinator.async_complete_task(task["id"])

    await runtime.coordinator.async_reset_points()

    assert task["id"] in runtime.tasks.data
    assert anna["id"] in runtime.members.data
    assert reward["id"] in runtime.rewards.data


# --- Urlaubsmodus ---------------------------------------------------------------


async def test_vacation_mode_pauses_only_opted_in_tasks(hass, init_integration) -> None:
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})
    paused_task = await _add_task(
        runtime,
        member_ids=[anna["id"]],
        name="Pausiert im Urlaub",
        **{CONF_TASK_VACATION_BEHAVIOR: VACATION_BEHAVIOR_PAUSE},
    )
    normal_task = await _add_task(runtime, member_ids=[anna["id"]], name="Läuft weiter")
    await runtime.coordinator.async_refresh()
    assert paused_task["id"] in runtime.coordinator.data.tasks
    assert normal_task["id"] in runtime.coordinator.data.tasks

    await runtime.coordinator.async_set_vacation_mode(True)
    await runtime.coordinator.async_refresh()

    assert runtime.coordinator.data.vacation_mode_active is True
    assert paused_task["id"] not in runtime.coordinator.data.tasks
    assert normal_task["id"] in runtime.coordinator.data.tasks

    await runtime.coordinator.async_set_vacation_mode(False)
    await runtime.coordinator.async_refresh()
    assert paused_task["id"] in runtime.coordinator.data.tasks


async def test_vacation_mode_state_persists_across_store_reload(
    hass, init_integration
) -> None:
    runtime = init_integration.runtime_data
    await runtime.coordinator.async_set_vacation_mode(True)

    from custom_components.family_tasks.storage import VacationModeStateStore

    reloaded = VacationModeStateStore(hass, default_active=False)
    await reloaded.async_load()
    assert reloaded.is_active is True


# --- Streak-Bonus ---------------------------------------------------------------


async def test_streak_bonus_awarded_after_required_consecutive_weeks(
    hass, init_integration
) -> None:
    """Week -2 already judged (streak 1, seeded directly via the state
    store - see StreakBonusStateStore); week -1 also meets target, so the
    second consecutive qualifying week should award the bonus the first
    refresh that happens once it has fully elapsed."""
    runtime = init_integration.runtime_data
    hass.config_entries.async_update_entry(
        init_integration,
        options={
            CONF_STREAK_BONUS_ENABLED: True,
            CONF_STREAK_BONUS_THRESHOLD_POINTS: 10,
            CONF_STREAK_BONUS_REQUIRED_WEEKS: 2,
            CONF_STREAK_BONUS_POINTS: 4,
        },
    )
    anna = await runtime.members.async_create_item({"name": "Anna"})
    monday = _start_of_week_utc(0)

    await runtime.streak_bonus_state.async_set(anna["id"], monday - timedelta(weeks=1), 1)
    await _add_points_at_utc(runtime, anna["id"], 10, monday - timedelta(weeks=1, days=-1))

    await _refresh_at_utc(runtime, monday + timedelta(hours=1))

    streak_entries = [
        e for e in runtime.completions.entries if e["task_id"] == STREAK_BONUS_TASK_ID
    ]
    assert len(streak_entries) == 1
    assert streak_entries[0]["points_awarded"] == 4
    assert runtime.coordinator.data.members[anna["id"]].streak_weeks == 2


async def test_streak_bonus_resets_after_a_missed_week(hass, init_integration) -> None:
    """Week -2 (seeded as already having a streak of 1) falls below target
    this time, so the streak must reset to 0 before counting week -1 fresh -
    not enough on its own for the (2-week) bonus yet."""
    runtime = init_integration.runtime_data
    hass.config_entries.async_update_entry(
        init_integration,
        options={
            CONF_STREAK_BONUS_ENABLED: True,
            CONF_STREAK_BONUS_THRESHOLD_POINTS: 10,
            CONF_STREAK_BONUS_REQUIRED_WEEKS: 2,
            CONF_STREAK_BONUS_POINTS: 4,
        },
    )
    anna = await runtime.members.async_create_item({"name": "Anna"})
    monday = _start_of_week_utc(0)

    await runtime.streak_bonus_state.async_set(anna["id"], monday - timedelta(weeks=2), 1)
    await _add_points_at_utc(runtime, anna["id"], 2, monday - timedelta(weeks=2, days=-1))
    await _add_points_at_utc(runtime, anna["id"], 10, monday - timedelta(weeks=1, days=-1))

    await _refresh_at_utc(runtime, monday + timedelta(hours=1))

    assert not any(
        e["task_id"] == STREAK_BONUS_TASK_ID for e in runtime.completions.entries
    )
    assert runtime.coordinator.data.members[anna["id"]].streak_weeks == 1


async def test_streak_bonus_disabled_by_default(hass, init_integration) -> None:
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})
    task = await _add_task(runtime, member_ids=[anna["id"]], points=20)
    await runtime.coordinator.async_refresh()
    await runtime.coordinator.async_complete_task(task["id"])
    await runtime.coordinator.async_refresh()

    assert not any(
        e["task_id"] == STREAK_BONUS_TASK_ID for e in runtime.completions.entries
    )
    assert runtime.coordinator.data.streak_bonus_enabled is False


# --- Absolute Meilenstein threshold points --------------------------------------


async def test_milestone_threshold_points_match_awarding_computation(
    hass, init_integration
) -> None:
    from custom_components.family_tasks.const import (
        CONF_MILESTONE_1_THRESHOLD_PERCENT,
        CONF_MILESTONE_2_THRESHOLD_PERCENT,
    )

    runtime = init_integration.runtime_data
    hass.config_entries.async_update_entry(
        init_integration,
        options={
            CONF_WEEKLY_PROGRESS_GOAL_POINTS: 15,
            CONF_MILESTONE_1_THRESHOLD_PERCENT: 50,
            CONF_MILESTONE_2_THRESHOLD_PERCENT: 150,
        },
    )
    await runtime.members.async_create_item({"name": "Anna"})
    await runtime.coordinator.async_refresh()

    # Both land on an exact .5 value (7.5 and 22.5) where Python's round()
    # (banker's rounding, nearest *even*) and a naive "always round .5 up"
    # implementation would disagree (7.5 -> 8, but 22.5 -> 22, not 23) - the
    # whole point of computing this server-side once and exposing it, rather
    # than letting the card recompute it independently in JS.
    assert runtime.coordinator.data.milestone_1_threshold_points == round(15 * 50 / 100) == 8
    assert runtime.coordinator.data.milestone_2_threshold_points == round(15 * 150 / 100) == 22


async def test_milestone_threshold_points_zero_without_weekly_goal(
    hass, init_integration
) -> None:
    runtime = init_integration.runtime_data
    await runtime.coordinator.async_refresh()
    assert runtime.coordinator.data.milestone_1_threshold_points == 0
    assert runtime.coordinator.data.milestone_2_threshold_points == 0


# --- Ablehnungsnotiz ------------------------------------------------------------


def _find_confirmation_task(runtime, original_task_id: str) -> dict | None:
    for task in runtime.tasks.data.values():
        confirms = task.get("confirms")
        if confirms and confirms["task_id"] == original_task_id:
            return task
    return None


async def test_rejection_note_stored_on_original_task_and_completion_entry(
    hass, init_integration
) -> None:
    runtime = init_integration.runtime_data
    timmy = await runtime.members.async_create_item({"name": "Timmy", "role": "child"})
    await runtime.members.async_create_item({"name": "Mom", "role": "parent"})
    task = await _add_task(runtime, member_ids=[timmy["id"]])
    await runtime.coordinator.async_refresh()
    await runtime.coordinator.async_complete_task(task["id"])
    await runtime.coordinator.async_refresh()

    confirmation_task = _find_confirmation_task(runtime, task["id"])
    await runtime.coordinator.async_skip_task(
        confirmation_task["id"], "Bett noch nicht gemacht"
    )
    await runtime.coordinator.async_refresh()

    status = runtime.coordinator.data.tasks[task["id"]]
    assert status.status == TASK_STATUS_PENDING
    assert status.last_rejection_note == "Bett noch nicht gemacht"
    assert status.last_rejection_at is not None

    rejection_entries = [
        e
        for e in runtime.completions.entries
        if e["task_id"] == MANUAL_POINTS_TASK_ID and e["note"] == "Bett noch nicht gemacht"
    ]
    assert len(rejection_entries) == 1
    assert rejection_entries[0]["points_awarded"] == -1


async def test_rejection_note_cleared_once_child_retries(hass, init_integration) -> None:
    runtime = init_integration.runtime_data
    timmy = await runtime.members.async_create_item({"name": "Timmy", "role": "child"})
    await runtime.members.async_create_item({"name": "Mom", "role": "parent"})
    task = await _add_task(runtime, member_ids=[timmy["id"]])
    await runtime.coordinator.async_refresh()
    await runtime.coordinator.async_complete_task(task["id"])
    await runtime.coordinator.async_refresh()

    confirmation_task = _find_confirmation_task(runtime, task["id"])
    await runtime.coordinator.async_skip_task(confirmation_task["id"], "Nicht ordentlich")
    await runtime.coordinator.async_refresh()
    assert runtime.coordinator.data.tasks[task["id"]].last_rejection_note == "Nicht ordentlich"

    # The child tries again.
    await runtime.coordinator.async_complete_task(task["id"])
    await runtime.coordinator.async_refresh()

    assert runtime.coordinator.data.tasks[task["id"]].last_rejection_note is None
    assert (
        runtime.coordinator.data.tasks[task["id"]].status
        == TASK_STATUS_AWAITING_CONFIRMATION
    )


# --- Reservierte Poolaufgabe fest zugewiesen ------------------------------------


async def test_claimed_pool_task_is_firmly_assigned_to_claimant(
    hass, init_integration
) -> None:
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna", "role": "child"})
    await runtime.members.async_create_item({"name": "Ben", "role": "child"})
    task = await _add_task(runtime, member_ids=[], points=5)
    await runtime.coordinator.async_refresh()

    status = runtime.coordinator.data.tasks[task["id"]]
    assert status.assigned_member_id is None
    assert status.assigned_member_ids == []

    await runtime.coordinator.async_claim_task(task["id"], anna["id"])
    await runtime.coordinator.async_refresh()

    status = runtime.coordinator.data.tasks[task["id"]]
    assert status.claimed_by_member_id == anna["id"]
    assert status.assigned_member_id == anna["id"]
    assert status.assigned_member_ids == [anna["id"]]
    assert runtime.coordinator.data.members[anna["id"]].open_tasks == 1

    await runtime.coordinator.async_release_task(task["id"], anna["id"])
    await runtime.coordinator.async_refresh()

    status = runtime.coordinator.data.tasks[task["id"]]
    assert status.assigned_member_id is None
    assert status.assigned_member_ids == []
