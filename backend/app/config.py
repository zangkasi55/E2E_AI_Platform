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
    azure_tenant_id: str = ""
    entra_orchestrator_client_id: str = ""
    entra_tool_bridge_client_id: str = ""
    entra_ui_client_id: str = ""

    # ---- Purview governance ------------------------------------------------
    purview_catalog_endpoint: str = ""
    purview_studio_url: str = ""
    # Purview account name (used by the Purview SDK in live mode).
    purview_account_name: str = ""
    # Purview collection that the agent data sources are registered under. Used
    # by the per-agent governance bindings (governance/agent_bindings.py).
    purview_collection: str = "agentic-poc"
    # Sensitivity labels that block agent ingestion of an uploaded document.
    purview_blocked_labels: list[str] = ["Confidential", "Highly Confidential"]

    # ---- Microsoft Defender for Cloud / DSPM for AI ------------------------
    # DSPM = Data Security Posture Management. For AI workloads this is delivered
    # by (a) Defender for Cloud's "AI workloads" plan (threat protection on the
    # Azure OpenAI / Foundry account) and (b) Microsoft Purview "DSPM for AI"
    # (sensitive-data discovery + posture across agent prompts/responses).
    defender_ai_plan_enabled: bool = True
    dspm_for_ai_enabled: bool = True

    # ---- Azure AI Foundry guardrails ---------------------------------------
    foundry_guardrail_policy_id: str = ""
    foundry_guardrail_policy_name: str = ""
    foundry_guardrail_mode: str = "enforce"
    foundry_guardrail_provider: str = "Azure AI Foundry"

    # ---- Azure AI Foundry project (SCBXAIplatformPOC) ----------------------
    # Data-plane endpoint of the Foundry project hosting the live agents, plus
    # the project name. Populated once the project is provisioned (see
    # backend/scripts/provision_foundry_agents.py).
    foundry_project_endpoint: str = ""
    foundry_project_name: str = ""

    # ---- Data paths --------------------------------------------------------
    data_dir: str = "../data"

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
        return (not self.mock_mode) or self.live_llm or self.use_foundry_agents

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
