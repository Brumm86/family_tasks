"""Constants for the Family Tasks integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "family_tasks"

PLATFORMS: Final = [Platform.SENSOR, Platform.BUTTON, Platform.BINARY_SENSOR, Platform.SWITCH]

# --- Config / options keys -------------------------------------------------

CONF_OVERDUE_AFTER_MINUTES: Final = "overdue_after_minutes"
CONF_DEFAULT_ROTATION_STRATEGY: Final = "default_rotation_strategy"
# Household-wide default battery warning level (percent). A "battery"
# recurrence task treats any monitored sensor at/below this as needing a
# charge/swap, unless the entity has its own override - see
# storage.BatteryOverrideStorageCollection / battery.py.
CONF_BATTERY_WARNING_THRESHOLD: Final = "battery_warning_threshold"

# v0.35: household-wide switch for whether an auto-generated battery-alert
# task (RECURRENCE_ONCE, tagged "battery_alert" - see
# FamilyTasksCoordinator._async_raise_battery_alerts) resolves itself the
# moment the battery it names recovers: back above its warning threshold for
# a numeric sensor, or no longer reporting low for a binary_sensor. Mirrors
# the per-task "auto_complete_on_normalize" flag on a "trigger" task's
# TASK_TRIGGER_STATE_SCHEMA/TASK_TRIGGER_NUMERIC_STATE_SCHEMA (v0.34), but as
# a single household-wide option rather than a per-task checkbox, since these
# alert tasks are raised automatically and have no task form of their own to
# hold one. Off by default: the alert task stays open (pending/overdue) until
# a family member completes/skips it by hand, exactly as before this option
# existed. Does not affect the older recurrence type "battery"
# (RECURRENCE_BATTERY) - that aggregate task already falls back to idle by
# itself once every monitored battery recovers, without ever logging a
# completion or awarding points either way.
CONF_BATTERY_ALERT_AUTO_COMPLETE_ON_RECOVERY: Final = (
    "battery_alert_auto_complete_on_recovery"
)

# v0.14: household-wide conversion rate for the "invest points" Handyzeit
# reward flow (see CONF_REWARD_SCREEN_TIME_INVESTABLE below) - how many
# minutes of screen time one invested point is worth. Applied at redemption
# time (storage.ws_redeem_reward), read fresh from the config entry's options
# every time, same as CONF_OVERDUE_AFTER_MINUTES/CONF_BATTERY_WARNING_THRESHOLD
# - so a parent changing it in Settings takes effect on the very next
# redemption without needing a restart.
CONF_SCREEN_TIME_MINUTES_PER_POINT: Final = "screen_time_minutes_per_point"

# v0.30: replaces the old weekly-winner bonus. Rather than a single
# household-wide "winner" taking all, every participating member who crosses
# one of two configurable progress thresholds *during* the current week
# (percentages of CONF_WEEKLY_PROGRESS_GOAL_POINTS - see
# CONF_MILESTONE_1_THRESHOLD_PERCENT/CONF_MILESTONE_2_THRESHOLD_PERCENT below)
# earns that threshold's "Meilensteinbonus" points immediately, live, the
# first refresh after they cross it - see
# FamilyTasksCoordinator._async_process_milestone_bonus in coordinator.py.
# Off by default so nothing changes for a household that doesn't opt in.
CONF_MILESTONE_BONUS_ENABLED: Final = "milestone_bonus_enabled"
# Threshold 1, as a percentage of CONF_WEEKLY_PROGRESS_GOAL_POINTS (default
# 100%, i.e. "reached the weekly goal") - vol.Range(min=1) both here and in
# its NumberSelector, since a 0% threshold would trigger before any points
# were earned at all.
CONF_MILESTONE_1_THRESHOLD_PERCENT: Final = "milestone_1_threshold_percent"
CONF_MILESTONE_1_BONUS_POINTS: Final = "milestone_1_bonus_points"
# Threshold 2 (default 200%, i.e. "double the weekly goal"). Must exceed
# threshold 1 - enforced by the options flow's schema, not just the default
# ordering, so the "first still-uncrossed threshold this week" logic in
# _async_process_milestone_bonus can rely on threshold 1 < threshold 2.
CONF_MILESTONE_2_THRESHOLD_PERCENT: Final = "milestone_2_threshold_percent"
CONF_MILESTONE_2_BONUS_POINTS: Final = "milestone_2_bonus_points"

# Internal-only sentinel task_ids for completion-log entries created by
# FamilyTasksCoordinator._async_process_milestone_bonus - never a real task,
# so neither shows up in the task list, and both are excluded from the
# per-member weekly completion history the card shows when a Bestenliste row
# is clicked (see WS_API_MEMBER_WEEKLY_COMPLETIONS below) even though the
# points themselves count normally toward that member's totals. Two distinct
# sentinels (not one) so a member who crosses both thresholds in the same
# week gets two independent completion-log entries rather than one
# overwriting/ambiguous with the other. Lives here (not in coordinator.py,
# where it originated) so storage.py's websocket handler for that history
# can exclude it too without an import cycle.
MILESTONE_BONUS_1_TASK_ID: Final = "__milestone_bonus_1__"
MILESTONE_BONUS_2_TASK_ID: Final = "__milestone_bonus_2__"

# v0.30 bugfix: internal-only sentinel for the one-time retroactive
# correction FamilyTasksCoordinator._async_correct_negative_balances applies
# to any member whose points_available had already gone negative because of
# the _available_points/weekly_spendable_points drift fixed in storage.py
# (see weekly_spendable_points there) - see that method's docstring for the
# full story. Guarded so it only ever tops a member up once, ever: excluded
# from the weekly completion history for the same reason as the sentinels
# above (it isn't a completed task).
POINTS_CORRECTION_TASK_ID: Final = "__points_correction__"

# v0.24: same sentinel pattern as MILESTONE_BONUS_1_TASK_ID/
# MILESTONE_BONUS_2_TASK_ID/POINTS_CORRECTION_TASK_ID above, for a manual
# points award/deduction a parent makes independent of any task (see
# WS_API_POINTS_AWARD/ws_award_points in storage.py) - never a real task, and
# excluded from the per-member weekly completion history for the same reason
# (it isn't a completed task), while still counting normally toward the
# member's points_total/points_week/points_month/points_available - and,
# since v0.30, toward points_week for Meilensteinbonus threshold-crossing
# purposes too (see FamilyTasksCoordinator._async_process_milestone_bonus) -
# a manually-awarded point is just as "real" as a task-completion one.
MANUAL_POINTS_TASK_ID: Final = "__manual_points_award__"

# v0.29: household-wide weekly point goal backing each child's
# "Wochenfortschritt" progress bar (replaces the flat Bestenliste ranking -
# see family-tasks-card.js). Points a member earns within a calendar week
# (Monday 00:00 local - Sunday 23:59, the same boundary points_week already
# uses) up to this many points only count toward reaching the goal itself;
# only points earned *beyond* the goal in that week are added to their
# spendable points_available balance, redeemable in the reward shop exactly
# as before. 0 (the default) disables the rule entirely - every point earned
# is immediately spendable, identical to the pre-v0.29 behavior. See
# FamilyTasksCoordinator._weekly_spendable_points in coordinator.py.
CONF_WEEKLY_PROGRESS_GOAL_POINTS: Final = "weekly_progress_goal_points"

# v0.32: household-wide "Streak-Bonus" - bonus points for a member who earns
# at least CONF_STREAK_BONUS_THRESHOLD_POINTS points *above*
# CONF_WEEKLY_PROGRESS_GOAL_POINTS in CONF_STREAK_BONUS_REQUIRED_WEEKS
# consecutive calendar weeks. Unlike the Meilensteinbonus (which awards live,
# mid-week, the moment a threshold is crossed), a streak can only be judged
# once a week has actually ended - see
# FamilyTasksCoordinator._async_process_streak_bonus, which processes each
# member's fully-elapsed weeks one at a time via StreakBonusStateStore. Once
# a member's streak reaches the required length, every further consecutive
# week keeps earning the bonus again (rolling), not just the one that first
# reached it - a maintained streak is rewarded every week, not once.
CONF_STREAK_BONUS_ENABLED: Final = "streak_bonus_enabled"
CONF_STREAK_BONUS_THRESHOLD_POINTS: Final = "streak_bonus_threshold_points"
CONF_STREAK_BONUS_REQUIRED_WEEKS: Final = "streak_bonus_required_weeks"
CONF_STREAK_BONUS_POINTS: Final = "streak_bonus_points"

# v0.32: household-wide "Urlaubsmodus" - see switch.py
# (FamilyTasksVacationModeSwitch) for the actual on/off entity, which is the
# source of truth once created; this option only seeds its *initial* value
# the first time VacationModeStateStore loads with nothing on disk yet, so a
# household that already wants it on can set that up during onboarding
# without having to remember to flip the switch separately afterwards. Not
# read again after that - see storage.VacationModeStateStore.
CONF_VACATION_MODE_DEFAULT: Final = "vacation_mode_default"

# Per-task override (TASK_CREATE_SCHEMA/TASK_UPDATE_SCHEMA in storage.py) of
# what should happen to this task's occurrences while the household-wide
# Urlaubsmodus switch is on - see VACATION_BEHAVIOR_SHOW/VACATION_BEHAVIOR_PAUSE
# below and the vacation-mode handling in
# FamilyTasksCoordinator._async_update_data. Only consulted while vacation
# mode is actually active; otherwise every task behaves exactly as if this
# field didn't exist.
CONF_TASK_VACATION_BEHAVIOR: Final = "vacation_behavior"
VACATION_BEHAVIOR_SHOW: Final = "show"
VACATION_BEHAVIOR_PAUSE: Final = "pause"
VACATION_BEHAVIORS: Final = [VACATION_BEHAVIOR_SHOW, VACATION_BEHAVIOR_PAUSE]

DEFAULT_OVERDUE_AFTER_MINUTES: Final = 60
DEFAULT_ROTATION_STRATEGY: Final = "round_robin"
DEFAULT_BATTERY_WARNING_THRESHOLD: Final = 20
DEFAULT_BATTERY_ALERT_AUTO_COMPLETE_ON_RECOVERY: Final = False
DEFAULT_SCREEN_TIME_MINUTES_PER_POINT: Final = 1
DEFAULT_MILESTONE_BONUS_ENABLED: Final = False
DEFAULT_MILESTONE_1_THRESHOLD_PERCENT: Final = 100
DEFAULT_MILESTONE_1_BONUS_POINTS: Final = 0
DEFAULT_MILESTONE_2_THRESHOLD_PERCENT: Final = 200
DEFAULT_MILESTONE_2_BONUS_POINTS: Final = 0
DEFAULT_WEEKLY_PROGRESS_GOAL_POINTS: Final = 0
DEFAULT_STREAK_BONUS_ENABLED: Final = False
DEFAULT_STREAK_BONUS_THRESHOLD_POINTS: Final = 0
DEFAULT_STREAK_BONUS_REQUIRED_WEEKS: Final = 2
DEFAULT_STREAK_BONUS_POINTS: Final = 0
DEFAULT_VACATION_MODE: Final = False

# Internal-only sentinel task_id for a completion-log entry created by
# FamilyTasksCoordinator._async_process_streak_bonus - same sentinel pattern
# as MILESTONE_BONUS_1_TASK_ID/MILESTONE_BONUS_2_TASK_ID above (never a real
# task, excluded from ws_list_member_weekly_completions, still counts
# normally toward the member's point totals).
STREAK_BONUS_TASK_ID: Final = "__streak_bonus__"

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

# --- Task claiming / reservation (v0.27) --------------------------------------
#
# Lets a member "annehmen" (claim) a task occurrence they're currently
# eligible to act on before actually completing it, reserving it for
# CLAIM_RESERVATION_MINUTES so nobody else may claim or complete it while the
# reservation is active - see FamilyTasksCoordinator.async_claim_task/
# async_complete_task in coordinator.py and ClaimStateStore in storage.py.
# Claiming is optional - "Erledigt" still works directly without claiming
# first - and is only offered at all for an occurrence more than one member
# is currently eligible to act on (see eligible_member_ids in coordinator.py);
# with only ever one possible actor there is nobody to reserve it against.
# If the claimant hasn't marked the occurrence done by the time the
# reservation lapses, they lose CLAIM_PENALTY_POINTS point(s) (logged under
# MANUAL_POINTS_TASK_ID, same mechanism ws_award_points already uses) and the
# occurrence reopens for everyone who was eligible before the claim.
CLAIM_RESERVATION_MINUTES: Final = 60
CLAIM_PENALTY_POINTS: Final = 1

# Points a "child" member loses when a parent explicitly rejects ("Ablehnen")
# their completion of a task requiring confirmation - see async_skip_task in
# coordinator.py. Logged the same way as CLAIM_PENALTY_POINTS above.
CONFIRMATION_REJECTION_PENALTY_POINTS: Final = 1

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
# v0.30: tracks, for the current calendar week only, which members have
# already been awarded each Meilensteinbonus threshold - so
# FamilyTasksCoordinator only ever awards a given member/threshold/week combo
# once, regardless of how often the coordinator refreshes. Reset (pruned)
# automatically whenever the current week rolls over - see
# storage.MilestoneBonusStateStore. Physical storage key/file unchanged since
# v0.14, where it tracked the (now removed) weekly-winner bonus instead - the
# old "last_awarded_week" shape is simply ignored by the new code the first
# time it loads under v0.30, same as any Store.async_load() encountering keys
# it doesn't recognize.
STORAGE_KEY_WEEKLY_BONUS_STATE: Final = f"{DOMAIN}.weekly_bonus_state"
# v0.17: the parent-maintained Favoriten template catalog - see
# WS_API_PREFIX_FAVORITES above.
STORAGE_KEY_FAVORITES: Final = f"{DOMAIN}.favorites"
# v0.27: which member currently has which task occurrence's "Annehmen"
# reservation open - see ClaimStateStore in storage.py and the "Task
# claiming / reservation" section above.
STORAGE_KEY_CLAIM_STATE: Final = f"{DOMAIN}.claim_state"
# v0.32: per-member Streak-Bonus cursor/counter - see StreakBonusStateStore
# in storage.py and CONF_STREAK_BONUS_ENABLED above.
STORAGE_KEY_STREAK_BONUS_STATE: Final = f"{DOMAIN}.streak_bonus_state"
# v0.32: the household-wide Urlaubsmodus on/off state - see
# VacationModeStateStore in storage.py and CONF_VACATION_MODE_DEFAULT above.
STORAGE_KEY_VACATION_MODE: Final = f"{DOMAIN}.vacation_mode"

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

# v0.24: marks a catalog reward as needing a short free-text note from the
# redeeming member, filled in at redemption time (family_tasks/
# reward_redemption/redeem's new optional "note") and stored on the
# resulting redemption entry - e.g. the seeded "Mittagessen auswählen"
# reward, where a child should be able to say *which* lunch they want
# instead of a parent having to ask separately after the fact. Off by
# default, same "opt-in per catalog item" pattern as
# CONF_REWARD_SCREEN_TIME_MINUTES/CONF_REWARD_AUTO_FULFILL - most rewards
# ("Filmabend aussuchen") don't need any extra detail. CONF_REWARD_NOTE_LABEL
# is the optional custom field label shown above the text field (e.g.
# "Gewünschtes Mittagessen"); falls back to a generic label in the card if
# left blank. See ws_redeem_reward in storage.py, which rejects a redemption
# of such a reward if "note" is missing/blank.
CONF_REWARD_NOTE_ENABLED: Final = "note_enabled"
CONF_REWARD_NOTE_LABEL: Final = "note_label"

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

# v0.32: fired whenever a parent rejects ("Ablehnen") a child's completion
# claim (member_id/member_name/task_name/note - note may be None) - same
# extension-point pattern as EVENT_TASK_ASSIGNED/EVENT_REWARD_REDEEMED. The
# integration itself only ever calls the member's notify.* service or raises
# a persistent_notification (see FamilyTasksCoordinator._async_notify_rejection
# in coordinator.py); a household's own automation can react to this event
# however else it likes.
EVENT_TASK_REJECTED: Final = f"{DOMAIN}_task_rejected"

# --- Manual point awards (v0.24) ------------------------------------------------
#
# Lets a parent grant (or, with a negative amount, deduct/correct) points for
# a member directly, independent of any task or reward - e.g. a one-off
# "half-yearly report card" bonus, or fixing a mistaken completion without
# having to fabricate a fake task for it. Not a StorageCollection: creating
# one just appends to the existing completion log (see
# MANUAL_POINTS_TASK_ID/CompletionLogStore.async_add_entry, same mechanism
# the Meilensteinbonus already uses) rather than being its own persisted,
# editable entity - there's nothing to later edit/delete, only ever more
# awards on top, same as a task completion itself is never edited after the
# fact. Parent-only (not a child, regardless of HA admin flag - same
# "_member_role_for_user != MEMBER_ROLE_CHILD" guard used throughout
# storage.py), see ws_award_points in storage.py.
WS_API_POINTS_AWARD: Final = f"{DOMAIN}/points/award"

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
# v0.27: reserve/give back an eligible task occurrence - see
# FamilyTasksCoordinator.async_claim_task/async_release_task in
# coordinator.py and the "Task claiming / reservation" section above. Plain
# services (like complete_task/skip_task/toggle_subtask above) rather than
# admin-only websocket commands, for the same reason toggle_subtask is one -
# any eligible family member, not just admins, needs to be able to call them.
SERVICE_CLAIM_TASK: Final = "claim_task"
SERVICE_RELEASE_TASK: Final = "release_task"
# v0.32: wipes stored *points* data - the completion log, reward redemptions,
# and Meilenstein-/Streak-Bonus tracking - back to zero, optionally scoped to
# one member (ATTR_MEMBER_ID) or, left unset, every member at once. Task and
# member *definitions* and the reward catalog itself are untouched - see
# FamilyTasksCoordinator.async_reset_points in coordinator.py. Admin-only is
# not enforceable at the plain-service level (unlike the websocket API), same
# as every other family_tasks.* service - a household is expected to guard
# this via HA's own user/area permissions if that matters to them.
SERVICE_RESET_POINTS: Final = "reset_points"

ATTR_TASK_ID: Final = "task_id"
ATTR_MEMBER_ID: Final = "member_id"
ATTR_SUBTASK_ID: Final = "subtask_id"
# v0.32: optional free-text note a parent leaves when rejecting ("Ablehnen")
# a child's completion via SERVICE_SKIP_TASK - see async_skip_task in
# coordinator.py.
ATTR_NOTE: Final = "note"

# --- Frontend -----------------------------------------------------------------

CARD_FILENAME: Final = "family-tasks-card.js"
CARD_URL_PATH: Final = f"/family_tasks_static/{CARD_FILENAME}"

# --- Misc -----------------------------------------------------------------

MANUFACTURER: Final = "Family Tasks"
