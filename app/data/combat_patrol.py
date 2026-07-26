"""Combat Patrol ("Patrouille") game mode data for Imperialis.

Summarizes, in this project's own words, the rules from the Combat Patrol
missions booklet the user added locally (``Rules and codex/combatpatrol_rules.pdf``,
not redistributed — see the copyright constraints elsewhere in this project).
This module contains NO copied Games Workshop mission/card text, only factual
mechanical summaries (same approach as ``app/data/phases.py`` for the core
rules), plus mission *titles* (proper nouns, used as identifiers like any
mission name shown elsewhere in the app).

Combat Patrol is a small-scale, no-list-building format: each player brings
a fixed "Patrol" (typically the contents of a Combat Patrol box) and its
associated datasheets rather than a points-built army. Battles last 5 rounds
on a 44" x 30" battlefield and are decided by the 6 missions below.
"""
from __future__ import annotations

BATTLEFIELD_SIZE = '44" x 30"'

# --- Pré-bataille : séquence d'une partie de Patrouille (paraphrasée) -----
SEQUENCE_STEPS = [
    "Choisir sa Patrouille (le contenu d'une boîte Combat Patrol, ou une force "
    "équivalente) et son Optimisation : chaque Patrouille propose une "
    "Optimisation « par défaut » et une « optionnelle » qui améliore une unité "
    "(typiquement le Seigneur de Guerre) ; annoncer son choix avant de jouer.",
    "Déterminer la mission : choisir une des 6 missions de Patrouille "
    "ci-dessous, ou en tirer une au hasard (1D6).",
    "Créer le champ de bataille : zone rectangulaire de 44\" x 30\", en plaçant "
    "le terrain et les pions d'objectif indiqués par la mission choisie.",
    "Déterminer l'Attaquant et le Défenseur : jet de dé, le gagnant choisit "
    "son camp (et donc sa zone de déploiement).",
    "Déclarer secrètement, dans l'ordre : les unités qui utilisent l'aptitude "
    "Escouades de Patrouille (division en unités plus petites), les "
    "attachements Leader/Garde du corps, les embarquements en Transport, et "
    "les unités qui commencent en Réserve.",
    "Déployer les armées tour à tour, en commençant par le Défenseur.",
    "Déterminer qui joue le premier tour (jet de dé).",
    "Résoudre les règles de pré-bataille (ex. Éclaireurs), en commençant par "
    "le joueur qui a le premier tour.",
    "Jouer 5 rounds de bataille. Round 1 : aucune Réserve n'arrive. Une "
    "Réserve non arrivée avant la fin du round 3 (et toute unité embarquée à "
    "son bord) compte comme détruite.",
    "Fin de partie : le joueur avec le plus de PdV gagne (égalité possible). "
    "Une Patrouille entièrement peinte au standard « Paré au Combat » "
    "rapporte 10 PdV bonus à son joueur.",
]

# --- Règle spécifique Patrouille, commune à toutes les missions -----------
SECURE_OBJECTIVES_RULE = (
    "Sécuriser les pions d'objectif : en fin de chaque phase de Commandement, "
    "si le joueur actif contrôle un pion d'objectif et a au moins une unité "
    "de Ligne (Battleline) non Ébranlée à portée de ce pion, il le sécurise. "
    "Un pion sécurisé reste sous son contrôle même sans figurine à portée, "
    "jusqu'à ce que l'adversaire le contrôle à la fin d'une phase de "
    "Commandement ultérieure."
)

# --- Les 6 missions de Patrouille -----------------------------------------
# rule_text / objective_text sont des résumés mécaniques (nos propres mots) ;
# battlefield_note renvoie au livret pour le schéma de déploiement précis
# (les mesures exactes de placement des pions ne sont pas reproduites ici).
MISSIONS = [
    {
        "name": "Choc de Patrouilles",
        "page": 7,
        "rule_name": "Extraire les Renseignements",
        "rule_text": (
            "À partir du round 2, à sa phase de Commandement, le joueur actif "
            "peut désigner un pion d'objectif qu'il contrôle pour en extraire "
            "les données. S'il le fait et que son Seigneur de Guerre est sur "
            "le champ de bataille (ou embarqué dans un Transport présent), il "
            "gagne 1 PC. Chaque pion ne peut être choisi qu'une seule fois "
            "pour toute la partie, par l'un ou l'autre joueur."
        ),
        "objective_name": "Prendre et Tenir",
        "objective_text": (
            "Rounds 2 à 4 : à la fin de sa phase de Commandement, le joueur "
            "actif marque 5 PdV par pion d'objectif qu'il contrôle (max 15 "
            "PdV/tour). Round 5 : le premier joueur marque comme d'habitude ; "
            "le second joueur marque en fin de TOUR (pas en fin de phase de "
            "Commandement)."
        ),
        "battlefield_note": "Voir schéma p.7 : zones de déploiement profondes, 4 pions d'objectif.",
    },
    {
        "name": "Récupération d'Archéotech",
        "page": 8,
        "rule_name": "Cellules Énergétiques Irradiées",
        "rule_text": (
            "Deux pions du No Man's Land disparaissent en cours de partie : "
            "au début du round 3, le Défenseur désigne au hasard un pion du "
            "No Man's Land (« Gamma ») ; au début du round 4, Gamma est "
            "retiré du champ de bataille et l'Attaquant désigne au hasard un "
            "des pions restants du No Man's Land (« Bêta ») ; au début du "
            "round 5, Bêta est à son tour retiré."
        ),
        "objective_name": "Récupérer l'Archéotech",
        "objective_text": (
            "Rounds 2 à 5 : 5 PdV par pion d'objectif contrôlé en fin de "
            "phase de Commandement (max 15 PdV/tour). En fin de partie : "
            "+10 PdV si vous contrôlez le dernier pion restant du No Man's Land."
        ),
        "battlefield_note": "Voir schéma p.8 : 2 pions retirés progressivement du No Man's Land.",
    },
    {
        "name": "Poste Avancé",
        "page": 9,
        "rule_name": "Saboter les Communications Ennemies",
        "rule_text": (
            "En fin de tour, si le joueur actif contrôle le pion d'objectif "
            "situé dans la zone de déploiement adverse, son adversaire ne "
            "peut plus utiliser le Stratagème Command Re-Roll jusqu'à la fin "
            "de la partie."
        ),
        "objective_name": "Terrain Vital",
        "objective_text": (
            "Rounds 2 à 4 : en fin de phase de Commandement, 5 PdV par pion "
            "du No Man's Land contrôlé, +10 PdV si vous contrôlez le pion en "
            "zone de déploiement adverse (max 15 PdV/tour au total). Round 5 : "
            "le second joueur marque en fin de TOUR plutôt qu'en fin de phase "
            "de Commandement."
        ),
        "battlefield_note": "Voir schéma p.9 : un pion isolé dans chaque zone de déploiement.",
    },
    {
        "name": "Terre Brûlée",
        "page": 10,
        "rule_name": "Raser et Détruire",
        "rule_text": (
            "À partir du round 2, en début de phase de Commandement, s'il "
            "reste au moins 2 pions d'objectif sur le champ de bataille, le "
            "joueur actif peut raser (retirer définitivement) 1 pion qu'il "
            "contrôle — sauf s'il y a une unité ennemie à 3\" de ce pion, et "
            "sauf le pion A pour l'Attaquant / le pion B pour le Défenseur "
            "(pions protégés pour chaque camp)."
        ),
        "objective_name": "Raser et Détruire",
        "objective_text": (
            "Rounds 2 à 4 : en fin de phase de Commandement, 5 PdV si vous "
            "contrôlez au moins un pion, +5 PdV si vous en contrôlez plus que "
            "l'adversaire, +10 PdV si vous avez rasé un pion ce tour. Round 5 : "
            "le second joueur marque en fin de TOUR plutôt qu'en fin de phase "
            "de Commandement."
        ),
        "battlefield_note": "Voir schéma p.10 : pions A et B protégés, chacun réservé à un camp.",
    },
    {
        "name": "Coup de Balai",
        "page": 11,
        "rule_name": "Lignes de Ravitaillement",
        "rule_text": (
            "En début de phase de Commandement, si le joueur actif contrôle "
            "le pion situé dans SA PROPRE zone de déploiement, il jette 1D6 : "
            "sur 4+ il gagne 1 PC."
        ),
        "objective_name": "Cibles Prioritaires",
        "objective_text": (
            "Rounds 2 à 4 : 5 PdV par pion d'objectif contrôlé en fin de "
            "phase de Commandement (max 15 PdV/tour). En fin de partie : "
            "l'Attaquant marque 5 PdV s'il contrôle le pion C et 10 PdV s'il "
            "contrôle le pion D ; le Défenseur marque 5 PdV s'il contrôle le "
            "pion B et 10 PdV s'il contrôle le pion A."
        ),
        "battlefield_note": "Voir schéma p.11 : 4 pions nommés A/B/C/D, deux dans chaque moitié.",
    },
    {
        "name": "Démonstration de Force",
        "page": 12,
        "rule_name": "Briser Leur Esprit / Revendiquer les Sites",
        "rule_text": (
            "Le Stratagème Insane Bravery (Courage Insensé) ne peut cibler "
            "une unité qu'à moins de 6\" de son propre Seigneur de Guerre. "
            "Les pions du No Man's Land sont des « sites symboliques » : en "
            "fin de phase de Commandement, si le joueur actif contrôle un "
            "site ET a une figurine Personnage à portée, il le revendique ; "
            "le site reste revendiqué tant qu'au moins une figurine du même "
            "joueur reste à portée."
        ),
        "objective_name": "Sites Symboliques",
        "objective_text": (
            "Rounds 2 à 4 : en fin de phase de Commandement, 5 PdV pour "
            "chacune des conditions remplies : contrôler au moins un pion, "
            "en contrôler au moins deux, avoir au moins un site symbolique "
            "revendiqué, avoir le même site revendiqué par la même figurine "
            "depuis au moins deux tours consécutifs. Round 5 : le second "
            "joueur marque en fin de TOUR plutôt qu'en fin de phase de "
            "Commandement."
        ),
        "battlefield_note": "Voir schéma p.12 : pions du No Man's Land = sites symboliques.",
    },
]


def get_mission(name: str) -> dict | None:
    """Return a mission dict by name (case-insensitive), or None."""
    key = (name or "").strip().lower()
    for m in MISSIONS:
        if m["name"].lower() == key:
            return m
    return None


def mission_names() -> list[str]:
    return [m["name"] for m in MISSIONS]


__all__ = [
    "BATTLEFIELD_SIZE",
    "SEQUENCE_STEPS",
    "SECURE_OBJECTIVES_RULE",
    "MISSIONS",
    "get_mission",
    "mission_names",
]
