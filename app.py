"""Users and tasks web application."""

from __future__ import annotations

import mimetypes
import os
import re
import uuid
from collections import defaultdict
from typing import Sequence
from datetime import date, datetime, timedelta, timezone
from flask import (
    Flask,
    Response,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import exc as sa_exc, inspect, or_, text
from sqlalchemy.orm import foreign, joinedload, selectinload
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from flask_socketio import SocketIO, join_room, leave_room

from booking import booking_bp

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
CHAT_REACTION_EMOJIS = frozenset({"👍", "❤️", "😂", "😮"})

def _project_type_is_tv_series(project_type: str | None) -> bool:
    """Episode count applies only to TV series projects."""
    return (project_type or "").strip().casefold() == "tv series"


VFX_STATUSES: tuple[str, ...] = (
    "pending",
    "assigned",
    "in_progress",
    "internal_review",
    "client_review",
    "approved",
    "delivered",
)
VFX_STATUS_INDEX = {k: i for i, k in enumerate(VFX_STATUSES)}
VFX_PRIORITIES: tuple[str, ...] = ("low", "medium", "high")
VFX_COMPLEXITIES: tuple[str, ...] = ("simple", "medium", "complex", "hero")


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
ROLE_USER = "user"
ROLE_GUEST = "guest"
ACCOUNT_ROLES = (ROLE_ADMIN, ROLE_SUPER_USER, ROLE_PRODUCER, ROLE_USER, ROLE_GUEST)

ROLE_LABELS = {
    ROLE_ADMIN: "Administrator",
    ROLE_SUPER_USER: "Super user",
    ROLE_PRODUCER: "Producer",
    ROLE_USER: "User",
    ROLE_GUEST: "Guest",
}

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
    app.config["CHAT_UPLOAD_FOLDER"] = chat_upload_root
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
        created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

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
        created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

        account = db.relationship("Account", backref=db.backref("directory_user", uselist=False))
        job_title = db.relationship("JobTitle", backref=db.backref("users", lazy=True))
        tasks = db.relationship("Task", backref="assignee", lazy=True, cascade="all, delete-orphan")

    class EditSuite(db.Model):
        """Post-production edit / color suite (bookable room)."""

        __tablename__ = "edit_suites"

        id = db.Column(db.Integer, primary_key=True)
        name = db.Column(db.String(200), nullable=False)
        is_active = db.Column(db.Boolean, nullable=False, default=True)

    class Vendor(db.Model):
        __tablename__ = "vendors"

        id = db.Column(db.Integer, primary_key=True)
        name = db.Column(db.String(200), nullable=False, unique=True)
        vendor_type = db.Column(db.String(32), nullable=False, default="studio")
        specialization = db.Column(db.String(120), nullable=False, default="")
        contact_info = db.Column(db.Text, nullable=False, default="")
        is_active = db.Column(db.Boolean, nullable=False, default=True)
        created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

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
        created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
        is_active = db.Column(db.Boolean, nullable=False, default=True)
        scene_id = db.Column(db.Integer, nullable=True, index=True)
        vfx_shot_id = db.Column(db.Integer, nullable=True, index=True)

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
        vfx_shot = db.relationship(
            "VfxShot",
            primaryjoin=lambda: foreign(Booking.vfx_shot_id) == VfxShot.id,
            backref=db.backref("suite_bookings_vfx", lazy=True),
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
        created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

        group = db.relationship("TaskGroup", backref=db.backref("title_presets", lazy=True))

    class TaskPriority(db.Model):
        __tablename__ = "task_priorities"

        id = db.Column(db.Integer, primary_key=True)
        name = db.Column(db.String(80), nullable=False, unique=True)
        created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

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
        created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
        completed_at = db.Column(db.DateTime, nullable=True)
        archived = db.Column(db.Boolean, nullable=False, default=False)

        group = db.relationship("TaskGroup", backref=db.backref("tasks", lazy=True))
        project = db.relationship("Project", back_populates="tasks")

    class Project(db.Model):
        __tablename__ = "projects"

        id = db.Column(db.Integer, primary_key=True)
        name = db.Column(db.String(200), nullable=False)
        project_type = db.Column(db.String(120), nullable=False)
        production_house = db.Column(db.String(200), nullable=False)
        director = db.Column(db.String(200), nullable=False)
        created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
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

        id = db.Column(db.Integer, primary_key=True)
        project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False, index=True)
        shooting_day_id = db.Column(
            db.Integer, db.ForeignKey("shooting_days_flat.id"), nullable=False, index=True
        )
        shooting_day_scene_id = db.Column(
            db.Integer,
            db.ForeignKey("shooting_day_scenes.id"),
            nullable=False,
            unique=True,
            index=True,
        )
        episode_number = db.Column(db.Integer, nullable=False, default=1, index=True)
        scene_number = db.Column(db.Integer, nullable=False, default=1, index=True)
        shot_code = db.Column(db.String(64), nullable=False, unique=True, index=True)
        description = db.Column(db.Text, nullable=False, default="")
        status = db.Column(db.String(16), nullable=False, default="pending", index=True)
        priority = db.Column(db.String(16), nullable=False, default="medium", index=True)
        complexity = db.Column(db.String(16), nullable=False, default="medium", index=True)
        assigned_artist_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
        assigned_vendor_id = db.Column(db.Integer, db.ForeignKey("vendors.id"), nullable=True, index=True)
        # Legacy fields retained for compatibility with existing SQLite rows.
        assigned_to = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
        assigned_vendor = db.Column(db.String(120), nullable=False, default="")
        estimated_days = db.Column(db.Integer, nullable=False, default=0)
        actual_days = db.Column(db.Integer, nullable=False, default=0)
        estimated_cost = db.Column(db.Float, nullable=False, default=0.0)
        actual_cost = db.Column(db.Float, nullable=False, default=0.0)
        currency = db.Column(db.String(8), nullable=False, default="USD")
        version = db.Column(db.Integer, nullable=False, default=1)
        version_number = db.Column(db.Integer, nullable=False, default=1)
        created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
        updated_at = db.Column(
            db.DateTime,
            default=lambda: datetime.now(timezone.utc),
            onupdate=lambda: datetime.now(timezone.utc),
            nullable=False,
        )

        project = db.relationship("Project", backref=db.backref("vfx_shots", lazy=True))
        shooting_day = db.relationship("ShootingDay", backref=db.backref("vfx_shots", lazy=True))
        source_scene = db.relationship(
            "ShootingDayScene",
            backref=db.backref("vfx_shot", uselist=False),
            uselist=False,
        )
        assignee = db.relationship(
            "User",
            foreign_keys=[assigned_artist_id],
            backref=db.backref("vfx_assigned_shots", lazy=True),
        )
        vendor = db.relationship("Vendor", backref=db.backref("vfx_shots", lazy=True))

    class VfxComment(db.Model):
        __tablename__ = "vfx_comment"

        id = db.Column(db.Integer, primary_key=True)
        vfx_shot_id = db.Column(db.Integer, db.ForeignKey("vfx_shot.id"), nullable=False, index=True)
        user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
        comment = db.Column(db.Text, nullable=False, default="")
        created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

        shot = db.relationship(
            "VfxShot",
            backref=db.backref("comments", lazy=True, cascade="all, delete-orphan"),
        )
        user = db.relationship("User", backref=db.backref("vfx_comments", lazy=True))

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
        created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
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
        created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

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
        created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)

        user = db.relationship("User", backref=db.backref("notifications", lazy=True))
        project = db.relationship("Project", backref=db.backref("notifications", lazy=True))

    # Hard-disk UI: audio entered in GB; columns remain TB (decimal GB per TB).
    HDD_STORAGE_GB_PER_TB = 1000.0
    VFX_REVIEW_THRESHOLD_DAYS = 2

    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)

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
    ) -> None:
        """Create one notification per project team member (user-specific rows)."""
        if project_id is None:
            return
        uid_list = _project_team_user_ids(project_id)
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
                Notification.is_resolved.is_(False),
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
    ) -> None:
        suite = db.session.get(EditSuite, suite_id)
        suite_name = (suite.name if suite is not None else f"Suite {suite_id}").strip()
        overlap_rule = (
            f"booking_overlap|{project_id}|{suite_id}|{booking_date.isoformat()}|"
            f"{start_t.isoformat()}|{end_t.isoformat()}"
        )
        _notification_emit_to_project(
            project_id=project_id,
            rule=overlap_rule,
            n_type="alert",
            severity="critical",
            title="Booking overlap detected",
            message=f"{suite_name} overlaps on {booking_date.isoformat()} ({start_t.strftime('%H:%M')}–{end_t.strftime('%H:%M')}).",
            entity_type="booking",
            entity_id=int(suite_id),
        )

    def emit_shooting_day_created_activity(day: ShootingDay, source: str) -> None:
        _notification_emit_to_project(
            project_id=day.project_id,
            rule="shooting_day_created",
            n_type="activity",
            severity="info",
            title=f"Shooting day created ({source})",
            message=f"Unit {int(day.unit_number or 1)} · Day {(day.day_name or '').strip() or '—'} · {day.shooting_date.isoformat()}",
            entity_type="shooting_day",
            entity_id=day.id,
        )

    def emit_vfx_delivered_activity(shot: VfxShot) -> None:
        ver = int(shot.version_number or shot.version or 1)
        _notification_emit_to_project(
            project_id=shot.project_id,
            rule=f"vfx_delivered|{shot.id}|{ver}",
            n_type="activity",
            severity="info",
            title=f"VFX delivered: {(shot.shot_code or '').strip() or 'Shot'}",
            message=(shot.description or "").strip()[:240] or "Shot marked delivered.",
            entity_type="vfx",
            entity_id=shot.id,
        )

    def evaluate_vfx_review_notifications(project_id: int | None = None) -> None:
        q = VfxShot.query.filter(VfxShot.status.in_(("internal_review", "client_review")))
        if project_id is not None:
            q = q.filter(VfxShot.project_id == project_id)
        shots = q.all()
        now = _utc_now()
        for shot in shots:
            ts = shot.updated_at or shot.created_at
            if ts is None:
                continue
            age = now - ts
            if age > timedelta(days=VFX_REVIEW_THRESHOLD_DAYS):
                _notification_emit_to_project(
                    project_id=shot.project_id,
                    rule="vfx_review_stale",
                    n_type="alert",
                    severity="warning",
                    title=f"VFX in review > {VFX_REVIEW_THRESHOLD_DAYS} days",
                    message=f"{(shot.shot_code or 'Shot').strip()} is still in review.",
                    entity_type="vfx",
                    entity_id=shot.id,
                )
        for row in Notification.query.filter(
            Notification.rule_key.startswith("vfx_review_stale:"),
            Notification.is_resolved.is_(False),
        ).all():
            shot = db.session.get(VfxShot, int(row.entity_id or 0))
            keep = False
            if shot is not None and (shot.status or "").strip() in ("internal_review", "client_review"):
                ts2 = shot.updated_at or shot.created_at
                if ts2 is not None and (now - ts2) > timedelta(days=VFX_REVIEW_THRESHOLD_DAYS):
                    keep = True
            if not keep:
                row.is_resolved = True
                row.is_read = True

    def _notification_relative_time(ts: datetime | None) -> str:
        if ts is None:
            return ""
        delta = _utc_now() - ts
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

    def _notification_to_dict(n: Notification) -> dict:
        return {
            "id": n.id,
            "type": (n.type or "activity").strip().lower(),
            "severity": (n.severity or "info").strip().lower(),
            "title": n.title or "",
            "message": n.message or "",
            "entity_type": n.entity_type or "",
            "entity_id": int(n.entity_id or 0),
            "project_id": int(n.project_id) if n.project_id is not None else None,
            "is_read": bool(n.is_read),
            "is_acknowledged": bool(n.is_acknowledged),
            "is_resolved": bool(n.is_resolved),
            "created_at": n.created_at.isoformat(timespec="seconds") if n.created_at else None,
            "created_ago": _notification_relative_time(n.created_at),
        }

    Task.project = db.relationship("Project", back_populates="tasks")

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

    def _next_vfx_shot_index(project_id: int, episode_number: int, scene_number: int) -> int:
        # `shot_code` is globally unique in SQLite schema, so include project id.
        prefix = f"P{int(project_id or 0):04d}_EP{int(episode_number or 0):02d}_SC{int(scene_number or 0):02d}_SH"
        rows = (
            VfxShot.query.filter(
                VfxShot.project_id == project_id,
                VfxShot.shot_code.like(f"{prefix}%"),
            )
            .order_by(VfxShot.id.asc())
            .all()
        )
        mx = 0
        for row in rows:
            code = (row.shot_code or "").strip().upper()
            mm = re.search(r"_SH(\d+)$", code)
            if not mm:
                continue
            try:
                mx = max(mx, int(mm.group(1)))
            except (TypeError, ValueError):
                continue
        return mx + 1

    def _build_vfx_shot_code(project_id: int, episode_number: int, scene_number: int) -> str:
        shot_n = _next_vfx_shot_index(project_id, episode_number, scene_number)
        return (
            f"P{int(project_id or 0):04d}_"
            f"EP{int(episode_number or 0):02d}_SC{int(scene_number or 0):02d}_SH{int(shot_n):02d}"
        )

    def ensure_vfx_shot_for_scene(scene: ShootingDayScene, force: bool = False) -> VfxShot | None:
        """Create a VFX shot if missing for a scene marked Needs VFX."""
        if scene is None or scene.shooting_day is None:
            return None
        if not force and not bool(scene.needs_vfx):
            return None
        existing = VfxShot.query.filter_by(shooting_day_scene_id=scene.id).first()
        if existing is not None:
            return existing
        sc_n = _parse_scene_number_from_label(scene.scene_label, fallback=scene.scene_number or 1)
        label = (scene.scene_label or "").strip()
        shot = VfxShot(
            project_id=scene.shooting_day.project_id,
            shooting_day_id=scene.shooting_day_id,
            shooting_day_scene_id=scene.id,
            episode_number=max(1, int(scene.episode_number or 1)),
            scene_number=sc_n,
            shot_code=_build_vfx_shot_code(scene.shooting_day.project_id, scene.episode_number, sc_n),
            description=label or f"Scene {sc_n}",
            status="pending",
            priority="medium",
            complexity="medium",
            estimated_days=0,
            actual_days=0,
            estimated_cost=0.0,
            actual_cost=0.0,
            currency="USD",
            version=1,
            version_number=1,
        )
        db.session.add(shot)
        return shot

    def _vfx_status_transition_ok(prev_status: str, next_status: str) -> bool:
        prev = (prev_status or "").strip().lower()
        nxt = (next_status or "").strip().lower()
        if prev not in VFX_STATUS_INDEX or nxt not in VFX_STATUS_INDEX:
            return False
        if prev == "delivered":
            return nxt == "delivered"
        return VFX_STATUS_INDEX[nxt] in (VFX_STATUS_INDEX[prev], VFX_STATUS_INDEX[prev] + 1)

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

    def ensure_sqlite_vfx_columns() -> None:
        if db.engine.dialect.name != "sqlite":
            return
        insp = inspect(db.engine)
        tables = set(insp.get_table_names())
        if "vendors" not in tables:
            Vendor.__table__.create(bind=db.engine, checkfirst=True)
        if "vfx_shot" not in tables:
            VfxShot.__table__.create(bind=db.engine, checkfirst=True)
        if "vfx_comment" not in tables:
            VfxComment.__table__.create(bind=db.engine, checkfirst=True)

        if "vfx_shot" in inspect(db.engine).get_table_names():
            cols = {c["name"] for c in inspect(db.engine).get_columns("vfx_shot")}
            with db.engine.begin() as conn:
                if "complexity" not in cols:
                    conn.execute(
                        text("ALTER TABLE vfx_shot ADD COLUMN complexity VARCHAR(16) NOT NULL DEFAULT 'medium'")
                    )
                if "assigned_artist_id" not in cols:
                    conn.execute(text("ALTER TABLE vfx_shot ADD COLUMN assigned_artist_id INTEGER"))
                if "assigned_vendor_id" not in cols:
                    conn.execute(text("ALTER TABLE vfx_shot ADD COLUMN assigned_vendor_id INTEGER"))
                if "estimated_cost" not in cols:
                    conn.execute(text("ALTER TABLE vfx_shot ADD COLUMN estimated_cost FLOAT NOT NULL DEFAULT 0"))
                if "actual_cost" not in cols:
                    conn.execute(text("ALTER TABLE vfx_shot ADD COLUMN actual_cost FLOAT NOT NULL DEFAULT 0"))
                if "currency" not in cols:
                    conn.execute(text("ALTER TABLE vfx_shot ADD COLUMN currency VARCHAR(8) NOT NULL DEFAULT 'USD'"))
                if "version_number" not in cols:
                    conn.execute(text("ALTER TABLE vfx_shot ADD COLUMN version_number INTEGER NOT NULL DEFAULT 1"))
                if "status" in cols:
                    conn.execute(
                        text(
                            "UPDATE vfx_shot SET status='internal_review' "
                            "WHERE trim(lower(coalesce(status,'')))='review'"
                        )
                    )
                if "assigned_to" in cols and "assigned_artist_id" in cols:
                    conn.execute(
                        text(
                            "UPDATE vfx_shot SET assigned_artist_id = assigned_to "
                            "WHERE assigned_artist_id IS NULL AND assigned_to IS NOT NULL"
                        )
                    )
                if "version" in cols and "version_number" in cols:
                    conn.execute(
                        text(
                            "UPDATE vfx_shot SET version_number = version "
                            "WHERE version_number = 1 AND version > 1"
                        )
                    )

        if "bookings" in inspect(db.engine).get_table_names():
            bcols = {c["name"] for c in inspect(db.engine).get_columns("bookings")}
            if "vfx_shot_id" not in bcols:
                with db.engine.begin() as conn:
                    conn.execute(text("ALTER TABLE bookings ADD COLUMN vfx_shot_id INTEGER"))

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
        ensure_sqlite_bookings_v2_columns()
        ensure_sqlite_bookings_scene_id_column()
        ensure_sqlite_shooting_days_flat_unit_day_name_columns()
        ensure_sqlite_shooting_day_scenes_pipeline_columns()
        ensure_sqlite_vfx_columns()
        ensure_sqlite_hard_disk_tables()
        ensure_sqlite_notification_tables()

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

    def account_may_use_machine_project_view(acc: Account | None) -> bool:
        """Machine Room project management access (/machine/project/<id>)."""
        if acc is None:
            return False
        r = _normalized_account_role_key(acc.role)
        return r == ROLE_ADMIN or r == ROLE_PRODUCER

    def account_can_access_admin_settings(acc: Account | None) -> bool:
        """Users page, Control panel, and related actions — administrator role only (not super user)."""
        return acc is not None and acc.is_admin

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
            "current_account_is_elevated": bool(acc and account_is_elevated(acc)),
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

    def visible_project_ids_for_account(acc: Account | None) -> set[int] | None:
        """None means no filter (administrator only). Otherwise project IDs from team membership."""
        if acc is None:
            return set()
        if acc.is_admin:
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
        "Vendor": Vendor,
        "EditSuite": EditSuite,
        "Booking": Booking,
        "ProductionScene": ProductionScene,
        "ProductionEpisode": ProductionEpisode,
        "VfxShot": VfxShot,
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
                last_at_iso = m.created_at.isoformat() if m.created_at else None
                if m.created_at:
                    last_sort = m.created_at.timestamp()
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
        created_iso = m.created_at.isoformat() if m.created_at else ""
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

    def task_visible_to_account(t: Task, acc: Account | None) -> bool:
        if acc is None:
            return False
        if acc.is_admin:
            return True
        allowed = visible_project_ids_for_account(acc)
        if t.project_id is None:
            return False
        return bool(allowed and t.project_id in allowed)

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
        acc = Account.query.get(session.get("account_id"))
        return account_may_update_task_status(task, acc)

    @app.template_global()
    def can_archive_task(task: Task) -> bool:
        acc = Account.query.get(session.get("account_id"))
        return account_may_archive_task(task, acc)

    @app.template_global()
    def can_delete_task(task: Task) -> bool:
        acc = Account.query.get(session.get("account_id"))
        return task_visible_to_account(task, acc)

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

    def vfx_shot_for_project(shot_id: int, project_id: int) -> VfxShot | None:
        shot = (
            VfxShot.query.options(
                joinedload(VfxShot.assignee).joinedload(User.job_title),
                joinedload(VfxShot.vendor),
                joinedload(VfxShot.source_scene),
            )
            .filter_by(id=shot_id)
            .first()
        )
        if shot is None or int(shot.project_id or 0) != int(project_id):
            return None
        return shot

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
        acc = Account.query.get(session.get("account_id"))
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
        acc = Account.query.get(session.get("account_id"))
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
        acc = Account.query.get(session.get("account_id"))
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
        acc = Account.query.get(session.get("account_id"))
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
        acc = Account.query.get(aid)
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

    @app.route("/")
    def index():
        acc = Account.query.get(session.get("account_id"))
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
                        Booking.booking_date == date.today(),
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

        return render_template(
            "index.html",
            user_count=user_count,
            task_count=task_count,
            open_tasks=open_tasks,
            project_count=project_count,
            booking_today_card=booking_today_card,
        )

    @app.route("/chat/threads", methods=["GET"])
    def chat_threads_api():
        # Match inject_globals / account_from_session (int PK); avoid query.get(session id)
        # type mismatches that returned 403 while the shell still rendered as "logged in".
        acc = account_from_session()
        if acc is None:
            return jsonify({"threads": []})
        return jsonify({"threads": build_chat_threads_for_dashboard(acc)})

    @app.route("/projects")
    def projects_list():
        acc = Account.query.get(session.get("account_id"))
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
        today = date.today()
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
        vfx_ctx = build_vfx_management_context(p)
        return render_template(
            "machine_project.html",
            project=p,
            workflow_active="overview",
            **machine_ctx,
            **vfx_ctx,
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
        if uid is None:
            return jsonify({"ok": True, "notifications": []})
        # Evaluate stale review warnings on fetch to avoid background jobs.
        evaluate_vfx_review_notifications()
        db.session.commit()
        raw_limit = (request.args.get("limit") or "50").strip()
        try:
            limit = max(1, min(200, int(raw_limit)))
        except (TypeError, ValueError):
            limit = 50
        kind = (request.args.get("type") or "all").strip().lower()
        q = (
            Notification.query.filter_by(user_id=uid)
            .filter(Notification.is_resolved.is_(False))
            .order_by(Notification.created_at.desc(), Notification.id.desc())
        )
        if kind in ("alert", "activity"):
            q = q.filter(Notification.type == kind)
        rows = q.limit(limit).all()
        return jsonify({"ok": True, "notifications": [_notification_to_dict(n) for n in rows]})

    @app.route("/notifications/read-all", methods=["POST"])
    def notifications_mark_all_read():
        actor = account_from_session()
        if actor is None:
            return jsonify({"ok": False, "error": "forbidden"}), 403
        uid = directory_user_id_for_account(actor)
        if uid is None:
            return jsonify({"ok": True})
        for r in Notification.query.filter(
            Notification.user_id == uid,
            Notification.is_read.is_(False),
        ).all():
            r.is_read = True
        db.session.commit()
        return jsonify({"ok": True})

    def _notification_mark_field(notification_id: int, field_name: str):
        actor = account_from_session()
        if actor is None:
            return jsonify({"ok": False, "error": "forbidden"}), 403
        uid = directory_user_id_for_account(actor)
        if uid is None:
            return jsonify({"ok": False, "error": "forbidden"}), 403
        n = db.session.get(Notification, notification_id)
        if n is None:
            return jsonify({"ok": False, "error": "not_found"}), 404
        if int(n.user_id or 0) != int(uid):
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
        try:
            emit_shooting_day_created_activity(day, "machine")
            db.session.commit()
        except sa_exc.IntegrityError:
            db.session.rollback()
            return jsonify({"ok": False, "error": "conflict"}), 409
        evaluate_hdd_notifications(hd.id)
        db.session.commit()
        return jsonify({"ok": True})

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
        actor = Account.query.get(session.get("account_id"))
        if actor is None or not account_is_elevated(actor):
            flash("Only administrators and super users can create projects.", "error")
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
        creator_uid = directory_user_id_for_account(actor)
        if creator_uid is not None:
            if ProjectMember.query.filter_by(project_id=p.id, user_id=creator_uid).first() is None:
                db.session.add(ProjectMember(project_id=p.id, user_id=creator_uid))
                db.session.commit()
        flash("Project created.", "success")
        return redirect(url_for("projects_list"))

    @app.route("/projects/reorder", methods=["POST"])
    def projects_reorder():
        actor = Account.query.get(session.get("account_id"))
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
        acc = Account.query.get(session.get("account_id"))
        p = Project.query.get_or_404(project_id)
        if not account_can_access_project(acc, p.id):
            flash("You do not have access to that project.", "error")
            return redirect(url_for("projects_list"))
        project_tasks_all = (
            Task.query.options(joinedload(Task.group), joinedload(Task.assignee))
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

    @app.route("/projects/<int:project_id>/completed")
    def project_completed_tasks(project_id: int):
        acc = Account.query.get(session.get("account_id"))
        p = Project.query.get_or_404(project_id)
        if not account_can_access_project(acc, p.id):
            flash("You do not have access to that project.", "error")
            return redirect(url_for("projects_list"))
        project_tasks_all = (
            Task.query.options(joinedload(Task.group), joinedload(Task.assignee))
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
        acc = Account.query.get(session.get("account_id"))
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
        acc = Account.query.get(session.get("account_id"))
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

    def build_vfx_management_context(p: Project) -> dict:
        """Shared VFX panel context for production VFX page and Machine Room project view."""
        pending_vfx_rows = (
            ShootingDayScene.query.join(ShootingDay, ShootingDayScene.shooting_day_id == ShootingDay.id)
            .filter(
                ShootingDay.project_id == p.id,
                ShootingDayScene.needs_vfx.is_(True),
            )
            .all()
        )
        created_any = False
        for row in pending_vfx_rows:
            before = VfxShot.query.filter_by(shooting_day_scene_id=row.id).first()
            if before is None:
                ensure_vfx_shot_for_scene(row, force=True)
                created_any = True
        if created_any:
            db.session.commit()
        shots = (
            VfxShot.query.options(
                joinedload(VfxShot.assignee).joinedload(User.job_title),
                joinedload(VfxShot.vendor),
                joinedload(VfxShot.source_scene),
            )
            .filter(VfxShot.project_id == p.id)
            .order_by(VfxShot.updated_at.desc(), VfxShot.id.desc())
            .all()
        )
        total_shots = len(shots)
        status_counts: dict[str, int] = {k: 0 for k in VFX_STATUSES}
        for shot in shots:
            st = (shot.status or "pending").strip().lower()
            if st not in status_counts:
                st = "pending"
            status_counts[st] += 1
        delivered_pct = int(round(100.0 * status_counts["delivered"] / total_shots)) if total_shots else 0
        in_progress_pct = (
            int(round(100.0 * status_counts["in_progress"] / total_shots)) if total_shots else 0
        )
        in_review_count = status_counts.get("internal_review", 0) + status_counts.get("client_review", 0)
        by_episode = sorted(
            {
                int(shot.episode_number or 0)
                for shot in shots
                if int(shot.episode_number or 0) > 0
            }
        )
        artist_users = (
            User.query.join(ProjectMember, ProjectMember.user_id == User.id)
            .options(joinedload(User.job_title))
            .filter(ProjectMember.project_id == p.id)
            .order_by(User.name.asc(), User.id.asc())
            .all()
        )
        vendors = (
            Vendor.query.order_by(Vendor.name.asc(), Vendor.id.asc()).all()
        )
        complexities = sorted(
            {
                (shot.complexity or "medium").strip().lower()
                for shot in shots
                if (shot.complexity or "").strip()
            }
        )
        return {
            "vfx_shots": shots,
            "vfx_status_counts": status_counts,
            "vfx_total_shots": total_shots,
            "vfx_in_review_count": in_review_count,
            "vfx_delivered_pct": delivered_pct,
            "vfx_in_progress_pct": in_progress_pct,
            "vfx_episode_options": by_episode,
            "vfx_artist_users": artist_users,
            "vfx_vendors": vendors,
            "vfx_statuses": VFX_STATUSES,
            "vfx_priorities": VFX_PRIORITIES,
            "vfx_complexities": (tuple(complexities) if complexities else VFX_COMPLEXITIES),
        }

    @app.route("/projects/<int:project_id>/production/vfx")
    def project_production_vfx(project_id: int):
        acc = Account.query.get(session.get("account_id"))
        p = Project.query.get_or_404(project_id)
        if not account_can_access_project(acc, p.id):
            flash("You do not have access to that project.", "error")
            return redirect(url_for("projects_list"))
        vfx_ctx = build_vfx_management_context(p)
        return render_template(
            "project_production.html",
            project=p,
            production_section="vfx",
            shooting_days=[],
            production_day_totals={},
            production_day_progress={},
            workflow_active="vfx",
            **vfx_ctx,
        )

    @app.route("/projects/<int:project_id>/episodes", methods=["GET", "POST"])
    def project_episodes(project_id: int):
        acc = Account.query.get(session.get("account_id"))
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
        acc = Account.query.get(session.get("account_id"))
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
        db.session.flush()
        ensure_vfx_shot_for_scene(row)
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
        acc = Account.query.get(session.get("account_id"))
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
        shot = VfxShot.query.filter_by(shooting_day_scene_id=link.id).first()
        if link.needs_vfx:
            shot = ensure_vfx_shot_for_scene(link)
        if shot is not None:
            shot.project_id = link.shooting_day.project_id
            shot.shooting_day_id = link.shooting_day_id
            shot.episode_number = max(1, int(link.episode_number or 1))
            shot.scene_number = _parse_scene_number_from_label(link.scene_label, fallback=link.scene_number or 1)
            if not (shot.description or "").strip():
                shot.description = (link.scene_label or "").strip() or f"Scene {shot.scene_number}"
        db.session.commit()
        flash("Shooting day row updated.", "success")
        return redirect(url_for("project_production_day", project_id=project_id, day_id=day_id))

    @app.route(
        "/projects/<int:project_id>/shooting-day-scenes/<int:link_id>/delete",
        methods=["POST"],
    )
    def shooting_day_scene_delete(project_id: int, link_id: int):
        acc = Account.query.get(session.get("account_id"))
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
        shot = VfxShot.query.filter_by(shooting_day_scene_id=link_id).first()
        if shot is not None:
            Booking.query.filter_by(vfx_shot_id=shot.id).update(
                {Booking.vfx_shot_id: None},
                synchronize_session=False,
            )
            db.session.delete(shot)
        db.session.delete(link)
        db.session.commit()
        flash("Scene row removed from this day.", "success")
        return redirect(url_for("project_production_day", project_id=project_id, day_id=day_id))

    @app.route("/projects/<int:project_id>/vfx/shots/<int:shot_id>", methods=["PATCH"])
    def project_vfx_shot_update(project_id: int, shot_id: int):
        acc = Account.query.get(session.get("account_id"))
        if not account_can_access_project(acc, project_id):
            return jsonify({"error": "forbidden"}), 403
        shot = vfx_shot_for_project(shot_id, project_id)
        if shot is None:
            return jsonify({"error": "not_found"}), 404
        if not request.is_json:
            return jsonify({"error": "validation", "message": "JSON body required."}), 400
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return jsonify({"error": "validation", "message": "Invalid body."}), 400

        if (shot.status or "").strip().lower() == "delivered":
            return (
                jsonify(
                    {
                        "error": "validation",
                        "message": "Delivered shots are locked.",
                    }
                ),
                400,
            )

        prev_status = (shot.status or "pending").strip().lower()
        status_in = (data.get("status") or shot.status or "pending").strip().lower()
        if status_in not in VFX_STATUS_INDEX:
            return jsonify({"error": "validation", "message": "Invalid status."}), 400
        if not _vfx_status_transition_ok(shot.status, status_in):
            return (
                jsonify(
                    {
                        "error": "validation",
                        "message": "Status must follow workflow order without skipping.",
                    }
                ),
                400,
            )

        priority_in = (data.get("priority") or shot.priority or "medium").strip().lower()
        if priority_in not in VFX_PRIORITIES:
            return jsonify({"error": "validation", "message": "Invalid priority."}), 400

        complexity_in = (data.get("complexity") or shot.complexity or "medium").strip().lower()
        if complexity_in not in VFX_COMPLEXITIES:
            return jsonify({"error": "validation", "message": "Invalid complexity."}), 400

        assigned_artist_id: int | None = None
        raw_assigned_to = data.get("assigned_artist_id", data.get("assigned_to"))
        if raw_assigned_to is not None and str(raw_assigned_to).strip() != "":
            try:
                assigned_artist_id = int(raw_assigned_to)
            except (TypeError, ValueError):
                return jsonify({"error": "validation", "message": "Invalid assignee."}), 400
            pm = ProjectMember.query.filter_by(project_id=project_id, user_id=assigned_artist_id).first()
            if pm is None:
                return jsonify({"error": "validation", "message": "Assignee must be on this project."}), 400
        assigned_vendor_id: int | None = None
        raw_vendor_id = data.get("assigned_vendor_id")
        if raw_vendor_id is not None and str(raw_vendor_id).strip() != "":
            try:
                assigned_vendor_id = int(raw_vendor_id)
            except (TypeError, ValueError):
                return jsonify({"error": "validation", "message": "Invalid vendor."}), 400
            vendor_obj = Vendor.query.get(assigned_vendor_id)
            if vendor_obj is None:
                return jsonify({"error": "validation", "message": "Vendor not found."}), 400

        assigned_vendor_name = (data.get("assigned_vendor") or "").strip()
        if len(assigned_vendor_name) > 120:
            return jsonify({"error": "validation", "message": "Vendor name is too long."}), 400
        if status_in != "pending" and assigned_artist_id is None and assigned_vendor_id is None and not assigned_vendor_name:
            return (
                jsonify(
                    {
                        "error": "validation",
                        "message": "Assign an artist or vendor before moving status forward.",
                    }
                ),
                400,
            )

        description = (data.get("description") or "").strip()
        if len(description) > 20_000:
            return jsonify({"error": "validation", "message": "Description is too long."}), 400

        try:
            estimated_days = max(0, int(data.get("estimated_days") or 0))
            actual_days = max(0, int(data.get("actual_days") or 0))
        except (TypeError, ValueError):
            return jsonify({"error": "validation", "message": "Days must be whole numbers."}), 400
        try:
            estimated_cost = max(0.0, float(data.get("estimated_cost") or 0))
            actual_cost = max(0.0, float(data.get("actual_cost") or 0))
        except (TypeError, ValueError):
            return jsonify({"error": "validation", "message": "Costs must be numeric."}), 400
        currency = (data.get("currency") or shot.currency or "USD").strip().upper()
        if len(currency) > 8:
            return jsonify({"error": "validation", "message": "Currency is too long."}), 400

        shot.status = status_in
        shot.priority = priority_in
        shot.complexity = complexity_in
        shot.assigned_artist_id = assigned_artist_id
        shot.assigned_vendor_id = assigned_vendor_id
        shot.assigned_to = assigned_artist_id
        shot.assigned_vendor = assigned_vendor_name
        shot.description = description
        shot.estimated_days = estimated_days
        shot.actual_days = actual_days
        shot.estimated_cost = estimated_cost
        shot.actual_cost = actual_cost
        shot.currency = currency
        shot.version = max(1, int(shot.version or 1)) + 1
        shot.version_number = max(1, int(shot.version_number or 1)) + 1
        shot.updated_at = datetime.now(timezone.utc)
        db.session.commit()
        if status_in == "delivered" and prev_status != "delivered":
            emit_vfx_delivered_activity(shot)
            db.session.commit()
        evaluate_vfx_review_notifications(project_id)
        db.session.commit()
        assignee = shot.assignee
        assignee_label = ""
        if assignee is not None:
            role_name = (
                (assignee.job_title.name or "").strip()
                if assignee.job_title is not None and assignee.job_title.name
                else ""
            )
            assignee_label = (assignee.name or "").strip()
            if role_name:
                assignee_label += f" — {role_name}"
        vendor = shot.vendor
        vendor_label = ""
        if vendor is not None:
            vendor_label = (vendor.name or "").strip()
            if (vendor.vendor_type or "").strip():
                vendor_label += f" ({vendor.vendor_type})"
        return jsonify(
            {
                "ok": True,
                "shot": {
                    "id": shot.id,
                    "status": shot.status,
                    "priority": shot.priority,
                    "complexity": shot.complexity,
                    "version": int(shot.version_number or shot.version or 1),
                    "assigned_artist_id": shot.assigned_artist_id,
                    "assigned_vendor_id": shot.assigned_vendor_id,
                    "assigned_to": shot.assigned_to,
                    "assigned_vendor": shot.assigned_vendor or "",
                    "assigned_label": assignee_label,
                    "vendor_label": vendor_label,
                    "description": shot.description or "",
                    "estimated_days": int(shot.estimated_days or 0),
                    "actual_days": int(shot.actual_days or 0),
                    "estimated_cost": float(shot.estimated_cost or 0),
                    "actual_cost": float(shot.actual_cost or 0),
                    "currency": shot.currency or "USD",
                    "updated_at": (
                        shot.updated_at.isoformat(timespec="seconds") if shot.updated_at else None
                    ),
                },
            }
        )

    @app.route("/projects/<int:project_id>/vfx/shots/<int:shot_id>/comments", methods=["POST"])
    def project_vfx_shot_comment_add(project_id: int, shot_id: int):
        acc = Account.query.get(session.get("account_id"))
        if not account_can_access_project(acc, project_id):
            return jsonify({"error": "forbidden"}), 403
        shot = vfx_shot_for_project(shot_id, project_id)
        if shot is None:
            return jsonify({"error": "not_found"}), 404
        uid = directory_user_id_for_account(acc)
        if uid is None:
            return jsonify({"error": "validation", "message": "No linked user for this account."}), 400
        body = request.get_json(silent=True) if request.is_json else {}
        if not isinstance(body, dict):
            body = {}
        txt = (body.get("comment") or "").strip()
        if not txt:
            return jsonify({"error": "validation", "message": "Comment is required."}), 400
        if len(txt) > 5000:
            return jsonify({"error": "validation", "message": "Comment is too long."}), 400
        c = VfxComment(vfx_shot_id=shot.id, user_id=uid, comment=txt)
        db.session.add(c)
        shot.version = max(1, int(shot.version or 1)) + 1
        shot.version_number = max(1, int(shot.version_number or 1)) + 1
        shot.updated_at = datetime.now(timezone.utc)
        db.session.commit()
        who = User.query.get(uid)
        return jsonify(
            {
                "ok": True,
                "comment": {
                    "id": c.id,
                    "text": c.comment,
                    "user": (who.name or who.email).strip() if who else "User",
                    "created_at": c.created_at.strftime("%Y-%m-%d %H:%M"),
                },
                "version": int(shot.version_number or shot.version or 1),
            }
        )

    @app.route("/projects/<int:project_id>/scenes/<int:scene_id>/mark-done", methods=["POST"])
    def production_scene_mark_done(project_id: int, scene_id: int):
        return redirect(url_for("project_episodes", project_id=project_id))

    @app.route("/projects/<int:project_id>/chat/messages", methods=["GET", "POST"])
    def project_chat_messages(project_id: int):
        acc = Account.query.get(session.get("account_id"))
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
        acc = Account.query.get(session.get("account_id"))
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
            m.deleted_at = datetime.now(timezone.utc)
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
        acc = Account.query.get(session.get("account_id"))
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
        acc = Account.query.get(session.get("account_id"))
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
        acc = Account.query.get(session.get("account_id"))
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
        acc = Account.query.get(session.get("account_id"))
        if not account_may_use_project_chat(acc, project_id):
            return jsonify({"error": "forbidden"}), 403
        n = chat_unread_count_for_account(acc, project_id)
        return jsonify({"count": n})

    @app.route("/projects/<int:project_id>/chat/mark-read", methods=["POST"])
    def project_chat_mark_read(project_id: int):
        acc = Account.query.get(session.get("account_id"))
        if not account_may_use_project_chat(acc, project_id):
            return jsonify({"error": "forbidden"}), 403
        chat_mark_project_read(acc, project_id)
        return jsonify({"ok": True})

    @app.route("/projects/<int:project_id>/edit", methods=["GET", "POST"])
    def project_edit(project_id: int):
        actor = Account.query.get(session.get("account_id"))
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
        actor = Account.query.get(session.get("account_id"))
        if actor is None or not account_is_elevated(actor):
            flash("Only administrators and super users can change project teams.", "error")
            return redirect(url_for("projects_list"))
        p = Project.query.get_or_404(project_id)
        if not account_can_access_project(actor, p.id):
            flash("You do not have access to that project.", "error")
            return redirect(url_for("projects_list"))
        if request.method == "GET":
            return redirect(url_for("project_detail", project_id=p.id))
        uid = request.form.get("user_id", type=int)
        added = 0
        if not uid:
            flash("Choose a user from the list to add.", "error")
            return redirect(url_for("project_detail", project_id=p.id))
        u = User.query.get(uid)
        if not u:
            flash("That user was not found.", "error")
            return redirect(url_for("project_detail", project_id=p.id))
        if ProjectMember.query.filter_by(project_id=p.id, user_id=uid).first():
            flash("That user is already on this project.", "error")
            return redirect(url_for("project_detail", project_id=p.id))
        db.session.add(ProjectMember(project_id=p.id, user_id=uid))
        try:
            db.session.commit()
        except sa_exc.IntegrityError:
            db.session.rollback()
            flash("Could not add team member (duplicate or database error).", "error")
            return redirect(url_for("project_detail", project_id=p.id))
        flash("Team member added to the project.", "success")
        return redirect(url_for("project_detail", project_id=p.id))

    @app.route("/projects/<int:project_id>/members/<int:user_id>/remove", methods=["GET", "POST"])
    def project_member_remove(project_id: int, user_id: int):
        actor = Account.query.get(session.get("account_id"))
        if actor is None or not account_is_elevated(actor):
            flash("Only administrators and super users can change project teams.", "error")
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

    @app.route("/projects/<int:project_id>/delete", methods=["POST"])
    def projects_delete(project_id: int):
        actor = account_from_session()
        if actor is None or not actor.is_admin:
            abort(403)
        p = Project.query.get_or_404(project_id)
        # Important: several project-scoped relationships (notably `VfxShot.project_id`)
        # are `NOT NULL` and are *not* configured with ORM cascades from `Project`.
        # If we delete the `Project` first, SQLAlchemy may attempt to dissociate rows
        # by setting those FKs to NULL, causing IntegrityError.
        # So we remove dependent rows first.
        for b in Booking.query.filter_by(project_id=p.id).all():
            db.session.delete(b)

        shots = VfxShot.query.filter_by(project_id=p.id).all()
        shot_ids = [s.id for s in shots]
        if shot_ids:
            VfxComment.query.filter(VfxComment.vfx_shot_id.in_(shot_ids)).delete(
                synchronize_session=False
            )
        for shot in shots:
            db.session.delete(shot)
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
        acc = Account.query.get(session.get("account_id"))
        vis = visible_project_ids_for_account(acc)
        task_groups = TaskGroup.query.order_by(TaskGroup.sort_order, TaskGroup.name).all()
        uid = directory_user_id_for_account(acc)
        selected_sort = (request.args.get("sort") or "").strip().lower()
        if selected_sort not in ("", "newest", "priority"):
            selected_sort = ""

        # Tasks page filters are client-side; load full visible set (JSON APIs unchanged).
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

        all_tasks = (
            q.options(joinedload(Task.assignee), joinedload(Task.project))
            .order_by(Task.created_at.desc())
            .all()
        )

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
                "created_at": t.created_at.isoformat() if t.created_at else "",
                "completed_at": t.completed_at.isoformat() if t.completed_at else "",
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
        actor = Account.query.get(session.get("account_id"))
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
        acc = Account.query.get(session.get("account_id"))
        t = Task.query.get_or_404(task_id)
        if not account_may_update_task_status(t, acc):
            flash("You cannot update that task’s status.", "error")
            return redirect(url_for("tasks_list"))
        if t.archived:
            flash("Unarchive the task before changing its status.", "error")
            return _redirect_after_task_action()
        status = (request.form.get("status") or "").strip().lower()
        if status not in ("open", "in_progress", "done"):
            flash("Invalid status.", "error")
            return redirect(url_for("tasks_list"))
        t.status = status
        if status == "done":
            t.completed_at = datetime.now(timezone.utc)
        else:
            t.completed_at = None
        db.session.commit()
        flash("Task status updated.", "success")
        return _redirect_after_task_action()

    @app.route("/tasks/<int:task_id>/archive", methods=["POST"])
    def tasks_archive(task_id: int):
        acc = Account.query.get(session.get("account_id"))
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
        flash("Task archived.", "success")
        return _redirect_after_task_action()

    @app.route("/tasks/<int:task_id>/unarchive", methods=["POST"])
    def tasks_unarchive(task_id: int):
        acc = Account.query.get(session.get("account_id"))
        t = Task.query.get_or_404(task_id)
        if not account_may_archive_task(t, acc):
            flash("You cannot restore that task.", "error")
            return _redirect_after_task_action()
        if not t.archived:
            flash("That task is not archived.", "error")
            return _redirect_after_task_action()
        t.archived = False
        db.session.commit()
        flash("Task restored from archive.", "success")
        return _redirect_after_task_action()

    @app.route("/tasks/<int:task_id>/delete", methods=["POST"])
    def tasks_delete(task_id: int):
        acc = Account.query.get(session.get("account_id"))
        t = Task.query.get_or_404(task_id)
        if not task_visible_to_account(t, acc):
            flash("You do not have access to that task.", "error")
            return _redirect_after_task_action()
        db.session.delete(t)
        db.session.commit()
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
                t.completed_at = datetime.now(timezone.utc)
            if status != "done":
                t.completed_at = None
            db.session.commit()
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
        db.session.delete(t)
        db.session.commit()
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
                    if cand is not None and Account.query.get(int(cand)) is not None:
                        aid = int(cand)
                except (BadSignature, SignatureExpired, TypeError, ValueError):
                    aid = None
        if not aid:
            return False
        join_room(f"user_{aid}")
        return True

    @socketio.on("join_project")
    def _socket_join_project(data):
        if not isinstance(data, dict):
            return
        try:
            pid = int(data.get("project_id"))
        except (TypeError, ValueError):
            return
        acc = Account.query.get(session.get("account_id"))
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
        acc = Account.query.get(session.get("account_id"))
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

    return app


app = create_app()

if __name__ == "__main__":
    socketio.run(
        app,
        debug=True,
        port=int(os.environ.get("PORT", "5000")),
        allow_unsafe_werkzeug=True,
    )
