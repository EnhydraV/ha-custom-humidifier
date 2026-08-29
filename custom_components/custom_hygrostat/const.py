"""Constants for Custom Hygrostat."""
from datetime import timedelta

DOMAIN = "custom_hygrostat"
PLATFORMS = ["humidifier"]

CONF_SENSOR = "target_sensor"
CONF_ACTION_ON = "turn_on_action"
CONF_ACTION_OFF = "turn_off_action"
CONF_MIN_HUMIDITY = "min_humidity"
CONF_MAX_HUMIDITY = "max_humidity"
# Consigne normale : un template, seule source de verite. Une valeur fixe
# s'ecrit "{{ 55 }}", une consigne partagee "{{ states('sensor.x')|float }}",
# et un ecart par piece se met dans le meme template.
CONF_TARGET_TEMPLATE = "target_template"
CONF_DRY_TOLERANCE = "dry_tolerance"
CONF_WET_TOLERANCE = "wet_tolerance"
CONF_MIN_CYCLE_DURATION = "min_cycle_duration"
CONF_BOOST_TIMER = "boost_timer"
# Consigne forcée pendant le mode boost
CONF_BOOST_HUMIDITY = "boost_humidity"
# Entité humidifier du fabricant : capteur interne + détection manuelle
CONF_DEVICE_ENTITY = "device_entity"
CONF_ENABLE_TEMPLATE = "enable_template"
# Ventilateur de l'appareil et template decidant sa puissance (en %)
CONF_FAN_ENTITY = "fan_entity"
CONF_FAN_SPEED_TEMPLATE = "fan_speed_template"
CONF_ERROR_TEMPLATE = "error_template"
# Période de grâce au démarrage de HA avant de piloter l'appareil (secondes)
CONF_STARTUP_DELAY = "startup_delay"
# Prise commandant l'alimentation de l'appareil, pour le redemarrer quand il
# ne repond plus (certains modules Tuya refusent les connexions locales
# jusqu'a une coupure de courant)
CONF_POWER_SWITCH = "power_switch"

DEFAULT_NAME = "Custom Hygrostat"
DEFAULT_TOLERANCE = 3
DEFAULT_MIN_HUMIDITY = 30
DEFAULT_MAX_HUMIDITY = 99
DEFAULT_TARGET_HUMIDITY = 55
DEFAULT_BOOST_HUMIDITY = 50
DEFAULT_FAN_SPEED = 50
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

# Coupure de courant appliquée par la prise pour redémarrer un appareil muet.
# Assez longue pour que l'électronique se réinitialise et que la pression du
# circuit frigorifique s'égalise avant le redémarrage du compresseur.
POWER_CYCLE_OFF_DELAY = timedelta(seconds=90)
# Deux redémarrages ne peuvent pas s'enchaîner : si l'appareil ne revient pas,
# c'est une panne, pas un blocage, et rien ne sert de le maltraiter en boucle
POWER_CYCLE_MIN_INTERVAL = timedelta(hours=2)
