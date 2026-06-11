import os
from datetime import datetime
from urllib.parse import quote_plus

from dotenv import load_dotenv
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(PROJECT_ROOT, ".env")


def load_env_file(env_path=ENV_FILE):
    load_dotenv(env_path)


def get_database_url():
    load_env_file()

    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "5432")
    name = os.getenv("DB_NAME", "productivity_tracker")
    user = os.getenv("DB_USER", "postgres")
    password = os.getenv("DB_PASSWORD", "")

    if not password:
        raise RuntimeError("DB_PASSWORD is not configured in the environment.")

    return (
        "postgresql+psycopg2://"
        f"{quote_plus(user)}:{quote_plus(password)}@{host}:{port}/{name}"
    )


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('employee', 'manager')", name="ck_users_role"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    employee_id: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    employee_name: Mapped[str] = mapped_column(String(160), nullable=False)
    login_email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    manager_email: Mapped[str] = mapped_column(String(255), nullable=False)
    sender_gmail: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    gmail_app_password: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="employee")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    projects: Mapped[list["Project"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    activities: Mapped[list["Activity"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    tasks: Mapped[list["Task"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Activity(Base):
    __tablename__ = "activities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=True)
    ai_task_name: Mapped[str] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(80), nullable=True)
    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    end_time: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    duration: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_assigned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    email_sent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="activities")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="projects")
    tasks: Mapped[list["Task"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    task_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(80), nullable=True)
    duration: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="tasks")
    project: Mapped["Project"] = relationship(back_populates="tasks")


engine = None
SessionLocal = None


def get_engine():
    global engine

    if engine is None:
        engine = create_engine(get_database_url(), pool_pre_ping=True, future=True)

    return engine


def get_session_factory():
    global SessionLocal

    if SessionLocal is None:
        SessionLocal = sessionmaker(
            bind=get_engine(),
            autoflush=False,
            autocommit=False,
            future=True,
        )

    return SessionLocal


def get_db_session():
    return get_session_factory()()


def create_tables():
    Base.metadata.create_all(bind=get_engine())
    ensure_activity_assignment_column()
    ensure_activity_email_archive_columns()


def ensure_activity_assignment_column():
    inspector = inspect(get_engine())
    if "activities" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("activities")}
    if "is_assigned" in columns:
        return
    with get_engine().begin() as connection:
        connection.execute(
            text("ALTER TABLE activities ADD COLUMN is_assigned BOOLEAN NOT NULL DEFAULT FALSE")
        )


def ensure_activity_email_archive_columns():
    inspector = inspect(get_engine())
    if "activities" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("activities")}
    statements = []
    if "email_sent" not in columns:
        statements.append("ALTER TABLE activities ADD COLUMN email_sent BOOLEAN NOT NULL DEFAULT FALSE")
    if "sent_at" not in columns:
        statements.append("ALTER TABLE activities ADD COLUMN sent_at TIMESTAMP NULL")
    if not statements:
        return
    with get_engine().begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def test_connection():
    with get_engine().connect() as connection:
        connection.execute(text("SELECT 1"))
    return True


def list_tables():
    return sorted(inspect(get_engine()).get_table_names())


def initialize_postgres_foundation(required=False):
    try:
        test_connection()
        create_tables()
        return True
    except Exception as error:
        if required:
            raise

        print(f"PostgreSQL foundation not initialized: {error}")
        return False
