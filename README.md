# Custom Hygrostat

Un hygrostat pour Home Assistant dérivé du `generic_hygrostat`, mais adapté à un cas d'usage spécifique :

- **Déshumidificateur uniquement** — la logique de régulation est inversée par rapport à un humidificateur.
- **Pas d'interrupteur** — l'allumage et l'extinction de l'appareil sont remplacés par des **séquences d'actions** (prise connectée, commande IR, notification, etc.), éditables dans l'UI.
- **Marche forcée temporisée (boost)** — un mode `boost` force l'appareil en marche pendant une durée configurable, puis repasse en régulation normale.
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
| Durée de la marche forcée | Durée du mode `boost` |
| Condition d'activation | Template optionnel ; `false` = appareil coupé (vide = toujours `true`) |
| Condition d'erreur | Template optionnel ; `true` = appareil coupé (vide = toujours `false`) |

## Fonctionnement de la régulation

L'appareil **démarre** quand `humidité ≥ cible + tolérance humide` et **s'arrête** quand `humidité ≤ cible − tolérance sèche`. Entre les deux, il conserve son état (hystérésis).

Le mode `boost` ignore la régulation, force la marche pour la durée configurée, puis revient automatiquement en mode `normal`.

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

Quand l'appareil est verrouillé : coupure immédiate (actions d'extinction), un `boost` en cours est annulé et la régulation est suspendue. Au déverrouillage, la régulation reprend normalement.

Exemple — condition d'erreur pour couper quand le réservoir est plein, sans automatisation :

```jinja
{{ is_state('binary_sensor.dryfy_cave_nw_reservoir', 'on') }}
```

Nuance : si le capteur passe `unavailable`, `is_state(..., 'on')` rend `false` → pas d'erreur, l'appareil continue. Pour couper aussi sur capteur indisponible (fail-safe) : `{{ not is_state('binary_sensor.dryfy_cave_nw_reservoir', 'off') }}`.

## Licence

MIT
