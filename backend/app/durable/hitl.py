"""Human-in-the-loop (HITL) pause / resume abstraction (UC1).

In the live system the credit-memo orchestration pauses on a **Durable Functions**
orchestration that waits for an external event, and approvals are delivered via a
**Service Bus** queue ``hitl-approvals`` (from a Teams reviewer action). This module
abstracts that so the FastAPI orchestrator can:

  * ``pause_for_approval(run_id, draft)`` — enqueue an approval request and mark
    the run AWAITING_APPROVAL,
  * ``resume(run_id, decision)`` — apply the human decision and continue.

In MOCK_MODE the "queue" is an in-process dict, so the demo's approve endpoint
works end-to-end without Azure.

TODO(copilot): Replace the in-memory queue with:
  * a Durable Functions orchestrator using ``context.wait_for_external_event``,
  * a Service Bus sender that posts the approval card to ``hitl-approvals``,
  * a Service Bus-triggered Function that calls back into the orchestrator on
    approve/reject. The HITLGateway interface below should stay stable.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Optional

from ..config import settings
from ..models import ApprovalDecision


@dataclass
class PendingApproval:
    """An approval request awaiting a human decision."""

    run_id: str
    draft: dict[str, Any]
    reviewer_channel: str = "teams"
    decision: Optional[ApprovalDecision] = None
    metadata: dict[str, Any] = field(default_factory=dict)


class HITLGateway:
    """Pause/resume gateway. Mock implementation backed by an in-memory dict."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: dict[str, PendingApproval] = {}

    def pause_for_approval(
        self,
        run_id: str,
        draft: dict[str, Any],
        *,
        reviewer_channel: str = "teams",
    ) -> PendingApproval:
        """Register an approval request (enqueue) and return the pending record."""
        pending = PendingApproval(run_id=run_id, draft=draft, reviewer_channel=reviewer_channel)
        with self._lock:
            self._pending[run_id] = pending
        self._enqueue_servicebus(pending)
        return pending

    def is_pending(self, run_id: str) -> bool:
        with self._lock:
            return run_id in self._pending and self._pending[run_id].decision is None

    def resume(self, run_id: str, decision: ApprovalDecision) -> PendingApproval:
        """Apply a human decision to a paused run.

        Raises ``KeyError`` if there is no pending approval for ``run_id``.
        """
        with self._lock:
            pending = self._pending[run_id]
            pending.decision = decision
        return pending

    def get(self, run_id: str) -> Optional[PendingApproval]:
        with self._lock:
            return self._pending.get(run_id)

    # -- live plumbing ------------------------------------------------------
    def _enqueue_servicebus(self, pending: PendingApproval) -> None:
        """Send the approval request to Service Bus queue ``hitl-approvals``.

        No-op in mock mode.
        """
        if settings.mock_mode:
            return
        try:  # pragma: no cover - requires Azure
            from azure.servicebus import ServiceBusClient, ServiceBusMessage  # type: ignore

            from ..identity import get_credential

            client = ServiceBusClient(
                fully_qualified_namespace=settings.servicebus_namespace,
                credential=get_credential(),
            )
            with client, client.get_queue_sender(settings.servicebus_hitl_queue) as sender:
                import json

                sender.send_messages(
                    ServiceBusMessage(
                        json.dumps({"run_id": pending.run_id, "draft": pending.draft}),
                        subject="credit-memo-approval",
                    )
                )
        except Exception:
            # TODO(copilot): surface failures to App Insights; do not lose the run.
            pass


# Shared singleton.
hitl_gateway = HITLGateway()
