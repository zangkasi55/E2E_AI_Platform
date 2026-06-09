"""Application configuration.

Pydantic ``Settings`` loaded from environment / ``.env``. All canonical Azure
resource names from POC_SPEC.md are used as defaults so the app is runnable in
mock mode with zero configuration.

TODO(copilot): When wiring live Azure, set MOCK_MODE=false and populate the
secret-bearing fields (APIM key, Cosmos, App Insights, Entra) from Key Vault
``agpoc-kv-dev`` via the Container Apps managed identity rather than .env.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly-typed application settings.

    Field names map 1:1 to the keys in ``.env.example``.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- Run mode ----------------------------------------------------------
    mock_mode: bool = True
    # When ``live_llm`` is true the agent model calls hit the live Azure OpenAI
    # deployment even while ``mock_mode`` keeps the APIM-fronted tools synthetic.
    # This lets the PoC demonstrate live gpt-4o agent reasoning without requiring
    # the (cost-deferred) APIM + Functions tool backend to be provisioned.
    live_llm: bool = False
    # When true, agent steps are executed by the provisioned Foundry **prompt
    # agents** (Foundry Agent Service, responses protocol) instead of a direct
    # Azure OpenAI chat call. Requires ``foundry_project_endpoint`` and a
    # populated ``foundry_agent_ids.json``. Implies live model calls.
    use_foundry_agents: bool = False
    # When true, the run is orchestrated by the provisioned Foundry **workflow
    # agents** (``definition.kind = "workflow"``) instead of the in-process
    # Python agent loop. The workflow drives the child agents server-side
    # (including the credit-memo HITL ``Question`` node); Python still enforces
    # the deterministic guardrail / sensitivity pre-gates, the policy
    # post-gates, and owns the AWAITING_APPROVAL state machine.
    use_foundry_workflows: bool = False
    # Registered workflow-agent names (see provision_foundry_agents.WORKFLOWS).
    foundry_credit_memo_workflow: str = "credit-memo-workflow"
    foundry_banking_workflow: str = "banking-control-workflow"
    # When true, the UC2 banking reasoning runs server-side in the
    # banking-control **hosted** agent (backend/hosted_agents/banking-control,
    # ``kind = hosted``). Unlike workflow-kind agents, hosted agents ARE
    # invocable via the per-agent responses route, so this path actually
    # executes the banking reasoning graph inside Foundry. The deterministic
    # banking steps (guardrails, EKYC, policy gate, handoff) always stay in
    # Python — the "no money moves" guarantee is never delegated to the agent.
    use_banking_hosted_agent: bool = False
    foundry_banking_hosted_agent: str = "banking-control-hosted"
    environment: str = "dev"
    log_level: str = "INFO"

    # ---- Azure OpenAI (agpoc-aoai-dev) -------------------------------------
    azure_openai_endpoint: str = "https://agpoc-aoai-dev.openai.azure.com/"
    azure_openai_api_version: str = "2024-06-01"
    azure_openai_deployment_gpt4o: str = "gpt-4o"
    azure_openai_deployment_gpt4o_mini: str = "gpt-4o-mini"

    # ---- API Management (agpoc-apim-dev) -----------------------------------
    apim_base_url: str = "https://agpoc-apim-dev.azure-api.net/tools"
    apim_subscription_key: str = ""
    # Optional OAuth scope for APIM tool-bridge bearer token validation.
    # If omitted, registry derives ``api://{ENTRA_TOOL_BRIDGE_CLIENT_ID}/.default``.
    apim_token_scope: str = ""

    # ---- Azure AI Search (agpoc-search-dev) --------------------------------
    azure_search_endpoint: str = "https://agpoc-search-dev.search.windows.net"
    azure_search_index: str = "memo-corpus"

    # ---- Cosmos DB (agpoc-cosmos-dev) --------------------------------------
    cosmos_endpoint: str = "https://agpoc-cosmos-dev.documents.azure.com:443/"
    cosmos_database: str = "agentaudit"
    cosmos_container_runs: str = "runs"
    cosmos_container_steps: str = "steps"
    cosmos_container_handoffs: str = "handoffs"
    cosmos_container_tokens: str = "tokens"

    # ---- Application Insights (agpoc-appi-dev) -----------------------------
    applicationinsights_connection_string: str = ""

    # ---- Service Bus (agpoc-sb-dev) ----------------------------------------
    servicebus_namespace: str = "agpoc-sb-dev.servicebus.windows.net"
    servicebus_hitl_queue: str = "hitl-approvals"

    # ---- Entra ID workload identity ----------------------------------------
    # Canonical PoC tenant (ddcbdc96…) used as the default so the platform's
    # Entra wiring resolves even when AZURE_TENANT_ID is not injected as an env
    # var. Override per-environment via the AZURE_TENANT_ID env var.
    azure_tenant_id: str = os.getenv("AZURE_TENANT_ID", "ddcbdc96-6162-4d91-bb0d-066343049ce1")
    # Fallback to AZURE_CLIENT_ID so Container Apps UAMI works without a
    # duplicate ENTRA_ORCHESTRATOR_CLIENT_ID env var.
    entra_orchestrator_client_id: str = os.getenv("ENTRA_ORCHESTRATOR_CLIENT_ID", os.getenv("AZURE_CLIENT_ID", ""))
    entra_tool_bridge_client_id: str = ""
    entra_ui_client_id: str = ""
    # UC2 banking-control HOSTED agent (backend/hosted_agents/banking-control)
    # runs under its OWN user-assigned managed identity. Falls back to the
    # orchestrator/AZURE_CLIENT_ID so the governance binding resolves even
    # before a dedicated UAMI is provisioned.
    entra_banking_hosted_client_id: str = os.getenv(
        "ENTRA_BANKING_HOSTED_CLIENT_ID", os.getenv("AZURE_CLIENT_ID", "")
    )

    # ---- Purview governance ------------------------------------------------
    # Canonical tenant Purview account (pview-isaru66-default-001). The catalog
    # endpoint is tenant-keyed. These defaults are display/wiring values; live
    # Purview SDK calls are still gated by ``mock_mode`` (see sensitivity.py).
    purview_catalog_endpoint: str = "https://ddcbdc96-6162-4d91-bb0d-066343049ce1-api.purview-service.microsoft.com/catalog"
    purview_studio_url: str = "https://purview.microsoft.com/"
    # Purview account name (used by the Purview SDK in live mode).
    purview_account_name: str = "pview-isaru66-default-001"
    # Purview collection that the agent data sources are registered under. Used
    # by the per-agent governance bindings (governance/agent_bindings.py).
    purview_collection: str = "agentic-poc"
    # Sensitivity labels that block agent ingestion of an uploaded document.
    purview_blocked_labels: list[str] = ["Confidential", "Highly Confidential"]

    # ---- Microsoft Defender for Cloud / DSPM for AI ------------------------
    # DSPM = Data Security Posture Management. Agents bind to the NEW DSPM
    # posture plane (not the legacy threat-protection-only signal):
    #   * Defender CSPM (CloudPosture Standard) with the Sensitive Data
    #     Discovery extension — the modern Defender for Cloud DSPM engine that
    #     discovers/maps sensitive data and attack paths. Deployed today as
    #     CloudPosture=Standard with SensitiveDataDiscovery=On.
    #   * Microsoft Purview "DSPM for AI" — the new Purview-portal posture for
    #     AI prompts/responses (sensitive-data discovery across agent traffic).
    # The Defender for "AI workloads" plan (`defender_ai_plan_enabled`) is
    # threat protection only (prompt-injection / anomalous-use alerts). It is
    # reported for completeness but is NOT the DSPM posture plane.
    defender_cspm_dspm_enabled: bool = True
    dspm_sensitive_data_discovery_enabled: bool = True
    dspm_for_ai_enabled: bool = True
    defender_ai_plan_enabled: bool = True

    # ---- Azure AI Foundry guardrails ---------------------------------------
    # Custom blocking RAI policy (scbx-guardrail-v1) attached to the gpt-4o /
    # gpt-4o-mini deployments on agpoc-aifoundry-dev. Set as the canonical
    # default so the governance guardrail wiring reflects the enforced policy.
    foundry_guardrail_policy_id: str = ""
    foundry_guardrail_policy_name: str = "scbx-guardrail-v1"
    foundry_guardrail_mode: str = "enforce"
    foundry_guardrail_provider: str = "Azure AI Foundry"

    # ---- Azure AI Foundry project (SCBXAIplatformPOC) ----------------------
    # Data-plane endpoint of the Foundry project hosting the live agents, plus
    # the project name. Populated once the project is provisioned (see
    # backend/scripts/provision_foundry_agents.py).
    foundry_project_endpoint: str = ""
    foundry_project_name: str = ""

    # ---- Data paths --------------------------------------------------------
    data_dir: str = "data"

    # ---- Derived helpers ---------------------------------------------------
    @property
    def live_active(self) -> bool:
        """True when any live execution path is active (real model / agent calls).

        Telemetry export (Azure Monitor + Foundry tracing) and token-metric
        emission key off this rather than ``mock_mode`` alone, so the hybrid
        demo mode (``MOCK_MODE=true`` + ``LIVE_LLM=true``/``USE_FOUNDRY_AGENTS``)
        still streams gen_ai spans + token usage into the Foundry project's
        connected Application Insights.
        """
        return (not self.mock_mode) or self.live_llm or self.use_foundry_agents or self.use_foundry_workflows

    @property
    def data_path(self) -> Path:
        """Absolute path to the synthetic ``data/`` directory.

        Resolves ``DATA_DIR`` relative to this file's repo location so the app
        works regardless of the current working directory.
        """
        raw = Path(self.data_dir)
        if raw.is_absolute():
            return raw
        # ``DATA_DIR`` (default "../data") is relative to the backend/ directory.
        # config.py is backend/app/config.py, so backend/ is parents[1].
        backend_dir = Path(__file__).resolve().parents[1]
        return (backend_dir / raw).resolve()

    def deployment_for(self, model: str) -> str:
        """Map a logical model name to its Azure OpenAI deployment name."""
        return {
            "gpt-4o": self.azure_openai_deployment_gpt4o,
            "gpt-4o-mini": self.azure_openai_deployment_gpt4o_mini,
        }.get(model, model)

    @property
    def foundry_agent_ids(self) -> dict[str, str]:
        """Live Foundry agent ids (logical_name -> agent version id), if provisioned.

        New-API Foundry agents are versioned and identified by name+version
        (e.g. ``memo-orchestrator:1``), not legacy ``asst_*`` ids. Reads
        ``backend/app/foundry_agent_ids.json`` written by
        ``scripts/provision_foundry_agents.py``. Returns an empty dict when the
        project has not been provisioned yet.
        """
        path = Path(__file__).resolve().parent / "foundry_agent_ids.json"
        if not path.exists():
            return {}
        try:
            import json

            return json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return {}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor (import-safe singleton)."""
    return Settings()


# Convenience module-level singleton for ergonomic imports.
settings = get_settings()

# Allow tests / tooling to force mock mode without a .env present.
if os.getenv("MOCK_MODE", "").lower() in {"1", "true", "yes"}:
    settings.mock_mode = True
