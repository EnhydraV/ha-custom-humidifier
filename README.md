# Custom Hygrostat

Un hygrostat pour Home Assistant dérivé du `generic_hygrostat`, mais adapté à un cas d'usage spécifique :

- **Déshumidificateur uniquement** — la logique de régulation est inversée par rapport à un humidificateur.
- **Pas d'interrupteur** — l'allumage et l'extinction de l'appareil sont remplacés par des **séquences d'actions** (prise connectée, commande IR, notification, etc.), éditables dans l'UI.
- **Marche forcée (boost)** — un mode `boost` force la **consigne** à une valeur dédiée (défaut 50 %) ; la régulation continue de fonctionner normalement avec cette cible abaissée. Piloté par une entité `timer` optionnelle (timer actif = boost, restauré après redémarrage de HA) ; sans timer, la marche forcée dure jusqu'au retour manuel en mode `normal`.
- **Conditions d'activation et d'erreur (templates)** — deux templates optionnels qui verrouillent l'appareil : la condition d'activation coupe quand elle rend `false`, la condition d'erreur coupe quand elle rend `true` (réservoir plein...). L'appareil ne peut tourner que si activation = `true` **et** erreur = `false`.
- **Réglages capteur conservés** — capteur d'humidité cible, humidité cible, tolérances sèche/humide, plage min/max réglable, durée minimale de cycle.

Tout se configure via l'interface (config flow + options flow). L'intégration est de type `helper` : elle apparaît dans **Paramètres → Appareils et services → Aides**.

## Installation via HACS

1. HACS → menu **⋮** → **Dépôts personnalisés**.
2. Ajoutez l'URL de ce dépôt, catégorie **Integration**.
3. Installez « Custom Hygrostat », puis redémarrez Home Assistant.
4. **Paramètres → Appareils et services → Ajouter une intégration → Custom Hygrostat** (ou via l'onglet *Aides*).

## Configuration

| Champ | Description |
|---|---|
| Nom | Nom de l'entité hygrostat |
| Capteur d'humidité | `sensor` de classe `humidity` |
| Actions à l'allumage | Séquence exécutée quand le déshumidificateur doit démarrer (obligatoire, non vide) |
| Actions à l'extinction | Séquence exécutée quand il doit s'arrêter (obligatoire, non vide) |
| Humidité cible | Consigne d'humidité (%) |
| Entité de consigne | `input_number`, `number` ou `sensor` optionnel qui pilote la consigne |
| Tolérance humide | Démarrage quand humidité ≥ cible + tolérance humide |
| Tolérance sèche | Arrêt quand humidité ≤ cible − tolérance sèche |
| Humidité min / max | Bornes réglables de la consigne |
| Durée min de cycle | Empêche les cycles marche/arrêt trop rapprochés |
| Attente maximale au démarrage | Plafond de l'attente des capteurs après un redémarrage de HA (défaut 120 s, 0 = régulation immédiate) |
| Timer de marche forcée | Entité `timer` optionnelle qui pilote le mode `boost` |
| Consigne en marche forcée | Consigne appliquée pendant le mode `boost` (défaut 50 %) |
| Entité déshumidificateur | Entité `humidifier` optionnelle du fabricant : capteur interne (moyenné) + détection manuelle |
| Prise d'alimentation | `switch` ou `input_boolean` optionnel : coupure de courant automatique quand l'appareil ne répond plus |
| Condition d'activation | Template optionnel ; `false` = appareil coupé (vide = toujours `true`) |
| Condition d'erreur | Template optionnel ; `true` = appareil coupé (vide = toujours `false`) |

## Fonctionnement de la régulation

L'appareil **démarre** quand `humidité ≥ cible + tolérance humide` et **s'arrête** quand `humidité ≤ cible − tolérance sèche`. Entre les deux, il conserve son état (hystérésis).

L'état `on`/`off` de l'entité reflète la **marche réelle de l'appareil** (déshumidification en cours ou non) : la régulation, elle, tourne en permanence — il n'y a pas d'interrupteur pour la désarmer, les conditions d'activation/erreur suffisent. Les services `humidifier.turn_on` / `turn_off` (et le toggle des cartes) agissent comme le bouton physique de l'appareil : `turn_on` déclenche une marche forcée (boost), `turn_off` arrête l'appareil et, hors boost, bloque la relance automatique pendant 2 h.

L'humidité utilisée est celle du capteur principal, ou la **moyenne** avec le capteur interne de l'appareil si une entité déshumidificateur est configurée (lecture de son attribut `current_humidity`). Si le capteur interne est indisponible ou illisible, le principal seul fait foi. Les deux lectures sont exposées dans les attributs `primary_humidity` et `secondary_humidity`, la valeur effective dans `current_humidity`.

### Marche forcée (boost)

Le mode `boost` ne force pas la marche de l'appareil : il **force la consigne** à la valeur « Consigne en marche forcée » (défaut 50 %). La régulation continue de fonctionner normalement — hystérésis, tolérances, durée min de cycle — mais vise cette cible abaissée : l'appareil démarre si l'humidité la dépasse, et s'arrête de lui-même une fois la cible atteinte, même en plein boost. La consigne affichée sur l'entité pendant le boost est la consigne forcée ; la consigne normale est restaurée à la sortie.

Avec une **entité `timer`** configurée (créez un helper Timer avec la durée voulue) :

- passer l'hygrostat en mode `boost` (ou `humidifier.turn_on`) démarre le timer ; repasser en `normal` (ou `humidifier.turn_off`, ou un verrouillage par la condition d'erreur) l'annule ;
- démarrer/annuler le timer par ailleurs (automatisation, dashboard) engage/termine aussi le boost — le timer fait foi ;
- à expiration du timer, retour automatique en régulation normale ;
- le timer étant restauré par HA, un boost en cours survit à un redémarrage.

Sans timer configuré, le mode `boost` est une marche forcée sans limite de durée : elle dure jusqu'au retour manuel en mode `normal`.

### Détection de la marche manuelle

L'hygrostat pilote l'appareil à l'aveugle via les actions : il ne sait pas ce que fait réellement l'appareil. En configurant l'**entité déshumidificateur** du fabricant, il compare l'état réel (`on`/`off`) à ce qu'il croit :

- **Allumage inattendu** (quelqu'un a démarré l'appareil à la main) → l'appareil est laissé en marche, un éventuel blocage 2 h est levé, et la régulation reprend simplement la main : l'appareil sera éteint quand l'humidité passera sous `consigne − tolérance sèche`. Si la condition d'erreur est active, la marche est refusée : les actions d'extinction sont exécutées. (Le passage automatique en mode `boost`, comportement antérieur, est désactivé dans le code.)
- **Extinction inattendue hors boost** → la régulation est bloquée pendant **2 h** : l'appareil ne sera pas relancé automatiquement avant l'échéance (attribut `manual_off_until`). `humidifier.turn_off` sur l'hygrostat produit le même blocage. Il est levé par un rallumage manuel, par un boost (`humidifier.turn_on`, mode `boost`) ou à l'expiration, et ne survit pas à un redémarrage de HA.
- **Extinction inattendue pendant un boost** → sortie du boost et resynchronisation ; la régulation reprend la main au prochain changement d'humidité (durée min de cycle respectée).
- **Au démarrage de HA**, l'état réel de l'appareil resynchronise l'hygrostat (sans déclencher de boost).

### Stabilisation au démarrage

Au redémarrage de Home Assistant, les entités se réhydratent dans le désordre. Décider avec une consigne pas encore chargée ou des templates pas encore évalués donne une mauvaise décision, appliquée à un vrai appareil.

L'hygrostat n'attend donc pas une durée fixe, mais **que chaque entrée configurée ait publié une valeur exploitable** : le capteur d'humidité, l'entité de consigne, l'entité déshumidificateur, et les deux templates. Dès que la dernière est prête, un contrôle forcé applique la décision. En pratique, cela se compte en secondes.

Le champ **Attente maximale au démarrage** (défaut 120 s) n'est qu'un garde-fou : si une entrée ne revient jamais, la régulation reprend quand même à l'échéance, et le journal indique lesquelles manquaient. `0` désactive complètement l'attente.

Pendant cette attente :

- la régulation n'allume ni n'éteint l'appareil (attributs `startup_grace_until` pour l'échéance du garde-fou et `pending_inputs` pour ce qui manque encore) ;
- les changements d'état de l'entité déshumidificateur resynchronisent l'hygrostat **silencieusement** : pas de boost fantôme ni de blocage 2 h au démarrage ;
- les coupures de sécurité restent immédiates : condition d'erreur, `humidifier.turn_off` ;
- le boost n'est pas concerné (un timer restauré ré-engage la marche forcée immédiatement) ;
- `humidifier.turn_on` sur l'hygrostat lève l'attente et engage la marche forcée (action explicite de l'utilisateur).

L'attente ne s'applique qu'à un vrai démarrage de HA, pas au rechargement de l'intégration (modification des options).

Ce qui est restauré d'une session à l'autre, c'est la **consigne** et le **mode**, pas l'humidité mesurée : après une coupure longue, la dernière mesure connue peut dater d'heures, et régler un appareil dessus serait exactement ce que le garde-fou du capteur cherche à éviter.

La consigne est restaurée **même lorsqu'une entité de consigne est configurée**, et c'est important : la valeur restaurée est justement la dernière valeur connue de cette entité, puisqu'elle y est recopiée à chaque changement. Si l'entité n'est pas encore lisible au démarrage, la régulation part donc de la dernière consigne réelle plutôt que du défaut de configuration. Sans cela, une entité illisible au mauvais moment ferait réguler sur une valeur que personne n'a choisie, et rien ne la corrigerait tant que l'entité ne changerait pas de valeur. L'attribut `normal_humidity` expose cette consigne hors boost (l'attribut standard `humidity` affiche celle du boost quand il est engagé).

### Entité de consigne

Si une entité de consigne est configurée, sa valeur (bornée par humidité min/max) devient la consigne de l'hygrostat et est suivie en continu :

- **`input_number` / `number`** : synchronisation bidirectionnelle — régler la consigne sur la carte de l'hygrostat écrit dans l'entité, et modifier l'entité met à jour l'hygrostat.
- **`sensor`** : l'entité commande seule ; le réglage direct sur l'hygrostat est ignoré (warning dans les logs).

Sans entité de consigne, le comportement reste celui d'origine : consigne interne, réglable sur l'entité et restaurée au redémarrage.

### Conditions d'activation et d'erreur

Deux templates optionnels, réévalués à chaque changement des entités qu'ils référencent. L'appareil n'est autorisé à tourner que si **activation = `true` ET erreur = `false`** :

| Template | Coupe l'appareil quand | Si vide |
|---|---|---|
| Condition d'activation | il rend `false` | considéré `true` (jamais bloquant) |
| Condition d'erreur | il rend `true` | considéré `false` (jamais bloquant) |

Les deux conditions n'ont pas le même poids face au mode `boost` :

- **Condition d'erreur `true`** : coupure immédiate de tout (actions d'extinction), **y compris un `boost` en cours** (timer annulé). Le boost est refusé tant que l'erreur est active.
- **Condition d'activation `false`** : suspend uniquement la régulation normale (appareil coupé en mode `normal`). **Le mode `boost` l'ignore** : il peut démarrer et se poursuivre — y compris déclenché par une marche manuelle. À la fin du boost, si l'activation est toujours `false`, l'appareil est coupé.

Au déverrouillage, la régulation reprend normalement.

Exemple — condition d'erreur pour couper quand le réservoir est plein, sans automatisation :

```jinja
{{ is_state('binary_sensor.dryfy_cave_nw_reservoir', 'on') }}
```

Nuance : si le capteur passe `unavailable`, `is_state(..., 'on')` rend `false` → pas d'erreur, l'appareil continue. Pour couper aussi sur capteur indisponible (fail-safe) : `{{ not is_state('binary_sensor.dryfy_cave_nw_reservoir', 'off') }}`.

### Quand l'appareil ne répond plus

L'hygrostat ne peut pas être plus fiable que l'entité qu'il pilote. Trois garde-fous, tous actifs uniquement si le champ **Entité déshumidificateur** est renseigné :

- **Entité indisponible** : si l'entité de l'appareil reste `unavailable` / `unknown` plus de 60 secondes, l'hygrostat se déclare lui aussi indisponible plutôt que d'afficher une marche imaginaire, et cesse de piloter. Il redevient disponible dès que l'appareil republie un état.
- **Aucune action dans le vide** : un allumage est refusé (avec un avertissement dans le journal) tant que l'appareil ne publie pas d'état exploitable, et une séquence d'actions qui échoue remet l'état affiché à sa valeur précédente.
- **Retour de l'appareil = resynchronisation, pas action manuelle** : un état qui réapparaît après `unknown` / `unavailable` n'est jamais interprété comme un geste humain (donc ni blocage de 2 h, ni levée de blocage) ; l'hygrostat se recale silencieusement puis laisse la régulation trancher.

Les coupures de sécurité (condition d'erreur, condition d'activation `false`, `turn_off`) sont envoyées **même si l'hygrostat se croit déjà à l'arrêt**, dès lors que l'appareil, lui, se déclare en marche.

### Redémarrage par coupure de courant

Certains appareils cessent d'accepter les connexions locales et ne reviennent que par une coupure d'alimentation, tout en continuant de répondre au ping et au cloud (le cas est documenté pour tuya-local : [issue #5736](https://github.com/make-all/tuya-local/issues/5736)). Renseignez alors le champ **Prise d'alimentation** avec la prise commandée qui alimente l'appareil : dès qu'il est déclaré injoignable, l'hygrostat coupe le courant 90 secondes puis le rétablit.

Garde-fous :

- **Un seul essai toutes les 2 heures.** Si l'appareil ne revient pas après une coupure, c'est une panne et non un blocage : insister ne ferait que le maltraiter.
- **Rien ne se passe si la prise elle-même est indisponible**, et le champ vide désactive complètement la fonction.
- **90 secondes hors tension**, de quoi réinitialiser l'électronique et laisser la pression du circuit frigorifique s'égaliser avant que le compresseur ne reparte. Ajustez `POWER_CYCLE_OFF_DELAY` dans `const.py` si votre appareil demande davantage.
- Si l'entité est retirée pendant la coupure (rechargement des options, arrêt de HA), **le courant est rendu quand même** : l'appareil ne peut pas rester éteint faute de quelqu'un pour le rallumer.

Attributs exposés : `device_offline` et `last_power_cycle`.

Attention : l'appareil est injoignable, donc son état réel est inconnu au moment de la coupure. Si le vôtre ne redémarre pas seul après un retour de courant, vérifiez son réglage de mémoire d'état (les prises Tuya exposent souvent un `power_outage_memory`).

### Conditions bloquantes : temporisation à la levée

Poser une condition bloquante (erreur `true`, activation `false`) est **immédiat**. La lever demande **60 secondes de stabilité** : un capteur qui clignote (typique d'un appareil qui se reconnecte en boucle) ne relance donc pas la machine à chaque scintillement. Une reprise après blocage respecte aussi la durée minimale de cycle.

### Capteur d'humidité muet

Si le capteur principal passe `unavailable` / `unknown`, sa dernière valeur reste utilisée pendant 30 minutes. Au-delà, elle est abandonnée : la régulation se rabat sur le capteur interne de l'appareil s'il y en a un, et sinon coupe l'appareil plutôt que de le laisser tourner à l'aveugle.

## Exemple de carte Mushroom

Nécessite [Mushroom](https://github.com/piitaya/lovelace-mushroom) (via HACS). À coller dans une carte **Manuel** du dashboard ; adaptez `entity` et `primary`. Toutes les informations viennent des attributs de l'hygrostat, aucune autre entité à référencer.

```yaml
type: custom:mushroom-template-card
entity: humidifier.cave_nw
primary: Cave NW
secondary: |-
  {% if states(entity) in ['unavailable', 'unknown'] %}
    Appareil injoignable
  {% elif state_attr(entity, 'error_active') %}
    Réservoir plein
  {% elif state_attr(entity, 'boost_active') %}
    Marche forcée - {{ state_attr(entity, 'current_humidity') }}% -> {{ state_attr(entity, 'humidity') }}%
  {% elif not state_attr(entity, 'enabled') %}
    Désactivé
  {% elif state_attr(entity, 'manual_off_until') %}
    Arrêt manuel - {{ state_attr(entity, 'current_humidity') }}%
  {% elif is_state(entity, 'on') %}
    En marche - {{ state_attr(entity, 'current_humidity') }}% → {{ state_attr(entity, 'humidity') }}%
  {% else %}
    En veille - {{ state_attr(entity, 'current_humidity') }}% -> {{ state_attr(entity, 'humidity') }}%
  {% endif %}
icon: |-
  {% if states(entity) in ['unavailable', 'unknown'] %}
    mdi:lan-disconnect
  {% elif state_attr(entity, 'error_active') %}
    mdi:water-alert
  {% elif state_attr(entity, 'boost_active') %}
    mdi:rocket-launch
  {% elif not state_attr(entity, 'enabled') %}
    mdi:water-off
  {% elif state_attr(entity, 'manual_off_until') %}
    mdi:air-humidifier-off
  {% elif is_state(entity, 'on') %}
    mdi:air-humidifier
  {% else %}
    mdi:water-percent
  {% endif %}
color: |-
  {% if states(entity) in ['unavailable', 'unknown'] %}
    grey
  {% elif state_attr(entity, 'error_active') %}
    red
  {% elif state_attr(entity, 'boost_active') %}
    purple
  {% elif not state_attr(entity, 'enabled') %}
    orange
  {% elif state_attr(entity, 'manual_off_until') %}
    amber
  {% elif is_state(entity, 'on') %}
    blue
  {% else %}
    green
  {% endif %}
features_position: bottom
icon_tap_action:
  action: more-info
tap_action:
  action: toggle
```

L'ordre des branches reflète les priorités de l'intégration : appareil injoignable > erreur > boost (qui ignore la condition d'activation) > désactivé > arrêt manuel > régulation. L'état `on`/`off` de l'entité étant la marche réelle de l'appareil, le `tap_action: toggle` agit comme son bouton physique : arrêt (avec blocage 2 h) s'il tourne, marche forcée sinon.

## Licence

MIT
