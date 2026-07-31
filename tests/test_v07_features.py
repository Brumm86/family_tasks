"""Tests for the v0.7 features: checklist tasks, the trigger-task current
sensor value, the completion-button hook, and assigned_member_ids (the fix
for a fixed multi-assignee task only ever showing one assignee).
"""

from __future__ import annotations

import pytest
import voluptuous as vol

from homeassistant.exceptions import HomeAssistantError

from custom_components.family_tasks.const import (
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


# --- assigned_member_ids (fixed multi-assignee display fix) -----------------


async def test_assigned_member_ids_lists_everyone_for_fixed_multi_assignee(
    hass, init_integration
) -> None:
    """A fixed rotation with several members lists all of them, not just one."""
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})
    ben = await runtime.members.async_create_item({"name": "Ben"})
    task = await _add_task(
        runtime,
        member_ids=[anna["id"], ben["id"]],
        rotation={"member_ids": [anna["id"], ben["id"]], "strategy": "fixed"},
    )
    await runtime.coordinator.async_refresh()

    status = runtime.coordinator.data.tasks[task["id"]]
    assert status.assigned_member_id == anna["id"]
    assert status.assigned_member_ids == [anna["id"], ben["id"]]


async def test_assigned_member_ids_is_a_single_entry_for_round_robin(
    hass, init_integration
) -> None:
    """Every rotation strategy except multi-assignee "fixed" has one assignee."""
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})
    ben = await runtime.members.async_create_item({"name": "Ben"})
    task = await _add_task(runtime, member_ids=[anna["id"], ben["id"]])
    await runtime.coordinator.async_refresh()

    status = runtime.coordinator.data.tasks[task["id"]]
    assert status.assigned_member_ids == [anna["id"]]


async def test_assigned_member_ids_is_a_single_entry_for_fixed_with_one_member(
    hass, init_integration
) -> None:
    """A "fixed" rotation with only one member is still just that one member."""
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})
    task = await _add_task(
        runtime,
        member_ids=[anna["id"]],
        rotation={"member_ids": [anna["id"]], "strategy": "fixed"},
    )
    await runtime.coordinator.async_refresh()

    status = runtime.coordinator.data.tasks[task["id"]]
    assert status.assigned_member_ids == [anna["id"]]


# --- trigger task: current sensor value -------------------------------------


async def test_trigger_task_reports_current_sensor_value(hass, init_integration) -> None:
    """The bound sensor's current state/unit is exposed on the task status."""
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})
    hass.states.async_set("sensor.soil_moisture", "42", {"unit_of_measurement": "%"})

    task = await _add_task(
        runtime,
        member_ids=[anna["id"]],
        recurrence={
            "type": "trigger",
            "trigger": {"kind": "numeric_state", "entity_id": "sensor.soil_moisture", "below": 50},
        },
    )
    await runtime.coordinator.async_refresh()

    status = runtime.coordinator.data.tasks[task["id"]]
    assert status.trigger_sensor_value == "42"
    assert status.trigger_sensor_unit == "%"


async def test_trigger_sensor_value_is_none_when_entity_has_no_state(
    hass, init_integration
) -> None:
    """An unknown trigger entity just leaves the value/unit unset, no error."""
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})

    task = await _add_task(
        runtime,
        member_ids=[anna["id"]],
        recurrence={
            "type": "trigger",
            "trigger": {"kind": "state", "entity_id": "binary_sensor.does_not_exist", "to_state": "on"},
        },
    )
    await runtime.coordinator.async_refresh()

    status = runtime.coordinator.data.tasks[task["id"]]
    assert status.trigger_sensor_value is None
    assert status.trigger_sensor_unit is None


# --- completion button -------------------------------------------------------


async def test_completion_button_is_pressed_on_task_completion(hass, init_integration) -> None:
    """A task's completion_button_entity_id gets 'button.press'-ed once done."""
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})
    calls = []

    async def _fake_press(call):
        calls.append(dict(call.data))

    hass.services.async_register("button", "press", _fake_press)

    task = await _add_task(
        runtime,
        member_ids=[anna["id"]],
        completion_button_entity_id="button.vacuum_resume",
    )
    await runtime.coordinator.async_refresh()

    await runtime.coordinator.async_complete_task(task["id"])
    await hass.async_block_till_done()

    assert calls == [{"entity_id": "button.vacuum_resume"}]


async def test_no_completion_button_configured_is_a_no_op(hass, init_integration) -> None:
    """Tasks without a completion_button_entity_id complete normally."""
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})
    task = await _add_task(runtime, member_ids=[anna["id"]])
    await runtime.coordinator.async_refresh()

    await runtime.coordinator.async_complete_task(task["id"])

    assert runtime.coordinator.data.members[anna["id"]].points_today == 5


# --- checklist tasks ---------------------------------------------------------


async def test_checklist_task_requires_at_least_one_subtask(hass, init_integration) -> None:
    """A checklist with no sub-items must be rejected."""
    runtime = init_integration.runtime_data

    with pytest.raises(vol.Invalid):
        await runtime.tasks.async_create_item(
            {
                "name": "Kofferpacken",
                "kind": "checklist",
                "recurrence": {"type": "once"},
                "rotation": {"member_ids": []},
            }
        )


async def test_checklist_task_rejects_duplicate_subtask_ids(hass, init_integration) -> None:
    """Sub-item ids must be unique within a task."""
    runtime = init_integration.runtime_data

    with pytest.raises(vol.Invalid):
        await runtime.tasks.async_create_item(
            {
                "name": "Kofferpacken",
                "kind": "checklist",
                "subtasks": [{"id": "a", "name": "Reisepass"}, {"id": "a", "name": "Ladekabel"}],
                "recurrence": {"type": "once"},
                "rotation": {"member_ids": []},
            }
        )


async def test_checklist_completes_only_once_every_subtask_is_checked(
    hass, init_integration
) -> None:
    """Checking every sub-item auto-completes the task (points + rotation);
    checking only some leaves it pending."""
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})
    ben = await runtime.members.async_create_item({"name": "Ben"})
    task = await _add_task(
        runtime,
        member_ids=[anna["id"], ben["id"]],
        kind="checklist",
        subtasks=[
            {"id": "passport", "name": "Reisepass"},
            {"id": "charger", "name": "Ladekabel"},
        ],
    )
    await runtime.coordinator.async_refresh()

    await runtime.coordinator.async_toggle_subtask(task["id"], "passport")
    # async_toggle_subtask's own refresh goes through the coordinator's
    # debounced async_request_refresh (immediate only the *first* time it's
    # called after a direct async_refresh()) - force a direct refresh before
    # asserting so a second action in the same test isn't racing a pending
    # debounced one, same pattern the rest of this suite uses around
    # back-to-back complete_task/skip_task calls.
    await runtime.coordinator.async_refresh()

    status = runtime.coordinator.data.tasks[task["id"]]
    assert status.status == TASK_STATUS_PENDING
    assert {s["id"]: s["checked"] for s in status.subtasks} == {
        "passport": True,
        "charger": False,
    }

    await runtime.coordinator.async_toggle_subtask(task["id"], "charger")
    await runtime.coordinator.async_refresh()

    status = runtime.coordinator.data.tasks[task["id"]]
    assert status.status == TASK_STATUS_DONE
    assert runtime.coordinator.data.members[anna["id"]].points_today == 5
    # Completing a checklist goes through the normal completion path, so
    # rotation still advances like any other multi-member task.
    assert runtime.tasks.data[task["id"]]["rotation"]["current_index"] == 1


async def test_unchecking_a_subtask_toggles_it_back_off(hass, init_integration) -> None:
    """Toggling an already-checked sub-item unchecks it again."""
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})
    task = await _add_task(
        runtime,
        member_ids=[anna["id"]],
        kind="checklist",
        subtasks=[{"id": "passport", "name": "Reisepass"}, {"id": "charger", "name": "Ladekabel"}],
    )
    await runtime.coordinator.async_refresh()

    await runtime.coordinator.async_toggle_subtask(task["id"], "passport")
    await runtime.coordinator.async_refresh()
    await runtime.coordinator.async_toggle_subtask(task["id"], "passport")
    await runtime.coordinator.async_refresh()

    status = runtime.coordinator.data.tasks[task["id"]]
    assert status.status == TASK_STATUS_PENDING
    assert all(not s["checked"] for s in status.subtasks)


async def test_toggle_subtask_rejects_non_checklist_task(hass, init_integration) -> None:
    """toggle_subtask must refuse a task that isn't a checklist."""
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})
    task = await _add_task(runtime, member_ids=[anna["id"]])
    await runtime.coordinator.async_refresh()

    with pytest.raises(HomeAssistantError):
        await runtime.coordinator.async_toggle_subtask(task["id"], "whatever")


async def test_toggle_subtask_rejects_unknown_subtask_id(hass, init_integration) -> None:
    """toggle_subtask must refuse a subtask_id that isn't part of the task."""
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})
    task = await _add_task(
        runtime,
        member_ids=[anna["id"]],
        kind="checklist",
        subtasks=[{"id": "passport", "name": "Reisepass"}],
    )
    await runtime.coordinator.async_refresh()

    with pytest.raises(HomeAssistantError):
        await runtime.coordinator.async_toggle_subtask(task["id"], "does-not-exist")
