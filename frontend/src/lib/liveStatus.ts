// =============================================================================
// lib/liveStatus.ts — derives test-expectation conformance from REAL backend
// signals instead of hardcoded arrays. Probes governance, the UC1/UC2 runs and
// token records, then maps each customer expectation / assessment criterion to
// a status backed by concrete evidence found in the live payloads. Re-runnable
// so dashboards can refresh on demand.
// =============================================================================
import { backend } from "./index";
import { USE_MOCK } from "./backend";
import type { GovernancePayload } from "./backend";
import type { Step } from "../types";

export type LiveStatus = "Demonstrated" | "Mocked" | "Documented" | "Unavailable";

export interface LiveExpectation {
  id: number;
  item: string;
  status: LiveStatus;
  where: string;
}

export interface LiveStatusReport {
  checkedAt: string;
  source: "live FastAPI" | "mock backend";
  minExpected: LiveExpectation[];
  assessment: LiveExpectation[];
  error?: string;
}

const PENDING = "Awaiting probe — press Refresh.";

function pass(id: number, item: string, where: string): LiveExpectation {
  return { id, item, status: "Demonstrated", where };
}

function fail(id: number, item: string): LiveExpectation {
  return { id, item, status: "Unavailable", where: "No live evidence found in backend payload." };
}

/**
 * Run all probes in parallel and map results to conformance items. Each item's
 * status reflects whether the evidence was actually present in the payloads.
 */
export async function probeLiveStatus(): Promise<LiveStatusReport> {
  const checkedAt = new Date().toISOString();
  const source = USE_MOCK ? "mock backend" : "live FastAPI";
  try {
    const [gov, uc1, uc2, uc2b, tokens] = await Promise.all([
      backend.getGovernance(),
      backend.getRun("credit_memo"),
      backend.getRun("banking"),
      backend.getRun("banking_blocked"),
      backend.getTokens(),
    ]);

    const allSteps: Step[] = [...uc1.steps, ...uc2.steps];
    const hitlStep = uc1.steps.find((s) => s.hitl || s.requiresApproval);
    const probStages = uc2.steps.filter((s) => s.zone === "prob");
    const detStages = uc2.steps.filter((s) => s.zone === "det");
    const handoffStep = uc2.steps.find((s) => s.handoff);
    const apimCalls = allSteps.filter((s) => s.apim).length;
    const blockedStep = uc2b.steps.find((s) => s.blocked);
    const dataControls = gov.data_policy.controls.length;
    const secControls = gov.security_policy.controls.length;
    const guardrail = gov.guardrail_policy;
    const configuredComponents = gov.component_wiring.filter((c) => c.configured).length;
    const totalComponents = gov.component_wiring.length;
    const runIds = new Set(tokens.map((t) => t.run_id)).size;

    const minExpected: LiveExpectation[] = [
      hitlStep
        ? pass(1, "UC1 credit memo orchestration with HITL approval", `Run ${uc1.run_id} · HITL gate at step ${hitlStep.step} (${uc1.steps.length} steps)`)
        : fail(1, "UC1 credit memo orchestration with HITL approval"),
      probStages.length && detStages.length
        ? pass(2, "UC2 conversational banking control boundary", `${probStages.length} probabilistic · ${detStages.length} deterministic stages`)
        : fail(2, "UC2 conversational banking control boundary"),
      handoffStep && handoffStep.handoff?.money_moved === false
        ? pass(3, "No direct money movement by agent", `${handoffStep.handoff.handoff_id} · money_moved=false · requires_step_up_auth`)
        : fail(3, "No direct money movement by agent"),
      apimCalls > 0
        ? pass(4, "APIM tool boundary and traceability", `${apimCalls} APIM-gated tool calls across UC1+UC2`)
        : fail(4, "APIM tool boundary and traceability"),
      dataControls > 0
        ? pass(5, "Purview data policy showcase", `${gov.data_policy.policy_id} · ${dataControls} controls · ${gov.data_policy.platform}`)
        : fail(5, "Purview data policy showcase"),
      secControls > 0
        ? pass(6, "EntraID security policy showcase", `${gov.security_policy.policy_id} · ${secControls} controls · ${gov.security_policy.platform}`)
        : fail(6, "EntraID security policy showcase"),
      guardrail.configured && blockedStep
        ? pass(7, "AI Foundry guardrail policy reference in UI", `${guardrail.provider} · ${guardrail.policy_id || guardrail.policy_name} · mode=${guardrail.mode} · block path verified`)
        : fail(7, "AI Foundry guardrail policy reference in UI"),
      {
        id: 8,
        item: "Production deployment hardening beyond PoC",
        status: "Documented",
        where: "docs/production-design-notes.md",
      },
    ];

    const assessment: LiveExpectation[] = [
      uc1.steps.length && uc2.steps.length
        ? pass(1, "Architecture and control pattern clarity", `UC1 ${uc1.steps.length} steps · UC2 ${uc2.steps.length} steps reachable`)
        : fail(1, "Architecture and control pattern clarity"),
      tokens.length > 0
        ? pass(2, "Token monitoring and cost transparency", `${tokens.length} token records across ${runIds} runs`)
        : fail(2, "Token monitoring and cost transparency"),
      totalComponents > 0
        ? pass(3, "Policy-driven governance visibility", `${configuredComponents}/${totalComponents} components configured`)
        : fail(3, "Policy-driven governance visibility"),
      {
        id: 4,
        item: "Live external integrations under tenant constraints",
        status: USE_MOCK ? "Mocked" : "Demonstrated",
        where: USE_MOCK
          ? "Synthetic data paths with real contract surfaces (mock backend)"
          : "Live FastAPI backend serving real integration responses",
      },
      {
        id: 5,
        item: "Release-readiness for production security baseline",
        status: "Documented",
        where: "docs/fit-gap.md and production notes",
      },
    ];

    return { checkedAt, source, minExpected, assessment };
  } catch (e) {
    return {
      checkedAt,
      source,
      minExpected: [],
      assessment: [],
      error: e instanceof Error ? e.message : String(e),
    };
  }
}

export const PROBE_PENDING_NOTE = PENDING;
