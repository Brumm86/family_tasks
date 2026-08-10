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
    CONF_OVERDUE_AFTER_MINUTES,
    CONF_SCREEN_TIME_MINUTES_PER_POINT,
    CONF_WEEKLY_PROGRESS_GOAL_POINTS,
    CONF_WEEKLY_WINNER_BONUS_ENABLED,
    CONF_WEEKLY_WINNER_BONUS_POINTS,
    DEFAULT_BATTERY_WARNING_THRESHOLD,
    DEFAULT_OVERDUE_AFTER_MINUTES,
    DEFAULT_ROTATION_STRATEGY,
    DEFAULT_SCREEN_TIME_MINUTES_PER_POINT,
    DEFAULT_WEEKLY_PROGRESS_GOAL_POINTS,
    DEFAULT_WEEKLY_WINNER_BONUS_ENABLED,
    DEFAULT_WEEKLY_WINNER_BONUS_POINTS,
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
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_OVERDUE_AFTER_MINUTES,
                    default=options.get(
                        CONF_OVERDUE_AFTER_MINUTES, DEFAULT_OVERDUE_AFTER_MINUTES
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(min=0, max=1440, mode=NumberSelectorMode.BOX)
                ),
                vol.Optional(
                    CONF_DEFAULT_ROTATION_STRATEGY,
                    default=options.get(
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
                    default=options.get(
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
                    default=options.get(
                        CONF_SCREEN_TIME_MINUTES_PER_POINT,
                        DEFAULT_SCREEN_TIME_MINUTES_PER_POINT,
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=1, max=120, mode=NumberSelectorMode.BOX, unit_of_measurement="min"
                    )
                ),
                # v0.14: whether/how many bonus points the current week's
                # point leader(s) get, credited once the week ends - see
                # FamilyTasksCoordinator._async_process_weekly_winner_bonus.
                vol.Optional(
                    CONF_WEEKLY_WINNER_BONUS_ENABLED,
                    default=options.get(
                        CONF_WEEKLY_WINNER_BONUS_ENABLED,
                        DEFAULT_WEEKLY_WINNER_BONUS_ENABLED,
                    ),
                ): BooleanSelector(),
                vol.Optional(
                    CONF_WEEKLY_WINNER_BONUS_POINTS,
                    default=options.get(
                        CONF_WEEKLY_WINNER_BONUS_POINTS,
                        DEFAULT_WEEKLY_WINNER_BONUS_POINTS,
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(min=0, max=1000, mode=NumberSelectorMode.BOX)
                ),
                # v0.29: weekly point goal backing each child's
                # "Wochenfortschritt" progress bar - points earned beyond
                # this within a calendar week become spendable, see
                # CONF_WEEKLY_PROGRESS_GOAL_POINTS in const.py. 0 (default)
                # disables the mechanic, keeping every earned point
                # immediately spendable as before this option existed.
                vol.Optional(
                    CONF_WEEKLY_PROGRESS_GOAL_POINTS,
                    default=options.get(
                        CONF_WEEKLY_PROGRESS_GOAL_POINTS,
                        DEFAULT_WEEKLY_PROGRESS_GOAL_POINTS,
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(min=0, max=1000, mode=NumberSelectorMode.BOX)
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
