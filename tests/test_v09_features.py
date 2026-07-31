"""Tests for the v0.9 features:

- The reward catalog (admin-only CRUD, `family_tasks/reward/*`): each item
  has a name and a price in points ("points_cost"). Replaces v0.8's
  parent-defined "reward groups".
- The redeem flow (`family_tasks/reward_redemption/redeem`): any family
  member who participates in the reward system (see
  CONF_MEMBER_REWARDS_OPT_IN / "participates_in_rewards") may redeem any
  catalog reward at any time, provided their current available point balance
  covers its price. The generic "reward_redemption/create" command is always
  rejected - redeeming is the only way to create one. Only a parent (not a
  "child", even with an HA admin account) may mark a redemption "fulfilled".
- MemberSummaryData.points_available: all-time points minus everything a
  member has already redeemed.
- Migration of v0.8 "reward group"/"claimed reward" storage data into the
  v0.9 shapes.
"""

from __future__ import annotations

from homeassistant.auth.const import GROUP_ID_ADMIN


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


# --- reward catalog (admin-only CRUD) ---------------------------------------


async def test_admin_can_manage_reward_catalog(hass, init_integration, hass_ws_client) -> None:
    runtime = init_integration.runtime_data
    _, client = await _client_for_new_user(hass, hass_ws_client, is_admin=True)

    await client.send_json_auto_id(
        {"type": "family_tasks/reward/create", "name": "Filmabend aussuchen", "points_cost": 10}
    )
    response = await client.receive_json()

    assert response["success"] is True
    assert response["result"]["name"] == "Filmabend aussuchen"
    assert response["result"]["points_cost"] == 10
    assert response["result"]["id"] in runtime.rewards.data


async def test_reward_catalog_points_cost_defaults_to_zero(
    hass, init_integration, hass_ws_client
) -> None:
    _, client = await _client_for_new_user(hass, hass_ws_client, is_admin=True)

    await client.send_json_auto_id({"type": "family_tasks/reward/create", "name": "Ausflug"})
    response = await client.receive_json()

    assert response["success"] is True
    assert response["result"]["points_cost"] == 0


async def test_non_admin_cannot_create_reward_catalog(
    hass, init_integration, hass_ws_client
) -> None:
    _, client = await _client_for_new_user(hass, hass_ws_client, is_admin=False)

    await client.send_json_auto_id(
        {"type": "family_tasks/reward/create", "name": "Sneaky reward", "points_cost": 1}
    )
    response = await client.receive_json()

    assert response["success"] is False


# --- redeem flow -------------------------------------------------------------


async def test_generic_reward_redemption_create_is_always_rejected(
    hass, init_integration, hass_ws_client
) -> None:
    """Even an admin cannot create a redemption through the generic command -
    only family_tasks/reward_redemption/redeem may."""
    _, client = await _client_for_new_user(hass, hass_ws_client, is_admin=True)

    await client.send_json_auto_id(
        {
            "type": "family_tasks/reward_redemption/create",
            "member_id": "anyone",
            "member_name": "Anyone",
            "reward_id": "whatever",
            "reward_name": "Whatever",
            "points_cost": 0,
        }
    )
    response = await client.receive_json()

    assert response["success"] is False


async def test_member_can_redeem_affordable_reward(
    hass, init_integration, hass_ws_client
) -> None:
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item(
        {"name": "Anna", "role": "child", "person_entity_id": "person.anna"}
    )
    reward = await runtime.rewards.async_create_item({"name": "Filmabend", "points_cost": 10})
    task = await _add_task(runtime, member_ids=[anna["id"]], points=15)
    await runtime.coordinator.async_refresh()
    await runtime.coordinator.async_complete_task(task["id"])
    await runtime.coordinator.async_refresh()

    assert runtime.coordinator.data.members[anna["id"]].points_available == 15

    user, client = await _client_for_new_user(hass, hass_ws_client, is_admin=False)
    hass.states.async_set("person.anna", "home", {"user_id": user.id})

    await client.send_json_auto_id(
        {"type": "family_tasks/reward_redemption/redeem", "reward_id": reward["id"]}
    )
    response = await client.receive_json()

    assert response["success"] is True
    redemption = response["result"]
    assert redemption["member_id"] == anna["id"]
    assert redemption["member_name"] == "Anna"
    assert redemption["reward_name"] == "Filmabend"
    assert redemption["points_cost"] == 10
    assert redemption["fulfilled"] is False

    await runtime.coordinator.async_refresh()
    # 15 earned - 10 spent = 5 left; points_total itself is untouched.
    assert runtime.coordinator.data.members[anna["id"]].points_available == 5
    assert runtime.coordinator.data.members[anna["id"]].points_total == 15

    # A second redemption the balance can't cover is rejected, and does not
    # create a second entry.
    await client.send_json_auto_id(
        {"type": "family_tasks/reward_redemption/redeem", "reward_id": reward["id"]}
    )
    second_response = await client.receive_json()
    assert second_response["success"] is False
    assert len(runtime.reward_redemptions.data) == 1


async def test_member_cannot_redeem_reward_they_cannot_afford(
    hass, init_integration, hass_ws_client
) -> None:
    runtime = init_integration.runtime_data
    await runtime.members.async_create_item(
        {"name": "Ben", "role": "child", "person_entity_id": "person.ben"}
    )
    reward = await runtime.rewards.async_create_item({"name": "Konsole", "points_cost": 1000})
    await runtime.coordinator.async_refresh()

    user, client = await _client_for_new_user(hass, hass_ws_client, is_admin=False)
    hass.states.async_set("person.ben", "home", {"user_id": user.id})

    await client.send_json_auto_id(
        {"type": "family_tasks/reward_redemption/redeem", "reward_id": reward["id"]}
    )
    response = await client.receive_json()

    assert response["success"] is False
    assert response["error"]["code"] == "invalid_format"
    assert not runtime.reward_redemptions.data


async def test_non_participating_member_cannot_redeem(
    hass, init_integration, hass_ws_client
) -> None:
    """participates_in_rewards=False blocks redemption even with enough points."""
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item(
        {
            "name": "Anna",
            "role": "child",
            "person_entity_id": "person.anna",
            "participates_in_rewards": False,
        }
    )
    reward = await runtime.rewards.async_create_item({"name": "Filmabend", "points_cost": 1})
    task = await _add_task(runtime, member_ids=[anna["id"]], points=50)
    await runtime.coordinator.async_refresh()
    await runtime.coordinator.async_complete_task(task["id"])
    await runtime.coordinator.async_refresh()

    user, client = await _client_for_new_user(hass, hass_ws_client, is_admin=False)
    hass.states.async_set("person.anna", "home", {"user_id": user.id})

    await client.send_json_auto_id(
        {"type": "family_tasks/reward_redemption/redeem", "reward_id": reward["id"]}
    )
    response = await client.receive_json()

    assert response["success"] is False
    assert response["error"]["code"] == "unauthorized"


async def test_member_participates_in_rewards_defaults_true(hass, init_integration) -> None:
    """Existing/newly created members keep showing up unless explicitly opted out."""
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})

    assert anna["participates_in_rewards"] is True


async def test_parent_can_fulfill_redemption_but_child_cannot(
    hass, init_integration, hass_ws_client
) -> None:
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item(
        {"name": "Anna", "role": "child", "person_entity_id": "person.anna"}
    )
    timmy = await runtime.members.async_create_item(
        {"name": "Timmy", "role": "child", "person_entity_id": "person.timmy"}
    )
    reward = await runtime.rewards.async_create_item({"name": "Filmabend", "points_cost": 5})
    redemption = await runtime.reward_redemptions.async_create_item(
        {
            "member_id": anna["id"],
            "member_name": "Anna",
            "reward_id": reward["id"],
            "reward_name": reward["name"],
            "points_cost": 5,
        }
    )

    # A "child"-linked user - even with an HA admin account - may not mark it
    # fulfilled (same rule as member management).
    child_user, child_client = await _client_for_new_user(
        hass, hass_ws_client, is_admin=True, name="Timmy's account"
    )
    hass.states.async_set("person.timmy", "home", {"user_id": child_user.id})
    await child_client.send_json_auto_id(
        {
            "type": "family_tasks/reward_redemption/update",
            "reward_redemption_id": redemption["id"],
            "fulfilled": True,
        }
    )
    child_response = await child_client.receive_json()
    assert child_response["success"] is False
    assert child_response["error"]["code"] == "unauthorized"
    assert runtime.reward_redemptions.data[redemption["id"]]["fulfilled"] is False

    # An ordinary admin (parent) account can.
    _, parent_client = await _client_for_new_user(hass, hass_ws_client, is_admin=True)
    await parent_client.send_json_auto_id(
        {
            "type": "family_tasks/reward_redemption/update",
            "reward_redemption_id": redemption["id"],
            "fulfilled": True,
        }
    )
    parent_response = await parent_client.receive_json()
    assert parent_response["success"] is True
    assert runtime.reward_redemptions.data[redemption["id"]]["fulfilled"] is True


# --- v0.8 -> v0.9 storage migration ------------------------------------------


async def test_legacy_reward_group_is_migrated_to_priced_catalog_item(
    hass, hass_storage, mock_config_entry
) -> None:
    """A v0.8 "reward group" (name/icon only) gets points_cost=0 backfilled."""
    hass_storage["family_tasks.reward_groups"] = {
        "version": 1,
        "minor_version": 1,
        "key": "family_tasks.reward_groups",
        "data": {"items": [{"id": "lunch", "name": "Mittagessen auswählen"}]},
    }

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    runtime = mock_config_entry.runtime_data
    assert runtime.rewards.data["lunch"]["name"] == "Mittagessen auswählen"
    assert runtime.rewards.data["lunch"]["points_cost"] == 0


async def test_legacy_claimed_reward_is_migrated_to_free_redemption(
    hass, hass_storage, mock_config_entry
) -> None:
    """A v0.8 claim (reward_group_id/name + detail, no price) is remapped and
    gets points_cost=0 so it never retroactively reduces anyone's balance."""
    hass_storage["family_tasks.rewards"] = {
        "version": 1,
        "minor_version": 1,
        "key": "family_tasks.rewards",
        "data": {
            "items": [
                {
                    "id": "anna-2026-07-27",
                    "member_id": "anna_id",
                    "member_name": "Anna",
                    "reward_group_id": "lunch",
                    "reward_group_name": "Mittagessen auswählen",
                    "detail": "Pizza",
                    "period_key": "2026-07-27",
                    "fulfilled": False,
                    "created_at": "2026-07-27T10:00:00+00:00",
                }
            ]
        },
    }

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    runtime = mock_config_entry.runtime_data
    migrated = runtime.reward_redemptions.data["anna-2026-07-27"]
    assert migrated["points_cost"] == 0
    assert migrated["reward_id"] == "lunch"
    assert migrated["reward_name"] == "Mittagessen auswählen (Pizza)"
    assert migrated["redeemed_at"] == "2026-07-27T10:00:00+00:00"
    assert "reward_group_id" not in migrated
    assert "period_key" not in migrated
