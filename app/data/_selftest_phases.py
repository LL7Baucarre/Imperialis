"""Runnable self-test for ``app.data.phases``.

Run with::

    python -m app.data._selftest_phases

Exits 0 on success, non-zero on failure.
"""

from __future__ import annotations

import sys

from app.data.phases import (
    PHASES,
    ROUNDS,
    PREGAME_STEPS,
    PHASE_DATA,
    WOUND_TABLE,
    advance_state,
    is_last_phase,
    phase_index,
    total_steps_for_round,
    phase_assist,
)


def _walk(round_, phase, active, first, *, max_ticks):
    """Walk the state machine, returning the trace and final state."""
    trace = [(round_, phase, active)]
    for _ in range(max_ticks):
        nxt = advance_state(round_, phase, active, first_seat=first)
        if nxt is None:
            trace.append(("GAME-OVER", None, None))
            return trace, None
        round_, phase, active = nxt
        trace.append((round_, phase, active))
    return trace, (round_, phase, active)


def test_structure():
    assert len(PHASES) == 5, PHASES
    assert PHASES == ["Command", "Movement", "Shooting", "Charge", "Fight"]
    assert ROUNDS == 5
    assert phase_index("Command") == 0
    assert phase_index("Fight") == 4
    assert is_last_phase("Fight") is True
    assert is_last_phase("Command") is False
    assert total_steps_for_round() == 10
    assert isinstance(PREGAME_STEPS, list) and len(PREGAME_STEPS) >= 6
    print("[ok] structure: PHASES/order/ROUNDS/PREGAME_STEPS/helpers")


def test_state_machine_two_rounds():
    first = 1
    # Round 1, Command, seat 1 (the first player).
    trace, final = _walk(1, "Command", 1, first, max_ticks=20)

    # Tick 5 (after 4 advances) -> Player 1's Fight done, switch to seat 2.
    # Indices in trace: 0 = start state, i = state after i advances.
    # After 4 advances we should be at (1, Fight, 1).
    assert trace[4] == (1, "Fight", 1), trace[:5]
    # After 5 advances: (1, Command, 2) -- opponent's turn starts.
    assert trace[5] == (1, "Command", 2), trace[:6]
    # After 9 advances: (1, Fight, 2).
    assert trace[9] == (1, "Fight", 2), trace[:10]
    # After 10 advances: round ticks to 2, back to first player, Command.
    assert trace[10] == (2, "Command", 1), trace[:11]

    print("[ok] state-machine: 2-round trace matches expected transitions")

    # Full game: 5 rounds * 2 players * 5 phases = 50 ticks from start.
    full_trace, full_final = _walk(1, "Command", 1, first, max_ticks=60)
    # The trace should contain a GAME-OVER marker.
    assert full_trace[-1] == ("GAME-OVER", None, None), full_trace[-5:]
    # And it should occur exactly after 50 advances (trace length 51).
    assert len(full_trace) == 51, len(full_trace)
    print("[ok] state-machine: full game ends after 50 phase-ticks with None")

    # Print the 2-round trace for the report.
    print("\n--- 2-round trace (round, phase, active_seat) ---")
    for i, s in enumerate(trace[:11]):
        print(f"  tick {i:2d}: {s}")
    return trace[:11]


def test_phase_data_completeness():
    for name in PHASES:
        assert name in PHASE_DATA, f"missing phase: {name}"
        pd = PHASE_DATA[name]
        assert pd.get("title"), name
        cl = pd.get("checklist", [])
        assert isinstance(cl, list) and len(cl) > 0, f"empty checklist: {name}"
        for item in cl:
            assert "text" in item and "id" in item and "who" in item, (name, item)
        dp = pd.get("dice_presets", [])
        assert isinstance(dp, list) and len(dp) >= 1, f"no dice preset: {name}"
        for d in dp:
            assert "name" in d and "count" in d and "sides" in d, (name, d)
    # Fight should also carry Consolidation/Hazard-style presets.
    fight_dp_names = {d["name"] for d in PHASE_DATA["Fight"]["dice_presets"]}
    assert "Consolidation" in fight_dp_names, fight_dp_names
    print("[ok] phase-data: every phase has checklist + dice presets")


def test_content_reminders():
    cmd_text = " ".join(c["text"] for c in PHASE_DATA["Command"]["checklist"]).lower()
    assert "cp" in cmd_text or "command point" in cmd_text, cmd_text
    assert "battle-shock" in cmd_text or "battle shock" in cmd_text, cmd_text
    print("[ok] content: Command checklist mentions CP and battle-shock")

    sho_text = " ".join(c["text"] for c in PHASE_DATA["Shooting"]["checklist"]).lower()
    assert "wound table" in sho_text, sho_text
    print("[ok] content: Shooting checklist mentions the wound table")

    mov_interv = PHASE_DATA["Movement"]["interventions"]
    mov_interv_text = " ".join(
        (i.get("name", "") + " " + i.get("window", "") + " " + i.get("note", ""))
        for i in mov_interv
    ).lower()
    assert "overwatch" in mov_interv_text and "movement" in mov_interv_text, mov_interv_text
    print("[ok] content: Movement interventions include Fire Overwatch at end of enemy Movement")


def test_phase_assist_with_fake_faction():
    # A fake faction-like object carrying detachments -> stratagems.
    class FakeStrat:
        def __init__(self, name, window, note):
            self.name = name
            self.window = window
            self.note = note

    class FakeDetachment:
        def __init__(self, stratagems):
            self.stratagems = stratagems

    class FakeFaction:
        def __init__(self, detachments):
            self.detachments = detachments

    faction = FakeFaction([
        FakeDetachment([
            FakeStrat("Furious Charge", "Fight phase", "+1 attack when charging"),
            FakeStrat("Steady Aim", "Shooting phase", "+1 to hit when stationary"),
            FakeStrat("Rallying Cry", "Command phase", "Re-roll a battle-shock test"),
        ]),
    ])

    res = phase_assist("Fight", faction)
    names = [i["name"] for i in res["interventions"]]
    assert "Furious Charge" in names, names
    assert "Steady Aim" not in names, names
    assert "wound_table" in res and len(res["wound_table"]) == 5, res["wound_table"]

    res_sho = phase_assist("Shooting", faction)
    sho_names = [i["name"] for i in res_sho["interventions"]]
    assert "Steady Aim" in sho_names, sho_names
    assert "Furious Charge" not in sho_names, sho_names

    # Plain call (no faction) still works and includes the universal windows.
    res_plain = phase_assist("Command")
    plain_names = [i["name"] for i in res_plain["interventions"]]
    assert "Command Re-Roll" in plain_names, plain_names
    print("[ok] phase_assist: best-effort faction stratagem merge works (and skips non-matching)")


def main():
    print("=" * 60)
    print("Imperialis phase-engine self-test")
    print("=" * 60)
    test_structure()
    test_state_machine_two_rounds()
    test_phase_data_completeness()
    test_content_reminders()
    test_phase_assist_with_fake_faction()
    print("-" * 60)
    print("ALL TESTS PASSED")
    print(f"ROUNDS={ROUNDS}, PHASES={PHASES}, steps/round={total_steps_for_round()}")
    print("WOUND_TABLE:")
    for row in WOUND_TABLE:
        print(f"  {row['attacker_str']:>12s} -> wound on {row['wound_on']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())