"""Tests for the v0.53 feature: manually-awarded points in the weekly
completions list.

Manually-awarded points appear in the "diese Woche erledigt" list
(ws_list_member_weekly_completions): explicit user request to show them
"unter den erledigten Aufgaben" with their point value and note.
MANUAL_POINTS_TASK_ID covers three distinct cases - a parent's deliberate
award/deduction (ws_award_points), the rejection penalty
(async_skip_task), and the expired-claim penalty (_async_expire_claim) -
all three now show up; the Meilenstein-/Streak-Bonus/points-correction
sentinels stay excluded, per explicit user request (none of those is a
single deliberate action the way the other three are).

v0.53 also shipped a Streak-Bonus payout-cap feature, tested by three tests
that used to live in this file. That cap turned out to be a misunderstanding
of the requested behaviour and was corrected in v0.54 (the bonus keeps being
paid every further qualifying week, just flat instead of climbing further -
see FamilyTasksCoordinator._async_process_member_streak_tier's docstring).
Those three tests were removed here and replaced by
tests/test_v054_features.py, which covers the corrected model; this file
keeps only the still-valid manual-points tests below.

This file follows the existing init_integration-fixture style for whenever a
real Python 3.13 HA test environment is available (see
project_family_tasks_test_env memory - the environment this was written in
can't run it end-to-end either, same limitation as every prior version).
"""

from __future__ import annotations

from homeassistant.util import dt as dt_util

from custom_components.family_tasks.const import (
    MANUAL_POINTS_TASK_ID,
    MILESTONE_BONUS_1_TASK_ID,
    POINTS_CORRECTION_TASK_ID,
    STREAK_BONUS_TASK_ID,
    WS_API_MEMBER_WEEKLY_COMPLETIONS,
)


# --- Manually-awarded points in the weekly completions list -----------------


async def test_manual_award_appears_in_weekly_completions(
    hass, init_integration, hass_ws_client
) -> None:
    """A parent's manual point award (with a note) now shows up in the list."""
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "family_tasks/points/award",
            "member_id": anna["id"],
            "points": 5,
            "note": "Oma beim Umzug geholfen",
        }
    )
    response = await client.receive_json()
    assert response["success"] is True

    await client.send_json_auto_id(
        {"type": WS_API_MEMBER_WEEKLY_COMPLETIONS, "member_id": anna["id"]}
    )
    response = await client.receive_json()
    assert response["success"] is True
    completions = response["result"]["completions"]
    assert len(completions) == 1
    assert completions[0]["task_name"] == "Oma beim Umzug geholfen"
    assert completions[0]["points_awarded"] == 5


async def test_manual_deduction_without_note_uses_generic_label(
    hass, init_integration, hass_ws_client
) -> None:
    """A manual deduction with no note falls back to the existing generic label."""
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "family_tasks/points/award", "member_id": anna["id"], "points": -2}
    )
    response = await client.receive_json()
    assert response["success"] is True

    await client.send_json_auto_id(
        {"type": WS_API_MEMBER_WEEKLY_COMPLETIONS, "member_id": anna["id"]}
    )
    response = await client.receive_json()
    completions = response["result"]["completions"]
    assert len(completions) == 1
    assert completions[0]["task_name"] == "Punkte abgezogen"
    assert completions[0]["points_awarded"] == -2


async def test_rejection_and_claim_expiry_penalties_also_appear(
    hass, init_integration, hass_ws_client
) -> None:
    """The two other MANUAL_POINTS_TASK_ID cases (system-triggered penalties,
    not a deliberate award) are included too, per explicit user request -
    each already carries its own distinguishing task_name."""
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})

    await runtime.completions.async_add_entry(
        task_id=MANUAL_POINTS_TASK_ID,
        period_key=dt_util.utcnow().date().isoformat(),
        member_id=anna["id"],
        points_awarded=-1,
        task_name="Nicht freigegeben: Zimmer aufräumen",
        note="Bett noch nicht gemacht",
    )
    await runtime.completions.async_add_entry(
        task_id=MANUAL_POINTS_TASK_ID,
        period_key=dt_util.utcnow().date().isoformat(),
        member_id=anna["id"],
        points_awarded=-1,
        task_name="Reservierung abgelaufen: Geschirrspüler ausräumen",
    )

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": WS_API_MEMBER_WEEKLY_COMPLETIONS, "member_id": anna["id"]}
    )
    response = await client.receive_json()
    task_names = {c["task_name"] for c in response["result"]["completions"]}
    assert task_names == {
        "Nicht freigegeben: Zimmer aufräumen",
        "Reservierung abgelaufen: Geschirrspüler ausräumen",
    }
    # The rejection's own separate explanation note is deliberately NOT
    # surfaced here (per explicit user request - "es reicht die Angabe ohne
    # Grund") - only task_name/points_awarded/completed_at are returned.
    for c in response["result"]["completions"]:
        assert "note" not in c


async def test_bonus_and_correction_sentinels_stay_excluded(
    hass, init_integration, hass_ws_client
) -> None:
    """Meilenstein-/Streak-Bonus and points-correction entries are still
    excluded - only MANUAL_POINTS_TASK_ID changed in v0.53."""
    runtime = init_integration.runtime_data
    anna = await runtime.members.async_create_item({"name": "Anna"})

    for task_id in (MILESTONE_BONUS_1_TASK_ID, POINTS_CORRECTION_TASK_ID, STREAK_BONUS_TASK_ID):
        await runtime.completions.async_add_entry(
            task_id=task_id,
            period_key=dt_util.utcnow().date().isoformat(),
            member_id=anna["id"],
            points_awarded=3,
            task_name="sollte nicht erscheinen",
        )

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": WS_API_MEMBER_WEEKLY_COMPLETIONS, "member_id": anna["id"]}
    )
    response = await client.receive_json()
    assert response["result"]["completions"] == []
