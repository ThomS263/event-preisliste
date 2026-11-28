from homeassistant.components.diagnostics import async_redact_data

from .const import DOMAIN


async def async_get_config_entry_diagnostics(hass, entry):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    return async_redact_data(
        {
            "server": entry.data.get("url"),
            "available": coordinator.last_update_success,
            "status": coordinator.data,
        },
        {"server"},
    )
