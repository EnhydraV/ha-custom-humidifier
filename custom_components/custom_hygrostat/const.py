"""Constants for Custom Hygrostat."""
from datetime import timedelta

DOMAIN = "custom_hygrostat"
PLATFORMS = ["humidifier"]

CONF_SENSOR = "target_sensor"
CONF_ACTION_ON = "turn_on_action"
CONF_ACTION_OFF = "turn_off_action"
CONF_MIN_HUMIDITY = "min_humidity"
CONF_MAX_HUMIDITY = "max_humidity"
CONF_TARGET_HUMIDITY = "target_humidity"
CONF_TARGET_ENTITY = "target_entity"
CONF_DRY_TOLERANCE = "dry_tolerance"
CONF_WET_TOLERANCE = "wet_tolerance"
CONF_MIN_CYCLE_DURATION = "min_cycle_duration"
CONF_BOOST_TIMER = "boost_timer"
# Entité humidifier du fabricant : capteur interne + détection manuelle
CONF_DEVICE_ENTITY = "device_entity"
CONF_ENABLE_TEMPLATE = "enable_template"
CONF_ERROR_TEMPLATE = "error_template"

DEFAULT_NAME = "Custom Hygrostat"
DEFAULT_TOLERANCE = 3
DEFAULT_MIN_HUMIDITY = 30
DEFAULT_MAX_HUMIDITY = 99
DEFAULT_TARGET_HUMIDITY = 55
DEFAULT_MIN_CYCLE_MINUTES = 0

# Blocage de la régulation après une extinction manuelle de l'appareil
MANUAL_OFF_HOLD = timedelta(hours=2)
