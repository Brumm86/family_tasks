"""Tests for the v0.54 fix: correct the Streak-Bonus payout model.

v0.53 shipped a misunderstanding of the requested Streak-Bonus behaviour:
FamilyTasksCoordinator._async_process_member_streak_tier paid the configured
bonus coins at most twice per streak - once at CONF_STREAK_BONUS_REQUIRED_WEEKS,
once more at CONF_STREAK_BONUS_REQUIRED_WEEKS + 1 - then nothing further until
the streak broke and rebuilt. The user clarified the intended behaviour: the
bonus should keep being paid every further qualifying week too, just without
climbing past double - exactly bonus_coins at required_weeks consecutive
weeks, then bonus_coins * 2 flat for every consecutive qualifying week after
that, for as long as the streak continues. See this fix's docstring updates
in coordinator.py/_async_process_member_streak_tier for the corrected model,
and family-tasks-card.js's _renderStreakInfo/streakDotsHtml comment updates -
the three streak dots' *rendering logic* did not need to change, since dot 3
already meant "reached the doubled tier", not "final payout" (only the prose
describing it was wrong).

This supersedes tests/test_v053_features.py's three now-invalid streak-cap
tests (removed there, see that file's trimmed docstring) with tests against
the corrected model. tests/test_v053_features.py's four manual-points tests
are untouched by this fix and remain there.

Standalone reimplementation-level verification of the pure payout-multiplier
decision logic was also run directly during development - see the session's
verification notes. This file follows the existing init_integration-fixture
style for whenever a real Python 3.13 HA test environment is available (see
project_family_tasks_test_env memory - the environment this was written in
can't run it end-to-end either, same limitation as every prior version).
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from homeassistant.util import dt as dt_util

from custom_components.family_tasks.const import (
    CONF_STREAK_150_BONUS_COINS,
    CONF_STREAK_200_BONUS_COINS,
    CONF_STREAK_BONUS_REQUIRED_WEEKS,
    CONF_WEEKLY_PROGRESS_GOAL_POINTS,
    COIN_REASON_STREAK_150,
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


async def test_streak_bonus_pays_once_at_required_weeks_then_double_every_week_after(
    hass, init_integration
) -> None:
    """required_weeks=2, bonus=4: weeks 2/3/4/5 in a row pay 4, 8, 8, 8 -
    single at the base threshold, then a flat double for every week beyond
    it, never climbing further and never stopping."""
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

    # Seed the "150" tier's cursor so one refresh catches up all five
    # elapsed weeks -5..-1 in a single pass (same technique
    # test_v053_features.py's now-removed streak tests used).
    await runtime.streak_bonus_state.async_set(anna["id"], "150", _start_of_week_utc(-5), 0)

    # Weeks -5..-1: five weeks in a row, comfortably over the 150%
    # checkpoint (15 points) - streak_count reaches 1, 2, 3, 4, 5.
    for offset in (-5, -4, -3, -2, -1):
        week_start = _start_of_week_utc(offset)
        await _complete_at_utc(runtime, task["id"], anna["id"], week_start + timedelta(days=1))
    await _refresh_at_utc(runtime, _start_of_week_utc(0))

    streak_credits = [
        e for e in runtime.coin_ledger.entries
        if e["member_id"] == anna["id"] and e["reason"] == COIN_REASON_STREAK_150
    ]
    # streak_count=1: nothing yet. streak_count=2 (required_weeks): 4.
    # streak_count=3/4/5 (beyond required_weeks): 8 each, flat - not 12/16/20.
    assert [e["amount"] for e in streak_credits] == [4, 8, 8, 8]
    assert runtime.coordinator.data.members[anna["id"]].streak_weeks_150 == 5


async def test_streak_bonus_tiers_are_independent(hass, init_integration) -> None:
    """The 150% and 200% tiers are processed (and paid) independently, each
    with its own required_weeks/bonus_coins and its own rolling 1x/2x
    payout - reaching 200% pays both tiers, since 200% implies 150% too."""
    runtime = init_integration.runtime_data
    hass.config_entries.async_update_entry(
        init_integration,
        options={
            CONF_WEEKLY_PROGRESS_GOAL_POINTS: 10,
            CONF_STREAK_BONUS_REQUIRED_WEEKS: 2,
            CONF_STREAK_150_BONUS_COINS: 4,
            CONF_STREAK_200_BONUS_COINS: 10,
        },
    )
    anna = await runtime.members.async_create_item({"name": "Anna"})
    task = await _add_task(runtime, member_ids=[anna["id"]], points=20)

    await runtime.streak_bonus_state.async_set(anna["id"], "150", _start_of_week_utc(-3), 0)
    await runtime.streak_bonus_state.async_set(anna["id"], "200", _start_of_week_utc(-3), 0)

    # Three weeks in a row at 20 points - comfortably over both the 150%
    # (15 points) and 200% (20 points) checkpoints.
    for offset in (-3, -2, -1):
        week_start = _start_of_week_utc(offset)
        await _complete_at_utc(runtime, task["id"], anna["id"], week_start + timedelta(days=1))
    await _refresh_at_utc(runtime, _start_of_week_utc(0))

    credits_150 = [
        e for e in runtime.coin_ledger.entries
        if e["member_id"] == anna["id"] and e["reason"] == COIN_REASON_STREAK_150
    ]
    credits_200 = [
        e for e in runtime.coin_ledger.entries
        if e["member_id"] == anna["id"] and e["reason"] == COIN_REASON_STREAK_200
    ]
    # Both tiers reach streak_count 1, 2, 3 - same rolling 1x/2x shape,
    # scaled to each tier's own bonus_coins.
    assert [e["amount"] for e in credits_150] == [4, 8]
    assert [e["amount"] for e in credits_200] == [10, 20]


async def test_streak_bonus_pays_again_after_break_and_rebuild(
    hass, init_integration
) -> None:
    """Once the streak breaks (a week under the checkpoint), the next streak
    pays out again from scratch at required_weeks."""
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

    await runtime.streak_bonus_state.async_set(anna["id"], "150", _start_of_week_utc(-5), 0)

    # Weeks -5..-4: a first streak that only reaches required_weeks (2).
    for offset in (-5, -4):
        week_start = _start_of_week_utc(offset)
        await _complete_at_utc(runtime, task["id"], anna["id"], week_start + timedelta(days=1))
    # Week -3: nothing completed - breaks the streak, resets streak_count to 0.
    # Weeks -2..-1: a second streak, also reaching required_weeks (2) again.
    for offset in (-2, -1):
        week_start = _start_of_week_utc(offset)
        await _complete_at_utc(runtime, task["id"], anna["id"], week_start + timedelta(days=1))
    await _refresh_at_utc(runtime, _start_of_week_utc(0))

    streak_credits = [
        e for e in runtime.coin_ledger.entries
        if e["member_id"] == anna["id"] and e["reason"] == COIN_REASON_STREAK_150
    ]
    # Each streak only reaches required_weeks (2) before breaking/ending ->
    # exactly 1 payout of the base amount each, 2 total, not 4.
    assert len(streak_credits) == 2, streak_credits
    assert [e["amount"] for e in streak_credits] == [4, 4]


async def test_streak_bonus_no_payout_before_required_weeks(hass, init_integration) -> None:
    """A single qualifying week (streak_count=1, required_weeks=2) pays
    nothing yet - unaffected by the v0.54 correction, still the very first
    step before either payout tier kicks in."""
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
