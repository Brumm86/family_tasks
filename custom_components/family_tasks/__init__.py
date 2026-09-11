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
    ATTR_NOTE,
    ATTR_SUBTASK_ID,
    ATTR_TASK_ID,
    CARD_FILENAME,
    CARD_URL_PATH,
    CONF_MEMBER_NOTIFY_SERVICE,
    CONF_VACATION_MODE_DEFAULT,
    DEFAULT_VACATION_MODE,
    DOMAIN,
    EVENT_TASK_ASSIGNED,
    PLATFORMS,
    SERVICE_CLAIM_TASK,
    SERVICE_COMPLETE_TASK,
    SERVICE_RELEASE_TASK,
    SERVICE_RESET_POINTS,
    SERVICE_SKIP_TASK,
    SERVICE_TOGGLE_SUBTASK,
)
from .battery import BatteryStateListener
from .coordinator import FamilyTasksCoordinator
from .storage import (
    BatteryOverrideStorageCollection,
    ChecklistStateStore,
    ClaimStateStore,
    CoinLedgerStore,
    CompletionLogStore,
    DeadlineExtensionStateStore,
    DeadlineNotificationStateStore,
    FavoriteStorageCollection,
    MemberStorageCollection,
    MilestoneBonusStateStore,
    RewardRedemptionStorageCollection,
    RewardStorageCollection,
    StreakBonusStateStore,
    TaskStorageCollection,
    TopScorerBonusStateStore,
    TriggerStateStore,
    UpdateNoticeStateStore,
    VacationModeStateStore,
    async_create_battery_overrides_collection,
    async_create_checklist_state_store,
    async_create_claim_state_store,
    async_create_coin_ledger_store,
    async_create_deadline_extension_state_store,
    async_create_deadline_notification_state_store,
    async_create_favorites_collection,
    async_create_members_collection,
    async_create_milestone_bonus_state_store,
    async_create_reward_redemptions_collection,
    async_create_rewards_collection,
    async_create_streak_bonus_state_store,
    async_create_tasks_collection,
    async_create_top_scorer_bonus_state_store,
    async_create_trigger_state_store,
    async_create_update_notice_state_store,
    async_create_vacation_mode_state_store,
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
SKIP_TASK_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_TASK_ID): cv.string,
        # v0.32: only meaningful when task_id is an auto-generated parent
        # confirmation task - see async_skip_task's "confirms" branch.
        # Ignored (harmlessly) for a normal task skip.
        vol.Optional(ATTR_NOTE): cv.string,
    }
)
TOGGLE_SUBTASK_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_TASK_ID): cv.string,
        vol.Required(ATTR_SUBTASK_ID): cv.string,
        vol.Optional(ATTR_MEMBER_ID): cv.string,
    }
)
CLAIM_TASK_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_TASK_ID): cv.string,
        vol.Optional(ATTR_MEMBER_ID): cv.string,
    }
)
RELEASE_TASK_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_TASK_ID): cv.string,
        vol.Optional(ATTR_MEMBER_ID): cv.string,
    }
)
RESET_POINTS_SCHEMA = vol.Schema({vol.Optional(ATTR_MEMBER_ID): cv.string})


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
    milestone_bonus_state: MilestoneBonusStateStore
    favorites: FavoriteStorageCollection
    claim_state: ClaimStateStore
    streak_bonus_state: StreakBonusStateStore
    vacation_mode_state: VacationModeStateStore
    coin_ledger: CoinLedgerStore
    deadline_notification_state: DeadlineNotificationStateStore
    top_scorer_bonus_state: TopScorerBonusStateStore
    deadline_extension_state: DeadlineExtensionStateStore


FamilyTasksConfigEntry: TypeAlias = ConfigEntry[FamilyTasksRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: FamilyTasksConfigEntry) -> bool:
    """Set up Family Tasks from a config entry."""
    tasks = await async_create_tasks_collection(hass)
    members = await async_create_members_collection(hass)
    battery_overrides = await async_create_battery_overrides_collection(hass)
    rewards = await async_create_rewards_collection(hass)
    reward_redemptions = await async_create_reward_redemptions_collection(hass)
    favorites = await async_create_favorites_collection(hass)

    # Created before the websocket API is set up below - the reward-redeem
    # command needs the completion log to work out a member's current
    # available point balance (see ws_redeem_reward in storage.py).
    completions = CompletionLogStore(hass)
    await completions.async_load()

    # v0.36: created before the websocket API too, same reasoning as
    # completions above - ws_redeem_reward needs it to work out a member's
    # current coin balance. See CoinLedgerStore in storage.py.
    coin_ledger = await async_create_coin_ledger_store(hass)

    # The websocket CRUD API is a hass-global registration; only needed once,
    # but harmless/no-ops for a second entry since single_config_entry=True
    # in the manifest already prevents that from happening in practice.
    async_setup_websocket_api(
        hass,
        entry,
        tasks,
        members,
        battery_overrides,
        rewards,
        reward_redemptions,
        completions,
        favorites,
        coin_ledger,
    )

    trigger_state = await async_create_trigger_state_store(hass)
    checklist_state = await async_create_checklist_state_store(hass)
    milestone_bonus_state = await async_create_milestone_bonus_state_store(hass)
    claim_state = await async_create_claim_state_store(hass)
    streak_bonus_state = await async_create_streak_bonus_state_store(hass)
    # v0.52: see TopScorerBonusStateStore in storage.py.
    top_scorer_bonus_state = await async_create_top_scorer_bonus_state_store(hass)
    # v0.32: CONF_VACATION_MODE_DEFAULT only ever seeds this the very first
    # time it loads with nothing on disk yet - see VacationModeStateStore in
    # storage.py.
    vacation_mode_default = entry.options.get(
        CONF_VACATION_MODE_DEFAULT, DEFAULT_VACATION_MODE
    )
    vacation_mode_state = await async_create_vacation_mode_state_store(
        hass, vacation_mode_default
    )
    # v0.41: see DeadlineNotificationStateStore in storage.py.
    deadline_notification_state = await async_create_deadline_notification_state_store(hass)
    # v0.57: see DeadlineExtensionStateStore in storage.py.
    deadline_extension_state = await async_create_deadline_extension_state_store(hass)

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
        milestone_bonus_state,
        claim_state,
        streak_bonus_state,
        vacation_mode_state,
        coin_ledger,
        deadline_notification_state,
        top_scorer_bonus_state,
        deadline_extension_state,
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
        milestone_bonus_state=milestone_bonus_state,
        favorites=favorites,
        claim_state=claim_state,
        streak_bonus_state=streak_bonus_state,
        vacation_mode_state=vacation_mode_state,
        coin_ledger=coin_ledger,
        deadline_notification_state=deadline_notification_state,
        top_scorer_bonus_state=top_scorer_bonus_state,
        deadline_extension_state=deadline_extension_state,
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
    # A redemption changes the acting member's coins_available (v0.9, coins
    # since v0.36) - see MemberSummaryData.coins_available in coordinator.py
    # - so the leaderboard card's balance display updates right away instead
    # of waiting for the next poll interval.
    entry.async_on_unload(
        reward_redemptions.async_add_change_set_listener(_async_collection_changed)
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _async_register_services(hass)
    await _async_register_frontend(hass, members)

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
    hass: HomeAssistant,
    member_id: str,
    member: dict,
    task_id: str,
    task_name: str,
    *,
    message: str | None = None,
    event_type: str = EVENT_TASK_ASSIGNED,
) -> None:
    """Best-effort notify one member about a new task.

    Two channels, same reasoning as CONF_MEMBER_NOTIFY_SERVICE in const.py -
    but only one of them ever fires for a given member (v0.16 change): a
    persistent_notification is only raised as a *fallback* now, for a member
    with no notify_service configured, instead of unconditionally. Calling
    the member's own configured notify.* service (Home Assistant Companion
    App) is what actually reaches their phone as a real push notification;
    additionally raising a persistent_notification for that same member just
    duplicated it a second time inside Home Assistant's own frontend/
    companion-app notification panel, which is exactly the "shows up twice"
    complaint this fixes - once push is set up for someone, Home Assistant's
    own notification list should stay quiet for them. A member with no
    notify_service still gets the persistent_notification as before, since
    that's the only channel they have. ``event_type`` fires unconditionally
    on top either way, for a household that wants to react some other way
    entirely (same extension-point pattern as EVENT_REWARD_REDEEMED).

    ``message``/``event_type`` (v0.39) let a caller other than "you were
    assigned a task" reuse the exact same two-channel delivery instead of
    duplicating it - default to the original "Neue Aufgabe: ..." wording and
    EVENT_TASK_ASSIGNED so the one remaining call site in this module is
    unaffected. The Aufgabenpool broadcast that used to be the other caller
    of this with a custom message/event_type moved to
    FamilyTasksCoordinator._async_notify_deadline in coordinator.py (v0.41,
    see _async_notify_new_task_assignments above) - it duplicates this same
    two-channel pattern rather than importing it, since coordinator.py can't
    import back from this module (circular import).
    """
    title = "Family Tasks"
    message = message or f"Neue Aufgabe: {task_name}"

    notify_service = member.get(CONF_MEMBER_NOTIFY_SERVICE)
    if notify_service:
        try:
            await hass.services.async_call(
                "notify", notify_service, {"title": title, "message": message}, blocking=False
            )
        except HomeAssistantError as err:
            _LOGGER.warning("Failed to call notify.%s for %s: %s", notify_service, member_id, err)
    else:
        try:
            persistent_notification.async_create(
                hass, message, title=title, notification_id=f"{DOMAIN}_task_{task_id}_{member_id}"
            )
        except Exception as err:  # noqa: BLE001 - best-effort, must never block task creation
            _LOGGER.warning("Failed to raise persistent notification for %s: %s", member_id, err)

    hass.bus.async_fire(
        event_type,
        {
            "member_id": member_id,
            "member_name": member.get("name"),
            "task_id": task_id,
            "task_name": task_name,
        },
    )


def _async_notify_new_task_assignments(hass: HomeAssistant, members: MemberStorageCollection):
    """Build a tasks change-set listener that notifies about a new task.

    Registered alongside the other family_tasks.task change-set listeners in
    async_setup_entry (see tasks.async_add_change_set_listener below) -
    fires for a task an admin creates by hand as well as one the coordinator
    raises automatically (a parent-confirmation task, a battery alert), since
    both go through TaskStorageCollection.async_create_item the same way.
    Only "added" changes are notified - an edit that merely changes who a
    task is assigned to isn't treated as "a new task" here.

    Only notifies a task with fixed/rotating assignee(s) (EVENT_TASK_ASSIGNED,
    "Neue Aufgabe: ..."). v0.39 used to also broadcast an "Aufgabenpool" task
    (no assignee at all - see is_pool_task in coordinator.py) to every active
    member here, on creation only; v0.41 moved that to
    FamilyTasksCoordinator._async_notify_task_status instead, which fires it
    from the regular per-refresh status computation via
    DeadlineNotificationStateStore - covering a recurring pool task's *next*
    occurrence appearing too, not just its very first one, so this listener
    no longer needs to handle member_ids being empty at all (whether an
    Aufgabenpool task or an auto-generated parent-confirmation task, which
    also has no member_ids - see item.get("confirms")).
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


async def _async_register_frontend(
    hass: HomeAssistant, members: MemberStorageCollection
) -> None:
    """Serve the bundled Lovelace card and auto-inject it on every dashboard.

    Uses add_extra_js_url so the card is available without the user having
    to add a Lovelace resource manually.

    Up to v0.14 this registered a second file (family-tasks-leaderboard-card.js)
    alongside this one - the leaderboard/rewards UI has been folded into the
    single family-tasks-card.js in v0.15 (see that file's header comment), so
    only one static path/JS URL is registered now. A household upgrading from
    an older version that still has a "type: custom:family-tasks-leaderboard-card"
    card on a dashboard will see that card fail to load (the custom element
    never gets defined again) - it should be removed from the dashboard, its
    former content now lives in the "Bestenliste" section of family-tasks-card.

    The injected URL carries a "?v=<integration version>" cache-buster. The
    static path is registered with cache_headers=False, but that alone doesn't
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

    v0.48: add_extra_js_url only ever registered the module URL (es5=False,
    the default). Home Assistant's own frontend feature-detects the running
    browser once at load time (window.latestJS) and only dynamically
    import()s registered module URLs when that check passes; on a browser it
    classifies as *not* "latest" it instead loads only the URLs separately
    registered with es5=True (as a plain, non-module <script src="...">, see
    home-assistant/frontend's index.html.template / its `_ls()` loader), and
    never even attempts the module URL at all - no request, no console
    error, nothing. Since this card's JS was only ever registered as a
    module URL, such a browser silently never received it: Lovelace then
    correctly reports "custom element doesn't exist" for
    "family-tasks-card", deterministically, on every single load, immune to
    a reload or to clearing the app's cache - unlike the caching problem
    described above, the browser never even tries to fetch the file here.
    Observed on two different Samsung phones' Home Assistant Companion App
    WebView, never on iPhone/Safari (long since "latestJS" by that check).
    The card file itself has no `import`/`export` statement - it never
    needed ES-module semantics to begin with - so the exact same cache-
    busted URL is now also registered under the es5 list: browsers HA
    considers modern keep using the dynamic-import path exactly as before,
    and any older/unrecognized browser now gets the identical file via the
    plain-script fallback instead of nothing at all.

    v0.56: on top of the URL-level cache-busting above, also best-effort
    tells every family member once per actual version change that it's
    worth fully restarting the Companion App - see
    _async_notify_frontend_update below for why that's the closest this
    integration can get to "clearing" a phone's own frontend cache, since
    there is no API for a Home Assistant integration to reach into a
    Companion App and force that itself.
    """
    if hass.data.get(f"{DOMAIN}_frontend_registered"):
        return
    hass.data[f"{DOMAIN}_frontend_registered"] = True

    integration = await async_get_integration(hass, DOMAIN)
    current_version = str(integration.version)
    cache_buster = f"v={current_version}"

    www_dir = Path(__file__).parent / "www"
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL_PATH, str(www_dir / CARD_FILENAME), cache_headers=False)]
    )
    card_url = f"{CARD_URL_PATH}?{cache_buster}"
    add_extra_js_url(hass, card_url)
    # v0.48: see the docstring above - without this second call, a browser
    # HA's frontend doesn't classify as "latestJS" would never even attempt
    # to load the card at all, regardless of caching.
    add_extra_js_url(hass, card_url, es5=True)

    await _async_notify_frontend_update(hass, members, current_version)


async def _async_notify_frontend_update(
    hass: HomeAssistant, members: MemberStorageCollection, current_version: str
) -> None:
    """Best-effort "please restart the Companion App" notice after an update.

    _async_register_frontend's own "?v=<integration version>" cache-buster
    (see its docstring above) already forces every browser/Companion-App
    WebView to fetch the new family-tasks-card.js on the next dashboard load
    instead of quietly keeping a stale, incompatible one cached - but a Home
    Assistant custom integration has no API to reach into a phone's
    Companion App and force *its own* frontend cache to actually revalidate.
    What v0.48/v0.51 established from real user reports (a Samsung
    Companion App WebView kept serving a pre-fix resource list until fully
    restarted, not just backgrounded/reopened) is that a full app restart
    reliably clears it. This function can't trigger that restart either -
    nothing can, from server-side - but it can at least tell every family
    member, automatically, that it's now worth doing.

    Fires at most once per actual version change (see
    UpdateNoticeStateStore in storage.py) - not on every Home Assistant
    restart, and not again on a plain config-entry reload (options change)
    that didn't come with a version bump. The very first time this ever
    runs (UpdateNoticeStateStore has nothing stored yet - a brand-new
    install, or an existing household's first restart after upgrading to
    the version that introduced this feature) only seeds the marker without
    notifying anyone: a fresh install isn't "updated" from anything, and an
    existing household only starts getting these notices from their *next*
    version bump onward. Uses the same two-channel notify_service/
    persistent_notification delivery as _async_notify_member above, kept as
    an independent implementation rather than a shared call since that
    helper's signature/notification_id/event are all task-shaped and don't
    fit an update notice.
    """
    state: UpdateNoticeStateStore = await async_create_update_notice_state_store(hass)
    is_first_ever_run = state.last_notified_version is None
    if state.last_notified_version == current_version:
        return
    await state.async_set(current_version)
    if is_first_ever_run:
        # A brand-new install isn't an "update" - nothing to tell anyone to
        # restart yet, and members/notify_service may not even be set up
        # this early. Just seed the marker so the *next* real version bump
        # is the first one that actually notifies anyone.
        return

    title = "Family Tasks aktualisiert"
    message = (
        f"Family Tasks wurde auf Version {current_version} aktualisiert. Bitte "
        "die Companion App einmal vollständig neu starten (nicht nur in den "
        "Hintergrund legen), damit sie die neueste Kartenversion lädt."
    )
    for member_id, member in members.data.items():
        if not member.get("active", True):
            continue
        notify_service = member.get(CONF_MEMBER_NOTIFY_SERVICE)
        if notify_service:
            try:
                await hass.services.async_call(
                    "notify", notify_service, {"title": title, "message": message}, blocking=False
                )
                continue
            except HomeAssistantError as err:
                _LOGGER.warning(
                    "Failed to call notify.%s for %s: %s", notify_service, member_id, err
                )
        try:
            persistent_notification.async_create(
                hass,
                message,
                title=title,
                notification_id=f"{DOMAIN}_update_{current_version}_{member_id}",
            )
        except Exception as err:  # noqa: BLE001 - best-effort, must never block setup
            _LOGGER.warning("Failed to raise persistent notification for %s: %s", member_id, err)


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
        await coordinator.async_skip_task(call.data[ATTR_TASK_ID], call.data.get(ATTR_NOTE))

    async def _async_toggle_subtask(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass)
        member_id = await _async_resolve_member_id(call)
        await coordinator.async_toggle_subtask(
            call.data[ATTR_TASK_ID], call.data[ATTR_SUBTASK_ID], member_id
        )

    async def _async_claim_task(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass)
        member_id = await _async_resolve_member_id(call)
        await coordinator.async_claim_task(call.data[ATTR_TASK_ID], member_id)

    async def _async_release_task(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass)
        member_id = await _async_resolve_member_id(call)
        await coordinator.async_release_task(call.data[ATTR_TASK_ID], member_id)

    async def _async_reset_points(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass)
        await coordinator.async_reset_points(call.data.get(ATTR_MEMBER_ID))

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
    hass.services.async_register(
        DOMAIN, SERVICE_CLAIM_TASK, _async_claim_task, schema=CLAIM_TASK_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_RELEASE_TASK, _async_release_task, schema=RELEASE_TASK_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_RESET_POINTS, _async_reset_points, schema=RESET_POINTS_SCHEMA
    )
