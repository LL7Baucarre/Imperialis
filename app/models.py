"""Schéma SQLite + helpers d'accès aux données pour Imperialis."""
import json
from app.db import get_db

# ---------------------------------------------------------------------------
# Schéma
# ---------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'setup',   -- setup | playing | finished
    round             INTEGER NOT NULL DEFAULT 1,
    phase             TEXT    NOT NULL DEFAULT 'Command',
    active_player_seat INTEGER NOT NULL DEFAULT 1,
    first_player_seat INTEGER NOT NULL DEFAULT 1,
    points_limit      INTEGER NOT NULL DEFAULT 2000,
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS players (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id       INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    seat          INTEGER NOT NULL,                     -- 1 ou 2
    name          TEXT NOT NULL,
    faction_file  TEXT,
    faction_name  TEXT,
    detachment    TEXT,
    cp            INTEGER NOT NULL DEFAULT 0,
    vp_total      INTEGER NOT NULL DEFAULT 0,
    UNIQUE(game_id, seat)
);

CREATE TABLE IF NOT EXISTS units (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id          INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    player_id        INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    bsdata_unit_id   TEXT,
    name             TEXT NOT NULL,
    custom_name      TEXT,
    points           INTEGER NOT NULL DEFAULT 0,
    models_total     INTEGER NOT NULL DEFAULT 1,
    models_current   INTEGER NOT NULL DEFAULT 1,
    wounds_total     INTEGER NOT NULL DEFAULT 0,
    wounds_current   INTEGER NOT NULL DEFAULT 0,
    battle_shocked   INTEGER NOT NULL DEFAULT 0,
    keywords_json    TEXT NOT NULL DEFAULT '[]',
    categories_json  TEXT NOT NULL DEFAULT '[]',
    stats_json       TEXT NOT NULL DEFAULT '{}',
    abilities_json   TEXT NOT NULL DEFAULT '[]',
    weapons_json     TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS game_missions (
    game_id              INTEGER PRIMARY KEY REFERENCES games(id) ON DELETE CASCADE,
    force_disposition_p1 TEXT,
    force_disposition_p2 TEXT,
    primary_deck_p1       TEXT,
    primary_deck_p2       TEXT,
    primary_card_p1       TEXT,
    primary_card_p2       TEXT,
    secondary_attacker   TEXT,
    secondary_defender    TEXT,
    matrix_autoresolved   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS vp_log (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id        INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    round          INTEGER NOT NULL,
    player_id      INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    vp_total_after INTEGER NOT NULL,
    delta          INTEGER NOT NULL,
    reason         TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS cp_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id       INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    round         INTEGER NOT NULL,
    phase         TEXT,
    player_id     INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    delta         INTEGER NOT NULL,
    reason        TEXT,
    stratagem_name TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS annotations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id    INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    round      INTEGER NOT NULL,
    phase      TEXT,
    player_id  INTEGER REFERENCES players(id) ON DELETE SET NULL,
    text       TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS dice_rolls (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id      INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    round        INTEGER NOT NULL,
    phase        TEXT,
    player_id    INTEGER REFERENCES players(id) ON DELETE SET NULL,
    count        INTEGER NOT NULL,
    sides        INTEGER NOT NULL DEFAULT 6,
    results_json TEXT NOT NULL DEFAULT '[]',
    sum          INTEGER NOT NULL DEFAULT 0,
    purpose      TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Jetons placés sur le plateau interactif. Une unité multi-figurines peut
-- être divisée en plusieurs jetons (chacun représente un sous-groupe de
-- modèles). Un jeton peut être marqué « détruit » (dead=1) pour rester
-- visible sur le plateau sans être retiré.
CREATE TABLE IF NOT EXISTS unit_tokens (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_id    INTEGER NOT NULL REFERENCES units(id) ON DELETE CASCADE,
    pos_x      REAL,
    pos_y      REAL,
    models     INTEGER NOT NULL DEFAULT 0,   -- nb de figurines de ce sous-groupe
    dead       INTEGER NOT NULL DEFAULT 0,   -- 1 = unité détruite (jeton grisé conservé)
    label      TEXT,                          -- suffixe optionnel (ex. « A », « B »)
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


# ---------------------------------------------------------------------------
# Helpers de sérialisation JSON
# ---------------------------------------------------------------------------
def _j(value):
    return json.dumps(value, ensure_ascii=False)


def _jd(text, default):
    if not text:
        return default
    try:
        return json.loads(text)
    except Exception:
        return default


# ---------------------------------------------------------------------------
# Games
# ---------------------------------------------------------------------------
def create_game(name, first_player_seat=1):
    db = get_db()
    cur = db.execute(
        "INSERT INTO games (name, first_player_seat, active_player_seat) VALUES (?,?,?)",
        (name, first_player_seat, first_player_seat),
    )
    gid = cur.lastrowid
    for seat in (1, 2):
        db.execute(
            "INSERT INTO players (game_id, seat, name) VALUES (?,?,?)",
            (gid, seat, f"Joueur {seat}"),
        )
    db.commit()
    return gid


def get_game(gid):
    return get_db().execute("SELECT * FROM games WHERE id=?", (gid,)).fetchone()


def delete_game(gid):
    """Supprime une partie et tout son contenu (joueurs, unités, missions,
    annotations, dés, historique VP/CP). Compte sur PRAGMA foreign_keys=ON et
    les ON DELETE CASCADE du schéma."""
    db = get_db()
    db.execute("DELETE FROM games WHERE id=?", (gid,))
    db.commit()


def set_game_state(gid, round_, phase, active_seat):
    get_db().execute(
        "UPDATE games SET round=?, phase=?, active_player_seat=?, status='playing' WHERE id=?",
        (round_, phase, active_seat, gid),
    )


def get_points_limit(gid) -> int:
    row = get_db().execute("SELECT points_limit FROM games WHERE id=?", (gid,)).fetchone()
    return int(row["points_limit"]) if row else 2000


def set_points_limit(gid, limit: int):
    get_db().execute("UPDATE games SET points_limit=? WHERE id=?", (int(limit), gid))
    get_db().commit()


# ---------------------------------------------------------------------------
# Players
# ---------------------------------------------------------------------------
def get_player(gid, seat):
    return get_db().execute(
        "SELECT * FROM players WHERE game_id=? AND seat=?", (gid, seat)
    ).fetchone()


def get_players(gid):
    return get_db().execute(
        "SELECT * FROM players WHERE game_id=? ORDER BY seat", (gid,)
    ).fetchall()


def set_player_faction(player_id, faction_file, faction_name, detachment=None):
    get_db().execute(
        "UPDATE players SET faction_file=?, faction_name=?, detachment=? WHERE id=?",
        (faction_file, faction_name, detachment, player_id),
    )


def adjust_cp(player_id, delta, reason="", stratagem_name=None, round_=1, phase=None):
    db = get_db()
    db.execute("UPDATE players SET cp = MAX(0, cp + ?) WHERE id=?", (delta, player_id))
    ply = db.execute("SELECT game_id, cp FROM players WHERE id=?", (player_id,)).fetchone()
    db.execute(
        "INSERT INTO cp_log (game_id, round, phase, player_id, delta, reason, stratagem_name) "
        "VALUES (?,?,?,?,?,?,?)",
        (ply["game_id"], round_, phase, player_id, delta, reason, stratagem_name),
    )


def adjust_vp(player_id, delta, reason=""):
    db = get_db()
    ply = db.execute("SELECT game_id, vp_total FROM players WHERE id=?", (player_id,)).fetchone()
    new_total = max(0, (ply["vp_total"] or 0) + delta)
    db.execute("UPDATE players SET vp_total=? WHERE id=?", (new_total, player_id))
    game = db.execute("SELECT round FROM games WHERE id=?", (ply["game_id"],)).fetchone()
    db.execute(
        "INSERT INTO vp_log (game_id, round, player_id, vp_total_after, delta, reason) "
        "VALUES (?,?,?,?,?,?)",
        (ply["game_id"], game["round"], player_id, new_total, delta, reason),
    )


# ---------------------------------------------------------------------------
# Units (rosters)
# ---------------------------------------------------------------------------
def add_unit(gid, player_id, unit_card, custom_name=None, models=None):
    """unit_card : objet UnitCard (app.data.bsdata) ou dict avec les mêmes champs."""
    u = unit_card
    stats = getattr(u, "statline", None) or (u.get("statline") if isinstance(u, dict) else None) or {}
    abilities = getattr(u, "abilities", None) or (u.get("abilities") if isinstance(u, dict) else None) or []
    weapons = getattr(u, "weapons", None) or (u.get("weapons") if isinstance(u, dict) else None) or []
    keywords = getattr(u, "keywords", None) or (u.get("keywords") if isinstance(u, dict) else None) or []
    categories = getattr(u, "categories", None) or (u.get("categories") if isinstance(u, dict) else None) or []
    uid = getattr(u, "id", None) or (u.get("id") if isinstance(u, dict) else None)
    name = getattr(u, "name", None) or (u.get("name") if isinstance(u, dict) else None)
    base_pts = getattr(u, "points", None) or (u.get("points") if isinstance(u, dict) else None) or 0
    transport = getattr(u, "transport", None) if not isinstance(u, dict) else u.get("transport")
    n_models = models or 1
    # Points 11e : coût par figurine × nombre de figurines. base_pts = coût de
    # l'unité pour sa taille mini (base_models) ; points_per_model est dérivé
    # côté bsdata quand possible, sinon on le recalcule ici.
    ppm = getattr(u, "points_per_model", None)
    if ppm is None and isinstance(u, dict):
        ppm = u.get("points_per_model")
    if not ppm:
        base_models = (getattr(u, "base_models", None)
                       or (u.get("base_models") if isinstance(u, dict) else None) or 1)
        try:
            base_models = max(1, int(base_models))
        except (TypeError, ValueError):
            base_models = 1
        ppm = round(base_pts / base_models) if base_pts else 0
    points = (ppm or 0) * n_models
    # Wounds (PV) : W characteristic per model * model count. Best-effort parse
    # via combat.parse_value (handles "3", "D6", "2D3+1" -> max).
    wounds_per_model = 1
    try:
        from app.data.combat import parse_value
        w = parse_value(stats.get("W") if isinstance(stats, dict) else None)
        if w and w > 0:
            wounds_per_model = w
    except Exception:
        pass
    wounds_total = wounds_per_model * n_models
    db = get_db()
    cur = db.execute(
        """INSERT INTO units
           (game_id, player_id, bsdata_unit_id, name, custom_name, points,
            models_total, models_current, wounds_total, wounds_current,
            keywords_json, categories_json,
            stats_json, abilities_json, weapons_json)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (gid, player_id, uid, name, custom_name, int(points),
         n_models, n_models, wounds_total, wounds_total,
         _j(keywords), _j(categories),
         _j(stats), _j(abilities), _j(weapons)),
    )
    db.commit()
    return cur.lastrowid


def get_units(player_id):
    rows = get_db().execute(
        "SELECT * FROM units WHERE player_id=? ORDER BY id", (player_id,)
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["keywords"] = _jd(r["keywords_json"], [])
        d["categories"] = _jd(r["categories_json"], [])
        d["stats"] = _jd(r["stats_json"], {})
        d["abilities"] = _jd(r["abilities_json"], [])
        d["weapons"] = _jd(r["weapons_json"], [])
        d["half_strength"] = (d["models_current"] <= d["models_total"] / 2) if d["models_total"] else False
        d["wounds_total"] = d.get("wounds_total") or 0
        d["wounds_current"] = d.get("wounds_current") if d.get("wounds_current") is not None else d["wounds_total"]
        d["pos_x"] = d.get("pos_x")
        d["pos_y"] = d.get("pos_y")
        out.append(d)
    return out


def remove_unit(unit_id):
    get_db().execute("DELETE FROM units WHERE id=?", (unit_id,))
    get_db().commit()


def set_unit_models(unit_id, current):
    get_db().execute("UPDATE units SET models_current=? WHERE id=?", (current, unit_id))
    get_db().commit()


def set_unit_wounds(unit_id, current):
    """Set the unit's remaining wounds (PV). Clamped to [0, wounds_total]."""
    db = get_db()
    r = db.execute("SELECT wounds_total FROM units WHERE id=?", (unit_id,)).fetchone()
    total = r["wounds_total"] if r else 0
    current = max(0, min(int(total), int(current)))
    db.execute("UPDATE units SET wounds_current=? WHERE id=?", (current, unit_id))
    db.commit()
    return current


def set_unit_position(unit_id, x, y):
    """Store a unit's board position as fractional coords (0..1, None to clear)."""
    db = get_db()
    if x is None or y is None:
        db.execute("UPDATE units SET pos_x=NULL, pos_y=NULL WHERE id=?", (unit_id,))
    else:
        db.execute("UPDATE units SET pos_x=?, pos_y=? WHERE id=?", (x, y, unit_id))
    db.commit()


def clear_unit_position(unit_id):
    db = get_db()
    db.execute("UPDATE units SET pos_x=NULL, pos_y=NULL WHERE id=?", (unit_id,))
    db.commit()


# ---------------------------------------------------------------------------
# Jetons du plateau interactif (unit_tokens)
# Une unité peut être divisée en plusieurs jetons ; un jeton peut être marqué
# détruit (dead) pour rester visible sans être retiré.
# ---------------------------------------------------------------------------
def get_tokens_for_game(gid):
    """Tous les jetons des unités d'une partie, avec le seat du propriétaire."""
    db = get_db()
    rows = db.execute(
        """SELECT t.*, u.player_id, u.game_id, p.seat
           FROM unit_tokens t
           JOIN units u ON u.id = t.unit_id
           JOIN players p ON p.id = u.player_id
           WHERE u.game_id = ?
           ORDER BY t.id""",
        (gid,),
    ).fetchall()
    return [dict(r) for r in rows]


def add_unit_token(unit_id, x, y, models=None, label=None):
    """Crée un jeton pour une unité. Si models n'est pas fourni, prend la totalité
    des modèles courants de l'unité."""
    db = get_db()
    if models is None:
        r = db.execute("SELECT models_current FROM units WHERE id=?", (unit_id,)).fetchone()
        models = r["models_current"] if r else 1
    models = max(1, int(models))
    cur = db.execute(
        "INSERT INTO unit_tokens (unit_id, pos_x, pos_y, models, label) VALUES (?,?,?,?,?)",
        (unit_id, x, y, models, label),
    )
    db.commit()
    return cur.lastrowid


def update_token_position(token_id, x, y):
    db = get_db()
    db.execute("UPDATE unit_tokens SET pos_x=?, pos_y=? WHERE id=?", (x, y, token_id))
    db.commit()


def split_token(token_id):
    """Divise un jeton en deux : détache 1 figurine dans un nouveau jeton placé
    juste à côté. Retourne l'id du nouveau jeton (ou None si le jeton source a
    1 figurine ou moins)."""
    db = get_db()
    r = db.execute("SELECT * FROM unit_tokens WHERE id=?", (token_id,)).fetchone()
    if not r or r["models"] <= 1:
        return None
    db.execute("UPDATE unit_tokens SET models=? WHERE id=?", (r["models"] - 1, token_id))
    nx = (r["pos_x"] or 0.5) + 0.04
    ny = (r["pos_y"] or 0.5) + 0.04
    nx = min(1.0, max(0.0, nx))
    ny = min(1.0, max(0.0, ny))
    cur = db.execute(
        "INSERT INTO unit_tokens (unit_id, pos_x, pos_y, models, label) VALUES (?,?,?,?,?)",
        (r["unit_id"], nx, ny, 1, r["label"]),
    )
    db.commit()
    return cur.lastrowid


def set_token_models(token_id, models):
    db = get_db()
    db.execute("UPDATE unit_tokens SET models=? WHERE id=?", (max(0, int(models)), token_id))
    db.commit()


def set_token_dead(token_id, dead=None):
    """Marque un jeton comme détruit (ou le rétablit). Toggle si dead est None."""
    db = get_db()
    r = db.execute("SELECT dead FROM unit_tokens WHERE id=?", (token_id,)).fetchone()
    if not r:
        return None
    if dead is None:
        dead = 0 if r["dead"] else 1
    db.execute("UPDATE unit_tokens SET dead=? WHERE id=?", (1 if dead else 0, token_id))
    db.commit()
    return 1 if dead else 0


def delete_token(token_id):
    db = get_db()
    db.execute("DELETE FROM unit_tokens WHERE id=?", (token_id,))
    db.commit()


def toggle_unit_shock(unit_id, shocked=None):
    db = get_db()
    if shocked is None:
        r = db.execute("SELECT battle_shocked FROM units WHERE id=?", (unit_id,)).fetchone()
        shocked = 0 if r["battle_shocked"] else 1
    db.execute("UPDATE units SET battle_shocked=? WHERE id=?", (shocked, unit_id))
    db.commit()
    return shocked


# ---------------------------------------------------------------------------
# Missions
# ---------------------------------------------------------------------------
def set_missions(gid, **fields):
    allowed = {"force_disposition_p1", "force_disposition_p2", "primary_deck_p1",
               "primary_deck_p2", "primary_card_p1", "primary_card_p2",
               "secondary_attacker", "secondary_defender", "matrix_autoresolved"}
    cols, vals = [], []
    for k, v in fields.items():
        if k in allowed:
            cols.append(f"{k}=?")
            vals.append(v)
    if not cols:
        return
    db = get_db()
    db.execute("INSERT OR IGNORE INTO game_missions (game_id) VALUES (?)", (gid,))
    db.execute(f"UPDATE game_missions SET {', '.join(cols)} WHERE game_id=?", (*vals, gid))
    db.commit()


def get_missions(gid):
    return get_db().execute("SELECT * FROM game_missions WHERE game_id=?", (gid,)).fetchone()


# ---------------------------------------------------------------------------
# Annotations & dés & historique
# ---------------------------------------------------------------------------
def add_annotation(gid, round_, phase, player_id, text):
    get_db().execute(
        "INSERT INTO annotations (game_id, round, phase, player_id, text) VALUES (?,?,?,?,?)",
        (gid, round_, phase, player_id, text),
    )
    get_db().commit()


def get_annotations(gid):
    return get_db().execute(
        "SELECT * FROM annotations WHERE game_id=? ORDER BY id DESC LIMIT 200", (gid,)
    ).fetchall()


def add_dice_roll(gid, round_, phase, player_id, count, sides, results, sum_, purpose):
    get_db().execute(
        "INSERT INTO dice_rolls (game_id, round, phase, player_id, count, sides, "
        "results_json, sum, purpose) VALUES (?,?,?,?,?,?,?,?,?)",
        (gid, round_, phase, player_id, count, sides, _j(results), sum_, purpose),
    )
    get_db().commit()


def get_dice_rolls(gid, limit=50):
    return get_db().execute(
        "SELECT * FROM dice_rolls WHERE game_id=? ORDER BY id DESC LIMIT ?", (gid, limit)
    ).fetchall()


def get_vp_history(gid):
    rows = get_db().execute(
        "SELECT round, player_id, vp_total_after, delta, reason, created_at "
        "FROM vp_log WHERE game_id=? ORDER BY id", (gid,)
    ).fetchall()
    return [dict(r) for r in rows]