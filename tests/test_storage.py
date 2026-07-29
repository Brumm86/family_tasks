"""Tests for the task/member storage collections."""

from __future__ import annotations

import pytest
import voluptuous as vol

from custom_components.family_tasks.storage import (
    async_create_members_collection,
    async_create_tasks_collection,
)


async def test_task_create_applies_defaults(hass) -> None:
    """Creating a task fills in default points/enabled and generates an id."""
    tasks = await async_create_tasks_collection(hass)

    task = await tasks.async_create_item(
        {
            "name": "Müll rausbringen",
            "recurrence": {"type": "daily"},
            "rotation": {"member_ids": ["anna", "ben"]},
        }
    )

    assert task["id"]
    assert task["points"] == 0
    assert task["enabled"] is True
    assert task["rotation"]["strategy"] == "round_robin"
    assert task["rotation"]["current_index"] == 0


async def test_task_update_merges_nested_rotation_dict(hass) -> None:
    """Updating only current_index must not drop member_ids/strategy."""
    tasks = await async_create_tasks_collection(hass)
    task = await tasks.async_create_item(
        {
            "name": "Spülmaschine",
            "points": 5,
            "recurrence": {"type": "daily"},
            "rotation": {"member_ids": ["anna", "ben"], "strategy": "round_robin"},
        }
    )

    updated = await tasks.async_update_item(task["id"], {"rotation": {"current_index": 1}})

    assert updated["rotation"]["member_ids"] == ["anna", "ben"]
    assert updated["rotation"]["strategy"] == "round_robin"
    assert updated["rotation"]["current_index"] == 1
    # Unrelated top-level fields must survive the update untouched.
    assert updated["points"] == 5


async def test_interval_days_task_gets_anchor_date_defaulted(hass) -> None:
    """An interval_days task without an explicit anchor_date gets one (today)."""
    tasks = await async_create_tasks_collection(hass)

    task = await tasks.async_create_item(
        {
            "name": "Rauchmelder prüfen",
            "recurrence": {"type": "interval_days", "interval": 90},
            "rotation": {"member_ids": ["anna"]},
        }
    )

    assert task["recurrence"]["anchor_date"]


async def test_trigger_recurrence_requires_trigger_definition(hass) -> None:
    """A 'trigger' recurrence without a 'trigger' sub-dict must be rejected."""
    tasks = await async_create_tasks_collection(hass)

    with pytest.raises(vol.Invalid):
        await tasks.async_create_item(
            {
                "name": "Mülleimer leeren",
                "recurrence": {"type": "trigger"},
                "rotation": {"member_ids": ["anna"]},
            }
        )


async def test_state_trigger_task_stores_entity_and_target_state(hass) -> None:
    """A binary-sensor-backed trigger task persists entity_id and to_state."""
    tasks = await async_create_tasks_collection(hass)

    task = await tasks.async_create_item(
        {
            "name": "Mülleimer leeren",
            "recurrence": {
                "type": "trigger",
                "trigger": {
                    "kind": "state",
                    "entity_id": "binary_sensor.bin_full",
                    "to_state": "on",
                },
            },
            "rotation": {"member_ids": ["anna"]},
        }
    )

    assert task["recurrence"]["trigger"]["entity_id"] == "binary_sensor.bin_full"
    assert task["recurrence"]["trigger"]["to_state"] == "on"


async def test_numeric_state_trigger_requires_above_or_below(hass) -> None:
    """A numeric_state trigger without 'above'/'below' must be rejected."""
    tasks = await async_create_tasks_collection(hass)

    with pytest.raises(vol.Invalid):
        await tasks.async_create_item(
            {
                "name": "Pflanzen gießen",
                "recurrence": {
                    "type": "trigger",
                    "trigger": {
                        "kind": "numeric_state",
                        "entity_id": "sensor.soil_moisture",
                    },
                },
                "rotation": {"member_ids": ["anna"]},
            }
        )


async def test_numeric_state_trigger_task_stores_threshold(hass) -> None:
    """A numeric-sensor-backed trigger task persists the above threshold."""
    tasks = await async_create_tasks_collection(hass)

    task = await tasks.async_create_item(
        {
            "name": "Mülleimer leeren",
            "recurrence": {
                "type": "trigger",
                "trigger": {
                    "kind": "numeric_state",
                    "entity_id": "sensor.bin_level",
                    "above": 80,
                },
            },
            "rotation": {"member_ids": ["anna"]},
        }
    )

    assert task["recurrence"]["trigger"]["above"] == 80.0


async def test_member_create_applies_defaults(hass) -> None:
    """Creating a member without person_entity_id/active still succeeds."""
    members = await async_create_members_collection(hass)

    member = await members.async_create_item({"name": "Anna"})

    assert member["id"]
    assert member["active"] is True
    assert "person_entity_id" not in member or member["person_entity_id"] is None
