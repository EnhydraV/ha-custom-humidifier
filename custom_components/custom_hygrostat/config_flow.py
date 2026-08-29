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
    CONF_MIN_HUMIDITY,
    CONF_MAX_HUMIDITY,
    CONF_TARGET_TEMPLATE,
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
                CONF_DEVICE_ENTITY, default=defaults.get(CONF_DEVICE_ENTITY)
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="humidifier")
            ),
            vol.Required(
                CONF_TARGET_TEMPLATE,
                default=defaults.get(
                    CONF_TARGET_TEMPLATE, "{{ %s }}" % DEFAULT_TARGET_HUMIDITY
                ),
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


# Templates dont le rendu est affiché sous le formulaire, avec leur libellé
PREVIEWED = (
    (CONF_TARGET_TEMPLATE, "Consigne"),
    (CONF_FAN_SPEED_TEMPLATE, "Ventilation"),
    (CONF_ENABLE_TEMPLATE, "Activation"),
    (CONF_ERROR_TEMPLATE, "Erreur"),
)


@callback
def _preview(hass: HomeAssistant, values: dict[str, Any]) -> dict[str, str]:
    """Rend les templates pour les montrer sous le formulaire.

    Evalué à chaque affichage, donc aussi après une erreur de validation :
    corriger un template et resoumettre suffit à en voir le résultat.
    """
    lignes = []
    for conf, label in PREVIEWED:
        tpl = (values.get(conf) or "").strip()
        if not tpl:
            continue
        try:
            rendu = Template(tpl, hass).async_render(parse_result=False)
        except Exception as err:  # noqa: BLE001 - template utilisateur
            rendu = f"erreur de rendu ({err})"
        lignes.append(f"{label} : {rendu}")
    # La clé doit toujours exister, sinon le formatage du libellé échoue
    return {"preview": "\n".join(lignes) if lignes else "aucun template renseigné"}


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
    for conf in (CONF_DEVICE_ENTITY, CONF_FAN_ENTITY, CONF_POWER_SWITCH):
        if (target := user_input.get(conf)) and target in own_ids:
            # Se désigner soi-même comme appareil piloté reboucle sur soi
            errors[conf] = "self_reference"
    if user_input.get(CONF_FAN_SPEED_TEMPLATE) and not user_input.get(CONF_FAN_ENTITY):
        # Un template de vitesse sans ventilateur a piloter ne sert a rien
        errors[CONF_FAN_ENTITY] = "fan_entity_required"
    if not (user_input.get(CONF_TARGET_TEMPLATE) or "").strip():
        errors[CONF_TARGET_TEMPLATE] = "target_required"
    for conf in (
        CONF_ENABLE_TEMPLATE,
        CONF_ERROR_TEMPLATE,
        CONF_FAN_SPEED_TEMPLATE,
        CONF_TARGET_TEMPLATE,
    ):
        if tpl := user_input.get(conf):
            try:
                Template(tpl, hass).ensure_valid()
            except TemplateError:
                errors[conf] = "invalid_template"
    return errors


class CustomHygrostatConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Custom Hygrostat."""

    VERSION = 3

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
                    CONF_BOOST_TIMER,
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

        defaults = user_input or {}
        return self.async_show_form(
            step_id="user",
            data_schema=_schema(defaults),
            errors=errors,
            description_placeholders=_preview(self.hass, defaults),
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
                    CONF_BOOST_TIMER,
                    CONF_POWER_SWITCH,
                    CONF_FAN_ENTITY,
                ):
                    user_input.setdefault(conf, None)
                return self.async_create_entry(title="", data=user_input)

        current = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="init",
            data_schema=_schema(current),
            errors=errors,
            description_placeholders=_preview(self.hass, user_input or current),
        )
