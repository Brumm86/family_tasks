"""Tests for the v0.30 Aufgabenpool (the points-shop balance and
point-based Meilensteinbonus tests of this file were removed with those
features in v0.36/v0.44):

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
    TASK_STATUS_DONE,
    TASK_STATUS_OVERDUE,
    TASK_STATUS_PENDING,
    TASK_STATUS_UPCOMING,
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


# --- Aufgabenpool -------------------------------------------------------------


async def test_pool_task_previews_this_weeks_occurrence_before_its_weekday(
    hass, init_integration
) -> None:
    """A weekly Aufgabenpool task due Friday must already show *this*
    Friday's occurrence on Monday, not last Friday's - see _pool_period_date.

    v0.40: a normally-assigned (non-pool) weekly task now previews this same
    week's occurrence too (see _current_period_date) - "Es sollen immer alle
    bereits vorhersehbaren Aufgaben der jeweils laufenden Woche angezeigt
    werden" - but as TASK_STATUS_UPCOMING rather than TASK_STATUS_PENDING:
    visible and claimable-free (nobody needs to "Annehmen" their own fixed
    assignment), but not completable until Friday actually arrives - see
    test_upcoming_weekly_task_not_completable_until_its_weekday below for
    that half. Before v0.40 this assigned task stayed pinned to *last*
    week's (already-resolved) Friday the whole time instead - see the
    v0.39.0 git tag if that old behavior is ever needed for reference.
    """
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna", "role": "child"})
    ben = await runtime.members.async_create_item({"name": "Ben", "role": "child"})
    monday = _start_of_week_utc(0)
    monday_morning = monday + timedelta(hours=9)
    # Create the tasks "on" that Monday too: a task's created_at (v0.39)
    # excludes earlier occurrences, so creating them at the real current time
    # (which may be later in the week) would hide this week's Friday.
    with (
        patch.object(dt_util, "now", return_value=dt_util.as_local(monday_morning)),
        patch.object(dt_util, "utcnow", return_value=monday_morning),
    ):
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

    await _refresh_at_utc(runtime, monday_morning)

    pool_status = runtime.coordinator.data.tasks[pool_task["id"]]
    expected_friday = (monday + timedelta(days=4)).date().isoformat()
    assert pool_status.period_key == expected_friday
    assert pool_status.status == TASK_STATUS_PENDING
    assert set(pool_status.eligible_member_ids) == {anna["id"], ben["id"]}
    assert pool_status.claimable is True

    # v0.40: the assigned task now resolves to *this* week's Friday too,
    # just as TASK_STATUS_UPCOMING instead of TASK_STATUS_PENDING/claimable.
    assigned_status = runtime.coordinator.data.tasks[assigned_task["id"]]
    assert assigned_status.period_key == expected_friday
    assert assigned_status.status == TASK_STATUS_UPCOMING
    assert assigned_status.claimable is False


async def test_pool_task_not_eligible_once_done(hass, init_integration) -> None:
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna", "role": "child"})
    await runtime.members.async_create_item({"name": "Ben", "role": "child"})
    task = await _add_task(runtime, member_ids=[], points=5)

    await runtime.coordinator.async_refresh()
    await runtime.coordinator.async_complete_task(task["id"], anna["id"], skip_confirmation=True)
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

    await runtime.coordinator.async_complete_task(task["id"], anna["id"], skip_confirmation=True)
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
