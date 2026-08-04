"""Constants for the Family Tasks integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "family_tasks"

PLATFORMS: Final = [Platform.SENSOR, Platform.BUTTON, Platform.BINARY_SENSOR]

# --- Config / options keys -------------------------------------------------

CONF_OVERDUE_AFTER_MINUTES: Final = "overdue_after_minutes"
CONF_DEFAULT_ROTATION_STRATEGY: Final = "default_rotation_strategy"
# Household-wide default battery warning level (percent). A "battery"
# recurrence task treats any monitored sensor at/below this as needing a
# charge/swap, unless the entity has its own override - see
# storage.BatteryOverrideStorageCollection / battery.py.
CONF_BATTERY_WARNING_THRESHOLD: Final = "battery_warning_threshold"

# v0.14: household-wide conversion rate for the "invest points" Handyzeit
# reward flow (see CONF_REWARD_SCREEN_TIME_INVESTABLE below) - how many
# minutes of screen time one invested point is worth. Applied at redemption
# time (storage.ws_redeem_reward), read fresh from the config entry's options
# every time, same as CONF_OVERDUE_AFTER_MINUTES/CONF_BATTERY_WARNING_THRESHOLD
# - so a parent changing it in Settings takes effect on the very next
# redemption without needing a restart.
CONF_SCREEN_TIME_MINUTES_PER_POINT: Final = "screen_time_minutes_per_point"

# v0.14: whether awarding bonus points to the current week's point leader(s)
# is turned on at all, and how many bonus points that is - see
# FamilyTasksCoordinator._async_process_weekly_winner_bonus in coordinator.py.
# Off by default so nothing changes for a household that doesn't opt in.
CONF_WEEKLY_WINNER_BONUS_ENABLED: Final = "weekly_winner_bonus_enabled"
CONF_WEEKLY_WINNER_BONUS_POINTS: Final = "weekly_winner_bonus_points"

# Internal-only sentinel task_id for completion-log entries created by
# FamilyTasksCoordinator._async_process_weekly_winner_bonus - never a real
# task, so it never shows up in the task list, and is excluded from the
# per-member weekly completion history the card shows when a Bestenliste row
# is clicked (see WS_API_MEMBER_WEEKLY_COMPLETIONS below) even though the
# points themselves count normally toward that member's totals. Lives here
# (not in coordinator.py, where it originated) so storage.py's websocket
# handler for that history can exclude it too without an import cycle.
WEEKLY_BONUS_TASK_ID: Final = "__weekly_winner_bonus__"

DEFAULT_OVERDUE_AFTER_MINUTES: Final = 60
DEFAULT_ROTATION_STRATEGY: Final = "round_robin"
DEFAULT_BATTERY_WARNING_THRESHOLD: Final = 20
DEFAULT_SCREEN_TIME_MINUTES_PER_POINT: Final = 1
DEFAULT_WEEKLY_WINNER_BONUS_ENABLED: Final = False
DEFAULT_WEEKLY_WINNER_BONUS_POINTS: Final = 0

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

# v0.14: optional notify.* service (just the part after "notify.", e.g.
# "mobile_app_pixel_8") this member's phone actually reads pushes from. See
# EVENT_TASK_ASSIGNED below - a plain persistent_notification.create is
# raised as a fallback whenever this is *not* set, since that's the only
# notification channel available then, but it only ever shows up inside Home
# Assistant's own frontend/companion-app notification panel, not as a real
# push notification on the phone's lock screen. Once this is set, the
# integration calls this member's own notify.* service instead (needs the
# Home Assistant Companion App set up on their phone and its notify service
# name filled in here) and no longer also raises the persistent_notification
# for them (v0.16 - it used to fire unconditionally alongside notify.*,
# duplicating every notification once real push was configured).
CONF_MEMBER_NOTIFY_SERVICE: Final = "notify_service"

# Per-task override of whether a child's completion needs parental sign-off
# (see the confirmation flow above). When absent/None, tasks assigned to a
# "child" member always require confirmation - the historical, still-default
# behavior. Children creating a task for *themselves* (see
# WS_API_TASK_CREATE_OWN below) choose this explicitly instead.
CONF_TASK_REQUIRES_CONFIRMATION: Final = "requires_confirmation"

# v0.22: set only by ws_create_own_task (WS_API_TASK_CREATE_OWN) - which
# family member created this task for themselves. Purely a visibility flag:
# family-tasks-card.js hides a task carrying this field from everyone except
# the member it names, including admins/parents - a child's casual
# self-reminder ("Zimmer aufräumen für mich") isn't meant to clutter anyone
# else's task list. The auto-generated parent-confirmation task raised once
# such a task is actually completed (see RECURRENCE_CONFIRMATION above) is a
# separate task entity that never carries this field, so parents still see
# and act on *that* one normally. Never set for an admin-created task -
# TASK_CREATE_SCHEMA/TASK_UPDATE_SCHEMA accept it structurally (so
# ws_create_own_task can pass it through the normal task-creation path), but
# nothing in the card's admin task form exposes a way to set it by hand.
CONF_TASK_CREATED_BY_MEMBER_ID: Final = "created_by_member_id"

# Optional per-task button entity (see CONF_COMPLETION_BUTTON_ENTITY_ID) that
# gets pressed the moment the task is actually marked done - mainly useful for
# "trigger" tasks that mirror a device's own state, e.g. a vacuum's "resume
# cleaning" button once its "needs emptying" sensor task is completed. Not
# restricted to recurrence type "trigger" server-side, but that is the only
# case the card currently offers it for. See
# FamilyTasksCoordinator._async_press_completion_button in coordinator.py.
CONF_COMPLETION_BUTTON_ENTITY_ID: Final = "completion_button_entity_id"

# v0.17: replaces the v0.16 "pin an existing task" star toggle entirely (that
# field, CONF_TASK_FAVORITE, is gone). A "Favorit" is now an independent,
# reusable *template* (see FavoriteStorageCollection in storage.py) a parent
# maintains - name, points, optional fixed assignee(s), task kind - separate
# from the tasks collection itself. It exists for chores that recur
# irregularly (e.g. "Auto waschen", "Keller aufräumen"): setting one up as a
# real recurring task makes no sense (there is no fixed schedule to hang a
# RECURRENCE_* type off of), but retyping the same name/points every time is
# tedious. Clicking a favorite (WS_API_FAVORITE_INSTANTIATE below) creates a
# brand new, independent RECURRENCE_ONCE task from it - open, not
# pre-completed - that behaves exactly like one an admin created by hand; the
# template itself is untouched and can be clicked again any number of times.
# Parent-only end to end: only a "parent" (HA admin, not linked to a "child"
# member - same rule as member/reward-catalog management) may see, manage, or
# instantiate favorites at all - see FavoriteStorageCollectionWebsocket.
WS_API_PREFIX_FAVORITES: Final = f"{DOMAIN}/favorite"
WS_API_FAVORITE_INSTANTIATE: Final = f"{WS_API_PREFIX_FAVORITES}/instantiate"

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
# v0.14: a "Pflichtaufgabe" (mandatory task) - behaves exactly like
# TASK_KIND_STANDARD as far as completion itself goes (a single "Erledigt"
# action), but is called out to the child as mandatory in the card, and while
# an occurrence of it is TASK_STATUS_OVERDUE, tick-based screen-time granting
# for exactly the member(s) it is assigned to is paused - see
# FamilyTasksCoordinator._async_update_data's screen_time_grant_active
# computation and binary_sensor.py. Resumes automatically the moment the
# occurrence is no longer overdue (completed, or - for a "child" assignee
# needing parental sign-off - once a parent confirms it); missed ticks are
# never made up, this only ever gates whether the *next* tick may grant
# anything. Not combinable with TASK_KIND_CHECKLIST - a task is one or the
# other, chosen via "Aufgabentyp" like any other kind.
TASK_KIND_MANDATORY: Final = "mandatory"
TASK_KINDS: Final = [TASK_KIND_STANDARD, TASK_KIND_CHECKLIST, TASK_KIND_MANDATORY]
# Kinds a "child" member may pick when creating a task for themselves (see
# WS_API_TASK_CREATE_OWN below) - "mandatory" is a parent-only concept (it
# exists to let a parent gate a child's screen time), so it's deliberately
# left out here.
OWN_TASK_KINDS: Final = [TASK_KIND_STANDARD, TASK_KIND_CHECKLIST]

# --- Storage ----------------------------------------------------------------

STORAGE_VERSION: Final = 1
STORAGE_VERSION_MINOR: Final = 3

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
# v0.14: tracks the last calendar week (Monday's ISO date) the weekly-winner
# bonus was already awarded for, so FamilyTasksCoordinator only ever awards it
# once per week, regardless of how often the coordinator refreshes. See
# storage.WeeklyBonusStateStore.
STORAGE_KEY_WEEKLY_BONUS_STATE: Final = f"{DOMAIN}.weekly_bonus_state"
# v0.17: the parent-maintained Favoriten template catalog - see
# WS_API_PREFIX_FAVORITES above.
STORAGE_KEY_FAVORITES: Final = f"{DOMAIN}.favorites"

MAX_COMPLETION_LOG_ENTRIES: Final = 500

# --- Websocket API prefixes --------------------------------------------------

WS_API_PREFIX_TASKS: Final = f"{DOMAIN}/task"
WS_API_PREFIX_MEMBERS: Final = f"{DOMAIN}/member"
WS_API_PREFIX_BATTERY_OVERRIDES: Final = f"{DOMAIN}/battery_override"
# Non-admin command: lets a member with role "child" create a task assigned
# to themselves only (points forced to 0), without needing an administrator
# account. See ws_create_own_task in storage.py.
WS_API_TASK_CREATE_OWN: Final = f"{WS_API_PREFIX_TASKS}/create_own"

# v0.22: read-only command backing the Bestenliste's per-member "which tasks
# did they complete this week" drill-down (clicking a leaderboard row opens a
# dialog listing them - see FamilyTasksCard._openMemberCompletions in
# family-tasks-card.js). Not a StorageCollection command - there is nothing
# to create/edit/delete here, just a filtered read of CompletionLogStore
# (which is intentionally not a StorageCollection either, see storage.py) -
# and not admin-restricted, since the underlying points/leaderboard data is
# already visible to every user regardless of role. See
# ws_list_member_weekly_completions in storage.py.
WS_API_MEMBER_WEEKLY_COMPLETIONS: Final = f"{WS_API_PREFIX_MEMBERS}/weekly_completions"

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

# Optional per-reward field (v0.12): whether redeeming this catalog item
# should mark the resulting redemption "fulfilled" immediately, instead of
# leaving it for a parent to mark "erledigt" by hand later (see
# RewardRedemptionStorageCollectionWebsocket/ws_redeem_reward in storage.py).
# Off by default - most rewards ("Filmabend aussuchen") still need a parent
# to actually hand something over before they're done. On for a screen-time
# reward this is more than a convenience: EVENT_REWARD_REDEEMED already fires
# unconditionally and a household automation applies the extra screen time
# right away with no parent involved, so "fulfilled" should reflect that it
# already happened rather than sit as a permanently-open item nobody will
# ever manually resolve.
CONF_REWARD_AUTO_FULFILL: Final = "auto_fulfill"

# v0.14: marks a "Handyzeit" catalog reward as using the "invest points"
# flow instead of a fixed price/fixed screen_time_minutes pair - the member
# chooses how many points to spend at redemption time (family_tasks/
# reward_redemption/redeem's new "points_spent"), and the screen time granted
# is points_spent * CONF_SCREEN_TIME_MINUTES_PER_POINT (the household-wide
# bonus factor from Options), not a value stored on the catalog item itself.
# "points_cost" is ignored for a reward with this flag set - see
# ws_redeem_reward in storage.py. Existing rewards that already had
# screen_time_minutes set are migrated to this flag on first load after the
# upgrade (see _async_migrate_screen_time_investable in storage.py), so a
# household's existing Handyzeit rewards switch to the new dynamic flow
# automatically instead of silently keeping the old fixed-minutes behavior.
CONF_REWARD_SCREEN_TIME_INVESTABLE: Final = "screen_time_investable"

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

# v0.14: fired whenever a new task is created/raised with a member assigned
# to it (member_id/member_name/task_id/task_name) - covers a task an admin
# creates by hand as well as an auto-generated one (parent-confirmation,
# battery alert). Same extension-point pattern as EVENT_REWARD_REDEEMED: the
# integration itself only ever raises a persistent_notification or calls the
# member's notify.* service (see CONF_MEMBER_NOTIFY_SERVICE above) and fires
# this event - a household's own automation can additionally react to it
# however it likes (a different notify target, a TTS announcement, etc.)
# without the integration having to know about any of that.
EVENT_TASK_ASSIGNED: Final = f"{DOMAIN}_task_assigned"

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

# --- Misc -----------------------------------------------------------------

MANUFACTURER: Final = "Family Tasks"
