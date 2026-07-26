"""API JSON : avancement de phase, annotations, CP/VP, stratagems, unités, résolveur."""
from flask import Blueprint, request, jsonify, abort

from app import models
from app.db import get_db
from app.helpers import get_game_or_404, game_context
from app.data import phases as P, missions as M
from app.data import combat as COMBAT

bp = Blueprint("api", __name__)


@bp.route("/phase/advance", methods=["POST"])
def phase_advance():
    gid = int((request.get_json(force=True, silent=True) or request.form).get("gid") or 0)
    g = get_game_or_404(gid)
    nxt = P.advance_state(g["round"], g["phase"], g["active_player_seat"], g["first_player_seat"])
    if nxt is None:
        get_db().execute("UPDATE games SET status='finished' WHERE id=?", (gid,))
        get_db().commit()
        return jsonify({"finished": True})
    new_round, new_phase, new_seat = nxt
    models.set_game_state(gid, new_round, new_phase, new_seat)
    get_db().commit()
    # 11e : à l'entrée dans chaque Command phase, les deux joueurs gagnent 1 CP
    if new_phase == "Command":
        _, players, _ = game_context(gid)
        for seat, p in players.items():
            models.adjust_cp(p["id"], +1, reason="Gain CP (Command phase)",
                             round_=new_round, phase=new_phase)
        get_db().commit()
    return jsonify({"round": new_round, "phase": new_phase, "active_seat": new_seat,
                    "finished": False})


@bp.route("/annotation", methods=["POST"])
def annotation():
    data = request.get_json(force=True, silent=True) or request.form
    gid = int(data.get("gid") or 0)
    get_game_or_404(gid)
    g = models.get_game(gid)
    text = (data.get("text") or "").strip()
    player_id = int(data.get("player_id") or 0) or None
    if text:
        models.add_annotation(gid, g["round"], g["phase"], player_id, text)
    return jsonify({"ok": True})


@bp.route("/unit/toggle-shock", methods=["POST"])
def unit_toggle_shock():
    data = request.get_json(force=True, silent=True) or request.form
    unit_id = int(data.get("unit_id") or 0)
    # shocked optionnel : 1/0 pour forcer l'état (ex. après un jet de Battle
    # Shock). Sans valeur → bascule.
    shocked_val = data.get("shocked")
    if shocked_val is None:
        shocked = models.toggle_unit_shock(unit_id)
    else:
        shocked = models.toggle_unit_shock(unit_id, shocked=int(shocked_val))
    return jsonify({"unit_id": unit_id, "battle_shocked": shocked})


@bp.route("/unit/models", methods=["POST"])
def unit_set_models():
    data = request.get_json(force=True, silent=True) or request.form
    unit_id = int(data.get("unit_id") or 0)
    current = int(data.get("current") or 1)
    models.set_unit_models(unit_id, current)
    return jsonify({"unit_id": unit_id, "models_current": current})


@bp.route("/unit/wounds", methods=["POST"])
def unit_set_wounds():
    data = request.get_json(force=True, silent=True) or request.form
    unit_id = int(data.get("unit_id") or 0)
    current = int(data.get("current") or 0)
    # delta optional: current = existing + delta
    delta = data.get("delta")
    if delta is not None:
        row = get_db().execute(
            "SELECT wounds_current FROM units WHERE id=?", (unit_id,)).fetchone()
        base = row["wounds_current"] if row else 0
        current = base + int(delta)
    new = models.set_unit_wounds(unit_id, current)
    return jsonify({"unit_id": unit_id, "wounds_current": new})


@bp.route("/unit/position", methods=["POST"])
def unit_set_position():
    data = request.get_json(force=True, silent=True) or request.form
    unit_id = int(data.get("unit_id") or 0)
    x = data.get("x")
    y = data.get("y")
    if x is not None and y is not None:
        x = max(0.0, min(1.0, float(x)))
        y = max(0.0, min(1.0, float(y)))
        models.set_unit_position(unit_id, x, y)
        return jsonify({"unit_id": unit_id, "x": x, "y": y})
    models.clear_unit_position(unit_id)
    return jsonify({"unit_id": unit_id, "cleared": True})


# ---- Jetons du plateau interactif (division + mort) ----

@bp.route("/token/place", methods=["POST"])
def token_place():
    """Place un nouveau jeton pour une unité (par défaut toutes ses figurines)."""
    data = request.get_json(force=True, silent=True) or request.form
    unit_id = int(data.get("unit_id") or 0)
    x = data.get("x")
    y = data.get("y")
    if x is None or y is None:
        x, y = 0.5, 0.5
    x = max(0.0, min(1.0, float(x)))
    y = max(0.0, min(1.0, float(y)))
    models_data = data.get("models")
    tid = models.add_unit_token(unit_id, x, y, models=models_data)
    return jsonify({"token_id": tid, "unit_id": unit_id, "x": x, "y": y})


@bp.route("/token/move", methods=["POST"])
def token_move():
    data = request.get_json(force=True, silent=True) or request.form
    token_id = int(data.get("token_id") or 0)
    x = max(0.0, min(1.0, float(data.get("x") or 0)))
    y = max(0.0, min(1.0, float(data.get("y") or 0)))
    models.update_token_position(token_id, x, y)
    return jsonify({"token_id": token_id, "x": x, "y": y})


@bp.route("/token/split", methods=["POST"])
def token_split():
    """Divise un jeton : détache 1 figurine dans un nouveau jeton juste à côté."""
    data = request.get_json(force=True, silent=True) or request.form
    token_id = int(data.get("token_id") or 0)
    new_id = models.split_token(token_id)
    if new_id is None:
        return jsonify({"ok": False, "error": "Jeton d'une seule figurine, impossible à diviser."})
    return jsonify({"ok": True, "token_id": token_id, "new_token_id": new_id})


@bp.route("/token/dead", methods=["POST"])
def token_dead():
    """Marque un jeton détruit (toggle) — reste sur le plateau, grisé."""
    data = request.get_json(force=True, silent=True) or request.form
    token_id = int(data.get("token_id") or 0)
    dead = models.set_token_dead(token_id)
    return jsonify({"token_id": token_id, "dead": dead})


@bp.route("/token/remove", methods=["POST"])
def token_remove():
    data = request.get_json(force=True, silent=True) or request.form
    token_id = int(data.get("token_id") or 0)
    models.delete_token(token_id)
    return jsonify({"token_id": token_id, "removed": True})


@bp.route("/cp", methods=["POST"])
def cp_adjust():
    data = request.get_json(force=True, silent=True) or request.form
    player_id = int(data.get("player_id") or 0)
    delta = int(data.get("delta") or 0)
    reason = (data.get("reason") or "").strip()
    ply = get_db().execute("SELECT game_id FROM players WHERE id=?", (player_id,)).fetchone()
    if not ply:
        abort(404)
    game = models.get_game(ply["game_id"])
    models.adjust_cp(player_id, delta, reason=reason, round_=game["round"], phase=game["phase"])
    get_db().commit()
    new_cp = get_db().execute("SELECT cp FROM players WHERE id=?", (player_id,)).fetchone()["cp"]
    return jsonify({"player_id": player_id, "cp": new_cp})


@bp.route("/vp", methods=["POST"])
def vp_adjust():
    data = request.get_json(force=True, silent=True) or request.form
    player_id = int(data.get("player_id") or 0)
    delta = int(data.get("delta") or 0)
    reason = (data.get("reason") or "").strip()
    models.adjust_vp(player_id, delta, reason=reason)
    get_db().commit()
    row = get_db().execute("SELECT vp_total FROM players WHERE id=?", (player_id,)).fetchone()
    return jsonify({"player_id": player_id, "vp_total": row["vp_total"]})


@bp.route("/stratagem/use", methods=["POST"])
def stratagem_use():
    data = request.get_json(force=True, silent=True) or request.form
    player_id = int(data.get("player_id") or 0)
    name = (data.get("name") or "Stratagem").strip()
    cp = int(data.get("cp") or 1)
    reason = f"Stratagem: {name}"
    ply = get_db().execute("SELECT game_id FROM players WHERE id=?", (player_id,)).fetchone()
    if not ply:
        abort(404)
    game = models.get_game(ply["game_id"])
    models.adjust_cp(player_id, -cp, reason=reason, stratagem_name=name,
                     round_=game["round"], phase=game["phase"])
    get_db().commit()
    new_cp = get_db().execute("SELECT cp FROM players WHERE id=?", (player_id,)).fetchone()["cp"]
    return jsonify({"player_id": player_id, "cp": new_cp, "stratagem": name, "spent": cp})


@bp.route("/mission/resolve-matrix", methods=["POST"])
def mission_resolve_matrix():
    data = request.get_json(force=True, silent=True) or request.form
    your_deck = data.get("your_deck")
    opp_deck = data.get("opp_deck")
    if not your_deck or not opp_deck:
        return jsonify({"card": None})
    card = M.resolve_primary_card(your_deck, opp_deck)
    return jsonify({"card": card})


def _unit_row(unit_id):
    """Fetch a unit row as a dict with parsed json fields (for the resolver)."""
    import json
    row = get_db().execute("SELECT * FROM units WHERE id=?", (unit_id,)).fetchone()
    if not row:
        return None
    u = dict(row)
    u["keywords"] = json.loads(u["keywords_json"] or "[]")
    u["stats"] = json.loads(u["stats_json"] or "{}")
    u["abilities"] = json.loads(u["abilities_json"] or "[]")
    u["weapons"] = json.loads(u["weapons_json"] or "[]")
    return u


@bp.route("/resolve-attack", methods=["POST"])
def resolve_attack():
    """Résolveur d'attaque (encart plateau) : calcule les cibles (blesser,
    sauvegarder, dégâts) pour une arme d'une unité attaquante vs une unité
    défenseuse. Aucun tir de dés — seulement le calcul des jets nécessaires."""
    data = request.get_json(force=True, silent=True) or request.form
    a_unit_id = int(data.get("a_unit_id") or 0)
    d_unit_id = int(data.get("d_unit_id") or 0)
    widx = int(data.get("w") or 0)
    a_unit = _unit_row(a_unit_id)
    d_unit = _unit_row(d_unit_id)
    if not a_unit or not d_unit:
        return jsonify({"ok": False, "error": "Unité introuvable."})
    weapons = a_unit["weapons"] or []
    if widx < 0 or widx >= len(weapons):
        return jsonify({"ok": False, "error": "Arme invalide."})
    weapon = weapons[widx]
    result = COMBAT.resolve_attack(
        weapon, d_unit.get("stats", {}) or {},
        num_attackers=a_unit["models_current"] or 1,
    )
    return jsonify({
        "ok": True,
        "weapon": weapon,
        "attacker": {"id": a_unit["id"], "name": a_unit["custom_name"] or a_unit["name"],
                     "models_current": a_unit["models_current"]},
        "defender": {"id": d_unit["id"], "name": d_unit["custom_name"] or d_unit["name"],
                     "stats": d_unit.get("stats", {}) or {},
                     "wounds_total": d_unit.get("wounds_total") or 0,
                     "wounds_current": (d_unit.get("wounds_current")
                                        if d_unit.get("wounds_current") is not None
                                        else d_unit.get("wounds_total") or 0)},
        "result": result,
    })