"""Database models: conversations, approvals and an append-only audit log."""

import secrets
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app.config import settings

_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, pool_pre_ping=True, connect_args=_connect_args)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Conversation(Base):
    """One visitor's conversation with the agent, plus everything needed to resume it."""

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Random secret given only to the visitor who started the conversation,
    # so nobody can read someone else's conversation by guessing its id.
    access_key: Mapped[str] = mapped_column(String(64), default=lambda: secrets.token_urlsafe(24))
    # idle -> running -> (waiting_approval -> queued -> running)* -> idle | failed
    status: Mapped[str] = mapped_column(String(32), default="queued")
    # Full message history with the LLM, saved after every step (checkpointing),
    # so a conversation waiting for approval survives restarts and deploys.
    messages: Mapped[list] = mapped_column(JSON, default=list)
    # Results of tools that already ran while we wait for a human decision.
    pending_tool_results: Mapped[list] = mapped_column(JSON, default=list)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    steps: Mapped[int] = mapped_column(Integer, default=0)  # steps in the current turn
    visitor_messages: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Approval(Base):
    """An action that waits for Dionysios to approve or reject it."""

    __tablename__ = "approvals"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    tool_use_id: Mapped[str] = mapped_column(String(128))
    tool_name: Mapped[str] = mapped_column(String(64))
    tool_input: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | approved | rejected
    reviewer: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditEvent(Base):
    """Append-only record of who/what did what and when. Rows are never updated or deleted."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id"), index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    event_type: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(128))  # "agent", "visitor", "system" or "human:<name>"
    data: Mapped[dict] = mapped_column(JSON, default=dict)


def init_db() -> None:
    # Demo shortcut. In production the schema would be managed with migrations (Alembic).
    Base.metadata.create_all(engine)
