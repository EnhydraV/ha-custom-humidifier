# HANDOFF — Custom Hygrostat

Journal de bord du projet, pour reprise dans une nouvelle session (humaine ou Claude).
Dernière mise à jour : 2026-07-14.

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

- **Installé dans une vraie instance HA le 2026-07-10** (Python 3.14) : le config
  flow initial passe (entrée créée), l'ouverture de l'options flow plantait
  (`AttributeError: property 'config_entry' ... has no setter`) — corrigé, voir
  problèmes connus. Aucun test automatisé.
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
- **Moyenne avec le capteur interne (2026-07-10, remaniée le jour même)** : le
  champ `secondary_sensor` séparé a été FUSIONNÉ dans l'entité déshumidificateur
  (`device_entity`, voir plus bas) : son attribut `current_humidity` sert de
  lecture secondaire. `_cur_humidity` = moyenne arrondie à 0,1 des lectures
  disponibles (`_recompute_humidity`) ; interne indisponible/illisible/absente →
  None → repli sur le principal seul. Asymétrie assumée : le principal ignore
  les événements `unavailable` (garde la dernière valeur, cf. problème connu
  n°5), l'interne est écartée de la moyenne. Attributs : `primary_humidity`,
  `secondary_humidity`, `current_humidity` (valeur effective).
- Hystérésis inversée (déshumidificateur) :
  - démarre quand `humidité >= cible + wet_tolerance`
  - s'arrête quand `humidité <= cible - dry_tolerance`
  - entre les deux : conserve l'état.
- `min_cycle_duration` : anti court-cyclage, vérifié dans `_async_control()` sauf si
  `force=True` (turn_on/off manuel, changement de consigne, fin de boost, démarrage).
- **Conditions d'activation et d'erreur (ajoutées le 2026-07-10)** : deux champs
  optionnels `enable_template` (bloque si `false`, vide = `true`) et
  `error_template` (bloque si `true`, vide = `false`). Autorisation de RÉGULATION :
  `_enabled` (property) = `_enable_ok and not _error`. Suivi réactif des deux via
  un seul `async_track_template_result` ; le callback dispatch par identité
  d'objet Template (`update.template is self._enable_template`).
  **Hiérarchie vs boost (précisée le 2026-07-10)** : l'ERREUR coupe tout
  (`_async_interlock_off` : timer annulé, mode normal, appareil off) et le boost
  est refusé tant qu'elle est active (`if self._error` dans start/engage_boost et
  la détection manuelle). L'ACTIVATION `false` ne suspend que la régulation
  normale (`_async_suspend` : appareil off, boost intact) — le boost l'ignore et
  peut démarrer/continuer pendant. Sortie de boost (`_async_leave_boost`, partagé
  par end_boost et set_mode normal) : si `_enabled` false → appareil coupé
  explicitement (sinon il resterait en marche, la régulation étant suspendue),
  sinon `_async_control(force=True)`. Retour de `_enabled` à `true` hors boost :
  `_async_resume`. Template en erreur de rendu : warning + dernier état connu.
  Attributs exposés : `enabled` (autorisation de régulation), `error_active`.
  Icône : le boost passe avant l'état « activation false ».
  Cas d'usage d'origine : remplacer l'automatisation « Cave NW » — condition
  d'erreur `{{ is_state('binary_sensor.dryfy_cave_nw_reservoir', 'on') }}`
  (réservoir plein → arrêt).
- **Entité de consigne (ajoutée le 2026-07-10)** : champ optionnel `target_entity`
  (`input_number` / `number` / `sensor`). Suivie via
  `async_track_state_change_event` + lecture initiale au démarrage ; valeur bornée
  min/max (`_update_target`). `async_set_humidity` : si l'entité est pilotable
  (`input_number`/`number`), écrit dedans via `set_value` (la valeur revient par le
  suivi d'état — synchro bidirectionnelle) ; si `sensor`, réglage ignoré + warning.
  Si configurée, elle prime sur la consigne restaurée (`RestoreEntity`).
  Piège traité dans le config flow : champ vidé → `setdefault(None)` avant
  sauvegarde, sinon la fusion `{**data, **options}` ressuscite l'ancienne valeur
  (champ déclaré avec `suggested_value`, pas de `default`).
- **Boost (remanié le 2026-07-10)** : le minuteur interne (`boost_duration` +
  `async_call_later`) a été SUPPRIMÉ au profit d'une entité `timer` optionnelle
  (`boost_timer`). Avec timer : `async_set_mode("boost")` appelle `timer.start`,
  et c'est le suivi d'état du timer (`_async_boost_timer_changed`) qui engage
  (`active` → `_async_engage_boost`) ou termine (autre état → `_async_end_boost`)
  le boost — le timer fait foi, y compris démarré/annulé de l'extérieur. Retour
  en `normal`, extinction de l'entité ou verrouillage template →
  `_async_cancel_boost_timer` (timer.cancel). Au démarrage, l'état du timer
  restauré par HA prime sur le mode restauré (un boost survit donc au restart).
  Sans timer : marche forcée SANS limite de durée, jusqu'au retour manuel en
  `normal` (mode boost restauré → ré-engagé). `_async_control` retourne
  immédiatement tant que le mode est `boost`.
- Restauration après redémarrage (`RestoreEntity`) : état on/off, consigne
  (attribut `humidity`), mode. Au démarrage de HA, lecture du capteur puis
  `_async_control(force=True)` (bloqué par la période de grâce, voir ci-dessous).
- **Période de grâce au démarrage (ajoutée le 2026-07-14)** : au restart de HA,
  les entités se réhydratent dans le désordre → régulation qui claque on/off et
  device_entity revenant de `unavailable` pris pour une action manuelle (boost
  fantôme / blocage 2 h). Nouveau champ `startup_delay` (secondes, défaut 120,
  0 = désactivé, `DEFAULT_STARTUP_DELAY_SECONDS`). Armée UNIQUEMENT lors d'un
  vrai démarrage (`EVENT_HOMEASSISTANT_START`, via `_async_startup_after_boot`),
  PAS au reload d'options (hass déjà `running`). Pendant la grâce
  (`_startup_grace_until` non None, property `_in_startup_grace`) :
  `_async_control` retourne immédiatement (même avec `force=True`), et les
  changements on/off de `device_entity` resynchronisent `_active` silencieusement
  (ni boost ni manual hold — donc une VRAIE action manuelle pendant la grâce est
  ignorée, assumé). À l'échéance (`async_call_later`) : `_async_control(force=True)`
  sur valeurs stabilisées. Restent immédiats : coupures d'erreur/suspend
  (`_async_device_turn_off` direct), `async_turn_off`, engagement du boost
  (timer restauré actif → marche forcée tout de suite). `async_turn_on` de
  l'hygrostat lève la grâce (`_clear_startup_grace`, aussi dans async_on_remove).
  Attribut exposé : `startup_grace_until`. Édge case assumé : fin de boost
  pendant la grâce → l'appareil reste dans son état jusqu'à l'échéance.
- Attributs exposés : `device_active` (l'appareil physique est-il censé tourner),
  `current_humidity`, `boost_active`.
- **Icône dynamique (property `icon`, ajoutée le 2026-07-10)** — MDI intégrés, par
  priorité : entité off → `mdi:air-humidifier-off` ; erreur → `mdi:water-alert` ;
  activation false → `mdi:water-off` ; boost → `mdi:rocket-launch` ; appareil en
  marche → `mdi:air-humidifier` ; veille (régulé, arrêté) → `mdi:water-percent`.
  Attention : une icône personnalisée posée par l'utilisateur dans l'UI fige
  l'icône et masque la dynamique. Pas de logo d'intégration (page Intégrations) :
  il faudrait une PR sur `home-assistant/brands` (`custom_integrations/custom_hygrostat/`).
- **Entité déshumidificateur (ajoutée le 2026-07-10, ex-`device_state_entity`)** :
  champ optionnel `device_entity` (domaine `humidifier` uniquement), double rôle
  via un SEUL tracker (`_async_device_changed`) : capteur interne (attribut
  `current_humidity` → moyenne, à chaque événement y compris attributs seuls) et
  détection de la marche manuelle. ATTENTION : la clé de conf a été renommée
  (`device_state_entity` → `device_entity`) — une entrée configurée avant le
  renommage doit être re-sauvée via les options.
  Détection de la marche manuelle : état réel `on` alors que `_active` est False
  → `_async_handle_manual_switch(True)` → resync `_active`/`_last_switched` puis
  boost (timer démarré) ; si verrouillé, actions d'extinction exécutées à la
  place. État réel `off` alors que `_active` True → resync + annulation
  timer/boost, la régulation reprendra au prochain événement capteur. Au
  démarrage HA : resync silencieuse de `_active` (pas de boost).
- **Blocage post-extinction manuelle (ajouté le 2026-07-10)** : extinction
  manuelle HORS boost → `_set_manual_hold()` : `_manual_off_until` = maintenant +
  `MANUAL_OFF_HOLD` (2 h, constante dans const.py) + `async_call_later` pour la
  relance à l'échéance. Pendant le blocage, `_async_control` refuse uniquement le
  rallumage (la coupure too_dry reste possible). Levé par : boost
  (`_async_engage_boost` → `_clear_manual_hold`, donc aussi rallumage manuel),
  `async_turn_on` de l'entité, ou expiration. Volontairement NON persisté
  (perdu au redémarrage de HA). Attribut exposé : `manual_off_until`.
  Extinction manuelle PENDANT un boost : pas de blocage, comportement inchangé. ANTI-COURSE :
  `_async_device_turn_on/off` mettent à jour `_active` AVANT d'exécuter les
  actions, pour que l'événement d'état résultant de nos propres actions soit
  ignoré (`is_on == self._active` dans le callback).
- Distinction importante : `_state` = l'hygrostat (l'entité) est actif ;
  `_active` = l'appareil physique tourne. L'entité peut être "on" avec l'appareil
  arrêté (humidité sous la cible).

## Config flow

- Un seul step, schéma commun config/options (`_schema(defaults)`).
- Capteur filtré sur `sensor` + device class `humidity`.
- Validation (factorisée dans `_validate()`) : `min_humidity < max_humidity`
  (`humidity_range`) et syntaxe des deux templates (`invalid_template`).
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
2. ~~**Options flow planté en prod**~~ **CORRIGÉ le 2026-07-10** : depuis
   HA 2024.11, `OptionsFlow.config_entry` est une property en lecture seule
   fournie par le framework ; l'assignation `self.config_entry = config_entry`
   dans `__init__` levait `AttributeError ... no setter` à l'ouverture des
   options. Fix : `__init__` supprimé, `CustomHygrostatOptionsFlow()` sans
   argument, `self.config_entry` utilisé tel quel. Détecté au premier test réel.
3. ~~`_async_device_turn_on(bypass_cycle=True)` : paramètre jamais utilisé~~
   **RETIRÉ le 2026-07-10** lors du remaniement du boost.
4. Fin de boost : `_async_end_boost` repasse par `_async_control(force=True)`, donc
   ignore `min_cycle_duration`. Voulu ? À confirmer, sinon un boost court suivi d'un
   arrêt immédiat peut faire claquer l'appareil deux fois coup sur coup.
5. Capteur qui passe `unavailable`/`unknown` : on ignore l'événement mais on garde la
   dernière humidité connue et l'appareil reste dans son état courant, potentiellement
   allumé indéfiniment. Le `generic_hygrostat` du core a un `sensor_stale_duration`
   pour ça — à envisager.
6. `iot_class: local_polling` dans le manifest alors que l'entité est
   `should_poll = False` et purement event-driven → `calculated` serait plus honnête.
7. Aucun test. Au minimum : tests du config flow et de l'hystérésis avec
   `pytest-homeassistant-custom-component`.
8. Pas de CI (validation hassfest + HACS action seraient bienvenues avant publication).

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

## Divers

- Le README contient un exemple de carte Lovelace `mushroom-template-card`
  (section « Exemple de carte Mushroom ») basée uniquement sur les attributs de
  l'entité ; l'ordre des branches suit les priorités erreur > off > boost >
  désactivé > régulation. À tenir à jour si les attributs changent.

## Reprise rapide

- Pas de dépendances à installer, pas de build : c'est du Python pur chargé par HA.
- Pour tester en vrai : copier `custom_components/custom_hygrostat/` dans le
  `config/custom_components/` d'une instance HA (ou monter le repo), redémarrer,
  ajouter l'intégration. Le point 1 (domaine) est corrigé mais jamais validé en
  conditions réelles : c'est la première chose à vérifier.
