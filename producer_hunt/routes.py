"""Producer Hunt Flask blueprint — fullscreen game only."""

from __future__ import annotations

from flask import Blueprint, render_template

producer_hunt_bp = Blueprint(
    "producer_hunt",
    __name__,
    template_folder="templates",
    static_folder="static/producer_hunt",
    static_url_path="/producer-hunt/static",
)


@producer_hunt_bp.get("/producer-hunt")
def page():
    return render_template("producer_hunt/game.html")
