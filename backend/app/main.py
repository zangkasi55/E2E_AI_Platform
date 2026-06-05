"""FastAPI application — Agentic AI Platform PoC orchestration runtime.

Maps to Azure Container Apps ``agpoc-aca-orch-dev``. Exposes the UC1 credit-memo
endpoints (with HITL approve/resume), the UC2 banking endpoint, run-trace
queries, and the token-monitoring endpoints.

Run locally:
    uvicorn app.main:app --reload --port 8000
(MOCK_MODE=true by default — no Azure needed.)
"""
from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .config import settings
from .governance.policies import governance_payload
from .models import (
    ApprovalDecision,
    BankingMessage,
    BankingResponse,
    RunRequest,
    RunState,
    TokenSummary,
)
from .orchestration.banking_controller import banking_controller
from .orchestration.memo_orchestrator import memo_orchestrator
from .telemetry.audit import audit_store
from .telemetry.otel import configure_telemetry
from .telemetry.purview_audit import recent_events
from .telemetry.tokens import token_meter

app = FastAPI(
    title="Agentic AI Platform PoC — Orchestrator",
    version="0.1.0",
    description="UC1 Credit Memo Drafting (HITL) + UC2 Conversational Banking (deterministic, no money movement).",
)

# CORS — the static demo UI pages (opened via file:// or a separate static host)
# poll endpoints such as ``/api/governance/policies`` to render the live platform
# wiring status. Allow any origin for the PoC; tighten to the UI host in prod.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    # No-op in MOCK_MODE; wires Azure Monitor in live mode.
    configure_telemetry()


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.get("/healthz", tags=["meta"])
def healthz() -> dict:
    """Liveness probe + effective mode."""
    return {
        "status": "ok",
        "mock_mode": settings.mock_mode,
        "environment": settings.environment,
        "version": app.version,
    }


@app.get("/api/governance/policies", tags=["governance"])
def get_governance_policies() -> dict:
    """Return data and security policy artifacts + component wiring status."""
    return governance_payload()


@app.get("/api/governance/dspm-events", tags=["governance"])
def get_dspm_events(limit: int = 50) -> list[dict]:
    """Recent Microsoft Purview / DSPM-for-AI data-security events.

    Includes sensitivity-label scans and DLP blocks raised by the credit-memo
    upload gate (Confidential / Highly Confidential rejections).
    """
    return recent_events(limit)


# ===========================================================================
# UC1 — Credit Memo
# ===========================================================================
@app.post("/api/credit-memo/run", response_model=RunState, tags=["credit-memo"])
def create_credit_memo_run(request: RunRequest) -> RunState:
    """Start a credit-memo drafting run. Returns the run paused at HITL."""
    return memo_orchestrator.start(request)


@app.get("/api/credit-memo/run/{run_id}", response_model=RunState, tags=["credit-memo"])
def get_credit_memo_run(run_id: str) -> RunState:
    """Fetch the current state of a credit-memo run."""
    run = audit_store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return run


class ApproveRequest(BaseModel):
    """Payload for the HITL approve/resume endpoint."""

    approved: bool
    reviewer: str
    comment: Optional[str] = None
    edits: Optional[dict] = None


@app.post("/api/credit-memo/run/{run_id}/approve", response_model=RunState, tags=["credit-memo"])
def approve_credit_memo_run(run_id: str, body: ApproveRequest) -> RunState:
    """HITL resume — apply a human decision and finalize/reject the memo."""
    decision = ApprovalDecision(
        approved=body.approved, reviewer=body.reviewer, comment=body.comment, edits=body.edits
    )
    try:
        return memo_orchestrator.approve(run_id, decision)
    except KeyError:
        raise HTTPException(status_code=404, detail="run not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


# ===========================================================================
# UC2 — Conversational Banking
# ===========================================================================
@app.post("/api/banking/message", response_model=BankingResponse, tags=["banking"])
def banking_message(msg: BankingMessage) -> BankingResponse:
    """Process a conversational-banking turn. NEVER moves money — at most emits
    an auditable transaction handoff."""
    return banking_controller.handle(msg)


# ===========================================================================
# Run trace
# ===========================================================================
@app.get("/api/runs/{run_id}/trace", tags=["runs"])
def get_run_trace(run_id: str) -> dict:
    """Return the ordered step trace (+ any handoffs) for a run."""
    run = audit_store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return {
        "run_id": run_id,
        "use_case": run.use_case,
        "status": run.status,
        "steps": [s.model_dump() for s in audit_store.steps_for_run(run_id)],
        "handoffs": [h.model_dump() for h in audit_store.handoffs_for_run(run_id)],
    }


# ===========================================================================
# Token monitoring
# ===========================================================================
@app.get("/api/tokens/summary", response_model=TokenSummary, tags=["tokens"])
def tokens_summary() -> TokenSummary:
    """Cumulative token usage aggregated by agent, model, and run."""
    return token_meter.summarize()


@app.get("/api/tokens", tags=["tokens"])
def tokens_all() -> list[dict]:
    """Return all token records for the dashboard."""
    return [r.model_dump() for r in token_meter.all_records()]


@app.get("/api/tokens/run/{run_id}", tags=["tokens"])
def tokens_for_run(run_id: str) -> dict:
    """Per-run token records + summary (powers the UI Token Monitor timeline)."""
    records = token_meter.records_for_run(run_id)
    return {
        "run_id": run_id,
        "summary": token_meter.summarize(records).model_dump(),
        "records": [r.model_dump() for r in records],
    }
