"""REST API: visitor conversations, Dionysios's approvals, and the audit log."""

import secrets
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.agent import (ApprovalError, ConversationBusy, add_message, decide_approval, run_agent,
                       start_conversation, transcript)
from app.config import settings
from app.db import Approval, AuditEvent, Conversation, SessionLocal, init_db
from app.knowledge import load_projects
from app.limits import check_limits, is_public_request

STATIC = Path(__file__).parent / "static"
NO_CACHE = {"Cache-Control": "no-cache"}  # browsers (especially on phones) always check for the latest page


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Interview my agent · Dionysios Kyriakongonas",
    description="An AI agent that answers questions about Dionysios from his CV and projects, "
                "with human-in-the-loop approval and an append-only audit log.",
    version="1.0.0",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


def require_admin(request: Request, x_admin_token: str = Header(default="")):
    """Protects the admin endpoints. Without ADMIN_TOKEN they only work from this laptop."""
    if settings.admin_token:
        if not secrets.compare_digest(x_admin_token, settings.admin_token):
            raise HTTPException(status_code=401, detail="Admin token required")
    elif is_public_request(request):
        raise HTTPException(status_code=403, detail="Set ADMIN_TOKEN in .env to use the admin view over a public link")


def _visitor_conversation(s, conversation_id: int, key: str) -> Conversation:
    """A visitor can only see a conversation if they have its secret key."""
    conv = s.get(Conversation, conversation_id)
    if conv is None or not key or not secrets.compare_digest(key, conv.access_key):
        raise HTTPException(status_code=404, detail="Conversation not found")  # same answer: don't reveal which ids exist
    return conv


# --- Schemas -----------------------------------------------------------------
class MessageIn(BaseModel):
    message: str = Field(min_length=1, max_length=1000, examples=["What has he built with MCP?"])


class SourceOut(BaseModel):
    id: str
    label: str


class TranscriptItem(BaseModel):
    role: str  # visitor | agent | tool
    text: str
    sources: list[SourceOut] = []  # only sources the code verified against the tool results


class ConversationOut(BaseModel):
    id: int
    status: str
    last_error: str | None
    visitor_messages: int
    input_tokens: int
    output_tokens: int
    created_at: datetime
    updated_at: datetime
    transcript: list[TranscriptItem]
    access_key: str | None = None  # only returned to the visitor who started the conversation


class ApprovalOut(BaseModel):
    id: int
    conversation_id: int
    tool_name: str
    tool_input: dict[str, Any]
    status: str
    reviewer: str | None
    reason: str | None
    created_at: datetime
    decided_at: datetime | None

    model_config = {"from_attributes": True}


class Decision(BaseModel):
    reviewer: str = Field(default="Dionysios", min_length=1, max_length=128)
    reason: str | None = Field(default=None, max_length=1000)


class AuditOut(BaseModel):
    id: int
    created_at: datetime
    event_type: str
    actor: str
    data: dict[str, Any]

    model_config = {"from_attributes": True}


def _out(conv: Conversation, with_key: bool = False) -> ConversationOut:
    return ConversationOut(
        access_key=conv.access_key if with_key else None,
        id=conv.id, status=conv.status, last_error=conv.last_error, visitor_messages=conv.visitor_messages,
        input_tokens=conv.input_tokens, output_tokens=conv.output_tokens, created_at=conv.created_at,
        updated_at=conv.updated_at, transcript=[TranscriptItem(**t) for t in transcript(conv)],
    )


# --- Pages ---------------------------------------------------------------------
@app.get("/", include_in_schema=False)
def visitor_page():
    return FileResponse(STATIC / "index.html", headers=NO_CACHE)


@app.get("/admin", include_in_schema=False)
def admin_page():
    return FileResponse(STATIC / "admin.html", headers=NO_CACHE)


# --- Public API ----------------------------------------------------------------
@app.get("/health", tags=["system"])
def health():
    return {"status": "ok", "llm_mode": settings.llm_mode, "model": settings.anthropic_model,
            "admin_protected": bool(settings.admin_token)}


@app.get("/api/projects", tags=["profile"])
def projects():
    return [{k: p[k] for k in ("name", "domain", "client", "summary", "tags", "case_study")} for p in load_projects()]


@app.post("/conversations", response_model=ConversationOut, status_code=201, tags=["conversations"],
          dependencies=[Depends(check_limits)])
def create_conversation(body: MessageIn, background: BackgroundTasks):
    """Start a conversation. Returns its access_key; use it as ?key= for the other visitor endpoints.
    The agent answers in the background; poll GET /conversations/{id}?key=..."""
    conv = start_conversation(body.message)
    background.add_task(run_agent, conv.id)
    return _out(conv, with_key=True)


@app.post("/conversations/{conversation_id}/messages", response_model=ConversationOut, status_code=202,
          tags=["conversations"], dependencies=[Depends(check_limits)])
def send_message(conversation_id: int, body: MessageIn, background: BackgroundTasks, key: str = Query(default="")):
    with SessionLocal() as s:
        _visitor_conversation(s, conversation_id, key)
    try:
        conv = add_message(conversation_id, body.message)
    except LookupError:
        raise HTTPException(status_code=404, detail="Conversation not found")
    except ConversationBusy as e:
        raise HTTPException(status_code=409, detail=str(e))
    background.add_task(run_agent, conv.id)
    return _out(conv)


@app.get("/conversations/{conversation_id}", response_model=ConversationOut, tags=["conversations"])
def get_conversation(conversation_id: int, key: str = Query(default="")):
    with SessionLocal() as s:
        return _out(_visitor_conversation(s, conversation_id, key))


# --- Admin API (Dionysios) -------------------------------------------------------
@app.get("/conversations", response_model=list[ConversationOut], tags=["admin"], dependencies=[Depends(require_admin)])
def list_conversations():
    with SessionLocal() as s:
        return [_out(c) for c in s.query(Conversation).order_by(Conversation.id.desc()).limit(50).all()]


@app.get("/conversations/{conversation_id}/audit", response_model=list[AuditOut], tags=["admin"],
         dependencies=[Depends(require_admin)])
def get_audit(conversation_id: int):
    """Everything that happened in this conversation, in order: messages, model calls, tools, approvals."""
    with SessionLocal() as s:
        if s.get(Conversation, conversation_id) is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return s.query(AuditEvent).filter_by(conversation_id=conversation_id).order_by(AuditEvent.id).all()


@app.get("/approvals", response_model=list[ApprovalOut], tags=["admin"], dependencies=[Depends(require_admin)])
def list_approvals(status: str | None = Query(default="pending", description="pending, approved, rejected or empty for all")):
    with SessionLocal() as s:
        q = s.query(Approval)
        if status:
            q = q.filter_by(status=status)
        return q.order_by(Approval.id.desc()).all()


def _decide(approval_id: int, approve: bool, body: Decision, background: BackgroundTasks):
    try:
        approval, resume = decide_approval(approval_id, approve, body.reviewer, body.reason)
    except LookupError:
        raise HTTPException(status_code=404, detail="Approval not found")
    except ApprovalError as e:
        raise HTTPException(status_code=409, detail=str(e))  # 409 Conflict: already decided
    if resume:
        background.add_task(run_agent, approval.conversation_id)
    return approval


@app.post("/approvals/{approval_id}/approve", response_model=ApprovalOut, tags=["admin"],
          dependencies=[Depends(require_admin)])
def approve(approval_id: int, background: BackgroundTasks, body: Decision = Decision()):
    """Approve the action. The tool runs now, then the agent continues."""
    return _decide(approval_id, True, body, background)


@app.post("/approvals/{approval_id}/reject", response_model=ApprovalOut, tags=["admin"],
          dependencies=[Depends(require_admin)])
def reject(approval_id: int, background: BackgroundTasks, body: Decision = Decision()):
    """Reject the action. The agent is told and replies to the visitor."""
    return _decide(approval_id, False, body, background)
