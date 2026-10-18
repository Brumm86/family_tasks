"""Tests for the v0.25 features:

- A parent completing a task currently assigned to a child is credited (and
  awarded points) as themselves, not as the child, and skips the parent-
  confirmation flow entirely - see FamilyTasksCoordinator.async_complete_task,
  which only ever gates on the *acting* member's role. The card change that
  re-shows the "Erledigt" button for this case (canAct in
  family-tasks-card.js) isn't covered here since this suite only exercises
  the coordinator/storage layer - see test_child_confirmation.py for the
  existing child-completion-needs-confirmation coverage this doesn't change.
- TaskStatusData.eligible_member_ids (and its "eligible_member_ids" sensor
  attribute, see sensor.py): identical to assigned_member_ids. v0.25-v0.49
  additionally let every other active child step in once a child's task went
  TASK_STATUS_OVERDUE; v0.50 removed that again, so an overdue task stays with
  its assignees (the Aufgabenpool case is covered in the v0.30 tests).
"""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.util import dt as dt_util

from custom_components.family_tasks.const import (
    TASK_STATUS_DONE,
    TASK_STATUS_OVERDUE,
    TASK_STATUS_PENDING,
)


async def _add_task(runtime, *, member_ids, **overrides):
    payload = {
        "name": "Geschirrspüler ausräumen",
        "points": 5,
        "recurrence": {"type": "daily"},
        "rotation": {"member_ids": member_ids, "strategy": "round_robin"},
    }
    payload.update(overrides)
    # Without an explicit due_time a daily task is only due at the end of the
    # day (five-status model, v0.42), so a test that wants an overdue task
    # needs one before the frozen "noon" used by _refresh_overdue below.
    if "overdue_after_minutes" in payload:
        payload.setdefault("due_time", "10:00")
    return await runtime.tasks.async_create_item(payload)


async def _refresh_overdue(runtime, hass):
    """Refresh the coordinator with "now" frozen well past any due_time.

    Mirrors test_coordinator.py's test_task_becomes_overdue_after_grace_period
    - tasks created via _add_task above default to recurrence "daily" with no
    explicit due_time (midnight local), so _add_task defaults a 10:00 due_time
    whenever overdue_after_minutes is given, and freezing "now" at noon then
    pushes today's occurrence into TASK_STATUS_OVERDUE.
    """
    frozen_local = dt_util.now().replace(hour=12, minute=0, second=0, microsecond=0)
    frozen_utc = dt_util.as_utc(frozen_local)
    with (
        patch.object(dt_util, "now", return_value=frozen_local),
        patch.object(dt_util, "utcnow", return_value=frozen_utc),
    ):
        await runtime.coordinator.async_refresh()


async def test_parent_completing_childs_task_awards_parent_not_child(
    hass, init_integration
) -> None:
    """A parent explicitly completing a child's task is credited (and paid) as themselves."""
    runtime = init_integration.runtime_data
    timmy = await runtime.members.async_create_item({"name": "Timmy", "role": "child"})
    mom = await runtime.members.async_create_item({"name": "Mom", "role": "parent"})
    task = await _add_task(runtime, member_ids=[timmy["id"]])
    await runtime.coordinator.async_refresh()

    # Same shape as the real complete_task service call once
    # async_member_id_for_context has resolved the logged-in parent's own
    # member id (see _async_resolve_member_id in __init__.py) - the card
    # itself never sends member_id, the backend resolves it from context.
    await runtime.coordinator.async_complete_task(task["id"], mom["id"])

    status = runtime.coordinator.data.tasks[task["id"]]
    assert status.status == TASK_STATUS_DONE
    assert status.last_completed_by == mom["id"]
    assert runtime.coordinator.data.members[mom["id"]].points_today == 5
    assert runtime.coordinator.data.members[timmy["id"]].points_today == 0


async def test_parent_completing_childs_task_skips_confirmation(
    hass, init_integration
) -> None:
    """Unlike the child completing it themselves, a parent's own completion never
    raises an awaiting-confirmation occurrence - there's no one left to confirm it."""
    runtime = init_integration.runtime_data
    timmy = await runtime.members.async_create_item({"name": "Timmy", "role": "child"})
    mom = await runtime.members.async_create_item({"name": "Mom", "role": "parent"})
    task = await _add_task(runtime, member_ids=[timmy["id"]])
    await runtime.coordinator.async_refresh()

    await runtime.coordinator.async_complete_task(task["id"], mom["id"])
    await runtime.coordinator.async_refresh()

    assert runtime.coordinator.data.tasks[task["id"]].status == TASK_STATUS_DONE
    # No auto-generated confirmation task was raised for this.
    assert not any(t.get("confirms") for t in runtime.tasks.data.values())


async def test_eligible_member_ids_matches_assigned_before_overdue(
    hass, init_integration
) -> None:
    """Before an occurrence is overdue, eligible_member_ids is just assigned_member_ids."""
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna", "role": "child"})
    await runtime.members.async_create_item({"name": "Ben", "role": "child"})
    task = await _add_task(runtime, member_ids=[anna["id"]])
    await runtime.coordinator.async_refresh()

    status = runtime.coordinator.data.tasks[task["id"]]
    assert status.status == TASK_STATUS_PENDING
    assert status.eligible_member_ids == [anna["id"]]


async def test_eligible_member_ids_stay_assigned_when_overdue(
    hass, init_integration
) -> None:
    """Since v0.50 an overdue child's task no longer widens to the other children."""
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna", "role": "child"})
    await runtime.members.async_create_item({"name": "Ben", "role": "child"})
    task = await _add_task(runtime, member_ids=[anna["id"]], overdue_after_minutes=1)
    await runtime.coordinator.async_refresh()

    await _refresh_overdue(runtime, hass)

    status = runtime.coordinator.data.tasks[task["id"]]
    assert status.status == TASK_STATUS_OVERDUE
    assert status.assigned_member_ids == [anna["id"]]
    assert status.eligible_member_ids == [anna["id"]]
