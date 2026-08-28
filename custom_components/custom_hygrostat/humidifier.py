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
from homeassistant.core import Context, CoreState, HomeAssistant, callback
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
    CONF_BOOST_HUMIDITY,
    CONF_DEVICE_ENTITY,
    CONF_ENABLE_TEMPLATE,
    CONF_ERROR_TEMPLATE,
    CONF_STARTUP_DELAY,
    DEFAULT_TOLERANCE,
    DEFAULT_MIN_HUMIDITY,
    DEFAULT_MAX_HUMIDITY,
    DEFAULT_TARGET_HUMIDITY,
    DEFAULT_BOOST_HUMIDITY,
    DEFAULT_MIN_CYCLE_MINUTES,
    DEFAULT_STARTUP_DELAY_SECONDS,
    DEVICE_OFFLINE_GRACE,
    TEMPLATE_CLEAR_DELAY,
    SENSOR_STALE_TIMEOUT,
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
                boost_humidity=cfg.get(CONF_BOOST_HUMIDITY, DEFAULT_BOOST_HUMIDITY),
                device_entity_id=cfg.get(CONF_DEVICE_ENTITY),
                startup_delay_seconds=cfg.get(
                    CONF_STARTUP_DELAY, DEFAULT_STARTUP_DELAY_SECONDS
                ),
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
        boost_humidity,
        device_entity_id,
        startup_delay_seconds,
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
        self._boost_humidity = boost_humidity
        self._device_entity_id = device_entity_id
        self._startup_delay = timedelta(seconds=startup_delay_seconds)

        self._attr_available_modes = [self.MODE_NORMAL, self.MODE_BOOST]
        self._attr_mode = self.MODE_NORMAL

        self._active = False
        self._cur_humidity = None
        self._primary_humidity = None
        self._secondary_humidity = None
        self._last_switched = None
        self._manual_off_until = None
        self._manual_hold_remove = None
        self._startup_grace_until = None
        self._startup_grace_remove = None
        # Appareil injoignable (confirmé après DEVICE_OFFLINE_GRACE)
        self._device_offline = False
        self._device_offline_remove = None
        # Temporisations de levée des conditions d'erreur / d'activation
        self._template_clear_remove = {}
        self._sensor_stale_remove = None
        self._enable_template = enable_template
        self._error_template = error_template
        self._enable_ok = True
        self._error = False

    async def async_added_to_hass(self):
        await super().async_added_to_hass()

        self.async_on_remove(self._clear_manual_hold)
        self.async_on_remove(self._clear_startup_grace)
        self.async_on_remove(self._clear_device_offline)
        self.async_on_remove(self._cancel_template_clears)
        self.async_on_remove(self._clear_sensor_watchdog)

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
                else:
                    self._arm_device_offline()
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
            # Rechargement à chaud (options, reload) : états déjà stables
            _async_startup()
        else:
            # Vrai démarrage de HA : les entités se réhydratent dans le
            # désordre, on laisse retomber la poussière avant de piloter
            @callback
            def _async_startup_after_boot(_event):
                self._arm_startup_grace()
                _async_startup()

            self.hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_START, _async_startup_after_boot
            )

    @property
    def available(self):
        # Un appareil qui ne répond plus ne doit pas afficher un état de
        # marche inventé : l'entité devient indisponible, comme la source
        return not self._device_offline

    @property
    def is_on(self):
        # L'état de l'entité reflète la marche réelle de l'appareil
        return self._active

    @property
    def _device_state(self):
        """État réel de l'appareil : True/False, None si inconnu."""
        if not self._device_entity_id:
            return None
        state = self.hass.states.get(self._device_entity_id)
        if state is None or state.state not in ("on", "off"):
            return None
        return state.state == "on"

    @property
    def _device_reachable(self):
        """Faux si l'appareil est configuré mais ne publie plus d'état."""
        return not self._device_entity_id or self._device_state is not None

    @property
    def icon(self):
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
        # En boost, la consigne forcée remplace la consigne normale
        if self._attr_mode == self.MODE_BOOST:
            return self._boost_humidity
        return self._target_humidity

    @property
    def extra_state_attributes(self):
        return {
            "current_humidity": self._cur_humidity,
            "primary_humidity": self._primary_humidity,
            "secondary_humidity": self._secondary_humidity,
            "boost_active": self._attr_mode == self.MODE_BOOST,
            "enabled": self._enabled,
            "error_active": self._error,
            "manual_off_until": self._manual_off_until,
            "startup_grace_until": self._startup_grace_until,
        }

    async def async_turn_on(self, **kwargs):
        # Allumer l'hygrostat = demande de marche immédiate, comme le bouton
        # de l'appareil : marche forcée (et fin de la période de grâce)
        self._clear_startup_grace()
        await self._async_start_boost()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        # Éteindre l'hygrostat = même geste que le bouton de l'appareil :
        # arrêt, et hors boost blocage de la relance automatique
        was_boost = self._attr_mode == self.MODE_BOOST
        await self._async_cancel_boost_timer()
        self._attr_mode = self.MODE_NORMAL
        if not was_boost and self._active:
            self._set_manual_hold()
        await self._async_device_turn_off(force=True)
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
        for update in updates:
            result = update.result
            if isinstance(result, TemplateError):
                # En erreur de rendu, on conserve le dernier état connu
                _LOGGER.warning("Template en erreur : %s", result)
                continue
            value = result_as_boolean(result)
            if update.template is self._enable_template:
                self._apply_enable(value)
            elif update.template is self._error_template:
                self._apply_error(value)

    @callback
    def _apply_error(self, value):
        # Sens restrictif immédiat, sens permissif temporisé : un capteur qui
        # clignote (appareil qui se reconnecte) ne doit pas relancer la machine
        if value:
            self._cancel_template_clear("error")
            if self._error:
                return
            self._error = True
            # Une erreur coupe tout, boost compris
            self.hass.async_create_task(self._async_interlock_off())
            return
        if self._error:
            self._schedule_template_clear("error")

    @callback
    def _apply_enable(self, value):
        if not value:
            self._cancel_template_clear("enable")
            if not self._enable_ok:
                return
            self._enable_ok = False
            if self._attr_mode == self.MODE_BOOST:
                # Le boost ignore la condition d'activation
                self.async_write_ha_state()
                return
            self.hass.async_create_task(self._async_suspend())
            return
        if not self._enable_ok:
            self._schedule_template_clear("enable")

    @callback
    def _schedule_template_clear(self, key):
        """Lève une condition bloquante seulement si elle reste stable."""
        if key in self._template_clear_remove:
            return

        @callback
        def _clear(_now):
            self._template_clear_remove.pop(key, None)
            if key == "error":
                self._error = False
            else:
                self._enable_ok = True
            if self._enabled and self._attr_mode != self.MODE_BOOST:
                self.hass.async_create_task(self._async_resume())
            else:
                self.async_write_ha_state()

        self._template_clear_remove[key] = async_call_later(
            self.hass, TEMPLATE_CLEAR_DELAY.total_seconds(), _clear
        )

    @callback
    def _cancel_template_clear(self, key):
        if (remove := self._template_clear_remove.pop(key, None)) is not None:
            remove()

    @callback
    def _cancel_template_clears(self):
        for remove in self._template_clear_remove.values():
            remove()
        self._template_clear_remove.clear()

    async def _async_resume(self):
        # Pas de force ici : une reprise ne doit pas court-circuiter le cycle
        # minimum, sous peine de rallumages en rafale quand un capteur clignote
        await self._async_control()
        self.async_write_ha_state()

    async def _async_suspend(self):
        # Activation false en mode normal : appareil coupé, régulation suspendue
        await self._async_device_turn_off(force=True)
        self.async_write_ha_state()

    async def _async_interlock_off(self):
        # Coupure prioritaire (erreur) : annule aussi un boost en cours
        await self._async_cancel_boost_timer()
        self._attr_mode = self.MODE_NORMAL
        await self._async_device_turn_off(force=True)
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
        self._attr_mode = self.MODE_BOOST
        # Le boost ne force pas la marche : il force la consigne,
        # la régulation normale fait le reste
        await self._async_control(force=True)
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
            await self._async_device_turn_off(force=True)
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
        old_state = event.data.get("old_state")
        # Humidité du capteur interne, à chaque changement (état ou attributs)
        before = (self._cur_humidity, self._secondary_humidity)
        self._update_secondary(new_state)
        changed = before != (self._cur_humidity, self._secondary_humidity)

        if new_state is None or new_state.state not in ("on", "off"):
            # L'appareil ne publie plus d'état exploitable : on ne pilote plus
            # rien, et on le déclare injoignable s'il ne revient pas
            self._arm_device_offline()
            if changed:
                self.async_write_ha_state()
            return

        was_offline = (
            self._device_offline or self._device_offline_remove is not None
        )
        self._clear_device_offline()

        # Détection de la marche/arrêt manuel
        if (is_on := new_state.state == "on") != self._active:
            if (
                self._in_startup_grace
                or was_offline
                or old_state is None
                or old_state.state not in ("on", "off")
            ):
                # État qui se réhydrate (redémarrage, appareil qui reconnecte
                # après unknown/unavailable) : ce n'est pas un geste humain.
                # Resynchronisation silencieuse, ni boost ni blocage 2 h.
                self._active = is_on
                self.async_write_ha_state()
                if not self._in_startup_grace:
                    self.hass.async_create_task(self._async_control())
                return
            self.hass.async_create_task(self._async_handle_manual_switch(is_on))
            return
        if changed or was_offline:
            self.async_write_ha_state()
        self.hass.async_create_task(self._async_control())

    # ----- Appareil injoignable -----

    @callback
    def _arm_device_offline(self):
        if self._device_offline or self._device_offline_remove is not None:
            return

        @callback
        def _offline(_now):
            self._device_offline_remove = None
            self._device_offline = True
            _LOGGER.warning(
                "%s ne répond plus : hygrostat marqué indisponible",
                self._device_entity_id,
            )
            self.async_write_ha_state()

        self._device_offline_remove = async_call_later(
            self.hass, DEVICE_OFFLINE_GRACE.total_seconds(), _offline
        )

    @callback
    def _clear_device_offline(self):
        if self._device_offline_remove is not None:
            self._device_offline_remove()
            self._device_offline_remove = None
        self._device_offline = False

    async def _async_handle_manual_switch(self, is_on):
        # L'appareil a changé d'état sans qu'on l'ait commandé
        self._active = is_on
        self._last_switched = dt_util.utcnow()
        if is_on:
            if self._error:
                # Erreur active (réservoir plein...) : on refuse la marche
                _LOGGER.warning("Allumage manuel refusé : condition d'erreur active")
                await self._async_device_turn_off(force=True)
                self.async_write_ha_state()
                return
            # Un rallumage manuel lève le blocage post-extinction
            self._clear_manual_hold()
            _LOGGER.info("Allumage manuel détecté : la régulation suit")
            # 2026-07-20 : l'allumage manuel ne déclenche plus le boost,
            # l'appareil tourne puis la régulation reprend la main
            # _LOGGER.info("Allumage manuel détecté : passage en boost")
            # await self._async_start_boost()
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

    # ----- Période de grâce au démarrage -----

    @property
    def _in_startup_grace(self):
        return self._startup_grace_until is not None

    @callback
    def _arm_startup_grace(self):
        if not self._startup_delay:
            return
        self._startup_grace_until = dt_util.utcnow() + self._startup_delay

        @callback
        def _grace_expired(_now):
            self._startup_grace_remove = None
            self._startup_grace_until = None
            _LOGGER.debug("Fin de la période de grâce, régulation appliquée")
            self.hass.async_create_task(self._async_control(force=True))
            self.async_write_ha_state()

        self._startup_grace_remove = async_call_later(
            self.hass, self._startup_delay.total_seconds(), _grace_expired
        )

    @callback
    def _clear_startup_grace(self):
        if self._startup_grace_remove is not None:
            self._startup_grace_remove()
            self._startup_grace_remove = None
        self._startup_grace_until = None

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
            # On conserve la dernière valeur connue, mais pas éternellement
            self._arm_sensor_watchdog()
            return
        self._clear_sensor_watchdog()
        self._update_humidity(new_state.state)
        self.hass.async_create_task(self._async_control())
        self.async_write_ha_state()

    @callback
    def _arm_sensor_watchdog(self):
        if self._sensor_stale_remove is not None:
            return

        @callback
        def _stale(_now):
            self._sensor_stale_remove = None
            _LOGGER.warning(
                "%s indisponible depuis %s : dernière mesure abandonnée",
                self._sensor_entity_id,
                SENSOR_STALE_TIMEOUT,
            )
            self._primary_humidity = None
            self._recompute_humidity()
            if self._active and self._cur_humidity is None:
                # Plus aucune mesure : on ne laisse pas l'appareil tourner en aveugle
                self.hass.async_create_task(self._async_device_turn_off(force=True))
            self.async_write_ha_state()

        self._sensor_stale_remove = async_call_later(
            self.hass, SENSOR_STALE_TIMEOUT.total_seconds(), _stale
        )

    @callback
    def _clear_sensor_watchdog(self):
        if self._sensor_stale_remove is not None:
            self._sensor_stale_remove()
            self._sensor_stale_remove = None

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
        if self._error:
            return
        if self._device_offline:
            # Appareil injoignable : rien à piloter, et surtout rien à prétendre
            return
        # Le boost ignore la condition d'activation, pas l'erreur
        if not self._enable_ok and self._attr_mode != self.MODE_BOOST:
            return
        if self._in_startup_grace:
            # Redémarrage de HA : on attend que les valeurs se stabilisent
            # avant d'allumer ou d'éteindre (contrôle forcé à l'échéance)
            return
        # Consigne effective : celle du boost quand il est engagé
        target = self.target_humidity
        if self._cur_humidity is None or target is None:
            return

        if not force and self._min_cycle_duration and self._last_switched:
            elapsed = dt_util.utcnow() - self._last_switched
            if elapsed < self._min_cycle_duration:
                return

        too_humid = self._cur_humidity >= target + self._wet_tolerance
        too_dry = self._cur_humidity <= target - self._dry_tolerance

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
        if not self._device_reachable:
            # Sans appareil joignable, l'action partirait dans le vide et
            # l'entité afficherait une marche imaginaire
            _LOGGER.warning(
                "Allumage ignoré : %s ne répond pas", self._device_entity_id
            )
            return
        # Croyance mise à jour AVANT l'action : l'événement de l'entité d'état
        # déclenché par nos propres actions ne doit pas passer pour manuel
        self._active = True
        self._last_switched = dt_util.utcnow()
        # _active porte l'état on/off de l'entité : publication immédiate
        self.async_write_ha_state()
        if not await self._async_run_action(self._action_on):
            self._active = False
            self.async_write_ha_state()

    async def _async_device_turn_off(self, force=False):
        # force : coupure de sécurité (erreur, suspension, arrêt manuel), à
        # envoyer même si on se croit déjà à l'arrêt alors que l'appareil tourne
        if not self._active and not (force and self._device_state):
            return
        if not self._device_reachable:
            _LOGGER.warning(
                "Extinction ignorée : %s ne répond pas", self._device_entity_id
            )
            return
        was_active = self._active
        self._active = False
        self._last_switched = dt_util.utcnow()
        self.async_write_ha_state()
        if not await self._async_run_action(self._action_off):
            self._active = was_active
            self.async_write_ha_state()

    async def _async_run_action(self, script):
        """Exécute une séquence d'actions ; renvoie False si elle a échoué."""
        try:
            # Sans contexte, HA émet un avertissement et perd la traçabilité
            await script.async_run(context=self._context or Context())
        except Exception:  # noqa: BLE001 - séquence utilisateur, tout est possible
            _LOGGER.exception("Échec de la séquence d'actions")
            return False
        return True
