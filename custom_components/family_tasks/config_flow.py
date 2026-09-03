"""Config flow for the Family Tasks integration."""

from __future__ import annotations

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
    CONF_MILESTONE_150_BONUS_COINS,
    CONF_MILESTONE_200_BONUS_COINS,
    CONF_OVERDUE_AFTER_MINUTES,
    CONF_SCREEN_TIME_MINUTES_PER_POINT,
    CONF_SCREEN_TIME_TICK_MINUTES,
    CONF_SCREEN_TIME_TICKS_PER_DAY,
    CONF_STREAK_150_BONUS_COINS,
    CONF_STREAK_200_BONUS_COINS,
    CONF_STREAK_BONUS_REQUIRED_WEEKS,
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
    DEFAULT_STREAK_150_BONUS_COINS,
    DEFAULT_STREAK_200_BONUS_COINS,
    DEFAULT_STREAK_BONUS_REQUIRED_WEEKS,
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
            # v0.36: the old threshold-2-must-exceed-threshold-1 validation
            # is gone along with the configurable thresholds themselves - the
            # Meilenstein-/Streak-Bonus checkpoints are now the fixed 150%/
            # 200% weekly-progress bands (PROGRESS_THRESHOLD_PERCENTS in
            # const.py), so there is no ordering left for a household to get
            # wrong here.
            return self.async_create_entry(data=user_input)

        # On a validation error, re-show the form pre-filled with what the
        # user just submitted (not the previously saved options) so a typo'd
        # field doesn't reset every other field back to its old value too.
        current = user_input if user_input is not None else self.config_entry.options
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
                # configurable-threshold, points-based version (v0.32). Bonus
                # coins for *maintaining* a fixed checkpoint (150% or 200% of
                # the weekly goal) for more than streak_bonus_required_weeks
                # consecutive calendar weeks - one bonus amount per tier, so
                # a household can reward the two checkpoints differently. See
                # CONF_STREAK_150_BONUS_COINS/CONF_STREAK_200_BONUS_COINS in
                # const.py and
                # FamilyTasksCoordinator._async_process_streak_coin_bonus. A
                # tier is off exactly when its bonus is 0.
                vol.Optional(
                    CONF_STREAK_BONUS_REQUIRED_WEEKS,
                    default=current.get(
                        CONF_STREAK_BONUS_REQUIRED_WEEKS,
                        DEFAULT_STREAK_BONUS_REQUIRED_WEEKS,
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(min=1, max=52, mode=NumberSelectorMode.BOX)
                ),
                vol.Optional(
                    CONF_STREAK_150_BONUS_COINS,
                    default=current.get(
                        CONF_STREAK_150_BONUS_COINS, DEFAULT_STREAK_150_BONUS_COINS
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(min=0, max=1000, mode=NumberSelectorMode.BOX)
                ),
                vol.Optional(
                    CONF_STREAK_200_BONUS_COINS,
                    default=current.get(
                        CONF_STREAK_200_BONUS_COINS, DEFAULT_STREAK_200_BONUS_COINS
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
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
