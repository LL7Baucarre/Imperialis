# Imperialis — Assistant de partie Warhammer 40k 11e édition

Application web Flask qui **assiste deux joueurs durant une partie de Warhammer 40k 11e édition** :
avancement des phases, affichage des passifs/stats/armes des unités, cartes de mission,
annotations d'actions, lancers de dés (avec le compte par joueur) et fenêtres d'intervention
(Stratagems / Points de Commande) — incluant les données de détachement/stratagems des codex.

## Sources de données

- **Unités, points, stats, capacités, armes, détachements** : [BSData/wh40k-11e](https://github.com/BSData/wh40k-11e)
  (46 fichiers JSON BattleScribe, déjà clonés dans `wh40k-11e/`).
- **Cartes de mission, Force Disposition, Mission Matrix, Layouts** :
  [game-datamissions.com/11th](https://game-datamissions.com/11th) (scrapé en local : les cartes sont
  des PNG + métadonnées JSON-LD serveur ; la matrix 5×5 est extraite en texte structuré).
- **Codex VF** : PDF du dossier `Rules and codex/` (référence hors-ligne, lien par faction).

## Installation

```bash
pip install -r requirements.txt      # Flask uniquement
python -m app.scraper.gdm_scraper    # scrape les missions (missions.json + PNG dans app/static/card_images)
python run.py                        # http://127.0.0.1:5000
```

Le scraper est idempotent et reprenable (`--force` pour tout retélécharger). En l'absence de réseau,
il écrit un `missions.json` de secours (5 decks + matrix) pour que l'app reste utilisable.

## Fonctionnalités

### Pré-partie
- **Constructeur de roster** (par joueur) : choix de la faction (41 factions jouables) et du
  détachement, recherche/filtre des unités par catégorie, ajout avec nombre de modèles, total de points.
- **Choix de mission** : force disposition par joueur → **auto-résolution de la carte primaire** via
  la Mission Matrix 5×5 (surchargeable), secondaires attacker/defender, layouts de terrain (Battlemaster).
- **Démarrage** : choix du premier joueur, récapitulatif.

### En partie
- **Plateau** : battle round X/5, barre de phases (Command → Movement → Shooting → Charge → Fight),
  joueur actif, CP & VP des deux joueurs (ajustables).
- **Carte de phase** : checklist d'actions (rappels génériques des règles core 11e), interventions
  (Stratagems universels + du détachement actif, avec coût CP et fenêtre), presets de dés
  (Advance D6, Charge 2D6, Battle-shock 2D6 vs LD, Hit/Wound/Save ×N, D3, lancer libre),
  table de blessure (en Shooting), zone d'annotation (texte libre, persisté).
- **Rosters latéraux** : unités dépliables en modale (stats, capacités, armes, mots-clés),
  toggle battle-shocked, compteur de modèles (badge demi-effectif).
- **Panneau mission** : images des cartes primaires (j1/j2) + secondaires.
- **Tracker VP** : tableau round×joueur (cumul + delta) + historique détaillé.
- **Référence codex** : détachements (règle + stratagems + enhancements), capacités/traits de faction,
  lien vers le PDF de codex VF local.
- **Avancement** : un clic passe à la phase/joueur/round suivant ; CP gagnés automatiquement au début
  de chaque Command phase (les deux joueurs, +1) ; fin automatique après le round 5.

### Persistance
SQLite (`imperialis.db`) : parties, joueurs, rosters/unités, missions, VP/CP logs, annotations, dés.

## Architecture

```
app/
  config.py / db.py / models.py / factory.py / helpers.py
  data/
    bsdata.py          # loader BSData -> UnitCard/FactionData/Detachment (+ cache)
    missions.py        # lecture missions.json + resolve_primary_card (matrix)
    phases.py          # machine à états 11e + checklists/interventions/presets dés
    _selftest*.py      # auto-tests des moteurs
  scraper/gdm_scraper.py   # scrape game-datamissions.com -> missions.json + PNG
  routes/  setup.py  game.py  api.py
  templates/  base, home, setup_*, play, tracker, reference, unit_modal, macros
  static/  css/app.css  js/app.js
run.py  requirements.txt
```

## Tests

```bash
python -m app.data._selftest          # loader BSData (Intercessor 80pts, Gladius, etc.)
python -m app.data._selftest_missions # scraper + matrix (Determined Acquisition, etc.)
python -m app.data._selftest_phases   # machine à états (cycle 5 rounds)
```

## Limitations actuelles (MVP)

- Attachement Leaders/Support, résolution complète des loadouts/Enhancements, transport détaillé :
  non gérés (les stats principales et capacités des unités sont chargées).
- Les stratagems/enhancements spécifiques par détachement peuvent être incomplets dans BSData 11e ;
  les Stratagems universaux couvrent les fenêtres d'intervention. Boutons +/- CP pour ajuster.
- Import de roster BattleScribe : non implémenté (constructeur intégré uniquement).