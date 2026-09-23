"""Tests for the v0.64 "yearly" recurrence type, and its v0.65 bug fix.

v0.64 added a fifth calendar-based recurrence option (alongside "daily"/
"weekly"/"interval_days"/"once", see RECURRENCE_TYPES in const.py): a task
due once a year on a fixed month/day, e.g. "immer am 29.07." for a birthday
or anniversary/reminder. Reuses the existing "anchor_date" field (already
used by "interval_days"/"once", see RECURRENCE_SCHEMA in storage.py and the
matching ha-date-input in family-tasks-card.js) - only its month/day end up
mattering, the year it happens to be saved with is never read again.

v0.64's first version of _current_period_date's "yearly" branch mirrored
"interval_days" unconditionally: the period was always either this year's
or last year's occurrence, whichever was more recent, staying "the current
period" (possibly overdue, if missed) until the next one rolled around a
year later. That turned out to be wrong for "yearly" specifically - unlike
"interval_days", whose anchor_date normally *is* the task's own creation
date, a "yearly" task's anchor only ever carries a month/day, so this always
resolved to *some* date from the current or previous calendar year
regardless of whether the task had even existed yet:

- A task created any time after its own month/day had already passed this
  year showed up immediately "überfällig" for a date before it was ever
  created - reported directly against a real Home Assistant instance: a
  task for "29.07." created in September showed as overdue for the July
  date the moment it was saved.
- A task created *before* its date (most of the year, for most tasks)
  resolved to *last* year's already-past occurrence instead of "not due
  yet" - so a brand-new "yearly" task was, in practice, never idle/"nicht
  fällig" at all, contrary to what the "nicht fällige Aufgaben" section is
  for.

v0.65 reworks the branch (see _yearly_occurrences, shared with
_pool_period_date) to mirror "weekly" instead: a due/overdue occurrence
still takes priority (same "stays the current period until completed or a
year passes" semantics "interval_days" already has), gated by the same
created_at guard "weekly" has had since v0.39 (a candidate before the task's
own creation is never "the" period); otherwise the *next* occurrence is
only previewed once it falls within the current calendar week (the same
bounded "Bald fällig" window every other recurrence type gets), and the
task is idle/hidden ("nicht fällig") the rest of the year.

Standalone reimplementation-level verification of the exact logic (a
line-for-line copy, asserted separately) was also run directly during
development - see the session's verification notes. This file follows the
existing test_v0*_features.py convention (see project_family_tasks_test_env
memory): the sandbox this was written in can't run it end-to-end (Python
3.10 only, and even after installing pytest-homeassistant-custom-component
the bundled homeassistant version predates StaticPathConfig, same blocker
documented for every prior version) - for whenever a real Python 3.13 HA
test environment is available.
"""

from __future__ import annotations

from datetime import date, timedelta

from custom_components.family_tasks.coordinator import (
    _current_period_date,
    _pool_period_date,
    _yearly_anchor_date,
    _yearly_occurrences,
)


# --- Pure _yearly_anchor_date behavior (no HA runtime needed) ---------------


def test_yearly_anchor_date_falls_back_to_feb_28_in_a_non_leap_year():
    assert _yearly_anchor_date(2027, 2, 29) == date(2027, 2, 28)
    # 2028 is a leap year - resolves to the real Feb 29th.
    assert _yearly_anchor_date(2028, 2, 29) == date(2028, 2, 29)


# --- The v0.65 bug fix itself: a brand-new task must never show as already
# overdue for a date before it existed, nor stay "not due yet" forever by
# resolving to a stale prior-year date instead --------------------------


def test_new_yearly_task_created_after_its_date_already_passed_this_year_is_idle():
    """The exact bug reported against a real Home Assistant instance: a
    "29.07." task created in September (its date long past for this year)
    must not show up immediately "überfällig" for a date before it ever
    existed - it should be idle/"nicht fällig" until its *next* occurrence
    (next year) comes near."""
    created_in_september = date(2026, 9, 23)
    birthday = {"type": "yearly", "anchor_date": "2026-07-29"}

    assert (
        _current_period_date(birthday, created_in_september, created_in_september)
        is None
    )
    # Still idle weeks later, same year - nowhere near next year's date yet.
    assert (
        _current_period_date(birthday, date(2026, 12, 1), created_in_september)
        is None
    )


def test_new_yearly_task_created_before_its_date_this_year_is_idle_not_last_years_date():
    """A task created any time before its own month/day this year must not
    resolve to *last* year's already-past occurrence (which would make it
    look immediately overdue too) - it's simply not due yet."""
    created_in_january = date(2026, 1, 5)
    birthday = {"type": "yearly", "anchor_date": "2020-07-29"}  # saved year is irrelevant

    assert _current_period_date(birthday, date(2026, 1, 10), created_in_january) is None
    assert _current_period_date(birthday, date(2026, 6, 1), created_in_january) is None


def test_yearly_period_previews_within_the_current_week_before_its_own_date():
    """Once the next occurrence falls within the current calendar week, it
    previews (same bounded "Bald fällig" window every other recurrence type
    gets) - _async_update_data is what turns "period_start is in the
    future" into TASK_STATUS_UPCOMING; this only checks the date itself."""
    created_in_january = date(2026, 1, 5)
    # 2026-07-29 is a Wednesday - Monday of that week is 2026-07-27.
    monday_of_due_week = date(2026, 7, 27)
    birthday = {"type": "yearly", "anchor_date": "2020-07-29"}

    assert (
        _current_period_date(birthday, monday_of_due_week, created_in_january)
        == date(2026, 7, 29)
    )
    # The day before that Monday, still more than a week out - idle.
    assert (
        _current_period_date(birthday, monday_of_due_week - timedelta(days=1), created_in_january)
        is None
    )


def test_yearly_period_is_due_on_and_stays_overdue_after_its_own_date():
    created_in_january = date(2026, 1, 5)
    birthday = {"type": "yearly", "anchor_date": "2020-07-29"}

    assert _current_period_date(birthday, date(2026, 7, 29), created_in_january) == date(2026, 7, 29)
    # Stays "the" period for the rest of the year (interval_days-style) -
    # _async_update_data's `now > deadline_at` check is what turns this into
    # TASK_STATUS_OVERDUE once its due_time/overdue_time has passed; this
    # only checks the date itself.
    assert _current_period_date(birthday, date(2026, 12, 31), created_in_january) == date(2026, 7, 29)
    # Rolls over to the next year's occurrence once it arrives.
    assert _current_period_date(birthday, date(2027, 7, 29), created_in_january) == date(2027, 7, 29)


def test_yearly_period_handles_a_feb_29_anchor_across_leap_and_non_leap_years():
    created_at = date(2020, 1, 1)
    leap_day_task = {"type": "yearly", "anchor_date": "2020-02-29"}

    assert _current_period_date(leap_day_task, date(2027, 3, 1), created_at) == date(2027, 2, 28)
    assert _current_period_date(leap_day_task, date(2028, 3, 1), created_at) == date(2028, 2, 29)


# --- _pool_period_date: an unassigned "Aufgabenpool" yearly task must always
# resolve to *some* upcoming date (never idle/None), same as "weekly" ------


def test_pool_yearly_task_previews_its_occurrence_regardless_of_the_current_week():
    """Unlike the assigned-task preview above, an Aufgabenpool occurrence
    must always be resolvable so a child can claim it in advance - not
    bounded to the current week."""
    created_in_january = date(2026, 1, 5)
    birthday = {"type": "yearly", "anchor_date": "2020-07-29"}

    assert _pool_period_date(birthday, date(2026, 1, 10), created_in_january) == date(2026, 7, 29)
    assert _pool_period_date(birthday, date(2026, 6, 1), created_in_january) == date(2026, 7, 29)


def test_pool_yearly_task_created_after_its_date_passed_previews_next_year():
    created_in_september = date(2026, 9, 23)
    birthday = {"type": "yearly", "anchor_date": "2026-07-29"}

    assert _pool_period_date(birthday, created_in_september, created_in_september) == date(2027, 7, 29)


# --- _yearly_occurrences directly -------------------------------------------


def test_yearly_occurrences_returns_none_due_and_next_years_date_when_created_after_this_years_passed():
    created_at = date(2026, 9, 23)
    birthday = {"type": "yearly", "anchor_date": "2026-07-29"}

    due_or_overdue, next_occurrence = _yearly_occurrences(birthday, created_at, created_at)
    assert due_or_overdue is None
    assert next_occurrence == date(2027, 7, 29)


def test_yearly_occurrences_returns_due_date_once_arrived_and_not_gated_by_created_at():
    created_at = date(2026, 1, 5)
    birthday = {"type": "yearly", "anchor_date": "2020-07-29"}

    due_or_overdue, next_occurrence = _yearly_occurrences(birthday, date(2026, 7, 29), created_at)
    assert due_or_overdue == date(2026, 7, 29)
    # next_occurrence is only ever consulted by a caller when due_or_overdue
    # is None - here it's simply "whatever comes after this year's date",
    # i.e. next year's, not itself asserted on by either caller.
    assert next_occurrence == date(2027, 7, 29)
