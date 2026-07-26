"""Bootstrap helper: ensures the BSData (wh40k-11e) data is present, cloning it
from GitHub if the directory is missing. Called once at app start-up so a
fresh checkout works without a manual ``git clone``."""
from __future__ import annotations

import subprocess
import sys

from app import config as cfg

BSDATA_REPO = "https://github.com/BSData/wh40k-11e.git"


def bsdata_present() -> bool:
    """True if the BSData directory looks populated (has JSON catalogues)."""
    if not cfg.BSDATA_DIR.is_dir():
        return False
    try:
        return any(cfg.BSDATA_DIR.glob("*.json"))
    except OSError:
        return False


def ensure_bsdata() -> bool:
    """Clone wh40k-11e if absent. No-op (returns True) if already present.
    Returns False (and prints a warning) if cloning failed."""
    if bsdata_present():
        return True
    parent = cfg.BSDATA_DIR.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
        print(f"[imperialis] BSData manquant — clonage de {BSDATA_REPO}…",
              file=sys.stderr)
        subprocess.run(
            ["git", "clone", "--depth", "1", BSDATA_REPO, str(cfg.BSDATA_DIR)],
            check=True,
        )
    except Exception as exc:
        print(f"[imperialis]Impossible de cloner BSData ({exc}). "
              f"Lance manuellement : git clone {BSDATA_REPO} wh40k-11e",
              file=sys.stderr)
        return False
    return bsdata_present()