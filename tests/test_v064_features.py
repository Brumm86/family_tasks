"""Tests for the v0.64 "yearly" recurrence type.

Adds a fifth calendar-based recurrence option (alongside "daily"/"weekly"/
"interval_days"/"once", see RECURRENCE_TYPES in const.py): a task due once a
year on a fixed month/day, e.g. "immer am 29.07." for a birthday or
anniversary. Reuses the existing "anchor_date" field (already used by
"interval_days"/"once", see RECURRENCE_SCHEMA in storage.py and the
matching ha-date-input in family-tasks-card.js) - only its month/day end up
mattering, the year it happens to be saved with is never read again.

_current_period_date's new "yearly" branch (coordinator.py) follows the same
before/after-the-anchor convention "interval_days" already uses: the period
is this year's occurrence once it has arrived (today >= this year's date),
and otherwise still last year's - not "due again" until the date actually
comes around. A new helper, _yearly_anchor_date, resolves a year/month/day
combination that could be invalid for a Feb 29th anchor outside a leap year,
falling back to Feb 28th rather than raising.

Standalone reimplementation-level verification of both functions' exact
logic (a line-for-line copy, asserted separately) was also run directly
during development - see the session's verification notes. This file
follows the existing test_v0*_features.py convention (see
project_family_tasks_test_env memory): the sandbox this was written in
can't run it end-to-end (Python 3.10 only, and even after installing
pytest-homeassistant-custom-component the bundled homeassistant version
predates StaticPathConfig, same blocker documented for every prior
version) - for whenever a real Python 3.13 HA test environment is
available.
"""

from __future__ import annotations

from datetime import date

from custom_components.family_tasks.coordinator import (
    _current_period_date,
    _yearly_anchor_date,
)


# --- Pure _current_period_date / _yearly_anchor_date behavior (no HA runtime
# needed) ---------------------------------------------------------------


def test_yearly_period_resolves_to_last_years_date_before_this_years_has_arrived():
    """Viewed the day before the anchor's month/day, the "current" occurrence
    is still last year's - it isn't "due" again until the date itself
    arrives, same before/after-anchor convention "interval_days" uses."""
    birthday = {"type": "yearly", "anchor_date": "2020-07-29"}  # year is irrelevant

    assert _current_period_date(birthday, date(2026, 7, 28)) == date(2025, 7, 29)


def test_yearly_period_resolves_to_this_years_date_on_and_after_the_anchor_day():
    birthday = {"type": "yearly", "anchor_date": "2020-07-29"}

    assert _current_period_date(birthday, date(2026, 7, 29)) == date(2026, 7, 29)
    # Stays "this year's" date for the rest of the year - the period doesn't
    # change again until next year's occurrence rolls around.
    assert _current_period_date(birthday, date(2026, 12, 31)) == date(2026, 7, 29)
    assert _current_period_date(birthday, date(2027, 1, 1)) == date(2026, 7, 29)
    assert _current_period_date(birthday, date(2027, 7, 29)) == date(2027, 7, 29)


def test_yearly_period_ignores_the_anchor_dates_own_saved_year():
    """Only month/day are ever read back out of anchor_date - unlike
    RECURRENCE_ONCE, where the exact saved date matters."""
    task = {"type": "yearly", "anchor_date": "1999-07-29"}

    assert _current_period_date(task, date(2026, 8, 1)) == date(2026, 7, 29)


def test_yearly_anchor_date_falls_back_to_feb_28_in_a_non_leap_year():
    assert _yearly_anchor_date(2027, 2, 29) == date(2027, 2, 28)
    # 2028 is a leap year - resolves to the real Feb 29th.
    assert _yearly_anchor_date(2028, 2, 29) == date(2028, 2, 29)


def test_yearly_period_handles_a_feb_29_anchor_across_leap_and_non_leap_years():
    leap_day_task = {"type": "yearly", "anchor_date": "2020-02-29"}

    assert _current_period_date(leap_day_task, date(2027, 3, 1)) == date(2027, 2, 28)
    assert _current_period_date(leap_day_task, date(2028, 3, 1)) == date(2028, 2, 29)
