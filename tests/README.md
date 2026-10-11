# Bancs d'essai

Le composant tourne dans Home Assistant, qui n'est pas installable ici. Ces
scripts contournent la difficulte sans rien dupliquer : ils LISENT le source de
`humidifier.py`, en extraient les methodes visees par `ast`, et les executent
avec des doublures minimales (horloge, journal, echeances, registre d'etats).

Ce qui est joue est donc le code reel du composant, pas une copie qui
divergerait au premier correctif. Une methode renommee fait echouer le script
immediatement, sur un message explicite.

    python3 tests/essai_inertie.py

Code de retour 0 si tout passe, 1 sinon.

| Script | Couvre |
|---|---|
| `essai_inertie.py` | Detection d'un appareil sous tension et inerte en pilotage par la prise : seuil, delai de demarrage, levee automatique, prise coupee a la main, mesure illisible, echeance. |
