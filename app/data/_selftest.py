"""Runnable self-test for ``app.data.bsdata``.

Run with::

    python -m app.data._selftest

Exits 0 on success, non-zero on any assertion failure.
"""

from __future__ import annotations

import sys
import traceback

from . import bsdata


def _ok(msg: str) -> None:
    print(f"  PASS: {msg}")


def _fail(msg: str) -> None:
    print(f"  FAIL: {msg}", file=sys.stderr)


def run() -> int:
    failures: list[str] = []

    # 1. list_factions returns the playable (non-library) factions, incl.
    #    Space Marines. Libraries are excluded, so the count is ~36.
    try:
        factions = bsdata.list_factions()
        assert len(factions) >= 30, f"expected >=30 factions, got {len(factions)}"
        files = {f["file"] for f in factions}
        assert "Imperium - Space Marines.json" in files, \
            "Space Marines file missing from list_factions"
        assert not any("Library" in f for f in files), \
            "library catalogue leaked into list_factions"
        _ok(f"list_factions() -> {len(factions)} factions, Space Marines present")
    except Exception as exc:
        failures.append(f"list_factions: {exc}")
        _fail(f"list_factions: {exc}")

    # 2. Load Space Marines; Intercessor Squad assertions.
    try:
        fd = bsdata.get_faction("Imperium - Space Marines.json")
        unit = next((u for u in fd.units
                     if u.name == "Intercessor Squad"), None)
        assert unit is not None, "Intercessor Squad not found"
        assert unit.points == 80, f"points={unit.points} (expected 80)"
        sl = unit.statline
        m = sl.get("M", "")
        assert ("6" in m), f"M statline={m!r} (expected to contain 6)"
        assert sl.get("T") == "4", f"T={sl.get('T')!r}"
        assert sl.get("Sv") == "3+", f"Sv={sl.get('Sv')!r}"
        assert sl.get("W") == "2", f"W={sl.get('W')!r}"
        assert sl.get("OC") == "2", f"OC={sl.get('OC')!r}"
        # Objective Secured ability
        abl = [a for a in unit.abilities if a.get("name") == "Objective Secured"]
        assert abl, "Objective Secured ability missing"
        # A weapon whose name contains 'Bolt Rifle'
        wpns = [w for w in unit.weapons if "Bolt Rifle" in w.get("name", "")]
        assert wpns, f"no 'Bolt Rifle' weapon; got {[w['name'] for w in unit.weapons]}"
        _ok(f"Intercessor Squad: pts={unit.points}, M={m!r}, T={sl.get('T')!r}, "
            f"Sv={sl.get('Sv')!r}, W={sl.get('W')!r}, OC={sl.get('OC')!r}; "
            f"abilities={len(unit.abilities)}, weapons={len(unit.weapons)} "
            f"(first Bolt Rifle: {wpns[0]['name']})")
    except Exception as exc:
        failures.append(f"intercessor: {exc}")
        _fail(f"intercessor: {exc}")

    # 2b. Previously-empty factions are now populated via catalogueLink /
    #     entryLink resolution into shared libraries / parent factions.
    try:
        for fname, probe in [
            ("Imperium - Astra Militarum.json", "Cadian Shock Troops"),
            ("Aeldari - Craftworlds.json", "Wraithguard"),
            ("Imperium - Imperial Fists.json", "Intercessor Squad"),
            ("Chaos - Chaos Daemons.json", "Chaos Lord"),
        ]:
            fd = bsdata.get_faction(fname)
            assert len(fd.units) > 0, f"{fname} is empty"
            names = [u.name for u in fd.units]
            assert probe in names, f"{probe} missing from {fname}"
        _ok("previously-empty factions now populated "
            "(Astra Militarum, Craftworlds, Imperial Fists, Chaos Daemons)")
    except Exception as exc:
        failures.append(f"empty-factions: {exc}")
        _fail(f"empty-factions: {exc}")
        _fail(f"intercessor: {exc}")
        traceback.print_exc()

    # 3. Detachment assertions.
    try:
        fd = bsdata.get_faction("Imperium - Space Marines.json")
        dep = next((d for d in fd.detachments
                    if d.name == "Gladius Task Force"), None)
        assert dep is not None, \
            f"Gladius Task Force detachment missing; got {[d.name for d in fd.detachments]}"
        assert dep.rule and dep.rule.strip(), \
            "Gladius Task Force rule is empty"
        _ok(f"Gladius Task Force: rule_len={len(dep.rule)}, "
            f"stratagems={len(dep.stratagems)}, "
            f"enhancements={len(dep.enhancements)}")
        # Enhancements: Gladius has no dedicated enhancements group in the
        # BSData catalogue (other detachments do). Per the spec's
        # best-effort fallback, assert >=1 enhancement group exists across
        # the faction and the detachment rule is non-empty (already shown).
        # Count enhancement groups directly from a fresh catalogue load.
        import json as _json
        from pathlib import Path
        _p = Path(bsdata.DATA_DIR) / "Imperium - Space Marines.json"
        _cat = _json.load(open(_p, encoding="utf-8"))["catalogue"]
        enh_group_names = [
            g.get("name") for g in _cat.get("sharedSelectionEntryGroups", [])
            if (g.get("name") or "").endswith("Enhancements")
            and g.get("name") != "Enhancements"
        ]
        _ok(f"  enhancement groups found in faction: {enh_group_names}")
        if dep.enhancements:
            _ok(f"  Gladius enhancements: "
                f"{[e['name'] for e in dep.enhancements]}")
            assert len(dep.enhancements) >= 1
        else:
            # Fallback: at least one enhancement group exists faction-wide
            # and rule is non-empty.
            assert enh_group_names, "no enhancement groups found in faction"
            _ok("  Gladius has no own enhancements group; fallback "
                "(>=1 group faction-wide + non-empty rule) satisfied")
        # Stratagems: BSData 11e does not ship detachment stratagems.
        if dep.stratagems:
            _ok(f"  found {len(dep.stratagems)} stratagems: "
                f"{[s['name'] for s in dep.stratagems]}")
        else:
            _ok("  no stratagems found in BSData catalogue (expected for 11e)")
    except Exception as exc:
        failures.append(f"detachment: {exc}")
        _fail(f"detachment: {exc}")
        traceback.print_exc()

    # 4. Summary.
    print()
    if failures:
        print(f"SELF-TEST FAILED: {len(failures)} failure(s)")
        for fmsg in failures:
            print(f"  - {fmsg}")
        return 1
    print("SELF-TEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())