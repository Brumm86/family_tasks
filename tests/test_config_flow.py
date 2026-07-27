"""Tests for the Family Tasks config flow."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

from custom_components.family_tasks.const import DOMAIN


async def test_user_flow_creates_entry(hass) -> None:
    """Submitting the (single) setup step creates a config entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Unsere Familie"}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Unsere Familie"
    assert result["data"] == {}


async def test_only_a_single_instance_is_allowed(hass, init_integration) -> None:
    """A second setup attempt must be aborted; Family Tasks is a singleton."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.ABORT
