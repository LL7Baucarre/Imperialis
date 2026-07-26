"""Routes de partie : plateau principal, tracker VP, référence codex, modale unité."""
from flask import Blueprint, render_template, request, redirect, url_for, abort, jsonify, send_from_directory, flash

from app import models, config as cfg
from app.db import get_db
from app.helpers import get_game_or_404, game_context, friendly_faction_name, codex_pdf_for_faction
from app.data import bsdata, phases as P, missions as M
from app.data import combat as COMBAT
from app.data import combat_patrol as CP

bp = Blueprint("game", __name__)


@bp.route("/codex/<path:filename>")
def codex_file(filename):
    """Sert un PDF de codex depuis le dossier Rules and codex/."""
    return send_from_directory(str(cfg.CODEX_DIR), filename, conditional=True)


def _mission_card_image(deck_name, card_name):
    """Retourne l'URL de l'image d'une carte primaire (deck + card name)."""
    if not deck_name or not card_name:
        return None
    deck = M.primary_deck(deck_name)
    if not deck:
        return None
    for c in deck.get("cards", []):
        if c.get("name") == card_name:
            return M.primary_card_image_url(deck.get("slug", ""), c.get("slug", ""))
    return None


def _flat_units(units):
    """Flat list of units (both seats) for the interactive board + resolver
    (client-side). Each entry carries position, wounds, stats and weapons."""
    out = []
    for seat in (1, 2):
        for u in units.get(seat, []):
            out.append({
                "id": u["id"], "seat": seat,
                "name": u.get("custom_name") or u.get("name"),
                "models_current": u.get("models_current") or 0,
                "models_total": u.get("models_total") or 0,
                "wounds_current": u.get("wounds_current") if u.get("wounds_current") is not None else (u.get("wounds_total") or 0),
                "wounds_total": u.get("wounds_total") or 0,
                "battle_shocked": bool(u.get("battle_shocked")),
                "pos_x": u.get("pos_x"), "pos_y": u.get("pos_y"),
                "stats": u.get("stats") or {},
                "weapons": u.get("weapons") or [],
            })
    return out


def _board_payload(units):
    """Liste plate des unités (pour la palette de la page Carte) avec
    models/wounds. Retourne aussi un index {unit_id: entry}."""
    units_flat = []
    by_id = {}
    for seat in (1, 2):
        for u in units.get(seat, []):
            entry = {
                "id": u["id"], "seat": seat,
                "name": u.get("custom_name") or u.get("name"),
                "models_total": u.get("models_total") or 0,
                "models_current": u.get("models_current") or 0,
                "wounds_total": u.get("wounds_total") or 0,
                "wounds_current": (u.get("wounds_current")
                                   if u.get("wounds_current") is not None
                                   else (u.get("wounds_total") or 0)),
                "battle_shocked": bool(u.get("battle_shocked")),
            }
            units_flat.append(entry)
            by_id[u["id"]] = entry
    return units_flat, by_id


def _board_tokens(gid, units):
    """Jetons placés pour la page Carte, enrichis avec seat/nom et indicateurs
    de l'unité parente (badge modèles / PV). Retourne (units_flat, tokens)."""
    units_flat, by_id = _board_payload(units)
    tokens = []
    for t in models.get_tokens_for_game(gid):
        parent = by_id.get(t["unit_id"])
        if not parent:
            continue
        tokens.append({
            "id": t["id"], "unit_id": t["unit_id"], "seat": parent["seat"],
            "name": parent["name"],
            "pos_x": t["pos_x"], "pos_y": t["pos_y"],
            "models": t["models"], "dead": bool(t["dead"]), "label": t.get("label"),
            "models_total": parent["models_total"],
            "models_current": parent["models_current"],
            "wounds_total": parent["wounds_total"],
            "wounds_current": parent["wounds_current"],
            "battle_shocked": parent["battle_shocked"],
        })
    return units_flat, tokens


@bp.route("/play/<int:gid>")
def play(gid):
    g = get_game_or_404(gid)
    # Le plateau n'a de sens qu'une fois la partie démarrée. Sinon on renvoie
    # sur la configuration plutôt que d'afficher un plateau vide/cassé.
    if g["status"] != "playing":
        flash("La partie n'est pas encore démarrée — termine la configuration d'abord.", "info")
        return redirect(url_for("setup.setup_hub", gid=gid))
    _, players, units = game_context(gid)
    m = models.get_missions(gid)
    active_seat = g["active_player_seat"]

    # Données de phase pour le joueur actif
    phase = g["phase"]
    phase_data = P.PHASE_DATA.get(phase, {})
    active_player = players[active_seat]
    opp_seat = 2 if active_seat == 1 else 1
    opponent_player = players[opp_seat]
    active_faction = bsdata.get_faction(active_player["faction_file"]) if active_player.get("faction_file") else None
    opponent_faction = bsdata.get_faction(opponent_player["faction_file"]) if opponent_player.get("faction_file") else None
    # attach selected detachment to faction_data so phase_assist can surface its rule
    active_detachment = None
    if active_faction is not None and active_player.get("detachment"):
        try:
            for d in (active_faction.detachments or []):
                if (getattr(d, "name", None) or "") == active_player["detachment"]:
                    active_faction.selected_detachment = d
                    active_detachment = d
                    break
        except Exception:
            pass
    active_units = units.get(active_seat, [])
    assist = P.phase_assist(phase, active_faction, units=active_units,
                            round_=g["round"], opponent_faction_data=opponent_faction)

    # Cartes mission (images)
    p1_img = _mission_card_image(m and m["primary_deck_p1"], m and m["primary_card_p1"]) if m else None
    p2_img = _mission_card_image(m and m["primary_deck_p2"], m and m["primary_card_p2"]) if m else None

    # Cartes de force disposition (une par joueur) + layout de terrain du matchup
    fd_p1_img = M.force_disposition_image_url(m["force_disposition_p1"]) \
        if m and m["force_disposition_p1"] else None
    fd_p2_img = M.force_disposition_image_url(m["force_disposition_p2"]) \
        if m and m["force_disposition_p2"] else None
    layout_img, layout_battlemaster_url = (None, None)
    if m and m["primary_deck_p1"]:
        layout_img, layout_battlemaster_url = M.layout_for_deck(m["primary_deck_p1"])

    # Texte règles des cartes (primary p1/p2 + secondaires attacker/defender)
    p1_text = M.primary_card_text(m["primary_deck_p1"], m["primary_card_p1"]) \
        if m and m["primary_deck_p1"] and m["primary_card_p1"] else None
    p2_text = M.primary_card_text(m["primary_deck_p2"], m["primary_card_p2"]) \
        if m and m["primary_deck_p2"] and m["primary_card_p2"] else None
    sec_att_text = M.secondary_card_text(m["secondary_attacker"], "attacker") \
        if m and m["secondary_attacker"] else None
    sec_def_text = M.secondary_card_text(m["secondary_defender"], "defender") \
        if m and m["secondary_defender"] else None

    # annotations
    annotations = models.get_annotations(gid)

    # VP history for inline tracker
    vp_hist = models.get_vp_history(gid)

    # Flat unit list for the resolver encart (client-side).
    units_json = _flat_units(units)

    cp_mission = CP.get_mission(g["combat_patrol_mission"]) if g["game_mode"] == "combat_patrol" else None

    return render_template(
        "play.html", g=g, players=players, units=units, missions=m,
        phase=phase, phase_data=phase_data, assist=assist,
        active_seat=active_seat, active_player=active_player,
        active_detachment=(active_detachment.to_dict() if active_detachment else None),
        p1_img=p1_img, p2_img=p2_img,
        p1_text=p1_text, p2_text=p2_text,
        sec_att_text=sec_att_text, sec_def_text=sec_def_text,
        fd_p1_img=fd_p1_img, fd_p2_img=fd_p2_img,
        layout_img=layout_img, layout_battlemaster_url=layout_battlemaster_url,
        annotations=annotations, vp_hist=vp_hist,
        wound_table=P.WOUND_TABLE, pregame=P.PREGAME_STEPS,
        units_json=units_json,
        cp_mission=cp_mission, cp_secure_rule=CP.SECURE_OBJECTIVES_RULE,
        cp_battlefield_size=CP.BATTLEFIELD_SIZE,
    )


@bp.route("/play/<int:gid>/board")
def board(gid):
    """Plateau interactif en pleine page : layout en fond + jetons d'unités
    déplaçables (positions persistées). Les unités multi-figurines peuvent être
    divisées en plusieurs jetons ; un jeton peut être marqué détruit."""
    g = get_game_or_404(gid)
    if g["status"] != "playing":
        flash("Lance la partie pour utiliser le plateau interactif.", "info")
        return redirect(url_for("setup.setup_hub", gid=gid))
    _, players, units = game_context(gid)
    m = models.get_missions(gid)
    layout_img, layout_battlemaster_url = (None, None)
    if m and m["primary_deck_p1"]:
        layout_img, layout_battlemaster_url = M.layout_for_deck(m["primary_deck_p1"])
    units_flat, tokens = _board_tokens(gid, units)
    return render_template(
        "board.html", g=g, players=players,
        layout_img=layout_img, layout_battlemaster_url=layout_battlemaster_url,
        units_json=units_flat, tokens_json=tokens,
    )


@bp.route("/play/<int:gid>/tracker")
def tracker(gid):
    g = get_game_or_404(gid)
    _, players, _ = game_context(gid)
    vp_hist = models.get_vp_history(gid)
    # Construire un tableau round x seat
    grid = {}
    for r in range(1, g["round"] + 1):
        grid[r] = {1: None, 2: None}
    for v in vp_hist:
        # seat du player_id
        p = get_db().execute("SELECT seat FROM players WHERE id=?", (v["player_id"],)).fetchone()
        if p and v["round"] in grid:
            grid[v["round"]][p["seat"]] = v
    return render_template("tracker.html", g=g, players=players, grid=grid, vp_hist=vp_hist)


@bp.route("/play/<int:gid>/reference/<int:seat>")
def reference(gid, seat):
    if seat not in (1, 2):
        abort(404)
    g = get_game_or_404(gid)
    _, players, _ = game_context(gid)
    player = players[seat]
    faction_file = player.get("faction_file")
    faction_data = bsdata.get_faction(faction_file) if faction_file else None
    detachments = [d.to_dict() for d in (faction_data.detachments if faction_data else [])]
    faction_abilities = []
    if faction_data:
        fa = getattr(faction_data, "faction_abilities", None) or []
        faction_abilities = [a if isinstance(a, dict) else a.to_dict() for a in fa]
    codex_pdf = codex_pdf_for_faction(faction_file, player.get("faction_name"))
    return render_template(
        "reference.html", g=g, seat=seat, player=player,
        faction_data=faction_data, detachments=detachments,
        faction_abilities=faction_abilities, codex_pdf=codex_pdf,
    )


@bp.route("/play/<int:gid>/unit/<int:unit_id>")
def unit_modal(gid, unit_id):
    """Fragment HTML pour la modale de détail d'unité (récupéré via fetch)."""
    row = get_db().execute("SELECT * FROM units WHERE id=?", (unit_id,)).fetchone()
    if not row:
        abort(404)
    import json
    u = dict(row)
    u["keywords"] = json.loads(u["keywords_json"] or "[]")
    u["categories"] = json.loads(u.get("categories_json") or "[]")
    u["stats"] = json.loads(u["stats_json"] or "{}")
    u["abilities"] = json.loads(u["abilities_json"] or "[]")
    u["weapons"] = json.loads(u["weapons_json"] or "[]")
    u["half_strength"] = (u["models_current"] <= u["models_total"] / 2) if u["models_total"] else False
    u["enhancement"] = (
        {"name": u["enhancement_name"], "cost": u.get("enhancement_cost") or 0,
         "text": u.get("enhancement_text") or ""}
        if u.get("enhancement_name") else None
    )
    return render_template("unit_modal.html", u=u)