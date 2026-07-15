# Custom Hygrostat

Un hygrostat pour Home Assistant dérivé du `generic_hygrostat`, mais adapté à un cas d'usage spécifique :

- **Déshumidificateur uniquement** — la logique de régulation est inversée par rapport à un humidificateur.
- **Pas d'interrupteur** — l'allumage et l'extinction de l'appareil sont remplacés par des **séquences d'actions** (prise connectée, commande IR, notification, etc.), éditables dans l'UI.
- **Marche forcée (boost)** — un mode `boost` force l'appareil en marche. Piloté par une entité `timer` optionnelle (timer actif = boost, restauré après redémarrage de HA) ; sans timer, la marche forcée dure jusqu'au retour manuel en mode `normal`.
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
| Actions à l'allumage | Séquence exécutée quand le déshumidificateur doit démarrer |
| Actions à l'extinction | Séquence exécutée quand il doit s'arrêter |
| Humidité cible | Consigne d'humidité (%) |
| Entité de consigne | `input_number`, `number` ou `sensor` optionnel qui pilote la consigne |
| Tolérance humide | Démarrage quand humidité ≥ cible + tolérance humide |
| Tolérance sèche | Arrêt quand humidité ≤ cible − tolérance sèche |
| Humidité min / max | Bornes réglables de la consigne |
| Durée min de cycle | Empêche les cycles marche/arrêt trop rapprochés |
| Délai de stabilisation au démarrage | Période de grâce après un redémarrage de HA pendant laquelle l'appareil n'est ni allumé ni éteint (défaut 120 s, 0 = désactivé) |
| Timer de marche forcée | Entité `timer` optionnelle qui pilote le mode `boost` |
| Entité déshumidificateur | Entité `humidifier` optionnelle du fabricant : capteur interne (moyenné) + détection manuelle |
| Condition d'activation | Template optionnel ; `false` = appareil coupé (vide = toujours `true`) |
| Condition d'erreur | Template optionnel ; `true` = appareil coupé (vide = toujours `false`) |

## Fonctionnement de la régulation

L'appareil **démarre** quand `humidité ≥ cible + tolérance humide` et **s'arrête** quand `humidité ≤ cible − tolérance sèche`. Entre les deux, il conserve son état (hystérésis).

L'état `on`/`off` de l'entité reflète la **marche réelle de l'appareil** (déshumidification en cours ou non) : la régulation, elle, tourne en permanence — il n'y a pas d'interrupteur pour la désarmer, les conditions d'activation/erreur suffisent. Les services `humidifier.turn_on` / `turn_off` (et le toggle des cartes) agissent comme le bouton physique de l'appareil : `turn_on` déclenche une marche forcée (boost), `turn_off` arrête l'appareil et, hors boost, bloque la relance automatique pendant 2 h.

L'humidité utilisée est celle du capteur principal, ou la **moyenne** avec le capteur interne de l'appareil si une entité déshumidificateur est configurée (lecture de son attribut `current_humidity`). Si le capteur interne est indisponible ou illisible, le principal seul fait foi. Les deux lectures sont exposées dans les attributs `primary_humidity` et `secondary_humidity`, la valeur effective dans `current_humidity`.

### Marche forcée (boost)

Le mode `boost` ignore la régulation et force la marche de l'appareil.

Avec une **entité `timer`** configurée (créez un helper Timer avec la durée voulue) :

- passer l'hygrostat en mode `boost` (ou `humidifier.turn_on`) démarre le timer ; repasser en `normal` (ou `humidifier.turn_off`, ou un verrouillage par la condition d'erreur) l'annule ;
- démarrer/annuler le timer par ailleurs (automatisation, dashboard) engage/termine aussi le boost — le timer fait foi ;
- à expiration du timer, retour automatique en régulation normale ;
- le timer étant restauré par HA, un boost en cours survit à un redémarrage.

Sans timer configuré, le mode `boost` est une marche forcée sans limite de durée : elle dure jusqu'au retour manuel en mode `normal`.

### Détection de la marche manuelle

L'hygrostat pilote l'appareil à l'aveugle via les actions : il ne sait pas ce que fait réellement l'appareil. En configurant l'**entité déshumidificateur** du fabricant, il compare l'état réel (`on`/`off`) à ce qu'il croit :

- **Allumage inattendu** (quelqu'un a démarré l'appareil à la main) → interprété comme une demande de marche forcée : passage en mode `boost` et démarrage du timer. Si l'hygrostat est verrouillé (condition d'erreur/activation), la marche est refusée : les actions d'extinction sont exécutées.
- **Extinction inattendue hors boost** → la régulation est bloquée pendant **2 h** : l'appareil ne sera pas relancé automatiquement avant l'échéance (attribut `manual_off_until`). `humidifier.turn_off` sur l'hygrostat produit le même blocage. Il est levé par un boost (y compris un rallumage manuel ou `humidifier.turn_on`) ou à l'expiration, et ne survit pas à un redémarrage de HA.
- **Extinction inattendue pendant un boost** → sortie du boost et resynchronisation ; la régulation reprend la main au prochain changement d'humidité (durée min de cycle respectée).
- **Au démarrage de HA**, l'état réel de l'appareil resynchronise l'hygrostat (sans déclencher de boost).

### Stabilisation au démarrage

Au redémarrage de Home Assistant, les entités se réhydratent dans le désordre : le capteur, le capteur interne, la consigne et les templates peuvent faire varier rapidement la décision de régulation, et l'entité déshumidificateur qui revient de `unavailable` risque d'être prise pour une action manuelle.

Pendant le **délai de stabilisation** (configurable, défaut 120 s) démarré à l'événement *Home Assistant started* :

- la régulation n'allume ni n'éteint l'appareil ; à l'échéance, un contrôle forcé applique la décision sur des valeurs stabilisées (attribut `startup_grace_until`) ;
- les changements d'état de l'entité déshumidificateur resynchronisent l'hygrostat **silencieusement** : pas de boost fantôme ni de blocage 2 h au démarrage ;
- les coupures de sécurité restent immédiates : condition d'erreur, `humidifier.turn_off` ;
- le boost n'est pas concerné (un timer restauré ré-engage la marche forcée immédiatement) ;
- `humidifier.turn_on` sur l'hygrostat lève le délai et engage la marche forcée (action explicite de l'utilisateur).

Le délai ne s'applique qu'à un vrai démarrage de HA, pas au rechargement de l'intégration (modification des options).

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

## Exemple de carte Mushroom

Nécessite [Mushroom](https://github.com/piitaya/lovelace-mushroom) (via HACS). À coller dans une carte **Manuel** du dashboard ; adaptez `entity` et `primary`. Toutes les informations viennent des attributs de l'hygrostat, aucune autre entité à référencer.

```yaml
type: custom:mushroom-template-card
entity: humidifier.cave_nw
primary: Cave NW
secondary: |-
  {% if state_attr(entity, 'error_active') %}
    Réservoir plein
  {% elif state_attr(entity, 'boost_active') %}
    Marche forcée - {{ state_attr(entity, 'current_humidity') }}%
  {% elif not state_attr(entity, 'enabled') %}
    Désactivé
  {% elif state_attr(entity, 'manual_off_until') %}
    Arrêt manuel - {{ state_attr(entity, 'current_humidity') }}%
  {% elif is_state(entity, 'on') %}
    En marche - {{ state_attr(entity, 'current_humidity') }}% → {{ state_attr(entity, 'humidity') }}%
  {% else %}
    En veille - {{ state_attr(entity, 'current_humidity') }}%
  {% endif %}
icon: |-
  {% if state_attr(entity, 'error_active') %}
    mdi:water-alert
  {% elif state_attr(entity, 'boost_active') %}
    mdi:rocket-launch
  {% elif not state_attr(entity, 'enabled') %}
    mdi:water-off
  {% elif is_state(entity, 'on') %}
    mdi:air-humidifier
  {% else %}
    mdi:water-percent
  {% endif %}
color: |-
  {% if state_attr(entity, 'error_active') %}
    red
  {% elif state_attr(entity, 'boost_active') %}
    purple
  {% elif not state_attr(entity, 'enabled') %}
    orange
  {% elif state_attr(entity, 'manual_off_until') %}
    grey
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

L'ordre des branches reflète les priorités de l'intégration : erreur > boost (qui ignore la condition d'activation) > désactivé > arrêt manuel > régulation. L'état `on`/`off` de l'entité étant la marche réelle de l'appareil, le `tap_action: toggle` agit comme son bouton physique : arrêt (avec blocage 2 h) s'il tourne, marche forcée sinon.

## Licence

MIT
