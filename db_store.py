import contextvars
import json
import logging
import os
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from sqlalchemy import Integer, Text, create_engine, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

logger = logging.getLogger(__name__)

_LOCAL_HOSTS = frozenset({
    "localhost",
    "127.0.0.1",
    "::1",
    "0.0.0.0",
    "host.docker.internal",
})


class StaleDataError(Exception):
    """Raised when a store was modified after the caller loaded it."""

    def __init__(self, store_name: str):
        self.store_name = store_name
        super().__init__(store_name)


class RemoteDatabaseBlocked(RuntimeError):
    """Raised when this process must not open a remote database."""


def database_hostname(database_url: str) -> str:
    """Return the database host with credentials removed."""
    url = (database_url or "").strip()
    if not url or url.startswith("sqlite"):
        return ""
    for marker in ("postgresql://", "postgres://"):
        if marker in url and not url.startswith(("postgres://", "postgresql://", "postgresql+")):
            url = url[url.index(marker):]
            break
    return (urlparse(url).hostname or "").strip().lower()


def is_local_database_url(database_url: str) -> bool:
    """True for SQLite, localhost, and single-label hosts such as a Compose service."""
    url = (database_url or "").strip()
    if not url or url.startswith("sqlite"):
        return True
    host = database_hostname(url)
    if not host:
        return False
    if host in _LOCAL_HOSTS:
        return True
    return "." not in host


def _env_flag(env, name: str) -> bool:
    return (env.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _running_tests(env, under_test) -> bool:
    if under_test is not None:
        return bool(under_test)
    if (env.get("PYTEST_CURRENT_TEST") or "").strip():
        return True
    return "pytest" in sys.modules


def remote_database_allowed(database_url: str, env=None, *, under_test=None) -> bool:
    """Remote Postgres is for the Railway deployment, not a laptop or test run.

    ``RAILWAY_DEPLOYMENT_ID``, ``RAILWAY_REPLICA_ID``, and ``RAILWAY_SNAPSHOT_ID``
    are injected into the running replica. ``railway run`` and a copied service
    ``.env`` do not receive them. ``MW_ALLOW_REMOTE_DB=1`` is the explicit
    maintenance override.
    """
    env = os.environ if env is None else env
    if _running_tests(env, under_test):
        return False
    if _env_flag(env, "MW_ALLOW_REMOTE_DB"):
        return True
    if is_local_database_url(database_url):
        return True
    deployed_markers = (
        "RAILWAY_DEPLOYMENT_ID",
        "RAILWAY_REPLICA_ID",
        "RAILWAY_SNAPSHOT_ID",
    )
    return any((env.get(name) or "").strip() for name in deployed_markers)


def select_database_url(env=None, *, under_test=None) -> str:
    """Return the database URL this process may open, or an empty string."""
    env = os.environ if env is None else env
    url = (env.get("DATABASE_URL") or "").strip()
    if not url:
        url = (env.get("DATABASE_PRIVATE_URL") or "").strip()
    if not url or is_local_database_url(url):
        return url
    if remote_database_allowed(url, env, under_test=under_test):
        return url
    return ""


def refuse_remote_database(env=None, *, under_test=None) -> str:
    """Drop a refused remote URL from the process environment and return the safe URL."""
    if env is None:
        env = os.environ
    selected = select_database_url(env, under_test=under_test)
    raw = (env.get("DATABASE_URL") or "").strip() or (env.get("DATABASE_PRIVATE_URL") or "").strip()
    if raw and not selected:
        env.pop("DATABASE_URL", None)
        env.pop("DATABASE_PRIVATE_URL", None)
    return selected


def assert_database_allowed(database_url: str, env=None, *, under_test=None) -> None:
    if is_local_database_url(database_url):
        return
    if remote_database_allowed(database_url, env, under_test=under_test):
        return
    host = database_hostname(database_url) or "unknown"
    raise RemoteDatabaseBlocked(
        f"Refusing remote database host {host}. "
        "Development and tests use local CSV files or a localhost database."
    )


def prepare_database_url(database_url: str) -> str:
    """Normalize Railway/Heroku Postgres URLs for SQLAlchemy + psycopg2."""
    url = database_url.strip()
    if not url:
        return url

    # Fix misconfigured Railway vars that prepend the DB name to the URL.
    if "postgresql://" in url and not url.startswith("postgresql"):
        url = url[url.index("postgresql://") :]
    elif "postgres://" in url and not url.startswith("postgres"):
        url = url[url.index("postgres://") :]

    if url.startswith("postgres://"):
        url = "postgresql+psycopg2://" + url[len("postgres://") :]
    elif url.startswith("postgresql://") and "+psycopg2" not in url.split("://", 1)[0]:
        url = "postgresql+psycopg2://" + url[len("postgresql://") :]

    # Railway and most cloud Postgres require SSL. Local Postgres usually does not.
    if url.startswith("postgresql") and "sslmode=" not in url and not is_local_database_url(url):
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}sslmode=require"

    return url


class Base(DeclarativeBase):
    pass


class StudentRow(Base):
    __tablename__ = "student_rows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    row_order: Mapped[int] = mapped_column(Integer, nullable=False)
    data_json: Mapped[str] = mapped_column(Text, nullable=False)


class LessonRow(Base):
    __tablename__ = "lesson_rows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    row_order: Mapped[int] = mapped_column(Integer, nullable=False)
    data_json: Mapped[str] = mapped_column(Text, nullable=False)


class ExtraSessionRow(Base):
    __tablename__ = "extra_session_rows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    row_order: Mapped[int] = mapped_column(Integer, nullable=False)
    data_json: Mapped[str] = mapped_column(Text, nullable=False)


class LessonAttendanceRow(Base):
    __tablename__ = "lesson_attendance_rows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    row_order: Mapped[int] = mapped_column(Integer, nullable=False)
    data_json: Mapped[str] = mapped_column(Text, nullable=False)


class StudentMonthlyReviewRow(Base):
    __tablename__ = "student_monthly_review_rows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    row_order: Mapped[int] = mapped_column(Integer, nullable=False)
    data_json: Mapped[str] = mapped_column(Text, nullable=False)


class TeacherClassRow(Base):
    __tablename__ = "teacher_class_rows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    row_order: Mapped[int] = mapped_column(Integer, nullable=False)
    data_json: Mapped[str] = mapped_column(Text, nullable=False)


class ChatMessageRow(Base):
    __tablename__ = "chat_message_rows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    row_order: Mapped[int] = mapped_column(Integer, nullable=False)
    data_json: Mapped[str] = mapped_column(Text, nullable=False)


class TeacherProfileRow(Base):
    __tablename__ = "teacher_profile_rows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    row_order: Mapped[int] = mapped_column(Integer, nullable=False)
    data_json: Mapped[str] = mapped_column(Text, nullable=False)


class StudentPhotoRow(Base):
    __tablename__ = "student_photo_rows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    row_order: Mapped[int] = mapped_column(Integer, nullable=False)
    data_json: Mapped[str] = mapped_column(Text, nullable=False)


class StudentSnapshotRow(Base):
    __tablename__ = "student_snapshot_rows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    row_order: Mapped[int] = mapped_column(Integer, nullable=False)
    data_json: Mapped[str] = mapped_column(Text, nullable=False)


class StudentTransferRow(Base):
    __tablename__ = "student_transfer_rows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    row_order: Mapped[int] = mapped_column(Integer, nullable=False)
    data_json: Mapped[str] = mapped_column(Text, nullable=False)


class LoginEventRow(Base):
    __tablename__ = "login_event_rows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    row_order: Mapped[int] = mapped_column(Integer, nullable=False)
    data_json: Mapped[str] = mapped_column(Text, nullable=False)


class StoreVersion(Base):
    __tablename__ = "store_versions"

    store_name: Mapped[str] = mapped_column(Text, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class StoreBackup(Base):
    """A restore point: the full contents of one store just before it was overwritten."""

    __tablename__ = "store_backups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    store_name: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)  # ISO 8601, UTC
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    data_json: Mapped[str] = mapped_column(Text, nullable=False)


# Restore points. Every overwrite of a store is a full replace, so the previous contents are kept
# here first: always before rows disappear or inside a bulk action (see backup_reason), otherwise
# at most every BACKUP_INTERVAL. Retention keeps the newest few plus one per day for a month.
BACKUP_INTERVAL = timedelta(minutes=30)
BACKUP_KEEP_RECENT = 10
BACKUP_KEEP_DAYS = 30
# Photos are large: copy them only before one disappears, and keep only a few copies.
BACKUP_PHOTO_STORE = "student_photos"
BACKUP_PHOTO_KEEP = 3
BACKUP_SKIP_STORES = frozenset({"login_events"})
REASON_AUTO = "auto"
REASON_REMOVAL = "removal"

_backup_context = contextvars.ContextVar("mw_backup_context", default=None)


@contextmanager
def backup_reason(reason: str):
    """Inside this block, every store that gets overwritten is backed up first (once), labelled `reason`."""
    # One timestamp for the whole action, so its restore points can be found and undone together.
    token = _backup_context.set({"reason": reason, "done": set(), "at": _utcnow()})
    try:
        yield
    finally:
        _backup_context.reset(token)


def _utcnow():
    return datetime.now(timezone.utc)


class UserRow(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    teacher_name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class DatabaseStore:
    _STORE_NAMES = {
        StudentRow: "students",
        LessonRow: "lessons",
        ExtraSessionRow: "extra_sessions",
        LessonAttendanceRow: "lesson_attendance",
        StudentMonthlyReviewRow: "monthly_reviews",
        TeacherClassRow: "teacher_classes",
        ChatMessageRow: "chat_messages",
        TeacherProfileRow: "teacher_profiles",
        StudentPhotoRow: "student_photos",
        StudentSnapshotRow: "student_snapshots",
        StudentTransferRow: "student_transfers",
        LoginEventRow: "login_events",
    }

    def __init__(self, database_url: str):
        assert_database_allowed(database_url)
        prepared = prepare_database_url(database_url)
        parsed = urlparse(prepared.replace("postgresql+psycopg2://", "postgresql://", 1))
        logger.info(
            "Connecting to database host=%s port=%s db=%s",
            parsed.hostname,
            parsed.port or 5432,
            (parsed.path or "").lstrip("/") or "(default)",
        )
        engine_kwargs = {"pool_pre_ping": True}
        if prepared.startswith("postgresql") and not is_local_database_url(prepared):
            engine_kwargs["connect_args"] = {
                "sslmode": "require",
                "connect_timeout": 5,
            }
        self.engine = create_engine(prepared, **engine_kwargs)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)

    def initialize(self):
        Base.metadata.create_all(self.engine)

    def initialize_users(self):
        Base.metadata.create_all(self.engine)

    def check_connection(self):
        with self.engine.connect() as conn:
            conn.execute(text("SELECT 1"))

    @contextmanager
    def session(self):
        session = Session(self.engine)
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def load_students(self):
        rows, _version = self.load_students_versioned()
        return rows

    def load_students_versioned(self):
        return self._load_rows(StudentRow)

    def save_students(self, rows, expected_version=None):
        return self._replace_rows(StudentRow, rows, expected_version=expected_version)

    def load_lessons(self):
        rows, _version = self.load_lessons_versioned()
        return rows

    def load_lessons_versioned(self):
        return self._load_rows(LessonRow)

    def save_lessons(self, rows, expected_version=None):
        return self._replace_rows(LessonRow, rows, expected_version=expected_version)

    def load_extra_sessions(self):
        rows, _version = self.load_extra_sessions_versioned()
        return rows

    def load_extra_sessions_versioned(self):
        return self._load_rows(ExtraSessionRow)

    def save_extra_sessions(self, rows, expected_version=None):
        return self._replace_rows(ExtraSessionRow, rows, expected_version=expected_version)

    def load_lesson_attendance(self):
        rows, _version = self.load_lesson_attendance_versioned()
        return rows

    def load_lesson_attendance_versioned(self):
        return self._load_rows(LessonAttendanceRow)

    def save_lesson_attendance(self, rows, expected_version=None):
        return self._replace_rows(LessonAttendanceRow, rows, expected_version=expected_version)

    def load_monthly_reviews(self):
        rows, _version = self.load_monthly_reviews_versioned()
        return rows

    def load_monthly_reviews_versioned(self):
        return self._load_rows(StudentMonthlyReviewRow)

    def save_monthly_reviews(self, rows, expected_version=None):
        return self._replace_rows(StudentMonthlyReviewRow, rows, expected_version=expected_version)

    def load_teacher_classes(self):
        rows, _version = self.load_teacher_classes_versioned()
        return rows

    def load_teacher_classes_versioned(self):
        return self._load_rows(TeacherClassRow)

    def save_teacher_classes(self, rows, expected_version=None):
        return self._replace_rows(TeacherClassRow, rows, expected_version=expected_version)

    def load_chat_messages(self):
        rows, _version = self.load_chat_messages_versioned()
        return rows

    def load_chat_messages_versioned(self):
        return self._load_rows(ChatMessageRow)

    def save_chat_messages(self, rows, expected_version=None):
        return self._replace_rows(ChatMessageRow, rows, expected_version=expected_version)

    def load_teacher_profiles(self):
        rows, _version = self.load_teacher_profiles_versioned()
        return rows

    def load_teacher_profiles_versioned(self):
        return self._load_rows(TeacherProfileRow)

    def save_teacher_profiles(self, rows, expected_version=None):
        return self._replace_rows(TeacherProfileRow, rows, expected_version=expected_version)

    def load_student_photos(self):
        rows, _version = self.load_student_photos_versioned()
        return rows

    def load_student_photos_versioned(self):
        return self._load_rows(StudentPhotoRow)

    def save_student_photos(self, rows, expected_version=None):
        return self._replace_rows(StudentPhotoRow, rows, expected_version=expected_version)

    def load_student_snapshots_versioned(self):
        return self._load_rows(StudentSnapshotRow)

    def save_student_snapshots(self, rows, expected_version=None):
        return self._replace_rows(StudentSnapshotRow, rows, expected_version=expected_version)

    def load_student_transfers_versioned(self):
        return self._load_rows(StudentTransferRow)

    def save_student_transfers(self, rows, expected_version=None):
        return self._replace_rows(StudentTransferRow, rows, expected_version=expected_version)

    def load_login_events(self):
        rows, _version = self.load_login_events_versioned()
        return rows

    def load_login_events_versioned(self):
        return self._load_rows(LoginEventRow)

    def save_login_events(self, rows, expected_version=None):
        return self._replace_rows(LoginEventRow, rows, expected_version=expected_version)

    def load_users(self):
        with self.session() as session:
            q = select(UserRow).order_by(UserRow.id.asc())
            records = session.execute(q).scalars().all()
            return [
                {
                    'id': r.id,
                    'email': r.email,
                    'password_hash': r.password_hash,
                    'role': r.role,
                    'teacher_name': r.teacher_name or '',
                    'active': bool(r.active),
                }
                for r in records
            ]

    def save_users(self, users):
        with self.session() as session:
            session.query(UserRow).delete()
            for u in users:
                session.add(UserRow(
                    id=u.get('id'),
                    email=u['email'],
                    password_hash=u['password_hash'],
                    role=u['role'],
                    teacher_name=u.get('teacher_name') or '',
                    active=1 if u.get('active', True) else 0,
                ))

    def _store_name(self, model):
        return self._STORE_NAMES[model]

    def _version_row(self, session, store_name):
        row = session.get(StoreVersion, store_name)
        if row is None:
            row = StoreVersion(store_name=store_name, version=0)
            session.add(row)
            session.flush()
        return row

    def _advisory_lock(self, session, store_name):
        if self.engine.dialect.name != 'postgresql':
            return
        session.execute(
            text('SELECT pg_advisory_xact_lock(hashtext(:name))'),
            {'name': store_name},
        )

    def _load_rows(self, model):
        store_name = self._store_name(model)
        with self.session() as session:
            version = self._version_row(session, store_name).version
            q = select(model).order_by(model.row_order.asc(), model.id.asc())
            records = session.execute(q).scalars().all()
            rows = []
            for record in records:
                try:
                    rows.append(json.loads(record.data_json))
                except (json.JSONDecodeError, TypeError) as exc:
                    logger.warning(
                        'Skipping corrupt %s row id=%s: %s',
                        store_name,
                        getattr(record, 'id', '?'),
                        exc,
                    )
            return rows, version

    def _replace_rows(self, model, rows, expected_version=None):
        with self.session() as session:
            return self._replace_rows_in(session, model, rows, expected_version)

    def _replace_rows_in(self, session, model, rows, expected_version=None):
        """Replace a store inside the caller's transaction (commit happens when it closes)."""
        store_name = self._store_name(model)
        self._advisory_lock(session, store_name)
        version_row = self._version_row(session, store_name)
        if expected_version is not None and version_row.version != expected_version:
            raise StaleDataError(store_name)
        self._backup_before_replace(session, model, store_name, len(rows))
        session.query(model).delete()
        payloads = [
            model(row_order=i, data_json=json.dumps(row, ensure_ascii=False))
            for i, row in enumerate(rows)
        ]
        session.add_all(payloads)
        version_row.version += 1
        session.flush()
        return version_row.version

    # ── Restore points ────────────────────────────────────────────────────────────

    def _model_for_store(self, store_name):
        for model, name in self._STORE_NAMES.items():
            if name == store_name:
                return model
        raise KeyError(store_name)

    def _backup_before_replace(self, session, model, store_name, new_count):
        if store_name in BACKUP_SKIP_STORES:
            return
        old = session.execute(
            select(model.data_json).order_by(model.row_order.asc(), model.id.asc())
        ).scalars().all()
        if not old:
            return
        context = _backup_context.get()
        created_at = _utcnow()
        if context is not None and store_name not in context["done"]:
            context["done"].add(store_name)
            reason, created_at = context["reason"], context["at"]
        elif new_count < len(old):
            reason = REASON_REMOVAL
        elif store_name == BACKUP_PHOTO_STORE or context is not None:
            return
        else:
            last = session.execute(
                select(StoreBackup.created_at)
                .where(StoreBackup.store_name == store_name)
                .order_by(StoreBackup.id.desc()).limit(1)
            ).scalar()
            if last and created_at - datetime.fromisoformat(last) < BACKUP_INTERVAL:
                return
            reason = REASON_AUTO
        session.add(StoreBackup(
            store_name=store_name,
            # Microseconds keep two quick actions with the same label in separate undo groups.
            created_at=created_at.isoformat(timespec="microseconds"),
            reason=reason,
            row_count=len(old),
            data_json="[" + ",".join(old) + "]",
        ))
        session.flush()
        self._prune_backups(session, store_name)

    def _prune_backups(self, session, store_name):
        photos = store_name == BACKUP_PHOTO_STORE
        keep_recent = BACKUP_PHOTO_KEEP if photos else BACKUP_KEEP_RECENT
        oldest_daily = _utcnow() - timedelta(days=0 if photos else BACKUP_KEEP_DAYS)
        rows = session.execute(
            select(StoreBackup.id, StoreBackup.created_at)
            .where(StoreBackup.store_name == store_name)
            .order_by(StoreBackup.id.desc())
        ).all()
        days_kept, drop = set(), []
        for i, (backup_id, created_at) in enumerate(rows):
            when = datetime.fromisoformat(created_at)
            if i < keep_recent:
                days_kept.add(when.date())
            elif when >= oldest_daily and when.date() not in days_kept:
                days_kept.add(when.date())
            else:
                drop.append(backup_id)
        if drop:
            session.query(StoreBackup).filter(StoreBackup.id.in_(drop)).delete(synchronize_session=False)

    def list_backups(self):
        """Restore points, newest first, without their contents."""
        with self.session() as session:
            rows = session.execute(
                select(StoreBackup.id, StoreBackup.store_name, StoreBackup.created_at,
                       StoreBackup.reason, StoreBackup.row_count)
                .order_by(StoreBackup.id.desc())
            ).all()
        return [
            {"id": r.id, "store": r.store_name, "created_at": r.created_at,
             "reason": r.reason, "row_count": r.row_count}
            for r in rows
        ]

    def restore_backup(self, backup_id, reason="restore"):
        """Put a restore point back. The current contents become a restore point of their own."""
        return self.restore_backups([backup_id], reason=reason)[0]

    def restore_backups(self, backup_ids, reason="restore"):
        """Put several restore points back together (e.g. everything one bulk action changed)."""
        # One transaction: either every store in the group is restored or none is.
        with backup_reason(reason), self.session() as session:
            backups = [session.get(StoreBackup, backup_id) for backup_id in backup_ids]
            if not backups or any(b is None for b in backups):
                raise KeyError(backup_ids)
            if len({b.store_name for b in backups}) != len(backups):
                raise ValueError("one restore point per store")
            plan = [(b.store_name, json.loads(b.data_json)) for b in backups]
            for store_name, rows in plan:
                self._replace_rows_in(session, self._model_for_store(store_name), rows)
        return [(store_name, len(rows)) for store_name, rows in plan]

    def export_all(self):
        """Every store's current rows plus user accounts (without password hashes)."""
        data = {name: self._load_rows(model)[0] for model, name in self._STORE_NAMES.items()}
        data["users"] = [
            {k: v for k, v in user.items() if k != "password_hash"} for user in self.load_users()
        ]
        return data
