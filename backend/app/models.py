"""Pydantic domain models shared across the backend.

These types are the contract between the API layer, the orchestrators, the
telemetry stores, and the UI. The ``TokenRecord`` schema in particular is the
canonical token-monitoring contract from POC_SPEC.md and must not drift.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


def _utcnow_iso() -> str:
    """ISO-8601 UTC timestamp (used for ``ts`` fields)."""
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid4())


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class UseCase(str, Enum):
    CREDIT_MEMO = "credit_memo"
    BANKING = "banking"


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"  # HITL pause (UC1)
    APPROVED = "approved"
    COMPLETED = "completed"
    REFUSED = "refused"  # guardrail block (UC2)
    FAILED = "failed"


class StepStatus(str, Enum):
    OK = "ok"
    BLOCKED = "blocked"
    ERROR = "error"


# ---------------------------------------------------------------------------
# Token monitoring (CANONICAL contract — POC_SPEC.md §Token monitoring)
# ---------------------------------------------------------------------------
class TokenRecord(BaseModel):
    """One record per model call. Stored in Cosmos ``tokens`` container and
    emitted to App Insights as custom metric ``gen_ai.token.usage``.

    Field set and names are fixed by the canonical contract.
    """

    run_id: str
    agent: str
    step: int
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    est_cost_usd: float = 0.0
    ts: str = Field(default_factory=_utcnow_iso)
    use_case: str  # "credit_memo" | "banking"

    # Cosmos requires an ``id``; partition key is run_id (see audit/tokens).
    id: str = Field(default_factory=_new_id)


# ---------------------------------------------------------------------------
# Step trace
# ---------------------------------------------------------------------------
class StepTrace(BaseModel):
    """A single planned/executed step in an orchestration run."""

    id: str = Field(default_factory=_new_id)
    run_id: str
    step: int
    agent: str
    action: str  # e.g. "search_documents", "plan", "guardrail_scan"
    status: StepStatus = StepStatus.OK
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    note: Optional[str] = None
    ts: str = Field(default_factory=_utcnow_iso)


# ---------------------------------------------------------------------------
# Run request / state
# ---------------------------------------------------------------------------
class RunRequest(BaseModel):
    """UC1 credit-memo run request."""

    class DRDocumentMetadata(BaseModel):
        """Client-supplied metadata for the DR attachment used at run start."""

        file_name: str
        size_bytes: int
        mime_type: Optional[str] = None
        last_modified_epoch_ms: Optional[int] = None
        uploaded_at: str = Field(default_factory=_utcnow_iso)
        # Extracted document text. When present, sub-agents analyse the actual
        # case content (identity, financials, bureau signals) rather than relying
        # on metadata. Best-effort; binary uploads may carry no usable text.
        content: Optional[str] = None

    applicant_id: str = Field(..., examples=["APP-1001"])
    template_id: str = Field("TMPL-SME-STD-01", examples=["TMPL-SME-STD-01"])
    requested_by: str = Field("loan.officer@example.local")
    notes: Optional[str] = None
    dr_document: Optional[DRDocumentMetadata] = None


class RunState(BaseModel):
    """Persisted state of a credit-memo run (Cosmos ``runs`` container)."""

    id: str = Field(default_factory=_new_id)  # == run_id
    run_id: str = Field(default_factory=_new_id)
    use_case: UseCase = UseCase.CREDIT_MEMO
    status: RunStatus = RunStatus.PENDING
    request: Optional[RunRequest] = None
    steps: list[StepTrace] = Field(default_factory=list)
    draft_memo: Optional[dict[str, Any]] = None
    final_memo: Optional[dict[str, Any]] = None
    # Set when a Purview sensitivity-label gate rejects the uploaded document.
    policy_block: Optional[dict[str, Any]] = None
    approval: Optional["ApprovalDecision"] = None
    created_at: str = Field(default_factory=_utcnow_iso)
    updated_at: str = Field(default_factory=_utcnow_iso)

    def touch(self) -> None:
        self.updated_at = _utcnow_iso()


class ApprovalDecision(BaseModel):
    """Human-in-the-loop decision recorded on resume (UC1)."""

    approved: bool
    reviewer: str
    comment: Optional[str] = None
    edits: Optional[dict[str, Any]] = None
    ts: str = Field(default_factory=_utcnow_iso)


# ---------------------------------------------------------------------------
# Banking (UC2)
# ---------------------------------------------------------------------------
class BankingMessage(BaseModel):
    """Inbound conversational-banking turn."""

    user_id: str = Field(..., examples=["USR-001"])
    src_account: Optional[str] = Field(None, examples=["ACC-001-CUR"])
    message: str = Field(..., examples=["Check my balance; if over 5000 transfer 2000 to mom"])
    # EKYC: the customer's confirmation that they are the account holder. The
    # controller requires this before any account action or transfer handoff.
    identity_confirmed: Optional[bool] = Field(
        None,
        description="True when the customer has confirmed they are the account holder (EKYC).",
    )
    # EKYC confirm/cancel loop: the customer is asked to Confirm or Cancel. A
    # cancel re-prompts (loop); more than two cancels aborts the flow as
    # EKYC_FAILED. ``ekyc_cancel_count`` carries how many cancels happened so far.
    ekyc_decision: Optional[Literal["confirm", "cancel"]] = Field(
        None,
        description="Customer's EKYC choice this turn: 'confirm' or 'cancel'.",
    )
    ekyc_cancel_count: int = Field(
        0,
        ge=0,
        description="How many times the customer has already cancelled EKYC in this flow.",
    )


class Slots(BaseModel):
    """Slot-filling result for a banking intent."""

    amount_thb: Optional[float] = None
    payee_alias: Optional[str] = None
    payee_id: Optional[str] = None
    src_account: Optional[str] = None
    threshold_thb: Optional[float] = None


class PolicyResult(BaseModel):
    """Deterministic policy/PDP evaluation result (not prompt-driven)."""

    eligible: bool
    reasons: list[str] = Field(default_factory=list)
    scope_ok: bool = True


class HandoffObject(BaseModel):
    """TERMINAL action for UC2. The controller NEVER moves money — it emits this
    auditable object for a downstream, human-confirmed, step-up-authenticated
    channel. Stored in Cosmos ``handoffs`` container.

    The two ``requires_*`` flags are hard-coded ``True`` by construction.
    """

    id: str = Field(default_factory=_new_id)
    handoff_id: str = Field(default_factory=lambda: f"HOFF-{uuid4().hex[:10]}")
    run_id: str
    user_id: str
    intent: str
    slots: Slots
    policy_result: PolicyResult
    # Non-negotiable safety flags (see POC_SPEC.md UC2 hard rule):
    requires_confirmation: Literal[True] = True
    requires_step_up_auth: Literal[True] = True
    status: Literal["pending_human_confirmation"] = "pending_human_confirmation"
    ts: str = Field(default_factory=_utcnow_iso)


class BankingResponse(BaseModel):
    """Result of processing one banking message."""

    run_id: str
    outcome: Literal[
        "HANDOFF_CREATED",
        "CONDITION_NOT_MET",
        "REFUSED",
        "INFO",
        "EKYC_REQUIRED",
        "EKYC_FAILED",
        "POLICY_DECLINED",
    ]
    message: str
    handoff: Optional[HandoffObject] = None
    ekyc: Optional[dict] = None
    # EKYC confirm/cancel loop bookkeeping echoed back to the client so the UI
    # can show "attempt N of 3" and resend the running cancel count.
    ekyc_cancel_count: int = 0
    judgement: Optional[dict] = None
    steps: list[StepTrace] = Field(default_factory=list)


class BankPolicy(BaseModel):
    """Adjustable bank transfer-limit policy (UC2)."""

    policy_id: Optional[str] = None
    name: Optional[str] = None
    currency: str = "THB"
    transfer_limit_thb_per_txn: float = Field(..., gt=0)
    ekyc_required_for_transfer: bool = True


class BankPolicyUpdate(BaseModel):
    """Payload to adjust the per-transaction transfer limit."""

    transfer_limit_thb_per_txn: float = Field(..., gt=0, examples=[1500.0])


# ---------------------------------------------------------------------------
# Token aggregation views (for /api/tokens/*)
# ---------------------------------------------------------------------------
class TokenSummary(BaseModel):
    total_tokens: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    est_cost_usd: float = 0.0
    by_agent: dict[str, int] = Field(default_factory=dict)
    by_model: dict[str, int] = Field(default_factory=dict)
    by_run: dict[str, int] = Field(default_factory=dict)
    record_count: int = 0


# Resolve forward reference (RunState -> ApprovalDecision).
RunState.model_rebuild()
