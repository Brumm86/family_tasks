"""Tests for the v0.23 features:

- Household-wide default rotation strategy (CONF_DEFAULT_ROTATION_STRATEGY):
  previously this options-flow field was accepted and stored, but nothing in
  the integration ever actually read it back, so the card's "+ Aufgabe
  hinzufügen" form always pre-selected "Reihum" (round_robin) regardless of
  what a household had configured here. FamilyTasksCoordinator now reads it
  fresh on every refresh (same pattern as the weekly-winner-bonus options,
  see test_v014_features.py) and exposes it as
  FamilyTasksData.default_rotation_strategy / the
  "default_rotation_strategy" attribute on every member's points sensor - see
  FamilyTasksMemberPointsSensor.extra_state_attributes in sensor.py.
"""

from __future__ import annotations

from custom_components.family_tasks.const import (
    CONF_DEFAULT_ROTATION_STRATEGY,
    DEFAULT_ROTATION_STRATEGY,
    ROTATION_STRATEGY_FIXED,
)


async def test_default_rotation_strategy_defaults_to_round_robin(
    hass, init_integration
) -> None:
    runtime = init_integration.runtime_data
    await runtime.coordinator.async_refresh()

    assert runtime.coordinator.data.default_rotation_strategy == DEFAULT_ROTATION_STRATEGY
    assert runtime.coordinator.data.default_rotation_strategy == "round_robin"


async def test_default_rotation_strategy_reflects_configured_option(
    hass, init_integration
) -> None:
    runtime = init_integration.runtime_data
    hass.config_entries.async_update_entry(
        init_integration,
        options={CONF_DEFAULT_ROTATION_STRATEGY: ROTATION_STRATEGY_FIXED},
    )
    await runtime.coordinator.async_refresh()

    assert runtime.coordinator.data.default_rotation_strategy == ROTATION_STRATEGY_FIXED


async def test_default_rotation_strategy_exposed_on_member_points_sensor(
    hass, init_integration
) -> None:
    """The card reads this off any member's points sensor - see
    _defaultRotationStrategy in family-tasks-card.js - so it needs to
    actually reach extra_state_attributes, not just FamilyTasksData."""
    runtime = init_integration.runtime_data
    hass.config_entries.async_update_entry(
        init_integration,
        options={CONF_DEFAULT_ROTATION_STRATEGY: ROTATION_STRATEGY_FIXED},
    )
    anna = await runtime.members.async_create_item({"name": "Anna"})
    await runtime.coordinator.async_refresh()
    await hass.async_block_till_done()

    sensor_state = next(
        state
        for state in hass.states.async_all()
        if state.attributes.get("member_id") == anna["id"]
        and "points_week" in state.attributes
    )
    assert sensor_state.attributes["default_rotation_strategy"] == ROTATION_STRATEGY_FIXED
