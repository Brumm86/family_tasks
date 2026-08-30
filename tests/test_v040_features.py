"""Tests for the three v0.40 changes:

1. Bug fix: a "weekly" task whose current-week occurrence hadn't happened
   yet used to be reported as plain TASK_STATUS_PENDING regardless of how
   far in the future that occurrence actually was - there was no separate
   "not due yet" status for a calendar-based task, only TASK_STATUS_IDLE
   (reserved for an untriggered sensor/battery task). A brand-new task
   created before its own configured weekday had ever occurred (see the
   v0.39 CHANGELOG entry/created_at) could therefore resolve to a date days
   away while still showing up as "offen" everywhere (the card's "Alle"
   list, a member's own filtered view, FamilyTasksMemberOpenTasksSensor).
   Fixed together with feature 3 below, which needed the same underlying
   period-date rework anyway - see TASK_STATUS_UPCOMING.

2. Bug fix: picking an icon via <ha-icon-picker>'s own type-to-filter search
   didn't work - typing a character into it fired the picker's own
   "value-changed" event immediately (unlike <ha-date-input>/<ha-time-input>,
   whose "value-changed" only ever fires once, on an actual final
   selection), which the card's shared value-changed listener replayed as a
   full "change", replacing the *entire* form via outerHTML and destroying
   the picker's own DOM (along with its open dropdown, typed filter text,
   and input focus) after every single keystroke. Pure frontend fix (see
   family-tasks-card.js's value-changed listener) with no coordinator/
   storage surface, so there is nothing to exercise here - see the
   project's jsdom-based smoke check (project_family_tasks_test_env memory)
   for that half instead, same as the v0.37 Münzen-Wochenfortschritt UI
   change noted there.

3. "Es sollen immer alle bereits vorhersehbaren Aufgaben der jeweils
   laufenden Woche angezeigt werden. Die Aufgaben sollen bis zur Fälligkeit
   mit einem grünen Label dargestellt werden ... Diese Aufgaben sollen erst
   am Tag ihrer Fälligkeit erledigt werden können.": a normally assigned
   (fixed/rotating, non-Aufgabenpool) "weekly" task now previews its
   current *calendar week's* occurrence from Monday onward, exactly like an
   Aufgabenpool task already did (_pool_period_date) - but as the new
   TASK_STATUS_UPCOMING rather than TASK_STATUS_PENDING: visible (with its
   due_at's weekday - the card's job, not tested here), not claimable, and
   -  enforced server-side in async_complete_task, not just by the card
   hiding/disabling the button - not completable until that day actually
   arrives. An Aufgabenpool task is explicitly unaffected (stays
   TASK_STATUS_PENDING/claimable for that same early window - claiming
   ahead of the day is the whole point of the pool, see
   test_v030_features.test_pool_task_previews_this_weeks_occurrence_before_its_weekday,
   updated alongside this file to also cover the assigned-task half's new
   TASK_STATUS_UPCOMING behavior). "Aufgaben sollen in chronologischer
   Reihenfolge nach ihrer Fälligkeit dargestellt werden" is a pure card
   sorting change (_sortByDueAt in family-tasks-card.js) with nothing to
   assert against the coordinator, so it isn't covered here either.

Standalone reimplementation-level verification of _current_period_date's
new pure logic (no HA runtime) was also run directly against a copy of the
real function during development - see the session's verification notes.
This file follows the existing init_integration-fixture style for whenever
a real Python 3.13 HA test environment is available (see
project_family_tasks_test_env memory - the sandbox this was written in
can't run it end-to-end, same as every other test_v0*_features.py file).
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

from homeassistant.util import dt as dt_util

from custom_components.family_tasks.const import (
    TASK_STATUS_IDLE,
    TASK_STATUS_PENDING,
    TASK_STATUS_UPCOMING,
)
from custom_components.family_tasks.coordinator import _current_period_date


# --- Pure _current_period_date behavior (no HA runtime needed) --------------


def test_weekly_period_bounded_to_current_week_returns_none_when_unreachable():
    """A brand-new task created *after* its only configured weekday already
    passed this week has nothing to preview until next week - see the long
    comment on _current_period_date's "weekly" branch. Distinct from the
    old (pre-v0.40) unbounded forward search, which used to jump straight
    to next week's occurrence instead and show it as already "offen"."""
    friday = date(2026, 9, 4)  # a Friday
    created_on_friday = friday  # task created that same day
    monday_only = {"type": "weekly", "weekdays": [0]}  # Monday already passed

    assert _current_period_date(monday_only, friday, created_on_friday) is None
    # Still nothing through the rest of that same week.
    sunday = friday + timedelta(days=2)
    assert _current_period_date(monday_only, sunday, created_on_friday) is None
    # But next week's Monday resolves normally again.
    next_monday = friday + timedelta(days=3)
    assert _current_period_date(monday_only, next_monday, created_on_friday) == next_monday


def test_weekly_period_previews_this_weeks_not_yet_arrived_weekday():
    """An existing (or brand-new-this-week) task due Friday, viewed on
    Monday, now resolves to *this* Friday - not last week's already-past
    one, and not hidden until Friday either. _async_update_data is what
    turns "period_start is in the future" into TASK_STATUS_UPCOMING; this
    only checks the date itself."""
    monday = date(2026, 8, 31)
    friday_only = {"type": "weekly", "weekdays": [4]}

    this_friday = monday + timedelta(days=4)
    assert _current_period_date(friday_only, monday, None) == this_friday
    # A task created that very Monday behaves the same (created_at doesn't
    # exclude anything still ahead of it).
    assert _current_period_date(friday_only, monday, monday) == this_friday


def test_weekly_period_still_flags_already_missed_day_this_week_as_overdue_target():
    """A Monday-only task, viewed midweek, still resolves *backward* to
    this week's already-passed Monday (not None, not next week) - _async_
    update_data's `now > deadline_at` check is what turns that into
    TASK_STATUS_OVERDUE; unaffected by the v0.40 rework."""
    wednesday = date(2026, 9, 2)
    monday_only = {"type": "weekly", "weekdays": [0]}
    this_monday = wednesday - timedelta(days=2)

    assert _current_period_date(monday_only, wednesday, None) == this_monday


# --- End-to-end via the coordinator -----------------------------------------


async def _add_task(runtime, *, member_ids, **overrides):
    payload = {
        "name": "Testaufgabe",
        "points": 5,
        "recurrence": {"type": "daily"},
        "rotation": {"member_ids": member_ids, "strategy": "fixed"},
    }
    payload.update(overrides)
    return await runtime.tasks.async_create_item(payload)


def _start_of_week_utc(offset_weeks: int = 0):
    """Mirror FamilyTasksCoordinator._async_update_data's start_of_week math
    - see the identical helper in test_v030_features.py for why."""
    local_now = dt_util.now()
    start_of_today = dt_util.as_utc(dt_util.start_of_local_day(local_now))
    start_of_week = start_of_today - timedelta(days=start_of_today.weekday())
    return start_of_week + timedelta(weeks=offset_weeks)


async def _refresh_at_utc(runtime, utc_dt) -> None:
    local_dt = dt_util.as_local(utc_dt)
    with (
        patch.object(dt_util, "now", return_value=local_dt),
        patch.object(dt_util, "utcnow", return_value=utc_dt),
    ):
        await runtime.coordinator.async_refresh()


async def _complete_at_utc(runtime, task_id, utc_dt, member_id=None) -> None:
    local_dt = dt_util.as_local(utc_dt)
    with (
        patch.object(dt_util, "now", return_value=local_dt),
        patch.object(dt_util, "utcnow", return_value=utc_dt),
    ):
        await runtime.coordinator.async_complete_task(task_id, member_id)


async def test_upcoming_weekly_task_not_completable_until_its_weekday(
    hass, init_integration
) -> None:
    """A fixed-assigned weekly task due Friday, viewed on Monday, is
    TASK_STATUS_UPCOMING - visible, but async_complete_task must silently
    refuse to mark it done early (same "silent no-op" pattern as every
    other guard clause there), exactly like the card's own disabled
    "Erledigt" button. Once Friday actually arrives, it behaves exactly
    like any other due task again."""
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna", "role": "child"})
    monday = _start_of_week_utc(0)

    # v0.39's created_at gate (see _current_period_date) would otherwise
    # make this test's outcome depend on which real weekday it happens to
    # run on (created_at is stamped from the real, un-mocked clock) - pin it
    # to this same simulated Monday instead, same as the "created after its
    # weekday passed" test below already has to.
    with (
        patch.object(dt_util, "now", return_value=dt_util.as_local(monday + timedelta(hours=9))),
        patch.object(dt_util, "utcnow", return_value=monday + timedelta(hours=9)),
    ):
        task = await _add_task(
            runtime,
            member_ids=[anna["id"]],
            points=5,
            recurrence={"type": "weekly", "weekdays": [4]},
            requires_confirmation=False,
        )

    await _refresh_at_utc(runtime, monday + timedelta(hours=9))

    status = runtime.coordinator.data.tasks[task["id"]]
    expected_friday = (monday + timedelta(days=4)).date().isoformat()
    assert status.period_key == expected_friday
    assert status.status == TASK_STATUS_UPCOMING
    assert status.assigned_member_id == anna["id"]
    assert status.claimable is False

    # Trying to complete it early is a no-op: no completion gets logged, and
    # a fresh refresh still finds it TASK_STATUS_UPCOMING, not done.
    await _complete_at_utc(runtime, task["id"], monday + timedelta(hours=10), anna["id"])
    await _refresh_at_utc(runtime, monday + timedelta(hours=10))
    still_upcoming = runtime.coordinator.data.tasks[task["id"]]
    assert still_upcoming.status == TASK_STATUS_UPCOMING
    assert runtime.coordinator.data.members[anna["id"]].points_total == 0

    # Friday itself: back to the normal pending/completable flow.
    friday = monday + timedelta(days=4, hours=9)
    await _refresh_at_utc(runtime, friday)
    assert runtime.coordinator.data.tasks[task["id"]].status == TASK_STATUS_PENDING

    await _complete_at_utc(runtime, task["id"], friday + timedelta(hours=1), anna["id"])
    await _refresh_at_utc(runtime, friday + timedelta(hours=1))
    assert runtime.coordinator.data.members[anna["id"]].points_total == 5


async def test_new_weekly_task_created_after_its_weekday_stays_idle_this_week(
    hass, init_integration
) -> None:
    """A task created *after* its only configured weekday already passed
    this week (e.g. created Friday for "Monday only") has nothing
    foreseeable this week - idle/not shown, same as an untriggered sensor
    task, rather than the pre-v0.40 behavior of either being immediately
    overdue (pre-v0.39) or previewing a date days into next week while
    still marked "offen" (v0.39-v0.39.x, the bug fixed here)."""
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna", "role": "child"})

    monday = _start_of_week_utc(0)
    friday = monday + timedelta(days=4, hours=9)

    with (
        patch.object(dt_util, "now", return_value=dt_util.as_local(friday)),
        patch.object(dt_util, "utcnow", return_value=friday),
    ):
        task = await _add_task(
            runtime,
            member_ids=[anna["id"]],
            points=5,
            recurrence={"type": "weekly", "weekdays": [0]},  # Monday only
        )

    await _refresh_at_utc(runtime, friday)
    status = runtime.coordinator.data.tasks[task["id"]]
    assert status.status == TASK_STATUS_IDLE
    assert status.period_key == ""

    # Still nothing on Sunday, same week.
    await _refresh_at_utc(runtime, monday + timedelta(days=6, hours=9))
    assert runtime.coordinator.data.tasks[task["id"]].status == TASK_STATUS_IDLE

    # Next Monday: resolves normally again.
    next_monday = monday + timedelta(weeks=1, hours=9)
    await _refresh_at_utc(runtime, next_monday)
    next_status = runtime.coordinator.data.tasks[task["id"]]
    assert next_status.period_key == (monday + timedelta(weeks=1)).date().isoformat()
    assert next_status.status == TASK_STATUS_PENDING
