"""Tests for the automatic battery-warning task (recurrence type 'battery')."""

from __future__ import annotations

from homeassistant.helpers import entity_registry as er

from custom_components.family_tasks.battery import (
    async_compute_low_batteries,
    async_discover_battery_entity_ids,
)
from custom_components.family_tasks.const import (
    TASK_STATUS_DONE,
    TASK_STATUS_IDLE,
    TASK_STATUS_PENDING,
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


async def _add_battery_task(runtime, *, member_ids=None):
    return await runtime.tasks.async_create_item(
        {
            "name": "Batterien wechseln",
            "points": 5,
            "recurrence": {"type": "battery"},
            "rotation": {"member_ids": member_ids or []},
        }
    )


# --- battery.py: discovery / aggregation ------------------------------------


async def test_discover_battery_entity_ids_finds_sensor_and_binary_sensor(hass) -> None:
    """A numeric battery sensor and a binary low-battery sensor are both found."""
    _register_battery_sensor(hass, "sensor.kitchen_battery", state="50")
    _register_battery_sensor(hass, "binary_sensor.hallway_lowbatt", state="off")
    er.async_get(hass).async_get_or_create(
        "sensor", "test", "humidity_uid", original_device_class="humidity"
    )

    entity_ids = async_discover_battery_entity_ids(hass)

    assert entity_ids == {"sensor.kitchen_battery", "binary_sensor.hallway_lowbatt"}


async def test_disabled_registry_entity_is_not_discovered(hass) -> None:
    """A battery entity disabled in the registry is skipped."""
    entry = er.async_get(hass).async_get_or_create(
        "sensor", "test", "disabled_uid", original_device_class="battery"
    )
    er.async_get(hass).async_update_entity(
        entry.entity_id, disabled_by=er.RegistryEntryDisabler.USER
    )

    assert async_discover_battery_entity_ids(hass) == set()


async def test_compute_low_batteries_uses_default_threshold(hass) -> None:
    """A numeric battery at/below the default threshold counts as low."""
    from custom_components.family_tasks.storage import (
        async_create_battery_overrides_collection,
    )

    _register_battery_sensor(hass, "sensor.low_battery", state="15")
    _register_battery_sensor(hass, "sensor.ok_battery", state="80")
    await hass.async_block_till_done()
    overrides = await async_create_battery_overrides_collection(hass)

    low = async_compute_low_batteries(hass, overrides, default_threshold=20)

    assert [b.entity_id for b in low] == ["sensor.low_battery"]
    assert low[0].level == 15.0
    assert low[0].threshold == 20


async def test_compute_low_batteries_binary_sensor_on_counts_as_low(hass) -> None:
    """A binary_sensor battery reporting 'on' counts as low, with no level/threshold."""
    from custom_components.family_tasks.storage import (
        async_create_battery_overrides_collection,
    )

    _register_battery_sensor(hass, "binary_sensor.smoke_detector_batt", state="on")
    await hass.async_block_till_done()
    overrides = await async_create_battery_overrides_collection(hass)

    low = async_compute_low_batteries(hass, overrides, default_threshold=20)

    assert len(low) == 1
    assert low[0].entity_id == "binary_sensor.smoke_detector_batt"
    assert low[0].level is None
    assert low[0].threshold is None


async def test_excluded_battery_is_never_counted_as_low(hass) -> None:
    """An entity with a battery_override 'excluded' item is skipped entirely."""
    from custom_components.family_tasks.storage import (
        async_create_battery_overrides_collection,
    )

    _register_battery_sensor(hass, "sensor.low_battery", state="5")
    await hass.async_block_till_done()
    overrides = await async_create_battery_overrides_collection(hass)
    await overrides.async_create_item({"entity_id": "sensor.low_battery", "excluded": True})

    low = async_compute_low_batteries(hass, overrides, default_threshold=20)

    assert low == []


async def test_per_entity_threshold_override_takes_precedence(hass) -> None:
    """A custom per-entity threshold overrides the household-wide default."""
    from custom_components.family_tasks.storage import (
        async_create_battery_overrides_collection,
    )

    _register_battery_sensor(hass, "sensor.picky_battery", state="30")
    await hass.async_block_till_done()
    overrides = await async_create_battery_overrides_collection(hass)
    # Default threshold (20) would not flag a battery at 30% - a custom,
    # higher threshold (40) does.
    await overrides.async_create_item({"entity_id": "sensor.picky_battery", "threshold": 40})

    low = async_compute_low_batteries(hass, overrides, default_threshold=20)

    assert [b.entity_id for b in low] == ["sensor.picky_battery"]
    assert low[0].threshold == 40


# --- coordinator integration --------------------------------------------------


async def test_battery_task_starts_idle_when_nothing_is_low(hass, init_integration) -> None:
    """A battery task with no low batteries is idle, not due."""
    runtime = init_integration.runtime_data
    _register_battery_sensor(hass, "sensor.ok_battery", state="90")
    await hass.async_block_till_done()

    task = await _add_battery_task(runtime)
    await runtime.coordinator.async_refresh()

    status = runtime.coordinator.data.tasks[task["id"]]
    assert status.status == TASK_STATUS_IDLE
    assert status.battery_entities == []


async def test_battery_task_becomes_pending_when_a_battery_is_low(
    hass, init_integration
) -> None:
    """A monitored battery at/below the default threshold makes the task due."""
    runtime = init_integration.runtime_data
    _register_battery_sensor(hass, "sensor.kitchen_battery", state="10", friendly_name="Kitchen")
    await hass.async_block_till_done()

    task = await _add_battery_task(runtime)
    await runtime.coordinator.async_refresh()

    status = runtime.coordinator.data.tasks[task["id"]]
    assert status.status == TASK_STATUS_PENDING
    assert status.battery_entities == [
        {
            "entity_id": "sensor.kitchen_battery",
            "name": "Kitchen",
            "level": 10.0,
            "threshold": 20,
        }
    ]


async def test_excluding_the_only_low_battery_returns_task_to_idle(
    hass, init_integration
) -> None:
    """Excluding a battery from monitoring removes it from a due task's list."""
    runtime = init_integration.runtime_data
    _register_battery_sensor(hass, "sensor.kitchen_battery", state="10")
    await hass.async_block_till_done()
    task = await _add_battery_task(runtime)
    await runtime.coordinator.async_refresh()
    assert runtime.coordinator.data.tasks[task["id"]].status == TASK_STATUS_PENDING

    await runtime.battery_overrides.async_create_item(
        {"entity_id": "sensor.kitchen_battery", "excluded": True}
    )
    await runtime.coordinator.async_refresh()

    status = runtime.coordinator.data.tasks[task["id"]]
    assert status.status == TASK_STATUS_IDLE
    assert status.battery_entities == []


async def test_completing_battery_task_awards_points(hass, init_integration) -> None:
    """Marking a due battery task done logs a completion like any other task."""
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})
    _register_battery_sensor(hass, "sensor.kitchen_battery", state="10")
    await hass.async_block_till_done()
    task = await _add_battery_task(runtime, member_ids=[anna["id"]])
    await runtime.coordinator.async_refresh()
    assert runtime.coordinator.data.tasks[task["id"]].status == TASK_STATUS_PENDING

    await runtime.coordinator.async_complete_task(task["id"])

    status = runtime.coordinator.data.tasks[task["id"]]
    assert status.status == TASK_STATUS_DONE
    assert runtime.coordinator.data.members[anna["id"]].points_today == 5


async def test_battery_task_does_not_count_towards_open_tasks_while_idle(
    hass, init_integration
) -> None:
    """An idle battery task must not inflate a member's 'open tasks' count."""
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})
    _register_battery_sensor(hass, "sensor.ok_battery", state="90")
    await hass.async_block_till_done()
    await _add_battery_task(runtime, member_ids=[anna["id"]])
    await runtime.coordinator.async_refresh()

    assert runtime.coordinator.data.members[anna["id"]].open_tasks == 0
