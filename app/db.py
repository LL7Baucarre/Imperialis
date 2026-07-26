"""Gestion de la connexion SQLite + initialisation du schéma."""
import sqlite3
from flask import g, current_app


def get_db() -> sqlite3.Connection:
    """Retourne la connexion SQLite attachée à la requête Flask courante."""
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(db_path):
    """Crée le schéma si absent et fait migrer les anciennes bases (ajoute les
    colonnes introduites après la première version)."""
    from app import models
    con = sqlite3.connect(db_path)
    con.executescript(models.SCHEMA)

    # Migrations : ajoute les colonnes apparues après la version initiale du
    # schéma (CREATE TABLE IF NOT EXISTS ne les ajoute pas sur une base déjà
    # existante). Idempotent.
    migrations = [
        ("units", "categories_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("games", "points_limit", "INTEGER NOT NULL DEFAULT 2000"),
        ("units", "wounds_total", "INTEGER NOT NULL DEFAULT 0"),
        ("units", "wounds_current", "INTEGER NOT NULL DEFAULT 0"),
        ("units", "pos_x", "REAL"),
        ("units", "pos_y", "REAL"),
        ("units", "enhancement_name", "TEXT"),
        ("units", "enhancement_cost", "INTEGER NOT NULL DEFAULT 0"),
        ("units", "enhancement_text", "TEXT"),
        ("games", "game_mode", "TEXT NOT NULL DEFAULT 'standard'"),
        ("games", "combat_patrol_mission", "TEXT"),
    ]
    for table, column, ddl in migrations:
        cols = {row[1] for row in con.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in cols:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
    con.commit()
    con.close()


def commit():
    get_db().commit()