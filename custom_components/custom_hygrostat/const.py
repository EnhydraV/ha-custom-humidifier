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
CONF_DRY_TOLERANCE = "dry_tolerance"
CONF_WET_TOLERANCE = "wet_tolerance"
CONF_MIN_CYCLE_DURATION = "min_cycle_duration"
CONF_BOOST_DURATION = "boost_duration"
CONF_ENABLE_TEMPLATE = "enable_template"

DEFAULT_NAME = "Custom Hygrostat"
DEFAULT_TOLERANCE = 3
DEFAULT_MIN_HUMIDITY = 30
DEFAULT_MAX_HUMIDITY = 99
DEFAULT_TARGET_HUMIDITY = 55
DEFAULT_BOOST_MINUTES = 30
DEFAULT_MIN_CYCLE_MINUTES = 0
