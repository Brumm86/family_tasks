"""Tests for the v0.44 coin-model redesign.

Before this version, a member's coin balance had two parts: the coin
ledger's own balance (Meilenstein-/Streak-Bonus credits, redemption debits)
plus a live "points earned beyond the weekly goal" computation
(storage.coins_from_task_points) - so a member earned zero coins in any
week they didn't fully reach CONF_WEEKLY_PROGRESS_GOAL_POINTS, however many
tasks they actually completed. v0.44 replaces the second part entirely: a
task now optionally carries its own "coin_value" (default 0, independent of
"points"), credited straight to CoinLedgerStore the moment the task is
completed - COIN_REASON_TASK_COMPLETION in const.py - with no dependency on
the weekly goal being reached at all. The Meilenstein-/Streak-Bonus
mechanism itself is unchanged (still judged against points_week vs. the
weekly goal, still credits coins directly to the ledger); only the base
"how does a member earn any coins at all" mechanic changed.

coins_available (MemberSummaryData.coins_available) is now simply
coin_ledger.balance(member_id) - see coordinator.py's _async_update_data.

Standalone reimplementation-level verification of the pure logic here
(voluptuous-only schema defaults, the credit-or-skip branch) was also run
directly against copies of the real code during development - see the
session's verification notes. This file follows the existing
init_integration-fixture style for whenever a real Python 3.13 HA test
environment is available (see project_family_tasks_test_env memory - the
sandbox this was written in can't run it end-to-end).
"""

from __future__ import annotations

from custom_components.family_tasks.const import CONF_WEEKLY_PROGRESS_GOAL_POINTS


async def _add_task(runtime, *, member_ids, **overrides):
    payload = {
        "name": "Rasen mähen",
        "points": 5,
        "coin_value": 0,
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


async def test_completing_a_task_credits_its_coin_value(hass, init_integration) -> None:
    """A task with a positive coin_value credits exactly that many coins on completion."""
    runtime = init_integration.runtime_data
    alice = await runtime.members.async_create_item({"name": "Alice"})
    task = await _add_task(runtime, member_ids=[alice["id"]], points=5, coin_value=3)
    await runtime.coordinator.async_refresh()

    await runtime.coordinator.async_complete_task(task["id"], member_id=alice["id"])
    await runtime.coordinator.async_refresh()

    assert runtime.coordinator.data.members[alice["id"]].coins_available == 3
    assert runtime.coin_ledger.balance(alice["id"]) == 3
    credits = [e for e in runtime.coin_ledger.entries if e["member_id"] == alice["id"]]
    assert len(credits) == 1
    assert credits[0]["reason"] == "task_completion"


async def test_default_coin_value_credits_nothing(hass, init_integration) -> None:
    """A task saved without an explicit coin_value (the v0.44 default, 0) earns no coins."""
    runtime = init_integration.runtime_data
    alice = await runtime.members.async_create_item({"name": "Alice"})
    # coin_value deliberately omitted - TASK_CREATE_SCHEMA defaults it to 0.
    task = await runtime.tasks.async_create_item(
        {
            "name": "Zimmer aufräumen",
            "points": 5,
            "recurrence": {"type": "daily"},
            "rotation": {"member_ids": [alice["id"]], "strategy": "round_robin"},
        }
    )
    await runtime.coordinator.async_refresh()

    await runtime.coordinator.async_complete_task(task["id"], member_id=alice["id"])
    await runtime.coordinator.async_refresh()

    assert runtime.coordinator.data.members[alice["id"]].points_today == 5
    assert runtime.coordinator.data.members[alice["id"]].coins_available == 0
    assert runtime.coin_ledger.balance(alice["id"]) == 0


async def test_coins_available_no_longer_gated_by_weekly_goal(hass, init_integration) -> None:
    """The whole point of v0.44: coins flow even in a week the goal is never reached."""
    runtime = init_integration.runtime_data
    hass.config_entries.async_update_entry(
        init_integration, options={CONF_WEEKLY_PROGRESS_GOAL_POINTS: 100}
    )
    alice = await runtime.members.async_create_item({"name": "Alice"})
    task = await _add_task(runtime, member_ids=[alice["id"]], points=5, coin_value=2)
    await runtime.coordinator.async_refresh()

    await runtime.coordinator.async_complete_task(task["id"], member_id=alice["id"])
    await runtime.coordinator.async_refresh()

    # Nowhere near the 100-point weekly goal - under the pre-v0.44 model
    # this would be 0 coins. Now it's the task's own coin_value regardless.
    assert runtime.coordinator.data.members[alice["id"]].points_week == 5
    assert runtime.coordinator.data.members[alice["id"]].coins_available == 2


async def test_parent_confirming_child_completion_credits_coin_value(
    hass, init_integration
) -> None:
    """The parent-confirms-a-child's-claim path credits coins too, not just direct completion."""
    runtime = init_integration.runtime_data
    timmy = await runtime.members.async_create_item({"name": "Timmy", "role": "child"})
    await runtime.members.async_create_item({"name": "Mom", "role": "parent"})
    task = await _add_task(runtime, member_ids=[timmy["id"]], points=5, coin_value=4)
    await runtime.coordinator.async_refresh()

    await runtime.coordinator.async_complete_task(task["id"])
    await runtime.coordinator.async_refresh()
    assert runtime.coordinator.data.members[timmy["id"]].coins_available == 0

    confirmation_task = _find_confirmation_task(runtime, task["id"])
    await runtime.coordinator.async_complete_task(confirmation_task["id"])
    await runtime.coordinator.async_refresh()

    assert runtime.coordinator.data.members[timmy["id"]].coins_available == 4
    assert runtime.coin_ledger.balance(timmy["id"]) == 4


async def test_favorite_instantiate_carries_coin_value_onto_new_task(
    hass, init_integration, hass_ws_client
) -> None:
    """A Favorit's own coin_value is copied onto every task created from it."""
    runtime = init_integration.runtime_data
    alice = await runtime.members.async_create_item({"name": "Alice"})
    favorite = await runtime.favorites.async_create_item(
        {"name": "Geschirrspüler ausräumen", "points": 3, "coin_value": 1, "member_ids": [alice["id"]]}
    )
    before = set(runtime.tasks.data)

    # Instantiating is admin/parent-only (see ws_instantiate_favorite in
    # storage.py); the default hass_ws_client(hass) connection has no
    # linked person entity at all, so _member_role_for_user resolves to
    # None, not "child" - the same "not a child" check every other
    # parent-only command in this module uses.
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "family_tasks/favorite/instantiate", "favorite_id": favorite["id"]}
    )
    response = await client.receive_json()
    assert response["success"] is True

    new_task_id = next(iter(set(runtime.tasks.data) - before))
    new_task = runtime.tasks.data[new_task_id]
    assert new_task["points"] == 3
    assert new_task["coin_value"] == 1
    # The template itself is untouched and can be reused.
    assert runtime.favorites.data[favorite["id"]]["coin_value"] == 1

    await runtime.coordinator.async_refresh()
    await runtime.coordinator.async_complete_task(new_task_id, member_id=alice["id"])
    await runtime.coordinator.async_refresh()

    assert runtime.coordinator.data.members[alice["id"]].coins_available == 1


async def test_reset_points_clears_coins_earned_from_task_completions(
    hass, init_integration
) -> None:
    """SERVICE_RESET_POINTS wipes coins earned via coin_value too, same as any other credit."""
    runtime = init_integration.runtime_data
    alice = await runtime.members.async_create_item({"name": "Alice"})
    task = await _add_task(runtime, member_ids=[alice["id"]], points=5, coin_value=6)
    await runtime.coordinator.async_refresh()
    await runtime.coordinator.async_complete_task(task["id"], member_id=alice["id"])
    await runtime.coordinator.async_refresh()
    assert runtime.coordinator.data.members[alice["id"]].coins_available == 6

    await runtime.coordinator.async_reset_points(alice["id"])
    await runtime.coordinator.async_refresh()

    assert runtime.coordinator.data.members[alice["id"]].coins_available == 0
    assert runtime.coin_ledger.balance(alice["id"]) == 0
