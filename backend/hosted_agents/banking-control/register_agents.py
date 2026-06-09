# Copyright (c) Microsoft. All rights reserved.
#
# One-shot helper: register the four SCBX UC2 banking-control reasoning agents as
# their own Foundry PromptAgents in the project, using the developer's az-login
# identity (AzureCliCredential). Idempotent: each run creates a new version.
#
# Usage (from this folder):
#   $env:FOUNDRY_PROJECT_ENDPOINT="https://<foundry>.services.ai.azure.com/api/projects/<project>"
#   $env:AZURE_AI_MODEL_DEPLOYMENT_NAME="gpt-4o"
#   python register_agents.py

from __future__ import annotations

import logging
import os

from agent_framework import Agent
from agent_framework.foundry import FoundryChatClient
from azure.identity import AzureCliCredential

import main

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("register_agents")


def run() -> int:
    endpoint = os.environ["FOUNDRY_PROJECT_ENDPOINT"]
    model = os.environ.get("AZURE_AI_MODEL_DEPLOYMENT_NAME", "gpt-4o")
    credential = AzureCliCredential()

    client = FoundryChatClient(project_endpoint=endpoint, model=model, credential=credential)
    specs = main._reasoning_specs()
    local_agents = {
        spec.foundry_name: Agent(
            client=client,
            name=spec.name,
            instructions=spec.instructions,
            default_options={"store": False},
        )
        for spec in specs
    }

    refs = main._register_prompt_agents(endpoint, credential, specs, local_agents)
    if not refs:
        log.error("No agents were registered. Check RBAC / endpoint and re-run.")
        return 1
    print("\nRegistered Foundry prompt agents:")
    for name, (agent_name, version) in refs.items():
        print(f"  - {agent_name}  (version {version})")
    print(f"\nTotal: {len(refs)} / {len(specs)} agents registered.")
    return 0 if len(refs) == len(specs) else 2


if __name__ == "__main__":
    raise SystemExit(run())
