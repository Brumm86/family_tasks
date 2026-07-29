"""Tests for child tasks requiring parental confirmation.

A member with role "child" can mark their assigned task done, but the
completion doesn't count yet: the coordinator raises an auto-generated task
for the household's parents (recurrence "confirmation", linked back via the
"confirms" field). Completing that task finalizes the child's completion
(points + rotation); skipping it rejects the claim.
"""

from __future__ import annotations

from custom_components.family_tasks.const import (
    TASK_STATUS_AWAITING_CONFIRMATION,
    TASK_STATUS_DONE,
    TASK_STATUS_PENDING,
)


async def _add_task(runtime, *, member_ids, **overrides):
    payload = {
        "name": "Zimmer aufräumen",
        "points": 5,
        "recurrence": {"type": "daily"},
        "rotation": {"member_ids": member_ids, "strategy": "round_robin"},
    }
    payload.update(overrides)
    return await runtime.tasks.async_create_item(payload)


def _find_confirmation_task(runtime, original_task_id: str) -> dict | None:
    for task in runtime.tasks.data.values():
        confirms = task.get("confirms")
        if confirms and confirms["task_id"] == original_task_id:
            return task
    return None


async def test_child_completion_awaits_confirmation_instead_of_finishing(
    hass, init_integration
) -> None:
    """A child's completion does not award points or finish the task right away."""
    runtime = init_integration.runtime_data
    timmy = await runtime.members.async_create_item({"name": "Timmy", "role": "child"})
    mom = await runtime.members.async_create_item({"name": "Mom", "role": "parent"})
    task = await _add_task(runtime, member_ids=[timmy["id"]])
    await runtime.coordinator.async_refresh()

    await runtime.coordinator.async_complete_task(task["id"])
    await runtime.coordinator.async_refresh()

    status = runtime.coordinator.data.tasks[task["id"]]
    assert status.status == TASK_STATUS_AWAITING_CONFIRMATION
    assert runtime.coordinator.data.members[timmy["id"]].points_today == 0

    confirmation_task = _find_confirmation_task(runtime, task["id"])
    assert confirmation_task is not None
    assert confirmation_task["confirms"]["member_id"] == timmy["id"]
    assert confirmation_task["rotation"]["member_ids"] == [mom["id"]]

    confirmation_status = runtime.coordinator.data.tasks[confirmation_task["id"]]
    assert confirmation_status.status == TASK_STATUS_PENDING


async def test_parent_confirming_finalizes_child_completion(
    hass, init_integration
) -> None:
    """Completing the auto-generated confirmation task awards the child's points."""
    runtime = init_integration.runtime_data
    timmy = await runtime.members.async_create_item({"name": "Timmy", "role": "child"})
    await runtime.members.async_create_item({"name": "Mom", "role": "parent"})
    task = await _add_task(runtime, member_ids=[timmy["id"]])
    await runtime.coordinator.async_refresh()
    await runtime.coordinator.async_complete_task(task["id"])
    await runtime.coordinator.async_refresh()

    confirmation_task = _find_confirmation_task(runtime, task["id"])
    await runtime.coordinator.async_complete_task(confirmation_task["id"])
    await runtime.coordinator.async_refresh()

    status = runtime.coordinator.data.tasks[task["id"]]
    assert status.status == TASK_STATUS_DONE
    assert status.last_completed_by == timmy["id"]
    assert runtime.coordinator.data.members[timmy["id"]].points_today == 5
    # The single-use confirmation task is gone once resolved.
    assert confirmation_task["id"] not in runtime.tasks.data


async def test_parent_rejecting_returns_task_to_pending(hass, init_integration) -> None:
    """Skipping the confirmation task rejects the claim without awarding points."""
    runtime = init_integration.runtime_data
    timmy = await runtime.members.async_create_item({"name": "Timmy", "role": "child"})
    await runtime.members.async_create_item({"name": "Mom", "role": "parent"})
    task = await _add_task(runtime, member_ids=[timmy["id"]])
    await runtime.coordinator.async_refresh()
    await runtime.coordinator.async_complete_task(task["id"])
    await runtime.coordinator.async_refresh()

    confirmation_task = _find_confirmation_task(runtime, task["id"])
    await runtime.coordinator.async_skip_task(confirmation_task["id"])
    await runtime.coordinator.async_refresh()

    status = runtime.coordinator.data.tasks[task["id"]]
    assert status.status == TASK_STATUS_PENDING
    assert runtime.coordinator.data.members[timmy["id"]].points_today == 0
    assert confirmation_task["id"] not in runtime.tasks.data

    # The child can raise a fresh claim for the same occurrence.
    await runtime.coordinator.async_complete_task(task["id"])
    await runtime.coordinator.async_refresh()
    assert (
        runtime.coordinator.data.tasks[task["id"]].status
        == TASK_STATUS_AWAITING_CONFIRMATION
    )


async def test_parent_completion_is_not_gated_by_confirmation(
    hass, init_integration
) -> None:
    """A task assigned to a member with the (default) 'parent' role completes normally."""
    runtime = init_integration.runtime_data
    mom = await runtime.members.async_create_item({"name": "Mom"})
    task = await _add_task(runtime, member_ids=[mom["id"]])
    await runtime.coordinator.async_refresh()

    await runtime.coordinator.async_complete_task(task["id"])

    status = runtime.coordinator.data.tasks[task["id"]]
    assert status.status == TASK_STATUS_DONE
    assert runtime.coordinator.data.members[mom["id"]].points_today == 5
