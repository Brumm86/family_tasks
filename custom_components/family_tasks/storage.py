"""Storage layer for the Family Tasks integration.

Task- and member definitions are managed as ``StorageCollection`` items so
they can be created/edited/deleted through the frontend (Settings UI /
a dedicated Lovelace card) via websocket commands, the same pattern used by
helpers such as ``counter`` or ``input_boolean``.

Task *completions* are an append-only log and therefore intentionally not a
StorageCollection (there is nothing to edit, only to append and prune).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

import voluptuous as vol
from voluptuous.humanize import humanize_error

from homeassistant.components import websocket_api
from homeassistant.const import CONF_ID
from homeassistant.core import Context, HomeAssistant, callback
from homeassistant.helpers import collection
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_COMPLETION_BUTTON_ENTITY_ID,
    CONF_MEMBER_NOTIFY_SERVICE,
    CONF_MEMBER_REWARDS_OPT_IN,
    CONF_REWARD_AUTO_FULFILL,
    CONF_REWARD_NOTE_ENABLED,
    CONF_REWARD_NOTE_LABEL,
    CONF_REWARD_SCREEN_TIME_INVESTABLE,
    CONF_REWARD_SCREEN_TIME_MINUTES,
    CONF_SCREEN_TIME_MINUTES_PER_POINT,
    CONF_TASK_CREATED_BY_MEMBER_ID,
    CONF_TASK_REQUIRES_CONFIRMATION,
    DEFAULT_ROTATION_STRATEGY,
    DEFAULT_SCREEN_TIME_MINUTES_PER_POINT,
    EVENT_REWARD_REDEEMED,
    MANUAL_POINTS_TASK_ID,
    MAX_COMPLETION_LOG_ENTRIES,
    MEMBER_ROLE_CHILD,
    MEMBER_ROLE_PARENT,
    MEMBER_ROLES,
    OWN_TASK_KINDS,
    RECURRENCE_INTERVAL_DAYS,
    RECURRENCE_ONCE,
    RECURRENCE_TRIGGER,
    RECURRENCE_TYPES,
    ROTATION_ONLY_CHILDREN,
    ROTATION_STRATEGIES,
    ROTATION_STRATEGY_FIXED,
    STORAGE_KEY_BATTERY_OVERRIDES,
    STORAGE_KEY_CHECKLIST_STATE,
    STORAGE_KEY_COMPLETIONS,
    STORAGE_KEY_FAVORITES,
    STORAGE_KEY_MEMBERS,
    STORAGE_KEY_REWARD_REDEMPTIONS,
    STORAGE_KEY_REWARDS,
    STORAGE_KEY_TASKS,
    STORAGE_KEY_TRIGGER_STATE,
    STORAGE_KEY_WEEKLY_BONUS_STATE,
    STORAGE_VERSION,
    STORAGE_VERSION_MINOR,
    TASK_KIND_CHECKLIST,
    TASK_KIND_STANDARD,
    TASK_KINDS,
    TASK_TRIGGER_KINDS,
    TASK_TRIGGER_NUMERIC_STATE,
    TASK_TRIGGER_STATE,
    WEEKLY_BONUS_TASK_ID,
    WS_API_FAVORITE_INSTANTIATE,
    WS_API_MEMBER_WEEKLY_COMPLETIONS,
    WS_API_POINTS_AWARD,
    WS_API_PREFIX_BATTERY_OVERRIDES,
    WS_API_PREFIX_FAVORITES,
    WS_API_PREFIX_MEMBERS,
    WS_API_PREFIX_REWARD_REDEMPTIONS,
    WS_API_PREFIX_REWARDS,
    WS_API_PREFIX_TASKS,
    WS_API_REWARD_REDEEM,
    WS_API_TASK_CREATE_OWN,
)

# --- Validation schemas ------------------------------------------------------


def _require_single_threshold(value: dict) -> dict:
    """A numeric_state trigger needs exactly one of 'above'/'below'.

    This is a directional crossing ("fires once the sensor rises above X" or
    "...falls below Y"), not a range - setting both would describe a band
    the value has to be inside of, which is a different (and confusing)
    trigger the card no longer offers.
    """
    has_above = "above" in value
    has_below = "below" in value
    if has_above == has_below:  # neither, or both
        raise vol.Invalid(
            "A 'numeric_state' trigger needs exactly one of 'above' or "
            "'below' - a single threshold direction, not a range."
        )
    return value


TASK_TRIGGER_STATE_SCHEMA = vol.Schema(
    {
        vol.Required("kind"): TASK_TRIGGER_STATE,
        vol.Required("entity_id"): cv.entity_id,
        vol.Optional("to_state", default="on"): str,
    }
)

TASK_TRIGGER_NUMERIC_STATE_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Required("kind"): TASK_TRIGGER_NUMERIC_STATE,
            vol.Required("entity_id"): cv.entity_id,
            vol.Optional("above"): vol.Coerce(float),
            vol.Optional("below"): vol.Coerce(float),
        }
    ),
    _require_single_threshold,
)

# Dispatches on "kind" so config errors point at the right sub-schema instead
# of vol.Any's generic "no valid value found" message.
TASK_TRIGGER_SCHEMA = vol.All(
    vol.Schema({vol.Required("kind"): vol.In(TASK_TRIGGER_KINDS)}, extra=vol.ALLOW_EXTRA),
    lambda value: (
        TASK_TRIGGER_STATE_SCHEMA(value)
        if value["kind"] == TASK_TRIGGER_STATE
        else TASK_TRIGGER_NUMERIC_STATE_SCHEMA(value)
    ),
)

RECURRENCE_SCHEMA = vol.Schema(
    {
        vol.Required("type"): vol.In(RECURRENCE_TYPES),
        vol.Optional("interval"): vol.All(int, vol.Range(min=1)),
        vol.Optional("weekdays"): [vol.All(int, vol.Range(min=0, max=6))],
        vol.Optional("anchor_date"): str,  # ISO date, required for interval_days
        vol.Optional("trigger"): TASK_TRIGGER_SCHEMA,  # required for type "trigger"
    },
    extra=vol.ALLOW_EXTRA,
)

ROTATION_SCHEMA = vol.Schema(
    {
        vol.Required("member_ids"): [str],
        vol.Optional("strategy", default=DEFAULT_ROTATION_STRATEGY): vol.In(
            ROTATION_STRATEGIES
        ),
        vol.Optional("current_index", default=0): vol.All(int, vol.Range(min=0)),
        # Only meaningful for strategy "least_points" - see ROTATION_ONLY_CHILDREN
        # in const.py.
        vol.Optional(ROTATION_ONLY_CHILDREN, default=False): bool,
    }
)

# Present only on auto-generated parent confirmation tasks (see
# RECURRENCE_CONFIRMATION in const.py): links the confirmation task back to
# the child's original task/occurrence it was raised for. Never set by the
# card - the coordinator is the only writer.
CONFIRMS_SCHEMA = vol.Schema(
    {
        vol.Required("task_id"): str,
        vol.Required("period_key"): str,
        vol.Required("member_id"): str,
    }
)

# Present only on auto-generated battery-warning tasks (see
# FamilyTasksCoordinator._async_raise_battery_alerts in coordinator.py):
# identifies which monitored battery entity the (recurrence "once") task was
# raised for, so the coordinator can tell whether that battery's current
# low-battery episode already has an unresolved task instead of creating a
# new one every refresh. Never set by the card - the coordinator is the only
# writer.
BATTERY_ALERT_SCHEMA = vol.Schema({vol.Required("entity_id"): str})

# One named item of a TASK_KIND_CHECKLIST task's checklist (see TASK_KINDS in
# const.py). "id" is opaque and client-generated (the card assigns one when a
# sub-item is added to the form) - it only needs to be stable and unique
# within the task, since it's what family_tasks/task/toggle_subtask and
# storage.ChecklistStateStore key checked/unchecked state on.
SUBTASK_SCHEMA = vol.Schema(
    {
        vol.Required("id"): str,
        vol.Required("name"): str,
    }
)


def _require_unique_subtask_ids(subtasks: list[dict]) -> list[dict]:
    ids = [s["id"] for s in subtasks]
    if len(ids) != len(set(ids)):
        raise vol.Invalid("Subtask ids must be unique within a task.")
    return subtasks


TASK_CREATE_SCHEMA: collection.VolDictType = {
    vol.Required("name"): str,
    vol.Optional("icon"): str,
    vol.Optional("points", default=0): vol.All(int, vol.Range(min=0)),
    vol.Optional("enabled", default=True): bool,
    vol.Optional("due_time"): str,  # "HH:MM"
    vol.Optional("overdue_after_minutes"): vol.All(int, vol.Range(min=0)),
    vol.Required("recurrence"): RECURRENCE_SCHEMA,
    vol.Required("rotation"): ROTATION_SCHEMA,
    vol.Optional("confirms"): CONFIRMS_SCHEMA,
    vol.Optional("battery_alert"): BATTERY_ALERT_SCHEMA,
    # See CONF_TASK_REQUIRES_CONFIRMATION in const.py. Absent/None means "use
    # the role-based default" (always required for a "child" assignee).
    vol.Optional(CONF_TASK_REQUIRES_CONFIRMATION): bool,
    # Optional button pressed once the task is actually marked done - see
    # CONF_COMPLETION_BUTTON_ENTITY_ID in const.py.
    vol.Optional(CONF_COMPLETION_BUTTON_ENTITY_ID): cv.entity_id,
    # See TASK_KIND_CHECKLIST in const.py.
    vol.Optional("kind", default=TASK_KIND_STANDARD): vol.In(TASK_KINDS),
    vol.Optional("subtasks", default=list): vol.All([SUBTASK_SCHEMA], _require_unique_subtask_ids),
    # See CONF_TASK_CREATED_BY_MEMBER_ID in const.py - only ever set by
    # ws_create_own_task, never by the card's admin task-creation form.
    vol.Optional(CONF_TASK_CREATED_BY_MEMBER_ID): str,
}

TASK_UPDATE_SCHEMA: collection.VolDictType = {
    vol.Optional("name"): str,
    vol.Optional("icon"): str,
    vol.Optional("points"): vol.All(int, vol.Range(min=0)),
    vol.Optional("enabled"): bool,
    vol.Optional("due_time"): str,
    vol.Optional("overdue_after_minutes"): vol.All(int, vol.Range(min=0)),
    vol.Optional("recurrence"): RECURRENCE_SCHEMA,
    vol.Optional("rotation"): ROTATION_SCHEMA,
    vol.Optional(CONF_TASK_REQUIRES_CONFIRMATION): bool,
    # Explicitly setting this to null clears a previously configured
    # completion button, mirroring how BATTERY_OVERRIDE_UPDATE_SCHEMA clears
    # "threshold" below.
    vol.Optional(CONF_COMPLETION_BUTTON_ENTITY_ID): vol.Any(None, cv.entity_id),
    vol.Optional("kind"): vol.In(TASK_KINDS),
    vol.Optional("subtasks"): vol.All([SUBTASK_SCHEMA], _require_unique_subtask_ids),
}

MEMBER_CREATE_SCHEMA: collection.VolDictType = {
    vol.Required("name"): str,
    vol.Optional("person_entity_id"): str,
    vol.Optional("icon"): str,
    vol.Optional("active", default=True): bool,
    # "child" members need a parent's confirmation before their completions
    # count (see RECURRENCE_CONFIRMATION / MEMBER_ROLE_CHILD in const.py).
    # Defaults to "parent" so existing members keep behaving exactly as
    # before this field was introduced.
    vol.Optional("role", default=MEMBER_ROLE_PARENT): vol.In(MEMBER_ROLES),
    # See CONF_MEMBER_REWARDS_OPT_IN in const.py - whether this member shows
    # up on the leaderboard card and may redeem catalog rewards. Defaults to
    # True so every existing member keeps behaving exactly as before this
    # field was introduced.
    vol.Optional(CONF_MEMBER_REWARDS_OPT_IN, default=True): bool,
    # See CONF_MEMBER_NOTIFY_SERVICE in const.py.
    vol.Optional(CONF_MEMBER_NOTIFY_SERVICE): str,
}

MEMBER_UPDATE_SCHEMA: collection.VolDictType = {
    vol.Optional("name"): str,
    vol.Optional("person_entity_id"): str,
    vol.Optional("icon"): str,
    vol.Optional("active"): bool,
    vol.Optional("role"): vol.In(MEMBER_ROLES),
    vol.Optional(CONF_MEMBER_REWARDS_OPT_IN): bool,
    # Explicitly setting this to null clears a previously configured notify
    # service, same "clear via null" pattern used elsewhere in this module.
    vol.Optional(CONF_MEMBER_NOTIFY_SERVICE): vol.Any(None, str),
}


class TaskStorageCollection(collection.DictStorageCollection):
    """Storage collection for recurring task definitions."""

    CREATE_SCHEMA = vol.Schema(TASK_CREATE_SCHEMA)
    UPDATE_SCHEMA = vol.Schema(TASK_UPDATE_SCHEMA)

    async def _process_create_data(self, data: dict) -> dict:
        """Validate data for a new task."""
        validated: dict = self.CREATE_SCHEMA(data)
        recurrence = validated["recurrence"]
        if recurrence["type"] in (
            RECURRENCE_INTERVAL_DAYS,
            RECURRENCE_ONCE,
        ) and not recurrence.get("anchor_date"):
            recurrence["anchor_date"] = dt_util.now().date().isoformat()
        if recurrence["type"] == RECURRENCE_TRIGGER and "trigger" not in recurrence:
            raise vol.Invalid(
                "A 'trigger' recurrence needs a 'trigger' definition (state or "
                "numeric_state)."
            )
        if validated.get("kind") == TASK_KIND_CHECKLIST and not validated.get("subtasks"):
            raise vol.Invalid(
                "A 'checklist' task needs at least one subtask - see TASK_KIND_CHECKLIST."
            )
        return validated

    @callback
    def _get_suggested_id(self, info: dict) -> str:
        return info["name"]

    async def _update_data(self, item: dict, update_data: dict) -> dict:
        """Return a new updated item, merging nested recurrence/rotation dicts."""
        validated = self.UPDATE_SCHEMA(update_data)
        updated = {**item, **validated}
        if "recurrence" in validated:
            updated["recurrence"] = {**item["recurrence"], **validated["recurrence"]}
        if "rotation" in validated:
            updated["rotation"] = {**item["rotation"], **validated["rotation"]}
        if updated["recurrence"]["type"] == RECURRENCE_TRIGGER and "trigger" not in updated[
            "recurrence"
        ]:
            raise vol.Invalid(
                "A 'trigger' recurrence needs a 'trigger' definition (state or "
                "numeric_state)."
            )
        if updated["recurrence"]["type"] in (
            RECURRENCE_INTERVAL_DAYS,
            RECURRENCE_ONCE,
        ) and not updated["recurrence"].get("anchor_date"):
            updated["recurrence"]["anchor_date"] = dt_util.now().date().isoformat()
        if (
            CONF_COMPLETION_BUTTON_ENTITY_ID in validated
            and validated[CONF_COMPLETION_BUTTON_ENTITY_ID] is None
        ):
            # Explicit clear, rather than persisting a literal None - mirrors
            # BatteryOverrideStorageCollection's "threshold" clearing below.
            updated.pop(CONF_COMPLETION_BUTTON_ENTITY_ID, None)
        if updated.get("kind") == TASK_KIND_CHECKLIST and not updated.get("subtasks"):
            raise vol.Invalid(
                "A 'checklist' task needs at least one subtask - see TASK_KIND_CHECKLIST."
            )
        return updated


class MemberStorageCollection(collection.DictStorageCollection):
    """Storage collection for family members."""

    CREATE_SCHEMA = vol.Schema(MEMBER_CREATE_SCHEMA)
    UPDATE_SCHEMA = vol.Schema(MEMBER_UPDATE_SCHEMA)

    async def _process_create_data(self, data: dict) -> dict:
        return self.CREATE_SCHEMA(data)

    @callback
    def _get_suggested_id(self, info: dict) -> str:
        return info["name"]

    async def _update_data(self, item: dict, update_data: dict) -> dict:
        validated = self.UPDATE_SCHEMA(update_data)
        updated = {**item, **validated}
        if (
            CONF_MEMBER_NOTIFY_SERVICE in validated
            and validated[CONF_MEMBER_NOTIFY_SERVICE] is None
        ):
            updated.pop(CONF_MEMBER_NOTIFY_SERVICE, None)
        return updated


# Per-entity overrides for the automatic battery-warning task (recurrence
# type "battery", see RECURRENCE_BATTERY in const.py). Items are created
# lazily, only for batteries the household wants to customize; every other
# battery entity Home Assistant reports (see
# battery.async_discover_battery_entity_ids) is monitored using the
# integration-wide default threshold (CONF_BATTERY_WARNING_THRESHOLD) without
# needing an item here at all.
BATTERY_OVERRIDE_CREATE_SCHEMA: collection.VolDictType = {
    vol.Required("entity_id"): cv.entity_id,
    vol.Optional("excluded", default=False): bool,
    # Percent. Absent/None means "use the integration-wide default".
    vol.Optional("threshold"): vol.All(vol.Coerce(float), vol.Range(min=0, max=100)),
}

BATTERY_OVERRIDE_UPDATE_SCHEMA: collection.VolDictType = {
    vol.Optional("excluded"): bool,
    # Explicitly setting "threshold" to null clears a previously set
    # override and falls back to the default again.
    vol.Optional("threshold"): vol.Any(
        None, vol.All(vol.Coerce(float), vol.Range(min=0, max=100))
    ),
}


class BatteryOverrideStorageCollection(collection.DictStorageCollection):
    """Storage collection for per-entity battery-monitoring overrides."""

    CREATE_SCHEMA = vol.Schema(BATTERY_OVERRIDE_CREATE_SCHEMA)
    UPDATE_SCHEMA = vol.Schema(BATTERY_OVERRIDE_UPDATE_SCHEMA)

    async def _process_create_data(self, data: dict) -> dict:
        return self.CREATE_SCHEMA(data)

    @callback
    def _get_suggested_id(self, info: dict) -> str:
        return info["entity_id"]

    async def _update_data(self, item: dict, update_data: dict) -> dict:
        validated = self.UPDATE_SCHEMA(update_data)
        updated = {**item, **validated}
        if "threshold" in validated and validated["threshold"] is None:
            # Explicit clear, rather than persisting a literal None - keeps
            # battery.async_compute_low_batteries' "threshold" in override
            # check symmetric with an override that never set one.
            updated.pop("threshold", None)
        return updated


# --- Favorites (v0.17) -------------------------------------------------------
#
# See WS_API_PREFIX_FAVORITES in const.py: a "Favorit" is a reusable task
# *template* a parent maintains (name, points, optional fixed assignee, task
# kind) - independent of the tasks collection itself. Clicking one
# (ws_instantiate_favorite below) creates a brand new, independent
# RECURRENCE_ONCE task from it; the template is untouched and can be reused
# any number of times. Structurally this mirrors the reward catalog just
# below (a small parent-maintained list of reusable items), not the tasks
# collection - there is no recurrence/rotation here, just the handful of
# fields a new task needs at creation time.
FAVORITE_CREATE_SCHEMA: collection.VolDictType = {
    vol.Required("name"): str,
    vol.Optional("icon"): str,
    vol.Optional("points", default=0): vol.All(int, vol.Range(min=0)),
    # Fixed assignee(s) every task created from this favorite gets - rotation
    # forced to ROTATION_STRATEGY_FIXED with these members, exactly like an
    # admin-created task with "Fest zugewiesen" and more than one member
    # checked (shared, all simultaneously assigned - see the "Aufgaben-Filter
    # nach Familienmitglied" note in family-tasks-card.js). An empty list
    # means "no fixed assignee", same as an admin-created task with nobody
    # checked under "Rotation". v0.18: a list, not a single optional
    # "member_id" as originally shipped in v0.17 - a favorite can now carry
    # more than one fixed assignee, same as a normal task.
    vol.Optional("member_ids", default=list): [str],
    vol.Optional("kind", default=TASK_KIND_STANDARD): vol.In(TASK_KINDS),
    vol.Optional("subtasks", default=list): vol.All([SUBTASK_SCHEMA], _require_unique_subtask_ids),
}

FAVORITE_UPDATE_SCHEMA: collection.VolDictType = {
    vol.Optional("name"): str,
    vol.Optional("icon"): str,
    vol.Optional("points"): vol.All(int, vol.Range(min=0)),
    vol.Optional("member_ids"): [str],
    vol.Optional("kind"): vol.In(TASK_KINDS),
    vol.Optional("subtasks"): vol.All([SUBTASK_SCHEMA], _require_unique_subtask_ids),
}


class FavoriteStorageCollection(collection.DictStorageCollection):
    """Storage collection for reusable Favoriten task templates."""

    CREATE_SCHEMA = vol.Schema(FAVORITE_CREATE_SCHEMA)
    UPDATE_SCHEMA = vol.Schema(FAVORITE_UPDATE_SCHEMA)

    async def _process_create_data(self, data: dict) -> dict:
        validated: dict = self.CREATE_SCHEMA(data)
        if validated.get("kind") == TASK_KIND_CHECKLIST and not validated.get("subtasks"):
            raise vol.Invalid(
                "Eine Checklisten-Favoriten-Vorlage braucht mindestens eine Unteraufgabe."
            )
        return validated

    @callback
    def _get_suggested_id(self, info: dict) -> str:
        return info["name"]

    async def _update_data(self, item: dict, update_data: dict) -> dict:
        validated = self.UPDATE_SCHEMA(update_data)
        # "member_ids" is a plain list field (unlike e.g. a nested
        # recurrence/rotation dict elsewhere in this module) - a full replace
        # via the dict spread is exactly right here: sending an empty list
        # clears all fixed assignees, same as unchecking every member in the
        # card's favorite form.
        updated = {**item, **validated}
        if updated.get("kind") == TASK_KIND_CHECKLIST and not updated.get("subtasks"):
            raise vol.Invalid(
                "Eine Checklisten-Favoriten-Vorlage braucht mindestens eine Unteraufgabe."
            )
        return updated


class FavoriteStorageCollectionWebsocket(collection.DictStorageCollectionWebsocket):
    """Favorite CRUD over websocket, parent-only like member management.

    Home Assistant's storage-collection websocket API already requires an
    administrator account for create/update/delete (see
    websocket_api.require_admin in the base class). On top of that, same as
    MemberStorageCollectionWebsocket/RewardRedemptionStorageCollectionWebsocket,
    a user linked to a "child" member is rejected outright regardless of
    their HA admin flag - Favoriten management (and instantiating one, see
    ws_instantiate_favorite below) is a parent-only concept end to end.
    """

    def __init__(
        self,
        storage_collection: FavoriteStorageCollection,
        api_prefix: str,
        model_name: str,
        create_schema: collection.VolDictType,
        update_schema: collection.VolDictType,
        members: MemberStorageCollection,
    ) -> None:
        super().__init__(storage_collection, api_prefix, model_name, create_schema, update_schema)
        self._members = members

    def _reject_if_child(
        self, connection: websocket_api.ActiveConnection, msg_id: int
    ) -> bool:
        role = _member_role_for_user(self._members.hass, self._members, connection.user)
        if role == MEMBER_ROLE_CHILD:
            connection.send_error(
                msg_id,
                websocket_api.ERR_UNAUTHORIZED,
                "Mitglieder mit der Rolle 'Kind' dürfen Favoriten nicht anlegen, "
                "bearbeiten oder löschen.",
            )
            return True
        return False

    async def ws_create_item(
        self, hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
    ) -> None:
        if self._reject_if_child(connection, msg["id"]):
            return
        await super().ws_create_item(hass, connection, msg)

    async def ws_update_item(
        self, hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
    ) -> None:
        if self._reject_if_child(connection, msg["id"]):
            return
        await super().ws_update_item(hass, connection, msg)

    async def ws_delete_item(
        self, hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
    ) -> None:
        if self._reject_if_child(connection, msg["id"]):
            return
        await super().ws_delete_item(hass, connection, msg)


# --- Rewards (v0.9) ------------------------------------------------------------
#
# The parent-defined reward catalog: each item has a name and a price in
# points ("points_cost") - see WS_API_PREFIX_REWARDS in const.py. Any
# participating family member may redeem any catalog item at any time
# (see RewardRedemptionStorageCollection below), not just a "weekly winner"
# (v0.8's model, removed in v0.9) - so unlike then, no per-redemption
# customization (the old free-text "detail") is needed here.
REWARD_CREATE_SCHEMA: collection.VolDictType = {
    vol.Required("name"): str,
    vol.Optional("icon"): str,
    vol.Optional("points_cost", default=0): vol.All(int, vol.Range(min=0)),
    # See CONF_REWARD_SCREEN_TIME_MINUTES/EVENT_REWARD_REDEEMED in const.py.
    vol.Optional(CONF_REWARD_SCREEN_TIME_MINUTES): vol.All(int, vol.Range(min=1)),
    # See CONF_REWARD_AUTO_FULFILL in const.py.
    vol.Optional(CONF_REWARD_AUTO_FULFILL, default=False): bool,
    # See CONF_REWARD_SCREEN_TIME_INVESTABLE in const.py.
    vol.Optional(CONF_REWARD_SCREEN_TIME_INVESTABLE, default=False): bool,
    # See CONF_REWARD_NOTE_ENABLED/CONF_REWARD_NOTE_LABEL in const.py.
    vol.Optional(CONF_REWARD_NOTE_ENABLED, default=False): bool,
    vol.Optional(CONF_REWARD_NOTE_LABEL): str,
}

REWARD_UPDATE_SCHEMA: collection.VolDictType = {
    vol.Optional("name"): str,
    vol.Optional("icon"): str,
    vol.Optional("points_cost"): vol.All(int, vol.Range(min=0)),
    # Explicitly setting this to null clears a previously set value - same
    # "clear via null" pattern as BatteryOverrideStorageCollection's
    # "threshold" below.
    vol.Optional(CONF_REWARD_SCREEN_TIME_MINUTES): vol.Any(
        None, vol.All(vol.Coerce(int), vol.Range(min=1))
    ),
    vol.Optional(CONF_REWARD_AUTO_FULFILL): bool,
    vol.Optional(CONF_REWARD_SCREEN_TIME_INVESTABLE): bool,
    vol.Optional(CONF_REWARD_NOTE_ENABLED): bool,
    # Same "explicit null clears it" pattern as screen_time_minutes above -
    # switching "Freitext bei Einlösung" back off leaves a stale label
    # around otherwise (harmless since it's ignored while note_enabled is
    # False, but _update_data below drops it the same way for consistency).
    vol.Optional(CONF_REWARD_NOTE_LABEL): vol.Any(None, str),
}


class RewardStorageCollection(collection.DictStorageCollection):
    """Storage collection for the parent-defined reward catalog.

    Formerly (v0.8) "reward groups" - categories a weekly winner picked from,
    with a free-text detail filled in at claim time. That flow is gone in
    v0.9: every catalog item now has a fixed price in points instead, and any
    participating member may redeem it whenever they can afford it (see
    RewardRedemptionStorageCollection below) - existing items are migrated in
    place the first time this collection loads (see
    _async_migrate_reward_catalog), keeping their name/icon and getting
    points_cost=0 until an admin sets a real price.
    """

    CREATE_SCHEMA = vol.Schema(REWARD_CREATE_SCHEMA)
    UPDATE_SCHEMA = vol.Schema(REWARD_UPDATE_SCHEMA)

    async def _process_create_data(self, data: dict) -> dict:
        return self.CREATE_SCHEMA(data)

    @callback
    def _get_suggested_id(self, info: dict) -> str:
        return info["name"]

    async def _update_data(self, item: dict, update_data: dict) -> dict:
        validated = self.UPDATE_SCHEMA(update_data)
        updated = {**item, **validated}
        if (
            CONF_REWARD_SCREEN_TIME_MINUTES in validated
            and validated[CONF_REWARD_SCREEN_TIME_MINUTES] is None
        ):
            # Explicit clear, rather than persisting a literal None - mirrors
            # BatteryOverrideStorageCollection's "threshold" clearing below.
            updated.pop(CONF_REWARD_SCREEN_TIME_MINUTES, None)
        if (
            CONF_REWARD_NOTE_LABEL in validated
            and validated[CONF_REWARD_NOTE_LABEL] is None
        ):
            updated.pop(CONF_REWARD_NOTE_LABEL, None)
        return updated


# A redemption: which member spent points on which catalog reward. Only ever
# created through ws_redeem_reward below (never the generic
# "reward_redemption/create" command, see
# RewardRedemptionStorageCollectionWebsocket) - "member_name", "reward_name"
# and "points_cost" are denormalized copies taken at redemption time so
# history/display still makes sense even if the member or reward is later
# renamed, repriced, or deleted. Creating one *is* the point deduction: a
# member's available balance (see MemberSummaryData.points_available in
# coordinator.py) is always computed fresh as all-time points earned minus
# the sum of "points_cost" across their redemptions, so there is nothing else
# to update once a redemption exists. "screen_time_minutes" (v0.11) is the
# same kind of denormalized copy, taken from the reward at redemption time -
# see CONF_REWARD_SCREEN_TIME_MINUTES in const.py - so history/the fired
# event still show the value that applied at redemption time even if the
# catalog item's own value is changed or cleared afterwards.
REWARD_REDEMPTION_CREATE_SCHEMA: collection.VolDictType = {
    vol.Required("member_id"): str,
    vol.Required("member_name"): str,
    vol.Required("reward_id"): str,
    vol.Required("reward_name"): str,
    vol.Required("points_cost"): vol.All(int, vol.Range(min=0)),
    vol.Optional("fulfilled", default=False): bool,
    # vol.Coerce(int), not a bare int (v0.16 fix): for a
    # CONF_REWARD_SCREEN_TIME_INVESTABLE redemption this value is computed
    # below as points_invested * the household's "Handyzeit-Minuten pro
    # investiertem Punkt" bonus factor (CONF_SCREEN_TIME_MINUTES_PER_POINT) -
    # and that factor comes back from the Options flow's NumberSelector as a
    # Python float (e.g. 2.0), even when the admin only ever typed a whole
    # number. A bare `int` schema entry does an isinstance() check, not a
    # conversion, so it rejected that float outright with ERR_INVALID_FORMAT -
    # silently, since the card's _confirmRedeem never surfaces a failed
    # callWS to the user (see the confirm-redeem fix in
    # family-tasks-card.js), so redeeming an investable Handyzeit reward
    # looked like the "Bestätigen" button simply did nothing. See
    # ws_redeem_reward below, which now also explicitly casts to int as the
    # actual fix; Coerce here is defense in depth so a future numeric drift
    # like this fails obviously instead of silently again.
    vol.Optional(CONF_REWARD_SCREEN_TIME_MINUTES): vol.All(vol.Coerce(int), vol.Range(min=1)),
    # v0.14: how many points the member chose to invest, only present for a
    # CONF_REWARD_SCREEN_TIME_INVESTABLE redemption - see ws_redeem_reward.
    # For that kind of redemption this is the same number as "points_cost"
    # (both are the deduction), kept as its own field purely so the history/
    # event payload can label it distinctly ("12 Punkte investiert" instead of
    # implying a fixed catalog price).
    vol.Optional("points_invested"): vol.All(int, vol.Range(min=1)),
    # v0.24: the redeeming member's free-text note, only present for a
    # CONF_REWARD_NOTE_ENABLED reward (e.g. which lunch they'd like) - see
    # ws_redeem_reward, which requires a non-blank value whenever the reward
    # asks for one.
    vol.Optional("note"): str,
}

# Only "fulfilled" may ever be changed after the fact - see
# RewardRedemptionStorageCollectionWebsocket, which additionally restricts
# *who* may flip it (parents only, not a "child" member even with an admin
# account).
REWARD_REDEMPTION_UPDATE_SCHEMA: collection.VolDictType = {
    vol.Optional("fulfilled"): bool,
}


class RewardRedemptionStorageCollection(collection.DictStorageCollection):
    """Storage collection for redeemed catalog rewards (points-shop purchases).

    Formerly (v0.8) "claimed weekly-winner rewards", one per member per
    calendar week. v0.9 removes that limit entirely - a member may redeem as
    often as their balance allows - existing items are migrated in place the
    first time this collection loads (see _async_migrate_reward_redemptions):
    mapped onto the new shape with points_cost=0 so they never retroactively
    reduce anyone's balance, exactly as if that historical claim had been free.
    """

    CREATE_SCHEMA = vol.Schema(REWARD_REDEMPTION_CREATE_SCHEMA)
    UPDATE_SCHEMA = vol.Schema(REWARD_REDEMPTION_UPDATE_SCHEMA)

    async def _process_create_data(self, data: dict) -> dict:
        validated = self.CREATE_SCHEMA(data)
        validated["redeemed_at"] = dt_util.utcnow().isoformat()
        return validated

    @callback
    def _get_suggested_id(self, info: dict) -> str:
        # A member may redeem the same reward more than once (no longer
        # once-per-week, see above) - IDManager appends "_2", "_3", ... on
        # collision, so this is just a readable base, not required to be
        # unique by itself.
        return f"{info['member_id']}-{info['reward_id']}"

    async def _update_data(self, item: dict, update_data: dict) -> dict:
        validated = self.UPDATE_SCHEMA(update_data)
        return {**item, **validated}


class RewardRedemptionStorageCollectionWebsocket(collection.DictStorageCollectionWebsocket):
    """Redemption CRUD over websocket, restricted beyond the base admin check.

    Creating a redemption is never allowed through the generic
    "reward_redemption/create" command, even for an admin - that's the whole
    point of the WS_API_REWARD_REDEEM flow (see ws_redeem_reward below): it
    has to check that the caller participates in the reward system and can
    actually afford the reward before an item may be created at all, which
    the generic storage-collection create command has no way to enforce.
    Marking a redemption "fulfilled" (the only field the update command
    allows in the first place, see REWARD_REDEMPTION_UPDATE_SCHEMA)
    additionally requires the caller not be linked to a "child" member,
    regardless of their HA admin flag - the same rule
    MemberStorageCollectionWebsocket applies to member management - so a
    child can't tick off their own redemption.
    """

    def __init__(
        self,
        storage_collection: RewardRedemptionStorageCollection,
        api_prefix: str,
        model_name: str,
        create_schema: collection.VolDictType,
        update_schema: collection.VolDictType,
        members: MemberStorageCollection,
    ) -> None:
        super().__init__(storage_collection, api_prefix, model_name, create_schema, update_schema)
        self._members = members

    def _reject_if_child(
        self, connection: websocket_api.ActiveConnection, msg_id: int
    ) -> bool:
        role = _member_role_for_user(self._members.hass, self._members, connection.user)
        if role == MEMBER_ROLE_CHILD:
            connection.send_error(
                msg_id,
                websocket_api.ERR_UNAUTHORIZED,
                "Mitglieder mit der Rolle 'Kind' dürfen Belohnungen nicht als "
                "erledigt markieren oder löschen.",
            )
            return True
        return False

    async def ws_create_item(
        self, hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
    ) -> None:
        connection.send_error(
            msg["id"],
            websocket_api.ERR_UNAUTHORIZED,
            "Belohnungen können nur über family_tasks/reward_redemption/redeem "
            "eingelöst werden.",
        )

    async def ws_update_item(
        self, hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
    ) -> None:
        if self._reject_if_child(connection, msg["id"]):
            return
        await super().ws_update_item(hass, connection, msg)

    async def ws_delete_item(
        self, hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
    ) -> None:
        if self._reject_if_child(connection, msg["id"]):
            return
        await super().ws_delete_item(hass, connection, msg)


def _member_id_for_user(
    hass: HomeAssistant, members: MemberStorageCollection, user: Any
) -> str | None:
    """Resolve the family member linked to a logged-in HA user, if any.

    The link goes through the "person" integration: a member's
    person_entity_id points at a person entity, and that person entity's
    "user_id" attribute (set when the person is linked to a HA user account
    in Settings -> People) identifies the HA user. Returns None if the user
    isn't linked to any member - callers should treat that as "not a child",
    i.e. not restricted, so accounts with no member link keep working exactly
    as before this lookup existed.
    """
    if user is None:
        return None
    for member_id, member in members.data.items():
        person_entity_id = member.get("person_entity_id")
        if not person_entity_id:
            continue
        state = hass.states.get(person_entity_id)
        if state is not None and state.attributes.get("user_id") == user.id:
            return member_id
    return None


def _member_role_for_user(
    hass: HomeAssistant, members: MemberStorageCollection, user: Any
) -> str | None:
    """Return the role of the member linked to a user, or None if unlinked."""
    member_id = _member_id_for_user(hass, members, user)
    if member_id is None:
        return None
    return members.data[member_id].get("role", MEMBER_ROLE_PARENT)


async def async_member_id_for_context(
    hass: HomeAssistant, members: MemberStorageCollection, context: Context | None
) -> str | None:
    """Resolve the family member linked to a service call's calling user.

    Mirrors _member_id_for_user, but a plain ``hass.services.async_call`` (the
    family_tasks.complete_task/toggle_subtask services, see
    _async_register_services in __init__.py) has no equivalent of the
    websocket API's already-resolved ``connection.user`` - only a Context
    carrying the caller's user_id (set automatically by HA for any call
    originating from a logged-in frontend session; None for calls with no
    associated user, e.g. from an automation). Returns None in that case, same
    as _member_id_for_user does for an unlinked/unknown user - callers should
    treat that as "can't tell who this is", not as an error.
    """
    if context is None or context.user_id is None:
        return None
    user = await hass.auth.async_get_user(context.user_id)
    return _member_id_for_user(hass, members, user)


class MemberStorageCollectionWebsocket(collection.DictStorageCollectionWebsocket):
    """Member CRUD over websocket, with an extra role-based guard.

    Home Assistant's storage-collection websocket API already requires an
    administrator account for create/update/delete (see
    websocket_api.require_admin in the base class). That alone isn't enough
    here: a household may not want to (or be able to) set up a separate,
    non-admin HA user for every child. So on top of the admin check, any
    request from a user linked (via person_entity_id) to a member with role
    "child" is rejected outright, regardless of that user's admin flag -
    children may never create, edit, or delete family members.
    """

    def __init__(
        self,
        storage_collection: MemberStorageCollection,
        api_prefix: str,
        model_name: str,
        create_schema: collection.VolDictType,
        update_schema: collection.VolDictType,
    ) -> None:
        super().__init__(storage_collection, api_prefix, model_name, create_schema, update_schema)
        self._members = storage_collection

    def _reject_if_child(
        self, connection: websocket_api.ActiveConnection, msg_id: int
    ) -> bool:
        role = _member_role_for_user(self._members.hass, self._members, connection.user)
        if role == MEMBER_ROLE_CHILD:
            connection.send_error(
                msg_id,
                websocket_api.ERR_UNAUTHORIZED,
                "Mitglieder mit der Rolle 'Kind' dürfen keine Familienmitglieder "
                "anlegen, bearbeiten oder löschen.",
            )
            return True
        return False

    async def ws_create_item(
        self, hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
    ) -> None:
        if self._reject_if_child(connection, msg["id"]):
            return
        await super().ws_create_item(hass, connection, msg)

    async def ws_update_item(
        self, hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
    ) -> None:
        if self._reject_if_child(connection, msg["id"]):
            return
        await super().ws_update_item(hass, connection, msg)

    async def ws_delete_item(
        self, hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
    ) -> None:
        if self._reject_if_child(connection, msg["id"]):
            return
        await super().ws_delete_item(hass, connection, msg)


# Schema for the non-admin "create a task for myself" command (see
# WS_API_TASK_CREATE_OWN in const.py). Deliberately excludes "points" and
# "rotation" - both are forced server-side in ws_create_own_task - and
# "confirms", which is coordinator-internal only.
CREATE_OWN_TASK_SCHEMA = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_API_TASK_CREATE_OWN,
        vol.Required("name"): str,
        vol.Optional("icon"): str,
        vol.Optional("due_time"): str,
        vol.Optional("overdue_after_minutes"): vol.All(int, vol.Range(min=0)),
        vol.Required("recurrence"): RECURRENCE_SCHEMA,
        # Chosen by the child creating the task: whether a parent has to sign
        # off before it counts as done. Defaults to True (the safer default).
        vol.Optional(CONF_TASK_REQUIRES_CONFIRMATION, default=True): bool,
        # A child may also create a checklist task for themselves (see
        # TASK_KIND_CHECKLIST in const.py) - same "kind"/"subtasks" fields as
        # the admin task schema; TaskStorageCollection._process_create_data
        # (invoked below via tasks.async_create_item) already enforces at
        # least one subtask for a checklist, no extra check needed here.
        # "mandatory" (TASK_KIND_MANDATORY) is deliberately excluded here -
        # see OWN_TASK_KINDS in const.py: it exists to let a parent gate a
        # child's screen time, not something a child should be able to set up
        # for themselves.
        vol.Optional("kind", default=TASK_KIND_STANDARD): vol.In(OWN_TASK_KINDS),
        vol.Optional("subtasks", default=list): vol.All(
            [SUBTASK_SCHEMA], _require_unique_subtask_ids
        ),
    }
)


REDEEM_REWARD_SCHEMA = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_API_REWARD_REDEEM,
        vol.Required("reward_id"): str,
        # v0.14: required (and only meaningful) for a
        # CONF_REWARD_SCREEN_TIME_INVESTABLE reward - how many points the
        # member wants to invest this time; the backend re-derives the
        # granted screen time from this (points_spent *
        # CONF_SCREEN_TIME_MINUTES_PER_POINT) rather than trusting a
        # client-computed minutes value. Ignored for any other reward.
        vol.Optional("points_spent"): vol.All(int, vol.Range(min=1)),
        # v0.24: required (and only meaningful) for a CONF_REWARD_NOTE_ENABLED
        # reward - e.g. which lunch the member wants for "Mittagessen
        # auswählen". Ignored for any other reward; ws_redeem_reward rejects
        # the redemption if the reward requires one and this is missing/blank.
        vol.Optional("note"): str,
    }
)


# v0.24 - see WS_API_POINTS_AWARD in const.py. "points" may be negative (a
# correction/deduction); zero is rejected in the handler below rather than
# here, so the error message can be specific instead of voluptuous' generic
# "value must be..." wording. The range bound is just a sanity limit against
# obvious fat-finger input, not a meaningful business rule.
AWARD_POINTS_SCHEMA = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_API_POINTS_AWARD,
        vol.Required("member_id"): str,
        vol.Required("points"): vol.All(int, vol.Range(min=-100000, max=100000)),
        vol.Optional("note"): str,
    }
)


def _available_points(
    completions: CompletionLogStore,
    reward_redemptions: RewardRedemptionStorageCollection,
    member_id: str,
) -> int:
    """A member's current spendable balance: all-time points minus redemptions.

    Mirrors FamilyTasksCoordinator._async_update_data's points_available
    computation (MemberSummaryData.points_available in coordinator.py) -
    duplicated here, not imported, the same way the old is_weekly_winner
    check used to be re-derived server-side independently of the coordinator,
    so a redemption is always validated against the authoritative source
    (the completion log + redemption history) rather than a value the client
    happens to have cached.
    """
    since = datetime.min.replace(tzinfo=dt_util.UTC)
    total = completions.points_since(member_id, since)
    spent = sum(
        r.get("points_cost", 0)
        for r in reward_redemptions.data.values()
        if r.get("member_id") == member_id
    )
    return total - spent


@callback
def async_setup_websocket_api(
    hass: HomeAssistant,
    entry: Any,
    tasks: TaskStorageCollection,
    members: MemberStorageCollection,
    battery_overrides: BatteryOverrideStorageCollection,
    rewards: RewardStorageCollection,
    reward_redemptions: RewardRedemptionStorageCollection,
    completions: CompletionLogStore,
    favorites: FavoriteStorageCollection,
) -> None:
    """Expose the storage collections over the websocket API for the frontend.

    ``entry`` (the config entry) is only needed so ws_redeem_reward can read
    CONF_SCREEN_TIME_MINUTES_PER_POINT from its options fresh on every
    redemption - same "read live, don't cache at setup" approach already used
    for CONF_OVERDUE_AFTER_MINUTES/CONF_BATTERY_WARNING_THRESHOLD in
    coordinator.py, so a parent changing the bonus factor in Settings applies
    immediately without a restart.
    """
    collection.DictStorageCollectionWebsocket(
        tasks, WS_API_PREFIX_TASKS, "task", TASK_CREATE_SCHEMA, TASK_UPDATE_SCHEMA
    ).async_setup(hass)
    MemberStorageCollectionWebsocket(
        members,
        WS_API_PREFIX_MEMBERS,
        "member",
        MEMBER_CREATE_SCHEMA,
        MEMBER_UPDATE_SCHEMA,
    ).async_setup(hass)
    # Plain CRUD, same as tasks - no extra role guard needed, unlike members:
    # battery overrides are an admin-only monitoring setting, not something a
    # "child" member's account would ever touch.
    collection.DictStorageCollectionWebsocket(
        battery_overrides,
        WS_API_PREFIX_BATTERY_OVERRIDES,
        "battery_override",
        BATTERY_OVERRIDE_CREATE_SCHEMA,
        BATTERY_OVERRIDE_UPDATE_SCHEMA,
    ).async_setup(hass)
    # The reward catalog is an admin-only (parent) monitoring-style setting,
    # same as battery overrides - plain CRUD, no extra role guard.
    collection.DictStorageCollectionWebsocket(
        rewards,
        WS_API_PREFIX_REWARDS,
        "reward",
        REWARD_CREATE_SCHEMA,
        REWARD_UPDATE_SCHEMA,
    ).async_setup(hass)
    # Redemptions themselves need the extra guards in
    # RewardRedemptionStorageCollectionWebsocket (create blocked entirely -
    # see WS_API_REWARD_REDEEM below - and "fulfilled" restricted to
    # non-child callers).
    RewardRedemptionStorageCollectionWebsocket(
        reward_redemptions,
        WS_API_PREFIX_REWARD_REDEMPTIONS,
        "reward_redemption",
        REWARD_REDEMPTION_CREATE_SCHEMA,
        REWARD_REDEMPTION_UPDATE_SCHEMA,
        members,
    ).async_setup(hass)
    # Favoriten CRUD needs the same "no child, regardless of HA admin flag"
    # guard as members/reward-catalog management - see
    # FavoriteStorageCollectionWebsocket above.
    FavoriteStorageCollectionWebsocket(
        favorites,
        WS_API_PREFIX_FAVORITES,
        "favorite",
        FAVORITE_CREATE_SCHEMA,
        FAVORITE_UPDATE_SCHEMA,
        members,
    ).async_setup(hass)

    @websocket_api.async_response
    async def ws_redeem_reward(
        hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
    ) -> None:
        """Let a participating member redeem a catalog reward.

        No admin permission required - instead the caller must resolve (via
        their linked person entity) to a family member who participates in
        the reward system (see CONF_MEMBER_REWARDS_OPT_IN in const.py), and
        that member's current available balance (_available_points above)
        must cover the reward's price. Creating the redemption entry is
        itself the deduction - there is no separate balance to update.

        A CONF_REWARD_SCREEN_TIME_INVESTABLE reward (v0.14) works
        differently: there is no fixed "points_cost" to check against - the
        caller supplies "points_spent" instead, and the screen time granted
        is derived from it (points_spent * CONF_SCREEN_TIME_MINUTES_PER_POINT,
        the household-wide bonus factor from Options) rather than a value
        stored on the catalog item. The balance check and deduction use
        points_spent in place of the (unused, for this reward kind)
        points_cost field.
        """
        member_id = _member_id_for_user(hass, members, connection.user)
        member = members.data.get(member_id) if member_id else None
        if member is None:
            connection.send_error(
                msg["id"],
                websocket_api.ERR_UNAUTHORIZED,
                "Kein mit diesem Konto verknüpftes Familienmitglied.",
            )
            return

        if not member.get(CONF_MEMBER_REWARDS_OPT_IN, True):
            connection.send_error(
                msg["id"],
                websocket_api.ERR_UNAUTHORIZED,
                "Dieses Familienmitglied nimmt nicht am Belohnungssystem teil.",
            )
            return

        reward = rewards.data.get(msg["reward_id"])
        if reward is None:
            connection.send_error(
                msg["id"], websocket_api.ERR_NOT_FOUND, "Belohnung nicht gefunden."
            )
            return

        is_investable = bool(reward.get(CONF_REWARD_SCREEN_TIME_INVESTABLE))
        points_invested: int | None = None
        screen_time_minutes = reward.get(CONF_REWARD_SCREEN_TIME_MINUTES)

        if is_investable:
            points_invested = msg.get("points_spent")
            if not points_invested:
                connection.send_error(
                    msg["id"],
                    websocket_api.ERR_INVALID_FORMAT,
                    "Bitte angeben, wie viele Punkte investiert werden sollen.",
                )
                return
            points_cost = points_invested
            bonus_per_point = (
                entry.options.get(
                    CONF_SCREEN_TIME_MINUTES_PER_POINT, DEFAULT_SCREEN_TIME_MINUTES_PER_POINT
                )
                if entry is not None
                else DEFAULT_SCREEN_TIME_MINUTES_PER_POINT
            )
            # int(), not just the raw product (v0.16 fix): the Options flow's
            # NumberSelector always returns bonus_per_point as a Python float
            # (e.g. 2.0) once an admin has ever saved the integration's
            # options, even for a whole number - so this product came out as
            # a float too, which REWARD_REDEMPTION_CREATE_SCHEMA's
            # screen_time_minutes field then rejected (see the schema
            # comment above), making every investable-reward redemption fail
            # silently. Rounding first avoids truncating down on a
            # non-integer bonus factor (e.g. 1.5 min/point).
            screen_time_minutes = int(round(points_invested * bonus_per_point))
        else:
            points_cost = reward.get("points_cost", 0)

        # v0.24: a CONF_REWARD_NOTE_ENABLED reward (e.g. "Mittagessen
        # auswählen") needs a non-blank note before it may be redeemed at
        # all - checked here, before the balance check below, so a member
        # who forgot to fill it in sees that specific error rather than a
        # possibly-unrelated "not enough points" one.
        note: str | None = None
        if reward.get(CONF_REWARD_NOTE_ENABLED):
            note = (msg.get("note") or "").strip()
            if not note:
                connection.send_error(
                    msg["id"],
                    websocket_api.ERR_INVALID_FORMAT,
                    "Bitte einen Text eingeben.",
                )
                return

        available = _available_points(completions, reward_redemptions, member_id)
        if available < points_cost:
            connection.send_error(
                msg["id"],
                websocket_api.ERR_INVALID_FORMAT,
                "Nicht genug Punkte für diese Belohnung.",
            )
            return

        try:
            redemption_data = {
                "member_id": member_id,
                "member_name": member["name"],
                "reward_id": reward["id"],
                "reward_name": reward["name"],
                "points_cost": points_cost,
            }
            if screen_time_minutes is not None:
                redemption_data[CONF_REWARD_SCREEN_TIME_MINUTES] = screen_time_minutes
            if points_invested is not None:
                redemption_data["points_invested"] = points_invested
            if note is not None:
                redemption_data["note"] = note
            # See CONF_REWARD_AUTO_FULFILL in const.py: a reward configured
            # that way (typically a screen-time reward, granted automatically
            # by a household automation reacting to EVENT_REWARD_REDEEMED
            # below) is created already "fulfilled" instead of sitting in the
            # "Bisherige Einlösungen" list waiting for a parent to mark it so
            # by hand.
            if reward.get(CONF_REWARD_AUTO_FULFILL):
                redemption_data["fulfilled"] = True
            item = await reward_redemptions.async_create_item(redemption_data)
            connection.send_result(msg["id"], item)
        except vol.Invalid as err:
            connection.send_error(msg["id"], websocket_api.ERR_INVALID_FORMAT, humanize_error(msg, err))
            return

        # Fires unconditionally, independent of screen_time_minutes: this is
        # the generic "a redemption just happened" extension point (see
        # EVENT_REWARD_REDEEMED in const.py), not screen-time-specific. A
        # household automation with an event trigger decides for itself what
        # to do with it - e.g. branch on event_data["member_id"] to bump the
        # right child's Google Family Link screen time by
        # event_data["screen_time_minutes"] if present, immediately and
        # without any parent having to intervene.
        hass.bus.async_fire(
            EVENT_REWARD_REDEEMED,
            {
                "member_id": member_id,
                "member_name": member["name"],
                "reward_id": reward["id"],
                "reward_name": reward["name"],
                "points_cost": points_cost,
                "points_invested": points_invested,
                CONF_REWARD_SCREEN_TIME_MINUTES: screen_time_minutes,
                "note": note,
            },
        )

    websocket_api.async_register_command(hass, WS_API_REWARD_REDEEM, ws_redeem_reward, REDEEM_REWARD_SCHEMA)

    @websocket_api.async_response
    async def ws_award_points(
        hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
    ) -> None:
        """Let a parent grant (or, with a negative amount, deduct) points for a member.

        Independent of any task or reward - see WS_API_POINTS_AWARD in
        const.py. Parent-only, same "not a child, regardless of HA admin
        flag" guard used throughout this module (ws_instantiate_favorite,
        reward-redemption "fulfilled", member management). Logged via the
        normal completion log under the internal MANUAL_POINTS_TASK_ID
        sentinel (same mechanism CompletionLogStore already uses for the
        weekly-winner bonus) so it counts toward the member's points_total/
        points_week/points_month/points_available exactly like a real task
        completion - there is no separate "adjustments" ledger.

        CompletionLogStore is a plain append-only log, not a
        StorageCollection - unlike tasks/members/reward_redemptions there is
        no change-set listener wired up in __init__.py to trigger a
        coordinator refresh automatically, so this reads the coordinator
        straight off the config entry's runtime_data (populated by the time
        this handler actually runs, well after async_setup_websocket_api
        itself returns during setup - same "resolved lazily, not at
        registration time" trick already used for entry.options in
        ws_redeem_reward above) and requests one explicitly, the same way
        FamilyTasksCoordinator's own async_complete_task/async_skip_task
        already do right after their own completions.async_add_entry call.
        """
        role = _member_role_for_user(hass, members, connection.user)
        if role == MEMBER_ROLE_CHILD:
            connection.send_error(
                msg["id"],
                websocket_api.ERR_UNAUTHORIZED,
                "Mitglieder mit der Rolle 'Kind' dürfen keine Punkte vergeben.",
            )
            return

        member = members.data.get(msg["member_id"])
        if member is None:
            connection.send_error(
                msg["id"], websocket_api.ERR_NOT_FOUND, "Familienmitglied nicht gefunden."
            )
            return

        points = msg["points"]
        if points == 0:
            connection.send_error(
                msg["id"], websocket_api.ERR_INVALID_FORMAT, "Punktzahl darf nicht 0 sein."
            )
            return

        note = (msg.get("note") or "").strip() or None
        entry_item = await completions.async_add_entry(
            task_id=MANUAL_POINTS_TASK_ID,
            period_key=dt_util.utcnow().date().isoformat(),
            member_id=msg["member_id"],
            points_awarded=points,
            task_name=note or ("Punkte erteilt" if points > 0 else "Punkte abgezogen"),
        )

        runtime_data = getattr(entry, "runtime_data", None) if entry is not None else None
        coordinator = getattr(runtime_data, "coordinator", None)
        if coordinator is not None:
            await coordinator.async_request_refresh()

        connection.send_result(msg["id"], entry_item)

    websocket_api.async_register_command(hass, WS_API_POINTS_AWARD, ws_award_points, AWARD_POINTS_SCHEMA)

    @websocket_api.async_response
    async def ws_create_own_task(
        hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
    ) -> None:
        """Let a "child" member create a task assigned only to themselves.

        No admin permission required - instead the caller must resolve (via
        their linked person entity) to a member with role "child". Points are
        always forced to 0 and the rotation is forced to that single member,
        so a child can never award themselves points or assign the task to
        someone else.
        """
        member_id = _member_id_for_user(hass, members, connection.user)
        role = members.data.get(member_id, {}).get("role") if member_id else None
        if member_id is None or role != MEMBER_ROLE_CHILD:
            connection.send_error(
                msg["id"],
                websocket_api.ERR_UNAUTHORIZED,
                "Nur Familienmitglieder mit der Rolle 'Kind' können eigene "
                "Aufgaben ohne Admin-Rechte anlegen.",
            )
            return

        data = dict(msg)
        data.pop("id")
        data.pop("type")
        requires_confirmation = data.pop(CONF_TASK_REQUIRES_CONFIRMATION, True)
        data["points"] = 0
        data["enabled"] = True
        data["rotation"] = {"member_ids": [member_id], "strategy": ROTATION_STRATEGY_FIXED}
        data[CONF_TASK_REQUIRES_CONFIRMATION] = requires_confirmation
        # v0.22: tags the task with its creator so the card can hide it from
        # everyone else - see CONF_TASK_CREATED_BY_MEMBER_ID in const.py.
        data[CONF_TASK_CREATED_BY_MEMBER_ID] = member_id

        try:
            item = await tasks.async_create_item(data)
            connection.send_result(msg["id"], item)
        except vol.Invalid as err:
            connection.send_error(
                msg["id"], websocket_api.ERR_INVALID_FORMAT, humanize_error(data, err)
            )
        except ValueError as err:
            connection.send_error(msg["id"], websocket_api.ERR_INVALID_FORMAT, str(err))

    websocket_api.async_register_command(
        hass, WS_API_TASK_CREATE_OWN, ws_create_own_task, CREATE_OWN_TASK_SCHEMA
    )

    @websocket_api.async_response
    async def ws_list_member_weekly_completions(
        hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
    ) -> None:
        """Return one member's non-skipped completions for the current calendar week.

        Backs the Bestenliste's click-through ("which tasks did this member
        complete this week") - see WS_API_MEMBER_WEEKLY_COMPLETIONS in
        const.py. The week boundary mirrors
        FamilyTasksCoordinator._async_update_data's start_of_week exactly
        (Monday 00:00 local) so this always lines up with the points_week
        figure already shown on the leaderboard. Not admin-restricted - any
        logged-in user may look up any member's completions, same as the
        leaderboard/points sensors themselves are already visible to
        everyone regardless of role. Excludes WEEKLY_BONUS_TASK_ID and
        MANUAL_POINTS_TASK_ID entries (v0.24) - neither is a completed task,
        even though both count normally toward the member's point totals.
        """
        member_id = msg["member_id"]
        if member_id not in members.data:
            connection.send_error(
                msg["id"], websocket_api.ERR_NOT_FOUND, "Familienmitglied nicht gefunden."
            )
            return

        local_now = dt_util.now()
        start_of_today = dt_util.as_utc(dt_util.start_of_local_day(local_now))
        start_of_week = start_of_today - timedelta(days=start_of_today.weekday())

        results: list[dict[str, Any]] = []
        for entry in completions.entries:
            if entry.get("completed_by_member_id") != member_id:
                continue
            if entry.get("skipped") or entry.get("task_id") in (
                WEEKLY_BONUS_TASK_ID,
                MANUAL_POINTS_TASK_ID,
            ):
                continue
            completed_at = dt_util.parse_datetime(entry.get("completed_at", ""))
            if completed_at is None or completed_at < start_of_week:
                continue
            # Prefer the denormalized name captured at completion time (v0.22)
            # - a "once" task is deleted the moment it's completed, so an
            # older entry (or one from before this field existed) falls back
            # to looking the task up by id, and finally to a generic label if
            # even that's gone.
            task = tasks.data.get(entry["task_id"])
            task_name = entry.get("task_name") or (task["name"] if task else "Aufgabe")
            results.append(
                {
                    "task_id": entry["task_id"],
                    "task_name": task_name,
                    "points_awarded": entry.get("points_awarded", 0),
                    "completed_at": entry["completed_at"],
                }
            )
        results.sort(key=lambda r: r["completed_at"], reverse=True)
        connection.send_result(msg["id"], {"completions": results})

    websocket_api.async_register_command(
        hass,
        WS_API_MEMBER_WEEKLY_COMPLETIONS,
        ws_list_member_weekly_completions,
        websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
            {
                vol.Required("type"): WS_API_MEMBER_WEEKLY_COMPLETIONS,
                vol.Required("member_id"): str,
            }
        ),
    )

    @websocket_api.require_admin
    @websocket_api.async_response
    async def ws_instantiate_favorite(
        hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
    ) -> None:
        """Create a new, independent RECURRENCE_ONCE task from a Favorit template.

        Parent-only, same as favorite CRUD itself (FavoriteStorageCollectionWebsocket)
        - @require_admin covers the HA-admin part, the role check below adds
        the same "not a child, regardless of HA admin flag" restriction used
        throughout this module. The favorite template itself is never
        modified by this - it stays exactly as configured and can be clicked
        again to create another, independent task.
        """
        role = _member_role_for_user(hass, members, connection.user)
        if role == MEMBER_ROLE_CHILD:
            connection.send_error(
                msg["id"],
                websocket_api.ERR_UNAUTHORIZED,
                "Mitglieder mit der Rolle 'Kind' dürfen keine Aufgaben aus "
                "Favoriten erstellen.",
            )
            return

        favorite = favorites.data.get(msg["favorite_id"])
        if favorite is None:
            connection.send_error(
                msg["id"], websocket_api.ERR_NOT_FOUND, "Favorit nicht gefunden."
            )
            return

        task_data: dict[str, Any] = {
            "name": favorite["name"],
            "points": favorite.get("points", 0),
            "enabled": True,
            # Always a single, never-repeating occurrence - see RECURRENCE_ONCE
            # in const.py. TaskStorageCollection._process_create_data fills in
            # "anchor_date" (today) since it's absent here.
            "recurrence": {"type": RECURRENCE_ONCE},
            # ROTATION_STRATEGY_FIXED with the favorite's member_ids as-is -
            # zero, one, or several members, exactly like an admin-created
            # task's own "Fest zugewiesen" rotation (several means shared,
            # all simultaneously assigned, not "pick one").
            "rotation": {
                "member_ids": list(favorite.get("member_ids") or []),
                "strategy": ROTATION_STRATEGY_FIXED,
            },
            "kind": favorite.get("kind", TASK_KIND_STANDARD),
        }
        if favorite.get("icon"):
            task_data["icon"] = favorite["icon"]
        if favorite.get("kind") == TASK_KIND_CHECKLIST:
            # Fresh copy, not a shared reference - each instantiated task owns
            # its own subtask list from here on, editable independently of the
            # favorite it was created from.
            task_data["subtasks"] = [dict(s) for s in favorite.get("subtasks", [])]

        try:
            item = await tasks.async_create_item(task_data)
            connection.send_result(msg["id"], item)
        except vol.Invalid as err:
            connection.send_error(
                msg["id"], websocket_api.ERR_INVALID_FORMAT, humanize_error(task_data, err)
            )

    websocket_api.async_register_command(
        hass,
        WS_API_FAVORITE_INSTANTIATE,
        ws_instantiate_favorite,
        websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
            {
                vol.Required("type"): WS_API_FAVORITE_INSTANTIATE,
                vol.Required("favorite_id"): str,
            }
        ),
    )


async def async_create_tasks_collection(hass: HomeAssistant) -> TaskStorageCollection:
    """Create and load the tasks storage collection."""
    store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY_TASKS, minor_version=STORAGE_VERSION_MINOR)
    id_manager = collection.IDManager()
    tasks = TaskStorageCollection(store, id_manager)
    await tasks.async_load()
    return tasks


async def async_create_members_collection(
    hass: HomeAssistant,
) -> MemberStorageCollection:
    """Create and load the members storage collection."""
    store: Store = Store(
        hass, STORAGE_VERSION, STORAGE_KEY_MEMBERS, minor_version=STORAGE_VERSION_MINOR
    )
    id_manager = collection.IDManager()
    members = MemberStorageCollection(store, id_manager)
    await members.async_load()
    return members


async def async_create_battery_overrides_collection(
    hass: HomeAssistant,
) -> BatteryOverrideStorageCollection:
    """Create and load the battery-override storage collection."""
    store: Store = Store(
        hass,
        STORAGE_VERSION,
        STORAGE_KEY_BATTERY_OVERRIDES,
        minor_version=STORAGE_VERSION_MINOR,
    )
    id_manager = collection.IDManager()
    battery_overrides = BatteryOverrideStorageCollection(store, id_manager)
    await battery_overrides.async_load()
    return battery_overrides


async def async_create_favorites_collection(hass: HomeAssistant) -> FavoriteStorageCollection:
    """Create and load the Favoriten template storage collection."""
    store: Store = Store(
        hass, STORAGE_VERSION, STORAGE_KEY_FAVORITES, minor_version=STORAGE_VERSION_MINOR
    )
    id_manager = collection.IDManager()
    favorites = FavoriteStorageCollection(store, id_manager)
    await favorites.async_load()
    return favorites


async def _async_migrate_reward_catalog(rewards: RewardStorageCollection) -> None:
    """Backfill v0.8 "reward group" items with the new "points_cost" field.

    v0.8 items only ever had "name"/"icon" - each gets points_cost=0 here, so
    the household sees them appear in the v0.9 catalog immediately (an admin
    then has to set a real price for them to be worth anything). Writes
    directly to storage rather than going through async_update_item, since
    that validates against REWARD_UPDATE_SCHEMA via the normal admin-facing
    update flow - fine for a single field backfill like this, but there is no
    need to round-trip through it for a one-time migration.
    """
    changed = False
    for item in rewards.data.values():
        if "points_cost" not in item:
            item["points_cost"] = 0
            changed = True
    if changed:
        await rewards.store.async_save({"items": list(rewards.data.values())})


async def _async_migrate_reward_redemptions(
    reward_redemptions: RewardRedemptionStorageCollection,
) -> None:
    """Backfill v0.8 "claimed reward" items into the v0.9 redemption shape.

    v0.8 items carry "reward_group_id"/"reward_group_name"/"detail"/
    "period_key" instead of "reward_id"/"reward_name"/"points_cost". Every
    migrated item gets points_cost=0 so it never retroactively reduces
    anyone's balance - exactly as if that historical claim had been free. The
    free-text "detail" (e.g. which lunch) has no v0.9 equivalent field, so
    it's folded into "reward_name" instead of being silently dropped.
    """
    changed = False
    for item in reward_redemptions.data.values():
        if "points_cost" in item:
            continue
        reward_id = item.pop("reward_group_id", None)
        reward_name = item.pop("reward_group_name", None)
        detail = item.pop("detail", None)
        item.pop("period_key", None)
        item["reward_id"] = item.get("reward_id", reward_id)
        item["reward_name"] = item.get("reward_name", reward_name)
        if detail:
            item["reward_name"] = f"{item['reward_name']} ({detail})"
        item["points_cost"] = 0
        item.setdefault("redeemed_at", item.get("created_at"))
        changed = True
    if changed:
        await reward_redemptions.store.async_save(
            {"items": list(reward_redemptions.data.values())}
        )


async def _async_migrate_screen_time_investable(rewards: RewardStorageCollection) -> None:
    """Switch existing "Handyzeit" rewards over to the v0.14 invest-points flow.

    Before v0.14, a reward with CONF_REWARD_SCREEN_TIME_MINUTES set granted a
    fixed number of minutes for a fixed "points_cost". From v0.14 on, that
    kind of reward instead lets the redeeming member choose how many points
    to invest, multiplied by the household-wide
    CONF_SCREEN_TIME_MINUTES_PER_POINT bonus factor - see
    CONF_REWARD_SCREEN_TIME_INVESTABLE in const.py. Every existing catalog
    item that already has screen_time_minutes set is therefore flagged
    investable here the first time this collection loads under v0.14, so a
    household's existing Handyzeit rewards pick up the new dynamic behavior
    automatically instead of silently keeping the old fixed-minutes one.
    Items created fresh after this point already go through
    REWARD_CREATE_SCHEMA, which defaults the flag to False - a parent has to
    deliberately pick "Handyzeit" as the reward type for a new item.
    """
    changed = False
    for item in rewards.data.values():
        if item.get(CONF_REWARD_SCREEN_TIME_MINUTES) is not None and CONF_REWARD_SCREEN_TIME_INVESTABLE not in item:
            item[CONF_REWARD_SCREEN_TIME_INVESTABLE] = True
            changed = True
    if changed:
        await rewards.store.async_save({"items": list(rewards.data.values())})


async def async_create_rewards_collection(hass: HomeAssistant) -> RewardStorageCollection:
    """Create and load the reward-catalog storage collection."""
    store: Store = Store(
        hass, STORAGE_VERSION, STORAGE_KEY_REWARDS, minor_version=STORAGE_VERSION_MINOR
    )
    id_manager = collection.IDManager()
    rewards = RewardStorageCollection(store, id_manager)
    await rewards.async_load()
    await _async_migrate_reward_catalog(rewards)
    await _async_migrate_screen_time_investable(rewards)
    return rewards


async def async_create_reward_redemptions_collection(
    hass: HomeAssistant,
) -> RewardRedemptionStorageCollection:
    """Create and load the reward-redemptions storage collection."""
    store: Store = Store(
        hass,
        STORAGE_VERSION,
        STORAGE_KEY_REWARD_REDEMPTIONS,
        minor_version=STORAGE_VERSION_MINOR,
    )
    id_manager = collection.IDManager()
    reward_redemptions = RewardRedemptionStorageCollection(store, id_manager)
    await reward_redemptions.async_load()
    await _async_migrate_reward_redemptions(reward_redemptions)
    return reward_redemptions


class CompletionLogStore:
    """Append-only log of completed/skipped task occurrences.

    Not a StorageCollection: entries are never edited by the user, only
    appended by the coordinator and pruned once they age out.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self._store: Store[list[dict[str, Any]]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY_COMPLETIONS, minor_version=STORAGE_VERSION_MINOR
        )
        self._entries: list[dict[str, Any]] = []

    async def async_load(self) -> None:
        """Load the log from disk."""
        self._entries = await self._store.async_load() or []

    @property
    def entries(self) -> list[dict[str, Any]]:
        """Return all log entries (most recent last)."""
        return self._entries

    def get_last_entry(self, task_id: str, period_key: str) -> dict[str, Any] | None:
        """Return the most recent log entry for a task's period, if any."""
        for entry in reversed(self._entries):
            if entry["task_id"] == task_id and entry["period_key"] == period_key:
                return entry
        return None

    async def async_add_entry(
        self,
        *,
        task_id: str,
        period_key: str,
        member_id: str | None,
        points_awarded: int,
        skipped: bool = False,
        task_name: str | None = None,
    ) -> dict[str, Any]:
        """Append a new completion/skip entry and persist it.

        ``task_name`` (v0.22) is a denormalized copy of the task's name at
        completion time - needed because a "once"-recurrence task is deleted
        the moment it's completed (see async_complete_task in
        coordinator.py), so a later lookup by task_id would otherwise find
        nothing. Used by ws_list_member_weekly_completions below to show a
        member's completed tasks even after such a task no longer exists;
        entries written before this field existed simply have it as None,
        and that lookup falls back to resolving the task_id against the
        still-existing tasks collection (or "Aufgabe" if that's gone too).
        """
        entry = {
            CONF_ID: uuid4().hex,
            "task_id": task_id,
            "period_key": period_key,
            "completed_by_member_id": member_id,
            "completed_at": dt_util.utcnow().isoformat(),
            "points_awarded": points_awarded,
            "skipped": skipped,
            "task_name": task_name,
        }
        self._entries.append(entry)
        if len(self._entries) > MAX_COMPLETION_LOG_ENTRIES:
            self._entries = self._entries[-MAX_COMPLETION_LOG_ENTRIES:]
        await self._store.async_save(self._entries)
        return entry

    def points_since(self, member_id: str, since: datetime) -> int:
        """Sum awarded points for a member since a given UTC timestamp."""
        total = 0
        for entry in self._entries:
            if entry["completed_by_member_id"] != member_id or entry["skipped"]:
                continue
            if dt_util.parse_datetime(entry["completed_at"]) >= since:
                total += entry["points_awarded"]
        return total


class TriggerStateStore:
    """Tracks the currently open occurrence of sensor-triggered tasks.

    Tasks with recurrence type "trigger" (see :mod:`.trigger`) have no
    calendar-based period; instead a new occurrence is opened here the moment
    a bound sensor's state satisfies the task's trigger condition, and it
    stays open until the task is completed or skipped. Not a
    StorageCollection: entries are runtime state written by the trigger
    listener, never edited by the user.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self._store: Store[dict[str, dict[str, Any]]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY_TRIGGER_STATE, minor_version=STORAGE_VERSION_MINOR
        )
        self._state: dict[str, dict[str, Any]] = {}

    async def async_load(self) -> None:
        """Load open trigger occurrences from disk."""
        self._state = await self._store.async_load() or {}

    def get(self, task_id: str) -> dict[str, Any] | None:
        """Return the open occurrence for a task, if any."""
        return self._state.get(task_id)

    async def async_activate(self, task_id: str, *, triggered_at: datetime) -> dict[str, Any]:
        """Open a new occurrence for a task, identified by its trigger time."""
        entry = {"period_key": triggered_at.isoformat(), "triggered_at": triggered_at.isoformat()}
        self._state[task_id] = entry
        await self._store.async_save(self._state)
        return entry

    async def async_clear(self, task_id: str) -> None:
        """Close a task's open occurrence, e.g. once completed or skipped."""
        if self._state.pop(task_id, None) is not None:
            await self._store.async_save(self._state)


async def async_create_trigger_state_store(hass: HomeAssistant) -> TriggerStateStore:
    """Create and load the sensor-trigger state store."""
    store = TriggerStateStore(hass)
    await store.async_load()
    return store


class ChecklistStateStore:
    """Tracks which sub-items are currently checked for a checklist task.

    A TASK_KIND_CHECKLIST task's sub-items (see TASK_KINDS in const.py) are
    checked off one at a time via family_tasks.toggle_subtask; the task only
    becomes "done" once every sub-item is checked for the *current* period
    (see FamilyTasksCoordinator.async_toggle_subtask). This is per-occurrence
    runtime state, not a StorageCollection: a new period always starts with
    every item unchecked again, so a stored entry whose period_key no longer
    matches the task's current period is simply treated as empty instead of
    needing an explicit reset - the next toggle for the new period overwrites
    it.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self._store: Store[dict[str, dict[str, Any]]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY_CHECKLIST_STATE, minor_version=STORAGE_VERSION_MINOR
        )
        # task_id -> {"period_key": str, "checked_ids": list[str]}
        self._state: dict[str, dict[str, Any]] = {}

    async def async_load(self) -> None:
        """Load checked sub-item state from disk."""
        self._state = await self._store.async_load() or {}

    def checked_ids(self, task_id: str, period_key: str) -> set[str]:
        """Return which sub-item ids are checked for a task's current period."""
        entry = self._state.get(task_id)
        if not entry or entry.get("period_key") != period_key:
            return set()
        return set(entry.get("checked_ids", []))

    async def async_toggle(self, task_id: str, period_key: str, subtask_id: str) -> set[str]:
        """Flip one sub-item's checked state for a task's current period."""
        checked = self.checked_ids(task_id, period_key)
        if subtask_id in checked:
            checked.discard(subtask_id)
        else:
            checked.add(subtask_id)
        self._state[task_id] = {"period_key": period_key, "checked_ids": sorted(checked)}
        await self._store.async_save(self._state)
        return checked

    async def async_clear(self, task_id: str) -> None:
        """Drop all stored checked state for a task, e.g. once it's deleted."""
        if self._state.pop(task_id, None) is not None:
            await self._store.async_save(self._state)


async def async_create_checklist_state_store(hass: HomeAssistant) -> ChecklistStateStore:
    """Create and load the checklist sub-item state store."""
    store = ChecklistStateStore(hass)
    await store.async_load()
    return store


class WeeklyBonusStateStore:
    """Tracks the last calendar week the weekly-winner bonus was awarded for.

    See CONF_WEEKLY_WINNER_BONUS_ENABLED/CONF_WEEKLY_WINNER_BONUS_POINTS in
    const.py and FamilyTasksCoordinator._async_process_weekly_winner_bonus in
    coordinator.py: at most one award happens per completed calendar week,
    computed from the *previous* week's points the first time a refresh
    happens after that week ends (Monday 00:00 local, i.e. "mit Ablauf des
    Sonntags"). "last_awarded_week" is the Monday-date (ISO) of the most
    recently awarded week - not a StorageCollection, this is coordinator-
    internal bookkeeping, never edited by the user, same as TriggerStateStore.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY_WEEKLY_BONUS_STATE, minor_version=STORAGE_VERSION_MINOR
        )
        self._state: dict[str, Any] = {}

    async def async_load(self) -> None:
        """Load the last-awarded-week marker from disk."""
        self._state = await self._store.async_load() or {}

    def last_awarded_week(self) -> str | None:
        """Return the Monday-date (ISO) of the last week a bonus was awarded for."""
        return self._state.get("last_awarded_week")

    async def async_set_last_awarded_week(self, period_key: str) -> None:
        """Record that a given week has now been processed (win or no winner)."""
        self._state["last_awarded_week"] = period_key
        await self._store.async_save(self._state)


async def async_create_weekly_bonus_state_store(hass: HomeAssistant) -> WeeklyBonusStateStore:
    """Create and load the weekly-winner-bonus state store."""
    store = WeeklyBonusStateStore(hass)
    await store.async_load()
    return store
