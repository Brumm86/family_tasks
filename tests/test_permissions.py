"""Tests for role-based permission guards:

- A user linked (via person_entity_id -> person.user_id) to a family member
  with role "child" may never create/update/delete family members over the
  websocket API, regardless of their HA admin flag.
- Only such a "child"-linked user may use the non-admin
  family_tasks/task/create_own command, and it always forces points=0 and a
  single-member ([self]) rotation.
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


async def test_admin_user_linked_to_child_member_cannot_create_members(
    hass, init_integration, hass_ws_client
) -> None:
    """Even an admin account is blocked from member CRUD if it's the child's."""
    runtime = init_integration.runtime_data
    await runtime.members.async_create_item(
        {"name": "Timmy", "role": "child", "person_entity_id": "person.timmy"}
    )
    user, client = await _client_for_new_user(hass, hass_ws_client, is_admin=True)
    hass.states.async_set("person.timmy", "home", {"user_id": user.id})

    await client.send_json_auto_id({"type": "family_tasks/member/create", "name": "Sneaky"})
    response = await client.receive_json()

    assert response["success"] is False
    assert response["error"]["code"] == "unauthorized"
    assert "Sneaky" not in [m["name"] for m in runtime.members.data.values()]


async def test_admin_user_linked_to_child_member_cannot_update_or_delete_members(
    hass, init_integration, hass_ws_client
) -> None:
    """The guard also covers update and delete, not just create."""
    runtime = init_integration.runtime_data
    timmy = await runtime.members.async_create_item(
        {"name": "Timmy", "role": "child", "person_entity_id": "person.timmy"}
    )
    other = await runtime.members.async_create_item({"name": "Mom", "role": "parent"})
    user, client = await _client_for_new_user(hass, hass_ws_client, is_admin=True)
    hass.states.async_set("person.timmy", "home", {"user_id": user.id})

    await client.send_json_auto_id(
        {"type": "family_tasks/member/update", "member_id": other["id"], "name": "Renamed"}
    )
    update_response = await client.receive_json()
    assert update_response["success"] is False
    assert update_response["error"]["code"] == "unauthorized"

    await client.send_json_auto_id(
        {"type": "family_tasks/member/delete", "member_id": other["id"]}
    )
    delete_response = await client.receive_json()
    assert delete_response["success"] is False
    assert delete_response["error"]["code"] == "unauthorized"

    assert other["id"] in runtime.members.data
    assert runtime.members.data[other["id"]]["name"] == "Mom"
    assert timmy["id"] in runtime.members.data


async def test_admin_user_not_linked_to_a_child_can_still_manage_members(
    hass, init_integration, hass_ws_client
) -> None:
    """Regression guard: an ordinary admin account keeps working as before."""
    runtime = init_integration.runtime_data
    _, client = await _client_for_new_user(hass, hass_ws_client, is_admin=True)

    await client.send_json_auto_id({"type": "family_tasks/member/create", "name": "Anna"})
    response = await client.receive_json()

    assert response["success"] is True
    assert response["result"]["name"] == "Anna"
    assert "Anna" in [m["name"] for m in runtime.members.data.values()]


async def test_child_can_create_own_task_without_admin_rights(
    hass, init_integration, hass_ws_client
) -> None:
    """A non-admin user linked to a 'child' member can create a task for
    themselves via the restricted create_own command."""
    runtime = init_integration.runtime_data
    timmy = await runtime.members.async_create_item(
        {"name": "Timmy", "role": "child", "person_entity_id": "person.timmy"}
    )
    user, client = await _client_for_new_user(hass, hass_ws_client, is_admin=False)
    hass.states.async_set("person.timmy", "home", {"user_id": user.id})

    await client.send_json_auto_id(
        {
            "type": "family_tasks/task/create_own",
            "name": "Zimmer aufräumen",
            "recurrence": {"type": "daily"},
            "requires_confirmation": False,
        }
    )
    response = await client.receive_json()

    assert response["success"] is True
    task = response["result"]
    assert task["points"] == 0
    assert task["rotation"]["member_ids"] == [timmy["id"]]
    assert task["requires_confirmation"] is False


async def test_non_child_user_cannot_use_create_own_task(
    hass, init_integration, hass_ws_client
) -> None:
    """A user not linked to any 'child' member is rejected by create_own."""
    _, client = await _client_for_new_user(hass, hass_ws_client, is_admin=False)

    await client.send_json_auto_id(
        {
            "type": "family_tasks/task/create_own",
            "name": "Sneaky task",
            "recurrence": {"type": "daily"},
        }
    )
    response = await client.receive_json()

    assert response["success"] is False
    assert response["error"]["code"] == "unauthorized"
