"""Tests for v0.71.0.

* Points can never drop below 0 (deductions are limited to the current weekly
  points; every sum over the completion log is floored at 0).
* Points above the second coin threshold do not count for the current week
  but are carried over to the next one (CARRYOVER_TASK_ID entry dated at the
  start of that week); the pending carry-over is exposed on the points sensor
  and the Wochensieger-Bonus is judged on what was actually earned.
* Parents can give/deduct coins manually (``family_tasks/coins/award``); the
  coin balance never drops below 0.

Same init_integration/hass_ws_client style as the other test files (needs a
real HA test environment to run end to end).
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from homeassistant.auth.const import GROUP_ID_ADMIN
from homeassistant.util import dt as dt_util

from custom_components.family_tasks.const import (
    CARRYOVER_TASK_ID,
    COIN_REASON_MANUAL,
    CONF_COIN_THRESHOLD_1_POINTS,
    CONF_COIN_THRESHOLD_2_POINTS,
    CONF_WEEKLY_PROGRESS_GOAL_POINTS,
    MANUAL_POINTS_TASK_ID,
)
from custom_components.family_tasks.storage import week_bounds

GOAL_OPTIONS = {
    CONF_WEEKLY_PROGRESS_GOAL_POINTS: 10,
    CONF_COIN_THRESHOLD_1_POINTS: 15,
    CONF_COIN_THRESHOLD_2_POINTS: 20,
}


async def _add(runtime, member_id: str, points: int, *, task_name: str = "Test") -> dict:
    return await runtime.coordinator.completions.async_add_entry(
        task_id=MANUAL_POINTS_TASK_ID,
        period_key="test",
        member_id=member_id,
        points_awarded=points,
        task_name=task_name,
    )


def _set_goal_options(hass, entry) -> None:
    hass.config_entries.async_update_entry(entry, options={**entry.options, **GOAL_OPTIONS})


async def _client_for_new_user(hass, hass_ws_client, *, is_admin: bool):
    group_ids = [GROUP_ID_ADMIN] if is_admin else []
    user = await hass.auth.async_create_user("Test User", group_ids=group_ids)
    refresh_token = await hass.auth.async_create_refresh_token(user, client_id="https://example.com")
    access_token = hass.auth.async_create_access_token(refresh_token)
    return user, await hass_ws_client(hass, access_token)


# --- Points never negative ---------------------------------------------------


async def test_deduction_without_points_stays_at_zero(hass, init_integration) -> None:
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})

    entry = await _add(runtime, anna["id"], -5)
    assert entry["points_awarded"] == 0
    assert entry["points_requested"] == -5

    await runtime.coordinator.async_refresh()
    member = runtime.coordinator.data.members[anna["id"]]
    assert (member.points_today, member.points_week, member.points_month, member.points_total) == (0, 0, 0, 0)


async def test_deduction_is_limited_to_the_weekly_points(hass, init_integration) -> None:
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})
    await _add(runtime, anna["id"], 4)

    entry = await _add(runtime, anna["id"], -10)
    assert entry["points_awarded"] == -4

    await runtime.coordinator.async_refresh()
    assert runtime.coordinator.data.members[anna["id"]].points_week == 0

    # No hidden debt: the next earned points count in full.
    await _add(runtime, anna["id"], 3)
    await runtime.coordinator.async_refresh()
    assert runtime.coordinator.data.members[anna["id"]].points_week == 3


async def test_manual_deduction_over_websocket_never_goes_negative(
    hass, init_integration, hass_ws_client
) -> None:
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})
    await _add(runtime, anna["id"], 2)

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "family_tasks/points/award", "member_id": anna["id"], "points": -50}
    )
    response = await client.receive_json()
    assert response["success"] is True
    assert response["result"]["points_awarded"] == -2

    await runtime.coordinator.async_refresh()
    assert runtime.coordinator.data.members[anna["id"]].points_total == 0


# --- Cap at the second coin threshold + carry-over ---------------------------


async def test_points_above_second_coin_threshold_are_carried_over(hass, init_integration) -> None:
    runtime = init_integration.runtime_data
    _set_goal_options(hass, init_integration)
    anna = await runtime.members.async_create_item({"name": "Anna"})

    await _add(runtime, anna["id"], 15)
    entry = await _add(runtime, anna["id"], 10)
    assert entry["points_awarded"] == 5
    assert entry["overflow_points"] == 5

    carry = [e for e in runtime.coordinator.completions.entries if e["task_id"] == CARRYOVER_TASK_ID]
    assert len(carry) == 1
    assert carry[0]["points_awarded"] == 5
    assert dt_util.parse_datetime(carry[0]["completed_at"]) == week_bounds(dt_util.now())[1]

    await runtime.coordinator.async_refresh()
    member = runtime.coordinator.data.members[anna["id"]]
    assert member.points_week == 20  # capped at coin threshold 2
    assert member.points_total == 20  # the carry-over is not effective yet
    assert member.points_carryover == 5
    assert member.points_week_earned == 25

    # Already at the cap: everything further goes to next week.
    entry = await _add(runtime, anna["id"], 3)
    assert entry["points_awarded"] == 0
    assert entry["overflow_points"] == 3
    await runtime.coordinator.async_refresh()
    assert runtime.coordinator.data.members[anna["id"]].points_carryover == 8


async def test_no_cap_without_weekly_goal(hass, init_integration) -> None:
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})
    entry = await _add(runtime, anna["id"], 500)
    assert entry["points_awarded"] == 500
    assert "overflow_points" not in entry


async def test_points_sensor_exposes_carryover(hass, init_integration) -> None:
    runtime = init_integration.runtime_data
    _set_goal_options(hass, init_integration)
    anna = await runtime.members.async_create_item({"name": "Anna"})
    await _add(runtime, anna["id"], 27)
    await runtime.coordinator.async_refresh()
    await hass.async_block_till_done()

    sensors = [
        s
        for s in hass.states.async_all("sensor")
        if s.attributes.get("member_id") == anna["id"] and "points_week" in s.attributes
    ]
    assert sensors
    assert sensors[0].attributes["points_week"] == 20
    assert sensors[0].attributes["points_carryover"] == 7
    assert sensors[0].attributes["points_week_earned"] == 27


async def test_carryover_counts_for_the_next_week(hass, init_integration) -> None:
    runtime = init_integration.runtime_data
    _set_goal_options(hass, init_integration)
    anna = await runtime.members.async_create_item({"name": "Anna"})
    await _add(runtime, anna["id"], 26)

    next_week_start = week_bounds(dt_util.now())[1]
    moment = next_week_start + timedelta(hours=1)
    with (
        patch.object(dt_util, "now", return_value=dt_util.as_local(moment)),
        patch.object(dt_util, "utcnow", return_value=moment),
    ):
        await runtime.coordinator.async_refresh()
        member = runtime.coordinator.data.members[anna["id"]]
        assert member.points_week == 6  # the carried-over points start the new week
        assert member.points_carryover == 0
        assert member.last_week_points == 20


async def test_earned_between_ignores_the_cap(hass, init_integration) -> None:
    """Wochensieger judging: carried-in points don't count, passed-on overflow does."""
    runtime = init_integration.runtime_data
    _set_goal_options(hass, init_integration)
    anna = await runtime.members.async_create_item({"name": "Anna"})
    await _add(runtime, anna["id"], 30)  # 20 this week + 10 carried over

    completions = runtime.coordinator.completions
    start, end = week_bounds(dt_util.now())
    moment = end + timedelta(hours=1)
    with (
        patch.object(dt_util, "now", return_value=dt_util.as_local(moment)),
        patch.object(dt_util, "utcnow", return_value=moment),
    ):
        assert completions.points_between(anna["id"], start, end) == 20
        assert completions.earned_between(anna["id"], start, end) == 30
        # In the following week the 10 carried-in points were not earned there.
        next_end = week_bounds(dt_util.now())[1]
        assert completions.points_between(anna["id"], end, next_end) == 10
        assert completions.earned_between(anna["id"], end, next_end) == 0


# --- Manual coins -------------------------------------------------------------


async def test_parent_can_give_coins(hass, init_integration, hass_ws_client) -> None:
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {"type": "family_tasks/coins/award", "member_id": anna["id"], "coins": 5, "note": "Extra"}
    )
    response = await client.receive_json()
    assert response["success"] is True
    assert response["result"]["amount"] == 5
    assert response["result"]["reason"] == COIN_REASON_MANUAL
    assert response["result"]["note"] == "Extra"
    assert runtime.coin_ledger.balance(anna["id"]) == 5

    await runtime.coordinator.async_refresh()
    assert runtime.coordinator.data.members[anna["id"]].coins_available == 5


async def test_coin_deduction_is_limited_to_the_balance(
    hass, init_integration, hass_ws_client
) -> None:
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})
    await runtime.coin_ledger.async_add_entry(
        member_id=anna["id"], amount=3, reason=COIN_REASON_MANUAL
    )
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {"type": "family_tasks/coins/award", "member_id": anna["id"], "coins": -10}
    )
    response = await client.receive_json()
    assert response["success"] is True
    assert response["result"]["amount"] == -3
    assert response["result"]["note"] == "Münzen abgezogen"
    assert runtime.coin_ledger.balance(anna["id"]) == 0

    # Nothing left to deduct -> rejected, balance unchanged.
    await client.send_json_auto_id(
        {"type": "family_tasks/coins/award", "member_id": anna["id"], "coins": -1}
    )
    response = await client.receive_json()
    assert response["success"] is False
    assert runtime.coin_ledger.balance(anna["id"]) == 0


async def test_coin_award_rejects_zero_and_unknown_member(
    hass, init_integration, hass_ws_client
) -> None:
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {"type": "family_tasks/coins/award", "member_id": anna["id"], "coins": 0}
    )
    assert (await client.receive_json())["success"] is False

    await client.send_json_auto_id(
        {"type": "family_tasks/coins/award", "member_id": "does-not-exist", "coins": 1}
    )
    response = await client.receive_json()
    assert response["success"] is False
    assert response["error"]["code"] == "not_found"


async def test_child_cannot_award_coins(hass, init_integration, hass_ws_client) -> None:
    runtime = init_integration.runtime_data
    timmy = await runtime.members.async_create_item(
        {"name": "Timmy", "role": "child", "person_entity_id": "person.timmy"}
    )
    user, client = await _client_for_new_user(hass, hass_ws_client, is_admin=True)
    hass.states.async_set("person.timmy", "home", {"user_id": user.id})

    await client.send_json_auto_id(
        {"type": "family_tasks/coins/award", "member_id": timmy["id"], "coins": 100}
    )
    response = await client.receive_json()
    assert response["success"] is False
    assert response["error"]["code"] == "unauthorized"
    assert runtime.coin_ledger.balance(timmy["id"]) == 0
