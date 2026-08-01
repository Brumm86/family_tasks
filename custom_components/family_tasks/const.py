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
# Household-wide default battery warning level (percent). A "battery"
# recurrence task treats any monitored sensor at/below this as needing a
# charge/swap, unless the entity has its own override - see
# storage.BatteryOverrideStorageCollection / battery.py.
CONF_BATTERY_WARNING_THRESHOLD: Final = "battery_warning_threshold"

DEFAULT_OVERDUE_AFTER_MINUTES: Final = 60
DEFAULT_ROTATION_STRATEGY: Final = "round_robin"
DEFAULT_BATTERY_WARNING_THRESHOLD: Final = 20

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
# A task that aggregates *every* battery-level entity Home Assistant knows
# about (see battery.py) instead of tracking one sensor like "trigger" does.
# Its period is daily (see _current_period_date in coordinator.py, same as
# RECURRENCE_DAILY) but the coordinator downgrades a due occurrence to
# TASK_STATUS_IDLE whenever no monitored battery is currently at/below its
# warning threshold - so the task only shows up as due when there is
# something to actually charge/swap, and lists exactly which batteries via
# the "battery_entities" attribute (see TaskStatusData). Which entities count
# (all discovered battery sensors, minus per-entity exclusions/threshold
# overrides in storage.BatteryOverrideStorageCollection) is independent of
# any single task, so more than one battery task can exist if a household
# wants to split them up (e.g. by area or by assignee).
#
# As of the household-driven default flow (see
# FamilyTasksCoordinator._async_raise_battery_alerts in coordinator.py), an
# admin no longer has to set one of these up: the coordinator itself raises a
# one-time (RECURRENCE_ONCE) task naming exactly the affected battery the
# moment it crosses at/below its threshold, assigned to every family member
# linked to a Home Assistant admin account. The "Batterien" card section is
# now configuration-only (per-entity exclude/threshold, same as before) and
# no longer offers creating a new "battery"-recurrence task - this type is
# kept only so households that already have one keep working unchanged.
RECURRENCE_BATTERY: Final = "battery"
RECURRENCE_TYPES: Final = [
    RECURRENCE_DAILY,
    RECURRENCE_WEEKLY,
    RECURRENCE_INTERVAL_DAYS,
    RECURRENCE_ONCE,
    RECURRENCE_TRIGGER,
    RECURRENCE_CONFIRMATION,
    RECURRENCE_BATTERY,
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

# Whether a member takes part in the reward system at all (v0.9): gates both
# whether they show up on the leaderboard card and whether they may redeem a
# catalog reward (see WS_API_REWARD_REDEEM below) - a household may only want
# its children competing for points/rewards, not the parents themselves.
# Defaults to True so every member kept behaving exactly as before this field
# was introduced (opting members out is an explicit admin action).
CONF_MEMBER_REWARDS_OPT_IN: Final = "participates_in_rewards"

# Per-task override of whether a child's completion needs parental sign-off
# (see the confirmation flow above). When absent/None, tasks assigned to a
# "child" member always require confirmation - the historical, still-default
# behavior. Children creating a task for *themselves* (see
# WS_API_TASK_CREATE_OWN below) choose this explicitly instead.
CONF_TASK_REQUIRES_CONFIRMATION: Final = "requires_confirmation"

# Optional per-task button entity (see CONF_COMPLETION_BUTTON_ENTITY_ID) that
# gets pressed the moment the task is actually marked done - mainly useful for
# "trigger" tasks that mirror a device's own state, e.g. a vacuum's "resume
# cleaning" button once its "needs emptying" sensor task is completed. Not
# restricted to recurrence type "trigger" server-side, but that is the only
# case the card currently offers it for. See
# FamilyTasksCoordinator._async_press_completion_button in coordinator.py.
CONF_COMPLETION_BUTTON_ENTITY_ID: Final = "completion_button_entity_id"

# --- Task kinds / checklists --------------------------------------------------
#
# Every task defaults to TASK_KIND_STANDARD (single "erledigt" action). A
# TASK_KIND_CHECKLIST task instead carries an open-ended list of named
# sub-items (task "subtasks": [{"id", "name"}, ...]) that get checked off
# individually - checked items render struck-through - and the task itself
# only becomes "done" once every sub-item is checked for the current period
# (see FamilyTasksCoordinator.async_toggle_subtask). Which sub-items are
# currently checked is per-occurrence runtime state, tracked the same way
# open trigger occurrences are (see storage.ChecklistStateStore), and resets
# whenever a new period starts, same as any other recurring task.
TASK_KIND_STANDARD: Final = "standard"
TASK_KIND_CHECKLIST: Final = "checklist"
TASK_KINDS: Final = [TASK_KIND_STANDARD, TASK_KIND_CHECKLIST]

# --- Storage ----------------------------------------------------------------

STORAGE_VERSION: Final = 1
STORAGE_VERSION_MINOR: Final = 2

STORAGE_KEY_TASKS: Final = f"{DOMAIN}.tasks"
STORAGE_KEY_MEMBERS: Final = f"{DOMAIN}.members"
STORAGE_KEY_COMPLETIONS: Final = f"{DOMAIN}.completions"
STORAGE_KEY_TRIGGER_STATE: Final = f"{DOMAIN}.trigger_state"
STORAGE_KEY_BATTERY_OVERRIDES: Final = f"{DOMAIN}.battery_overrides"
STORAGE_KEY_CHECKLIST_STATE: Final = f"{DOMAIN}.checklist_state"
# The parent-defined reward catalog (v0.9): each item has a name and a price
# in points (see RewardStorageCollection in storage.py). The physical storage
# key/file is unchanged since v0.8, where it held "reward groups" - parent-
# defined categories a weekly winner picked from; existing items are
# transparently migrated in place (points_cost=0 backfilled) the first time
# this collection loads under v0.9 - see _async_migrate_reward_catalog.
STORAGE_KEY_REWARDS: Final = f"{DOMAIN}.reward_groups"
# Redemption history: every time a participating member redeems a catalog
# reward, spending points (v0.9) - see RewardRedemptionStorageCollection in
# storage.py. The physical storage key/file is unchanged since v0.8, where it
# held "claimed weekly-winner rewards" (one per member per calendar week);
# existing items are migrated in place (mapped onto the new shape,
# points_cost=0 so they don't retroactively affect anyone's balance) the
# first time this collection loads under v0.9 - see
# _async_migrate_reward_redemptions.
STORAGE_KEY_REWARD_REDEMPTIONS: Final = f"{DOMAIN}.rewards"

MAX_COMPLETION_LOG_ENTRIES: Final = 500

# --- Websocket API prefixes --------------------------------------------------

WS_API_PREFIX_TASKS: Final = f"{DOMAIN}/task"
WS_API_PREFIX_MEMBERS: Final = f"{DOMAIN}/member"
WS_API_PREFIX_BATTERY_OVERRIDES: Final = f"{DOMAIN}/battery_override"
# Non-admin command: lets a member with role "child" create a task assigned
# to themselves only (points forced to 0), without needing an administrator
# account. See ws_create_own_task in storage.py.
WS_API_TASK_CREATE_OWN: Final = f"{WS_API_PREFIX_TASKS}/create_own"

# --- Rewards (v0.9) ------------------------------------------------------------
#
# A points-shop: parents maintain a catalog of rewards, each with a price in
# points (WS_API_PREFIX_REWARDS, plain admin CRUD - see RewardStorageCollection
# in storage.py). Any family member who participates in the reward system (see
# CONF_MEMBER_REWARDS_OPT_IN above) can redeem any catalog reward at any time,
# provided their available point balance (all-time points earned minus
# everything they've already redeemed - see MemberSummaryData.points_available
# in coordinator.py) covers its price. Redeeming is not exposed through the
# generic storage-collection "create" command for WS_API_PREFIX_REWARD_REDEMPTIONS
# (see RewardRedemptionStorageCollectionWebsocket in storage.py) because it
# needs the extra participation/balance checks - only WS_API_REWARD_REDEEM can
# create a redemption entry, and creating one *is* the point deduction: balance
# is always computed fresh from history, never stored/mutated directly.
# Parents (not children, regardless of HA admin flag) can mark a redemption
# "fulfilled" once they've handed the reward over.
WS_API_PREFIX_REWARDS: Final = f"{DOMAIN}/reward"
WS_API_PREFIX_REWARD_REDEMPTIONS: Final = f"{DOMAIN}/reward_redemption"
WS_API_REWARD_REDEEM: Final = f"{WS_API_PREFIX_REWARD_REDEMPTIONS}/redeem"

# Optional per-reward field (v0.11): how many minutes of extra screen time
# this catalog item is worth, purely informational as far as this integration
# is concerned - see EVENT_REWARD_REDEEMED below for how a household actually
# wires it up to something (e.g. Google Family Link) via their own
# automation. Absent/None means "not a screen-time reward" (e.g. "Filmabend
# aussuchen"); explicitly setting it to null via reward/update clears a
# previously set value, same pattern as BatteryOverrideStorageCollection's
# "threshold".
CONF_REWARD_SCREEN_TIME_MINUTES: Final = "screen_time_minutes"

# Fired on hass.bus the moment a redemption is created (end of ws_redeem_reward
# in storage.py), carrying member_id/member_name/reward_id/reward_name/
# points_cost/screen_time_minutes. This - not a hardcoded call into a specific
# automation entity_id - is the integration's extension point for "redeeming
# this reward should immediately *do* something": a household automation
# listens for this event (event trigger) and branches on event_data.member_id
# (e.g. to add screen_time_minutes of extra time to the right child's Google
# Family Link account, each child needing its own amount/target entity - both
# entirely defined in that automation, not in this integration). Triggering
# the automation directly by ID instead would bypass its own trigger
# conditions and hardcode an HA-specific entity_id into this integration;
# firing a plain event keeps the coupling one-directional and lets more than
# one automation react to the same redemption if needed.
EVENT_REWARD_REDEEMED: Final = f"{DOMAIN}_reward_redeemed"

# --- Coordinator --------------------------------------------------------------

COORDINATOR_UPDATE_INTERVAL: Final = timedelta(minutes=15)

# --- Services -----------------------------------------------------------------

SERVICE_COMPLETE_TASK: Final = "complete_task"
SERVICE_SKIP_TASK: Final = "skip_task"
# Checks/unchecks one sub-item of a TASK_KIND_CHECKLIST task. A plain service
# (like complete_task/skip_task above) rather than an admin-only websocket
# command, so any family member - not just admins - can tick off their own
# checklist items.
SERVICE_TOGGLE_SUBTASK: Final = "toggle_subtask"

ATTR_TASK_ID: Final = "task_id"
ATTR_MEMBER_ID: Final = "member_id"
ATTR_SUBTASK_ID: Final = "subtask_id"

# --- Frontend -----------------------------------------------------------------

CARD_FILENAME: Final = "family-tasks-card.js"
CARD_URL_PATH: Final = f"/family_tasks_static/{CARD_FILENAME}"

LEADERBOARD_CARD_FILENAME: Final = "family-tasks-leaderboard-card.js"
LEADERBOARD_CARD_URL_PATH: Final = f"/family_tasks_static/{LEADERBOARD_CARD_FILENAME}"

# --- Misc -----------------------------------------------------------------

MANUFACTURER: Final = "Family Tasks"
