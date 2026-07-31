"""Tests for the v0.8 features that are still current in v0.9:

- A "child" member can create a checklist task for themselves via the
  restricted family_tasks/task/create_own command (same "kind"/"subtasks"
  fields as the admin task schema).

(v0.8's reward-group/weekly-winner-claim system and
MemberSummaryData.is_weekly_winner were replaced in v0.9 by a points-shop
model - see test_v09_features.py for the current reward tests.)
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
