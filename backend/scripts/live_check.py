"""Live validation: invoke the agent model layer against the deployed Foundry
gpt-4o / gpt-4o-mini deployments.

Run from the ``backend/`` directory so ``.env`` (LIVE_LLM=true, MOCK_MODE=true)
is loaded by ``config.py``. Authenticates with DefaultAzureCredential — locally
your ``az login`` user (granted "Cognitive Services OpenAI User" on the Foundry
account); in Container Apps the orchestrator managed identity.

This proves: deployments exist, endpoint + Entra auth work, and tokens are
metered end-to-end. APIM-fronted tools remain synthetic (MOCK_MODE=true).
"""
from __future__ import annotations

from app.agents.base import Agent
from app.config import settings


def main() -> None:
    print(f"MOCK_MODE={settings.mock_mode}  LIVE_LLM={settings.live_llm}")
    print(f"endpoint={settings.azure_openai_endpoint}")
    print(f"api_version={settings.azure_openai_api_version}")

    checks = [
        ("memo_orchestrator", "gpt-4o",
         "You plan and coordinate sub-agents to draft an SME credit memo. You never finalize without human approval.",
         "In one sentence, state the plan to draft an SME credit memo for applicant APP-1001."),
        ("doc_retrieval", "gpt-4o-mini",
         "You retrieve and ground statements on approved sources only.",
         "Name the approved source types you would search for an SME credit memo."),
    ]

    for name, model, sys_prompt, user_prompt in checks:
        agent = Agent(name, model=model, system_prompt=sys_prompt, use_case="credit_memo")
        result = agent.run_step(run_id="live-check", step=0, user_prompt=user_prompt)
        rec = result.token_record
        print("\n" + "=" * 70)
        print(f"[{name} / {model}] LIVE response:")
        print(result.text.strip()[:600])
        print(f"tokens: prompt={rec.prompt_tokens} completion={rec.completion_tokens} "
              f"total={rec.total_tokens}  est_cost=${rec.est_cost_usd:.6f}")

    print("\nLIVE_CHECK_OK")


if __name__ == "__main__":
    main()
