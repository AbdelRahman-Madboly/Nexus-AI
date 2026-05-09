"""
api/models/crm_models.py
========================
Pydantic v2 request/response models for all 4 Nexus database tables.

Rules enforced here:
  - Every endpoint has a typed request model AND a typed response model.
  - No dict / Any return types anywhere in the project.
  - LeadStage enum is the single source of truth for valid stage values.
  - Create variants omit server-generated fields (id, timestamps).
  - Update variants make every field Optional so partial updates work.
  - All models use model_config = ConfigDict(from_attributes=True) so they
    can be constructed directly from aiosqlite.Row objects.
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import uuid4

from pydantic import ConfigDict, Field
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# LeadStage enum — single source of truth used by agents + CRM + MCP tools
# ---------------------------------------------------------------------------

class LeadStage(str, Enum):
    new_lead     = "new_lead"
    hot_lead     = "hot_lead"      # score >= 80
    nurture      = "nurture"       # score 50-79
    proposal     = "proposal"
    closed_won   = "closed_won"
    closed_lost  = "closed_lost"
    disqualified = "disqualified"  # score < 50
    escalated    = "escalated"     # red flags present


# ---------------------------------------------------------------------------
# Lead models
# ---------------------------------------------------------------------------

class LeadBase(BaseModel):
    """Shared fields for Lead create + update."""
    company:       str            = Field(..., description="Company or organisation name.")
    contact_name:  Optional[str]  = Field(None, description="Primary contact full name.")
    contact_email: Optional[str]  = Field(None, description="Primary contact email.")
    source:        Optional[str]  = Field(None, description="Lead source — website, referral, LinkedIn, etc.")
    stage:         LeadStage      = Field(LeadStage.new_lead, description="Current pipeline stage.")
    score:         int            = Field(0, ge=0, le=100, description="Lead quality score (0-100).")


class LeadCreate(LeadBase):
    """
    Request body for POST /api/agents/lead/classify and direct lead creation.
    id and timestamps are server-generated — not accepted from the client.
    """
    pass


class LeadUpdate(BaseModel):
    """
    Request body for PATCH /api/leads/{id}.
    Every field is Optional — partial updates are valid.
    """
    company:       Optional[str]       = None
    contact_name:  Optional[str]       = None
    contact_email: Optional[str]       = None
    source:        Optional[str]       = None
    stage:         Optional[LeadStage] = None
    score:         Optional[int]       = Field(None, ge=0, le=100)


class Lead(LeadBase):
    """
    Full Lead record — returned by all read endpoints.
    Constructed from aiosqlite.Row via model_validate(dict(row)).
    """
    model_config = ConfigDict(from_attributes=True)

    id:         str       = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime  = Field(default_factory=datetime.utcnow)
    updated_at: datetime  = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Deal models
# ---------------------------------------------------------------------------

class DealBase(BaseModel):
    """Shared fields for Deal create + update."""
    lead_id:      str            = Field(..., description="FK → leads.id")
    stage:        str            = Field(..., description="Deal stage name.")
    value:        Optional[float]= Field(None, ge=0, description="Estimated deal value in USD.")
    owner:        Optional[str]  = Field(None, description="Sales rep name or ID responsible.")
    last_contact: Optional[datetime] = Field(None, description="Timestamp of most recent contact.")


class DealCreate(DealBase):
    """Request body for deal creation. id and timestamps are server-generated."""
    pass


class DealUpdate(BaseModel):
    """Partial update for a Deal record."""
    stage:        Optional[str]      = None
    value:        Optional[float]    = Field(None, ge=0)
    owner:        Optional[str]      = None
    last_contact: Optional[datetime] = None


class Deal(DealBase):
    """Full Deal record returned by read endpoints."""
    model_config = ConfigDict(from_attributes=True)

    id:         str      = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# AgentRun models
# ---------------------------------------------------------------------------

class AgentRunStatus(str, Enum):
    running   = "running"
    completed = "completed"
    failed    = "failed"


class AgentRunCreate(BaseModel):
    """Written to agent_runs at the start of every LangGraph run."""
    agent_name: str            = Field(..., description="e.g. 'lead_classifier'")
    run_id:     str            = Field(..., description="LangGraph thread / run UUID.")
    input_json: Optional[str]  = Field(None, description="JSON-serialised input state.")


class AgentRunUpdate(BaseModel):
    """Written to agent_runs when the run completes or fails."""
    output_json:  Optional[str]      = None
    status:       Optional[AgentRunStatus] = None
    completed_at: Optional[datetime] = None


class AgentRun(BaseModel):
    """Full AgentRun record — returned by GET /api/agents/trace/{run_id}."""
    model_config = ConfigDict(from_attributes=True)

    id:           str
    agent_name:   str
    run_id:       str
    input_json:   Optional[str]      = None
    output_json:  Optional[str]      = None
    status:       AgentRunStatus     = AgentRunStatus.running
    started_at:   datetime
    completed_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# RagQuery models
# ---------------------------------------------------------------------------

class RagQueryCreate(BaseModel):
    """Written to rag_queries when a RAG query is received."""
    query_text: str           = Field(..., description="The user's raw question.")
    model_used: Optional[str] = Field(None, description="LLM model that answered.")


class RagQueryUpdate(BaseModel):
    """Written to rag_queries once the RAG pipeline completes."""
    response_text: Optional[str] = None
    sources_json:  Optional[str] = None   # JSON-serialised list of source citations
    latency_ms:    Optional[int] = Field(None, ge=0)


class RagQuery(BaseModel):
    """Full RagQuery record."""
    model_config = ConfigDict(from_attributes=True)

    id:            str
    query_text:    str
    response_text: Optional[str] = None
    sources_json:  Optional[str] = None
    latency_ms:    Optional[int] = None
    model_used:    Optional[str] = None
    created_at:    datetime


# ---------------------------------------------------------------------------
# Shared API envelope models
# ---------------------------------------------------------------------------

class HealthComponent(BaseModel):
    """Status of a single infrastructure component."""
    status:  str           = Field(..., description="'ok' | 'degraded' | 'down'")
    detail:  Optional[str] = None


class HealthResponse(BaseModel):
    """GET /api/health response."""
    status:     str                            = "ok"
    components: dict[str, HealthComponent]    = Field(default_factory=dict)