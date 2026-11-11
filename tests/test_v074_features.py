"""Tests for v0.74.0: a member may hold only one "Annehmen" reservation at a time."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.util import dt as dt_util

from custom_components.family_tasks.const import CLAIM_RESERVATION_MINUTES


async def _pool_task(runtime, name):
    return await runtime.tasks.async_create_item(
        {
            "name": name,
            "points": 3,
            "recurrence": {"type": "daily"},
            "rotation": {"member_ids": [], "strategy": "fixed"},
        }
    )


async def _setup(runtime):
    anna = await runtime.members.async_create_item({"name": "Anna", "role": "child"})
    ben = await runtime.members.async_create_item({"name": "Ben", "role": "child"})
    first = await _pool_task(runtime, "Erste")
    second = await _pool_task(runtime, "Zweite")
    await runtime.coordinator.async_refresh()
    return anna, ben, first, second


async def test_second_claim_by_same_member_is_ignored(hass, init_integration) -> None:
    runtime = init_integration.runtime_data
    anna, ben, first, second = await _setup(runtime)

    await runtime.coordinator.async_claim_task(first["id"], anna["id"])
    await runtime.coordinator.async_claim_task(second["id"], anna["id"])
    await runtime.coordinator.async_refresh()

    tasks = runtime.coordinator.data.tasks
    assert tasks[first["id"]].claimed_by_member_id == anna["id"]
    assert tasks[second["id"]].claimed_by_member_id is None
    assert runtime.coordinator.active_claim_task_id(anna["id"]) == first["id"]


async def test_other_member_can_still_claim_another_task(hass, init_integration) -> None:
    runtime = init_integration.runtime_data
    anna, ben, first, second = await _setup(runtime)

    await runtime.coordinator.async_claim_task(first["id"], anna["id"])
    await runtime.coordinator.async_claim_task(second["id"], ben["id"])
    await runtime.coordinator.async_refresh()

    tasks = runtime.coordinator.data.tasks
    assert tasks[first["id"]].claimed_by_member_id == anna["id"]
    assert tasks[second["id"]].claimed_by_member_id == ben["id"]


async def test_claim_possible_again_after_release(hass, init_integration) -> None:
    runtime = init_integration.runtime_data
    anna, ben, first, second = await _setup(runtime)

    await runtime.coordinator.async_claim_task(first["id"], anna["id"])
    await runtime.coordinator.async_release_task(first["id"], anna["id"])
    assert runtime.coordinator.active_claim_task_id(anna["id"]) is None

    await runtime.coordinator.async_claim_task(second["id"], anna["id"])
    await runtime.coordinator.async_refresh()
    assert runtime.coordinator.data.tasks[second["id"]].claimed_by_member_id == anna["id"]


async def test_expired_claim_does_not_block_new_claim(hass, init_integration) -> None:
    runtime = init_integration.runtime_data
    anna, ben, first, second = await _setup(runtime)

    await runtime.coordinator.async_claim_task(first["id"], anna["id"])
    # Age the stored claim past its reservation window.
    entry = runtime.coordinator.claim_state._state[first["id"]]
    entry["claimed_at"] = (
        dt_util.utcnow() - timedelta(minutes=CLAIM_RESERVATION_MINUTES + 1)
    ).isoformat()
    assert runtime.coordinator.active_claim_task_id(anna["id"]) is None

    await runtime.coordinator.async_claim_task(second["id"], anna["id"])
    await runtime.coordinator.async_refresh()
    assert runtime.coordinator.data.tasks[second["id"]].claimed_by_member_id == anna["id"]
