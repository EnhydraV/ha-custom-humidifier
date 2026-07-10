# HANDOFF — Custom Hygrostat

Journal de bord du projet, pour reprise dans une nouvelle session (humaine ou Claude).
Dernière mise à jour : 2026-07-10.

## Besoin initial (verbatim)

> Dans Home Assistant, j'aimerais étendre les hygrostats génériques par un truc
> spécifique à mon cas :
> - uniquement déshumidificateur
> - l'interrupteur est remplacé par des actions quand on allume et quand on éteint
> - un timer permet de mettre en marche forcée l'appareil
> - on garde les réglages concernant le capteur d'humidité et ses seuils

## C'est quoi

Intégration custom Home Assistant (type `helper`, installable via HACS) : un hygrostat
**déshumidificateur uniquement**, dérivé dans l'esprit du `generic_hygrostat` du core,
mais avec deux différences majeures :

1. **Pas d'entité switch pilotée** : l'allumage/extinction de l'appareil passe par des
   **séquences d'actions** arbitraires (`Script` HA), éditables dans l'UI via
   `ActionSelector` — prise connectée, commande IR, notification, peu importe.
2. **Mode `boost`** : marche forcée temporisée qui court-circuite la régulation pendant
   une durée configurable, puis retour automatique en mode `normal`.

Tout se configure dans l'UI (config flow + options flow), zéro YAML.

## État actuel

- Code écrit et structuré, **jamais testé dans un vrai Home Assistant** à ma
  connaissance. Aucun test automatisé.
- Deux commits "initial commit" sur `main`, arbre propre.
- `hacs.json` cible HA `2026.0.0` minimum ; manifest en `0.1.0`.
- Repo destiné à être publié comme dépôt custom HACS
  (`github.com/EnhydraV/ha-custom-humidifier` d'après le manifest).

## Structure

```
custom_components/custom_hygrostat/
├── __init__.py       # setup/unload de la config entry + reload sur update des options
├── const.py          # DOMAIN, clés de conf, valeurs par défaut
├── config_flow.py    # config flow + options flow (schéma partagé via _schema())
├── humidifier.py     # l'entité CustomHygrostat (toute la logique)
├── manifest.json
├── strings.json      # libellés (rédigés en français)
└── translations/     # en.json, fr.json
```

## Logique de régulation (humidifier.py)

- `CustomHygrostat(HumidifierEntity, RestoreEntity)`, device class `DEHUMIDIFIER`,
  feature `MODES` (`normal` / `boost`).
- Hystérésis inversée (déshumidificateur) :
  - démarre quand `humidité >= cible + wet_tolerance`
  - s'arrête quand `humidité <= cible - dry_tolerance`
  - entre les deux : conserve l'état.
- `min_cycle_duration` : anti court-cyclage, vérifié dans `_async_control()` sauf si
  `force=True` (turn_on/off manuel, changement de consigne, fin de boost, démarrage).
- **Condition d'activation (ajoutée le 2026-07-10)** : champ optionnel
  `enable_template` (TemplateSelector). Suivi réactif via
  `async_track_template_result` + `TrackTemplate`. Quand le rendu passe à `false`
  (`result_as_boolean`) : boost annulé, appareil coupé (`_async_interlock_off`,
  ignore min_cycle — c'est un verrouillage), régulation suspendue
  (`_async_control` retourne tôt) et boost refusé. Retour à `true` :
  `_async_control(force=True)`. Template en erreur : warning + on garde le
  dernier état connu. Vide/absent : toujours `true`. Attribut exposé : `enabled`.
  Cas d'usage d'origine : remplacer l'automatisation « Cave NW » qui coupait
  l'entité quand `binary_sensor.dryfy_cave_nw_reservoir` (réservoir plein)
  était `on` → template `{{ is_state('binary_sensor.dryfy_cave_nw_reservoir', 'off') }}`.
- Boost : `async_set_mode("boost")` force la marche via `_async_device_turn_on()`,
  arme un `async_call_later` de `boost_duration` minutes ; à échéance, retour en
  `normal` + `_async_control(force=True)`. `_async_control` retourne immédiatement
  tant que le mode est `boost`. Éteindre l'entité annule le boost.
- Restauration après redémarrage (`RestoreEntity`) : état on/off, consigne
  (attribut `humidity`), mode. Au démarrage de HA, lecture du capteur puis
  `_async_control(force=True)`.
- Attributs exposés : `device_active` (l'appareil physique est-il censé tourner),
  `current_humidity`, `boost_active`.
- Distinction importante : `_state` = l'hygrostat (l'entité) est actif ;
  `_active` = l'appareil physique tourne. L'entité peut être "on" avec l'appareil
  arrêté (humidité sous la cible).

## Config flow

- Un seul step, schéma commun config/options (`_schema(defaults)`).
- Capteur filtré sur `sensor` + device class `humidity`.
- Validation (factorisée dans `_validate()`) : `min_humidity < max_humidity`
  (`humidity_range`) et syntaxe du template d'activation (`invalid_template`).
- `unique_id` dérivé du nom slugifié → deux hygrostats ne peuvent pas porter le
  même nom (`already_configured`).
- Options flow : mêmes champs, pré-remplis avec `{**entry.data, **entry.options}` ;
  la sauvegarde déclenche un reload complet de l'entry (listener dans `__init__.py`).

## Problèmes connus / à faire (par ordre de gravité)

1. ~~**BUG bloquant — incohérence de domaine**~~ **CORRIGÉ le 2026-07-10** :
   `manifest.json` déclarait `"domain": "custom_humidifier"` alors que `const.py`
   avait `DOMAIN = "custom_hygrostat"` → le config flow s'enregistrait sous un
   domaine que HA ne cherchait pas. Harmonisé sur `custom_hygrostat` (nommage
   user-facing déjà partout) : dossier renommé `custom_components/custom_hygrostat/`,
   manifest (`domain` + `name`) et `hacs.json` alignés. Les URLs GitHub du manifest
   pointent toujours vers `ha-custom-humidifier` (nom du repo, inchangé). Pas encore
   validé dans une vraie instance HA.
2. `_async_device_turn_on(bypass_cycle=True)` : le paramètre `bypass_cycle` n'est
   **jamais utilisé** dans le corps de la méthode. Inoffensif (le check min_cycle est
   dans `_async_control`, que le boost ne traverse pas), mais c'est du code mort qui
   sème le doute — soit l'implémenter, soit le retirer.
3. Fin de boost : `_async_end_boost` repasse par `_async_control(force=True)`, donc
   ignore `min_cycle_duration`. Voulu ? À confirmer, sinon un boost court suivi d'un
   arrêt immédiat peut faire claquer l'appareil deux fois coup sur coup.
4. Capteur qui passe `unavailable`/`unknown` : on ignore l'événement mais on garde la
   dernière humidité connue et l'appareil reste dans son état courant, potentiellement
   allumé indéfiniment. Le `generic_hygrostat` du core a un `sensor_stale_duration`
   pour ça — à envisager.
5. `iot_class: local_polling` dans le manifest alors que l'entité est
   `should_poll = False` et purement event-driven → `calculated` serait plus honnête.
6. Aucun test. Au minimum : tests du config flow et de l'hystérésis avec
   `pytest-homeassistant-custom-component`.
7. Pas de CI (validation hassfest + HACS action seraient bienvenues avant publication).

## Décisions de conception (le "pourquoi")

- **Actions plutôt que switch** : le cas d'usage réel pilote des appareils sans entité
  switch propre (IR, scénarios). D'où `Script` + `ActionSelector`, ce qui rend
  l'intégration incompatible avec le `generic_hygrostat` du core mais beaucoup plus
  flexible.
- **`integration_type: helper`** : l'hygrostat n'apporte pas de device, il compose des
  entités existantes — il apparaît dans Paramètres → Aides, comme les helpers core.
- **Reload complet sur changement d'options** plutôt que mise à jour à chaud :
  plus simple, et acceptable vu la fréquence des changements de config.
- **Une seule entité par entry** : pas de multi-hygrostat par entrée, on crée
  plusieurs entrées.

## Reprise rapide

- Pas de dépendances à installer, pas de build : c'est du Python pur chargé par HA.
- Pour tester en vrai : copier `custom_components/custom_hygrostat/` dans le
  `config/custom_components/` d'une instance HA (ou monter le repo), redémarrer,
  ajouter l'intégration. Le point 1 (domaine) est corrigé mais jamais validé en
  conditions réelles : c'est la première chose à vérifier.
