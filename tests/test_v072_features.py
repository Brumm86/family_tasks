"""Tests for v0.72.0: administrative services (services.py).

Everything the card can do over the websocket API is also available as a
service: CRUD for tasks, members, Favoriten, rewards and battery overrides,
awarding points/coins, extending a deadline, reading and changing the
household options. The services are admin-only, and a user linked to a
"child" member is rejected even if that HA user is an administrator.

Same init_integration style as the other test files (needs a real HA test
environment to run end to end).
"""

from __future__ import annotations

import pytest

from homeassistant.auth.const import GROUP_ID_ADMIN
from homeassistant.core import Context
from homeassistant.exceptions import ServiceValidationError, Unauthorized

from custom_components.family_tasks.const import (
    CONF_COIN_THRESHOLD_1_POINTS,
    CONF_SCREEN_TIME_MALUS_START_DATE,
    CONF_WEEKLY_PROGRESS_GOAL_POINTS,
    DOMAIN,
)

TASK = {
    "name": "Paper recycling",
    "points": 5,
    "recurrence": {"type": "weekly", "weekdays": [2]},
    "rotation": {"member_ids": [], "strategy": "round_robin"},
}


async def _call(hass, service: str, data: dict, *, context: Context | None = None) -> dict:
    return await hass.services.async_call(
        DOMAIN, service, data, blocking=True, return_response=True, context=context
    )


async def _context_for_new_user(hass, *, is_admin: bool) -> tuple:
    # The first regular user of an auth store becomes its owner (and thus an
    # admin); create a throwaway one so "Test User" is an ordinary user.
    if not any(not u.system_generated for u in await hass.auth.async_get_users()):
        await hass.auth.async_create_user("Owner", group_ids=[GROUP_ID_ADMIN])
    group_ids = [GROUP_ID_ADMIN] if is_admin else []
    user = await hass.auth.async_create_user("Test User", group_ids=group_ids)
    return user, Context(user_id=user.id)


# --- CRUD ---------------------------------------------------------------------


async def test_task_crud_round_trip(hass, init_integration) -> None:
    created = await _call(hass, "create_task", {"task": TASK})
    task_id = created["id"]
    assert created["name"] == "Paper recycling"
    assert task_id in init_integration.runtime_data.tasks.data

    listed = await _call(hass, "list_tasks", {})
    assert [t["id"] for t in listed["tasks"]] == [task_id]
    assert listed["tasks"][0]["current"]["status"]

    updated = await _call(hass, "update_task", {"task_id": task_id, "changes": {"points": 8}})
    assert updated["points"] == 8
    assert updated["name"] == "Paper recycling"

    deleted = await _call(hass, "delete_task", {"task_id": task_id})
    assert deleted == {"deleted": task_id}
    assert task_id not in init_integration.runtime_data.tasks.data


async def test_list_tasks_without_status(hass, init_integration) -> None:
    await _call(hass, "create_task", {"task": TASK})
    listed = await _call(hass, "list_tasks", {"include_status": False})
    assert "current" not in listed["tasks"][0]


async def test_create_task_with_invalid_payload_is_rejected(hass, init_integration) -> None:
    with pytest.raises(ServiceValidationError):
        await _call(hass, "create_task", {"task": {"name": "No recurrence"}})
    assert not init_integration.runtime_data.tasks.data


async def test_update_unknown_item_is_rejected(hass, init_integration) -> None:
    with pytest.raises(ServiceValidationError):
        await _call(hass, "update_task", {"task_id": "nope", "changes": {"points": 1}})
    with pytest.raises(ServiceValidationError):
        await _call(hass, "delete_member", {"member_id": "nope"})


async def test_member_favorite_reward_and_battery_override_crud(hass, init_integration) -> None:
    member = await _call(hass, "create_member", {"member": {"name": "Anna", "role": "child"}})
    assert member["role"] == "child"
    members = await _call(hass, "list_members", {})
    assert members["members"][0]["current"]["points_total"] == 0

    favorite = await _call(hass, "create_favorite", {"favorite": {"name": "Dishes", "points": 3}})
    favorites = await _call(hass, "list_favorites", {})
    assert [f["id"] for f in favorites["favorites"]] == [favorite["id"]]
    await _call(hass, "update_favorite", {"favorite_id": favorite["id"], "changes": {"points": 4}})
    assert init_integration.runtime_data.favorites.data[favorite["id"]]["points"] == 4

    reward = await _call(hass, "create_reward", {"reward": {"name": "Movie", "coin_cost": 10}})
    rewards = await _call(hass, "list_rewards", {})
    assert [r["id"] for r in rewards["rewards"]] == [reward["id"]]

    override = await _call(
        hass,
        "create_battery_override",
        {"battery_override": {"entity_id": "sensor.example_battery", "threshold": 15}},
    )
    await _call(
        hass,
        "update_battery_override",
        {"override_id": override["id"], "changes": {"threshold": None}},
    )
    assert "threshold" not in init_integration.runtime_data.battery_overrides.data[
        override["id"]
    ] or init_integration.runtime_data.battery_overrides.data[override["id"]]["threshold"] is None
    await _call(hass, "delete_battery_override", {"override_id": override["id"]})
    assert not (await _call(hass, "list_battery_overrides", {}))["battery_overrides"]

    await _call(hass, "delete_reward", {"reward_id": reward["id"]})
    await _call(hass, "delete_favorite", {"favorite_id": favorite["id"]})
    await _call(hass, "delete_member", {"member_id": member["id"]})
    assert not init_integration.runtime_data.members.data


# --- Points, coins, deadlines, Favoriten ---------------------------------------


async def test_award_points_and_coins(hass, init_integration) -> None:
    member = await _call(hass, "create_member", {"member": {"name": "Anna"}})

    entry = await _call(hass, "award_points", {"member_id": member["id"], "points": 7, "note": "Bonus"})
    assert entry["points_awarded"] == 7
    summary = (await _call(hass, "list_members", {}))["members"][0]["current"]
    assert summary["points_week"] == 7

    await _call(hass, "award_coins", {"member_id": member["id"], "coins": 5})
    summary = (await _call(hass, "list_members", {}))["members"][0]["current"]
    assert summary["coins_available"] == 5

    # A coin deduction is limited to the balance, like in the card.
    entry = await _call(hass, "award_coins", {"member_id": member["id"], "coins": -50})
    assert entry["amount"] == -5

    with pytest.raises(ServiceValidationError):
        await _call(hass, "award_points", {"member_id": member["id"], "points": 0})
    with pytest.raises(ServiceValidationError):
        await _call(hass, "award_coins", {"member_id": member["id"], "coins": -1})
    with pytest.raises(ServiceValidationError):
        await _call(hass, "award_points", {"member_id": "nope", "points": 1})


async def test_instantiate_favorite_creates_a_one_time_task(hass, init_integration) -> None:
    member = await _call(hass, "create_member", {"member": {"name": "Anna"}})
    favorite = await _call(hass, "create_favorite", {"favorite": {"name": "Dishes", "points": 3}})

    task = await _call(
        hass,
        "instantiate_favorite",
        {"favorite_id": favorite["id"], "member_ids": [member["id"]]},
    )
    assert task["name"] == "Dishes"
    assert task["recurrence"]["type"] == "once"
    assert task["rotation"]["member_ids"] == [member["id"]]
    assert favorite["id"] in init_integration.runtime_data.favorites.data

    with pytest.raises(ServiceValidationError):
        await _call(hass, "instantiate_favorite", {"favorite_id": "nope"})


async def test_extend_task_deadline_for_task_that_is_not_due(hass, init_integration) -> None:
    with pytest.raises(ServiceValidationError):
        await _call(hass, "extend_task_deadline", {"task_id": "nope", "minutes": 30})


async def test_list_and_fulfill_reward_redemptions(hass, init_integration) -> None:
    runtime = init_integration.runtime_data
    redemption = await runtime.reward_redemptions.async_create_item(
        {
            "member_id": "m1",
            "member_name": "Anna",
            "reward_id": "r1",
            "reward_name": "Movie",
            "coin_cost": 10,
        }
    )
    open_only = await _call(hass, "list_reward_redemptions", {"only_open": True})
    assert [r["id"] for r in open_only["reward_redemptions"]] == [redemption["id"]]

    done = await _call(hass, "fulfill_reward_redemption", {"redemption_id": redemption["id"]})
    assert done["fulfilled"] is True
    open_only = await _call(hass, "list_reward_redemptions", {"only_open": True})
    assert open_only["reward_redemptions"] == []


# --- Settings -----------------------------------------------------------------


async def test_update_settings_merges_and_resets(hass, init_integration) -> None:
    result = await _call(
        hass,
        "update_settings",
        {
            "settings": {
                CONF_WEEKLY_PROGRESS_GOAL_POINTS: 100,
                CONF_COIN_THRESHOLD_1_POINTS: 150,
                CONF_SCREEN_TIME_MALUS_START_DATE: "2026-11-02",
            }
        },
    )
    options = init_integration.options
    assert result["options"][CONF_WEEKLY_PROGRESS_GOAL_POINTS] == 100
    assert options[CONF_COIN_THRESHOLD_1_POINTS] == 150
    # Dates are stored as ISO strings, like the options flow does.
    assert options[CONF_SCREEN_TIME_MALUS_START_DATE] == "2026-11-02"

    # A second call only touches what it names; null resets an option.
    await _call(hass, "update_settings", {"settings": {CONF_COIN_THRESHOLD_1_POINTS: None}})
    assert CONF_COIN_THRESHOLD_1_POINTS not in init_integration.options
    assert init_integration.options[CONF_WEEKLY_PROGRESS_GOAL_POINTS] == 100

    settings = await _call(hass, "get_settings", {})
    assert settings["options"][CONF_WEEKLY_PROGRESS_GOAL_POINTS] == 100
    assert settings["vacation_mode_active"] in (True, False)
    assert len(settings["effective_thresholds"]["malus_points"]) == 4
    assert len(settings["effective_thresholds"]["coin_points"]) == 2


async def test_update_settings_rejects_unordered_thresholds_and_unknown_keys(
    hass, init_integration
) -> None:
    with pytest.raises(ServiceValidationError):
        await _call(
            hass,
            "update_settings",
            {"settings": {CONF_WEEKLY_PROGRESS_GOAL_POINTS: 100, CONF_COIN_THRESHOLD_1_POINTS: 50}},
        )
    assert CONF_WEEKLY_PROGRESS_GOAL_POINTS not in init_integration.options

    with pytest.raises(Exception):  # vol.Invalid from the service schema
        await _call(hass, "update_settings", {"settings": {"no_such_option": 1}})


# --- Permissions --------------------------------------------------------------


async def test_non_admin_user_is_rejected(hass, init_integration) -> None:
    _, context = await _context_for_new_user(hass, is_admin=False)
    with pytest.raises(Unauthorized):
        await _call(hass, "create_task", {"task": TASK}, context=context)
    with pytest.raises(Unauthorized):
        await _call(hass, "list_tasks", {}, context=context)
    assert not init_integration.runtime_data.tasks.data


async def test_admin_user_linked_to_child_member_is_rejected(hass, init_integration) -> None:
    runtime = init_integration.runtime_data
    await runtime.members.async_create_item(
        {"name": "Timmy", "role": "child", "person_entity_id": "person.timmy"}
    )
    user, context = await _context_for_new_user(hass, is_admin=True)
    hass.states.async_set("person.timmy", "home", {"user_id": user.id})

    with pytest.raises(Unauthorized):
        await _call(hass, "create_task", {"task": TASK}, context=context)
    with pytest.raises(Unauthorized):
        await _call(hass, "award_points", {"member_id": "x", "points": 5}, context=context)
    assert not runtime.tasks.data


async def test_ordinary_admin_user_and_user_less_calls_are_allowed(hass, init_integration) -> None:
    _, context = await _context_for_new_user(hass, is_admin=True)
    created = await _call(hass, "create_task", {"task": TASK}, context=context)
    assert created["id"] in init_integration.runtime_data.tasks.data

    # No user at all (automation / script) works too, as for any other service.
    created = await _call(hass, "create_task", {"task": {**TASK, "name": "Second"}})
    assert created["name"] == "Second"
