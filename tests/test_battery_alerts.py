"""Tests for the automatic battery-alert task (v0.6): rather than requiring
an admin to set up and assign a "battery"-recurrence task, the coordinator
itself raises a one-time task the moment a monitored battery crosses at/below
its warning threshold, naming exactly that battery and assigned to every
family member linked to a Home Assistant admin account (see
FamilyTasksCoordinator._async_raise_battery_alerts in coordinator.py).
"""

from __future__ import annotations

from homeassistant.auth.const import GROUP_ID_ADMIN
from homeassistant.helpers import entity_registry as er

from custom_components.family_tasks.const import RECURRENCE_ONCE


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


async def _add_admin_member(hass, runtime, *, name="Mom"):
    """Create a family member linked to a fresh HA admin user account."""
    member = await runtime.members.async_create_item(
        {"name": name, "person_entity_id": f"person.{name.lower()}"}
    )
    user = await hass.auth.async_create_user(name, group_ids=[GROUP_ID_ADMIN])
    hass.states.async_set(f"person.{name.lower()}", "home", {"user_id": user.id})
    return member, user


def _alert_tasks(runtime):
    return [t for t in runtime.tasks.data.values() if t.get("battery_alert")]


async def test_no_alert_task_when_nothing_is_low(hass, init_integration) -> None:
    """Nothing is raised while every monitored battery is above its threshold."""
    runtime = init_integration.runtime_data
    _register_battery_sensor(hass, "sensor.ok_battery", state="90")
    await hass.async_block_till_done()

    await runtime.coordinator.async_refresh()

    assert _alert_tasks(runtime) == []


async def test_low_battery_raises_a_once_task_named_after_it(
    hass, init_integration
) -> None:
    """A numeric battery at/below the threshold raises a one-time alert task."""
    runtime = init_integration.runtime_data
    _register_battery_sensor(
        hass, "sensor.kitchen_battery", state="10", friendly_name="Kitchen"
    )
    await hass.async_block_till_done()

    await runtime.coordinator.async_refresh()

    alerts = _alert_tasks(runtime)
    assert len(alerts) == 1
    assert alerts[0]["battery_alert"] == {"entity_id": "sensor.kitchen_battery"}
    assert "Kitchen" in alerts[0]["name"]
    assert "10" in alerts[0]["name"]
    assert alerts[0]["recurrence"]["type"] == RECURRENCE_ONCE
    assert alerts[0]["points"] == 0


async def test_binary_sensor_battery_raises_alert_without_a_percentage(
    hass, init_integration
) -> None:
    """A binary_sensor battery reporting low gets a name with no level suffix."""
    runtime = init_integration.runtime_data
    _register_battery_sensor(
        hass, "binary_sensor.smoke_detector_batt", state="on", friendly_name="Smoke detector"
    )
    await hass.async_block_till_done()

    await runtime.coordinator.async_refresh()

    alerts = _alert_tasks(runtime)
    assert len(alerts) == 1
    assert "Smoke detector" in alerts[0]["name"]
    assert "%" not in alerts[0]["name"]


async def test_alert_task_is_assigned_to_admin_linked_members_only(
    hass, init_integration
) -> None:
    """rotation.member_ids is exactly the members linked to an admin account."""
    runtime = init_integration.runtime_data
    admin_member, _ = await _add_admin_member(hass, runtime, name="Mom")
    # A non-admin-linked member must not be swept in.
    await runtime.members.async_create_item({"name": "Timmy", "role": "child"})
    _register_battery_sensor(hass, "sensor.kitchen_battery", state="10")
    await hass.async_block_till_done()

    await runtime.coordinator.async_refresh()

    alerts = _alert_tasks(runtime)
    assert len(alerts) == 1
    assert alerts[0]["rotation"]["member_ids"] == [admin_member["id"]]
    assert alerts[0]["rotation"]["strategy"] == "fixed"


async def test_alert_task_with_no_admin_linked_member_is_still_created(
    hass, init_integration
) -> None:
    """No admin-linked member yet: the task is still raised, just unassigned."""
    runtime = init_integration.runtime_data
    _register_battery_sensor(hass, "sensor.kitchen_battery", state="10")
    await hass.async_block_till_done()

    await runtime.coordinator.async_refresh()

    alerts = _alert_tasks(runtime)
    assert len(alerts) == 1
    assert alerts[0]["rotation"]["member_ids"] == []


async def test_repeated_refreshes_while_still_low_do_not_duplicate_the_alert(
    hass, init_integration
) -> None:
    """A battery that stays low must not get a fresh task every refresh."""
    runtime = init_integration.runtime_data
    _register_battery_sensor(hass, "sensor.kitchen_battery", state="10")
    await hass.async_block_till_done()

    await runtime.coordinator.async_refresh()
    await runtime.coordinator.async_refresh()
    await runtime.coordinator.async_refresh()

    assert len(_alert_tasks(runtime)) == 1


async def test_completing_the_alert_lets_a_still_low_battery_raise_a_new_one(
    hass, init_integration
) -> None:
    """Once resolved, the next refresh can raise a fresh alert for the same battery.

    Battery alerts are recurrence "once" tasks, so as of v0.7 completing one
    deletes it outright (see test_once_task_is_deleted_after_completion in
    test_new_features.py) rather than leaving it around marked "Erledigt" -
    that deletion is itself what makes the entity fall out of
    _async_raise_battery_alerts' open_alert_entities set, letting a fresh
    alert be raised for it.
    """
    runtime = init_integration.runtime_data
    _register_battery_sensor(hass, "sensor.kitchen_battery", state="10")
    await hass.async_block_till_done()
    await runtime.coordinator.async_refresh()
    first_alert_id = _alert_tasks(runtime)[0]["id"]

    await runtime.coordinator.async_complete_task(first_alert_id)
    assert first_alert_id not in runtime.tasks.data
    assert first_alert_id not in runtime.coordinator.data.tasks

    await runtime.coordinator.async_refresh()

    alerts = _alert_tasks(runtime)
    assert len(alerts) == 1
    assert first_alert_id not in [a["id"] for a in alerts]


async def test_excluded_battery_never_raises_an_alert(hass, init_integration) -> None:
    """A battery excluded via battery_override is never considered low at all."""
    runtime = init_integration.runtime_data
    _register_battery_sensor(hass, "sensor.kitchen_battery", state="10")
    await hass.async_block_till_done()
    await runtime.battery_overrides.async_create_item(
        {"entity_id": "sensor.kitchen_battery", "excluded": True}
    )

    await runtime.coordinator.async_refresh()

    assert _alert_tasks(runtime) == []
