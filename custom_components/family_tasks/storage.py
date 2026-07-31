"""Storage layer for the Family Tasks integration.

Task- and member definitions are managed as ``StorageCollection`` items so
they can be created/edited/deleted through the frontend (Settings UI /
a dedicated Lovelace card) via websocket commands, the same pattern used by
helpers such as ``counter`` or ``input_boolean``.

Task *completions* are an append-only log and therefore intentionally not a
StorageCollection (there is nothing to edit, only to append and prune).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

import voluptuous as vol
from voluptuous.humanize import humanize_error

from homeassistant.components import websocket_api
from homeassistant.const import CONF_ID
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import collection
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_COMPLETION_BUTTON_ENTITY_ID,
    CONF_TASK_REQUIRES_CONFIRMATION,
    DEFAULT_ROTATION_STRATEGY,
    MAX_COMPLETION_LOG_ENTRIES,
    MEMBER_ROLE_CHILD,
    MEMBER_ROLE_PARENT,
    MEMBER_ROLES,
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
    STORAGE_KEY_MEMBERS,
    STORAGE_KEY_TASKS,
    STORAGE_KEY_TRIGGER_STATE,
    STORAGE_VERSION,
    STORAGE_VERSION_MINOR,
    TASK_KIND_CHECKLIST,
    TASK_KIND_STANDARD,
    TASK_KINDS,
    TASK_TRIGGER_KINDS,
    TASK_TRIGGER_NUMERIC_STATE,
    TASK_TRIGGER_STATE,
    WS_API_PREFIX_BATTERY_OVERRIDES,
    WS_API_PREFIX_MEMBERS,
    WS_API_PREFIX_TASKS,
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
}

MEMBER_UPDATE_SCHEMA: collection.VolDictType = {
    vol.Optional("name"): str,
    vol.Optional("person_entity_id"): str,
    vol.Optional("icon"): str,
    vol.Optional("active"): bool,
    vol.Optional("role"): vol.In(MEMBER_ROLES),
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
        return {**item, **validated}


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
    }
)


@callback
def async_setup_websocket_api(
    hass: HomeAssistant,
    tasks: TaskStorageCollection,
    members: MemberStorageCollection,
    battery_overrides: BatteryOverrideStorageCollection,
) -> None:
    """Expose the storage collections over the websocket API for the frontend."""
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
    ) -> dict[str, Any]:
        """Append a new completion/skip entry and persist it."""
        entry = {
            CONF_ID: uuid4().hex,
            "task_id": task_id,
            "period_key": period_key,
            "completed_by_member_id": member_id,
            "completed_at": dt_util.utcnow().isoformat(),
            "points_awarded": points_awarded,
            "skipped": skipped,
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
