"""Warhammer 40k 11th-edition turn/phase state machine + per-phase assist content.

Stdlib-only. Reminders are short factual rule recaps written in this project's
own words. They are NOT Games Workshop mission/card text. Faction stratagems
live in bsdata and are merged by the app via ``phase_assist``.

Verified 11th-edition structure (trusted):
- A game is 5 Battle Rounds. Each round BOTH players take a full turn.
- Each turn = 5 phases in fixed order: Command, Movement, Shooting, Charge, Fight.
- The "first" player (configurable, default 1) takes the first turn each round.
- Command phase: start-of-phase abilities; BOTH players +1 CP (start at 0 CP);
  battle-shock tests for units at/below half strength (2D6 >= Leadership to pass;
  failed shock persists until a successful roll; shocked units have OC 0, cannot
  be targeted by Stratagems, cannot start/complete Actions); command abilities;
  end-of-phase; score objectives.
- Movement: Normal / Advance / Fall Back / Remain Stationary; engagement range
  2" horizontal / 5" vertical; reserves set up wholly within 6" of a board edge
  and >8" from enemies; charges from reserves need 9"; no enemy deployment zone
  before round 3; Fire Overwatch fires at the END of the opponent's Movement phase.
- Shooting: cover -1 to attacker BS; Plunging Fire +1 BS from terrain >=3" high;
  Indirect Fire hits on unmodified 6 (4+ if stationary + spotter);
  Hit -> Wound -> Save -> Damage; one stratagem per unit per phase; crit on
  unmodified 6; unmodified 1 always fails.
- Charge: roll 2D6 FIRST then pick targets within 12"; end closer to a charge
  target, within 1" if possible, engaged if possible; reserves charge needs 9";
  successful chargers gain Fights First.
- Fight: shared Pile-In (active first), then Fights First step (active selects
  first), then remaining combats alternating; Overrun Fight if unengaged when
  selected; attacks Hit -> Wound -> Save -> Damage using WS; shared
  Consolidation (active first).
"""

from __future__ import annotations

# --- Core constants -------------------------------------------------------

PHASES = ["Command", "Movement", "Shooting", "Charge", "Fight"]
ROUNDS = 5

PREGAME_STEPS = [
    "Roll off to determine garrison and which player chooses to deploy first or take the first turn.",
    "Choose deployment zones and place objective markers / objective terrain features as the mission directs.",
    "Draw force disposition cards for both players as required by the mission pack.",
    "Resolve primary mission cards via the mission matrix to set each player's primary objectives.",
    "Reveal warlord traits, arc/secondary selections, and any pre-battle upgrades.",
    "Deploy units in their deployment zone (units with Deep Strike / Ingress / reserves set aside).",
    "Place any models that set up before the first turn but outside a deployment zone, if the mission allows.",
    "Offer the Seize Initiative option to the player going second when applicable.",
    "Resolve any 'at the start of the battle' abilities and begin Battle Round 1, Command phase, first player's turn.",
]


# --- Per-phase assist data ------------------------------------------------

PHASE_DATA = {
    "Command": {
        "title": "Command Phase",
        "subtitle": "Gain CP, test battle-shock, use command abilities, score objectives.",
        "checklist": [
            {"id": "cmd-start", "text": "Resolve any 'start of Command phase' abilities.", "who": "both"},
            {"id": "cmd-cp", "text": "Both players gain 1 Command Point (CP). Players start the game at 0 CP.", "who": "both"},
            {"id": "cmd-shock", "text": "Test battle-shock for each friendly unit at or below half strength: roll 2D6 and meet/exceed Leadership to pass.", "who": "active"},
            {"id": "cmd-shock-fail", "text": "A failed battle-shock persists until a later Command phase produces a successful roll. Battle-shocked units have OC 0, cannot be targeted by Stratagems, and cannot start or complete Actions.", "who": "active"},
            {"id": "cmd-abilities", "text": "Use command abilities, including any detachment command ability the active player wishes to trigger this round.", "who": "active"},
            {"id": "cmd-cards", "text": "Draw / score primary and secondary mission cards as the mission allows.", "who": "active"},
            {"id": "cmd-objectives", "text": "Tally objective points for held objectives and completed mission cards.", "who": "both"},
            {"id": "cmd-end", "text": "Resolve any 'end of Command phase' abilities before moving to the Movement phase.", "who": "both"},
        ],
        "interventions": [
            {"name": "Command Re-Roll", "cp": 1, "window": "Anytime", "owner": "both", "note": "Re-roll a single die roll (hit, wound, save, advance, charge, battle-shock, etc.). One stratagem per unit per phase."},
            {"name": "Insane Bravery", "cp": 1, "window": "Once per battle", "owner": "active", "note": "Auto-pass a single battle-shock test for one unit. Limited to once per battle."},
            {"name": "Epic Challenge", "cp": 1, "window": "Command phase", "owner": "active", "note": "Boost a character's combat profile for a duel. Faction stratagems may add further command-phase windows."},
        ],
    },
    "Movement": {
        "title": "Movement Phase",
        "subtitle": "Move units: Normal, Advance, Fall Back, or Remain Stationary. Reserves arrive; Fire Overwatch fires at end of enemy Movement.",
        "checklist": [
            {"id": "mov-move", "text": "Choose a move type per unit: Normal (up to M\"), Advance (M + D6, no shoot/charge), Fall Back (up to M\", no shoot/charge/start Action), or Remain Stationary.", "who": "active"},
            {"id": "mov-heavy", "text": "Heavy weapons get +1 to hit if the unit moved 3\" or less this phase (including Remaining Stationary).", "who": "active"},
            {"id": "mov-engagement", "text": "Stay clear of engagement range: 2\" horizontal / 5\" vertical of enemy models unless charging or already engaged.", "who": "active"},
            {"id": "mov-reserves", "text": "Set up reserves / Deep Strike / Ingress wholly within 6\" of a board edge and more than 8\" from enemy models.", "who": "active"},
            {"id": "mov-restrict", "text": "No unit may enter the opponent's deployment zone before Battle Round 3 unless a rule explicitly allows it.", "who": "active"},
            {"id": "mov-actions", "text": "Start any Actions that require the unit to remain stationary or not move (Advance / Fall Back units cannot start Actions).", "who": "active"},
            {"id": "mov-overwatch", "text": "End of phase: the opponent may spend 1 CP to Fire Overwatch against one of your units that just moved.", "who": "opponent"},
        ],
        "interventions": [
            {"name": "Fire Overwatch", "cp": 1, "window": "End of enemy Movement phase", "owner": "opponent", "note": "Shoot one of your units at an enemy unit that just moved. Resolves at the very end of the opponent's Movement phase, NOT in their Charge phase."},
            {"name": "Rapid Ingress", "cp": 1, "window": "Movement phase / reserves", "owner": "active", "note": "Bring a reserves unit in outside the normal reserves timing."},
            {"name": "Smokescreen", "cp": 1, "window": "Movement phase", "owner": "active", "note": "Pop smoke for -1 to hit against the unit until your next Movement phase."},
            {"name": "Command Re-Roll", "cp": 1, "window": "Anytime", "owner": "both", "note": "Re-roll the Advance distance die or any other single die."},
        ],
    },
    "Shooting": {
        "title": "Shooting Phase",
        "subtitle": "Resolve attacks: Hit -> Wound -> Save -> Damage. Cover, Plunging Fire, Indirect Fire, and one stratagem per unit per phase.",
        "checklist": [
            {"id": "sho-target", "text": "Select a ranged weapon for each model that may fire. Check line of sight, range, and that the target is a valid enemy unit.", "who": "active"},
            {"id": "sho-modifiers", "text": "Apply hit modifiers: cover gives the attacker -1 BS; Plunging Fire +1 BS if firing from terrain >=3\" high; modifiers stack unless a rule says otherwise.", "who": "active"},
            {"id": "sho-indirect", "text": "Indirect Fire hits on an unmodified 6 (4+ if the firing model was stationary AND has a spotter).", "who": "active"},
            {"id": "sho-hit", "text": "Roll to hit: each attack die equals a hit on the model's BS, applying modifiers. Unmodified 6 is a critical; unmodified 1 always fails.", "who": "active"},
            {"id": "sho-wound", "text": "Roll to wound using the wound table (see reminder). Unmodified 6 is a critical; unmodified 1 always fails.", "who": "active"},
            {"id": "sho-save", "text": "Opponent rolls saves, allocating wounds and applying armour penetration and damage per weapon.", "who": "opponent"},
            {"id": "sho-stratagem", "text": "At most one stratagem per unit per phase. Pick the moment carefully (e.g. before hit, before wound, before damage).", "who": "active"},
            {"id": "sho-actions", "text": "Shooting units may still be completing Actions if the Action allows it; Advancing / Falling Back units generally cannot shoot.", "who": "active"},
        ],
        "interventions": [
            {"name": "Command Re-Roll", "cp": 1, "window": "Anytime", "owner": "both", "note": "Re-roll one hit, wound, save, or damage die. One stratagem per unit per phase."},
            {"name": "Explosives", "cp": 1, "window": "Shooting phase", "owner": "active", "note": "Boost a ranged weapon's damage profile. One stratagem per unit per phase."},
        ],
    },
    "Charge": {
        "title": "Charge Phase",
        "subtitle": "Roll 2D6 first, then pick targets within 12\". Reserves charges need 9\". Successful chargers gain Fights First.",
        "checklist": [
            {"id": "chg-roll", "text": "Roll 2D6 for the charge distance FIRST, before declaring the target unit(s).", "who": "active"},
            {"id": "chg-targets", "text": "Select charge target(s) within 12\" of the charging unit. The unit must end closer to a charge target than it started.", "who": "active"},
            {"id": "chg-engagement", "text": "Move the charger into engagement range (within 1\" horizontally / 5\" vertically) of a target if possible, and engage as many targets as the move allows.", "who": "active"},
            {"id": "chg-reserves", "text": "A unit arriving from reserves this turn must roll 9+ on the 2D6 to complete a charge.", "who": "active"},
            {"id": "chg-fightsfirst", "text": "Successful chargers gain Fights First for the following Fight phase.", "who": "active"},
            {"id": "chg-restrict", "text": "Units that Advanced or Fell Back this turn cannot charge. Units that shot may still charge unless a weapon forbids it.", "who": "active"},
        ],
        "interventions": [
            {"name": "Heroic Intervention", "cp": 2, "window": "Charge phase / Fight phase", "owner": "opponent", "note": "Move a character (and optionally a nearby unit) up to 3\" toward an enemy that just charged or is engaged. 1-2 CP depending on the unit."},
            {"name": "Command Re-Roll", "cp": 1, "window": "Anytime", "owner": "both", "note": "Re-roll one of the 2D6 charge dice. One stratagem per unit per phase."},
        ],
    },
    "Fight": {
        "title": "Fight Phase",
        "subtitle": "Pile-In, Fights First, alternating combats, Overrun Fight, then Consolidation.",
        "checklist": [
            {"id": "fht-pilein", "text": "Shared Pile-In: both players move eligible units up to 3\" toward the nearest enemy. Active player goes first.", "who": "both"},
            {"id": "fht-fightsfirst", "text": "Fights First step: all units with Fights First (including this turn's successful chargers) fight. Active player selects the first unit.", "who": "active"},
            {"id": "fht-remaining", "text": "Remaining combats alternate between players, active player choosing first each time a player selects a unit to fight.", "who": "active"},
            {"id": "fht-overrun", "text": "Overrun Fight: if a selected unit is no longer engaged when picked, it may make an extra pile-in move.", "who": "active"},
            {"id": "fht-attacks", "text": "Resolve melee attacks Hit -> Wound -> Save -> Damage using Weapon Skill (WS). Critical on unmodified 6; unmodified 1 always fails.", "who": "active"},
            {"id": "fht-consolidate", "text": "Shared Consolidation after all combats: each eligible unit moves up to 3\". Active player goes first.", "who": "both"},
            {"id": "fht-hazard", "text": "Resolve any hazardous terrain or end-of-fight triggers as models pile in / consolidate.", "who": "both"},
        ],
        "interventions": [
            {"name": "Counteroffensive", "cp": 2, "window": "Fight phase", "owner": "opponent", "note": "Make an enemy unit fight later than it otherwise would, or interrupt the alternating combat order."},
            {"name": "Heroic Intervention", "cp": 2, "window": "Charge phase / Fight phase", "owner": "opponent", "note": "Move a character and optional nearby unit toward the enemy during the Fight phase."},
            {"name": "Crushing Impact", "cp": 1, "window": "Fight phase", "owner": "active", "note": "Add damage when a charging unit fights for the first time this phase."},
            {"name": "Command Re-Roll", "cp": 1, "window": "Anytime", "owner": "both", "note": "Re-roll one hit, wound, save, or damage die in melee. One stratagem per unit per phase."},
        ],
    },
}


# --- Wound table reminder (fact-only, own words) --------------------------

WOUND_TABLE = [
    {"attacker_str": "S >= 2T", "wound_on": "2+"},
    {"attacker_str": "S > T", "wound_on": "3+"},
    {"attacker_str": "S == T", "wound_on": "4+"},
    {"attacker_str": "S < T", "wound_on": "5+"},
    {"attacker_str": "S <= 0.5T", "wound_on": "6+"},
]


# --- State machine --------------------------------------------------------

def phase_index(name: str) -> int:
    """Return the 0-based index of a phase in :data:`PHASES`."""
    return PHASES.index(name)


def is_last_phase(name: str) -> bool:
    """True if ``name`` is the last phase in :data:`PHASES` (Fight)."""
    return name == PHASES[-1]


def total_steps_for_round() -> int:
    """Number of phase-ticks in one battle round (both players' turns)."""
    return len(PHASES) * 2


def _other_seat(seat: int) -> int:
    return 2 if seat == 1 else 1


def advance_state(round_, phase, active_seat, first_seat=1):
    """Advance the game one phase-tick.

    Returns ``(new_round, new_phase, new_active_seat)`` or ``None`` when the
    game is over (after round 5, the second player's Fight phase).

    The "first" player (``first_seat`` in {1, 2}) takes the first turn of each
    battle round. Within a round, players alternate via the Fight phase:
    first-seat's turn ends -> second-seat's turn -> both have played a full
    turn -> round ticks up.
    """
    if phase not in PHASES:
        raise ValueError(f"Unknown phase: {phase!r}")
    if active_seat not in (1, 2):
        raise ValueError(f"active_seat must be 1 or 2, got {active_seat!r}")
    if first_seat not in (1, 2):
        raise ValueError(f"first_seat must be 1 or 2, got {first_seat!r}")

    idx = PHASES.index(phase)

    # Same-turn advance: not yet the last phase.
    if phase != PHASES[-1]:
        return round_, PHASES[idx + 1], active_seat

    # Fight phase -> switch active player.
    new_seat = _other_seat(active_seat)
    if new_seat == first_seat:
        # We just finished the second player's turn -> a full battle round done.
        new_round = round_ + 1
        if new_round > ROUNDS:
            return None  # game over
        return new_round, PHASES[0], first_seat
    # Switching to the non-first player mid-round -> their turn starts.
    return round_, PHASES[0], new_seat


# --- Phase assist (universal + faction stratagems) ------------------------

# Keywords used to loosely tag universal stratagems by phase. Faction
# stratagems are merged by best-effort keyword match (see ``phase_assist``).
_PHASE_KEYWORDS = {
    "Command": ["command", "cp", "battle-shock", "leadership", "objective", "score"],
    "Movement": ["movement", "move", "reserve", "ingress", "overwatch", "smoke", "advance"],
    "Shooting": ["shoot", "shooting", "ranged", "hit", "wound", "save", "bs", "indirect", "plunging"],
    "Charge": ["charge", "heroic intervention"],
    "Fight": ["fight", "pile", "consolidat", "counter", "overrun", "melee", "crushing"],
}


def _safe_getattr(obj, *names, default=None):
    for n in names:
        try:
            v = getattr(obj, n)
        except Exception:
            continue
        if v is not None:
            return v
    return default


def _iter_faction_stratagems(faction_data):
    """Yield stratagem-like dicts from a loose FactionData object.

    Tolerates many shapes: a list, an object with ``stratagems``, a detachment
    with ``stratagems``, detachments list, or a selected detachment.
    """
    if faction_data is None:
        return
    # Direct list of stratagems.
    if isinstance(faction_data, (list, tuple)):
        for s in faction_data:
            yield s
        return
    # A single stratagem dict.
    if isinstance(faction_data, dict) and ("name" in faction_data or "cp" in faction_data):
        yield faction_data
        return

    stratagems = _safe_getattr(faction_data, "stratagems")
    if stratagems:
        for s in stratagems:
            yield s
        return

    detachment = _safe_getattr(faction_data, "selected_detachment", "detachment")
    if detachment is not None:
        ds = _safe_getattr(detachment, "stratagems")
        if ds:
            for s in ds:
                yield s
            return

    detachments = _safe_getattr(faction_data, "detachments")
    if detachments:
        for d in detachments:
            ds = _safe_getattr(d, "stratagems")
            if ds:
                for s in ds:
                    yield s


def _stratagem_phase_match(stratagem, phase):
    """Best-effort: does this stratagem look relevant to ``phase``?"""
    text_parts = []
    for field in ("name", "window", "note", "description", "phase", "when"):
        try:
            v = _safe_getattr(stratagem, field) if not isinstance(stratagem, dict) else stratagem.get(field)
        except Exception:
            v = None
        if v:
            text_parts.append(str(v).lower())
    text = " ".join(text_parts)
    if not text:
        return False
    for kw in _PHASE_KEYWORDS.get(phase, []):
        if kw in text:
            return True
    return False


# --- Evolutionary, context-aware actions -------------------------------
# Phase timing actions (start / end of phase), written in this project's own
# words. These are the "what to do right now" prompts that adapt to the phase.
_PHASE_TIMINGS = {
    "Command": {
        "start": [
            ("Début de la phase de Command : chaque joueur gagne 1 CP.", "both"),
            ("Résoudre les capacités et effets « au début de la phase de Command ».", "both"),
            ("Tester le battle-shock pour chaque unité amie à ou sous le demi-effectif (2D6 ≥ Command Value).", "active"),
        ],
        "end": [
            ("Comptabiliser les objectifs / cartes de mission déclenchés ce tour.", "both"),
            ("Résoudre les effets « à la fin de la phase de Command ».", "both"),
        ],
    },
    "Movement": {
        "start": [
            ("Pour chaque unité, choisir le type de mouvement : Normal, Advance (M+D6, ni tir ni charge), Fall Back (ni tir ni Action) ou Remain Stationary.", "active"),
            ("Arrivée des réserves / Deep Strike / Ingress : wholly within 6\" d'un bord de table et >8\" des ennemis.", "active"),
        ],
        "end": [
            ("L'adversaire peut dépenser 1 CP pour Fire Overwatch contre une de tes unités qui vient de bouger.", "opponent"),
        ],
    },
    "Shooting": {
        "start": [
            ("Sélectionner une arme de tir par modèle : vérifier ligne de vue, portée et cible valide.", "active"),
            ("Appliquer les modificateurs de touche (couvert -1 BS, Plunging Fire +1 BS, Indirect Fire 6+ / 4+ si fixe + spotter).", "active"),
        ],
        "end": [
            ("Une seule stratagem par unité par phase : choisir le bon moment (avant touche / blessure / dégâts).", "active"),
        ],
    },
    "Charge": {
        "start": [
            ("Lancer 2D6 pour la distance de charge AVANT de choisir la cible.", "active"),
            ("Choisir la/les cible(s) within 12\" ; finir plus proche de la cible qu'au départ.", "active"),
        ],
        "end": [
            ("Les chargeurs réussis gagnent Fights First pour la phase de Fight à venir.", "active"),
        ],
    },
    "Fight": {
        "start": [
            ("Pile-In partagé : déplacer les unités engagées jusqu'à 3\" vers l'ennemi le plus proche (joueur actif d'abord).", "both"),
            ("Étape Fights First : toutes les unités avec Fights First frappent (joueur actif choisit la première).", "active"),
        ],
        "end": [
            ("Consolidation partagée : déplacement jusqu'à 3\" (joueur actif d'abord).", "both"),
        ],
    },
}


def _round_actions(round_):
    """Round-gated reminders (reserves, deployment-zone restrictions)."""
    out = []
    if round_ <= 1:
        out.append(("Round 1 : aucune réserve ne peut arriver ce tour (sauf règle explicite).", "both"))
    if round_ >= 2:
        out.append(("Réserves : arrivée autorisée depuis ce round.", "active"))
    if round_ >= 3:
        out.append(("À partir du round 3 : entrée dans la zone de déploiement adverse autorisée.", "active"))
    if round_ >= 5:
        out.append(("Dernier battle round : vérifier les objectifs de fin de partie / cartes primaires.", "both"))
    return out


# Phase keywords looked for in unit ability descriptions to surface triggers.
_ABILITY_PHASE_KEYWORDS = {
    "Command": ["command phase", "start of your command", "start of the command",
                "end of your command", "battle-shock", "leadership", "objective control",
                "command ability"],
    "Movement": ["movement phase", "start of your movement", "end of your movement",
                 "advance", "fall back", "deep strike", "ingress", "reserves", "overwatch",
                 "remains stationary", "remain stationary"],
    "Shooting": ["shooting phase", "start of your shooting", "end of your shooting",
                 "ranged weapon", "ranged attack", "shoots", "fires", "hit roll",
                 "indirect", "plunging fire"],
    "Charge": ["charge phase", "start of your charge", "end of your charge",
               "declares a charge", "charges", "heroic intervention"],
    "Fight": ["fight phase", "start of your fight", "end of your fight",
              "pile in", "pile-in", "consolidation", "fights first", "melee weapon",
              "weapon skill", "each time this model fights"],
}


def _unit_phase_actions(units, phase):
    """Surface active-player unit abilities that look relevant to ``phase``.

    Returns a list of {id, unit, name, text} dicts (text is a short snippet of
    the ability description). Best-effort keyword match; tolerates any shape.
    """
    if not units:
        return []
    kws = _ABILITY_PHASE_KEYWORDS.get(phase, [])
    out = []
    for u in units:
        if not isinstance(u, dict):
            continue
        uname = u.get("custom_name") or u.get("name") or "Unité"
        abilities = u.get("abilities") or []
        if not isinstance(abilities, list):
            continue
        for ab in abilities:
            if not isinstance(ab, dict):
                continue
            name = ab.get("name") or ""
            desc = ab.get("description") or ab.get("text") or ""
            text = (name + " " + desc).lower()
            if not any(kw in text for kw in kws):
                continue
            out.append({
                "id": f"unit-{u.get('id')}-{name[:12].lower().replace(' ', '-')}",
                "unit": uname,
                "name": name,
                "text": desc.strip(),
                "who": "active",
                "kind": "unit",
            })
    # Cap to a sane number to avoid flooding the panel.
    return out[:12]


def _detachment_rule(faction_data):
    """Best-effort: pull the active detachment's rule text for a reminder."""
    if faction_data is None:
        return None
    det = _safe_getattr(faction_data, "selected_detachment", "detachment")
    if det is not None:
        rule = _safe_getattr(det, "rule")
        if rule:
            return (_safe_getattr(det, "name") or "Détachement"), rule
    detachments = _safe_getattr(faction_data, "detachments")
    if detachments:
        d0 = detachments[0]
        rule = _safe_getattr(d0, "rule")
        if rule:
            return (_safe_getattr(d0, "name") or "Détachement"), rule
    return None


def _merge_faction_stratagems(interventions, seen_names, faction_data, phase, owner):
    """Append phase-relevant faction stratagems to ``interventions``, tagged
    with ``owner`` ('active' or 'opponent'). Dedup by name via ``seen_names``."""
    if faction_data is None:
        return
    try:
        for s in _iter_faction_stratagems(faction_data):
            try:
                if not _stratagem_phase_match(s, phase):
                    continue
            except Exception:
                continue
            if isinstance(s, dict):
                name = s.get("name")
                cp = s.get("cp")
                window = s.get("window")
                note = s.get("note", s.get("description", ""))
            else:
                name = _safe_getattr(s, "name")
                cp = _safe_getattr(s, "cp")
                window = _safe_getattr(s, "window")
                note = _safe_getattr(s, "note", "description") or ""
            if not name or name in seen_names:
                continue
            seen_names.add(name)
            interventions.append({
                "name": name,
                "cp": cp,
                "window": window or "",
                "note": note,
                "owner": owner,
                "source": "faction",
            })
    except Exception:
        pass


def phase_assist(phase, faction_data=None, units=None, round_=1,
                 opponent_faction_data=None):
    """Return a dict combining universal PHASE_DATA with faction stratagems and
    an evolutionary, context-aware ``actions`` list.

    ``units`` is the active player's roster (list of unit dicts with
    ``abilities``), used to surface unit abilities that trigger in this phase.
    ``round_`` is the current battle round (1..5), used for round-gated
    reminders (reserves, deployment-zone restrictions).
    ``faction_data`` is the active player's faction; ``opponent_faction_data``
    is the other player's faction — its phase-relevant stratagems are merged
    too, tagged ``owner='opponent'`` (the opponent can react during the active
    player's turn: Fire Overwatch, Heroic Intervention, Counteroffensive…).

    Each intervention carries an ``owner`` field: 'active', 'opponent', or
    'both' — the UI uses it to debit the right player's CP.

    Result shape::

        {
            "title": str,
            "subtitle": str,
            "checklist": [...],
            "actions": [...],         # evolutionary, context-aware (timing/round/faction/units)
            "interventions": [...],   # universal first, then matched faction
            "detachment_rule": str?,  # active player's detachment rule (if any)
            "wound_table": [...],     # always present (handy for the UI)
        }

    Faction stratagems are filtered best-effort by keyword match on the
    stratagem's name / window / note / description. Anything that fails to
    parse is silently skipped so the UI can keep rendering.
    """
    if phase not in PHASE_DATA:
        raise KeyError(f"No phase data for {phase!r}")
    base = PHASE_DATA[phase]
    interventions = list(base.get("interventions", []))
    # Ensure every universal intervention has an owner (default 'both').
    for iv in interventions:
        if isinstance(iv, dict) and not iv.get("owner"):
            iv["owner"] = "both"

    seen_names = {i.get("name") for i in interventions if isinstance(i, dict)}
    _merge_faction_stratagems(interventions, seen_names, faction_data, phase, "active")
    _merge_faction_stratagems(interventions, seen_names, opponent_faction_data, phase, "opponent")

    # Evolutionary, context-aware actions: phase timing + round-gated +
    # unit-ability triggers + detachment rule reminder.
    actions = []
    timing = _PHASE_TIMINGS.get(phase, {})
    for text, who in timing.get("start", []):
        actions.append({"id": f"tm-start-{phase}", "text": text, "who": who, "kind": "start"})
    for text, who in _round_actions(round_ or 1):
        actions.append({"id": f"round-{round_}-{text[:12]}", "text": text, "who": who, "kind": "round"})
    try:
        actions.extend(_unit_phase_actions(units, phase))
    except Exception:
        pass
    for text, who in timing.get("end", []):
        actions.append({"id": f"tm-end-{phase}", "text": text, "who": who, "kind": "end"})

    det_rule = None
    try:
        det_rule = _detachment_rule(faction_data)
    except Exception:
        det_rule = None

    return {
        "title": base.get("title", phase),
        "subtitle": base.get("subtitle", ""),
        "checklist": list(base.get("checklist", [])),
        "actions": actions,
        "interventions": interventions,
        "detachment_rule": det_rule,
        "wound_table": WOUND_TABLE,
    }