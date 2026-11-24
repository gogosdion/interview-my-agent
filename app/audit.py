"""Audit logging. Each event is written in the same database transaction as the
state change it describes, so the log and the data can never disagree."""

from sqlalchemy.orm import Session

from app.db import AuditEvent


def log_event(session: Session, conversation_id: int | None, event_type: str, actor: str, data: dict | None = None) -> None:
    session.add(AuditEvent(conversation_id=conversation_id, event_type=event_type, actor=actor, data=data or {}))


def preview(text: str, limit: int = 300) -> str:
    """Keep audit rows small: store a preview, not whole documents."""
    text = text or ""
    return text if len(text) <= limit else text[:limit] + "…"
