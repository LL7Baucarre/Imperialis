"""Scraper for GDM (game-datamissions.com / gdmissions.app) 11th-edition data.

Stdlib-only. Fetches server-rendered JSON-LD from the Next.js PWA, downloads
mission card PNGs, and writes a single ``missions.json`` summary file plus the
ground-truth Force Disposition Matrix.

The card *text* lives only inside the PNG images (we do not OCR); the metadata
(deck names, card names, image URLs, matrix cells) is parsed from
``<script type="application/ld+json">`` blocks and the server-rendered matrix
HTML.
"""
from __future__ import annotations

import argparse
import gzip
import html
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE_URL = "https://gdmissions.app"
USER_AGENT = "Imperialis/0.1 (local game assistant)"
POLITE_DELAY = 0.4  # seconds between requests

# Canonical 5 primary-mission decks (display name -> slug). The site lists them
# in a different order, but we present them in this fixed canonical order so
# the matrix rows/columns line up deterministically.
DECK_ORDER = [
    ("Take and Hold", "take-and-hold"),
    ("Purge the Foe", "purge-the-foe"),
    ("Disruption", "disruption"),
    ("Reconnaissance", "reconnaissance"),
    ("Priority Assets", "priority-assets"),
]

# Ground-truth Force Disposition Matrix (rows = "your" deck, columns =
# "opponent" deck). Used as a fallback when the live site is unreachable, and
# to validate whatever we parse from the site.
MATRIX_DECKS = ["Take and Hold", "Purge the Foe", "Disruption",
                "Reconnaissance", "Priority Assets"]
MATRIX_GROUND_TRUTH = {
    "Take and Hold": {
        "Take and Hold": "Battlefield Dominance",
        "Purge the Foe": "Immovable Object",
        "Disruption": "Determined Acquisition",
        "Reconnaissance": "Purge and Secure",
        "Priority Assets": "Inescapable Dominion",
    },
    "Purge the Foe": {
        "Take and Hold": "Unstoppable Force",
        "Purge the Foe": "Meatgrinder",
        "Disruption": "Punishment",
        "Reconnaissance": "Consecrate",
        "Priority Assets": "Destroyer's Wrath",
    },
    "Disruption": {
        "Take and Hold": "Death Trap",
        "Purge the Foe": "Delaying Action",
        "Disruption": "Outmanoeuvre",
        "Reconnaissance": "Smoke and Mirrors",
        "Priority Assets": "Locate and Deny",
    },
    "Reconnaissance": {
        "Take and Hold": "Reconnaissance Sweep",
        "Purge the Foe": "Triangulation",
        "Disruption": "Surveil the Foe",
        "Reconnaissance": "Gather Intel",
        "Priority Assets": "Search and Scour",
    },
    "Priority Assets": {
        "Take and Hold": "Secure Asset",
        "Purge the Foe": "Vital Link",
        "Disruption": "Extract Relic",
        "Reconnaissance": "Vanguard Operation",
        "Priority Assets": "Sabotage",
    },
}


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------
def _get(url: str, timeout: float = 20.0) -> str | None:
    """Fetch a URL, transparently gunzipping. Returns text or None on failure."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Encoding": "gzip",
            "Accept": "text/html,application/xhtml+xml,*/*",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
    except urllib.error.HTTPError as e:
        # 404 / 5xx — caller decides what to do
        return None
    except (urllib.error.URLError, TimeoutError, OSError):
        return None
    if data[:2] == b"\x1f\x8b":  # gzip magic
        try:
            data = gzip.decompress(data)
        except OSError:
            pass
    return data.decode("utf-8", "replace")


def _polite() -> None:
    time.sleep(POLITE_DELAY)


# ---------------------------------------------------------------------------
# JSON-LD extraction
# ---------------------------------------------------------------------------
_JSONLD_RE = re.compile(
    r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.S
)


def _extract_jsonld(page_html: str) -> list[dict]:
    """Return all JSON-LD objects on the page as a flat list of dicts."""
    out: list[dict] = []
    for m in _JSONLD_RE.finditer(page_html):
        raw = m.group(1).strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, list):
            for item in obj:
                if isinstance(item, dict):
                    out.append(item)
        elif isinstance(obj, dict):
            out.append(obj)
    return out


def _find_type(blocks: list[dict], type_name: str) -> dict | None:
    for b in blocks:
        if b.get("@type") == type_name:
            return b
    return None


def _find_collection_page(blocks: list[dict]) -> dict | None:
    """CollectionPage whose mainEntity is an ItemList."""
    for b in blocks:
        if b.get("@type") == "CollectionPage":
            me = b.get("mainEntity")
            if isinstance(me, dict) and me.get("@type") == "ItemList":
                return b
    return None


# ---------------------------------------------------------------------------
# Image download
# ---------------------------------------------------------------------------
def _download_image(url: str, dest: Path, force: bool) -> bool:
    """Download ``url`` to ``dest``. Skip if exists and not force. Returns True
    if a file exists at dest after the call."""
    if dest.exists() and not force:
        return True
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Encoding": "gzip",
            "Accept": "image/*,*/*",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
        if data[:2] == b"\x1f\x8b":
            try:
                data = gzip.decompress(data)
            except OSError:
                pass
        if not data:
            return False
        dest.write_bytes(data)
        return True
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


# ---------------------------------------------------------------------------
# Section scrapers
# ---------------------------------------------------------------------------
def _slugify(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


def _collect_index_decks(section: str) -> list[dict]:
    """Fetch /11th/<section> and return list of {name, slug, url} from its
    CollectionPage ItemList."""
    page = _get(f"{BASE_URL}/11th/{section}")
    if not page:
        return []
    blocks = _extract_jsonld(page)
    cp = _find_collection_page(blocks)
    if not cp:
        return []
    items = cp["mainEntity"].get("itemListElement", [])
    out = []
    for it in items:
        name = it.get("name")
        url = it.get("url")
        if not name or not url:
            continue
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        out.append({"name": name, "slug": slug, "url": url})
    return out


def _collect_deck_cards(deck_url: str) -> tuple[list[dict], str]:
    """Fetch a deck page. Returns (cards, tagline).

    cards: list of {name, slug, url, number}. tagline: deck description string.
    """
    page = _get(deck_url)
    if not page:
        return [], ""
    blocks = _extract_jsonld(page)
    cp = _find_collection_page(blocks)
    if not cp:
        return [], ""
    tagline = cp.get("description", "") or ""
    items = cp["mainEntity"].get("itemListElement", [])
    cards = []
    for it in items:
        name = it.get("name")
        url = it.get("url")
        if not name or not url:
            continue
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        cards.append({
            "name": name,
            "slug": slug,
            "url": url,
            "number": it.get("position"),
        })
    return cards, tagline


def _card_image_url(card_url: str) -> str | None:
    """Fetch a card page and extract the CreativeWork image URL."""
    page = _get(card_url)
    if not page:
        return None
    blocks = _extract_jsonld(page)
    cw = _find_type(blocks, "CreativeWork")
    if not cw:
        return None
    return cw.get("image")


# ---------------------------------------------------------------------------
# RSC flight extraction (card rules text)
# ---------------------------------------------------------------------------
def _extract_rsc_chunks(html: str) -> list[str]:
    """Extract raw RSC flight chunks from ``self.__next_f.push([1,"..."])``.

    Uses a manual scan that respects backslash-escaping inside the JS string
    literal (a regex cannot reliably do this across the whole page).
    """
    chunks: list[str] = []
    marker = 'self.__next_f.push([1,"'
    i = 0
    while True:
        j = html.find(marker, i)
        if j < 0:
            break
        start = j + len(marker)
        k = start
        buf: list[str] = []
        while k < len(html):
            ch = html[k]
            if ch == "\\" and k + 1 < len(html):
                buf.append(html[k:k + 2])
                k += 2
                continue
            if ch == '"':
                break
            buf.append(ch)
            k += 1
        chunks.append("".join(buf))
        i = k + 1
    return chunks


def _decode_js_string(raw: str) -> str:
    """Decode a JS-escaped string (resolve \\uXXXX, \\n, \\", \\\\, …)."""
    s = raw
    s = s.replace('\\"', '"').replace("\\'", "'")
    s = s.replace("\\\\", "\\")
    s = s.replace("\\n", "\n").replace("\\t", "\t").replace("\\r", "\r")
    s = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), s)
    return s


def _extract_rsc_flight(html: str) -> str:
    """Return the concatenated, decoded RSC flight stream for a page."""
    return "".join(_decode_js_string(c) for c in _extract_rsc_chunks(html))


def _brace_match(s: str, start: int) -> str | None:
    """Brace-match a JSON object starting at ``s[start] == '{'``, respecting
    string literals and backslash escapes. Returns the object substring or
    None if unbalanced."""
    depth = 0
    i = start
    in_str = False
    while i < len(s):
        ch = s[i]
        if in_str:
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            i += 1
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return s[start:i + 1]
        i += 1
    return None


def _normalize_undefined(obj_str: str) -> str:
    """Replace ``$undefined`` tokens (bare or quoted) with JSON ``null`` so
    the object parses with stdlib json."""
    s = obj_str.replace('"$undefined"', "null")
    s = re.sub(r'(:\s*)\$undefined', r"\1null", s)
    s = re.sub(r'(\[\s*)\$undefined', r"\1null", s)
    s = re.sub(r'(,\s*)\$undefined', r"\1null", s)
    return s


def _extract_card_text(flight: str, key: str) -> dict | None:
    """Extract the ``key`` (``"primary"`` or ``"secondary"``) props object from
    the RSC flight stream and parse it as JSON. Returns None if not found or
    unparseable."""
    idx = flight.find('"%s":' % key)
    if idx < 0:
        return None
    brace_start = flight.find("{", idx)
    if brace_start < 0:
        return None
    obj_str = _brace_match(flight, brace_start)
    if not obj_str:
        return None
    try:
        return json.loads(_normalize_undefined(obj_str))
    except json.JSONDecodeError:
        return None


def _fetch_card_page(card_url: str) -> tuple[str | None, dict | None]:
    """Fetch a card page and return (image_url_from_jsonld, rsc_text_or_None).

    Combines the existing JSON-LD image lookup with the RSC rules-text
    extraction in a single page fetch.
    """
    page = _get(card_url)
    if not page:
        return None, None
    # image (JSON-LD)
    img = None
    blocks = _extract_jsonld(page)
    cw = _find_type(blocks, "CreativeWork")
    if cw:
        img = cw.get("image")
    # text (RSC flight) — primary first, then secondary
    flight = _extract_rsc_flight(page)
    text = _extract_card_text(flight, "primary") or _extract_card_text(flight, "secondary")
    return img, text


def _scrape_primary(images_dir: Path, force: bool) -> list[dict]:
    """Scrape primary-missions decks + cards + images."""
    decks_meta = _collect_index_decks("primary-missions")
    if not decks_meta:
        return []
    # Reorder into canonical DECK_ORDER when possible.
    by_slug = {d["slug"]: d for d in decks_meta}
    ordered = []
    for name, slug in DECK_ORDER:
        if slug in by_slug:
            ordered.append(by_slug[slug])
    # include any extras the site lists that we don't know about
    for d in decks_meta:
        if d not in ordered:
            ordered.append(d)

    result = []
    for d in ordered:
        _polite()
        cards, tagline = _collect_deck_cards(d["url"])
        deck_out = {
            "name": d["name"],
            "slug": d["slug"],
            "tagline": tagline,
            "cards": [],
        }
        for c in cards:
            _polite()
            img_url, text = _fetch_card_page(c["url"])
            rel = None
            if img_url:
                # https://gdmissions.app/assets/11th/primary-missions/<deck>/<slug>.png
                # -> primary-missions/<deck>/<slug>.png
                rel = _asset_rel_path(img_url, "primary-missions")
                if rel:
                    dest = images_dir / rel
                    _polite()
                    _download_image(img_url, dest, force)
            deck_out["cards"].append({
                "name": c["name"],
                "slug": c["slug"],
                "number": c["number"],
                "image": rel,
                "text": _clean_card_text(text),
            })
        result.append(deck_out)
    return result


def _scrape_secondary(images_dir: Path, force: bool) -> list[dict]:
    """Scrape secondary-missions cards (try defender and attacker variants)."""
    decks_meta = _collect_index_decks("secondary-missions")
    if not decks_meta:
        return []

    result = []
    seen_slugs = set()
    for d in decks_meta:
        base_url = d["url"]
        # base_url ends with <base-slug>-defender per the index. Derive base.
        base = base_url.rsplit("/", 1)[0]
        name = d["name"]
        for role, suffix in (("defender", "-defender"), ("attacker", "-attacker")):
            slug = _slugify(name) + suffix
            if slug in seen_slugs:
                continue
            card_url = f"{BASE_URL}/11th/secondary-missions/{slug}"
            _polite()
            img_url, text = _fetch_card_page(card_url)
            if not img_url:
                # 404 / not found — skip gracefully
                continue
            seen_slugs.add(slug)
            rel = _asset_rel_path(img_url, "secondary-missions")
            if rel:
                dest = images_dir / rel
                _polite()
                _download_image(img_url, dest, force)
            result.append({
                "name": name,
                "slug": slug,
                "role": role,
                "image": rel,
                "text": _clean_card_text(text),
            })
    return result


def _scrape_force_disposition(images_dir: Path, force: bool) -> list[dict]:
    decks_meta = _collect_index_decks("force-disposition")
    if not decks_meta:
        return []
    result = []
    for d in decks_meta:
        _polite()
        img_url = _card_image_url(d["url"])
        rel = None
        if img_url:
            rel = _asset_rel_path(img_url, "force-disposition")
            if rel:
                dest = images_dir / rel
                _polite()
                _download_image(img_url, dest, force)
        result.append({"name": d["name"], "slug": d["slug"], "image": rel})
    return result


def _scrape_layouts(images_dir: Path, force: bool) -> list[dict]:
    """Best-effort: per-deck layout page. Grab the first no-measurements image
    and any battlemaster.online URL if present."""
    decks_meta = _collect_index_decks("layouts")
    if not decks_meta:
        return []
    result = []
    for d in decks_meta:
        _polite()
        # The deck page lists sub-pages per opponent deck. Pick the first
        # opponent sub-page (mirror matchup) and read its layout image.
        page = _get(d["url"])
        sub_url = None
        bm_url = None
        if page:
            blocks = _extract_jsonld(page)
            cp = _find_collection_page(blocks)
            if cp:
                items = cp["mainEntity"].get("itemListElement", [])
                if items:
                    sub_url = items[0].get("url")
            # best-effort battlemaster link
            m = re.search(r"https?://[a-zA-Z0-9._/-]*battlemaster\.online[^\s\"'<>]*",
                          page)
            if m:
                bm_url = m.group(0)

        img_rel = None
        if sub_url:
            _polite()
            sub_page = _get(sub_url)
            if sub_page:
                if not bm_url:
                    m = re.search(
                        r"https?://[a-zA-Z0-9._/-]*battlemaster\.online[^\s\"'<>]*",
                        sub_page)
                    if m:
                        bm_url = m.group(0)
                # prefer no-measurements image
                imgs = re.findall(
                    r"/assets/11th/layouts/no-measurements/[^\"]+\.png", sub_page)
                if imgs:
                    abs_img = BASE_URL + imgs[0]
                    rel = _asset_rel_path(abs_img, "layouts")
                    if rel:
                        dest = images_dir / rel
                        _polite()
                        if _download_image(abs_img, dest, force):
                            img_rel = rel

        result.append({
            "deck": d["name"],
            "slug": d["slug"],
            "image": img_rel,
            "battlemaster_url": bm_url,
        })
    return result


def _asset_rel_path(asset_url: str, section: str) -> str | None:
    """Convert an /assets/11th/<section>/<...>.png URL to a relative path
    ``<section>/<...>.png`` (used both as filesystem path under images_dir
    and as the JSON ``image`` value)."""
    m = re.search(r"/assets/11th/(.+\.png)$", asset_url)
    if not m:
        return None
    return m.group(1)


# ---------------------------------------------------------------------------
# Card text normalization
# ---------------------------------------------------------------------------
def _text_to_html(s: str) -> str:
    """Normalize a card-text fragment to safe HTML with only ``<b>`` tags.

    Primary cards use markdown ``**x**``; secondary cards use inline ``<b>x</b>``.
    GDM wraps highlighted terms in spans (``cB__mark`` for plain highlights,
    ``cB__wmWord`` for written-out numbers whose real value lives in
    ``data-n`` — e.g. ``<span class="cB__wmWord" data-n="3">three</span>``
    should render as ``3``). We strip those spans, substituting the ``data-n``
    value for word-number spans, drop every other tag except ``<b>``, escape
    the remaining text, then re-introduce ``<b>`` from both ``**x**`` and
    explicit ``<b>`` forms so the stored text is consistent and safe to render
    with ``|safe``.

    The input may already be HTML-escaped (older scrapes stored
    ``&lt;span&gt;``), so we unescape first and operate on real tags.
    """
    if not s:
        return ""
    s = html.unescape(str(s))
    # Word-number spans: replace the whole span with the numeric data-n value.
    s = re.sub(
        r'<span[^>]*class="cB__wmWord"[^>]*data-n="(\d+)"[^>]*>.*?</span>',
        r"\1", s, flags=re.S)
    s = re.sub(
        r'<span[^>]*data-n="(\d+)"[^>]*class="cB__wmWord"[^>]*>.*?</span>',
        r"\1", s, flags=re.S)
    # Drop all remaining spans, keeping their inner text (cB__mark, etc.).
    s = re.sub(r"<span[^>]*>(.*?)</span>", r"\1", s, flags=re.S)
    # Remove every other tag except <b>/</b>.
    s = re.sub(r"</?(?!b\b)[^>]*>", "", s, flags=re.S)
    out = html.escape(s, quote=False)  # & < > -> entities
    # markdown bold **x**  -> <b>x</b>
    out = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", out)
    # escaped <b>/<\/b> (from explicit tags we kept then escaped) -> real tags
    out = out.replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>")
    return out


def _clean_row(row: dict) -> dict:
    """Normalize one scoring row/tier."""
    if not isinstance(row, dict):
        return {}
    out = {"text": _text_to_html(row.get("text"))}
    if "vp" in row and row["vp"] is not None:
        out["vp"] = row["vp"]
    for flag in ("perUnit", "cumulative", "plus", "or", "kind", "perEvent"):
        if row.get(flag) not in (None, False):
            out[flag] = row[flag]
    return out


def _clean_card_text(text: dict | None) -> dict | None:
    """Normalize a parsed primary/secondary card-text object for storage.

    Returns None if no text. Output shape::

        {"name": str, "kindLabel"?: str,
         "sections": [{"when": str, "trigger"?: str, "chip"?: str,
                        "rows": [{text, vp, ...flags}]}]}
    """
    if not isinstance(text, dict):
        return None
    sections_out = []
    for sec in text.get("sections", []) or []:
        if not isinstance(sec, dict):
            continue
        rows = sec.get("tiers") or sec.get("rows") or []
        s_out = {"when": _text_to_html(sec.get("when"))}
        if sec.get("trigger"):
            s_out["trigger"] = _text_to_html(sec.get("trigger"))
        if sec.get("chip"):
            s_out["chip"] = sec.get("chip")
        s_out["rows"] = [_clean_row(r) for r in rows if isinstance(r, dict)]
        sections_out.append(s_out)
    if not sections_out:
        return None
    out = {"name": text.get("name") or "", "sections": sections_out}
    if text.get("kindLabel"):
        out["kindLabel"] = text.get("kindLabel")
    if text.get("rule") and text.get("rule") != "$undefined":
        out["rule"] = _text_to_html(text.get("rule"))
    return out


# ---------------------------------------------------------------------------
# Matrix parsing
# ---------------------------------------------------------------------------
def _parse_matrix(page_html: str) -> dict | None:
    """Parse the server-rendered Force Disposition Matrix from /11th/matrix.

    Structure (verified):
      5 column headers  : <span class="fdm-nm">Deck</span><span class="fdm-sub">Opponent</span>
      Then per row       : <span class="fdm-nm">Deck</span><span class="fdm-sub">You</span>
                          followed by 5 <span class="fdm-mn">Card Name</span>
    """
    tokens = re.findall(
        r'<span class="(fdm-nm|fdm-sub|fdm-mn)">([^<]+)</span>', page_html
    )
    if not tokens:
        return None

    # First, consume the column header run: consecutive fdm-nm/fdm-sub pairs
    # with fdm-sub == "Opponent".
    col_decks: list[str] = []
    i = 0
    while i + 1 < len(tokens):
        if tokens[i][0] == "fdm-nm" and tokens[i + 1][0] == "fdm-sub":
            if tokens[i + 1][1] == "Opponent":
                col_decks.append(html.unescape(tokens[i][1]))
                i += 2
                continue
            else:
                break  # reached the first "You" row
        else:
            break
    if len(col_decks) != 5:
        return None

    cells: dict[str, dict[str, str]] = {}
    while i < len(tokens):
        # expect a row header: fdm-nm + fdm-sub=="You"
        if tokens[i][0] != "fdm-nm" or i + 1 >= len(tokens):
            break
        row_deck = html.unescape(tokens[i][1])
        if tokens[i + 1][0] != "fdm-sub" or tokens[i + 1][1] != "You":
            break
        i += 2
        row_cells = {}
        for col in col_decks:
            if i >= len(tokens) or tokens[i][0] != "fdm-mn":
                break
            row_cells[col] = html.unescape(tokens[i][1])
            i += 1
        if len(row_cells) != len(col_decks):
            return None
        cells[row_deck] = row_cells

    if len(cells) != 5:
        return None
    return {"decks": col_decks, "cells": cells}


def _validate_matrix(parsed: dict) -> bool:
    """Compare parsed matrix to ground truth. Returns True if every cell
    matches (apostrophe forms normalised)."""
    if not parsed:
        return False
    cells = parsed.get("cells", {})
    for your_deck, row in MATRIX_GROUND_TRUTH.items():
        if your_deck not in cells:
            return False
        for opp_deck, expected in row.items():
            got = cells[your_deck].get(opp_deck)
            if got is None:
                return False
            if _norm_name(got) != _norm_name(expected):
                return False
    return True


def _norm_name(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def _scrape_matrix() -> dict:
    page = _get(f"{BASE_URL}/11th/matrix")
    if page:
        parsed = _parse_matrix(page)
        if parsed and _validate_matrix(parsed):
            return parsed
    # fallback to ground truth
    return {"decks": list(MATRIX_DECKS),
            "cells": {k: dict(v) for k, v in MATRIX_GROUND_TRUTH.items()}}


# ---------------------------------------------------------------------------
# Fallback (total network failure)
# ---------------------------------------------------------------------------
def _fallback_payload() -> dict:
    primary_decks = []
    for name, slug in DECK_ORDER:
        primary_decks.append({
            "name": name, "slug": slug, "tagline": "", "cards": [],
        })
    return {
        "primary_decks": primary_decks,
        "secondary": [],
        "force_disposition": [],
        "layouts": [],
        "matrix": {"decks": list(MATRIX_DECKS),
                   "cells": {k: dict(v) for k, v in MATRIX_GROUND_TRUTH.items()}},
        "_fallback": True,
    }


# ---------------------------------------------------------------------------
# Re-clean stored card text (one-shot migration for older missions.json)
# ---------------------------------------------------------------------------
def _reclean_text_obj(text: dict) -> dict | None:
    """Re-apply :func:`_text_to_html` to an already-cleaned card-text object.

    Older scrapes stored GDM spans (``cB__mark`` / ``cB__wmWord``) as escaped
    HTML inside the text fields. This walks the stored shape and re-normalizes
    every text fragment in place.
    """
    if not isinstance(text, dict):
        return text
    if text.get("rule"):
        text["rule"] = _text_to_html(text["rule"])
    for sec in text.get("sections", []) or []:
        if not isinstance(sec, dict):
            continue
        if sec.get("when"):
            sec["when"] = _text_to_html(sec["when"])
        if sec.get("trigger"):
            sec["trigger"] = _text_to_html(sec["trigger"])
        for r in sec.get("rows", []) or []:
            if isinstance(r, dict) and r.get("text"):
                r["text"] = _text_to_html(r["text"])
    return text


def reclean(path: str = "app/missions.json") -> int:
    """Re-normalize all stored card-text fragments in ``missions.json``.

    Returns the number of card-text objects touched. Idempotent: running it on
    already-clean data is a no-op (re-escaping stable text yields the same
    output).
    """
    p = Path(path)
    if not p.exists():
        return 0
    data = json.loads(p.read_text(encoding="utf-8"))
    touched = 0
    for deck in data.get("primary_decks", []) or []:
        for c in deck.get("cards", []) or []:
            if c.get("text") is not None:
                c["text"] = _reclean_text_obj(c["text"])
                touched += 1
    for c in data.get("secondary", []) or []:
        if c.get("text") is not None:
            c["text"] = _reclean_text_obj(c["text"])
            touched += 1
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return touched


# ---------------------------------------------------------------------------
# Top-level scrape()
# ---------------------------------------------------------------------------
def scrape(output_dir: str = "app",
            images_dir: str = "app/static/card_images",
            force: bool = False) -> dict:
    """Scrape GDM 11th-edition data and write ``<output_dir>/missions.json``
    plus downloaded PNGs under ``images_dir``.

    Returns the dict that was written.
    """
    out_dir = Path(output_dir)
    img_dir = Path(images_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    img_dir.mkdir(parents=True, exist_ok=True)

    payload: dict = {}
    errors: list[str] = []

    # --- Primary missions ---
    try:
        primary = _scrape_primary(img_dir, force)
        payload["primary_decks"] = primary
    except Exception as e:  # noqa: BLE001 — resilience
        errors.append(f"primary: {e!r}")
        payload["primary_decks"] = []

    # --- Secondary missions ---
    try:
        secondary = _scrape_secondary(img_dir, force)
        payload["secondary"] = secondary
    except Exception as e:  # noqa: BLE001
        errors.append(f"secondary: {e!r}")
        payload["secondary"] = []

    # --- Force disposition ---
    try:
        fd = _scrape_force_disposition(img_dir, force)
        payload["force_disposition"] = fd
    except Exception as e:  # noqa: BLE001
        errors.append(f"force_disposition: {e!r}")
        payload["force_disposition"] = []

    # --- Layouts ---
    try:
        layouts = _scrape_layouts(img_dir, force)
        payload["layouts"] = layouts
    except Exception as e:  # noqa: BLE001
        errors.append(f"layouts: {e!r}")
        payload["layouts"] = []

    # --- Matrix ---
    try:
        payload["matrix"] = _scrape_matrix()
    except Exception as e:  # noqa: BLE001
        errors.append(f"matrix: {e!r}")
        payload["matrix"] = {"decks": list(MATRIX_DECKS),
                             "cells": {k: dict(v)
                                       for k, v in MATRIX_GROUND_TRUTH.items()}}

    # If everything failed (no network at all), use the full fallback so the
    # app still has deck names + matrix.
    everything_empty = (
        not payload.get("primary_decks")
        and not payload.get("secondary")
        and not payload.get("force_disposition")
        and not payload.get("layouts")
    )
    if everything_empty:
        fb = _fallback_payload()
        # keep whatever matrix we did build (fallback already includes it)
        fb["matrix"] = payload.get("matrix", fb["matrix"])
        payload = fb

    payload["_errors"] = errors

    out_path = out_dir / "missions.json"
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    return payload


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _main() -> int:
    p = argparse.ArgumentParser(
        description="Scrape GDM 11th-edition mission data (stdlib only).")
    sub = p.add_subparsers(dest="cmd")
    p_scrape = sub.add_parser("scrape", help="Re-scrape from the live site.")
    p_scrape.add_argument("--output-dir", default="app",
                          help="Directory to write missions.json (default: app)")
    p_scrape.add_argument("--images-dir", default="app/static/card_images",
                          help="Directory for downloaded card PNGs")
    p_scrape.add_argument("--force", action="store_true",
                          help="Re-download images even if they already exist")
    p_reclean = sub.add_parser("reclean",
                               help="Re-normalize stored card text in place.")
    p_reclean.add_argument("--path", default="app/missions.json",
                           help="Path to missions.json")
    # Backward-compat: bare args (no subcommand) still trigger a scrape.
    args, extra = p.parse_known_args()
    if args.cmd == "reclean":
        n = reclean(args.path)
        print(f"Re-cleaned {n} card-text object(s) in {args.path}")
        return 0

    # Default: scrape (honour legacy flags passed without a subcommand).
    if args.cmd == "scrape":
        out_dir = args.output_dir
        img_dir = args.images_dir
        force = args.force
    else:
        out_dir = "app"
        img_dir = "app/static/card_images"
        force = "--force" in (extra or [])

    payload = scrape(out_dir, img_dir, force)
    n_pri = len(payload.get("primary_decks", []))
    n_cards = sum(len(d.get("cards", []))
                  for d in payload.get("primary_decks", []))
    n_sec = len(payload.get("secondary", []))
    n_fd = len(payload.get("force_disposition", []))
    n_lay = len(payload.get("layouts", []))
    matrix_ok = _validate_matrix(payload.get("matrix", {}))
    print(f"Wrote {out_dir}/missions.json")
    print(f"  primary decks: {n_pri} ({n_cards} cards)")
    print(f"  secondary cards: {n_sec}")
    print(f"  force disposition: {n_fd}")
    print(f"  layouts: {n_lay}")
    print(f"  matrix valid: {matrix_ok}")
    if payload.get("_errors"):
        print("  errors:", payload["_errors"])
    if payload.get("_fallback"):
        print("  NOTE: used fallback payload (live site unreachable)")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())