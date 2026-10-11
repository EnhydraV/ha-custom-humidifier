"""Source d'humidite selon le mode, sur le VRAI code de humidifier.py.

Meme principe que essai_inertie.py : les methodes sont extraites du source par
ast et executees avec des doublures. Ce qui est verifie ici, c'est qu'en
pilotage par la prise la regulation n'utilise QUE le capteur externe.
"""
import ast, io, os, textwrap

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "..", "custom_components", "custom_hygrostat", "humidifier.py")
VOULUES = {"_async_device_changed", "_update_secondary", "_recompute_humidity",
           "_update_humidity"}

arbre = ast.parse(io.open(SRC, encoding="utf-8").read())
classe = next(n for n in arbre.body
              if isinstance(n, ast.ClassDef) and n.name == "CustomHygrostat")
methodes = [n for n in classe.body
            if isinstance(n, ast.FunctionDef) and n.name in VOULUES]
manquantes = VOULUES - {m.name for m in methodes}
assert not manquantes, f"methodes introuvables : {manquantes}"

class _Log:
    def warning(self, m, *a): pass
    def info(self, m, *a): pass
    def exception(self, m, *a): pass

def callback(f): return f
STATE_UNAVAILABLE, STATE_UNKNOWN = "unavailable", "unknown"

ns = {"_LOGGER": _Log(), "callback": callback,
      "STATE_UNAVAILABLE": STATE_UNAVAILABLE, "STATE_UNKNOWN": STATE_UNKNOWN}
exec("class Hygro:\n" + textwrap.indent(
    "\n".join(ast.unparse(m) for m in methodes), "    "), ns)
Hygro = ns["Hygro"]

# Collaborateurs hors sujet, neutralises
for nom in ("_arm_device_offline", "_clear_device_offline", "_input_ready",
            "_evaluate_stall", "async_write_ha_state", "_async_control",
            "_async_handle_manual_switch"):
    setattr(Hygro, nom, lambda self, *a, **k: None)
Hygro._in_startup_grace = property(lambda self: False)

class Etat:
    def __init__(self, etat, **attrs):
        self.state = etat
        self.attributes = attrs

class Hass:
    def async_create_task(self, coro): return None

def neuf(plug_only, primaire=60.0):
    h = Hygro()
    h.hass = Hass()
    h._plug_only = plug_only
    h._active = False
    h._cur_humidity = None
    h._primary_humidity = None
    h._secondary_humidity = None
    h._device_offline = False
    h._device_offline_remove = None
    h._update_humidity(primaire)
    return h

def evenement(nouveau, ancien=None):
    return type("E", (), {"data": {"new_state": nouveau, "old_state": ancien}})()

ok = ko = 0
def verifier(nom, condition, detail=""):
    global ok, ko
    if condition:
        ok += 1; print(f"  OK   {nom}")
    else:
        ko += 1; print(f"  ECHEC {nom} {detail}")

# --- 1. mode normal : le capteur interne de l'appareil entre dans la moyenne
h = neuf(plug_only=False, primaire=60.0)
h._async_device_changed(evenement(Etat("on", current_humidity=50.0)))
verifier("appareil en reseau : moyenne des deux capteurs (60 et 50 -> 55)",
         h._cur_humidity == 55.0, f"obtenu {h._cur_humidity}")

# --- 2. pilotage par la prise : une prise bavarde ne pollue PAS la regulation
h = neuf(plug_only=True, primaire=60.0)
h._async_device_changed(evenement(Etat("on", current_humidity=50.0)))
verifier("pilotage par la prise : seul le capteur externe compte (60)",
         h._cur_humidity == 60.0 and h._secondary_humidity is None,
         f"obtenu {h._cur_humidity} / secondaire {h._secondary_humidity}")

# --- 3. prise ordinaire, sans attribut d'humidite : meme resultat
h = neuf(plug_only=True, primaire=58.0)
h._async_device_changed(evenement(Etat("on")))
verifier("prise sans attribut : regulation sur 58",
         h._cur_humidity == 58.0, f"obtenu {h._cur_humidity}")

# --- 4. le capteur externe reste la seule source quand il change
h._update_humidity(47.5)
verifier("nouvelle mesure externe prise en compte (47.5)",
         h._cur_humidity == 47.5, f"obtenu {h._cur_humidity}")

# --- 5. capteur externe illisible : plus aucune valeur, donc aucune regulation
h._update_humidity("bof")
verifier("capteur externe illisible : aucune humidite retenue",
         h._cur_humidity is None, f"obtenu {h._cur_humidity}")

# --- 6. en mode normal, un capteur interne illisible laisse le principal seul
h = neuf(plug_only=False, primaire=62.0)
h._async_device_changed(evenement(Etat("on", current_humidity="n/a")))
verifier("capteur interne illisible : repli sur le principal (62)",
         h._cur_humidity == 62.0, f"obtenu {h._cur_humidity}")

# --- 7. en mode normal, appareil indisponible : le principal seul
h = neuf(plug_only=False, primaire=55.0)
h._async_device_changed(evenement(Etat("unavailable", current_humidity=40.0)))
verifier("appareil indisponible : son humidite est ecartee (55)",
         h._cur_humidity == 55.0, f"obtenu {h._cur_humidity}")

print(f"\n  {ok} reussis, {ko} echoues")
raise SystemExit(1 if ko else 0)
