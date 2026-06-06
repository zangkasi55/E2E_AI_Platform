from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..config import settings
from .agent_bindings import agent_bindings


_DEFAULT_DATA_POLICY: dict[str, Any] = {
    "policy_id": "dp-purview-credit-memo-001",
    "name": "Credit Memo Data Governance Policy",
    "owner": "Data Governance Office",
    "platform": "Microsoft Purview",
    "scope": ["credit_memo", "banking"],
    "controls": [
        {
            "id": "DP-01",
            "title": "Classify sensitive financial and customer attributes",
            "requirement": "All applicant and customer records are classified with Purview labels before retrieval.",
            "purview_capability": "Auto classification + glossary term mapping",
        },
        {
            "id": "DP-02",
            "title": "Lineage and source grounding",
            "requirement": "Each memo statement must map to an approved source document and lineage entry.",
            "purview_capability": "Lineage graph + catalog metadata",
        },
        {
            "id": "DP-03",
            "title": "Retention and auditability",
            "requirement": "Run traces and policy decisions must be retained for 365 days.",
            "purview_capability": "Data estate governance and retention oversight",
        },
    ],
}

_DEFAULT_SECURITY_POLICY: dict[str, Any] = {
    "policy_id": "sp-entra-apim-agent-001",
    "name": "Agent Tool Access Security Policy",
    "owner": "Security Architecture",
    "platform": "Microsoft Entra ID + Azure API Management",
    "scope": ["orchestrator", "tool_bridge", "ui"],
    "controls": [
        {
            "id": "SP-01",
            "title": "Token-based access control",
            "requirement": "All tool calls require Entra-issued JWT tokens validated by APIM.",
            "entra_capability": "App registrations, OAuth2 scopes, managed identity",
        },
        {
            "id": "SP-02",
            "title": "Least-privilege role assignments",
            "requirement": "Each workload identity receives only the minimum role per component.",
            "entra_capability": "RBAC role assignment + workload identity separation",
        },
        {
            "id": "SP-03",
            "title": "Deterministic policy boundary",
            "requirement": "APIM policy enforces scope checks, rate limits, and request logging for tool invocations.",
            "entra_capability": "Scope claims and audience validation",
        },
    ],
}


def _normalize_policy(policy: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    """Ensure policy payload always has required UI fields."""
    merged = {**fallback, **(policy or {})}
    merged["scope"] = merged.get("scope") or fallback["scope"]
    merged["controls"] = merged.get("controls") or fallback["controls"]
    return merged


def _load_policy_json(file_name: str, fallback: dict[str, Any]) -> dict[str, Any]:
    # Uses configured DATA_DIR so this works both locally and in containers.
    path = (Path(settings.data_path) / "policies" / file_name).resolve()
    if not path.exists():
        return fallback
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return _normalize_policy(raw, fallback)
        return fallback
    except Exception:
        return fallback


def component_wiring() -> list[dict[str, Any]]:
    return [
        {
            "component": "Entra ID",
            # The platform's Entra wiring is the orchestrator workload identity
            # (UAMI). There is no separate UI SPA app registration in this PoC,
            # so wiring is satisfied by tenant + any agent/tool/UI client id.
            "configured": bool(
                settings.azure_tenant_id
                and (
                    settings.entra_orchestrator_client_id
                    or settings.entra_tool_bridge_client_id
                    or settings.entra_ui_client_id
                )
            ),
            "details": {
                "tenant_id": settings.azure_tenant_id,
                "orchestrator_client_id": settings.entra_orchestrator_client_id,
                "tool_bridge_client_id": settings.entra_tool_bridge_client_id,
                "ui_client_id": settings.entra_ui_client_id,
            },
        },
        {
            "component": "APIM",
            "configured": bool(settings.apim_base_url),
            "details": {"base_url": settings.apim_base_url},
        },
        {
            "component": "Purview",
            "configured": bool(settings.purview_catalog_endpoint or settings.purview_studio_url),
            "details": {
                "catalog_endpoint": settings.purview_catalog_endpoint,
                "studio_url": settings.purview_studio_url,
                "collection": settings.purview_collection,
            },
        },
        {
            "component": "Defender / DSPM for AI",
            "configured": bool(settings.defender_ai_plan_enabled or settings.dspm_for_ai_enabled),
            "details": {
                "defender_ai_workloads_plan": settings.defender_ai_plan_enabled,
                "purview_dspm_for_ai": settings.dspm_for_ai_enabled,
            },
        },
        {
            "component": "Cosmos",
            "configured": bool(settings.cosmos_endpoint and settings.cosmos_database),
            "details": {
                "endpoint": settings.cosmos_endpoint,
                "database": settings.cosmos_database,
                "runs_container": settings.cosmos_container_runs,
                "steps_container": settings.cosmos_container_steps,
                "tokens_container": settings.cosmos_container_tokens,
            },
        },
    ]


def governance_payload() -> dict[str, Any]:
    return {
        "data_policy": _load_policy_json("data_policy.json", _DEFAULT_DATA_POLICY),
        "security_policy": _load_policy_json("security_policy.json", _DEFAULT_SECURITY_POLICY),
        "guardrail_policy": {
            "provider": settings.foundry_guardrail_provider,
            "policy_id": settings.foundry_guardrail_policy_id,
            "policy_name": settings.foundry_guardrail_policy_name,
            "mode": settings.foundry_guardrail_mode,
            "configured": bool(settings.foundry_guardrail_policy_id or settings.foundry_guardrail_policy_name),
        },
        "component_wiring": component_wiring(),
        "agent_bindings": agent_bindings(),
    }
