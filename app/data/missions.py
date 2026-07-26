"""Mission data loader for Imperialis (stdlib only).

Reads ``app/missions.json`` produced by ``app.scraper.gdm_scraper.scrape``
and offers simple accessors used by the Flask app. Results of ``load_missions``
are cached with ``functools.lru_cache``.
"""
from __future__ import annotations

import functools
import json
from pathlib import Path
from typing import Any, Iterable

DEFAULT_PATH = "app/missions.json"


@functools.lru_cache(maxsize=8)
def _load(path: str) -> tuple[dict, float]:
    """Internal cached loader keyed on the path string. Returns (data, mtime)
    so callers can detect a changed file by bumping the key."""
    p = Path(path)
    if not p.exists():
        return {}, 0.0
    return json.loads(p.read_text(encoding="utf-8")), p.stat().st_mtime


def load_missions(path: str = DEFAULT_PATH) -> dict:
    """Load and return the missions data dict. Returns ``{}`` if the file is
    missing or unreadable. Cached by path."""
    try:
        data, _ = _load(path)
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _reload(path: str = DEFAULT_PATH) -> dict:
    """Force a fresh read (bypass cache). Handy during scraping."""
    _load.cache_clear()
    return load_missions(path)


# ---------------------------------------------------------------------------
# Accessors
# ---------------------------------------------------------------------------
def primary_decks(path: str = DEFAULT_PATH) -> list[dict]:
    """List of primary mission decks: [{name, slug, tagline, cards:[...]}]."""
    return list(load_missions(path).get("primary_decks", []))


def primary_deck(name_or_slug: str, path: str = DEFAULT_PATH) -> dict | None:
    """Return a single primary deck by name or slug (case-insensitive)."""
    key = (name_or_slug or "").lower()
    for d in primary_decks(path):
        if d.get("name", "").lower() == key or d.get("slug", "").lower() == key:
            return d
    return None


def primary_card_text(deck_name: str, card_name: str,
                      path: str = DEFAULT_PATH) -> dict | None:
    """Return the structured rules text for a primary card (by deck + card
    name). None if not found or no text scraped."""
    deck = primary_deck(deck_name, path)
    if not deck:
        return None
    key = (card_name or "").lower()
    for c in deck.get("cards", []):
        if (c.get("name") or "").lower() == key:
            return c.get("text")
    return None


def secondary_card_text(name: str, role: str | None = None,
                        path: str = DEFAULT_PATH) -> dict | None:
    """Return the structured rules text for a secondary card (by name, and
    optionally role 'attacker'/'defender'). None if not found."""
    key = (name or "").lower()
    for c in secondary_cards(None, path):
        if (c.get("name") or "").lower() != key:
            continue
        if role and (c.get("role") or "").lower() != role.lower():
            continue
        return c.get("text")
    # fallback: first match by name regardless of role
    for c in secondary_cards(None, path):
        if (c.get("name") or "").lower() == key:
            return c.get("text")
    return None


def secondary_cards(role: str | None = None,
                    path: str = DEFAULT_PATH) -> list[dict]:
    """List secondary mission cards. If ``role`` is given ('attacker' or
    'defender'), filter to that role."""
    cards = load_missions(path).get("secondary", [])
    if role is None:
        return list(cards)
    role = role.lower()
    return [c for c in cards if c.get("role", "").lower() == role]


def force_dispositions(path: str = DEFAULT_PATH) -> list[dict]:
    return list(load_missions(path).get("force_disposition", []))


def force_disposition_image_url(deck_name: str | None,
                                 path: str = DEFAULT_PATH) -> str | None:
    """Image URL de la carte de force disposition pour un deck (par name ou
    slug). None si introuvable."""
    if not deck_name:
        return None
    key = deck_name.lower()
    for fd in force_dispositions(path):
        if (fd.get("name") or "").lower() == key \
                or (fd.get("slug") or "").lower() == key:
            return image_rel_to_url(fd.get("image"))
    return None


def layouts(path: str = DEFAULT_PATH) -> list[dict]:
    return list(load_missions(path).get("layouts", []))


def layout_for_deck(deck_name: str | None,
                    path: str = DEFAULT_PATH) -> tuple[str | None, str | None]:
    """Retourne (image_url, battlemaster_url) du layout de terrain pour un deck.
    (None, None) si introuvable. Les données actuelles ne couvrent qu'un
    matchup par deck ; on prend la première image disponible pour ce deck."""
    if not deck_name:
        return None, None
    key = deck_name.lower()
    for l in layouts(path):
        if (l.get("deck") or "").lower() == key \
                or (l.get("slug") or "").lower() == key:
            return image_rel_to_url(l.get("image")), l.get("battlemaster_url")
    return None, None


def matrix(path: str = DEFAULT_PATH) -> dict:
    """Return the Force Disposition Matrix as
    ``{"decks": [...], "cells": {your: {opp: card_name}}}``."""
    m = load_missions(path).get("matrix", {})
    return m if isinstance(m, dict) else {}


def resolve_primary_card(your_deck: str, opp_deck: str,
                         path: str = DEFAULT_PATH) -> str | None:
    """Resolve the primary mission card name for a (your_deck, opp_deck)
    matchup using the matrix cells. Returns None if unknown."""
    cells = matrix(path).get("cells", {})
    row = cells.get(your_deck)
    if not row:
        return None
    return row.get(opp_deck)


# ---------------------------------------------------------------------------
# Image URL helpers
# ---------------------------------------------------------------------------
CARD_IMAGES_URL_PREFIX = "/static/card_images"


def card_image_url(section: str, deck: str, slug: str) -> str:
    """Return the Flask URL path for a card image.

    ``section`` is e.g. 'primary-missions', 'secondary-missions',
    'force-disposition', 'layouts'. ``deck`` and ``slug`` identify the file.
    """
    return f"{CARD_IMAGES_URL_PREFIX}/{section}/{deck}/{slug}.png"


def image_rel_to_url(rel: str | None) -> str | None:
    """Convert a relative image path stored in missions.json (e.g.
    'primary-missions/take-and-hold/battlefield-dominance.png') into the Flask
    URL path. Returns None if rel is None."""
    if not rel:
        return None
    return f"{CARD_IMAGES_URL_PREFIX}/{rel.lstrip('/')}"


def primary_card_image_url(deck_slug: str, card_slug: str,
                           path: str = DEFAULT_PATH) -> str | None:
    """Convenience: image URL for a primary card by deck/card slug."""
    deck = primary_deck(deck_slug, path)
    if not deck:
        return None
    for c in deck.get("cards", []):
        if c.get("slug") == card_slug:
            return image_rel_to_url(c.get("image"))
    return None


__all__ = [
    "load_missions",
    "_reload",
    "primary_decks",
    "primary_deck",
    "primary_card_text",
    "secondary_cards",
    "secondary_card_text",
    "force_dispositions",
    "force_disposition_image_url",
    "layouts",
    "layout_for_deck",
    "matrix",
    "resolve_primary_card",
    "card_image_url",
    "image_rel_to_url",
    "primary_card_image_url",
]