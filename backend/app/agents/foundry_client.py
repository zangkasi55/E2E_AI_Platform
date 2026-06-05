"""Foundry Agent Service client — real invocation of provisioned prompt agents.

The agents in ``backend/app/foundry_agent_ids.json`` are **prompt agents**
(``definition.kind = "prompt"``) created by
``scripts/provision_foundry_agents.py`` against the new Foundry Agents API
(``api-version=v1``). At runtime they are invoked over the OpenAI-compatible
**responses** protocol exposed per-agent:

    POST {project_endpoint}/agents/{agent_name}/endpoint/protocols/openai/responses

The prompt agent already carries its model + system instructions server-side, so
the request body only needs the user ``input``. Multi-turn is supported via the
returned ``conversation``/``previous_response_id`` but the orchestrator issues
single-shot calls today.

Auth: ``DefaultAzureCredential`` with the data-plane scope
``https://ai.azure.com/.default`` (same as the provisioning script). The caller
(the orchestrator UAMI) needs the *Azure AI User* role on the project.

This module is import-safe without the Azure SDK installed: ``azure-identity`` is
imported lazily so mock mode keeps working offline.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

from ..config import settings

API_VERSION = "v1"
TOKEN_SCOPE = "https://ai.azure.com/.default"

# Cached bearer-token credential (created lazily in live mode).
_credential = None


@dataclass
class FoundryAgentResult:
    """Result of a Foundry prompt-agent invocation."""

    text: str
    usage: dict[str, int]
    agent_name: str
    agent_version: Optional[str]
    response_id: Optional[str]


def split_agent_id(agent_id: str) -> tuple[str, Optional[str]]:
    """Split a versioned agent id (``memo-orchestrator:3``) into (name, version)."""
    if ":" in agent_id:
        name, _, version = agent_id.partition(":")
        return name, version or None
    return agent_id, None


def _get_token() -> str:
    global _credential
    if _credential is None:
        from azure.identity import DefaultAzureCredential  # type: ignore

        _credential = DefaultAzureCredential(
            managed_identity_client_id=settings.entra_orchestrator_client_id or None
        )
    return _credential.get_token(TOKEN_SCOPE).token


def _responses_url(agent_name: str) -> str:
    endpoint = settings.foundry_project_endpoint.rstrip("/")
    return (
        f"{endpoint}/agents/{agent_name}/endpoint/protocols/openai/responses"
        f"?api-version={API_VERSION}"
    )


def _extract_text(payload: dict) -> str:
    """Pull assistant text out of an OpenAI Responses (or chat) payload."""
    # 1) Convenience field some servers include.
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"]
    # 2) Responses API: output[] -> message -> content[] -> output_text.
    out = payload.get("output")
    if isinstance(out, list):
        parts: list[str] = []
        for item in out:
            if not isinstance(item, dict):
                continue
            for chunk in item.get("content", []) or []:
                if isinstance(chunk, dict) and isinstance(chunk.get("text"), str):
                    parts.append(chunk["text"])
        if parts:
            return "".join(parts)
    # 3) Chat-completions fallback.
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        msg = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
        if isinstance(msg.get("content"), str):
            return msg["content"]
    return ""


def _extract_usage(payload: dict) -> dict[str, int]:
    """Normalize usage to ``{prompt_tokens, completion_tokens}``."""
    usage = payload.get("usage") or {}
    prompt = usage.get("input_tokens", usage.get("prompt_tokens"))
    completion = usage.get("output_tokens", usage.get("completion_tokens"))
    out: dict[str, int] = {}
    if prompt is not None:
        out["prompt_tokens"] = int(prompt)
    if completion is not None:
        out["completion_tokens"] = int(completion)
    return out


def invoke_prompt_agent(agent_id: str, input_text: str) -> FoundryAgentResult:
    """Invoke a provisioned Foundry prompt agent and return text + usage.

    Raises ``RuntimeError`` on transport / HTTP errors so the caller can fall
    back to a direct model call without crashing the run.
    """
    agent_name, agent_version = split_agent_id(agent_id)
    url = _responses_url(agent_name)
    body = json.dumps({"input": input_text}).encode()
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {_get_token()}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            payload = json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as exc:  # pragma: no cover - network path
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"Foundry agent '{agent_name}' invoke failed ({exc.code}): {detail}")
    except urllib.error.URLError as exc:  # pragma: no cover - network path
        raise RuntimeError(f"Foundry agent '{agent_name}' invoke transport error: {exc.reason}")

    return FoundryAgentResult(
        text=_extract_text(payload),
        usage=_extract_usage(payload),
        agent_name=agent_name,
        agent_version=agent_version,
        response_id=payload.get("id"),
    )
