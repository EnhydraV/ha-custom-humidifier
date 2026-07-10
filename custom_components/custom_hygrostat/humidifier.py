"""Custom dehumidifier-only hygrostat with on/off actions and boost timer."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.components.humidifier import (
    HumidifierDeviceClass,
    HumidifierEntity,
    HumidifierEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    EVENT_HOMEASSISTANT_START,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import CoreState, HomeAssistant, callback
from homeassistant.exceptions import TemplateError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import (
    TrackTemplate,
    async_call_later,
    async_track_state_change_event,
    async_track_template_result,
)
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.script import Script
from homeassistant.helpers.template import Template, result_as_boolean
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    CONF_SENSOR,
    CONF_ACTION_ON,
    CONF_ACTION_OFF,
    CONF_MIN_HUMIDITY,
    CONF_MAX_HUMIDITY,
    CONF_TARGET_HUMIDITY,
    CONF_TARGET_ENTITY,
    CONF_DRY_TOLERANCE,
    CONF_WET_TOLERANCE,
    CONF_MIN_CYCLE_DURATION,
    CONF_BOOST_DURATION,
    CONF_ENABLE_TEMPLATE,
    CONF_ERROR_TEMPLATE,
    DEFAULT_TOLERANCE,
    DEFAULT_MIN_HUMIDITY,
    DEFAULT_MAX_HUMIDITY,
    DEFAULT_TARGET_HUMIDITY,
    DEFAULT_BOOST_MINUTES,
    DEFAULT_MIN_CYCLE_MINUTES,
)

_LOGGER = logging.getLogger(__name__)

CONF_NAME = "name"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the hygrostat from a config entry."""
    cfg = {**entry.data, **entry.options}

    name = cfg.get(CONF_NAME, entry.title)
    action_on = Script(hass, cfg[CONF_ACTION_ON], name, DOMAIN)
    action_off = Script(hass, cfg[CONF_ACTION_OFF], name, DOMAIN)

    # Templates vides ou absents = hygrostat toujours autorisé
    enable_template = None
    if tpl := cfg.get(CONF_ENABLE_TEMPLATE):
        enable_template = Template(tpl, hass)
    error_template = None
    if tpl := cfg.get(CONF_ERROR_TEMPLATE):
        error_template = Template(tpl, hass)

    async_add_entities(
        [
            CustomHygrostat(
                unique_id=entry.entry_id,
                name=name,
                sensor_entity_id=cfg[CONF_SENSOR],
                action_on=action_on,
                action_off=action_off,
                min_humidity=cfg.get(CONF_MIN_HUMIDITY, DEFAULT_MIN_HUMIDITY),
                max_humidity=cfg.get(CONF_MAX_HUMIDITY, DEFAULT_MAX_HUMIDITY),
                target_humidity=cfg.get(CONF_TARGET_HUMIDITY, DEFAULT_TARGET_HUMIDITY),
                target_entity_id=cfg.get(CONF_TARGET_ENTITY),
                dry_tolerance=cfg.get(CONF_DRY_TOLERANCE, DEFAULT_TOLERANCE),
                wet_tolerance=cfg.get(CONF_WET_TOLERANCE, DEFAULT_TOLERANCE),
                min_cycle_minutes=cfg.get(CONF_MIN_CYCLE_DURATION, DEFAULT_MIN_CYCLE_MINUTES),
                boost_minutes=cfg.get(CONF_BOOST_DURATION, DEFAULT_BOOST_MINUTES),
                enable_template=enable_template,
                error_template=error_template,
            )
        ]
    )


class CustomHygrostat(HumidifierEntity, RestoreEntity):
    """Dehumidifier-only hygrostat using on/off actions + boost timer."""

    _attr_should_poll = False
    _attr_device_class = HumidifierDeviceClass.DEHUMIDIFIER
    _attr_supported_features = HumidifierEntityFeature.MODES
    _attr_has_entity_name = False

    MODE_NORMAL = "normal"
    MODE_BOOST = "boost"

    def __init__(
        self,
        unique_id,
        name,
        sensor_entity_id,
        action_on,
        action_off,
        min_humidity,
        max_humidity,
        target_humidity,
        target_entity_id,
        dry_tolerance,
        wet_tolerance,
        min_cycle_minutes,
        boost_minutes,
        enable_template,
        error_template,
    ):
        self._attr_unique_id = unique_id
        self._attr_name = name
        self._sensor_entity_id = sensor_entity_id
        self._action_on = action_on
        self._action_off = action_off
        self._attr_min_humidity = min_humidity
        self._attr_max_humidity = max_humidity
        self._target_humidity = target_humidity
        self._target_entity_id = target_entity_id
        self._dry_tolerance = dry_tolerance
        self._wet_tolerance = wet_tolerance
        self._min_cycle_duration = timedelta(minutes=min_cycle_minutes)
        self._boost_duration = timedelta(minutes=boost_minutes)

        self._attr_available_modes = [self.MODE_NORMAL, self.MODE_BOOST]
        self._attr_mode = self.MODE_NORMAL

        self._state = False
        self._active = False
        self._cur_humidity = None
        self._boost_remove = None
        self._last_switched = None
        self._enable_template = enable_template
        self._error_template = error_template
        self._enable_ok = True
        self._error = False

    async def async_added_to_hass(self):
        await super().async_added_to_hass()

        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [self._sensor_entity_id], self._async_sensor_changed
            )
        )

        if self._target_entity_id:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, [self._target_entity_id], self._async_target_changed
                )
            )

        track_templates = [
            TrackTemplate(tpl, None)
            for tpl in (self._enable_template, self._error_template)
            if tpl is not None
        ]
        if track_templates:
            tpl_info = async_track_template_result(
                self.hass, track_templates, self._async_templates_changed
            )
            self.async_on_remove(tpl_info.async_remove)
            tpl_info.async_refresh()

        if (old_state := await self.async_get_last_state()) is not None:
            self._state = old_state.state == "on"
            # L'entité de consigne, si configurée, prime sur la valeur restaurée
            if (
                (h := old_state.attributes.get("humidity")) is not None
                and not self._target_entity_id
            ):
                self._target_humidity = h
            if old_state.attributes.get("mode") in self._attr_available_modes:
                self._attr_mode = old_state.attributes["mode"]

        @callback
        def _async_startup(*_):
            sensor_state = self.hass.states.get(self._sensor_entity_id)
            if sensor_state and sensor_state.state not in (
                STATE_UNAVAILABLE,
                STATE_UNKNOWN,
            ):
                self._update_humidity(sensor_state.state)
            if self._target_entity_id:
                target_state = self.hass.states.get(self._target_entity_id)
                if target_state and target_state.state not in (
                    STATE_UNAVAILABLE,
                    STATE_UNKNOWN,
                ):
                    self._update_target(target_state.state)
            self.hass.async_create_task(self._async_control(force=True))
            self.async_write_ha_state()

        if self.hass.state == CoreState.running:
            _async_startup()
        else:
            self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_START, _async_startup)

    @property
    def is_on(self):
        return self._state

    @property
    def icon(self):
        if not self._state:
            return "mdi:air-humidifier-off"
        if self._error:
            return "mdi:water-alert"
        if not self._enable_ok:
            return "mdi:water-off"
        if self._attr_mode == self.MODE_BOOST:
            return "mdi:rocket-launch"
        if self._active:
            return "mdi:air-humidifier"
        # Régulation en veille : appareil arrêté, humidité sous le seuil
        return "mdi:water-percent"

    @property
    def target_humidity(self):
        return self._target_humidity

    @property
    def extra_state_attributes(self):
        return {
            "device_active": self._active,
            "current_humidity": self._cur_humidity,
            "boost_active": self._attr_mode == self.MODE_BOOST,
            "enabled": self._enabled,
            "error_active": self._error,
        }

    async def async_turn_on(self, **kwargs):
        self._state = True
        await self._async_control(force=True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        self._cancel_boost()
        self._attr_mode = self.MODE_NORMAL
        self._state = False
        await self._async_device_turn_off()
        self.async_write_ha_state()

    async def async_set_humidity(self, humidity):
        if self._target_entity_id:
            domain = self._target_entity_id.split(".")[0]
            if domain in ("input_number", "number"):
                # La nouvelle valeur reviendra via le suivi d'état de l'entité
                await self.hass.services.async_call(
                    domain,
                    "set_value",
                    {"entity_id": self._target_entity_id, "value": humidity},
                    blocking=True,
                    context=self._context,
                )
            else:
                _LOGGER.warning(
                    "Consigne pilotée par %s (lecture seule) : réglage ignoré",
                    self._target_entity_id,
                )
            return
        self._target_humidity = humidity
        await self._async_control(force=True)
        self.async_write_ha_state()

    async def async_set_mode(self, mode):
        if mode not in self._attr_available_modes:
            return
        if mode == self.MODE_BOOST:
            await self._async_start_boost()
        else:
            self._cancel_boost()
            self._attr_mode = self.MODE_NORMAL
            await self._async_control(force=True)
        self.async_write_ha_state()

    # ----- Conditions d'activation et d'erreur (templates) -----

    @property
    def _enabled(self):
        # Autorisé uniquement si activation true ET erreur false
        return self._enable_ok and not self._error

    @callback
    def _async_templates_changed(self, event, updates):
        was_enabled = self._enabled
        for update in updates:
            result = update.result
            if isinstance(result, TemplateError):
                # En erreur de rendu, on conserve le dernier état connu
                _LOGGER.warning("Template en erreur : %s", result)
                continue
            if update.template is self._enable_template:
                self._enable_ok = result_as_boolean(result)
            elif update.template is self._error_template:
                self._error = result_as_boolean(result)
        if self._enabled == was_enabled:
            # L'autorisation combinée n'a pas bougé, mais l'icône
            # ou les attributs peuvent avoir changé
            self.async_write_ha_state()
            return
        if self._enabled:
            self.hass.async_create_task(self._async_resume())
        else:
            self.hass.async_create_task(self._async_interlock_off())

    async def _async_resume(self):
        await self._async_control(force=True)
        self.async_write_ha_state()

    async def _async_interlock_off(self):
        # Coupure prioritaire : annule aussi un boost en cours
        self._cancel_boost()
        self._attr_mode = self.MODE_NORMAL
        await self._async_device_turn_off()
        self.async_write_ha_state()

    # ----- Boost (marche forcée temporisée) -----

    async def _async_start_boost(self):
        if not self._enabled:
            _LOGGER.warning("Boost refusé : hygrostat verrouillé (activation ou erreur)")
            return
        if not self._state:
            self._state = True
        self._cancel_boost()
        self._attr_mode = self.MODE_BOOST
        await self._async_device_turn_on(bypass_cycle=True)

        @callback
        def _boost_finished(_now):
            self._boost_remove = None
            self.hass.async_create_task(self._async_end_boost())

        self._boost_remove = async_call_later(
            self.hass, self._boost_duration.total_seconds(), _boost_finished
        )

    async def _async_end_boost(self):
        self._attr_mode = self.MODE_NORMAL
        await self._async_control(force=True)
        self.async_write_ha_state()

    def _cancel_boost(self):
        if self._boost_remove is not None:
            self._boost_remove()
            self._boost_remove = None

    # ----- Entité de consigne -----

    @callback
    def _async_target_changed(self, event):
        new_state = event.data.get("new_state")
        if new_state is None or new_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return
        self._update_target(new_state.state)
        self.hass.async_create_task(self._async_control())
        self.async_write_ha_state()

    @callback
    def _update_target(self, state):
        try:
            value = float(state)
        except (ValueError, TypeError):
            _LOGGER.warning("Consigne illisible : %s", state)
            return
        self._target_humidity = min(
            max(value, self._attr_min_humidity), self._attr_max_humidity
        )

    # ----- Capteur -----

    @callback
    def _async_sensor_changed(self, event):
        new_state = event.data.get("new_state")
        if new_state is None or new_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return
        self._update_humidity(new_state.state)
        self.hass.async_create_task(self._async_control())
        self.async_write_ha_state()

    @callback
    def _update_humidity(self, state):
        try:
            self._cur_humidity = float(state)
        except (ValueError, TypeError):
            _LOGGER.warning("Humidité illisible : %s", state)
            self._cur_humidity = None

    # ----- Régulation (déshumidificateur uniquement) -----

    async def _async_control(self, force=False):
        if not self._enabled:
            return
        if self._attr_mode == self.MODE_BOOST:
            return
        if not self._state or self._cur_humidity is None or self._target_humidity is None:
            return

        if not force and self._min_cycle_duration and self._last_switched:
            elapsed = dt_util.utcnow() - self._last_switched
            if elapsed < self._min_cycle_duration:
                return

        too_humid = self._cur_humidity >= self._target_humidity + self._wet_tolerance
        too_dry = self._cur_humidity <= self._target_humidity - self._dry_tolerance

        if self._active:
            if too_dry:
                await self._async_device_turn_off()
        else:
            if too_humid:
                await self._async_device_turn_on()

    async def _async_device_turn_on(self, bypass_cycle=False):
        if self._active:
            return
        await self._action_on.async_run(context=self._context)
        self._active = True
        self._last_switched = dt_util.utcnow()

    async def _async_device_turn_off(self):
        if not self._active:
            return
        await self._action_off.async_run(context=self._context)
        self._active = False
        self._last_switched = dt_util.utcnow()
