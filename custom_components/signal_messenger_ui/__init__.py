"""The Signal Messenger UI integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .api import SignalApiClient
from .config_flow import create_client
from .const import DOMAIN
from .services import async_setup_services

if TYPE_CHECKING:
    from .notify import SignalNotifyEntity

PLATFORMS: list[Platform] = [Platform.NOTIFY]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass
class SignalData:
    """Runtime data of a config entry."""

    client: SignalApiClient
    entities: dict[str, SignalNotifyEntity] = field(default_factory=dict)


type SignalConfigEntry = ConfigEntry[SignalData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration's actions."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: SignalConfigEntry) -> bool:
    """Set up a sender account from a config entry."""
    # No request here: the REST API may still be starting when HA boots.
    entry.runtime_data = SignalData(client=create_client(hass, dict(entry.data)))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: SignalConfigEntry) -> None:
    """Reload when recipients are added, changed or removed."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: SignalConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
