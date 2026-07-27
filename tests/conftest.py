"""Global fixtures for the Family Tasks integration tests."""

from __future__ import annotations

import pytest

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.family_tasks.const import DOMAIN

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom_components/ discovery for every test in this suite."""
    yield


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a (not yet added) Family Tasks config entry."""
    return MockConfigEntry(domain=DOMAIN, title="Family Tasks", data={}, options={})


@pytest.fixture
async def init_integration(hass, mock_config_entry: MockConfigEntry) -> MockConfigEntry:
    """Set up the Family Tasks integration for a test and return its entry."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    return mock_config_entry
