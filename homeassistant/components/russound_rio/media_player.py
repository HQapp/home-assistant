"""Support for Russound multizone controllers using RIO Protocol."""
import logging

import voluptuous as vol

from homeassistant.components.media_player import (
    MediaPlayerDevice, PLATFORM_SCHEMA)
from homeassistant.components.media_player.const import (
    MEDIA_TYPE_MUSIC, SUPPORT_SELECT_SOURCE, SUPPORT_TURN_OFF,
    SUPPORT_TURN_ON, SUPPORT_VOLUME_MUTE, SUPPORT_VOLUME_SET)
from homeassistant.const import (
    CONF_HOST, CONF_NAME, CONF_PORT, EVENT_HOMEASSISTANT_STOP, STATE_OFF,
    STATE_ON)
from homeassistant.core import callback
import homeassistant.helpers.config_validation as cv

_LOGGER = logging.getLogger(__name__)

SUPPORT_RUSSOUND = SUPPORT_VOLUME_MUTE | SUPPORT_VOLUME_SET | \
                   SUPPORT_TURN_ON | SUPPORT_TURN_OFF | SUPPORT_SELECT_SOURCE

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_HOST): cv.string,
    vol.Required(CONF_NAME): cv.string,
    vol.Optional(CONF_PORT, default=9621): cv.port,
})


async def async_setup_platform(
        hass, config, async_add_entities, discovery_info=None):
    """Set up the Russound RIO platform."""
    from russound_rio import Russound

    host = config.get(CONF_HOST)
    port = config.get(CONF_PORT)

    russ = Russound(hass.loop, host, port)

    await russ.connect()

    # Discover sources and zones
    sources = await russ.enumerate_sources()
    valid_zones = await russ.enumerate_zones()

    devices = []
    for zone_id, name in valid_zones:
        await russ.watch_zone(zone_id)
        dev = RussoundZoneDevice(russ, zone_id, name, sources)
        devices.append(dev)

    @callback
    def on_stop(event):
        """Shutdown cleanly when hass stops."""
        hass.loop.create_task(russ.close())

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, on_stop)

    async_add_entities(devices)


class RussoundZoneDevice(MediaPlayerDevice):
    """Representation of a Russound Zone."""

    def __init__(self, russ, zone_id, name, sources):
        """Initialize the zone device."""
        super().__init__()
        self._name = name
        self._russ = russ
        self._zone_id = zone_id
        self._sources = sources

    def _zone_var(self, name, default=None):
        return self._russ.get_cached_zone_variable(
            self._zone_id, name, default)

    def _source_var(self, name, default=None):
        current = int(self._zone_var('currentsource', 0))
        if current:
            return self._russ.get_cached_source_variable(
                current, name, default)
        return default

    def _source_na_var(self, name):
        """Will replace invalid values with None."""
        current = int(self._zone_var('currentsource', 0))
        if current:
            value = self._russ.get_cached_source_variable(
                current, name, None)
            if value in (None, "", "------"):
                return None
            return value
        return None

    def _zone_callback_handler(self, zone_id, *args):
        if zone_id == self._zone_id:
            self.schedule_update_ha_state()

    def _source_callback_handler(self, source_id, *args):
        current = int(self._zone_var('currentsource', 0))
        if source_id == current:
            self.schedule_update_ha_state()

    async def async_added_to_hass(self):
        """Register callback handlers."""
        self._russ.add_zone_callback(self._zone_callback_handler)
        self._russ.add_source_callback(self._source_callback_handler)

    @property
    def should_poll(self):
        """No polling needed."""
        return False

    @property
    def name(self):
        """Return the name of the zone."""
        return self._zone_var('name', self._name)

    @property
    def state(self):
        """Return the state of the device."""
        status = self._zone_var('status', "OFF")
        if status == 'ON':
            return STATE_ON
        if status == 'OFF':
            return STATE_OFF

    @property
    def supported_features(self):
        """Flag media player features that are supported."""
        return SUPPORT_RUSSOUND

    @property
    def source(self):
        """Get the currently selected source."""
        return self._source_na_var('name')

    @property
    def source_list(self):
        """Return a list of available input sources."""
        return [x[1] for x in self._sources]

    @property
    def media_content_type(self):
        """Content type of current playing media."""
        return MEDIA_TYPE_MUSIC

    @property
    def media_title(self):
        """Title of current playing media."""
        return self._source_na_var('songname')

    @property
    def media_artist(self):
        """Artist of current playing media, music track only."""
        return self._source_na_var('artistname')

    @property
    def media_album_name(self):
        """Album name of current playing media, music track only."""
        return self._source_na_var('albumname')

    @property
    def media_image_url(self):
        """Image url of current playing media."""
        return self._source_na_var('coverarturl')

    @property
    def volume_level(self):
        """Volume level of the media player (0..1).

        Value is returned based on a range (0..50).
        Therefore float divide by 50 to get to the required range.
        """
        return float(self._zone_var('volume', 0)) / 50.0

    def async_turn_off(self):
        """Turn off the zone."""
        return self._russ.send_zone_event(self._zone_id, 'ZoneOff')

    def async_turn_on(self):
        """Turn on the zone."""
        return self._russ.send_zone_event(self._zone_id, 'ZoneOn')

    def async_set_volume_level(self, volume):
        """Set the volume level."""
        rvol = int(volume * 50.0)
        return self._russ.send_zone_event(
            self._zone_id, 'KeyPress', 'Volume', rvol)

    def async_select_source(self, source):
        """Select the source input for this zone."""
        for source_id, name in self._sources:
            if name.lower() != source.lower():
                continue
            return self._russ.send_zone_event(
                self._zone_id, 'SelectSource', source_id)