"""The Custom Hygrostat integration."""
from __future__ import annotations

import logging
import re

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_TARGET_TEMPLATE, DEFAULT_TARGET_HUMIDITY, PLATFORMS

_LOGGER = logging.getLogger(__name__)

# Clés de la v1, remplacées par CONF_TARGET_TEMPLATE
LEGACY_TARGET_HUMIDITY = "target_humidity"
LEGACY_TARGET_ENTITY = "target_entity"
LEGACY_TARGET_OFFSET = "target_offset_template"

# Un template d'une seule expression, dont on peut réutiliser le corps
SINGLE_EXPRESSION = re.compile(r"^\s*\{\{(?P<body>[^{}]+)\}\}\s*$")


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Custom Hygrostat from a config entry."""
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload entry when options are updated."""
    await hass.config_entries.async_reload(entry.entry_id)


def _build_target_template(cfg: dict) -> tuple[str, str | None]:
    """Compose le template de consigne à partir des trois anciens champs.

    Renvoie le template et, le cas échéant, un avertissement à journaliser.
    """
    entity = cfg.get(LEGACY_TARGET_ENTITY)
    fixed = cfg.get(LEGACY_TARGET_HUMIDITY, DEFAULT_TARGET_HUMIDITY)
    offset = (cfg.get(LEGACY_TARGET_OFFSET) or "").strip()

    if not entity:
        # Consigne fixe : elle s'écrit très bien en template
        return "{{ %s }}" % fixed, None

    # Pas de valeur par défaut sur le filtre float : une source illisible lève
    # une erreur de rendu, et l'entité conserve alors sa dernière consigne
    # plutôt que de basculer sur une valeur que personne n'a choisie.
    base = "states('%s')|float" % entity
    if not offset:
        return "{{ %s }}" % base, None

    if (match := SINGLE_EXPRESSION.match(offset)) is not None:
        return "{{ (%s) + (%s) }}" % (base, match.group("body").strip()), None

    # Écart trop complexe pour être recomposé mécaniquement : on garde la
    # consigne sans lui, et on le dit franchement plutôt que de produire un
    # template douteux.
    return (
        "{{ %s }}" % base,
        "l'écart de consigne (%s) n'a pas pu être fusionné automatiquement, "
        "reportez-le à la main dans le template de consigne" % offset,
    )


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old entry."""
    if entry.version >= 2:
        return True

    # v1 -> v2 : consigne fixe, entité de consigne et écart fusionnés dans un
    # unique template, seule source de vérité de la consigne normale.
    data = {**entry.data}
    options = {**entry.options}
    template, warning = _build_target_template({**data, **options})

    for cfg in (data, options):
        for key in (LEGACY_TARGET_HUMIDITY, LEGACY_TARGET_ENTITY, LEGACY_TARGET_OFFSET):
            cfg.pop(key, None)
    data[CONF_TARGET_TEMPLATE] = template
    options.pop(CONF_TARGET_TEMPLATE, None)

    hass.config_entries.async_update_entry(entry, data=data, options=options, version=2)
    _LOGGER.info("%s migré en v2, consigne : %s", entry.title, template)
    if warning:
        _LOGGER.warning("%s : %s", entry.title, warning)
    return True
