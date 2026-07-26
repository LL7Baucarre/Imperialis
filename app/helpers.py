"""Helpers partagés : nettoyage markup BSData, choix de factions, contexte de partie."""
import re
import html as _html
from markupsafe import Markup
from flask import abort, url_for
from app.data import bsdata as bs


# ---------------------------------------------------------------------------
# Markup BSData -> HTML sûr
# ---------------------------------------------------------------------------
def clean_bsdata(text):
    """Convertit le markup BattleScribe (^^**gras**^^, **gras**, \\n) en HTML
    échappé, renvoyé comme ``Markup`` (safe) pour ne pas être ré-échappé par
    Jinja lors du rendu (``{{ x | bsd }}`` sans ``|safe``)."""
    if not text:
        return Markup("")
    s = str(text)
    # BSData mixe gras (**) et surlignage (^^). Les formes combinées ^^**X**^^
    # et **^^X^^** sont ramenées à **X** en collapsant les frontières mixtes,
    # pour éviter qu'un regex ne croise deux marqueurs adjacents.
    s = s.replace("^^**", "**").replace("**^^", "**")
    s = s.replace("****", "**")
    # formes restantes -> <strong>
    s = re.sub(r"\^\*(\*(.+?)\*)\*\^", r"<strong>\2</strong>", s)   # ^**X**^
    s = re.sub(r"\^\^(.+?)\^\^", r"<strong>\1</strong>", s)         # ^^X^^
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)         # **X**
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    # échapper le reste, puis réintégrer les <strong> placés
    s = _html.escape(s)
    s = s.replace("&lt;strong&gt;", "<strong>").replace("&lt;/strong&gt;", "</strong>")
    s = s.replace("\n", "<br>")
    return Markup(s)


def plain_bsdata(text):
    """Version texte plat (sans balises) pour attributs/titres."""
    if not text:
        return ""
    s = str(text)
    s = re.sub(r"\^\*?\*?", "", s)
    s = s.replace("**", "").replace("^^", "")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


# ---------------------------------------------------------------------------
# Factions jouables (on exclut les bibliothèques partagées et Unaligned)
# ---------------------------------------------------------------------------
_EXCLUDE = ("Library", "Unaligned Forces")


def playable_factions():
    out = []
    for f in bs.list_factions():
        fname = f.get("name", "") or f.get("file", "")
        if any(x in fname or x in f.get("file", "") for x in _EXCLUDE):
            continue
        out.append(f)
    out.sort(key=lambda f: (f.get("name", "") or f.get("file", "")).lower())
    return out


def friendly_faction_name(faction_file, fallback=None):
    f = next((x for x in bs.list_factions() if x["file"] == faction_file), None)
    if f and f.get("name"):
        # "Imperium - Adeptus Astartes - Space Marines" -> garder le dernier segment significatif
        return f["name"]
    return fallback or faction_file


def codex_pdf_for_faction(faction_file, faction_name):
    """Retourne le chemin (relatif au projet) d'un PDF de codex si présent, sinon None."""
    import os
    from app import config as cfg
    if not faction_name:
        return None
    # heuristique : normaliser le nom de faction pour matcher un nom de fichier PDF
    fn = (faction_name or "").lower()
    mapping = {
        "adepta sororitas": "Adepta_Sororitas",
        "adeptus custodes": "Adeptus_Custodes",
        "adeptus mechanicus": "Adeptus_Mechanicus",
        "aeldari": "Aeldari", "asuryani": "Aeldari", "craftworld": "Aeldari",
        "astra militarum": "Astra_Militarum",
        "black templars": "Black_Templars",
        "blood angels": "Blood_Angels",
        "genestealer": "Cultes_Genestealer", "cultes genestealer": "Cultes_Genestealer",
        "dark angels": "Dark_Angels",
        "death guard": "Death_Guard",
        "emperors children": "Emperors_Children", "emperor's children": "Emperors_Children",
        "tau": "Empire_Tau", "t'au": "Empire_Tau",
        "imperial agent": "Imperial_Agent",
        "leagues of votann": "Leagues_Of_Votann",
        "orks": "Orks",
        "space marines": "Space_Marines",
        "space marines du chaos": "Space_Marines_Du_Chaos", "chaos space marines": "Space_Marines_Du_Chaos",
        "space wolves": "Space_Wolves",
        "tyranids": "Tyranides", "tyranides": "Tyranides",
        "world eaters": "World_Eaters",
        "necrons": "Necrons",
        "drukhari": "Drukhari",
        "grey knights": "Grey_Knight", "grey knight": "Grey_Knight",
        "thousand sons": "Thousand_Sons",
    }
    key = None
    for k, v in mapping.items():
        if k in fn:
            key = v
            break
    if not key:
        return None
    for ext in (".pdf",):
        cand = f"Codex-{key}-V10-VF{ext}"
        alt = f"Codex_V10-{key}-VF{ext}"
        for name in (cand, alt):
            p = cfg.CODEX_DIR / name
            if p.exists():
                return str(p.relative_to(cfg.BASE_DIR)).replace("\\", "/")
    return None


# ---------------------------------------------------------------------------
# Contexte de partie
# ---------------------------------------------------------------------------
def get_game_or_404(gid):
    from app import models
    g = models.get_game(gid)
    if not g:
        abort(404)
    return g


def game_context(gid):
    """Retourne (game, players_by_seat, units_by_player) pour une partie."""
    from app import models
    g = models.get_game(gid)
    players = {p["seat"]: dict(p) for p in models.get_players(gid)}
    units = {seat: models.get_units(p["id"]) for seat, p in players.items()}
    return g, players, units


def seat_label(seat):
    return f"Joueur {seat}"