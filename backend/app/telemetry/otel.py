"""OpenTelemetry + Azure Monitor (Application Insights) wiring.

Exports traces and the custom metric ``gen_ai.token.usage`` to App Insights
``agpoc-appi-dev``. All setup is a no-op in MOCK_MODE so the app runs offline.

TODO(copilot): For live deployment, set APPLICATIONINSIGHTS_CONNECTION_STRING
(from Key Vault) and call :func:`configure_telemetry` once at startup. Consider
enabling the OpenTelemetry FastAPI + httpx instrumentations for auto-tracing.
"""
from __future__ import annotations

from typing import Optional

from ..config import settings
from ..models import TokenRecord

# Module-level handles, created lazily in configure_telemetry().
_tracer = None
_meter = None
_token_usage_counter = None
_configured = False


def configure_telemetry() -> None:
    """Idempotently configure Azure Monitor + OTEL.

    Configures whenever an App Insights connection string is present — including
    the mock demo (``MOCK_MODE=true``). This means every run (mock, hybrid, or
    fully live) emits per-agent ``gen_ai`` spans + ``gen_ai.token.usage`` metrics
    into Application Insights and the Foundry project's connected Tracing view,
    so App Insights and Foundry Observability are demonstrably wired for all
    agents and not gated behind a live LLM path. When no connection string is
    configured the setup is a silent no-op so the app still runs offline.
    """
    global _configured, _tracer, _meter, _token_usage_counter
    if _configured:
        return
    if not settings.applicationinsights_connection_string:
        # Nothing to export to; stay silent rather than crash the PoC.
        _configured = True
        return

    # Lazy imports so the module compiles without the SDK installed. Wrapped so
    # a telemetry-setup failure degrades to a no-op instead of crashing startup
    # (this path now runs in the production mock demo, not only in live mode).
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor  # type: ignore
        from opentelemetry import metrics, trace  # type: ignore

        configure_azure_monitor(
            connection_string=settings.applicationinsights_connection_string,
            # TODO(copilot): set service.name resource attr to "agpoc-aca-orch-dev".
        )
        _tracer = trace.get_tracer("agpoc.orchestrator")
        _meter = metrics.get_meter("agpoc.orchestrator")
        # Canonical custom metric name.
        _token_usage_counter = _meter.create_counter(
            name="gen_ai.token.usage",
            unit="token",
            description="Generative-AI token usage per model call",
        )
    except Exception:  # pragma: no cover - telemetry must never break the app
        _tracer = None
        _meter = None
        _token_usage_counter = None
    _configured = True


def get_tracer():
    """Return the configured tracer (or None in mock mode)."""
    return _tracer


def record_token_metric(rec: TokenRecord) -> None:
    """Emit one ``gen_ai.token.usage`` data point with canonical dimensions."""
    if _token_usage_counter is None:
        return
    foundry_agent_id = settings.foundry_agent_ids.get(rec.agent)
    from ..identity import identity_for

    identity = identity_for(rec.agent)
    _token_usage_counter.add(
        rec.total_tokens,
        attributes={
            "gen_ai.response.model": rec.model,
            "agent": rec.agent,
            "agent.id": foundry_agent_id or rec.agent,
            "agent.identity.client_id": identity.client_id or "",
            "agent.identity.role": identity.app_role,
            "use_case": rec.use_case,
            "run_id": rec.run_id,
        },
    )


def start_span(name: str, attributes: Optional[dict] = None):
    """Context-manager span helper; returns a null context in mock mode."""
    if _tracer is None:
        from contextlib import nullcontext

        return nullcontext()
    return _tracer.start_as_current_span(name, attributes=attributes or {})


# ---------------------------------------------------------------------------
# Foundry-native GenAI telemetry (OpenTelemetry GenAI semantic conventions).
#
# Foundry's project Tracing / Observability view is span-based and recognizes
# spans that follow the ``gen_ai.*`` semantic conventions. Wrapping every model
# / agent call in a ``gen_ai`` span (with ``gen_ai.usage.*`` token attributes)
# makes per-call token usage show up natively in the Foundry portal — fed by the
# Application Insights connection wired onto the project in foundry.bicep.
# ---------------------------------------------------------------------------
GEN_AI_SYSTEM = "az.ai.foundry"


def start_gen_ai_span(
    *,
    operation: str,
    target: str,
    agent: str,
    model: str,
    use_case: str,
    run_id: str,
    agent_id: Optional[str] = None,
    identity_client_id: Optional[str] = None,
    identity_role: Optional[str] = None,
):
    """Start a GenAI-convention span (``<operation> <target>``) for one call.

    ``operation`` is ``invoke_agent`` for Foundry Agent Service calls or ``chat``
    for direct model calls. Returns a null context in mock mode.
    """
    if _tracer is None:
        from contextlib import nullcontext

        return nullcontext()
    return _tracer.start_as_current_span(
        f"{operation} {target}",
        attributes={
            "gen_ai.system": GEN_AI_SYSTEM,
            "gen_ai.operation.name": operation,
            "gen_ai.request.model": model,
            "gen_ai.agent.name": agent,
            "agent.id": agent_id or agent,
            "agent.identity.client_id": identity_client_id or "",
            "agent.identity.role": identity_role or "",
            "use_case": use_case,
            "run_id": run_id,
        },
    )


def set_gen_ai_usage(prompt_tokens: int, completion_tokens: int) -> None:
    """Annotate the current span with GenAI token-usage attributes."""
    if _tracer is None:
        return
    from opentelemetry import trace  # type: ignore

    span = trace.get_current_span()
    if span is None:
        return
    span.set_attribute("gen_ai.usage.input_tokens", prompt_tokens)
    span.set_attribute("gen_ai.usage.output_tokens", completion_tokens)
    span.set_attribute("gen_ai.usage.total_tokens", prompt_tokens + completion_tokens)


def emit_agent_activity(
    *,
    event: str,
    run_id: str,
    agent: str,
    action: str,
    status: str,
    step: Optional[int] = None,
) -> None:
    """Emit a lightweight activity span for orchestration/tool lifecycle events."""
    foundry_agent_id = settings.foundry_agent_ids.get(agent)
    from ..identity import identity_for

    identity = identity_for(agent)
    attrs = {
        "event": event,
        "run_id": run_id,
        "agent": agent,
        "agent.id": foundry_agent_id or agent,
        "agent.identity.client_id": identity.client_id or "",
        "agent.identity.role": identity.app_role,
        "action": action,
        "status": status,
    }
    if step is not None:
        attrs["step"] = step
    with start_span(f"agent.activity.{event}", attributes=attrs):
        return
