"""Bulgarian power outages for a configured place or client number."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN
from .coordinator import OutageConfigEntry, OutageCoordinator, format_issue_id

PLATFORMS = [Platform.BINARY_SENSOR, Platform.CALENDAR, Platform.EVENT, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: OutageConfigEntry) -> bool:
    coordinator = OutageCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: OutageConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: OutageConfigEntry) -> None:
    ir.async_delete_issue(hass, DOMAIN, format_issue_id(entry))
