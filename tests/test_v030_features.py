"""Tests for the v0.30 features:

- Negative points_available bugfix: storage._available_points (the
  server-side balance check in ws_redeem_reward) used to ignore the v0.29
  weekly-goal rule entirely, so a redemption could be accepted for more than
  a member's true spendable balance - see storage.weekly_spendable_points,
  now shared by both call sites. FamilyTasksCoordinator._async_correct_negative_balances
  additionally tops up, once, any member left with a negative balance from
  that drift before upgrading.
- "Meilensteinbonus" (CONF_MILESTONE_BONUS_ENABLED and the
  CONF_MILESTONE_1_*/CONF_MILESTONE_2_* constants): replaces the old
  weekly-winner bonus. Every participating, active member who crosses one of
  two configurable thresholds (percentages of CONF_WEEKLY_PROGRESS_GOAL_POINTS)
  during the current week is credited that threshold's bonus immediately, the
  first refresh after crossing it - see
  FamilyTasksCoordinator._async_process_milestone_bonus in coordinator.py.
- "Aufgabenpool": a task with no fixed assignee(s) and no rotation at all
  (empty rotation.member_ids) is unassigned by design - every active child is
  eligible for it the whole time it's pending or overdue (not just once
  overdue, unlike a normally-assigned task), and a "weekly" recurrence pool
  task previews the current calendar week's occurrence even before its
  weekday arrives, instead of only the most recent past one - see
  is_pool_task/_pool_period_date in coordinator.py.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from homeassistant.util import dt as dt_util

from custom_components.family_tasks.const import (
    CONF_MILESTONE_1_BONUS_POINTS,
    CONF_MILESTONE_1_THRESHOLD_PERCENT,
    CONF_MILESTONE_2_BONUS_POINTS,
    CONF_MILESTONE_2_THRESHOLD_PERCENT,
    CONF_MILESTONE_BONUS_ENABLED,
    CONF_WEEKLY_PROGRESS_GOAL_POINTS,
    MILESTONE_BONUS_1_TASK_ID,
    MILESTONE_BONUS_2_TASK_ID,
    POINTS_CORRECTION_TASK_ID,
    TASK_STATUS_DONE,
    TASK_STATUS_OVERDUE,
    TASK_STATUS_PENDING,
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
    """Mirror FamilyTasksCoordinator._async_update_data's start_of_week math.

    Deriving the reference Monday from the exact same
    now -> start_of_local_day -> as_utc -> subtract-weekday formula the
    coordinator itself uses (rather than approximating it independently)
    means these tests stay correct regardless of the test environment's
    configured timezone.
    """
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


async def _complete_at_utc(runtime, task_id, utc_dt) -> None:
    local_dt = dt_util.as_local(utc_dt)
    with (
        patch.object(dt_util, "now", return_value=local_dt),
        patch.object(dt_util, "utcnow", return_value=utc_dt),
    ):
        await runtime.coordinator.async_complete_task(task_id)


# --- Negative points_available bugfix ---------------------------------------


async def test_redemption_rejected_beyond_weekly_goal_spendable_balance(
    hass, init_integration, hass_ws_client
) -> None:
    """A redemption may not exceed the *spendable* balance, only the raw total.

    Before v0.30, storage._available_points ignored CONF_WEEKLY_PROGRESS_GOAL_POINTS
    entirely and would have accepted this (15 total points >= 8 point cost).
    """
    from tests.test_v014_features import _client_for_new_user

    runtime = init_integration.runtime_data
    hass.config_entries.async_update_entry(
        init_integration, options={CONF_WEEKLY_PROGRESS_GOAL_POINTS: 10}
    )
    anna = await runtime.members.async_create_item(
        {"name": "Anna", "role": "child", "person_entity_id": "person.anna"}
    )
    reward = await runtime.rewards.async_create_item({"name": "Kino", "points_cost": 8})
    task = await _add_task(runtime, member_ids=[anna["id"]], points=15)
    await runtime.coordinator.async_refresh()
    await runtime.coordinator.async_complete_task(task["id"])
    await runtime.coordinator.async_refresh()

    # 15 earned this week, goal 10 -> only 5 are spendable.
    assert runtime.coordinator.data.members[anna["id"]].points_available == 5

    user, client = await _client_for_new_user(hass, hass_ws_client, is_admin=False)
    hass.states.async_set("person.anna", "home", {"user_id": user.id})

    await client.send_json_auto_id(
        {"type": "family_tasks/reward_redemption/redeem", "reward_id": reward["id"]}
    )
    response = await client.receive_json()

    assert response["success"] is False
    assert not runtime.reward_redemptions.data


async def test_redemption_within_weekly_goal_spendable_balance_succeeds(
    hass, init_integration, hass_ws_client
) -> None:
    from tests.test_v014_features import _client_for_new_user

    runtime = init_integration.runtime_data
    hass.config_entries.async_update_entry(
        init_integration, options={CONF_WEEKLY_PROGRESS_GOAL_POINTS: 10}
    )
    anna = await runtime.members.async_create_item(
        {"name": "Anna", "role": "child", "person_entity_id": "person.anna"}
    )
    reward = await runtime.rewards.async_create_item({"name": "Kino", "points_cost": 5})
    task = await _add_task(runtime, member_ids=[anna["id"]], points=15)
    await runtime.coordinator.async_refresh()
    await runtime.coordinator.async_complete_task(task["id"])
    await runtime.coordinator.async_refresh()

    user, client = await _client_for_new_user(hass, hass_ws_client, is_admin=False)
    hass.states.async_set("person.anna", "home", {"user_id": user.id})

    await client.send_json_auto_id(
        {"type": "family_tasks/reward_redemption/redeem", "reward_id": reward["id"]}
    )
    response = await client.receive_json()

    assert response["success"] is True
    await runtime.coordinator.async_refresh()
    assert runtime.coordinator.data.members[anna["id"]].points_available == 0


async def test_negative_balance_corrected_once(hass, init_integration) -> None:
    """A pre-existing negative balance (simulating the pre-v0.30 bug) is
    topped up to exactly 0, exactly once."""
    runtime = init_integration.runtime_data
    hass.config_entries.async_update_entry(
        init_integration, options={CONF_WEEKLY_PROGRESS_GOAL_POINTS: 10}
    )
    anna = await runtime.members.async_create_item({"name": "Anna"})
    task = await _add_task(runtime, member_ids=[anna["id"]], points=10)
    await runtime.coordinator.async_refresh()
    await runtime.coordinator.async_complete_task(task["id"])

    # Simulate a redemption that the pre-v0.30 bug let through even though
    # nothing was actually spendable yet (10 earned == goal, 0 spendable).
    await runtime.reward_redemptions.async_create_item(
        {
            "member_id": anna["id"],
            "member_name": "Anna",
            "reward_id": "fake-reward",
            "reward_name": "Kino",
            "points_cost": 6,
        }
    )

    await runtime.coordinator.async_refresh()

    assert runtime.coordinator.data.members[anna["id"]].points_available == 0
    correction_entries = [
        e for e in runtime.completions.entries if e["task_id"] == POINTS_CORRECTION_TASK_ID
    ]
    assert len(correction_entries) == 1
    assert correction_entries[0]["points_awarded"] == 6
    assert correction_entries[0]["completed_by_member_id"] == anna["id"]

    # A second refresh must not correct again.
    await runtime.coordinator.async_refresh()
    correction_entries = [
        e for e in runtime.completions.entries if e["task_id"] == POINTS_CORRECTION_TASK_ID
    ]
    assert len(correction_entries) == 1


# --- Meilensteinbonus --------------------------------------------------------


async def test_milestone_bonus_awarded_live_when_threshold_crossed(
    hass, init_integration
) -> None:
    """Unlike the old weekly-winner bonus, this must not wait for the week to end."""
    runtime = init_integration.runtime_data
    hass.config_entries.async_update_entry(
        init_integration,
        options={
            CONF_WEEKLY_PROGRESS_GOAL_POINTS: 10,
            CONF_MILESTONE_BONUS_ENABLED: True,
            CONF_MILESTONE_1_THRESHOLD_PERCENT: 100,
            CONF_MILESTONE_1_BONUS_POINTS: 5,
        },
    )
    anna = await runtime.members.async_create_item({"name": "Anna"})
    task = await _add_task(runtime, member_ids=[anna["id"]], points=10)

    monday = _start_of_week_utc(0)
    await _complete_at_utc(runtime, task["id"], monday + timedelta(days=1))
    # Refresh the same week, well before it ends - the bonus must already be
    # credited here, not only after the week rolls over.
    await _refresh_at_utc(runtime, monday + timedelta(days=1, hours=1))

    assert runtime.coordinator.data.members[anna["id"]].points_total == 10 + 5
    period_key = monday.date().isoformat()
    assert await runtime.milestone_bonus_state.async_has_awarded(period_key, 1, anna["id"])
    milestone_entries = [
        e for e in runtime.completions.entries if e["task_id"] == MILESTONE_BONUS_1_TASK_ID
    ]
    assert len(milestone_entries) == 1


async def test_milestone_bonus_both_thresholds_same_refresh(hass, init_integration) -> None:
    runtime = init_integration.runtime_data
    hass.config_entries.async_update_entry(
        init_integration,
        options={
            CONF_WEEKLY_PROGRESS_GOAL_POINTS: 10,
            CONF_MILESTONE_BONUS_ENABLED: True,
            CONF_MILESTONE_1_THRESHOLD_PERCENT: 100,
            CONF_MILESTONE_1_BONUS_POINTS: 5,
            CONF_MILESTONE_2_THRESHOLD_PERCENT: 200,
            CONF_MILESTONE_2_BONUS_POINTS: 8,
        },
    )
    anna = await runtime.members.async_create_item({"name": "Anna"})
    task = await _add_task(runtime, member_ids=[anna["id"]], points=20)

    monday = _start_of_week_utc(0)
    await _complete_at_utc(runtime, task["id"], monday + timedelta(days=1))
    await _refresh_at_utc(runtime, monday + timedelta(days=1, hours=1))

    assert runtime.coordinator.data.members[anna["id"]].points_total == 20 + 5 + 8
    assert any(
        e["task_id"] == MILESTONE_BONUS_1_TASK_ID for e in runtime.completions.entries
    )
    assert any(
        e["task_id"] == MILESTONE_BONUS_2_TASK_ID for e in runtime.completions.entries
    )


async def test_milestone_bonus_not_double_awarded_on_repeat_refresh(
    hass, init_integration
) -> None:
    runtime = init_integration.runtime_data
    hass.config_entries.async_update_entry(
        init_integration,
        options={
            CONF_WEEKLY_PROGRESS_GOAL_POINTS: 10,
            CONF_MILESTONE_BONUS_ENABLED: True,
            CONF_MILESTONE_1_THRESHOLD_PERCENT: 100,
            CONF_MILESTONE_1_BONUS_POINTS: 5,
        },
    )
    anna = await runtime.members.async_create_item({"name": "Anna"})
    task = await _add_task(runtime, member_ids=[anna["id"]], points=10)

    monday = _start_of_week_utc(0)
    await _complete_at_utc(runtime, task["id"], monday + timedelta(days=1))
    await _refresh_at_utc(runtime, monday + timedelta(days=1, hours=1))
    await _refresh_at_utc(runtime, monday + timedelta(days=1, hours=2))
    await _refresh_at_utc(runtime, monday + timedelta(days=2))

    assert runtime.coordinator.data.members[anna["id"]].points_total == 10 + 5
    milestone_entries = [
        e for e in runtime.completions.entries if e["task_id"] == MILESTONE_BONUS_1_TASK_ID
    ]
    assert len(milestone_entries) == 1


async def test_milestone_bonus_disabled_by_default(hass, init_integration) -> None:
    runtime = init_integration.runtime_data
    hass.config_entries.async_update_entry(
        init_integration, options={CONF_WEEKLY_PROGRESS_GOAL_POINTS: 10}
    )
    anna = await runtime.members.async_create_item({"name": "Anna"})
    task = await _add_task(runtime, member_ids=[anna["id"]], points=10)

    monday = _start_of_week_utc(0)
    await _complete_at_utc(runtime, task["id"], monday + timedelta(days=1))
    await _refresh_at_utc(runtime, monday + timedelta(days=1, hours=1))

    assert runtime.coordinator.data.members[anna["id"]].points_total == 10
    assert not any(
        e["task_id"] in (MILESTONE_BONUS_1_TASK_ID, MILESTONE_BONUS_2_TASK_ID)
        for e in runtime.completions.entries
    )


async def test_milestone_bonus_requires_a_weekly_goal(hass, init_integration) -> None:
    """Both thresholds are percentages *of* the weekly goal - without one
    (CONF_WEEKLY_PROGRESS_GOAL_POINTS at its default of 0), there is nothing
    for them to be a percentage of, so the bonus stays off even if enabled."""
    runtime = init_integration.runtime_data
    hass.config_entries.async_update_entry(
        init_integration,
        options={
            CONF_MILESTONE_BONUS_ENABLED: True,
            CONF_MILESTONE_1_THRESHOLD_PERCENT: 100,
            CONF_MILESTONE_1_BONUS_POINTS: 5,
        },
    )
    anna = await runtime.members.async_create_item({"name": "Anna"})
    task = await _add_task(runtime, member_ids=[anna["id"]], points=10)

    monday = _start_of_week_utc(0)
    await _complete_at_utc(runtime, task["id"], monday + timedelta(days=1))
    await _refresh_at_utc(runtime, monday + timedelta(days=1, hours=1))

    assert runtime.coordinator.data.members[anna["id"]].points_total == 10


# --- Aufgabenpool -------------------------------------------------------------


async def test_pool_task_previews_this_weeks_occurrence_before_its_weekday(
    hass, init_integration
) -> None:
    """A weekly Aufgabenpool task due Friday must already show *this*
    Friday's occurrence on Monday, not last Friday's - see _pool_period_date.
    A normally-assigned (non-pool) weekly task keeps the old backward-only
    behavior for comparison."""
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna", "role": "child"})
    ben = await runtime.members.async_create_item({"name": "Ben", "role": "child"})
    pool_task = await _add_task(
        runtime, member_ids=[], points=5, recurrence={"type": "weekly", "weekdays": [4]}
    )
    assigned_task = await _add_task(
        runtime,
        member_ids=[anna["id"]],
        points=5,
        recurrence={"type": "weekly", "weekdays": [4]},
        name="Zugewiesene Aufgabe",
    )

    monday = _start_of_week_utc(0)
    await _refresh_at_utc(runtime, monday + timedelta(hours=9))

    pool_status = runtime.coordinator.data.tasks[pool_task["id"]]
    expected_friday = (monday + timedelta(days=4)).date().isoformat()
    assert pool_status.period_key == expected_friday
    assert pool_status.status == TASK_STATUS_PENDING
    assert set(pool_status.eligible_member_ids) == {anna["id"], ben["id"]}
    assert pool_status.claimable is True

    # The assigned task still resolves to last week's Friday (the old,
    # backward-only behavior) - unaffected by the pool-only change.
    assigned_status = runtime.coordinator.data.tasks[assigned_task["id"]]
    last_friday = (monday - timedelta(days=3)).date().isoformat()
    assert assigned_status.period_key == last_friday


async def test_pool_task_not_eligible_once_done(hass, init_integration) -> None:
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna", "role": "child"})
    await runtime.members.async_create_item({"name": "Ben", "role": "child"})
    task = await _add_task(runtime, member_ids=[], points=5)

    await runtime.coordinator.async_refresh()
    await runtime.coordinator.async_complete_task(task["id"], anna["id"])
    await runtime.coordinator.async_refresh()

    status = runtime.coordinator.data.tasks[task["id"]]
    assert status.status == TASK_STATUS_DONE
    assert runtime.coordinator.data.members[anna["id"]].points_total == 5


async def test_pool_task_claim_then_complete_flow(hass, init_integration) -> None:
    """A child reserves an Aufgabenpool task, then completes it themself."""
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna", "role": "child"})
    await runtime.members.async_create_item({"name": "Ben", "role": "child"})
    task = await _add_task(runtime, member_ids=[], points=7)
    await runtime.coordinator.async_refresh()

    await runtime.coordinator.async_claim_task(task["id"], anna["id"])
    await runtime.coordinator.async_refresh()

    status = runtime.coordinator.data.tasks[task["id"]]
    assert status.claimed_by_member_id == anna["id"]
    assert status.eligible_member_ids == [anna["id"]]

    await runtime.coordinator.async_complete_task(task["id"], anna["id"])
    await runtime.coordinator.async_refresh()

    assert runtime.coordinator.data.tasks[task["id"]].status == TASK_STATUS_DONE
    assert runtime.coordinator.data.members[anna["id"]].points_total == 7


async def test_pool_task_overdue_still_eligible_to_all_active_children(
    hass, init_integration
) -> None:
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna", "role": "child"})
    ben = await runtime.members.async_create_item({"name": "Ben", "role": "child"})
    frozen_local = dt_util.now().replace(hour=12, minute=0, second=0, microsecond=0)
    due_time_str = (frozen_local - timedelta(hours=2)).strftime("%H:%M")
    task = await _add_task(
        runtime, member_ids=[], points=5, due_time=due_time_str, overdue_after_minutes=30
    )

    with (
        patch.object(dt_util, "now", return_value=frozen_local),
        patch.object(dt_util, "utcnow", return_value=dt_util.as_utc(frozen_local)),
    ):
        await runtime.coordinator.async_refresh()

    status = runtime.coordinator.data.tasks[task["id"]]
    assert status.status == TASK_STATUS_OVERDUE
    assert set(status.eligible_member_ids) == {anna["id"], ben["id"]}
