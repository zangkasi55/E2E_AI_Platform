// =============================================================================
// components/panels.tsx — observability + control panels shared by UC1/UC2:
// RunControls, ToolCallCard, HITLApprovalBar, AuditTrailPanel, TokenCounter.
// =============================================================================
import type { ModelId, RunStatus, Step, ToolName } from "../types";
import { useState } from "react";
import { TOOLS } from "../data/mockData";
import { AnimatedNumber, Badge, JsonBlock } from "./primitives";
import type { AuditEntry } from "../hooks/useRunPlayer";

const STATUS_LABEL: Record<RunStatus, string> = {
  ready: "ready",
  playing: "playing",
  paused: "paused",
  awaiting_approval: "awaiting approval",
  awaiting_ekyc: "awaiting EKYC",
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
  allowReplayTerminal,
}: {
  status: RunStatus;
  onPlay(): void;
  onPause(): void;
  onStep(): void;
  onReset(): void;
  disabled?: boolean;
  allowReplayTerminal?: boolean;
}) {
  const playing = status === "playing";
  const terminal = status === "done" || status === "blocked";
  const gated = status === "awaiting_approval" || status === "awaiting_ekyc";
  const shouldDisable = !!disabled;
  const disablePlay = (terminal && !allowReplayTerminal) || gated || shouldDisable;
  return (
    <div className="controls">
      {playing ? (
        <button className="btn" onClick={onPause}>
          ⏸ Pause
        </button>
      ) : (
        <button className="btn primary" onClick={onPlay} disabled={disablePlay}>
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
  decision,
  reason,
  guidance,
  onApprove,
  onReject,
}: {
  active: boolean;
  resolved: boolean;
  decision?: "approved" | "rejected" | null;
  reason?: string;
  guidance?: {
    recommendation?: string;
    should_approve?: string[];
    should_not_approve?: string[];
  };
  onApprove(reason?: string): void;
  onReject(reason: string): void;
}) {
  const [note, setNote] = useState("");
  const [rejectError, setRejectError] = useState<string | null>(null);

  if (!active && !resolved && !decision) return null;
  if (resolved || decision) {
    const approved = decision === "approved";
    return (
      <div className={`hitlbar resolved ${approved ? "approved" : "rejected"}`}>
        <h3>
          <span aria-hidden>{approved ? "✓" : "✕"}</span> {approved ? "Approved by reviewer" : "Rejected by reviewer"}
        </h3>
        <p>
          {approved
            ? "Durable Functions resumed. The final memo is committed with a full audit trail."
            : "The reviewer declined the draft. Durable Functions resumed and the audited decision (DECLINED) was committed to Cosmos with a full audit trail."}
        </p>
        {reason ? (
          <p className="hitl-note-summary">
            <strong>Reviewer note:</strong> {reason}
          </p>
        ) : null}
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
              <strong>Reasons to reject:</strong> {guidance.should_not_approve.join("; ")}
            </div>
          ) : null}
        </div>
      ) : null}
      <div className="hitl-note-wrap">
        <label htmlFor="hitl-reviewer-note">Reviewer note (required for reject; optional for approve)</label>
        <textarea
          id="hitl-reviewer-note"
          className="hitl-note"
          value={note}
          onChange={(e) => {
            setNote(e.target.value);
            if (rejectError) setRejectError(null);
          }}
          rows={3}
          placeholder="Enter the human reviewer reason or note..."
        />
        {rejectError ? <div className="hitl-note-error">{rejectError}</div> : null}
      </div>
      <div className="acts">
        <button className="btn ok" onClick={() => onApprove(note.trim())}>
          ✓ Approve &amp; finalize
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
