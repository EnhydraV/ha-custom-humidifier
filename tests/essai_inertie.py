"""Exerce la VRAIE logique d'inertie, extraite du source du composant.

Aucune copie : les methodes sont lues dans humidifier.py et executees telles
quelles, avec Home Assistant remplace par des doublures minimales.
"""
import ast, io, textwrap
from datetime import datetime, timedelta, timezone

import os
SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "..", "custom_components", "custom_hygrostat", "humidifier.py")
VOULUES = {"_evaluate_stall", "_arm_stall_timer", "_cancel_stall_timer",
           "_set_stall", "_clear_stall", "_power_draw"}

arbre = ast.parse(io.open(SRC, encoding="utf-8").read())
classe = next(n for n in arbre.body
              if isinstance(n, ast.ClassDef) and n.name == "CustomHygrostat")
methodes = [n for n in classe.body
            if isinstance(n, ast.FunctionDef) and n.name in VOULUES]
manquantes = VOULUES - {m.name for m in methodes}
assert not manquantes, f"methodes introuvables : {manquantes}"

horloge = {"t": datetime(2026, 1, 1, tzinfo=timezone.utc)}
echeances = []

class _Dt:
    @staticmethod
    def utcnow(): return horloge["t"]

class _Log:
    def __init__(self): self.lignes = []
    def warning(self, m, *a): self.lignes.append(("warning", m % a if a else m))
    def info(self, m, *a): self.lignes.append(("info", m % a if a else m))
    def exception(self, m, *a): self.lignes.append(("exception", m))

def async_call_later(hass, delai, cb):
    jeton = {"delai": delai, "cb": cb, "annule": False}
    echeances.append(jeton)
    def annuler(): jeton["annule"] = True
    return annuler

def callback(f): return f

STATE_UNAVAILABLE, STATE_UNKNOWN = "unavailable", "unknown"

ns = {"dt_util": _Dt, "_LOGGER": _Log(), "async_call_later": async_call_later,
      "callback": callback, "STATE_UNAVAILABLE": STATE_UNAVAILABLE,
      "STATE_UNKNOWN": STATE_UNKNOWN}
corps = "\n".join(ast.unparse(m) for m in methodes)
exec("class Hygro:\n" + textwrap.indent(corps, "    "), ns)
Hygro = ns["Hygro"]

class Etats:
    def __init__(self): self.d = {}
    def get(self, eid):
        v = self.d.get(eid)
        return None if v is None else type("S", (), {"state": v})()

class Hass:
    def __init__(self): self.states = Etats()

def neuf(watts=None, seuil=10.0, delai=180):
    h = Hygro()
    h.hass = Hass()
    h._plug_only = True
    h._power_sensor_entity_id = "sensor.prise_power"
    h._power_switch_entity_id = "switch.prise"
    h._stall_watts = seuil
    h._stall_delay = timedelta(seconds=delai)
    h._stalled = False
    h._low_power_since = None
    h._stall_remove = None
    h._active = True
    h._ecritures = 0
    h.async_write_ha_state = lambda: setattr(h, "_ecritures", h._ecritures + 1)
    h.hass.states.d["switch.prise"] = "on"
    if watts is not None:
        h.hass.states.d["sensor.prise_power"] = str(watts)
    return h

def avancer(s):
    horloge["t"] += timedelta(seconds=s)

def tirer_echeances():
    """Declenche les echeances non annulees arrivees a terme."""
    global echeances
    a_jouer = [e for e in echeances if not e["annule"]]
    echeances = []
    for e in a_jouer:
        e["cb"](horloge["t"])

def _device_state(h):
    v = h.hass.states.d.get(h._power_switch_entity_id)
    return None if v not in ("on", "off") else v == "on"

Hygro._device_state = property(_device_state)

ok = ko = 0
def verifier(nom, condition):
    global ok, ko
    if condition:
        ok += 1; print(f"  OK   {nom}")
    else:
        ko += 1; print(f"  ECHEC {nom}")

# --- 1. marche normale : forte consommation, aucune inertie
h = neuf(watts=430)
h._evaluate_stall()
verifier("430 W en marche -> aucune inertie", not h._stalled and h._low_power_since is None)

# --- 2. consommation basse, mais le delai n'est pas ecoule
h = neuf(watts=3)
h._evaluate_stall()
verifier("3 W, premiere mesure -> en sursis, pas encore d'inertie",
         not h._stalled and h._low_power_since is not None)
avancer(170); h._evaluate_stall()
verifier("3 W depuis 170 s (< 180) -> toujours pas d'inertie", not h._stalled)

# --- 3. le delai s'ecoule : inertie declaree
avancer(20); h._evaluate_stall()
verifier("3 W depuis 190 s -> inertie declaree", h._stalled)
verifier("l'etat a ete publie", h._ecritures >= 1)

# --- 4. le reservoir est vide, l'appareil repart tout seul
h.hass.states.d["sensor.prise_power"] = "415"
h._evaluate_stall()
verifier("retour a 415 W -> inertie levee", not h._stalled and h._low_power_since is None)

# --- 5. demarrage : 180 s de grace apres la mise sous tension
h = neuf(watts=0)
h._evaluate_stall()               # t0 : le compresseur n'a pas demarre
avancer(60); h._evaluate_stall()
verifier("0 W a 60 s apres allumage -> grace respectee", not h._stalled)
h.hass.states.d["sensor.prise_power"] = "380"
avancer(30); h._evaluate_stall()
verifier("demarrage a 90 s -> aucune fausse alerte", not h._stalled)

# --- 6. appareil qu'on ne croit pas en marche
h = neuf(watts=2); h._active = False
h._evaluate_stall()
verifier("hygrostat a l'arret -> aucun verdict", not h._stalled and h._low_power_since is None)

# --- 7. prise coupee a la main pendant le sursis
h = neuf(watts=2)
h._evaluate_stall()
h.hass.states.d["switch.prise"] = "off"
h._evaluate_stall()
verifier("prise coupee -> sursis annule", h._low_power_since is None)

# --- 8. mesure illisible : aucun verdict, ni dans un sens ni dans l'autre
h = neuf(watts=430)
h._evaluate_stall()
h.hass.states.d["sensor.prise_power"] = "unavailable"
h._evaluate_stall()
verifier("mesure indisponible -> aucun verdict", not h._stalled)

# --- 9. l'echeance declenche l'inertie sans nouvelle mesure de la prise
h = neuf(watts=4)
h._evaluate_stall()
verifier("une echeance a ete armee", any(not e["annule"] for e in echeances))
avancer(180); tirer_echeances()
verifier("echeance tiree -> inertie declaree sans republication", h._stalled)

# --- 10. mode desactive : la detection ne tourne pas
h = neuf(watts=1); h._plug_only = False
h._evaluate_stall()
verifier("hors pilotage par la prise -> detection inerte", not h._stalled)

print(f"\n  {ok} reussis, {ko} echoues")
raise SystemExit(1 if ko else 0)
