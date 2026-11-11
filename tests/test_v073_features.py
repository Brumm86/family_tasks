"""Tests for v0.73.0: optional ``from_state`` on a "state" sensor trigger.

A trigger ``{"kind": "state", "entity_id": ..., "from_state": "running",
"to_state": "on"}`` only opens the task on the transition running -> on, not
when the entity reaches "on" from any other state (e.g. a dryer that reports
"on" briefly at program start before switching to "running").
"""

from __future__ import annotations

import pytest
import voluptuous as vol

from custom_components.family_tasks.const import TASK_STATUS_IDLE, TASK_STATUS_PENDING

ENTITY = "sensor.test_dryer_state"


async def _add_task(runtime, *, member_ids, **trigger_extra):
    return await runtime.tasks.async_create_item(
        {
            "name": "Bring laundry up",
            "points": 2,
            "recurrence": {
                "type": "trigger",
                "trigger": {"kind": "state", "entity_id": ENTITY, "to_state": "on", **trigger_extra},
            },
            "rotation": {"member_ids": member_ids},
        }
    )


async def _set(hass, state: str) -> None:
    hass.states.async_set(ENTITY, state)
    await hass.async_block_till_done()


async def test_from_state_is_stored(hass, init_integration) -> None:
    runtime = init_integration.runtime_data
    task = await _add_task(runtime, member_ids=[], from_state="running")
    assert task["recurrence"]["trigger"]["from_state"] == "running"

    plain = await _add_task(runtime, member_ids=[])
    assert "from_state" not in plain["recurrence"]["trigger"]


async def test_invalid_from_state_type_is_rejected(hass, init_integration) -> None:
    with pytest.raises(vol.Invalid):
        await _add_task(init_integration.runtime_data, member_ids=[], from_state=["running"])


async def test_program_start_blip_does_not_open_task(hass, init_integration) -> None:
    """off -> on (program start) must not trigger; running -> on (program end) must."""
    runtime = init_integration.runtime_data
    await _set(hass, "off")
    task = await _add_task(runtime, member_ids=[], from_state="running")
    await runtime.coordinator.async_refresh()
    assert runtime.coordinator.data.tasks[task["id"]].status == TASK_STATUS_IDLE

    await _set(hass, "on")  # brief "on" at program start
    await runtime.coordinator.async_refresh()
    assert runtime.coordinator.data.tasks[task["id"]].status == TASK_STATUS_IDLE

    await _set(hass, "running")
    await runtime.coordinator.async_refresh()
    assert runtime.coordinator.data.tasks[task["id"]].status == TASK_STATUS_IDLE

    await _set(hass, "on")  # program finished
    await runtime.coordinator.async_refresh()
    assert runtime.coordinator.data.tasks[task["id"]].status == TASK_STATUS_PENDING


async def test_without_from_state_any_transition_into_on_opens_task(hass, init_integration) -> None:
    """Regression guard: without from_state the behavior is unchanged."""
    runtime = init_integration.runtime_data
    await _set(hass, "off")
    task = await _add_task(runtime, member_ids=[])
    await runtime.coordinator.async_refresh()

    await _set(hass, "on")
    await runtime.coordinator.async_refresh()
    assert runtime.coordinator.data.tasks[task["id"]].status == TASK_STATUS_PENDING


async def test_unavailable_previous_state_does_not_satisfy_from_state(hass, init_integration) -> None:
    runtime = init_integration.runtime_data
    await _set(hass, "unavailable")
    task = await _add_task(runtime, member_ids=[], from_state="running")
    await runtime.coordinator.async_refresh()

    await _set(hass, "on")
    await runtime.coordinator.async_refresh()
    assert runtime.coordinator.data.tasks[task["id"]].status == TASK_STATUS_IDLE
