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
# Consigne forcée pendant le mode boost
CONF_BOOST_HUMIDITY = "boost_humidity"
# Entité humidifier du fabricant : capteur interne + détection manuelle
CONF_DEVICE_ENTITY = "device_entity"
CONF_ENABLE_TEMPLATE = "enable_template"
CONF_ERROR_TEMPLATE = "error_template"
# Période de grâce au démarrage de HA avant de piloter l'appareil (secondes)
CONF_STARTUP_DELAY = "startup_delay"

DEFAULT_NAME = "Custom Hygrostat"
DEFAULT_TOLERANCE = 3
DEFAULT_MIN_HUMIDITY = 30
DEFAULT_MAX_HUMIDITY = 99
DEFAULT_TARGET_HUMIDITY = 55
DEFAULT_BOOST_HUMIDITY = 50
DEFAULT_MIN_CYCLE_MINUTES = 0
DEFAULT_STARTUP_DELAY_SECONDS = 120

# Blocage de la régulation après une extinction manuelle de l'appareil
MANUAL_OFF_HOLD = timedelta(hours=2)

# Délai de tolérance avant de déclarer l'appareil injoignable (entité
# indisponible) quand son entité passe unknown/unavailable
DEVICE_OFFLINE_GRACE = timedelta(seconds=60)

# Stabilité exigée avant de LEVER une condition d'erreur ou de réactivation :
# un capteur qui clignote ne doit pas relancer l'appareil
TEMPLATE_CLEAR_DELAY = timedelta(seconds=60)

# Capteur d'humidité indisponible depuis ce délai : la dernière valeur connue
# est abandonnée (et l'appareil coupé s'il n'y a plus aucune mesure)
SENSOR_STALE_TIMEOUT = timedelta(minutes=30)
