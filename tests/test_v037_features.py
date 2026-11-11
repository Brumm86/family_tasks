"""Tests for the three v0.37 changes:

1. A member can now be marked "paused" (CONF_MEMBER_PAUSED) - temporarily
   away from the household's task/reward system (e.g. a school trip),
   without touching their permanent "active"/CONF_MEMBER_REWARDS_OPT_IN
   configuration. See that constant's docstring in const.py for the full
   list of what pausing does.

2. Coins earned beyond the weekly goal now persist independently of
   CompletionLogStore's bounded size (MAX_COMPLETION_LOG_ENTRIES) - once a
   calendar week is over, its surplus is finalized into CoinLedgerStore
   (never pruned - see the v0.37 fix in that store's async_add_entry) by
   FamilyTasksCoordinator._async_process_weekly_coin_conversion, instead of
   being recomputed live from the completion log on every refresh forever.
   RETIRED IN v0.44: coins no longer derive from points/the weekly goal at
   all (a task earns coins directly via its own "coin_value" instead) - the
   whole weekly-conversion mechanism this point describes, and the three
   tests that covered it, are removed. Kept here only as a historical note;
   see const.py's COIN_REASON_WEEKLY_CONVERSION docstring for the full
   story.

3. Bug fix: editing a task via the card (family_tasks/task/update) no
   longer resets an in-progress round-robin/least-points rotation's
   current_index back to 0. TASK_UPDATE_SCHEMA's "rotation" field reuses
   ROTATION_SCHEMA (shared with TASK_CREATE_SCHEMA), which declares
   current_index as vol.Optional(..., default=0) - voluptuous re-inserts
   that default whenever the key is absent from the input, which it always
   was from the card's task-edit form (current_index is coordinator-internal
   bookkeeping, never exposed in the form). See
   TaskStorageCollection._update_data in storage.py for the fix itself; the
   scenario here exercises it through the full websocket update path.

Standalone reimplementation-level verification of the pure logic behind all
three (voluptuous-only, no HA runtime) was also run directly against copies
of the real code during development - see the session's verification notes.
This file follows the existing init_integration-fixture style for whenever a
real Python 3.13 HA test environment is available (see
project_family_tasks_test_env memory - the sandbox this was written in can't
run it end-to-end).
"""

from __future__ import annotations

from custom_components.family_tasks.const import CONF_MEMBER_PAUSED


async def _create_task(runtime, *, name, member_ids, points=5, strategy="round_robin"):
    return await runtime.tasks.async_create_item(
        {
            "name": name,
            "points": points,
            "recurrence": {"type": "daily"},
            "rotation": {"member_ids": member_ids, "strategy": strategy},
        }
    )


# --- 3) rotation current_index preservation on edit -------------------------


async def test_editing_a_task_preserves_rotation_progress(hass, init_integration) -> None:
    """A task rotating among 3 members, currently on the 3rd, keeps its place
    across an edit that has nothing to do with rotation (e.g. renaming it) -
    the bug this fixes silently reassigned it back to the 1st member on
    every single edit.
    """
    runtime = init_integration.runtime_data
    alice = await runtime.members.async_create_item({"name": "Alice"})
    bob = await runtime.members.async_create_item({"name": "Bob"})
    carol = await runtime.members.async_create_item({"name": "Carol"})
    task = await _create_task(
        runtime, name="Müll rausbringen", member_ids=[alice["id"], bob["id"], carol["id"]]
    )
    # Advance the rotation to the 3rd member directly in storage, simulating
    # two prior completions having already happened.
    await runtime.tasks.async_update_item(
        task["id"], {"rotation": {**task["rotation"], "current_index": 2}}
    )
    await runtime.coordinator.async_refresh()
    assert runtime.coordinator.data.tasks[task["id"]].assigned_member_id == carol["id"]

    # An edit that never mentions rotation.current_index at all - just like
    # the card's task-edit form.
    await runtime.tasks.async_update_item(
        task["id"],
        {
            "name": "Müll rausbringen (Mo)",
            "recurrence": {"type": "daily"},
            "rotation": {"member_ids": [alice["id"], bob["id"], carol["id"]], "strategy": "round_robin"},
        },
    )
    await runtime.coordinator.async_refresh()

    assert runtime.tasks.data[task["id"]]["rotation"]["current_index"] == 2
    assert runtime.coordinator.data.tasks[task["id"]].assigned_member_id == carol["id"]


async def test_rotation_still_advances_normally_on_completion(hass, init_integration) -> None:
    """The fix must not break the coordinator's own rotation advancement,
    which *does* always send an explicit current_index.
    """
    runtime = init_integration.runtime_data
    alice = await runtime.members.async_create_item({"name": "Alice"})
    bob = await runtime.members.async_create_item({"name": "Bob"})
    task = await _create_task(runtime, name="Spülmaschine", member_ids=[alice["id"], bob["id"]])
    await runtime.coordinator.async_refresh()
    assert runtime.coordinator.data.tasks[task["id"]].assigned_member_id == alice["id"]

    await runtime.coordinator.async_complete_task(task["id"], member_id=alice["id"])
    await runtime.coordinator.async_refresh()

    assert runtime.tasks.data[task["id"]]["rotation"]["current_index"] == 1
    assert runtime.coordinator.data.tasks[task["id"]].assigned_member_id == bob["id"]


# --- 1) member pause ---------------------------------------------------------


async def test_paused_member_is_skipped_by_rotation(hass, init_integration) -> None:
    runtime = init_integration.runtime_data
    alice = await runtime.members.async_create_item({"name": "Alice"})
    bob = await runtime.members.async_create_item(
        {"name": "Bob", CONF_MEMBER_PAUSED: True}
    )
    task = await _create_task(
        runtime, name="Zimmer aufräumen", member_ids=[alice["id"], bob["id"]]
    )
    await runtime.coordinator.async_refresh()

    status = runtime.coordinator.data.tasks[task["id"]]
    assert status.assigned_member_id == alice["id"]
    assert bob["id"] not in status.assigned_member_ids


async def test_task_assigned_solely_to_a_paused_member_is_not_due(hass, init_integration) -> None:
    runtime = init_integration.runtime_data
    bob = await runtime.members.async_create_item(
        {"name": "Bob", CONF_MEMBER_PAUSED: True}
    )
    task = await _create_task(runtime, name="Rasen mähen", member_ids=[bob["id"]])
    await runtime.coordinator.async_refresh()

    assert task["id"] not in runtime.coordinator.data.tasks


async def test_unpausing_a_member_makes_their_solo_task_due_again(hass, init_integration) -> None:
    runtime = init_integration.runtime_data
    bob = await runtime.members.async_create_item(
        {"name": "Bob", CONF_MEMBER_PAUSED: True}
    )
    task = await _create_task(runtime, name="Rasen mähen", member_ids=[bob["id"]])
    await runtime.coordinator.async_refresh()
    assert task["id"] not in runtime.coordinator.data.tasks

    await runtime.members.async_update_item(bob["id"], {CONF_MEMBER_PAUSED: False})
    await runtime.coordinator.async_refresh()

    assert task["id"] in runtime.coordinator.data.tasks
    assert runtime.coordinator.data.tasks[task["id"]].assigned_member_id == bob["id"]


async def test_pool_task_never_treated_as_fully_paused(hass, init_integration) -> None:
    """An Aufgabenpool task (no fixed assignee, empty rotation.member_ids)
    must never be swept up by the "every assignee paused" skip - it has no
    assignees to begin with.
    """
    runtime = init_integration.runtime_data
    await runtime.members.async_create_item(
        {"name": "Bob", CONF_MEMBER_PAUSED: True}
    )
    task = await _create_task(runtime, name="Pool-Aufgabe", member_ids=[])
    await runtime.coordinator.async_refresh()

    assert task["id"] in runtime.coordinator.data.tasks


async def test_paused_member_excluded_from_pool_eligibility(hass, init_integration) -> None:
    runtime = init_integration.runtime_data
    alice = await runtime.members.async_create_item({"name": "Alice"})
    bob = await runtime.members.async_create_item(
        {"name": "Bob", CONF_MEMBER_PAUSED: True}
    )
    task = await _create_task(runtime, name="Pool-Aufgabe", member_ids=[])
    await runtime.coordinator.async_refresh()

    eligible = runtime.coordinator.data.tasks[task["id"]].eligible_member_ids
    assert alice["id"] in eligible
    assert bob["id"] not in eligible
