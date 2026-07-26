"""Factory de l'application Flask Imperialis."""
from flask import Flask
from app import config as cfg
from app.db import close_db, init_db
from app.bootstrap import ensure_bsdata


def create_app():
    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.config["SECRET_KEY"] = cfg.SECRET_KEY
    app.config["DATABASE"] = str(cfg.DATABASE)
    app.config["MAX_ROUNDS"] = cfg.MAX_ROUNDS

    # S'assure que les données BSData (wh40k-11e) sont présentes — un fresh
    # checkout auto-clone le dépôt. Non-fatal : l'app démarre quand même et
    # l'utilisateur pourra cloner manuellement.
    try:
        ensure_bsdata()
    except Exception as exc:  # pragma: no cover - best effort
        print(f"[imperialis] ensure_bsdata a échoué ({exc}).", flush=True)

    # Init DB si absent
    init_db(app.config["DATABASE"])

    app.teardown_appcontext(close_db)

    # Filtres Jinja pour le markup BSData
    from app.helpers import clean_bsdata, plain_bsdata, playable_factions, unit_category_display
    app.jinja_env.filters["bsd"] = clean_bsdata
    app.jinja_env.filters["plain"] = plain_bsdata
    app.jinja_env.globals["unit_category_display"] = unit_category_display

    # Context processor global (données communes aux templates)
    from app.auth import auth_enabled, is_authed
    @app.context_processor
    def inject_globals():
        return {
            "PHASES": cfg.PHASES,
            "MAX_ROUNDS": cfg.MAX_ROUNDS,
            "playable_factions": playable_factions,
            "auth_enabled": auth_enabled(),
            "authed": is_authed(),
        }

    # Authentification par passphrase (gating toute l'app + codex PDF)
    from app.auth import bp as auth_bp, enforce_auth
    app.register_blueprint(auth_bp)
    app.before_request(enforce_auth)

    # Enregistrement des blueprints (chargement différé, tolérant)
    from app.routes import setup as setup_bp
    from app.routes import game as game_bp
    from app.routes import api as api_bp
    app.register_blueprint(setup_bp.bp)
    app.register_blueprint(game_bp.bp)
    app.register_blueprint(api_bp.bp, url_prefix="/api")

    return app