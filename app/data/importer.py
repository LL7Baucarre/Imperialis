"""Roster importer for Imperialis.

Parses army rosters exported by NewRecruit / BattleScribe and maps them onto
our BSData-backed ``UnitCard`` objects so they can be added to a player's
roster. Supports:

* **BattleScribe ``.rosz``** — a zip containing a ``.ros`` XML roster.
* **BattleScribe ``.ros``** — the XML roster itself.
* **NewRecruit native JSON** — best-effort (NewRecruit's schema varies between
  versions; we look for the common ``forces``/``selections`` shape and several
  field-name variants for the entry id, model count and points).

All parsers return a :class:`ParsedRoster` (faction catalogue id + list of
:class:`ParsedUnit`). Resolution to ``UnitCard`` is done separately by
:func:`resolve`, which matches by BSData entry id (incl. entryLink aliases)
first, then by display name, and reports the units it could not match.
"""

from __future__ import annotations

import io
import json
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field


@dataclass
class ParsedUnit:
    entry_id: str | None = None        # BSData selection entry / link id
    name: str = ""
    models: int = 1
    points: int | None = None


@dataclass
class ParsedRoster:
    faction_catalogue_id: str | None = None
    faction_name: str | None = None
    units: list[ParsedUnit] = field(default_factory=list)
    format: str = ""                   # "rosz" | "ros" | "newrecruit-json"


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------

def _detect(filename: str, data: bytes) -> str:
    name = (filename or "").lower()
    # Zip magic (rosz is a zip).
    if data[:4] == b"PK\x03\x04":
        return "rosz"
    if name.endswith(".rosz"):
        return "rosz"
    stripped = data.lstrip()
    if stripped[:1] == b"<":
        return "ros"
    if name.endswith(".ros") or name.endswith(".xml"):
        return "ros"
    if name.endswith(".json") or stripped[:1] in (b"{", b"["):
        return "newrecruit-json"
    # Fall back to content sniffing.
    if b"<roster" in data[:4096] or b"rosterSchema" in data[:4096]:
        return "ros"
    return "newrecruit-json"


def parse_roster(filename: str, data: bytes) -> ParsedRoster:
    """Parse raw roster bytes into a :class:`ParsedRoster`."""
    fmt = _detect(filename, data)
    if fmt == "rosz":
        return _parse_rosz(data)
    if fmt == "ros":
        return _parse_ros(data, "ros")
    return _parse_newrecruit_json(data)


# ---------------------------------------------------------------------------
# BattleScribe XML (.rosz / .ros)
# ---------------------------------------------------------------------------

def _localname(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _parse_rosz(data: bytes) -> ParsedRoster:
    bio = io.BytesIO(data)
    with zipfile.ZipFile(bio) as zf:
        # Find the .ros member inside the zip.
        ros_name = None
        for nm in zf.namelist():
            if nm.lower().endswith(".ros"):
                ros_name = nm
                break
        if ros_name is None and zf.namelist():
            ros_name = zf.namelist()[0]
        if ros_name is None:
            return ParsedRoster(format="rosz")
        xml_bytes = zf.read(ros_name)
    pr = _parse_ros(xml_bytes, "rosz")
    return pr


def _parse_ros(xml_bytes: bytes, fmt: str) -> ParsedRoster:
    pr = ParsedRoster(format=fmt)
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return pr

    # Forces carry the faction catalogue id/name.
    forces = []
    for el in root.iter():
        if _localname(el.tag) == "force":
            forces.append(el)

    if forces:
        f0 = forces[0]
        pr.faction_catalogue_id = f0.get("catalogueId") or f0.get("catalogueRevisionId")
        pr.faction_name = f0.get("catalogueName") or f0.get("name")

    for force in forces:
        # Top-level <selections> of the force are the units (nested selections
        # are models / wargear / abilities).
        selections_container = None
        for child in force:
            if _localname(child.tag) == "selections":
                selections_container = child
                break
        if selections_container is None:
            continue
        for sel in selections_container:
            if _localname(sel.tag) != "selection":
                continue
            _collect_ros_selection(sel, pr)

    return pr


def _collect_ros_selection(sel: ET.Element, pr: ParsedRoster) -> None:
    """A top-level force selection is a unit. Its model count is the largest
    nested ``model``-typed selection's ``number`` (or its own ``number``)."""
    name = sel.get("name") or ""
    entry_id = sel.get("entryId") or sel.get("id")
    # Points: <costs><cost name="pts" value="80"/></costs>
    points = None
    for costs in sel:
        if _localname(costs.tag) != "costs":
            continue
        for cost in costs:
            if _localname(cost.tag) != "cost":
                continue
            if (cost.get("name") or "").lower() in ("pts", "points"):
                try:
                    points = int(round(float(cost.get("value") or 0)))
                except ValueError:
                    pass
    # Model count: look for nested model selections.
    models = _ros_model_count(sel)
    if models <= 0:
        try:
            models = int(sel.get("number") or 1)
        except ValueError:
            models = 1
    pr.units.append(ParsedUnit(entry_id=entry_id, name=name,
                               models=max(1, models), points=points))


def _ros_model_count(sel: ET.Element) -> int:
    """Sum the ``number`` of nested ``model``-typed selections."""
    total = 0
    for child in sel:
        if _localname(child.tag) != "selections":
            continue
        for sub in child:
            if _localname(sub.tag) != "selection":
                continue
            if (sub.get("type") or "").lower() == "model":
                try:
                    total += int(sub.get("number") or 0)
                except ValueError:
                    pass
            # Some rosters nest the model one level deeper.
            for deeper in sub:
                if _localname(deeper.tag) != "selections":
                    continue
                for d in deeper:
                    if _localname(d.tag) != "selection":
                        continue
                    if (d.get("type") or "").lower() == "model":
                        try:
                            total += int(d.get("number") or 0)
                        except ValueError:
                            pass
    return total


# ---------------------------------------------------------------------------
# NewRecruit native JSON
# ---------------------------------------------------------------------------

def _as_list(v) -> list:
    if v is None:
        return []
    if isinstance(v, list):
        return v
    return [v]


def _node_cost_pts(node: dict) -> int | None:
    """Extract points from a NewRecruit selection node, trying the common
    field-name variants across versions."""
    cost = node.get("cost")
    if isinstance(cost, dict):
        for key in ("pts", "points", "Pts", "Points"):
            if cost.get(key) is not None:
                try:
                    return int(round(float(cost[key])))
                except (TypeError, ValueError):
                    pass
    costs = node.get("costs")
    if isinstance(costs, list):
        for c in costs:
            if isinstance(c, dict) and (c.get("name") or "").lower() in ("pts", "points"):
                try:
                    return int(round(float(c.get("value") or 0)))
                except (TypeError, ValueError):
                    pass
    for key in ("points", "pts", "Points", "totalPoints"):
        if node.get(key) is not None:
            try:
                return int(round(float(node[key])))
            except (TypeError, ValueError):
                pass
    return None


def _node_models(node: dict) -> int:
    for key in ("count", "number", "modelCount", "models", "quantity"):
        if node.get(key) is not None:
            try:
                v = int(node[key])
                if v > 0:
                    return v
            except (TypeError, ValueError):
                pass
    return 1


def _walk_forces(node, forces_out: list, catalogues_out: list):
    """Recursively collect force-like dicts (those carrying a ``catalogue``
    or ``catalogueId``) and their direct ``selections``."""
    if isinstance(node, dict):
        cat = node.get("catalogue")
        if isinstance(cat, dict) or node.get("catalogueId") or node.get("catalog"):
            forces_out.append(node)
        for key in ("forces", "force", "rosters", "roster"):
            if key in node:
                _walk_forces(node[key], forces_out, catalogues_out)
        # NewRecruit sometimes nests selections under "forces" only.
    elif isinstance(node, list):
        for item in node:
            _walk_forces(item, forces_out, catalogues_out)


def _parse_newrecruit_json(data: bytes) -> ParsedRoster:
    pr = ParsedRoster(format="newrecruit-json")
    try:
        doc = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return pr

    forces: list = []
    _walk_forces(doc, forces, [])
    if not forces:
        # Some exports put everything under a top-level "roster".
        roster = doc.get("roster") if isinstance(doc, dict) else None
        if isinstance(roster, dict):
            _walk_forces(roster, forces, [])

    for force in forces:
        cat = force.get("catalogue") or force.get("catalog")
        if isinstance(cat, dict):
            pr.faction_catalogue_id = pr.faction_catalogue_id or cat.get("id")
            pr.faction_name = pr.faction_name or cat.get("name")
        else:
            pr.faction_catalogue_id = pr.faction_catalogue_id or force.get("catalogueId")
            pr.faction_name = pr.faction_name or force.get("catalogueName") or force.get("catalogName")

        selections = _as_list(force.get("selections") or force.get("units"))
        for sel in selections:
            if not isinstance(sel, dict):
                continue
            entry_id = sel.get("entryId") or sel.get("entryLinkId") or sel.get("id")
            name = sel.get("name") or sel.get("unit") or ""
            if not name and not entry_id:
                continue
            pr.units.append(ParsedUnit(
                entry_id=entry_id,
                name=name,
                models=_node_models(sel),
                points=_node_cost_pts(sel),
            ))

    return pr


# ---------------------------------------------------------------------------
# Resolution to UnitCard
# ---------------------------------------------------------------------------

@dataclass
class ImportResult:
    matched: list[dict] = field(default_factory=list)     # [{unit_card, models}]
    unmatched: list[dict] = field(default_factory=list)    # [{name, entry_id, ...}]
    faction_file: str | None = None
    faction_name: str | None = None
    format: str = ""


def resolve(parsed: ParsedRoster, prefer_faction_file: str | None = None):
    """Resolve a :class:`ParsedRoster` to our UnitCards. Returns an
    :class:`ImportResult` with matched / unmatched lists."""
    from app.data import bsdata

    # Determine the target faction file.
    faction_file = prefer_faction_file
    if not faction_file and parsed.faction_catalogue_id:
        faction_file = bsdata.faction_file_by_catalogue_id(parsed.faction_catalogue_id)

    result = ImportResult(faction_file=faction_file,
                           faction_name=parsed.faction_name,
                           format=parsed.format)

    for pu in parsed.units:
        unit = None
        if pu.entry_id:
            unit = bsdata.get_unit_by_id(pu.entry_id,
                                         prefer_faction_file=faction_file)
        if unit is None and pu.name:
            unit = bsdata.get_unit_by_name(pu.name, faction_file=faction_file)
        if unit is not None:
            result.matched.append({
                "unit": unit,
                "models": pu.models,
                "points": pu.points if pu.points is not None else unit.points,
                "name": unit.name,
            })
        else:
            result.unmatched.append({
                "name": pu.name or "(sans nom)",
                "entry_id": pu.entry_id,
                "models": pu.models,
                "points": pu.points,
            })
    return result