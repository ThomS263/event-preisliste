from __future__ import annotations

from datetime import timedelta

from homeassistant.const import CONF_ACCESS_TOKEN, CONF_URL, Platform
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AuthenticationError, EventPreislisteApi
from .const import DOMAIN, SCAN_INTERVAL_SECONDS

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR]


async def async_setup_entry(hass, entry):
    if not entry.data.get(CONF_ACCESS_TOKEN):
        raise ConfigEntryAuthFailed("Status token missing")
    api = EventPreislisteApi(
        async_get_clientsession(hass),
        entry.data[CONF_URL],
        entry.data[CONF_ACCESS_TOKEN],
    )

    async def update():
        try:
            return await api.status()
        except AuthenticationError as error:
            raise ConfigEntryAuthFailed(str(error)) from error
        except ConnectionError as error:
            raise UpdateFailed(str(error)) from error

    coordinator = DataUpdateCoordinator(
        hass,
        logger=__import__("logging").getLogger(__name__),
        name="Event-Preisliste",
        update_method=update,
        update_interval=timedelta(seconds=SCAN_INTERVAL_SECONDS),
    )
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass, entry):
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unloaded
