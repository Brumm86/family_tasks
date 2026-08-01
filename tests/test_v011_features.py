"""Tests for the v0.11 features:

- Reward catalog items can carry an optional "screen_time_minutes" (see
  CONF_REWARD_SCREEN_TIME_MINUTES in const.py) - purely informational to the
  integration itself, editable via `family_tasks/reward/create|update` like
  any other reward field, and clearable again via an explicit `null` on
  update (same "clear via null" pattern as
  BatteryOverrideStorageCollection's "threshold").
- Every successful redemption (`family_tasks/reward_redemption/redeem`) fires
  a new `family_tasks_reward_redeemed` event on the event bus (see
  EVENT_REWARD_REDEEMED in const.py), carrying member_id/member_name/
  reward_id/reward_name/points_cost/screen_time_minutes - this is the
  integration's extension point for a household automation to react
  immediately (e.g. adding Google Family Link screen time for the redeeming
  child), instead of the integration calling a specific automation entity_id
  directly. The event fires for every redemption, not just screen-time ones;
  screen_time_minutes is simply None when the reward didn't set one.
- The redemption record itself denormalizes screen_time_minutes (like it
  already did for reward_name/points_cost) so history stays meaningful even
  if the catalog item's value later changes.
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


# --- reward catalog: screen_time_minutes ------------------------------------


async def test_reward_can_set_screen_time_minutes(hass, init_integration, hass_ws_client) -> None:
    _, client = await _client_for_new_user(hass, hass_ws_client, is_admin=True)

    await client.send_json_auto_id(
        {
            "type": "family_tasks/reward/create",
            "name": "Extra Bildschirmzeit",
            "points_cost": 5,
            "screen_time_minutes": 30,
        }
    )
    response = await client.receive_json()

    assert response["success"] is True
    assert response["result"]["screen_time_minutes"] == 30


async def test_reward_screen_time_minutes_absent_by_default(
    hass, init_integration, hass_ws_client
) -> None:
    _, client = await _client_for_new_user(hass, hass_ws_client, is_admin=True)

    await client.send_json_auto_id(
        {"type": "family_tasks/reward/create", "name": "Filmabend", "points_cost": 5}
    )
    response = await client.receive_json()

    assert response["success"] is True
    assert "screen_time_minutes" not in response["result"]


async def test_reward_rejects_zero_or_negative_screen_time_minutes(
    hass, init_integration, hass_ws_client
) -> None:
    _, client = await _client_for_new_user(hass, hass_ws_client, is_admin=True)

    await client.send_json_auto_id(
        {
            "type": "family_tasks/reward/create",
            "name": "Ungültig",
            "screen_time_minutes": 0,
        }
    )
    response = await client.receive_json()

    assert response["success"] is False


async def test_reward_update_can_clear_screen_time_minutes(
    hass, init_integration, hass_ws_client
) -> None:
    runtime = init_integration.runtime_data
    reward = await runtime.rewards.async_create_item(
        {"name": "Extra Bildschirmzeit", "points_cost": 5, "screen_time_minutes": 30}
    )

    _, client = await _client_for_new_user(hass, hass_ws_client, is_admin=True)
    await client.send_json_auto_id(
        {
            "type": "family_tasks/reward/update",
            "reward_id": reward["id"],
            "screen_time_minutes": None,
        }
    )
    response = await client.receive_json()

    assert response["success"] is True
    assert "screen_time_minutes" not in runtime.rewards.data[reward["id"]]


# --- family_tasks_reward_redeemed event -------------------------------------


async def test_redeeming_a_screen_time_reward_fires_event_with_minutes(
    hass, init_integration, hass_ws_client
) -> None:
    from pytest_homeassistant_custom_component.common import async_capture_events

    from custom_components.family_tasks.const import EVENT_REWARD_REDEEMED

    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item(
        {"name": "Anna", "role": "child", "person_entity_id": "person.anna"}
    )
    reward = await runtime.rewards.async_create_item(
        {"name": "Extra Bildschirmzeit", "points_cost": 5, "screen_time_minutes": 20}
    )
    task = await _add_task(runtime, member_ids=[anna["id"]], points=10)
    await runtime.coordinator.async_refresh()
    await runtime.coordinator.async_complete_task(task["id"])
    await runtime.coordinator.async_refresh()

    user, client = await _client_for_new_user(hass, hass_ws_client, is_admin=False)
    hass.states.async_set("person.anna", "home", {"user_id": user.id})

    events = async_capture_events(hass, EVENT_REWARD_REDEEMED)

    await client.send_json_auto_id(
        {"type": "family_tasks/reward_redemption/redeem", "reward_id": reward["id"]}
    )
    response = await client.receive_json()
    await hass.async_block_till_done()

    assert response["success"] is True
    assert len(events) == 1
    data = events[0].data
    assert data["member_id"] == anna["id"]
    assert data["member_name"] == "Anna"
    assert data["reward_id"] == reward["id"]
    assert data["reward_name"] == "Extra Bildschirmzeit"
    assert data["points_cost"] == 5
    assert data["screen_time_minutes"] == 20

    # Denormalized onto the redemption record itself too, like reward_name.
    redemption_id = response["result"]["id"]
    assert runtime.reward_redemptions.data[redemption_id]["screen_time_minutes"] == 20


async def test_redeeming_a_non_screen_time_reward_still_fires_event(
    hass, init_integration, hass_ws_client
) -> None:
    """The event is generic - it fires for every redemption, with
    screen_time_minutes simply None when the reward never set one, and the
    redemption record doesn't carry the key at all (matches how a reward
    without the field behaves)."""
    from pytest_homeassistant_custom_component.common import async_capture_events

    from custom_components.family_tasks.const import EVENT_REWARD_REDEEMED

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

    events = async_capture_events(hass, EVENT_REWARD_REDEEMED)

    await client.send_json_auto_id(
        {"type": "family_tasks/reward_redemption/redeem", "reward_id": reward["id"]}
    )
    response = await client.receive_json()
    await hass.async_block_till_done()

    assert response["success"] is True
    assert len(events) == 1
    assert events[0].data["screen_time_minutes"] is None

    redemption_id = response["result"]["id"]
    assert "screen_time_minutes" not in runtime.reward_redemptions.data[redemption_id]


async def test_no_event_fired_when_redemption_is_rejected(
    hass, init_integration, hass_ws_client
) -> None:
    """An unaffordable redemption is rejected before the point where the
    event would fire - no event, no redemption entry."""
    from pytest_homeassistant_custom_component.common import async_capture_events

    from custom_components.family_tasks.const import EVENT_REWARD_REDEEMED

    runtime = init_integration.runtime_data
    await runtime.members.async_create_item(
        {"name": "Ben", "role": "child", "person_entity_id": "person.ben"}
    )
    reward = await runtime.rewards.async_create_item({"name": "Konsole", "points_cost": 1000})
    await runtime.coordinator.async_refresh()

    user, client = await _client_for_new_user(hass, hass_ws_client, is_admin=False)
    hass.states.async_set("person.ben", "home", {"user_id": user.id})

    events = async_capture_events(hass, EVENT_REWARD_REDEEMED)

    await client.send_json_auto_id(
        {"type": "family_tasks/reward_redemption/redeem", "reward_id": reward["id"]}
    )
    response = await client.receive_json()
    await hass.async_block_till_done()

    assert response["success"] is False
    assert not events
