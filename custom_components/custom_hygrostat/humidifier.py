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
    CONF_BOOST_TIMER,
    CONF_DEVICE_ENTITY,
    CONF_ENABLE_TEMPLATE,
    CONF_ERROR_TEMPLATE,
    DEFAULT_TOLERANCE,
    DEFAULT_MIN_HUMIDITY,
    DEFAULT_MAX_HUMIDITY,
    DEFAULT_TARGET_HUMIDITY,
    DEFAULT_MIN_CYCLE_MINUTES,
    MANUAL_OFF_HOLD,
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
                boost_timer_entity_id=cfg.get(CONF_BOOST_TIMER),
                device_entity_id=cfg.get(CONF_DEVICE_ENTITY),
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
        boost_timer_entity_id,
        device_entity_id,
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
        self._boost_timer_entity_id = boost_timer_entity_id
        self._device_entity_id = device_entity_id

        self._attr_available_modes = [self.MODE_NORMAL, self.MODE_BOOST]
        self._attr_mode = self.MODE_NORMAL

        self._state = False
        self._active = False
        self._cur_humidity = None
        self._primary_humidity = None
        self._secondary_humidity = None
        self._last_switched = None
        self._manual_off_until = None
        self._manual_hold_remove = None
        self._enable_template = enable_template
        self._error_template = error_template
        self._enable_ok = True
        self._error = False

    async def async_added_to_hass(self):
        await super().async_added_to_hass()

        self.async_on_remove(self._clear_manual_hold)

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

        if self._boost_timer_entity_id:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    [self._boost_timer_entity_id],
                    self._async_boost_timer_changed,
                )
            )

        if self._device_entity_id:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    [self._device_entity_id],
                    self._async_device_changed,
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
            if self._device_entity_id:
                # Capteur interne + resynchronisation de l'état réel
                device_state = self.hass.states.get(self._device_entity_id)
                self._update_secondary(device_state)
                if device_state and device_state.state in ("on", "off"):
                    self._active = device_state.state == "on"
            if self._boost_timer_entity_id:
                # Le timer restauré par HA fait foi, pas le mode restauré
                timer_state = self.hass.states.get(self._boost_timer_entity_id)
                if timer_state and timer_state.state == "active":
                    self.hass.async_create_task(self._async_engage_boost())
                elif self._attr_mode == self.MODE_BOOST:
                    self._attr_mode = self.MODE_NORMAL
            elif self._attr_mode == self.MODE_BOOST:
                # Marche forcée manuelle (sans timer) restaurée
                self.hass.async_create_task(self._async_engage_boost())
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
        # Le boost passe avant l'activation, qu'il ignore
        if self._attr_mode == self.MODE_BOOST:
            return "mdi:rocket-launch"
        if not self._enable_ok:
            return "mdi:water-off"
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
            "primary_humidity": self._primary_humidity,
            "secondary_humidity": self._secondary_humidity,
            "boost_active": self._attr_mode == self.MODE_BOOST,
            "enabled": self._enabled,
            "error_active": self._error,
            "manual_off_until": self._manual_off_until,
        }

    async def async_turn_on(self, **kwargs):
        # Action explicite sur l'hygrostat : lève le blocage manuel
        self._clear_manual_hold()
        self._state = True
        await self._async_control(force=True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        await self._async_cancel_boost_timer()
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
            await self._async_cancel_boost_timer()
            await self._async_leave_boost()
        self.async_write_ha_state()

    # ----- Conditions d'activation et d'erreur (templates) -----

    @property
    def _enabled(self):
        # Autorisé uniquement si activation true ET erreur false
        return self._enable_ok and not self._error

    @callback
    def _async_templates_changed(self, event, updates):
        was_error = self._error
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
        if self._error and not was_error:
            # Une erreur coupe tout, boost compris
            self.hass.async_create_task(self._async_interlock_off())
            return
        if self._enabled == was_enabled:
            # L'autorisation n'a pas bougé, mais l'icône
            # ou les attributs peuvent avoir changé
            self.async_write_ha_state()
            return
        if self._attr_mode == self.MODE_BOOST:
            # Le boost ignore la condition d'activation
            self.async_write_ha_state()
            return
        if self._enabled:
            self.hass.async_create_task(self._async_resume())
        else:
            self.hass.async_create_task(self._async_suspend())

    async def _async_resume(self):
        await self._async_control(force=True)
        self.async_write_ha_state()

    async def _async_suspend(self):
        # Activation false en mode normal : appareil coupé, régulation suspendue
        await self._async_device_turn_off()
        self.async_write_ha_state()

    async def _async_interlock_off(self):
        # Coupure prioritaire (erreur) : annule aussi un boost en cours
        await self._async_cancel_boost_timer()
        self._attr_mode = self.MODE_NORMAL
        await self._async_device_turn_off()
        self.async_write_ha_state()

    # ----- Boost (marche forcée) -----

    async def _async_start_boost(self):
        if self._error:
            _LOGGER.warning("Boost refusé : condition d'erreur active")
            return
        if self._boost_timer_entity_id:
            # Le passage en boost suivra le changement d'état du timer
            await self.hass.services.async_call(
                "timer",
                "start",
                {"entity_id": self._boost_timer_entity_id},
                blocking=True,
                context=self._context,
            )
            return
        # Sans timer : marche forcée jusqu'au retour manuel en mode normal
        await self._async_engage_boost()

    async def _async_engage_boost(self):
        if self._error:
            _LOGGER.warning("Boost refusé : condition d'erreur active")
            return
        # Le boost lève le blocage post-extinction manuelle
        self._clear_manual_hold()
        if not self._state:
            self._state = True
        self._attr_mode = self.MODE_BOOST
        await self._async_device_turn_on()
        self.async_write_ha_state()

    async def _async_end_boost(self):
        if self._attr_mode != self.MODE_BOOST:
            return
        await self._async_leave_boost()
        self.async_write_ha_state()

    async def _async_leave_boost(self):
        self._attr_mode = self.MODE_NORMAL
        if not self._enabled:
            # Régulation suspendue : l'appareil ne doit pas rester en marche
            await self._async_device_turn_off()
        else:
            await self._async_control(force=True)

    async def _async_cancel_boost_timer(self):
        if self._boost_timer_entity_id:
            await self.hass.services.async_call(
                "timer",
                "cancel",
                {"entity_id": self._boost_timer_entity_id},
                blocking=True,
                context=self._context,
            )

    @callback
    def _async_boost_timer_changed(self, event):
        new_state = event.data.get("new_state")
        if new_state is None:
            return
        if new_state.state == "active":
            self.hass.async_create_task(self._async_engage_boost())
        else:
            self.hass.async_create_task(self._async_end_boost())

    # ----- Entité déshumidificateur (capteur interne + détection manuelle) -----

    @callback
    def _async_device_changed(self, event):
        new_state = event.data.get("new_state")
        # Humidité du capteur interne, à chaque changement (état ou attributs)
        self._update_secondary(new_state)
        # Détection de la marche/arrêt manuel
        if (
            new_state is not None
            and new_state.state in ("on", "off")
            and (is_on := new_state.state == "on") != self._active
        ):
            self.hass.async_create_task(self._async_handle_manual_switch(is_on))
            return
        self.hass.async_create_task(self._async_control())
        self.async_write_ha_state()

    async def _async_handle_manual_switch(self, is_on):
        # L'appareil a changé d'état sans qu'on l'ait commandé
        self._active = is_on
        self._last_switched = dt_util.utcnow()
        if is_on:
            if self._error:
                # Erreur active (réservoir plein...) : on refuse la marche
                _LOGGER.warning("Allumage manuel refusé : condition d'erreur active")
                await self._async_device_turn_off()
                self.async_write_ha_state()
                return
            _LOGGER.info("Allumage manuel détecté : passage en boost")
            if not self._state:
                self._state = True
            await self._async_start_boost()
        else:
            was_boost = self._attr_mode == self.MODE_BOOST
            await self._async_cancel_boost_timer()
            self._attr_mode = self.MODE_NORMAL
            if not was_boost:
                # Extinction manuelle hors boost : la régulation ne doit pas
                # relancer l'appareil avant l'échéance
                self._set_manual_hold()
                _LOGGER.info(
                    "Extinction manuelle : relance auto bloquée pendant %s",
                    MANUAL_OFF_HOLD,
                )
        self.async_write_ha_state()

    @callback
    def _set_manual_hold(self):
        self._clear_manual_hold()
        self._manual_off_until = dt_util.utcnow() + MANUAL_OFF_HOLD

        @callback
        def _hold_expired(_now):
            self._manual_hold_remove = None
            self._manual_off_until = None
            self.hass.async_create_task(self._async_control())
            self.async_write_ha_state()

        self._manual_hold_remove = async_call_later(
            self.hass, MANUAL_OFF_HOLD.total_seconds(), _hold_expired
        )

    @callback
    def _clear_manual_hold(self):
        if self._manual_hold_remove is not None:
            self._manual_hold_remove()
            self._manual_hold_remove = None
        self._manual_off_until = None

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
            self._primary_humidity = float(state)
        except (ValueError, TypeError):
            _LOGGER.warning("Humidité illisible : %s", state)
            self._primary_humidity = None
        self._recompute_humidity()

    @callback
    def _update_secondary(self, state_obj):
        # Humidité interne (attribut current_humidity) ; indisponible ou
        # absente = écartée de la moyenne (repli sur le capteur principal)
        value = None
        if state_obj is not None and state_obj.state not in (
            STATE_UNAVAILABLE,
            STATE_UNKNOWN,
        ):
            raw = state_obj.attributes.get("current_humidity")
            try:
                value = float(raw)
            except (ValueError, TypeError):
                if raw is not None:
                    _LOGGER.warning("Humidité interne illisible : %s", raw)
        self._secondary_humidity = value
        self._recompute_humidity()

    @callback
    def _recompute_humidity(self):
        values = [
            v
            for v in (self._primary_humidity, self._secondary_humidity)
            if v is not None
        ]
        self._cur_humidity = round(sum(values) / len(values), 1) if values else None

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
                if (
                    self._manual_off_until is not None
                    and dt_util.utcnow() < self._manual_off_until
                ):
                    # Extinction manuelle récente : pas de relance auto
                    return
                await self._async_device_turn_on()

    async def _async_device_turn_on(self):
        if self._active:
            return
        # Croyance mise à jour AVANT l'action : l'événement de l'entité d'état
        # déclenché par nos propres actions ne doit pas passer pour manuel
        self._active = True
        self._last_switched = dt_util.utcnow()
        await self._action_on.async_run(context=self._context)

    async def _async_device_turn_off(self):
        if not self._active:
            return
        self._active = False
        self._last_switched = dt_util.utcnow()
        await self._action_off.async_run(context=self._context)
