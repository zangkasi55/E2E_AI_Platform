// =============================================================================
// components/banking.tsx — UC2 deterministic-control visuals. Probabilistic zone
// (intent/slot/conditional) sits ABOVE the deterministic boundary; the
// deterministic zone (APIM scope bar + tool stages + PDP + guardrails) sits
// below. Terminal action is an auditable HandoffObject — the agent moves NO
// money. POC_SPEC §UC2 hard rule.
// =============================================================================
import { useState } from "react";
import type { AgentStatus, HandoffObject, Step } from "../types";
import { TOOLS } from "../data/mockData";
import { JsonBlock, StatusChip } from "./primitives";

interface GuardrailPolicyRef {
  provider: string;
  policy_id: string;
  policy_name: string;
  mode: string;
  configured: boolean;
}

interface StageDef {
  id: string;
  label: string;
  role: string;
  zone: "prob" | "det";
  gov?: boolean;
}

const PROB_STAGES: StageDef[] = [
  { id: "intent_decomposition", label: "Intent decomposition", role: "Parse NL → ordered intents", zone: "prob" },
  { id: "slot_filling", label: "Slot filling", role: "Extract & validate slots", zone: "prob" },
  { id: "conditional_eval", label: "Conditional logic", role: "Evaluate guard condition", zone: "prob" },
];

const DET_STAGES: StageDef[] = [
  { id: "balance_lookup", label: "get_balance", role: TOOLS.get_balance.sig, zone: "det" },
  { id: "payee_resolution", label: "resolve_payee", role: TOOLS.resolve_payee.sig, zone: "det" },
  { id: "eligibility_check", label: "check_transfer_eligibility + PDP", role: "Policy Decision Point", zone: "det", gov: true },
  { id: "human_approval", label: "human_approval_gate", role: "HITL · over-limit approval", zone: "det", gov: true },
  { id: "handoff", label: "request_transaction_handoff", role: "Terminal · auditable handoff", zone: "det" },
];

const SG: Record<string, string> = {
  intent_decomposition: "IN",
  slot_filling: "SL",
  conditional_eval: "IF",
  balance_lookup: "B",
  payee_resolution: "P",
  eligibility_check: "E",
  human_approval: "HA",
  handoff: "H",
};

function StageRow({ s, status }: { s: StageDef; status: AgentStatus }) {
  const cls = ["stage", s.zone, s.gov ? "gov" : "", status].filter(Boolean).join(" ");
  return (
    <div className={cls} aria-current={status === "working" ? "step" : undefined} aria-label={`${s.label}: ${status}`}>
      <span className="sg" aria-hidden>
        {SG[s.id] ?? s.label.slice(0, 2).toUpperCase()}
      </span>
      <div className="smeta">
        <div className="snm">{s.label}</div>
        <div className="srole">{s.role}</div>
      </div>
      <StatusChip status={status} />
    </div>
  );
}

export function ProbabilisticZone({ nodeStatus }: { nodeStatus: (id: string) => AgentStatus }) {
  return (
    <div className="zone prob">
      <div className="zlab">
        <span aria-hidden>◆</span> Probabilistic zone · LLM reasoning
      </div>
      <div className="stages">
        {PROB_STAGES.map((s) => (
          <StageRow key={s.id} s={s} status={nodeStatus(s.id)} />
        ))}
      </div>
    </div>
  );
}

export function DeterministicBoundary() {
  return (
    <div className="boundary" role="separator" aria-label="probabilistic / deterministic boundary">
      ▲ probabilistic · deterministic ▼
    </div>
  );
}

export function DeterministicZone({
  nodeStatus,
  guardrailPolicy,
}: {
  nodeStatus: (id: string) => AgentStatus;
  guardrailPolicy?: GuardrailPolicyRef;
}) {
  return (
    <div className="zone det">
      <div className="zlab">
        <span aria-hidden>▣</span> Deterministic control zone · APIM + PDP
      </div>
      <div className="apimbar">
        <span aria-hidden>🛡</span> APIM tool gateway · scope enforcement · every tool call logged
      </div>
      {guardrailPolicy ? (
        <div className="apimbar">
          <span aria-hidden>🧱</span>
          {guardrailPolicy.provider} guardrail policy · {guardrailPolicy.policy_name || "(unnamed)"}
          {guardrailPolicy.policy_id ? ` (${guardrailPolicy.policy_id})` : ""} · mode={guardrailPolicy.mode}
        </div>
      ) : null}
      <div className="stages">
        {DET_STAGES.map((s) => (
          <StageRow key={s.id} s={s} status={nodeStatus(s.id)} />
        ))}
      </div>
    </div>
  );
}

export function HandoffObjectCard({ handoff }: { handoff?: HandoffObject }) {
  if (!handoff) return null;
  return (
    <div className="handoff">
      <h3>
        <span aria-hidden>✓</span> Handoff object · {handoff.handoff_id}
      </h3>
      <p className="sub sub-zero-margin">
        Terminal action. The agent produced an auditable handoff — <strong>no money was moved</strong>.
      </p>
      <div className="flags">
        <span className="flag confirm">requires_confirmation: true</span>
        <span className="flag auth">requires_step_up_auth: true</span>
        <span className="flag nomoney">money_moved: false</span>
      </div>
      <JsonBlock data={handoff} />
    </div>
  );
}

// Identity-confirmation (EKYC) gate. Before any account tool runs, the customer
// must Confirm or Cancel. Cancelling is a bounded retry loop: after maxCancels
// cancels, the next cancel aborts the process (EKYC_FAILED). The agent never
// proceeds to account access without an explicit customer confirmation.
export function EkycGate({
  active,
  confirmed,
  failed,
  cancelCount,
  maxCancels,
  userId,
  onConfirm,
  onCancel,
}: {
  active: boolean;
  confirmed: boolean;
  failed: boolean;
  cancelCount: number;
  maxCancels: number;
  userId?: string;
  onConfirm(): void;
  onCancel(): void;
}) {
  if (!active && !failed && !confirmed) return null;

  if (failed) {
    return (
      <div className="hitlbar resolved rejected">
        <h3>
          <span aria-hidden>✕</span> EKYC failed · process cancelled
        </h3>
        <p>
          Identity confirmation was cancelled {cancelCount} times (more than the {maxCancels} allowed). The process has
          been cancelled — no account was accessed and no money was moved.
        </p>
      </div>
    );
  }

  if (confirmed && !active) {
    return (
      <div className="hitlbar resolved approved">
        <h3>
          <span aria-hidden>✓</span> Identity confirmed · EKYC passed
        </h3>
        <p>The customer confirmed their identity. The run resumes through the deterministic control flow.</p>
      </div>
    );
  }

  const attempt = cancelCount + 1;
  const totalAttempts = maxCancels + 1;
  const cancelsLeft = Math.max(0, maxCancels - cancelCount);
  return (
    <div className="hitlbar">
      <h3>
        <span aria-hidden>🪪</span> EKYC · customer identity confirmation required
      </h3>
      <p>
        Before any account tool runs, you must confirm your identity. Choose <strong>Confirm</strong> to proceed, or{" "}
        <strong>Cancel</strong> to abort. Cancelling more than {maxCancels} times cancels the process.
      </p>
      <div className="sub hitl-guidance">
        <div>
          <strong>Customer:</strong> {userId ?? "—"} · method=customer_confirmation
        </div>
        <div>
          <strong>Attempt:</strong> {attempt} of {totalAttempts}
          {cancelCount > 0 ? ` · cancelled ${cancelCount} · ${cancelsLeft} cancel(s) left` : ""}
        </div>
      </div>
      <div className="acts">
        <button className="btn ok" onClick={onConfirm}>
          ✓ Confirm identity
        </button>
        <button className="btn warn" onClick={onCancel}>
          ✕ Cancel
        </button>
      </div>
    </div>
  );
}

export function GuardrailBlockBanner({
  step,
  guardrailPolicy,
}: {
  step?: Step | null;
  guardrailPolicy?: GuardrailPolicyRef;
}) {
  return (
    <div className="blockbanner">
      <h3>
        <span aria-hidden>⛔</span> Guardrail block · deterministic
      </h3>
      <p>
        {step?.result ??
          "Unsafe directive cannot override the control policy. No tools invoked. No handoff created."}
      </p>
      {guardrailPolicy?.configured ? (
        <p>
          Enforced by {guardrailPolicy.provider} policy {guardrailPolicy.policy_name || "(unnamed)"}
          {guardrailPolicy.policy_id ? ` (${guardrailPolicy.policy_id})` : ""}.
        </p>
      ) : null}
    </div>
  );
}

// Human-in-the-loop approval gate for over-limit transfers. Mirrors the credit-
// memo HITL bar but with banking copy. The agent cannot self-approve — an
// authorized banker must decide before the over-limit transfer can execute.
export function TransferApprovalGate({
  active,
  resolved,
  decision,
  reason,
  amount,
  limit,
  currency,
  payeeName,
  onApprove,
  onReject,
}: {
  active: boolean;
  resolved: boolean;
  decision?: "approved" | "rejected" | null;
  reason?: string;
  amount: number;
  limit: number;
  currency: string;
  payeeName?: string;
  onApprove(reason?: string): void;
  onReject(reason: string): void;
}) {
  const [note, setNote] = useState("");
  const [rejectError, setRejectError] = useState<string | null>(null);

  if (!active && !resolved && !decision) return null;

  const fmt = (n: number) => n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  if (resolved || decision) {
    const approved = decision === "approved";
    return (
      <div className={`hitlbar resolved ${approved ? "approved" : "rejected"}`}>
        <h3>
          <span aria-hidden>{approved ? "✓" : "✕"}</span> {approved ? "Approved by banker" : "Rejected by banker"}
        </h3>
        <p>
          {approved
            ? "Banker approved the over-limit transfer. The workflow resumes and the handoff is released for step-up confirmation; the downstream core-banking system executes the transfer."
            : "Banker declined the over-limit transfer. No money is moved; the audited decline is logged with the reviewer reason."}
        </p>
        {reason ? (
          <p className="hitl-note-summary">
            <strong>Banker note:</strong> {reason}
          </p>
        ) : null}
      </div>
    );
  }

  return (
    <div className="hitlbar">
      <h3>
        <span aria-hidden>⛛</span> Human-in-the-loop · over-limit approval required
      </h3>
      <p>
        Azure AI Foundry agent workflow · the transfer exceeds the per-transaction limit, so the run is paused.
        The agent cannot self-approve — an authorized banker must decide.
      </p>
      <div className="sub hitl-guidance">
        <div>
          <strong>Amount:</strong> {fmt(amount)} {currency} {payeeName ? `→ ${payeeName}` : ""}
        </div>
        <div>
          <strong>Per-txn limit:</strong> {fmt(limit)} {currency} · over by {fmt(Math.max(0, amount - limit))} {currency}
        </div>
      </div>
      <div className="hitl-note-wrap">
        <label htmlFor="xfer-banker-note">Banker note (required for reject; optional for approve)</label>
        <textarea
          id="xfer-banker-note"
          className="hitl-note"
          value={note}
          onChange={(e) => {
            setNote(e.target.value);
            if (rejectError) setRejectError(null);
          }}
          rows={3}
          placeholder="Enter the banker's reason or note..."
        />
        {rejectError ? <div className="hitl-note-error">{rejectError}</div> : null}
      </div>
      <div className="acts">
        <button className="btn ok" onClick={() => onApprove(note.trim())}>
          ✓ Approve transfer
        </button>
        <button
          className="btn warn"
          onClick={() => {
            const trimmed = note.trim();
            if (!trimmed) {
              setRejectError("Please provide a rejection reason.");
              return;
            }
            onReject(trimmed);
          }}
        >
          ✕ Reject
        </button>
      </div>
    </div>
  );
}
