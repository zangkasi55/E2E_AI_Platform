// =============================================================================
// lib/backend.ts — the single data interface the UI talks to. Two interchangeable
// implementations satisfy it: a mock (canned data from data/mockData.ts) and a
// real one (lib/api.ts, FastAPI orchestrator). Selected by VITE_USE_MOCK.
// Components never branch on which backend is live (POC_SPEC §5 wiring table).
// =============================================================================
import type { RunDef, RunKey, TokenRecord } from "../types";
import type { DspmEvent } from "./dspmEvents";

export interface DRDocumentMetadata {
  file_name: string;
  size_bytes: number;
  mime_type?: string;
  last_modified_epoch_ms?: number;
  uploaded_at: string;
  // Extracted document text. Sent so the backend agent can analyse the actual
  // case content (identity, financials, bureau signals) instead of relying on
  // the filename. Best-effort: binary uploads may yield no usable text.
  content?: string;
}

export interface GetRunOptions {
  drDocument?: DRDocumentMetadata;
  bankingMessage?: string;
}

export interface GovernanceControl {
  id: string;
  title: string;
  requirement: string;
  purview_capability?: string;
  entra_capability?: string;
}

export interface GovernancePolicy {
  policy_id: string;
  name: string;
  owner: string;
  platform: string;
  scope: string[];
  controls: GovernanceControl[];
}

export interface ComponentWiring {
  component: string;
  configured: boolean;
  details: Record<string, string>;
}

/** A single pillar block inside a per-agent binding (always has `configured`). */
export interface PillarBinding {
  configured: boolean;
  [key: string]: unknown;
}

/** Per-agent nine-pillar governance/observability wiring binding. */
export interface AgentBinding {
  agent: string;
  use_case: string;
  entra: PillarBinding;
  apim: PillarBinding;
  guardrail: PillarBinding;
  agent_workflow: PillarBinding;
  ai_foundry: PillarBinding;
  dspm: PillarBinding;
  purview: PillarBinding;
  app_insights: PillarBinding;
  foundry_observability: PillarBinding;
}

export interface GovernancePayload {
  data_policy: GovernancePolicy;
  security_policy: GovernancePolicy;
  guardrail_policy: {
    provider: string;
    policy_id: string;
    policy_name: string;
    mode: string;
    configured: boolean;
  };
  component_wiring: ComponentWiring[];
  /** Per-agent nine-pillar wiring (optional for older/mocked payloads). */
  agent_bindings?: AgentBinding[];
}

export interface Backend {
  /** Start / fetch a run and its ordered steps. POST /api/runs → GET /api/runs/{id}. */
  getRun(key: RunKey, options?: GetRunOptions): Promise<RunDef>;
  /** Token records for the dashboard. GET /api/tokens. */
  getTokens(): Promise<TokenRecord[]>;
  /** Governance policies + component wiring status. */
  getGovernance(): Promise<GovernancePayload>;
  /** Microsoft Purview / DSPM-for-AI data-security events (label scans + DLP blocks). */
  getDspmEvents(limit?: number): Promise<DspmEvent[]>;
  /** Resume a HITL-paused run on human approval. POST /api/runs/{id}/approve. */
  approve(runId: string, decision: "approve" | "reject", reviewer: string, reason?: string): Promise<void>;
}

export const USE_MOCK = String(import.meta.env.VITE_USE_MOCK ?? "true") !== "false";
const DEFAULT_API_BASE = "https://agpoc-aca-orch-dev.purplebush-679f865f.swedencentral.azurecontainerapps.io";
const configuredApiBase = String(import.meta.env.VITE_API_BASE_URL ?? DEFAULT_API_BASE).trim();
export const API_BASE = configuredApiBase.endsWith("/") ? configuredApiBase.slice(0, -1) : configuredApiBase;
