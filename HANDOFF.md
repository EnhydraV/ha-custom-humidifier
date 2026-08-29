# HANDOFF — Custom Hygrostat

Journal de bord du projet, pour reprise dans une nouvelle session (humaine ou Claude).
Dernière mise à jour : 2026-07-20.

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
2. **Mode `boost`** : « marche forcée » temporisée par une entité `timer` — depuis le
   2026-07-20, il ne court-circuite plus la régulation mais force la CONSIGNE
   (défaut 50 %), la régulation faisant le reste.

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
- **Boost (remanié le 2026-07-10, resémantisé le 2026-07-20)** : le minuteur
  interne (`boost_duration` + `async_call_later`) a été SUPPRIMÉ au profit d'une
  entité `timer` optionnelle (`boost_timer`). Avec timer :
  `async_set_mode("boost")` appelle `timer.start`,
  et c'est le suivi d'état du timer (`_async_boost_timer_changed`) qui engage
  (`active` → `_async_engage_boost`) ou termine (autre état → `_async_end_boost`)
  le boost — le timer fait foi, y compris démarré/annulé de l'extérieur. Retour
  en `normal`, extinction de l'entité ou verrouillage template →
  `_async_cancel_boost_timer` (timer.cancel). Au démarrage, l'état du timer
  restauré par HA prime sur le mode restauré (un boost survit donc au restart).
  Sans timer : boost SANS limite de durée, jusqu'au retour manuel en
  `normal` (mode boost restauré → ré-engagé).
  **Consigne forcée (2026-07-20, demande utilisateur)** : le boost ne force
  PLUS la marche de l'appareil ; il force la consigne à `boost_humidity`
  (nouveau champ, `CONF_BOOST_HUMIDITY`, défaut `DEFAULT_BOOST_HUMIDITY` = 50).
  La property `target_humidity` renvoie cette valeur tant que le mode est
  `boost` (la consigne normale, interne ou pilotée par `target_entity`, est
  restaurée à la sortie). `_async_control` ne retourne plus early en boost :
  la régulation tourne pendant le boost avec la consigne effective
  (`self.target_humidity`). Les gardes d'autorisation ont été éclatées :
  `if self._error: return` puis `if not self._enable_ok and mode != boost:
  return` — le boost ignore toujours l'activation mais pas l'erreur.
  `_async_engage_boost` ne fait plus `_async_device_turn_on()` mais
  `_async_control(force=True)`. Conséquences assumées : un boost n'allume
  l'appareil que si humidité > consigne boost + wet_tolerance (un allumage
  manuel avec air déjà sec → rééteint aussitôt par la régulation) ; l'appareil
  s'arrête de lui-même en plein boost une fois `<= boost − dry_tolerance` ;
  pendant la grâce de démarrage, l'engagement du boost n'allume plus
  immédiatement (la régulation appliquera la consigne boost à l'échéance).
- Restauration après redémarrage (`RestoreEntity`) : consigne (attribut
  `humidity`) et mode — PAS l'état on/off, qui reflète la marche réelle et se
  resynchronise via `device_entity` (sinon repart de off). Au démarrage de HA,
  lecture du capteur puis `_async_control(force=True)` (bloqué par la période
  de grâce, voir ci-dessous).
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
  (`_async_device_turn_off` direct), `async_turn_off`. L'engagement du boost
  pendant la grâce ne pilote plus rien depuis le 2026-07-20 (le mode passe à
  `boost` mais la consigne forcée ne s'applique qu'à l'échéance de la grâce,
  via `_async_control`). `async_turn_on` de
  l'hygrostat lève la grâce (`_clear_startup_grace`, aussi dans async_on_remove)
  et engage un boost (sémantique 2026-07-15).
  Attribut exposé : `startup_grace_until`. Édge case assumé : fin de boost
  pendant la grâce → l'appareil reste dans son état jusqu'à l'échéance.
- **État de l'entité = marche réelle (remanié le 2026-07-15)** : `_state`
  (hygrostat armé/désarmé) a été SUPPRIMÉ — plus d'interrupteur de régulation,
  « les règles automatiques suffisent » (demande utilisateur). `is_on` renvoie
  `_active` (l'appareil déshumidifie ou non) ; `_async_device_turn_on/off`
  publient l'état immédiatement (`async_write_ha_state` juste après la mise à
  jour de la croyance, avant les actions). L'attribut `device_active`,
  devenu redondant, a été RETIRÉ (carte du README adaptée : `is_state(entity,
  'on')`, plus de branche « Eteint »). `turn_on`/`turn_off` calqués sur le
  bouton physique : `async_turn_on` → `_async_start_boost()` (+ levée de la
  grâce) ; `async_turn_off` → annulation timer, mode normal, et hors boost
  `_set_manual_hold()` (blocage 2 h) avant coupure — même sémantique que
  l'extinction manuelle détectée. La régulation n'est plus conditionnée qu'aux
  templates, à la grâce, au boost et au blocage manuel.
- Attributs exposés : `current_humidity`, `boost_active` (+ `primary/secondary_humidity`,
  `enabled`, `error_active`, `manual_off_until`, `startup_grace_until`).
- **Icône dynamique (property `icon`, ajoutée le 2026-07-10)** — MDI intégrés, par
  priorité : erreur → `mdi:water-alert` ; boost → `mdi:rocket-launch` ;
  activation false → `mdi:water-off` ; appareil en
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
  → `_async_handle_manual_switch(True)` → resync `_active`/`_last_switched`,
  levée du blocage 2 h éventuel, et c'est tout : la régulation reprend la main
  (extinction quand too_dry). Le passage automatique en boost (comportement
  2026-07-10) a été MIS EN COMMENTAIRE le 2026-07-20 à la demande de
  l'utilisateur (« commenter le code qui allume le mode boost à l'allumage
  manuel ») — le code est encore là, commenté, si on veut le réactiver.
  Si condition d'erreur active, actions d'extinction exécutées à la place.
  État réel `off` alors que `_active` True → resync + annulation
  timer/boost, la régulation reprendra au prochain événement capteur. Au
  démarrage HA : resync silencieuse de `_active` (pas de boost).
- **Blocage post-extinction manuelle (ajouté le 2026-07-10)** : extinction
  manuelle HORS boost → `_set_manual_hold()` : `_manual_off_until` = maintenant +
  `MANUAL_OFF_HOLD` (2 h, constante dans const.py) + `async_call_later` pour la
  relance à l'échéance. `async_turn_off` de l'entité pose le MÊME blocage
  (depuis le 2026-07-15). Pendant le blocage, `_async_control` refuse uniquement le
  rallumage (la coupure too_dry reste possible). Levé par : boost
  (`_async_engage_boost` → `_clear_manual_hold`, donc aussi rallumage manuel et
  `async_turn_on`), ou expiration. Volontairement NON persisté
  (perdu au redémarrage de HA). Attribut exposé : `manual_off_until`.
  Extinction manuelle PENDANT un boost : pas de blocage, comportement inchangé. ANTI-COURSE :
  `_async_device_turn_on/off` mettent à jour `_active` AVANT d'exécuter les
  actions, pour que l'événement d'état résultant de nos propres actions soit
  ignoré (`is_on == self._active` dans le callback).
- Distinction importante (historique) : il existait un `_state` (hygrostat
  armé) distinct de `_active` (appareil qui tourne) — supprimé le 2026-07-15,
  seul `_active` subsiste et porte l'état de l'entité.

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
7. Allumage manuel pendant que la condition d'activation est `false` : la
   régulation étant suspendue (et le boost n'étant plus déclenché depuis le
   2026-07-20), l'appareil tourne sans garde-fou jusqu'au prochain basculement
   du template d'activation (le retour à `true` relance `_async_control`, qui
   l'éteindra si too_dry). La condition d'erreur, elle, refuse toujours la
   marche immédiatement. Assumé pour l'instant.
8. Aucun test. Au minimum : tests du config flow et de l'hystérésis avec
   `pytest-homeassistant-custom-component`.
9. Pas de CI (validation hassfest + HACS action seraient bienvenues avant publication).

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
  (section « Exemple de carte Mushroom ») basée sur l'état et les attributs de
  l'entité ; l'ordre des branches suit les priorités erreur > boost >
  désactivé > arrêt manuel > régulation. À tenir à jour si les attributs
  changent. Une carte copiée avant le 2026-07-15 référence `device_active`
  (attribut supprimé) et une branche « Eteint » : à remplacer.

## Reprise rapide

- Pas de dépendances à installer, pas de build : c'est du Python pur chargé par HA.
- Pour tester en vrai : copier `custom_components/custom_hygrostat/` dans le
  `config/custom_components/` d'une instance HA (ou monter le repo), redémarrer,
  ajouter l'intégration. Le point 1 (domaine) est corrigé mais jamais validé en
  conditions réelles : c'est la première chose à vérifier.

## Diagnostic en production du 2026-08-28 (instance ha.cocodrilo.enhydra.fr)

Session de diagnostic sans modification de code. Sources : API REST HA (states,
history 3 jours, logbook, config des entries via options flow ouvert puis
abandonne), WebSocket `system_log/list`, configs des 91 automations et 41
scripts. HA 2026.8.3, Python 3.14. Quatre entries chargees : DH Salle a manger
d'ete, DH Cave NW, DH Salle de bain, DH SDB NE.

### Contexte materiel (cause racine de la majorite des derapages)

Les quatre appareils reels sont des DryFy pilotes par `tuya_local`, et cette
couche est instable :
- `DryFy SAM d'ete` et `DryFy SDB NE` : entries en `setup_retry`
  (« tuya-local device offline », erreur 914 « check device key or version,
  likely needs a power cycle »). Leurs entites sont `unavailable` depuis au
  moins le 24/08 : les hygrostats DH SAM d'ete et DH SDB NE pilotent le vide
  depuis des jours tout en affichant « en marche ».
- `DryFy SDB` et `DryFy Cave NW` : entries chargees mais l'appareil decroche en
  boucle (539 « Failed to fetch device status / Device Unreachable », 243
  « error reading »). L'entite humidifier passe `unknown` toutes les quelques
  minutes (~50 fois en 3 jours pour Cave NW) puis republie son etat.
- Preuve directe du « marque en marche alors que rien ne tourne » : 480
  warnings `Referenced entities ... are missing or not currently available`
  (dont `humidifier.cave_nw_dryfy_cave_nw`, `fan.dryfy_sdb_ne`). Les actions
  on/off partent dans le vide, l'entite publie quand meme `on`.

### Bugs de configuration cote instance (pas le code)

1. **DH SDB NE : `turn_off_action` VIDE.** L'hygrostat passe a `off` et n'envoie
   rien. Le schema le permet (`vol.Required(..., default=[])` accepte la liste
   vide) : a valider dans `_validate()`.
2. **DH SAM d'ete : `turn_on_action` contient `humidifier.set_mode {mode:
   boost}` ciblant `humidifier.dh_salle_a_manger_d_ete`, soit lui-meme** (les
   trois autres entries ciblent bien le DryFy). Chaque demarrage automatique se
   transforme donc en marche forcee de 1 h a 50 % (visible le 08-25 20:05:42 et
   le 08-27 00:23:55 : `on|normal|60` puis `on|boost|50` dans la meme seconde,
   retour a `normal` exactement 1 h plus tard).
3. **`script.initialisation_deshumidificateurs`** (appele par les automations
   `Presence` ET `Absence`) fait `humidifier.turn_on` sur les 4 hygrostats puis
   `timer.finish` sur 3 des 4 timers. Depuis la resemantisation du 2026-07-15
   (`turn_on` = marche forcee), ce script veut dire « boost puis annule
   aussitot » : les 4 entites claquent on/off dans la meme seconde a chaque
   changement de presence (08-26 09:48:05, 15:57:21, 18:22:15, 08-27 19:43:06).
   Et `timer.marche_forcee_dh_cave_nw` n'est PAS dans la liste des
   `timer.finish` : la cave part en boost 2 h a 50 % a chaque bascule de
   presence (08-25 15:16 -> 18:15, 08-26 09:48 -> 10:47, 15:38 -> 17:57). C'est
   l'explication principale du « en marche alors qu'il devrait pas ».
4. **Templates d'erreur reservoir** du type `{{ is_state('binary_sensor.
   xxx_reservoir','on') }}` : rendent `False` quand le capteur est
   `unavailable`, c'est-a-dire precisement quand l'appareil a decroche (souvent
   parce qu'il s'est arrete, reservoir plein). La securite ne s'applique donc
   pas au pire moment.
5. La consigne est pilotee par `sensor.consigne_deshumidificateurs` (domaine
   `sensor`, donc lecture seule) : `async_set_humidity` est ignore avec un
   warning, la consigne n'est pas reglable depuis l'UI. Sa valeur bouge selon
   l'heure (60 / 75 / 80).

### Faiblesses du code confirmees par la prod (a corriger)

Par gravite decroissante :

1. **La croyance `_active` n'est jamais reconciliee avec la realite.**
   `_async_device_turn_on/off` publient l'etat AVANT de lancer le script, sans
   `try/except` ni verification a posteriori. Script en echec ou entite cible
   indisponible = entite bloquee sur `on` indefiniment. Pistes : refuser d'agir
   (ou passer `available = False`) quand le `device_entity` est indisponible,
   proteger l'execution du script, et re-verifier l'etat reel N secondes apres
   l'action pour resynchroniser.
2. **`_async_device_turn_off` sort tot si `not self._active`** : quand la
   croyance est desynchronisee (appareil reellement en marche, hygrostat qui se
   croit a l'arret), aucune commande d'arret ne part plus jamais, y compris
   l'interlock « reservoir plein ». La securite depend d'une croyance. Il faut
   un chemin `force` pour les coupures de securite, ou se fier a l'etat reel du
   `device_entity`.
3. **Detection « manuelle » trop naive** : tout `on`/`off` du `device_entity`
   qui contredit la croyance est pris pour une action humaine. Avec tuya_local
   qui passe par `unknown`/`unavailable` puis republie, ca donne de faux
   allumages manuels (resync + levee du blocage 2 h) et de fausses extinctions
   manuelles. Cinq blocages 2 h ont ete poses sur DH Cave NW entre le 26 et le
   27 (21:26:09, 00:09:45, 03:34:20, 05:45:55, 07:59:04), chaque fois dans la
   minute suivant un `unknown -> off` du DryFy correle au reservoir. Piste :
   ignorer (ou traiter en resync silencieuse) toute transition venant de
   `unknown`/`unavailable`, n'accepter comme manuelle qu'une transition entre
   deux etats connus, et temporiser.
4. **Aucun anti-rebond sur les templates.** Le binary_sensor reservoir de Cave
   NW oscille `on -> off -> on` en 15 a 20 s a chaque tentative de reconnexion
   (39 transitions en 3 jours). Chaque `off` fugace declenche `_async_resume` ->
   `_async_control(force=True)` -> rallumage alors que le reservoir est toujours
   plein. Il faut une duree de stabilite avant de lever une erreur.
5. **`force=True` distribue trop largement + `min_cycle_duration` a 0 partout**
   (fin de boost, resume, set_humidity, demarrage) : on observe des series
   on/off/on/off en 30 s (08-25 14:38:04 -> 14:38:32, 08-26 10:47:29 ->
   10:48:05). Mauvais pour un compresseur. Le cycle minimum ne devrait etre
   contournable que pour les COUPURES, jamais pour les rallumages.
6. **Spam d'etat / recorder** : le DryFy publie `current_humidity` toutes les
   ~3 s ; `_async_device_changed` recalcule la moyenne, appelle
   `async_write_ha_state()` ET `_async_control()` a chaque evenement, d'ou
   4983 points d'historique en 3 jours pour `humidifier.dh_cave_nw` et une
   humidite effective qui oscille de 0,5 %. N'ecrire que si la valeur arrondie
   change.
7. `Script.async_run(context=self._context)` avec `_context` a `None` : warning
   `Running script requires passing in a context` (constate sur dh_cave_nw et
   dh_sdb_ne). Passer un `Context` construit explicitement.
8. Toujours pas traite : probleme connu n°5 (capteur principal `unavailable` ->
   derniere valeur conservee indefiniment). Les capteurs `sensor.sb_*` sont des
   groupes qui peuvent partir en `unavailable`.
9. Aucune garde anti-boucle : rien n'empeche une action on/off de cibler
   l'hygrostat lui-meme (cf. bug de config n°2), detectable au config flow.

## Correctifs du 2026-08-28 (suite du diagnostic ci-dessus)

Version du manifest passee a **0.2.0**, `iot_class` corrige en `calculated`
(l'entite est event-driven, `should_poll = False`).

### humidifier.py

- **Disponibilite (nouveau)** : property `available`. Si un `device_entity` est
  configure et qu'il reste `unavailable` / `unknown` plus de
  `DEVICE_OFFLINE_GRACE` (60 s), l'hygrostat se declare indisponible au lieu
  d'afficher une marche imaginaire, et `_async_control` ne pilote plus rien.
  Retour a un etat exploitable = disponibilite retablie immediatement.
  Nouvelles properties internes `_device_state` (True/False/None) et
  `_device_reachable`.
- **Plus d'action dans le vide** : `_async_device_turn_on` refuse d'agir (avec
  warning) si l'appareil n'est pas joignable. Les sequences passent par
  `_async_run_action`, qui attrape les exceptions et RETABLIT la croyance
  precedente si l'action a echoue.
- **Coupures de securite inconditionnelles** :
  `_async_device_turn_off(force=True)` envoie les actions d'extinction meme si
  `_active` est deja False, des lors que l'appareil, lui, publie `on`. Utilise
  par `_async_interlock_off`, `_async_suspend`, `_async_leave_boost`,
  `async_turn_off`, l'allumage manuel refuse et le watchdog capteur.
- **Detection manuelle assainie** : une transition qui vient de `unknown` /
  `unavailable` / d'un appareil qui etait hors ligne n'est plus prise pour un
  geste humain (plus de blocage 2 h fantome). Resynchronisation silencieuse,
  puis `_async_control`. Le callback ne reecrit l'etat que si quelque chose a
  reellement change (fin du spam de recorder sur les attributs).
- **Templates temporises** : `_async_templates_changed` a ete eclate en
  `_apply_error` / `_apply_enable`. Poser une condition bloquante est immediat,
  la lever exige `TEMPLATE_CLEAR_DELAY` (60 s) de stabilite
  (`_schedule_template_clear` / `_cancel_template_clear`). Fin des rallumages
  a chaque clignotement du capteur de reservoir.
- **`_async_resume` ne force plus** : une reprise apres blocage respecte la
  duree minimale de cycle. Le contournement du cycle reste reserve aux gestes
  explicites (turn_on, boost, changement de consigne) et au demarrage.
- **Watchdog capteur (probleme connu n°5, traite)** : capteur principal
  `unavailable` / `unknown` pendant `SENSOR_STALE_TIMEOUT` (30 min) -> la
  derniere valeur est abandonnee ; s'il ne reste aucune mesure et que
  l'appareil tourne, il est coupe. Arme uniquement sur un evenement
  d'indisponibilite, jamais sur le silence d'un capteur (pas de faux positif
  sur un capteur qui ne publie que sur changement).
- **Contexte** : `Script.async_run(context=self._context or Context())`, fin du
  warning « Running script requires passing in a context ».

### config_flow.py

- `_validate()` refuse desormais une sequence d'actions VIDE (`empty_action`) et
  une action qui cible l'hygrostat lui-meme (`self_reference`, via
  `_own_entity_ids()` : registre d'entites de l'entry en options,
  `humidifier.<slug du nom>` a la creation). Nouveaux messages dans
  `strings.json`, `translations/fr.json` et `translations/en.json`.

### Cote instance (applique en direct par l'API)

- **Dashboard `lovelace`** : les 4 tuiles mushroom des deshumidificateurs
  etaient restees sur la semantique d'avant le 2026-07-15 (branche `Eteint`
  placee avant tout le reste, donc affichee des que l'appareil ne tournait pas,
  et `device_active` supprime depuis, donc branche « En marche » morte : une
  machine en marche s'affichait « En veille »). Reecrites : appareil
  injoignable > reservoir > boost > desactive > arret manuel (avec l'heure de
  fin) > en marche > en veille, plus le double-tap « marche forcee » ajoute sur
  la tuile Cave NW qui ne l'avait pas. Sauvegarde de l'ancienne configuration
  complete dans `$SUPERCLAUDE_SCRATCH/lovelace-backup-<horodatage>.json`.

### Applique cote instance le 2026-08-28

- **Options des 4 entries** (API config_entries) : action d'extinction ajoutee sur
  DH SDB NE (`humidifier.turn_off` sur `humidifier.dryfy_sdb_ne`, elle etait
  VIDE) ; l'action d'allumage de DH SAM d'ete ne se boostait plus elle-meme
  (`humidifier.set_mode` recible sur `humidifier.bureau_dryfy_sam_d_ete`) ;
  `min_cycle_duration` passe de 0 a 5 min sur les quatre. Anciennes options dans
  `$SUPERCLAUDE_SCRATCH/entries-backup-<horodatage>.json`.
- **`script.initialisation_deshumidificateurs`** : le `humidifier.turn_on` sur les
  4 hygrostats a ete SUPPRIME (il declenchait une marche forcee a chaque bascule
  de presence depuis la resemantisation du 2026-07-15), et le `timer.finish`
  couvre desormais les QUATRE timers, marche forcee de la cave comprise. Ancienne
  version dans `$SUPERCLAUDE_SCRATCH/script-initialisation-deshumidificateurs-<horodatage>.json`.

### Redemarrage par coupure de courant (2026-08-29)

Nouveau champ optionnel `power_switch` (`CONF_POWER_SWITCH`, domaines `switch` /
`input_boolean`) : la prise commandee qui alimente l'appareil. Quand celui-ci est
declare injoignable (mecanisme `_device_offline` du 2026-08-28),
`_async_power_cycle` coupe le courant `POWER_CYCLE_OFF_DELAY` (90 s) puis le
retablit. Garde-fous : un seul essai par `POWER_CYCLE_MIN_INTERVAL` (2 h), abandon
si la prise est elle-meme indisponible, et sur `CancelledError` (retrait de
l'entite pendant la coupure) le courant est rendu quand meme. Attributs exposes :
`device_offline`, `last_power_cycle`.

Le delai de 90 s n'est pas cosmetique : c'est une protection du compresseur (la
pression du circuit frigorifique doit s'egaliser avant le redemarrage), pas
seulement une reinitialisation d'electronique.

Motivation : issue amont **make-all/tuya-local#5736**, ouverte, « Protocol 3.4
device permanently loses local connectivity until power cycle (914 -> 901) ». Le
rapporteur d'origine utilise un deshumidificateur Wood's WDD90 en protocole 3.4,
symptomes identiques : le cloud et le ping continuent de fonctionner, seul le LAN
est mort, et SEUL un power cycle repare. Le mainteneur penche pour un bug de
firmware de l'appareil ; plusieurs contributeurs situent la regression apres
tuya-local 2026.3.3. Voir aussi #5848 (boucle de reception morte sans watchdog),
#5136 et #5347.

### Attente des entrees au demarrage (2026-08-29, remplace la periode de grace)

Constat qui a motive le changement : au redemarrage du 29/08 10:05, le DryFy SAM
d'ete a restaure SON PROPRE etat (on + mode boost) apres son power cycle.
L'hygrostat a resynchronise `_active` sur la realite et affiche donc `on` a 64 %
pour une consigne de 75 -- correct, mais la periode de grace de 120 s a laisse
l'appareil tourner pour rien. Coupure a 10:07:33, exactement a l'echeance.

Le delai FIXE a donc ete remplace par une attente des ENTREES. `_arm_startup_grace`
construit `_pending_inputs` a partir de ce qui est configure (`sensor`, `target`,
`device`, `enable`, `error`) ; chaque callback appelle `_input_ready(<nom>)` quand
il obtient une valeur exploitable, et la derniere levee declenche
`_async_control(force=True)`. En pratique : quelques secondes au lieu de deux
minutes. `_in_startup_grace` vaut desormais `self._pending_inputs is not None`.

`startup_delay` n'est plus qu'un PLAFOND (le libelle du champ a ete change en
consequence dans strings/fr/en) : a l'echeance, la regulation reprend quand meme et
le journal liste les entrees restees muettes. `0` = aucune attente.

Trois pieges traites, a ne pas casser en refactorant :

1. **Templates evalues AVANT `EVENT_HOMEASSISTANT_START`** (`async_refresh()` dans
   `async_added_to_hass`) : leur passage pret serait perdu et l'attente durerait
   jusqu'au plafond. D'ou `_inputs_seen`, alimente par `_input_ready` meme quand
   aucune attente n'est armee, et soustrait du `pending` a l'armement. Si tout a
   deja parle, aucune attente n'est armee du tout.
2. **`_async_device_changed` capture `in_grace` EN TETE de callback**, avant
   `_input_ready("device")`. Sinon lever l'attente sur cette meme entree ferait
   passer le retour de l'appareil pour une action manuelle (boost fantome /
   blocage 2 h) -- exactement ce que la grace devait empecher.
3. **Appareil declare hors ligne** : `_offline` appelle `_input_ready("device")`,
   sinon un appareil muet ferait attendre jusqu'au plafond alors que le verdict
   est deja rendu.

Nouvel attribut de diagnostic : `pending_inputs` (liste triee, `None` hors attente).

Ce qui est restaure reste la consigne et le mode, PAS l'humidite mesuree : apres
une coupure longue elle peut dater d'heures, et reguler dessus est precisement ce
que `SENSOR_STALE_TIMEOUT` cherche a eviter.

### Constats de production du 2026-08-29

- **Code deploye et fonctionnel** : les hygrostats dont l'appareil est hors ligne
  affichent bien `unavailable` au lieu d'inventer un etat.
- **`poll_only` fonctionne** (mis sur DryFy SDB le 28/08). A nuits comparables
  (20h-08h UTC) : 31 coupures / 45,7 min d'indisponibilite AVANT, contre 8
  coupures / 8,6 min APRES. Les longues fenetres (700-1200 s) ont disparu, il ne
  reste que des decrochages de 30 a 110 s, dont la moitie sous les 60 s de grace
  et donc totalement absorbes.
- Le formulaire d'options de tuya_local TESTE la connexion avant d'enregistrer :
  impossible de mettre `poll_only` sur un appareil deja hors ligne (`DryFy Cave
  NW` a ete refuse avec `base: connection`). A refaire quand il sera revenu.
- **Prises reperees** : `switch.ns06` pour Cave NW, `switch.salle_de_bain_ne_lm02`
  pour SDB NE. Rien pour DH Salle de bain ni DH SAM d'ete. LM02 mesure 0,9 W de
  veille (appareil vivant qui refuse le local, cas ideal pour le power cycle) ;
  NS06 mesure 0 W depuis deux jours ET la prise elle-meme decroche en boucle, donc
  le power cycle n'y reglera probablement rien.

### Reste a faire

- Redeployer le code (le champ `power_switch` n'existe pas encore sur l'instance)
  puis renseigner la prise sur DH SDB NE, le cas le plus prometteur.
- Trois DryFy sur quatre sont injoignables (SAM d'ete, SDB NE, et Cave NW depuis
  le 28/08 22h35 UTC) : intervention physique necessaire.
- Option de repli si le power cycle ne suffit pas : retrograder tuya-local en
  2026.3.3 via HACS (menu 3 points -> Redownload -> « Need a different version? »).
  NON VERIFIE sur HA 2026.8.3, un contributeur de l'issue le fait tourner sur
  2026.8.1.
- Templates d'erreur reservoir laisses tels quels : ils rendent `false` quand le
  capteur est `unavailable`. La disponibilite geree dans le code couvre le cas,
  mais un `{{ not is_state('...', 'off') }}` reste une option.
- Toujours aucun test automatise ni CI (problemes connus n°8 et 9).
