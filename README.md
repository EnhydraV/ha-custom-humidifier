# Custom Hygrostat

Un hygrostat pour Home Assistant dérivé du `generic_hygrostat`, mais adapté à un cas d'usage spécifique :

- **Déshumidificateur uniquement** — la logique de régulation est inversée par rapport à un humidificateur.
- **Pas d'interrupteur** — l'allumage et l'extinction de l'appareil sont remplacés par des **séquences d'actions** (prise connectée, commande IR, notification, etc.), éditables dans l'UI.
- **Marche forcée temporisée (boost)** — un mode `boost` force l'appareil en marche pendant une durée configurable, puis repasse en régulation normale.
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
| Tolérance humide | Démarrage quand humidité ≥ cible + tolérance humide |
| Tolérance sèche | Arrêt quand humidité ≤ cible − tolérance sèche |
| Humidité min / max | Bornes réglables de la consigne |
| Durée min de cycle | Empêche les cycles marche/arrêt trop rapprochés |
| Durée de la marche forcée | Durée du mode `boost` |

## Fonctionnement de la régulation

L'appareil **démarre** quand `humidité ≥ cible + tolérance humide` et **s'arrête** quand `humidité ≤ cible − tolérance sèche`. Entre les deux, il conserve son état (hystérésis).

Le mode `boost` ignore la régulation, force la marche pour la durée configurée, puis revient automatiquement en mode `normal`.

## Licence

MIT
