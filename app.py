"""Users and tasks web application."""

from __future__ import annotations

import mimetypes
import os
import re
import subprocess
import uuid
from urllib.parse import urlparse
from collections import defaultdict
from typing import Sequence
from datetime import date, datetime, timedelta
from flask import (
    Flask,
    Response,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    session,
    url_for,
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import and_, case, exc as sa_exc, exists, func, inspect, or_, select, text
from sqlalchemy.orm import foreign, joinedload, selectinload
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from flask_socketio import SocketIO, join_room, leave_room

from booking import booking_bp
from time_utils import CAIRO_TZ, now_local, today_cairo

db = SQLAlchemy()
SOCKET_AUTH_SALT = "tm-socket"
SOCKET_AUTH_MAX_AGE = 86400  # 24h; page refresh issues a new token

socketio = SocketIO(async_mode="threading")

MIN_PASSWORD_LENGTH = 8

AVATAR_PRESET_COUNT = 8
AVATAR_UPLOAD_MAX_BYTES = 2 * 1024 * 1024
AVATAR_ALLOWED_EXT = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp"})

CHAT_UPLOAD_MAX_BYTES = 5 * 1024 * 1024
CHAT_ALLOWED_EXT = frozenset({".png", ".jpg", ".jpeg", ".webp"})
CHAT_AUDIO_MAX_BYTES = 15 * 1024 * 1024
CHAT_AUDIO_EXT = frozenset({".webm", ".ogg", ".opus", ".mp3", ".m4a", ".wav", ".mp4"})
SCENE_REF_MAX_BYTES = 300 * 1024 * 1024
SCENE_REF_ALLOWED_EXT = frozenset({".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"})
CHAT_REACTION_EMOJIS = frozenset({"👍", "❤️", "😂", "😮"})

def _project_type_is_tv_series(project_type: str | None) -> bool:
    """Episode count applies only to TV series projects."""
    return (project_type or "").strip().casefold() == "tv series"


VFX_EDITOR_STATUSES: tuple[str, ...] = ("pending", "sent", "review", "approved")
VFX_DEPARTMENTS: tuple[str, ...] = ("animation", "fx", "comp")
VFX_VERSION_ALLOWED_EXT = frozenset({".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".webm", ".mov", ".m4v"})
VFX_VERSION_MAX_BYTES = 80 * 1024 * 1024


CHAT_AUDIO_MIME_TO_EXT = {
    "audio/webm": ".webm",
    "video/webm": ".webm",
    "audio/ogg": ".ogg",
    "application/ogg": ".ogg",
    "audio/opus": ".opus",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/m4a": ".m4a",
    "audio/aac": ".m4a",
    "video/mp4": ".mp4",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
}


def _ext_for_chat_audio(part_mime: str | None, filename: str | None, raw: bytes) -> str:
    mime = (part_mime or "").split(";")[0].strip().lower()
    ext = CHAT_AUDIO_MIME_TO_EXT.get(mime)
    if ext and ext in CHAT_AUDIO_EXT:
        return ext
    if filename:
        e = os.path.splitext(secure_filename(filename))[1].lower()
        if e in CHAT_AUDIO_EXT:
            return e
    if raw.startswith(b"\x1a\x45\xdf\xa3"):
        return ".webm"
    if len(raw) >= 12 and raw[4:8] == b"ftyp":
        return ".m4a"
    if raw.startswith(b"ID3") or (
        len(raw) >= 2 and raw[0] == 0xFF and (raw[1] & 0xE0) == 0xE0
    ):
        return ".mp3"
    if len(raw) >= 12 and raw.startswith(b"RIFF") and raw[8:12] == b"WAVE":
        return ".wav"
    if raw.startswith(b"OggS"):
        return ".ogg"
    return ".webm"

ROLE_ADMIN = "admin"
ROLE_SUPER_USER = "super_user"
ROLE_PRODUCER = "producer"
ROLE_MACHINE_ROOM = "machine_room"
ROLE_USER = "user"
ROLE_GUEST = "guest"
ACCOUNT_ROLES = (
    ROLE_ADMIN,
    ROLE_SUPER_USER,
    ROLE_PRODUCER,
    ROLE_MACHINE_ROOM,
    ROLE_USER,
    ROLE_GUEST,
)

ROLE_LABELS = {
    ROLE_ADMIN: "Administrator",
    ROLE_SUPER_USER: "Super user",
    ROLE_PRODUCER: "Producer",
    ROLE_MACHINE_ROOM: "Machine Room",
    ROLE_USER: "User",
    ROLE_GUEST: "Guest",
}

# Machine-room dashboard live rows (progress bar) — copy then optional convert pipeline.
MR_TIMED_STREAM_TITLES = frozenset({"Copy Material", "Convert"})
MR_STREAM_COPY_TITLE = "Copy Material"
MR_STREAM_CONVERT_TITLE = "Convert"

# Directory job titles that grant super-user privileges (same as role "super_user").
SUPER_USER_JOB_TITLE_NAMES = frozenset({"Post-Producer in-house", "Main Editor"})


def _normalized_account_role_key(raw: str | None) -> str:
    """Lowercase role string with spaces/dashes folded to underscores (matches form values)."""
    if not raw:
        return ""
    return re.sub(r"[\s\-]+", "_", raw.strip().lower())

# Directory user used for seeded pipeline tasks so assignee stays non-null.
POOL_USER_EMAIL = "_pipeline@task-manager.local"
POOL_USER_NAME = "Pipeline (unassigned)"

DEFAULT_TASK_GROUP_NAMES = (
    "Editing",
    "DI / Machine",
    "Color Grading",
    "Sound",
    "Vfx",
)

EDITING_GROUP_TASK_TITLES = (
    "Sync",
    "First Edit",
    "Export to Color grading",
    "Export to Vfx",
    "Export to Sound Mix",
    "Mastring",
)


def _display_name_from_email(email: str) -> str:
    local = email.split("@", 1)[0] if email else ""
    label = local.replace(".", " ").replace("_", " ").strip()
    return label.title() if label else "User"


def _safe_next_url(target: str | None) -> str:
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return url_for("index")


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["APP_NAME"] = os.environ.get("APP_NAME", "BIGbang Studios")
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-change-in-production")
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "instance", "app.db")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    upload_root = os.path.join(os.path.dirname(db_path), "uploads", "avatars")
    os.makedirs(upload_root, exist_ok=True)
    app.config["PROFILE_AVATAR_UPLOAD_FOLDER"] = upload_root
    chat_upload_root = os.path.join(os.path.dirname(db_path), "uploads", "chat")
    os.makedirs(chat_upload_root, exist_ok=True)
    scene_ref_upload_root = os.path.join(os.path.dirname(db_path), "uploads", "scene_refs")
    os.makedirs(scene_ref_upload_root, exist_ok=True)
    vfx_version_upload_root = os.path.join(os.path.dirname(db_path), "uploads", "vfx_versions")
    os.makedirs(vfx_version_upload_root, exist_ok=True)
    test_db_uri = (os.environ.get("TASK_MANAGER_TEST_DATABASE") or "").strip()
    if test_db_uri:
        app.config["SQLALCHEMY_DATABASE_URI"] = test_db_uri
        app.config["TESTING"] = True
    else:
        app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)
    socketio.init_app(
        app,
        cors_allowed_origins="*",
        manage_session=False,
        always_connect=True,
    )

    class Account(db.Model):
        """Application login (separate from directory User / assignees)."""

        __tablename__ = "accounts"

        id = db.Column(db.Integer, primary_key=True)
        email = db.Column(db.String(255), nullable=False, unique=True)
        username = db.Column(db.String(64), nullable=True, unique=True)
        password_hash = db.Column(db.String(256), nullable=False)
        role = db.Column(db.String(32), nullable=False, default=ROLE_USER)
        created_at = db.Column(db.DateTime, default=now_local)

        @property
        def is_admin(self) -> bool:
            return _normalized_account_role_key(self.role) == ROLE_ADMIN

        @property
        def display_login(self) -> str:
            return self.username or self.email

        @property
        def display_name(self) -> str:
            u = self.directory_user
            if u is not None and (u.name or "").strip():
                return u.name.strip()
            return self.display_login

    class JobTitle(db.Model):
        """Directory job role (e.g. Colorist) — separate from task group / task title presets."""

        __tablename__ = "job_titles"

        id = db.Column(db.Integer, primary_key=True)
        name = db.Column(db.String(120), nullable=False, unique=True)

    class User(db.Model):
        __tablename__ = "users"

        id = db.Column(db.Integer, primary_key=True)
        name = db.Column(db.String(120), nullable=False)
        email = db.Column(db.String(255), nullable=False, unique=True)
        account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=True, unique=True)
        job_title_id = db.Column(db.Integer, db.ForeignKey("job_titles.id"), nullable=True)
        phone = db.Column(db.String(40), nullable=True)
        avatar_kind = db.Column(db.String(16), nullable=False, default="preset")
        avatar_preset = db.Column(db.String(8), nullable=False, default="01")
        avatar_upload = db.Column(db.String(255), nullable=True)
        created_at = db.Column(db.DateTime, default=now_local)

        account = db.relationship("Account", backref=db.backref("directory_user", uselist=False))
        job_title = db.relationship("JobTitle", backref=db.backref("users", lazy=True))
        tasks = db.relationship("Task", backref="assignee", lazy=True, cascade="all, delete-orphan")

    class EditSuite(db.Model):
        """Post-production edit / color suite (bookable room)."""

        __tablename__ = "edit_suites"

        id = db.Column(db.Integer, primary_key=True)
        name = db.Column(db.String(200), nullable=False)
        is_active = db.Column(db.Boolean, nullable=False, default=True)

    class Booking(db.Model):
        """Time-based reservation of an edit suite, scoped to a project and people."""

        __tablename__ = "bookings"

        id = db.Column(db.Integer, primary_key=True)
        edit_suite_id = db.Column(db.Integer, db.ForeignKey("edit_suites.id"), nullable=False)
        # Legacy SQLite rows: NOT NULL user_id predates booked_by_id; ORM must set on insert.
        user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
        project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False)
        booked_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
        booked_for_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
        booking_date = db.Column(db.Date, nullable=False)
        start_time = db.Column(db.Time, nullable=False)
        end_time = db.Column(db.Time, nullable=False)
        is_full_day = db.Column(db.Boolean, nullable=False, default=False)
        notes = db.Column(db.Text, nullable=False, default="")
        created_at = db.Column(db.DateTime, default=now_local)
        is_active = db.Column(db.Boolean, nullable=False, default=True)
        scene_id = db.Column(db.Integer, nullable=True, index=True)

        edit_suite = db.relationship("EditSuite", backref=db.backref("bookings", lazy=True))
        project = db.relationship("Project", backref=db.backref("suite_bookings", lazy=True))
        booked_by_user = db.relationship(
            "User", foreign_keys=[booked_by_id], backref=db.backref("bookings_created", lazy=True)
        )
        booked_for_user = db.relationship(
            "User", foreign_keys=[booked_for_id], backref=db.backref("bookings_assigned", lazy=True)
        )
        shooting_day_scene = db.relationship(
            "ShootingDayScene",
            primaryjoin=lambda: foreign(Booking.scene_id) == ShootingDayScene.id,
            backref=db.backref("suite_bookings", lazy=True),
            uselist=False,
        )

    class TaskGroup(db.Model):
        __tablename__ = "task_groups"

        id = db.Column(db.Integer, primary_key=True)
        name = db.Column(db.String(120), nullable=False, unique=True)
        sort_order = db.Column(db.Integer, nullable=False, default=0)

    class TaskGroupTitle(db.Model):
        """Preset task title under a task group (Control panel)."""

        __tablename__ = "task_group_titles"

        id = db.Column(db.Integer, primary_key=True)
        group_id = db.Column(db.Integer, db.ForeignKey("task_groups.id"), nullable=False)
        title = db.Column(db.String(200), nullable=False)
        description = db.Column(db.Text, default="")
        sort_order = db.Column(db.Integer, nullable=False, default=0)
        created_at = db.Column(db.DateTime, default=now_local)

        group = db.relationship("TaskGroup", backref=db.backref("title_presets", lazy=True))

    class TaskPriority(db.Model):
        __tablename__ = "task_priorities"

        id = db.Column(db.Integer, primary_key=True)
        name = db.Column(db.String(80), nullable=False, unique=True)
        created_at = db.Column(db.DateTime, default=now_local)

    class Task(db.Model):
        __tablename__ = "tasks"

        id = db.Column(db.Integer, primary_key=True)
        title = db.Column(db.String(200), nullable=False)
        description = db.Column(db.Text, default="")
        status = db.Column(db.String(32), nullable=False, default="open")
        priority = db.Column(db.String(16), nullable=False, default="medium")
        user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
        group_id = db.Column(db.Integer, db.ForeignKey("task_groups.id"), nullable=True)
        project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=True)
        created_at = db.Column(db.DateTime, default=now_local)
        completed_at = db.Column(db.DateTime, nullable=True)
        archived = db.Column(db.Boolean, nullable=False, default=False)
        # Machine-room "Copy Material" live UI (optional; null for normal tasks).
        copy_started_at = db.Column(db.DateTime, nullable=True)
        copy_estimated_minutes = db.Column(db.Integer, nullable=True)
        copy_day_name = db.Column(db.String(80), nullable=True)
        copy_unit_number = db.Column(db.Integer, nullable=True)

        group = db.relationship("TaskGroup", backref=db.backref("tasks", lazy=True))
        project = db.relationship("Project", back_populates="tasks")

    class Project(db.Model):
        __tablename__ = "projects"

        id = db.Column(db.Integer, primary_key=True)
        name = db.Column(db.String(200), nullable=False)
        project_type = db.Column(db.String(120), nullable=False)
        production_house = db.Column(db.String(200), nullable=False)
        director = db.Column(db.String(200), nullable=False)
        created_at = db.Column(db.DateTime, default=now_local)
        sort_order = db.Column(db.Integer, nullable=False, default=0)
        number_of_episodes = db.Column(db.Integer, nullable=False, default=0)
        estimated_shooting_days = db.Column(db.Integer, nullable=False, default=0)

        tasks = db.relationship("Task", back_populates="project", lazy=True)
        memberships = db.relationship(
            "ProjectMember",
            back_populates="project",
            cascade="all, delete-orphan",
            lazy=True,
        )
        chat_messages = db.relationship(
            "ChatMessage",
            back_populates="project",
            cascade="all, delete-orphan",
            lazy=True,
        )
        shooting_days = db.relationship(
            "ShootingDay",
            back_populates="project",
            cascade="all, delete-orphan",
            lazy=True,
            order_by="ShootingDay.shooting_date, ShootingDay.id",
        )
        production_episodes = db.relationship(
            "ProductionEpisode",
            back_populates="project",
            cascade="all, delete-orphan",
            lazy=True,
            order_by="ProductionEpisode.episode_number, ProductionEpisode.id",
        )

    class ShootingDay(db.Model):
        """Flat shooting day per project (spreadsheet-style scene rows)."""

        __tablename__ = "shooting_days_flat"

        id = db.Column(db.Integer, primary_key=True)
        project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False, index=True)
        unit_number = db.Column(db.Integer, nullable=False, default=1)
        day_name = db.Column(db.String(50), nullable=False, default="")
        shooting_date = db.Column(db.Date, nullable=False)

        project = db.relationship("Project", back_populates="shooting_days")
        scene_rows = db.relationship(
            "SceneRow",
            back_populates="shooting_day",
            cascade="all, delete-orphan",
            lazy=True,
            order_by="SceneRow.sort_order, SceneRow.id",
        )
        pipeline_scenes = db.relationship(
            "ShootingDayScene",
            back_populates="shooting_day",
            cascade="all, delete-orphan",
            lazy=True,
            order_by="ShootingDayScene.id",
        )

    class SceneRow(db.Model):
        __tablename__ = "scene_rows"

        id = db.Column(db.Integer, primary_key=True)
        shooting_day_id = db.Column(
            db.Integer, db.ForeignKey("shooting_days_flat.id"), nullable=False, index=True
        )
        episode = db.Column(db.String(120), nullable=False, default="")
        scene = db.Column(db.String(120), nullable=False, default="")
        sync = db.Column(db.Boolean, nullable=False, default=False)
        first_edit = db.Column(db.Boolean, nullable=False, default=False)
        final_edit = db.Column(db.Boolean, nullable=False, default=False)
        duration_seconds = db.Column(db.Integer, nullable=False, default=0)
        notes = db.Column(db.Text, nullable=False, default="")
        sort_order = db.Column(db.Integer, nullable=False, default=0)

        shooting_day = db.relationship("ShootingDay", back_populates="scene_rows")

    class ProductionEpisode(db.Model):
        """Planned episode under a project (scripted production pipeline)."""

        __tablename__ = "pipeline_episodes"
        __table_args__ = (
            db.UniqueConstraint("project_id", "episode_number", name="uq_production_episode_project_num"),
        )

        id = db.Column(db.Integer, primary_key=True)
        project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False, index=True)
        episode_number = db.Column(db.Integer, nullable=False)
        title = db.Column(db.String(200), nullable=True)

        project = db.relationship("Project", back_populates="production_episodes")
        scenes = db.relationship(
            "ProductionScene",
            back_populates="episode",
            cascade="all, delete-orphan",
            lazy=True,
            order_by="ProductionScene.scene_number, ProductionScene.id",
        )

    class ProductionScene(db.Model):
        """Scene under an episode; assignable to shooting days and edit bookings."""

        __tablename__ = "pipeline_scenes"
        __table_args__ = (
            db.UniqueConstraint("episode_id", "scene_number", name="uq_production_scene_episode_num"),
        )

        id = db.Column(db.Integer, primary_key=True)
        episode_id = db.Column(db.Integer, db.ForeignKey("pipeline_episodes.id"), nullable=False, index=True)
        scene_number = db.Column(db.Integer, nullable=False)
        description = db.Column(db.Text, nullable=False, default="")
        estimated_duration_minutes = db.Column(db.Integer, nullable=False, default=0)
        ready_for_editing = db.Column(db.Boolean, nullable=False, default=False)

        episode = db.relationship("ProductionEpisode", back_populates="scenes")
        # Legacy model retained for compatibility; shooting-day rows are now the source of truth.

    class ShootingDayScene(db.Model):
        """Scene row captured under a shooting day (single source of truth)."""

        __tablename__ = "shooting_day_scenes"

        id = db.Column(db.Integer, primary_key=True)
        shooting_day_id = db.Column(
            db.Integer, db.ForeignKey("shooting_days_flat.id"), nullable=False, index=True
        )
        # Legacy column retained for SQLite compatibility with existing databases.
        scene_id = db.Column(db.Integer, nullable=False, default=0, index=True)
        episode_number = db.Column(db.Integer, nullable=False, default=1, index=True)
        scene_label = db.Column(db.String(120), nullable=False, default="")
        scene_number = db.Column(db.Integer, nullable=False, default=1)
        duration = db.Column(db.Integer, nullable=False, default=0)
        duration_seconds = db.Column(db.Integer, nullable=False, default=0)
        # Legacy non-null columns kept for SQLite compatibility with existing rows/schema.
        actual_duration_minutes = db.Column(db.Integer, nullable=False, default=0)
        notes = db.Column(db.Text, nullable=False, default="")
        status = db.Column(db.String(16), nullable=False, default="pending")
        sync_done = db.Column(db.Boolean, nullable=False, default=False)
        first_edit_done = db.Column(db.Boolean, nullable=False, default=False)
        needs_vfx = db.Column(db.Boolean, nullable=False, default=False)

        shooting_day = db.relationship("ShootingDay", back_populates="pipeline_scenes")

    class VfxShot(db.Model):
        __tablename__ = "vfx_shot"
        __table_args__ = (
            db.UniqueConstraint("scene_id", "shot_number", name="uq_vfx_scene_shot_number"),
            db.UniqueConstraint("shot_code", name="uq_vfx_shot_code"),
        )

        id = db.Column(db.Integer, primary_key=True)
        project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False, index=True)
        scene_id = db.Column(db.Integer, db.ForeignKey("shooting_day_scenes.id"), nullable=False, index=True)
        episode_number = db.Column(db.Integer, nullable=True, index=True)
        reel_number = db.Column(db.Integer, nullable=True, index=True)
        shot_number = db.Column(db.Integer, nullable=False, default=1)
        shot_code = db.Column(db.String(64), nullable=False, index=True)
        shot_briefing = db.Column(db.Text, nullable=False, default="")
        department = db.Column(db.String(16), nullable=False, default="animation", index=True)
        vendor = db.Column(db.String(24), nullable=False, default="in_house")
        vendor_name = db.Column(db.String(120), nullable=False, default="")
        shot_ref_frame = db.Column(db.Text, nullable=False, default="")
        sent_at = db.Column(db.DateTime, nullable=True)
        status = db.Column(db.String(16), nullable=False, default="pending", index=True)
        created_at = db.Column(db.DateTime, default=now_local, nullable=False)

        project = db.relationship("Project", backref=db.backref("vfx_shots", lazy=True))
        scene = db.relationship("ShootingDayScene", backref=db.backref("vfx_shots", lazy=True))
        comments = db.relationship(
            "VfxShotComment",
            back_populates="shot",
            cascade="all, delete-orphan",
            lazy=True,
            order_by="VfxShotComment.created_at",
        )

    class VfxVersion(db.Model):
        __tablename__ = "vfx_version"

        id = db.Column(db.Integer, primary_key=True)
        shot_id = db.Column(db.Integer, db.ForeignKey("vfx_shot.id"), nullable=False, index=True)
        version_number = db.Column(db.Integer, nullable=False, default=1)
        image = db.Column(db.Text, nullable=False, default="")
        comment = db.Column(db.Text, nullable=False, default="")
        created_at = db.Column(db.DateTime, default=now_local, nullable=False)

        shot = db.relationship(
            "VfxShot",
            backref=db.backref("versions", lazy=True, cascade="all, delete-orphan"),
        )

    class VfxShotComment(db.Model):
        __tablename__ = "vfx_shot_comment"

        id = db.Column(db.Integer, primary_key=True)
        shot_id = db.Column(db.Integer, db.ForeignKey("vfx_shot.id"), nullable=False, index=True)
        user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
        parent_id = db.Column(db.Integer, db.ForeignKey("vfx_shot_comment.id"), nullable=True, index=True)
        body = db.Column(db.Text, nullable=False, default="")
        resolved = db.Column(db.Boolean, nullable=False, default=False)
        created_at = db.Column(db.DateTime, default=now_local, nullable=False)

        shot = db.relationship("VfxShot", back_populates="comments")
        user = db.relationship("User", backref=db.backref("vfx_shot_comments", lazy=True))

    class SceneReference(db.Model):
        __tablename__ = "scene_reference"

        id = db.Column(db.Integer, primary_key=True)
        scene_id = db.Column(db.Integer, db.ForeignKey("shooting_day_scenes.id"), nullable=False, index=True)
        video_url = db.Column(db.Text, nullable=False, default="")
        notes = db.Column(db.Text, nullable=False, default="")
        created_at = db.Column(db.DateTime, default=now_local, nullable=False)

        scene = db.relationship(
            "ShootingDayScene",
            backref=db.backref("scene_references", lazy=True, cascade="all, delete-orphan"),
        )

    class ProjectMember(db.Model):
        __tablename__ = "project_members"

        id = db.Column(db.Integer, primary_key=True)
        project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False)
        user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
        __table_args__ = (db.UniqueConstraint("project_id", "user_id", name="uq_project_member"),)

        project = db.relationship("Project", back_populates="memberships")
        user = db.relationship("User", backref=db.backref("project_memberships", lazy=True))

    class ChatMessage(db.Model):
        __tablename__ = "chat_messages"

        id = db.Column(db.Integer, primary_key=True)
        project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False, index=True)
        user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
        message = db.Column(db.Text, nullable=True)
        image_path = db.Column(db.String(255), nullable=True)
        audio_path = db.Column(db.String(255), nullable=True)
        created_at = db.Column(db.DateTime, default=now_local)
        is_deleted = db.Column(db.Boolean, nullable=False, default=False)
        deleted_at = db.Column(db.DateTime, nullable=True)

        project = db.relationship("Project", back_populates="chat_messages")
        user = db.relationship("User", backref=db.backref("chat_messages", lazy=True))

    class ChatMessageReaction(db.Model):
        __tablename__ = "chat_message_reactions"

        id = db.Column(db.Integer, primary_key=True)
        message_id = db.Column(db.Integer, db.ForeignKey("chat_messages.id"), nullable=False, index=True)
        user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
        emoji = db.Column(db.String(16), nullable=False)
        __table_args__ = (
            db.UniqueConstraint("message_id", "user_id", name="uq_chat_reaction_msg_user"),
        )

        message = db.relationship(
            "ChatMessage",
            backref=db.backref(
                "reactions",
                lazy=True,
                cascade="all, delete-orphan",
            ),
        )
        user = db.relationship("User", backref=db.backref("chat_message_reactions", lazy=True))

    class ProjectChatReadState(db.Model):
        """Per-account last seen message id per project (for unread counts)."""

        __tablename__ = "project_chat_read_states"

        id = db.Column(db.Integer, primary_key=True)
        account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False)
        project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False)
        last_read_message_id = db.Column(db.Integer, nullable=False, default=0)
        __table_args__ = (
            db.UniqueConstraint("account_id", "project_id", name="uq_chat_read_account_project"),
        )

    class HardDisk(db.Model):
        __tablename__ = "hard_disk"

        id = db.Column(db.Integer, primary_key=True)
        project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False, index=True)
        name = db.Column(db.String(120), nullable=False)
        capacity_tb = db.Column(db.Float, nullable=False, default=0.0)
        type = db.Column(db.String(80), nullable=False, default="")
        created_at = db.Column(db.DateTime, default=now_local)

        project = db.relationship("Project", backref=db.backref("hard_disks", lazy=True))
        usages = db.relationship(
            "HardDiskUsage",
            back_populates="hard_disk",
            cascade="all, delete-orphan",
            lazy=True,
            order_by="HardDiskUsage.id",
        )

    class HardDiskUsage(db.Model):
        __tablename__ = "hard_disk_usage"
        __table_args__ = (
            db.UniqueConstraint("hard_disk_id", "shooting_day_id", name="uq_hdd_usage_disk_day"),
        )

        id = db.Column(db.Integer, primary_key=True)
        hard_disk_id = db.Column(db.Integer, db.ForeignKey("hard_disk.id"), nullable=False, index=True)
        shooting_day_id = db.Column(
            db.Integer, db.ForeignKey("shooting_days_flat.id"), nullable=False, index=True
        )
        video_size_tb = db.Column(db.Float, nullable=False, default=0.0)
        audio_size_tb = db.Column(db.Float, nullable=False, default=0.0)
        notes = db.Column(db.Text, nullable=False, default="")

        hard_disk = db.relationship("HardDisk", back_populates="usages")
        shooting_day = db.relationship("ShootingDay")

    class Notification(db.Model):
        __tablename__ = "notification"
        __table_args__ = (
            db.UniqueConstraint("rule_key", name="uq_notification_rule_key"),
        )

        id = db.Column(db.Integer, primary_key=True)
        user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
        type = db.Column(db.String(32), nullable=False, default="activity", index=True)
        severity = db.Column(db.String(16), nullable=False, default="info", index=True)
        title = db.Column(db.String(255), nullable=False, default="")
        message = db.Column(db.Text, nullable=False, default="")
        entity_type = db.Column(db.String(64), nullable=False, default="", index=True)
        entity_id = db.Column(db.Integer, nullable=False, default=0, index=True)
        project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=True, index=True)
        is_read = db.Column(db.Boolean, nullable=False, default=False, index=True)
        is_acknowledged = db.Column(db.Boolean, nullable=False, default=False, index=True)
        is_resolved = db.Column(db.Boolean, nullable=False, default=False, index=True)
        rule_key = db.Column(db.String(255), nullable=False, default="")
        created_at = db.Column(db.DateTime, nullable=False, default=now_local, index=True)

        user = db.relationship("User", backref=db.backref("notifications", lazy=True))
        project = db.relationship("Project", backref=db.backref("notifications", lazy=True))

    class MusicMount(db.Model):
        """Server-side mount point for indexed audio (no uploads)."""

        __tablename__ = "music_mount"
        __table_args__ = (db.UniqueConstraint("base_path", name="uq_music_mount_base_path"),)

        id = db.Column(db.Integer, primary_key=True)
        name = db.Column(db.String(512), nullable=False, default="")
        base_path = db.Column(db.String(2048), nullable=False, default="")
        created_at = db.Column(db.DateTime, nullable=False, default=now_local, index=True)

        files = db.relationship("MusicFile", back_populates="mount", lazy=True)

    class MusicFile(db.Model):
        """Indexed audio on disk; file_path is absolute; scoped to mount when mount_id is set."""

        __tablename__ = "music_file"

        id = db.Column(db.Integer, primary_key=True)
        mount_id = db.Column(db.Integer, db.ForeignKey("music_mount.id"), nullable=True, index=True)
        file_path = db.Column(db.String(2048), nullable=False, unique=True, index=True)
        name = db.Column(db.String(512), nullable=False, index=True)
        folder = db.Column(db.String(2048), nullable=False, default="")
        duration = db.Column(db.Float, nullable=False, default=0.0)
        type = db.Column(db.String(16), nullable=False, default="")
        color_tag = db.Column(db.String(64), nullable=True)
        is_favorite = db.Column(db.Boolean, nullable=False, default=False)
        comments = db.Column(db.Text, nullable=True)
        created_at = db.Column(db.DateTime, nullable=False, default=now_local, index=True)

        mount = db.relationship("MusicMount", back_populates="files")

    class AudioUsage(db.Model):
        __tablename__ = "audio_usage"

        id = db.Column(db.Integer, primary_key=True)
        file_id = db.Column(db.Integer, db.ForeignKey("music_file.id"), nullable=False, index=True)
        project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=True, index=True)
        user_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=True, index=True)
        action = db.Column(db.String(24), nullable=False, default="play", index=True)
        created_at = db.Column(db.DateTime, nullable=False, default=now_local, index=True)

        file = db.relationship("MusicFile", backref=db.backref("usage_rows", lazy=True))
        project = db.relationship("Project", backref=db.backref("audio_usage_rows", lazy=True))
        user = db.relationship("Account", backref=db.backref("audio_usage_rows", lazy=True))

    class ProjectAudioLibrary(db.Model):
        __tablename__ = "project_audio_library"

        id = db.Column(db.Integer, primary_key=True)
        project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False, index=True)
        name = db.Column(db.String(255), nullable=False, default="")
        parent_id = db.Column(db.Integer, db.ForeignKey("project_audio_library.id"), nullable=True, index=True)
        created_at = db.Column(db.DateTime, nullable=False, default=now_local, index=True)

        project = db.relationship("Project", backref=db.backref("audio_libraries", lazy=True))
        parent = db.relationship(
            "ProjectAudioLibrary",
            remote_side=[id],
            backref=db.backref("children", lazy=True),
        )

    class ProjectAudioFolder(db.Model):
        __tablename__ = "project_audio_folder"
        __table_args__ = (
            db.UniqueConstraint(
                "project_id",
                "library_id",
                "mount_id",
                "folder_path",
                name="uq_project_audio_folder_link",
            ),
        )

        id = db.Column(db.Integer, primary_key=True)
        project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False, index=True)
        library_id = db.Column(db.Integer, db.ForeignKey("project_audio_library.id"), nullable=False, index=True)
        mount_id = db.Column(db.Integer, db.ForeignKey("music_mount.id"), nullable=False, index=True)
        folder_path = db.Column(db.String(2048), nullable=False, default="")
        created_at = db.Column(db.DateTime, nullable=False, default=now_local, index=True)

        project = db.relationship("Project", backref=db.backref("audio_folder_links", lazy=True))
        library = db.relationship("ProjectAudioLibrary", backref=db.backref("folder_links", lazy=True))
        mount = db.relationship("MusicMount")

    # Hard-disk UI: audio entered in GB; columns remain TB (decimal GB per TB).
    HDD_STORAGE_GB_PER_TB = 1000.0
    VFX_REVIEW_THRESHOLD_DAYS = 2

    def _utc_now() -> datetime:
        """Naive Africa/Cairo wall time for ORM columns (same as :func:`now_local`)."""
        return now_local()

    def _cairo_now_aware() -> datetime:
        """Current instant as timezone-aware Cairo (for deltas vs stored naive rows)."""
        return datetime.now(CAIRO_TZ)

    def _ensure_cairo_aware(dt: datetime | None) -> datetime | None:
        """Interpret naive datetimes as Cairo wall time; return timezone-aware Cairo."""
        if dt is None:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=CAIRO_TZ)
        return dt.astimezone(CAIRO_TZ)

    def isoformat_stored_instant(dt: datetime | None) -> str:
        """ISO-8601 string for JSON (naive = Cairo wall clock; no trailing Z)."""
        if dt is None or not isinstance(dt, datetime):
            return ""
        if dt.tzinfo is not None:
            dt = dt.astimezone(CAIRO_TZ).replace(tzinfo=None)
        return dt.replace(microsecond=0).isoformat(timespec="seconds")

    def _epoch_ms_from_stored_naive(dt: datetime | None) -> float:
        if dt is None or not isinstance(dt, datetime):
            return 0.0
        if dt.tzinfo is None:
            aware = dt.replace(tzinfo=CAIRO_TZ)
        else:
            aware = dt.astimezone(CAIRO_TZ)
        return float(aware.timestamp() * 1000.0)

    def format_datetime_cairo(dt: date | datetime | None, fmt: str = "%Y-%m-%d %H:%M") -> str:
        """Format stored naive Cairo datetime for server-rendered HTML."""
        if dt is None:
            return "—"
        if isinstance(dt, date) and not isinstance(dt, datetime):
            return dt.isoformat()
        if not isinstance(dt, datetime):
            return "—"
        if dt.tzinfo is not None:
            dt = dt.astimezone(CAIRO_TZ).replace(tzinfo=None)
        return dt.strftime(fmt)

    def _notification_unresolved_filter():
        """Treat NULL is_resolved as open (SQLite / legacy rows)."""
        return or_(Notification.is_resolved.is_(False), Notification.is_resolved.is_(None))

    def _notification_rule_key(rule: str, entity_type: str, entity_id: int, user_id: int) -> str:
        return f"{rule}:{entity_type}:{int(entity_id)}:{int(user_id)}"

    def _project_team_user_ids(project_id: int | None) -> list[int]:
        if project_id is None:
            return []
        rows = ProjectMember.query.filter_by(project_id=int(project_id)).all()
        return sorted({int(m.user_id) for m in rows if m.user_id is not None})

    def _notification_emit_to_project(
        *,
        project_id: int | None,
        rule: str,
        n_type: str,
        severity: str,
        title: str,
        message: str,
        entity_type: str,
        entity_id: int,
        extra_user_ids: Sequence[int] | None = None,
    ) -> None:
        """Create one notification per project team member (user-specific rows)."""
        if project_id is None:
            return
        base = set(_project_team_user_ids(project_id))
        for x in extra_user_ids or ():
            try:
                base.add(int(x))
            except (TypeError, ValueError):
                continue
        uid_list = sorted(base)
        if not uid_list:
            return
        eid = int(entity_id or 0)
        et = (entity_type or "").strip() or "unknown"
        r = (rule or "").strip() or "rule"
        for uid in uid_list:
            rk = _notification_rule_key(r, et, eid, uid)
            if Notification.query.filter_by(rule_key=rk).first() is not None:
                continue
            n = Notification(
                user_id=uid,
                type=n_type,
                severity=severity,
                title=title,
                message=message,
                entity_type=et,
                entity_id=eid,
                project_id=int(project_id),
                is_read=False,
                is_acknowledged=False,
                is_resolved=False,
                rule_key=rk,
                created_at=_utc_now(),
            )
            db.session.add(n)
        db.session.flush()

    def _notification_resolve_project_rule_prefix(project_id: int | None, rule_prefix: str) -> None:
        """Mark unresolved notifications for this project whose rule_key starts with prefix."""
        if project_id is None or not (rule_prefix or "").strip():
            return
        pref = rule_prefix.strip()
        rows = (
            Notification.query.filter(
                Notification.project_id == int(project_id),
                Notification.rule_key.startswith(pref),
                _notification_unresolved_filter(),
            )
            .all()
        )
        for row in rows:
            row.is_resolved = True
            row.is_read = True

    def evaluate_hdd_notifications(hdd_id: int) -> None:
        hd = db.session.get(HardDisk, hdd_id)
        if hd is None:
            return
        used = (
            db.session.query(
                db.func.coalesce(
                    db.func.sum(HardDiskUsage.video_size_tb + HardDiskUsage.audio_size_tb),
                    0.0,
                )
            )
            .filter(HardDiskUsage.hard_disk_id == hd.id)
            .scalar()
        )
        used_tb = float(used or 0.0)
        cap_tb = float(hd.capacity_tb or 0.0)
        free_tb = cap_tb - used_tb

        rk_over_prefix = f"hdd_over_capacity:hdd:{hd.id}:"
        if used_tb > cap_tb + 1e-9:
            _notification_emit_to_project(
                project_id=hd.project_id,
                rule="hdd_over_capacity",
                n_type="alert",
                severity="critical",
                title=f"{(hd.name or 'HDD').strip()} over capacity",
                message=f"Used {used_tb:.2f}TB / {cap_tb:.2f}TB.",
                entity_type="hdd",
                entity_id=hd.id,
            )
        else:
            _notification_resolve_project_rule_prefix(hd.project_id, rk_over_prefix)

        rk_low_prefix = f"hdd_low_free:hdd:{hd.id}:"
        is_low_free = cap_tb > 0 and free_tb / cap_tb < 0.1
        if is_low_free:
            _notification_emit_to_project(
                project_id=hd.project_id,
                rule="hdd_low_free",
                n_type="alert",
                severity="warning",
                title=f"{(hd.name or 'HDD').strip()} low free space",
                message=f"Free {free_tb:.2f}TB ({(100.0 * free_tb / cap_tb):.1f}%).",
                entity_type="hdd",
                entity_id=hd.id,
            )
        else:
            _notification_resolve_project_rule_prefix(hd.project_id, rk_low_prefix)

    def emit_booking_overlap_alert(
        *,
        project_id: int,
        suite_id: int,
        booking_date: date,
        start_t,
        end_t,
        attempting_user_id: int | None = None,
    ) -> None:
        suite = db.session.get(EditSuite, suite_id)
        suite_name = (suite.name if suite is not None else f"Suite {suite_id}").strip()
        overlap_rule = (
            f"booking_overlap|{project_id}|{suite_id}|{booking_date.isoformat()}|"
            f"{start_t.isoformat()}|{end_t.isoformat()}"
        )
        extra = [attempting_user_id] if attempting_user_id is not None else None
        _notification_emit_to_project(
            project_id=project_id,
            rule=overlap_rule,
            n_type="alert",
            severity="critical",
            title="Booking overlap detected",
            message=f"{suite_name} overlaps on {booking_date.isoformat()} ({start_t.strftime('%H:%M')}–{end_t.strftime('%H:%M')}).",
            entity_type="booking",
            entity_id=int(suite_id),
            extra_user_ids=extra,
        )

    def emit_shooting_day_created_activity(day: ShootingDay, source: str) -> None:
        proj = db.session.get(Project, day.project_id)
        pname = (proj.name or "").strip() if proj is not None else "Project"
        _notification_emit_to_project(
            project_id=day.project_id,
            rule="shooting_day_created",
            n_type="activity",
            severity="info",
            title=f"{pname} · Shooting day created ({source})",
            message=f"Unit {int(day.unit_number or 1)} · Day {(day.day_name or '').strip() or '—'} · {day.shooting_date.isoformat()}",
            entity_type="shooting_day",
            entity_id=day.id,
        )

    def _notification_relative_time(ts: datetime | None) -> str:
        if ts is None:
            return ""
        ts_cairo = _ensure_cairo_aware(ts)
        if ts_cairo is None:
            return ""
        delta = _cairo_now_aware() - ts_cairo
        sec = max(0, int(delta.total_seconds()))
        if sec < 60:
            return f"{sec}s ago"
        mins = sec // 60
        if mins < 60:
            return f"{mins}m ago"
        hrs = mins // 60
        if hrs < 24:
            return f"{hrs}h ago"
        days = hrs // 24
        return f"{days}d ago"

    def serialize_notification(n: Notification) -> dict:
        """JSON-safe payload for the notification panel (all keys always present)."""
        created_iso = isoformat_stored_instant(n.created_at if isinstance(n.created_at, datetime) else None)
        return {
            "id": int(n.id or 0),
            "title": (n.title or "") if n.title is not None else "",
            "message": (n.message or "") if n.message is not None else "",
            "severity": ((n.severity or "info") or "info").strip().lower(),
            "type": ((n.type or "activity") or "activity").strip().lower(),
            "entity_type": (n.entity_type or "") if n.entity_type is not None else "",
            "entity_id": int(n.entity_id or 0),
            "project_id": int(n.project_id) if n.project_id is not None else None,
            "user_id": int(n.user_id) if n.user_id is not None else None,
            "is_read": bool(n.is_read),
            "is_acknowledged": bool(n.is_acknowledged),
            "is_resolved": bool(n.is_resolved) if n.is_resolved is not None else False,
            "rule_key": (n.rule_key or "") if n.rule_key is not None else "",
            "created_at": created_iso,
            "created_ago": _notification_relative_time(
                n.created_at if isinstance(n.created_at, datetime) else None
            ),
        }

    def shooting_day_scene_duration_seconds(link: ShootingDayScene) -> int:
        ds = int(getattr(link, "duration_seconds", 0) or 0)
        if ds > 0:
            return ds
        return max(0, int(link.duration or 0)) * 60

    def shooting_day_total_seconds(day: ShootingDay) -> int:
        """Legacy scene rows (seconds) + pipeline rows (duration_seconds or legacy minutes)."""
        legacy_sec = sum(int(r.duration_seconds or 0) for r in day.scene_rows)
        pipeline_sec = sum(shooting_day_scene_duration_seconds(link) for link in day.pipeline_scenes)
        return legacy_sec + pipeline_sec

    def shooting_day_sync_edit_percentages(day: ShootingDay) -> dict[str, int]:
        """Percent of rows with sync and first edit done (pipeline rows + legacy scene rows)."""
        pipeline = list(getattr(day, "pipeline_scenes", ()) or ())
        legacy = list(getattr(day, "scene_rows", ()) or ())
        total = len(pipeline) + len(legacy)
        if not total:
            return {"sync": 0, "edit": 0}
        sync_n = sum(1 for ln in pipeline if ln.sync_done) + sum(1 for r in legacy if r.sync)
        edit_n = sum(1 for ln in pipeline if ln.first_edit_done) + sum(
            1 for r in legacy if r.first_edit
        )
        return {
            "sync": int(round(100.0 * sync_n / total)),
            "edit": int(round(100.0 * edit_n / total)),
        }

    def _parse_scene_number_from_label(raw_scene_label: str | None, fallback: int = 1) -> int:
        raw = (raw_scene_label or "").strip()
        m = re.search(r"\d+", raw)
        if m:
            try:
                return max(1, int(m.group(0)))
            except (TypeError, ValueError):
                pass
        return max(1, int(fallback or 1))

    def _next_vfx_shot_number(scene_id: int) -> int:
        mx = (
            db.session.query(func.max(VfxShot.shot_number))
            .filter(VfxShot.scene_id == int(scene_id))
            .scalar()
        )
        return max(0, int(mx or 0)) + 1

    def _build_vfx_shot_code(episode_number: int, scene_number: int, shot_number: int) -> str:
        return (
            f"Eps{int(episode_number or 0):02d}_"
            f"Scene{int(scene_number or 0):02d}_"
            f"Shot{int(shot_number or 0):02d}"
        )

    def format_duration_mmss(seconds: int) -> str:
        sec = max(0, int(seconds or 0))
        m, s = divmod(sec, 60)
        return f"{m:02d}:{s:02d}"

    def format_duration_day_total(seconds: int) -> str:
        sec = max(0, int(seconds or 0))
        m, s = divmod(sec, 60)
        return f"{m}:{s:02d}"

    def parse_duration_input(raw: str | None) -> int | None:
        s = (raw or "").strip()
        if not s:
            return None
        if s.isdigit():
            return max(0, int(s))
        parts = [p.strip() for p in s.split(":") if p.strip() != ""]
        try:
            if len(parts) == 2:
                return max(0, int(parts[0]) * 60 + int(parts[1]))
            if len(parts) == 3:
                return max(0, int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2]))
        except ValueError:
            return None
        return None

    def parse_shooting_day_duration_seconds(raw: str | None) -> int | None:
        """M:SS / H:MM:SS, or a whole number meaning minutes (legacy). Empty = 0."""
        s = (raw or "").strip()
        if not s:
            return 0
        if ":" in s:
            v = parse_duration_input(s)
            return v
        if s.isdigit():
            return max(0, int(s)) * 60
        return parse_duration_input(s)

    def scene_row_to_dict(r: SceneRow) -> dict:
        return {
            "id": r.id,
            "episode": r.episode or "",
            "scene": r.scene or "",
            "sync": bool(r.sync),
            "first_edit": bool(r.first_edit),
            "final_edit": bool(r.final_edit),
            "duration_seconds": int(r.duration_seconds or 0),
            "notes": r.notes or "",
        }

    PRESET_AVATAR_IDS = tuple(f"{i:02d}" for i in range(1, AVATAR_PRESET_COUNT + 1))

    def normalize_avatar_preset_id(raw: str | None) -> str:
        s = (raw or "01").strip()
        if s.isdigit():
            s = f"{int(s):02d}"
        return s if s in PRESET_AVATAR_IDS else "01"

    def preset_avatar_static_path(pid: str | None) -> str:
        return f"avatars/preset-{normalize_avatar_preset_id(pid)}.svg"

    def remove_profile_avatar_file(basename: str | None) -> None:
        if not basename or "/" in basename or "\\" in basename or basename.startswith("."):
            return
        path = os.path.join(upload_root, basename)
        real_upload = os.path.realpath(upload_root)
        real_file = os.path.realpath(path)
        try:
            if os.path.commonpath([real_upload, real_file]) != real_upload:
                return
        except ValueError:
            return
        if os.path.isfile(real_file):
            try:
                os.remove(real_file)
            except OSError:
                pass

    def remove_chat_upload_file(basename: str | None) -> None:
        if not basename or "/" in basename or "\\" in basename or basename.startswith("."):
            return
        path = os.path.join(chat_upload_root, basename)
        real_upload = os.path.realpath(chat_upload_root)
        real_file = os.path.realpath(path)
        try:
            if os.path.commonpath([real_upload, real_file]) != real_upload:
                return
        except ValueError:
            return
        if os.path.isfile(real_file):
            try:
                os.remove(real_file)
            except OSError:
                pass

    def remove_scene_reference_file(basename: str | None) -> None:
        if not basename or "/" in basename or "\\" in basename or basename.startswith("."):
            return
        path = os.path.join(scene_ref_upload_root, basename)
        real_upload = os.path.realpath(scene_ref_upload_root)
        real_file = os.path.realpath(path)
        try:
            if os.path.commonpath([real_upload, real_file]) != real_upload:
                return
        except ValueError:
            return
        if os.path.isfile(real_file):
            try:
                os.remove(real_file)
            except OSError:
                pass

    def remove_vfx_version_file(basename: str | None) -> None:
        if not basename or "/" in basename or "\\" in basename or basename.startswith("."):
            return
        path = os.path.join(vfx_version_upload_root, basename)
        real_upload = os.path.realpath(vfx_version_upload_root)
        real_file = os.path.realpath(path)
        try:
            if os.path.commonpath([real_upload, real_file]) != real_upload:
                return
        except ValueError:
            return
        if os.path.isfile(real_file):
            try:
                os.remove(real_file)
            except OSError:
                pass

    def avatar_href_for_user(u: User | None) -> str:
        if u is None:
            return url_for("static", filename="avatars/preset-01.svg")
        kind = (u.avatar_kind or "preset").lower()
        if kind == "upload" and (u.avatar_upload or "").strip():
            return url_for("profile_avatar_file", filename=u.avatar_upload.strip())
        return url_for("static", filename=preset_avatar_static_path(u.avatar_preset))

    bootstrap_admin_email = os.environ.get("BOOTSTRAP_ADMIN_EMAIL", "admin@tbbstudios.com").strip().lower()
    bootstrap_admin_username = (os.environ.get("BOOTSTRAP_ADMIN_USERNAME", "admin") or "admin").strip().lower()
    bootstrap_admin_password = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD", "password")

    def ensure_sqlite_accounts_username_role_columns() -> None:
        if db.engine.dialect.name != "sqlite":
            return
        insp = inspect(db.engine)
        if "accounts" not in insp.get_table_names():
            return
        col_names = {c["name"] for c in insp.get_columns("accounts")}
        with db.engine.begin() as conn:
            if "username" not in col_names:
                conn.execute(text("ALTER TABLE accounts ADD COLUMN username VARCHAR(64)"))
            if "role" not in col_names:
                conn.execute(text("ALTER TABLE accounts ADD COLUMN role VARCHAR(32)"))
            conn.execute(text("UPDATE accounts SET role = 'user' WHERE role IS NULL OR role = ''"))

    def ensure_bootstrap_admin_account() -> None:
        if not bootstrap_admin_email:
            return
        acc = Account.query.filter_by(email=bootstrap_admin_email).first()
        if acc:
            changed = False
            if acc.role != ROLE_ADMIN:
                acc.role = ROLE_ADMIN
                changed = True
            if bootstrap_admin_username:
                taken = Account.query.filter(
                    Account.id != acc.id,
                    Account.username == bootstrap_admin_username,
                ).first()
                if not taken and acc.username != bootstrap_admin_username:
                    acc.username = bootstrap_admin_username
                    changed = True
            if changed:
                db.session.commit()
            return
        uname = bootstrap_admin_username
        if uname and Account.query.filter_by(username=uname).first():
            uname = None
        db.session.add(
            Account(
                email=bootstrap_admin_email,
                username=uname,
                password_hash=generate_password_hash(bootstrap_admin_password, method="pbkdf2:sha256"),
                role=ROLE_ADMIN,
            )
        )
        db.session.commit()

    def ensure_sqlite_users_account_column() -> None:
        if db.engine.dialect.name != "sqlite":
            return
        insp = inspect(db.engine)
        if "users" not in insp.get_table_names():
            return
        col_names = {c["name"] for c in insp.get_columns("users")}
        if "account_id" in col_names:
            return
        with db.engine.begin() as conn:
            conn.execute(text("ALTER TABLE users ADD COLUMN account_id INTEGER UNIQUE"))

    def ensure_sqlite_users_profile_columns() -> None:
        if db.engine.dialect.name != "sqlite":
            return
        insp = inspect(db.engine)
        if "users" not in insp.get_table_names():
            return
        col_names = {c["name"] for c in insp.get_columns("users")}
        stmts: list[str] = []
        if "phone" not in col_names:
            stmts.append("ALTER TABLE users ADD COLUMN phone VARCHAR(40)")
        if "avatar_kind" not in col_names:
            stmts.append(
                "ALTER TABLE users ADD COLUMN avatar_kind VARCHAR(16) NOT NULL DEFAULT 'preset'"
            )
        if "avatar_preset" not in col_names:
            stmts.append(
                "ALTER TABLE users ADD COLUMN avatar_preset VARCHAR(8) NOT NULL DEFAULT '01'"
            )
        if "avatar_upload" not in col_names:
            stmts.append("ALTER TABLE users ADD COLUMN avatar_upload VARCHAR(255)")
        if stmts:
            with db.engine.begin() as conn:
                for stmt in stmts:
                    conn.execute(text(stmt))
        for u in User.query.all():
            if not (u.avatar_kind or "").strip():
                u.avatar_kind = "preset"
            if not (u.avatar_preset or "").strip():
                u.avatar_preset = "01"
        db.session.commit()

    def ensure_sqlite_users_job_title_column() -> None:
        if db.engine.dialect.name != "sqlite":
            return
        insp = inspect(db.engine)
        if "users" not in insp.get_table_names():
            return
        col_names = {c["name"] for c in insp.get_columns("users")}
        if "job_title_id" in col_names:
            return
        with db.engine.begin() as conn:
            conn.execute(text("ALTER TABLE users ADD COLUMN job_title_id INTEGER"))

    def link_account_to_directory_user(acc: Account, display_name: str | None = None) -> User:
        """Ensure a directory User row exists for this login account (assignee list)."""
        linked = User.query.filter_by(account_id=acc.id).first()
        if linked:
            return linked
        name = (display_name or "").strip() or _display_name_from_email(acc.email)
        existing = User.query.filter_by(email=acc.email).first()
        if existing is not None:
            if existing.account_id is None:
                existing.account_id = acc.id
                if (display_name or "").strip():
                    existing.name = name
                return existing
            if existing.account_id == acc.id:
                return existing
        u = User(name=name, email=acc.email, account_id=acc.id)
        db.session.add(u)
        return u

    def ensure_all_accounts_have_directory_users() -> None:
        for acc in Account.query.order_by(Account.id).all():
            link_account_to_directory_user(acc, display_name=None)
        db.session.commit()

    def ensure_sqlite_tasks_group_column() -> None:
        if db.engine.dialect.name != "sqlite":
            return
        insp = inspect(db.engine)
        if "tasks" not in insp.get_table_names():
            return
        col_names = {c["name"] for c in insp.get_columns("tasks")}
        if "group_id" in col_names:
            return
        with db.engine.begin() as conn:
            conn.execute(text("ALTER TABLE tasks ADD COLUMN group_id INTEGER"))

    def ensure_sqlite_tasks_project_column() -> None:
        if db.engine.dialect.name != "sqlite":
            return
        insp = inspect(db.engine)
        if "tasks" not in insp.get_table_names():
            return
        col_names = {c["name"] for c in insp.get_columns("tasks")}
        if "project_id" in col_names:
            return
        with db.engine.begin() as conn:
            conn.execute(text("ALTER TABLE tasks ADD COLUMN project_id INTEGER"))

    def ensure_sqlite_projects_sort_order_column() -> None:
        if db.engine.dialect.name != "sqlite":
            return
        insp = inspect(db.engine)
        if "projects" not in insp.get_table_names():
            return
        col_names = {c["name"] for c in insp.get_columns("projects")}
        if "sort_order" in col_names:
            return
        with db.engine.begin() as conn:
            conn.execute(text("ALTER TABLE projects ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0"))
        ordered = Project.query.order_by(Project.created_at.asc(), Project.id.asc()).all()
        for i, p in enumerate(ordered):
            p.sort_order = i
        db.session.commit()

    def ensure_sqlite_projects_episodes_shooting_columns() -> None:
        if db.engine.dialect.name != "sqlite":
            return
        insp = inspect(db.engine)
        if "projects" not in insp.get_table_names():
            return
        col_names = {c["name"] for c in insp.get_columns("projects")}
        with db.engine.begin() as conn:
            if "number_of_episodes" not in col_names:
                conn.execute(
                    text("ALTER TABLE projects ADD COLUMN number_of_episodes INTEGER NOT NULL DEFAULT 0")
                )
            if "estimated_shooting_days" not in col_names:
                conn.execute(
                    text(
                        "ALTER TABLE projects ADD COLUMN estimated_shooting_days INTEGER NOT NULL DEFAULT 0"
                    )
                )

    def ensure_pipeline_pool_user() -> User:
        u = User.query.filter_by(email=POOL_USER_EMAIL).first()
        if u:
            return u
        u = User(name=POOL_USER_NAME, email=POOL_USER_EMAIL)
        db.session.add(u)
        db.session.commit()
        return u

    def ensure_task_groups_and_editing_tasks() -> None:
        for i, name in enumerate(DEFAULT_TASK_GROUP_NAMES):
            g = TaskGroup.query.filter_by(name=name).first()
            if g is None:
                db.session.add(TaskGroup(name=name, sort_order=i))
        db.session.commit()

        editing = TaskGroup.query.filter_by(name="Editing").first()
        if editing is None:
            return

        have = {row.title for row in TaskGroupTitle.query.filter_by(group_id=editing.id).all()}
        for title in EDITING_GROUP_TASK_TITLES:
            if title in have:
                continue
            mx = (
                db.session.query(db.func.max(TaskGroupTitle.sort_order))
                .filter(TaskGroupTitle.group_id == editing.id)
                .scalar()
            )
            nxt = (mx if mx is not None else -1) + 1
            db.session.add(TaskGroupTitle(group_id=editing.id, title=title, sort_order=nxt))
        db.session.commit()

    def ensure_sqlite_chat_messages_audio_path() -> None:
        if db.engine.dialect.name != "sqlite":
            return
        insp = inspect(db.engine)
        if "chat_messages" not in insp.get_table_names():
            return
        col_names = {c["name"] for c in insp.get_columns("chat_messages")}
        if "audio_path" in col_names:
            return
        with db.engine.begin() as conn:
            conn.execute(text("ALTER TABLE chat_messages ADD COLUMN audio_path VARCHAR(255)"))

    def ensure_sqlite_chat_messages_soft_delete_columns() -> None:
        if db.engine.dialect.name != "sqlite":
            return
        insp = inspect(db.engine)
        if "chat_messages" not in insp.get_table_names():
            return
        col_names = {c["name"] for c in insp.get_columns("chat_messages")}
        with db.engine.begin() as conn:
            if "is_deleted" not in col_names:
                conn.execute(
                    text(
                        "ALTER TABLE chat_messages ADD COLUMN is_deleted BOOLEAN NOT NULL DEFAULT 0"
                    )
                )
            if "deleted_at" not in col_names:
                conn.execute(text("ALTER TABLE chat_messages ADD COLUMN deleted_at DATETIME"))

    def ensure_sqlite_tasks_completed_archived_columns() -> None:
        if db.engine.dialect.name != "sqlite":
            return
        insp = inspect(db.engine)
        if "tasks" not in insp.get_table_names():
            return
        col_names = {c["name"] for c in insp.get_columns("tasks")}
        added_completed = False
        with db.engine.begin() as conn:
            if "completed_at" not in col_names:
                conn.execute(text("ALTER TABLE tasks ADD COLUMN completed_at DATETIME"))
                added_completed = True
            if "archived" not in col_names:
                conn.execute(text("ALTER TABLE tasks ADD COLUMN archived BOOLEAN NOT NULL DEFAULT 0"))
        if added_completed:
            with db.engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE tasks SET completed_at = created_at "
                        "WHERE status = 'done' AND completed_at IS NULL"
                    )
                )

    def ensure_sqlite_tasks_priority_column() -> None:
        if db.engine.dialect.name != "sqlite":
            return
        insp = inspect(db.engine)
        if "tasks" not in insp.get_table_names():
            return
        col_names = {c["name"] for c in insp.get_columns("tasks")}
        if "priority" in col_names:
            return
        with db.engine.begin() as conn:
            conn.execute(text("ALTER TABLE tasks ADD COLUMN priority VARCHAR(16) NOT NULL DEFAULT 'medium'"))
            conn.execute(text("UPDATE tasks SET priority = 'medium' WHERE priority IS NULL OR priority = ''"))

    def ensure_sqlite_tasks_copy_material_columns() -> None:
        if db.engine.dialect.name != "sqlite":
            return
        insp = inspect(db.engine)
        if "tasks" not in insp.get_table_names():
            return
        col_names = {c["name"] for c in insp.get_columns("tasks")}
        with db.engine.begin() as conn:
            if "copy_started_at" not in col_names:
                conn.execute(text("ALTER TABLE tasks ADD COLUMN copy_started_at DATETIME"))
            if "copy_estimated_minutes" not in col_names:
                conn.execute(text("ALTER TABLE tasks ADD COLUMN copy_estimated_minutes INTEGER"))
            if "copy_day_name" not in col_names:
                conn.execute(text("ALTER TABLE tasks ADD COLUMN copy_day_name VARCHAR(80)"))
            if "copy_unit_number" not in col_names:
                conn.execute(text("ALTER TABLE tasks ADD COLUMN copy_unit_number INTEGER"))

    def ensure_sqlite_bookings_v2_columns() -> None:
        if db.engine.dialect.name != "sqlite":
            return
        insp = inspect(db.engine)
        if "bookings" not in insp.get_table_names():
            return
        col_names = {c["name"] for c in insp.get_columns("bookings")}
        with db.engine.begin() as conn:
            if "project_id" not in col_names:
                conn.execute(text("ALTER TABLE bookings ADD COLUMN project_id INTEGER"))
            if "booked_by_id" not in col_names:
                conn.execute(text("ALTER TABLE bookings ADD COLUMN booked_by_id INTEGER"))
            if "booked_for_id" not in col_names:
                conn.execute(text("ALTER TABLE bookings ADD COLUMN booked_for_id INTEGER"))
            if "notes" not in col_names:
                conn.execute(text("ALTER TABLE bookings ADD COLUMN notes TEXT NOT NULL DEFAULT ''"))
        col_names = {c["name"] for c in insp.get_columns("bookings")}
        if "user_id" in col_names:
            with db.engine.begin() as conn:
                conn.execute(text("UPDATE bookings SET booked_by_id = user_id WHERE booked_by_id IS NULL"))
                conn.execute(text("UPDATE bookings SET booked_for_id = user_id WHERE booked_for_id IS NULL"))
        with db.engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE bookings SET project_id = (SELECT MIN(id) FROM projects) "
                    "WHERE project_id IS NULL AND EXISTS (SELECT 1 FROM projects)"
                )
            )
            conn.execute(
                text(
                    "UPDATE bookings SET user_id = booked_by_id "
                    "WHERE user_id IS NULL AND booked_by_id IS NOT NULL"
                )
            )

    def ensure_sqlite_shooting_days_flat_unit_day_name_columns() -> None:
        if db.engine.dialect.name != "sqlite":
            return
        insp = inspect(db.engine)
        if "shooting_days_flat" not in insp.get_table_names():
            return
        col_names = {c["name"] for c in insp.get_columns("shooting_days_flat")}
        with db.engine.begin() as conn:
            if "unit_number" not in col_names:
                conn.execute(
                    text(
                        "ALTER TABLE shooting_days_flat ADD COLUMN unit_number INTEGER NOT NULL DEFAULT 1"
                    )
                )
            if "day_name" not in col_names:
                conn.execute(
                    text(
                        "ALTER TABLE shooting_days_flat ADD COLUMN day_name VARCHAR(50) NOT NULL DEFAULT ''"
                    )
                )
        rows = (
            ShootingDay.query.order_by(
                ShootingDay.project_id, ShootingDay.shooting_date.asc(), ShootingDay.id.asc()
            ).all()
        )
        if not any(not (d.day_name or "").strip() for d in rows):
            return
        cur_pid: int | None = None
        idx = 0
        for d in rows:
            if d.project_id != cur_pid:
                cur_pid = d.project_id
                idx = 0
            idx += 1
            if not (d.day_name or "").strip():
                d.day_name = f"Day {idx}"
            if d.unit_number is None or int(d.unit_number) < 1:
                d.unit_number = 1
        db.session.commit()

    def ensure_sqlite_bookings_scene_id_column() -> None:
        if db.engine.dialect.name != "sqlite":
            return
        insp = inspect(db.engine)
        if "bookings" not in insp.get_table_names():
            return
        col_names = {c["name"] for c in insp.get_columns("bookings")}
        if "scene_id" in col_names:
            return
        with db.engine.begin() as conn:
            conn.execute(text("ALTER TABLE bookings ADD COLUMN scene_id INTEGER"))

    def ensure_sqlite_shooting_day_scenes_pipeline_columns() -> None:
        if db.engine.dialect.name != "sqlite":
            return
        insp = inspect(db.engine)
        if "shooting_day_scenes" not in insp.get_table_names():
            return
        col_names = {c["name"] for c in insp.get_columns("shooting_day_scenes")}
        with db.engine.begin() as conn:
            if "episode_number" not in col_names:
                conn.execute(
                    text(
                        "ALTER TABLE shooting_day_scenes "
                        "ADD COLUMN episode_number INTEGER NOT NULL DEFAULT 1"
                    )
                )
            if "scene_number" not in col_names:
                conn.execute(
                    text(
                        "ALTER TABLE shooting_day_scenes "
                        "ADD COLUMN scene_number INTEGER NOT NULL DEFAULT 1"
                    )
                )
            if "duration" not in col_names:
                conn.execute(
                    text(
                        "ALTER TABLE shooting_day_scenes "
                        "ADD COLUMN duration INTEGER NOT NULL DEFAULT 0"
                    )
                )
            if "sync_done" not in col_names:
                conn.execute(
                    text(
                        "ALTER TABLE shooting_day_scenes "
                        "ADD COLUMN sync_done BOOLEAN NOT NULL DEFAULT 0"
                    )
                )
            if "first_edit_done" not in col_names:
                conn.execute(
                    text(
                        "ALTER TABLE shooting_day_scenes "
                        "ADD COLUMN first_edit_done BOOLEAN NOT NULL DEFAULT 0"
                    )
                )
            if "scene_label" not in col_names:
                conn.execute(
                    text(
                        "ALTER TABLE shooting_day_scenes "
                        "ADD COLUMN scene_label VARCHAR(120) NOT NULL DEFAULT ''"
                    )
                )
            if "duration_seconds" not in col_names:
                conn.execute(
                    text(
                        "ALTER TABLE shooting_day_scenes "
                        "ADD COLUMN duration_seconds INTEGER NOT NULL DEFAULT 0"
                    )
                )
            if "needs_vfx" not in col_names:
                conn.execute(
                    text(
                        "ALTER TABLE shooting_day_scenes "
                        "ADD COLUMN needs_vfx BOOLEAN NOT NULL DEFAULT 0"
                    )
                )
        col_after = {c["name"] for c in inspect(db.engine).get_columns("shooting_day_scenes")}
        if "scene_label" in col_after and "scene_number" in col_after:
            with db.engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE shooting_day_scenes SET scene_label = CAST(scene_number AS TEXT) "
                        "WHERE trim(coalesce(scene_label, '')) = ''"
                    )
                )
        if "duration_seconds" in col_after and "duration" in col_after:
            with db.engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE shooting_day_scenes SET duration_seconds = duration * 60 "
                        "WHERE duration_seconds = 0 AND duration > 0"
                    )
                )

    def ensure_sqlite_vfx_editor_tables() -> None:
        """Create editor-mode VFX tables/columns on SQLite when missing."""
        if db.engine.dialect.name != "sqlite":
            return
        insp = inspect(db.engine)
        tables = set(insp.get_table_names())
        with db.engine.begin() as conn:
            if "vfx_shot" not in tables:
                VfxShot.__table__.create(bind=db.engine, checkfirst=True)
            if "vfx_version" not in tables:
                VfxVersion.__table__.create(bind=db.engine, checkfirst=True)
            if "scene_reference" not in tables:
                SceneReference.__table__.create(bind=db.engine, checkfirst=True)
        if "vfx_shot" in inspect(db.engine).get_table_names():
            cols = {c["name"] for c in inspect(db.engine).get_columns("vfx_shot")}
            with db.engine.begin() as conn:
                if "shot_briefing" not in cols:
                    conn.execute(
                        text("ALTER TABLE vfx_shot ADD COLUMN shot_briefing TEXT NOT NULL DEFAULT ''")
                    )
                if "status" not in cols:
                    conn.execute(
                        text("ALTER TABLE vfx_shot ADD COLUMN status VARCHAR(16) NOT NULL DEFAULT 'pending'")
                    )
                if "created_at" not in cols:
                    conn.execute(
                        text("ALTER TABLE vfx_shot ADD COLUMN created_at DATETIME")
                    )
                if "department" not in cols:
                    conn.execute(
                        text(
                            "ALTER TABLE vfx_shot ADD COLUMN department VARCHAR(16) NOT NULL DEFAULT 'animation'"
                        )
                    )
                if "vendor" not in cols:
                    conn.execute(
                        text(
                            "ALTER TABLE vfx_shot ADD COLUMN vendor VARCHAR(24) NOT NULL DEFAULT 'in_house'"
                        )
                    )
                if "vendor_name" not in cols:
                    conn.execute(
                        text("ALTER TABLE vfx_shot ADD COLUMN vendor_name VARCHAR(120) NOT NULL DEFAULT ''")
                    )
                if "shot_ref_frame" not in cols:
                    conn.execute(
                        text("ALTER TABLE vfx_shot ADD COLUMN shot_ref_frame TEXT NOT NULL DEFAULT ''")
                    )
                if "sent_at" not in cols:
                    conn.execute(
                        text("ALTER TABLE vfx_shot ADD COLUMN sent_at DATETIME")
                    )
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_vfx_scene_shot_number "
                        "ON vfx_shot(scene_id, shot_number)"
                    )
                )
                conn.execute(
                    text("CREATE UNIQUE INDEX IF NOT EXISTS uq_vfx_shot_code ON vfx_shot(shot_code)")
                )
        tables_after = set(inspect(db.engine).get_table_names())
        if "vfx_shot_comment" not in tables_after:
            VfxShotComment.__table__.create(bind=db.engine, checkfirst=True)

    def ensure_sqlite_hard_disk_tables() -> None:
        """Create HDD tracking tables on SQLite when missing (additive migration)."""
        if db.engine.dialect.name != "sqlite":
            return
        insp = inspect(db.engine)
        names = set(insp.get_table_names())
        if "hard_disk" not in names:
            HardDisk.__table__.create(bind=db.engine, checkfirst=True)
        if "hard_disk_usage" not in names:
            HardDiskUsage.__table__.create(bind=db.engine, checkfirst=True)

    def ensure_sqlite_music_mount_tables() -> None:
        """Create music_mount and add music_file.mount_id on SQLite when missing."""
        if db.engine.dialect.name != "sqlite":
            return
        insp = inspect(db.engine)
        names = set(insp.get_table_names())
        if "music_mount" not in names:
            MusicMount.__table__.create(bind=db.engine, checkfirst=True)
        if "music_file" not in names:
            return
        cols = {c["name"] for c in insp.get_columns("music_file")}
        if "mount_id" not in cols:
            with db.engine.begin() as conn:
                conn.execute(
                    text(
                        "ALTER TABLE music_file ADD COLUMN mount_id INTEGER "
                        "REFERENCES music_mount(id)"
                    )
                )
        if "is_favorite" not in cols:
            with db.engine.begin() as conn:
                conn.execute(
                    text(
                        "ALTER TABLE music_file ADD COLUMN is_favorite INTEGER NOT NULL DEFAULT 0"
                    )
                )

    def ensure_sqlite_project_audio_library_tables() -> None:
        """Create project audio library tables on SQLite when missing."""
        if db.engine.dialect.name != "sqlite":
            return
        insp = inspect(db.engine)
        names = set(insp.get_table_names())
        if "project_audio_library" not in names:
            ProjectAudioLibrary.__table__.create(bind=db.engine, checkfirst=True)
        if "project_audio_folder" not in names:
            ProjectAudioFolder.__table__.create(bind=db.engine, checkfirst=True)

    def ensure_sqlite_audio_usage_tables() -> None:
        """Create audio_usage table on SQLite when missing."""
        if db.engine.dialect.name != "sqlite":
            return
        insp = inspect(db.engine)
        names = set(insp.get_table_names())
        if "audio_usage" not in names:
            AudioUsage.__table__.create(bind=db.engine, checkfirst=True)

    def ensure_sqlite_notification_tables() -> None:
        """Create Notification table on SQLite when missing (additive migration)."""
        if db.engine.dialect.name != "sqlite":
            return
        insp = inspect(db.engine)
        names = set(insp.get_table_names())
        if "notification" not in names:
            Notification.__table__.create(bind=db.engine, checkfirst=True)
            return
        cols = {c["name"] for c in insp.get_columns("notification")}
        with db.engine.begin() as conn:
            if "rule_key" not in cols:
                conn.execute(text("ALTER TABLE notification ADD COLUMN rule_key VARCHAR(255) NOT NULL DEFAULT ''"))
            if "is_resolved" not in cols:
                conn.execute(text("ALTER TABLE notification ADD COLUMN is_resolved BOOLEAN NOT NULL DEFAULT 0"))
            if "user_id" not in cols:
                conn.execute(
                    text("ALTER TABLE notification ADD COLUMN user_id INTEGER REFERENCES users(id)")
                )
                conn.execute(text("DELETE FROM notification WHERE user_id IS NULL"))

    def ensure_sqlite_notification_legacy_created_at_shift() -> None:
        """One-time correction when legacy rows stored local wall time as naive UTC.

        Set TM_NOTIFICATION_CREATED_AT_SHIFT_HOURS (e.g. 2) once, restart; leaves a marker
        in instance/ so it does not run again. Off by default (no env = no-op).
        """
        raw = (os.environ.get("TM_NOTIFICATION_CREATED_AT_SHIFT_HOURS") or "").strip()
        if not raw:
            return
        try:
            hrs = int(raw)
        except ValueError:
            return
        if hrs == 0 or db.engine.dialect.name != "sqlite":
            return
        mark = os.path.join(app.instance_path, f".done_notification_created_at_shift_{hrs}h")
        if os.path.isfile(mark):
            return
        insp = inspect(db.engine)
        if "notification" not in insp.get_table_names():
            return
        mod_sql = f"{hrs:+d} hours"
        with db.engine.begin() as conn:
            conn.execute(
                text("UPDATE notification SET created_at = datetime(created_at, :mod)"),
                {"mod": mod_sql},
            )
        try:
            with open(mark, "w", encoding="utf-8") as f:
                f.write("ok\n")
        except OSError:
            pass

    def ensure_sqlite_stored_instant_utc_to_cairo_v1() -> None:
        """One-time: naive datetimes were UTC wall clock; shift +2h to Cairo (Egypt, no DST).

        Writes instance/.done_tm_stored_instant_utc_to_cairo_v1 so it runs once per DB file.
        """
        if db.engine.dialect.name != "sqlite":
            return
        mark = os.path.join(app.instance_path, ".done_tm_stored_instant_utc_to_cairo_v1")
        if os.path.isfile(mark):
            return
        insp = inspect(db.engine)
        names = set(insp.get_table_names())
        columns_by_table: list[tuple[str, tuple[str, ...]]] = [
            ("accounts", ("created_at",)),
            ("users", ("created_at",)),
            ("vendors", ("created_at",)),
            ("bookings", ("created_at",)),
            ("task_group_titles", ("created_at",)),
            ("task_priorities", ("created_at",)),
            ("tasks", ("created_at", "completed_at", "copy_started_at")),
            ("projects", ("created_at",)),
            ("chat_messages", ("created_at", "deleted_at")),
            ("notification", ("created_at",)),
            ("hard_disk", ("created_at",)),
        ]
        with db.engine.begin() as conn:
            for table, cols in columns_by_table:
                if table not in names:
                    continue
                existing = {c["name"] for c in insp.get_columns(table)}
                for col in cols:
                    if col not in existing:
                        continue
                    conn.execute(
                        text(
                            f"UPDATE {table} SET {col} = datetime({col}, '+2 hours') "
                            f"WHERE {col} IS NOT NULL"
                        )
                    )
        try:
            with open(mark, "w", encoding="utf-8") as f:
                f.write("ok\n")
        except OSError:
            pass

    with app.app_context():
        db.create_all()
        ensure_sqlite_tasks_group_column()
        ensure_sqlite_tasks_project_column()
        ensure_sqlite_tasks_completed_archived_columns()
        ensure_sqlite_users_account_column()
        ensure_sqlite_users_job_title_column()
        ensure_sqlite_users_profile_columns()
        ensure_sqlite_accounts_username_role_columns()
        ensure_sqlite_projects_sort_order_column()
        ensure_sqlite_projects_episodes_shooting_columns()
        ensure_bootstrap_admin_account()
        ensure_all_accounts_have_directory_users()
        ensure_task_groups_and_editing_tasks()
        ensure_sqlite_chat_messages_audio_path()
        ensure_sqlite_chat_messages_soft_delete_columns()
        ensure_sqlite_tasks_priority_column()
        ensure_sqlite_tasks_copy_material_columns()
        ensure_sqlite_bookings_v2_columns()
        ensure_sqlite_bookings_scene_id_column()
        ensure_sqlite_shooting_days_flat_unit_day_name_columns()
        ensure_sqlite_shooting_day_scenes_pipeline_columns()
        ensure_sqlite_vfx_editor_tables()
        ensure_sqlite_hard_disk_tables()
        ensure_sqlite_music_mount_tables()
        ensure_sqlite_project_audio_library_tables()
        ensure_sqlite_audio_usage_tables()
        ensure_sqlite_notification_tables()
        ensure_sqlite_notification_legacy_created_at_shift()
        ensure_sqlite_stored_instant_utc_to_cairo_v1()

    PUBLIC_ENDPOINTS = frozenset({"login", "register", "logout", "static"})

    def account_is_super_user_effective(acc: Account | None) -> bool:
        """True when account role is super_user or directory job title matches."""
        if acc is None:
            return False
        if _normalized_account_role_key(acc.role) == ROLE_SUPER_USER:
            return True
        du = (
            User.query.options(joinedload(User.job_title))
            .filter_by(account_id=acc.id)
            .first()
        )
        if du is None:
            return False
        jt = du.job_title
        if jt is None:
            return False
        return (jt.name or "").strip() in SUPER_USER_JOB_TITLE_NAMES

    def account_is_elevated(acc: Account | None) -> bool:
        """Administrator or super user (by role or job title)."""
        return acc is not None and (acc.is_admin or account_is_super_user_effective(acc))

    def account_can_create_projects(acc: Account | None) -> bool:
        """Project creation: admin, super user, or producer."""
        if acc is None:
            return False
        return bool(account_is_elevated(acc) or _normalized_account_role_key(acc.role) == ROLE_PRODUCER)

    def account_can_manage_project_team(acc: Account | None) -> bool:
        """Project team membership management: admin, super user, or producer."""
        if acc is None:
            return False
        return bool(account_is_elevated(acc) or _normalized_account_role_key(acc.role) == ROLE_PRODUCER)

    def account_can_manage_music_mounts(acc: Account | None) -> bool:
        """Music mounts management: administrator or super user only."""
        if acc is None:
            return False
        return bool(acc.is_admin or account_is_super_user_effective(acc))

    def account_may_use_machine_project_view(acc: Account | None) -> bool:
        """Machine Room project management access (/machine/project/<id>)."""
        if acc is None:
            return False
        r = _normalized_account_role_key(acc.role)
        return r in (ROLE_ADMIN, ROLE_PRODUCER, ROLE_MACHINE_ROOM)

    def account_can_access_admin_settings(acc: Account | None) -> bool:
        """Users page, Control panel, and related actions — administrator role only (not super user)."""
        return acc is not None and acc.is_admin

    def account_is_machine_room_role(acc: Account | None) -> bool:
        return acc is not None and _normalized_account_role_key(acc.role) == ROLE_MACHINE_ROOM

    def account_from_session() -> Account | None:
        raw = session.get("account_id")
        try:
            pk = int(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None
        return db.session.get(Account, pk) if pk is not None else None

    @app.before_request
    def enforce_logged_in_users_only():
        # Engine.IO / Socket.IO handshake must not be redirected to HTML login.
        if request.path.startswith("/socket.io"):
            return
        if request.endpoint in PUBLIC_ENDPOINTS or request.endpoint is None:
            return
        if not session.get("account_id"):
            flash("Please sign in to continue.", "error")
            return redirect(url_for("login", next=request.path))
        ep = request.endpoint or ""
        raw_aid = session.get("account_id")
        try:
            acc_pk = int(raw_aid) if raw_aid is not None else None
        except (TypeError, ValueError):
            acc_pk = None
        acc = db.session.get(Account, acc_pk) if acc_pk is not None else None
        if acc_pk is None or acc is None:
            session.clear()
            flash("Your session is no longer valid. Please sign in again.", "error")
            return redirect(url_for("login", next=request.path))
        if ep.startswith("control_"):
            if acc is None or not account_can_access_admin_settings(acc):
                flash("Only administrators can access the control panel.", "error")
                return redirect(url_for("index"))
        if ep.startswith("users_"):
            if acc is None or not account_can_access_admin_settings(acc):
                flash("Only administrators can access Users (view, add, edit, or remove).", "error")
                return redirect(url_for("index"))
        if account_is_machine_room_role(acc):
            if request.path.startswith("/projects"):
                flash("You do not have access to the projects area.", "error")
                return redirect(url_for("machine_room"))
            if request.path.startswith("/booking/manage"):
                flash("You do not have access to booking management.", "error")
                return redirect(url_for("machine_room"))
            _tasks_path = request.path.rstrip("/")
            if _tasks_path == "/tasks":
                flash("You do not have access to the tasks list.", "error")
                return redirect(url_for("machine_room_tasks_tab", tab_slug="progress"))

    @app.context_processor
    def inject_globals():
        aid = session.get("account_id")
        try:
            acc_pk = int(aid) if aid is not None else None
        except (TypeError, ValueError):
            acc_pk = None
        acc = db.session.get(Account, acc_pk) if acc_pk is not None else None
        du = User.query.filter_by(account_id=aid).first() if aid else None
        socket_token = ""
        if aid:
            ser = URLSafeTimedSerializer(app.config["SECRET_KEY"], salt=SOCKET_AUTH_SALT)
            socket_token = ser.dumps({"account_id": int(aid)})
        return {
            "current_account": acc,
            "current_account_is_admin": bool(acc and acc.is_admin),
            "current_account_is_machine_room": bool(acc and account_is_machine_room_role(acc)),
            "current_account_is_elevated": bool(acc and account_is_elevated(acc)),
            "current_account_can_create_projects": bool(acc and account_can_create_projects(acc)),
            "current_account_can_manage_project_team": bool(acc and account_can_manage_project_team(acc)),
            "current_account_can_manage_music_mounts": bool(acc and account_can_manage_music_mounts(acc)),
            "current_account_avatar_url": avatar_href_for_user(du) if aid else None,
            "app_name": app.config["APP_NAME"],
            "role_labels": ROLE_LABELS,
            "account_roles": ACCOUNT_ROLES,
            "socket_connect_token": socket_token,
            "directory_chat_user_id": du.id if du else None,
        }

    def directory_user_id_for_account(acc: Account | None) -> int | None:
        if acc is None:
            return None
        u = User.query.filter_by(account_id=acc.id).first()
        return u.id if u else None

    def _notification_visible_filter(*, uid: int | None, visible: set[int] | None):
        """Rows for this viewer: own user_id, or legacy null-user rows on any project they are on.

        Uses EXISTS(ProjectMember) so all team projects are covered even if visible set drifts.
        """
        if uid is None:
            if visible is None:
                # Administrator / Machine Room (broad project access) without a directory user:
                # per-user rows still have user_id set — show all project-scoped notifications.
                return Notification.project_id.isnot(None)
            if visible:
                return and_(
                    Notification.user_id.is_(None),
                    Notification.project_id.in_(list(visible)),
                )
            return None

        on_my_team_projects = exists(
            select(1)
            .select_from(ProjectMember)
            .where(
                ProjectMember.project_id == Notification.project_id,
                ProjectMember.user_id == uid,
            )
            .correlate(Notification)
        )
        mine = Notification.user_id == uid
        legacy_on_my_teams = and_(
            Notification.user_id.is_(None),
            Notification.project_id.isnot(None),
            on_my_team_projects,
        )
        if visible is None:
            admin_legacy = and_(Notification.user_id.is_(None), Notification.project_id.isnot(None))
            return or_(mine, admin_legacy)
        if not visible:
            return mine
        return or_(mine, legacy_on_my_teams)

    def _notification_row_may_mutate(actor: Account, n: Notification) -> bool:
        uid = directory_user_id_for_account(actor)
        if int(n.user_id or 0) and uid is not None and int(n.user_id) == int(uid):
            return True
        if n.user_id is not None:
            if n.project_id is not None and account_is_elevated(actor):
                return account_can_access_project(actor, int(n.project_id))
            return False
        if n.project_id is None:
            return False
        return account_can_access_project(actor, int(n.project_id))

    def visible_project_ids_for_account(acc: Account | None) -> set[int] | None:
        """None = see all projects (administrator or Machine Room role). Else team membership IDs."""
        if acc is None:
            return set()
        if acc.is_admin or _normalized_account_role_key(acc.role) == ROLE_MACHINE_ROOM:
            return None
        uid = directory_user_id_for_account(acc)
        if uid is None:
            return set()
        return {m.project_id for m in ProjectMember.query.filter_by(user_id=uid).all()}

    def account_can_access_project(acc: Account | None, project_id: int) -> bool:
        if acc is None:
            return False
        allowed = visible_project_ids_for_account(acc)
        if allowed is None:
            return True
        return project_id in allowed

    app.extensions["booking"] = {
        "db": db,
        "Account": Account,
        "User": User,
        "Project": Project,
        "ProjectMember": ProjectMember,
        "EditSuite": EditSuite,
        "Booking": Booking,
        "ProductionScene": ProductionScene,
        "ProductionEpisode": ProductionEpisode,
        "ShootingDayScene": ShootingDayScene,
        "ShootingDay": ShootingDay,
        "emit_booking_overlap_alert": emit_booking_overlap_alert,
        "account_from_session": account_from_session,
        "account_can_access_admin_settings": account_can_access_admin_settings,
        "directory_user_id_for_account": directory_user_id_for_account,
        "visible_project_ids_for_account": visible_project_ids_for_account,
        "account_can_access_project": account_can_access_project,
    }
    app.register_blueprint(booking_bp)

    def account_may_use_project_chat(acc: Account | None, project_id: int) -> bool:
        """Only directory users listed on the project team may use chat (same scope as task assignees)."""
        if not account_can_access_project(acc, project_id):
            return False
        uid = directory_user_id_for_account(acc)
        if uid is None:
            return False
        return ProjectMember.query.filter_by(project_id=project_id, user_id=uid).first() is not None

    def ensure_project_chat_read_initialized(acc: Account | None, project_id: int) -> None:
        if acc is None or not account_may_use_project_chat(acc, project_id):
            return
        exists = ProjectChatReadState.query.filter_by(
            account_id=acc.id, project_id=project_id
        ).first()
        if exists is not None:
            return
        mx = (
            db.session.query(db.func.max(ChatMessage.id))
            .filter(ChatMessage.project_id == project_id)
            .scalar()
        )
        mid = int(mx) if mx is not None else 0
        db.session.add(
            ProjectChatReadState(
                account_id=acc.id,
                project_id=project_id,
                last_read_message_id=mid,
            )
        )
        db.session.commit()

    def chat_unread_count_for_account(acc: Account | None, project_id: int) -> int:
        if acc is None or not account_may_use_project_chat(acc, project_id):
            return 0
        ensure_project_chat_read_initialized(acc, project_id)
        state = ProjectChatReadState.query.filter_by(
            account_id=acc.id, project_id=project_id
        ).first()
        last_id = state.last_read_message_id if state else 0
        uid = directory_user_id_for_account(acc)
        q = ChatMessage.query.filter(
            ChatMessage.project_id == project_id,
            ChatMessage.id > last_id,
        )
        if uid is not None:
            q = q.filter(ChatMessage.user_id != uid)
        return q.count()

    def chat_mark_project_read(acc: Account | None, project_id: int) -> None:
        if acc is None or not account_may_use_project_chat(acc, project_id):
            return
        ensure_project_chat_read_initialized(acc, project_id)
        mx = (
            db.session.query(db.func.max(ChatMessage.id))
            .filter(ChatMessage.project_id == project_id)
            .scalar()
        )
        mid = int(mx) if mx is not None else 0
        state = ProjectChatReadState.query.filter_by(
            account_id=acc.id, project_id=project_id
        ).first()
        if state is None:
            return
        if mid > state.last_read_message_id:
            state.last_read_message_id = mid
            db.session.commit()

    def eligible_chat_project_ids(acc: Account | None) -> list[int]:
        """Projects where the account has team chat (directory user on project team)."""
        uid = directory_user_id_for_account(acc)
        if uid is None:
            return []
        return [
            pm.project_id
            for pm in ProjectMember.query.filter_by(user_id=uid)
            .order_by(ProjectMember.project_id.asc())
            .all()
        ]

    def build_chat_threads_for_dashboard(acc: Account | None) -> list[dict]:
        """Metadata for dashboard chat sidebar: one row per eligible project."""
        pids = eligible_chat_project_ids(acc)
        if not pids:
            return []
        projects = Project.query.filter(Project.id.in_(pids)).all()
        pmap = {p.id: p for p in projects}
        agg_rows = (
            db.session.query(
                ChatMessage.project_id.label("pid"),
                db.func.max(ChatMessage.id).label("mid"),
            )
            .filter(ChatMessage.project_id.in_(pids))
            .group_by(ChatMessage.project_id)
            .all()
        )
        mid_by_pid = {r.pid: int(r.mid) for r in agg_rows}
        last_msg_by_pid: dict[int, ChatMessage] = {}
        if mid_by_pid:
            lids = list(mid_by_pid.values())
            for m in ChatMessage.query.filter(ChatMessage.id.in_(lids)).all():
                last_msg_by_pid[m.project_id] = m
        enriched: list[tuple[float, dict]] = []
        for pid in pids:
            p = pmap.get(pid)
            if p is None:
                continue
            m = last_msg_by_pid.get(pid)
            preview = "No messages yet"
            last_at_iso: str | None = None
            last_sort = 0.0
            if m is not None:
                last_at_iso = isoformat_stored_instant(m.created_at) if m.created_at else None
                if m.created_at:
                    last_sort = _epoch_ms_from_stored_naive(m.created_at)
                txt = (m.message or "").strip()
                if txt:
                    preview = (txt[:100] + "…") if len(txt) > 100 else txt
                elif m.image_path:
                    preview = "Photo"
                elif m.audio_path:
                    preview = "Voice message"
            unread = chat_unread_count_for_account(acc, pid)
            enriched.append(
                (
                    last_sort,
                    {
                        "project_id": pid,
                        "name": (p.name or "").strip() or "Project",
                        "last_preview": preview,
                        "last_at": last_at_iso,
                        "unread": unread,
                        "messages_url": url_for("project_chat_messages", project_id=pid),
                        "unread_url": url_for("project_chat_unread_count", project_id=pid),
                        "mark_read_url": url_for("project_chat_mark_read", project_id=pid),
                        "detail_url": url_for("project_detail", project_id=pid),
                    },
                )
            )
        enriched.sort(key=lambda t: (-t[0], t[1]["name"].lower()))
        return [t[1] for t in enriched]

    def find_project_mentions_for_text(project_id: int, text: str | None) -> list[User]:
        """Resolve @DisplayName tokens against project members (longest name first)."""
        if not text:
            return []
        members = (
            User.query.join(ProjectMember, ProjectMember.user_id == User.id)
            .filter(ProjectMember.project_id == project_id)
            .all()
        )
        named: list[tuple[User, str]] = []
        for u in members:
            name = (u.name or "").strip()
            if name:
                named.append((u, name))
        named.sort(key=lambda t: len(t[1]), reverse=True)
        found: dict[int, User] = {}
        pos = 0
        n = len(text)
        while pos < n:
            at = text.find("@", pos)
            if at < 0:
                break
            rest = text[at + 1 :]
            hit: User | None = None
            hit_len = 0
            for u, name in named:
                if rest.startswith(name):
                    boundary = rest[len(name) : len(name) + 1]
                    if boundary and boundary[0].isalnum():
                        continue
                    hit = u
                    hit_len = len(name)
                    break
            if hit is not None:
                found[hit.id] = hit
                pos = at + 1 + hit_len
            else:
                pos = at + 1
        return list(found.values())

    def summarize_chat_reactions(
        reaction_rows: Sequence[ChatMessageReaction],
        viewer_dir_user_id: int | None,
    ) -> list[dict]:
        counts: dict[str, int] = defaultdict(int)
        viewer_emoji: str | None = None
        for r in reaction_rows:
            counts[r.emoji] += 1
            if viewer_dir_user_id is not None and r.user_id == viewer_dir_user_id:
                viewer_emoji = r.emoji
        out: list[dict] = []
        seen: set[str] = set()
        for em in CHAT_REACTION_EMOJIS:
            if em in counts:
                out.append(
                    {
                        "emoji": em,
                        "count": counts[em],
                        "me": viewer_emoji == em,
                    }
                )
                seen.add(em)
        for em in sorted(counts.keys()):
            if em not in seen:
                out.append(
                    {
                        "emoji": em,
                        "count": counts[em],
                        "me": viewer_emoji == em,
                    }
                )
        return out

    def chat_message_json(
        m: ChatMessage,
        viewer_dir_user_id: int | None,
        *,
        reactions: Sequence[ChatMessageReaction] | None = None,
    ) -> dict:
        u = m.user
        username = u.name if u is not None else "Unknown"
        avatar_initial = "?"
        for ch in username.strip():
            if ch.isalnum():
                avatar_initial = ch.upper()
                break
        base_me = viewer_dir_user_id is not None and m.user_id == viewer_dir_user_id
        created_iso = isoformat_stored_instant(m.created_at)
        if m.is_deleted:
            return {
                "id": m.id,
                "username": username,
                "message": "",
                "image_url": None,
                "audio_url": None,
                "avatar_initial": avatar_initial,
                "created_at": created_iso,
                "is_me": base_me,
                "is_deleted": True,
                "reactions": [],
            }
        image_url = None
        if (m.image_path or "").strip():
            image_url = url_for(
                "project_chat_attachment",
                project_id=m.project_id,
                filename=m.image_path.strip(),
            )
        audio_url = None
        if (m.audio_path or "").strip():
            audio_url = url_for(
                "project_chat_attachment",
                project_id=m.project_id,
                filename=m.audio_path.strip(),
            )
        react_seq = reactions if reactions is not None else []
        return {
            "id": m.id,
            "username": username,
            "message": (m.message or "").strip(),
            "image_url": image_url,
            "audio_url": audio_url,
            "avatar_initial": avatar_initial,
            "created_at": created_iso,
            "is_me": base_me,
            "is_deleted": False,
            "reactions": summarize_chat_reactions(react_seq, viewer_dir_user_id),
        }

    def emit_notification_to_account(account_id: int, payload: dict, event: str = "notification") -> None:
        """Push a Socket.IO event to every connection for this login account (room user_<id>)."""
        socketio.emit(event, payload, room=f"user_{account_id}")

    def emit_tasks_feed_changed(*project_ids: int | None) -> None:
        """Notify browsers to refresh task HTML fragments (room joined by every authenticated socket)."""
        ids: set[int] = set()
        for x in project_ids:
            if x is None:
                continue
            try:
                ids.add(int(x))
            except (TypeError, ValueError):
                continue
        try:
            socketio.emit(
                "tasks_changed",
                {"project_ids": sorted(ids)},
                room="tasks_feed",
            )
        except Exception:
            app.logger.exception("tasks_changed emit failed")

    def task_visible_to_account(t: Task, acc: Account | None) -> bool:
        if acc is None:
            return False
        if acc.is_admin:
            return True
        allowed = visible_project_ids_for_account(acc)
        if t.project_id is None:
            return False
        return bool(allowed and t.project_id in allowed)

    def di_machine_task_group_id() -> int | None:
        return db.session.query(TaskGroup.id).filter(TaskGroup.name == "DI / Machine").scalar()

    def fetch_dashboard_machine_room_tasks(acc: Account | None) -> list[Task]:
        """Timed copy/convert stream rows for the Machine Room dashboard panel."""
        if acc is None or not account_is_machine_room_role(acc):
            return []
        dm_gid = di_machine_task_group_id()
        if dm_gid is None:
            return []
        return (
            Task.query.options(
                joinedload(Task.group),
                joinedload(Task.assignee),
                joinedload(Task.project),
            )
            .filter(
                Task.group_id == int(dm_gid),
                Task.archived.is_(False),
                Task.status.in_(("open", "in_progress")),
                Task.title.in_(MR_TIMED_STREAM_TITLES),
                Task.copy_estimated_minutes.isnot(None),
            )
            .order_by(Task.created_at.desc())
            .all()
        )

    MR_MACHINE_ROOM_TASKS_PER_PAGE = 10

    def mr_operator_user_ids(acc: Account | None) -> list[int]:
        """Directory user ids whose linked account has the Machine Room role."""
        if acc is None or not account_is_machine_room_role(acc):
            return []
        linked_users = (
            User.query.options(joinedload(User.account))
            .filter(User.account_id.isnot(None))
            .all()
        )
        return [
            u.id
            for u in linked_users
            if u.account is not None and account_is_machine_room_role(u.account)
        ]

    def fetch_mr_operator_assigned_tasks(acc: Account | None) -> list[Task]:
        """All non-archived tasks assigned to any directory user with the Machine Room role."""
        mr_user_ids = mr_operator_user_ids(acc)
        if not mr_user_ids:
            return []
        return (
            Task.query.options(
                joinedload(Task.assignee), joinedload(Task.project), joinedload(Task.group)
            )
            .filter(Task.user_id.in_(mr_user_ids), Task.archived.is_(False))
            .order_by(Task.created_at.desc())
            .all()
        )

    def _mr_machine_room_tasks_tab_from_request(fragment_tab_slug: str | None = None) -> str:
        """Tab from URL path (/machine-room/tasks/<slug>), fragment path, or legacy ?tab=."""
        if fragment_tab_slug in ("progress", "finished"):
            return fragment_tab_slug
        tv = request.view_args or {}
        slug = (tv.get("tab_slug") or "").strip().lower()
        if slug in ("progress", "finished"):
            return slug
        t = (request.args.get("tab") or "progress").strip().lower()
        if t in ("progress", "finished"):
            return t
        return "progress"

    def _mr_machine_room_tasks_parse_request(fragment_tab_slug: str | None = None) -> dict:
        """Query args for MR tasks lists; tab comes from path when present."""
        q = (request.args.get("q") or "").strip()
        project_id = request.args.get("project_id", type=int)
        user_id = request.args.get("user_id", type=int)
        status = (request.args.get("status") or "").strip().lower()
        if status not in ("", "open", "in_progress"):
            status = ""
        sort = (request.args.get("sort") or "").strip().lower()
        if sort not in ("newest", "priority"):
            sort = "newest"
        tab = _mr_machine_room_tasks_tab_from_request(fragment_tab_slug)
        if tab == "finished":
            status = ""
        elif status == "done":
            status = ""
        pg = request.args.get("pg", type=int) or 1
        pf = request.args.get("pf", type=int) or 1
        pg = max(1, int(pg))
        pf = max(1, int(pf))
        return {
            "q": q,
            "project_id": project_id,
            "user_id": user_id,
            "status": status,
            "sort": sort,
            "tab": tab,
            "pg": pg,
            "pf": pf,
        }

    def _mr_machine_room_tasks_base_query(mr_user_ids: list[int], tab: str, filt: dict):
        """Filtered query for one tab (progress = open/in_progress, finished = done)."""
        qy = Task.query.options(
            joinedload(Task.assignee), joinedload(Task.project), joinedload(Task.group)
        ).filter(Task.user_id.in_(mr_user_ids), Task.archived.is_(False))
        if tab == "finished":
            qy = qy.filter(Task.status == "done")
        else:
            qy = qy.filter(Task.status.in_(("open", "in_progress")))
            if filt["status"] in ("open", "in_progress"):
                qy = qy.filter(Task.status == filt["status"])
        pid = filt.get("project_id")
        if pid is not None and int(pid) > 0:
            qy = qy.filter(Task.project_id == int(pid))
        uid = filt.get("user_id")
        if uid is not None and int(uid) > 0:
            qy = qy.filter(Task.user_id == int(uid))
        raw_q = (filt.get("q") or "").strip()
        if raw_q:
            like = f"%{raw_q}%"
            parts = [
                Task.title.ilike(like),
                Task.description.ilike(like),
                Task.copy_day_name.ilike(like),
            ]
            if raw_q.isdigit():
                try:
                    parts.append(Task.copy_unit_number == int(raw_q))
                except (TypeError, ValueError):
                    pass
            qy = qy.filter(or_(*parts))
        sort = filt.get("sort") or "newest"
        if sort == "priority":
            pr_rank = case(
                (Task.priority == "high", 3),
                (Task.priority == "medium", 2),
                else_=1,
            )
            qy = qy.order_by(pr_rank.desc(), Task.created_at.desc(), Task.id.desc())
        else:
            qy = qy.order_by(Task.created_at.desc(), Task.id.desc())
        return qy

    def _mr_machine_room_tasks_filter_choices(mr_user_ids: list[int]) -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
        """Distinct (id, label) for project and assignee filters."""
        rows = (
            db.session.query(Task.project_id, Task.user_id)
            .filter(Task.user_id.in_(mr_user_ids), Task.archived.is_(False))
            .distinct()
            .all()
        )
        pids = sorted({int(r[0]) for r in rows if r[0] is not None})
        uids = sorted({int(r[1]) for r in rows if r[1] is not None})
        projects: list[tuple[int, str]] = []
        if pids:
            for p in Project.query.filter(Project.id.in_(pids)).order_by(Project.name.asc()).all():
                projects.append((int(p.id), (p.name or "").strip() or f"Project {p.id}"))
        users: list[tuple[int, str]] = []
        if uids:
            for u in User.query.filter(User.id.in_(uids)).order_by(User.name.asc()).all():
                users.append((int(u.id), (u.name or u.email or "").strip() or f"User {u.id}"))
        return projects, users

    def _mr_machine_room_tasks_query_params(merged: dict) -> dict:
        """GET query only (tab is in the path); omit default pg=1 and pf=1."""
        out: dict = {}
        if merged.get("q"):
            out["q"] = merged["q"]
        if merged.get("project_id"):
            out["project_id"] = int(merged["project_id"])
        if merged.get("user_id"):
            out["user_id"] = int(merged["user_id"])
        if merged.get("status"):
            out["status"] = merged["status"]
        if merged.get("sort") and merged["sort"] != "newest":
            out["sort"] = merged["sort"]
        if int(merged.get("pg") or 1) > 1:
            out["pg"] = int(merged["pg"])
        if int(merged.get("pf") or 1) > 1:
            out["pf"] = int(merged["pf"])
        return out

    def machine_room_tasks_page_bundle(
        actor: Account | None, *, fragment_tab_slug: str | None = None
    ) -> dict | None:
        """Template context for /machine-room/tasks/<tab>; None if not MR or not logged in."""
        if actor is None or not account_is_machine_room_role(actor):
            return None
        mr_user_ids = mr_operator_user_ids(actor)
        filt = _mr_machine_room_tasks_parse_request(fragment_tab_slug)
        per = MR_MACHINE_ROOM_TASKS_PER_PAGE
        if not mr_user_ids:
            return {
                "mr_operator_ids_empty": True,
                "mr_user_ids": [],
                "filt": filt,
                "mr_per_page": per,
                "mr_url": lambda **overrides: url_for("machine_room_tasks_tab", tab_slug="progress"),
                "mr_status_next_url": url_for("machine_room_tasks_tab", tab_slug="progress"),
                "project_choices": [],
                "user_choices": [],
            }

        q_progress = _mr_machine_room_tasks_base_query(mr_user_ids, "progress", filt)
        q_finished = _mr_machine_room_tasks_base_query(mr_user_ids, "finished", filt)
        total_progress = q_progress.count()
        total_finished = q_finished.count()
        pc_progress = max(1, (total_progress + per - 1) // per)
        pc_finished = max(1, (total_finished + per - 1) // per)
        pg = min(filt["pg"], pc_progress)
        pf = min(filt["pf"], pc_finished)
        filt = {**filt, "pg": pg, "pf": pf}

        progress_tasks = (
            q_progress.offset((pg - 1) * per).limit(per).all()
        )
        finished_tasks = (
            q_finished.offset((pf - 1) * per).limit(per).all()
        )
        project_choices, user_choices = _mr_machine_room_tasks_filter_choices(mr_user_ids)

        def mr_url(**overrides) -> str:
            m = {**filt, **overrides}
            return url_for(
                "machine_room_tasks_tab",
                tab_slug=m["tab"],
                **_mr_machine_room_tasks_query_params(m),
            )

        return {
            "mr_operator_ids_empty": False,
            "mr_user_ids": mr_user_ids,
            "filt": filt,
            "mr_per_page": per,
            "total_progress": total_progress,
            "total_finished": total_finished,
            "progress_page": pg,
            "finished_page": pf,
            "progress_page_count": pc_progress,
            "finished_page_count": pc_finished,
            "progress_tasks": progress_tasks,
            "finished_tasks": finished_tasks,
            "project_choices": project_choices,
            "user_choices": user_choices,
            "mr_url": mr_url,
            "mr_status_next_url": mr_url(),
        }

    def all_tasks_for_tasks_list_page(acc: Account | None) -> list[Task]:
        """Same visible task set as the /tasks page (non-archived, permission-scoped)."""
        vis = visible_project_ids_for_account(acc)
        uid = directory_user_id_for_account(acc)
        if vis is None:
            q = Task.query.filter(Task.archived.is_(False))
        elif not vis:
            if uid is None:
                q = Task.query.filter(text("1=0"))
            else:
                q = Task.query.filter(Task.user_id == uid, Task.archived.is_(False))
        elif uid is not None:
            q = Task.query.filter(
                or_(Task.project_id.in_(vis), Task.user_id == uid),
                Task.archived.is_(False),
            )
        else:
            q = Task.query.filter(Task.project_id.in_(vis), Task.archived.is_(False))
        return (
            q.options(joinedload(Task.assignee), joinedload(Task.project))
            .order_by(Task.created_at.desc())
            .all()
        )

    def task_is_machine_room_stream_task(t: Task) -> bool:
        """Live timed rows (Copy Material / Convert) on the Machine Room overview stream."""
        gid = di_machine_task_group_id()
        if gid is None or int(t.group_id or 0) != int(gid):
            return False
        if (t.title or "").strip() not in MR_TIMED_STREAM_TITLES:
            return False
        if t.copy_estimated_minutes is None:
            return False
        if bool(t.archived):
            return False
        if (t.status or "").strip().lower() not in ("open", "in_progress"):
            return False
        return True

    def account_may_machine_room_operate_stream_task(t: Task, acc: Account | None) -> bool:
        return (
            acc is not None
            and account_is_machine_room_role(acc)
            and task_is_machine_room_stream_task(t)
        )

    def account_may_update_task_status(t: Task, acc: Account | None) -> bool:
        """Only the logged-in account's directory user, when they are the task assignee, may set status."""
        if acc is None:
            return False
        uid = directory_user_id_for_account(acc)
        return uid is not None and t.user_id == uid

    def account_may_archive_task(t: Task, acc: Account | None) -> bool:
        """Assignee or elevated users may archive/unarchive tasks they can see."""
        if acc is None or not task_visible_to_account(t, acc):
            return False
        if account_is_elevated(acc):
            return True
        return account_may_update_task_status(t, acc)

    @app.template_global()
    def can_update_task_status(task: Task) -> bool:
        acc = db.session.get(Account, session.get("account_id"))
        return account_may_update_task_status(task, acc)

    @app.template_global()
    def can_archive_task(task: Task) -> bool:
        acc = db.session.get(Account, session.get("account_id"))
        return account_may_archive_task(task, acc)

    @app.template_global()
    def can_delete_task(task: Task) -> bool:
        acc = db.session.get(Account, session.get("account_id"))
        return task_visible_to_account(task, acc)

    @app.template_global()
    def can_machine_room_operate_stream_task(task: Task) -> bool:
        acc = db.session.get(Account, session.get("account_id"))
        return account_may_machine_room_operate_stream_task(task, acc)

    @app.template_filter("fmt_duration_mmss")
    def fmt_duration_mmss_filter(seconds: int | None) -> str:
        return format_duration_mmss(int(seconds or 0))

    @app.template_filter("fmt_duration_total")
    def fmt_duration_total_filter(seconds: int | None) -> str:
        return format_duration_day_total(int(seconds or 0))

    @app.template_filter("shooting_row_duration_sec")
    def shooting_row_duration_sec_filter(link: ShootingDayScene | None) -> int:
        if link is None:
            return 0
        return shooting_day_scene_duration_seconds(link)

    @app.template_filter("fmt_cairo")
    def fmt_cairo_filter(dt: date | datetime | None, fmt: str = "%Y-%m-%d %H:%M") -> str:
        return format_datetime_cairo(dt, fmt)

    @app.template_filter("fmt_cairo_date")
    def fmt_cairo_date_filter(dt: date | datetime | None) -> str:
        return format_datetime_cairo(dt, "%Y-%m-%d")

    @app.template_filter("epoch_ms_stored")
    def epoch_ms_stored_filter(dt: date | datetime | None) -> int:
        """Milliseconds since Unix epoch for a naive Cairo-stored datetime (sorting / client)."""
        if dt is None or not isinstance(dt, datetime):
            return 0
        return int(_epoch_ms_from_stored_naive(dt))

    def _production_redirect(project_id: int) -> Response:
        return redirect(url_for("project_production", project_id=project_id))

    def shooting_day_in_project(day_id: int, project_id: int) -> ShootingDay | None:
        d = db.session.get(ShootingDay, day_id)
        if d is None or d.project_id != project_id:
            return None
        return d

    def scene_row_in_project(row_id: int, project_id: int) -> SceneRow | None:
        r = db.session.get(SceneRow, row_id)
        if r is None:
            return None
        d = r.shooting_day
        if d is None or d.project_id != project_id:
            return None
        return r

    def shooting_day_scene_for_project(link_id: int, project_id: int) -> ShootingDayScene | None:
        link = (
            ShootingDayScene.query.options(joinedload(ShootingDayScene.shooting_day))
            .filter_by(id=link_id)
            .first()
        )
        if link is None or link.shooting_day is None or link.shooting_day.project_id != project_id:
            return None
        return link

    def next_legacy_scene_id_for_day(day_id: int) -> int:
        """Compatibility allocator for legacy UNIQUE(shooting_day_id, scene_id)."""
        mx = (
            db.session.query(db.func.max(ShootingDayScene.scene_id))
            .filter(ShootingDayScene.shooting_day_id == day_id)
            .scalar()
        )
        try:
            return max(1, int(mx or 0) + 1)
        except (TypeError, ValueError):
            return 1

    @app.route("/projects/<int:project_id>/shooting-days", methods=["POST"])
    def shooting_day_create(project_id: int):
        acc = db.session.get(Account, session.get("account_id"))
        p = Project.query.get_or_404(project_id)
        if not account_can_access_project(acc, p.id):
            flash("You do not have access to that project.", "error")
            return redirect(url_for("projects_list"))

        raw_unit = (request.form.get("unit_number") or "").strip()
        try:
            unit_number = int(raw_unit)
        except ValueError:
            flash("Select a valid unit number.", "error")
            return _production_redirect(project_id)
        if unit_number < 1:
            flash("Unit number must be at least 1.", "error")
            return _production_redirect(project_id)

        day_name = (request.form.get("day_name") or "").strip()
        if not day_name:
            flash("Enter a day name.", "error")
            return _production_redirect(project_id)
        if len(day_name) > 50:
            flash("Day name must be 50 characters or fewer.", "error")
            return _production_redirect(project_id)

        raw_date = (request.form.get("shooting_date") or "").strip()
        try:
            sd = datetime.strptime(raw_date, "%Y-%m-%d").date()
        except ValueError:
            flash("Use a valid shooting date.", "error")
            return _production_redirect(project_id)

        day = ShootingDay(
            project_id=p.id,
            unit_number=unit_number,
            day_name=day_name,
            shooting_date=sd,
        )
        db.session.add(day)
        db.session.flush()
        emit_shooting_day_created_activity(day, "production")
        db.session.commit()
        flash("Shooting day added.", "success")
        return redirect(
            url_for("project_production_day", project_id=project_id, day_id=day.id, new=1)
        )

    @app.route("/projects/<int:project_id>/production/days/<int:day_id>/delete", methods=["POST"])
    def production_day_delete(project_id: int, day_id: int):
        acc = db.session.get(Account, session.get("account_id"))
        d = shooting_day_in_project(day_id, project_id)
        if d is None:
            abort(404)
        if not account_can_access_project(acc, project_id):
            flash("You cannot delete this day.", "error")
            return redirect(url_for("projects_list"))
        db.session.delete(d)
        db.session.commit()
        flash("Shooting day removed.", "success")
        return _production_redirect(project_id)

    @app.route("/projects/<int:project_id>/production/day/<int:day_id>/rows", methods=["POST"])
    def production_scene_row_create(project_id: int, day_id: int):
        acc = db.session.get(Account, session.get("account_id"))
        if not account_can_access_project(acc, project_id):
            return jsonify({"error": "forbidden"}), 403
        d = shooting_day_in_project(day_id, project_id)
        if d is None:
            return jsonify({"error": "not_found"}), 404
        mx = (
            db.session.query(db.func.max(SceneRow.sort_order))
            .filter_by(shooting_day_id=d.id)
            .scalar()
        )
        nxt = (int(mx) if mx is not None else -1) + 1
        row = SceneRow(shooting_day_id=d.id, sort_order=nxt)
        db.session.add(row)
        db.session.commit()
        db.session.refresh(d)
        return jsonify(
            {"row": scene_row_to_dict(row), "total_seconds": shooting_day_total_seconds(d)}
        )

    @app.route(
        "/projects/<int:project_id>/production/scene-rows/<int:row_id>",
        methods=["PATCH", "DELETE"],
    )
    def production_scene_row_mutate(project_id: int, row_id: int):
        acc = db.session.get(Account, session.get("account_id"))
        if not account_can_access_project(acc, project_id):
            return jsonify({"error": "forbidden"}), 403
        r = scene_row_in_project(row_id, project_id)
        if r is None:
            return jsonify({"error": "not_found"}), 404
        if request.method == "DELETE":
            day_pk = r.shooting_day_id
            db.session.delete(r)
            db.session.commit()
            d = db.session.get(ShootingDay, day_pk)
            return jsonify(
                {
                    "ok": True,
                    "total_seconds": shooting_day_total_seconds(d) if d is not None else 0,
                }
            )
        if not request.is_json:
            return jsonify({"error": "json"}), 400
        body = request.get_json(silent=True) or {}
        if "episode" in body:
            r.episode = str(body.get("episode") or "")[:120]
        if "scene" in body:
            r.scene = str(body.get("scene") or "")[:120]
        if "sync" in body:
            r.sync = bool(body.get("sync"))
        if "first_edit" in body:
            r.first_edit = bool(body.get("first_edit"))
        if "final_edit" in body:
            r.final_edit = bool(body.get("final_edit"))
        if "duration_seconds" in body:
            try:
                r.duration_seconds = max(0, int(body.get("duration_seconds")))
            except (TypeError, ValueError):
                pass
        if "duration" in body:
            ds = parse_duration_input(str(body.get("duration")))
            if ds is not None:
                r.duration_seconds = ds
        if "notes" in body:
            r.notes = str(body.get("notes") or "")[:8000]
        db.session.commit()
        d = r.shooting_day
        return jsonify(
            {"row": scene_row_to_dict(r), "total_seconds": shooting_day_total_seconds(d)}
        )

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if session.get("account_id"):
            return redirect(_safe_next_url(request.args.get("next")))

        if request.method == "POST":
            login_id = (request.form.get("login") or request.form.get("email") or "").strip()
            password = request.form.get("password") or ""
            next_url = _safe_next_url(request.form.get("next") or request.args.get("next"))

            if not login_id or not password:
                flash("Email or username and password are required.", "error")
                return render_template("login.html", next_url=next_url)

            login_lower = login_id.lower()
            if "@" in login_id:
                acc = Account.query.filter_by(email=login_lower).first()
            else:
                acc = Account.query.filter(
                    db.func.lower(Account.username) == login_lower,
                ).first()
            if acc is None or not check_password_hash(acc.password_hash, password):
                flash("Invalid sign-in or password.", "error")
                return render_template("login.html", next_url=next_url)

            session.clear()
            session["account_id"] = acc.id
            flash("Signed in.", "success")
            return redirect(next_url)

        return render_template("login.html", next_url=_safe_next_url(request.args.get("next")))

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if session.get("account_id"):
            return redirect(url_for("index"))

        if request.method == "POST":
            name = (request.form.get("name") or "").strip()
            email = (request.form.get("email") or "").strip().lower()
            password = request.form.get("password") or ""
            confirm = request.form.get("confirm") or ""

            if not email or not password:
                flash("Email and password are required.", "error")
                return render_template("register.html")

            if not name:
                flash("Name is required.", "error")
                return render_template("register.html")

            if len(password) < MIN_PASSWORD_LENGTH:
                flash(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.", "error")
                return render_template("register.html")

            if password != confirm:
                flash("Passwords do not match.", "error")
                return render_template("register.html")

            acc = Account(
                email=email,
                password_hash=generate_password_hash(password, method="pbkdf2:sha256"),
                role=ROLE_USER,
            )
            db.session.add(acc)
            try:
                db.session.commit()
            except sa_exc.IntegrityError:
                db.session.rollback()
                flash("An account with that email already exists.", "error")
                return render_template("register.html")

            try:
                link_account_to_directory_user(acc, display_name=name)
                db.session.commit()
            except sa_exc.IntegrityError:
                db.session.rollback()
                stale = db.session.get(Account, acc.id)
                if stale is not None:
                    db.session.delete(stale)
                    db.session.commit()
                flash("Could not create directory profile for that email.", "error")
                return render_template("register.html")

            session.clear()
            session["account_id"] = acc.id
            flash("Account created. You are signed in.", "success")
            return redirect(url_for("index"))

        return render_template("register.html")

    @app.route("/logout", methods=["POST"])
    def logout():
        session.clear()
        flash("Signed out.", "success")
        return redirect(url_for("login"))

    @app.route("/profile", methods=["GET", "POST"])
    def profile():
        aid = session.get("account_id")
        if not aid:
            flash("Please sign in to continue.", "error")
            return redirect(url_for("login"))
        acc = db.session.get(Account, aid)
        if acc is None:
            session.clear()
            flash("Please sign in to continue.", "error")
            return redirect(url_for("login"))
        du = User.query.filter_by(account_id=acc.id).first()

        if request.method == "POST":
            action = (request.form.get("action") or "profile").strip().lower()
            if action == "password":
                current_pw = request.form.get("current_password") or ""
                new_pw = request.form.get("new_password") or ""
                confirm_pw = request.form.get("confirm_password") or ""
                if not current_pw or not new_pw:
                    flash("Current password and new password are required.", "error")
                    return redirect(url_for("profile"))
                if len(new_pw) < MIN_PASSWORD_LENGTH:
                    flash(f"New password must be at least {MIN_PASSWORD_LENGTH} characters.", "error")
                    return redirect(url_for("profile"))
                if new_pw != confirm_pw:
                    flash("New passwords do not match.", "error")
                    return redirect(url_for("profile"))
                if not check_password_hash(acc.password_hash, current_pw):
                    flash("Current password is incorrect.", "error")
                    return redirect(url_for("profile"))
                acc.password_hash = generate_password_hash(new_pw, method="pbkdf2:sha256")
                db.session.commit()
                flash("Password updated.", "success")
                return redirect(url_for("profile"))

            if action == "avatar_upload":
                if du is None:
                    flash("Could not load your directory profile.", "error")
                    return redirect(url_for("profile"))
                upload_part = request.files.get("avatar_file")
                if (
                    not upload_part
                    or not upload_part.filename
                    or not str(upload_part.filename).strip()
                ):
                    flash("Choose an image to upload.", "error")
                    return redirect(url_for("profile"))
                orig = secure_filename(upload_part.filename) or "photo"
                ext = os.path.splitext(orig)[1].lower()
                if ext not in AVATAR_ALLOWED_EXT:
                    flash("Use PNG, JPG, GIF, or WebP for your photo.", "error")
                    return redirect(url_for("profile"))
                raw = upload_part.read()
                if len(raw) > AVATAR_UPLOAD_MAX_BYTES:
                    flash("Profile image is too large (max 2 MB).", "error")
                    return redirect(url_for("profile"))
                remove_profile_avatar_file(du.avatar_upload)
                new_upload_base = f"u{du.id}-{uuid.uuid4().hex}{ext}"
                dest = os.path.join(upload_root, new_upload_base)
                try:
                    with open(dest, "wb") as out:
                        out.write(raw)
                except OSError:
                    flash("Could not save your photo.", "error")
                    return redirect(url_for("profile"))
                du.avatar_kind = "upload"
                du.avatar_upload = new_upload_base
                try:
                    db.session.commit()
                    flash("Photo updated.", "success")
                except Exception:
                    db.session.rollback()
                    remove_profile_avatar_file(new_upload_base)
                    flash("Could not save your photo.", "error")
                return redirect(url_for("profile"))

            name = (request.form.get("name") or "").strip()
            email = (request.form.get("email") or "").strip().lower()
            if not name or not email:
                flash("Full name and email are required.", "error")
                return redirect(url_for("profile"))
            if du is None:
                link_account_to_directory_user(acc, display_name=name)
                db.session.commit()
                du = User.query.filter_by(account_id=acc.id).first()
            if du is None:
                flash("Could not load your directory profile.", "error")
                return redirect(url_for("profile"))
            if acc.email != email:
                taken = (
                    Account.query.filter(Account.email == email, Account.id != acc.id).first()
                    or User.query.filter(User.email == email, User.id != du.id).first()
                )
                if taken:
                    flash("That email is already in use.", "error")
                    return redirect(url_for("profile"))

            du.name = name
            phone_raw = (request.form.get("phone") or "").strip()[:40]
            du.phone = phone_raw or None

            jt_raw = request.form.get("job_title_id")
            if jt_raw is None or (isinstance(jt_raw, str) and not jt_raw.strip()):
                du.job_title_id = None
            else:
                try:
                    jtid = int(jt_raw)
                except (TypeError, ValueError):
                    jtid = 0
                if jtid and JobTitle.query.get(jtid) is not None:
                    du.job_title_id = jtid
                else:
                    du.job_title_id = None

            acc.email = email
            du.email = email
            try:
                db.session.commit()
                flash("Profile updated.", "success")
            except sa_exc.IntegrityError:
                db.session.rollback()
                flash("Could not save profile (email may be taken).", "error")
            return redirect(url_for("profile"))

        job_titles = JobTitle.query.order_by(JobTitle.name).all()

        return render_template(
            "profile.html",
            account=acc,
            directory_user=du,
            job_titles=job_titles,
        )

    @app.route("/profile/avatar-file/<path:filename>")
    def profile_avatar_file(filename: str):
        if not session.get("account_id"):
            abort(404)
        if "/" in filename or "\\" in filename or ".." in filename or filename.startswith("."):
            abort(404)
        u = User.query.filter_by(account_id=session["account_id"]).first()
        if u is None or (u.avatar_kind or "").lower() != "upload":
            abort(404)
        if (u.avatar_upload or "") != filename:
            abort(404)
        return send_from_directory(upload_root, filename)

    _music_supported_ext = (".wav", ".mp3", ".mp4")
    _music_tag_palette = ("red", "orange", "yellow", "green", "blue", "purple")

    def _music_parse_color_tags(raw: str | None) -> list[str]:
        if not raw:
            return []
        parts = [p.strip().lower() for p in str(raw).split(",")]
        out: list[str] = []
        for p in parts:
            if p in _music_tag_palette and p not in out:
                out.append(p)
        return out

    def _music_color_tags_to_db(tags: list[str]) -> str | None:
        clean: list[str] = []
        for t in tags:
            v = (t or "").strip().lower()
            if v in _music_tag_palette and v not in clean:
                clean.append(v)
        return ",".join(clean) if clean else None

    def _music_mount_base_real(mount: MusicMount) -> str:
        return os.path.realpath(os.path.abspath(mount.base_path))

    def _music_file_under_mount(file_path: str, mount: MusicMount) -> str | None:
        """Resolved file path if it exists as a file and stays under mount.base_path."""
        try:
            real_f = os.path.realpath(os.path.abspath(file_path))
            base = _music_mount_base_real(mount)
        except OSError:
            return None
        prefix = base + os.sep
        if real_f != base and not real_f.startswith(prefix):
            return None
        if not os.path.isfile(real_f):
            return None
        return real_f

    def ensure_project_main_audio_library(project_id: int) -> ProjectAudioLibrary:
        row = (
            ProjectAudioLibrary.query.filter_by(project_id=project_id, parent_id=None)
            .order_by(ProjectAudioLibrary.id.asc())
            .first()
        )
        if row is not None:
            if (row.name or "").strip().lower() != "main":
                row.name = "Main"
                db.session.commit()
            return row
        row = ProjectAudioLibrary(project_id=project_id, name="Main", parent_id=None)
        db.session.add(row)
        db.session.commit()
        return row

    def _music_get_or_create_for_mount_rel(
        mount: MusicMount, rel_path: str
    ) -> MusicFile | None:
        """Return indexed row for mount+relative path; create a row if file exists."""
        rel = (rel_path or "").strip().replace("\\", "/")
        parts = [p for p in rel.split("/") if p and p != "."]
        if any(p == ".." for p in parts):
            return None
        if not parts:
            return None
        name = parts[-1]
        if not name.lower().endswith(_music_supported_ext):
            return None
        try:
            base = _music_mount_base_real(mount)
        except OSError:
            return None
        target = os.path.realpath(os.path.join(base, *parts))
        prefix = base + os.sep
        if target != base and not target.startswith(prefix):
            return None
        if not os.path.isfile(target):
            return None
        row = MusicFile.query.filter_by(file_path=target).first()
        if row is not None:
            if row.mount_id is None:
                row.mount_id = mount.id
            return row
        rel_fold = "/".join(parts[:-1])
        ext = (name.rsplit(".", 1)[-1] if "." in name else "").lower()
        row = MusicFile(
            mount_id=mount.id,
            file_path=target,
            name=name,
            folder=rel_fold,
            duration=0.0,
            type=ext,
        )
        db.session.add(row)
        return row

    def scan_mount(mount: MusicMount) -> int:
        """Walk one mount; insert MusicFile rows (mutagen duration). Returns count added."""
        from mutagen import File as MutagenFile

        base_path = _music_mount_base_real(mount)
        if not os.path.isdir(base_path):
            raise FileNotFoundError(base_path)

        added = 0
        pending = 0
        for root, _dirs, files in os.walk(base_path):
            for fname in files:
                if not fname.lower().endswith(_music_supported_ext):
                    continue
                full_path = os.path.join(root, fname)
                try:
                    resolved = os.path.realpath(full_path)
                except OSError:
                    continue
                prefix = base_path + os.sep
                if resolved != base_path and not resolved.startswith(prefix):
                    continue
                if not os.path.isfile(resolved):
                    continue
                if MusicFile.query.filter_by(file_path=resolved).first() is not None:
                    continue
                duration = 0.0
                try:
                    audio = MutagenFile(resolved)
                    if audio is not None and getattr(audio, "info", None) is not None:
                        duration = float(getattr(audio.info, "length", 0) or 0)
                except Exception:
                    duration = 0.0
                ext = (fname.rsplit(".", 1)[-1] if "." in fname else "").lower()
                rel_fold = os.path.relpath(root, base_path)
                folder_display = "" if rel_fold in (".", "") else rel_fold
                db.session.add(
                    MusicFile(
                        mount_id=mount.id,
                        file_path=resolved,
                        name=fname,
                        folder=folder_display,
                        duration=duration,
                        type=ext,
                    )
                )
                added += 1
                pending += 1
                if pending >= 256:
                    db.session.commit()
                    pending = 0
        if pending:
            db.session.commit()
        return added

    @app.route("/music-library/")
    @app.route("/music-library")
    def music_library():
        def _serialize_folder_nodes(children: dict[str, dict[str, object]]) -> list[dict[str, object]]:
            items: list[dict[str, object]] = []
            for name in sorted(children.keys(), key=lambda s: s.lower()):
                node = children[name]
                items.append(
                    {
                        "name": node["name"],
                        "path": node["path"],
                        "children": _serialize_folder_nodes(node["children"]),  # type: ignore[index]
                    }
                )
            return items

        q = (request.args.get("q") or "").strip()
        query = MusicFile.query.options(joinedload(MusicFile.mount))
        search_files: list[MusicFile] = []
        if q:
            like = f"%{q}%"
            query = query.filter(
                or_(MusicFile.name.ilike(like), MusicFile.folder.ilike(like))
            )
            search_files = query.order_by(MusicFile.created_at.desc()).all()

        folder_rows = (
            db.session.query(
                MusicFile.mount_id.label("mount_id"),
                MusicMount.name.label("mount_name"),
                MusicFile.folder.label("folder"),
            )
            .outerjoin(MusicMount, MusicMount.id == MusicFile.mount_id)
            .distinct()
            .order_by(MusicMount.name.asc(), MusicFile.folder.asc())
            .all()
        )
        mounts_map: dict[str, dict[str, object]] = {}
        for r in folder_rows:
            m_id = int(r.mount_id) if r.mount_id is not None else 0
            m_name = ((r.mount_name or "").strip() if r.mount_name is not None else "") or "Unassigned mount"
            mkey = f"{m_id}:{m_name}"
            if mkey not in mounts_map:
                mounts_map[mkey] = {
                    "mount_id": m_id,
                    "mount": m_name,
                    "children": {},
                }
            folder_raw = (r.folder or "").strip().replace("\\", "/")
            if folder_raw in ("", "."):
                continue
            current = mounts_map[mkey]["children"]  # type: ignore[index]
            parts = [p for p in folder_raw.split("/") if p]
            built = []
            for p in parts:
                built.append(p)
                if p not in current:
                    current[p] = {"name": p, "path": "/".join(built), "children": {}}  # type: ignore[index]
                current = current[p]["children"]  # type: ignore[index]

        folder_tree: list[dict[str, object]] = []
        for mkey in sorted(mounts_map.keys(), key=lambda k: str(mounts_map[k]["mount"]).lower()):
            mount_node = mounts_map[mkey]
            folder_tree.append(
                {
                    "mount_id": mount_node["mount_id"],
                    "mount": mount_node["mount"],
                    "children": _serialize_folder_nodes(mount_node["children"]),  # type: ignore[index]
                }
            )

        count_rows = (
            db.session.query(
                MusicFile.mount_id,
                MusicFile.folder,
                func.count(MusicFile.id).label("n"),
            )
            .group_by(MusicFile.mount_id, MusicFile.folder)
            .all()
        )
        by_mount_folder_counts: dict[int, dict[str, int]] = defaultdict(dict)
        for r in count_rows:
            mid = int(r.mount_id) if r.mount_id is not None else 0
            fold = (r.folder or "").strip().replace("\\", "/")
            by_mount_folder_counts[mid][fold] = int(r.n or 0)

        def subtree_file_count(mount_id: int, path_prefix: str) -> int:
            path_prefix = (path_prefix or "").strip().replace("\\", "/")
            total = 0
            folder_map = by_mount_folder_counts.get(mount_id, {})
            for fpath, n in folder_map.items():
                if not path_prefix:
                    continue
                if fpath == path_prefix or fpath.startswith(path_prefix + "/"):
                    total += n
            return total

        def root_indexed_file_count(mount_id: int) -> int:
            folder_map = by_mount_folder_counts.get(mount_id, {})
            return int(folder_map.get("", 0)) + int(folder_map.get(".", 0))

        folder_subtree_counts: dict[str, int] = {}

        def walk_folder_nodes(nodes: list[dict[str, object]], mid: int) -> None:
            for node in nodes:
                path = str((node.get("path") or "")).strip().replace("\\", "/")
                key = f"{mid}:{path}"
                folder_subtree_counts[key] = subtree_file_count(mid, path)
                children = node.get("children") or []
                if isinstance(children, list):
                    walk_folder_nodes(children, mid)  # type: ignore[arg-type]

        for branch in folder_tree:
            bid = int(branch["mount_id"])  # type: ignore[arg-type]
            kids = branch.get("children") or []
            if isinstance(kids, list):
                walk_folder_nodes(kids, bid)

        folder_root_file_counts: dict[int, int] = {}
        for branch in folder_tree:
            bid = int(branch["mount_id"])  # type: ignore[arg-type]
            folder_root_file_counts[bid] = root_indexed_file_count(bid)

        usage_top: list[dict[str, object]] = []
        usage_recent: list[dict[str, object]] = []
        try:
            top_q = (
                db.session.query(AudioUsage.file_id, func.count(AudioUsage.id).label("cnt"))
                .group_by(AudioUsage.file_id)
                .order_by(func.count(AudioUsage.id).desc())
                .limit(10)
                .all()
            )
            for file_id, cnt in top_q:
                mf = db.session.get(MusicFile, int(file_id))
                usage_top.append(
                    {
                        "id": int(file_id),
                        "name": mf.name if mf else "Unknown",
                        "count": int(cnt),
                    }
                )
            recent_rows = AudioUsage.query.order_by(AudioUsage.created_at.desc()).limit(10).all()
            for row in recent_rows:
                mf = row.file
                usage_recent.append(
                    {
                        "file_id": int(row.file_id),
                        "name": mf.name if mf else "Unknown",
                        "action": str(row.action or ""),
                        "at": row.created_at.isoformat() if row.created_at else "",
                    }
                )
        except Exception:
            usage_top = []
            usage_recent = []

        actor = account_from_session()
        visible = visible_project_ids_for_account(actor)
        project_query = Project.query.order_by(Project.name.asc())
        if visible is not None:
            if not visible:
                project_rows = []
            else:
                project_rows = project_query.filter(Project.id.in_(list(visible))).all()
        else:
            project_rows = project_query.all()
        project_audio_targets: dict[int, list[dict[str, object]]] = {}
        if project_rows:
            pids = [int(p.id) for p in project_rows]
            libs = (
                ProjectAudioLibrary.query.filter(ProjectAudioLibrary.project_id.in_(pids))
                .order_by(ProjectAudioLibrary.parent_id.asc(), ProjectAudioLibrary.name.asc())
                .all()
            )
            by_pid: dict[int, list[ProjectAudioLibrary]] = defaultdict(list)
            for l in libs:
                by_pid[int(l.project_id)].append(l)
            for p in project_rows:
                ensure_project_main_audio_library(int(p.id))
                libs_for_project = by_pid.get(int(p.id), [])
                if not libs_for_project:
                    libs_for_project = (
                        ProjectAudioLibrary.query.filter_by(project_id=int(p.id))
                        .order_by(ProjectAudioLibrary.parent_id.asc(), ProjectAudioLibrary.name.asc())
                        .all()
                    )
                project_audio_targets[int(p.id)] = [
                    {"id": int(l.id), "name": l.name, "parent_id": (int(l.parent_id) if l.parent_id else None)}
                    for l in libs_for_project
                ]

        mounts = MusicMount.query.order_by(MusicMount.created_at.asc()).all()

        music_total_files = int(MusicFile.query.count())
        music_total_folders = int(len(folder_rows))
        music_recent_preview = (
            MusicFile.query.options(joinedload(MusicFile.mount))
            .order_by(MusicFile.created_at.desc())
            .limit(8)
            .all()
        )

        file_usage_counts: dict[int, int] = {}
        if search_files:
            sids = [int(f.id) for f in search_files]
            if sids:
                for fid, cnt in (
                    db.session.query(AudioUsage.file_id, func.count(AudioUsage.id))
                    .filter(AudioUsage.file_id.in_(sids))
                    .group_by(AudioUsage.file_id)
                    .all()
                ):
                    file_usage_counts[int(fid)] = int(cnt or 0)

        return render_template(
            "music_library.html",
            search_files=search_files,
            folder_tree=folder_tree,
            folder_subtree_counts=folder_subtree_counts,
            folder_root_file_counts=folder_root_file_counts,
            mounts=mounts,
            projects_for_audio=project_rows,
            project_audio_targets=project_audio_targets,
            query=q,
            usage_top=usage_top,
            usage_recent=usage_recent,
            music_total_files=music_total_files,
            music_total_folders=music_total_folders,
            music_recent_preview=music_recent_preview,
            file_usage_counts=file_usage_counts,
        )

    @app.route("/music-library/files")
    def music_library_files():
        folder = (request.args.get("folder") or "").strip()
        mount_id = request.args.get("mount_id", type=int)
        name_q = (request.args.get("q") or "").strip()
        query = MusicFile.query
        if mount_id is not None:
            query = query.filter(MusicFile.mount_id == int(mount_id))
        query = query.filter(MusicFile.folder == folder)
        if name_q:
            like = f"%{name_q}%"
            query = query.filter(MusicFile.name.ilike(like))
        files = query.order_by(MusicFile.name.asc()).all()
        usage_by_id: dict[int, int] = {}
        if files:
            fids = [int(f.id) for f in files]
            for fid, cnt in (
                db.session.query(AudioUsage.file_id, func.count(AudioUsage.id))
                .filter(AudioUsage.file_id.in_(fids))
                .group_by(AudioUsage.file_id)
                .all()
            ):
                usage_by_id[int(fid)] = int(cnt or 0)
        return jsonify(
            [
                {
                    "id": f.id,
                    "name": f.name,
                    "duration": float(f.duration or 0),
                    "folder": f.folder or "",
                    "mount_id": int(f.mount_id) if f.mount_id is not None else None,
                    "file_path": f.file_path,
                    "type": (f.type or "").strip(),
                    "usage_count": int(usage_by_id.get(int(f.id), 0)),
                }
                for f in files
            ]
        )

    @app.route("/music-library/mount/add/", methods=["POST"])
    @app.route("/music-library/mount/add", methods=["POST"])
    def music_library_mount_add():
        actor = account_from_session()
        if not account_can_manage_music_mounts(actor):
            flash("Only administrators and super users can manage music mounts.", "error")
            return redirect(url_for("music_library"))
        raw = (request.form.get("base_path") or "").strip()
        if not raw:
            flash("Mount path is required.", "error")
            return redirect(url_for("music_library"))
        try:
            resolved = os.path.realpath(os.path.abspath(os.path.expanduser(raw)))
        except OSError:
            flash("Invalid path.", "error")
            return redirect(url_for("music_library"))
        if not os.path.exists(resolved):
            flash("Path does not exist.", "error")
            return redirect(url_for("music_library"))
        if not os.path.isdir(resolved):
            flash("Path must be a directory.", "error")
            return redirect(url_for("music_library"))
        if MusicMount.query.filter_by(base_path=resolved).first() is not None:
            flash("That mount path is already registered.", "warning")
            return redirect(url_for("music_library"))
        label = os.path.basename(resolved.rstrip(os.sep)) or resolved
        db.session.add(MusicMount(name=label, base_path=resolved))
        db.session.commit()
        flash("Mount added.", "success")
        return redirect(url_for("music_library"))

    @app.route("/music-library/browse/<int:mount_id>/")
    @app.route("/music-library/browse/<int:mount_id>")
    def browse_mount(mount_id: int):
        actor = account_from_session()
        if not account_can_manage_music_mounts(actor):
            flash("Only administrators and super users can access mount browsing.", "error")
            return redirect(url_for("music_library"))
        m = db.session.get(MusicMount, mount_id)
        if m is None:
            abort(404)
        rel = (request.args.get("path") or "").strip().replace("\\", "/")
        parts = [p for p in rel.split("/") if p and p != "."]
        if any(p == ".." for p in parts):
            abort(400)
        rel_norm = "/".join(parts)
        try:
            base = _music_mount_base_real(m)
        except OSError:
            abort(404)
        if not os.path.isdir(base):
            abort(404)
        target = os.path.realpath(os.path.join(base, *parts)) if parts else base
        prefix = base + os.sep
        if target != base and not target.startswith(prefix):
            abort(403)
        if not os.path.isdir(target):
            abort(404)
        items: list[dict[str, str | bool]] = []
        folder_key = rel_norm if rel_norm else ""
        existing_rows = MusicFile.query.filter_by(mount_id=m.id, folder=folder_key).all()
        indexed_by_name = {r.name: r for r in existing_rows}
        try:
            entry_names = os.listdir(target)
        except OSError:
            abort(403)

        def _is_dir(n: str) -> bool:
            try:
                return os.path.isdir(os.path.join(target, n))
            except OSError:
                return False

        for name in sorted(entry_names, key=lambda x: (not _is_dir(x), x.lower())):
            item_path = os.path.join(target, name)
            child_rel = f"{rel_norm}/{name}" if rel_norm else name
            try:
                is_dir = os.path.isdir(item_path)
            except OSError:
                continue
            playable = (
                not is_dir
                and name.lower().endswith(_music_supported_ext)
            )
            indexed = indexed_by_name.get(name)
            items.append(
                {
                    "name": name,
                    "is_dir": is_dir,
                    "path": child_rel,
                    "playable": playable,
                    "file_id": indexed.id if indexed else None,
                    "color_tags": _music_parse_color_tags(indexed.color_tag if indexed else ""),
                    "comments": (indexed.comments if indexed else "") or "",
                }
            )
        parent_path = ""
        if rel_norm:
            parent_path = "/".join(rel_norm.split("/")[:-1])
        return render_template(
            "browse.html",
            mount=m,
            items=items,
            path=rel_norm,
            parent_path=parent_path,
        )

    @app.route("/music-library/mount/<int:mount_id>/play/")
    @app.route("/music-library/mount/<int:mount_id>/play")
    def browse_play_file(mount_id: int):
        """Stream a file under a mount by relative path (browse view; not indexed required)."""
        actor = account_from_session()
        if not account_can_manage_music_mounts(actor):
            abort(403)
        m = db.session.get(MusicMount, mount_id)
        if m is None:
            abort(404)
        rel = (request.args.get("path") or "").strip().replace("\\", "/")
        parts = [p for p in rel.split("/") if p and p != "."]
        if any(p == ".." for p in parts):
            abort(400)
        if not parts:
            abort(404)
        fname = parts[-1]
        if not fname.lower().endswith(_music_supported_ext):
            abort(404)
        try:
            base = _music_mount_base_real(m)
        except OSError:
            abort(404)
        target = os.path.realpath(os.path.join(base, *parts))
        prefix = base + os.sep
        if target != base and not target.startswith(prefix):
            abort(403)
        if not os.path.isfile(target):
            abort(404)
        mt, _enc = mimetypes.guess_type(target)
        return send_file(
            target, conditional=True, mimetype=mt or "application/octet-stream"
        )

    @app.route("/music-library/mount/<int:mount_id>/tag/", methods=["POST"])
    @app.route("/music-library/mount/<int:mount_id>/tag", methods=["POST"])
    def music_library_mount_tag(mount_id: int):
        """Update color_tag/comments for a file under this mount (DB metadata only)."""
        actor = account_from_session()
        if not account_can_manage_music_mounts(actor):
            return jsonify({"ok": False, "error": "forbidden"}), 403
        m = db.session.get(MusicMount, mount_id)
        if m is None:
            return jsonify({"ok": False, "error": "mount_not_found"}), 404
        payload = request.get_json(silent=True) or {}
        raw_path = (payload.get("path") or request.form.get("path") or "").strip()
        row = _music_get_or_create_for_mount_rel(m, raw_path)
        if row is None:
            return jsonify({"ok": False, "error": "invalid_path"}), 400
        raw_color_tags = payload.get("color_tags")
        if raw_color_tags is None:
            raw_color_tags = request.form.getlist("color_tags")
        if raw_color_tags is None:
            raw_color_tags = []
        if isinstance(raw_color_tags, str):
            color_tags = _music_parse_color_tags(raw_color_tags)
        elif isinstance(raw_color_tags, list):
            color_tags = _music_parse_color_tags(",".join([str(x) for x in raw_color_tags]))
        else:
            color_tags = []
        raw_comments = (payload.get("comments") or request.form.get("comments") or "").strip()
        row.color_tag = _music_color_tags_to_db(color_tags)
        row.comments = raw_comments[:5000] or None
        db.session.commit()
        return jsonify(
            {
                "ok": True,
                "file_id": row.id,
                "color_tags": _music_parse_color_tags(row.color_tag),
                "comments": row.comments or "",
            }
        )

    @app.route("/music-library/file/<int:file_id>/meta/", methods=["POST"])
    @app.route("/music-library/file/<int:file_id>/meta", methods=["POST"])
    def music_library_file_meta(file_id: int):
        """Update color tags/favorite for an indexed music file (DB metadata only)."""
        row = db.session.get(MusicFile, file_id)
        if row is None:
            return jsonify({"ok": False, "error": "file_not_found"}), 404
        payload = request.get_json(silent=True) or {}
        raw_color_tags = payload.get("color_tags")
        if raw_color_tags is None:
            raw_color_tags = request.form.getlist("color_tags")
        if isinstance(raw_color_tags, str):
            color_tags = _music_parse_color_tags(raw_color_tags)
        elif isinstance(raw_color_tags, list):
            color_tags = _music_parse_color_tags(",".join([str(x) for x in raw_color_tags]))
        else:
            color_tags = []
        raw_favorite = payload.get("is_favorite")
        if raw_favorite is None:
            raw_favorite = request.form.get("is_favorite")
        is_favorite = str(raw_favorite).strip().lower() in {"1", "true", "yes", "on"}
        row.color_tag = _music_color_tags_to_db(color_tags)
        row.is_favorite = bool(is_favorite)
        db.session.commit()
        return jsonify(
            {
                "ok": True,
                "file_id": row.id,
                "color_tags": _music_parse_color_tags(row.color_tag),
                "is_favorite": bool(row.is_favorite),
            }
        )

    @app.route("/music-library/mount/<int:mount_id>/scan/")
    @app.route("/music-library/mount/<int:mount_id>/scan")
    def music_library_scan_mount(mount_id: int):
        actor = account_from_session()
        if not account_can_manage_music_mounts(actor):
            flash("Only administrators and super users can manage music mounts.", "error")
            return redirect(url_for("music_library"))
        m = db.session.get(MusicMount, mount_id)
        if m is None:
            abort(404)
        try:
            n = scan_mount(m)
            flash(f"Scan complete. {n} new file(s) indexed for “{m.name}”.", "success")
        except FileNotFoundError:
            flash(f"Mount path is not available: {m.base_path}", "error")
        except Exception:
            app.logger.exception("music_library_scan_mount")
            flash("Scan failed. Check server logs.", "error")
        return redirect(url_for("music_library"))

    @app.route("/music-library/mount/<int:mount_id>/remove/", methods=["POST"])
    @app.route("/music-library/mount/<int:mount_id>/remove", methods=["POST"])
    def music_library_mount_remove(mount_id: int):
        """Unmount library path and remove its indexed files from DB only."""
        actor = account_from_session()
        if not account_can_manage_music_mounts(actor):
            return jsonify({"ok": False, "error": "forbidden"}), 403
        m = db.session.get(MusicMount, mount_id)
        if m is None:
            return jsonify({"ok": False, "error": "not_found"}), 404
        removed_files = MusicFile.query.filter_by(mount_id=mount_id).count()
        MusicFile.query.filter_by(mount_id=mount_id).delete(synchronize_session=False)
        db.session.delete(m)
        db.session.commit()
        return jsonify({"ok": True, "removed_files": int(removed_files)})

    @app.route("/audio/<int:file_id>")
    def stream_audio(file_id: int):
        mf = db.session.get(MusicFile, file_id)
        if mf is None:
            abort(404)
        if not os.path.exists(mf.file_path):
            abort(404)
        if mf.mount_id is not None:
            mount = db.session.get(MusicMount, mf.mount_id)
            if mount is None:
                abort(403)
            real_f = _music_file_under_mount(mf.file_path, mount)
            if real_f is None:
                abort(403)
        else:
            try:
                real_f = os.path.realpath(os.path.abspath(mf.file_path))
            except OSError:
                abort(404)
            if not os.path.isfile(real_f):
                abort(404)
            allowed = False
            for m in MusicMount.query.all():
                base = _music_mount_base_real(m)
                pref = base + os.sep
                if real_f == base or real_f.startswith(pref):
                    allowed = True
                    break
            if not allowed:
                abort(403)
        mt, _enc = mimetypes.guess_type(real_f)
        return send_file(
            real_f, conditional=True, mimetype=mt or "application/octet-stream"
        )

    @app.route("/audio/track", methods=["POST"])
    def track_audio():
        actor = account_from_session()
        if actor is None:
            return jsonify({"ok": False, "error": "forbidden"}), 403
        payload = request.get_json(silent=True) or {}
        raw_file_id = payload.get("file_id")
        action = str(payload.get("action") or "").strip().lower()
        raw_project_id = payload.get("project_id")
        try:
            file_id = int(raw_file_id)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "invalid_file_id"}), 400
        row = db.session.get(MusicFile, file_id)
        if row is None:
            return jsonify({"ok": False, "error": "file_not_found"}), 404
        if action not in {"play", "drag", "copy"}:
            return jsonify({"ok": False, "error": "invalid_action"}), 400

        project_id: int | None = None
        if raw_project_id not in (None, ""):
            try:
                parsed_project_id = int(raw_project_id)
            except (TypeError, ValueError):
                parsed_project_id = None
            if parsed_project_id is not None and account_can_access_project(actor, parsed_project_id):
                project_id = parsed_project_id

        db.session.add(
            AudioUsage(
                file_id=int(row.id),
                project_id=project_id,
                user_id=int(actor.id),
                action=action,
            )
        )
        db.session.commit()
        return jsonify({"ok": True})

    @app.route("/music-library/show/<int:file_id>")
    def music_library_show_in_finder(file_id: int):
        """macOS only: reveal indexed file in Finder (DB/index only; no file mutation)."""
        mf = db.session.get(MusicFile, file_id)
        if mf is None:
            return jsonify({"ok": False, "error": "not_found"}), 404
        if os.name != "posix":
            return jsonify({"ok": False, "error": "unsupported_platform"}), 400

        real_f: str | None = None
        if mf.mount_id is not None:
            mount = db.session.get(MusicMount, mf.mount_id)
            if mount is None:
                return jsonify({"ok": False, "error": "forbidden"}), 403
            real_f = _music_file_under_mount(mf.file_path, mount)
            if real_f is None:
                return jsonify({"ok": False, "error": "forbidden"}), 403
        else:
            # Legacy rows without mount_id: allow only if path stays under any registered mount.
            try:
                candidate = os.path.realpath(os.path.abspath(mf.file_path))
            except OSError:
                candidate = ""
            if not candidate or not os.path.isfile(candidate):
                return jsonify({"ok": False, "error": "not_found"}), 404
            for m in MusicMount.query.all():
                base = _music_mount_base_real(m)
                pref = base + os.sep
                if candidate == base or candidate.startswith(pref):
                    real_f = candidate
                    break
            if real_f is None:
                return jsonify({"ok": False, "error": "forbidden"}), 403

        if not os.path.exists(real_f):
            return jsonify({"ok": False, "error": "not_found"}), 404
        try:
            subprocess.run(["open", "-R", real_f], check=False)
        except Exception:
            return jsonify({"ok": False, "error": "open_failed"}), 500
        return jsonify({"ok": True})

    @app.route("/music-library/delete/<int:file_id>/", methods=["POST"])
    @app.route("/music-library/delete/<int:file_id>", methods=["POST"])
    def delete_music_file(file_id: int):
        """Remove index row only; never deletes audio from disk."""
        mf = db.session.get(MusicFile, file_id)
        if mf is None:
            return jsonify({"ok": False, "error": "not_found"}), 404
        db.session.delete(mf)
        db.session.commit()
        return jsonify({"ok": True})

    @app.route("/")
    def index():
        acc = db.session.get(Account, session.get("account_id"))
        vis = visible_project_ids_for_account(acc)
        user_count = User.query.count()
        if vis is None:
            # Administrator: all projects, original dashboard semantics
            task_count = Task.query.filter_by(archived=False).count()
            open_tasks = Task.query.filter_by(status="open", archived=False).count()
        elif not vis:
            task_count = 0
            open_tasks = 0
        else:
            uid = directory_user_id_for_account(acc)
            if uid is None:
                task_count = 0
                open_tasks = 0
            else:
                # Team-member projects only: "My Open Tasks" + "All Tasks" (all open in those projects)
                open_tasks = (
                    Task.query.filter(
                        Task.project_id.in_(vis),
                        Task.archived.is_(False),
                        Task.status == "open",
                        Task.user_id == uid,
                    ).count()
                )
                task_count = (
                    Task.query.filter(
                        Task.project_id.in_(vis),
                        Task.archived.is_(False),
                        Task.status == "open",
                    ).count()
                )

        # Dashboard "Number of projects": administrators = all rows; everyone else = team membership only
        if acc is not None and acc.is_admin:
            project_count = Project.query.count()
        elif not vis:
            project_count = 0
        else:
            project_count = len(vis)

        booking_today_card = None
        if acc is not None:
            uid_bt = directory_user_id_for_account(acc)
            if uid_bt is not None:
                bt = (
                    Booking.query.options(
                        joinedload(Booking.edit_suite),
                        joinedload(Booking.project),
                        joinedload(Booking.booked_for_user),
                    )
                    .filter(
                        Booking.booked_for_id == uid_bt,
                        Booking.booking_date == today_cairo(),
                        Booking.is_active.is_(True),
                    )
                    .order_by(Booking.start_time.asc())
                    .first()
                )
                if bt is not None:
                    sn = bt.edit_suite.name if bt.edit_suite is not None else "Room"
                    pn = bt.project.name if bt.project is not None else ""
                    bf = bt.booked_for_user
                    bf_name = (bf.name or bf.email or "").strip() if bf is not None else ""
                    booking_today_card = {
                        "suite_name": sn,
                        "project_name": pn,
                        "time_label": f"{bt.start_time.strftime('%H:%M')}–{bt.end_time.strftime('%H:%M')}",
                        "booked_for_name": bf_name,
                        "is_full_day": bool(bt.is_full_day),
                    }

        machine_room_tasks = fetch_dashboard_machine_room_tasks(acc)

        return render_template(
            "index.html",
            user_count=user_count,
            task_count=task_count,
            open_tasks=open_tasks,
            project_count=project_count,
            booking_today_card=booking_today_card,
            machine_room_tasks=machine_room_tasks,
        )

    @app.route("/chat/threads", methods=["GET"])
    def chat_threads_api():
        # Match inject_globals / account_from_session (int PK); avoid query.get(session id)
        # type mismatches that returned 403 while the shell still rendered as "logged in".
        acc = account_from_session()
        if acc is None:
            return jsonify({"threads": []})
        return jsonify({"threads": build_chat_threads_for_dashboard(acc)})

    @app.route("/ui/fragment/dashboard-machine-room-tasks")
    def ui_fragment_dashboard_machine_room_tasks():
        acc = account_from_session()
        if acc is None:
            abort(403)
        machine_room_tasks = fetch_dashboard_machine_room_tasks(acc)
        return render_template(
            "partials/fragment_dashboard_mr_tasks_section.html",
            machine_room_tasks=machine_room_tasks,
        )

    @app.route("/ui/fragment/machine-room/tasks-zone", defaults={"tab_slug": None})
    @app.route("/ui/fragment/machine-room/tasks-zone/<tab_slug>")
    def ui_fragment_machine_room_tasks_zone(tab_slug: str | None):
        actor = account_from_session()
        if actor is None or not account_is_machine_room_role(actor):
            abort(403)
        if tab_slug is not None and tab_slug not in ("progress", "finished"):
            abort(404)
        bundle = machine_room_tasks_page_bundle(actor, fragment_tab_slug=tab_slug)
        if bundle is None:
            abort(403)
        return render_template("partials/fragment_mr_tasks_refresh_zone.html", **bundle)

    @app.route("/ui/fragment/tasks/my-stream-slot")
    def ui_fragment_tasks_my_stream_slot():
        acc = account_from_session()
        if acc is None or account_is_machine_room_role(acc):
            abort(403)
        du = User.query.filter_by(account_id=acc.id).first() if acc else None
        if du is None:
            return render_template(
                "partials/fragment_tasks_my_stream_slot.html",
                my_tasks=[],
            )
        all_tasks = all_tasks_for_tasks_list_page(acc)
        my_tasks = sorted(
            [t for t in all_tasks if t.user_id == du.id],
            key=lambda t: t.created_at,
            reverse=True,
        )
        return render_template(
            "partials/fragment_tasks_my_stream_slot.html",
            my_tasks=my_tasks,
        )

    @app.route("/ui/fragment/project/<int:project_id>/tasks-panel-body")
    def ui_fragment_project_tasks_panel_body(project_id: int):
        acc = account_from_session()
        if acc is None:
            abort(403)
        p = Project.query.get_or_404(project_id)
        if not account_can_access_project(acc, p.id):
            abort(403)
        project_tasks_all = (
            Task.query.options(
                joinedload(Task.group), joinedload(Task.assignee), joinedload(Task.project)
            )
            .filter_by(project_id=p.id)
            .order_by(Task.created_at.desc())
            .all()
        )
        active_tasks = [
            t
            for t in project_tasks_all
            if not t.archived and t.status in ("open", "in_progress")
        ]
        member_ids = {m.user_id for m in p.memberships}
        if member_ids:
            member_users = (
                User.query.options(joinedload(User.job_title))
                .filter(User.id.in_(member_ids))
                .all()
            )
        else:
            member_users = []
        has_title_presets = TaskGroupTitle.query.count() > 0
        return render_template(
            "partials/fragment_project_tasks_panel_body.html",
            project=p,
            active_tasks=active_tasks,
            has_title_presets=has_title_presets,
            member_users=member_users,
        )

    @app.route("/projects")
    def projects_list():
        acc = db.session.get(Account, session.get("account_id"))
        vis = visible_project_ids_for_account(acc)
        q = (
            Project.query.options(
                selectinload(Project.memberships).selectinload(ProjectMember.user)
            )
            .order_by(Project.sort_order.asc(), Project.id.asc())
        )
        if vis is None:
            projects = q.all()
        elif not vis:
            projects = []
        else:
            projects = q.filter(Project.id.in_(vis)).all()
        project_team_search = {}
        for p in projects:
            parts: list[str] = []
            for m in p.memberships:
                u = m.user
                if u is None:
                    continue
                nm = (u.name or "").strip()
                em = (u.email or "").strip()
                if nm:
                    parts.append(nm)
                if em:
                    parts.append(em)
            project_team_search[p.id] = " ".join(parts)
        return render_template(
            "projects.html",
            projects=projects,
            project_team_search=project_team_search,
        )

    @app.route("/machine-room")
    def machine_room():
        actor = account_from_session()
        if actor is None:
            abort(403)
        query = (request.args.get("q") or "").strip()

        vis = visible_project_ids_for_account(actor)
        projects = (
            Project.query.options(
                selectinload(Project.memberships).selectinload(ProjectMember.user)
            )
            .order_by(Project.sort_order.asc(), Project.id.asc())
        )
        if vis is None:
            projects = projects.all()
        elif not vis:
            projects = []
        else:
            projects = projects.filter(Project.id.in_(vis)).all()

        project_members: dict[int, list[User]] = {}
        for p in projects:
            project_members[p.id] = [m.user for m in (p.memberships or []) if m.user is not None]

        return render_template(
            "machine_room.html",
            projects=projects,
            project_members=project_members,
            query=query,
        )

    @app.route("/machine-room/tasks")
    def machine_room_tasks():
        """Legacy / bare URL → redirect to path-based tab (preserves filters)."""
        actor = account_from_session()
        if actor is None:
            abort(403)
        if not account_is_machine_room_role(actor):
            flash("That page is only available for Machine Room accounts.", "error")
            return redirect(url_for("index"))
        flat = request.args.to_dict(flat=True)
        tab = (flat.pop("tab", None) or "progress").strip().lower()
        if tab not in ("progress", "finished"):
            tab = "progress"
        qd: dict = {}
        for k, v in flat.items():
            if not v and v != 0:
                continue
            if k in ("project_id", "user_id", "pg", "pf"):
                try:
                    qd[k] = int(v)
                except (TypeError, ValueError):
                    continue
            else:
                qd[k] = v
        if qd.get("pg") == 1:
            qd.pop("pg", None)
        if qd.get("pf") == 1:
            qd.pop("pf", None)
        return redirect(url_for("machine_room_tasks_tab", tab_slug=tab, **qd))

    @app.route("/machine-room/tasks/<tab_slug>")
    def machine_room_tasks_tab(tab_slug: str):
        """Tasks assigned to MR directory users; tab in path: progress | finished."""
        if tab_slug not in ("progress", "finished"):
            abort(404)
        actor = account_from_session()
        if actor is None:
            abort(403)
        if not account_is_machine_room_role(actor):
            flash("That page is only available for Machine Room accounts.", "error")
            return redirect(url_for("index"))
        bundle = machine_room_tasks_page_bundle(actor)
        if bundle is None:
            abort(403)
        return render_template("machine_room_tasks.html", **bundle)

    def build_machine_project_context(p: Project) -> dict:
        production_episode_count = max(0, int(p.number_of_episodes or 0))
        machine_shooting_days = (
            ShootingDay.query.filter_by(project_id=p.id)
            .order_by(ShootingDay.shooting_date.asc(), ShootingDay.id.asc())
            .all()
        )
        machine_pipeline_count = (
            ShootingDayScene.query.join(
                ShootingDay, ShootingDayScene.shooting_day_id == ShootingDay.id
            )
            .filter(ShootingDay.project_id == p.id)
            .count()
        )
        sync_done_n = (
            ShootingDayScene.query.join(
                ShootingDay, ShootingDayScene.shooting_day_id == ShootingDay.id
            )
            .filter(ShootingDay.project_id == p.id, ShootingDayScene.sync_done.is_(True))
            .count()
        )
        edit_done_n = (
            ShootingDayScene.query.join(
                ShootingDay, ShootingDayScene.shooting_day_id == ShootingDay.id
            )
            .filter(ShootingDay.project_id == p.id, ShootingDayScene.first_edit_done.is_(True))
            .count()
        )
        machine_scene_sync_pct = (
            int(round(100.0 * sync_done_n / machine_pipeline_count))
            if machine_pipeline_count
            else 0
        )
        machine_scene_edit_pct = (
            int(round(100.0 * edit_done_n / machine_pipeline_count))
            if machine_pipeline_count
            else 0
        )
        links = (
            ShootingDayScene.query.join(
                ShootingDay, ShootingDayScene.shooting_day_id == ShootingDay.id
            )
            .filter(ShootingDay.project_id == p.id)
            .all()
        )
        by_episode: dict[int, list[ShootingDayScene]] = defaultdict(list)
        for row in links:
            ep_num = int(row.episode_number or 0)
            if 1 <= ep_num <= production_episode_count:
                by_episode[ep_num].append(row)
        machine_episode_rows: list[dict] = []
        episodes_done = 0
        for ep_num in range(1, production_episode_count + 1):
            rows = by_episode.get(ep_num, [])
            sync_done = bool(rows) and all(bool(r.sync_done) for r in rows)
            first_edit_done = bool(rows) and all(bool(r.first_edit_done) for r in rows)
            if sync_done and first_edit_done:
                episodes_done += 1
            machine_episode_rows.append(
                {
                    "episode_number": ep_num,
                    "scene_count": len(rows),
                    "sync_done": sync_done,
                    "first_edit_done": first_edit_done,
                }
            )
        machine_episodes_pct = (
            int(round(100.0 * episodes_done / production_episode_count))
            if production_episode_count
            else 0
        )
        today = today_cairo()
        machine_booking_active = Booking.query.filter_by(
            project_id=p.id, is_active=True
        ).count()
        machine_booking_upcoming = Booking.query.filter(
            Booking.project_id == p.id,
            Booking.is_active.is_(True),
            Booking.booking_date >= today,
        ).count()

        def shooting_day_hdd_label(day: ShootingDay) -> str:
            unit = int(day.unit_number or 1)
            dn = (day.day_name or "").strip() or "—"
            ds = day.shooting_date.isoformat() if day.shooting_date else "—"
            return f"Unit {unit} · Day {dn} · {ds}"

        hdds = (
            HardDisk.query.filter_by(project_id=p.id)
            .options(
                selectinload(HardDisk.usages).joinedload(HardDiskUsage.shooting_day),
            )
            .order_by(HardDisk.created_at.desc(), HardDisk.id.desc())
            .all()
        )
        machine_hdd_cards: list[dict] = []
        machine_hdd_total_capacity_tb = 0.0
        machine_hdd_total_used_tb = 0.0
        for hd in hdds:
            usages = list(hd.usages or [])
            used_tb = sum(
                float(u.video_size_tb or 0) + float(u.audio_size_tb or 0) for u in usages
            )
            cap_tb = float(hd.capacity_tb or 0)
            free_tb = cap_tb - used_tb
            machine_hdd_total_capacity_tb += cap_tb
            machine_hdd_total_used_tb += used_tb
            linked_ids = {u.shooting_day_id for u in usages}
            usage_rows: list[dict] = []
            for u in sorted(
                usages,
                key=lambda x: (
                    (x.shooting_day.shooting_date if x.shooting_day is not None else date.min),
                    x.id,
                ),
            ):
                day = u.shooting_day
                if day is None:
                    continue
                vtb = float(u.video_size_tb or 0)
                atb = float(u.audio_size_tb or 0)
                usage_rows.append(
                    {
                        "id": u.id,
                        "unit_number": int(day.unit_number or 1),
                        "day_name": (day.day_name or "").strip(),
                        "shooting_date": day.shooting_date,
                        "video_tb": vtb,
                        "audio_tb": atb,
                        "video_gb": vtb * HDD_STORAGE_GB_PER_TB,
                        "audio_gb": atb * HDD_STORAGE_GB_PER_TB,
                        "notes": u.notes or "",
                        "label": shooting_day_hdd_label(day),
                    }
                )
            dropdown_options = [
                {"id": d.id, "label": shooting_day_hdd_label(d)}
                for d in machine_shooting_days
                if d.id not in linked_ids
            ]
            machine_hdd_cards.append(
                {
                    "id": hd.id,
                    "name": hd.name,
                    "capacity_tb": cap_tb,
                    "type": (hd.type or "").strip(),
                    "used_tb": used_tb,
                    "free_tb": free_tb,
                    "usage_rows": usage_rows,
                    "dropdown_options": dropdown_options,
                }
            )
        machine_hdd_total_free_tb = machine_hdd_total_capacity_tb - machine_hdd_total_used_tb

        return {
            "production_episode_count": production_episode_count,
            "machine_shooting_days": machine_shooting_days,
            "machine_pipeline_scene_count": machine_pipeline_count,
            "machine_scene_sync_pct": machine_scene_sync_pct,
            "machine_scene_edit_pct": machine_scene_edit_pct,
            "machine_episode_rows": machine_episode_rows,
            "machine_episodes_done": episodes_done,
            "machine_episodes_pct": machine_episodes_pct,
            "machine_booking_active": machine_booking_active,
            "machine_booking_upcoming": machine_booking_upcoming,
            "machine_hdd_cards": machine_hdd_cards,
            "machine_hdd_total_capacity_tb": machine_hdd_total_capacity_tb,
            "machine_hdd_total_used_tb": machine_hdd_total_used_tb,
            "machine_hdd_total_free_tb": machine_hdd_total_free_tb,
        }

    @app.route("/machine/project/<int:project_id>")
    def machine_project(project_id: int):
        actor = account_from_session()
        if actor is None:
            abort(403)
        p = Project.query.get_or_404(project_id)
        if not account_can_access_project(actor, p.id):
            flash("You do not have access to that project.", "error")
            return redirect(url_for("machine_room"))
        if not account_may_use_machine_project_view(actor):
            abort(403)
        machine_ctx = build_machine_project_context(p)
        return render_template(
            "machine_project.html",
            project=p,
            workflow_active="overview",
            **machine_ctx,
        )

    @app.route("/machine/project/<int:project_id>/hard-disks", methods=["POST"])
    def machine_project_hard_disk_create(project_id: int):
        actor = account_from_session()
        if actor is None:
            abort(403)
        p = Project.query.get_or_404(project_id)
        if not account_can_access_project(actor, p.id):
            flash("You do not have access to that project.", "error")
            return redirect(url_for("machine_room"))
        if not account_may_use_machine_project_view(actor):
            abort(403)
        name = (request.form.get("name") or "").strip()
        disk_type = (request.form.get("type") or "").strip()
        if not name:
            flash("Hard disk name is required.", "error")
            return redirect(url_for("machine_project", project_id=project_id))
        if not disk_type:
            flash("Disk type is required.", "error")
            return redirect(url_for("machine_project", project_id=project_id))
        try:
            capacity_tb = float((request.form.get("capacity_tb") or "").strip())
        except (TypeError, ValueError):
            flash("Capacity must be a number.", "error")
            return redirect(url_for("machine_project", project_id=project_id))
        if capacity_tb <= 0:
            flash("Capacity must be greater than 0 TB.", "error")
            return redirect(url_for("machine_project", project_id=project_id))
        db.session.add(
            HardDisk(
                project_id=p.id,
                name=name[:120],
                capacity_tb=capacity_tb,
                type=disk_type[:80],
            )
        )
        db.session.commit()
        hd = (
            HardDisk.query.filter_by(project_id=p.id)
            .order_by(HardDisk.id.desc())
            .first()
        )
        if hd is not None:
            evaluate_hdd_notifications(hd.id)
            db.session.commit()
        flash("Hard disk added.", "success")
        return redirect(url_for("machine_project", project_id=project_id))

    @app.route("/machine/hdd/update-name", methods=["POST"])
    def machine_hdd_update_name():
        """Rename a hard disk (JSON). Used by Machine Room inline editor (no full page reload)."""
        actor = account_from_session()
        if actor is None:
            return jsonify({"ok": False, "error": "forbidden"}), 403
        if not account_may_use_machine_project_view(actor):
            return jsonify({"ok": False, "error": "forbidden"}), 403
        data = request.get_json(silent=True) or {}
        try:
            hid = int(data.get("id"))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "invalid_id"}), 400
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"ok": False, "error": "name_required"}), 400
        hd = db.session.get(HardDisk, hid)
        if hd is None:
            return jsonify({"ok": False, "error": "not_found"}), 404
        if not account_can_access_project(actor, hd.project_id):
            return jsonify({"ok": False, "error": "forbidden"}), 403
        hd.name = name[:120]
        db.session.commit()
        return jsonify({"ok": True})

    @app.route("/notifications", methods=["GET"])
    def notifications_list():
        actor = account_from_session()
        if actor is None:
            return jsonify({"ok": False, "error": "forbidden"}), 403
        uid = directory_user_id_for_account(actor)
        visible = visible_project_ids_for_account(actor)
        vis = _notification_visible_filter(uid=uid, visible=visible)
        if vis is None:
            return jsonify({"ok": True, "notifications": []})
        raw_limit = (request.args.get("limit") or "50").strip()
        try:
            limit = max(1, min(200, int(raw_limit)))
        except (TypeError, ValueError):
            limit = 50
        kind = (request.args.get("type") or "all").strip().lower()
        q = (
            Notification.query.filter(_notification_unresolved_filter())
            .filter(vis)
            .order_by(Notification.created_at.desc(), Notification.id.desc())
        )
        if kind in ("alert", "activity"):
            q = q.filter(db.func.lower(db.func.coalesce(Notification.type, "")) == kind)
        rows = q.limit(limit).all()
        return jsonify({"ok": True, "notifications": [serialize_notification(n) for n in rows]})

    @app.route("/notifications/read-all", methods=["POST"])
    def notifications_mark_all_read():
        actor = account_from_session()
        if actor is None:
            return jsonify({"ok": False, "error": "forbidden"}), 403
        uid = directory_user_id_for_account(actor)
        visible = visible_project_ids_for_account(actor)
        vis = _notification_visible_filter(uid=uid, visible=visible)
        if vis is None:
            return jsonify({"ok": True})
        for r in Notification.query.filter(vis, Notification.is_read.is_(False)).all():
            r.is_read = True
        db.session.commit()
        return jsonify({"ok": True})

    def _notification_mark_field(notification_id: int, field_name: str):
        actor = account_from_session()
        if actor is None:
            return jsonify({"ok": False, "error": "forbidden"}), 403
        n = db.session.get(Notification, notification_id)
        if n is None:
            return jsonify({"ok": False, "error": "not_found"}), 404
        if not _notification_row_may_mutate(actor, n):
            return jsonify({"ok": False, "error": "forbidden"}), 403
        if field_name == "is_acknowledged":
            n.is_acknowledged = True
            n.is_read = True
        elif field_name == "is_resolved":
            n.is_resolved = True
            n.is_read = True
        elif field_name == "is_read":
            n.is_read = True
        else:
            return jsonify({"ok": False, "error": "invalid"}), 400
        db.session.commit()
        return jsonify({"ok": True})

    @app.route("/notifications/read/<int:notification_id>", methods=["POST"])
    def notifications_mark_read(notification_id: int):
        return _notification_mark_field(notification_id, "is_read")

    @app.route("/notifications/ack/<int:notification_id>", methods=["POST"])
    def notifications_ack(notification_id: int):
        return _notification_mark_field(notification_id, "is_acknowledged")

    @app.route("/notifications/resolve/<int:notification_id>", methods=["POST"])
    def notifications_resolve(notification_id: int):
        return _notification_mark_field(notification_id, "is_resolved")

    @app.route("/debug-notifications")
    def debug_notifications():
        """Temporary: total notification row count (admin only)."""
        actor = account_from_session()
        if actor is None or not account_can_access_admin_settings(actor):
            abort(403)
        return str(Notification.query.count())

    @app.route("/machine/project/<int:project_id>/hdd/add-shooting-day", methods=["POST"])
    def machine_hdd_add_shooting_day(project_id: int):
        """Create a shooting day (same model as production) and link it to a project HDD in one step."""
        actor = account_from_session()
        if actor is None:
            return jsonify({"ok": False, "error": "forbidden"}), 403
        p = Project.query.get_or_404(project_id)
        if not account_can_access_project(actor, p.id):
            return jsonify({"ok": False, "error": "forbidden"}), 403
        if not account_may_use_machine_project_view(actor):
            return jsonify({"ok": False, "error": "forbidden"}), 403

        data = request.get_json(silent=True) or {}
        action = (data.get("action") or "create_link").strip().lower()
        if action not in ("create_link", "start_copy"):
            action = "create_link"
        start_copy = action == "start_copy"
        copy_mins: int | None = None
        if start_copy:
            try:
                copy_mins = int(data.get("copy_time_minutes"))
            except (TypeError, ValueError):
                copy_mins = None
            if copy_mins is None or copy_mins < 1:
                return jsonify({"ok": False, "error": "invalid_copy_time"}), 400
            assign_uid = directory_user_id_for_account(actor)
            if assign_uid is None:
                return jsonify({"ok": False, "error": "no_directory_user"}), 400

        try:
            disk_id = int(data.get("disk_id"))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "invalid_disk"}), 400

        hd = db.session.get(HardDisk, disk_id)
        if hd is None or hd.project_id != p.id:
            return jsonify({"ok": False, "error": "disk_not_found"}), 404

        try:
            unit_number = int(data.get("unit_number"))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "invalid_unit"}), 400
        if unit_number < 1:
            return jsonify({"ok": False, "error": "invalid_unit"}), 400

        day_name = (data.get("day_name") or "").strip()
        if not day_name:
            return jsonify({"ok": False, "error": "day_name_required"}), 400
        if len(day_name) > 50:
            return jsonify({"ok": False, "error": "day_name_too_long"}), 400

        raw_date = (data.get("shooting_date") or "").strip()
        try:
            sd = datetime.strptime(raw_date, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "invalid_date"}), 400

        try:
            video_tb = float(data.get("video_size_tb") or 0)
            audio_gb = float(data.get("audio_size_gb") or 0)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "invalid_sizes"}), 400
        if video_tb < 0 or audio_gb < 0:
            return jsonify({"ok": False, "error": "invalid_sizes"}), 400
        audio_tb = audio_gb / HDD_STORAGE_GB_PER_TB
        notes = (data.get("notes") or "").strip()

        existing_used = sum(
            float(u.video_size_tb or 0) + float(u.audio_size_tb or 0)
            for u in HardDiskUsage.query.filter_by(hard_disk_id=hd.id).all()
        )
        cap = float(hd.capacity_tb or 0)
        if existing_used + video_tb + audio_tb > cap + 1e-9:
            return jsonify({"ok": False, "error": "over_capacity"}), 400

        day = ShootingDay(
            project_id=p.id,
            unit_number=unit_number,
            day_name=day_name[:50],
            shooting_date=sd,
        )
        db.session.add(day)
        db.session.flush()
        db.session.add(
            HardDiskUsage(
                hard_disk_id=hd.id,
                shooting_day_id=day.id,
                video_size_tb=video_tb,
                audio_size_tb=audio_tb,
                notes=notes,
            )
        )
        copy_task_id: int | None = None
        if start_copy:
            if ProjectMember.query.filter_by(project_id=p.id, user_id=assign_uid).first() is None:
                db.session.add(ProjectMember(project_id=p.id, user_id=assign_uid))
            dm_group = TaskGroup.query.filter_by(name="DI / Machine").first()
            dm_gid = int(dm_group.id) if dm_group is not None else None
            starter = db.session.get(User, assign_uid)
            starter_label = (starter.name or "").strip() if starter is not None else actor.display_name
            copy_task = Task(
                title="Copy Material",
                description="",
                user_id=int(assign_uid),
                group_id=dm_gid,
                project_id=p.id,
                status="open",
                priority="high",
                copy_started_at=_utc_now(),
                copy_estimated_minutes=int(copy_mins),
                copy_day_name=day_name[:80],
                copy_unit_number=int(unit_number),
            )
            db.session.add(copy_task)
            db.session.flush()
            copy_task_id = int(copy_task.id)
            _notification_emit_to_project(
                project_id=p.id,
                rule=f"copy_task_started|{copy_task_id}",
                n_type="activity",
                severity="info",
                title="Copy task started",
                message=f"{starter_label} started copying material ({day_name[:80]}, Unit {unit_number}).",
                entity_type="task",
                entity_id=copy_task_id,
            )
        try:
            emit_shooting_day_created_activity(day, "machine")
            db.session.commit()
        except sa_exc.IntegrityError:
            db.session.rollback()
            return jsonify({"ok": False, "error": "conflict"}), 409
        evaluate_hdd_notifications(hd.id)
        db.session.commit()
        emit_tasks_feed_changed(p.id)
        out: dict = {"ok": True}
        if start_copy:
            out["copy_started"] = True
            out["task_id"] = copy_task_id
        return jsonify(out)

    @app.route("/machine/project/<int:project_id>/hard-disks/<int:disk_id>/usage", methods=["POST"])
    def machine_project_hard_disk_usage_add(project_id: int, disk_id: int):
        actor = account_from_session()
        if actor is None:
            abort(403)
        p = Project.query.get_or_404(project_id)
        if not account_can_access_project(actor, p.id):
            flash("You do not have access to that project.", "error")
            return redirect(url_for("machine_room"))
        if not account_may_use_machine_project_view(actor):
            abort(403)
        hd = db.session.get(HardDisk, disk_id)
        if hd is None or hd.project_id != p.id:
            flash("Hard disk not found.", "error")
            return redirect(url_for("machine_project", project_id=project_id))
        raw_day = (request.form.get("shooting_day_id") or "").strip()
        try:
            shooting_day_id = int(raw_day)
        except (TypeError, ValueError):
            flash("Select a shooting day.", "error")
            return redirect(url_for("machine_project", project_id=project_id))
        day = shooting_day_in_project(shooting_day_id, p.id)
        if day is None:
            flash("That shooting day is not on this project.", "error")
            return redirect(url_for("machine_project", project_id=project_id))
        try:
            video_tb = float((request.form.get("video_size_tb") or "0").strip() or 0)
            audio_gb = float((request.form.get("audio_size_gb") or "0").strip() or 0)
        except (TypeError, ValueError):
            flash("Video and audio sizes must be numbers.", "error")
            return redirect(url_for("machine_project", project_id=project_id))
        if video_tb < 0 or audio_gb < 0:
            flash("Sizes cannot be negative.", "error")
            return redirect(url_for("machine_project", project_id=project_id))
        audio_tb = audio_gb / HDD_STORAGE_GB_PER_TB
        notes = (request.form.get("notes") or "").strip()
        existing_used = sum(
            float(u.video_size_tb or 0) + float(u.audio_size_tb or 0)
            for u in HardDiskUsage.query.filter_by(hard_disk_id=hd.id).all()
        )
        cap = float(hd.capacity_tb or 0)
        if existing_used + video_tb + audio_tb > cap + 1e-9:
            flash("Video plus audio would exceed this disk capacity.", "error")
            return redirect(url_for("machine_project", project_id=project_id))
        db.session.add(
            HardDiskUsage(
                hard_disk_id=hd.id,
                shooting_day_id=day.id,
                video_size_tb=video_tb,
                audio_size_tb=audio_tb,
                notes=notes,
            )
        )
        try:
            db.session.commit()
        except sa_exc.IntegrityError:
            db.session.rollback()
            flash("That shooting day is already linked to this disk.", "error")
            return redirect(url_for("machine_project", project_id=project_id))
        evaluate_hdd_notifications(hd.id)
        db.session.commit()
        flash("Shooting day linked to disk.", "success")
        return redirect(url_for("machine_project", project_id=project_id))

    @app.route(
        "/machine/project/<int:project_id>/hard-disks/<int:disk_id>/usage/<int:usage_id>/delete",
        methods=["POST"],
    )
    def machine_project_hard_disk_usage_delete(project_id: int, disk_id: int, usage_id: int):
        actor = account_from_session()
        if actor is None:
            abort(403)
        p = Project.query.get_or_404(project_id)
        if not account_can_access_project(actor, p.id):
            flash("You do not have access to that project.", "error")
            return redirect(url_for("machine_room"))
        if not account_may_use_machine_project_view(actor):
            abort(403)
        hd = db.session.get(HardDisk, disk_id)
        if hd is None or hd.project_id != p.id:
            flash("Hard disk not found.", "error")
            return redirect(url_for("machine_project", project_id=project_id))
        row = db.session.get(HardDiskUsage, usage_id)
        if row is None or row.hard_disk_id != hd.id:
            flash("That link was not found.", "error")
            return redirect(url_for("machine_project", project_id=project_id))
        db.session.delete(row)
        db.session.commit()
        evaluate_hdd_notifications(hd.id)
        db.session.commit()
        flash("Shooting day unlinked from disk.", "success")
        return redirect(url_for("machine_project", project_id=project_id))

    @app.route("/projects/new", methods=["POST"])
    def projects_create():
        actor = db.session.get(Account, session.get("account_id"))
        if actor is None or not account_can_create_projects(actor):
            flash("Only administrators, super users, and producers can create projects.", "error")
            return redirect(url_for("projects_list"))
        name = (request.form.get("name") or "").strip()
        project_type = (request.form.get("project_type") or "").strip()
        production_house = (request.form.get("production_house") or "").strip()
        director = (request.form.get("director") or "").strip()
        if not name or not project_type or not production_house or not director:
            flash("All fields are required.", "error")
            return redirect(url_for("projects_list"))
        try:
            number_of_episodes = max(0, int((request.form.get("number_of_episodes") or "0").strip() or 0))
        except (TypeError, ValueError):
            number_of_episodes = 0
        if not _project_type_is_tv_series(project_type):
            number_of_episodes = 0
        try:
            estimated_shooting_days = max(
                0, int((request.form.get("estimated_shooting_days") or "0").strip() or 0)
            )
        except (TypeError, ValueError):
            estimated_shooting_days = 0
        mx = db.session.query(db.func.max(Project.sort_order)).scalar()
        next_ord = (mx if mx is not None else -1) + 1
        p = Project(
            name=name,
            project_type=project_type,
            production_house=production_house,
            director=director,
            sort_order=next_ord,
            number_of_episodes=number_of_episodes,
            estimated_shooting_days=estimated_shooting_days,
        )
        db.session.add(p)
        db.session.commit()
        ensure_project_main_audio_library(p.id)
        creator_uid = directory_user_id_for_account(actor)
        if creator_uid is not None:
            if ProjectMember.query.filter_by(project_id=p.id, user_id=creator_uid).first() is None:
                db.session.add(ProjectMember(project_id=p.id, user_id=creator_uid))
                db.session.commit()
        flash("Project created.", "success")
        return redirect(url_for("projects_list"))

    @app.route("/projects/reorder", methods=["POST"])
    def projects_reorder():
        actor = db.session.get(Account, session.get("account_id"))
        if actor is None or not actor.is_admin:
            return jsonify({"ok": False, "error": "forbidden"}), 403
        data = request.get_json(silent=True) or {}
        raw_ids = data.get("project_ids")
        if not isinstance(raw_ids, list) or not raw_ids:
            return jsonify({"ok": False, "error": "invalid"}), 400
        try:
            id_list = [int(x) for x in raw_ids]
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "invalid"}), 400
        all_ids = {p.id for p in Project.query.all()}
        if set(id_list) != all_ids or len(id_list) != len(all_ids):
            return jsonify({"ok": False, "error": "mismatch"}), 400
        for order, pid in enumerate(id_list):
            p = db.session.get(Project, pid)
            if p is not None:
                p.sort_order = order
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            app.logger.exception("projects_reorder")
            return jsonify({"ok": False, "error": "save"}), 500
        return jsonify({"ok": True})

    @app.route("/projects/<int:project_id>")
    def project_detail(project_id: int):
        acc = db.session.get(Account, session.get("account_id"))
        p = Project.query.get_or_404(project_id)
        if not account_can_access_project(acc, p.id):
            flash("You do not have access to that project.", "error")
            return redirect(url_for("projects_list"))
        project_tasks_all = (
            Task.query.options(
                joinedload(Task.group), joinedload(Task.assignee), joinedload(Task.project)
            )
            .filter_by(project_id=p.id)
            .order_by(Task.created_at.desc())
            .all()
        )
        active_tasks = [
            t
            for t in project_tasks_all
            if not t.archived and t.status in ("open", "in_progress")
        ]
        member_ids = {m.user_id for m in p.memberships}
        if member_ids:
            member_users = (
                User.query.options(joinedload(User.job_title))
                .filter(User.id.in_(member_ids))
                .all()
            )
            member_users.sort(key=lambda u: u.name.lower())
        else:
            member_users = []

        def _exclude_from_team_picker(u: User) -> bool:
            """Omit admin accounts and literal Admin identity from add-member picker."""
            if (u.name or "").strip().lower() == "admin":
                return True
            u_acc = u.account
            if u_acc is None:
                return False
            if u_acc.is_admin:
                return True
            if (u_acc.username or "").strip().lower() == "admin":
                return True
            return False

        all_users = (
            User.query.options(joinedload(User.job_title), joinedload(User.account))
            .order_by(User.name)
            .all()
        )
        available_to_add = [
            u
            for u in all_users
            if u.id not in member_ids and not _exclude_from_team_picker(u)
        ]
        task_groups = TaskGroup.query.order_by(
            TaskGroup.sort_order, TaskGroup.name
        ).all()
        titles_by_group: dict[int, list[TaskGroupTitle]] = defaultdict(list)
        for pt in TaskGroupTitle.query.order_by(
            TaskGroupTitle.sort_order, TaskGroupTitle.id
        ).all():
            titles_by_group[pt.group_id].append(pt)
        has_title_presets = TaskGroupTitle.query.count() > 0
        user_project_ids: dict[int, list[int]] = defaultdict(list)
        for pm in ProjectMember.query.all():
            user_project_ids[pm.user_id].append(pm.project_id)
        production_episode_count = max(0, int(p.number_of_episodes or 0))
        return render_template(
            "project_detail.html",
            project=p,
            active_tasks=active_tasks,
            member_users=member_users,
            available_to_add=available_to_add,
            task_groups=task_groups,
            titles_by_group=dict(titles_by_group),
            has_title_presets=has_title_presets,
            user_project_ids=dict(user_project_ids),
            production_episode_count=production_episode_count,
            workflow_active="overview",
        )

    @app.route("/projects/<int:project_id>/audio-library")
    def project_audio_library(project_id: int):
        acc = db.session.get(Account, session.get("account_id"))
        p = Project.query.get_or_404(project_id)
        if not account_can_access_project(acc, p.id):
            flash("You do not have access to that project.", "error")
            return redirect(url_for("projects_list"))
        main_audio_library = ensure_project_main_audio_library(p.id)
        audio_libraries = (
            ProjectAudioLibrary.query.filter_by(project_id=p.id)
            .order_by(ProjectAudioLibrary.parent_id.asc(), ProjectAudioLibrary.name.asc())
            .all()
        )
        linked_audio_folders = (
            ProjectAudioFolder.query.options(
                joinedload(ProjectAudioFolder.mount),
                joinedload(ProjectAudioFolder.library),
            )
            .filter_by(project_id=p.id)
            .order_by(ProjectAudioFolder.created_at.desc())
            .all()
        )
        audio_library_folders: dict[int, list[dict[str, object]]] = defaultdict(list)
        if linked_audio_folders:
            links_by_key: dict[tuple[int, int, str], ProjectAudioFolder] = {}
            for link in linked_audio_folders:
                key = (
                    int(link.library_id or 0),
                    int(link.mount_id or 0),
                    (link.folder_path or ""),
                )
                links_by_key[key] = link

            file_rows = (
                db.session.query(
                    ProjectAudioFolder.library_id.label("library_id"),
                    ProjectAudioFolder.mount_id.label("mount_id"),
                    ProjectAudioFolder.folder_path.label("folder_path"),
                    MusicFile.id.label("file_id"),
                    MusicFile.name.label("file_name"),
                    MusicFile.file_path.label("file_path"),
                    MusicFile.duration.label("duration"),
                    MusicFile.color_tag.label("color_tag"),
                    MusicFile.is_favorite.label("is_favorite"),
                )
                .join(
                    MusicFile,
                    and_(
                        MusicFile.mount_id == ProjectAudioFolder.mount_id,
                        MusicFile.folder == ProjectAudioFolder.folder_path,
                    ),
                )
                .filter(ProjectAudioFolder.project_id == p.id)
                .order_by(
                    ProjectAudioFolder.library_id.asc(),
                    ProjectAudioFolder.mount_id.asc(),
                    ProjectAudioFolder.folder_path.asc(),
                    MusicFile.name.asc(),
                )
                .all()
            )
            grouped_files: dict[tuple[int, int, str], list[dict[str, object]]] = defaultdict(list)
            for row in file_rows:
                gkey = (int(row.library_id or 0), int(row.mount_id or 0), row.folder_path or "")
                grouped_files[gkey].append(
                    {
                        "id": int(row.file_id),
                        "name": row.file_name or "",
                        "file_path": row.file_path or "",
                        "duration": float(row.duration or 0),
                        "color_tags": _music_parse_color_tags(row.color_tag),
                        "is_favorite": bool(row.is_favorite),
                    }
                )

            for key, link in links_by_key.items():
                lib_id, _mount_id, folder_path = key
                mount_name = (link.mount.name if link.mount else "Mount") or "Mount"
                audio_library_folders[lib_id].append(
                    {
                        "link_id": int(link.id),
                        "folder_path": folder_path,
                        "mount_name": mount_name,
                        "files": grouped_files.get(key, []),
                    }
                )

            for lib_id in list(audio_library_folders.keys()):
                audio_library_folders[lib_id].sort(
                    key=lambda x: (str(x["mount_name"]).lower(), str(x["folder_path"]).lower())
                )
        return render_template(
            "project_audio_library.html",
            project=p,
            main_audio_library=main_audio_library,
            audio_libraries=audio_libraries,
            linked_audio_folders=linked_audio_folders,
            audio_library_folders=dict(audio_library_folders),
            workflow_active="audio",
        )

    @app.route("/projects/<int:project_id>/completed")
    def project_completed_tasks(project_id: int):
        acc = db.session.get(Account, session.get("account_id"))
        p = Project.query.get_or_404(project_id)
        if not account_can_access_project(acc, p.id):
            flash("You do not have access to that project.", "error")
            return redirect(url_for("projects_list"))
        project_tasks_all = (
            Task.query.options(
                joinedload(Task.group), joinedload(Task.assignee), joinedload(Task.project)
            )
            .filter_by(project_id=p.id)
            .order_by(Task.created_at.desc())
            .all()
        )
        completed_tasks = [
            t for t in project_tasks_all if not t.archived and t.status == "done"
        ]
        return render_template(
            "project_completed_tasks.html",
            project=p,
            completed_tasks=completed_tasks,
        )

    @app.route("/projects/<int:project_id>/production")
    def project_production(project_id: int):
        acc = db.session.get(Account, session.get("account_id"))
        p = Project.query.get_or_404(project_id)
        if not account_can_access_project(acc, p.id):
            flash("You do not have access to that project.", "error")
            return redirect(url_for("projects_list"))
        shooting_days = (
            ShootingDay.query.filter_by(project_id=p.id)
            .options(
                joinedload(ShootingDay.scene_rows),
                joinedload(ShootingDay.pipeline_scenes),
            )
            .order_by(ShootingDay.shooting_date.asc(), ShootingDay.id.asc())
            .all()
        )
        production_day_totals = {
            d.id: shooting_day_total_seconds(d) for d in shooting_days
        }
        production_day_progress = {
            d.id: shooting_day_sync_edit_percentages(d) for d in shooting_days
        }
        return render_template(
            "project_production.html",
            project=p,
            production_section="days",
            shooting_days=shooting_days,
            production_day_totals=production_day_totals,
            production_day_progress=production_day_progress,
            workflow_active="shooting",
        )

    @app.route("/projects/<int:project_id>/production/day/<int:day_id>")
    def project_production_day(project_id: int, day_id: int):
        acc = db.session.get(Account, session.get("account_id"))
        p = Project.query.get_or_404(project_id)
        if not account_can_access_project(acc, p.id):
            flash("You do not have access to that project.", "error")
            return redirect(url_for("projects_list"))
        day = ShootingDay.query.filter_by(id=day_id, project_id=p.id).first()
        if day is None:
            abort(404)
        ordered_ids = (
            db.session.query(ShootingDay.id)
            .filter_by(project_id=p.id)
            .order_by(ShootingDay.shooting_date.asc(), ShootingDay.id.asc())
            .all()
        )
        id_list = [int(r[0]) for r in ordered_ids]
        day_display_index = id_list.index(day_id) + 1
        pipeline_links = (
            ShootingDayScene.query.filter_by(shooting_day_id=day.id)
            .order_by(
                ShootingDayScene.episode_number.asc(),
                ShootingDayScene.scene_label.asc(),
                ShootingDayScene.id.asc(),
            )
            .all()
        )
        total_duration_seconds = sum(shooting_day_scene_duration_seconds(link) for link in pipeline_links)
        max_episode_number = max(0, int(p.number_of_episodes or 0))
        total_scenes = len(pipeline_links)
        if total_scenes:
            sync_done_n = sum(1 for ln in pipeline_links if ln.sync_done)
            edit_done_n = sum(1 for ln in pipeline_links if ln.first_edit_done)
            sync_percentage = int(round(100.0 * sync_done_n / total_scenes))
            edit_percentage = int(round(100.0 * edit_done_n / total_scenes))
        else:
            sync_percentage = 0
            edit_percentage = 0
        return render_template(
            "project_production_day.html",
            project=p,
            production_section="days",
            production_day=day,
            day_display_index=day_display_index,
            pipeline_links=pipeline_links,
            total_duration_seconds=total_duration_seconds,
            max_episode_number=max_episode_number,
            total_scenes=total_scenes,
            sync_percentage=sync_percentage,
            edit_percentage=edit_percentage,
            workflow_active="shooting",
        )

    def _vfx_media_is_remote(s: str | None) -> bool:
        u = (s or "").strip().lower()
        return u.startswith("http://") or u.startswith("https://")

    def _vfx_is_video_media(s: str | None) -> bool:
        raw = (s or "").strip()
        if not raw:
            return False
        path = urlparse(raw).path if _vfx_media_is_remote(raw) else raw
        ext = os.path.splitext(path)[1].lower()
        return ext in {".mp4", ".webm", ".mov", ".m4v", ".mkv", ".avi"}

    def _next_scene_display_number_for_episode(project_id: int, episode_number: int) -> int:
        rows = (
            ShootingDayScene.query.join(ShootingDay, ShootingDayScene.shooting_day_id == ShootingDay.id)
            .filter(
                ShootingDay.project_id == int(project_id),
                ShootingDayScene.episode_number == int(episode_number),
            )
            .all()
        )
        mx = 0
        for sc in rows:
            n = _parse_scene_number_from_label(sc.scene_label, fallback=sc.scene_number or 1)
            mx = max(mx, n)
        return max(1, mx + 1)

    def _vfx_scene_aggregate_dot(shots: list[VfxShot]) -> str:
        if not shots:
            return "pending"
        statuses = [(getattr(s, "status", None) or "pending").lower() for s in shots]
        if any(x == "pending" for x in statuses):
            return "pending"
        if all(x == "approved" for x in statuses):
            return "approved"
        if any(x in ("review", "sent") for x in statuses):
            return "review"
        return "pending"

    def _vfx_version_preview_url(project_id: int, image: str) -> str:
        raw = (image or "").strip()
        if not raw:
            return ""
        if _vfx_media_is_remote(raw):
            return raw
        return url_for("project_vfx_version_file", project_id=project_id, filename=raw)

    def _scene_ref_preview_url(project_id: int, video_url: str) -> str:
        raw = (video_url or "").strip()
        if not raw:
            return ""
        if _vfx_media_is_remote(raw):
            return raw
        return url_for("project_vfx_scene_reference_file", project_id=project_id, filename=raw)

    def build_vfx_editor_payload(p: Project) -> dict:
        is_tv = _project_type_is_tv_series(p.project_type)
        rows = (
            ShootingDayScene.query.join(ShootingDay, ShootingDayScene.shooting_day_id == ShootingDay.id)
            .options(
                joinedload(ShootingDayScene.vfx_shots).joinedload(VfxShot.versions),
                joinedload(ShootingDayScene.vfx_shots).joinedload(VfxShot.comments).joinedload(
                    VfxShotComment.user
                ),
                joinedload(ShootingDayScene.scene_references),
            )
            .filter(ShootingDay.project_id == p.id)
            .order_by(
                ShootingDay.shooting_date.asc(),
                ShootingDay.id.asc(),
                ShootingDayScene.episode_number.asc(),
                ShootingDayScene.scene_number.asc(),
                ShootingDayScene.id.asc(),
            )
            .all()
        )
        scenes_out: list[dict] = []
        for sc in rows:
            shots = sorted(sc.vfx_shots or [], key=lambda s: int(s.shot_number or 0))
            sc_num = _parse_scene_number_from_label(sc.scene_label, fallback=sc.scene_number or 1)
            group_key = max(1, int(sc.episode_number or 1))
            group_label = f"Eps{group_key:02d}" if is_tv else f"Reel{group_key:02d}"
            shot_list: list[dict] = []
            for sh in shots:
                versions = sorted(sh.versions or [], key=lambda v: int(v.version_number or 0))
                cv = max((int(v.version_number or 0) for v in versions), default=0)
                comments_sorted = sorted(
                    sh.comments or [],
                    key=lambda c: (c.created_at or now_local(), c.id),
                )
                shot_list.append(
                    {
                        "id": sh.id,
                        "shotCode": sh.shot_code,
                        "department": (sh.department or "animation").strip().lower(),
                        "vendor": (sh.vendor or "in_house").strip().lower(),
                        "vendorName": sh.vendor_name or "",
                        "shotRefFrame": sh.shot_ref_frame or "",
                        "shotRefFrameUrl": _vfx_version_preview_url(p.id, sh.shot_ref_frame or ""),
                        "shotRefFrameIsVideo": _vfx_is_video_media(sh.shot_ref_frame),
                        "status": (sh.status or "pending").strip().lower(),
                        "sentAt": isoformat_stored_instant(
                            sh.sent_at if isinstance(sh.sent_at, datetime) else None
                        ),
                        "currentVersion": cv,
                        "versions": [
                            {
                                "id": v.id,
                                "versionNumber": int(v.version_number or 0),
                                "image": v.image or "",
                                "previewUrl": _vfx_version_preview_url(p.id, v.image or ""),
                                "isVideo": _vfx_is_video_media(v.image),
                                "comment": v.comment or "",
                                "createdAt": isoformat_stored_instant(
                                    v.created_at if isinstance(v.created_at, datetime) else None
                                ),
                            }
                            for v in versions
                        ],
                        "comments": [
                            {
                                "id": c.id,
                                "userId": c.user_id,
                                "userName": (c.user.name if c.user else "Unknown"),
                                "body": c.body or "",
                                "parentId": c.parent_id,
                                "resolved": bool(c.resolved),
                                "createdAt": isoformat_stored_instant(
                                    c.created_at if isinstance(c.created_at, datetime) else None
                                ),
                            }
                            for c in comments_sorted
                        ],
                    }
                )
            has_review = any((s.status or "").lower() == "review" for s in shots)
            refs = [rf for rf in (sc.scene_references or [])]
            scene_preview = refs[0] if refs else None
            scenes_out.append(
                {
                    "id": sc.id,
                    "groupKey": group_key,
                    "groupLabel": group_label,
                    "sceneDisplayNumber": sc_num,
                    "sceneTitle": f"Scene {sc_num}",
                    "sceneLabel": sc.scene_label or "",
                    "sceneNotes": sc.notes or "",
                    "needsVfx": bool(sc.needs_vfx),
                    "hasReviewShot": has_review,
                    "shotCount": len(shots),
                    "aggregateDot": _vfx_scene_aggregate_dot(shots),
                    "scenePreviewUrl": (
                        _scene_ref_preview_url(p.id, scene_preview.video_url or "") if scene_preview else ""
                    ),
                    "scenePreviewIsVideo": (
                        _vfx_is_video_media(scene_preview.video_url) if scene_preview else False
                    ),
                    "scenePreviewReferenceId": int(scene_preview.id) if scene_preview else None,
                    "references": [
                        {
                            "id": rf.id,
                            "videoUrl": rf.video_url or "",
                            "previewUrl": _scene_ref_preview_url(p.id, rf.video_url or ""),
                            "isRemote": _vfx_media_is_remote(rf.video_url),
                            "isVideo": _vfx_is_video_media(rf.video_url),
                            "notes": rf.notes or "",
                        }
                        for rf in refs
                    ],
                    "shots": shot_list,
                }
            )
        groups_map: dict[int, list[dict]] = defaultdict(list)
        for s in scenes_out:
            groups_map[int(s["groupKey"])].append(s)
        if is_tv:
            max_ep = max(0, int(p.number_of_episodes or 0))
            for epn in range(1, max_ep + 1):
                groups_map.setdefault(epn, [])
        groups = [
            {
                "key": k,
                "label": (f"Eps{k:02d}" if is_tv else f"Reel{k:02d}"),
                "scenes": groups_map[k],
            }
            for k in sorted(groups_map.keys())
        ]
        default_day = (
            ShootingDay.query.filter_by(project_id=p.id)
            .order_by(ShootingDay.shooting_date.desc(), ShootingDay.id.desc())
            .first()
        )
        return {
            "projectId": p.id,
            "isTv": is_tv,
            "statuses": list(VFX_EDITOR_STATUSES),
            "departments": list(VFX_DEPARTMENTS),
            "groups": groups,
            "scenes": scenes_out,
            "hasShootingDays": default_day is not None,
            "defaultShootingDayId": int(default_day.id) if default_day else None,
        }

    def build_vfx_editor_context(p: Project) -> dict:
        return {
            "vfx_editor_payload": build_vfx_editor_payload(p),
            "vfx_editor_statuses": VFX_EDITOR_STATUSES,
        }

    @app.route("/projects/<int:project_id>/vfx", methods=["GET"])
    def project_vfx(project_id: int):
        acc = db.session.get(Account, session.get("account_id"))
        p = Project.query.get_or_404(project_id)
        if not account_can_access_project(acc, p.id):
            flash("You do not have access to that project.", "error")
            return redirect(url_for("projects_list"))
        ctx = build_vfx_editor_context(p)
        return render_template(
            "project_vfx_editor.html",
            project=p,
            workflow_active="vfx",
            vfx_directory_user_id=directory_user_id_for_account(acc),
            **ctx,
        )

    @app.route("/projects/<int:project_id>/vfx/data", methods=["GET"])
    def project_vfx_data(project_id: int):
        acc = db.session.get(Account, session.get("account_id"))
        p = Project.query.get_or_404(project_id)
        if not account_can_access_project(acc, p.id):
            return jsonify({"ok": False, "error": "forbidden"}), 403
        return jsonify({"ok": True, "payload": build_vfx_editor_payload(p)})

    @app.route("/projects/<int:project_id>/vfx/version-file/<path:filename>", methods=["GET"])
    def project_vfx_version_file(project_id: int, filename: str):
        actor = account_from_session()
        if actor is None or not account_can_access_project(actor, project_id):
            abort(403)
        if "/" in filename or "\\" in filename or ".." in filename or filename.startswith("."):
            abort(404)
        ver = (
            VfxVersion.query.join(VfxShot, VfxVersion.shot_id == VfxShot.id)
            .filter(VfxShot.project_id == project_id, VfxVersion.image == filename)
            .first()
        )
        shot_ref = (
            VfxShot.query.filter_by(project_id=project_id, shot_ref_frame=filename).first()
            if ver is None
            else None
        )
        if ver is None and shot_ref is None:
            abort(404)
        return send_from_directory(vfx_version_upload_root, filename)

    @app.route("/projects/<int:project_id>/vfx/api/scenes/<int:scene_id>", methods=["POST"])
    def project_vfx_api_scene_update(project_id: int, scene_id: int):
        acc = db.session.get(Account, session.get("account_id"))
        if not account_can_access_project(acc, project_id):
            return jsonify({"ok": False, "error": "forbidden"}), 403
        scene = shooting_day_scene_for_project(scene_id, project_id)
        if scene is None:
            return jsonify({"ok": False, "error": "not_found"}), 404
        data = request.get_json(silent=True) or {}
        if "scene_label" in data:
            label = str(data.get("scene_label") or "").strip()
            if not label:
                return jsonify({"ok": False, "error": "scene_label_required"}), 400
            if len(label) > 120:
                return jsonify({"ok": False, "error": "scene_label_too_long"}), 400
            scene.scene_label = label
            scene.scene_number = _parse_scene_number_from_label(label, fallback=scene.scene_number or 1)
        if "notes" in data:
            notes = str(data.get("notes") or "").strip()
            if len(notes) > 20_000:
                return jsonify({"ok": False, "error": "notes_too_long"}), 400
            scene.notes = notes
        db.session.commit()
        return jsonify({"ok": True, "payload": build_vfx_editor_payload(Project.query.get(project_id))})

    @app.route("/projects/<int:project_id>/vfx/api/scenes/create", methods=["POST"])
    def project_vfx_api_scene_create(project_id: int):
        acc = db.session.get(Account, session.get("account_id"))
        p = Project.query.get_or_404(project_id)
        if not account_can_access_project(acc, p.id):
            return jsonify({"ok": False, "error": "forbidden"}), 403
        data = request.get_json(silent=True) or {}
        try:
            group_key = int(data.get("group_key"))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "invalid_group"}), 400
        if group_key < 1:
            return jsonify({"ok": False, "error": "invalid_group"}), 400
        if _project_type_is_tv_series(p.project_type):
            max_ep = max(0, int(p.number_of_episodes or 0))
            if max_ep < 1:
                return jsonify({"ok": False, "error": "no_episodes_configured"}), 400
            if group_key > max_ep:
                return jsonify({"ok": False, "error": "invalid_episode"}), 400
            ep_num = group_key
        else:
            ep_num = min(999, max(1, group_key))
        try:
            opt_day = int(data.get("shooting_day_id") or 0)
        except (TypeError, ValueError):
            opt_day = 0
        if opt_day:
            d = shooting_day_in_project(opt_day, project_id)
        else:
            d = (
                ShootingDay.query.filter_by(project_id=project_id)
                .order_by(ShootingDay.shooting_date.desc(), ShootingDay.id.desc())
                .first()
            )
        if d is None:
            return jsonify({"ok": False, "error": "no_shooting_day"}), 400
        raw_scene = (data.get("scene_label") or "").strip()
        if not raw_scene:
            raw_scene = str(_next_scene_display_number_for_episode(project_id, ep_num))
        if len(raw_scene) > 120:
            return jsonify({"ok": False, "error": "scene_too_long"}), 400
        notes = (data.get("notes") or "").strip()
        if len(notes) > 20_000:
            return jsonify({"ok": False, "error": "notes_too_long"}), 400
        dur_sec_i = 0
        dur_min = 0
        sn = _parse_scene_number_from_label(raw_scene, fallback=1)
        row = ShootingDayScene(
            shooting_day_id=d.id,
            scene_id=next_legacy_scene_id_for_day(d.id),
            episode_number=ep_num,
            scene_label=raw_scene,
            scene_number=max(1, int(sn or 1)),
            duration=dur_min,
            duration_seconds=dur_sec_i,
            actual_duration_minutes=dur_min,
            notes=notes,
            status="pending",
            sync_done=False,
            first_edit_done=False,
            needs_vfx=True,
        )
        db.session.add(row)
        db.session.commit()
        return jsonify({"ok": True, "payload": build_vfx_editor_payload(p)})

    @app.route("/projects/<int:project_id>/vfx/api/shots/<int:shot_id>", methods=["POST"])
    def project_vfx_api_shot_update(project_id: int, shot_id: int):
        acc = db.session.get(Account, session.get("account_id"))
        if not account_can_access_project(acc, project_id):
            return jsonify({"ok": False, "error": "forbidden"}), 403
        shot = VfxShot.query.filter_by(id=shot_id, project_id=project_id).first()
        if shot is None:
            return jsonify({"ok": False, "error": "not_found"}), 404
        data = request.get_json(silent=True) or {}
        if "status" in data:
            st = str(data.get("status") or "").strip().lower()
            if st not in VFX_EDITOR_STATUSES:
                return jsonify({"ok": False, "error": "invalid_status"}), 400
            shot.status = st
            if st == "sent" and shot.sent_at is None:
                shot.sent_at = now_local()
        if "department" in data:
            dep = str(data.get("department") or "").strip().lower()
            if dep not in VFX_DEPARTMENTS:
                return jsonify({"ok": False, "error": "invalid_department"}), 400
            shot.department = dep
        if "shot_code" in data:
            code = str(data.get("shot_code") or "").strip()
            if not code:
                return jsonify({"ok": False, "error": "shot_code_required"}), 400
            if len(code) > 64 or not re.fullmatch(r"[A-Za-z0-9_-]+", code):
                return jsonify({"ok": False, "error": "invalid_shot_code"}), 400
            clash = VfxShot.query.filter(
                VfxShot.project_id == project_id,
                VfxShot.shot_code == code,
                VfxShot.id != shot.id,
            ).first()
            if clash is not None:
                return jsonify({"ok": False, "error": "shot_code_exists"}), 400
            shot.shot_code = code
        if "vendor" in data:
            vendor = str(data.get("vendor") or "").strip().lower()
            if vendor not in ("in_house", "external"):
                return jsonify({"ok": False, "error": "invalid_vendor"}), 400
            shot.vendor = vendor
            if vendor != "external":
                shot.vendor_name = ""
        if "vendor_name" in data:
            vendor_name = str(data.get("vendor_name") or "").strip()
            if len(vendor_name) > 120:
                return jsonify({"ok": False, "error": "vendor_name_too_long"}), 400
            shot.vendor_name = vendor_name
        if "sent_at" in data:
            raw_sent = str(data.get("sent_at") or "").strip()
            if not raw_sent:
                shot.sent_at = None
            else:
                try:
                    shot.sent_at = datetime.fromisoformat(raw_sent)
                except ValueError:
                    return jsonify({"ok": False, "error": "invalid_sent_at"}), 400
        if "shot_briefing" in data:
            briefing = str(data.get("shot_briefing") or "").strip()
            if len(briefing) > 20_000:
                return jsonify({"ok": False, "error": "briefing_too_long"}), 400
            shot.shot_briefing = briefing
        db.session.commit()
        return jsonify({"ok": True, "payload": build_vfx_editor_payload(Project.query.get(project_id))})

    @app.route("/projects/<int:project_id>/vfx/api/shots/<int:shot_id>/ref-frame", methods=["POST"])
    def project_vfx_api_shot_ref_frame(project_id: int, shot_id: int):
        acc = db.session.get(Account, session.get("account_id"))
        if not account_can_access_project(acc, project_id):
            return jsonify({"ok": False, "error": "forbidden"}), 403
        shot = VfxShot.query.filter_by(id=shot_id, project_id=project_id).first()
        if shot is None:
            return jsonify({"ok": False, "error": "not_found"}), 404
        file_part = request.files.get("image_file") or request.files.get("file")
        if file_part is None or not (file_part.filename or "").strip():
            return jsonify({"ok": False, "error": "file_required"}), 400
        orig = secure_filename(file_part.filename) or "ref"
        ext = os.path.splitext(orig)[1].lower()
        if ext not in VFX_VERSION_ALLOWED_EXT:
            return jsonify({"ok": False, "error": "unsupported_format"}), 400
        raw = file_part.read()
        if len(raw) > VFX_VERSION_MAX_BYTES:
            return jsonify({"ok": False, "error": "file_too_large"}), 400
        fname = f"ref{shot.id}-{uuid.uuid4().hex}{ext}"
        dest = os.path.join(vfx_version_upload_root, fname)
        try:
            with open(dest, "wb") as f:
                f.write(raw)
        except OSError:
            return jsonify({"ok": False, "error": "save_failed"}), 500
        old = (shot.shot_ref_frame or "").strip()
        if old and not _vfx_media_is_remote(old):
            remove_vfx_version_file(old)
        shot.shot_ref_frame = fname
        db.session.commit()
        return jsonify({"ok": True, "payload": build_vfx_editor_payload(Project.query.get(project_id))})

    @app.route("/projects/<int:project_id>/vfx/api/shots/<int:shot_id>/delete", methods=["POST"])
    def project_vfx_api_shot_delete(project_id: int, shot_id: int):
        acc = db.session.get(Account, session.get("account_id"))
        if not account_can_access_project(acc, project_id):
            return jsonify({"ok": False, "error": "forbidden"}), 403
        shot = VfxShot.query.filter_by(id=shot_id, project_id=project_id).first()
        if shot is None:
            return jsonify({"ok": False, "error": "not_found"}), 404
        for ver in shot.versions or []:
            img = (ver.image or "").strip()
            if img and not _vfx_media_is_remote(img):
                remove_vfx_version_file(img)
        rf = (shot.shot_ref_frame or "").strip()
        if rf and not _vfx_media_is_remote(rf):
            remove_vfx_version_file(rf)
        db.session.delete(shot)
        db.session.commit()
        return jsonify({"ok": True, "payload": build_vfx_editor_payload(Project.query.get(project_id))})

    @app.route("/projects/<int:project_id>/vfx/api/scenes/<int:scene_id>/shots", methods=["POST"])
    def project_vfx_api_scene_add_shot_json(project_id: int, scene_id: int):
        acc = db.session.get(Account, session.get("account_id"))
        if not account_can_access_project(acc, project_id):
            return jsonify({"ok": False, "error": "forbidden"}), 403
        scene = shooting_day_scene_for_project(scene_id, project_id)
        if scene is None:
            return jsonify({"ok": False, "error": "not_found"}), 404
        if not bool(scene.needs_vfx):
            return jsonify({"ok": False, "error": "needs_vfx_required"}), 400
        data = request.get_json(silent=True) or {}
        dep = str(data.get("department") or "animation").strip().lower()
        if dep not in VFX_DEPARTMENTS:
            return jsonify({"ok": False, "error": "invalid_department"}), 400
        ep_num = max(1, int(scene.episode_number or 1))
        scene_num = _parse_scene_number_from_label(scene.scene_label, fallback=scene.scene_number or 1)
        shot_num = _next_vfx_shot_number(scene.id)
        shot = VfxShot(
            project_id=project_id,
            scene_id=scene.id,
            episode_number=ep_num,
            reel_number=None,
            shot_number=shot_num,
            shot_code=_build_vfx_shot_code(ep_num, scene_num, shot_num),
            shot_briefing="",
            department=dep,
            status="pending",
            created_at=now_local(),
        )
        db.session.add(shot)
        db.session.commit()
        return jsonify({"ok": True, "payload": build_vfx_editor_payload(Project.query.get(project_id))})

    @app.route("/projects/<int:project_id>/vfx/api/scenes/<int:scene_id>/shots/bulk", methods=["POST"])
    def project_vfx_api_scene_bulk_shots(project_id: int, scene_id: int):
        acc = db.session.get(Account, session.get("account_id"))
        if not account_can_access_project(acc, project_id):
            return jsonify({"ok": False, "error": "forbidden"}), 403
        scene = shooting_day_scene_for_project(scene_id, project_id)
        if scene is None:
            return jsonify({"ok": False, "error": "not_found"}), 404
        if not bool(scene.needs_vfx):
            return jsonify({"ok": False, "error": "needs_vfx_required"}), 400
        data = request.get_json(silent=True) or {}
        start_n = max(1, int(data.get("start") or 1))
        end_n = max(start_n, int(data.get("end") or 10))
        if end_n > 99:
            return jsonify({"ok": False, "error": "range_too_large"}), 400
        ep_num = max(1, int(scene.episode_number or 1))
        scene_num = _parse_scene_number_from_label(scene.scene_label, fallback=scene.scene_number or 1)
        existing_nums = {int(s.shot_number) for s in (scene.vfx_shots or [])}
        cycle = list(VFX_DEPARTMENTS)
        created = 0
        for n in range(start_n, end_n + 1):
            if n in existing_nums:
                continue
            dep = cycle[(n - 1) % len(cycle)]
            sh = VfxShot(
                project_id=project_id,
                scene_id=scene.id,
                episode_number=ep_num,
                reel_number=None,
                shot_number=n,
                shot_code=_build_vfx_shot_code(ep_num, scene_num, n),
                shot_briefing="",
                department=dep,
                status="pending",
                created_at=now_local(),
            )
            db.session.add(sh)
            created += 1
        db.session.commit()
        return jsonify(
            {"ok": True, "created": created, "payload": build_vfx_editor_payload(Project.query.get(project_id))}
        )

    @app.route("/projects/<int:project_id>/vfx/api/shots/<int:shot_id>/versions", methods=["POST"])
    def project_vfx_api_add_version(project_id: int, shot_id: int):
        acc = db.session.get(Account, session.get("account_id"))
        if not account_can_access_project(acc, project_id):
            return jsonify({"ok": False, "error": "forbidden"}), 403
        shot = VfxShot.query.filter_by(id=shot_id, project_id=project_id).first()
        if shot is None:
            return jsonify({"ok": False, "error": "not_found"}), 404
        image = ""
        comment = ""
        file_part = request.files.get("image_file") or request.files.get("file")
        if file_part and (file_part.filename or "").strip():
            orig = secure_filename(file_part.filename) or "version"
            ext = os.path.splitext(orig)[1].lower()
            if ext not in VFX_VERSION_ALLOWED_EXT:
                return jsonify({"ok": False, "error": "unsupported_format"}), 400
            raw = file_part.read()
            if len(raw) > VFX_VERSION_MAX_BYTES:
                return jsonify({"ok": False, "error": "file_too_large"}), 400
            fname = f"vfx{shot.id}-{uuid.uuid4().hex}{ext}"
            dest = os.path.join(vfx_version_upload_root, fname)
            try:
                with open(dest, "wb") as f:
                    f.write(raw)
            except OSError:
                return jsonify({"ok": False, "error": "save_failed"}), 500
            image = fname
            comment = (request.form.get("comment") or "").strip()
        if not image and request.is_json:
            body = request.get_json(silent=True) or {}
            image = (body.get("image") or "").strip()
            comment = (body.get("comment") or "").strip()
        elif not image:
            image = (request.form.get("image") or "").strip()
            comment = (request.form.get("comment") or "").strip()
        if not image:
            return jsonify({"ok": False, "error": "image_required"}), 400
        if len(comment) > 20_000:
            return jsonify({"ok": False, "error": "comment_too_long"}), 400
        next_version = (
            db.session.query(func.max(VfxVersion.version_number)).filter(VfxVersion.shot_id == shot.id).scalar()
        )
        ver = VfxVersion(
            shot_id=shot.id,
            version_number=max(0, int(next_version or 0)) + 1,
            image=image,
            comment=comment,
            created_at=now_local(),
        )
        db.session.add(ver)
        db.session.commit()
        return jsonify({"ok": True, "payload": build_vfx_editor_payload(Project.query.get(project_id))})

    @app.route("/projects/<int:project_id>/vfx/api/shots/<int:shot_id>/comments", methods=["POST"])
    def project_vfx_api_shot_comment_add(project_id: int, shot_id: int):
        acc = db.session.get(Account, session.get("account_id"))
        if not account_can_access_project(acc, project_id):
            return jsonify({"ok": False, "error": "forbidden"}), 403
        uid = directory_user_id_for_account(acc)
        if uid is None:
            return jsonify({"ok": False, "error": "no_directory_user"}), 403
        shot = VfxShot.query.filter_by(id=shot_id, project_id=project_id).first()
        if shot is None:
            return jsonify({"ok": False, "error": "not_found"}), 404
        data = request.get_json(silent=True) or {}
        body = (data.get("body") or "").strip()
        if not body:
            return jsonify({"ok": False, "error": "empty_body"}), 400
        if len(body) > 20_000:
            return jsonify({"ok": False, "error": "body_too_long"}), 400
        parent_id = data.get("parent_id")
        pid: int | None = None
        if parent_id is not None and str(parent_id).strip() != "":
            try:
                pid = int(parent_id)
            except (TypeError, ValueError):
                pid = None
            if pid is not None:
                parent = VfxShotComment.query.filter_by(id=pid, shot_id=shot.id).first()
                if parent is None:
                    return jsonify({"ok": False, "error": "invalid_parent"}), 400
        row = VfxShotComment(
            shot_id=shot.id,
            user_id=uid,
            parent_id=pid,
            body=body,
            resolved=False,
            created_at=now_local(),
        )
        db.session.add(row)
        db.session.commit()
        u = db.session.get(User, uid)
        comment_out = {
            "id": row.id,
            "userId": uid,
            "userName": (u.name if u else "Unknown"),
            "body": row.body,
            "parentId": row.parent_id,
            "resolved": False,
            "createdAt": isoformat_stored_instant(row.created_at),
        }
        return jsonify({"ok": True, "comment": comment_out})

    @app.route("/projects/<int:project_id>/vfx/api/comments/<int:comment_id>/resolve", methods=["POST"])
    def project_vfx_api_comment_resolve(project_id: int, comment_id: int):
        acc = db.session.get(Account, session.get("account_id"))
        if not account_can_access_project(acc, project_id):
            return jsonify({"ok": False, "error": "forbidden"}), 403
        row = (
            VfxShotComment.query.join(VfxShot, VfxShotComment.shot_id == VfxShot.id)
            .filter(VfxShotComment.id == comment_id, VfxShot.project_id == project_id)
            .first()
        )
        if row is None:
            return jsonify({"ok": False, "error": "not_found"}), 404
        row.resolved = True
        db.session.commit()
        return jsonify({"ok": True, "commentId": comment_id, "resolved": True})

    @app.route("/projects/<int:project_id>/vfx/scenes/<int:scene_id>/shots", methods=["POST"])
    def project_vfx_scene_add_shot(project_id: int, scene_id: int):
        acc = db.session.get(Account, session.get("account_id"))
        if not account_can_access_project(acc, project_id):
            flash("You do not have access to that project.", "error")
            return redirect(url_for("projects_list"))
        scene = shooting_day_scene_for_project(scene_id, project_id)
        if scene is None:
            abort(404)
        if not bool(scene.needs_vfx):
            flash("This scene is not marked as Needs VFX.", "error")
            return redirect(url_for("project_vfx", project_id=project_id))
        ep_num = max(1, int(scene.episode_number or 1))
        scene_num = _parse_scene_number_from_label(scene.scene_label, fallback=scene.scene_number or 1)
        shot_num = _next_vfx_shot_number(scene.id)
        dep = (request.form.get("department") or "animation").strip().lower()
        if dep not in VFX_DEPARTMENTS:
            dep = "animation"
        shot = VfxShot(
            project_id=project_id,
            scene_id=scene.id,
            episode_number=ep_num,
            reel_number=None,
            shot_number=shot_num,
            shot_code=_build_vfx_shot_code(ep_num, scene_num, shot_num),
            shot_briefing="",
            department=dep,
            status="pending",
            created_at=now_local(),
        )
        db.session.add(shot)
        db.session.commit()
        if (request.headers.get("X-VFX-Response") or "").strip().lower() == "json":
            return jsonify({"ok": True, "payload": build_vfx_editor_payload(Project.query.get(project_id))})
        flash(f"Shot created: {shot.shot_code}", "success")
        return redirect(url_for("project_vfx", project_id=project_id))

    @app.route("/projects/<int:project_id>/vfx/shots/<int:shot_id>/update", methods=["POST"])
    def project_vfx_shot_update(project_id: int, shot_id: int):
        acc = db.session.get(Account, session.get("account_id"))
        if not account_can_access_project(acc, project_id):
            flash("You do not have access to that project.", "error")
            return redirect(url_for("projects_list"))
        shot = (
            VfxShot.query.options(joinedload(VfxShot.scene).joinedload(ShootingDayScene.shooting_day))
            .filter_by(id=shot_id, project_id=project_id)
            .first()
        )
        if shot is None:
            abort(404)
        status = (request.form.get("status") or shot.status or "pending").strip().lower()
        if status not in VFX_EDITOR_STATUSES:
            flash("Invalid shot status.", "error")
            return redirect(url_for("project_vfx", project_id=project_id))
        briefing = (request.form.get("shot_briefing") or "").strip()
        if len(briefing) > 20_000:
            flash("Shot briefing is too long.", "error")
            return redirect(url_for("project_vfx", project_id=project_id))
        dep = (request.form.get("department") or shot.department or "animation").strip().lower()
        if dep not in VFX_DEPARTMENTS:
            flash("Invalid department.", "error")
            return redirect(url_for("project_vfx", project_id=project_id))
        shot.status = status
        shot.shot_briefing = briefing
        shot.department = dep
        db.session.commit()
        flash(f"Updated {shot.shot_code}.", "success")
        return redirect(url_for("project_vfx", project_id=project_id))

    @app.route("/projects/<int:project_id>/vfx/shots/<int:shot_id>/versions", methods=["POST"])
    def project_vfx_add_version(project_id: int, shot_id: int):
        acc = db.session.get(Account, session.get("account_id"))
        if not account_can_access_project(acc, project_id):
            flash("You do not have access to that project.", "error")
            return redirect(url_for("projects_list"))
        shot = VfxShot.query.filter_by(id=shot_id, project_id=project_id).first()
        if shot is None:
            abort(404)
        image = (request.form.get("image") or "").strip()
        comment = (request.form.get("comment") or "").strip()
        if not image:
            flash("Version image URL/path is required.", "error")
            return redirect(url_for("project_vfx", project_id=project_id))
        if len(comment) > 20_000:
            flash("Version comment is too long.", "error")
            return redirect(url_for("project_vfx", project_id=project_id))
        next_version = (
            db.session.query(func.max(VfxVersion.version_number))
            .filter(VfxVersion.shot_id == shot.id)
            .scalar()
        )
        ver = VfxVersion(
            shot_id=shot.id,
            version_number=max(0, int(next_version or 0)) + 1,
            image=image,
            comment=comment,
            created_at=now_local(),
        )
        db.session.add(ver)
        db.session.commit()
        flash(f"Added {shot.shot_code} v{ver.version_number}.", "success")
        return redirect(url_for("project_vfx", project_id=project_id))

    @app.route("/projects/<int:project_id>/vfx/scenes/<int:scene_id>/references", methods=["POST"])
    def project_vfx_add_scene_reference(project_id: int, scene_id: int):
        acc = db.session.get(Account, session.get("account_id"))
        if not account_can_access_project(acc, project_id):
            flash("You do not have access to that project.", "error")
            return redirect(url_for("projects_list"))
        scene = shooting_day_scene_for_project(scene_id, project_id)
        if scene is None:
            abort(404)
        video_url = (request.form.get("video_url") or "").strip()
        video_file = request.files.get("video_file")
        if video_file and (video_file.filename or "").strip():
            orig = secure_filename(video_file.filename) or "reference"
            ext = os.path.splitext(orig)[1].lower()
            if ext not in SCENE_REF_ALLOWED_EXT:
                flash("Unsupported video format.", "error")
                return redirect(url_for("project_vfx", project_id=project_id))
            raw = video_file.read()
            if len(raw) > SCENE_REF_MAX_BYTES:
                flash("Video file is too large.", "error")
                return redirect(url_for("project_vfx", project_id=project_id))
            fname = f"sc{scene.id}-{uuid.uuid4().hex}{ext}"
            dest = os.path.join(scene_ref_upload_root, fname)
            try:
                with open(dest, "wb") as f:
                    f.write(raw)
            except OSError:
                flash("Could not save uploaded video.", "error")
                return redirect(url_for("project_vfx", project_id=project_id))
            video_url = fname
        notes = (request.form.get("notes") or "").strip()
        if not video_url:
            flash("Reference video URL/path is required.", "error")
            return redirect(url_for("project_vfx", project_id=project_id))
        if len(notes) > 20_000:
            flash("Reference notes are too long.", "error")
            return redirect(url_for("project_vfx", project_id=project_id))
        ref = SceneReference(
            scene_id=scene.id,
            video_url=video_url,
            notes=notes,
            created_at=now_local(),
        )
        db.session.add(ref)
        db.session.commit()
        if (request.headers.get("X-VFX-Response") or "").strip().lower() == "json":
            return jsonify({"ok": True, "payload": build_vfx_editor_payload(Project.query.get(project_id))})
        flash("Scene reference added.", "success")
        return redirect(url_for("project_vfx", project_id=project_id))

    @app.route("/projects/<int:project_id>/vfx/api/references/<int:reference_id>/delete", methods=["POST"])
    def project_vfx_api_reference_delete(project_id: int, reference_id: int):
        acc = db.session.get(Account, session.get("account_id"))
        if not account_can_access_project(acc, project_id):
            return jsonify({"ok": False, "error": "forbidden"}), 403
        ref = (
            SceneReference.query.join(ShootingDayScene, SceneReference.scene_id == ShootingDayScene.id)
            .join(ShootingDay, ShootingDayScene.shooting_day_id == ShootingDay.id)
            .filter(
                SceneReference.id == reference_id,
                ShootingDay.project_id == project_id,
            )
            .first()
        )
        if ref is None:
            return jsonify({"ok": False, "error": "not_found"}), 404
        if not _vfx_media_is_remote(ref.video_url):
            remove_scene_reference_file(ref.video_url)
        db.session.delete(ref)
        db.session.commit()
        return jsonify({"ok": True, "payload": build_vfx_editor_payload(Project.query.get(project_id))})

    @app.route("/projects/<int:project_id>/vfx/scene-reference-file/<path:filename>", methods=["GET"])
    def project_vfx_scene_reference_file(project_id: int, filename: str):
        actor = account_from_session()
        if actor is None or not account_can_access_project(actor, project_id):
            abort(403)
        if "/" in filename or "\\" in filename or ".." in filename or filename.startswith("."):
            abort(404)
        ref = (
            SceneReference.query.join(ShootingDayScene, SceneReference.scene_id == ShootingDayScene.id)
            .join(ShootingDay, ShootingDayScene.shooting_day_id == ShootingDay.id)
            .filter(
                ShootingDay.project_id == project_id,
                SceneReference.video_url == filename,
            )
            .first()
        )
        if ref is None:
            abort(404)
        return send_from_directory(scene_ref_upload_root, filename)

    @app.route("/projects/<int:project_id>/episodes", methods=["GET", "POST"])
    def project_episodes(project_id: int):
        acc = db.session.get(Account, session.get("account_id"))
        p = Project.query.get_or_404(project_id)
        if not account_can_access_project(acc, p.id):
            flash("You do not have access to that project.", "error")
            return redirect(url_for("projects_list"))
        episode_count = max(0, int(p.number_of_episodes or 0))
        links = (
            ShootingDayScene.query.join(ShootingDay, ShootingDayScene.shooting_day_id == ShootingDay.id)
            .filter(ShootingDay.project_id == p.id)
            .all()
        )
        by_episode: dict[int, list[ShootingDayScene]] = defaultdict(list)
        for row in links:
            ep_num = int(row.episode_number or 0)
            if 1 <= ep_num <= episode_count:
                by_episode[ep_num].append(row)
        episodes = []
        for ep_num in range(1, episode_count + 1):
            rows = by_episode.get(ep_num, [])
            _ts = sum(shooting_day_scene_duration_seconds(r) for r in rows)
            total_duration = (_ts + 59) // 60 if _ts else 0
            sync_done = bool(rows) and all(bool(r.sync_done) for r in rows)
            first_edit_done = bool(rows) and all(bool(r.first_edit_done) for r in rows)
            episodes.append(
                {
                    "episode_number": ep_num,
                    "scene_count": len(rows),
                    "total_duration": total_duration,
                    "sync_done": sync_done,
                    "first_edit_done": first_edit_done,
                }
            )
        return render_template(
            "project_episodes.html",
            project=p,
            episodes=episodes,
            workflow_active="episodes",
        )

    @app.route("/projects/<int:project_id>/episode/<int:episode_id>", methods=["GET", "POST"])
    def project_episode_detail(project_id: int, episode_id: int):
        return redirect(url_for("project_episodes", project_id=project_id))

    @app.route("/projects/<int:project_id>/episode/<int:episode_id>/scene/<int:scene_id>/edit", methods=["GET", "POST"])
    def project_scene_edit(project_id: int, episode_id: int, scene_id: int):
        return redirect(url_for("project_episodes", project_id=project_id))

    @app.route(
        "/projects/<int:project_id>/production/days/<int:day_id>/assign-scene",
        methods=["POST"],
    )
    def shooting_day_assign_scene(project_id: int, day_id: int):
        acc = db.session.get(Account, session.get("account_id"))
        if not account_can_access_project(acc, project_id):
            flash("You do not have access to that project.", "error")
            return redirect(url_for("projects_list"))
        d = shooting_day_in_project(day_id, project_id)
        if d is None:
            abort(404)
        max_episode = max(0, int(d.project.number_of_episodes or 0))
        if max_episode < 1:
            flash("Set Number of episodes on the project before adding rows.", "error")
            return redirect(url_for("project_production_day", project_id=project_id, day_id=day_id))
        raw_ep = (request.form.get("episode_number") or "").strip()
        raw_scene = (request.form.get("scene_label") or request.form.get("scene_number") or "").strip()
        raw_duration = (request.form.get("duration") or "").strip()
        notes = (request.form.get("notes") or "").strip()
        sync_done = request.form.get("sync_done") == "1"
        first_edit_done = request.form.get("first_edit_done") == "1"
        needs_vfx = request.form.get("needs_vfx") == "1"
        try:
            ep_num = int(raw_ep)
        except ValueError:
            flash("Episode must be a whole number.", "error")
            return redirect(url_for("project_production_day", project_id=project_id, day_id=day_id))
        if ep_num < 1 or ep_num > max_episode:
            flash(f"Episode must be between 1 and {max_episode}.", "error")
            return redirect(url_for("project_production_day", project_id=project_id, day_id=day_id))
        if not raw_scene:
            flash("Scene is required.", "error")
            return redirect(url_for("project_production_day", project_id=project_id, day_id=day_id))
        if len(raw_scene) > 120:
            flash("Scene is too long (120 characters max).", "error")
            return redirect(url_for("project_production_day", project_id=project_id, day_id=day_id))
        dur_sec = parse_shooting_day_duration_seconds(raw_duration)
        if dur_sec is None:
            flash("Duration must be M:SS (e.g. 4:30), H:MM:SS, or whole minutes.", "error")
            return redirect(url_for("project_production_day", project_id=project_id, day_id=day_id))
        if len(notes) > 20_000:
            flash("Notes are too long.", "error")
            return redirect(url_for("project_production_day", project_id=project_id, day_id=day_id))
        dur_sec_i = max(0, int(dur_sec))
        dur_min = (dur_sec_i + 59) // 60 if dur_sec_i else 0
        row = ShootingDayScene(
            shooting_day_id=day_id,
            scene_id=next_legacy_scene_id_for_day(day_id),
            episode_number=ep_num,
            scene_label=raw_scene,
            scene_number=1,
            duration=dur_min,
            duration_seconds=dur_sec_i,
            actual_duration_minutes=dur_min,
            notes=notes,
            status="done" if (sync_done and first_edit_done) else "pending",
            sync_done=sync_done,
            first_edit_done=first_edit_done,
            needs_vfx=needs_vfx,
        )
        db.session.add(row)
        db.session.commit()
        flash("Row added to this shooting day.", "success")
        return redirect(
            url_for("project_production_day", project_id=project_id, day_id=day_id, new=row.id)
        )

    @app.route(
        "/projects/<int:project_id>/shooting-day-scenes/<int:link_id>/update",
        methods=["POST"],
    )
    def shooting_day_scene_update(project_id: int, link_id: int):
        acc = db.session.get(Account, session.get("account_id"))
        if not account_can_access_project(acc, project_id):
            flash("You do not have access to that project.", "error")
            return redirect(url_for("projects_list"))
        link = shooting_day_scene_for_project(link_id, project_id)
        if link is None:
            abort(404)
        day_id = link.shooting_day_id
        max_episode = max(0, int(link.shooting_day.project.number_of_episodes or 0))
        if max_episode < 1:
            flash("Set Number of episodes on the project before editing rows.", "error")
            return redirect(url_for("project_production_day", project_id=project_id, day_id=day_id))
        raw_ep = (request.form.get("episode_number") or "").strip()
        raw_scene = (request.form.get("scene_label") or request.form.get("scene_number") or "").strip()
        raw_dur = (request.form.get("duration") or "").strip()
        try:
            ep_num = int(raw_ep)
        except ValueError:
            flash("Episode must be a whole number.", "error")
            return redirect(url_for("project_production_day", project_id=project_id, day_id=day_id))
        if ep_num < 1 or ep_num > max_episode:
            flash(f"Episode must be between 1 and {max_episode}.", "error")
            return redirect(url_for("project_production_day", project_id=project_id, day_id=day_id))
        if not raw_scene:
            flash("Scene is required.", "error")
            return redirect(url_for("project_production_day", project_id=project_id, day_id=day_id))
        if len(raw_scene) > 120:
            flash("Scene is too long (120 characters max).", "error")
            return redirect(url_for("project_production_day", project_id=project_id, day_id=day_id))
        dur_sec = parse_shooting_day_duration_seconds(raw_dur)
        if dur_sec is None:
            flash("Duration must be M:SS (e.g. 4:30), H:MM:SS, or whole minutes.", "error")
            return redirect(url_for("project_production_day", project_id=project_id, day_id=day_id))
        notes = (request.form.get("notes") or "").strip()
        if len(notes) > 20_000:
            flash("Notes are too long.", "error")
            return redirect(url_for("project_production_day", project_id=project_id, day_id=day_id))
        dur_sec_i = max(0, int(dur_sec))
        dur_min = (dur_sec_i + 59) // 60 if dur_sec_i else 0
        link.episode_number = ep_num
        link.scene_label = raw_scene
        link.scene_number = 1
        link.duration_seconds = dur_sec_i
        link.duration = dur_min
        link.actual_duration_minutes = dur_min
        link.notes = notes
        link.sync_done = request.form.get("sync_done") == "1"
        link.first_edit_done = request.form.get("first_edit_done") == "1"
        link.needs_vfx = request.form.get("needs_vfx") == "1"
        link.status = "done" if (link.sync_done and link.first_edit_done) else "pending"
        db.session.commit()
        flash("Shooting day row updated.", "success")
        return redirect(url_for("project_production_day", project_id=project_id, day_id=day_id))

    @app.route(
        "/projects/<int:project_id>/shooting-day-scenes/<int:link_id>/delete",
        methods=["POST"],
    )
    def shooting_day_scene_delete(project_id: int, link_id: int):
        acc = db.session.get(Account, session.get("account_id"))
        if not account_can_access_project(acc, project_id):
            flash("You do not have access to that project.", "error")
            return redirect(url_for("projects_list"))
        link = shooting_day_scene_for_project(link_id, project_id)
        if link is None:
            abort(404)
        day_id = link.shooting_day_id
        Booking.query.filter_by(scene_id=link_id).update(
            {Booking.scene_id: None},
            synchronize_session=False,
        )
        shot_ids = [int(s.id) for s in (link.vfx_shots or [])]
        if shot_ids:
            for sh in link.vfx_shots or []:
                rf = (sh.shot_ref_frame or "").strip()
                if rf and not _vfx_media_is_remote(rf):
                    remove_vfx_version_file(rf)
            for ver in VfxVersion.query.filter(VfxVersion.shot_id.in_(shot_ids)).all():
                img = (ver.image or "").strip()
                if img and not (
                    img.lower().startswith("http://") or img.lower().startswith("https://")
                ):
                    remove_vfx_version_file(img)
            VfxShotComment.query.filter(VfxShotComment.shot_id.in_(shot_ids)).delete(
                synchronize_session=False
            )
            VfxVersion.query.filter(VfxVersion.shot_id.in_(shot_ids)).delete(synchronize_session=False)
            VfxShot.query.filter(VfxShot.id.in_(shot_ids)).delete(synchronize_session=False)
        for rf in SceneReference.query.filter_by(scene_id=link_id).all():
            remove_scene_reference_file(rf.video_url)
        SceneReference.query.filter_by(scene_id=link_id).delete(synchronize_session=False)
        db.session.delete(link)
        db.session.commit()
        if (request.headers.get("X-VFX-Response") or "").strip().lower() == "json":
            return jsonify({"ok": True, "payload": build_vfx_editor_payload(Project.query.get(project_id))})
        flash("Scene row removed from this day.", "success")
        return redirect(url_for("project_production_day", project_id=project_id, day_id=day_id))

    @app.route("/projects/<int:project_id>/scenes/<int:scene_id>/mark-done", methods=["POST"])
    def production_scene_mark_done(project_id: int, scene_id: int):
        return redirect(url_for("project_episodes", project_id=project_id))

    @app.route("/projects/<int:project_id>/chat/messages", methods=["GET", "POST"])
    def project_chat_messages(project_id: int):
        acc = db.session.get(Account, session.get("account_id"))
        if not account_may_use_project_chat(acc, project_id):
            return jsonify({"error": "forbidden"}), 403
        viewer_uid = directory_user_id_for_account(acc)

        if request.method == "GET":
            rows = (
                ChatMessage.query.filter_by(project_id=project_id)
                .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
                .all()
            )
            ids = [m.id for m in rows]
            react_by_mid: dict[int, list[ChatMessageReaction]] = defaultdict(list)
            if ids:
                for r in ChatMessageReaction.query.filter(
                    ChatMessageReaction.message_id.in_(ids)
                ).all():
                    react_by_mid[r.message_id].append(r)
            return jsonify(
                {
                    "messages": [
                        chat_message_json(
                            m, viewer_uid, reactions=react_by_mid.get(m.id, [])
                        )
                        for m in rows
                    ],
                }
            )

        # POST — multipart: text and/or one attachment (image or audio)
        text_raw = (request.form.get("message") or request.form.get("text") or "").strip()
        audio_part = request.files.get("audio")
        image_part = request.files.get("image") or request.files.get("file")

        audio_raw: bytes | None = None
        if audio_part is not None:
            try:
                blob = audio_part.read()
            except Exception:
                blob = b""
            if len(blob) > 0:
                audio_raw = blob

        has_audio = audio_raw is not None
        has_image = bool(
            image_part and image_part.filename and image_part.filename.strip()
        )
        if has_audio and has_image:
            return (
                jsonify(
                    {
                        "error": "one_attachment",
                        "detail": "Send either a photo or a voice note per message, not both.",
                    }
                ),
                400,
            )
        if not text_raw and not has_audio and not has_image:
            return jsonify({"error": "empty", "detail": "Add text, a photo, or a voice note."}), 400

        uid = directory_user_id_for_account(acc)
        if uid is None:
            return jsonify({"error": "no_profile"}), 403

        image_name: str | None = None
        audio_name: str | None = None
        if has_audio:
            assert audio_raw is not None
            raw = audio_raw
            if len(raw) > CHAT_AUDIO_MAX_BYTES:
                return jsonify({"error": "too_large", "detail": "Voice note must be 15 MB or smaller."}), 400
            ext = _ext_for_chat_audio(
                getattr(audio_part, "mimetype", None),
                getattr(audio_part, "filename", None),
                raw,
            )
            if ext not in CHAT_AUDIO_EXT:
                ext = ".webm"
            audio_name = f"p{project_id}-u{uid}-a{uuid.uuid4().hex}{ext}"
            dest = os.path.join(chat_upload_root, audio_name)
            with open(dest, "wb") as out:
                out.write(raw)
        elif has_image:
            up = image_part
            raw = up.read() if up else b""
            if len(raw) > CHAT_UPLOAD_MAX_BYTES:
                return jsonify({"error": "too_large", "detail": "Image must be 5 MB or smaller."}), 400
            orig = secure_filename(up.filename or "") or "image"
            ext = os.path.splitext(orig)[1].lower()
            if ext not in CHAT_ALLOWED_EXT:
                return (
                    jsonify(
                        {
                            "error": "bad_type",
                            "detail": "Allowed image types: JPG, PNG, JPEG, WebP.",
                        }
                    ),
                    400,
                )
            image_name = f"p{project_id}-u{uid}-{uuid.uuid4().hex}{ext}"
            dest = os.path.join(chat_upload_root, image_name)
            with open(dest, "wb") as out:
                out.write(raw)

        msg_text = text_raw if text_raw else None
        cm = ChatMessage(
            project_id=project_id,
            user_id=uid,
            message=msg_text,
            image_path=image_name,
            audio_path=audio_name,
        )
        db.session.add(cm)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            if image_name:
                remove_chat_upload_file(image_name)
            if audio_name:
                remove_chat_upload_file(audio_name)
            app.logger.exception("project_chat_messages post")
            return jsonify({"error": "save"}), 500

        socketio.emit(
            "chat_updated",
            {
                "project_id": project_id,
                "message_id": cm.id,
                "user_id": uid,
            },
            room=f"project_{project_id}",
        )

        if msg_text:
            proj = Project.query.get(project_id)
            pname = (proj.name or "Project").strip() if proj else "Project"
            sender_u = User.query.get(uid)
            sender_label = (sender_u.name or "Someone").strip() if sender_u else "Someone"
            chat_href = url_for("index") + "#gchat-" + str(project_id)
            for mentioned in find_project_mentions_for_text(project_id, msg_text):
                if mentioned.id == uid:
                    continue
                if mentioned.account_id is None:
                    continue
                emit_notification_to_account(
                    mentioned.account_id,
                    {
                        "type": "mention",
                        "message": f"{sender_label} mentioned you in {pname}",
                        "href": chat_href,
                        "project_id": project_id,
                    },
                )

        return jsonify({"message": chat_message_json(cm, viewer_uid, reactions=[])}), 201

    @app.route("/projects/<int:project_id>/chat/messages/<int:message_id>", methods=["DELETE"])
    def project_chat_message_delete(project_id: int, message_id: int):
        acc = db.session.get(Account, session.get("account_id"))
        if not account_may_use_project_chat(acc, project_id):
            return jsonify({"error": "forbidden"}), 403
        uid = directory_user_id_for_account(acc)
        if uid is None:
            return jsonify({"error": "no_profile"}), 403
        m = ChatMessage.query.filter_by(id=message_id, project_id=project_id).first()
        if m is None:
            return jsonify({"error": "not_found"}), 404
        if m.user_id != uid:
            return (
                jsonify(
                    {
                        "error": "forbidden",
                        "detail": "Only the sender can delete this message.",
                    }
                ),
                403,
            )
        if not m.is_deleted:
            m.is_deleted = True
            m.deleted_at = now_local()
            db.session.commit()
            socketio.emit(
                "chat_updated",
                {
                    "project_id": project_id,
                    "message_id": m.id,
                    "user_id": uid,
                    "kind": "delete",
                },
                room=f"project_{project_id}",
            )
        return (
            jsonify(
                {
                    "ok": True,
                    "message": chat_message_json(m, uid, reactions=[]),
                }
            ),
            200,
        )

    @app.route("/projects/<int:project_id>/chat/messages/<int:message_id>/reaction", methods=["POST"])
    def project_chat_message_reaction(project_id: int, message_id: int):
        acc = db.session.get(Account, session.get("account_id"))
        if not account_may_use_project_chat(acc, project_id):
            return jsonify({"error": "forbidden"}), 403
        uid = directory_user_id_for_account(acc)
        if uid is None:
            return jsonify({"error": "no_profile"}), 403
        m = ChatMessage.query.filter_by(id=message_id, project_id=project_id).first()
        if m is None:
            return jsonify({"error": "not_found"}), 404
        if m.is_deleted:
            return (
                jsonify(
                    {"error": "gone", "detail": "Message was deleted."},
                ),
                410,
            )
        body = request.get_json(silent=True) or {}
        emoji = (body.get("emoji") or "").strip()
        if emoji not in CHAT_REACTION_EMOJIS:
            return (
                jsonify(
                    {
                        "error": "bad_emoji",
                        "detail": "Use one of the supported reaction emoji.",
                    }
                ),
                400,
            )
        existing = ChatMessageReaction.query.filter_by(
            message_id=m.id, user_id=uid
        ).first()
        if existing:
            if existing.emoji == emoji:
                db.session.delete(existing)
            else:
                existing.emoji = emoji
        else:
            db.session.add(
                ChatMessageReaction(message_id=m.id, user_id=uid, emoji=emoji)
            )
        try:
            db.session.commit()
        except sa_exc.IntegrityError:
            db.session.rollback()
            return jsonify({"error": "conflict"}), 409
        rows = ChatMessageReaction.query.filter_by(message_id=m.id).all()
        summaries = summarize_chat_reactions(rows, uid)
        socketio.emit(
            "chat_updated",
            {
                "project_id": project_id,
                "message_id": m.id,
                "user_id": uid,
                "kind": "reaction",
            },
            room=f"project_{project_id}",
        )
        return jsonify({"reactions": summaries}), 200

    @app.route("/projects/<int:project_id>/chat/attachments/<path:filename>")
    def project_chat_attachment(project_id: int, filename: str):
        acc = db.session.get(Account, session.get("account_id"))
        if not account_may_use_project_chat(acc, project_id):
            abort(403)
        if "/" in filename or "\\" in filename or ".." in filename or filename.startswith("."):
            abort(404)
        ok = (
            ChatMessage.query.filter(
                ChatMessage.project_id == project_id,
                ChatMessage.is_deleted.is_(False),
                or_(
                    ChatMessage.image_path == filename,
                    ChatMessage.audio_path == filename,
                ),
            ).first()
            is not None
        )
        if not ok:
            abort(404)
        ext = os.path.splitext(filename)[1].lower()
        mt = mimetypes.guess_type(filename)[0]
        if not mt:
            mt = {
                ".webm": "audio/webm",
                ".m4a": "audio/mp4",
                ".mp4": "audio/mp4",
                ".ogg": "audio/ogg",
                ".opus": "audio/ogg",
                ".mp3": "audio/mpeg",
                ".wav": "audio/wav",
            }.get(ext)
        return send_from_directory(
            chat_upload_root, filename, mimetype=mt or "application/octet-stream"
        )

    @app.route("/projects/<int:project_id>/chat/team", methods=["GET"])
    def project_chat_team(project_id: int):
        acc = db.session.get(Account, session.get("account_id"))
        if not account_may_use_project_chat(acc, project_id):
            return jsonify({"error": "forbidden"}), 403
        member_ids = {
            m.user_id for m in ProjectMember.query.filter_by(project_id=project_id).all()
        }
        if not member_ids:
            return jsonify({"team": []})
        users = (
            User.query.options(joinedload(User.job_title))
            .filter(User.id.in_(member_ids))
            .order_by(User.name)
            .all()
        )
        team = [
            {"id": u.id, "name": (u.name or "").strip()}
            for u in users
            if (u.name or "").strip()
        ]
        return jsonify({"team": team})

    @app.route("/projects/<int:project_id>/chat/unread-count")
    def project_chat_unread_count(project_id: int):
        acc = db.session.get(Account, session.get("account_id"))
        if not account_may_use_project_chat(acc, project_id):
            return jsonify({"error": "forbidden"}), 403
        n = chat_unread_count_for_account(acc, project_id)
        return jsonify({"count": n})

    @app.route("/projects/<int:project_id>/chat/mark-read", methods=["POST"])
    def project_chat_mark_read(project_id: int):
        acc = db.session.get(Account, session.get("account_id"))
        if not account_may_use_project_chat(acc, project_id):
            return jsonify({"error": "forbidden"}), 403
        chat_mark_project_read(acc, project_id)
        return jsonify({"ok": True})

    @app.route("/projects/<int:project_id>/edit", methods=["GET", "POST"])
    def project_edit(project_id: int):
        actor = db.session.get(Account, session.get("account_id"))
        if actor is None or not account_is_elevated(actor):
            flash("Only administrators and super users can edit project details.", "error")
            return redirect(url_for("project_detail", project_id=project_id))
        p = Project.query.get_or_404(project_id)
        if not account_can_access_project(actor, p.id):
            flash("You do not have access to that project.", "error")
            return redirect(url_for("projects_list"))
        if request.method == "POST":
            name = (request.form.get("name") or "").strip()
            project_type = (request.form.get("project_type") or "").strip()
            production_house = (request.form.get("production_house") or "").strip()
            director = (request.form.get("director") or "").strip()
            if not name or not project_type or not production_house or not director:
                flash("All fields are required.", "error")
                return redirect(url_for("project_edit", project_id=p.id))
            try:
                number_of_episodes = max(
                    0, int((request.form.get("number_of_episodes") or "0").strip() or 0)
                )
            except (TypeError, ValueError):
                number_of_episodes = 0
            if not _project_type_is_tv_series(project_type):
                number_of_episodes = 0
            try:
                estimated_shooting_days = max(
                    0, int((request.form.get("estimated_shooting_days") or "0").strip() or 0)
                )
            except (TypeError, ValueError):
                estimated_shooting_days = 0
            try:
                p.name = name
                p.project_type = project_type
                p.production_house = production_house
                p.director = director
                p.number_of_episodes = number_of_episodes
                p.estimated_shooting_days = estimated_shooting_days
                db.session.commit()
            except Exception:
                db.session.rollback()
                app.logger.exception("project_edit save failed")
                flash("Could not save changes. Check the server log or try again.", "error")
                return redirect(url_for("project_edit", project_id=p.id))
            flash("Project updated.", "success")
            return redirect(url_for("project_detail", project_id=p.id))
        return render_template("project_edit.html", project=p)

    @app.route("/projects/<int:project_id>/members/add", methods=["GET", "POST"])
    def project_members_add(project_id: int):
        actor = db.session.get(Account, session.get("account_id"))
        if actor is None or not account_can_manage_project_team(actor):
            flash("Only administrators, super users, and producers can change project teams.", "error")
            return redirect(url_for("projects_list"))
        p = Project.query.get_or_404(project_id)
        if not account_can_access_project(actor, p.id):
            flash("You do not have access to that project.", "error")
            return redirect(url_for("projects_list"))
        if request.method == "GET":
            return redirect(url_for("project_detail", project_id=p.id))
        raw_ids = request.form.getlist("user_ids")
        if not raw_ids:
            single = request.form.get("user_id")
            if single:
                raw_ids = [single]
        candidate_ids: list[int] = []
        for raw in raw_ids:
            try:
                uid = int(raw)
            except (TypeError, ValueError):
                continue
            if uid not in candidate_ids:
                candidate_ids.append(uid)
        if not candidate_ids:
            flash("Choose at least one user from the list to add.", "error")
            return redirect(url_for("project_detail", project_id=p.id))

        existing_ids = {
            int(m.user_id)
            for m in ProjectMember.query.filter_by(project_id=p.id).all()
            if m.user_id is not None
        }
        users_by_id = {
            int(u.id): u for u in User.query.filter(User.id.in_(candidate_ids)).all()
        }
        added = 0
        skipped_missing = 0
        skipped_existing = 0
        for uid in candidate_ids:
            if uid not in users_by_id:
                skipped_missing += 1
                continue
            if uid in existing_ids:
                skipped_existing += 1
                continue
            db.session.add(ProjectMember(project_id=p.id, user_id=uid))
            existing_ids.add(uid)
            added += 1
        try:
            db.session.commit()
        except sa_exc.IntegrityError:
            db.session.rollback()
            flash("Could not add one or more team members (duplicate or database error).", "error")
            return redirect(url_for("project_detail", project_id=p.id))
        if added:
            flash(f"Added {added} team member(s) to the project.", "success")
        if skipped_existing:
            flash(f"{skipped_existing} selected user(s) were already on this project.", "warning")
        if skipped_missing:
            flash(f"{skipped_missing} selected user(s) were not found.", "error")
        return redirect(url_for("project_detail", project_id=p.id))

    @app.route("/projects/<int:project_id>/members/<int:user_id>/remove", methods=["GET", "POST"])
    def project_member_remove(project_id: int, user_id: int):
        actor = db.session.get(Account, session.get("account_id"))
        if actor is None or not account_can_manage_project_team(actor):
            flash("Only administrators, super users, and producers can change project teams.", "error")
            return redirect(url_for("projects_list"))
        p = Project.query.get_or_404(project_id)
        if not account_can_access_project(actor, p.id):
            flash("You do not have access to that project.", "error")
            return redirect(url_for("projects_list"))
        if request.method == "GET":
            return redirect(url_for("project_detail", project_id=p.id))
        m = ProjectMember.query.filter_by(project_id=p.id, user_id=user_id).first()
        if m is None:
            flash("That user is not on this project team.", "error")
            return redirect(url_for("project_detail", project_id=p.id))
        db.session.delete(m)
        db.session.commit()
        flash("Removed from project team.", "success")
        return redirect(url_for("project_detail", project_id=p.id))

    @app.route("/project/<int:project_id>/audio-library/create", methods=["POST"])
    def project_audio_library_create(project_id: int):
        actor = db.session.get(Account, session.get("account_id"))
        if actor is None or not account_can_manage_project_team(actor):
            flash("Only administrators, super users, and producers can manage project audio libraries.", "error")
            return redirect(url_for("project_audio_library", project_id=project_id))
        p = Project.query.get_or_404(project_id)
        if not account_can_access_project(actor, p.id):
            flash("You do not have access to that project.", "error")
            return redirect(url_for("projects_list"))
        name = (request.form.get("name") or "").strip()
        if not name:
            flash("Library name is required.", "error")
            return redirect(url_for("project_audio_library", project_id=p.id))
        parent_id = request.form.get("parent_id", type=int)
        if parent_id:
            parent = db.session.get(ProjectAudioLibrary, int(parent_id))
            if parent is None or int(parent.project_id) != int(p.id):
                flash("Invalid parent library.", "error")
                return redirect(url_for("project_audio_library", project_id=p.id))
        else:
            parent = ensure_project_main_audio_library(p.id)
            parent_id = int(parent.id)
        row = ProjectAudioLibrary(project_id=p.id, name=name[:255], parent_id=parent_id)
        db.session.add(row)
        db.session.commit()
        flash("Audio sub-library created.", "success")
        return redirect(url_for("project_audio_library", project_id=p.id))

    @app.route("/project/<int:project_id>/audio-library/move", methods=["POST"])
    def project_audio_library_move(project_id: int):
        wants_json = "application/json" in (request.headers.get("Accept") or "").lower()
        actor = db.session.get(Account, session.get("account_id"))
        if actor is None or not account_can_manage_project_team(actor):
            msg = "Only administrators, super users, and producers can manage project audio libraries."
            if wants_json:
                return jsonify({"ok": False, "error": "forbidden", "message": msg}), 403
            flash(msg, "error")
            return redirect(url_for("project_audio_library", project_id=project_id))
        p = Project.query.get_or_404(project_id)
        if not account_can_access_project(actor, p.id):
            msg = "You do not have access to that project."
            if wants_json:
                return jsonify({"ok": False, "error": "forbidden", "message": msg}), 403
            flash(msg, "error")
            return redirect(url_for("projects_list"))
        payload = request.get_json(silent=True) or {}
        library_id = payload.get("library_id", request.form.get("library_id", type=int))
        target_parent_id = payload.get(
            "target_parent_id", request.form.get("target_parent_id", type=int)
        )
        try:
            library_id = int(library_id)
        except (TypeError, ValueError):
            library_id = 0
        if library_id <= 0:
            msg = "Invalid library."
            if wants_json:
                return jsonify({"ok": False, "error": "invalid", "message": msg}), 400
            flash(msg, "error")
            return redirect(url_for("project_audio_library", project_id=p.id))
        lib = db.session.get(ProjectAudioLibrary, library_id)
        if lib is None or int(lib.project_id) != int(p.id):
            msg = "Library not found."
            if wants_json:
                return jsonify({"ok": False, "error": "not_found", "message": msg}), 404
            flash(msg, "error")
            return redirect(url_for("project_audio_library", project_id=p.id))
        if target_parent_id in ("", None):
            target_parent_id = None
            target_parent = None
        else:
            try:
                target_parent_id = int(target_parent_id)
            except (TypeError, ValueError):
                target_parent_id = 0
            target_parent = db.session.get(ProjectAudioLibrary, target_parent_id)
            if target_parent is None or int(target_parent.project_id) != int(p.id):
                msg = "Target parent library not found."
                if wants_json:
                    return jsonify({"ok": False, "error": "invalid_parent", "message": msg}), 400
                flash(msg, "error")
                return redirect(url_for("project_audio_library", project_id=p.id))
        if target_parent_id is not None and int(target_parent_id) == int(lib.id):
            msg = "A library cannot be moved into itself."
            if wants_json:
                return jsonify({"ok": False, "error": "cycle", "message": msg}), 400
            flash(msg, "error")
            return redirect(url_for("project_audio_library", project_id=p.id))
        # Keep the auto-created main library as root.
        if str(lib.name or "").strip().lower() == "main" and lib.parent_id is None:
            msg = "Main library must stay at the root level."
            if wants_json:
                return jsonify({"ok": False, "error": "main_locked", "message": msg}), 400
            flash(msg, "error")
            return redirect(url_for("project_audio_library", project_id=p.id))
        # Prevent cycles: target parent cannot be a descendant of the moved library.
        if target_parent_id is not None:
            parent_cursor = target_parent
            while parent_cursor is not None:
                if int(parent_cursor.id) == int(lib.id):
                    msg = "Invalid move: cannot move a library into its own descendant."
                    if wants_json:
                        return jsonify({"ok": False, "error": "cycle", "message": msg}), 400
                    flash(msg, "error")
                    return redirect(url_for("project_audio_library", project_id=p.id))
                parent_cursor = (
                    db.session.get(ProjectAudioLibrary, int(parent_cursor.parent_id))
                    if parent_cursor.parent_id
                    else None
                )
        lib.parent_id = target_parent_id
        db.session.commit()
        msg = "Library moved."
        if wants_json:
            return jsonify(
                {
                    "ok": True,
                    "message": msg,
                    "library_id": int(lib.id),
                    "parent_id": (int(lib.parent_id) if lib.parent_id else None),
                }
            )
        flash(msg, "success")
        return redirect(url_for("project_audio_library", project_id=p.id))

    @app.route("/project/<int:project_id>/audio-library/delete/<int:library_id>", methods=["POST"])
    def project_audio_library_delete(project_id: int, library_id: int):
        wants_json = "application/json" in (request.headers.get("Accept") or "").lower()
        actor = db.session.get(Account, session.get("account_id"))
        if actor is None or not account_can_manage_project_team(actor):
            msg = "Only administrators, super users, and producers can manage project audio libraries."
            if wants_json:
                return jsonify({"ok": False, "error": "forbidden", "message": msg}), 403
            flash(msg, "error")
            return redirect(url_for("project_audio_library", project_id=project_id))
        p = Project.query.get_or_404(project_id)
        if not account_can_access_project(actor, p.id):
            msg = "You do not have access to that project."
            if wants_json:
                return jsonify({"ok": False, "error": "forbidden", "message": msg}), 403
            flash(msg, "error")
            return redirect(url_for("projects_list"))
        lib = db.session.get(ProjectAudioLibrary, int(library_id))
        if lib is None or int(lib.project_id) != int(p.id):
            msg = "Library not found."
            if wants_json:
                return jsonify({"ok": False, "error": "not_found", "message": msg}), 404
            flash(msg, "error")
            return redirect(url_for("project_audio_library", project_id=p.id))

        main_library = ensure_project_main_audio_library(p.id)
        if int(lib.id) == int(main_library.id):
            msg = "Main library cannot be removed."
            if wants_json:
                return jsonify({"ok": False, "error": "main_locked", "message": msg}), 400
            flash(msg, "error")
            return redirect(url_for("project_audio_library", project_id=p.id))

        fallback_parent_id = (
            int(lib.parent_id) if lib.parent_id else int(main_library.id)
        )

        for child in ProjectAudioLibrary.query.filter_by(parent_id=lib.id).all():
            child.parent_id = fallback_parent_id
        for linked in ProjectAudioFolder.query.filter_by(project_id=p.id, library_id=lib.id).all():
            linked.library_id = fallback_parent_id

        db.session.delete(lib)
        db.session.commit()
        msg = "Library removed."
        if wants_json:
            return jsonify({"ok": True, "message": msg, "fallback_parent_id": fallback_parent_id})
        flash(msg, "success")
        return redirect(url_for("project_audio_library", project_id=p.id))

    @app.route("/project/<int:project_id>/audio-library/link-folder", methods=["POST"])
    def project_audio_library_link_folder(project_id: int):
        wants_json = "application/json" in (request.headers.get("Accept") or "").lower()
        actor = db.session.get(Account, session.get("account_id"))
        if actor is None:
            msg = "Please sign in to continue."
            if wants_json:
                return jsonify({"ok": False, "error": "forbidden", "message": msg}), 403
            flash(msg, "error")
            return redirect(url_for("project_audio_library", project_id=project_id))
        p = Project.query.get_or_404(project_id)
        if not account_can_access_project(actor, p.id):
            msg = "You do not have access to that project."
            if wants_json:
                return jsonify({"ok": False, "error": "forbidden", "message": msg}), 403
            flash(msg, "error")
            return redirect(url_for("projects_list"))
        library_id = request.form.get("library_id", type=int)
        mount_id = request.form.get("mount_id", type=int)
        folder_path = (request.form.get("folder_path") or "").strip().replace("\\", "/")
        if library_id is None or mount_id is None:
            msg = "Library and mount are required."
            if wants_json:
                return jsonify({"ok": False, "error": "invalid", "message": msg}), 400
            flash(msg, "error")
            return redirect(url_for("project_audio_library", project_id=p.id))
        lib = db.session.get(ProjectAudioLibrary, int(library_id))
        if lib is None or int(lib.project_id) != int(p.id):
            msg = "Invalid target library."
            if wants_json:
                return jsonify({"ok": False, "error": "invalid_library", "message": msg}), 400
            flash(msg, "error")
            return redirect(url_for("project_audio_library", project_id=p.id))
        mount = db.session.get(MusicMount, int(mount_id))
        if mount is None:
            msg = "Invalid mount."
            if wants_json:
                return jsonify({"ok": False, "error": "invalid_mount", "message": msg}), 400
            flash(msg, "error")
            return redirect(url_for("project_audio_library", project_id=p.id))
        exists = ProjectAudioFolder.query.filter_by(
            project_id=p.id,
            library_id=lib.id,
            mount_id=mount.id,
            folder_path=folder_path,
        ).first()
        if exists is None:
            db.session.add(
                ProjectAudioFolder(
                    project_id=p.id,
                    library_id=lib.id,
                    mount_id=mount.id,
                    folder_path=folder_path,
                )
            )
            db.session.commit()
            msg = "Indexed folder linked to project library."
            if wants_json:
                return jsonify({"ok": True, "linked": True, "message": msg})
            flash(msg, "success")
        else:
            msg = "That folder is already linked to this library."
            if wants_json:
                return jsonify({"ok": True, "linked": False, "message": msg})
            flash(msg, "warning")
        return redirect(url_for("project_audio_library", project_id=p.id))

    @app.route("/project/<int:project_id>/audio-library/unlink-folder/<int:link_id>", methods=["POST"])
    def project_audio_library_unlink_folder(project_id: int, link_id: int):
        wants_json = "application/json" in (request.headers.get("Accept") or "").lower()
        actor = db.session.get(Account, session.get("account_id"))
        if actor is None or not account_can_manage_project_team(actor):
            msg = "Only administrators, super users, and producers can manage project audio libraries."
            if wants_json:
                return jsonify({"ok": False, "error": "forbidden", "message": msg}), 403
            flash(msg, "error")
            return redirect(url_for("project_audio_library", project_id=project_id))
        p = Project.query.get_or_404(project_id)
        if not account_can_access_project(actor, p.id):
            msg = "You do not have access to that project."
            if wants_json:
                return jsonify({"ok": False, "error": "forbidden", "message": msg}), 403
            flash(msg, "error")
            return redirect(url_for("projects_list"))
        link = db.session.get(ProjectAudioFolder, link_id)
        if link is None or int(link.project_id) != int(p.id):
            msg = "Linked folder not found."
            if wants_json:
                return jsonify({"ok": False, "error": "not_found", "message": msg}), 404
            flash(msg, "error")
            return redirect(url_for("project_audio_library", project_id=p.id))
        db.session.delete(link)
        db.session.commit()
        msg = "Folder removed from project audio library."
        if wants_json:
            return jsonify({"ok": True, "message": msg})
        flash(msg, "success")
        return redirect(url_for("project_audio_library", project_id=p.id))

    @app.route("/project/<int:project_id>/audio-library/move-folder/<int:link_id>", methods=["POST"])
    def project_audio_library_move_folder(project_id: int, link_id: int):
        wants_json = "application/json" in (request.headers.get("Accept") or "").lower()
        actor = db.session.get(Account, session.get("account_id"))
        if actor is None or not account_can_manage_project_team(actor):
            msg = "Only administrators, super users, and producers can manage project audio libraries."
            if wants_json:
                return jsonify({"ok": False, "error": "forbidden", "message": msg}), 403
            flash(msg, "error")
            return redirect(url_for("project_audio_library", project_id=project_id))
        p = Project.query.get_or_404(project_id)
        if not account_can_access_project(actor, p.id):
            msg = "You do not have access to that project."
            if wants_json:
                return jsonify({"ok": False, "error": "forbidden", "message": msg}), 403
            flash(msg, "error")
            return redirect(url_for("projects_list"))
        link = db.session.get(ProjectAudioFolder, int(link_id))
        if link is None or int(link.project_id) != int(p.id):
            msg = "Linked folder not found."
            if wants_json:
                return jsonify({"ok": False, "error": "not_found", "message": msg}), 404
            flash(msg, "error")
            return redirect(url_for("project_audio_library", project_id=p.id))
        payload = request.get_json(silent=True) or {}
        target_library_id = payload.get("target_library_id", request.form.get("target_library_id", type=int))
        try:
            target_library_id = int(target_library_id)
        except (TypeError, ValueError):
            target_library_id = 0
        target_lib = db.session.get(ProjectAudioLibrary, target_library_id)
        if target_lib is None or int(target_lib.project_id) != int(p.id):
            msg = "Target library not found."
            if wants_json:
                return jsonify({"ok": False, "error": "invalid_library", "message": msg}), 400
            flash(msg, "error")
            return redirect(url_for("project_audio_library", project_id=p.id))
        if int(link.library_id) == int(target_lib.id):
            msg = "Folder is already in that library."
            if wants_json:
                return jsonify({"ok": True, "moved": False, "message": msg})
            flash(msg, "warning")
            return redirect(url_for("project_audio_library", project_id=p.id))

        dupe = ProjectAudioFolder.query.filter_by(
            project_id=p.id,
            library_id=target_lib.id,
            mount_id=link.mount_id,
            folder_path=link.folder_path,
        ).first()
        if dupe is not None and int(dupe.id) != int(link.id):
            db.session.delete(link)
            db.session.commit()
            msg = "Folder already existed in target library. Duplicate link removed."
            if wants_json:
                return jsonify({"ok": True, "moved": True, "deduped": True, "message": msg})
            flash(msg, "success")
            return redirect(url_for("project_audio_library", project_id=p.id))

        link.library_id = int(target_lib.id)
        db.session.commit()
        msg = "Folder moved to target library."
        if wants_json:
            return jsonify({"ok": True, "moved": True, "message": msg})
        flash(msg, "success")
        return redirect(url_for("project_audio_library", project_id=p.id))

    @app.route("/project/<int:project_id>/audio-library/<int:library_id>/files")
    def project_audio_library_files(project_id: int, library_id: int):
        actor = db.session.get(Account, session.get("account_id"))
        if actor is None or not account_can_access_project(actor, project_id):
            return jsonify({"error": "forbidden"}), 403
        lib = db.session.get(ProjectAudioLibrary, library_id)
        if lib is None or int(lib.project_id) != int(project_id):
            return jsonify({"error": "not_found"}), 404
        rows = (
            MusicFile.query.join(
                ProjectAudioFolder,
                and_(
                    MusicFile.mount_id == ProjectAudioFolder.mount_id,
                    MusicFile.folder == ProjectAudioFolder.folder_path,
                ),
            )
            .filter(ProjectAudioFolder.project_id == project_id)
            .filter(ProjectAudioFolder.library_id == library_id)
            .order_by(MusicFile.name.asc())
            .all()
        )
        return jsonify(
            [
                {
                    "id": r.id,
                    "name": r.name,
                    "duration": float(r.duration or 0),
                    "folder": r.folder or "",
                }
                for r in rows
            ]
        )

    @app.route("/projects/<int:project_id>/delete", methods=["POST"])
    def projects_delete(project_id: int):
        actor = account_from_session()
        if actor is None or not actor.is_admin:
            abort(403)
        p = Project.query.get_or_404(project_id)
        # Remove dependent rows first before deleting the project.
        for b in Booking.query.filter_by(project_id=p.id).all():
            db.session.delete(b)
        scene_ids = [
            int(sc.id)
            for sc in (
                ShootingDayScene.query.join(ShootingDay, ShootingDayScene.shooting_day_id == ShootingDay.id)
                .filter(ShootingDay.project_id == p.id)
                .all()
            )
        ]
        if scene_ids:
            shot_rows = VfxShot.query.filter(VfxShot.scene_id.in_(scene_ids)).all()
            shot_ids = [int(s.id) for s in shot_rows]
            if shot_ids:
                for sh in shot_rows:
                    rf = (sh.shot_ref_frame or "").strip()
                    if rf and not _vfx_media_is_remote(rf):
                        remove_vfx_version_file(rf)
                for ver in VfxVersion.query.filter(VfxVersion.shot_id.in_(shot_ids)).all():
                    img = (ver.image or "").strip()
                    if img and not (
                        img.lower().startswith("http://") or img.lower().startswith("https://")
                    ):
                        remove_vfx_version_file(img)
                VfxShotComment.query.filter(VfxShotComment.shot_id.in_(shot_ids)).delete(
                    synchronize_session=False
                )
                VfxVersion.query.filter(VfxVersion.shot_id.in_(shot_ids)).delete(synchronize_session=False)
            VfxShot.query.filter(VfxShot.scene_id.in_(scene_ids)).delete(synchronize_session=False)
            for rf in SceneReference.query.filter(SceneReference.scene_id.in_(scene_ids)).all():
                remove_scene_reference_file(rf.video_url)
            SceneReference.query.filter(SceneReference.scene_id.in_(scene_ids)).delete(
                synchronize_session=False
            )

        for cm in ChatMessage.query.filter_by(project_id=p.id).all():
            if cm.image_path:
                remove_chat_upload_file(cm.image_path)
            if cm.audio_path:
                remove_chat_upload_file(cm.audio_path)
            db.session.delete(cm)
        for rs in ProjectChatReadState.query.filter_by(project_id=p.id).all():
            db.session.delete(rs)
        for t in Task.query.filter_by(project_id=p.id).all():
            db.session.delete(t)
        for m in ProjectMember.query.filter_by(project_id=p.id).all():
            db.session.delete(m)
        db.session.delete(p)
        db.session.commit()
        flash("Project and its tasks were removed.", "success")
        return redirect(url_for("projects_list"))

    @app.route("/users")
    def users_list():
        actor = account_from_session()
        if not account_can_access_admin_settings(actor):
            flash("Only administrators can access the Users page.", "error")
            return redirect(url_for("index"))
        users = (
            User.query.options(joinedload(User.job_title))
            .order_by(User.name)
            .all()
        )
        job_titles = JobTitle.query.order_by(JobTitle.name).all()
        return render_template("users.html", users=users, job_titles=job_titles)

    @app.route("/users/<int:user_id>/role", methods=["POST"])
    def users_set_role(user_id: int):
        actor = account_from_session()
        if not account_can_access_admin_settings(actor):
            flash("Only administrators can change user roles.", "error")
            return redirect(url_for("index"))
        u = User.query.get_or_404(user_id)
        if not u.account_id:
            flash("External users are not linked to an account — there is no role to change.", "error")
            return redirect(url_for("users_list"))
        acc = db.session.get(Account, u.account_id)
        if acc is None:
            flash("Account not found.", "error")
            return redirect(url_for("users_list"))
        role = (request.form.get("role") or "").strip().lower()
        if role not in ACCOUNT_ROLES:
            flash("Invalid role.", "error")
            return redirect(url_for("users_list"))
        if role == ROLE_ADMIN and not actor.is_admin:
            flash("Only administrators may assign the administrator role.", "error")
            return redirect(url_for("users_list"))
        if acc.is_admin and role != ROLE_ADMIN:
            if Account.query.filter_by(role=ROLE_ADMIN).count() <= 1:
                flash("Cannot demote the last administrator.", "error")
                return redirect(url_for("users_list"))
        acc.role = role
        db.session.commit()
        flash("User role updated.", "success")
        return redirect(url_for("users_list"))

    @app.route("/users/<int:user_id>/job-title", methods=["POST"])
    def users_set_job_title(user_id: int):
        actor = account_from_session()
        if not account_can_access_admin_settings(actor):
            flash("Only administrators can change job titles.", "error")
            return redirect(url_for("index"))
        u = User.query.get_or_404(user_id)
        jt_raw = request.form.get("job_title_id")
        if jt_raw is None or (isinstance(jt_raw, str) and not jt_raw.strip()):
            u.job_title_id = None
        else:
            try:
                jtid = int(jt_raw)
            except (TypeError, ValueError):
                jtid = 0
            if jtid and JobTitle.query.get(jtid) is not None:
                u.job_title_id = jtid
            else:
                u.job_title_id = None
        db.session.commit()
        flash("Job title updated.", "success")
        return redirect(url_for("users_list"))

    @app.route("/users/new", methods=["POST"])
    def users_create():
        actor = account_from_session()
        if not account_can_access_admin_settings(actor):
            flash("Only administrators can add directory users.", "error")
            return redirect(url_for("index"))
        name = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        if not name or not email:
            flash("Name and email are required.", "error")
            return redirect(url_for("users_list"))
        if Account.query.filter_by(email=email).first():
            flash("That email is registered — the user already appears in the list from their account.", "error")
            return redirect(url_for("users_list"))
        u = User(name=name, email=email)
        db.session.add(u)
        try:
            db.session.commit()
            flash("User created.", "success")
        except sa_exc.IntegrityError:
            db.session.rollback()
            flash("A user with that email already exists.", "error")
        return redirect(url_for("users_list"))

    @app.route("/users/<int:user_id>/edit", methods=["POST"])
    def users_update(user_id: int):
        actor = account_from_session()
        if not account_can_access_admin_settings(actor):
            flash("Only administrators can edit directory users.", "error")
            return redirect(url_for("index"))
        u = User.query.get_or_404(user_id)
        name = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        if not name or not email:
            flash("Name and email are required.", "error")
            return redirect(url_for("users_list"))
        u.name = name
        if u.account_id:
            acc = db.session.get(Account, u.account_id)
            if acc is not None and acc.email != email:
                taken = (
                    Account.query.filter(Account.email == email, Account.id != acc.id).first()
                    or User.query.filter(User.email == email, User.id != u.id).first()
                )
                if taken:
                    flash("That email is already in use.", "error")
                    return redirect(url_for("users_list"))
                acc.email = email
        u.email = email
        try:
            db.session.commit()
            flash("User updated.", "success")
        except sa_exc.IntegrityError:
            db.session.rollback()
            flash("A user with that email already exists.", "error")
        return redirect(url_for("users_list"))

    @app.route("/users/<int:user_id>/delete", methods=["POST"])
    def users_delete(user_id: int):
        actor = account_from_session()
        if not account_can_access_admin_settings(actor):
            flash("Only administrators can delete directory users.", "error")
            return redirect(url_for("index"))
        u = User.query.get_or_404(user_id)
        if u.account_id:
            flash("Registered users cannot be deleted here. They are tied to a login account.", "error")
            return redirect(url_for("users_list"))
        db.session.delete(u)
        db.session.commit()
        flash("User and their tasks were removed.", "success")
        return redirect(url_for("users_list"))

    @app.route("/tasks")
    def tasks_list():
        acc = db.session.get(Account, session.get("account_id"))
        vis = visible_project_ids_for_account(acc)
        task_groups = TaskGroup.query.order_by(TaskGroup.sort_order, TaskGroup.name).all()
        uid = directory_user_id_for_account(acc)
        selected_sort = (request.args.get("sort") or "").strip().lower()
        if selected_sort not in ("", "newest", "priority"):
            selected_sort = ""

        # Tasks page filters are client-side; load full visible set (JSON APIs unchanged).
        all_tasks = all_tasks_for_tasks_list_page(acc)

        tasks_by_group: dict[int | None, list[Task]] = defaultdict(list)
        for t in all_tasks:
            tasks_by_group[t.group_id].append(t)
        if vis is None:
            users = User.query.order_by(User.name).all()
            projects = Project.query.order_by(Project.sort_order.asc(), Project.id.asc()).all()
        elif not vis:
            users = []
            projects = []
        else:
            member_ids = {
                pm.user_id
                for pm in ProjectMember.query.filter(ProjectMember.project_id.in_(vis)).all()
            }
            if member_ids:
                users = User.query.filter(User.id.in_(member_ids)).order_by(User.name).all()
            else:
                users = []
            projects = (
                Project.query.filter(Project.id.in_(vis))
                .order_by(Project.sort_order.asc(), Project.id.asc())
                .all()
            )
        titles_by_group: dict[int, list[TaskGroupTitle]] = defaultdict(list)
        for pt in TaskGroupTitle.query.order_by(TaskGroupTitle.sort_order, TaskGroupTitle.id).all():
            titles_by_group[pt.group_id].append(pt)
        has_title_presets = TaskGroupTitle.query.count() > 0
        user_project_ids: dict[int, list[int]] = defaultdict(list)
        for pm in ProjectMember.query.all():
            user_project_ids[pm.user_id].append(pm.project_id)
        return render_template(
            "tasks.html",
            task_groups=task_groups,
            tasks_by_group=dict(tasks_by_group),
            titles_by_group=dict(titles_by_group),
            users=users,
            projects=projects,
            has_title_presets=has_title_presets,
            user_project_ids=dict(user_project_ids),
            selected_sort=(selected_sort or "newest"),
        )

    @app.route("/api/tasks", methods=["GET"])
    def api_tasks_all():
        """Admin-only REST endpoint: all tasks across all projects/users."""
        actor = account_from_session()
        if actor is None or not actor.is_admin:
            return jsonify({"error": "forbidden"}), 403

        status = (request.args.get("status") or "").strip().lower()
        if status not in ("", "open", "in_progress", "done"):
            status = ""

        search = (request.args.get("search") or "").strip()

        project_id = request.args.get("project_id", type=int)
        user_id = request.args.get("user_id", type=int)
        limit = request.args.get("limit", type=int) or 200
        offset = request.args.get("offset", type=int) or 0
        limit = max(1, min(int(limit), 1000))
        offset = max(0, int(offset))

        q = Task.query.options(joinedload(Task.project), joinedload(Task.assignee))
        if status:
            q = q.filter(Task.status == status)
        if search:
            like = f"%{search}%"
            q = (
                q.join(Project, Task.project_id == Project.id, isouter=True)
                .join(User, Task.user_id == User.id, isouter=True)
                .filter(or_(Project.name.ilike(like), User.name.ilike(like)))
            )
        if project_id:
            q = q.filter(Task.project_id == project_id)
        if user_id:
            q = q.filter(Task.user_id == user_id)

        total = q.count()
        rows = q.order_by(Task.created_at.desc(), Task.id.desc()).offset(offset).limit(limit).all()

        def _task_json(t: Task) -> dict:
            p = t.project
            u = t.assignee
            return {
                "id": t.id,
                "title": t.title,
                "description": t.description or "",
                "status": t.status,
                "priority": (t.priority or "medium"),
                "archived": bool(t.archived),
                "created_at": isoformat_stored_instant(t.created_at),
                "completed_at": isoformat_stored_instant(t.completed_at),
                "project": {"id": p.id, "name": p.name} if p is not None else None,
                "user": {"id": u.id, "name": u.name} if u is not None else None,
            }

        return jsonify(
            {
                "ok": True,
                "total": total,
                "limit": limit,
                "offset": offset,
                "tasks": [_task_json(t) for t in rows],
            }
        )

    def _redirect_after_task_action() -> Response:
        raw_next = (request.form.get("next") or "").strip()
        if raw_next.startswith("/") and not raw_next.startswith("//"):
            return redirect(raw_next)
        return redirect(url_for("tasks_list"))

    @app.route("/tasks/new", methods=["POST"])
    def tasks_create():
        preset_id = request.form.get("preset_id", type=int)
        group_id = request.form.get("group_id", type=int)
        project_id = request.form.get("project_id", type=int)
        user_id = request.form.get("user_id", type=int)
        priority_raw = (request.form.get("priority") or "").strip().lower()
        extra_description = (request.form.get("description") or "").strip()

        preset = TaskGroupTitle.query.get(preset_id) if preset_id else None
        if not preset:
            flash("Choose a task title from the list.", "error")
            return _redirect_after_task_action()
        if group_id and preset.group_id != group_id:
            flash("Task title does not match the selected task group.", "error")
            return _redirect_after_task_action()
        if not project_id:
            flash("Choose a project.", "error")
            return _redirect_after_task_action()
        project = Project.query.get(project_id)
        if not project:
            flash("Invalid project.", "error")
            return _redirect_after_task_action()
        actor = db.session.get(Account, session.get("account_id"))
        vis = visible_project_ids_for_account(actor)
        if vis is not None and project.id not in vis:
            flash("You cannot create tasks for that project.", "error")
            return _redirect_after_task_action()
        if not user_id:
            flash("Choose an assignee.", "error")
            return _redirect_after_task_action()
        user = User.query.get(user_id)
        if not user:
            flash("Invalid assignee.", "error")
            return _redirect_after_task_action()
        if not ProjectMember.query.filter_by(project_id=project.id, user_id=user_id).first():
            flash("Only users assigned to this project can receive tasks. Add them on the project page.", "error")
            return _redirect_after_task_action()

        description = (preset.description or "").strip()
        if extra_description:
            description = f"{description}\n{extra_description}".strip() if description else extra_description

        if priority_raw not in ("low", "medium", "high"):
            priority_raw = "medium"

        t = Task(
            title=preset.title,
            description=description,
            user_id=user_id,
            group_id=preset.group_id,
            project_id=project.id,
            status="open",
            priority=priority_raw,
        )
        db.session.add(t)
        db.session.commit()
        emit_tasks_feed_changed(project.id)
        if user.account_id is not None and (
            actor is None or user.account_id != actor.id
        ):
            emit_notification_to_account(
                user.account_id,
                {
                    "type": "task_assigned",
                    "title": t.title,
                    "project_name": project.name,
                    "task_id": t.id,
                    "project_id": project.id,
                    "href": url_for("tasks_list"),
                },
            )
        flash("Task created.", "success")
        return _redirect_after_task_action()

    @app.route("/tasks/<int:task_id>/status", methods=["POST"])
    def tasks_set_status(task_id: int):
        acc = db.session.get(Account, session.get("account_id"))
        t = Task.query.get_or_404(task_id)

        def _tasks_status_error_redirect() -> Response:
            raw = (request.form.get("next") or "").strip()
            if raw.startswith("/") and not raw.startswith("//"):
                return redirect(raw)
            return redirect(url_for("tasks_list"))

        status = (request.form.get("status") or "").strip().lower()
        if status not in ("open", "in_progress", "done"):
            flash("Invalid status.", "error")
            return _tasks_status_error_redirect()
        assignee_ok = account_may_update_task_status(t, acc)
        mr_stream_ok = account_may_machine_room_operate_stream_task(t, acc) and status in (
            "open",
            "in_progress",
        )
        if not assignee_ok and not mr_stream_ok:
            flash("You cannot update that task’s status.", "error")
            return _tasks_status_error_redirect()
        if status == "done" and not assignee_ok:
            flash("You cannot mark that task done from here.", "error")
            return _tasks_status_error_redirect()
        if t.archived:
            flash("Unarchive the task before changing its status.", "error")
            return _redirect_after_task_action()
        t.status = status
        if status == "done":
            t.completed_at = now_local()
        else:
            t.completed_at = None
        db.session.commit()
        emit_tasks_feed_changed(t.project_id)
        flash("Task status updated.", "success")
        return _redirect_after_task_action()

    @app.route("/tasks/<int:task_id>/machine-room/finish", methods=["POST"])
    def tasks_machine_room_stream_finish(task_id: int):
        """Machine Room: force-complete a live copy/convert task; copy may optionally start Convert."""
        acc = db.session.get(Account, session.get("account_id"))
        t = Task.query.get_or_404(task_id)
        if not account_may_machine_room_operate_stream_task(t, acc):
            flash("You cannot finish that task.", "error")
            return _redirect_after_task_action()
        if t.archived:
            flash("Unarchive the task before changing its status.", "error")
            return _redirect_after_task_action()
        title_norm = (t.title or "").strip()
        raw_sc = (request.form.get("start_convert") or "").strip().lower()
        start_convert = raw_sc in ("1", "true", "yes", "on")
        try:
            convert_minutes = int((request.form.get("convert_minutes") or "0").strip())
        except (TypeError, ValueError):
            convert_minutes = 0
        if title_norm == MR_STREAM_COPY_TITLE and start_convert and convert_minutes < 1:
            flash("Enter a convert estimate of at least 1 minute, or choose not to start Convert.", "error")
            return _redirect_after_task_action()
        now = now_local()
        est = max(0, int(t.copy_estimated_minutes or 0))
        if est > 0:
            t.copy_started_at = now - timedelta(minutes=est)
        else:
            t.copy_started_at = now
        t.status = "done"
        t.completed_at = now
        pid = int(t.project_id) if t.project_id is not None else None
        day_nm = (t.copy_day_name or "").strip() or "—"
        unit_nm = t.copy_unit_number if t.copy_unit_number is not None else "—"
        pname = (t.project.name or "").strip() if t.project is not None else ""
        if pid is not None:
            if title_norm == MR_STREAM_COPY_TITLE:
                _notification_emit_to_project(
                    project_id=pid,
                    rule=f"mr_copy_finished|{t.id}",
                    n_type="activity",
                    severity="info",
                    title="Copy task finished",
                    message=(
                        f"Machine Room marked the copy finished ({day_nm}, Unit {unit_nm})"
                        + (f" on {pname}." if pname else ".")
                    ),
                    entity_type="task",
                    entity_id=int(t.id),
                )
                if start_convert and convert_minutes >= 1:
                    new_t = Task(
                        title=MR_STREAM_CONVERT_TITLE,
                        description="",
                        user_id=int(t.user_id),
                        group_id=int(t.group_id) if t.group_id is not None else None,
                        project_id=pid,
                        status="in_progress",
                        priority=(t.priority or "medium"),
                        copy_started_at=now,
                        copy_estimated_minutes=max(1, min(convert_minutes, 2880)),
                        copy_day_name=t.copy_day_name,
                        copy_unit_number=t.copy_unit_number,
                    )
                    db.session.add(new_t)
                    db.session.flush()
                    nid = int(new_t.id)
                    _notification_emit_to_project(
                        project_id=pid,
                        rule=f"mr_convert_started|{nid}",
                        n_type="activity",
                        severity="info",
                        title="Convert task started",
                        message=(
                            f"Machine Room started a Convert task ({day_nm}, Unit {unit_nm}, "
                            f"~{int(new_t.copy_estimated_minutes or 0)}m)"
                            + (f" on {pname}." if pname else ".")
                        ),
                        entity_type="task",
                        entity_id=nid,
                    )
                    flash("Copy finished and Convert task started. Project members were notified.", "success")
                else:
                    _notification_emit_to_project(
                        project_id=pid,
                        rule=f"mr_convert_declined|{t.id}",
                        n_type="activity",
                        severity="info",
                        title="Convert not started",
                        message=(
                            "Machine Room finished the copy and chose not to start a Convert task "
                            f"({day_nm}, Unit {unit_nm})"
                            + (f" on {pname}." if pname else ".")
                        ),
                        entity_type="task",
                        entity_id=int(t.id),
                    )
                    flash("Task finished. Project members were notified.", "success")
            elif title_norm == MR_STREAM_CONVERT_TITLE:
                _notification_emit_to_project(
                    project_id=pid,
                    rule=f"mr_convert_finished|{t.id}",
                    n_type="activity",
                    severity="info",
                    title="Convert task finished",
                    message=(
                        f"Machine Room marked the convert finished ({day_nm}, Unit {unit_nm})"
                        + (f" on {pname}." if pname else ".")
                    ),
                    entity_type="task",
                    entity_id=int(t.id),
                )
                flash("Task finished. Project members were notified.", "success")
        else:
            flash("Task finished.", "success")
        db.session.commit()
        emit_tasks_feed_changed(pid)
        return _redirect_after_task_action()

    @app.route("/tasks/<int:task_id>/machine-room/cancel-delete", methods=["POST"])
    def tasks_machine_room_stream_cancel_delete(task_id: int):
        """Machine Room: delete a live copy task and notify the project team."""
        acc = db.session.get(Account, session.get("account_id"))
        t = Task.query.get_or_404(task_id)
        if not account_may_machine_room_operate_stream_task(t, acc):
            flash("You cannot remove that task.", "error")
            return _redirect_after_task_action()
        pid = int(t.project_id) if t.project_id is not None else None
        tid = int(t.id)
        day_nm = (t.copy_day_name or "").strip() or "—"
        unit_nm = t.copy_unit_number if t.copy_unit_number is not None else "—"
        assignee_label = ""
        if t.assignee is not None:
            assignee_label = (t.assignee.name or t.assignee.email or "").strip()
        if pid is not None:
            pname = (t.project.name or "").strip() if t.project is not None else ""
            title_norm = (t.title or "").strip()
            is_conv = title_norm == MR_STREAM_CONVERT_TITLE
            _notification_emit_to_project(
                project_id=pid,
                rule=(f"mr_convert_cancelled|{tid}" if is_conv else f"mr_copy_cancelled|{tid}"),
                n_type="activity",
                severity="warning",
                title=("Convert task cancelled" if is_conv else "Copy task cancelled"),
                message=(
                    (
                        "Machine Room cancelled and deleted the convert task "
                        if is_conv
                        else "Machine Room cancelled and deleted the copy task "
                    )
                    + f"({day_nm}, Unit {unit_nm})"
                    + (f" on {pname}" if pname else "")
                    + (f", assigned to {assignee_label}." if assignee_label else ".")
                ),
                entity_type="task",
                entity_id=tid,
            )
        db.session.delete(t)
        db.session.commit()
        emit_tasks_feed_changed(pid)
        flash("Task removed. Project members were notified.", "success")
        return _redirect_after_task_action()

    @app.route("/tasks/<int:task_id>/archive", methods=["POST"])
    def tasks_archive(task_id: int):
        acc = db.session.get(Account, session.get("account_id"))
        t = Task.query.get_or_404(task_id)
        if not account_may_archive_task(t, acc):
            flash("You cannot archive that task.", "error")
            return _redirect_after_task_action()
        if t.archived:
            flash("That task is already archived.", "error")
            return _redirect_after_task_action()
        if t.status != "done":
            flash("Only completed tasks can be archived.", "error")
            return _redirect_after_task_action()
        t.archived = True
        db.session.commit()
        emit_tasks_feed_changed(t.project_id)
        flash("Task archived.", "success")
        return _redirect_after_task_action()

    @app.route("/tasks/<int:task_id>/unarchive", methods=["POST"])
    def tasks_unarchive(task_id: int):
        acc = db.session.get(Account, session.get("account_id"))
        t = Task.query.get_or_404(task_id)
        if not account_may_archive_task(t, acc):
            flash("You cannot restore that task.", "error")
            return _redirect_after_task_action()
        if not t.archived:
            flash("That task is not archived.", "error")
            return _redirect_after_task_action()
        t.archived = False
        db.session.commit()
        emit_tasks_feed_changed(t.project_id)
        flash("Task restored from archive.", "success")
        return _redirect_after_task_action()

    @app.route("/tasks/<int:task_id>/delete", methods=["POST"])
    def tasks_delete(task_id: int):
        acc = db.session.get(Account, session.get("account_id"))
        t = Task.query.get_or_404(task_id)
        if not task_visible_to_account(t, acc):
            flash("You do not have access to that task.", "error")
            return _redirect_after_task_action()
        del_pid = t.project_id
        db.session.delete(t)
        db.session.commit()
        emit_tasks_feed_changed(del_pid)
        flash("Task deleted.", "success")
        return _redirect_after_task_action()

    @app.route("/debug/priorities", methods=["GET", "POST"])
    def debug_priorities():
        actor = account_from_session()
        if actor is None or not actor.is_admin:
            abort(403)

        action = (request.form.get("action") or "").strip().lower()
        if request.method == "POST" and action:
            if action == "create":
                name = (request.form.get("name") or "").strip()
                if not name:
                    flash("Name is required.", "error")
                    return redirect(url_for("debug_priorities"))
                db.session.add(TaskPriority(name=name))
                try:
                    db.session.commit()
                    flash("Priority added.", "success")
                except sa_exc.IntegrityError:
                    db.session.rollback()
                    flash("That priority already exists.", "error")
                return redirect(url_for("debug_priorities"))

            if action == "update":
                pid = request.form.get("id", type=int)
                row = TaskPriority.query.get(pid) if pid else None
                if row is None:
                    flash("Priority not found.", "error")
                    return redirect(url_for("debug_priorities"))
                name = (request.form.get("name") or "").strip()
                if not name:
                    flash("Name is required.", "error")
                    return redirect(url_for("debug_priorities"))
                row.name = name
                try:
                    db.session.commit()
                    flash("Priority updated.", "success")
                except sa_exc.IntegrityError:
                    db.session.rollback()
                    flash("That priority already exists.", "error")
                return redirect(url_for("debug_priorities"))

            if action == "delete":
                pid = request.form.get("id", type=int)
                row = TaskPriority.query.get(pid) if pid else None
                if row is None:
                    flash("Priority not found.", "error")
                    return redirect(url_for("debug_priorities"))
                db.session.delete(row)
                db.session.commit()
                flash("Priority deleted.", "success")
                return redirect(url_for("debug_priorities"))

        rows = TaskPriority.query.order_by(TaskPriority.name.asc(), TaskPriority.id.asc()).all()
        return render_template("debug_priorities.html", rows=rows)

    @app.route("/control")
    def control_panel():
        actor = account_from_session()
        if not account_can_access_admin_settings(actor):
            flash("Only administrators can access the control panel.", "error")
            return redirect(url_for("index"))
        groups = TaskGroup.query.order_by(TaskGroup.sort_order, TaskGroup.id).all()
        presets_by_group: dict[int, list[TaskGroupTitle]] = defaultdict(list)
        for pt in TaskGroupTitle.query.order_by(TaskGroupTitle.sort_order, TaskGroupTitle.id).all():
            presets_by_group[pt.group_id].append(pt)
        job_titles = JobTitle.query.order_by(JobTitle.name).all()
        admin_tasks: list[Task] = []
        admin_tasks_total = 0
        admin_tasks_page = 1
        admin_tasks_per_page = 20
        admin_tasks_page_count = 1
        admin_task_status = ""
        admin_tasks_search = ""
        admin_sort = ""
        admin_sort_direction = "asc"
        if actor is not None and actor.is_admin:
            admin_task_status = (request.args.get("task_status") or "").strip().lower()
            if admin_task_status not in ("", "open", "in_progress", "done"):
                admin_task_status = ""
            admin_tasks_search = (request.args.get("search") or "").strip()
            admin_tasks_page = request.args.get("page", type=int) or 1
            admin_tasks_page = max(1, int(admin_tasks_page))
            admin_sort = (request.args.get("sort") or "").strip().lower()
            if admin_sort not in ("task", "project", "user", "status", "priority"):
                admin_sort = ""
            admin_sort_direction = (request.args.get("direction") or "asc").strip().lower()
            if admin_sort_direction not in ("asc", "desc"):
                admin_sort_direction = "asc"

            q = Task.query.options(joinedload(Task.project), joinedload(Task.assignee))
            if admin_task_status:
                q = q.filter(Task.status == admin_task_status)
            if admin_tasks_search:
                like = f"%{admin_tasks_search}%"
                q = (
                    q.join(Project, Task.project_id == Project.id, isouter=True)
                    .join(User, Task.user_id == User.id, isouter=True)
                    .filter(or_(Project.name.ilike(like), User.name.ilike(like)))
                )
            admin_tasks_total = q.count()
            if admin_tasks_total == 0:
                admin_tasks_page_count = 1
                admin_tasks_page = 1
            else:
                admin_tasks_page_count = (admin_tasks_total + admin_tasks_per_page - 1) // admin_tasks_per_page
                admin_tasks_page = min(admin_tasks_page, admin_tasks_page_count)
            admin_tasks = (
                q.order_by(Task.created_at.desc(), Task.id.desc())
                .offset((admin_tasks_page - 1) * admin_tasks_per_page)
                .limit(admin_tasks_per_page)
                .all()
            )
        admin_all_tasks_boot: dict | None = None
        if actor is not None and actor.is_admin:
            boot_tasks: list[dict] = []
            for t in admin_tasks:
                p = t.project
                u = t.assignee
                boot_tasks.append(
                    {
                        "id": t.id,
                        "title": t.title or "",
                        "status": t.status,
                        "priority": t.priority or "medium",
                        "projectName": p.name if p else "No project",
                        "userName": u.name if u else "",
                        "updateUrl": url_for("control_task_update", task_id=t.id),
                        "deleteUrl": url_for("control_task_delete", task_id=t.id),
                    }
                )
            admin_all_tasks_boot = {
                "apiUrl": url_for("api_tasks_all"),
                "controlPanelPath": url_for("control_panel"),
                "perPage": admin_tasks_per_page,
                "taskStatus": admin_task_status,
                "search": admin_tasks_search,
                "page": admin_tasks_page,
                "total": admin_tasks_total,
                "pageCount": admin_tasks_page_count,
                "sort": admin_sort,
                "direction": admin_sort_direction,
                "tasks": boot_tasks,
            }
        return render_template(
            "control_panel.html",
            groups=groups,
            presets_by_group=dict(presets_by_group),
            job_titles=job_titles,
            admin_tasks=admin_tasks,
            admin_tasks_total=admin_tasks_total,
            admin_tasks_page=admin_tasks_page,
            admin_tasks_per_page=admin_tasks_per_page,
            admin_tasks_page_count=admin_tasks_page_count,
            admin_task_status=admin_task_status,
            admin_tasks_search=admin_tasks_search,
            admin_sort=admin_sort,
            admin_sort_direction=admin_sort_direction,
            admin_all_tasks_boot=admin_all_tasks_boot,
        )

    @app.route("/control/tasks/<int:task_id>/update", methods=["POST"])
    def control_task_update(task_id: int):
        actor = account_from_session()
        if actor is None or not actor.is_admin:
            abort(403)
        t = Task.query.get_or_404(task_id)
        title = (request.form.get("title") or "").strip()
        status = (request.form.get("status") or "").strip().lower()
        priority = (request.form.get("priority") or "").strip().lower()
        if not title:
            flash("Title is required.", "error")
        elif status not in ("open", "in_progress", "done"):
            flash("Invalid status.", "error")
        elif priority not in ("low", "medium", "high"):
            flash("Invalid priority.", "error")
        else:
            t.title = title
            t.status = status
            t.priority = priority
            if status == "done" and t.completed_at is None:
                t.completed_at = now_local()
            if status != "done":
                t.completed_at = None
            db.session.commit()
            emit_tasks_feed_changed(t.project_id)
            flash("Task updated.", "success")
        raw_next = (request.form.get("next") or "").strip()
        if raw_next.startswith("/") and not raw_next.startswith("//"):
            return redirect(raw_next)
        return redirect(url_for("control_panel", section="all-tasks"))

    @app.route("/control/tasks/<int:task_id>/delete", methods=["POST"])
    def control_task_delete(task_id: int):
        actor = account_from_session()
        if actor is None or not actor.is_admin:
            abort(403)
        t = Task.query.get_or_404(task_id)
        ctl_pid = t.project_id
        db.session.delete(t)
        db.session.commit()
        emit_tasks_feed_changed(ctl_pid)
        flash("Task deleted.", "success")
        raw_next = (request.form.get("next") or "").strip()
        if raw_next.startswith("/") and not raw_next.startswith("//"):
            return redirect(raw_next)
        return redirect(url_for("control_panel", section="all-tasks"))

    @app.route("/control/groups/new", methods=["POST"])
    def control_groups_new():
        name = (request.form.get("name") or "").strip()
        if not name:
            flash("Group name is required.", "error")
            return redirect(url_for("control_panel"))
        max_ord = db.session.query(db.func.max(TaskGroup.sort_order)).scalar()
        next_ord = (max_ord if max_ord is not None else -1) + 1
        db.session.add(TaskGroup(name=name, sort_order=next_ord))
        try:
            db.session.commit()
            flash("Task group added.", "success")
        except sa_exc.IntegrityError:
            db.session.rollback()
            flash("A group with that name already exists.", "error")
        return redirect(url_for("control_panel"))

    @app.route("/control/groups/<int:group_id>/rename", methods=["POST"])
    def control_groups_rename(group_id: int):
        g = TaskGroup.query.get_or_404(group_id)
        name = (request.form.get("name") or "").strip()
        if not name:
            flash("Group name is required.", "error")
            return redirect(url_for("control_panel"))
        g.name = name
        try:
            db.session.commit()
            flash("Group renamed.", "success")
        except sa_exc.IntegrityError:
            db.session.rollback()
            flash("A group with that name already exists.", "error")
        return redirect(url_for("control_panel"))

    @app.route("/control/groups/<int:group_id>/move", methods=["POST"])
    def control_groups_move(group_id: int):
        direction = (request.form.get("direction") or "").lower()
        if direction not in ("up", "down"):
            return redirect(url_for("control_panel"))
        ordered = TaskGroup.query.order_by(TaskGroup.sort_order, TaskGroup.id).all()
        ids = [x.id for x in ordered]
        if group_id not in ids:
            return redirect(url_for("control_panel"))
        i = ids.index(group_id)
        j = i - 1 if direction == "up" else i + 1
        if j < 0 or j >= len(ordered):
            return redirect(url_for("control_panel"))
        a, b = ordered[i], ordered[j]
        a.sort_order, b.sort_order = b.sort_order, a.sort_order
        db.session.commit()
        return redirect(url_for("control_panel"))

    @app.route("/control/groups/<int:group_id>/delete", methods=["POST"])
    def control_groups_delete(group_id: int):
        g = TaskGroup.query.get_or_404(group_id)
        for pt in TaskGroupTitle.query.filter_by(group_id=g.id).all():
            db.session.delete(pt)
        for t in Task.query.filter_by(group_id=g.id).all():
            t.group_id = None
        db.session.delete(g)
        db.session.commit()
        flash("Group removed. Task title presets were deleted; existing tasks were uncategorized.", "success")
        return redirect(url_for("control_panel"))

    @app.route("/control/titles/new", methods=["POST"])
    def control_title_new():
        title = (request.form.get("title") or "").strip()
        description = (request.form.get("description") or "").strip()
        group_id = request.form.get("group_id", type=int)
        if not title or not group_id:
            flash("Task title and group are required.", "error")
            return redirect(url_for("control_panel"))
        group = TaskGroup.query.get(group_id)
        if not group:
            flash("Invalid group.", "error")
            return redirect(url_for("control_panel"))
        if TaskGroupTitle.query.filter_by(group_id=group.id, title=title).first():
            flash("That task title already exists in this group.", "error")
            return redirect(url_for("control_panel"))
        mx = (
            db.session.query(db.func.max(TaskGroupTitle.sort_order))
            .filter(TaskGroupTitle.group_id == group.id)
            .scalar()
        )
        nxt = (mx if mx is not None else -1) + 1
        db.session.add(
            TaskGroupTitle(
                group_id=group.id,
                title=title,
                description=description,
                sort_order=nxt,
            )
        )
        db.session.commit()
        flash("Task title added.", "success")
        return redirect(url_for("control_panel"))

    @app.route("/control/titles/<int:title_id>/delete", methods=["POST"])
    def control_title_delete(title_id: int):
        pt = TaskGroupTitle.query.get_or_404(title_id)
        db.session.delete(pt)
        db.session.commit()
        flash("Task title removed from the group.", "success")
        return redirect(url_for("control_panel"))

    @app.route("/control/job-titles/new", methods=["POST"])
    def control_job_title_new():
        name = (request.form.get("name") or "").strip()
        if not name:
            flash("Job title name is required.", "error")
            return redirect(url_for("control_panel"))
        db.session.add(JobTitle(name=name))
        try:
            db.session.commit()
            flash("Job title added.", "success")
        except sa_exc.IntegrityError:
            db.session.rollback()
            flash("A job title with that name already exists.", "error")
        return redirect(url_for("control_panel"))

    @app.route("/control/job-titles/<int:job_title_id>/rename", methods=["POST"])
    def control_job_title_rename(job_title_id: int):
        jt = JobTitle.query.get_or_404(job_title_id)
        name = (request.form.get("name") or "").strip()
        if not name:
            flash("Job title name is required.", "error")
            return redirect(url_for("control_panel"))
        jt.name = name
        try:
            db.session.commit()
            flash("Job title updated.", "success")
        except sa_exc.IntegrityError:
            db.session.rollback()
            flash("A job title with that name already exists.", "error")
        return redirect(url_for("control_panel"))

    @app.route("/control/job-titles/<int:job_title_id>/delete", methods=["POST"])
    def control_job_title_delete(job_title_id: int):
        jt = JobTitle.query.get_or_404(job_title_id)
        for u in User.query.filter_by(job_title_id=jt.id).all():
            u.job_title_id = None
        db.session.delete(jt)
        db.session.commit()
        flash("Job title removed. Users with this title had their selection cleared.", "success")
        return redirect(url_for("control_panel"))

    @socketio.on("connect")
    def _socket_connect(auth=None):
        aid = session.get("account_id")
        if not aid and auth and isinstance(auth, dict):
            raw = auth.get("token")
            if raw:
                try:
                    ser = URLSafeTimedSerializer(app.config["SECRET_KEY"], salt=SOCKET_AUTH_SALT)
                    data = ser.loads(raw, max_age=SOCKET_AUTH_MAX_AGE)
                    cand = data.get("account_id")
                    if cand is not None and db.session.get(Account, int(cand)) is not None:
                        aid = int(cand)
                except (BadSignature, SignatureExpired, TypeError, ValueError):
                    aid = None
        if not aid:
            return False
        join_room(f"user_{aid}")
        join_room("tasks_feed")
        return True

    @socketio.on("join_project")
    def _socket_join_project(data):
        if not isinstance(data, dict):
            return
        try:
            pid = int(data.get("project_id"))
        except (TypeError, ValueError):
            return
        acc = db.session.get(Account, session.get("account_id"))
        if not account_may_use_project_chat(acc, pid):
            return
        prev = session.get("socket_chat_project_id")
        if prev is not None and prev != pid:
            leave_room(f"project_{prev}")
        join_room(f"project_{pid}")
        session["socket_chat_project_id"] = pid
        session.modified = True

    @socketio.on("sync_chat_rooms")
    def _socket_sync_chat_rooms(data):
        """Subscribe to chat_updated for multiple projects (dashboard chat hub)."""
        if not isinstance(data, dict):
            return
        raw = data.get("project_ids")
        if not isinstance(raw, list):
            return
        acc = db.session.get(Account, session.get("account_id"))
        if acc is None:
            return
        validated: list[int] = []
        for x in raw:
            try:
                pid = int(x)
            except (TypeError, ValueError):
                continue
            if account_may_use_project_chat(acc, pid):
                validated.append(pid)
        prev_list = session.get("socket_chat_room_set") or []
        prev_set = {int(x) for x in prev_list if x is not None}
        new_set = set(validated)
        for pid in prev_set - new_set:
            leave_room(f"project_{pid}")
        for pid in new_set - prev_set:
            join_room(f"project_{pid}")
        session["socket_chat_room_set"] = list(new_set)
        session.modified = True

    @socketio.on("leave_project")
    def _socket_leave_project(data):
        if not isinstance(data, dict):
            data = {}
        raw = data.get("project_id")
        try:
            pid = int(raw)
        except (TypeError, ValueError):
            pid = session.get("socket_chat_project_id")
        if pid is None:
            return
        leave_room(f"project_{pid}")
        if session.get("socket_chat_project_id") == pid:
            session.pop("socket_chat_project_id", None)
            session.modified = True

    # Expose ORM classes for `tests/` (GET /notifications panel checks, etc.).
    app.extensions["tm_test_models"] = {
        "Account": Account,
        "User": User,
        "Project": Project,
        "ProjectMember": ProjectMember,
        "Notification": Notification,
    }

    return app


app = create_app()

if __name__ == "__main__":
    # Default 5001: macOS AirPlay uses 5000 on ::1, so http://localhost:5000 often
    # hits AirTunes (403) instead of this app. Override with PORT / HOST if needed.
    _port = int(os.environ.get("PORT", "5001"))
    _host = os.environ.get("HOST", "127.0.0.1")
    _debug = True
    if (not _debug) or (os.environ.get("WERKZEUG_RUN_MAIN") == "true"):
        print(f"\n  Open in browser: http://{_host}:{_port}/\n", flush=True)
    socketio.run(
        app,
        host=_host,
        debug=_debug,
        port=_port,
        allow_unsafe_werkzeug=True,
    )
