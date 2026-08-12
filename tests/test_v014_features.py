"""Tests for the v0.14 features:

- Handyzeit reward "invest points" flow (CONF_REWARD_SCREEN_TIME_INVESTABLE):
  a reward flagged this way lets the redeeming member choose how many points
  to spend, and the granted screen time is points_spent *
  CONF_SCREEN_TIME_MINUTES_PER_POINT (see ws_redeem_reward in storage.py).
  Existing rewards that already had a fixed screen_time_minutes are migrated
  to this flag on load (see _async_migrate_screen_time_investable).
- The new "mandatory" task kind (TASK_KIND_MANDATORY, "Pflichtaufgabe"): an
  overdue occurrence pauses the per-member screen_time_grant_active flag
  (MemberSummaryData.screen_time_grant_active / the new binary_sensor.py
  platform) for exactly whoever it's assigned to, resuming automatically once
  it's no longer overdue.
- A new task with an assigned member fires EVENT_TASK_ASSIGNED and, if the
  member has CONF_MEMBER_NOTIFY_SERVICE set, calls that notify.* service (see
  _async_notify_new_task_assignments in __init__.py).
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from homeassistant.util import dt as dt_util

from custom_components.family_tasks.const import (
    CONF_SCREEN_TIME_MINUTES_PER_POINT,
    EVENT_TASK_ASSIGNED,
    TASK_STATUS_OVERDUE,
)


async def _client_for_new_user(hass, hass_ws_client, *, is_admin: bool, name: str = "Test User"):
    from homeassistant.auth.const import GROUP_ID_ADMIN

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
        "rotation": {"member_ids": member_ids, "strategy": "fixed"},
    }
    payload.update(overrides)
    return await runtime.tasks.async_create_item(payload)


# --- Handyzeit "invest points" redemption -----------------------------------


async def test_investable_redeem_derives_minutes_from_default_bonus_factor(
    hass, init_integration, hass_ws_client
) -> None:
    """Default bonus factor is 1 minute per point (DEFAULT_SCREEN_TIME_MINUTES_PER_POINT)."""
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item(
        {"name": "Anna", "role": "child", "person_entity_id": "person.anna"}
    )
    reward = await runtime.rewards.async_create_item(
        {"name": "Handyzeit", "screen_time_investable": True}
    )
    task = await _add_task(runtime, member_ids=[anna["id"]], points=20)
    await runtime.coordinator.async_refresh()
    await runtime.coordinator.async_complete_task(task["id"])
    await runtime.coordinator.async_refresh()

    user, client = await _client_for_new_user(hass, hass_ws_client, is_admin=False)
    hass.states.async_set("person.anna", "home", {"user_id": user.id})

    await client.send_json_auto_id(
        {
            "type": "family_tasks/reward_redemption/redeem",
            "reward_id": reward["id"],
            "points_spent": 12,
        }
    )
    response = await client.receive_json()

    assert response["success"] is True
    assert response["result"]["points_cost"] == 12
    assert response["result"]["points_invested"] == 12
    assert response["result"]["screen_time_minutes"] == 12

    await runtime.coordinator.async_refresh()
    assert runtime.coordinator.data.members[anna["id"]].points_available == 8


async def test_investable_redeem_uses_configured_bonus_factor(
    hass, init_integration, hass_ws_client
) -> None:
    runtime = init_integration.runtime_data
    hass.config_entries.async_update_entry(
        init_integration, options={CONF_SCREEN_TIME_MINUTES_PER_POINT: 3}
    )
    anna = await runtime.members.async_create_item(
        {"name": "Anna", "role": "child", "person_entity_id": "person.anna"}
    )
    reward = await runtime.rewards.async_create_item(
        {"name": "Handyzeit", "screen_time_investable": True}
    )
    task = await _add_task(runtime, member_ids=[anna["id"]], points=20)
    await runtime.coordinator.async_refresh()
    await runtime.coordinator.async_complete_task(task["id"])
    await runtime.coordinator.async_refresh()

    user, client = await _client_for_new_user(hass, hass_ws_client, is_admin=False)
    hass.states.async_set("person.anna", "home", {"user_id": user.id})

    await client.send_json_auto_id(
        {
            "type": "family_tasks/reward_redemption/redeem",
            "reward_id": reward["id"],
            "points_spent": 4,
        }
    )
    response = await client.receive_json()

    assert response["success"] is True
    assert response["result"]["screen_time_minutes"] == 12  # 4 points * 3 min/point


async def test_investable_redeem_requires_points_spent(hass, init_integration, hass_ws_client) -> None:
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item(
        {"name": "Anna", "role": "child", "person_entity_id": "person.anna"}
    )
    reward = await runtime.rewards.async_create_item(
        {"name": "Handyzeit", "screen_time_investable": True}
    )
    task = await _add_task(runtime, member_ids=[anna["id"]], points=20)
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


async def test_investable_redeem_rejected_without_enough_points(
    hass, init_integration, hass_ws_client
) -> None:
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item(
        {"name": "Anna", "role": "child", "person_entity_id": "person.anna"}
    )
    reward = await runtime.rewards.async_create_item(
        {"name": "Handyzeit", "screen_time_investable": True}
    )
    # Anna has 0 points so far.

    user, client = await _client_for_new_user(hass, hass_ws_client, is_admin=False)
    hass.states.async_set("person.anna", "home", {"user_id": user.id})

    await client.send_json_auto_id(
        {
            "type": "family_tasks/reward_redemption/redeem",
            "reward_id": reward["id"],
            "points_spent": 5,
        }
    )
    response = await client.receive_json()

    assert response["success"] is False
    assert not runtime.reward_redemptions.data


async def test_existing_screen_time_reward_is_migrated_to_investable(hass, init_integration) -> None:
    """A pre-v0.14 catalog item (screen_time_minutes set, no investable key
    at all) is switched over to the invest-points flow the next time the
    rewards collection loads - see _async_migrate_screen_time_investable."""
    from custom_components.family_tasks.storage import _async_migrate_screen_time_investable

    runtime = init_integration.runtime_data
    reward = await runtime.rewards.async_create_item(
        {"name": "Alte Handyzeit", "points_cost": 5, "screen_time_minutes": 30}
    )
    # Simulate a pre-v0.14 stored item: drop the key the schema would
    # otherwise have defaulted to False, exactly like data written before
    # this field existed.
    del runtime.rewards.data[reward["id"]]["screen_time_investable"]

    await _async_migrate_screen_time_investable(runtime.rewards)

    assert runtime.rewards.data[reward["id"]]["screen_time_investable"] is True


# --- Mandatory tasks / screen_time_grant_active -----------------------------


async def _refresh_at_local(runtime, local_dt) -> None:
    with (
        patch.object(dt_util, "now", return_value=local_dt),
        patch.object(dt_util, "utcnow", return_value=dt_util.as_utc(local_dt)),
    ):
        await runtime.coordinator.async_refresh()


async def _complete_at_local(runtime, task_id, local_dt) -> None:
    with (
        patch.object(dt_util, "now", return_value=local_dt),
        patch.object(dt_util, "utcnow", return_value=dt_util.as_utc(local_dt)),
    ):
        await runtime.coordinator.async_complete_task(task_id)


async def test_overdue_mandatory_task_pauses_only_the_assigned_member(
    hass, init_integration
) -> None:
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})
    ben = await runtime.members.async_create_item({"name": "Ben"})

    frozen_local = dt_util.now().replace(hour=12, minute=0, second=0, microsecond=0)
    due_time_str = (frozen_local - timedelta(hours=2)).strftime("%H:%M")

    task = await _add_task(
        runtime,
        member_ids=[anna["id"]],
        kind="mandatory",
        due_time=due_time_str,
        overdue_after_minutes=30,
    )

    await _refresh_at_local(runtime, frozen_local)

    assert runtime.coordinator.data.tasks[task["id"]].status == TASK_STATUS_OVERDUE
    assert runtime.coordinator.data.members[anna["id"]].screen_time_grant_active is False
    # Ben has no mandatory task at all - unaffected.
    assert runtime.coordinator.data.members[ben["id"]].screen_time_grant_active is True


async def test_completing_the_mandatory_task_resumes_the_grant(hass, init_integration) -> None:
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})

    frozen_local = dt_util.now().replace(hour=12, minute=0, second=0, microsecond=0)
    due_time_str = (frozen_local - timedelta(hours=2)).strftime("%H:%M")
    task = await _add_task(
        runtime,
        member_ids=[anna["id"]],
        kind="mandatory",
        due_time=due_time_str,
        overdue_after_minutes=30,
    )
    await _refresh_at_local(runtime, frozen_local)
    assert runtime.coordinator.data.members[anna["id"]].screen_time_grant_active is False

    await _complete_at_local(runtime, task["id"], frozen_local)

    assert runtime.coordinator.data.members[anna["id"]].screen_time_grant_active is True


async def test_pending_not_yet_overdue_mandatory_task_does_not_pause(hass, init_integration) -> None:
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})
    task = await _add_task(runtime, member_ids=[anna["id"]], kind="mandatory")
    await runtime.coordinator.async_refresh()

    assert runtime.coordinator.data.tasks[task["id"]].status != TASK_STATUS_OVERDUE
    assert runtime.coordinator.data.members[anna["id"]].screen_time_grant_active is True


# --- New-task notifications -------------------------------------------------


async def test_new_task_assignment_fires_event_and_calls_notify_service(hass, init_integration) -> None:
    from pytest_homeassistant_custom_component.common import async_capture_events, async_mock_service

    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item(
        {"name": "Anna", "notify_service": "test_target"}
    )
    notify_calls = async_mock_service(hass, "notify", "test_target")
    events = async_capture_events(hass, EVENT_TASK_ASSIGNED)

    task = await _add_task(runtime, member_ids=[anna["id"]])
    await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0].data["member_id"] == anna["id"]
    assert events[0].data["task_id"] == task["id"]

    assert len(notify_calls) == 1
    assert "Testaufgabe" in notify_calls[0].data["message"]


async def test_new_task_without_notify_service_still_fires_event(hass, init_integration) -> None:
    from pytest_homeassistant_custom_component.common import async_capture_events

    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})
    events = async_capture_events(hass, EVENT_TASK_ASSIGNED)

    await _add_task(runtime, member_ids=[anna["id"]])
    await hass.async_block_till_done()

    assert len(events) == 1
