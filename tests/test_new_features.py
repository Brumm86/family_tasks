"""Tests for: 'once' recurrence, 'least_points' rotation, and the
requires_confirmation override for child tasks.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from homeassistant.util import dt as dt_util

from custom_components.family_tasks.const import (
    TASK_STATUS_AWAITING_CONFIRMATION,
    TASK_STATUS_DONE,
    TASK_STATUS_PENDING,
)


async def _add_task(runtime, *, member_ids, **overrides):
    payload = {
        "name": "Testaufgabe",
        "points": 5,
        "recurrence": {"type": "daily"},
        "rotation": {"member_ids": member_ids, "strategy": "round_robin"},
    }
    payload.update(overrides)
    return await runtime.tasks.async_create_item(payload)


# --- recurrence "once" ------------------------------------------------------


async def test_once_task_gets_anchor_date_defaulted(hass, init_integration) -> None:
    """A 'once' task without an explicit anchor_date gets one (today)."""
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})

    task = await _add_task(
        runtime, member_ids=[anna["id"]], recurrence={"type": "once"}
    )

    assert task["recurrence"]["anchor_date"]


async def test_once_task_stays_done_across_days(hass, init_integration) -> None:
    """Completing a 'once' task keeps it done forever - its period never changes."""
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})
    today = dt_util.now().date()
    task = await _add_task(
        runtime,
        member_ids=[anna["id"]],
        recurrence={"type": "once", "anchor_date": today.isoformat()},
    )
    await runtime.coordinator.async_refresh()

    await runtime.coordinator.async_complete_task(task["id"])

    status = runtime.coordinator.data.tasks[task["id"]]
    assert status.status == TASK_STATUS_DONE

    # Fast-forward "today" by a week and refresh: a daily/weekly task would
    # open a new occurrence, but a 'once' task's period is pinned to its
    # anchor date, so it must still read as done.
    future = dt_util.now() + timedelta(days=7)
    with patch.object(dt_util, "now", return_value=future):
        await runtime.coordinator.async_refresh()

    assert runtime.coordinator.data.tasks[task["id"]].status == TASK_STATUS_DONE


# --- rotation strategy "least_points" ---------------------------------------


async def test_least_points_strategy_assigns_the_lowest_scorer(
    hass, init_integration
) -> None:
    """The 'least_points' strategy assigns whoever currently has fewest points."""
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})
    ben = await runtime.members.async_create_item({"name": "Ben"})

    # Give Anna a head start in points via an unrelated already-completed task.
    scoring_task = await _add_task(runtime, member_ids=[anna["id"]], points=10)
    await runtime.coordinator.async_refresh()
    await runtime.coordinator.async_complete_task(scoring_task["id"])
    await runtime.coordinator.async_refresh()

    task = await _add_task(
        runtime,
        member_ids=[anna["id"], ben["id"]],
        rotation={
            "member_ids": [anna["id"], ben["id"]],
            "strategy": "least_points",
        },
    )
    await runtime.coordinator.async_refresh()

    status = runtime.coordinator.data.tasks[task["id"]]
    assert status.assigned_member_id == ben["id"]


async def test_least_points_only_children_ignores_parents_in_the_pool(
    hass, init_integration
) -> None:
    """With only_children set, a parent in the pool is never picked, even
    with fewer points than every child candidate."""
    runtime = init_integration.runtime_data
    mom = await runtime.members.async_create_item({"name": "Mom", "role": "parent"})
    timmy = await runtime.members.async_create_item({"name": "Timmy", "role": "child"})
    sue = await runtime.members.async_create_item({"name": "Sue", "role": "child"})

    # Sue has fewer points than Timmy; Mom (parent) has none at all.
    scoring_task = await _add_task(runtime, member_ids=[timmy["id"]], points=10)
    await runtime.coordinator.async_refresh()
    await runtime.coordinator.async_complete_task(scoring_task["id"])
    await runtime.coordinator.async_refresh()

    task = await _add_task(
        runtime,
        member_ids=[mom["id"], timmy["id"], sue["id"]],
        rotation={
            "member_ids": [mom["id"], timmy["id"], sue["id"]],
            "strategy": "least_points",
            "only_children": True,
        },
    )
    await runtime.coordinator.async_refresh()

    status = runtime.coordinator.data.tasks[task["id"]]
    assert status.assigned_member_id == sue["id"]


async def test_least_points_strategy_does_not_advance_a_stored_index(
    hass, init_integration
) -> None:
    """Completing a least_points task must not touch rotation.current_index -
    the assignee is recomputed fresh every refresh instead."""
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})
    ben = await runtime.members.async_create_item({"name": "Ben"})
    task = await _add_task(
        runtime,
        member_ids=[anna["id"], ben["id"]],
        rotation={
            "member_ids": [anna["id"], ben["id"]],
            "strategy": "least_points",
        },
    )
    await runtime.coordinator.async_refresh()

    await runtime.coordinator.async_complete_task(task["id"])

    assert runtime.tasks.data[task["id"]]["rotation"]["current_index"] == 0


# --- requires_confirmation override -----------------------------------------


async def test_requires_confirmation_false_skips_the_parent_gate(
    hass, init_integration
) -> None:
    """A child's task with requires_confirmation=False completes immediately."""
    runtime = init_integration.runtime_data
    timmy = await runtime.members.async_create_item({"name": "Timmy", "role": "child"})
    task = await _add_task(
        runtime, member_ids=[timmy["id"]], requires_confirmation=False
    )
    await runtime.coordinator.async_refresh()

    await runtime.coordinator.async_complete_task(task["id"])

    status = runtime.coordinator.data.tasks[task["id"]]
    assert status.status == TASK_STATUS_DONE
    assert runtime.coordinator.data.members[timmy["id"]].points_today == 5


async def test_requires_confirmation_unset_still_defaults_to_true(
    hass, init_integration
) -> None:
    """Legacy behavior: a child task without an explicit flag still needs
    parental sign-off."""
    runtime = init_integration.runtime_data
    timmy = await runtime.members.async_create_item({"name": "Timmy", "role": "child"})
    task = await _add_task(runtime, member_ids=[timmy["id"]])
    await runtime.coordinator.async_refresh()

    await runtime.coordinator.async_complete_task(task["id"])
    await runtime.coordinator.async_refresh()

    status = runtime.coordinator.data.tasks[task["id"]]
    assert status.status == TASK_STATUS_AWAITING_CONFIRMATION


async def test_points_month_is_tracked_per_member(hass, init_integration) -> None:
    """The member summary exposes an all-time-this-month points total."""
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})
    task = await _add_task(runtime, member_ids=[anna["id"]], points=7)
    await runtime.coordinator.async_refresh()

    await runtime.coordinator.async_complete_task(task["id"])

    assert runtime.coordinator.data.members[anna["id"]].points_month == 7
