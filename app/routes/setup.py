"""Routes de pré-partie : création, constructeur de roster, choix de mission."""
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, Response

import json
import datetime as _dt

from app import models
from app.db import get_db
from app.helpers import (
    get_game_or_404, game_context, playable_factions, friendly_faction_name,
    codex_pdf_for_faction,
)
from app.data import bsdata, missions as M
from app.data import importer as IMP
from app.data import validator as VAL

bp = Blueprint("setup", __name__)


# Organisation du sélecteur d'unités par rôle (Army Roster 11e).
#   ROSTER_GROUPS  = ordre de priorité d'affectation (une unité peut porter
#                    plusieurs catégories ; on prend la plus spécifique).
#   GROUP_DISPLAY  = ordre d'affichage des en-têtes.
# NB : les unités qui ne matchent aucun de ces rôles tombent dans « Autres ».
#     Les alliés cross-faction (Imperial Agents, Knights…) ne sont pas inclus
#     ici (nécessite les relations d'alliance par faction).
ROSTER_GROUPS = ["Epic Hero", "Character", "Battleline", "Dedicated Transport",
                 "Fortification", "Mounted", "Vehicle", "Infantry"]
GROUP_DISPLAY = ["Epic Hero", "Character", "Battleline", "Infantry", "Mounted",
                 "Vehicle", "Dedicated Transport", "Fortification"]


def _roster_group(u):
    cats = set(u.categories or [])
    for g in ROSTER_GROUPS:
        if g in cats:
            return g
    return "Autres"


# ---------------------------------------------------------------------------
# Accueil + création
# ---------------------------------------------------------------------------
@bp.route("/")
def home():
    rows = get_db().execute(
        "SELECT id, name, status, round, created_at FROM games ORDER BY id DESC"
    ).fetchall()
    return render_template("home.html", games=rows)


@bp.route("/new", methods=["POST"])
def new_game():
    name = (request.form.get("name") or "").strip() or "Nouvelle partie"
    gid = models.create_game(name, first_player_seat=1)
    return redirect(url_for("setup.roster", gid=gid, seat=1))


@bp.route("/delete/<int:gid>", methods=["POST"])
def delete_game(gid):
    """Supprime une partie (et tout son contenu via ON DELETE CASCADE)."""
    g = models.get_game(gid)
    if g:
        models.delete_game(gid)
        flash(f"Partie « {g['name']} » supprimée.", "info")
    return redirect(url_for("setup.home"))


# ---------------------------------------------------------------------------
# Hub de setup
# ---------------------------------------------------------------------------
@bp.route("/setup/<int:gid>")
def setup_hub(gid):
    g = get_game_or_404(gid)
    _, players, units = game_context(gid)

    # Étapes guidées (pour les débutants) : on calcule l'état de chaque étape
    # pour afficher des indicateurs de progression côté template.
    p1, p2 = players[1], players[2]
    step1 = {
        "done_p1": bool(p1.get("faction_file")) and len(units.get(1, [])) > 0,
        "done_p2": bool(p2.get("faction_file")) and len(units.get(2, [])) > 0,
    }
    m = models.get_missions(gid)
    step2 = {"done": bool(m and (m.get("force_disposition_p1") or m.get("primary_card_p1")))}
    ready = step1["done_p1"] and step1["done_p2"]
    step3 = {"done": ready and step2["done"]}

    return render_template("setup_hub.html", g=g, players=players, units=units,
                           ready=ready, step1=step1, step2=step2, step3=step3,
                           has_mission=bool(m and (m.get("force_disposition_p1") or m.get("primary_card_p1"))))


# ---------------------------------------------------------------------------
# Constructeur de roster
# ---------------------------------------------------------------------------
@bp.route("/setup/<int:gid>/roster/<int:seat>")
def roster(gid, seat):
    if seat not in (1, 2):
        abort(404)
    g = get_game_or_404(gid)
    _, players, units = game_context(gid)
    player = players[seat]
    other_seat = 2 if seat == 1 else 1

    faction_file = player.get("faction_file")
    faction_data = bsdata.get_faction(faction_file) if faction_file else None
    factions = playable_factions()

    # Recherche d'unités (regroupées par rôle 11e — Army Roster)
    search = request.args.get("q", "").strip()
    category = request.args.get("cat", "").strip() or None
    if category and category not in GROUP_DISPLAY and category != "Autres":
        category = None
    units_browser = []
    grouped = {}
    if faction_data:
        units_browser = bsdata.faction_units(faction_file, search=search or None)
        units_browser = units_browser[:300]
        for u in units_browser:
            grouped.setdefault(_roster_group(u), []).append(u)
    ordered_groups = [(g, grouped[g]) for g in GROUP_DISPLAY if g in grouped]
    if "Autres" in grouped:
        ordered_groups.append(("Autres", grouped["Autres"]))
    if category:
        ordered_groups = [(g, lst) for g, lst in ordered_groups if g == category]

    detachments = []
    if faction_data:
        detachments = [d.to_dict() for d in faction_data.detachments]
    active_detachment = next((d for d in detachments if d["name"] == player.get("detachment")), None)

    # BSData donne les points pour l'unité ; on somme les points des unités du roster
    roster_units = units.get(seat, [])
    total_pts = sum(u["points"] for u in roster_units)
    points_limit = models.get_points_limit(gid)
    issues = VAL.validate_roster(
        roster_units, points_limit=points_limit,
        detachment=player.get("detachment"),
    )
    taken_enhancements = {u["enhancement"]["name"] for u in roster_units if u.get("enhancement")}

    return render_template(
        "setup_roster.html", g=g, seat=seat, other_seat=other_seat,
        player=player, factions=factions, faction_file=faction_file,
        faction_name=friendly_faction_name(faction_file, player.get("faction_name")),
        faction_data=faction_data, detachments=detachments,
        active_detachment=active_detachment, taken_enhancements=taken_enhancements,
        units_browser=units_browser, groups=ordered_groups, group_options=GROUP_DISPLAY,
        search=search, category=category, roster=roster_units, total_pts=total_pts,
        points_limit=points_limit, issues=issues,
        other_ready=bool(players[other_seat].get("faction_file")),
    )


@bp.route("/setup/<int:gid>/faction/<int:seat>", methods=["POST"])
def set_faction(gid, seat):
    get_game_or_404(gid)
    _, players, _ = game_context(gid)
    player = players[seat]
    faction_file = request.form.get("faction_file")
    detachment = request.form.get("detachment") or None
    if faction_file and any(f["file"] == faction_file for f in playable_factions()):
        fname = friendly_faction_name(faction_file)
        # reset du roster si on change de faction
        if player.get("faction_file") and player.get("faction_file") != faction_file:
            get_db().execute("DELETE FROM units WHERE player_id=?", (player["id"],))
        models.set_player_faction(player["id"], faction_file, fname, detachment)
        get_db().commit()
    return redirect(url_for("setup.roster", gid=gid, seat=seat))


@bp.route("/setup/<int:gid>/points-limit", methods=["POST"])
def set_points_limit(gid):
    get_game_or_404(gid)
    try:
        limit = int(request.form.get("points_limit") or 2000)
    except ValueError:
        limit = 2000
    limit = max(250, min(10000, limit))
    models.set_points_limit(gid, limit)
    seat = request.form.get("seat") or 1
    return redirect(url_for("setup.roster", gid=gid, seat=int(seat)))


@bp.route("/setup/<int:gid>/unit/add/<int:seat>", methods=["POST"])
def add_unit_route(gid, seat):
    g = get_game_or_404(gid)
    _, players, _ = game_context(gid)
    player = players[seat]
    unit_id = request.form.get("unit_id")
    models_count = int(request.form.get("models") or 1)
    if not player.get("faction_file") or not unit_id:
        abort(400)
    unit = bsdata.get_unit(player["faction_file"], unit_id)
    if not unit:
        abort(404)
    custom_name = (request.form.get("custom_name") or "").strip() or None
    models.add_unit(gid, player["id"], unit, custom_name=custom_name, models=models_count)
    return redirect(url_for("setup.roster", gid=gid, seat=seat))


@bp.route("/setup/<int:gid>/unit/remove/<int:unit_id>", methods=["POST"])
def remove_unit_route(gid, unit_id):
    get_game_or_404(gid)
    models.remove_unit(unit_id)
    # redirige vers le seat du roster concerné
    row = get_db().execute("SELECT player_id FROM units WHERE id=?", (unit_id,)).fetchone()
    seat = 1
    if row:
        p = get_db().execute("SELECT seat FROM players WHERE id=?", (row["player_id"],)).fetchone()
        if p:
            seat = p["seat"]
    return redirect(url_for("setup.roster", gid=gid, seat=seat))


@bp.route("/setup/<int:gid>/unit/enhancement/<int:seat>/<int:unit_id>", methods=["POST"])
def set_unit_enhancement_route(gid, seat, unit_id):
    """Assigne (ou retire) un Enhancement du détachement actif à une unité
    Character du roster. En 11e, un Enhancement donné n'est utilisable qu'une
    fois par armée — on l'impose ici plutôt que de le faire vérifier au
    joueur."""
    if seat not in (1, 2):
        abort(404)
    g = get_game_or_404(gid)
    _, players, units = game_context(gid)
    player = players[seat]

    row = get_db().execute("SELECT player_id, categories_json FROM units WHERE id=?", (unit_id,)).fetchone()
    if not row or row["player_id"] != player["id"]:
        abort(404)

    enh_name = (request.form.get("enhancement") or "").strip()
    if not enh_name:
        models.clear_unit_enhancement(unit_id)
        return redirect(url_for("setup.roster", gid=gid, seat=seat))

    categories = json.loads(row["categories_json"] or "[]")
    if "Character" not in categories:
        flash("Seul un Personnage (Character) peut recevoir un Enhancement.", "error")
        return redirect(url_for("setup.roster", gid=gid, seat=seat))

    faction_data = bsdata.get_faction(player["faction_file"]) if player.get("faction_file") else None
    det = next((d for d in (faction_data.detachments if faction_data else [])
                if d.name == player.get("detachment")), None)
    enh = next((e for e in (det.enhancements if det else []) if e["name"] == enh_name), None)
    if not enh:
        abort(400)

    # Un Enhancement donné : un seul exemplaire par armée.
    already = next((u for u in units.get(seat, [])
                    if u["id"] != unit_id and (u.get("enhancement") or {}).get("name") == enh_name), None)
    if already:
        flash(f"« {enh_name} » est déjà pris par « {already.get('custom_name') or already['name']} » "
              f"— un seul exemplaire par armée.", "error")
        return redirect(url_for("setup.roster", gid=gid, seat=seat))

    models.set_unit_enhancement(unit_id, enh["name"], cost=enh.get("cost") or 0, text=enh.get("text") or "")
    return redirect(url_for("setup.roster", gid=gid, seat=seat))


# ---------------------------------------------------------------------------
# Import de roster (NewRecruit .rosz/.json, BattleScribe .ros/.rosz)
# ---------------------------------------------------------------------------
@bp.route("/setup/<int:gid>/import/<int:seat>", methods=["POST"])
def import_roster(gid, seat):
    if seat not in (1, 2):
        abort(404)
    g = get_game_or_404(gid)
    _, players, _ = game_context(gid)
    player = players[seat]

    upload = request.files.get("roster_file")
    if not upload or not upload.filename:
        flash("Aucun fichier reçu.", "error")
        return redirect(url_for("setup.roster", gid=gid, seat=seat))

    data = upload.read()
    try:
        parsed = IMP.parse_roster(upload.filename, data)
    except Exception as exc:
        flash(f"Impossible de lire le fichier ({exc}).", "error")
        return redirect(url_for("setup.roster", gid=gid, seat=seat))

    if not parsed.units:
        flash("Format non reconnu ou roster vide. Formats acceptés : export "
              "Imperialis (JSON), NewRecruit « BattleScribe (.rosz) » ou JSON, "
              "BattleScribe (.ros/.rosz).", "error")
        return redirect(url_for("setup.roster", gid=gid, seat=seat))

    prefer = player.get("faction_file")
    result = IMP.resolve(parsed, prefer_faction_file=prefer)

    # If the player has no faction yet, adopt the roster's faction (+ detachment,
    # when known exactly — our own export carries it; BattleScribe/NewRecruit
    # rosters don't expose it in a form we can trust).
    roster_faction = result.faction_file
    if not prefer and roster_faction:
        fname = friendly_faction_name(roster_faction, parsed.faction_name)
        models.set_player_faction(player["id"], roster_faction, fname, parsed.detachment)
        get_db().commit()
        flash(f"Faction définie : {fname}."
              + (f" Détachement : {parsed.detachment}." if parsed.detachment else ""), "info")
        prefer = roster_faction
    elif prefer and roster_faction and prefer != roster_faction:
        flash(f"Note : le roster est pour « {parsed.faction_name or roster_faction} » "
              f"mais ta faction courante est différente — les unités communes "
              f"ont été ajoutées quand même.", "info")

    added = 0
    for m in result.matched:
        models.add_unit(gid, player["id"], m["unit"], models=m["models"])
        added += 1
    get_db().commit()

    summary = f"Importé {added} unité(s) depuis le roster."
    if result.unmatched:
        names = ", ".join(u["name"] for u in result.unmatched[:8])
        more = "" if len(result.unmatched) <= 8 else f" (+{len(result.unmatched) - 8} autres)"
        summary += f" {len(result.unmatched)} non reconnue(s) : {names}{more}."
    flash(summary, "ok")
    return redirect(url_for("setup.roster", gid=gid, seat=seat))


# ---------------------------------------------------------------------------
# Export de roster (JSON téléchargeable, pour conserver/réutiliser une armée)
# ---------------------------------------------------------------------------
@bp.route("/setup/<int:gid>/export/<int:seat>")
def export_roster(gid, seat):
    if seat not in (1, 2):
        abort(404)
    g = get_game_or_404(gid)
    _, players, units = game_context(gid)
    player = players[seat]
    roster_units = units.get(seat, [])
    payload = {
        "format": "imperialis-roster",
        "version": 1,
        "exported_at": _dt.datetime.utcnow().isoformat() + "Z",
        "game": {"id": gid, "name": g["name"]},
        "player": {
            "name": player.get("name"),
            "faction_file": player.get("faction_file"),
            "faction_name": player.get("faction_name"),
            "detachment": player.get("detachment"),
        },
        "points_limit": models.get_points_limit(gid),
        "total_points": sum(u["points"] for u in roster_units),
        "units": [
            {
                "bsdata_unit_id": u.get("bsdata_unit_id"),
                "name": u.get("name"),
                "custom_name": u.get("custom_name"),
                "points": u.get("points"),
                "models_total": u.get("models_total"),
                "categories": u.get("categories") or [],
                "keywords": u.get("keywords") or [],
                "stats": u.get("stats") or {},
                "abilities": u.get("abilities") or [],
                "weapons": u.get("weapons") or [],
            }
            for u in roster_units
        ],
    }
    body = json.dumps(payload, indent=2, ensure_ascii=False)
    p_slug = (player.get("name") or f"joueur{seat}").strip().replace(" ", "_")
    f_slug = (player.get("faction_file") or "armee").replace(".json", "")
    resp = Response(body, mimetype="application/json")
    resp.headers["Content-Disposition"] = f'attachment; filename="imperialis-{f_slug}-{p_slug}.json"'
    return resp


# ---------------------------------------------------------------------------
# Fiche complète d'une unité BSData (rendu pour la modale du sélecteur)
# ---------------------------------------------------------------------------
@bp.route("/setup/<int:gid>/unit-card/<int:seat>/<unit_id>")
def unit_card(gid, seat, unit_id):
    if seat not in (1, 2):
        abort(404)
    get_game_or_404(gid)
    _, players, _ = game_context(gid)
    faction_file = players[seat].get("faction_file")
    if not faction_file:
        abort(404)
    u = bsdata.get_unit(faction_file, unit_id)
    if not u:
        abort(404)
    data = {
        "name": u.name, "custom_name": None,
        "keywords": u.keywords, "categories": u.categories,
        "stats": u.statline,
        "abilities": u.abilities, "weapons": u.weapons,
        "transport": u.transport,
        "models_total": u.base_models, "models_current": u.base_models,
        "points": u.points, "points_per_model": u.points_per_model,
        "half_strength": False, "battle_shocked": False,
    }
    return render_template("unit_modal.html", u=data)


# ---------------------------------------------------------------------------
# Choix de mission
# ---------------------------------------------------------------------------
@bp.route("/setup/<int:gid>/mission", methods=["GET", "POST"])
def mission(gid):
    g = get_game_or_404(gid)
    _, players, units = game_context(gid)
    if request.method == "POST":
        fd1 = request.form.get("force_disposition_p1") or None
        fd2 = request.form.get("force_disposition_p2") or None
        card1 = request.form.get("primary_card_p1") or None
        card2 = request.form.get("primary_card_p2") or None
        sec_att = request.form.get("secondary_attacker") or None
        sec_def = request.form.get("secondary_defender") or None
        # auto-résolution matrix si pas de surcharge
        auto = 0
        if fd1 and fd2 and not card1:
            card1 = M.resolve_primary_card(fd1, fd2)
            auto = 1
        if fd1 and fd2 and not card2:
            card2 = M.resolve_primary_card(fd2, fd1)
            auto = 1
        models.set_missions(
            gid,
            force_disposition_p1=fd1, force_disposition_p2=fd2,
            primary_deck_p1=fd1, primary_deck_p2=fd2,
            primary_card_p1=card1, primary_card_p2=card2,
            secondary_attacker=sec_att, secondary_defender=sec_def,
            matrix_autoresolved=auto,
        )
        # store deck names too (deck == disposition name)
        return redirect(url_for("setup.start_confirm", gid=gid))

    # GET
    decks = M.primary_decks()
    force_disps = M.force_dispositions()
    secondaries = M.secondary_cards()
    layouts = [{**l, "image_url": M.image_rel_to_url(l.get("image"))}
               for l in M.layouts()]
    m = models.get_missions(gid)
    current = dict(m) if m else {}

    # Image maps for live preview of cards at configuration time.
    fd_images = [{"name": fd.get("name"), "image_url": M.image_rel_to_url(fd.get("image"))}
                 for fd in force_disps]
    primary_images = {
        d.get("name"): [{"name": c.get("name"),
                         "image_url": M.image_rel_to_url(c.get("image"))}
                        for c in d.get("cards", [])]
        for d in decks
    }
    secondary_images = [{"name": c.get("name"), "role": c.get("role"),
                         "image_url": M.image_rel_to_url(c.get("image"))}
                        for c in secondaries]

    return render_template(
        "setup_mission.html", g=g, players=players, decks=decks,
        force_disps=force_disps, secondaries=secondaries, layouts=layouts,
        current=current, resolve=M.resolve_primary_card,
        fd_images=fd_images, primary_images=primary_images,
        secondary_images=secondary_images,
    )


@bp.route("/setup/<int:gid>/start", methods=["GET", "POST"])
def start_confirm(gid):
    g = get_game_or_404(gid)
    _, players, units = game_context(gid)
    if request.method == "POST":
        first = int(request.form.get("first_player_seat") or 1)
        get_db().execute(
            "UPDATE games SET status='playing', round=1, phase='Command', "
            "active_player_seat=?, first_player_seat=? WHERE id=?",
            (first, first, gid),
        )
        get_db().commit()
        # 11e : round 1 Command phase — les deux joueurs gagnent 1 CP
        _, players, _ = game_context(gid)
        for seat, p in players.items():
            models.adjust_cp(p["id"], +1, reason="Gain CP (Round 1 Command phase)",
                             round_=1, phase="Command")
        get_db().commit()
        return redirect(url_for("game.play", gid=gid))
    m = models.get_missions(gid)
    return render_template("start_confirm.html", g=g, players=players,
                           units=units, missions=m)