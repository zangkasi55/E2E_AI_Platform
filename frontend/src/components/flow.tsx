// =============================================================================
// components/flow.tsx — UC1 live pipeline. ParentAgentBanner (memo_orchestrator)
// + an <ol> of AgentNode rows (doc_retrieval, financial_ratio, bureau_summary,
// memo_assembler, HITL gate, final memo). The headline behavior: the working
// node is unmistakable (colored fill + glow + blinking chip); done = green +
// check; pending = dimmed. POC_SPEC §1 headline requirement.
// =============================================================================
import type { AgentRoster, AgentStatus } from "../types";
import { StatusChip } from "./primitives";

const GLYPH: Record<string, string> = {
  memo_orchestrator: "MO",
  doc_retrieval: "DR",
  financial_ratio: "FR",
  bureau_summary: "BS",
  memo_assembler: "MA",
  hitl: "⛛",
  final: "✓",
};

export function ParentAgentBanner({ status }: { status: AgentStatus }) {
  return (
    <div className={`parentbanner ${status === "working" ? "working" : ""}`}>
      <span className="pa-icon" aria-hidden>
        MO
      </span>
      <div className="pa-meta">
        <strong>memo_orchestrator</strong>
        <div>Parent orchestrator · plans &amp; dispatches sub-agents · Durable Functions</div>
      </div>
      <div style={{ marginLeft: "auto" }}>
        <StatusChip status={status} />
      </div>
    </div>
  );
}

interface AgentNodeProps {
  id: string;
  label: string;
  role: string;
  status: AgentStatus;
  variant?: "subagent" | "parent" | "hitl" | "final";
  onClick?: (id: string) => void;
}

export function AgentNode({ id, label, role, status, variant = "subagent", onClick }: AgentNodeProps) {
  const cls = ["node", variant === "hitl" ? "hitl" : "", variant === "final" ? "final" : "", status].
    filter(Boolean).
    join(" ");
  const interactive = typeof onClick === "function";
  return (
    <li
      className={`${cls}${interactive ? " clickable" : ""}`}
      aria-current={status === "working" ? "step" : undefined}
      aria-label={`${label}: ${status}`}
      onClick={interactive ? () => onClick(id) : undefined}
      onKeyDown={
        interactive
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onClick(id);
              }
            }
          : undefined
      }
      role={interactive ? "button" : undefined}
      tabIndex={interactive ? 0 : undefined}
    >
      <span className="glyph" aria-hidden>
        {GLYPH[id] ?? label.slice(0, 2).toUpperCase()}
      </span>
      <div className="meta">
        <div className="nm">{label}</div>
        <div className="role">{role}</div>
      </div>
      <StatusChip status={status} />
    </li>
  );
}

export function AgentFlowGraph({
  agents,
  nodeStatus,
  onNodeClick,
}: {
  agents: AgentRoster[];
  nodeStatus: (id: string) => AgentStatus;
  onNodeClick?: (id: string) => void;
}) {
  const subAgents = agents.filter((a) => !a.parent);
  const parent = agents.find((a) => a.parent);
  return (
    <div>
      {parent && <ParentAgentBanner status={nodeStatus(parent.id)} />}
      <ol className="flow">
        {subAgents.map((a) => (
          <AgentNode key={a.id} id={a.id} label={a.label} role={a.role} status={nodeStatus(a.id)} onClick={onNodeClick} />
        ))}
        <AgentNode
          id="hitl"
          label="Human review gate"
          role="HITL · reviewer approves or rejects with reason"
          status={nodeStatus("hitl")}
          variant="hitl"
        />
        <AgentNode
          id="final"
          label="Final audited memo"
          role="Durable Functions resume · committed to Cosmos"
          status={nodeStatus("final")}
          variant="final"
        />
      </ol>
    </div>
  );
}
