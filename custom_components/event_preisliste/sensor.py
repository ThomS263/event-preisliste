from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

SENSORS = {
    "events": ("Events gesamt", "mdi:calendar-multiple"),
    "published": ("Veröffentlichte Events", "mdi:calendar-check"),
    "items": ("Artikel", "mdi:currency-eur"),
    "stands": ("Stände", "mdi:storefront"),
    "markers": ("Planpunkte", "mdi:map-marker-multiple"),
    "sold_out": ("Ausverkaufte Artikel", "mdi:cart-off"),
    "version": ("Version", "mdi:information-outline"),
}


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        EventStat(coordinator, entry, key, name, icon)
        for key, (name, icon) in SENSORS.items()
    )


class EventStat(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry, key, name, icon):
        super().__init__(coordinator)
        self.key = key
        self._attr_name = name
        self._attr_icon = icon
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Event-Preisliste",
            "manufacturer": "ThomS263",
            "configuration_url": entry.data["url"],
        }

    @property
    def native_value(self):
        return self.coordinator.data.get(self.key)
