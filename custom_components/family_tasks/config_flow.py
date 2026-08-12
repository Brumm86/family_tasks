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
    CONF_BATTERY_WARNING_THRESHOLD,
    CONF_DEFAULT_ROTATION_STRATEGY,
    CONF_MILESTONE_1_BONUS_POINTS,
    CONF_MILESTONE_1_THRESHOLD_PERCENT,
    CONF_MILESTONE_2_BONUS_POINTS,
    CONF_MILESTONE_2_THRESHOLD_PERCENT,
    CONF_MILESTONE_BONUS_ENABLED,
    CONF_OVERDUE_AFTER_MINUTES,
    CONF_SCREEN_TIME_MINUTES_PER_POINT,
    CONF_WEEKLY_PROGRESS_GOAL_POINTS,
    DEFAULT_BATTERY_WARNING_THRESHOLD,
    DEFAULT_MILESTONE_1_BONUS_POINTS,
    DEFAULT_MILESTONE_1_THRESHOLD_PERCENT,
    DEFAULT_MILESTONE_2_BONUS_POINTS,
    DEFAULT_MILESTONE_2_THRESHOLD_PERCENT,
    DEFAULT_MILESTONE_BONUS_ENABLED,
    DEFAULT_OVERDUE_AFTER_MINUTES,
    DEFAULT_ROTATION_STRATEGY,
    DEFAULT_SCREEN_TIME_MINUTES_PER_POINT,
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
            # v0.30: threshold 2 must exceed threshold 1 - the Meilensteinbonus
            # awards each threshold independently as points_week crosses it
            # (see FamilyTasksCoordinator._async_process_milestone_bonus), so
            # a threshold 2 at or below threshold 1 would make it either
            # unreachable in a meaningful order or award both simultaneously
            # every time, neither of which matches "two distinct milestones".
            if (
                user_input[CONF_MILESTONE_2_THRESHOLD_PERCENT]
                <= user_input[CONF_MILESTONE_1_THRESHOLD_PERCENT]
            ):
                errors["base"] = "milestone_threshold_order"
            else:
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
                # v0.30: "Meilensteinbonus" - replaces the old weekly-winner
                # bonus. Whether/how many bonus points a member earns, live,
                # the moment they cross each of two progress thresholds
                # (percentages of the weekly goal just above) - see
                # FamilyTasksCoordinator._async_process_milestone_bonus. Only
                # takes effect if the weekly goal above is > 0, since both
                # thresholds are defined as a percentage of it.
                vol.Optional(
                    CONF_MILESTONE_BONUS_ENABLED,
                    default=current.get(
                        CONF_MILESTONE_BONUS_ENABLED, DEFAULT_MILESTONE_BONUS_ENABLED
                    ),
                ): BooleanSelector(),
                vol.Optional(
                    CONF_MILESTONE_1_THRESHOLD_PERCENT,
                    default=current.get(
                        CONF_MILESTONE_1_THRESHOLD_PERCENT,
                        DEFAULT_MILESTONE_1_THRESHOLD_PERCENT,
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=1, max=1000, mode=NumberSelectorMode.BOX, unit_of_measurement="%"
                    )
                ),
                vol.Optional(
                    CONF_MILESTONE_1_BONUS_POINTS,
                    default=current.get(
                        CONF_MILESTONE_1_BONUS_POINTS, DEFAULT_MILESTONE_1_BONUS_POINTS
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(min=0, max=1000, mode=NumberSelectorMode.BOX)
                ),
                vol.Optional(
                    CONF_MILESTONE_2_THRESHOLD_PERCENT,
                    default=current.get(
                        CONF_MILESTONE_2_THRESHOLD_PERCENT,
                        DEFAULT_MILESTONE_2_THRESHOLD_PERCENT,
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=1, max=1000, mode=NumberSelectorMode.BOX, unit_of_measurement="%"
                    )
                ),
                vol.Optional(
                    CONF_MILESTONE_2_BONUS_POINTS,
                    default=current.get(
                        CONF_MILESTONE_2_BONUS_POINTS, DEFAULT_MILESTONE_2_BONUS_POINTS
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(min=0, max=1000, mode=NumberSelectorMode.BOX)
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
