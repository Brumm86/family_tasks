"""Administrative services for the Family Tasks integration (v0.72).

Everything the Lovelace card can do over the websocket API (create, edit and
delete tasks, members, Favoriten, rewards and battery overrides, award points
and coins, extend a deadline, change the household options) is also available
as a Home Assistant service here, so it can be driven from automations,
scripts, voice assistants or an MCP server without the card.

Design notes:

* The services are thin wrappers around the very same storage collections,
  schemas and coordinator methods the websocket handlers use (see
  ``storage.py``) - there is no second implementation of any rule. Payloads
  are validated by the collections' own ``CREATE_SCHEMA``/``UPDATE_SCHEMA``,
  so a service call is accepted or rejected exactly like the card's request.
* Every service here is registered as an *admin* service
  (``async_register_admin_service``): a call made by a logged-in non-admin
  user is rejected. On top of that, a user linked to a member with the role
  "child" is rejected even if that HA user happens to be an administrator -
  the same rule the websocket handlers apply. Calls without a user (an
  automation or script) are allowed, as for every other service.
* Reading services return their data as a service response
  (``SupportsResponse.ONLY``); creating/updating services return the stored
  item (``SupportsResponse.OPTIONAL``), which is how a caller learns the ID
  of something it just created.
* The six pre-existing services (complete_task, skip_task, ...) are
  unchanged and still registered in ``__init__.py``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any

import voluptuous as vol
from voluptuous.humanize import humanize_error

from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import (
    HomeAssistantError,
    ServiceValidationError,
    Unauthorized,
)
from homeassistant.helpers import collection
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.service import async_register_admin_service
from homeassistant.util import dt as dt_util

from .const import (
    COIN_REASON_MANUAL,
    COIN_THRESHOLD_KEYS,
    CONF_BATTERY_ALERT_AUTO_COMPLETE_ON_RECOVERY,
    CONF_BATTERY_WARNING_THRESHOLD,
    CONF_DEFAULT_ROTATION_STRATEGY,
    CONF_MILESTONE_150_BONUS_COINS,
    CONF_MILESTONE_200_BONUS_COINS,
    CONF_OVERDUE_AFTER_MINUTES,
    CONF_SCREEN_TIME_MALUS_START_DATE,
    CONF_SCREEN_TIME_MINUTES_PER_POINT,
    CONF_SCREEN_TIME_TICK_MINUTES,
    CONF_SCREEN_TIME_TICKS_PER_DAY,
    CONF_SPOTIFY_THRESHOLD_POINTS,
    CONF_STREAK_BONUS_2_WEEKS_COINS,
    CONF_STREAK_BONUS_3_WEEKS_COINS,
    CONF_TOP_SCORER_BONUS_COINS,
    CONF_VACATION_MODE_DEFAULT,
    CONF_WEEKLY_PROGRESS_GOAL_POINTS,
    DOMAIN,
    EXTEND_TASK_DEADLINE_MAX_MINUTES,
    MALUS_THRESHOLD_KEYS,
    MANUAL_POINTS_TASK_ID,
    MEMBER_ROLE_CHILD,
    ROTATION_STRATEGIES,
    resolve_progress_thresholds,
    thresholds_ascending,
)
from .storage import _member_role_for_user, _task_data_from_favorite

# --- Service names ------------------------------------------------------------

SERVICE_CREATE_TASK = "create_task"
SERVICE_UPDATE_TASK = "update_task"
SERVICE_DELETE_TASK = "delete_task"
SERVICE_LIST_TASKS = "list_tasks"

SERVICE_CREATE_MEMBER = "create_member"
SERVICE_UPDATE_MEMBER = "update_member"
SERVICE_DELETE_MEMBER = "delete_member"
SERVICE_LIST_MEMBERS = "list_members"

SERVICE_CREATE_FAVORITE = "create_favorite"
SERVICE_UPDATE_FAVORITE = "update_favorite"
SERVICE_DELETE_FAVORITE = "delete_favorite"
SERVICE_LIST_FAVORITES = "list_favorites"
SERVICE_INSTANTIATE_FAVORITE = "instantiate_favorite"

SERVICE_CREATE_REWARD = "create_reward"
SERVICE_UPDATE_REWARD = "update_reward"
SERVICE_DELETE_REWARD = "delete_reward"
SERVICE_LIST_REWARDS = "list_rewards"
SERVICE_LIST_REWARD_REDEMPTIONS = "list_reward_redemptions"
SERVICE_FULFILL_REWARD_REDEMPTION = "fulfill_reward_redemption"

SERVICE_CREATE_BATTERY_OVERRIDE = "create_battery_override"
SERVICE_UPDATE_BATTERY_OVERRIDE = "update_battery_override"
SERVICE_DELETE_BATTERY_OVERRIDE = "delete_battery_override"
SERVICE_LIST_BATTERY_OVERRIDES = "list_battery_overrides"

SERVICE_AWARD_POINTS = "award_points"
SERVICE_AWARD_COINS = "award_coins"
SERVICE_EXTEND_TASK_DEADLINE = "extend_task_deadline"

SERVICE_GET_SETTINGS = "get_settings"
SERVICE_UPDATE_SETTINGS = "update_settings"

# --- Schemas ------------------------------------------------------------------

_NON_EMPTY_DICT = vol.All(dict, vol.Length(min=1))
_POINTS_RANGE = vol.All(int, vol.Range(min=-100000, max=100000))


def _count(minimum: int, maximum: int) -> vol.All:
    """An integer option value, tolerant of floats (JSON, number selectors)."""
    return vol.All(vol.Coerce(int), vol.Range(min=minimum, max=maximum))


def _nullable_count(minimum: int, maximum: int) -> vol.Any:
    return vol.Any(None, _count(minimum, maximum))


# Mirrors the fields (and their limits) of the options flow in config_flow.py.
# ``None`` removes an option again (falls back to its default / derived value).
SETTINGS_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_OVERDUE_AFTER_MINUTES): _count(0, 1440),
        vol.Optional(CONF_DEFAULT_ROTATION_STRATEGY): vol.In(ROTATION_STRATEGIES),
        vol.Optional(CONF_BATTERY_WARNING_THRESHOLD): _count(0, 100),
        vol.Optional(CONF_BATTERY_ALERT_AUTO_COMPLETE_ON_RECOVERY): cv.boolean,
        vol.Optional(CONF_SCREEN_TIME_MINUTES_PER_POINT): _count(1, 120),
        vol.Optional(CONF_SCREEN_TIME_TICK_MINUTES): _count(0, 60),
        vol.Optional(CONF_SCREEN_TIME_TICKS_PER_DAY): _count(0, 100),
        vol.Optional(CONF_SCREEN_TIME_MALUS_START_DATE): vol.Any(None, cv.date),
        vol.Optional(CONF_WEEKLY_PROGRESS_GOAL_POINTS): _count(0, 1000),
        vol.Optional(CONF_MILESTONE_150_BONUS_COINS): _count(0, 1000),
        vol.Optional(CONF_MILESTONE_200_BONUS_COINS): _count(0, 1000),
        vol.Optional(CONF_STREAK_BONUS_2_WEEKS_COINS): _count(0, 1000),
        vol.Optional(CONF_STREAK_BONUS_3_WEEKS_COINS): _count(0, 1000),
        vol.Optional(CONF_TOP_SCORER_BONUS_COINS): _count(0, 1000),
        vol.Optional(CONF_SPOTIFY_THRESHOLD_POINTS): _count(0, 100000),
        vol.Optional(CONF_VACATION_MODE_DEFAULT): cv.boolean,
        **{
            vol.Optional(key): _nullable_count(0, 100000)
            for key in (*MALUS_THRESHOLD_KEYS, *COIN_THRESHOLD_KEYS)
        },
    }
)


class _Kind:
    """One storage-collection backed object type with generic CRUD services."""

    def __init__(
        self,
        *,
        key: str,
        plural: str,
        attr: str,
        id_field: str,
        label: str,
        services: tuple[str, str, str, str],
    ) -> None:
        self.key = key  # payload field of create_* (e.g. "task")
        self.plural = plural  # response field of list_* (e.g. "tasks")
        self.attr = attr  # attribute on the entry's runtime data
        self.id_field = id_field  # id field of update_*/delete_* (e.g. "task_id")
        self.label = label  # for German error messages
        self.create_service, self.update_service, self.delete_service, self.list_service = (
            services
        )


KINDS: tuple[_Kind, ...] = (
    _Kind(
        key="task",
        plural="tasks",
        attr="tasks",
        id_field="task_id",
        label="Aufgabe",
        services=(
            SERVICE_CREATE_TASK,
            SERVICE_UPDATE_TASK,
            SERVICE_DELETE_TASK,
            SERVICE_LIST_TASKS,
        ),
    ),
    _Kind(
        key="member",
        plural="members",
        attr="members",
        id_field="member_id",
        label="Familienmitglied",
        services=(
            SERVICE_CREATE_MEMBER,
            SERVICE_UPDATE_MEMBER,
            SERVICE_DELETE_MEMBER,
            SERVICE_LIST_MEMBERS,
        ),
    ),
    _Kind(
        key="favorite",
        plural="favorites",
        attr="favorites",
        id_field="favorite_id",
        label="Favorit",
        services=(
            SERVICE_CREATE_FAVORITE,
            SERVICE_UPDATE_FAVORITE,
            SERVICE_DELETE_FAVORITE,
            SERVICE_LIST_FAVORITES,
        ),
    ),
    _Kind(
        key="reward",
        plural="rewards",
        attr="rewards",
        id_field="reward_id",
        label="Belohnung",
        services=(
            SERVICE_CREATE_REWARD,
            SERVICE_UPDATE_REWARD,
            SERVICE_DELETE_REWARD,
            SERVICE_LIST_REWARDS,
        ),
    ),
    _Kind(
        key="battery_override",
        plural="battery_overrides",
        attr="battery_overrides",
        id_field="override_id",
        label="Batterie-Override",
        services=(
            SERVICE_CREATE_BATTERY_OVERRIDE,
            SERVICE_UPDATE_BATTERY_OVERRIDE,
            SERVICE_DELETE_BATTERY_OVERRIDE,
            SERVICE_LIST_BATTERY_OVERRIDES,
        ),
    ),
)

# --- Helpers ------------------------------------------------------------------


def _get_runtime(hass: HomeAssistant) -> tuple[Any, Any]:
    """Return the (single) config entry and its runtime data."""
    entries = hass.config_entries.async_entries(DOMAIN)
    entry = entries[0] if entries else None
    runtime = getattr(entry, "runtime_data", None) if entry is not None else None
    if entry is None or runtime is None:
        raise HomeAssistantError("Family Tasks is not configured")
    return entry, runtime


async def _async_authorize(hass: HomeAssistant, call: ServiceCall) -> tuple[Any, Any]:
    """Reject a caller linked to a "child" member; return (entry, runtime data).

    ``async_register_admin_service`` has already rejected non-admin users by
    the time this runs. A child's HA user may nevertheless be an
    administrator, so the member role is checked here too - the same rule the
    websocket handlers apply ("not a child, regardless of HA admin flag").
    """
    entry, runtime = _get_runtime(hass)
    user_id = call.context.user_id
    if user_id is not None:
        user = await hass.auth.async_get_user(user_id)
        if _member_role_for_user(hass, runtime.members, user) == MEMBER_ROLE_CHILD:
            raise Unauthorized(context=call.context)
    return entry, runtime


def _iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def _task_status_dict(status: Any) -> dict[str, Any]:
    """Serialize the coordinator's computed status of one task."""
    return {
        field: _iso(getattr(status, field, None))
        for field in (
            "status",
            "period_key",
            "due_at",
            "deadline_at",
            "assigned_member_id",
            "last_completed_by",
            "last_completed_at",
        )
    }


def _member_summary_dict(summary: Any) -> dict[str, Any]:
    return {
        field: getattr(summary, field, None)
        for field in (
            "points_today",
            "points_week",
            "points_month",
            "points_total",
            "open_tasks",
            "coins_available",
        )
    }


# --- Generic CRUD handlers ----------------------------------------------------


def _make_create(
    hass: HomeAssistant, kind: _Kind
) -> Callable[[ServiceCall], Awaitable[dict[str, Any]]]:
    async def _handler(call: ServiceCall) -> dict[str, Any]:
        _, runtime = await _async_authorize(hass, call)
        data = dict(call.data[kind.key])
        try:
            item = await getattr(runtime, kind.attr).async_create_item(data)
        except vol.Invalid as err:
            raise ServiceValidationError(humanize_error(data, err)) from err
        return dict(item)

    return _handler


def _make_update(
    hass: HomeAssistant, kind: _Kind
) -> Callable[[ServiceCall], Awaitable[dict[str, Any]]]:
    async def _handler(call: ServiceCall) -> dict[str, Any]:
        _, runtime = await _async_authorize(hass, call)
        item_id = call.data[kind.id_field]
        changes = dict(call.data["changes"])
        try:
            item = await getattr(runtime, kind.attr).async_update_item(item_id, changes)
        except collection.ItemNotFound as err:
            raise ServiceValidationError(f"{kind.label} '{item_id}' nicht gefunden.") from err
        except vol.Invalid as err:
            raise ServiceValidationError(humanize_error(changes, err)) from err
        return dict(item)

    return _handler


def _make_delete(
    hass: HomeAssistant, kind: _Kind
) -> Callable[[ServiceCall], Awaitable[dict[str, Any]]]:
    async def _handler(call: ServiceCall) -> dict[str, Any]:
        _, runtime = await _async_authorize(hass, call)
        item_id = call.data[kind.id_field]
        try:
            await getattr(runtime, kind.attr).async_delete_item(item_id)
        except collection.ItemNotFound as err:
            raise ServiceValidationError(f"{kind.label} '{item_id}' nicht gefunden.") from err
        return {"deleted": item_id}

    return _handler


def _make_list(
    hass: HomeAssistant, kind: _Kind
) -> Callable[[ServiceCall], Awaitable[dict[str, Any]]]:
    async def _handler(call: ServiceCall) -> dict[str, Any]:
        _, runtime = await _async_authorize(hass, call)
        with_state = (kind.key == "task" and call.data.get("include_status", True)) or (
            kind.key == "member" and call.data.get("include_summary", True)
        )
        if with_state:
            # Points, coin balances and task states are only recomputed on a
            # coordinator refresh; make sure a read right after a write (e.g.
            # award_points) reflects it instead of the last polled snapshot.
            await runtime.coordinator.async_refresh()
        data = runtime.coordinator.data
        items: list[dict[str, Any]] = []
        for item_id, stored in getattr(runtime, kind.attr).data.items():
            item = dict(stored)
            # Tasks and members additionally carry the coordinator's current,
            # computed state (open/overdue/done, points, coin balance ...),
            # which is not part of the stored definition.
            if kind.key == "task" and with_state and data:
                status = data.tasks.get(item_id)
                if status is not None:
                    item["current"] = _task_status_dict(status)
            elif kind.key == "member" and with_state and data:
                summary = data.members.get(item_id)
                if summary is not None:
                    item["current"] = _member_summary_dict(summary)
            items.append(item)
        return {kind.plural: items}

    return _handler


# --- Special services ---------------------------------------------------------


def _register_special_services(hass: HomeAssistant, register: Callable[..., None]) -> None:
    async def _award_points(call: ServiceCall) -> dict[str, Any]:
        _, runtime = await _async_authorize(hass, call)
        coordinator = runtime.coordinator
        member_id = call.data["member_id"]
        if member_id not in runtime.members.data:
            raise ServiceValidationError("Familienmitglied nicht gefunden.")
        points = call.data["points"]
        if points == 0:
            raise ServiceValidationError("Punktzahl darf nicht 0 sein.")
        note = (call.data.get("note") or "").strip() or None
        entry_item = await coordinator.completions.async_add_entry(
            task_id=MANUAL_POINTS_TASK_ID,
            period_key=dt_util.utcnow().date().isoformat(),
            member_id=member_id,
            points_awarded=points,
            task_name=note or ("Punkte erteilt" if points > 0 else "Punkte abgezogen"),
        )
        await coordinator.async_request_refresh()
        return dict(entry_item)

    async def _award_coins(call: ServiceCall) -> dict[str, Any]:
        _, runtime = await _async_authorize(hass, call)
        coordinator = runtime.coordinator
        member_id = call.data["member_id"]
        if member_id not in runtime.members.data:
            raise ServiceValidationError("Familienmitglied nicht gefunden.")
        coins = call.data["coins"]
        if coins == 0:
            raise ServiceValidationError("Münzanzahl darf nicht 0 sein.")
        if coins < 0:
            # Same rule as the card: a deduction is limited to the balance.
            balance = coordinator.coin_ledger.balance(member_id)
            if balance <= 0:
                raise ServiceValidationError(
                    "Das Mitglied hat keine Münzen, die abgezogen werden könnten."
                )
            coins = -min(-coins, balance)
        note = (call.data.get("note") or "").strip() or None
        entry_item = await coordinator.coin_ledger.async_add_entry(
            member_id=member_id,
            amount=coins,
            reason=COIN_REASON_MANUAL,
            note=note or ("Münzen erteilt" if coins > 0 else "Münzen abgezogen"),
        )
        await coordinator.async_request_refresh()
        return dict(entry_item)

    async def _extend_task_deadline(call: ServiceCall) -> dict[str, Any]:
        _, runtime = await _async_authorize(hass, call)
        try:
            new_deadline = await runtime.coordinator.async_extend_task_deadline(
                call.data["task_id"], call.data["minutes"]
            )
        except HomeAssistantError as err:
            raise ServiceValidationError(str(err)) from err
        if new_deadline is None:
            raise ServiceValidationError(
                "Für diese Aufgabe ist aktuell nichts fällig, das verlängert werden könnte."
            )
        return {"deadline_at": new_deadline.isoformat()}

    async def _instantiate_favorite(call: ServiceCall) -> dict[str, Any]:
        _, runtime = await _async_authorize(hass, call)
        favorite = runtime.favorites.data.get(call.data["favorite_id"])
        if favorite is None:
            raise ServiceValidationError("Favorit nicht gefunden.")
        task_data = _task_data_from_favorite(favorite)
        if call.data.get("member_ids") is not None:
            task_data["rotation"]["member_ids"] = list(call.data["member_ids"])
        try:
            item = await runtime.tasks.async_create_item(task_data)
        except vol.Invalid as err:
            raise ServiceValidationError(humanize_error(task_data, err)) from err
        return dict(item)

    async def _list_reward_redemptions(call: ServiceCall) -> dict[str, Any]:
        _, runtime = await _async_authorize(hass, call)
        items = [dict(item) for item in runtime.reward_redemptions.data.values()]
        if call.data.get("only_open"):
            items = [item for item in items if not item.get("fulfilled")]
        return {"reward_redemptions": items}

    async def _fulfill_reward_redemption(call: ServiceCall) -> dict[str, Any]:
        _, runtime = await _async_authorize(hass, call)
        redemption_id = call.data["redemption_id"]
        try:
            item = await runtime.reward_redemptions.async_update_item(
                redemption_id, {"fulfilled": call.data["fulfilled"]}
            )
        except collection.ItemNotFound as err:
            raise ServiceValidationError(
                f"Einlösung '{redemption_id}' nicht gefunden."
            ) from err
        return dict(item)

    async def _get_settings(call: ServiceCall) -> dict[str, Any]:
        entry, runtime = await _async_authorize(hass, call)
        options = dict(entry.options)
        goal = int(options.get(CONF_WEEKLY_PROGRESS_GOAL_POINTS) or 0)
        malus, coin = resolve_progress_thresholds(options, goal)
        data = runtime.coordinator.data
        return {
            "options": options,
            # The thresholds actually in effect: a threshold not set
            # explicitly is derived from the weekly goal (0 = off).
            "effective_thresholds": {
                "malus_points": list(malus),
                "coin_points": list(coin),
            },
            "vacation_mode_active": getattr(data, "vacation_mode_active", None),
        }

    async def _update_settings(call: ServiceCall) -> dict[str, Any]:
        entry, runtime = await _async_authorize(hass, call)
        options = dict(entry.options)
        for key, value in call.data["settings"].items():
            if value is None:
                options.pop(key, None)
            elif isinstance(value, date):
                # Config-entry options are stored as JSON: dates as ISO strings
                # (see the options flow in config_flow.py).
                options[key] = value.isoformat()
            else:
                options[key] = value
        # Same consistency rule as the options flow: malus 1 < 2 < 3 < 4 <
        # weekly goal < coin 1 < coin 2.
        goal = int(options.get(CONF_WEEKLY_PROGRESS_GOAL_POINTS) or 0)
        if goal > 0:
            malus, coin = resolve_progress_thresholds(options, goal)
            if not thresholds_ascending(malus, goal, coin):
                raise ServiceValidationError(
                    "Die Schwellen müssen streng aufsteigend sein: Malus 1 < 2 < 3 < 4 "
                    "< Wochenziel < Münz-Schwelle 1 < 2."
                )
        hass.config_entries.async_update_entry(entry, options=options)
        await runtime.coordinator.async_request_refresh()
        return {"options": options}

    register(
        SERVICE_AWARD_POINTS,
        _award_points,
        vol.Schema(
            {
                vol.Required("member_id"): cv.string,
                vol.Required("points"): _POINTS_RANGE,
                vol.Optional("note"): cv.string,
            }
        ),
        SupportsResponse.OPTIONAL,
    )
    register(
        SERVICE_AWARD_COINS,
        _award_coins,
        vol.Schema(
            {
                vol.Required("member_id"): cv.string,
                vol.Required("coins"): _POINTS_RANGE,
                vol.Optional("note"): cv.string,
            }
        ),
        SupportsResponse.OPTIONAL,
    )
    register(
        SERVICE_EXTEND_TASK_DEADLINE,
        _extend_task_deadline,
        vol.Schema(
            {
                vol.Required("task_id"): cv.string,
                vol.Required("minutes"): vol.All(
                    int, vol.Range(min=1, max=EXTEND_TASK_DEADLINE_MAX_MINUTES)
                ),
            }
        ),
        SupportsResponse.OPTIONAL,
    )
    register(
        SERVICE_INSTANTIATE_FAVORITE,
        _instantiate_favorite,
        vol.Schema(
            {
                vol.Required("favorite_id"): cv.string,
                vol.Optional("member_ids"): [cv.string],
            }
        ),
        SupportsResponse.OPTIONAL,
    )
    register(
        SERVICE_LIST_REWARD_REDEMPTIONS,
        _list_reward_redemptions,
        vol.Schema({vol.Optional("only_open", default=False): cv.boolean}),
        SupportsResponse.ONLY,
    )
    register(
        SERVICE_FULFILL_REWARD_REDEMPTION,
        _fulfill_reward_redemption,
        vol.Schema(
            {
                vol.Required("redemption_id"): cv.string,
                vol.Optional("fulfilled", default=True): cv.boolean,
            }
        ),
        SupportsResponse.OPTIONAL,
    )
    register(SERVICE_GET_SETTINGS, _get_settings, vol.Schema({}), SupportsResponse.ONLY)
    register(
        SERVICE_UPDATE_SETTINGS,
        _update_settings,
        vol.Schema({vol.Required("settings"): vol.All(dict, vol.Length(min=1), SETTINGS_SCHEMA)}),
        SupportsResponse.OPTIONAL,
    )


# --- Registration -------------------------------------------------------------


def async_register_admin_services(hass: HomeAssistant) -> None:
    """Register the administrative services (idempotent)."""
    if hass.services.has_service(DOMAIN, SERVICE_CREATE_TASK):
        return

    def register(
        name: str,
        handler: Callable[[ServiceCall], Awaitable[dict[str, Any]]],
        schema: vol.Schema,
        supports_response: SupportsResponse,
    ) -> None:
        async_register_admin_service(
            hass, DOMAIN, name, handler, schema, supports_response=supports_response
        )

    for kind in KINDS:
        register(
            kind.create_service,
            _make_create(hass, kind),
            vol.Schema({vol.Required(kind.key): _NON_EMPTY_DICT}),
            SupportsResponse.OPTIONAL,
        )
        register(
            kind.update_service,
            _make_update(hass, kind),
            vol.Schema(
                {
                    vol.Required(kind.id_field): cv.string,
                    vol.Required("changes"): _NON_EMPTY_DICT,
                }
            ),
            SupportsResponse.OPTIONAL,
        )
        register(
            kind.delete_service,
            _make_delete(hass, kind),
            vol.Schema({vol.Required(kind.id_field): cv.string}),
            SupportsResponse.OPTIONAL,
        )
        list_schema: dict[Any, Any] = {}
        if kind.key == "task":
            list_schema[vol.Optional("include_status", default=True)] = cv.boolean
        elif kind.key == "member":
            list_schema[vol.Optional("include_summary", default=True)] = cv.boolean
        register(
            kind.list_service,
            _make_list(hass, kind),
            vol.Schema(list_schema),
            SupportsResponse.ONLY,
        )

    _register_special_services(hass, register)
