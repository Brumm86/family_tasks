"""Constants for the Family Tasks integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "family_tasks"

PLATFORMS: Final = [Platform.SENSOR, Platform.BUTTON, Platform.BINARY_SENSOR, Platform.SWITCH]

# --- Config / options keys -------------------------------------------------

# Household-wide fallback grace period, still used only by any task saved
# before v0.39 whose own "overdue_after_minutes" hasn't been superseded by an
# absolute "overdue_time" yet (see the "Task kinds / checklists" section
# below and _deadline_at in coordinator.py) - a new task's own "Überfällig
# ab" is always an explicit time-of-day set on the task itself now, no longer
# derived from this option.
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

# v0.36: fixed weekly-progress-percent checkpoints (percentages of
# CONF_WEEKLY_PROGRESS_GOAL_POINTS) the whole coin system is built around -
# replaces the pre-v0.36 Meilensteinbonus/Streak-Bonus, which let a household
# pick its own percent thresholds, with five checkpoints fixed the same way
# for everyone. 100% is "reached the weekly goal". Only meaningful while a
# weekly goal > 0 is configured - see CONF_WEEKLY_PROGRESS_GOAL_POINTS below,
# PROGRESS_BAND_TICK_ADJUSTMENT_MINUTES, and the coin-bonus constants below
# for what happens at each one.
PROGRESS_THRESHOLD_PERCENTS: Final = [0, 50, 100, 150, 200]

# v0.36: replaces the pre-v0.36 tick-based screen-time automation's fixed
# per-tick increment with one that responds to how a child is doing against
# their weekly-progress percent (see PROGRESS_THRESHOLD_PERCENTS above) -
# "Bei 0% soll die im Blueprint eingestellte Handyzeit pro Tick um 2 Minuten
# reduziert werden. Bei 50% soll die Zeit um 1 Minute pro Tick reduziert
# werden. Im Übrigen soll sie nicht geändert werden." Keyed by the *band* a
# member's current weekly-progress percent falls into: below 50% -> -2,
# 50% up to (not including) 100% -> -1, 100% and above -> unchanged. See
# FamilyTasksCoordinator._screen_time_tick_adjustment_minutes, which computes
# the per-member minutes value exposed as an attribute on
# FamilyTasksMemberPointsSensor
# (screen_time_tick_adjustment_minutes) for a household's
# Handyzeit-Verwaltung blueprint to read and subtract from its own configured
# per-tick increment (clamped at 0, never negative) - see
# blueprints/handyzeit_verwaltung.yaml. Not configurable - fixed household-
# wide amounts, same as PROGRESS_THRESHOLD_PERCENTS itself.
PROGRESS_BAND_TICK_ADJUSTMENT_MINUTES: Final = {0: -2, 50: -1, 100: 0}

# v0.36: bonus *coins* (see the "Münzen"/coin-shop section below) awarded
# live, the moment a participating member's weekly points cross the fixed
# 150%/200% weekly-progress checkpoints (PROGRESS_THRESHOLD_PERCENTS) -
# replaces the pre-v0.36 Meilensteinbonus (which paid *points* at an admin-
# chosen percent) entirely. 0 (the default) means no bonus at that
# checkpoint - no separate "enabled" switch, same as the pre-v0.36 bonus-
# points fields already worked when 0. See
# FamilyTasksCoordinator._async_process_milestone_coin_bonus.
CONF_MILESTONE_150_BONUS_COINS: Final = "milestone_150_bonus_coins"
CONF_MILESTONE_200_BONUS_COINS: Final = "milestone_200_bonus_coins"

# v0.36: extra bonus coins for *maintaining* the 150%/200% checkpoint above
# in more than one consecutive calendar week - on top of (not instead of) the
# per-week Meilenstein coin bonus above, same idea as the pre-v0.36
# Streak-Bonus paid on top of the weekly goal itself. Judged once a week has
# actually ended - see FamilyTasksCoordinator._async_process_streak_coin_bonus
# and StreakBonusStateStore in storage.py (tracks the 150%/200% tiers
# independently per member since v0.36).
# CONF_STREAK_BONUS_REQUIRED_WEEKS is shared by both tiers - default 2, i.e.
# "mehr als eine Woche in Folge".
CONF_STREAK_BONUS_REQUIRED_WEEKS: Final = "streak_bonus_required_weeks"
CONF_STREAK_150_BONUS_COINS: Final = "streak_150_bonus_coins"
CONF_STREAK_200_BONUS_COINS: Final = "streak_200_bonus_coins"

# Internal-only sentinel "reason" values for CoinLedgerStore entries created
# by FamilyTasksCoordinator._async_process_milestone_coin_bonus/
# _async_process_streak_coin_bonus - see storage.CoinLedgerStore. Unlike the
# points-based bonuses they replace, these never touch CompletionLogStore at
# all (a coin bonus must never count toward weekly-progress percent, or
# crossing 150% could itself push a member toward 200% purely from the bonus
# just paid for 150%) - the coin ledger is its own, separate append-only log,
# so there is no completion-log sentinel task_id to exclude from
# WS_API_MEMBER_WEEKLY_COMPLETIONS history here the way
# MILESTONE_BONUS_1_TASK_ID/STREAK_BONUS_TASK_ID below used to need.
COIN_REASON_MILESTONE_150: Final = "milestone_150"
COIN_REASON_MILESTONE_200: Final = "milestone_200"
COIN_REASON_STREAK_150: Final = "streak_150"
COIN_REASON_STREAK_200: Final = "streak_200"
# A shop redemption (negative amount) - see ws_redeem_reward in storage.py.
COIN_REASON_REDEMPTION: Final = "redemption"
# v0.44: a completed task's own "Münzwert" (task.get("coin_value", 0)),
# credited straight to CoinLedgerStore the moment the completion is logged -
# see FamilyTasksCoordinator.async_complete_task/_async_finalize_confirmation
# and the "coin_value" field on TASK_CREATE_SCHEMA/TASK_UPDATE_SCHEMA in
# storage.py. This is now the household's only *base* way to earn coins -
# see COIN_REASON_WEEKLY_CONVERSION below for the mechanic it replaces.
COIN_REASON_TASK_COMPLETION: Final = "task_completion"
# v0.37-v0.43 (retired in v0.44): a fully-elapsed calendar week's "points
# beyond the weekly goal" surplus, finalized into the ledger - see the old
# FamilyTasksCoordinator._async_process_weekly_coin_conversion and
# storage.WeeklyCoinConversionStateStore, both removed in v0.44. Coins are no
# longer derived from points/the weekly goal at all - a task now earns coins
# directly via its own "Münzwert" (COIN_REASON_TASK_COMPLETION above) - but
# this sentinel stays defined (and unused by anything that credits coins
# going forward) purely because a household upgrading from an older version
# may still have real historical CoinLedgerStore entries carrying it, and
# nothing should choke on reading those back.
COIN_REASON_WEEKLY_CONVERSION: Final = "weekly_conversion"

# v0.30-v0.35 sentinel task_ids, retired in v0.36 along with the points-based
# Meilensteinbonus/Streak-Bonus/negative-balance-correction machinery that
# created completion-log entries under them (see coordinator.py's CHANGELOG
# history) - no longer created by anything, but kept defined and still
# excluded from WS_API_MEMBER_WEEKLY_COMPLETIONS history in storage.py, since
# a household upgrading from an older version may still have real historical
# completion-log entries carrying these task_ids that should keep being
# hidden from that per-member weekly drill-down.
MILESTONE_BONUS_1_TASK_ID: Final = "__milestone_bonus_1__"
MILESTONE_BONUS_2_TASK_ID: Final = "__milestone_bonus_2__"
POINTS_CORRECTION_TASK_ID: Final = "__points_correction__"
STREAK_BONUS_TASK_ID: Final = "__streak_bonus__"

# v0.24: sentinel task_id for a manual points award/deduction a parent makes
# independent of any task (see WS_API_POINTS_AWARD/ws_award_points in
# storage.py) - never a real task, and excluded from the per-member weekly
# completion history for the same reason as the retired sentinels above (it
# isn't a completed task), while still counting normally toward the member's
# points_total/points_week/points_month - a manually-awarded point is just as
# "real" as a task-completion one, including toward the Meilenstein-/
# Streak-coin-bonus checkpoints (points_week vs. CONF_WEEKLY_PROGRESS_GOAL_POINTS).
# Never itself credits coins directly - see COIN_REASON_TASK_COMPLETION
# above for the only thing that does since v0.44.
MANUAL_POINTS_TASK_ID: Final = "__manual_points_award__"

# v0.29: household-wide weekly point goal backing each child's
# "Wochenfortschritt" progress bar (replaces the flat Bestenliste ranking -
# see family-tasks-card.js) and the fixed PROGRESS_THRESHOLD_PERCENTS
# checkpoints (150%/200%) the Meilenstein-/Streak-coin-bonus are judged
# against. Points themselves are never directly spendable in the reward shop
# (v0.36) - only ever drive this progress percent. v0.44: points earned
# *beyond* this goal no longer convert to coins either (that was the v0.36-
# v0.43 model, storage.coins_from_task_points, since removed) - coins now
# come exclusively from a task's own "coin_value" (COIN_REASON_TASK_COMPLETION)
# plus the Meilenstein-/Streak-Bonus, both entirely independent of this goal
# being reached at all. 0 (the default) disables the whole percent mechanic -
# see FamilyTasksCoordinator._async_update_data.
CONF_WEEKLY_PROGRESS_GOAL_POINTS: Final = "weekly_progress_goal_points"

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
DEFAULT_WEEKLY_PROGRESS_GOAL_POINTS: Final = 0
DEFAULT_MILESTONE_150_BONUS_COINS: Final = 0
DEFAULT_MILESTONE_200_BONUS_COINS: Final = 0
DEFAULT_STREAK_BONUS_REQUIRED_WEEKS: Final = 2
DEFAULT_STREAK_150_BONUS_COINS: Final = 0
DEFAULT_STREAK_200_BONUS_COINS: Final = 0
DEFAULT_VACATION_MODE: Final = False

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
# v0.40: a calendar-based task (in practice: "weekly") whose current-week
# occurrence is already known (see _current_period_date in coordinator.py)
# but not due yet - visible with its weekday so it isn't a surprise once the
# day arrives, but not completable until then (see async_complete_task).
# Never used for an "Aufgabenpool" task (is_pool_task in coordinator.py),
# which stays TASK_STATUS_PENDING for the same early-preview window -
# claiming/completing one ahead of its day is the whole point of the pool.
TASK_STATUS_UPCOMING: Final = "upcoming"
TASK_STATUSES: Final = [
    TASK_STATUS_IDLE,
    TASK_STATUS_PENDING,
    TASK_STATUS_UPCOMING,
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

# v0.37: a member marked "paused" is temporarily away from the household's
# task/reward system entirely - e.g. a child on a school trip for the week -
# without an admin having to touch their permanent CONF_MEMBER_REWARDS_OPT_IN/
# "active" configuration (both of which are meant as lasting household setup,
# not something to flip on and off every time someone travels). Distinct from
# both:
#   - CONF_MEMBER_REWARDS_OPT_IN: a permanent "this member never competes for
#     points/rewards at all" choice (e.g. for a parent's own account).
#   - "active": a permanent "this member no longer exists/uses the household
#     at all" toggle.
# While paused, a member (see FamilyTasksCoordinator._member_paused):
#   - is skipped when picking who a rotating/fixed task's occurrence is
#     assigned to (FamilyTasksCoordinator._async_update_data) - a task whose
#     *every* current assignee is paused is treated exactly like a household-
#     wide Urlaubsmodus-paused task (skipped entirely, not due) instead of
#     sitting there overdue with nobody able to act on it.
#   - is never added as a fallback "other eligible member" for an overdue
#     task or an Aufgabenpool occurrence - no new work lands on someone who
#     isn't there to do it.
#   - is excluded from Meilenstein-/Streak-coin-bonus eligibility, the
#     "Wochenfortschritt" progress bar, and reward-catalog redemption -
#     mirroring what CONF_MEMBER_REWARDS_OPT_IN already does, just
#     temporarily.
# Toggled via the same member-edit form as "active"/CONF_MEMBER_REWARDS_OPT_IN
# (family_tasks/member/update) - defaults to False so every existing member
# keeps behaving exactly as before this field was introduced. Nothing already
# earned (points, coins) is touched by pausing/unpausing - only new
# assignment and reward-system participation are gated.
CONF_MEMBER_PAUSED: Final = "paused"

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
# Every task defaults to TASK_KIND_STANDARD (single "erledigt" action).
# TASK_KIND_MANDATORY additionally gates screen time while overdue (see
# below). Either kind may *also* optionally carry a checklist (task
# "subtasks": [{"id", "name"}, ...], see SUBTASK_SCHEMA in storage.py) -
# sub-items get checked off individually (checked items render struck-
# through), and the task itself only becomes "done" once every sub-item is
# checked for the current period (see
# FamilyTasksCoordinator.async_toggle_subtask). Which sub-items are currently
# checked is per-occurrence runtime state, tracked the same way open trigger
# occurrences are (see storage.ChecklistStateStore), and resets whenever a
# new period starts, same as any other recurring task.
#
# v0.39: "checklist" used to be its own third TASK_KIND, mutually exclusive
# with "mandatory" - a task was either a checklist or a Pflichtaufgabe, never
# both, which meant a mandatory task could never also have a checklist.
# TASK_KIND_CHECKLIST is kept only so a task saved before this version (its
# stored "kind" is still literally "checklist") keeps loading/validating
# without a migration step; nothing in this codebase treats it specially any
# more - whether a task has a checklist is now determined purely by whether
# it has any "subtasks" at all (see e.g. FamilyTasksCoordinator's checklist
# handling), independent of "kind". The card normalizes an old checklist
# task's kind to "standard" (its subtasks carry over unchanged) the next time
# it's opened for editing - see taskToForm in family-tasks-card.js.
TASK_KIND_STANDARD: Final = "standard"
TASK_KIND_CHECKLIST: Final = "checklist"
# v0.14: a "Pflichtaufgabe" (mandatory task) - behaves exactly like
# TASK_KIND_STANDARD as far as completion itself goes (a single "Erledigt"
# action, or - since v0.39 - a checklist, exactly like a standard task), but
# is called out to the child as mandatory in the card, and while an
# occurrence of it is TASK_STATUS_OVERDUE, tick-based screen-time granting
# for exactly the member(s) it is assigned to is paused - see
# FamilyTasksCoordinator._async_update_data's screen_time_grant_active
# computation and binary_sensor.py. Resumes automatically the moment the
# occurrence is no longer overdue (completed, or - for a "child" assignee
# needing parental sign-off - once a parent confirms it); missed ticks are
# never made up, this only ever gates whether the *next* tick may grant
# anything.
TASK_KIND_MANDATORY: Final = "mandatory"
# Kinds selectable via "Aufgabentyp" going forward - TASK_KIND_CHECKLIST is
# deliberately excluded (see above); vol.In(TASK_KINDS) still accepts it on
# an update payload that doesn't touch "kind" at all, since voluptuous only
# validates keys actually present, but the card never sends it again.
TASK_KINDS: Final = [TASK_KIND_STANDARD, TASK_KIND_MANDATORY, TASK_KIND_CHECKLIST]
# Kinds a "child" member may pick when creating a task for themselves (see
# WS_API_TASK_CREATE_OWN below) - "mandatory" is a parent-only concept (it
# exists to let a parent gate a child's screen time), so it's deliberately
# left out here. Just TASK_KIND_STANDARD since v0.39 - a checklist is now an
# optional add-on (subtasks), not a separate kind to choose.
OWN_TASK_KINDS: Final = [TASK_KIND_STANDARD]

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
# already been awarded each Meilenstein coin-bonus checkpoint (150%/200%,
# "threshold_1"/"threshold_2" internally - unchanged field names since v0.36
# only changed what gets awarded there, not the tracking shape) - so
# FamilyTasksCoordinator only ever awards a given member/checkpoint/week
# combo once, regardless of how often the coordinator refreshes. Reset
# (pruned) automatically whenever the current week rolls over - see
# storage.MilestoneBonusStateStore. Physical storage key/file unchanged since
# v0.14, where it tracked the (now removed) weekly-winner bonus instead - an
# unrecognized older shape is simply ignored the first time it loads under
# whichever version actually changed it, same as any Store.async_load()
# encountering keys it doesn't recognize.
STORAGE_KEY_WEEKLY_BONUS_STATE: Final = f"{DOMAIN}.weekly_bonus_state"
# v0.36: the coin-shop ledger - every credit (v0.44: a completed task's own
# "Münzwert", see COIN_REASON_TASK_COMPLETION above, plus the Meilenstein-/
# Streak-coin bonuses) and debit (a shop redemption) a member's coin balance
# is made up of - see storage.CoinLedgerStore. A member's coins_available is
# simply this ledger's balance(); before v0.44 it also included a live
# "points beyond the weekly goal" computation (coins_from_task_points),
# removed along with COIN_REASON_WEEKLY_CONVERSION's crediting logic.
STORAGE_KEY_COIN_LEDGER: Final = f"{DOMAIN}.coin_ledger"
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
# v0.41: tracks which "fällig"/"überfällig" reminders (per assigned
# member) and which Aufgabenpool "appeared" broadcasts have already fired
# for a task's *current* occurrence - see DeadlineNotificationStateStore in
# storage.py and FamilyTasksCoordinator._async_notify_task_status in
# coordinator.py. Without this, the same reminder would re-fire on every
# single coordinator refresh for as long as the occurrence stays pending or
# overdue.
STORAGE_KEY_DEADLINE_NOTIFICATION_STATE: Final = f"{DOMAIN}.deadline_notification_state"

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

# --- Rewards (v0.9, currency switched to coins in v0.36) -----------------------
#
# A coin-shop: parents maintain a catalog of rewards, each with a price in
# "Münzen"/coins (WS_API_PREFIX_REWARDS, plain admin CRUD - see
# RewardStorageCollection in storage.py). Any family member who participates
# in the reward system (see CONF_MEMBER_REWARDS_OPT_IN above) can redeem any
# catalog reward at any time, provided their available coin balance (see
# MemberSummaryData.coins_available in coordinator.py) covers its price.
# Before v0.36 this was a *points*-shop - a reward's price was "points_cost"
# and the balance was points_available (all-time points minus redemptions).
# v0.36 splits the two currencies entirely: points now only ever drive the
# "Wochenfortschritt" weekly-progress percent, never shop spending directly.
# v0.36-v0.43 derived coins from that same weekly-progress surplus (see
# CONF_WEEKLY_PROGRESS_GOAL_POINTS above); v0.44 replaces that with coins
# earned directly per completed task (see "coin_value" on TASK_CREATE_SCHEMA
# in storage.py and COIN_REASON_TASK_COMPLETION above), plus the Meilenstein-/
# Streak-Bonus on top - see that constant's own comment for the full history.
# Redeeming is not exposed through
# the generic storage-collection "create" command for
# WS_API_PREFIX_REWARD_REDEMPTIONS (see RewardRedemptionStorageCollectionWebsocket
# in storage.py) because it needs the extra participation/balance checks -
# only WS_API_REWARD_REDEEM can create a redemption entry, and creating one
# *is* the coin deduction (a debit entry in storage.CoinLedgerStore). Parents
# (not children, regardless of HA admin flag) can mark a redemption
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

# v0.14: marks a "Handyzeit" catalog reward as using the "invest coins" flow
# (points before v0.36) instead of a fixed price/fixed screen_time_minutes
# pair - the member chooses how many coins to spend at redemption time
# (family_tasks/reward_redemption/redeem's "coins_spent", named
# "points_spent" before v0.36), and the screen time granted is coins_spent *
# CONF_SCREEN_TIME_MINUTES_PER_POINT (the household-wide bonus factor from
# Options - name/option-key kept as-is across the v0.36 currency switch so an
# already-configured value isn't silently reset), not a value stored on the
# catalog item itself. "coin_cost" is ignored for a reward with this flag
# set - see ws_redeem_reward in storage.py. Existing rewards that already had
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
# coin_cost/screen_time_minutes. This - not a hardcoded call into a specific
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

# v0.39: fired whenever a new "Aufgabenpool" occurrence (no fixed/rotating
# assignee, see is_pool_task in coordinator.py) becomes actionable - every
# active, non-paused member is notified, since any of them could be the one
# to claim it, unlike EVENT_TASK_ASSIGNED above which only ever reaches the
# task's actual assignee(s). Same extension-point pattern as
# EVENT_TASK_ASSIGNED/EVENT_TASK_REJECTED (member_id/member_name/task_id/
# task_name). v0.41: raised from FamilyTasksCoordinator._async_notify_task_status
# in coordinator.py (once per task per occurrence, via
# DeadlineNotificationStateStore) rather than only once from
# __init__._async_notify_new_task_assignments on task *creation* - a
# recurring Aufgabenpool task's next occurrence appearing now notifies again
# too, not just its very first one.
EVENT_TASK_POOL_ADDED: Final = f"{DOMAIN}_task_pool_added"

# v0.41: fired once per assigned member the moment their task's current
# occurrence becomes due (TASK_STATUS_PENDING) - see
# FamilyTasksCoordinator._async_notify_task_status/DeadlineNotificationStateStore
# in coordinator.py/storage.py. Same extension-point pattern as
# EVENT_TASK_ASSIGNED (member_id/member_name/task_id/task_name); a pool task
# (no fixed/rotating assignee) never fires this, see EVENT_TASK_POOL_ADDED
# above instead.
EVENT_TASK_DUE: Final = f"{DOMAIN}_task_due"

# v0.41: fired once per assigned member the moment their task's current
# occurrence turns overdue (TASK_STATUS_OVERDUE) - same mechanism/exclusions
# as EVENT_TASK_DUE above.
EVENT_TASK_OVERDUE: Final = f"{DOMAIN}_task_overdue"

# --- Manual point awards (v0.24) ------------------------------------------------
#
# Lets a parent grant (or, with a negative amount, deduct/correct) points for
# a member directly, independent of any task or reward - e.g. a one-off
# "half-yearly report card" bonus, or fixing a mistaken completion without
# having to fabricate a fake task for it. Not a StorageCollection: creating
# one just appends to the existing completion log (see
# MANUAL_POINTS_TASK_ID/CompletionLogStore.async_add_entry) rather than being
# its own persisted, editable entity - there's nothing to later edit/delete, only ever more
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
# v0.32: wipes stored *points/coins* data - the completion log, reward
# redemptions, the coin ledger, and Meilenstein-/Streak-Bonus tracking - back
# to zero, optionally scoped to one member (ATTR_MEMBER_ID) or, left unset,
# every member at once. Task and
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
