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
from homeassistant.helpers import selector
from homeassistant.helpers.template import Template

from .const import (
    DOMAIN,
    CONF_SENSOR,
    CONF_ACTION_ON,
    CONF_ACTION_OFF,
    CONF_MIN_HUMIDITY,
    CONF_MAX_HUMIDITY,
    CONF_TARGET_HUMIDITY,
    CONF_DRY_TOLERANCE,
    CONF_WET_TOLERANCE,
    CONF_MIN_CYCLE_DURATION,
    CONF_BOOST_DURATION,
    CONF_ENABLE_TEMPLATE,
    CONF_ERROR_TEMPLATE,
    DEFAULT_NAME,
    DEFAULT_TOLERANCE,
    DEFAULT_MIN_HUMIDITY,
    DEFAULT_MAX_HUMIDITY,
    DEFAULT_TARGET_HUMIDITY,
    DEFAULT_BOOST_MINUTES,
    DEFAULT_MIN_CYCLE_MINUTES,
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
                CONF_BOOST_DURATION,
                default=defaults.get(CONF_BOOST_DURATION, DEFAULT_BOOST_MINUTES),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, max=240, step=1, unit_of_measurement="min",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
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


def _validate(hass: HomeAssistant, user_input: dict[str, Any]) -> dict[str, str]:
    """Validate user input shared by config and options flows."""
    errors: dict[str, str] = {}
    if user_input[CONF_MIN_HUMIDITY] >= user_input[CONF_MAX_HUMIDITY]:
        errors["base"] = "humidity_range"
    for conf in (CONF_ENABLE_TEMPLATE, CONF_ERROR_TEMPLATE):
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
        return CustomHygrostatOptionsFlow(config_entry)


class CustomHygrostatOptionsFlow(OptionsFlow):
    """Handle options flow (edit after setup)."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        """Manage the options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = _validate(self.hass, user_input)
            if not errors:
                return self.async_create_entry(title="", data=user_input)

        current = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="init", data_schema=_schema(current), errors=errors
        )
