"""Config flow for Custom Hygrostat."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import TemplateError
from homeassistant.helpers import entity_registry as er, selector
from homeassistant.helpers.template import Template
from homeassistant.util import slugify

from .const import (
    DOMAIN,
    CONF_SENSOR,
    CONF_ACTION_ON,
    CONF_ACTION_OFF,
    CONF_MIN_HUMIDITY,
    CONF_MAX_HUMIDITY,
    CONF_TARGET_HUMIDITY,
    CONF_TARGET_ENTITY,
    CONF_TARGET_OFFSET_TEMPLATE,
    CONF_DRY_TOLERANCE,
    CONF_WET_TOLERANCE,
    CONF_MIN_CYCLE_DURATION,
    CONF_BOOST_TIMER,
    CONF_BOOST_HUMIDITY,
    CONF_DEVICE_ENTITY,
    CONF_ENABLE_TEMPLATE,
    CONF_ERROR_TEMPLATE,
    CONF_FAN_ENTITY,
    CONF_FAN_SPEED_TEMPLATE,
    CONF_STARTUP_DELAY,
    CONF_POWER_SWITCH,
    DEFAULT_NAME,
    DEFAULT_TOLERANCE,
    DEFAULT_MIN_HUMIDITY,
    DEFAULT_MAX_HUMIDITY,
    DEFAULT_TARGET_HUMIDITY,
    DEFAULT_BOOST_HUMIDITY,
    DEFAULT_MIN_CYCLE_MINUTES,
    DEFAULT_STARTUP_DELAY_SECONDS,
)

CONF_NAME = "name"


def _schema(defaults: dict[str, Any]) -> vol.Schema:
    """Build the form schema with given defaults."""
    return vol.Schema(
        {
            vol.Required(
                CONF_NAME, default=defaults.get(CONF_NAME, DEFAULT_NAME)
            ): selector.TextSelector(),
            vol.Required(
                CONF_SENSOR, default=defaults.get(CONF_SENSOR)
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="sensor", device_class="humidity"
                )
            ),
            vol.Required(
                CONF_ACTION_ON, default=defaults.get(CONF_ACTION_ON, [])
            ): selector.ActionSelector(),
            vol.Required(
                CONF_ACTION_OFF, default=defaults.get(CONF_ACTION_OFF, [])
            ): selector.ActionSelector(),
            vol.Optional(
                CONF_TARGET_HUMIDITY,
                default=defaults.get(CONF_TARGET_HUMIDITY, DEFAULT_TARGET_HUMIDITY),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=100, step=1, unit_of_measurement="%",
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            vol.Optional(
                CONF_TARGET_ENTITY,
                description={"suggested_value": defaults.get(CONF_TARGET_ENTITY)},
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=["input_number", "number", "sensor"]
                )
            ),
            vol.Optional(
                CONF_TARGET_OFFSET_TEMPLATE,
                default=defaults.get(CONF_TARGET_OFFSET_TEMPLATE, ""),
            ): selector.TemplateSelector(),
            vol.Optional(
                CONF_DRY_TOLERANCE,
                default=defaults.get(CONF_DRY_TOLERANCE, DEFAULT_TOLERANCE),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=20, step=0.5, unit_of_measurement="%",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                CONF_WET_TOLERANCE,
                default=defaults.get(CONF_WET_TOLERANCE, DEFAULT_TOLERANCE),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=20, step=0.5, unit_of_measurement="%",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                CONF_MIN_HUMIDITY,
                default=defaults.get(CONF_MIN_HUMIDITY, DEFAULT_MIN_HUMIDITY),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=100, step=1, unit_of_measurement="%",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                CONF_MAX_HUMIDITY,
                default=defaults.get(CONF_MAX_HUMIDITY, DEFAULT_MAX_HUMIDITY),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=100, step=1, unit_of_measurement="%",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                CONF_MIN_CYCLE_DURATION,
                default=defaults.get(CONF_MIN_CYCLE_DURATION, DEFAULT_MIN_CYCLE_MINUTES),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=120, step=1, unit_of_measurement="min",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                CONF_STARTUP_DELAY,
                default=defaults.get(CONF_STARTUP_DELAY, DEFAULT_STARTUP_DELAY_SECONDS),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=600, step=5, unit_of_measurement="s",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                CONF_BOOST_TIMER,
                description={"suggested_value": defaults.get(CONF_BOOST_TIMER)},
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="timer")
            ),
            vol.Optional(
                CONF_BOOST_HUMIDITY,
                default=defaults.get(CONF_BOOST_HUMIDITY, DEFAULT_BOOST_HUMIDITY),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=100, step=1, unit_of_measurement="%",
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            vol.Optional(
                CONF_DEVICE_ENTITY,
                description={"suggested_value": defaults.get(CONF_DEVICE_ENTITY)},
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="humidifier")
            ),
            vol.Optional(
                CONF_POWER_SWITCH,
                description={"suggested_value": defaults.get(CONF_POWER_SWITCH)},
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=["switch", "input_boolean"]
                )
            ),
            vol.Optional(
                CONF_FAN_ENTITY,
                description={"suggested_value": defaults.get(CONF_FAN_ENTITY)},
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="fan")
            ),
            vol.Optional(
                CONF_FAN_SPEED_TEMPLATE,
                default=defaults.get(CONF_FAN_SPEED_TEMPLATE, ""),
            ): selector.TemplateSelector(),
            vol.Optional(
                CONF_ENABLE_TEMPLATE,
                default=defaults.get(CONF_ENABLE_TEMPLATE, ""),
            ): selector.TemplateSelector(),
            vol.Optional(
                CONF_ERROR_TEMPLATE,
                default=defaults.get(CONF_ERROR_TEMPLATE, ""),
            ): selector.TemplateSelector(),
        }
    )


def _own_entity_ids(
    hass: HomeAssistant, user_input: dict[str, Any], entry: ConfigEntry | None
) -> set[str]:
    """Entity ids de l'hygrostat lui-même, pour détecter l'auto-référence."""
    ids = {f"humidifier.{slugify(user_input.get(CONF_NAME) or '')}"}
    if entry is not None:
        registry = er.async_get(hass)
        ids.update(
            entity.entity_id
            for entity in er.async_entries_for_config_entry(registry, entry.entry_id)
        )
    return {eid for eid in ids if eid and not eid.endswith(".")}


def _referenced_strings(node: Any) -> set[str]:
    """Toutes les chaînes d'une séquence d'actions, pour comparaison exacte."""
    if isinstance(node, str):
        return {node}
    if isinstance(node, dict):
        return set().union(*(_referenced_strings(v) for v in node.values())) if node else set()
    if isinstance(node, (list, tuple)):
        return set().union(*(_referenced_strings(v) for v in node)) if node else set()
    return set()


def _validate(
    hass: HomeAssistant,
    user_input: dict[str, Any],
    entry: ConfigEntry | None = None,
) -> dict[str, str]:
    """Validate user input shared by config and options flows."""
    errors: dict[str, str] = {}
    if user_input[CONF_MIN_HUMIDITY] >= user_input[CONF_MAX_HUMIDITY]:
        errors["base"] = "humidity_range"
    own_ids = _own_entity_ids(hass, user_input, entry)
    for conf in (CONF_ACTION_ON, CONF_ACTION_OFF):
        actions = user_input.get(conf)
        if not actions:
            # Une séquence vide laisse l'hygrostat croire qu'il pilote quelque
            # chose alors qu'il n'envoie rien
            errors[conf] = "empty_action"
            continue
        if own_ids & _referenced_strings(actions):
            # Une action qui cible l'hygrostat lui-même reboucle sur lui
            errors[conf] = "self_reference"
    if user_input.get(CONF_FAN_SPEED_TEMPLATE) and not user_input.get(CONF_FAN_ENTITY):
        # Un template de vitesse sans ventilateur a piloter ne sert a rien
        errors[CONF_FAN_ENTITY] = "fan_entity_required"
    for conf in (
        CONF_ENABLE_TEMPLATE,
        CONF_ERROR_TEMPLATE,
        CONF_FAN_SPEED_TEMPLATE,
        CONF_TARGET_OFFSET_TEMPLATE,
    ):
        if tpl := user_input.get(conf):
            try:
                Template(tpl, hass).ensure_valid()
            except TemplateError:
                errors[conf] = "invalid_template"
    return errors


class CustomHygrostatConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Custom Hygrostat."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = _validate(self.hass, user_input)
            if not errors:
                # Champ vidé = None explicite, sinon la fusion data/options
                # ressusciterait l'ancienne valeur
                for conf in (
                    CONF_TARGET_ENTITY,
                    CONF_BOOST_TIMER,
                    CONF_DEVICE_ENTITY,
                    CONF_POWER_SWITCH,
                    CONF_FAN_ENTITY,
                ):
                    user_input.setdefault(conf, None)
                await self.async_set_unique_id(
                    f"{DOMAIN}_{user_input[CONF_NAME].lower().replace(' ', '_')}"
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input[CONF_NAME], data=user_input
                )

        return self.async_show_form(
            step_id="user", data_schema=_schema(user_input or {}), errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Get the options flow."""
        # config_entry est fourni par la property OptionsFlow.config_entry
        return CustomHygrostatOptionsFlow()


class CustomHygrostatOptionsFlow(OptionsFlow):
    """Handle options flow (edit after setup)."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        """Manage the options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = _validate(self.hass, user_input, self.config_entry)
            if not errors:
                for conf in (
                    CONF_TARGET_ENTITY,
                    CONF_BOOST_TIMER,
                    CONF_DEVICE_ENTITY,
                    CONF_POWER_SWITCH,
                    CONF_FAN_ENTITY,
                ):
                    user_input.setdefault(conf, None)
                return self.async_create_entry(title="", data=user_input)

        current = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="init", data_schema=_schema(current), errors=errors
        )
