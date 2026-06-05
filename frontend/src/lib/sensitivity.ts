// =============================================================================
// lib/sensitivity.ts — client mirror of the backend Purview sensitivity gate
// (backend/app/governance/sensitivity.py). Resolves the Microsoft Purview
// sensitivity label for an uploaded file from its name and decides whether the
// credit-memo agent may ingest it. Confidential / Highly Confidential → blocked.
// Kept in sync with the synthetic catalog data/credit_memo/sensitivity_labels.json
// so the deployed mock demo behaves identically to the live FastAPI gate.
// =============================================================================

export interface SensitivityResult {
  file_name: string;
  label: string;
  label_id: string;
  full_name: string;
  color: string;
  protected: boolean;
  source: string;
  blocked: boolean;
  justification: string;
}

const BLOCKED_LABELS = new Set(["Confidential", "Highly Confidential"]);

const LABEL_COLORS: Record<string, string> = {
  "Highly Confidential": "#a4262c",
  Confidential: "#d83b01",
  General: "#107c10",
  Public: "#605e5c",
};

// Synthetic Purview catalog (exact file-name → label). Mirrors the JSON file.
const CATALOG: Record<string, Omit<SensitivityResult, "file_name" | "blocked" | "justification">> = {
  "Siam-Lotus-Board-Resolution-HIGHLY-CONFIDENTIAL.txt": {
    label: "Highly Confidential",
    label_id: "9f8c7b6a-5d4e-4c3b-2a1f-0e9d8c7b6a5f",
    full_name: "Highly Confidential \\ Board & Legal",
    color: "#a4262c",
    protected: true,
    source: "purview_catalog",
  },
  "credit-file-APP-1001-siam-lotus-foods.txt": {
    label: "General",
    label_id: "1a2b3c4d-0000-4a5b-9c8d-7e6f5a4b3c2d",
    full_name: "General \\ Internal Business",
    color: "#107c10",
    protected: false,
    source: "purview_catalog",
  },
};

function heuristic(fileName: string): Omit<SensitivityResult, "file_name" | "blocked" | "justification"> {
  const name = (fileName || "").toLowerCase();
  let label = "General";
  let full = "General \\ Internal Business";
  if (/(highly[\s_-]*confidential|restricted|top[\s_-]*secret)/.test(name)) {
    label = "Highly Confidential";
    full = "Highly Confidential \\ Board & Legal";
  } else if (name.includes("confidential")) {
    label = "Confidential";
    full = "Confidential \\ Restricted";
  }
  return {
    label,
    label_id: `heuristic-${label.toLowerCase().replace(/\s+/g, "-")}`,
    full_name: full,
    color: LABEL_COLORS[label] ?? "#605e5c",
    protected: label === "Confidential" || label === "Highly Confidential",
    source: "purview_auto_labeling_heuristic",
  };
}

export function resolveSensitivityLabel(fileName: string): SensitivityResult {
  const resolved = CATALOG[fileName] ?? heuristic(fileName);
  const blocked = BLOCKED_LABELS.has(resolved.label);
  const justification = blocked
    ? `Microsoft Purview classified this file as '${resolved.full_name}'. Files labeled Confidential or Highly Confidential are blocked from agent ingestion by the credit-memo data-loss-prevention policy.`
    : `Microsoft Purview label '${resolved.full_name}' permits agent ingestion for credit-memo drafting.`;
  return { file_name: fileName, ...resolved, blocked, justification };
}
