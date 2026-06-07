// =============================================================================
// lib/mockBackend.ts — dev implementation of Backend using canned data.
// Mirrors the real route shapes so the UI is byte-for-byte identical when the
// FastAPI orchestrator lands. Small artificial latency keeps the UX realistic.
// =============================================================================
import type { Backend, AgentBinding, GovernancePayload } from "./backend";
import type { RunDef, RunKey, Step, TokenRecord } from "../types";
import { RUNS, TOKENS } from "../data/mockData";
import { resolveSensitivityLabel } from "./sensitivity";
import { getDspmEvents, recordDspmEvent, type DspmEvent } from "./dspmEvents";

const delay = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Build a per-agent binding with all nine pillars configured (mock). */
function mockBinding(agent: string, use_case: string): AgentBinding {
  const on = { configured: true } as const;
  return {
    agent,
    use_case,
    entra: on,
    apim: on,
    guardrail: on,
    agent_workflow: on,
    ai_foundry: on,
    dspm: on,
    purview: on,
    app_insights: on,
    foundry_observability: on,
  };
}

const MOCK_AGENT_BINDINGS: AgentBinding[] = [
  mockBinding("memo_orchestrator", "credit_memo"),
  mockBinding("doc_retrieval", "credit_memo"),
  mockBinding("financial_ratio", "credit_memo"),
  mockBinding("bureau_summary", "credit_memo"),
  mockBinding("memo_assembler", "credit_memo"),
  mockBinding("banking_controller", "banking"),
];

export const mockBackend: Backend = {
  async getRun(key: RunKey, options): Promise<RunDef> {
    await delay(180);
    const run = RUNS[key];
    if (!run) throw new Error(`Unknown run key: ${key}`);

    // --- Purview / DSPM sensitivity-label gate (UC1 credit memo) ----------
    if (key === "credit_memo" && options?.drDocument) {
      const sensitivity = resolveSensitivityLabel(options.drDocument.file_name);
      const event = recordDspmEvent({
        event_type: sensitivity.blocked ? "dlp_block" : "sensitivity_label_scan",
        decision: sensitivity.blocked ? "blocked" : "allowed",
        severity: sensitivity.blocked ? "high" : "informational",
        label: sensitivity.label,
        label_full_name: sensitivity.full_name,
        file_name: sensitivity.file_name,
        run_id: run.run_id,
        user: "loan.officer@scbx.local",
        use_case: "credit_memo",
        detail: sensitivity.justification,
      });
      if (sensitivity.blocked) {
        const blockStep: Step = {
          step: 1,
          agent: "doc_retrieval",
          model: "gpt-4o-mini",
          phase: "tool",
          title: "Purview sensitivity-label scan",
          tool: null,
          apim: true,
          blocked: true,
          detail:
            "Microsoft Purview / DSPM for AI gate evaluated the uploaded document before ingestion.",
          result: sensitivity.justification,
          audit: `PURVIEW BLOCK · label=${sensitivity.label} · dspm_event=${event.id}`,
          params: { sensitivity, dspm_event: event },
        };
        return {
          run_id: run.run_id,
          use_case: "credit_memo",
          applicant: run.applicant,
          steps: [blockStep],
          policyBlock: {
            reason: "sensitivity_label",
            label: sensitivity.label,
            label_full_name: sensitivity.full_name,
            file_name: sensitivity.file_name,
            justification: sensitivity.justification,
            source: sensitivity.source,
            dspm_event_id: event.id,
          },
        };
      }
    }

    const clone = structuredClone(run);
    if ((key === "banking" || key === "banking_blocked") && options?.bankingMessage?.trim()) {
      clone.message = options.bankingMessage.trim();
    }
    // structuredClone so the player can mutate locally without touching source.
    return clone;
  },

  async getTokens(): Promise<TokenRecord[]> {
    await delay(140);
    return structuredClone(TOKENS);
  },

  async getDspmEvents(limit = 50): Promise<DspmEvent[]> {
    await delay(100);
    return getDspmEvents(limit);
  },

  async getGovernance(): Promise<GovernancePayload> {
    await delay(120);
    return {
      data_policy: {
        policy_id: "dp-purview-credit-memo-001",
        name: "Credit Memo Data Governance Policy",
        owner: "Data Governance Office",
        platform: "Microsoft Purview",
        scope: ["credit_memo", "banking"],
        controls: [
          {
            id: "DP-01",
            title: "Classify sensitive financial and customer attributes",
            requirement: "All applicant and customer records are classified with Purview labels before retrieval.",
            purview_capability: "Auto classification + glossary term mapping",
          },
          {
            id: "DP-02",
            title: "Lineage and source grounding",
            requirement: "Each memo statement maps to an approved source document and lineage entry.",
            purview_capability: "Lineage graph + catalog metadata",
          },
        ],
      },
      security_policy: {
        policy_id: "sp-entra-apim-agent-001",
        name: "Agent Tool Access Security Policy",
        owner: "Security Architecture",
        platform: "Microsoft Entra ID + Azure API Management",
        scope: ["orchestrator", "tool_bridge", "ui"],
        controls: [
          {
            id: "SP-01",
            title: "Token-based access control",
            requirement: "All tool calls require Entra-issued JWT tokens validated by APIM.",
            entra_capability: "OAuth2 scopes + managed identity",
          },
          {
            id: "SP-02",
            title: "Least-privilege role assignments",
            requirement: "Each workload identity receives minimum RBAC permissions.",
            entra_capability: "RBAC + workload identity separation",
          },
        ],
      },
      guardrail_policy: {
        provider: "Azure AI Foundry",
        policy_id: "gr-foundry-banking-001",
        policy_name: "Banking Prompt Safety Policy",
        mode: "enforce",
        configured: true,
      },
      component_wiring: [
        {
          component: "Entra ID",
          configured: true,
          details: {
            tenant_id: "ddcbdc96-6162-4d91-bb0d-066343049ce1",
            ui_app: "agpoc-ui-dev",
            tool_bridge_app: "agpoc-tool-bridge-dev",
          },
        },
        {
          component: "APIM",
          configured: true,
          details: { base_url: "https://agpoc-apim-dev.azure-api.net/tools" },
        },
        {
          component: "Purview",
          configured: true,
          details: {
            catalog_endpoint:
              "https://ddcbdc96-6162-4d91-bb0d-066343049ce1-api.purview-service.microsoft.com/catalog",
            studio_url: "https://purview.microsoft.com/",
            collection: "agentic-poc",
          },
        },
        {
          component: "Defender / DSPM for AI",
          configured: true,
          details: { defender_ai_workloads_plan: "enabled", purview_dspm_for_ai: "enabled" },
        },
        {
          component: "Cosmos",
          configured: true,
          details: {
            endpoint: "https://agpoc-cosmos-dev.documents.azure.com:443/",
            database: "agentaudit",
            runs_container: "runs",
            steps_container: "steps",
            tokens_container: "tokens",
          },
        },
        {
          component: "Guardrail",
          configured: true,
          details: { provider: "Azure AI Foundry", policy_name: "scbx-guardrail-v1", mode: "enforce" },
        },
        {
          component: "AI Foundry",
          configured: true,
          details: {
            openai_endpoint: "https://agpoc-aoai-dev.openai.azure.com/",
            project_name: "SCBXAIplatformPOC",
            agents: "model-direct",
          },
        },
        {
          component: "Agent workflow",
          configured: true,
          details: {
            topology:
              "memo_orchestrator -> {doc_retrieval, financial_ratio, bureau_summary, memo_assembler}; banking_controller",
            foundry_workflow_agents: "in-process orchestrator",
          },
        },
        {
          component: "App Insights",
          configured: true,
          details: { metric: "gen_ai.token.usage", connection: "configured" },
        },
        {
          component: "Foundry Observability",
          configured: true,
          details: { tracing: "gen_ai.* spans", view: "Foundry project Tracing" },
        },
      ],
      agent_bindings: MOCK_AGENT_BINDINGS,
    };
  },

  async approve(
    _runId: string,
    _decision: "approve" | "reject",
    _reviewer: string,
    _reason?: string,
  ): Promise<void> {
    await delay(120);
    // No-op in mock: the player resumes locally to the final step.
  },
};
