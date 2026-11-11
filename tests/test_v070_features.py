"""Tests for v0.70.0: Spotify-Freigabe (Mindestpunktzahl der Vorwoche).

A child's Spotify is unlocked for the whole current calendar week when the
points of the already-final previous week reached the household-wide
CONF_SPOTIFY_THRESHOLD_POINTS (0 = feature off). The integration only exposes
the per-child binary sensor; the Handyzeit-Verwaltung blueprint does the actual
switching in Family Link.
"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from custom_components.family_tasks.const import (
    CONF_SPOTIFY_THRESHOLD_POINTS,
    DEFAULT_SPOTIFY_THRESHOLD_POINTS,
    DOMAIN,
    MANUAL_POINTS_TASK_ID,
)


def _last_week_moment():
    """A moment safely inside the previous calendar week (local time)."""
    today = dt_util.start_of_local_day()
    this_monday = today - timedelta(days=today.weekday())
    return this_monday - timedelta(days=2, hours=-12)


async def _log_points(runtime, member_id: str, points: int, *, last_week: bool) -> None:
    entry = await runtime.coordinator.completions.async_add_entry(
        task_id=MANUAL_POINTS_TASK_ID,
        period_key="test",
        member_id=member_id,
        points_awarded=points,
        task_name="Testpunkte",
    )
    if last_week:
        entry["completed_at"] = _last_week_moment().isoformat()


def _set_threshold(hass, entry, value) -> None:
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_SPOTIFY_THRESHOLD_POINTS: value}
    )


def _sensor_state(hass, entry, member_id: str):
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "binary_sensor", DOMAIN, f"{entry.entry_id}_member_{member_id}_spotify_unlocked"
    )
    return entity_id, (hass.states.get(entity_id) if entity_id else None)


async def test_threshold_defaults_to_off(hass, init_integration) -> None:
    coordinator = init_integration.runtime_data.coordinator
    assert DEFAULT_SPOTIFY_THRESHOLD_POINTS == 0
    assert coordinator._spotify_threshold_points() == 0
    assert coordinator.data.spotify_threshold_points == 0


async def test_options_flow_saves_threshold_as_int(hass, init_integration) -> None:
    result = await hass.config_entries.options.async_init(init_integration.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SPOTIFY_THRESHOLD_POINTS: 25.0}
    )
    assert result["type"] == "create_entry"
    assert result["data"][CONF_SPOTIFY_THRESHOLD_POINTS] == 25
    assert isinstance(result["data"][CONF_SPOTIFY_THRESHOLD_POINTS], int)


async def test_options_flow_threshold_independent_of_ascending_chain(
    hass, init_integration
) -> None:
    """The Spotify threshold may be above or below every malus/coin threshold."""
    for value in (1, 10_000):
        result = await hass.config_entries.options.async_init(init_integration.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_SPOTIFY_THRESHOLD_POINTS: value}
        )
        assert result["type"] == "create_entry"
        assert result["data"][CONF_SPOTIFY_THRESHOLD_POINTS] == value


async def test_unlock_follows_previous_week_points(hass, init_integration) -> None:
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna", "role": "child"})
    ben = await runtime.members.async_create_item({"name": "Ben", "role": "child"})
    await _log_points(runtime, anna["id"], 25, last_week=True)
    await _log_points(runtime, ben["id"], 19, last_week=True)
    _set_threshold(hass, init_integration, 20)
    await runtime.coordinator.async_refresh()

    data = runtime.coordinator.data
    assert data.spotify_threshold_points == 20
    assert data.members[anna["id"]].last_week_points == 25
    assert data.members[anna["id"]].spotify_unlocked is True
    assert data.members[ben["id"]].last_week_points == 19
    assert data.members[ben["id"]].spotify_unlocked is False

    # Exactly on the threshold counts.
    await _log_points(runtime, ben["id"], 1, last_week=True)
    await runtime.coordinator.async_refresh()
    assert runtime.coordinator.data.members[ben["id"]].spotify_unlocked is True


async def test_current_week_points_do_not_unlock(hass, init_integration) -> None:
    """Points earned this week only count for *next* week's unlock."""
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna", "role": "child"})
    await _log_points(runtime, anna["id"], 500, last_week=False)
    _set_threshold(hass, init_integration, 20)
    await runtime.coordinator.async_refresh()

    member = runtime.coordinator.data.members[anna["id"]]
    assert member.points_week == 500
    assert member.last_week_points == 0
    assert member.spotify_unlocked is False


async def test_threshold_zero_means_off(hass, init_integration) -> None:
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna", "role": "child"})
    await _log_points(runtime, anna["id"], 500, last_week=True)
    _set_threshold(hass, init_integration, 0)
    await runtime.coordinator.async_refresh()

    member = runtime.coordinator.data.members[anna["id"]]
    assert member.last_week_points == 500
    assert member.spotify_unlocked is False


async def test_binary_sensor_only_for_children_and_state(hass, init_integration) -> None:
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna", "role": "child"})
    papa = await runtime.members.async_create_item({"name": "Papa", "role": "parent"})
    await _log_points(runtime, anna["id"], 30, last_week=True)
    await runtime.coordinator.async_refresh()
    await hass.async_block_till_done()

    # Parents never get the sensor.
    assert _sensor_state(hass, init_integration, papa["id"])[0] is None

    # Feature off -> unavailable (a consumer must leave Spotify alone).
    entity_id, state = _sensor_state(hass, init_integration, anna["id"])
    assert entity_id is not None
    assert state.state == "unavailable"

    _set_threshold(hass, init_integration, 20)
    await runtime.coordinator.async_refresh()
    await hass.async_block_till_done()
    state = hass.states.get(entity_id)
    assert state.state == "on"
    assert state.attributes["threshold_points"] == 20
    assert state.attributes["last_week_points"] == 30
    assert state.attributes["unlocked_next_week"] is False  # nothing earned this week yet

    await _log_points(runtime, anna["id"], 20, last_week=False)
    _set_threshold(hass, init_integration, 40)
    await runtime.coordinator.async_refresh()
    await hass.async_block_till_done()
    state = hass.states.get(entity_id)
    assert state.state == "off"  # 30 last week < 40
    assert state.attributes["points_week"] == 20
    assert state.attributes["unlocked_next_week"] is False  # 20 < 40

    _set_threshold(hass, init_integration, 15)
    await runtime.coordinator.async_refresh()
    await hass.async_block_till_done()
    state = hass.states.get(entity_id)
    assert state.state == "on"
    assert state.attributes["unlocked_next_week"] is True  # 20 >= 15


async def test_points_sensor_exposes_threshold_for_the_card(hass, init_integration) -> None:
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna", "role": "child"})
    _set_threshold(hass, init_integration, 33)
    await runtime.coordinator.async_refresh()
    await hass.async_block_till_done()

    points_sensors = [
        s
        for s in hass.states.async_all("sensor")
        if s.attributes.get("member_id") == anna["id"] and "points_week" in s.attributes
    ]
    assert points_sensors
    assert points_sensors[0].attributes["spotify_threshold_points"] == 33
