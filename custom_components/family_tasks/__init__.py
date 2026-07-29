"""The Family Tasks integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

import voluptuous as vol

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .const import (
    ATTR_MEMBER_ID,
    ATTR_TASK_ID,
    CARD_FILENAME,
    CARD_URL_PATH,
    DOMAIN,
    PLATFORMS,
    SERVICE_COMPLETE_TASK,
    SERVICE_SKIP_TASK,
)
from .coordinator import FamilyTasksCoordinator
from .storage import (
    CompletionLogStore,
    MemberStorageCollection,
    TaskStorageCollection,
    TriggerStateStore,
    async_create_members_collection,
    async_create_tasks_collection,
    async_create_trigger_state_store,
    async_setup_websocket_api,
)
from .trigger import TaskTriggerListener

_LOGGER = logging.getLogger(__name__)

COMPLETE_TASK_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_TASK_ID): cv.string,
        vol.Optional(ATTR_MEMBER_ID): cv.string,
    }
)
SKIP_TASK_SCHEMA = vol.Schema({vol.Required(ATTR_TASK_ID): cv.string})


@dataclass(slots=True)
class FamilyTasksRuntimeData:
    """Runtime objects stored on the config entry."""

    coordinator: FamilyTasksCoordinator
    tasks: TaskStorageCollection
    members: MemberStorageCollection
    trigger_state: TriggerStateStore


FamilyTasksConfigEntry: TypeAlias = ConfigEntry[FamilyTasksRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: FamilyTasksConfigEntry) -> bool:
    """Set up Family Tasks from a config entry."""
    tasks = await async_create_tasks_collection(hass)
    members = await async_create_members_collection(hass)

    # The websocket CRUD API is a hass-global registration; only needed once,
    # but harmless/no-ops for a second entry since single_config_entry=True
    # in the manifest already prevents that from happening in practice.
    async_setup_websocket_api(hass, tasks, members)

    completions = CompletionLogStore(hass)
    await completions.async_load()

    trigger_state = await async_create_trigger_state_store(hass)

    coordinator = FamilyTasksCoordinator(
        hass, entry, tasks, members, completions, trigger_state
    )
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = FamilyTasksRuntimeData(
        coordinator=coordinator, tasks=tasks, members=members, trigger_state=trigger_state
    )

    # Sensor-triggered tasks (recurrence type "trigger") open a new occurrence
    # as soon as their bound sensor's state matches, instead of on a schedule.
    trigger_listener = TaskTriggerListener(hass, coordinator, tasks)
    trigger_listener.async_setup()
    entry.async_on_unload(trigger_listener.async_unload)

    # Re-evaluate derived state whenever a task or member definition changes
    # (created/edited/deleted) instead of waiting for the next poll interval.
    async def _async_collection_changed(_change_set: object) -> None:
        await coordinator.async_request_refresh()

    entry.async_on_unload(
        tasks.async_add_change_set_listener(_async_collection_changed)
    )
    entry.async_on_unload(
        tasks.async_add_change_set_listener(trigger_listener.async_on_tasks_changed)
    )
    entry.async_on_unload(
        members.async_add_change_set_listener(_async_collection_changed)
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _async_register_services(hass)
    await _async_register_frontend(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: FamilyTasksConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


def _get_coordinator(hass: HomeAssistant) -> FamilyTasksCoordinator:
    """Return the coordinator for the (single) Family Tasks config entry."""
    entries: list[FamilyTasksConfigEntry] = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        raise HomeAssistantError("Family Tasks is not configured")
    return entries[0].runtime_data.coordinator


async def _async_register_frontend(hass: HomeAssistant) -> None:
    """Serve the bundled Lovelace card and auto-inject it on every dashboard.

    Uses add_extra_js_url so the card is available without the user having
    to add a Lovelace resource manually.
    """
    if hass.data.get(f"{DOMAIN}_frontend_registered"):
        return
    hass.data[f"{DOMAIN}_frontend_registered"] = True

    card_path = Path(__file__).parent / "www" / CARD_FILENAME
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL_PATH, str(card_path), cache_headers=False)]
    )
    add_extra_js_url(hass, CARD_URL_PATH)


def _async_register_services(hass: HomeAssistant) -> None:
    """Register the family_tasks.complete_task / skip_task services once."""
    if hass.services.has_service(DOMAIN, SERVICE_COMPLETE_TASK):
        return

    async def _async_complete_task(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass)
        await coordinator.async_complete_task(
            call.data[ATTR_TASK_ID], call.data.get(ATTR_MEMBER_ID)
        )

    async def _async_skip_task(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass)
        await coordinator.async_skip_task(call.data[ATTR_TASK_ID])

    hass.services.async_register(
        DOMAIN, SERVICE_COMPLETE_TASK, _async_complete_task, schema=COMPLETE_TASK_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SKIP_TASK, _async_skip_task, schema=SKIP_TASK_SCHEMA
    )
