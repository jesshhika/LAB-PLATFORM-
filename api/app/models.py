from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from api.app.core.db import Base


class LabSession(Base):
    __tablename__ = "lab_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    lab_id: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(32), default="provisioning")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    max_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    vm_name: Mapped[str | None] = mapped_column(String(128))
    resource_group: Mapped[str | None] = mapped_column(String(128))
    vm_private_ip: Mapped[str | None] = mapped_column(String(45))
    vm_username: Mapped[str | None] = mapped_column(String(128))
    vm_password_secret_name: Mapped[str | None] = mapped_column(String(128))
    azure_username_secret_name: Mapped[str | None] = mapped_column(String(128))
    azure_password_secret_name: Mapped[str | None] = mapped_column(String(128))
    azure_resource_group: Mapped[str | None] = mapped_column(String(128))
    azure_subscription_id: Mapped[str | None] = mapped_column(String(36))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    extension_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class LabProgress(Base):
    __tablename__ = "lab_progress"
    __table_args__ = (UniqueConstraint("user_id", "lab_id", name="uq_lab_progress_user_lab"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    lab_id: Mapped[str] = mapped_column(String(128), index=True)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    method: Mapped[str | None] = mapped_column(String(32))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TaskProgress(Base):
    __tablename__ = "task_progress"
    __table_args__ = (
        UniqueConstraint("user_id", "lab_id", "task_index", name="uq_task_progress_user_lab_task"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    lab_id: Mapped[str] = mapped_column(String(128), index=True)
    task_index: Mapped[int] = mapped_column(Integer)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LabUser(Base):
    __tablename__ = "lab_users"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(32), default="learner")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    slug: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(256))
    description: Mapped[str] = mapped_column(Text, default="")
    image_definition: Mapped[str | None] = mapped_column(String(128))
    image_version: Mapped[str | None] = mapped_column(String(64))
    vm_size: Mapped[str] = mapped_column(String(64), default="Standard_B2s")
    session_minutes: Mapped[int] = mapped_column(Integer, default=180)
    pool_size: Mapped[int] = mapped_column(Integer, default=0)
    needs_azure_sandbox: Mapped[bool] = mapped_column(Boolean, default=False)


class Enrollment(Base):
    __tablename__ = "enrollments"
    __table_args__ = (UniqueConstraint("user_id", "course_id", name="uq_enrollment_user_course"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    course_id: Mapped[str] = mapped_column(String(128), index=True)
    enrolled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    action: Mapped[str] = mapped_column(String(128), index=True)
    details: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
