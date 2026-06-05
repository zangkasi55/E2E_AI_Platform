"""Agent base class (Semantic Kernel pattern).

An :class:`Agent` wraps a single Azure OpenAI model deployment and exposes a
``run_step`` method that:
  * issues the model call (or a canned response in MOCK_MODE),
  * meters tokens via :data:`token_meter`,
  * returns the text plus the :class:`TokenRecord`.

The orchestrators compose agents; agents do not know about runs/HITL — they are
thin, reusable model-call units. This keeps the topology in POC_SPEC.md
(memo_orchestrator -> {doc_retrieval, financial_ratio, bureau_summary,
memo_assembler}; banking_controller) easy to wire with Semantic Kernel later.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..config import settings
from ..identity import identity_for
from ..governance.agent_bindings import governance_for
from ..models import TokenRecord
from ..telemetry.otel import set_gen_ai_usage, start_gen_ai_span
from ..telemetry.tokens import token_meter


@dataclass
class AgentResult:
    """Output of an :meth:`Agent.run_step` call."""

    text: str
    token_record: TokenRecord


class Agent:
    """A named model-call unit bound to a model deployment.

    Parameters
    ----------
    name:
        Canonical agent name (must match POC_SPEC.md topology).
    model:
        Logical model name ("gpt-4o" or "gpt-4o-mini"); mapped to a deployment
        via :meth:`Settings.deployment_for`.
    system_prompt:
        Base instruction prepended to every call.
    use_case:
        "credit_memo" or "banking" (recorded on token records).
    """

    def __init__(
        self,
        name: str,
        model: str,
        system_prompt: str,
        use_case: str,
    ) -> None:
        self.name = name
        self.model = model
        self.system_prompt = system_prompt
        self.use_case = use_case
        self.identity = identity_for(name)
        # Four-pillar governance binding (Entra · Purview · DSPM · Guardrail).
        self.governance = governance_for(name)
        self._client = None  # lazily created Azure OpenAI client (live mode)

    # -- public API ---------------------------------------------------------
    def run_step(
        self,
        *,
        run_id: str,
        step: int,
        user_prompt: str,
        mock_response: Optional[str] = None,
    ) -> AgentResult:
        """Execute one model call and meter its tokens.

        In MOCK_MODE this returns ``mock_response`` (or a deterministic canned
        string) and estimates tokens with the len/4 heuristic — no network.
        """
        prompt_text = f"{self.system_prompt}\n\n{user_prompt}"

        # Decide the execution path:
        #   * Foundry Agent Service (real prompt-agent invocation) when enabled
        #     and a provisioned agent id exists for this agent.
        #   * Direct Azure OpenAI chat when ``live_llm`` is set.
        #   * Deterministic mock otherwise.
        foundry_agent_id = (
            settings.foundry_agent_ids.get(self.name)
            if (settings.use_foundry_agents and settings.foundry_project_endpoint)
            else None
        )
        use_mock = settings.mock_mode and not settings.live_llm and not foundry_agent_id

        if foundry_agent_id:
            operation, target = "invoke_agent", foundry_agent_id
        else:
            operation, target = "chat", self.model

        with start_gen_ai_span(
            operation=operation,
            target=target,
            agent=self.name,
            model=self.model,
            use_case=self.use_case,
            run_id=run_id,
        ):
            if foundry_agent_id:
                completion_text, usage = self._call_foundry_agent(
                    foundry_agent_id, prompt_text, user_prompt
                )
            elif not use_mock:
                completion_text, usage = self._call_azure_openai(prompt_text)
            else:
                completion_text = mock_response if mock_response is not None else (
                    f"[mock:{self.name}] processed {len(user_prompt)} chars"
                )
                usage = None  # force estimation

            record = token_meter.meter_call(
                run_id=run_id,
                agent=self.name,
                step=step,
                model=self.model,
                use_case=self.use_case,
                prompt_text=prompt_text,
                completion_text=completion_text,
                usage=usage,
            )
            # Annotate the gen_ai span with the resolved token usage so it shows
            # natively in the Foundry project Tracing view.
            set_gen_ai_usage(record.prompt_tokens, record.completion_tokens)
        return AgentResult(text=completion_text, token_record=record)

    # -- Foundry Agent Service call ----------------------------------------
    def _call_foundry_agent(
        self, agent_id: str, prompt_text: str, user_prompt: str
    ) -> tuple[str, Optional[dict]]:
        """Invoke the provisioned Foundry prompt agent (responses protocol).

        The prompt agent already carries its model + system instructions
        server-side, so only the user turn is sent. On any transport/HTTP error
        we fall back to a direct Azure OpenAI call so a run never hard-fails on
        telemetry/agent-service hiccups.
        """
        from .foundry_client import invoke_prompt_agent  # lazy: live mode only

        try:
            result = invoke_prompt_agent(agent_id, user_prompt)
            if result.text:
                return result.text, (result.usage or None)
            # Empty completion — fall through to the direct path below.
        except RuntimeError:
            if settings.mock_mode and not settings.live_llm:
                # No live model to fall back to in pure mock mode.
                return (f"[mock:{self.name}] processed {len(user_prompt)} chars", None)
        return self._call_azure_openai(prompt_text)

    # -- live model call ----------------------------------------------------
    def _call_azure_openai(self, prompt_text: str) -> tuple[str, dict]:
        """Call Azure OpenAI chat completions; return (text, usage dict).

        Lazily builds an AzureOpenAI client authenticated with the orchestrator
        managed identity (Entra token provider).

        TODO(copilot): Replace this direct SDK call with a Semantic Kernel
        ``ChatCompletionAgent`` + function-calling so the registry tools are
        invoked by the planner rather than the orchestrator imperatively.
        """
        client = self._get_client()
        deployment = settings.deployment_for(self.model)
        resp = client.chat.completions.create(  # type: ignore[union-attr]
            model=deployment,
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": prompt_text},
            ],
            temperature=0.2,
        )
        text = resp.choices[0].message.content or ""
        usage = {
            "prompt_tokens": resp.usage.prompt_tokens,
            "completion_tokens": resp.usage.completion_tokens,
        }
        return text, usage

    def _get_client(self):
        if self._client is not None:
            return self._client
        from azure.identity import get_bearer_token_provider  # type: ignore
        from openai import AzureOpenAI  # type: ignore

        from ..identity import get_credential

        token_provider = get_bearer_token_provider(
            get_credential(), "https://cognitiveservices.azure.com/.default"
        )
        self._client = AzureOpenAI(
            azure_endpoint=settings.azure_openai_endpoint,
            azure_ad_token_provider=token_provider,
            api_version=settings.azure_openai_api_version,
        )
        return self._client
