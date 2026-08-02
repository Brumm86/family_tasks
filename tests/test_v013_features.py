"""Tests for the v0.13 fix:

Completing a task through the `family_tasks.complete_task` / `toggle_subtask`
*services* (as opposed to calling the coordinator directly, which every other
test file in this suite does) never told the coordinator who actually
completed it - the Lovelace card's "Erledigt"/checklist controls only ever
send `task_id` (see family-tasks-card.js), never `member_id`.
`FamilyTasksCoordinator.async_complete_task` then fell back to
`_assigned_member_id`, which for a "fixed" rotation shared by more than one
member (see `_assigned_member_ids`) always resolves to `member_ids[0]` -
regardless of which of the assignees actually pressed the button. For a task
fixed-assigned to two children this meant the parent confirmation request
raised by `_async_request_confirmation` could name the wrong child.

The fix resolves the acting member from the service call's `Context.user_id`
(stamped automatically by Home Assistant for any call made by a logged-in
user, e.g. from the Lovelace card) via the same person_entity_id link already
used for reward redemption/create_own_task - see
`storage.async_member_id_for_context` / `__init__._async_resolve_member_id`.
An explicit `member_id` in the service call data still wins, and a caller
with no resolvable link still falls back to the previous behaviour.
"""

from __future__ import annotations

from homeassistant.core import Context

from custom_components.family_tasks.const import (
    ATTR_MEMBER_ID,
    ATTR_SUBTASK_ID,
    ATTR_TASK_ID,
    DOMAIN,
    SERVICE_COMPLETE_TASK,
    SERVICE_TOGGLE_SUBTASK,
)


async def _add_task(runtime, *, member_ids, strategy="fixed", **overrides):
    payload = {
        "name": "Küche aufräumen",
        "points": 5,
        "recurrence": {"type": "daily"},
        "rotation": {"member_ids": member_ids, "strategy": strategy},
    }
    payload.update(overrides)
    return await runtime.tasks.async_create_item(payload)


def _find_confirmation_task(runtime, original_task_id: str) -> dict | None:
    for task in runtime.tasks.data.values():
        confirms = task.get("confirms")
        if confirms and confirms["task_id"] == original_task_id:
            return task
    return None


async def test_complete_task_service_attributes_to_the_calling_user_not_member_ids_0(
    hass, init_integration
) -> None:
    """A shared fixed-assignment task must credit whoever actually clicked
    "Erledigt", not always the first member in rotation.member_ids."""
    runtime = init_integration.runtime_data
    ben = await runtime.members.async_create_item(
        {"name": "Ben", "role": "child", "person_entity_id": "person.ben"}
    )
    anna = await runtime.members.async_create_item(
        {"name": "Anna", "role": "child", "person_entity_id": "person.anna"}
    )
    await runtime.members.async_create_item({"name": "Mom", "role": "parent"})
    # Deliberately ben first: the old fallback (_assigned_member_id on a
    # "fixed" rotation) always picked member_ids[0], i.e. ben, regardless of
    # who completed it.
    task = await _add_task(runtime, member_ids=[ben["id"], anna["id"]])
    await runtime.coordinator.async_refresh()

    anna_user = await hass.auth.async_create_user("Anna's account")
    hass.states.async_set("person.anna", "home", {"user_id": anna_user.id})

    await hass.services.async_call(
        DOMAIN,
        SERVICE_COMPLETE_TASK,
        {ATTR_TASK_ID: task["id"]},
        blocking=True,
        context=Context(user_id=anna_user.id),
    )
    await runtime.coordinator.async_refresh()

    confirmation_task = _find_confirmation_task(runtime, task["id"])
    assert confirmation_task is not None
    assert confirmation_task["confirms"]["member_id"] == anna["id"]


async def test_complete_task_service_explicit_member_id_wins_over_context(
    hass, init_integration
) -> None:
    """An explicitly passed member_id still overrides context resolution."""
    runtime = init_integration.runtime_data
    ben = await runtime.members.async_create_item(
        {"name": "Ben", "role": "child", "person_entity_id": "person.ben"}
    )
    anna = await runtime.members.async_create_item(
        {"name": "Anna", "role": "child", "person_entity_id": "person.anna"}
    )
    await runtime.members.async_create_item({"name": "Mom", "role": "parent"})
    task = await _add_task(runtime, member_ids=[ben["id"], anna["id"]])
    await runtime.coordinator.async_refresh()

    anna_user = await hass.auth.async_create_user("Anna's account")
    hass.states.async_set("person.anna", "home", {"user_id": anna_user.id})

    await hass.services.async_call(
        DOMAIN,
        SERVICE_COMPLETE_TASK,
        {ATTR_TASK_ID: task["id"], ATTR_MEMBER_ID: ben["id"]},
        blocking=True,
        context=Context(user_id=anna_user.id),
    )
    await runtime.coordinator.async_refresh()

    confirmation_task = _find_confirmation_task(runtime, task["id"])
    assert confirmation_task is not None
    assert confirmation_task["confirms"]["member_id"] == ben["id"]


async def test_complete_task_service_without_linked_user_falls_back_as_before(
    hass, init_integration
) -> None:
    """No context / no linked member: falls back to the previous behaviour
    (assigned_member_id) instead of erroring out."""
    runtime = init_integration.runtime_data
    mom = await runtime.members.async_create_item({"name": "Mom", "role": "parent"})
    task = await _add_task(runtime, member_ids=[mom["id"]], strategy="round_robin")
    await runtime.coordinator.async_refresh()

    await hass.services.async_call(
        DOMAIN,
        SERVICE_COMPLETE_TASK,
        {ATTR_TASK_ID: task["id"]},
        blocking=True,
    )
    await runtime.coordinator.async_refresh()

    status = runtime.coordinator.data.tasks[task["id"]]
    assert status.last_completed_by == mom["id"]


async def test_toggle_subtask_service_attributes_to_the_calling_user(
    hass, init_integration
) -> None:
    """The same context resolution applies to the checklist toggle service,
    which also completes the task (and can trigger a confirmation) once the
    last sub-item is checked."""
    runtime = init_integration.runtime_data
    ben = await runtime.members.async_create_item(
        {"name": "Ben", "role": "child", "person_entity_id": "person.ben"}
    )
    anna = await runtime.members.async_create_item(
        {"name": "Anna", "role": "child", "person_entity_id": "person.anna"}
    )
    await runtime.members.async_create_item({"name": "Mom", "role": "parent"})
    task = await _add_task(
        runtime,
        member_ids=[ben["id"], anna["id"]],
        kind="checklist",
        subtasks=[{"id": "a", "name": "Geschirr"}],
    )
    await runtime.coordinator.async_refresh()

    anna_user = await hass.auth.async_create_user("Anna's account")
    hass.states.async_set("person.anna", "home", {"user_id": anna_user.id})

    await hass.services.async_call(
        DOMAIN,
        SERVICE_TOGGLE_SUBTASK,
        {ATTR_TASK_ID: task["id"], ATTR_SUBTASK_ID: "a"},
        blocking=True,
        context=Context(user_id=anna_user.id),
    )
    await runtime.coordinator.async_refresh()

    confirmation_task = _find_confirmation_task(runtime, task["id"])
    assert confirmation_task is not None
    assert confirmation_task["confirms"]["member_id"] == anna["id"]
