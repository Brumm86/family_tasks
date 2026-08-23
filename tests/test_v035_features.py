"""Tests for the v0.35 feature: an auto-generated battery-alert task
(RECURRENCE_ONCE, tagged "battery_alert" - see
FamilyTasksCoordinator._async_raise_battery_alerts) can now optionally
complete itself once the battery it names recovers - back above its warning
threshold for a numeric sensor, or no longer reporting low for a
binary_sensor - instead of staying open until a family member completes or
skips it by hand. Off by default; controlled by the new household-wide
CONF_BATTERY_ALERT_AUTO_COMPLETE_ON_RECOVERY option (see config_flow.py).

The other half of v0.35 - an "Ausgeschlossene anzeigen"/"Ausgeschlossene
ausblenden" toggle for the "Batterien" card section, filtering out
already-excluded battery entities by default - is a pure family-tasks-card.js
UI change with no backend surface, so it has no coverage here; see the
project's jsdom-based smoke check (not part of this pytest suite, see
project_family_tasks_test_env memory) for that instead.
"""

from __future__ import annotations

from homeassistant.helpers import entity_registry as er

from custom_components.family_tasks.const import (
    CONF_BATTERY_ALERT_AUTO_COMPLETE_ON_RECOVERY,
)


def _register_battery_sensor(hass, entity_id, *, state, friendly_name=None):
    domain, object_id = entity_id.split(".", 1)
    er.async_get(hass).async_get_or_create(
        domain,
        "test",
        f"{object_id}_uid",
        suggested_object_id=object_id,
        original_device_class="battery",
    )
    hass.states.async_set(entity_id, state, {"friendly_name": friendly_name or entity_id})


def _alert_tasks(runtime):
    return [t for t in runtime.tasks.data.values() if t.get("battery_alert")]


def _enable_auto_complete_on_recovery(hass, config_entry) -> None:
    hass.config_entries.async_update_entry(
        config_entry,
        options={CONF_BATTERY_ALERT_AUTO_COMPLETE_ON_RECOVERY: True},
    )


async def test_recovered_alert_task_stays_open_by_default(
    hass, init_integration
) -> None:
    """Without the new option, a recovered battery's alert task is left open
    exactly as before v0.35 - someone still has to complete/skip it by hand.
    """
    runtime = init_integration.runtime_data
    _register_battery_sensor(hass, "sensor.kitchen_battery", state="10")
    await hass.async_block_till_done()
    await runtime.coordinator.async_refresh()
    alert_id = _alert_tasks(runtime)[0]["id"]

    hass.states.async_set(
        "sensor.kitchen_battery", "90", {"friendly_name": "sensor.kitchen_battery"}
    )
    await hass.async_block_till_done()
    await runtime.coordinator.async_refresh()
    await hass.async_block_till_done()

    alerts = _alert_tasks(runtime)
    assert len(alerts) == 1
    assert alerts[0]["id"] == alert_id
    assert runtime.completions.get_last_entry(alert_id, alerts[0]["recurrence"]["anchor_date"]) is None


async def test_recovered_alert_task_auto_completes_when_enabled(
    hass, init_integration
) -> None:
    """With the option on, the same recovery instead completes the task -
    logged (0 points, since battery-alert tasks are always worth 0) and
    deleted, same as a manual "Erledigt" on a RECURRENCE_ONCE task.
    """
    runtime = init_integration.runtime_data
    _enable_auto_complete_on_recovery(hass, init_integration)
    _register_battery_sensor(hass, "sensor.kitchen_battery", state="10")
    await hass.async_block_till_done()
    await runtime.coordinator.async_refresh()
    alert = _alert_tasks(runtime)[0]
    alert_id = alert["id"]
    period_key = alert["recurrence"]["anchor_date"]

    hass.states.async_set(
        "sensor.kitchen_battery", "90", {"friendly_name": "sensor.kitchen_battery"}
    )
    await hass.async_block_till_done()
    await runtime.coordinator.async_refresh()
    # The completion itself is scheduled via hass.async_create_task rather
    # than awaited inline (see the comment in _async_raise_battery_alerts for
    # why) - block_till_done lets it, and the refresh it triggers, finish.
    await hass.async_block_till_done()

    assert alert_id not in runtime.tasks.data
    entry = runtime.completions.get_last_entry(alert_id, period_key)
    assert entry is not None
    assert entry["points_awarded"] == 0
    assert _alert_tasks(runtime) == []


async def test_still_low_battery_alert_is_never_auto_completed(
    hass, init_integration
) -> None:
    """The option only reacts to *recovery* - a battery that never stops
    being low must not have its alert task completed out from under it.
    """
    runtime = init_integration.runtime_data
    _enable_auto_complete_on_recovery(hass, init_integration)
    _register_battery_sensor(hass, "sensor.kitchen_battery", state="10")
    await hass.async_block_till_done()

    await runtime.coordinator.async_refresh()
    await hass.async_block_till_done()
    await runtime.coordinator.async_refresh()
    await hass.async_block_till_done()

    alerts = _alert_tasks(runtime)
    assert len(alerts) == 1
    assert runtime.completions.entries == []


async def test_recovery_then_relapse_raises_a_fresh_alert(
    hass, init_integration
) -> None:
    """Once auto-completed on recovery, the battery going low again later
    raises a brand new alert task, same as completing one by hand today
    (see test_completing_the_alert_lets_a_still_low_battery_raise_a_new_one
    in test_battery_alerts.py).
    """
    runtime = init_integration.runtime_data
    _enable_auto_complete_on_recovery(hass, init_integration)
    _register_battery_sensor(hass, "sensor.kitchen_battery", state="10")
    await hass.async_block_till_done()
    await runtime.coordinator.async_refresh()
    first_alert_id = _alert_tasks(runtime)[0]["id"]

    hass.states.async_set(
        "sensor.kitchen_battery", "90", {"friendly_name": "sensor.kitchen_battery"}
    )
    await hass.async_block_till_done()
    await runtime.coordinator.async_refresh()
    await hass.async_block_till_done()
    assert _alert_tasks(runtime) == []

    hass.states.async_set(
        "sensor.kitchen_battery", "10", {"friendly_name": "sensor.kitchen_battery"}
    )
    await hass.async_block_till_done()
    await runtime.coordinator.async_refresh()
    await hass.async_block_till_done()

    alerts = _alert_tasks(runtime)
    assert len(alerts) == 1
    assert alerts[0]["id"] != first_alert_id


async def test_binary_sensor_alert_auto_completes_when_no_longer_low(
    hass, init_integration
) -> None:
    """Recovery for a binary_sensor battery means it stops reporting "on"
    (HA's low-battery convention) - same auto-complete path as the numeric
    case, just without a percentage involved.
    """
    runtime = init_integration.runtime_data
    _enable_auto_complete_on_recovery(hass, init_integration)
    _register_battery_sensor(
        hass, "binary_sensor.smoke_detector_batt", state="on", friendly_name="Smoke detector"
    )
    await hass.async_block_till_done()
    await runtime.coordinator.async_refresh()
    alert_id = _alert_tasks(runtime)[0]["id"]

    hass.states.async_set(
        "binary_sensor.smoke_detector_batt", "off", {"friendly_name": "Smoke detector"}
    )
    await hass.async_block_till_done()
    await runtime.coordinator.async_refresh()
    await hass.async_block_till_done()

    assert alert_id not in runtime.tasks.data
    assert _alert_tasks(runtime) == []
