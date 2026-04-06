"""Users and tasks web application."""

from __future__ import annotations

import mimetypes
import os
import re
import uuid
from collections import defaultdict
from datetime import datetime, timezone
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
from sqlalchemy.orm import joinedload
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from flask_socketio import SocketIO, join_room, leave_room

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
ROLE_USER = "user"
ROLE_GUEST = "guest"
ACCOUNT_ROLES = (ROLE_ADMIN, ROLE_SUPER_USER, ROLE_USER, ROLE_GUEST)

ROLE_LABELS = {
    ROLE_ADMIN: "Administrator",
    ROLE_SUPER_USER: "Super user",
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

    class Task(db.Model):
        __tablename__ = "tasks"

        id = db.Column(db.Integer, primary_key=True)
        title = db.Column(db.String(200), nullable=False)
        description = db.Column(db.Text, default="")
        status = db.Column(db.String(32), nullable=False, default="open")
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

        project = db.relationship("Project", back_populates="chat_messages")
        user = db.relationship("User", backref=db.backref("chat_messages", lazy=True))

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

    Task.project = db.relationship("Project", back_populates="tasks")

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
        ensure_bootstrap_admin_account()
        ensure_all_accounts_have_directory_users()
        ensure_task_groups_and_editing_tasks()
        ensure_sqlite_chat_messages_audio_path()

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
        }

    def directory_user_id_for_account(acc: Account | None) -> int | None:
        if acc is None:
            return None
        u = User.query.filter_by(account_id=acc.id).first()
        return u.id if u else None

    def visible_project_ids_for_account(acc: Account | None) -> set[int] | None:
        """None means no filter (admin / super user). Otherwise project IDs the account may access."""
        if acc is None:
            return set()
        if account_is_elevated(acc):
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

    def chat_message_json(m: ChatMessage, viewer_dir_user_id: int | None) -> dict:
        u = m.user
        username = u.name if u is not None else "Unknown"
        avatar_initial = "?"
        for ch in username.strip():
            if ch.isalnum():
                avatar_initial = ch.upper()
                break
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
        return {
            "id": m.id,
            "username": username,
            "message": (m.message or "").strip(),
            "image_url": image_url,
            "audio_url": audio_url,
            "avatar_initial": avatar_initial,
            "created_at": m.created_at.isoformat() if m.created_at else "",
            "is_me": viewer_dir_user_id is not None and m.user_id == viewer_dir_user_id,
        }

    def emit_notification_to_account(account_id: int, payload: dict, event: str = "notification") -> None:
        """Push a Socket.IO event to every connection for this login account (room user_<id>)."""
        socketio.emit(event, payload, room=f"user_{account_id}")

    def task_visible_to_account(t: Task, acc: Account | None) -> bool:
        if acc is None:
            return False
        if account_is_elevated(acc):
            return True
        allowed = visible_project_ids_for_account(acc)
        if allowed is None:
            return True
        if t.project_id is None:
            return False
        return t.project_id in allowed

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
            new_upload_base: str | None = None
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

            avatar_source = (request.form.get("avatar_source") or "preset").strip().lower()
            upload_part = request.files.get("avatar_file")
            if avatar_source == "upload" and upload_part and upload_part.filename and upload_part.filename.strip():
                raw = upload_part.read()
                if len(raw) > AVATAR_UPLOAD_MAX_BYTES:
                    flash("Profile image is too large (max 2 MB).", "error")
                    return redirect(url_for("profile"))
                orig = secure_filename(upload_part.filename) or "photo"
                ext = os.path.splitext(orig)[1].lower()
                if ext not in AVATAR_ALLOWED_EXT:
                    flash("Use PNG, JPG, GIF, or WebP for your photo.", "error")
                    return redirect(url_for("profile"))
                remove_profile_avatar_file(du.avatar_upload)
                new_upload_base = f"u{du.id}-{uuid.uuid4().hex}{ext}"
                dest = os.path.join(upload_root, new_upload_base)
                with open(dest, "wb") as out:
                    out.write(raw)
                du.avatar_kind = "upload"
                du.avatar_upload = new_upload_base
            elif avatar_source == "preset":
                pid = normalize_avatar_preset_id(request.form.get("avatar_preset"))
                remove_profile_avatar_file(du.avatar_upload)
                du.avatar_kind = "preset"
                du.avatar_preset = pid
                du.avatar_upload = None

            acc.email = email
            du.email = email
            try:
                db.session.commit()
                flash("Profile updated.", "success")
            except sa_exc.IntegrityError:
                db.session.rollback()
                if new_upload_base:
                    remove_profile_avatar_file(new_upload_base)
                flash("Could not save profile (email may be taken).", "error")
            return redirect(url_for("profile"))

        if du is None:
            profile_active_preset = "01"
        elif (du.avatar_kind or "preset").lower() == "upload":
            profile_active_preset = None
        else:
            profile_active_preset = normalize_avatar_preset_id(du.avatar_preset)

        job_titles = JobTitle.query.order_by(JobTitle.name).all()

        return render_template(
            "profile.html",
            account=acc,
            directory_user=du,
            preset_avatar_ids=PRESET_AVATAR_IDS,
            profile_active_preset=profile_active_preset,
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
            task_count = Task.query.filter_by(archived=False).count()
            open_tasks = Task.query.filter_by(status="open", archived=False).count()
            project_count = Project.query.count()
        elif not vis:
            task_count = 0
            open_tasks = 0
            project_count = 0
        else:
            task_count = Task.query.filter(
                Task.project_id.in_(vis), Task.archived == False
            ).count()
            open_tasks = Task.query.filter(
                Task.project_id.in_(vis), Task.status == "open", Task.archived == False
            ).count()
            project_count = len(vis)
        return render_template(
            "index.html",
            user_count=user_count,
            task_count=task_count,
            open_tasks=open_tasks,
            project_count=project_count,
        )

    @app.route("/projects")
    def projects_list():
        acc = Account.query.get(session.get("account_id"))
        vis = visible_project_ids_for_account(acc)
        q = Project.query.order_by(Project.sort_order.asc(), Project.id.asc())
        if vis is None:
            projects = q.all()
        elif not vis:
            projects = []
        else:
            projects = q.filter(Project.id.in_(vis)).all()
        return render_template("projects.html", projects=projects)

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
        mx = db.session.query(db.func.max(Project.sort_order)).scalar()
        next_ord = (mx if mx is not None else -1) + 1
        db.session.add(
            Project(
                name=name,
                project_type=project_type,
                production_house=production_house,
                director=director,
                sort_order=next_ord,
            )
        )
        db.session.commit()
        flash("Project created.", "success")
        return redirect(url_for("projects_list"))

    @app.route("/projects/reorder", methods=["POST"])
    def projects_reorder():
        actor = Account.query.get(session.get("account_id"))
        if actor is None or not account_is_elevated(actor):
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
        all_users = User.query.order_by(User.name).all()
        available_to_add = [u for u in all_users if u.id not in member_ids]
        chat_allowed = account_may_use_project_chat(acc, p.id)
        chat_unread_count = (
            chat_unread_count_for_account(acc, p.id) if chat_allowed else 0
        )
        chat_team_mentions = [
            {"id": u.id, "name": (u.name or "").strip()}
            for u in member_users
            if (u.name or "").strip()
        ]
        chat_viewer_user_id = (
            directory_user_id_for_account(acc) if chat_allowed else None
        )
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
        return render_template(
            "project_detail.html",
            project=p,
            active_tasks=active_tasks,
            member_users=member_users,
            available_to_add=available_to_add,
            chat_allowed=chat_allowed,
            chat_unread_count=chat_unread_count,
            chat_team_mentions=chat_team_mentions,
            chat_viewer_user_id=chat_viewer_user_id,
            task_groups=task_groups,
            titles_by_group=dict(titles_by_group),
            has_title_presets=has_title_presets,
            user_project_ids=dict(user_project_ids),
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
            return jsonify(
                {
                    "messages": [chat_message_json(m, viewer_uid) for m in rows],
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
            chat_href = url_for("project_detail", project_id=project_id) + "#project-chat"
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

        return jsonify({"message": chat_message_json(cm, viewer_uid)}), 201

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
                p.name = name
                p.project_type = project_type
                p.production_house = production_house
                p.director = director
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
        if vis is None:
            all_tasks = (
                Task.query.filter_by(archived=False)
                .order_by(Task.created_at.desc())
                .all()
            )
        elif not vis:
            if uid is None:
                all_tasks = []
            else:
                all_tasks = (
                    Task.query.filter(Task.user_id == uid, Task.archived == False)
                    .order_by(Task.created_at.desc())
                    .all()
                )
        elif uid is not None:
            all_tasks = (
                Task.query.filter(
                    or_(Task.project_id.in_(vis), Task.user_id == uid),
                    Task.archived == False,
                )
                .order_by(Task.created_at.desc())
                .all()
            )
        else:
            all_tasks = (
                Task.query.filter(Task.project_id.in_(vis), Task.archived == False)
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

        t = Task(
            title=preset.title,
            description=description,
            user_id=user_id,
            group_id=preset.group_id,
            project_id=project.id,
            status="open",
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
        return render_template(
            "control_panel.html",
            groups=groups,
            presets_by_group=dict(presets_by_group),
            job_titles=job_titles,
        )

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
