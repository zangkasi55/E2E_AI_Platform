"""TokenMeter — per-call token accounting and cost estimation.

Responsibilities (POC_SPEC.md §Token monitoring):
  1. Wrap each model call and compute prompt/completion/total tokens.
  2. Estimate USD cost from a small price table (gpt-4o, gpt-4o-mini).
  3. Write the canonical :class:`TokenRecord` to Cosmos ``tokens`` container.
  4. Emit App Insights custom metric ``gen_ai.token.usage``.
  5. Provide aggregation helpers for the /api/tokens/* endpoints.

In MOCK_MODE token counts are estimated with a ``len(text)//4`` heuristic and
nothing is written to Azure (records are kept in an in-memory list so the
demo UI still works).
"""
from __future__ import annotations

import threading
from typing import Any, Iterable, Optional

from ..config import settings
from ..models import TokenRecord, TokenSummary

# ---------------------------------------------------------------------------
# Price table — USD per 1K tokens (PoC estimates; update from Azure pricing).
# TODO(copilot): Move to config / Key Vault and refresh from the Azure retail
# prices API for the southeastasia region.
# ---------------------------------------------------------------------------
PRICE_TABLE_USD_PER_1K: dict[str, dict[str, float]] = {
    "gpt-4o": {"prompt": 0.0050, "completion": 0.0150},
    "gpt-4o-mini": {"prompt": 0.00015, "completion": 0.00060},
}


def estimate_tokens(text: str) -> int:
    """Cheap tokenizer heuristic used in MOCK_MODE (~4 chars/token)."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def estimate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Compute estimated USD cost for a call from the price table."""
    price = PRICE_TABLE_USD_PER_1K.get(model)
    if price is None:
        # Unknown model — fall back to gpt-4o pricing but do not crash.
        price = PRICE_TABLE_USD_PER_1K["gpt-4o"]
    cost = (prompt_tokens / 1000.0) * price["prompt"] + (
        completion_tokens / 1000.0
    ) * price["completion"]
    return round(cost, 6)


class TokenMeter:
    """Records token usage and exposes aggregation queries.

    A single instance is created in ``main.py`` and shared across orchestrators.
    Thread-safe for the simple append/read patterns used here.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # In-memory mirror of token records (always populated; the source of
        # truth for the demo UI in mock mode).
        self._records: list[TokenRecord] = []
        self._cosmos_container = None  # lazily created in live mode

    # -- recording ----------------------------------------------------------
    def record(
        self,
        *,
        run_id: str,
        agent: str,
        step: int,
        model: str,
        use_case: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> TokenRecord:
        """Build, persist, and emit a single :class:`TokenRecord`."""
        total = prompt_tokens + completion_tokens
        rec = TokenRecord(
            run_id=run_id,
            agent=agent,
            step=step,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total,
            est_cost_usd=estimate_cost_usd(model, prompt_tokens, completion_tokens),
            use_case=use_case,
        )
        with self._lock:
            self._records.append(rec)

        if not settings.mock_mode:
            self._write_cosmos(rec)
        self._emit_metric(rec)
        return rec

    def meter_call(
        self,
        *,
        run_id: str,
        agent: str,
        step: int,
        model: str,
        use_case: str,
        prompt_text: str,
        completion_text: str,
        usage: Optional[dict[str, int]] = None,
    ) -> TokenRecord:
        """Convenience wrapper around :meth:`record`.

        If the model SDK returns a ``usage`` dict (live mode), use it; otherwise
        estimate from text (mock mode).
        """
        if usage:
            prompt_tokens = int(usage.get("prompt_tokens", 0))
            completion_tokens = int(usage.get("completion_tokens", 0))
        else:
            prompt_tokens = estimate_tokens(prompt_text)
            completion_tokens = estimate_tokens(completion_text)
        return self.record(
            run_id=run_id,
            agent=agent,
            step=step,
            model=model,
            use_case=use_case,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    # -- persistence / emission --------------------------------------------
    def _write_cosmos(self, rec: TokenRecord) -> None:
        """Write a token record to Cosmos ``tokens`` (partition key = run_id)."""
        try:
            container = self._get_cosmos_container()
            if container is not None:
                container.upsert_item(rec.model_dump())
        except Exception:  # pragma: no cover - best effort in PoC
            # TODO(copilot): add retry/backoff + DLQ. Never let telemetry break a run.
            pass

    def _get_cosmos_container(self):
        if self._cosmos_container is not None:
            return self._cosmos_container
        if settings.mock_mode:
            return None
        # Lazy import so the module compiles without azure-cosmos installed.
        from azure.cosmos import CosmosClient  # type: ignore

        from ..identity import get_credential

        client = CosmosClient(settings.cosmos_endpoint, credential=get_credential())
        db = client.get_database_client(settings.cosmos_database)
        self._cosmos_container = db.get_container_client(settings.cosmos_container_tokens)
        return self._cosmos_container

    def _emit_metric(self, rec: TokenRecord) -> None:
        """Emit App Insights custom metric ``gen_ai.token.usage``.

        Uses OpenTelemetry metrics when configured; no-op when no live path is
        active (``live_active``).
        """
        if not settings.live_active:
            return
        try:
            from .otel import record_token_metric

            record_token_metric(rec)
        except Exception:  # pragma: no cover
            pass

    # -- aggregation (for /api/tokens/*) -----------------------------------
    def all_records(self) -> list[TokenRecord]:
        with self._lock:
            return list(self._records)

    def records_for_run(self, run_id: str) -> list[TokenRecord]:
        with self._lock:
            return [r for r in self._records if r.run_id == run_id]

    def summarize(self, records: Optional[Iterable[TokenRecord]] = None) -> TokenSummary:
        """Aggregate records by agent, model, run + cumulative cost."""
        recs = list(records) if records is not None else self.all_records()
        summary = TokenSummary()
        for r in recs:
            summary.total_tokens += r.total_tokens
            summary.total_prompt_tokens += r.prompt_tokens
            summary.total_completion_tokens += r.completion_tokens
            summary.est_cost_usd += r.est_cost_usd
            summary.by_agent[r.agent] = summary.by_agent.get(r.agent, 0) + r.total_tokens
            summary.by_model[r.model] = summary.by_model.get(r.model, 0) + r.total_tokens
            summary.by_run[r.run_id] = summary.by_run.get(r.run_id, 0) + r.total_tokens
        summary.record_count = len(recs)
        summary.est_cost_usd = round(summary.est_cost_usd, 6)
        return summary

    def summarize_run(self, run_id: str) -> TokenSummary:
        return self.summarize(self.records_for_run(run_id))


# Shared singleton (imported by orchestrators + main).
token_meter = TokenMeter()
