"""Org-scoped schema. Every table carries organization_id for multi-tenant isolation.
RLS policies for Postgres deployments live in db/migrations/0002_rls.sql."""
import datetime
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def uid() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)


class ApiKey(Base):
    __tablename__ = "api_keys"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    key_hash: Mapped[str] = mapped_column(String(64), index=True)  # sha256 hex
    scopes: Mapped[List[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)
    revoked_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)


class Agent(Base):
    """Agent registry: definitions live separate from reusable skills."""
    __tablename__ = "agents"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    slug: Mapped[str] = mapped_column(String(80), index=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(32), default="specialist")  # orchestrator|specialist
    description: Mapped[str] = mapped_column(Text, default="")
    skills: Mapped[List[str]] = mapped_column(JSON, default=list)  # allowed skill slugs
    permissions: Mapped[List[str]] = mapped_column(JSON, default=list)  # action classes allowed
    status: Mapped[str] = mapped_column(String(24), default="active")
    active_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)


class AgentVersion(Base):
    __tablename__ = "agent_versions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    instructions: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str] = mapped_column(String(80), default="")
    definition: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)


class Skill(Base):
    __tablename__ = "skills"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    slug: Mapped[str] = mapped_column(String(80), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    active_version: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)


class SkillVersion(Base):
    __tablename__ = "skill_versions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    skill_id: Mapped[str] = mapped_column(ForeignKey("skills.id"), index=True)
    version: Mapped[str] = mapped_column(String(40))  # semver
    content_hash: Mapped[str] = mapped_column(String(64))
    body: Mapped[str] = mapped_column(Text)  # SKILL.md contents at publish time
    schema_input: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    schema_output: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(24), default="published")  # published|rolled_back
    created_by: Mapped[str] = mapped_column(String(120), default="")
    approval_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    agent_id: Mapped[Optional[str]] = mapped_column(ForeignKey("agents.id"), nullable=True)
    skill_slug: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    input: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    # queued|running|succeeded|failed|waiting_approval|cancelled
    priority: Mapped[int] = mapped_column(Integer, default=100)
    scheduled_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=600)
    conversation_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    created_by: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class TaskRun(Base):
    __tablename__ = "task_runs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(24), default="running")
    skill_version: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    output: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    started_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    task_id: Mapped[Optional[str]] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(120))  # e.g. skill.publish, schedule.create
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    requested_by: Mapped[str] = mapped_column(String(120), default="")
    decided_by: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    decided_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    owner_user_id: Mapped[str] = mapped_column(String(120), index=True)  # owner-only memory
    client_app: Mapped[str] = mapped_column(String(80), default="laurel-haven")
    title: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    role: Mapped[str] = mapped_column(String(24))
    content: Mapped[str] = mapped_column(Text, default="")
    tool_events: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)


class UsageCost(Base):
    __tablename__ = "usage_costs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    task_run_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    provider: Mapped[str] = mapped_column(String(40), default="openai")
    model: Mapped[str] = mapped_column(String(80), default="")
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    organization_id: Mapped[Optional[str]] = mapped_column(String(32), index=True, nullable=True)
    principal_type: Mapped[str] = mapped_column(String(24), default="system")  # owner|machine|system
    principal_id: Mapped[str] = mapped_column(String(120), default="")
    action: Mapped[str] = mapped_column(String(120), index=True)
    entity: Mapped[str] = mapped_column(String(80), default="")
    entity_id: Mapped[str] = mapped_column(String(64), default="")
    detail: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow, index=True)


class Schedule(Base):
    __tablename__ = "schedules"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    interval_seconds: Mapped[int] = mapped_column(Integer, default=3600)
    agent_slug: Mapped[str] = mapped_column(String(80))
    skill_slug: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    input: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(24), default="active")  # active|paused
    next_run_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class EventTrigger(Base):
    __tablename__ = "event_triggers"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    event_name: Mapped[str] = mapped_column(String(120), index=True)
    agent_slug: Mapped[str] = mapped_column(String(80))
    skill_slug: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    input_template: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(24), default="active")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)
