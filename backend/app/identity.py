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
import os
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
    # Whether this agent is invoked at runtime as its OWN Foundry agent (and
    # therefore requires a provisioned Foundry AgentID). Governance-only entries
    # (e.g. conversational-banking sub-steps that run inside the
    # ``banking_controller`` flow rather than as separate Foundry agents) set
    # this False so they carry an Entra role + governance binding WITHOUT
    # gating startup on a Foundry AgentID mapping.
    requires_foundry_agent: bool = True

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
    # UC2 controller + conversational-banking sub-agents
    "banking_controller": AgentIdentity("banking_controller", "entra_orchestrator_client_id", "controller.banking"),
    # EKYC identity-confirmation agent — may only run the EKYC verify tool.
    # These three run inside the banking_controller flow (not as separate
    # runtime Foundry agents yet), so requires_foundry_agent=False keeps them
    # off the startup AgentID-coverage gate while still carrying Entra roles.
    "ekyc_agent": AgentIdentity(
        "ekyc_agent", "entra_orchestrator_client_id", "verifier.ekyc", requires_foundry_agent=False
    ),
    # Bank-query agent — read-only account snapshot (balance/status); moves no money.
    "bank_query": AgentIdentity(
        "bank_query", "entra_orchestrator_client_id", "reader.account", requires_foundry_agent=False
    ),
    # Judgement agent — deterministic transfer-limit decision; moves no money.
    "judgement_agent": AgentIdentity(
        "judgement_agent", "entra_orchestrator_client_id", "judge.transfer", requires_foundry_agent=False
    ),
    # UC2 as a Foundry HOSTED AGENT — the banking-control flow packaged and
    # deployed as a containerized hosted agent (backend/hosted_agents/banking-
    # control). It authenticates with its OWN user-assigned managed identity
    # (resolved from AZURE_CLIENT_ID at runtime) rather than the orchestrator
    # identity, so it has a dedicated client-id setting. requires_foundry_agent
    # is False because it is deployed/registered as its own hosted endpoint
    # (not invoked as an in-process sub-agent of the orchestrator), so it must
    # not gate the orchestrator's Foundry AgentID-coverage startup check.
    "banking_control_hosted": AgentIdentity(
        "banking_control_hosted",
        "entra_banking_hosted_client_id",
        "controller.banking",
        requires_foundry_agent=False,
    ),
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
    from azure.identity import DefaultAzureCredential, ManagedIdentityCredential  # type: ignore

    client_id = settings.entra_orchestrator_client_id or os.getenv("AZURE_CLIENT_ID") or None

    # In live mode, force ManagedIdentityCredential so every agent path uses
    # the configured AgentID/UAMI instead of local/dev credential fallbacks.
    if settings.live_active:
        return ManagedIdentityCredential(client_id=client_id)

    # Local dev / CI fallback chain.
    return DefaultAzureCredential(managed_identity_client_id=client_id)


def identity_for(agent: str) -> AgentIdentity:
    """Look up the (intended) identity for an agent, defaulting to orchestrator."""
    return AGENT_IDENTITIES.get(
        agent,
        AgentIdentity(agent, "entra_orchestrator_client_id", "orchestrator"),
    )


def validate_foundry_agent_id_coverage() -> list[str]:
    """Return logical agent names missing a Foundry AgentID mapping.

    Only agents invoked at runtime as their own Foundry agent
    (``requires_foundry_agent=True``) are required to have a mapping.
    Governance-only identity entries are excluded so they can declare an Entra
    role / governance binding without being provisioned in Foundry.
    """
    required = {
        name
        for name, ident in AGENT_IDENTITIES.items()
        if ident.requires_foundry_agent
    }
    mapped = set(settings.foundry_agent_ids.keys())
    return sorted(required - mapped)
