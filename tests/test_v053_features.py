"""Tests for the v0.53 features:

- Streak-Bonus payout cap: before this version,
  FamilyTasksCoordinator._async_process_member_streak_tier credited the
  configured bonus coins *every* elapsed week once a member's per-tier
  streak_count reached CONF_STREAK_BONUS_REQUIRED_WEEKS ("rolling"), so an
  indefinitely long streak was worth an unbounded number of payouts. As of
  v0.53 the bonus is paid at most twice per streak: once when the counter
  first reaches CONF_STREAK_BONUS_REQUIRED_WEEKS, and a second, final time
  when it reaches CONF_STREAK_BONUS_REQUIRED_WEEKS + 1 - after that the
  streak can keep running, but no further payout follows until it breaks
  (a week under the checkpoint resets the counter to 0) and is rebuilt.
  This mirrors the three "streak dots" now shown next to a member's name in
  the card (family-tasks-card.js), which also top out at the same two
  milestones - see _activeStreakTierFor/streakDotsHtml there.

- Manually-awarded points now appear in the "diese Woche erledigt" list
  (ws_list_member_weekly_completions): explicit user request to show them
  "unter den erledigten Aufgaben" with their point value and note.
  MANUAL_POINTS_TASK_ID covers three distinct cases - a parent's deliberate
  award/deduction (ws_award_points), the rejection penalty
  (async_skip_task), and the expired-claim penalty (_async_expire_claim) -
  all three now show up; the Meilenstein-/Streak-Bonus/points-correction
  sentinels stay excluded, per explicit user request (none of those is a
  single deliberate action the way the other three are).

Standalone reimplementation-level verification of the pure payout-cap
decision logic (and the card's matching streak-dot threshold logic) was
also run directly during development - see the session's verification
notes. This file follows the existing init_integration-fixture style for
whenever a real Python 3.13 HA test environment is available (see
project_family_tasks_test_env memory - the environment this was written in
can't run it end-to-end either, same limitation as every prior version).
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from homeassistant.util import dt as dt_util

from custom_components.family_tasks.const import (
    CONF_STREAK_150_BONUS_COINS,
    CONF_STREAK_BONUS_REQUIRED_WEEKS,
    CONF_WEEKLY_PROGRESS_GOAL_POINTS,
    COIN_REASON_STREAK_150,
    MANUAL_POINTS_TASK_ID,
    MILESTONE_BONUS_1_TASK_ID,
    POINTS_CORRECTION_TASK_ID,
    STREAK_BONUS_TASK_ID,
    WS_API_MEMBER_WEEKLY_COMPLETIONS,
)


def _start_of_week_utc(offset_weeks: int = 0):
    """Mirror FamilyTasksCoordinator._async_update_data's start_of_week math -
    same helper as test_v030_features.py's, duplicated here so this file
    has no cross-file import dependency.
    """
    local_now = dt_util.now()
    start_of_today = dt_util.as_utc(dt_util.start_of_local_day(local_now))
    start_of_week = start_of_today - timedelta(days=start_of_today.weekday())
    return start_of_week + timedelta(weeks=offset_weeks)


async def _refresh_at_utc(runtime, utc_dt) -> None:
    local_dt = dt_util.as_local(utc_dt)
    with (
        patch.object(dt_util, "now", return_value=local_dt),
        patch.object(dt_util, "utcnow", return_value=utc_dt),
    ):
        await runtime.coordinator.async_refresh()


async def _complete_at_utc(runtime, task_id, member_id, utc_dt) -> None:
    local_dt = dt_util.as_local(utc_dt)
    with (
        patch.object(dt_util, "now", return_value=local_dt),
        patch.object(dt_util, "utcnow", return_value=utc_dt),
    ):
        await runtime.coordinator.async_complete_task(task_id, member_id=member_id)


async def _add_task(runtime, *, member_ids, points=20, **overrides):
    payload = {
        "name": "Testaufgabe",
        "points": points,
        "recurrence": {"type": "daily"},
        "rotation": {"member_ids": member_ids, "strategy": "fixed"},
    }
    payload.update(overrides)
    return await runtime.tasks.async_create_item(payload)


# --- Streak-Bonus payout cap -------------------------------------------------


async def test_streak_bonus_paid_at_required_weeks_and_required_weeks_plus_one(
    hass, init_integration
) -> None:
    """A streak reaching weeks 2 and 3 (required_weeks=2, the default) pays
    exactly twice, not once per week from week 2 onward."""
    runtime = init_integration.runtime_data
    hass.config_entries.async_update_entry(
        init_integration,
        options={
            CONF_WEEKLY_PROGRESS_GOAL_POINTS: 10,
            CONF_STREAK_BONUS_REQUIRED_WEEKS: 2,
            CONF_STREAK_150_BONUS_COINS: 4,
        },
    )
    anna = await runtime.members.async_create_item({"name": "Anna"})
    task = await _add_task(runtime, member_ids=[anna["id"]], points=20)

    # A brand-new tier cursor otherwise starts at "last week" (see
    # StreakBonusStateStore/_async_process_member_streak_tier's docstring),
    # so a single refresh would only ever catch up one elapsed week. Seed
    # the "150" tier's cursor to start at week -4 so one refresh below
    # catches up all four weeks -4..-1 in one pass, same technique
    # test_v032_features.py used for the pre-v0.36 single-tier store.
    await runtime.streak_bonus_state.async_set(anna["id"], "150", _start_of_week_utc(-4), 0)

    # Four fully-elapsed weeks (-4..-1), each comfortably over the 150%
    # checkpoint (15 points) - a streak that reaches week 4, well past the
    # required_weeks(2) + 1 = 3 cap.
    for offset in (-4, -3, -2, -1):
        week_start = _start_of_week_utc(offset)
        await _complete_at_utc(runtime, task["id"], anna["id"], week_start + timedelta(days=1))
    await _refresh_at_utc(runtime, _start_of_week_utc(0))

    streak_credits = [
        e for e in runtime.coin_ledger.entries
        if e["member_id"] == anna["id"] and e["reason"] == COIN_REASON_STREAK_150
    ]
    assert len(streak_credits) == 2, streak_credits
    assert sum(e["amount"] for e in streak_credits) == 8
    # streak_weeks_150 itself is NOT capped internally - it keeps counting
    # the true consecutive-week length; only the payout (and the card's
    # three dots) cap out at required_weeks + 1.
    assert runtime.coordinator.data.members[anna["id"]].streak_weeks_150 == 4


async def test_streak_bonus_pays_again_after_break_and_rebuild(
    hass, init_integration
) -> None:
    """Once the streak breaks (a week under the checkpoint), the next streak
    pays out again from scratch at required_weeks and required_weeks + 1."""
    runtime = init_integration.runtime_data
    hass.config_entries.async_update_entry(
        init_integration,
        options={
            CONF_WEEKLY_PROGRESS_GOAL_POINTS: 10,
            CONF_STREAK_BONUS_REQUIRED_WEEKS: 2,
            CONF_STREAK_150_BONUS_COINS: 4,
        },
    )
    anna = await runtime.members.async_create_item({"name": "Anna"})
    task = await _add_task(runtime, member_ids=[anna["id"]], points=20)

    # Seed the cursor to start at week -5 (see the previous test for why
    # this is needed) so one refresh below catches up all five weeks.
    await runtime.streak_bonus_state.async_set(anna["id"], "150", _start_of_week_utc(-5), 0)

    # Weeks -5..-4: a first streak that reaches the cap (2 payouts).
    for offset in (-5, -4):
        week_start = _start_of_week_utc(offset)
        await _complete_at_utc(runtime, task["id"], anna["id"], week_start + timedelta(days=1))
    # Week -3: nothing completed - breaks the streak.
    # Weeks -2..-1: a second streak, reaching the cap again.
    for offset in (-2, -1):
        week_start = _start_of_week_utc(offset)
        await _complete_at_utc(runtime, task["id"], anna["id"], week_start + timedelta(days=1))
    await _refresh_at_utc(runtime, _start_of_week_utc(0))

    streak_credits = [
        e for e in runtime.coin_ledger.entries
        if e["member_id"] == anna["id"] and e["reason"] == COIN_REASON_STREAK_150
    ]
    # First streak only reaches required_weeks (2) before breaking -> 1
    # payout. Second streak also only reaches 2 before the window ends ->
    # 1 more payout. Total 2, not 4 - each streak paid according to how far
    # it actually got.
    assert len(streak_credits) == 2, streak_credits


async def test_streak_bonus_no_payout_before_required_weeks(hass, init_integration) -> None:
    """A single qualifying week (streak_count=1, required_weeks=2) pays nothing yet."""
    runtime = init_integration.runtime_data
    hass.config_entries.async_update_entry(
        init_integration,
        options={
            CONF_WEEKLY_PROGRESS_GOAL_POINTS: 10,
            CONF_STREAK_BONUS_REQUIRED_WEEKS: 2,
            CONF_STREAK_150_BONUS_COINS: 4,
        },
    )
    anna = await runtime.members.async_create_item({"name": "Anna"})
    task = await _add_task(runtime, member_ids=[anna["id"]], points=20)

    week_start = _start_of_week_utc(-1)
    await _complete_at_utc(runtime, task["id"], anna["id"], week_start + timedelta(days=1))
    await _refresh_at_utc(runtime, _start_of_week_utc(0))

    streak_credits = [
        e for e in runtime.coin_ledger.entries
        if e["member_id"] == anna["id"] and e["reason"] == COIN_REASON_STREAK_150
    ]
    assert streak_credits == []
    assert runtime.coordinator.data.members[anna["id"]].streak_weeks_150 == 1


# --- Manually-awarded points in the weekly completions list -----------------


async def test_manual_award_appears_in_weekly_completions(
    hass, init_integration, hass_ws_client
) -> None:
    """A parent's manual point award (with a note) now shows up in the list."""
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "family_tasks/points/award",
            "member_id": anna["id"],
            "points": 5,
            "note": "Oma beim Umzug geholfen",
        }
    )
    response = await client.receive_json()
    assert response["success"] is True

    await client.send_json_auto_id(
        {"type": WS_API_MEMBER_WEEKLY_COMPLETIONS, "member_id": anna["id"]}
    )
    response = await client.receive_json()
    assert response["success"] is True
    completions = response["result"]["completions"]
    assert len(completions) == 1
    assert completions[0]["task_name"] == "Oma beim Umzug geholfen"
    assert completions[0]["points_awarded"] == 5


async def test_manual_deduction_without_note_uses_generic_label(
    hass, init_integration, hass_ws_client
) -> None:
    """A manual deduction with no note falls back to the existing generic label."""
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "family_tasks/points/award", "member_id": anna["id"], "points": -2}
    )
    response = await client.receive_json()
    assert response["success"] is True

    await client.send_json_auto_id(
        {"type": WS_API_MEMBER_WEEKLY_COMPLETIONS, "member_id": anna["id"]}
    )
    response = await client.receive_json()
    completions = response["result"]["completions"]
    assert len(completions) == 1
    assert completions[0]["task_name"] == "Punkte abgezogen"
    assert completions[0]["points_awarded"] == -2


async def test_rejection_and_claim_expiry_penalties_also_appear(
    hass, init_integration, hass_ws_client
) -> None:
    """The two other MANUAL_POINTS_TASK_ID cases (system-triggered penalties,
    not a deliberate award) are included too, per explicit user request -
    each already carries its own distinguishing task_name."""
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})

    await runtime.completions.async_add_entry(
        task_id=MANUAL_POINTS_TASK_ID,
        period_key=dt_util.utcnow().date().isoformat(),
        member_id=anna["id"],
        points_awarded=-1,
        task_name="Nicht freigegeben: Zimmer aufräumen",
        note="Bett noch nicht gemacht",
    )
    await runtime.completions.async_add_entry(
        task_id=MANUAL_POINTS_TASK_ID,
        period_key=dt_util.utcnow().date().isoformat(),
        member_id=anna["id"],
        points_awarded=-1,
        task_name="Reservierung abgelaufen: Geschirrspüler ausräumen",
    )

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": WS_API_MEMBER_WEEKLY_COMPLETIONS, "member_id": anna["id"]}
    )
    response = await client.receive_json()
    task_names = {c["task_name"] for c in response["result"]["completions"]}
    assert task_names == {
        "Nicht freigegeben: Zimmer aufräumen",
        "Reservierung abgelaufen: Geschirrspüler ausräumen",
    }
    # The rejection's own separate explanation note is deliberately NOT
    # surfaced here (per explicit user request - "es reicht die Angabe ohne
    # Grund") - only task_name/points_awarded/completed_at are returned.
    for c in response["result"]["completions"]:
        assert "note" not in c


async def test_bonus_and_correction_sentinels_stay_excluded(
    hass, init_integration, hass_ws_client
) -> None:
    """Meilenstein-/Streak-Bonus and points-correction entries are still
    excluded - only MANUAL_POINTS_TASK_ID changed in v0.53."""
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})

    for task_id in (MILESTONE_BONUS_1_TASK_ID, POINTS_CORRECTION_TASK_ID, STREAK_BONUS_TASK_ID):
        await runtime.completions.async_add_entry(
            task_id=task_id,
            period_key=dt_util.utcnow().date().isoformat(),
            member_id=anna["id"],
            points_awarded=3,
            task_name="sollte nicht erscheinen",
        )

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": WS_API_MEMBER_WEEKLY_COMPLETIONS, "member_id": anna["id"]}
    )
    response = await client.receive_json()
    assert response["result"]["completions"] == []
