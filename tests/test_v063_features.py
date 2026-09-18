"""Tests for the v0.63 Streak-Bonus simplification.

Three related changes shipped together in v0.63:

1. Kids can now see every child's weekly progress in the Wochenfortschritt
   section, not just their own (family-tasks-card.js: _progressMembers() no
   longer takes an isChildUser/currentMemberId argument and always returns
   every eligible child). Purely client-side - not covered here, see the
   session's jsdom smoke-test notes in the project memory instead.

2. The Handyzeit tick-malus banding (PROGRESS_BAND_TICK_ADJUSTMENT_MINUTES,
   const.py) gained two additional, harsher bands: 0% -> -6 min/tick (was
   part of the old blanket "<25%: -4" band), 10% -> -5 min/tick. Pure data
   change to an existing, already-tested banding function
   (_screen_time_tick_adjustment_minutes) - not covered here either.

3. **This file's actual subject**: the Streak-Bonus (coordinator.py,
   _async_process_streak_coin_bonus/_async_process_member_streak_tier) is
   simplified. Before v0.63 there were two entirely independent streak
   tiers (150% and 200% of the weekly goal), each with its own
   CONF_STREAK_BONUS_REQUIRED_WEEKS-configurable payout threshold that then
   doubled once and stayed doubled (see test_v054_features.py). v0.63
   removes the 150% tier entirely and replaces the single configurable
   "required weeks" threshold with two fixed, independently configurable
   milestones against the 200% mark only: CONF_STREAK_BONUS_2_WEEKS_COINS
   (paid starting the 2nd consecutive qualifying week) and
   CONF_STREAK_BONUS_3_WEEKS_COINS (paid starting the 3rd consecutive
   qualifying week, and repeated every further consecutive week - the
   "rolling, no cap" shape from v0.54 is kept, just re-anchored to fixed
   2-/3-week milestones instead of a configurable one). Both amounts credit
   the same COIN_REASON_STREAK_200 ledger reason (there is only one tier
   left, so no separate reason constant is needed).

This supersedes tests/test_v054_features.py, which still imports the
removed CONF_STREAK_150_BONUS_COINS/CONF_STREAK_200_BONUS_COINS/
CONF_STREAK_BONUS_REQUIRED_WEEKS/COIN_REASON_STREAK_150 symbols and is left
untouched as a historical artifact rather than fixed in place, matching
this repo's established precedent for superseded version-specific test
files (see tests/test_v032_features.py, broken the same way since v0.36).

Standalone reimplementation-level verification of the pure payout-milestone
decision logic was also run directly during development - see the
session's verification notes. This file follows the existing
init_integration-fixture style for whenever a real Python 3.13 HA test
environment is available (see project_family_tasks_test_env memory - the
environment this was written in can't run it end-to-end either, same
limitation as every prior version).
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from homeassistant.util import dt as dt_util

from custom_components.family_tasks.const import (
    CONF_STREAK_BONUS_2_WEEKS_COINS,
    CONF_STREAK_BONUS_3_WEEKS_COINS,
    CONF_WEEKLY_PROGRESS_GOAL_POINTS,
    COIN_REASON_STREAK_200,
)


def _start_of_week_utc(offset_weeks: int = 0):
    """Mirror FamilyTasksCoordinator._async_update_data's start_of_week math -
    same helper duplicated in every version's test file (see
    test_v030_features.py) so this file has no cross-file import dependency.
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


async def test_streak_bonus_pays_2_weeks_then_3_weeks_then_repeats_3_weeks_amount(
    hass, init_integration
) -> None:
    """bonus_2_weeks=4, bonus_3_weeks=10: five weeks in a row over the 200%
    mark pay 0, 4, 10, 10, 10 - nothing for week 1, the 2-weeks amount
    exactly once at week 2, then the (higher) 3-weeks amount starting at
    week 3 and repeating flat for every further consecutive week, never
    climbing further and never stopping."""
    runtime = init_integration.runtime_data
    hass.config_entries.async_update_entry(
        init_integration,
        options={
            CONF_WEEKLY_PROGRESS_GOAL_POINTS: 10,
            CONF_STREAK_BONUS_2_WEEKS_COINS: 4,
            CONF_STREAK_BONUS_3_WEEKS_COINS: 10,
        },
    )
    anna = await runtime.members.async_create_item({"name": "Anna"})
    task = await _add_task(runtime, member_ids=[anna["id"]], points=20)

    # Seed the "200" tier's cursor so one refresh catches up all five
    # elapsed weeks -5..-1 in a single pass (same technique
    # test_v054_features.py's streak tests used).
    await runtime.streak_bonus_state.async_set(anna["id"], "200", _start_of_week_utc(-5), 0)

    # Weeks -5..-1: five weeks in a row, comfortably at/over the 200%
    # checkpoint (20 points) - streak_count reaches 1, 2, 3, 4, 5.
    for offset in (-5, -4, -3, -2, -1):
        week_start = _start_of_week_utc(offset)
        await _complete_at_utc(runtime, task["id"], anna["id"], week_start + timedelta(days=1))
    await _refresh_at_utc(runtime, _start_of_week_utc(0))

    streak_credits = [
        e for e in runtime.coin_ledger.entries
        if e["member_id"] == anna["id"] and e["reason"] == COIN_REASON_STREAK_200
    ]
    # streak_count=1: nothing yet. streak_count=2: the 2-weeks amount (4).
    # streak_count=3/4/5: the (higher) 3-weeks amount (10) each, flat.
    assert [e["amount"] for e in streak_credits] == [4, 10, 10, 10]
    assert runtime.coordinator.data.members[anna["id"]].streak_weeks_200 == 5


async def test_streak_bonus_2_weeks_and_3_weeks_independently_configurable(
    hass, init_integration
) -> None:
    """The 2-weeks amount can be disabled (0) while the 3-weeks amount stays
    active - no payout at week 2, first payout only once week 3 is reached,
    confirming the two amounts are read and applied independently."""
    runtime = init_integration.runtime_data
    hass.config_entries.async_update_entry(
        init_integration,
        options={
            CONF_WEEKLY_PROGRESS_GOAL_POINTS: 10,
            CONF_STREAK_BONUS_2_WEEKS_COINS: 0,
            CONF_STREAK_BONUS_3_WEEKS_COINS: 10,
        },
    )
    anna = await runtime.members.async_create_item({"name": "Anna"})
    task = await _add_task(runtime, member_ids=[anna["id"]], points=20)

    await runtime.streak_bonus_state.async_set(anna["id"], "200", _start_of_week_utc(-3), 0)

    for offset in (-3, -2, -1):
        week_start = _start_of_week_utc(offset)
        await _complete_at_utc(runtime, task["id"], anna["id"], week_start + timedelta(days=1))
    await _refresh_at_utc(runtime, _start_of_week_utc(0))

    streak_credits = [
        e for e in runtime.coin_ledger.entries
        if e["member_id"] == anna["id"] and e["reason"] == COIN_REASON_STREAK_200
    ]
    # Week 2 pays nothing (2-weeks amount disabled), week 3 pays the
    # 3-weeks amount - exactly one payout, not two.
    assert [e["amount"] for e in streak_credits] == [10]


async def test_streak_bonus_pays_again_after_break_and_rebuild(
    hass, init_integration
) -> None:
    """Once the streak breaks (a week under the 200% checkpoint), the next
    streak pays out again from scratch starting at the 2-weeks milestone."""
    runtime = init_integration.runtime_data
    hass.config_entries.async_update_entry(
        init_integration,
        options={
            CONF_WEEKLY_PROGRESS_GOAL_POINTS: 10,
            CONF_STREAK_BONUS_2_WEEKS_COINS: 4,
            CONF_STREAK_BONUS_3_WEEKS_COINS: 10,
        },
    )
    anna = await runtime.members.async_create_item({"name": "Anna"})
    task = await _add_task(runtime, member_ids=[anna["id"]], points=20)

    await runtime.streak_bonus_state.async_set(anna["id"], "200", _start_of_week_utc(-5), 0)

    # Weeks -5..-4: a first streak that only reaches the 2-weeks milestone.
    for offset in (-5, -4):
        week_start = _start_of_week_utc(offset)
        await _complete_at_utc(runtime, task["id"], anna["id"], week_start + timedelta(days=1))
    # Week -3: nothing completed - breaks the streak, resets streak_count to 0.
    # Weeks -2..-1: a second streak, also reaching the 2-weeks milestone again.
    for offset in (-2, -1):
        week_start = _start_of_week_utc(offset)
        await _complete_at_utc(runtime, task["id"], anna["id"], week_start + timedelta(days=1))
    await _refresh_at_utc(runtime, _start_of_week_utc(0))

    streak_credits = [
        e for e in runtime.coin_ledger.entries
        if e["member_id"] == anna["id"] and e["reason"] == COIN_REASON_STREAK_200
    ]
    # Each streak only reaches the 2-weeks milestone before breaking/ending
    # -> exactly 1 payout of the 2-weeks amount each, 2 total, not 4.
    assert len(streak_credits) == 2, streak_credits
    assert [e["amount"] for e in streak_credits] == [4, 4]


async def test_streak_bonus_no_payout_before_2_weeks(hass, init_integration) -> None:
    """A single qualifying week (streak_count=1) pays nothing yet - the very
    first step before either the 2-weeks or 3-weeks milestone is reached."""
    runtime = init_integration.runtime_data
    hass.config_entries.async_update_entry(
        init_integration,
        options={
            CONF_WEEKLY_PROGRESS_GOAL_POINTS: 10,
            CONF_STREAK_BONUS_2_WEEKS_COINS: 4,
            CONF_STREAK_BONUS_3_WEEKS_COINS: 10,
        },
    )
    anna = await runtime.members.async_create_item({"name": "Anna"})
    task = await _add_task(runtime, member_ids=[anna["id"]], points=20)

    week_start = _start_of_week_utc(-1)
    await _complete_at_utc(runtime, task["id"], anna["id"], week_start + timedelta(days=1))
    await _refresh_at_utc(runtime, _start_of_week_utc(0))

    streak_credits = [
        e for e in runtime.coin_ledger.entries
        if e["member_id"] == anna["id"] and e["reason"] == COIN_REASON_STREAK_200
    ]
    assert streak_credits == []
    assert runtime.coordinator.data.members[anna["id"]].streak_weeks_200 == 1
