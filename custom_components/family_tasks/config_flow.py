"""Config flow for the Family Tasks integration."""

from __future__ import annotations

from datetime import date
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    DateSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
)

from .const import (
    CONF_BATTERY_ALERT_AUTO_COMPLETE_ON_RECOVERY,
    CONF_BATTERY_WARNING_THRESHOLD,
    CONF_DEFAULT_ROTATION_STRATEGY,
    COIN_THRESHOLD_KEYS,
    CONF_COIN_THRESHOLD_1_POINTS,
    CONF_COIN_THRESHOLD_2_POINTS,
    CONF_MALUS_THRESHOLD_1_POINTS,
    CONF_MALUS_THRESHOLD_2_POINTS,
    CONF_MALUS_THRESHOLD_3_POINTS,
    CONF_MALUS_THRESHOLD_4_POINTS,
    CONF_MILESTONE_150_BONUS_COINS,
    MALUS_THRESHOLD_KEYS,
    resolve_progress_thresholds,
    thresholds_ascending,
    CONF_MILESTONE_200_BONUS_COINS,
    CONF_OVERDUE_AFTER_MINUTES,
    CONF_SCREEN_TIME_MALUS_START_DATE,
    CONF_SCREEN_TIME_MINUTES_PER_POINT,
    CONF_SCREEN_TIME_TICK_MINUTES,
    CONF_SCREEN_TIME_TICKS_PER_DAY,
    CONF_STREAK_BONUS_2_WEEKS_COINS,
    CONF_STREAK_BONUS_3_WEEKS_COINS,
    CONF_TOP_SCORER_BONUS_COINS,
    CONF_VACATION_MODE_DEFAULT,
    CONF_WEEKLY_PROGRESS_GOAL_POINTS,
    DEFAULT_BATTERY_ALERT_AUTO_COMPLETE_ON_RECOVERY,
    DEFAULT_BATTERY_WARNING_THRESHOLD,
    DEFAULT_MILESTONE_150_BONUS_COINS,
    DEFAULT_MILESTONE_200_BONUS_COINS,
    DEFAULT_OVERDUE_AFTER_MINUTES,
    DEFAULT_ROTATION_STRATEGY,
    DEFAULT_SCREEN_TIME_MINUTES_PER_POINT,
    DEFAULT_SCREEN_TIME_TICK_MINUTES,
    DEFAULT_SCREEN_TIME_TICKS_PER_DAY,
    DEFAULT_STREAK_BONUS_2_WEEKS_COINS,
    DEFAULT_STREAK_BONUS_3_WEEKS_COINS,
    DEFAULT_TOP_SCORER_BONUS_COINS,
    DEFAULT_VACATION_MODE,
    DEFAULT_WEEKLY_PROGRESS_GOAL_POINTS,
    DOMAIN,
    ROTATION_STRATEGIES,
)

DEFAULT_TITLE = "Family Tasks"


class FamilyTasksConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Family Tasks."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial (and only) setup step.

        Family Tasks manages all household members and tasks itself via
        storage collections, so there is nothing to configure here beyond a
        display name; the entry is a singleton (see single_config_entry in
        the manifest).
        """
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            return self.async_create_entry(title=user_input[CONF_NAME], data={})

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_NAME, default=DEFAULT_TITLE): str}),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Create the options flow."""
        return FamilyTasksOptionsFlow()


class FamilyTasksOptionsFlow(OptionsFlow):
    """Handle Family Tasks options (household-wide defaults).

    Task and member CRUD is intentionally not part of this flow; it happens
    through the storage collection websocket API / frontend, matching how
    other storage-collection-backed helpers are managed.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}
        if user_input is not None:
            data = dict(user_input)
            # v0.68: the malus/coin thresholds are absolute points now; an
            # empty field means "derive from the weekly goal" (see
            # resolve_progress_thresholds). They must be strictly ascending:
            # malus 1 < 2 < 3 < 4 < weekly goal < coin 1 < coin 2.
            for key in (*MALUS_THRESHOLD_KEYS, *COIN_THRESHOLD_KEYS):
                if data.get(key) in (None, ""):
                    data.pop(key, None)
                else:
                    data[key] = int(data[key])
            goal_points = int(data.get(CONF_WEEKLY_PROGRESS_GOAL_POINTS) or 0)
            if goal_points > 0:
                malus, coin = resolve_progress_thresholds(data, goal_points)
                if not thresholds_ascending(malus, goal_points, coin):
                    errors["base"] = "thresholds_not_ascending"
                    return self._show_form(user_input, errors)
            # v0.46: DateSelector (see CONF_SCREEN_TIME_MALUS_START_DATE
            # below) validates to a raw datetime.date object, but
            # config-entry options are persisted through HA's plain
            # JSONEncoder (homeassistant.helpers.storage.Store), which has
            # no support for datetime.date - only datetime.datetime. Store
            # its ISO string instead (dt_util.parse_date on read, see
            # _async_update_data in coordinator.py), same representation
            # every other date in this integration already uses (e.g.
            # TaskStorageCollection's created_at).
            malus_start_date = data.get(CONF_SCREEN_TIME_MALUS_START_DATE)
            if isinstance(malus_start_date, date):
                data[CONF_SCREEN_TIME_MALUS_START_DATE] = malus_start_date.isoformat()
            return self.async_create_entry(data=data)

        # On a validation error, re-show the form pre-filled with what the
        # user just submitted (not the previously saved options) so a typo'd
        # field doesn't reset every other field back to its old value too.
        return self._show_form(None, errors)

    def _show_form(
        self, user_input: dict[str, Any] | None, errors: dict[str, str]
    ) -> ConfigFlowResult:
        """Render the options form (pre-filled from user_input after an error)."""
        current = user_input if user_input is not None else self.config_entry.options
        goal_now = int(current.get(CONF_WEEKLY_PROGRESS_GOAL_POINTS) or 0)
        malus_now, coin_now = resolve_progress_thresholds(current, goal_now)

        def _threshold(key: str, suggested: int) -> tuple[vol.Optional, NumberSelector]:
            return (
                vol.Optional(key, description={"suggested_value": suggested}),
                NumberSelector(
                    NumberSelectorConfig(
                        min=0, max=100000, mode=NumberSelectorMode.BOX, unit_of_measurement="Pkt."
                    )
                ),
            )

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_OVERDUE_AFTER_MINUTES,
                    default=current.get(
                        CONF_OVERDUE_AFTER_MINUTES, DEFAULT_OVERDUE_AFTER_MINUTES
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(min=0, max=1440, mode=NumberSelectorMode.BOX)
                ),
                vol.Optional(
                    CONF_DEFAULT_ROTATION_STRATEGY,
                    default=current.get(
                        CONF_DEFAULT_ROTATION_STRATEGY, DEFAULT_ROTATION_STRATEGY
                    ),
                ): SelectSelector(
                    SelectSelectorConfig(options=ROTATION_STRATEGIES, translation_key="rotation_strategy")
                ),
                # Default warning level for "battery" recurrence tasks (see
                # RECURRENCE_BATTERY) - overridable per entity via the card's
                # battery-monitoring section.
                vol.Optional(
                    CONF_BATTERY_WARNING_THRESHOLD,
                    default=current.get(
                        CONF_BATTERY_WARNING_THRESHOLD, DEFAULT_BATTERY_WARNING_THRESHOLD
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0, max=100, mode=NumberSelectorMode.BOX, unit_of_measurement="%"
                    )
                ),
                # v0.35: whether an auto-generated battery-alert task
                # (RECURRENCE_ONCE, "battery_alert" - see
                # FamilyTasksCoordinator._async_raise_battery_alerts)
                # completes itself once the battery it names recovers, same
                # as a "trigger" task's per-task auto_complete_on_normalize
                # checkbox (v0.34) but as one household-wide setting, since
                # these alert tasks have no form of their own.
                vol.Optional(
                    CONF_BATTERY_ALERT_AUTO_COMPLETE_ON_RECOVERY,
                    default=current.get(
                        CONF_BATTERY_ALERT_AUTO_COMPLETE_ON_RECOVERY,
                        DEFAULT_BATTERY_ALERT_AUTO_COMPLETE_ON_RECOVERY,
                    ),
                ): BooleanSelector(),
                # v0.14: how many minutes of screen time one point invested
                # into a CONF_REWARD_SCREEN_TIME_INVESTABLE ("Handyzeit")
                # reward is worth - see ws_redeem_reward in storage.py.
                vol.Optional(
                    CONF_SCREEN_TIME_MINUTES_PER_POINT,
                    default=current.get(
                        CONF_SCREEN_TIME_MINUTES_PER_POINT,
                        DEFAULT_SCREEN_TIME_MINUTES_PER_POINT,
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=1, max=120, mode=NumberSelectorMode.BOX, unit_of_measurement="min"
                    )
                ),
                # v0.45: purely informational mirror of two values that live
                # in the household's own Handyzeit-Verwaltung blueprint
                # automation (blueprints/handyzeit_verwaltung.yaml) - "Erhöhung
                # pro Tick" (increment_minutes) and how many entries
                # "Automatische Plus-Uhrzeiten" (plus_times) has. Lets the card
                # estimate/explain each child's expected Handyzeit for today -
                # see CONF_SCREEN_TIME_TICK_MINUTES/CONF_SCREEN_TIME_TICKS_PER_DAY
                # in const.py. Leaving either at 0 (the default) disables the
                # estimate entirely rather than showing a guessed number that
                # doesn't match the blueprint's actual configured values.
                vol.Optional(
                    CONF_SCREEN_TIME_TICK_MINUTES,
                    default=current.get(
                        CONF_SCREEN_TIME_TICK_MINUTES, DEFAULT_SCREEN_TIME_TICK_MINUTES
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0, max=60, mode=NumberSelectorMode.BOX, unit_of_measurement="min"
                    )
                ),
                vol.Optional(
                    CONF_SCREEN_TIME_TICKS_PER_DAY,
                    default=current.get(
                        CONF_SCREEN_TIME_TICKS_PER_DAY, DEFAULT_SCREEN_TIME_TICKS_PER_DAY
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(min=0, max=100, mode=NumberSelectorMode.BOX)
                ),
                # v0.46: household-wide "malus considered active from" date -
                # see CONF_SCREEN_TIME_MALUS_START_DATE in const.py. Left
                # empty (no suggested_value/default forces a value, so the
                # field submits nothing at all when cleared - see
                # async_step_init above) the Handyzeit-Tick-Malus never
                # applies, same as before this option existed.
                vol.Optional(
                    CONF_SCREEN_TIME_MALUS_START_DATE,
                    description={
                        "suggested_value": current.get(CONF_SCREEN_TIME_MALUS_START_DATE)
                    },
                ): DateSelector(),
                # v0.29: weekly point goal backing each child's
                # "Wochenfortschritt" progress bar - points earned beyond
                # this within a calendar week become spendable, see
                # CONF_WEEKLY_PROGRESS_GOAL_POINTS in const.py. 0 (default)
                # disables the mechanic, keeping every earned point
                # immediately spendable as before this option existed.
                vol.Optional(
                    CONF_WEEKLY_PROGRESS_GOAL_POINTS,
                    default=current.get(
                        CONF_WEEKLY_PROGRESS_GOAL_POINTS,
                        DEFAULT_WEEKLY_PROGRESS_GOAL_POINTS,
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(min=0, max=1000, mode=NumberSelectorMode.BOX)
                ),
                # v0.36: "Meilensteinbonus" - replaces the old configurable-
                # threshold, points-based version (v0.30). Bonus coins (the
                # reward-shop currency, not points - see the "Rewards"
                # section in const.py) credited live, the moment a member's
                # current-week points cross the fixed 150%/200%
                # weekly-progress checkpoints (see PROGRESS_THRESHOLD_PERCENTS
                # in const.py and
                # FamilyTasksCoordinator._async_process_milestone_coin_bonus).
                # A tier is off exactly when its bonus is 0. Only takes
                # effect if the weekly goal above is > 0, since both
                # checkpoints are a percentage of it.
                vol.Optional(
                    CONF_MILESTONE_150_BONUS_COINS,
                    default=current.get(
                        CONF_MILESTONE_150_BONUS_COINS, DEFAULT_MILESTONE_150_BONUS_COINS
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(min=0, max=1000, mode=NumberSelectorMode.BOX)
                ),
                vol.Optional(
                    CONF_MILESTONE_200_BONUS_COINS,
                    default=current.get(
                        CONF_MILESTONE_200_BONUS_COINS, DEFAULT_MILESTONE_200_BONUS_COINS
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(min=0, max=1000, mode=NumberSelectorMode.BOX)
                ),
                # v0.36: "Streak-Bonus" - replaces the old single
                # configurable-threshold, points-based version (v0.32).
                # v0.63: simplified on explicit user request to a single tier
                # at the fixed 200% weekly-progress checkpoint, with two
                # independently configurable coin amounts for two fixed
                # milestones instead of one amount plus a configurable
                # required-weeks/doubling rule - the old 150% tier and
                # CONF_STREAK_BONUS_REQUIRED_WEEKS are both gone (see git
                # history for the v0.36-v0.54 evolution of this feature). See
                # CONF_STREAK_BONUS_2_WEEKS_COINS/CONF_STREAK_BONUS_3_WEEKS_COINS
                # in const.py and
                # FamilyTasksCoordinator._async_process_streak_coin_bonus.
                # Off exactly when both amounts are 0.
                vol.Optional(
                    CONF_STREAK_BONUS_2_WEEKS_COINS,
                    default=current.get(
                        CONF_STREAK_BONUS_2_WEEKS_COINS,
                        DEFAULT_STREAK_BONUS_2_WEEKS_COINS,
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(min=0, max=1000, mode=NumberSelectorMode.BOX)
                ),
                vol.Optional(
                    CONF_STREAK_BONUS_3_WEEKS_COINS,
                    default=current.get(
                        CONF_STREAK_BONUS_3_WEEKS_COINS,
                        DEFAULT_STREAK_BONUS_3_WEEKS_COINS,
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(min=0, max=1000, mode=NumberSelectorMode.BOX)
                ),
                # v0.52: "Wochensieger-Bonus" - extra bonus coins for the single
                # household member with the most points in a fully-elapsed
                # calendar week (absolute points, not relative to any
                # individual weekly goal - unlike the Meilenstein-/
                # Streak-Bonus above, this does not require a weekly goal to
                # be configured at all). No bonus is paid on a tie for first
                # place. See CONF_TOP_SCORER_BONUS_COINS in const.py and
                # FamilyTasksCoordinator._async_process_top_scorer_coin_bonus.
                # Off exactly when 0 (default), same convention as every
                # other bonus amount above.
                vol.Optional(
                    CONF_TOP_SCORER_BONUS_COINS,
                    default=current.get(
                        CONF_TOP_SCORER_BONUS_COINS, DEFAULT_TOP_SCORER_BONUS_COINS
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(min=0, max=1000, mode=NumberSelectorMode.BOX)
                ),
                # v0.32: only seeds VacationModeStateStore's initial value the
                # first time it loads with nothing on disk yet - the actual
                # on/off control after that is switch.FamilyTasksVacationModeSwitch,
                # not this option. See CONF_VACATION_MODE_DEFAULT in const.py.
                vol.Optional(
                    CONF_VACATION_MODE_DEFAULT,
                    default=current.get(CONF_VACATION_MODE_DEFAULT, DEFAULT_VACATION_MODE),
                ): BooleanSelector(),
            }
        )
        # v0.68: absolute-point thresholds - malus 1-4 right behind the weekly
        # goal, the two coin thresholds right before the coin bonuses
        # (vol.Schema keeps insertion order, which is the form order).
        malus_fields = [
            _threshold(key, value)
            for key, value in zip(
                (
                    CONF_MALUS_THRESHOLD_1_POINTS,
                    CONF_MALUS_THRESHOLD_2_POINTS,
                    CONF_MALUS_THRESHOLD_3_POINTS,
                    CONF_MALUS_THRESHOLD_4_POINTS,
                ),
                malus_now,
            )
        ]
        coin_fields = [
            _threshold(key, value)
            for key, value in zip(
                (CONF_COIN_THRESHOLD_1_POINTS, CONF_COIN_THRESHOLD_2_POINTS), coin_now
            )
        ]
        ordered: dict = {}
        for marker, selector in schema.schema.items():
            if marker.schema == CONF_MILESTONE_150_BONUS_COINS:
                ordered.update(coin_fields)
            ordered[marker] = selector
            if marker.schema == CONF_WEEKLY_PROGRESS_GOAL_POINTS:
                ordered.update(malus_fields)
        schema = vol.Schema(ordered)
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
