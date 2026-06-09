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
        import os

        # Stamp a stable service name so Application Insights records a
        # ``cloud_RoleName`` the Foundry portal can filter by (otherwise spans
        # arrive as "unknown_service" and are hard to attribute to this app).
        os.environ.setdefault("OTEL_SERVICE_NAME", "agpoc-aca-orch-dev")

        from azure.monitor.opentelemetry import configure_azure_monitor  # type: ignore
        from opentelemetry import metrics, trace  # type: ignore

        configure_azure_monitor(
            connection_string=settings.applicationinsights_connection_string,
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
# Foundry's project Tracing / Observability view (and each agent's Traces tab)
# is span-based and only recognizes spans that follow the documented
# ``gen_ai.*`` semantic conventions:
#   * span ``kind`` MUST be CLIENT (INTERNAL spans are not surfaced as GenAI
#     operations in the portal),
#   * ``gen_ai.system`` MUST be a recognized provider id — ``az.ai.agents`` for
#     Foundry Agent Service ``invoke_agent`` calls, ``az.ai.openai`` for direct
#     Azure OpenAI ``chat`` calls (the previous custom ``az.ai.foundry`` value
#     was ignored, so no agent showed any traces),
#   * the span name MUST be ``<operation> <agent-or-model>``,
#   * per-agent correlation in the portal keys off ``gen_ai.agent.id`` — it must
#     carry the *Foundry* agent id (e.g. ``memo-orchestrator:3``), not the local
#     logical name, and must be present even in the mock demo path.
# These spans are fed into the Application Insights resource wired onto the
# project in foundry.bicep (the same resource the Container App exports to).
# ---------------------------------------------------------------------------
GEN_AI_SYSTEM_AGENTS = "az.ai.agents"
GEN_AI_SYSTEM_OPENAI = "az.ai.openai"


def _gen_ai_system_for(operation: str) -> str:
    """Map a GenAI operation name to its recognized ``gen_ai.system`` provider."""
    return GEN_AI_SYSTEM_AGENTS if operation == "invoke_agent" else GEN_AI_SYSTEM_OPENAI


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
    for direct model calls. The span is emitted as ``SpanKind.CLIENT`` with the
    documented ``gen_ai.*`` attributes so it surfaces natively in the Foundry
    portal Tracing view and the per-agent Traces tab. Returns a null context in
    mock mode (no exporter configured).
    """
    if _tracer is None:
        from contextlib import nullcontext

        return nullcontext()
    from opentelemetry.trace import SpanKind  # type: ignore

    resolved_agent_id = agent_id or agent
    server_address = ""
    try:  # endpoint host, for the GenAI ``server.address`` convention
        from urllib.parse import urlparse

        from ..config import settings as _settings

        raw_endpoint = (
            _settings.foundry_project_endpoint
            if operation == "invoke_agent"
            else _settings.azure_openai_endpoint
        )
        server_address = urlparse(raw_endpoint).netloc if raw_endpoint else ""
    except Exception:  # pragma: no cover - never break telemetry on parse
        server_address = ""
    return _tracer.start_as_current_span(
        f"{operation} {target}",
        kind=SpanKind.CLIENT,
        attributes={
            "gen_ai.system": _gen_ai_system_for(operation),
            "gen_ai.operation.name": operation,
            "gen_ai.request.model": model,
            "gen_ai.agent.id": resolved_agent_id,
            "gen_ai.agent.name": agent,
            "gen_ai.thread.id": run_id,
            "server.address": server_address,
            # Custom dimensions retained for the token-monitor / audit views.
            "agent.id": resolved_agent_id,
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
