"""Army conformance validator for Warhammer 40k 11e.

Checks a roster (a list of stored unit dicts as returned by
``models.get_units``) against the 11e army-construction rules we can derive
from BSData categories:

* Points total must not exceed the game's points limit.
* Epic Heroes (category ``Epic Hero``) are unique: at most one of each, and
  counted toward the 0-1 per-name limit.
* Other units: at most 3 of the same unit (by name), raised to 6 if the unit is
  ``Battleline``. Dedicated Transports stay at 3.
* A detachment should be selected.
* The roster should not be empty.

This is guidance, not an exhaustive judge — BSData 11e is still maturing and
some edge cases (attachments, Dedicated Transport tagging) may be imperfect.
Every issue carries a severity (``error`` / ``warning`` / ``info``).
"""

from __future__ import annotations

from collections import Counter, defaultdict


def _cats(u: dict) -> set[str]:
    return set(u.get("categories") or [])


def _is_battleline(u: dict) -> bool:
    cats = _cats(u)
    return "Battleline" in cats or "Troops" in cats


def _is_epic_hero(u: dict) -> bool:
    return "Epic Hero" in _cats(u)


def _is_transport(u: dict) -> bool:
    cats = _cats(u)
    return "Dedicated Transport" in cats or "Transport" in cats


def validate_roster(units: list[dict], points_limit: int = 2000,
                    detachment: str | None = None,
                    game_mode: str = "standard") -> list[dict]:
    """Return a list of issue dicts: ``{severity, message}``.

    ``units`` items are the dicts from ``models.get_units`` (with ``name``,
    ``points``, ``categories``, ``models_total``...). ``game_mode`` is
    ``'standard'`` (points-built army) or ``'combat_patrol'`` (Patrouille : la
    composition vient d'une Patrouille à effectif fixe, pas d'un budget de
    points — le contrôle de budget est donc désactivé dans ce mode).
    """
    issues: list[dict] = []

    if not units:
        issues.append({"severity": "warning",
                       "message": "Roster vide — ajoute au moins une unité."})
        return issues

    # --- Points --- (mode Patrouille : pas de budget de points à respecter)
    total = sum(int(u.get("points") or 0) for u in units)
    if game_mode == "combat_patrol":
        issues.append({"severity": "info",
                       "message": f"Mode Patrouille : {total} pts au total — "
                                  f"pas de budget de points à respecter."})
    elif total > points_limit:
        issues.append({
            "severity": "error",
            "message": f"Dépasse le budget : {total} pts > limite {points_limit} pts "
                       f"(−{total - points_limit} pts).",
        })
    elif points_limit - total > points_limit * 0.25 and points_limit > 0:
        issues.append({
            "severity": "info",
            "message": f"Budget utilisé : {total} / {points_limit} pts "
                       f"({points_limit - total} pts restantes).",
        })
    else:
        issues.append({"severity": "info",
                       "message": f"Budget utilisé : {total} / {points_limit} pts."})

    # --- Detachment --- (une Patrouille n'utilise pas de détachement)
    if game_mode != "combat_patrol" and not detachment:
        issues.append({"severity": "warning",
                       "message": "Aucun détachement sélectionné — un détachement "
                                  "est requis en 11e (il définit tes règles et "
                                  "stratagems)."})

    # --- Unit duplication limits (11e army composition) --- (non applicable
    # en Patrouille : la composition vient d'une liste fixe, pas de plafonds
    # de duplication par nom d'unité).
    if game_mode != "combat_patrol":
        # Group by canonical name; Epic Heroes are also tracked individually.
        name_counts: Counter = Counter(u.get("name") or "" for u in units)
        epic_names: set[str] = set()

        for u in units:
            name = u.get("name") or ""
            if _is_epic_hero(u):
                epic_names.add(name)
                if name_counts[name] > 1:
                    issues.append({
                        "severity": "error",
                        "message": f"« {name} » est un Epic Hero : une seule "
                                   f"exemplaire autorisée (×{name_counts[name]}).",
                    })

        # For non-epic units, enforce the per-name cap (6 for Battleline, 3
        # otherwise). Report each name that exceeds once.
        reported: set[str] = set()
        for name, count in name_counts.items():
            if not name or name in epic_names or name in reported:
                continue
            reported.add(name)
            # Find a representative unit to know if it's Battleline/Transport.
            rep = next((u for u in units if (u.get("name") or "") == name), None)
            if rep is None:
                continue
            if _is_battleline(rep):
                cap = 6
                label = "Battleline"
            elif _is_transport(rep):
                cap = 3
                label = "Dedicated Transport"
            else:
                cap = 3
                label = "unité"
            if count > cap:
                issues.append({
                    "severity": "error",
                    "message": f"« {name} » : maximum {cap} ({label}) en 11e — "
                               f"tu en as {count}.",
                })

    # --- Character / Warlord hint ---
    characters = [u for u in units if "Character" in _cats(u)]
    if not characters and units:
        issues.append({"severity": "warning",
                       "message": "Aucun Personnage dans le roster — il te faut "
                                  "un Personnage pour désigner ton Warlord."})

    return issues


def severity_rank(sev: str) -> int:
    return {"error": 0, "warning": 1, "info": 2}.get(sev, 3)