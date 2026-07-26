"""Authentification par passphrase partagée pour toute l'app.

En production, ``IMPERIALIS_PASSPHRASE`` est définie dans l'environnement ; toute
requête non authentifiée est redirigée vers ``/login`` (ou 401 pour l'API JSON).
Cela protège aussi la route ``/codex/<file>`` qui sert les PDF VF (copyright
Games Workshop) : aucun accès public, donc pas de redistribution.
"""
import secrets

from flask import (
    Blueprint, abort, redirect, render_template, request, session, url_for,
)

from app import config as cfg

bp = Blueprint("auth", __name__)


def auth_enabled() -> bool:
    return bool(cfg.APP_PASSPHRASE)


def is_authed() -> bool:
    return session.get("authed") is True


def enforce_auth():
    """Hook ``before_request`` : bloque l'accès si la passphrase est définie et
    l'utilisateur n'est pas authentifié. Laisse passer /login, /logout et les
    fichiers statiques (CSS de la page de login)."""
    if not auth_enabled():
        return None
    endpoint = request.endpoint
    if endpoint in ("auth.login", "auth.logout") or endpoint == "static":
        return None
    if is_authed():
        return None
    if request.path.startswith("/api/"):
        abort(401)
    return redirect(url_for("auth.login", next=request.path))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if not auth_enabled():
        return redirect(url_for("setup.home"))
    err = None
    if request.method == "POST":
        given = request.form.get("passphrase", "")
        if secrets.compare_digest(given, cfg.APP_PASSPHRASE):
            session["authed"] = True
            nxt = request.args.get("next") or url_for("setup.home")
            return redirect(nxt)
        err = "Passphrase incorrecte."
    return render_template("login.html", err=err)


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))