"""The Family Tasks integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

import voluptuous as vol

from homeassistant.components import persistent_notification
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import collection
from homeassistant.helpers import config_validation as cv
from homeassistant.loader import async_get_integration

from .const import (
    ATTR_MEMBER_ID,
    ATTR_SUBTASK_ID,
    ATTR_TASK_ID,
    CARD_FILENAME,
    CARD_URL_PATH,
    CONF_MEMBER_NOTIFY_SERVICE,
    DOMAIN,
    EVENT_TASK_ASSIGNED,
    LEADERBOARD_CARD_FILENAME,
    LEADERBOARD_CARD_URL_PATH,
    PLATFORMS,
    SERVICE_COMPLETE_TASK,
    SERVICE_SKIP_TASK,
    SERVICE_TOGGLE_SUBTASK,
)
from .battery import BatteryStateListener
from .coordinator import FamilyTasksCoordinator
from .storage import (
    BatteryOverrideStorageCollection,
    ChecklistStateStore,
    CompletionLogStore,
    MemberStorageCollection,
    RewardRedemptionStorageCollection,
    RewardStorageCollection,
    TaskStorageCollection,
    TriggerStateStore,
    WeeklyBonusStateStore,
    async_create_battery_overrides_collection,
    async_create_checklist_state_store,
    async_create_members_collection,
    async_create_reward_redemptions_collection,
    async_create_rewards_collection,
    async_create_tasks_collection,
    async_create_trigger_state_store,
    async_create_weekly_bonus_state_store,
    async_member_id_for_context,
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
TOGGLE_SUBTASK_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_TASK_ID): cv.string,
        vol.Required(ATTR_SUBTASK_ID): cv.string,
        vol.Optional(ATTR_MEMBER_ID): cv.string,
    }
)


@dataclass(slots=True)
class FamilyTasksRuntimeData:
    """Runtime objects stored on the config entry."""

    coordinator: FamilyTasksCoordinator
    tasks: TaskStorageCollection
    members: MemberStorageCollection
    trigger_state: TriggerStateStore
    battery_overrides: BatteryOverrideStorageCollection
    checklist_state: ChecklistStateStore
    rewards: RewardStorageCollection
    reward_redemptions: RewardRedemptionStorageCollection
    weekly_bonus_state: WeeklyBonusStateStore


FamilyTasksConfigEntry: TypeAlias = ConfigEntry[FamilyTasksRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: FamilyTasksConfigEntry) -> bool:
    """Set up Family Tasks from a config entry."""
    tasks = await async_create_tasks_collection(hass)
    members = await async_create_members_collection(hass)
    battery_overrides = await async_create_battery_overrides_collection(hass)
    rewards = await async_create_rewards_collection(hass)
    reward_redemptions = await async_create_reward_redemptions_collection(hass)

    # Created before the websocket API is set up below - the reward-redeem
    # command needs the completion log to work out a member's current
    # available point balance (see ws_redeem_reward in storage.py).
    completions = CompletionLogStore(hass)
    await completions.async_load()

    # The websocket CRUD API is a hass-global registration; only needed once,
    # but harmless/no-ops for a second entry since single_config_entry=True
    # in the manifest already prevents that from happening in practice.
    async_setup_websocket_api(
        hass, entry, tasks, members, battery_overrides, rewards, reward_redemptions, completions
    )

    trigger_state = await async_create_trigger_state_store(hass)
    checklist_state = await async_create_checklist_state_store(hass)
    weekly_bonus_state = await async_create_weekly_bonus_state_store(hass)

    coordinator = FamilyTasksCoordinator(
        hass,
        entry,
        tasks,
        members,
        completions,
        trigger_state,
        battery_overrides,
        checklist_state,
        reward_redemptions,
        weekly_bonus_state,
    )
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = FamilyTasksRuntimeData(
        coordinator=coordinator,
        tasks=tasks,
        members=members,
        trigger_state=trigger_state,
        battery_overrides=battery_overrides,
        checklist_state=checklist_state,
        rewards=rewards,
        reward_redemptions=reward_redemptions,
        weekly_bonus_state=weekly_bonus_state,
    )

    # Sensor-triggered tasks (recurrence type "trigger") open a new occurrence
    # as soon as their bound sensor's state matches, instead of on a schedule.
    trigger_listener = TaskTriggerListener(hass, coordinator, tasks)
    trigger_listener.async_setup()
    entry.async_on_unload(trigger_listener.async_unload)

    # Battery tasks (recurrence type "battery") aggregate every battery-level
    # entity HA knows about; this requests a refresh as soon as one of them
    # changes state instead of waiting for the next poll interval.
    battery_listener = BatteryStateListener(hass, coordinator)
    battery_listener.async_setup()
    entry.async_on_unload(battery_listener.async_unload)
    entry.async_on_unload(coordinator.async_add_listener(battery_listener.async_resubscribe))

    # Re-evaluate derived state whenever a task, member, or battery-override
    # definition changes (created/edited/deleted) instead of waiting for the
    # next poll interval.
    async def _async_collection_changed(_change_set: object) -> None:
        await coordinator.async_request_refresh()

    entry.async_on_unload(
        tasks.async_add_change_set_listener(_async_collection_changed)
    )
    entry.async_on_unload(
        tasks.async_add_change_set_listener(trigger_listener.async_on_tasks_changed)
    )
    entry.async_on_unload(
        tasks.async_add_change_set_listener(_async_notify_new_task_assignments(hass, members))
    )
    entry.async_on_unload(
        members.async_add_change_set_listener(_async_collection_changed)
    )
    entry.async_on_unload(
        battery_overrides.async_add_change_set_listener(_async_collection_changed)
    )
    # A redemption changes the acting member's points_available (v0.9) - see
    # MemberSummaryData.points_available in coordinator.py - so the
    # leaderboard card's balance display updates right away instead of
    # waiting for the next poll interval.
    entry.async_on_unload(
        reward_redemptions.async_add_change_set_listener(_async_collection_changed)
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


async def _async_notify_member(
    hass: HomeAssistant, member_id: str, member: dict, task_id: str, task_name: str
) -> None:
    """Best-effort notify one member that a new task now involves them.

    Two channels, same reasoning as CONF_MEMBER_NOTIFY_SERVICE in const.py:
    a persistent_notification is always raised (visible inside Home
    Assistant's own frontend/companion-app notification panel), but that
    alone never reaches the phone as an actual push notification - only
    calling the member's own configured notify.* service (Home Assistant
    Companion App) does that, so it's used in addition whenever set.
    EVENT_TASK_ASSIGNED fires unconditionally on top, for a household that
    wants to react some other way entirely (same extension-point pattern as
    EVENT_REWARD_REDEEMED).
    """
    title = "Family Tasks"
    message = f"Neue Aufgabe: {task_name}"

    try:
        persistent_notification.async_create(
            hass, message, title=title, notification_id=f"{DOMAIN}_task_{task_id}_{member_id}"
        )
    except Exception as err:  # noqa: BLE001 - best-effort, must never block task creation
        _LOGGER.warning("Failed to raise persistent notification for %s: %s", member_id, err)

    notify_service = member.get(CONF_MEMBER_NOTIFY_SERVICE)
    if notify_service:
        try:
            await hass.services.async_call(
                "notify", notify_service, {"title": title, "message": message}, blocking=False
            )
        except HomeAssistantError as err:
            _LOGGER.warning("Failed to call notify.%s for %s: %s", notify_service, member_id, err)

    hass.bus.async_fire(
        EVENT_TASK_ASSIGNED,
        {
            "member_id": member_id,
            "member_name": member.get("name"),
            "task_id": task_id,
            "task_name": task_name,
        },
    )


def _async_notify_new_task_assignments(hass: HomeAssistant, members: MemberStorageCollection):
    """Build a tasks change-set listener that notifies newly assigned members.

    Registered alongside the other family_tasks.task change-set listeners in
    async_setup_entry (see tasks.async_add_change_set_listener below) -
    fires for a task an admin creates by hand as well as one the coordinator
    raises automatically (a parent-confirmation task, a battery alert), since
    both go through TaskStorageCollection.async_create_item the same way.
    Only "added" changes are notified - an edit that merely changes who a
    task is assigned to isn't treated as "a new task" here.
    """

    async def _listener(change_sets) -> None:
        for change in change_sets:
            if change.change_type != collection.CHANGE_ADDED:
                continue
            item = change.item
            member_ids = (item.get("rotation") or {}).get("member_ids") or []
            if not member_ids:
                continue
            task_name = item.get("name", "Aufgabe")
            for member_id in member_ids:
                member = members.data.get(member_id)
                if not member or not member.get("active", True):
                    continue
                await _async_notify_member(hass, member_id, member, item.get("id", ""), task_name)

    return _listener


async def _async_register_frontend(hass: HomeAssistant) -> None:
    """Serve the bundled Lovelace cards and auto-inject them on every dashboard.

    Uses add_extra_js_url so the cards are available without the user having
    to add a Lovelace resource manually.

    The injected URLs carry a "?v=<integration version>" cache-buster. Static
    paths are registered with cache_headers=False, but that alone doesn't
    stop every client from caching the file: browsers may still apply
    heuristic caching, and Home Assistant's installed-PWA/companion-app
    service worker in particular caches same-URL requests aggressively
    regardless of response headers. Without a version-changing URL, a device
    that already cached an older family-tasks-card.js keeps using it after an
    update - including one from before some websocket field or attribute it
    now relies on existed - which is exactly the "cards occasionally don't
    load correctly" symptom: it isn't a load failure so much as some devices
    silently running stale, incompatible JS. Bumping the query string on every
    release forces a fresh fetch instead.
    """
    if hass.data.get(f"{DOMAIN}_frontend_registered"):
        return
    hass.data[f"{DOMAIN}_frontend_registered"] = True

    integration = await async_get_integration(hass, DOMAIN)
    cache_buster = f"v={integration.version}"

    www_dir = Path(__file__).parent / "www"
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(CARD_URL_PATH, str(www_dir / CARD_FILENAME), cache_headers=False),
            StaticPathConfig(
                LEADERBOARD_CARD_URL_PATH,
                str(www_dir / LEADERBOARD_CARD_FILENAME),
                cache_headers=False,
            ),
        ]
    )
    add_extra_js_url(hass, f"{CARD_URL_PATH}?{cache_buster}")
    add_extra_js_url(hass, f"{LEADERBOARD_CARD_URL_PATH}?{cache_buster}")


def _async_register_services(hass: HomeAssistant) -> None:
    """Register the family_tasks.complete_task / skip_task services once."""
    if hass.services.has_service(DOMAIN, SERVICE_COMPLETE_TASK):
        return

    async def _async_resolve_member_id(call: ServiceCall) -> str | None:
        """Who actually made this call, if it's explicit or resolvable.

        An explicit ``member_id`` in call.data always wins (e.g. an
        automation acting on a specific member's behalf). Otherwise, for a
        call originating from a logged-in frontend session (the Lovelace
        card's "Erledigt"/checklist controls, which never set member_id
        themselves - see family-tasks-card.js), HA's own service-call
        machinery already stamps call.context.user_id with the calling
        user's id; async_member_id_for_context resolves that to a family
        member via the same person_entity_id link used elsewhere (redemption,
        create_own_task). Without this, a task shared between several fixed
        assignees always attributed every completion to member_ids[0]
        regardless of who actually pressed the button - see
        FamilyTasksCoordinator.async_complete_task's docstring.
        """
        coordinator = _get_coordinator(hass)
        member_id = call.data.get(ATTR_MEMBER_ID)
        if member_id is not None:
            return member_id
        return await async_member_id_for_context(hass, coordinator.members, call.context)

    async def _async_complete_task(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass)
        member_id = await _async_resolve_member_id(call)
        await coordinator.async_complete_task(call.data[ATTR_TASK_ID], member_id)

    async def _async_skip_task(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass)
        await coordinator.async_skip_task(call.data[ATTR_TASK_ID])

    async def _async_toggle_subtask(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass)
        member_id = await _async_resolve_member_id(call)
        await coordinator.async_toggle_subtask(
            call.data[ATTR_TASK_ID], call.data[ATTR_SUBTASK_ID], member_id
        )

    hass.services.async_register(
        DOMAIN, SERVICE_COMPLETE_TASK, _async_complete_task, schema=COMPLETE_TASK_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SKIP_TASK, _async_skip_task, schema=SKIP_TASK_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_TOGGLE_SUBTASK,
        _async_toggle_subtask,
        schema=TOGGLE_SUBTASK_SCHEMA,
    )
