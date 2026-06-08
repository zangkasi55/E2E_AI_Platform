"""Foundry **workflow agent** runtime client (UC1 / UC2 orchestration engine).

This complements :mod:`foundry_client` (which invokes single *prompt* agents).
Here we invoke the provisioned Foundry **workflow agents**
(``definition.kind = "workflow"`` — ``credit-memo-workflow`` and
``banking-control-workflow``) created by
``scripts/provision_foundry_agents.py``. A workflow agent drives its child
agents server-side per the declarative CSDL (including the human-approval
``Question`` node in the credit-memo workflow).

Invocation uses the same per-agent OpenAI-compatible **responses** endpoint as
prompt agents, addressed by the workflow agent name, plus the preview opt-in
header required by Workflow Agents::

    POST {project_endpoint}/agents/{workflow_name}/endpoint/protocols/openai/responses
    Foundry-Features: WorkflowAgents=V1Preview

Two operations are exposed:

* :func:`invoke_workflow` — start a workflow run with the initial user input.
  The credit-memo workflow runs its agents and then PAUSES at the ``Question``
  (HITL) node, returning a ``response_id``/``conversation_id`` resume handle.
* :func:`resume_workflow` — continue a paused workflow by sending the reviewer's
  decision (``"approve"`` / ``"reject"``) against the prior ``response_id``.

Design note — *deterministic policy boundary stays in Python*. The Python
orchestrators ([memo_orchestrator.py], [banking_controller.py]) still run the
guardrail / sensitivity pre-gates, the policy post-gates, and own the
``AWAITING_APPROVAL`` state machine. This client only delegates the agentic
(LLM) orchestration to Foundry; it never relies on the preview workflow engine
to enforce the "no money moves" / hard-reject guarantees.

Mock-safe: in ``MOCK_MODE`` (and no ``LIVE_LLM``) no network call is made — a
deterministic synthetic result is returned so the demo and tests run offline.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

from ..config import settings
from .foundry_client import (
    API_VERSION,
    _extract_text,
    _extract_usage,
    _get_token,
)

# Preview opt-in header (must match provision_foundry_agents.WORKFLOW_OPT_IN_HEADER).
WORKFLOW_OPT_IN_HEADER = ("Foundry-Features", "WorkflowAgents=V1Preview")

# Server status values that indicate the run paused awaiting human input. The
# exact value is preview-dependent, so several plausible signals are accepted.
_AWAITING_STATUSES = {
    "requires_action",
    "requires_input",
    "in_progress",
    "incomplete",
    "paused",
    "waiting",
}


@dataclass
class WorkflowRunResult:
    """Result of a workflow-agent invocation (or resume)."""

    text: str
    usage: dict[str, int] = field(default_factory=dict)
    workflow_name: str = ""
    response_id: Optional[str] = None
    conversation_id: Optional[str] = None
    awaiting_input: bool = False
    status: Optional[str] = None
    mocked: bool = False


def _responses_url(workflow_name: str) -> str:
    endpoint = settings.foundry_project_endpoint.rstrip("/")
    return (
        f"{endpoint}/agents/{workflow_name}/endpoint/protocols/openai/responses"
        f"?api-version={API_VERSION}"
    )


def _awaiting_input(payload: dict) -> bool:
    """Best-effort detection that a workflow paused on a HITL ``Question`` node."""
    status = str(payload.get("status") or "").lower()
    if status in _AWAITING_STATUSES:
        return True
    # Some preview responses surface a pending question as a required action.
    if payload.get("required_action") or payload.get("requires_action"):
        return True
    return False


def _post(workflow_name: str, body: dict) -> dict:
    """POST a responses request to the workflow agent endpoint (live mode)."""
    req = urllib.request.Request(
        _responses_url(workflow_name),
        data=json.dumps(body).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {_get_token()}",
            "Content-Type": "application/json",
            WORKFLOW_OPT_IN_HEADER[0]: WORKFLOW_OPT_IN_HEADER[1],
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as exc:  # pragma: no cover - network path
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(
            f"Foundry workflow '{workflow_name}' invoke failed ({exc.code}): {detail}"
        )
    except urllib.error.URLError as exc:  # pragma: no cover - network path
        raise RuntimeError(
            f"Foundry workflow '{workflow_name}' transport error: {exc.reason}"
        )


def _live() -> bool:
    """True when the workflow should be invoked over the network."""
    return bool(settings.foundry_project_endpoint) and (
        (not settings.mock_mode) or settings.live_llm or settings.use_foundry_agents
    )


def invoke_workflow(workflow_name: str, input_text: str) -> WorkflowRunResult:
    """Start a workflow-agent run with the initial user ``input_text``.

    Returns a :class:`WorkflowRunResult` carrying any narrative text the workflow
    produced and a resume handle (``response_id``/``conversation_id``) so a
    paused HITL run can be continued. In mock mode a deterministic synthetic
    result is returned without any network call.
    """
    if not _live():
        return WorkflowRunResult(
            text=f"[workflow-mock:{workflow_name}] orchestrated agents for input "
            f"({len(input_text)} chars).",
            workflow_name=workflow_name,
            response_id=f"mock-resp-{abs(hash(input_text)) % 10_000_000}",
            conversation_id=f"mock-conv-{abs(hash(workflow_name)) % 10_000_000}",
            awaiting_input=True,
            status="mock",
            mocked=True,
        )
    payload = _post(workflow_name, {"input": input_text})
    return WorkflowRunResult(
        text=_extract_text(payload),
        usage=_extract_usage(payload),
        workflow_name=workflow_name,
        response_id=payload.get("id"),
        conversation_id=(payload.get("conversation") or {}).get("id")
        if isinstance(payload.get("conversation"), dict)
        else payload.get("conversation_id"),
        awaiting_input=_awaiting_input(payload),
        status=payload.get("status"),
    )


def resume_workflow(
    workflow_name: str,
    previous_response_id: Optional[str],
    answer: str,
    *,
    conversation_id: Optional[str] = None,
) -> WorkflowRunResult:
    """Continue a paused workflow by sending the reviewer's ``answer``.

    ``answer`` is the HITL decision text (``"approve"`` / ``"reject"``) routed to
    the workflow's ``Question`` node via ``previous_response_id``.
    """
    if not _live():
        return WorkflowRunResult(
            text=f"[workflow-mock:{workflow_name}] resumed with decision '{answer}'.",
            workflow_name=workflow_name,
            response_id=previous_response_id,
            conversation_id=conversation_id,
            awaiting_input=False,
            status="mock",
            mocked=True,
        )
    body: dict = {"input": answer}
    if previous_response_id:
        body["previous_response_id"] = previous_response_id
    if conversation_id:
        body["conversation"] = {"id": conversation_id}
    payload = _post(workflow_name, body)
    return WorkflowRunResult(
        text=_extract_text(payload),
        usage=_extract_usage(payload),
        workflow_name=workflow_name,
        response_id=payload.get("id") or previous_response_id,
        conversation_id=conversation_id,
        awaiting_input=_awaiting_input(payload),
        status=payload.get("status"),
    )
