"""Tests for sensor-triggered tasks (recurrence type 'trigger')."""

from __future__ import annotations

from custom_components.family_tasks.const import (
    TASK_STATUS_IDLE,
    TASK_STATUS_PENDING,
)


async def _add_state_trigger_task(
    runtime, *, member_ids, entity_id="binary_sensor.bin_full"
):
    return await runtime.tasks.async_create_item(
        {
            "name": "Mülleimer leeren",
            "points": 5,
            "recurrence": {
                "type": "trigger",
                "trigger": {"kind": "state", "entity_id": entity_id, "to_state": "on"},
            },
            "rotation": {"member_ids": member_ids},
        }
    )


async def _add_numeric_trigger_task(
    runtime, *, member_ids, entity_id="sensor.bin_level", above=80
):
    return await runtime.tasks.async_create_item(
        {
            "name": "Mülleimer leeren",
            "points": 5,
            "recurrence": {
                "type": "trigger",
                "trigger": {
                    "kind": "numeric_state",
                    "entity_id": entity_id,
                    "above": above,
                },
            },
            "rotation": {"member_ids": member_ids},
        }
    )


async def test_trigger_task_starts_idle(hass, init_integration) -> None:
    """A trigger task with no sensor event yet is idle, not due."""
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})
    hass.states.async_set("binary_sensor.bin_full", "off")
    await hass.async_block_till_done()

    task = await _add_state_trigger_task(runtime, member_ids=[anna["id"]])
    await runtime.coordinator.async_refresh()

    assert runtime.coordinator.data.tasks[task["id"]].status == TASK_STATUS_IDLE


async def test_binary_sensor_turning_on_makes_task_pending(
    hass, init_integration
) -> None:
    """The state trigger opens an occurrence once the bound entity matches."""
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})
    hass.states.async_set("binary_sensor.bin_full", "off")
    await hass.async_block_till_done()
    task = await _add_state_trigger_task(runtime, member_ids=[anna["id"]])
    await runtime.coordinator.async_refresh()

    hass.states.async_set("binary_sensor.bin_full", "on")
    await hass.async_block_till_done()

    assert runtime.coordinator.data.tasks[task["id"]].status == TASK_STATUS_PENDING


async def test_repeated_matching_state_does_not_reopen_task(
    hass, init_integration
) -> None:
    """Flipping attributes while already 'on' must not open a second occurrence."""
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})
    hass.states.async_set("binary_sensor.bin_full", "off")
    await hass.async_block_till_done()
    task = await _add_state_trigger_task(runtime, member_ids=[anna["id"]])
    await runtime.coordinator.async_refresh()

    hass.states.async_set("binary_sensor.bin_full", "on")
    await hass.async_block_till_done()
    first_triggered_at = runtime.trigger_state.get(task["id"])["triggered_at"]

    hass.states.async_set("binary_sensor.bin_full", "on", {"extra": "attr"})
    await hass.async_block_till_done()

    assert runtime.trigger_state.get(task["id"])["triggered_at"] == first_triggered_at


async def test_completing_trigger_task_returns_it_to_idle(
    hass, init_integration
) -> None:
    """Completing the open occurrence clears it until the sensor fires again."""
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})
    hass.states.async_set("binary_sensor.bin_full", "off")
    await hass.async_block_till_done()
    task = await _add_state_trigger_task(runtime, member_ids=[anna["id"]])
    await runtime.coordinator.async_refresh()
    hass.states.async_set("binary_sensor.bin_full", "on")
    await hass.async_block_till_done()
    assert runtime.coordinator.data.tasks[task["id"]].status == TASK_STATUS_PENDING

    await runtime.coordinator.async_complete_task(task["id"])

    assert runtime.trigger_state.get(task["id"]) is None
    assert runtime.coordinator.data.tasks[task["id"]].status == TASK_STATUS_IDLE
    assert runtime.coordinator.data.members[anna["id"]].points_today == 5


async def test_trigger_task_fires_again_after_completion(
    hass, init_integration
) -> None:
    """A new sensor event after completion re-opens a fresh occurrence."""
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})
    hass.states.async_set("binary_sensor.bin_full", "off")
    await hass.async_block_till_done()
    task = await _add_state_trigger_task(runtime, member_ids=[anna["id"]])
    await runtime.coordinator.async_refresh()
    hass.states.async_set("binary_sensor.bin_full", "on")
    await hass.async_block_till_done()
    await runtime.coordinator.async_complete_task(task["id"])

    hass.states.async_set("binary_sensor.bin_full", "off")
    await hass.async_block_till_done()
    hass.states.async_set("binary_sensor.bin_full", "on")
    await hass.async_block_till_done()

    assert runtime.coordinator.data.tasks[task["id"]].status == TASK_STATUS_PENDING
    assert runtime.coordinator.data.members[anna["id"]].points_today == 10


async def test_numeric_state_trigger_fires_on_crossing_threshold(
    hass, init_integration
) -> None:
    """Crossing above the configured threshold opens an occurrence."""
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})
    hass.states.async_set("sensor.bin_level", "50")
    await hass.async_block_till_done()
    task = await _add_numeric_trigger_task(runtime, member_ids=[anna["id"]], above=80)
    await runtime.coordinator.async_refresh()

    hass.states.async_set("sensor.bin_level", "90")
    await hass.async_block_till_done()

    assert runtime.coordinator.data.tasks[task["id"]].status == TASK_STATUS_PENDING


async def test_numeric_state_trigger_does_not_reopen_while_still_above(
    hass, init_integration
) -> None:
    """Bouncing around above the threshold keeps a single open occurrence."""
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})
    hass.states.async_set("sensor.bin_level", "50")
    await hass.async_block_till_done()
    task = await _add_numeric_trigger_task(runtime, member_ids=[anna["id"]], above=80)
    await runtime.coordinator.async_refresh()

    hass.states.async_set("sensor.bin_level", "90")
    await hass.async_block_till_done()
    first_triggered_at = runtime.trigger_state.get(task["id"])["triggered_at"]

    hass.states.async_set("sensor.bin_level", "95")
    await hass.async_block_till_done()

    assert runtime.trigger_state.get(task["id"])["triggered_at"] == first_triggered_at


async def test_unrelated_entity_state_change_is_ignored(
    hass, init_integration
) -> None:
    """State changes on entities not referenced by any trigger task are ignored."""
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})
    hass.states.async_set("binary_sensor.bin_full", "off")
    await hass.async_block_till_done()
    task = await _add_state_trigger_task(runtime, member_ids=[anna["id"]])
    await runtime.coordinator.async_refresh()

    hass.states.async_set("binary_sensor.unrelated", "on")
    await hass.async_block_till_done()

    assert runtime.coordinator.data.tasks[task["id"]].status == TASK_STATUS_IDLE
