// =============================================================================
// components/panels.tsx — observability + control panels shared by UC1/UC2:
// RunControls, ToolCallCard, HITLApprovalBar, AuditTrailPanel, TokenCounter.
// =============================================================================
import type { ModelId, RunStatus, Step, ToolName } from "../types";
import { TOOLS } from "../data/mockData";
import { AnimatedNumber, Badge, JsonBlock } from "./primitives";
import type { AuditEntry } from "../hooks/useRunPlayer";

const STATUS_LABEL: Record<RunStatus, string> = {
  ready: "ready",
  playing: "playing",
  paused: "paused",
  awaiting_approval: "awaiting approval",
  done: "done",
  blocked: "blocked",
};

export function RunControls({
  status,
  onPlay,
  onPause,
  onStep,
  onReset,
  disabled,
}: {
  status: RunStatus;
  onPlay(): void;
  onPause(): void;
  onStep(): void;
  onReset(): void;
  disabled?: boolean;
}) {
  const playing = status === "playing";
  const terminal = status === "done" || status === "blocked";
  const gated = status === "awaiting_approval";
  const shouldDisable = !!disabled;
  return (
    <div className="controls">
      {playing ? (
        <button className="btn" onClick={onPause}>
          ⏸ Pause
        </button>
      ) : (
        <button className="btn primary" onClick={onPlay} disabled={terminal || gated || shouldDisable}>
          ▶ Play
        </button>
      )}
      <button className="btn" onClick={onStep} disabled={terminal || gated || shouldDisable}>
        ⤼ Step
      </button>
      <button className="btn" onClick={onReset}>
        ↺ Reset
      </button>
      <span className={`runstatus ${status}`}>{STATUS_LABEL[status]}</span>
    </div>
  );
}

function modelVariant(model?: ModelId | null) {
  return model ? ("model" as const) : ("none" as const);
}

export function ToolCallCard({ step }: { step: Step | null }) {
  if (!step) {
    return (
      <div className="stepcard">
        <p className="audit-empty">Press Play to start the run. The current tool call appears here.</p>
      </div>
    );
  }
  const tool = step.tool as ToolName | null | undefined;
  const sig = tool ? TOOLS[tool]?.sig : undefined;
  return (
    <div className="stepcard">
      <div className="sc-head">
        <span className="sc-idx">STEP {step.step}</span>
        <span className="sc-title">{step.title}</span>
      </div>
      <div className="sc-head">
        <Badge variant="none">{step.stage ?? step.agent}</Badge>
        {step.model ? <Badge variant={modelVariant(step.model)}>{step.model}</Badge> : <Badge variant="none">no model</Badge>}
        {tool && (
          <Badge variant="tool">
            {tool}
            {sig ? <span className="sig">{sig}</span> : null}
          </Badge>
        )}
        {step.chainTool && <Badge variant="tool">+ {step.chainTool}</Badge>}
        {step.apim && <Badge variant="apim">via APIM · scope-checked</Badge>}
        {step.hitl && <Badge variant="hitl">HITL pause</Badge>}
        {step.blocked && <Badge variant="blocked">guardrail block</Badge>}
      </div>
      <div className="sc-detail">{step.detail}</div>
      {step.params && <JsonBlock data={step.params} />}
      <div className="sc-result">{step.result}</div>
    </div>
  );
}

export function HITLApprovalBar({
  active,
  resolved,
  guidance,
  onApprove,
  onRequestEdits,
}: {
  active: boolean;
  resolved: boolean;
  guidance?: {
    recommendation?: string;
    should_approve?: string[];
    should_not_approve?: string[];
  };
  onApprove(): void;
  onRequestEdits(): void;
}) {
  if (!active && !resolved) return null;
  if (resolved) {
    return (
      <div className="hitlbar resolved">
        <h3>
          <span aria-hidden>✓</span> Approved by reviewer
        </h3>
        <p>Durable Functions resumed. The final memo is committed with a full audit trail.</p>
      </div>
    );
  }
  return (
    <div className="hitlbar">
      <h3>
        <span aria-hidden>⛛</span> Human-in-the-loop · approval required
      </h3>
      <p>
        The workflow is paused. No memo is final without human approval. The agent drafts; the human decides.
      </p>
      {guidance ? (
        <div className="sub hitl-guidance">
          <div>
            <strong>Recommendation:</strong> {guidance.recommendation ?? "review"}
          </div>
          {guidance.should_approve?.length ? (
            <div>
              <strong>Reasons to approve:</strong> {guidance.should_approve.join("; ")}
            </div>
          ) : null}
          {guidance.should_not_approve?.length ? (
            <div>
              <strong>Reasons to request edits:</strong> {guidance.should_not_approve.join("; ")}
            </div>
          ) : null}
        </div>
      ) : null}
      <div className="acts">
        <button className="btn ok" onClick={onApprove}>
          ✓ Approve &amp; finalize
        </button>
        <button className="btn warn" onClick={onRequestEdits}>
          ✎ Request edits
        </button>
      </div>
    </div>
  );
}

const AUDIT_GLYPH: Record<AuditEntry["kind"], string> = {
  plan: "P",
  tool: "T",
  hitl: "H",
  block: "✕",
  sec: "S",
};

export function AuditTrailPanel({ audit }: { audit: AuditEntry[] }) {
  if (audit.length === 0) {
    return <p className="audit-empty">No audit records yet. Each step writes a structured record to Cosmos.</p>;
  }
  return (
    <ol className="audit">
      {audit.map((a, i) => (
        <li className={`arow ${a.kind}`} key={i}>
          <span className="ai" aria-hidden>
            {AUDIT_GLYPH[a.kind]}
          </span>
          <span className="at">{a.text}</span>
        </li>
      ))}
    </ol>
  );
}

export function TokenCounter({
  prompt,
  completion,
  total,
  cost,
  consumer,
  model,
}: {
  prompt: number;
  completion: number;
  total: number;
  cost: number;
  consumer?: string;
  model?: ModelId | null;
}) {
  return (
    <div>
      <div className="tgrid">
        <div className="tcell">
          <div className="tlab">Prompt</div>
          <div className="tval tnum">
            <AnimatedNumber value={prompt} />
          </div>
        </div>
        <div className="tcell">
          <div className="tlab">Completion</div>
          <div className="tval tnum">
            <AnimatedNumber value={completion} />
          </div>
        </div>
        <div className="tcell total">
          <div className="tlab">Total</div>
          <div className="tval tnum">
            <AnimatedNumber value={total} />
          </div>
        </div>
      </div>
      <div className="consumer">
        {model && <span className="dotm" aria-hidden />}
        <span>
          {consumer ?? "—"} {model ? `· ${model}` : ""}
        </span>
        <span style={{ marginLeft: "auto" }}>
          est. cost <span className="cost tnum">${cost.toFixed(4)}</span>
        </span>
      </div>
      <p className="sub" style={{ marginTop: 8, marginBottom: 0 }}>
        Each model call emits App Insights metric <code>gen_ai.token.usage</code> → Cosmos <code>tokens</code>.
      </p>
    </div>
  );
}
