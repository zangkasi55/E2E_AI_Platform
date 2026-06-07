"""Per-agent governance bindings — the nine-pillar platform wiring.

Every agent in the topology (UC1 ``memo_orchestrator`` + four sub-agents, and
UC2 ``banking_controller``) is explicitly bound to **all nine** platform
governance / observability pillars so the wiring is auditable per-agent rather
than only at the platform level:

  EntraID · APIM · Guardrail · Agent workflow · AI Foundry · DSPM · Purview ·
  Application Insights · Foundry Observability

The first four "data/security" pillars below describe classification and policy;
the remaining ones (APIM, AI Foundry, Agent workflow, App Insights, Foundry
Observability) are resolved from live settings + telemetry wiring so every agent
declares the full nine-pillar binding:

* **Entra ID** — the workload identity / least-privilege app-role the agent runs
  under (see :mod:`app.identity`). Maps to a managed identity + RBAC created by
  ``infra/modules/identity.bicep``.
* **Purview** — the data-governance collection and the data *classifications*
  the agent is permitted to touch (PII, financial, credit-bureau, …). Backed by
  ``infra/modules/purview.bicep``.
* **DSPM** — Data Security Posture Management (the *new* DSPM, not the legacy
  threat-protection-only signal): Microsoft Defender CSPM with Sensitive Data
  Discovery (``infra/modules/defender.bicep`` — ``CloudPosture`` Standard) plus
  Microsoft Purview *DSPM for AI* posture. Records the sensitivity tier
  monitored for the agent's prompts/responses. The Defender *AI workloads* plan
  is reported for completeness but is threat-protection only.
* **Guardrail** — the Azure AI Foundry content-safety policy (Prompt Shields,
  protected-material, groundedness, harmful-content, PII handling) enforced on
  the agent's model deployment, plus the deterministic guardrails in
  ``orchestration/banking_controller.py``.

The :func:`governance_for` lookup is attached to every :class:`app.agents.base.Agent`
instance and surfaced through ``/api/governance/policies`` via
:func:`app.governance.policies.governance_payload`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..config import settings
from ..identity import identity_for


@dataclass(frozen=True)
class AgentGovernance:
    """The four-pillar governance binding for a single agent."""

    agent: str
    use_case: str
    # Entra ID — least-privilege app-role (resolved to an identity via identity.py)
    entra_app_role: str
    # Purview — collection + the data classifications this agent may access
    purview_collection: str
    data_classifications: tuple[str, ...]
    # DSPM — sensitivity tier monitored by the new DSPM (Defender CSPM Sensitive
    # Data Discovery + Purview DSPM for AI)
    dspm_sensitivity: str
    # Guardrail — the content-safety / policy controls enforced for this agent
    guardrail_controls: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        """Render the binding, resolving live config (identity, endpoints)."""
        ident = identity_for(self.agent)
        return {
            "agent": self.agent,
            "use_case": self.use_case,
            "entra": {
                "configured": bool(ident.client_id or settings.azure_tenant_id),
                "identity": ident.agent,
                "app_role": self.entra_app_role,
                "client_id": ident.client_id or "",
                "tenant_id": settings.azure_tenant_id,
            },
            "purview": {
                "configured": bool(
                    settings.purview_catalog_endpoint or settings.purview_studio_url
                ),
                "collection": self.purview_collection,
                "classifications": list(self.data_classifications),
                "catalog_endpoint": settings.purview_catalog_endpoint,
            },
            "dspm": {
                # NEW DSPM posture plane: Defender CSPM (Sensitive Data
                # Discovery) + Microsoft Purview DSPM for AI. The legacy
                # Defender "AI workloads" plan is threat-protection only and is
                # reported below but no longer gates the DSPM binding.
                "configured": (
                    settings.defender_cspm_dspm_enabled
                    or settings.dspm_for_ai_enabled
                ),
                "generation": "new",
                "defender_cspm_dspm": settings.defender_cspm_dspm_enabled,
                "sensitive_data_discovery": settings.dspm_sensitive_data_discovery_enabled,
                "purview_dspm_for_ai": settings.dspm_for_ai_enabled,
                "defender_ai_workloads_plan": settings.defender_ai_plan_enabled,
                "sensitivity": self.dspm_sensitivity,
                "monitored": (
                    settings.defender_cspm_dspm_enabled
                    or settings.dspm_sensitive_data_discovery_enabled
                    or settings.dspm_for_ai_enabled
                ),
            },
            "guardrail": {
                "configured": bool(
                    settings.foundry_guardrail_policy_id
                    or settings.foundry_guardrail_policy_name
                ),
                "provider": settings.foundry_guardrail_provider,
                "policy_id": settings.foundry_guardrail_policy_id,
                "policy_name": settings.foundry_guardrail_policy_name,
                "mode": settings.foundry_guardrail_mode,
                "controls": list(self.guardrail_controls),
            },
            # ---- APIM — deterministic tool boundary for this agent ----------
            "apim": {
                "configured": bool(settings.apim_base_url),
                "base_url": settings.apim_base_url,
                "token_scope": settings.apim_token_scope
                or (
                    f"api://{settings.entra_tool_bridge_client_id}/.default"
                    if settings.entra_tool_bridge_client_id
                    else ""
                ),
                "subscription_key_configured": bool(settings.apim_subscription_key),
                "tool_bridge_client_id": settings.entra_tool_bridge_client_id,
                "note": "Agent tool calls are brokered through APIM with an Entra tool-bridge token.",
            },
            # ---- AI Foundry — model deployment / agent backing this agent ---
            "ai_foundry": {
                "configured": bool(
                    settings.azure_openai_endpoint or settings.foundry_project_endpoint
                ),
                "openai_endpoint": settings.azure_openai_endpoint,
                "project_endpoint": settings.foundry_project_endpoint,
                "project_name": settings.foundry_project_name,
                "agent_id": settings.foundry_agent_ids.get(self.agent, ""),
                "deployments": [
                    settings.azure_openai_deployment_gpt4o,
                    settings.azure_openai_deployment_gpt4o_mini,
                ],
                "guardrail_policy": settings.foundry_guardrail_policy_name,
                "mode": "foundry-agent"
                if (settings.use_foundry_agents and settings.foundry_agent_ids.get(self.agent))
                else "model-direct",
            },
            # ---- Agent workflow — orchestration topology membership ---------
            "agent_workflow": {
                "configured": True,
                "use_case": self.use_case,
                "role": self.entra_app_role,
                "orchestrated": True,
                "foundry_workflow_agents": settings.use_foundry_agents,
                "note": "Agent participates in the orchestrated agent graph "
                "(Semantic Kernel orchestrator / Foundry workflow agents).",
            },
            # ---- Application Insights — per-agent token + span telemetry -----
            "app_insights": {
                "configured": bool(settings.applicationinsights_connection_string),
                "metric": "gen_ai.token.usage",
                "dimensions": [
                    "agent",
                    "agent.id",
                    "agent.identity.client_id",
                    "use_case",
                    "run_id",
                ],
                "note": "Per-agent token usage + gen_ai spans exported to Application Insights.",
            },
            # ---- Foundry Observability — gen_ai spans in the project view ----
            "foundry_observability": {
                "configured": bool(
                    settings.applicationinsights_connection_string
                    and (
                        settings.foundry_project_endpoint
                        or settings.azure_openai_endpoint
                    )
                ),
                "tracing": "gen_ai.* semantic-convention spans",
                "view": "Foundry project Tracing / Observability",
                "operation": "invoke_agent" if settings.use_foundry_agents else "chat",
                "note": "gen_ai spans surface per-agent token usage natively in the Foundry portal.",
            },
        }


# ---------------------------------------------------------------------------
# Canonical per-agent bindings. Classifications mirror the synthetic-data
# sensitivity model used by Purview classification (applicant PII, national-id
# sensitive PII, account numbers, financial figures, credit-bureau data).
# ---------------------------------------------------------------------------
_CREDIT_MEMO = "credit_memo"
_BANKING = "banking"

AGENT_GOVERNANCE: dict[str, AgentGovernance] = {
    # ---- UC1: Credit Memo Drafting -------------------------------------
    "memo_orchestrator": AgentGovernance(
        agent="memo_orchestrator",
        use_case=_CREDIT_MEMO,
        entra_app_role="orchestrator",
        purview_collection=settings.purview_collection,
        data_classifications=("PII", "Financial", "Credit-Bureau"),
        dspm_sensitivity="high",
        guardrail_controls=(
            "Prompt Shields (jailbreak)",
            "Protected material",
            "Groundedness detection",
            "PII redaction",
        ),
    ),
    "doc_retrieval": AgentGovernance(
        agent="doc_retrieval",
        use_case=_CREDIT_MEMO,
        entra_app_role="reader.search",
        purview_collection=settings.purview_collection,
        data_classifications=("PII", "Document"),
        dspm_sensitivity="medium",
        guardrail_controls=(
            "Prompt Shields (jailbreak)",
            "Protected material",
            "Groundedness detection",
        ),
    ),
    "financial_ratio": AgentGovernance(
        agent="financial_ratio",
        use_case=_CREDIT_MEMO,
        entra_app_role="reader.financials",
        purview_collection=settings.purview_collection,
        data_classifications=("Financial",),
        dspm_sensitivity="medium",
        guardrail_controls=(
            "Prompt Shields (jailbreak)",
            "Groundedness detection",
        ),
    ),
    "bureau_summary": AgentGovernance(
        agent="bureau_summary",
        use_case=_CREDIT_MEMO,
        entra_app_role="reader.bureau",
        purview_collection=settings.purview_collection,
        data_classifications=("Credit-Bureau", "Sensitive-PII"),
        dspm_sensitivity="high",
        guardrail_controls=(
            "Prompt Shields (jailbreak)",
            "PII redaction",
            "Groundedness detection",
        ),
    ),
    "memo_assembler": AgentGovernance(
        agent="memo_assembler",
        use_case=_CREDIT_MEMO,
        entra_app_role="writer.memo",
        purview_collection=settings.purview_collection,
        data_classifications=("PII", "Financial", "Credit-Bureau"),
        dspm_sensitivity="high",
        guardrail_controls=(
            "Prompt Shields (jailbreak)",
            "Protected material",
            "Groundedness detection",
            "Harmful content filter",
        ),
    ),
    # ---- UC2: Conversational Banking Control ---------------------------
    "banking_controller": AgentGovernance(
        agent="banking_controller",
        use_case=_BANKING,
        entra_app_role="controller.banking",
        purview_collection=settings.purview_collection,
        data_classifications=("PII", "Account", "Financial"),
        dspm_sensitivity="high",
        guardrail_controls=(
            "Prompt Shields (jailbreak)",
            "Policy-override / OTP-bypass detection",
            "Harmful content filter",
            "No-money-movement enforcement",
        ),
    ),
}


def governance_for(agent: str) -> AgentGovernance:
    """Return the four-pillar binding for an agent (defaults to orchestrator)."""
    return AGENT_GOVERNANCE.get(
        agent,
        AgentGovernance(
            agent=agent,
            use_case=_CREDIT_MEMO,
            entra_app_role="orchestrator",
            purview_collection=settings.purview_collection,
            data_classifications=("PII",),
            dspm_sensitivity="medium",
            guardrail_controls=("Prompt Shields (jailbreak)",),
        ),
    )


def agent_bindings() -> list[dict[str, Any]]:
    """All per-agent governance bindings, ordered UC1 then UC2."""
    return [AGENT_GOVERNANCE[name].as_dict() for name in AGENT_GOVERNANCE]
