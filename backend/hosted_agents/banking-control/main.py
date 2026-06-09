# Copyright (c) Microsoft. All rights reserved.
#
# SCBX UC2 - Conversational Banking Control, packaged as a Microsoft Foundry
# HOSTED AGENT (definition.kind = "hosted").
#
# This is the same UC2 flow that the declarative workflow agent
# (banking_control_workflow.yaml) describes, re-implemented as a Microsoft Agent
# Framework graph so it can run as a containerized hosted agent on Foundry:
#
#   intake -> ekyc -> bank_query -> banking_controller -> judgement
#          -> policy_gate -> human_approval_gate -> transaction_handoff
#
# Probabilistic reasoning (the four LLM agents) stays ABOVE the boundary; the
# limit decision and the human-approval escalation are enforced DETERMINISTICALLY
# below it (policy_gate / human_approval_gate), exactly like the live banking UI.
#
# Over-limit rule: when a transfer EXCEEDS the per-transaction limit
# (policy SCBX-RETAIL-XFER-001, default 1,500 THB), the agent does NOT proceed on
# its own authority. It escalates to an authorized banker (human-in-the-loop) and
# returns an "AWAITING human approval" result instead of a release handoff. No
# agent moves money; the only terminal action is an auditable transaction handoff
# that still requires downstream confirmation and step-up authentication.

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass

from agent_framework import Agent, Executor, Message, WorkflowBuilder, WorkflowContext, handler
from agent_framework.foundry import FoundryAgent, FoundryChatClient, to_prompt_agent
from agent_framework_foundry_hosting import ResponsesHostServer
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv
from typing_extensions import Never

# Foundry sets these at runtime; override=False keeps runtime values authoritative.
load_dotenv(override=False)

logger = logging.getLogger("scbx.banking_control_hosted")

# --- Policy (mirrors backend/data/banking/policy.json - SCBX-RETAIL-XFER-001) --
POLICY_ID = "SCBX-RETAIL-XFER-001"
TRANSFER_LIMIT_THB = float(os.environ.get("BANK_TRANSFER_LIMIT_THB", "1500"))
CURRENCY = "THB"

# --- Foundry agent registration -----------------------------------------------
# Stable names under which the four reasoning agents are REGISTERED as separate
# Foundry PromptAgents - they appear individually in the project's Agents blade
# (not just the single hosted workflow agent).
EKYC_AGENT_NAME = os.environ.get("EKYC_AGENT_NAME", "scbx-banking-ekyc")
BANK_QUERY_AGENT_NAME = os.environ.get("BANK_QUERY_AGENT_NAME", "scbx-banking-bank-query")
CONTROLLER_AGENT_NAME = os.environ.get("CONTROLLER_AGENT_NAME", "scbx-banking-controller")
JUDGEMENT_AGENT_NAME = os.environ.get("JUDGEMENT_AGENT_NAME", "scbx-banking-judgement")


def _register_enabled() -> bool:
    """Whether to publish the four reasoning agents to the Foundry project.

    Defaults to on for real deployments; set ``FOUNDRY_REGISTER_AGENTS=false``
    for offline build validation (no network / no Foundry RBAC).
    """
    return os.environ.get("FOUNDRY_REGISTER_AGENTS", "true").strip().lower() in (
        "1",
        "true",
        "yes",
    )


# --- Entra ID: workload identity for every Azure/Foundry call -----------------
def _entra_credential() -> DefaultAzureCredential:
    """DefaultAzureCredential bound to the agent's Entra workload identity.

    In Foundry / Azure Container Apps the agent authenticates with a (user-
    assigned) **managed identity** - no secrets. When ``AZURE_CLIENT_ID`` is set
    the credential pins that specific managed identity; otherwise it falls back
    to the system-assigned identity / developer login (``az login``) locally.
    """
    client_id = os.environ.get("AZURE_CLIENT_ID") or os.environ.get(
        "AZURE_MANAGED_IDENTITY_CLIENT_ID"
    )
    if client_id:
        return DefaultAzureCredential(managed_identity_client_id=client_id)
    return DefaultAzureCredential()


# --- Observability: OpenTelemetry gen_ai tracing -> App Insights + Foundry -----
def setup_observability() -> None:
    """Wire gen_ai.* OpenTelemetry spans/metrics to Application Insights.

    The same ``APPLICATIONINSIGHTS_CONNECTION_STRING`` that backs the platform's
    Application Insights also surfaces these spans natively in the **Foundry
    project Tracing / Observability** view, so per-agent token usage and the
    HITL decision are auditable end-to-end. Best-effort: a telemetry failure
    must never take the agent down.
    """
    conn = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING", "").strip()
    try:
        from agent_framework.observability import (
            configure_otel_providers,
            enable_instrumentation,
        )

        exporters = None
        if conn:
            from azure.monitor.opentelemetry.exporter import (
                AzureMonitorLogExporter,
                AzureMonitorMetricExporter,
                AzureMonitorTraceExporter,
            )

            exporters = [
                AzureMonitorTraceExporter(connection_string=conn),
                AzureMonitorMetricExporter(connection_string=conn),
                AzureMonitorLogExporter(connection_string=conn),
            ]
        # Enable sensitive data only when explicitly opted in (PII-safe default).
        enable_sensitive = os.environ.get("OTEL_ENABLE_SENSITIVE_DATA", "").lower() in (
            "1",
            "true",
            "yes",
        )
        configure_otel_providers(exporters=exporters, enable_sensitive_data=enable_sensitive)
        enable_instrumentation(enable_sensitive_data=enable_sensitive)
        logger.info(
            "Observability enabled (app_insights=%s, gen_ai spans -> Foundry Observability)",
            bool(conn),
        )
    except Exception as exc:  # pragma: no cover - telemetry is best-effort
        logger.warning("Observability setup skipped: %s", exc)


@dataclass
class BankingState:
    """State threaded through every node of the banking-control graph."""

    user_message: str
    amount: float | None = None
    payee: str | None = None
    ekyc_note: str = ""
    account_note: str = ""
    control_note: str = ""
    judgement_note: str = ""
    over_limit: bool = False
    decision: str = "permit"  # "permit" | "escalate"


def _thb(value: float | None) -> str:
    return f"{value:,.2f} {CURRENCY}" if value is not None else f"unknown {CURRENCY}"


# --- Deterministic intake: parse amount + payee from the customer message ------
_AMOUNT_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(?:thb|baht|฿)?", re.IGNORECASE)
_PAYEE_RE = re.compile(r"\bto\s+([A-Za-z0-9_]+)", re.IGNORECASE)


class Intake(Executor):
    """Start node: regex-parse the structured transfer slots from the message."""

    def __init__(self) -> None:
        super().__init__(id="intake")

    @handler
    async def run(self, messages: list[Message], ctx: WorkflowContext[BankingState]) -> None:
        # As a hosted (Responses-protocol) agent the workflow is entered with the
        # conversation turn (list[Message]); use the latest user text as the
        # transfer instruction to parse.
        message = ""
        for msg in reversed(messages):
            text = getattr(msg, "text", None)
            if text:
                message = text
                break
        state = BankingState(user_message=message)
        amt = _AMOUNT_RE.search(message.replace("to ", " to "))
        if amt:
            try:
                state.amount = float(amt.group(1).replace(",", ""))
            except ValueError:
                state.amount = None
        payee = _PAYEE_RE.search(message)
        if payee:
            state.payee = payee.group(1)
        await ctx.send_message(state)


# --- LLM reasoning nodes (probabilistic zone) ---------------------------------
class AgentStep(Executor):
    """Runs one prompt agent and stores its narrative on the shared state."""

    def __init__(self, executor_id: str, agent, field_name: str, prompt_fn) -> None:
        super().__init__(id=executor_id)
        self._agent = agent
        self._field = field_name
        self._prompt_fn = prompt_fn

    @handler
    async def run(self, state: BankingState, ctx: WorkflowContext[BankingState]) -> None:
        try:
            result = await self._agent.run(self._prompt_fn(state))
            text = getattr(result, "text", None) or str(result)
        except Exception as exc:  # keep the flow resilient for the PoC
            text = f"({self._field} unavailable: {exc})"
        setattr(state, self._field, text.strip())
        await ctx.send_message(state)


# --- Deterministic policy gate (control zone) ---------------------------------
class PolicyGate(Executor):
    """Authoritative over-limit decision - independent of LLM phrasing."""

    def __init__(self) -> None:
        super().__init__(id="policy_gate")

    @handler
    async def run(self, state: BankingState, ctx: WorkflowContext[BankingState]) -> None:
        state.over_limit = state.amount is not None and state.amount > TRANSFER_LIMIT_THB
        state.decision = "escalate" if state.over_limit else "permit"
        await ctx.send_message(state)


# --- Human-in-the-loop over-limit approval gate -------------------------------
class HumanApprovalGate(Executor):
    """When over-limit, the agent cannot self-approve - it escalates to a banker."""

    def __init__(self) -> None:
        super().__init__(id="human_approval_gate")

    @handler
    async def run(self, state: BankingState, ctx: WorkflowContext[BankingState]) -> None:
        # Pass-through node: the decision was set by PolicyGate. Kept as its own
        # node so the over-limit HITL gate is an explicit, visible step in the
        # agent flow (mirrors the 'human_approval' Question gate in the
        # declarative workflow and the HITL pause in Durable Functions).
        await ctx.send_message(state)


# --- Terminal: auditable transaction handoff or HITL escalation ---------------
class TransactionHandoff(Executor):
    """Builds the final response: either an over-limit escalation or a handoff."""

    def __init__(self) -> None:
        super().__init__(id="transaction_handoff")

    @handler
    async def run(self, state: BankingState, ctx: WorkflowContext[Never, str]) -> None:
        payee = state.payee or "the requested payee"
        reasoning = "\n".join(
            line
            for line in (
                f"- EKYC: {state.ekyc_note}" if state.ekyc_note else "",
                f"- Account: {state.account_note}" if state.account_note else "",
                f"- Control: {state.control_note}" if state.control_note else "",
                f"- Judgement: {state.judgement_note}" if state.judgement_note else "",
            )
            if line
        )

        if state.over_limit:
            over_by = (state.amount or 0) - TRANSFER_LIMIT_THB
            body = (
                "⛛ HUMAN APPROVAL REQUIRED — over-limit transfer\n\n"
                f"The transfer of {_thb(state.amount)} to {payee} exceeds the "
                f"per-transaction limit of {_thb(TRANSFER_LIMIT_THB)} "
                f"(over by {_thb(over_by)}, policy {POLICY_ID}).\n"
                "Under SCBX policy the agent cannot approve its own over-limit "
                "transfer, so the request is escalated to an authorized banker "
                "(human-in-the-loop). The transaction handoff is held until the "
                "banker approves; no money has moved.\n\n"
                "Decision required: approve (release handoff for step-up "
                "confirmation) or reject (decline the transfer)."
            )
        else:
            body = (
                "✓ Within policy — transaction handoff prepared\n\n"
                f"The transfer of {_thb(state.amount)} to {payee} is within the "
                f"per-transaction limit of {_thb(TRANSFER_LIMIT_THB)} "
                f"(policy {POLICY_ID}). An auditable transaction handoff has been "
                "prepared. The agent moves no money — the handoff still requires "
                "downstream confirmation and step-up authentication."
            )

        if reasoning:
            body = f"{body}\n\nAgent reasoning:\n{reasoning}"
        await ctx.yield_output(body)


@dataclass
class ReasoningAgentSpec:
    """One probabilistic reasoning agent in the banking-control workflow.

    Each spec is published as its OWN Foundry PromptAgent (``foundry_name``) and
    is also the in-process source of truth for instructions/options.
    """

    foundry_name: str
    executor_id: str
    name: str
    description: str
    instructions: str
    field: str
    prompt_fn: object


def _reasoning_specs() -> list[ReasoningAgentSpec]:
    """The four reasoning agents, each registered as a separate Foundry agent."""
    return [
        ReasoningAgentSpec(
            EKYC_AGENT_NAME,
            "ekyc",
            "ekyc",
            "SCBX UC2 EKYC agent - confirms the customer is the legitimate account holder.",
            (
                "You are the EKYC agent for SCBX conversational banking. Confirm the "
                "customer is the legitimate account holder before any account action. "
                "Reply with a short EKYC decision (passed / not passed) and the method."
            ),
            "ekyc_note",
            lambda s: s.user_message,
        ),
        ReasoningAgentSpec(
            BANK_QUERY_AGENT_NAME,
            "bank_query",
            "bank-query",
            "SCBX UC2 bank-query agent - read-only account snapshot for the policy check.",
            (
                "You are the bank-query agent. For a customer who has passed EKYC, "
                "summarize the relevant account snapshot (balance in THB, status) the "
                "downstream policy check needs. Read-only; never move money."
            ),
            "account_note",
            lambda s: s.user_message,
        ),
        ReasoningAgentSpec(
            CONTROLLER_AGENT_NAME,
            "banking_controller",
            "banking-controller",
            "SCBX UC2 banking controller - decomposes the request into intent + slots.",
            (
                "You are the banking controller. Decompose the customer's request into "
                "an intent plus slots (payee, amount, currency, source account). "
                "Summarize the proposed transfer in one or two sentences. You never "
                "move money; the only terminal action is a transaction handoff."
            ),
            "control_note",
            lambda s: s.user_message,
        ),
        ReasoningAgentSpec(
            JUDGEMENT_AGENT_NAME,
            "judgement",
            "judgement",
            "SCBX UC2 judgement agent - go/no-go against EKYC, balance and transfer policy.",
            (
                "You are the judgement agent. Decide go/no-go on the proposed transfer "
                "using EKYC, balance sufficiency, and the bank transfer policy "
                f"({POLICY_ID}, per-transaction limit {TRANSFER_LIMIT_THB:.0f} THB). "
                "State whether the amount is within or over the limit and why. You "
                "never move money; a pass only authorizes an auditable handoff."
            ),
            "judgement_note",
            lambda s: (
                f"{s.user_message}\n\n[parsed amount={s.amount} "
                f"limit={TRANSFER_LIMIT_THB:.0f} payee={s.payee}]"
            ),
        ),
    ]


def _register_prompt_agents(project_endpoint, credential, specs, local_agents):
    """Publish each reasoning agent as a versioned Foundry **PromptAgent**.

    After this runs, all four agents appear individually in the Foundry
    project's Agents blade, and the workflow connects to each registered version
    via ``FoundryAgent`` so every step is attributed to its own agent in Foundry
    Observability.

    Best-effort: if the project endpoint / RBAC is unavailable, returns an empty
    map and the workflow transparently falls back to the in-process agents.
    """
    refs: dict[str, tuple[str, str]] = {}
    try:
        from azure.ai.projects import AIProjectClient
    except Exception as exc:  # pragma: no cover - dependency guard
        logger.warning("azure-ai-projects unavailable; in-process agents only: %s", exc)
        return refs

    try:
        with AIProjectClient(endpoint=project_endpoint, credential=credential) as project:
            for spec in specs:
                try:
                    definition = to_prompt_agent(local_agents[spec.foundry_name])
                    details = project.agents.create_version(
                        agent_name=spec.foundry_name,
                        definition=definition,
                        description=spec.description,
                        metadata={
                            "policy_id": POLICY_ID,
                            "use_case": "UC2-conversational-banking-control",
                            "role": spec.name,
                            "hitl": "over-limit-human-approval",
                        },
                    )
                    version = str(getattr(details, "version", "") or getattr(details, "id", ""))
                    refs[spec.foundry_name] = (spec.foundry_name, version)
                    logger.info(
                        "Registered Foundry prompt agent %s (v%s)", spec.foundry_name, version
                    )
                except Exception as exc:  # one agent failing must not sink the rest
                    logger.warning(
                        "Could not register prompt agent %s: %s", spec.foundry_name, exc
                    )
    except Exception as exc:  # pragma: no cover - registration is best-effort
        logger.warning("Foundry registration skipped (using in-process agents): %s", exc)
    return refs


def build_workflow_agent():
    # Entra workload identity for every Foundry call (managed identity in ACA).
    credential = _entra_credential()
    project_endpoint = os.environ["FOUNDRY_PROJECT_ENDPOINT"]
    model = os.environ.get("AZURE_AI_MODEL_DEPLOYMENT_NAME", "gpt-4o")

    # FoundryChatClient targets the project's model deployment and emits gen_ai
    # spans into Foundry Observability.
    client = FoundryChatClient(
        project_endpoint=project_endpoint,
        model=model,
        credential=credential,
    )

    specs = _reasoning_specs()
    # In-process agents: the single source of truth for instructions/options and
    # the offline fallback when Foundry registration is disabled/unavailable.
    local_agents = {
        spec.foundry_name: Agent(
            client=client,
            name=spec.name,
            instructions=spec.instructions,
            default_options={"store": False},
        )
        for spec in specs
    }

    # Register the four agents as separate Foundry PromptAgents, then connect the
    # workflow to those registered versions so each step is attributed to its own
    # agent in Foundry. Falls back to the in-process agent on any failure.
    registered = (
        _register_prompt_agents(project_endpoint, credential, specs, local_agents)
        if _register_enabled()
        else {}
    )

    def _executor_agent(spec: ReasoningAgentSpec):
        ref = registered.get(spec.foundry_name)
        if ref is not None:
            return FoundryAgent(
                project_endpoint=project_endpoint,
                agent_name=ref[0],
                agent_version=ref[1] or None,
                credential=credential,
            )
        return local_agents[spec.foundry_name]

    intake = Intake()
    ekyc, bank_query, controller, judgement = (
        AgentStep(spec.executor_id, _executor_agent(spec), spec.field, spec.prompt_fn)
        for spec in specs
    )
    policy_gate = PolicyGate()
    human_approval_gate = HumanApprovalGate()
    handoff = TransactionHandoff()

    return (
        WorkflowBuilder(start_executor=intake, output_from=[handoff])
        .add_edge(intake, ekyc)
        .add_edge(ekyc, bank_query)
        .add_edge(bank_query, controller)
        .add_edge(controller, judgement)
        .add_edge(judgement, policy_gate)
        .add_edge(policy_gate, human_approval_gate)
        .add_edge(human_approval_gate, handoff)
        .build()
        .as_agent()
    )


def main() -> None:
    # Tracing/observability first so the build + first turn are captured.
    setup_observability()
    server = ResponsesHostServer(build_workflow_agent())
    server.run()


if __name__ == "__main__":
    main()
