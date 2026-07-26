"""Combat resolution math for Warhammer 40k 11e.

Pure functions that turn a weapon profile + a defender's statline into the
target numbers a player needs to roll. No copyrighted rules text — just the
arithmetic of the 11e core mechanics (to-wound table, AP vs save, invulnerable
save) and best-effort parsing of BSData characteristic strings (``"3+"``,
``"D6"``, ``"2D3+1"``…).
"""

from __future__ import annotations

import re


# ---------------------------------------------------------------------------
# Parsing of characteristic strings
# ---------------------------------------------------------------------------

_DICE = re.compile(r"(?:(\d*)\s*D\s*(\d+))|(\d+)")


def parse_value(text) -> int | None:
    """Best-effort integer parse of a characteristic.

    Returns the value for fixed numbers. For dice expressions (``D6``,
    ``2D3``, ``D3+1``) returns the maximum (so the UI can show a worst-case);
    ``None`` if it cannot be parsed.
    """
    if text is None:
        return None
    s = str(text).strip()
    if not s:
        return None
    # Strip trailing annotations like " [Blast]", " (*)".
    s = re.sub(r"\s*\[.*?\]", "", s).strip()
    s = re.sub(r"\*.*$", "", s).strip()
    # Pure number.
    m = re.fullmatch(r"-?\d+", s)
    if m:
        try:
            return int(s)
        except ValueError:
            return None
    # Dice expression like "D6", "2D6", "D3+1", "2D3+1".
    total = 0
    found = False
    for tok in re.findall(r"([+-]?\s*(?:\d*\s*D\s*\d+|\d+))", s):
        t = tok.replace(" ", "")
        sign = -1 if t.startswith("-") else 1
        t = t.lstrip("+-")
        m = re.fullmatch(r"(\d*)D(\d+)", t)
        if m:
            n = int(m.group(1) or 1)
            sides = int(m.group(2))
            total += sign * n * sides  # max value of the dice
            found = True
            continue
        m = re.fullmatch(r"\d+", t)
        if m:
            total += sign * int(t)
            found = True
    return total if found else None


def expected_value(text) -> float | None:
    """Expected (average) value of a characteristic string, for dice
    expressions. ``D6`` -> 3.5, ``2D3`` -> 4, ``D3+1`` -> 2.5, ``4`` -> 4.0."""
    if text is None:
        return None
    s = re.sub(r"\s*\[.*?\]", "", str(text)).strip()
    s = re.sub(r"\*.*$", "", s).strip()
    if re.fullmatch(r"-?\d+", s):
        return float(int(s))
    total = 0.0
    found = False
    for tok in re.findall(r"([+-]?\s*(?:\d*\s*D\s*\d+|\d+))", s):
        t = tok.replace(" ", "")
        sign = -1 if t.startswith("-") else 1
        t = t.lstrip("+-")
        m = re.fullmatch(r"(\d*)D(\d+)", t)
        if m:
            n = int(m.group(1) or 1)
            sides = int(m.group(2))
            total += sign * n * (sides + 1) / 2
            found = True
            continue
        m = re.fullmatch(r"\d+", t)
        if m:
            total += sign * int(t)
            found = True
    return total if found else None


def _save_target(sv_text) -> int | None:
    """``"3+"`` -> 3, ``"4+"`` -> 4, ``"-"``/``None`` -> None."""
    if not sv_text:
        return None
    m = re.search(r"(\d+)\s*\+", str(sv_text))
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# 11e to-wound table
# ---------------------------------------------------------------------------

def to_wound_target(strength: int | None, toughness: int | None) -> int | None:
    """Roll needed (on a D6) to wound, per the 11e wound table.

    * S >= 2*T  -> 2+
    * S > T    -> 3+
    * S == T   -> 4+
    * S < T    -> 5+
    * S <= T/2 -> 6+   (i.e. T >= 2*S)
    """
    if strength is None or toughness is None or toughness <= 0:
        return None
    s, t = strength, toughness
    if s >= 2 * t:
        return 2
    if s > t:
        return 3
    if s == t:
        return 4
    if s * 2 <= t:
        return 6
    return 5  # s < t but s > t/2


# ---------------------------------------------------------------------------
# Save computation (AP vs armour, invulnerable save)
# ---------------------------------------------------------------------------

def best_save(sv_text, ap_text, inv_text):
    """Return a dict describing the defender's save situation.

    ``armour_target``   — armour save target after AP, or None if AP removes it.
    ``invuln_target``   — invulnerable save target, or None.
    ``chosen_target``   — the best (lowest) usable target.
    ``chosen_kind``     — 'armour' | 'invuln' | 'none'
    """
    armour = _save_target(sv_text)
    invuln = _save_target(inv_text)
    ap = parse_value(ap_text)
    # AP is a negative bonus to the attacker: "-1" AP means the defender's
    # armour save gets WORSE by 1 (target increases by 1).
    if armour is not None and ap is not None:
        armour = armour + abs(ap)
        if armour > 6:
            armour = None  # armour save impossible after AP
    chosen = None
    kind = "none"
    if armour is not None and invuln is not None:
        if armour <= invuln:
            chosen, kind = armour, "armour"
        else:
            chosen, kind = invuln, "invuln"
    elif armour is not None:
        chosen, kind = armour, "armour"
    elif invuln is not None:
        chosen, kind = invuln, "invuln"
    return {
        "armour_target": armour,
        "invuln_target": invuln,
        "chosen_target": chosen,
        "chosen_kind": kind,
    }


# ---------------------------------------------------------------------------
# Full attack resolution summary
# ---------------------------------------------------------------------------

def resolve_attack(weapon: dict, defender_stats: dict,
                   num_attackers: int = 1) -> dict:
    """Compute the target numbers for one weapon vs one defender.

    ``weapon``        — a weapon dict (name, type, range, A, S, AP, D, abilities)
                       as stored on a roster unit (``weapons_json``).
    ``defender_stats``— the defender's statline dict (T, Sv, InSv, W).
    ``num_attackers`` — model count (used to scale A when A is per-model; we
                       surface both the raw A and A×attackers).

    Returns a dict with parsed inputs and computed targets + expected outcomes.
    """
    s = parse_value(weapon.get("S"))
    t = parse_value(defender_stats.get("T"))
    ap = weapon.get("AP")
    a_raw = weapon.get("A")
    d_raw = weapon.get("D")

    a_val = parse_value(a_raw)
    a_exp = expected_value(a_raw)
    d_exp = expected_value(d_raw)

    wound_target = to_wound_target(s, t)
    save = best_save(defender_stats.get("Sv"), ap, defender_stats.get("InSv"))
    wounds = parse_value(defender_stats.get("W"))

    # Expected hits/wounds/unsaved per the parsed numbers (educational).
    p_wound = (7 - wound_target) / 6 if wound_target else None
    p_save = ((7 - save["chosen_target"]) / 6
              if save["chosen_target"] else None)
    p_unsaved = (1 - p_save) if p_save is not None else None

    exp_attacks = (a_exp or 0) * num_attackers if a_exp is not None else None
    exp_wounds = None
    exp_unsaved = None
    exp_damage = None
    if exp_attacks is not None and p_wound is not None:
        exp_wounds = exp_attacks * p_wound
    if exp_wounds is not None and p_unsaved is not None:
        exp_unsaved = exp_wounds * p_unsaved
    if exp_unsaved is not None and d_exp is not None:
        exp_damage = exp_unsaved * d_exp

    return {
        "weapon": weapon,
        "S": s, "T": t, "AP": ap,
        "A_raw": a_raw, "A_val": a_val, "A_expected": a_exp,
        "D_raw": d_raw, "D_expected": d_exp,
        "num_attackers": num_attackers,
        "wound_target": wound_target,          # int 2..6 or None
        "wound_target_str": f"{wound_target}+" if wound_target else "—",
        "save": save,
        "save_target_str": (f"{save['chosen_target']}+"
                            if save["chosen_target"] else "—"),
        "defender_wounds": wounds,
        "exp_attacks": exp_attacks,
        "exp_wounds": exp_wounds,
        "exp_unsaved": exp_unsaved,
        "exp_damage": exp_damage,
    }