"""Microsoft Entra ID workload-identity helpers.

In Azure, each component runs under its own identity (app registrations
``agpoc-orchestrator``, ``agpoc-tool-bridge``, ``agpoc-ui``). The orchestrator
container authenticates to Azure OpenAI, Cosmos, Service Bus, and APIM using a
managed identity resolved by ``DefaultAzureCredential``.

In MOCK_MODE we never construct a real credential — callers should branch on
``settings.mock_mode`` first.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .config import settings


@dataclass(frozen=True)
class AgentIdentity:
    """Per-agent identity metadata.

    NOTE: For the PoC all sub-agents run inside the single orchestrator
    container and therefore share the ``agpoc-orchestrator`` workload identity.
    The ``app_role`` here documents the *intended* least-privilege mapping.

    TODO(copilot): When splitting agents into separate Container Apps / Functions,
    give each its own user-assigned managed identity and APIM product
    subscription so tool scopes can be enforced per-agent at the PDP (see
    tools/registry.py scope checks).
    """

    agent: str
    client_id_setting: str  # which Settings field holds the client id
    app_role: str  # logical least-privilege role name

    @property
    def client_id(self) -> Optional[str]:
        return getattr(settings, self.client_id_setting, "") or None


# Logical identity map for the agent topology (UC1 + UC2).
AGENT_IDENTITIES: dict[str, AgentIdentity] = {
    # UC1 parent + sub-agents
    "memo_orchestrator": AgentIdentity("memo_orchestrator", "entra_orchestrator_client_id", "orchestrator"),
    "doc_retrieval": AgentIdentity("doc_retrieval", "entra_orchestrator_client_id", "reader.search"),
    "financial_ratio": AgentIdentity("financial_ratio", "entra_orchestrator_client_id", "reader.financials"),
    "bureau_summary": AgentIdentity("bureau_summary", "entra_orchestrator_client_id", "reader.bureau"),
    "memo_assembler": AgentIdentity("memo_assembler", "entra_orchestrator_client_id", "writer.memo"),
    # UC2 controller
    "banking_controller": AgentIdentity("banking_controller", "entra_orchestrator_client_id", "controller.banking"),
}


def get_credential():
    """Return a ``DefaultAzureCredential`` for live Azure access.

    Lazily imports ``azure-identity`` so the module compiles / imports cleanly
    in environments without the SDK (e.g. mock mode, CI syntax checks).
    """
    if settings.mock_mode and not settings.live_active:
        raise RuntimeError(
            "get_credential() called in MOCK_MODE — guard with settings.mock_mode."
        )
    # TODO(copilot): In Container Apps this resolves the user-assigned managed
    # identity. Locally it falls back to az-cli / VS Code / env credentials.
    from azure.identity import DefaultAzureCredential  # type: ignore

    return DefaultAzureCredential(
        managed_identity_client_id=settings.entra_orchestrator_client_id or None
    )


def identity_for(agent: str) -> AgentIdentity:
    """Look up the (intended) identity for an agent, defaulting to orchestrator."""
    return AGENT_IDENTITIES.get(
        agent,
        AgentIdentity(agent, "entra_orchestrator_client_id", "orchestrator"),
    )
