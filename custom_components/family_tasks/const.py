"""Constants for the Family Tasks integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "family_tasks"

PLATFORMS: Final = [Platform.SENSOR, Platform.BUTTON]

# --- Config / options keys -------------------------------------------------

CONF_OVERDUE_AFTER_MINUTES: Final = "overdue_after_minutes"
CONF_DEFAULT_ROTATION_STRATEGY: Final = "default_rotation_strategy"

DEFAULT_OVERDUE_AFTER_MINUTES: Final = 60
DEFAULT_ROTATION_STRATEGY: Final = "round_robin"

ROTATION_STRATEGY_ROUND_ROBIN: Final = "round_robin"
ROTATION_STRATEGY_RANDOM: Final = "random"
ROTATION_STRATEGY_FIXED: Final = "fixed"
# Picks whichever candidate in rotation.member_ids currently has the fewest
# points (see ROTATION_ONLY_CHILDREN below to narrow the candidate pool to
# members with role "child"). Unlike the other strategies this is computed
# fresh on every coordinator refresh instead of advancing a stored index -
# see FamilyTasksCoordinator._member_with_least_points.
ROTATION_STRATEGY_LEAST_POINTS: Final = "least_points"
ROTATION_STRATEGIES: Final = [
    ROTATION_STRATEGY_ROUND_ROBIN,
    ROTATION_STRATEGY_RANDOM,
    ROTATION_STRATEGY_FIXED,
    ROTATION_STRATEGY_LEAST_POINTS,
]

# Rotation option: when the strategy is ROTATION_STRATEGY_LEAST_POINTS, only
# consider members with role MEMBER_ROLE_CHILD among rotation.member_ids when
# picking the least-points candidate (falls back to the full pool if none of
# the candidates are children).
ROTATION_ONLY_CHILDREN: Final = "only_children"

RECURRENCE_DAILY: Final = "daily"
RECURRENCE_WEEKLY: Final = "weekly"
RECURRENCE_INTERVAL_DAYS: Final = "interval_days"
# A single occurrence that never repeats: due once on "anchor_date" and, once
# completed/skipped, stays done forever because its period_key (the anchor
# date) never changes - see _current_period_date in coordinator.py.
RECURRENCE_ONCE: Final = "once"
RECURRENCE_TRIGGER: Final = "trigger"
# Internal-only recurrence used for auto-generated parent confirmation tasks
# (see const "Child tasks / parent confirmation" section below). Behaves like
# RECURRENCE_TRIGGER (idle until opened, then a single open occurrence) but
# is opened programmatically by the coordinator instead of by a bound sensor,
# and is intentionally not offered in the card's recurrence picker.
RECURRENCE_CONFIRMATION: Final = "confirmation"
RECURRENCE_TYPES: Final = [
    RECURRENCE_DAILY,
    RECURRENCE_WEEKLY,
    RECURRENCE_INTERVAL_DAYS,
    RECURRENCE_ONCE,
    RECURRENCE_TRIGGER,
    RECURRENCE_CONFIRMATION,
]

# --- Sensor triggers ----------------------------------------------------------
#
# A task with recurrence type RECURRENCE_TRIGGER has no calendar schedule of
# its own; instead a new occurrence becomes due when a sensor it is bound to
# satisfies one of the following conditions (mirroring Home Assistant's own
# "state" and "numeric_state" automation triggers):
#   - TASK_TRIGGER_STATE: a binary_sensor (or any entity) reaches a given state.
#   - TASK_TRIGGER_NUMERIC_STATE: a numeric sensor crosses a single threshold,
#     either rising above it ("above") or falling below it ("below"). Exactly
#     one of the two must be set - this is a directional crossing, not a
#     range/band between two bounds.

TASK_TRIGGER_STATE: Final = "state"
TASK_TRIGGER_NUMERIC_STATE: Final = "numeric_state"
TASK_TRIGGER_KINDS: Final = [TASK_TRIGGER_STATE, TASK_TRIGGER_NUMERIC_STATE]

# --- Task status values -----------------------------------------------------

TASK_STATUS_IDLE: Final = "idle"
TASK_STATUS_PENDING: Final = "pending"
TASK_STATUS_OVERDUE: Final = "overdue"
TASK_STATUS_AWAITING_CONFIRMATION: Final = "awaiting_confirmation"
TASK_STATUS_DONE: Final = "done"
TASK_STATUSES: Final = [
    TASK_STATUS_IDLE,
    TASK_STATUS_PENDING,
    TASK_STATUS_OVERDUE,
    TASK_STATUS_AWAITING_CONFIRMATION,
    TASK_STATUS_DONE,
]

# --- Member roles / child task confirmation ----------------------------------
#
# A member's role determines whether their completions need parental sign-off:
# when a member with role MEMBER_ROLE_CHILD marks their assigned task done,
# the coordinator does not award points immediately. Instead it opens the
# task's status as TASK_STATUS_AWAITING_CONFIRMATION and creates a single-use
# task (recurrence RECURRENCE_CONFIRMATION, see above) assigned to the
# household's parents. Completing *that* task finalizes the child's
# completion (points + rotation); skipping it rejects the claim and returns
# the original task to its normal pending/overdue state.

MEMBER_ROLE_PARENT: Final = "parent"
MEMBER_ROLE_CHILD: Final = "child"
MEMBER_ROLES: Final = [MEMBER_ROLE_PARENT, MEMBER_ROLE_CHILD]

# Per-task override of whether a child's completion needs parental sign-off
# (see the confirmation flow above). When absent/None, tasks assigned to a
# "child" member always require confirmation - the historical, still-default
# behavior. Children creating a task for *themselves* (see
# WS_API_TASK_CREATE_OWN below) choose this explicitly instead.
CONF_TASK_REQUIRES_CONFIRMATION: Final = "requires_confirmation"

# --- Storage ----------------------------------------------------------------

STORAGE_VERSION: Final = 1
STORAGE_VERSION_MINOR: Final = 1

STORAGE_KEY_TASKS: Final = f"{DOMAIN}.tasks"
STORAGE_KEY_MEMBERS: Final = f"{DOMAIN}.members"
STORAGE_KEY_COMPLETIONS: Final = f"{DOMAIN}.completions"
STORAGE_KEY_TRIGGER_STATE: Final = f"{DOMAIN}.trigger_state"

MAX_COMPLETION_LOG_ENTRIES: Final = 500

# --- Websocket API prefixes --------------------------------------------------

WS_API_PREFIX_TASKS: Final = f"{DOMAIN}/task"
WS_API_PREFIX_MEMBERS: Final = f"{DOMAIN}/member"
# Non-admin command: lets a member with role "child" create a task assigned
# to themselves only (points forced to 0), without needing an administrator
# account. See ws_create_own_task in storage.py.
WS_API_TASK_CREATE_OWN: Final = f"{WS_API_PREFIX_TASKS}/create_own"

# --- Coordinator --------------------------------------------------------------

COORDINATOR_UPDATE_INTERVAL: Final = timedelta(minutes=15)

# --- Services -----------------------------------------------------------------

SERVICE_COMPLETE_TASK: Final = "complete_task"
SERVICE_SKIP_TASK: Final = "skip_task"

ATTR_TASK_ID: Final = "task_id"
ATTR_MEMBER_ID: Final = "member_id"

# --- Frontend -----------------------------------------------------------------

CARD_FILENAME: Final = "family-tasks-card.js"
CARD_URL_PATH: Final = f"/family_tasks_static/{CARD_FILENAME}"

LEADERBOARD_CARD_FILENAME: Final = "family-tasks-leaderboard-card.js"
LEADERBOARD_CARD_URL_PATH: Final = f"/family_tasks_static/{LEADERBOARD_CARD_FILENAME}"

# --- Misc -----------------------------------------------------------------

MANUFACTURER: Final = "Family Tasks"
