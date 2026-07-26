"""Configuration de l'application Imperialis."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # .../Imperialis

# Données BSData (cloné)
BSDATA_DIR = BASE_DIR / "wh40k-11e"
BSDATA_GAMESYSTEM = BSDATA_DIR / "Warhammer 40,000.json"

# Codex PDF (référence VF)
CODEX_DIR = BASE_DIR / "Rules and codex"

# Données de mission (produites par le scraper GDM)
MISSIONS_JSON = BASE_DIR / "app" / "missions.json"
CARD_IMAGES_DIR = BASE_DIR / "app" / "static" / "card_images"
CARD_IMAGES_URL = "/static/card_images"

# Cache unités BSData normalisées
UNITS_CACHE = BASE_DIR / "app" / "data" / "units_cache.json"

# Base de données SQLite
DATABASE = BASE_DIR / "imperialis.db"

# Partie
MAX_ROUNDS = 5
PHASES = ["Command", "Movement", "Shooting", "Charge", "Fight"]

SECRET_KEY = os.environ.get("IMPERIALIS_SECRET_KEY", "dev-secret-change-me")

# Passphrase d'accès à toute l'app (prod). Vide -> pas d'auth (dev local).
# Sert aussi à gating des PDF de codex (/codex/<file>) pour éviter la redistribution
# publique de matériel copyrighté Games Workshop.
APP_PASSPHRASE = os.environ.get("IMPERIALIS_PASSPHRASE", "")