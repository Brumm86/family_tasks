"""Tests for the v0.34 features:

- An overdue TASK_KIND_MANDATORY task now keeps pausing
  MemberSummaryData.screen_time_grant_active for as long as it's
  TASK_STATUS_AWAITING_CONFIRMATION past its deadline, not just while it's
  TASK_STATUS_OVERDUE - a child's own completion claim no longer resumes
  screen time before a parent actually confirms it (see the
  screen_time_paused_members computation in
  FamilyTasksCoordinator._async_update_data).
- A "trigger" (sensor-based) task's trigger definition may now set
  "auto_complete_on_normalize": True (see TASK_TRIGGER_STATE_SCHEMA /
  TASK_TRIGGER_NUMERIC_STATE_SCHEMA in storage.py). When set,
  trigger.TaskTriggerListener completes the open occurrence automatically
  the moment the bound sensor transitions back out of the condition that
  opened it, via the new FamilyTasksCoordinator.async_handle_sensor_normalized
  / async_complete_task(..., skip_confirmation=True) path - bypassing a
  parent-confirmation step even for a task assigned to a "child" member.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from homeassistant.util import dt as dt_util

from custom_components.family_tasks.const import (
    TASK_STATUS_AWAITING_CONFIRMATION,
    TASK_STATUS_DONE,
    TASK_STATUS_IDLE,
    TASK_STATUS_OVERDUE,
    TASK_STATUS_PENDING,
)


def _find_confirmation_task(runtime, original_task_id: str) -> dict | None:
    for task in runtime.tasks.data.values():
        confirms = task.get("confirms")
        if confirms and confirms["task_id"] == original_task_id:
            return task
    return None


async def _add_mandatory_task(runtime, *, member_ids, **overrides):
    payload = {
        "name": "Zimmer aufräumen",
        "points": 5,
        "kind": "mandatory",
        "recurrence": {"type": "daily"},
        "rotation": {"member_ids": member_ids, "strategy": "fixed"},
        "overdue_after_minutes": 30,
    }
    payload.update(overrides)
    return await runtime.tasks.async_create_item(payload)


async def _refresh_at_local(runtime, local_dt) -> None:
    with (
        patch.object(dt_util, "now", return_value=local_dt),
        patch.object(dt_util, "utcnow", return_value=dt_util.as_utc(local_dt)),
    ):
        await runtime.coordinator.async_refresh()


async def _complete_at_local(runtime, task_id, local_dt, **kwargs) -> None:
    with (
        patch.object(dt_util, "now", return_value=local_dt),
        patch.object(dt_util, "utcnow", return_value=dt_util.as_utc(local_dt)),
    ):
        await runtime.coordinator.async_complete_task(task_id, **kwargs)


# --- Screen-time pause survives an open parent confirmation -----------------


async def test_overdue_mandatory_task_awaiting_confirmation_still_pauses_grant(
    hass, init_integration
) -> None:
    """A child's completion claim on an overdue mandatory task must not
    resume screen time by itself - only an actual parent confirmation does.
    """
    runtime = init_integration.runtime_data
    timmy = await runtime.members.async_create_item({"name": "Timmy", "role": "child"})
    await runtime.members.async_create_item({"name": "Mom", "role": "parent"})

    frozen_local = dt_util.now().replace(hour=12, minute=0, second=0, microsecond=0)
    due_time_str = (frozen_local - timedelta(hours=2)).strftime("%H:%M")
    task = await _add_mandatory_task(
        runtime, member_ids=[timmy["id"]], due_time=due_time_str
    )

    await _refresh_at_local(runtime, frozen_local)
    assert runtime.coordinator.data.tasks[task["id"]].status == TASK_STATUS_OVERDUE
    assert runtime.coordinator.data.members[timmy["id"]].screen_time_grant_active is False

    await _complete_at_local(runtime, task["id"], frozen_local)
    await _refresh_at_local(runtime, frozen_local)

    status = runtime.coordinator.data.tasks[task["id"]]
    assert status.status == TASK_STATUS_AWAITING_CONFIRMATION
    # This is the actual v0.34 fix: pre-v0.34 this flipped to True the
    # instant the child's claim was logged, before any parent sign-off.
    assert runtime.coordinator.data.members[timmy["id"]].screen_time_grant_active is False


async def test_parent_confirming_resumes_the_grant(hass, init_integration) -> None:
    """Once a parent actually confirms, the pause lifts."""
    runtime = init_integration.runtime_data
    timmy = await runtime.members.async_create_item({"name": "Timmy", "role": "child"})
    await runtime.members.async_create_item({"name": "Mom", "role": "parent"})

    frozen_local = dt_util.now().replace(hour=12, minute=0, second=0, microsecond=0)
    due_time_str = (frozen_local - timedelta(hours=2)).strftime("%H:%M")
    task = await _add_mandatory_task(
        runtime, member_ids=[timmy["id"]], due_time=due_time_str
    )
    await _refresh_at_local(runtime, frozen_local)
    await _complete_at_local(runtime, task["id"], frozen_local)
    await _refresh_at_local(runtime, frozen_local)
    assert runtime.coordinator.data.members[timmy["id"]].screen_time_grant_active is False

    confirmation_task = _find_confirmation_task(runtime, task["id"])
    assert confirmation_task is not None
    await _complete_at_local(runtime, confirmation_task["id"], frozen_local)
    await _refresh_at_local(runtime, frozen_local)

    assert runtime.coordinator.data.tasks[task["id"]].status == TASK_STATUS_DONE
    assert runtime.coordinator.data.members[timmy["id"]].screen_time_grant_active is True


async def test_parent_rejecting_leaves_grant_paused_while_still_overdue(
    hass, init_integration
) -> None:
    """A rejected claim falls back to TASK_STATUS_OVERDUE - still paused."""
    runtime = init_integration.runtime_data
    timmy = await runtime.members.async_create_item({"name": "Timmy", "role": "child"})
    await runtime.members.async_create_item({"name": "Mom", "role": "parent"})

    frozen_local = dt_util.now().replace(hour=12, minute=0, second=0, microsecond=0)
    due_time_str = (frozen_local - timedelta(hours=2)).strftime("%H:%M")
    task = await _add_mandatory_task(
        runtime, member_ids=[timmy["id"]], due_time=due_time_str
    )
    await _refresh_at_local(runtime, frozen_local)
    await _complete_at_local(runtime, task["id"], frozen_local)
    await _refresh_at_local(runtime, frozen_local)

    confirmation_task = _find_confirmation_task(runtime, task["id"])
    await _refresh_at_local(runtime, frozen_local)
    with (
        patch.object(dt_util, "now", return_value=frozen_local),
        patch.object(dt_util, "utcnow", return_value=dt_util.as_utc(frozen_local)),
    ):
        await runtime.coordinator.async_skip_task(confirmation_task["id"])
    await _refresh_at_local(runtime, frozen_local)

    assert runtime.coordinator.data.tasks[task["id"]].status == TASK_STATUS_OVERDUE
    assert runtime.coordinator.data.members[timmy["id"]].screen_time_grant_active is False


async def test_awaiting_confirmation_before_deadline_does_not_pause(
    hass, init_integration
) -> None:
    """Completing early (before the Karenzzeit has even elapsed) never pauses."""
    runtime = init_integration.runtime_data
    timmy = await runtime.members.async_create_item({"name": "Timmy", "role": "child"})
    await runtime.members.async_create_item({"name": "Mom", "role": "parent"})

    frozen_local = dt_util.now().replace(hour=12, minute=0, second=0, microsecond=0)
    # Due an hour from now - nowhere near overdue yet.
    due_time_str = (frozen_local + timedelta(hours=1)).strftime("%H:%M")
    task = await _add_mandatory_task(
        runtime, member_ids=[timmy["id"]], due_time=due_time_str
    )
    await _refresh_at_local(runtime, frozen_local)
    assert runtime.coordinator.data.tasks[task["id"]].status == TASK_STATUS_PENDING

    await _complete_at_local(runtime, task["id"], frozen_local)
    await _refresh_at_local(runtime, frozen_local)

    assert (
        runtime.coordinator.data.tasks[task["id"]].status
        == TASK_STATUS_AWAITING_CONFIRMATION
    )
    assert runtime.coordinator.data.members[timmy["id"]].screen_time_grant_active is True


# --- Sensor auto-complete on normalize ---------------------------------------


async def _add_state_trigger_task(
    runtime,
    *,
    member_ids,
    entity_id="binary_sensor.bin_full",
    auto_complete_on_normalize=True,
    **overrides,
):
    payload = {
        "name": "Mülleimer leeren",
        "points": 5,
        "recurrence": {
            "type": "trigger",
            "trigger": {
                "kind": "state",
                "entity_id": entity_id,
                "to_state": "on",
                "auto_complete_on_normalize": auto_complete_on_normalize,
            },
        },
        "rotation": {"member_ids": member_ids},
    }
    payload.update(overrides)
    return await runtime.tasks.async_create_item(payload)


async def _add_numeric_trigger_task(
    runtime,
    *,
    member_ids,
    entity_id="sensor.bin_level",
    above=80,
    auto_complete_on_normalize=True,
):
    return await runtime.tasks.async_create_item(
        {
            "name": "Mülleimer leeren",
            "points": 5,
            "recurrence": {
                "type": "trigger",
                "trigger": {
                    "kind": "numeric_state",
                    "entity_id": entity_id,
                    "above": above,
                    "auto_complete_on_normalize": auto_complete_on_normalize,
                },
            },
            "rotation": {"member_ids": member_ids},
        }
    )


async def test_state_trigger_auto_completes_when_sensor_normalizes(
    hass, init_integration
) -> None:
    """Sensor leaving the matching state completes the open occurrence."""
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})
    hass.states.async_set("binary_sensor.bin_full", "off")
    await hass.async_block_till_done()
    task = await _add_state_trigger_task(runtime, member_ids=[anna["id"]])
    await runtime.coordinator.async_refresh()

    hass.states.async_set("binary_sensor.bin_full", "on")
    await hass.async_block_till_done()
    assert runtime.coordinator.data.tasks[task["id"]].status == TASK_STATUS_PENDING

    hass.states.async_set("binary_sensor.bin_full", "off")
    await hass.async_block_till_done()

    assert runtime.trigger_state.get(task["id"]) is None
    assert runtime.coordinator.data.tasks[task["id"]].status == TASK_STATUS_IDLE
    assert runtime.coordinator.data.members[anna["id"]].points_today == 5


async def test_state_trigger_without_flag_stays_open_when_sensor_normalizes(
    hass, init_integration
) -> None:
    """Default behavior (flag off) is unchanged - normalizing does nothing."""
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})
    hass.states.async_set("binary_sensor.bin_full", "off")
    await hass.async_block_till_done()
    task = await _add_state_trigger_task(
        runtime, member_ids=[anna["id"]], auto_complete_on_normalize=False
    )
    await runtime.coordinator.async_refresh()

    hass.states.async_set("binary_sensor.bin_full", "on")
    await hass.async_block_till_done()
    hass.states.async_set("binary_sensor.bin_full", "off")
    await hass.async_block_till_done()

    assert runtime.trigger_state.get(task["id"]) is not None
    assert runtime.coordinator.data.tasks[task["id"]].status == TASK_STATUS_PENDING
    assert runtime.coordinator.data.members[anna["id"]].points_today == 0


async def test_numeric_state_trigger_auto_completes_crossing_back(
    hass, init_integration
) -> None:
    """An 'above' numeric trigger normalizes once the value drops back down."""
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})
    hass.states.async_set("sensor.bin_level", "50")
    await hass.async_block_till_done()
    task = await _add_numeric_trigger_task(runtime, member_ids=[anna["id"]], above=80)
    await runtime.coordinator.async_refresh()

    hass.states.async_set("sensor.bin_level", "90")
    await hass.async_block_till_done()
    assert runtime.trigger_state.get(task["id"]) is not None

    hass.states.async_set("sensor.bin_level", "50")
    await hass.async_block_till_done()

    assert runtime.trigger_state.get(task["id"]) is None
    assert runtime.coordinator.data.members[anna["id"]].points_today == 5


async def test_auto_complete_on_normalize_skips_parent_confirmation_for_child(
    hass, init_integration
) -> None:
    """A child-assigned trigger task still auto-completes without raising a
    parent confirmation task - the sensor itself is treated as proof."""
    runtime = init_integration.runtime_data
    timmy = await runtime.members.async_create_item({"name": "Timmy", "role": "child"})
    await runtime.members.async_create_item({"name": "Mom", "role": "parent"})
    hass.states.async_set("binary_sensor.bin_full", "off")
    await hass.async_block_till_done()
    task = await _add_state_trigger_task(runtime, member_ids=[timmy["id"]])
    await runtime.coordinator.async_refresh()

    hass.states.async_set("binary_sensor.bin_full", "on")
    await hass.async_block_till_done()
    hass.states.async_set("binary_sensor.bin_full", "off")
    await hass.async_block_till_done()

    status = runtime.coordinator.data.tasks[task["id"]]
    assert status.status == TASK_STATUS_IDLE
    assert status.last_completed_by == timmy["id"]
    assert runtime.coordinator.data.members[timmy["id"]].points_today == 5
    assert _find_confirmation_task(runtime, task["id"]) is None


async def test_normalizing_with_no_open_occurrence_is_a_no_op(
    hass, init_integration
) -> None:
    """Turning the flag on after the sensor already normalized does nothing."""
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})
    hass.states.async_set("binary_sensor.bin_full", "off")
    await hass.async_block_till_done()
    task = await _add_state_trigger_task(runtime, member_ids=[anna["id"]])
    await runtime.coordinator.async_refresh()

    # No trigger has ever fired - nothing open to complete.
    await runtime.coordinator.async_handle_sensor_normalized(task["id"])

    assert runtime.trigger_state.get(task["id"]) is None
    assert runtime.coordinator.data.members[anna["id"]].points_today == 0
