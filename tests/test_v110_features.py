"""Tests for v1.1.0: a child can take back a task it created via Favoriten.

family_tasks/favorite/claim creates a task for the child and submits it as
done, which raises a parent confirmation task. family_tasks/task/withdraw
lets the creator delete that task again without any deduction; the parent
confirmation task is deleted with it.
"""

from __future__ import annotations

from custom_components.family_tasks.const import CONF_TASK_CREATED_BY_MEMBER_ID


async def _client_for_new_user(hass, hass_ws_client, *, person_entity_id: str):
    """Create a plain (non-admin) HA user linked to a person entity, return a ws client."""
    user = await hass.auth.async_create_user(person_entity_id, group_ids=[])
    refresh_token = await hass.auth.async_create_refresh_token(user, client_id="https://example.com")
    access_token = hass.auth.async_create_access_token(refresh_token)
    client = await hass_ws_client(hass, access_token)
    hass.states.async_set(person_entity_id, "home", {"user_id": user.id})
    return client


async def _setup(hass, runtime, hass_ws_client):
    timmy = await runtime.members.async_create_item(
        {"name": "Timmy", "role": "child", "person_entity_id": "person.timmy"}
    )
    lena = await runtime.members.async_create_item(
        {"name": "Lena", "role": "child", "person_entity_id": "person.lena"}
    )
    mom = await runtime.members.async_create_item({"name": "Mom", "role": "parent"})
    favorite = await runtime.favorites.async_create_item({"name": "Spülmaschine", "points": 3})
    timmy_client = await _client_for_new_user(hass, hass_ws_client, person_entity_id="person.timmy")
    lena_client = await _client_for_new_user(hass, hass_ws_client, person_entity_id="person.lena")
    return timmy, lena, mom, favorite, timmy_client, lena_client


async def _claim(client, favorite_id):
    await client.send_json_auto_id({"type": "family_tasks/favorite/claim", "favorite_id": favorite_id})
    response = await client.receive_json()
    assert response["success"] is True
    return response["result"]


def _confirmation_tasks(runtime, task_id):
    return [
        t
        for t in runtime.tasks.data.values()
        if (t.get("confirms") or {}).get("task_id") == task_id
    ]


async def test_claimed_favorite_task_is_tagged_with_its_creator(
    hass, init_integration, hass_ws_client
) -> None:
    runtime = init_integration.runtime_data
    timmy, _lena, _mom, favorite, timmy_client, _ = await _setup(hass, runtime, hass_ws_client)

    task = await _claim(timmy_client, favorite["id"])

    assert runtime.tasks.data[task["id"]][CONF_TASK_CREATED_BY_MEMBER_ID] == timmy["id"]
    assert len(_confirmation_tasks(runtime, task["id"])) == 1


async def test_withdraw_deletes_task_and_confirmation_without_penalty(
    hass, init_integration, hass_ws_client
) -> None:
    runtime = init_integration.runtime_data
    timmy, _lena, _mom, favorite, timmy_client, _ = await _setup(hass, runtime, hass_ws_client)
    task = await _claim(timmy_client, favorite["id"])
    entries_before = list(runtime.coordinator.completions.entries)

    await timmy_client.send_json_auto_id({"type": "family_tasks/task/withdraw", "task_id": task["id"]})
    response = await timmy_client.receive_json()
    await hass.async_block_till_done()

    assert response["success"] is True
    assert task["id"] not in runtime.tasks.data
    assert _confirmation_tasks(runtime, task["id"]) == []
    # No deduction and no credit: nothing was written to the completion log.
    assert runtime.coordinator.completions.entries == entries_before
    assert runtime.coordinator.data.members[timmy["id"]].points_today == 0


async def test_withdraw_rejected_for_another_member(hass, init_integration, hass_ws_client) -> None:
    runtime = init_integration.runtime_data
    _timmy, _lena, _mom, favorite, timmy_client, lena_client = await _setup(
        hass, runtime, hass_ws_client
    )
    task = await _claim(timmy_client, favorite["id"])

    await lena_client.send_json_auto_id({"type": "family_tasks/task/withdraw", "task_id": task["id"]})
    response = await lena_client.receive_json()

    assert response["success"] is False
    assert response["error"]["code"] == "unauthorized"
    assert task["id"] in runtime.tasks.data
    assert len(_confirmation_tasks(runtime, task["id"])) == 1


async def test_withdraw_rejected_for_task_not_created_by_caller(
    hass, init_integration, hass_ws_client
) -> None:
    """A parent-assigned task cannot be deleted by the child it is assigned to."""
    runtime = init_integration.runtime_data
    timmy, _lena, _mom, _favorite, timmy_client, _ = await _setup(hass, runtime, hass_ws_client)
    task = await runtime.tasks.async_create_item(
        {
            "name": "Zimmer aufräumen",
            "points": 5,
            "recurrence": {"type": "daily"},
            "rotation": {"member_ids": [timmy["id"]], "strategy": "round_robin"},
        }
    )

    await timmy_client.send_json_auto_id({"type": "family_tasks/task/withdraw", "task_id": task["id"]})
    response = await timmy_client.receive_json()

    assert response["success"] is False
    assert task["id"] in runtime.tasks.data


async def test_withdraw_rejected_for_confirmation_task(hass, init_integration, hass_ws_client) -> None:
    runtime = init_integration.runtime_data
    _timmy, _lena, _mom, favorite, timmy_client, _ = await _setup(hass, runtime, hass_ws_client)
    task = await _claim(timmy_client, favorite["id"])
    confirmation = _confirmation_tasks(runtime, task["id"])[0]

    await timmy_client.send_json_auto_id(
        {"type": "family_tasks/task/withdraw", "task_id": confirmation["id"]}
    )
    response = await timmy_client.receive_json()

    assert response["success"] is False
    assert confirmation["id"] in runtime.tasks.data
