"""AuditStore — persists run / step / handoff records.

Writes to Cosmos containers ``runs``, ``steps``, ``handoffs`` (db ``agentaudit``)
and supports query-by-run_id. In MOCK_MODE everything is held in memory so the
demo works without Azure, while keeping the exact same call sites the live mode
will use.
"""
from __future__ import annotations

import threading
from typing import Optional

from ..config import settings
from ..models import HandoffObject, RunState, StepTrace
from .otel import emit_agent_activity


class AuditStore:
    """Run/step/handoff persistence with an in-memory mock implementation."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runs: dict[str, RunState] = {}
        self._steps: dict[str, list[StepTrace]] = {}
        self._handoffs: dict[str, HandoffObject] = {}
        self._cosmos = None  # lazily created (db client) in live mode

    # -- runs ---------------------------------------------------------------
    def save_run(self, run: RunState) -> RunState:
        run.touch()
        with self._lock:
            self._runs[run.run_id] = run
        self._upsert("runs", run.model_dump(), pk=run.run_id)
        emit_agent_activity(
            event="run_state",
            run_id=run.run_id,
            agent="memo_orchestrator" if run.use_case.value == "credit_memo" else "banking_controller",
            action="save_run",
            status=str(run.status),
        )
        return run

    def get_run(self, run_id: str) -> Optional[RunState]:
        with self._lock:
            return self._runs.get(run_id)

    def list_runs(self) -> list[RunState]:
        with self._lock:
            return list(self._runs.values())

    # -- steps --------------------------------------------------------------
    def append_step(self, step: StepTrace) -> StepTrace:
        with self._lock:
            self._steps.setdefault(step.run_id, []).append(step)
        self._upsert("steps", step.model_dump(), pk=step.run_id)
        emit_agent_activity(
            event="step_trace",
            run_id=step.run_id,
            agent=step.agent,
            action=step.action,
            status=step.status.value,
            step=step.step,
        )
        return step

    def steps_for_run(self, run_id: str) -> list[StepTrace]:
        with self._lock:
            return list(self._steps.get(run_id, []))

    # -- handoffs -----------------------------------------------------------
    def save_handoff(self, handoff: HandoffObject) -> HandoffObject:
        with self._lock:
            self._handoffs[handoff.handoff_id] = handoff
        self._upsert("handoffs", handoff.model_dump(), pk=handoff.run_id)
        emit_agent_activity(
            event="handoff",
            run_id=handoff.run_id,
            agent="banking_controller",
            action="request_transaction_handoff",
            status=handoff.status,
        )
        return handoff

    def get_handoff(self, handoff_id: str) -> Optional[HandoffObject]:
        with self._lock:
            return self._handoffs.get(handoff_id)

    def handoffs_for_run(self, run_id: str) -> list[HandoffObject]:
        with self._lock:
            return [h for h in self._handoffs.values() if h.run_id == run_id]

    # -- cosmos plumbing ----------------------------------------------------
    def _container_name(self, logical: str) -> str:
        return {
            "runs": settings.cosmos_container_runs,
            "steps": settings.cosmos_container_steps,
            "handoffs": settings.cosmos_container_handoffs,
        }[logical]

    def _upsert(self, logical: str, item: dict, *, pk: str) -> None:
        """Best-effort Cosmos upsert; writes whenever a real run is active.

        Gated on ``live_active`` (real model/agent execution) rather than on
        ``mock_mode`` so that genuine runs persist to the real Cosmos
        ``agentaudit`` containers even while synthetic *tools* stay offline.
        """
        if not settings.live_active:
            return
        try:
            db = self._get_cosmos_db()
            container = db.get_container_client(self._container_name(logical))
            container.upsert_item(item)
        except Exception:  # pragma: no cover - PoC best effort
            # TODO(copilot): add retry + dead-letter; surface to App Insights.
            pass

    def _get_cosmos_db(self):
        if self._cosmos is not None:
            return self._cosmos
        from azure.cosmos import CosmosClient  # type: ignore

        from ..identity import get_credential

        client = CosmosClient(settings.cosmos_endpoint, credential=get_credential())
        self._cosmos = client.get_database_client(settings.cosmos_database)
        return self._cosmos


# Shared singleton.
audit_store = AuditStore()
