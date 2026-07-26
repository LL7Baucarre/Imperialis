"""Pure-Python, dependency-free loader for BSData (BattleScribe) WH40k 11e
faction catalogues.

Loads faction JSON files into normalized Python objects (UnitCard,
Detachment, FactionData) using only the standard library. Builds and
maintains an on-disk cache (``units_cache.json``) that is rebuilt when a
faction file is newer than the cache.

Public API
----------
list_factions()                       -> list[dict{file, name}]
get_faction(file)                     -> FactionData            (cached)
faction_units(file, search, category)  -> list[UnitCard]
get_unit(file, unit_id)               -> UnitCard | None
load_index()                          -> dict[file -> FactionData]
"""

from __future__ import annotations

import json
import os
import sys
import glob
import functools
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Directory containing the 46 BSData JSON files.
DATA_DIR = Path(__file__).resolve().parent.parent.parent / "wh40k-11e"
GAMESYSTEM_FILE = "Warhammer 40,000.json"

# profileType ids (from the gamesystem file). Classify a profile by its
# ``typeId`` field (NOT ``profileTypeId`` which is frequently None).
PT_UNIT = "c547-1836-d8a-ff4f"          # Unit statline
PT_RANGED = "f77d-b953-8fa4-b762"       # Ranged Weapons
PT_ABILITIES = "9cc3-6d83-4dd3-9b64"    # Abilities
PT_MELEE = "8a40-4aaa-c780-9046"       # Melee Weapons
PT_TRANSPORT = "74f8-5443-9d6d-1f1e"   # Transport

UNIT_CHARS = ("M", "T", "Sv", "W", "LD", "OC", "InSv")

# Files excluded from the *faction list* (they are shared libraries / the
# gamesystem / unaligned pool). They may still be loaded for resolution.
_EXCLUDE_EXACT = {GAMESYSTEM_FILE, "Unaligned Forces.json"}


def _is_library_file(fname: str) -> bool:
    """Return True for shared-library catalogues. Names come in several
    shapes — ``Library - Titans``, ``Aeldari - Aeldari Library``,
    ``Imperium - Astra Militarum - Library`` — so match on the base name
    (without extension) ending in `` Library`` or starting with ``Library ``."""
    base = fname[:-5] if fname.endswith(".json") else fname
    return base.endswith(" Library") or base.startswith("Library ")


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _warn(msg: str) -> None:
    print(f"[bsdata] WARNING: {msg}", file=sys.stderr)


def _char_text(c: dict) -> str:
    """Characteristic value lives under ``$text`` (preferred) or ``value``."""
    if not isinstance(c, dict):
        return ""
    v = c.get("$text")
    if v is None:
        v = c.get("value")
    if v is None:
        return ""
    return str(v)


def _profile_type(p: dict) -> str:
    """Return the effective profileType id for a profile object."""
    tid = p.get("typeId")
    if tid:
        return tid
    ptid = p.get("profileTypeId")
    if ptid:
        return ptid
    return ""


def _profile_type_name(p: dict) -> str:
    return (p.get("typeName") or "")


def _pts(costs: list | None) -> int | None:
    if not costs:
        return None
    for c in costs:
        if isinstance(c, dict) and c.get("name") == "pts":
            try:
                return int(c.get("value"))
            except (TypeError, ValueError):
                return None
    return None


def _char_lookup(profile: dict, name: str) -> str:
    for c in (profile.get("characteristics") or []):
        if isinstance(c, dict) and c.get("name") == name:
            return _char_text(c)
    return ""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

class UnitCard:
    """A normalized unit entry."""

    def __init__(self, id: str, name: str, faction_file: str):
        self.id = id
        self.name = name
        self.faction_file = faction_file
        self.points: int | None = None
        self.keywords: list[str] = []
        self.categories: list[str] = []
        self.statline: dict[str, str] = {}
        self.abilities: list[dict] = []          # {name, description}
        self.weapons: list[dict] = []            # {name,type,range,A,BS,WS,S,AP,D,abilities}
        self.transport: str | None = None
        self.aliases: list[str] = []             # other BSData ids that resolve to this unit

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "faction_file": self.faction_file,
            "points": self.points,
            "keywords": list(self.keywords),
            "categories": list(self.categories),
            "statline": dict(self.statline),
            "abilities": list(self.abilities),
            "weapons": list(self.weapons),
            "transport": self.transport,
            "aliases": list(self.aliases),
        }

    def __repr__(self):
        return f"<UnitCard {self.name!r} ({self.points}pts)>"


class Detachment:
    def __init__(self, name: str):
        self.name = name
        self.rule: str = ""
        self.stratagems: list[dict] = []   # {name, cp, text}
        self.enhancements: list[dict] = []  # {name, text, cost}

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "rule": self.rule,
            "stratagems": list(self.stratagems),
            "enhancements": list(self.enhancements),
        }

    def __repr__(self):
        return f"<Detachment {self.name!r}>"


class FactionData:
    def __init__(self, file: str, name: str):
        self.file = file
        self.name = name
        self.units: list[UnitCard] = []
        self.detachments: list[Detachment] = []
        self.faction_abilities: list[dict] = []  # {name, description}

    def to_dict(self) -> dict:
        return {
            "file": self.file,
            "name": self.name,
            "units": [u.to_dict() for u in self.units],
            "detachments": [d.to_dict() for d in self.detachments],
            "faction_abilities": list(self.faction_abilities),
        }

    def __repr__(self):
        return f"<FactionData {self.name!r} units={len(self.units)}>"


# ---------------------------------------------------------------------------
# ID-resolution context
# ---------------------------------------------------------------------------

class _Ctx:
    """Holds id->object maps for a catalogue plus the gamesystem shared rules,
    used to resolve entryLinks / infoLinks."""

    def __init__(self):
        self.entries: dict[str, dict] = {}   # selectionEntry id -> entry
        self.profiles: dict[str, dict] = {}  # sharedProfile id -> profile
        self.rules: dict[str, dict] = {}     # sharedRule id -> rule
        self.gs_rules: dict[str, dict] = {}  # gamesystem sharedRules
        self.gs_profiles: dict[str, dict] = {}  # gamesystem sharedProfiles

    def resolve_entry(self, target_id: str) -> dict | None:
        return self.entries.get(target_id)

    def resolve_rule(self, target_id: str) -> dict | None:
        return (self.rules.get(target_id)
                or self.gs_rules.get(target_id))

    def resolve_profile(self, target_id: str) -> dict | None:
        return (self.profiles.get(target_id)
                or self.gs_profiles.get(target_id))


@functools.lru_cache(maxsize=1)
def _gamesystem_ctx() -> tuple[dict, dict]:
    """Return (shared_rules_map, shared_profiles_map) for the gamesystem."""
    path = DATA_DIR / GAMESYSTEM_FILE
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as exc:
        _warn(f"could not load gamesystem {path}: {exc}")
        return {}, {}
    gs = data.get("gameSystem", {})
    rules = {}
    for r in gs.get("sharedRules", []) or []:
        rid = r.get("id")
        if rid:
            rules[rid] = r
    profiles = {}
    for p in gs.get("sharedProfiles", []) or []:
        pid = p.get("id")
        if pid:
            profiles[pid] = p
    return rules, profiles


# ---------------------------------------------------------------------------
# Catalogue-link resolution
# ---------------------------------------------------------------------------
# Many factions store their units in shared *library* catalogues and reference
# them from the main file via root ``entryLinks`` (targetId -> shared entry in a
# linked library). To populate those factions we must (1) resolve
# ``catalogueLinks`` to actual files and (2) merge the linked catalogues'
# shared entries/profiles/rules into the resolution context so entryLinks and
# infoLinks can be followed. Without this, ~14 factions (Aeldari, Astra
# Militarum, Imperial Knights, the SM successor chapters, ...) appear empty.

@functools.lru_cache(maxsize=1)
def _catalogue_id_to_file() -> dict[str, str]:
    """Map ``catalogue.id`` -> filename for every catalogue JSON in DATA_DIR
    (libraries included, gamesystem excluded). Lets us resolve a
    ``catalogueLink.targetId`` to a file on disk."""
    out: dict[str, str] = {}
    for p in glob.glob(str(DATA_DIR / "*.json")):
        fname = os.path.basename(p)
        if fname == GAMESYSTEM_FILE:
            continue
        try:
            with open(p, encoding="utf-8") as fh:
                cid = json.load(fh).get("catalogue", {}).get("id")
        except Exception:
            continue
        if cid:
            out[cid] = fname
    return out


@functools.lru_cache(maxsize=None)
def _load_raw_catalogue(file: str) -> dict:
    """Load and return the raw ``catalogue`` dict for ``file`` (cached)."""
    with open(DATA_DIR / file, encoding="utf-8") as fh:
        return json.load(fh).get("catalogue", {})


def _linked_files(file: str) -> list[str]:
    """Return filenames of every catalogue linked (transitively) by ``file``,
    cycle-safe. Includes shared libraries and parent faction catalogues."""
    idmap = _catalogue_id_to_file()
    visited: set[str] = set()
    ordered: list[str] = []
    stack = [file]
    while stack:
        cur = stack.pop()
        if cur in visited:
            continue
        visited.add(cur)
        try:
            cat = _load_raw_catalogue(cur)
        except Exception:
            continue
        for cl in (cat.get("catalogueLinks") or []):
            if not isinstance(cl, dict):
                continue
            tgt = idmap.get(cl.get("targetId") or "")
            if tgt and tgt not in visited:
                ordered.append(tgt)
                stack.append(tgt)
    return ordered


def _build_merged_ctx(file: str) -> tuple[_Ctx, list[str]]:
    """Build a resolution context whose entry/profile/rule maps cover ``file``
    and every linked catalogue. Linked entries fill in only when not already
    present (self takes precedence). Returns (ctx, linked_files)."""
    ctx = _Ctx()
    linked = _linked_files(file)
    for f in [file] + linked:
        try:
            cat = _load_raw_catalogue(f)
        except Exception:
            continue
        for e in (cat.get("sharedSelectionEntries") or []):
            eid = e.get("id") if isinstance(e, dict) else None
            if eid and eid not in ctx.entries:
                ctx.entries[eid] = e
        for p in (cat.get("sharedProfiles") or []):
            pid = p.get("id") if isinstance(p, dict) else None
            if pid and pid not in ctx.profiles:
                ctx.profiles[pid] = p
        for r in (cat.get("sharedRules") or []):
            rid = r.get("id") if isinstance(r, dict) else None
            if rid and rid not in ctx.rules:
                ctx.rules[rid] = r
    gs_rules, gs_profiles = _gamesystem_ctx()
    ctx.gs_rules = gs_rules
    ctx.gs_profiles = gs_profiles
    return ctx, linked


# ---------------------------------------------------------------------------
# Faction discovery
# ---------------------------------------------------------------------------

def _faction_files() -> list[str]:
    files = []
    for p in glob.glob(str(DATA_DIR / "*.json")):
        fname = os.path.basename(p)
        if fname in _EXCLUDE_EXACT:
            continue
        if _is_library_file(fname):
            continue
        files.append(fname)
    files.sort()
    return files


@functools.lru_cache(maxsize=1)
def list_factions() -> list[dict]:
    """Return ``[{file, name}, ...]`` for all faction catalogues."""
    out = []
    for fname in _faction_files():
        try:
            with open(DATA_DIR / fname, encoding="utf-8") as fh:
                data = json.load(fh)
            cat = data.get("catalogue", {})
            disp = cat.get("name") or _friendly_name(fname)
        except Exception as exc:
            _warn(f"list_factions: failed to read {fname}: {exc}")
            disp = _friendly_name(fname)
        out.append({"file": fname, "name": disp})
    return out


def _friendly_name(fname: str) -> str:
    base = os.path.splitext(fname)[0]
    # "Imperium - Space Marines" -> "Space Marines"; drop a leading
    # alliance prefix before the first " - ".
    if " - " in base:
        base = base.split(" - ", 1)[1]
    return base


# ---------------------------------------------------------------------------
# Building a FactionData from a raw catalogue
# ---------------------------------------------------------------------------

def _build_ctx(cat: dict) -> _Ctx:
    """Build a resolution context from a single catalogue dict (used by
    tests / direct callers). ``_build_faction`` uses the richer
    :func:`_build_merged_ctx` instead."""
    ctx = _Ctx()
    for e in cat.get("sharedSelectionEntries", []) or []:
        eid = e.get("id")
        if eid:
            ctx.entries[eid] = e
    for p in cat.get("sharedProfiles", []) or []:
        pid = p.get("id")
        if pid:
            ctx.profiles[pid] = p
    for r in cat.get("sharedRules", []) or []:
        rid = r.get("id")
        if rid:
            ctx.rules[rid] = r
    gs_rules, gs_profiles = _gamesystem_ctx()
    ctx.gs_rules = gs_rules
    ctx.gs_profiles = gs_profiles
    return ctx


def _collect_profiles(entry: dict, ctx: _Ctx, acc: list[dict], seen: set):
    """Recursively gather all profile dicts under ``entry`` (its own,
    nested selectionEntries/selectionEntryGroups/entryLinks)."""
    for p in (entry.get("profiles") or []):
        if isinstance(p, dict):
            acc.append(p)
    for k in ("selectionEntries", "selectionEntryGroups", "entryLinks"):
        for sub in (entry.get(k) or []):
            if isinstance(sub, dict):
                _collect_profiles(sub, ctx, acc, seen)
    # entryLinks with targetId: resolve to the linked shared entry and
    # collect its profiles (the actual weapon profile lives there).
    tid = entry.get("targetId")
    if tid and tid not in seen:
        seen.add(tid)
        linked = ctx.resolve_entry(tid)
        if linked:
            _collect_profiles(linked, ctx, acc, seen)
            # follow the linked entry's own entryLinks too
            for el in (linked.get("entryLinks") or []):
                if isinstance(el, dict):
                    _collect_profiles(el, ctx, acc, seen)


def _collect_abilities(entry: dict, ctx: _Ctx, acc: list[dict],
                       seen: set, depth: int = 0):
    """Gather ability dicts {name, description} from Abilities profiles and
    from infoLinks that resolve to shared rules."""
    # Direct Abilities profiles on this entry.
    for p in (entry.get("profiles") or []):
        if not isinstance(p, dict):
            continue
        if _profile_type(p) == PT_ABILITIES or \
           _profile_type_name(p) == "Abilities":
            name = p.get("name") or ""
            desc = _char_lookup(p, "Description")
            acc.append({"name": name, "description": desc})
    # infoLinks of type "rule" -> resolve to sharedRules (catalogue +
    # gamesystem) for the description text.
    for il in (entry.get("infoLinks") or []):
        if not isinstance(il, dict):
            continue
        if il.get("type") == "rule" or il.get("targetType") == "rule":
            name = il.get("name") or ""
            tid = il.get("targetId")
            desc = ""
            if tid:
                rule = ctx.resolve_rule(tid)
                if rule:
                    desc = rule.get("description") or ""
            acc.append({"name": name, "description": desc})
    # Recurse into nested selectionEntries / selectionEntryGroups /
    # entryLinks, but guard against runaway depth / cycles.
    if depth > 8:
        return
    for k in ("selectionEntries", "selectionEntryGroups", "entryLinks"):
        for sub in (entry.get(k) or []):
            if isinstance(sub, dict):
                _collect_abilities(sub, ctx, acc, seen, depth + 1)
    tid = entry.get("targetId")
    if tid and tid not in seen:
        seen.add(tid)
        linked = ctx.resolve_entry(tid)
        if linked:
            _collect_abilities(linked, ctx, acc, seen, depth + 1)


def _find_first_model_unit_profile(entry: dict, ctx: _Ctx,
                                     seen: set, depth: int = 0) -> dict | None:
    """Walk nested model entries and return the first Unit-type profile."""
    # Check direct profiles first.
    for p in (entry.get("profiles") or []):
        if isinstance(p, dict) and _profile_type(p) == PT_UNIT:
            return p
    if depth > 10:
        return None
    for k in ("selectionEntries", "selectionEntryGroups", "entryLinks"):
        for sub in (entry.get(k) or []):
            if isinstance(sub, dict):
                found = _find_first_model_unit_profile(sub, ctx, seen, depth + 1)
                if found:
                    return found
    # Resolve entryLink target.
    tid = entry.get("targetId")
    if tid and tid not in seen:
        seen.add(tid)
        linked = ctx.resolve_entry(tid)
        if linked:
            return _find_first_model_unit_profile(linked, ctx, seen, depth + 1)
    return None


def _build_unit(entry: dict, faction_file: str, ctx: _Ctx) -> UnitCard | None:
    try:
        unit = UnitCard(entry.get("id", ""), entry.get("name", ""), faction_file)
        unit.points = _pts(entry.get("costs"))

        # Keywords / categories from categoryLinks (already carry "name").
        cats = []
        kw = []
        for cl in (entry.get("categoryLinks") or []):
            if not isinstance(cl, dict):
                continue
            nm = cl.get("name") or ""
            if not nm:
                continue
            cats.append(nm)
            if nm.startswith("Faction:"):
                kw.append(nm)
        unit.categories = cats
        unit.keywords = kw

        # Statline: first nested model's Unit profile.
        prof = _find_first_model_unit_profile(entry, ctx, set())
        if prof:
            for c in UNIT_CHARS:
                unit.statline[c] = _char_lookup(prof, c)
            # Transport profile on the model, if any.
        else:
            for c in UNIT_CHARS:
                unit.statline[c] = ""

        # Look for a Transport profile anywhere under the unit.
        all_profiles: list[dict] = []
        _collect_profiles(entry, ctx, all_profiles, set())
        for p in all_profiles:
            if _profile_type(p) == PT_TRANSPORT or \
               _profile_type_name(p) == "Transport":
                unit.transport = _char_lookup(p, "Capacity") or \
                                 _char_lookup(p, "Description")
                break

        # Abilities (Abilities profiles + infoLinks to shared rules).
        abil: list[dict] = []
        _collect_abilities(entry, ctx, abil, set())
        # Dedupe by name keeping first.
        names_seen = set()
        for a in abil:
            if a["name"] in names_seen:
                continue
            names_seen.add(a["name"])
            unit.abilities.append(a)

        # Weapons: any Ranged / Melee profile under the unit tree.
        for p in all_profiles:
            pt = _profile_type(p)
            if pt == PT_RANGED:
                unit.weapons.append(_weapon_dict(p, "Ranged"))
            elif pt == PT_MELEE:
                unit.weapons.append(_weapon_dict(p, "Melee"))

        return unit
    except Exception as exc:  # pragma: no cover - defensive
        _warn(f"build_unit failed for {entry.get('name')!r}: {exc}")
        return None


def _weapon_dict(p: dict, wtype: str) -> dict:
    return {
        "name": p.get("name") or "",
        "type": wtype,
        "range": _char_lookup(p, "Range"),
        "A": _char_lookup(p, "A"),
        "BS": _char_lookup(p, "BS"),
        "WS": _char_lookup(p, "WS"),
        "S": _char_lookup(p, "S"),
        "AP": _char_lookup(p, "AP"),
        "D": _char_lookup(p, "D"),
        "abilities": _char_lookup(p, "Abilities") or _char_lookup(p, "Keywords"),
    }


def _build_detachment(entry: dict, ctx: _Ctx) -> Detachment:
    dep = Detachment(entry.get("name", ""))
    # Rule text: concatenate all rule descriptions.
    rule_texts = []
    for r in (entry.get("rules") or []):
        if isinstance(r, dict):
            txt = r.get("description") or ""
            if txt:
                rule_texts.append(txt)
            elif r.get("name"):
                rule_texts.append(r.get("name"))
    dep.rule = "\n\n".join(rule_texts).strip()

    # Stratagems: best-effort. Look for rules whose name mentions "Stratagem"
    # or infoLinks that resolve to a rule. BSData 11e typically does NOT ship
    # detachment stratagems, so this may be empty.
    strats = []
    for r in (entry.get("rules") or []):
        if not isinstance(r, dict):
            continue
        nm = r.get("name") or ""
        if "stratagem" in nm.lower():
            txt = r.get("description") or ""
            cp = _extract_cp(nm + " " + txt)
            strats.append({"name": nm, "cp": cp, "text": txt})
    for il in (entry.get("infoLinks") or []):
        if not isinstance(il, dict):
            continue
        nm = il.get("name") or ""
        tid = il.get("targetId")
        txt = ""
        if tid:
            rule = ctx.resolve_rule(tid) or {}
            txt = rule.get("description") or ""
        if "stratagem" in nm.lower() or "stratagem" in txt.lower():
            strats.append({"name": nm, "cp": _extract_cp(nm + " " + txt),
                           "text": txt})
    dep.stratagems = strats
    return dep


def _extract_cp(text: str) -> int | None:
    """Best-effort extraction of a CP cost from text like '... (1CP)'."""
    import re
    m = re.search(r"(\d+)\s*[-\s]?CP", text, re.IGNORECASE)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return None
    return None


def _extract_units(cat: dict, file: str, ctx: _Ctx) -> list[UnitCard]:
    """Extract this catalogue's selectable units: own ``sharedSelectionEntries``
    of type ``unit`` plus root ``entryLinks`` whose target exposes a Unit
    statline (a shared ``unit`` in a library, or a ``model`` carrying the Unit
    profile for successor-chapter characters). Units are tagged with ``file``
    and deduplicated by canonical id; an entryLink's own id is recorded as an
    alias on the resulting unit."""
    out: list[UnitCard] = []
    seen: set[str] = set()

    for e in (cat.get("sharedSelectionEntries") or []):
        if not isinstance(e, dict) or e.get("type") != "unit":
            continue
        u = _build_unit(e, file, ctx)
        if u and u.id not in seen:
            out.append(u)
            seen.add(u.id)

    for el in (cat.get("entryLinks") or []):
        if not isinstance(el, dict):
            continue
        tid = el.get("targetId")
        if not tid:
            continue
        target = ctx.resolve_entry(tid)
        if not target or not isinstance(target, dict):
            continue
        # Keep shared 'unit' entries (library units like Cadian Shock Troops)
        # and 'model' entries (successor-chapter characters like Lysander). Skip
        # 'upgrade' targets (Detachment / options) — group targets already
        # failed to resolve above. Note some 'unit' entries lack a Unit statline
        # profile in BSData 11e; we still surface them so they're selectable.
        if target.get("type") not in ("unit", "model"):
            continue
        u = _build_unit(target, file, ctx)
        if not u:
            continue
        if el.get("name"):
            u.name = el["name"]
        if not u.categories:
            cats: list[str] = []
            kw: list[str] = []
            for cl in (el.get("categoryLinks") or []):
                if isinstance(cl, dict) and cl.get("name"):
                    cats.append(cl["name"])
                    if cl["name"].startswith("Faction:"):
                        kw.append(cl["name"])
            if cats:
                u.categories = cats
                u.keywords = kw
        if u.points is None:
            u.points = _pts(el.get("costs"))
        if el.get("id") and el["id"] != u.id:
            u.aliases.append(el["id"])
        if u.id not in seen:
            out.append(u)
            seen.add(u.id)
    return out


def _build_faction(file: str) -> FactionData | None:
    path = DATA_DIR / file
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as exc:
        _warn(f"build_faction: could not load {file}: {exc}")
        return None
    cat = data.get("catalogue", {})
    # Merged context resolves entryLinks/infoLinks into linked libraries.
    ctx, linked = _build_merged_ctx(file)
    fd = FactionData(file, cat.get("name") or _friendly_name(file))

    # Units: own sharedSelectionEntries (type == "unit") plus root entryLinks
    # resolving to library/parent units. This fills the previously-empty
    # factions (Aeldari, Astra Militarum, Imperial Knights, Chaos Daemons...).
    fd.units = _extract_units(cat, file, ctx)
    seen_ids: set[str] = {u.id for u in fd.units}

    # 11e Space Marines supplements: Blood Angels, Dark Angels, Space Wolves,
    # Black Templars, Deathwatch and the successor chapters (Imperial Fists,
    # Iron Hands, ...) all field the Space Marines roster plus their own
    # unique units. BSData only links these chapters to Space Marines (for
    # profile resolution) without re-listing SM units as root entryLinks, so
    # we explicitly merge the SM roster into every chapter that links to it.
    # (Factions like Chaos Daemons link to Chaos Space Marines too, but that is
    # NOT an inheritance pattern — Daemons curates its CSM-accessible units via
    # its own root entryLinks, so it is unaffected by this SM-only merge.)
    SM_FILE = "Imperium - Space Marines.json"
    if file != SM_FILE and SM_FILE in linked:
        try:
            sm_cat = _load_raw_catalogue(SM_FILE)
            for u in _extract_units(sm_cat, file, ctx):
                if u.id not in seen_ids:
                    fd.units.append(u)
                    seen_ids.add(u.id)
        except Exception as exc:  # pragma: no cover - defensive
            _warn(f"SM roster merge failed for {file}: {exc}")

    # Detachments / enhancements / faction abilities: gather groups from the
    # faction itself AND linked catalogues (successor chapters inherit their
    # parent's detachments, e.g. Imperial Fists -> Space Marines). Dedupe by
    # group name so a faction that defines its own groups isn't doubled.
    groups: list[dict] = []
    seen_gnames: set[str] = set()
    for g in (cat.get("sharedSelectionEntryGroups") or []):
        if isinstance(g, dict) and (g.get("name") or "") not in seen_gnames:
            groups.append(g)
            seen_gnames.add(g.get("name") or "")
    for f in linked:
        try:
            lcat = _load_raw_catalogue(f)
        except Exception:
            continue
        for g in (lcat.get("sharedSelectionEntryGroups") or []):
            if isinstance(g, dict) and (g.get("name") or "") not in seen_gnames:
                groups.append(g)
                seen_gnames.add(g.get("name") or "")

    # Detachments: groups named "Detachment".
    for g in groups:
        if (g.get("name") or "") != "Detachment":
            continue
        for se in (g.get("selectionEntries") or []):
            if isinstance(se, dict):
                dep = _build_detachment(se, ctx)
                if not any(d.name == dep.name for d in fd.detachments):
                    fd.detachments.append(dep)

    # Enhancements: groups ending in "Enhancements"; assign to the detachment
    # whose name is a prefix of the group name, else to the first detachment.
    enh_groups = [g for g in groups
                  if (g.get("name") or "").endswith("Enhancements")
                  and (g.get("name") or "") != "Enhancements"]
    for dep in fd.detachments:
        for g in enh_groups:
            if (g.get("name") or "").startswith(dep.name):
                dep.enhancements.extend(_enhancements_from_group(g))
    if fd.detachments and enh_groups:
        leftover = [g for g in enh_groups
                    if not any((g.get("name") or "").startswith(d.name)
                               for d in fd.detachments)]
        for g in leftover:
            fd.detachments[0].enhancements.extend(_enhancements_from_group(g))

    # Faction abilities: groups ending in "Battle Traits" or == "Abilities".
    for g in groups:
        gname = g.get("name") or ""
        if not (gname.endswith("Battle Traits") or gname == "Abilities"):
            continue
        for se in (g.get("selectionEntries") or []):
            if not isinstance(se, dict):
                continue
            for p in (se.get("profiles") or []):
                if isinstance(p, dict) and \
                   (_profile_type(p) == PT_ABILITIES or
                    _profile_type_name(p) == "Abilities"):
                    fd.faction_abilities.append({
                        "name": p.get("name") or se.get("name") or "",
                        "description": _char_lookup(p, "Description"),
                    })

    return fd


def _enhancements_from_group(g: dict) -> list[dict]:
    out = []
    for se in (g.get("selectionEntries") or []):
        if not isinstance(se, dict):
            continue
        text = ""
        for p in (se.get("profiles") or []):
            if isinstance(p, dict) and \
               (_profile_type(p) == PT_ABILITIES or
                _profile_type_name(p) == "Abilities"):
                text = _char_lookup(p, "Description")
                break
        out.append({
            "name": se.get("name") or "",
            "text": text,
            "cost": _pts(se.get("costs")),
        })
    return out


# ---------------------------------------------------------------------------
# Index + cache
# ---------------------------------------------------------------------------

_CACHE_PATH = Path(__file__).resolve().parent / "units_cache.json"
# Bump when the cache schema/semantics change so a stale cache is rebuilt.
_CACHE_VERSION = 3
_index_cache: dict[str, FactionData] | None = None


def _newest_faction_mtime() -> float:
    """Newest mtime across ALL catalogue JSONs (libraries included, since
    library files are now load-bearing via catalogueLink resolution)."""
    newest = 0.0
    for p in glob.glob(str(DATA_DIR / "*.json")):
        if os.path.basename(p) == GAMESYSTEM_FILE:
            continue
        try:
            newest = max(newest, os.path.getmtime(p))
        except OSError:
            pass
    return newest


def _cache_fresh() -> bool:
    if not _CACHE_PATH.exists():
        return False
    try:
        cmeta = os.path.getmtime(_CACHE_PATH)
    except OSError:
        return False
    if cmeta < _newest_faction_mtime():
        return False
    try:
        with open(_CACHE_PATH, encoding="utf-8") as fh:
            if json.load(fh).get("version") != _CACHE_VERSION:
                return False
    except Exception:
        return False
    return True


def _write_cache(index: dict[str, FactionData]) -> None:
    try:
        payload = {
            "version": _CACHE_VERSION,
            "faction_files": _faction_files(),
            "factions": {f: fd.to_dict() for f, fd in index.items()},
        }
        tmp = _CACHE_PATH.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
        os.replace(tmp, _CACHE_PATH)
    except Exception as exc:
        _warn(f"write_cache failed: {exc}")


def _faction_from_dict(f: str, d: dict) -> FactionData:
    fd = FactionData(f, d.get("name") or _friendly_name(f))
    for u in d.get("units", []):
        uc = UnitCard(u.get("id", ""), u.get("name", ""), f)
        uc.points = u.get("points")
        uc.keywords = u.get("keywords", [])
        uc.categories = u.get("categories", [])
        uc.statline = u.get("statline", {})
        uc.abilities = u.get("abilities", [])
        uc.weapons = u.get("weapons", [])
        uc.transport = u.get("transport")
        uc.aliases = u.get("aliases", [])
        fd.units.append(uc)
    for dp in d.get("detachments", []):
        dep = Detachment(dp.get("name", ""))
        dep.rule = dp.get("rule", "")
        dep.stratagems = dp.get("stratagems", [])
        dep.enhancements = dp.get("enhancements", [])
        fd.detachments.append(dep)
    fd.faction_abilities = d.get("faction_abilities", [])
    return fd


def load_index() -> dict[str, FactionData]:
    """Return a ``{file: FactionData}`` dict for every faction. Idempotent;
    builds an on-disk cache on first call (or when stale)."""
    global _index_cache
    if _index_cache is not None:
        return _index_cache

    index: dict[str, FactionData] = {}

    if _cache_fresh():
        try:
            with open(_CACHE_PATH, encoding="utf-8") as fh:
                payload = json.load(fh)
            for f, d in payload.get("factions", {}).items():
                index[f] = _faction_from_dict(f, d)
            if index:
                _index_cache = index
                return index
        except Exception as exc:
            _warn(f"cache read failed, rebuilding: {exc}")
            index = {}

    # Build from source.
    for fname in _faction_files():
        fd = _build_faction(fname)
        if fd is not None:
            index[fname] = fd

    _write_cache(index)
    _index_cache = index
    return index


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@functools.lru_cache(maxsize=None)
def get_faction(file: str) -> FactionData:
    """Return the FactionData for ``file``. Cached via lru_cache and
    backed by :func:`load_index`."""
    return load_index()[file]


def faction_units(file: str, search: str | None = None,
                  category: str | None = None) -> list[UnitCard]:
    """Return the unit list for a faction, optionally filtered.

    ``search``  - substring filter on unit name (case-insensitive).
    ``category``- substring filter on the unit's categories list.
    """
    fd = get_faction(file)
    units = list(fd.units)
    if search:
        s = search.lower()
        units = [u for u in units if s in u.name.lower()]
    if category:
        c = category.lower()
        units = [u for u in units
                 if any(c in (cat or "").lower() for cat in u.categories)]
    return units


def get_unit(file: str, unit_id: str) -> UnitCard | None:
    fd = get_faction(file)
    for u in fd.units:
        if u.id == unit_id:
            return u
    return None


def get_unit_by_id(unit_id: str, prefer_faction_file: str | None = None) \
        -> UnitCard | None:
    """Find a unit by its BSData entry id across every faction. Matches the
    unit's canonical id OR any of its aliases (entryLink ids that resolve to
    it). If ``prefer_faction_file`` is given and that faction has the unit,
    return it from there."""
    def _match(fd: FactionData) -> UnitCard | None:
        for u in fd.units:
            if u.id == unit_id or unit_id in u.aliases:
                return u
        return None
    if prefer_faction_file:
        u = _match(get_faction(prefer_faction_file))
        if u:
            return u
    for f, fd in load_index().items():
        u = _match(fd)
        if u:
            return u
    return None


def get_unit_by_name(name: str, faction_file: str | None = None) -> UnitCard | None:
    """Find a unit by display name (case-insensitive, ignores ``[Legends]``
    suffix). Searches ``faction_file`` first if given, then every faction."""
    def _norm(n: str) -> str:
        return (n or "").lower().replace("[legends]", "").strip()

    target = _norm(name)
    if not target:
        return None

    def _match(fd: FactionData) -> UnitCard | None:
        for u in fd.units:
            if _norm(u.name) == target:
                return u
        # substring fallback
        for u in fd.units:
            if target in _norm(u.name) or _norm(u.name) in target:
                return u
        return None

    if faction_file:
        u = _match(get_faction(faction_file))
        if u:
            return u
    for f, fd in load_index().items():
        u = _match(fd)
        if u:
            return u
    return None


def faction_file_by_catalogue_id(catalogue_id: str) -> str | None:
    """Map a BSData ``catalogue.id`` (as found in a roster file's force) to the
    corresponding playable faction filename, or None if it's a library /
    gamesystem / unknown catalogue."""
    if not catalogue_id:
        return None
    fname = _catalogue_id_to_file().get(catalogue_id)
    if not fname or _is_library_file(fname) or fname in _EXCLUDE_EXACT:
        return None
    return fname


def rebuild_cache() -> dict[str, FactionData]:
    """Force a from-source rebuild of the index and refresh the on-disk cache.
    Useful after the BSData clone is updated."""
    global _index_cache
    _index_cache = None
    get_faction.cache_clear()
    index: dict[str, FactionData] = {}
    for fname in _faction_files():
        fd = _build_faction(fname)
        if fd is not None:
            index[fname] = fd
    _write_cache(index)
    _index_cache = index
    return index


if __name__ == "__main__":
    # Quick CLI smoke check.
    for f in list_factions()[:3]:
        print(f["file"], "->", f["name"])