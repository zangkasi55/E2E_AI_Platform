// =============================================================================
// theme.ts — canonical color language (POC_SPEC §Color language). Reuse EXACTLY.
// These are also declared as CSS custom properties in styles.css (:root) so
// className-based styling and inline style={{...}} stay in sync.
// =============================================================================
import type { ModelId } from "./types";

export const colors = {
  agent: "#0B5CAB", // parent agent / orchestrator
  agent2: "#2E7DD1", // sub-agent / active working fill
  model: "#5B2D8E", // model calls (gpt-4o)
  tool: "#0E7C7B", // tools / APIM tool zone
  data: "#2E7D32", // data + "ok"
  gov: "#7A1FA2", // governance / PDP
  obs: "#C25E00", // observability / HITL pause / audit
  sec: "#1A4E8A", // security
  channel: "#37474F", // channels / user
  blocked: "#B3261E", // blocked + deterministic boundary
  ok: "#2E7D32", // success / done
  ink: "#1A1A1A", // text
  muted: "#5F6B7A", // secondary text
} as const;

export type ColorToken = keyof typeof colors;

// Illustrative model price table (USD per 1K tokens). The real deployment's
// per-1K rates can replace these, or read est_cost_usd straight from records.
export const PRICE: Record<ModelId, { prompt: number; completion: number }> = {
  "gpt-4o": { prompt: 0.0025, completion: 0.01 },
  "gpt-4o-mini": { prompt: 0.00015, completion: 0.0006 },
};

export function estCost(model: ModelId, prompt: number, completion: number): number {
  const t = PRICE[model] ?? PRICE["gpt-4o"];
  return +((prompt / 1000) * t.prompt + (completion / 1000) * t.completion).toFixed(5);
}

// Per-model accent for token badges/dots.
export function modelColor(model?: ModelId | null): string {
  if (model === "gpt-4o") return colors.model;
  if (model === "gpt-4o-mini") return "#8A6DB3";
  return colors.muted;
}
