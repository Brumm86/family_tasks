"""Tests for v0.68: Handyzeit-malus and coin thresholds as absolute points.

The malus stages (previously 10/25/50/75/100 % of the weekly goal) and the
two coin checkpoints (previously 150/200 %) are now absolute point values,
each set separately in the options flow. A threshold that is not set is
derived from the weekly goal times its legacy percent, so existing
installations behave unchanged. Like the other version-specific files this
needs a Python 3.13 HA test environment to run end to end; the pure helpers
(resolve_progress_thresholds, thresholds_ascending) were additionally
verified standalone.
"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.util import dt as dt_util

from custom_components.family_tasks.const import (
    COIN_REASON_MILESTONE_150,
    COIN_REASON_MILESTONE_200,
    CONF_COIN_THRESHOLD_1_POINTS,
    CONF_COIN_THRESHOLD_2_POINTS,
    CONF_MALUS_THRESHOLD_1_POINTS,
    CONF_MALUS_THRESHOLD_2_POINTS,
    CONF_MALUS_THRESHOLD_3_POINTS,
    CONF_MALUS_THRESHOLD_4_POINTS,
    CONF_MILESTONE_150_BONUS_COINS,
    CONF_MILESTONE_200_BONUS_COINS,
    CONF_WEEKLY_PROGRESS_GOAL_POINTS,
    resolve_progress_thresholds,
    thresholds_ascending,
)


def test_unset_thresholds_derive_from_goal_and_legacy_percents() -> None:
    malus, coin = resolve_progress_thresholds({}, 100)
    assert malus == (10, 25, 50, 75)
    assert coin == (150, 200)
    malus, coin = resolve_progress_thresholds({}, 40)
    assert malus == (4, 10, 20, 30)
    assert coin == (60, 80)


def test_explicit_thresholds_win_and_goal_zero_gives_zero() -> None:
    options = {
        CONF_MALUS_THRESHOLD_1_POINTS: 5,
        CONF_COIN_THRESHOLD_2_POINTS: 333,
    }
    malus, coin = resolve_progress_thresholds(options, 100)
    assert malus == (5, 25, 50, 75)
    assert coin == (150, 333)
    assert resolve_progress_thresholds({}, 0) == ((0, 0, 0, 0), (0, 0))


def test_thresholds_ascending() -> None:
    assert thresholds_ascending((10, 25, 50, 75), 100, (150, 200))
    assert not thresholds_ascending((10, 25, 50, 75), 75, (150, 200))
    assert not thresholds_ascending((10, 25, 50, 75), 100, (200, 200))
    assert not thresholds_ascending((25, 25, 50, 75), 100, (150, 200))


async def test_malus_banding_uses_absolute_points(hass, init_integration) -> None:
    coordinator = init_integration.runtime_data.coordinator
    thresholds = (10, 20, 30, 40)
    expected = {0: -6, 9: -6, 10: -5, 19: -5, 20: -3, 29: -3, 30: -2, 39: -2, 40: -1, 49: -1, 50: 0, 80: 0}
    for points, minutes in expected.items():
        assert (
            coordinator._screen_time_tick_adjustment_minutes(points, 50, thresholds)
            == minutes
        ), points
    # No weekly goal -> no malus at all.
    assert coordinator._screen_time_tick_adjustment_minutes(0, 0, thresholds) == 0


async def test_malus_banding_reads_options_when_thresholds_not_passed(
    hass, init_integration
) -> None:
    hass.config_entries.async_update_entry(
        init_integration,
        options={
            CONF_WEEKLY_PROGRESS_GOAL_POINTS: 100,
            CONF_MALUS_THRESHOLD_1_POINTS: 5,
            CONF_MALUS_THRESHOLD_2_POINTS: 6,
            CONF_MALUS_THRESHOLD_3_POINTS: 7,
            CONF_MALUS_THRESHOLD_4_POINTS: 8,
        },
    )
    coordinator = init_integration.runtime_data.coordinator
    assert coordinator._screen_time_tick_adjustment_minutes(4, 100) == -6
    assert coordinator._screen_time_tick_adjustment_minutes(5, 100) == -5
    assert coordinator._screen_time_tick_adjustment_minutes(8, 100) == -1
    assert coordinator._screen_time_tick_adjustment_minutes(100, 100) == 0


async def test_coin_bonus_uses_absolute_thresholds(hass, init_integration) -> None:
    """Coin thresholds 30/45 (goal 20) pay at 30 and 45 points, not at 150/200 %."""
    runtime = init_integration.runtime_data
    hass.config_entries.async_update_entry(
        init_integration,
        options={
            CONF_WEEKLY_PROGRESS_GOAL_POINTS: 20,
            CONF_COIN_THRESHOLD_1_POINTS: 30,
            CONF_COIN_THRESHOLD_2_POINTS: 45,
            CONF_MILESTONE_150_BONUS_COINS: 3,
            CONF_MILESTONE_200_BONUS_COINS: 7,
        },
    )
    anna = await runtime.members.async_create_item({"name": "Anna"})
    task = await runtime.tasks.async_create_item(
        {
            "name": "Testaufgabe",
            "points": 35,
            "recurrence": {"type": "daily"},
            "rotation": {"member_ids": [anna["id"]], "strategy": "fixed"},
        }
    )
    await runtime.coordinator.async_complete_task(task["id"], member_id=anna["id"])
    await runtime.coordinator.async_refresh()
    reasons = [e["reason"] for e in runtime.coin_ledger.entries if e["member_id"] == anna["id"]]
    assert COIN_REASON_MILESTONE_150 in reasons  # 35 >= 30
    assert COIN_REASON_MILESTONE_200 not in reasons  # 35 < 45
    data = runtime.coordinator.data
    assert (data.milestone_150_threshold_points, data.milestone_200_threshold_points) == (30, 45)


async def test_options_flow_rejects_non_ascending_thresholds(hass, init_integration) -> None:
    result = await hass.config_entries.options.async_init(init_integration.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_WEEKLY_PROGRESS_GOAL_POINTS: 100,
            CONF_MALUS_THRESHOLD_1_POINTS: 50,
            CONF_MALUS_THRESHOLD_2_POINTS: 25,
        },
    )
    assert result["type"] == "form"
    assert result["errors"] == {"base": "thresholds_not_ascending"}


async def test_options_flow_saves_valid_absolute_thresholds(hass, init_integration) -> None:
    result = await hass.config_entries.options.async_init(init_integration.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_WEEKLY_PROGRESS_GOAL_POINTS: 100,
            CONF_MALUS_THRESHOLD_1_POINTS: 15,
            CONF_MALUS_THRESHOLD_2_POINTS: 30,
            CONF_MALUS_THRESHOLD_3_POINTS: 60,
            CONF_MALUS_THRESHOLD_4_POINTS: 80,
            CONF_COIN_THRESHOLD_1_POINTS: 120,
            CONF_COIN_THRESHOLD_2_POINTS: 180,
        },
    )
    assert result["type"] == "create_entry"
    assert result["data"][CONF_MALUS_THRESHOLD_1_POINTS] == 15
    assert result["data"][CONF_COIN_THRESHOLD_2_POINTS] == 180
