import logging
import uuid

import voluptuous as vol
from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import ATTR_ATTRIBUTION, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from . import AlertsDataUpdateCoordinator
from .const import (
    ATTRIBUTION,
    CONF_GPS_LOC,
    CONF_INTERVAL,
    CONF_TIMEOUT,
    CONF_TRACKER,
    CONF_ZONE_ID,
    COORDINATOR,
    DEFAULT_ICON,
    DEFAULT_INTERVAL,
    DEFAULT_NAME,
    DEFAULT_TIMEOUT,
    DOMAIN,
)

# ---------------------------------------------------------
# API Documentation
# ---------------------------------------------------------
# https://www.weather.gov/documentation/services-web-api
# https://forecast-v3.weather.gov/documentation
# ---------------------------------------------------------

_LOGGER = logging.getLogger(__name__)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_ZONE_ID): cv.string,
        vol.Optional(CONF_GPS_LOC): cv.string,
        vol.Optional(CONF_TRACKER): cv.string,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_INTERVAL, default=DEFAULT_INTERVAL): int,
        vol.Optional(CONF_TIMEOUT, default=DEFAULT_TIMEOUT): int,
    }
)


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Configuration from yaml"""
    if DOMAIN not in hass.data.keys():
        hass.data.setdefault(DOMAIN, {})
        if CONF_ZONE_ID in config:
            config.entry_id = slugify(f"{config.get(CONF_ZONE_ID)}")
        elif CONF_GPS_LOC in config:
            config.entry_id = slugify(f"{config.get(CONF_GPS_LOC)}")
        elif CONF_TRACKER in config:
            config.entry_id = slugify(f"{config.get(CONF_TRACKER)}")            
        else:
            raise ValueError("GPS, Zone or Device Tracker needs to be configured.")
        config.data = config
    else:
        if CONF_ZONE_ID in config:
            config.entry_id = slugify(f"{config.get(CONF_ZONE_ID)}")
        elif CONF_GPS_LOC in config:
            config.entry_id = slugify(f"{config.get(CONF_GPS_LOC)}")
        elif CONF_TRACKER in config:
            config.entry_id = slugify(f"{config.get(CONF_TRACKER)}")
        else:
            raise ValueError("GPS, Zone or Device Tracker needs to be configured.")
        config.data = config

    # Setup the data coordinator
    coordinator = AlertsDataUpdateCoordinator(
        hass,
        config,
        config[CONF_TIMEOUT],
        config[CONF_INTERVAL],
    )

    # Fetch initial data so we have data when entities subscribe
    await coordinator.async_refresh()

    hass.data[DOMAIN][config.entry_id] = {
        COORDINATOR: coordinator,
    }
    async_add_entities([NWSAlertSensor(hass, config)], True)


async def async_setup_entry(hass, entry, async_add_entities):
    """Setup the sensor platform."""
    async_add_entities([NWSAlertSensor(hass, entry)], True)


class NWSAlertSensor(CoordinatorEntity):
    """Representation of a Sensor."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(hass.data[DOMAIN][entry.entry_id][COORDINATOR])
        self._config = entry
        self._name = entry.data[CONF_NAME]
        self._icon = DEFAULT_ICON
        self.coordinator = hass.data[DOMAIN][entry.entry_id][COORDINATOR]

    async def async_update(self):
        """Run update."""
        alerts = []

        try:
            async with async_timeout.timeout(10):
                response = await self.session.get(URL.format(self.feedid))
                if response.status != 200:
                    self._state = "unavailable"
                    _LOGGER.warning(
                        "[%s] Possible API outage. Currently unable to download from weather.gov - HTTP status code %s",
                        self.feedid,
                        response.status
                    )
                else:
                    data = await response.json()

                    if data.get("features") is not None:
                        for alert in data["features"]:
                            if alert.get("properties") is not None:
                                properties = alert["properties"]
                                if properties["ends"] is None:
                                    properties["endsExpires"] = properties.get("expires", "null")
                                else:
                                    properties["endsExpires"] = properties.get("ends", "null")
                                alerts.append(
                                    {
                                        "area": properties.get("areaDesc", "null"),
                                        "certainty": properties.get("certainty", "null"),
                                        "description": properties.get("description", "null"),
                                        "ends": properties.get("ends", "null"),
                                        "event": properties.get("event", "null"),
                                        "instruction": properties.get("instruction", "null"),
                                        "response": properties.get("response", "null"),
                                        "sent": properties.get("sent", "null"),
                                        "severity": properties.get("severity", "null"),
                                        "title": properties.get("headline", "null").split(" by ")[0],
                                        "urgency": properties.get("urgency", "null"),
                                        "NWSheadline": properties["parameters"].get("NWSheadline", "null"),
                                        "hailSize": properties["parameters"].get("hailSize", "null"),
                                        "windGust": properties["parameters"].get("windGust", "null"),
                                        "waterspoutDetection": properties["parameters"].get("waterspoutDetection", "null"),
                                        "effective": properties.get("effective", "null"),
                                        "expires": properties.get("expires", "null"),
                                        "endsExpires": properties.get("endsExpires", "null"),
                                        "onset": properties.get("onset", "null"),
                                        "status": properties.get("status", "null"),
                                        "messageType": properties.get("messageType", "null"),
                                        "category": properties.get("category", "null"),
                                        "sender": properties.get("sender", "null"),
                                        "senderName": properties.get("senderName", "null"),
                                        "id": properties.get("id", "null"),
                                        "zoneid": self.feedid,
                                    }
                                )
                    alerts.sort(key=lambda x: (x['id']), reverse=True)

                    for sorted_alert in alerts:
                        _LOGGER.debug(
                            "[%s] Sorted alert ID: %s",
                            self.feedid,
                            sorted_alert.get("id", "null")
                        )

                    self._state = len(alerts)
                    self._attr = {
                        "alerts": alerts,
                        "integration": "weatheralerts",
                        "state": self.zone_state,
                        "zone": self.feedid,
                    }
        except Exception:  # pylint: disable=broad-except
            self.exception = sys.exc_info()[0].__name__
            connected = False
        else:
            connected = True
        finally:
            # Handle connection messages here.
            if self.connected:
                if not connected:
                    self._state = "unavailable"
                    _LOGGER.warning(
                        "[%s] Could not update the sensor (%s)",
                        self.feedid,
                        self.exception,
                    )

            elif not self.connected:
                if connected:
                    _LOGGER.info("[%s] Update of the sensor completed", self.feedid)
                else:
                    self._state = "unavailable"
                    _LOGGER.warning(
                        "[%s] Still no update (%s)", self.feedid, self.exception
                    )

            self.connected = connected

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def unique_id(self):
        """
        Return a unique, Home Assistant friendly identifier for this entity.
        """
        return f"{slugify(self._name)}_{self._config.entry_id}"

    @property
    def state(self):
        """Return the state of the sensor."""
        if self.coordinator.data is None:
            return None
        elif "state" in self.coordinator.data.keys():
            return self.coordinator.data["state"]
        return None
        
    @property
    def unit_of_measurement(self):
        """Return the unit_of_measurement."""
        return "Alerts"

    @property
    def icon(self):
        """Return the icon to use in the frontend, if any."""
        return self._icon

    @property
    def extra_state_attributes(self):
        """Return attributes."""
        return self._attr

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success

    @property
    def device_info(self) -> DeviceInfo:
        """Return device registry information."""
        return DeviceInfo(
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, self._config.entry_id)},
            manufacturer="NWS",
            name="NWS Alerts",
        )
