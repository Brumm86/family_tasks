"""Tests for the v0.8 features:

- A "child" member can create a checklist task for themselves via the
  restricted family_tasks/task/create_own command (same "kind"/"subtasks"
  fields as the admin task schema).
- Reward groups (admin-only CRUD) and the reward-claim flow: only the
  current weekly winner may claim one (family_tasks/reward/claim), at most
  once per calendar week, and only a parent (not a "child", even with an HA
  admin account) may mark one "fulfilled". The generic "reward/create"
  command is always rejected - claiming is the only way to create one.
- FamilyTasksCoordinator's is_weekly_winner computation on MemberSummaryData.
"""

from __future__ import annotations

from homeassistant.auth.const import GROUP_ID_ADMIN

from custom_components.family_tasks.const import TASK_KIND_CHECKLIST


async def _client_for_new_user(hass, hass_ws_client, *, is_admin: bool, name: str = "Test User"):
    """Create a fresh HA user (admin or not) and return a connected ws client."""
    group_ids = [GROUP_ID_ADMIN] if is_admin else []
    user = await hass.auth.async_create_user(name, group_ids=group_ids)
    refresh_token = await hass.auth.async_create_refresh_token(user)
    access_token = hass.auth.async_create_access_token(refresh_token)
    client = await hass_ws_client(hass, access_token)
    return user, client


async def _add_task(runtime, *, member_ids, **overrides):
    payload = {
        "name": "Testaufgabe",
        "points": 5,
        "recurrence": {"type": "daily"},
        "rotation": {"member_ids": member_ids, "strategy": "round_robin"},
    }
    payload.update(overrides)
    return await runtime.tasks.async_create_item(payload)


# --- children can create checklist self-tasks -------------------------------


async def test_child_can_create_own_checklist_task(
    hass, init_integration, hass_ws_client
) -> None:
    """create_own now accepts kind=checklist with named sub-items."""
    runtime = init_integration.runtime_data
    timmy = await runtime.members.async_create_item(
        {"name": "Timmy", "role": "child", "person_entity_id": "person.timmy"}
    )
    user, client = await _client_for_new_user(hass, hass_ws_client, is_admin=False)
    hass.states.async_set("person.timmy", "home", {"user_id": user.id})

    await client.send_json_auto_id(
        {
            "type": "family_tasks/task/create_own",
            "name": "Kofferpacken",
            "recurrence": {"type": "once", "anchor_date": "2026-08-01"},
            "kind": "checklist",
            "subtasks": [{"id": "a", "name": "Reisepass"}, {"id": "b", "name": "Zahnbürste"}],
        }
    )
    response = await client.receive_json()

    assert response["success"] is True
    task = response["result"]
    assert task["kind"] == TASK_KIND_CHECKLIST
    assert [s["name"] for s in task["subtasks"]] == ["Reisepass", "Zahnbürste"]
    assert task["points"] == 0
    assert task["rotation"]["member_ids"] == [timmy["id"]]


async def test_child_own_checklist_task_needs_at_least_one_subtask(
    hass, init_integration, hass_ws_client
) -> None:
    """The same 'checklist needs >=1 subtask' rule applies to create_own."""
    runtime = init_integration.runtime_data
    await runtime.members.async_create_item(
        {"name": "Timmy", "role": "child", "person_entity_id": "person.timmy"}
    )
    user, client = await _client_for_new_user(hass, hass_ws_client, is_admin=False)
    hass.states.async_set("person.timmy", "home", {"user_id": user.id})

    await client.send_json_auto_id(
        {
            "type": "family_tasks/task/create_own",
            "name": "Kofferpacken",
            "recurrence": {"type": "daily"},
            "kind": "checklist",
            "subtasks": [],
        }
    )
    response = await client.receive_json()

    assert response["success"] is False
    assert response["error"]["code"] == "invalid_format"


# --- reward groups (admin-only CRUD) ----------------------------------------


async def test_admin_can_manage_reward_groups(hass, init_integration, hass_ws_client) -> None:
    runtime = init_integration.runtime_data
    _, client = await _client_for_new_user(hass, hass_ws_client, is_admin=True)

    await client.send_json_auto_id(
        {"type": "family_tasks/reward_group/create", "name": "Mittagessen auswählen"}
    )
    response = await client.receive_json()

    assert response["success"] is True
    assert response["result"]["name"] == "Mittagessen auswählen"
    assert response["result"]["id"] in runtime.reward_groups.data


async def test_non_admin_cannot_create_reward_groups(
    hass, init_integration, hass_ws_client
) -> None:
    _, client = await _client_for_new_user(hass, hass_ws_client, is_admin=False)

    await client.send_json_auto_id(
        {"type": "family_tasks/reward_group/create", "name": "Sneaky group"}
    )
    response = await client.receive_json()

    assert response["success"] is False


# --- reward claim flow -------------------------------------------------------


async def test_generic_reward_create_is_always_rejected(
    hass, init_integration, hass_ws_client
) -> None:
    """Even an admin cannot create a reward through the generic command -
    only family_tasks/reward/claim may."""
    _, client = await _client_for_new_user(hass, hass_ws_client, is_admin=True)

    await client.send_json_auto_id(
        {
            "type": "family_tasks/reward/create",
            "member_id": "anyone",
            "member_name": "Anyone",
            "reward_group_id": "whatever",
            "reward_group_name": "Whatever",
            "detail": "Pizza",
            "period_key": "2026-07-27",
        }
    )
    response = await client.receive_json()

    assert response["success"] is False


async def test_weekly_winner_can_claim_a_reward(
    hass, init_integration, hass_ws_client
) -> None:
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item(
        {"name": "Anna", "role": "child", "person_entity_id": "person.anna"}
    )
    ben = await runtime.members.async_create_item({"name": "Ben", "role": "child"})
    group = await runtime.reward_groups.async_create_item({"name": "Mittagessen auswählen"})

    # Anna has more points this week than Ben, so she's the sole winner.
    winning_task = await _add_task(runtime, member_ids=[anna["id"]], points=10)
    losing_task = await _add_task(runtime, member_ids=[ben["id"]], points=3)
    await runtime.coordinator.async_refresh()
    await runtime.coordinator.async_complete_task(winning_task["id"])
    await runtime.coordinator.async_complete_task(losing_task["id"])
    await runtime.coordinator.async_refresh()

    assert runtime.coordinator.data.members[anna["id"]].is_weekly_winner is True
    assert runtime.coordinator.data.members[ben["id"]].is_weekly_winner is False

    user, client = await _client_for_new_user(hass, hass_ws_client, is_admin=False)
    hass.states.async_set("person.anna", "home", {"user_id": user.id})

    await client.send_json_auto_id(
        {
            "type": "family_tasks/reward/claim",
            "reward_group_id": group["id"],
            "detail": "Pizza",
        }
    )
    response = await client.receive_json()

    assert response["success"] is True
    reward = response["result"]
    assert reward["member_id"] == anna["id"]
    assert reward["member_name"] == "Anna"
    assert reward["reward_group_name"] == "Mittagessen auswählen"
    assert reward["detail"] == "Pizza"
    assert reward["fulfilled"] is False

    # A second claim the same week is rejected.
    await client.send_json_auto_id(
        {
            "type": "family_tasks/reward/claim",
            "reward_group_id": group["id"],
            "detail": "Nochmal Pizza",
        }
    )
    second_response = await client.receive_json()
    assert second_response["success"] is False


async def test_non_winner_cannot_claim_a_reward(
    hass, init_integration, hass_ws_client
) -> None:
    runtime = init_integration.runtime_data
    await runtime.members.async_create_item(
        {"name": "Ben", "role": "child", "person_entity_id": "person.ben"}
    )
    group = await runtime.reward_groups.async_create_item({"name": "Mittagessen auswählen"})
    await runtime.coordinator.async_refresh()

    user, client = await _client_for_new_user(hass, hass_ws_client, is_admin=False)
    hass.states.async_set("person.ben", "home", {"user_id": user.id})

    # Nobody has any points yet this week, so nobody is a winner.
    await client.send_json_auto_id(
        {
            "type": "family_tasks/reward/claim",
            "reward_group_id": group["id"],
            "detail": "Pizza",
        }
    )
    response = await client.receive_json()

    assert response["success"] is False
    assert response["error"]["code"] == "unauthorized"


async def test_parent_can_fulfill_reward_but_child_cannot(
    hass, init_integration, hass_ws_client
) -> None:
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item(
        {"name": "Anna", "role": "child", "person_entity_id": "person.anna"}
    )
    timmy = await runtime.members.async_create_item(
        {"name": "Timmy", "role": "child", "person_entity_id": "person.timmy"}
    )
    group = await runtime.reward_groups.async_create_item({"name": "Mittagessen auswählen"})
    reward = await runtime.rewards.async_create_item(
        {
            "member_id": anna["id"],
            "member_name": "Anna",
            "reward_group_id": group["id"],
            "reward_group_name": group["name"],
            "detail": "Pizza",
            "period_key": "2026-07-27",
        }
    )

    # A "child"-linked user - even with an HA admin account - may not mark it
    # fulfilled (same rule as member management).
    child_user, child_client = await _client_for_new_user(
        hass, hass_ws_client, is_admin=True, name="Timmy's account"
    )
    hass.states.async_set("person.timmy", "home", {"user_id": child_user.id})
    await child_client.send_json_auto_id(
        {"type": "family_tasks/reward/update", "reward_id": reward["id"], "fulfilled": True}
    )
    child_response = await child_client.receive_json()
    assert child_response["success"] is False
    assert child_response["error"]["code"] == "unauthorized"
    assert runtime.rewards.data[reward["id"]]["fulfilled"] is False

    # An ordinary admin (parent) account can.
    _, parent_client = await _client_for_new_user(hass, hass_ws_client, is_admin=True)
    await parent_client.send_json_auto_id(
        {"type": "family_tasks/reward/update", "reward_id": reward["id"], "fulfilled": True}
    )
    parent_response = await parent_client.receive_json()
    assert parent_response["success"] is True
    assert runtime.rewards.data[reward["id"]]["fulfilled"] is True


# --- is_weekly_winner tie / nobody-wins cases --------------------------------


async def test_weekly_winner_tie_shares_the_win(hass, init_integration) -> None:
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})
    ben = await runtime.members.async_create_item({"name": "Ben"})
    task_a = await _add_task(runtime, member_ids=[anna["id"]], points=5)
    task_b = await _add_task(runtime, member_ids=[ben["id"]], points=5)
    await runtime.coordinator.async_refresh()

    await runtime.coordinator.async_complete_task(task_a["id"])
    await runtime.coordinator.async_complete_task(task_b["id"])
    await runtime.coordinator.async_refresh()

    assert runtime.coordinator.data.members[anna["id"]].is_weekly_winner is True
    assert runtime.coordinator.data.members[ben["id"]].is_weekly_winner is True


async def test_nobody_wins_with_zero_points(hass, init_integration) -> None:
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})
    await runtime.coordinator.async_refresh()

    assert runtime.coordinator.data.members[anna["id"]].is_weekly_winner is False
