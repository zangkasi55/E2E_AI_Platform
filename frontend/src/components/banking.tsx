// =============================================================================
// components/banking.tsx — UC2 deterministic-control visuals. Probabilistic zone
// (intent/slot/conditional) sits ABOVE the deterministic boundary; the
// deterministic zone (APIM scope bar + tool stages + PDP + guardrails) sits
// below. Terminal action is an auditable HandoffObject — the agent moves NO
// money. POC_SPEC §UC2 hard rule.
// =============================================================================
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
  { id: "handoff", label: "request_transaction_handoff", role: "Terminal · auditable handoff", zone: "det" },
];

const SG: Record<string, string> = {
  intent_decomposition: "IN",
  slot_filling: "SL",
  conditional_eval: "IF",
  balance_lookup: "B",
  payee_resolution: "P",
  eligibility_check: "E",
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
