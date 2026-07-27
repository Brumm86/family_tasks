"""Tests for the Family Tasks coordinator: status, rotation, points."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from homeassistant.util import dt as dt_util

from custom_components.family_tasks.const import (
    TASK_STATUS_DONE,
    TASK_STATUS_OVERDUE,
    TASK_STATUS_PENDING,
)


async def _add_task(runtime, *, member_ids, **overrides):
    payload = {
        "name": "Müll rausbringen",
        "points": 5,
        "recurrence": {"type": "daily"},
        "rotation": {"member_ids": member_ids, "strategy": "round_robin"},
    }
    payload.update(overrides)
    return await runtime.tasks.async_create_item(payload)


async def test_daily_task_starts_pending_and_assigned_to_first_member(
    hass, init_integration
) -> None:
    """A freshly created task is pending and assigned to the first rotation member."""
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})
    ben = await runtime.members.async_create_item({"name": "Ben"})
    task = await _add_task(runtime, member_ids=[anna["id"], ben["id"]])

    await runtime.coordinator.async_refresh()

    status = runtime.coordinator.data.tasks[task["id"]]
    assert status.status == TASK_STATUS_PENDING
    assert status.assigned_member_id == anna["id"]


async def test_complete_task_awards_points_and_advances_rotation(
    hass, init_integration
) -> None:
    """Completing a task logs it, awards points, and rotates to the next member."""
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})
    ben = await runtime.members.async_create_item({"name": "Ben"})
    task = await _add_task(runtime, member_ids=[anna["id"], ben["id"]])
    await runtime.coordinator.async_refresh()

    await runtime.coordinator.async_complete_task(task["id"])

    status = runtime.coordinator.data.tasks[task["id"]]
    assert status.status == TASK_STATUS_DONE
    assert status.last_completed_by == anna["id"]

    assert runtime.coordinator.data.members[anna["id"]].points_today == 5
    # Rotation has moved on to Ben for the *next* occurrence.
    assert runtime.tasks.data[task["id"]]["rotation"]["current_index"] == 1


async def test_complete_task_is_idempotent_within_the_same_period(
    hass, init_integration
) -> None:
    """Calling complete_task twice for the same period must only count once."""
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})
    ben = await runtime.members.async_create_item({"name": "Ben"})
    task = await _add_task(runtime, member_ids=[anna["id"], ben["id"]])
    await runtime.coordinator.async_refresh()

    await runtime.coordinator.async_complete_task(task["id"])
    await runtime.coordinator.async_complete_task(task["id"])

    assert runtime.tasks.data[task["id"]]["rotation"]["current_index"] == 1
    assert runtime.coordinator.data.members[anna["id"]].points_today == 5


async def test_skip_task_does_not_advance_rotation_or_award_points(
    hass, init_integration
) -> None:
    """Skipping resolves the period but leaves rotation and points untouched."""
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})
    ben = await runtime.members.async_create_item({"name": "Ben"})
    task = await _add_task(runtime, member_ids=[anna["id"], ben["id"]])
    await runtime.coordinator.async_refresh()

    await runtime.coordinator.async_skip_task(task["id"])

    status = runtime.coordinator.data.tasks[task["id"]]
    assert status.status == TASK_STATUS_DONE  # period resolved...
    assert runtime.tasks.data[task["id"]]["rotation"]["current_index"] == 0  # ...but no rotation
    assert runtime.coordinator.data.members[anna["id"]].points_today == 0  # ...and no points


async def test_fixed_strategy_never_rotates(hass, init_integration) -> None:
    """The 'fixed' strategy always keeps the same assignee after completion."""
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})
    ben = await runtime.members.async_create_item({"name": "Ben"})
    task = await _add_task(
        runtime,
        member_ids=[anna["id"], ben["id"]],
        rotation={"member_ids": [anna["id"], ben["id"]], "strategy": "fixed"},
    )
    await runtime.coordinator.async_refresh()

    await runtime.coordinator.async_complete_task(task["id"])

    assert runtime.tasks.data[task["id"]]["rotation"]["current_index"] == 0


async def test_task_becomes_overdue_after_grace_period(hass, init_integration) -> None:
    """A task is 'overdue' once now is past due_time + overdue_after_minutes."""
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})

    # Anchor everything to "now" (whatever timezone the test hass defaults to)
    # so the test doesn't depend on assumptions about that timezone.
    frozen_local = dt_util.now().replace(hour=12, minute=0, second=0, microsecond=0)
    due_time_str = (frozen_local - timedelta(hours=2)).strftime("%H:%M")

    task = await _add_task(
        runtime,
        member_ids=[anna["id"]],
        due_time=due_time_str,
        overdue_after_minutes=30,
    )

    frozen_utc = dt_util.as_utc(frozen_local)
    with (
        patch.object(dt_util, "now", return_value=frozen_local),
        patch.object(dt_util, "utcnow", return_value=frozen_utc),
    ):
        await runtime.coordinator.async_refresh()

    assert runtime.coordinator.data.tasks[task["id"]].status == TASK_STATUS_OVERDUE
