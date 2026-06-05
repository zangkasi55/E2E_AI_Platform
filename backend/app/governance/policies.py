from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..config import settings
from .agent_bindings import agent_bindings


def _load_policy_json(file_name: str) -> dict[str, Any]:
    repo_dir = Path(__file__).resolve().parents[3]
    path = (repo_dir / "data" / "policies" / file_name).resolve()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def component_wiring() -> list[dict[str, Any]]:
    return [
        {
            "component": "Entra ID",
            "configured": bool(settings.azure_tenant_id and settings.entra_ui_client_id),
            "details": {
                "tenant_id": settings.azure_tenant_id,
                "ui_client_id": settings.entra_ui_client_id,
                "tool_bridge_client_id": settings.entra_tool_bridge_client_id,
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
        "data_policy": _load_policy_json("data_policy.json"),
        "security_policy": _load_policy_json("security_policy.json"),
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
