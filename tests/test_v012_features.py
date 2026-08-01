"""Tests for the v0.12 features:

- Reward catalog items can carry an optional "auto_fulfill" flag (see
  CONF_REWARD_AUTO_FULFILL in const.py) - off by default. A redemption of a
  reward with this flag set is created already "fulfilled": true instead of
  waiting for a parent to mark it so by hand via
  `family_tasks/reward_redemption/update` (mirrors how CONF_REWARD_SCREEN_TIME_MINUTES
  was added in v0.11 - plain admin-editable field via `family_tasks/reward/create|update`).

Note: the other v0.12 changes (checklist sub-item sort order, the reward
editing dialog, the "Belohnungstyp" form field, and hiding fulfilled
redemptions by default) live entirely in the Lovelace cards
(family-tasks-card.js / family-tasks-leaderboard-card.js) - this repo has no
JS test harness, so those are covered by manual/browser verification only,
not here.
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


# --- reward catalog: auto_fulfill -------------------------------------------


async def test_reward_auto_fulfill_defaults_to_false(hass, init_integration, hass_ws_client) -> None:
    _, client = await _client_for_new_user(hass, hass_ws_client, is_admin=True)

    await client.send_json_auto_id(
        {"type": "family_tasks/reward/create", "name": "Filmabend", "points_cost": 5}
    )
    response = await client.receive_json()

    assert response["success"] is True
    assert response["result"]["auto_fulfill"] is False


async def test_reward_can_set_auto_fulfill(hass, init_integration, hass_ws_client) -> None:
    _, client = await _client_for_new_user(hass, hass_ws_client, is_admin=True)

    await client.send_json_auto_id(
        {
            "type": "family_tasks/reward/create",
            "name": "Extra Bildschirmzeit",
            "points_cost": 5,
            "screen_time_minutes": 30,
            "auto_fulfill": True,
        }
    )
    response = await client.receive_json()

    assert response["success"] is True
    assert response["result"]["auto_fulfill"] is True


async def test_reward_update_can_toggle_auto_fulfill(hass, init_integration, hass_ws_client) -> None:
    runtime = init_integration.runtime_data
    reward = await runtime.rewards.async_create_item({"name": "Filmabend", "points_cost": 5})
    assert runtime.rewards.data[reward["id"]]["auto_fulfill"] is False

    _, client = await _client_for_new_user(hass, hass_ws_client, is_admin=True)
    await client.send_json_auto_id(
        {
            "type": "family_tasks/reward/update",
            "reward_id": reward["id"],
            "auto_fulfill": True,
        }
    )
    response = await client.receive_json()

    assert response["success"] is True
    assert runtime.rewards.data[reward["id"]]["auto_fulfill"] is True


# --- redemption "fulfilled" reflects auto_fulfill ---------------------------


async def test_redeeming_an_auto_fulfill_reward_creates_fulfilled_redemption(
    hass, init_integration, hass_ws_client
) -> None:
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item(
        {"name": "Anna", "role": "child", "person_entity_id": "person.anna"}
    )
    reward = await runtime.rewards.async_create_item(
        {
            "name": "Extra Bildschirmzeit",
            "points_cost": 5,
            "screen_time_minutes": 20,
            "auto_fulfill": True,
        }
    )
    task = await _add_task(runtime, member_ids=[anna["id"]], points=10)
    await runtime.coordinator.async_refresh()
    await runtime.coordinator.async_complete_task(task["id"])
    await runtime.coordinator.async_refresh()

    user, client = await _client_for_new_user(hass, hass_ws_client, is_admin=False)
    hass.states.async_set("person.anna", "home", {"user_id": user.id})

    await client.send_json_auto_id(
        {"type": "family_tasks/reward_redemption/redeem", "reward_id": reward["id"]}
    )
    response = await client.receive_json()

    assert response["success"] is True
    assert response["result"]["fulfilled"] is True
    redemption_id = response["result"]["id"]
    assert runtime.reward_redemptions.data[redemption_id]["fulfilled"] is True


async def test_redeeming_a_non_auto_fulfill_reward_stays_unfulfilled(
    hass, init_integration, hass_ws_client
) -> None:
    """Default behaviour (unchanged from v0.9): a redemption starts out
    unfulfilled, and a parent has to mark it "erledigt" by hand via
    `family_tasks/reward_redemption/update`."""
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item(
        {"name": "Anna", "role": "child", "person_entity_id": "person.anna"}
    )
    reward = await runtime.rewards.async_create_item({"name": "Filmabend", "points_cost": 5})
    task = await _add_task(runtime, member_ids=[anna["id"]], points=10)
    await runtime.coordinator.async_refresh()
    await runtime.coordinator.async_complete_task(task["id"])
    await runtime.coordinator.async_refresh()

    user, client = await _client_for_new_user(hass, hass_ws_client, is_admin=False)
    hass.states.async_set("person.anna", "home", {"user_id": user.id})

    await client.send_json_auto_id(
        {"type": "family_tasks/reward_redemption/redeem", "reward_id": reward["id"]}
    )
    response = await client.receive_json()

    assert response["success"] is True
    assert response["result"]["fulfilled"] is False
