"""Shared helpers for platforms with dynamically created/removed entities."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN


@callback
def async_prune_stale_entities(
    hass: HomeAssistant,
    entry: ConfigEntry,
    *,
    platform: str,
    valid_unique_ids: set[str],
) -> None:
    """Remove registered entities no longer backed by a task/member.

    Called after every coordinator refresh. Tasks and members are managed as
    storage collection items and can be deleted through the frontend at any
    time; when that happens the corresponding sensor/button entities should
    disappear instead of lingering as permanently unavailable.
    """
    registry = er.async_get(hass)
    for entity_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if (
            entity_entry.domain == platform
            and entity_entry.platform == DOMAIN
            and entity_entry.unique_id not in valid_unique_ids
        ):
            registry.async_remove(entity_entry.entity_id)
