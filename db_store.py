import json
import logging
from contextlib import contextmanager
from urllib.parse import urlparse

from sqlalchemy import Integer, Text, create_engine, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

logger = logging.getLogger(__name__)


class StaleDataError(Exception):
    """Raised when a store was modified after the caller loaded it."""

    def __init__(self, store_name: str):
        self.store_name = store_name
        super().__init__(store_name)


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

    # Railway and most cloud Postgres require SSL; skip for local sqlite tests.
    if url.startswith("postgresql") and "sslmode=" not in url:
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


class StoreVersion(Base):
    __tablename__ = "store_versions"

    store_name: Mapped[str] = mapped_column(Text, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


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
    }

    def __init__(self, database_url: str):
        prepared = prepare_database_url(database_url)
        parsed = urlparse(prepared.replace("postgresql+psycopg2://", "postgresql://", 1))
        logger.info(
            "Connecting to database host=%s port=%s db=%s",
            parsed.hostname,
            parsed.port or 5432,
            (parsed.path or "").lstrip("/") or "(default)",
        )
        engine_kwargs = {"pool_pre_ping": True}
        if prepared.startswith("postgresql"):
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
        store_name = self._store_name(model)
        with self.session() as session:
            self._advisory_lock(session, store_name)
            version_row = self._version_row(session, store_name)
            if expected_version is not None and version_row.version != expected_version:
                raise StaleDataError(store_name)
            session.query(model).delete()
            payloads = [
                model(row_order=i, data_json=json.dumps(row, ensure_ascii=False))
                for i, row in enumerate(rows)
            ]
            session.add_all(payloads)
            version_row.version += 1
            session.flush()
            return version_row.version
