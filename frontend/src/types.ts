// =============================================================================
// types.ts — canonical TypeScript contracts for the Agentic AI Platform PoC UI.
// Shapes mirror working/POC_SPEC.md + the Cosmos containers (runs / steps /
// handoffs / tokens). Keep field names identical to the backend so the mock
// data layer and the real FastAPI layer are interchangeable (see lib/backend).
// =============================================================================

export type ModelId = "gpt-4o" | "gpt-4o-mini";

export type ToolName =
  | "search_documents"
  | "get_financials"
  | "calculate_ratios"
  | "get_bureau_report"
  | "render_memo"
  | "get_balance"
  | "resolve_payee"
  | "check_transfer_eligibility"
  | "request_transaction_handoff";

export type AgentStatus = "pending" | "working" | "done" | "blocked";

export type UseCase = "credit_memo" | "banking";

export type RunStatus =
  | "ready"
  | "playing"
  | "paused"
  | "awaiting_approval"
  | "awaiting_ekyc"
  | "done"
  | "blocked";

export interface StepTokens {
  prompt: number;
  completion: number;
}

// Canonical token contract — POC_SPEC §Token monitoring.
export interface TokenRecord {
  run_id: string;
  agent: string;
  step: number;
  model: ModelId;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  est_cost_usd: number;
  ts: string;
  use_case: UseCase;
}

// UC2 terminal — POC_SPEC §UC2 hard rule. The agent moves NO money.
export interface HandoffObject {
  handoff_id: string;
  intent: string;
  slots: Record<string, unknown>;
  policy_result: "permit" | "deny";
  requires_confirmation: true;
  requires_step_up_auth: true;
  money_moved: false;
  tool_trace: ToolName[];
  payee_name?: string;
}

// A single orchestration step (covers UC1 phases and UC2 prob/det stages).
export interface Step {
  step: number;
  agent: string;
  title: string;
  detail: string;
  result: string;
  audit: string;
  model?: ModelId | null;
  // UC1
  phase?: "plan" | "tool" | "hitl" | "final";
  chainTool?: ToolName;
  requiresApproval?: boolean;
  hitl?: boolean;
  // UC2
  stage?: string;
  zone?: "prob" | "det";
  // Identity-confirmation (EKYC) gate: the run pauses for the customer to
  // Confirm or Cancel before any account tool runs.
  ekyc?: boolean;
  // shared
  tool?: ToolName | null;
  apim?: boolean;
  params?: Record<string, unknown>;
  tokens?: StepTokens | null;
  blocked?: boolean;
  handoff?: HandoffObject;
}

export interface RunDef {
  run_id: string;
  use_case: UseCase;
  steps: Step[];
  applicant?: string;
  message?: string;
  // Set when a Purview sensitivity-label gate rejects the uploaded document.
  policyBlock?: PolicyBlock;
}

// Purview / DSPM rejection surfaced to the credit-memo page.
export interface PolicyBlock {
  reason: "sensitivity_label";
  label: string;
  label_full_name: string;
  file_name: string;
  justification: string;
  source: string;
  dspm_event_id?: string;
}

export type RunKey = "credit_memo" | "banking" | "banking_blocked";

export interface ToolMeta {
  sig: string;
  uc: "UC1" | "UC2";
}

export interface AgentRoster {
  id: string;
  label: string;
  role: string;
  parent?: boolean;
}

// Token dashboard aggregations.
export interface RunAggregate {
  run_id: string;
  use_case: UseCase;
  tokens: number;
  cost: number;
  calls: number;
  ts: string;
}

export interface TokenAggregate {
  total: { prompt: number; completion: number; total: number; cost: number };
  byAgent: Record<string, number>;
  byModel: Record<string, number>;
  byRun: Record<string, RunAggregate>;
}
