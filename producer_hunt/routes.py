"""Producer Hunt Flask blueprint — fullscreen game only."""

from __future__ import annotations

import logging
from pathlib import Path

from flask import Blueprint, current_app, render_template

from security_support import is_production_env

from . import ASSET_VERSION

log = logging.getLogger("producer_hunt")

_ASSET_ROOT = Path(__file__).resolve().parent / "static" / "producer_hunt" / "assets"
_missing_assets_logged = False

producer_hunt_bp = Blueprint(
    "producer_hunt",
    __name__,
    template_folder="templates",
    static_folder="static/producer_hunt",
    static_url_path="/producer-hunt/static",
)


def _warn_if_assets_missing() -> None:
    global _missing_assets_logged
    if _missing_assets_logged:
        return
    required = _ASSET_ROOT / "environment" / "studio" / "backgrounds" / "studio_background_far.png"
    if required.is_file():
        return
    _missing_assets_logged = True
    log.error("Required static asset failed to load: %s", required.name)


@producer_hunt_bp.get("/producer-hunt")
def page():
    try:
        _warn_if_assets_missing()
        return render_template(
            "producer_hunt/game.html",
            producer_hunt_asset_version=ASSET_VERSION,
            producer_hunt_allow_debug=not is_production_env(),
        )
    except Exception:
        current_app.logger.exception("Producer Hunt failed to initialize")
        raise
