// =============================================================================
// hooks/useRunPlayer.ts — the central run state machine (the prototype's
// AGPOC.player). Walks an ordered Step[] on a timer or one step at a time,
// accumulates token totals + audit records, pauses at the HITL gate, and
// resumes to the final step on approve(). Pure reducer → panels render state.
// =============================================================================
import { useCallback, useEffect, useMemo, useReducer, useRef } from "react";
import type {
  AgentStatus,
  HandoffObject,
  RunDef,
  RunStatus,
  Step,
  TokenRecord,
} from "../types";
import { estCost } from "../theme";

const TICK_MS = 1900;
// EKYC identity gate: the customer may Cancel up to this many times; the next
// cancel aborts the run (EKYC_FAILED). Mirrors the backend banking controller
// (MAX_EKYC_CANCELS).
const MAX_EKYC_CANCELS = 2;

export interface AuditEntry {
  step: number;
  kind: "plan" | "tool" | "hitl" | "block" | "sec";
  text: string;
}

interface TokenTotals {
  prompt: number;
  completion: number;
  total: number;
  cost: number;
}

interface PlayerState {
  run: RunDef | null;
  index: number; // -1 = not started; else last-executed step index
  status: RunStatus;
  tokens: TokenTotals;
  records: TokenRecord[];
  audit: AuditEntry[];
  handoff?: HandoffObject;
  blocked: boolean;
  approved: boolean;
  hitlDecision: "approved" | "rejected" | null;
  hitlReason: string;
  // EKYC identity gate.
  ekycCancelCount: number;
  ekycConfirmed: boolean;
  ekycFailed: boolean;
}

type Action =
  | { type: "load"; run: RunDef }
  | { type: "advance" }
  | { type: "play" }
  | { type: "pause" }
  | { type: "reset" }
  | { type: "approve"; reason?: string }
  | { type: "reject"; reason: string }
  | { type: "ekyc_confirm" }
  | { type: "ekyc_cancel" };

const EMPTY_TOTALS: TokenTotals = { prompt: 0, completion: 0, total: 0, cost: 0 };

function initialState(run: RunDef | null): PlayerState {
  return {
    run,
    index: -1,
    status: "ready",
    tokens: EMPTY_TOTALS,
    records: [],
    audit: [],
    handoff: undefined,
    blocked: false,
    approved: false,
    hitlDecision: null,
    hitlReason: "",
    ekycCancelCount: 0,
    ekycConfirmed: false,
    ekycFailed: false,
  };
}

function auditKind(s: Step): AuditEntry["kind"] {
  if (s.blocked) return "block";
  if (s.hitl) return "hitl";
  if (s.phase === "plan") return "plan";
  if (s.tool) return "tool";
  return "sec";
}

// Apply one step's effects (tokens, audit, handoff) on top of prior state.
function applyStep(state: PlayerState, s: Step): PlayerState {
  const audit = [...state.audit, { step: s.step, kind: auditKind(s), text: s.audit }];
  let tokens = state.tokens;
  let records = state.records;
  if (s.tokens && s.model && state.run) {
    const total = s.tokens.prompt + s.tokens.completion;
    const cost = estCost(s.model, s.tokens.prompt, s.tokens.completion);
    tokens = {
      prompt: state.tokens.prompt + s.tokens.prompt,
      completion: state.tokens.completion + s.tokens.completion,
      total: state.tokens.total + total,
      cost: +(state.tokens.cost + cost).toFixed(5),
    };
    records = [
      ...state.records,
      {
        run_id: state.run.run_id,
        agent: s.stage ?? s.agent,
        step: s.step,
        model: s.model,
        prompt_tokens: s.tokens.prompt,
        completion_tokens: s.tokens.completion,
        total_tokens: total,
        est_cost_usd: cost,
        ts: new Date().toISOString(),
        use_case: state.run.use_case,
      },
    ];
  }
  return {
    ...state,
    tokens,
    records,
    audit,
    handoff: s.handoff ?? state.handoff,
    blocked: state.blocked || !!s.blocked,
  };
}

function reducer(state: PlayerState, action: Action): PlayerState {
  switch (action.type) {
    case "load":
      return initialState(action.run);

    case "reset":
      return initialState(state.run);

    case "play":
      if (!state.run || state.status === "done" || state.status === "blocked") return state;
      if (state.status === "awaiting_approval" || state.status === "awaiting_ekyc") return state;
      return { ...state, status: "playing" };

    case "pause":
      if (state.status === "playing") return { ...state, status: "paused" };
      return state;

    case "advance": {
      if (!state.run) return state;
      const next = state.index + 1;
      const steps = state.run.steps;
      if (next >= steps.length) return { ...state, status: "done" };
      const step = steps[next];
      const applied = applyStep({ ...state, index: next }, step);

      // Terminal / gating states.
      if (step.blocked) return { ...applied, status: "blocked" };
      if (step.ekyc) return { ...applied, status: "awaiting_ekyc" };
      if (step.hitl) return { ...applied, status: "awaiting_approval" };
      if (next === steps.length - 1) return { ...applied, status: "done" };
      return { ...applied, status: state.status === "paused" ? "paused" : "playing" };
    }

    case "approve": {
      if (state.status !== "awaiting_approval") return state;
      const reason = (action.reason ?? "").trim();
      const audit = [
        ...state.audit,
        {
          step: state.index >= 0 && state.run?.steps[state.index] ? state.run.steps[state.index].step : 0,
          kind: "hitl" as const,
          text: reason
            ? `HITL decision=APPROVE · reviewer_note=${reason}`
            : "HITL decision=APPROVE",
        },
      ];
      return {
        ...state,
        approved: true,
        status: "playing",
        hitlDecision: "approved",
        hitlReason: reason,
        audit,
      };
    }

    case "reject": {
      if (state.status !== "awaiting_approval") return state;
      const reason = action.reason.trim();
      if (!reason) return state;
      const audit = [
        ...state.audit,
        {
          step: state.index >= 0 && state.run?.steps[state.index] ? state.run.steps[state.index].step : 0,
          kind: "hitl" as const,
          text: `HITL decision=REJECT · reviewer_reason=${reason}`,
        },
      ];
      // A rejection is still a decision that must be recorded: the final
      // "audited memo" step commits the DECLINED outcome to Cosmos exactly like
      // an approval. Rewrite the final node to reflect the logged decision,
      // then let the player advance into it so the node lights up and the
      // result is captured in the audit trail.
      let run = state.run;
      if (run) {
        const steps = run.steps.map((s) =>
          s.phase === "final"
            ? {
                ...s,
                title: "memo_orchestrator · finalize_memo (declined)",
                detail:
                  "Durable Functions resumes and commits the audited outcome — decision=DECLINED — with the reviewer signature. The rejection is logged; full audit trail persisted to Cosmos.",
                result: "final",
                audit: `hitl_resume (declined) · decision=REJECT · reviewer_reason=${reason} · committed`,
              }
            : s,
        );
        run = { ...run, steps };
      }
      return {
        ...state,
        run,
        approved: false,
        blocked: false,
        status: "playing",
        hitlDecision: "rejected",
        hitlReason: reason,
        audit,
      };
    }

    case "ekyc_confirm": {
      if (state.status !== "awaiting_ekyc") return state;
      const stepNo = state.index >= 0 && state.run?.steps[state.index] ? state.run.steps[state.index].step : 0;
      const audit = [
        ...state.audit,
        { step: stepNo, kind: "sec" as const, text: "EKYC decision=CONFIRM · identity confirmed · proceeding" },
      ];
      // Resume playback past the EKYC gate.
      return { ...state, status: "playing", ekycConfirmed: true, audit };
    }

    case "ekyc_cancel": {
      if (state.status !== "awaiting_ekyc") return state;
      const stepNo = state.index >= 0 && state.run?.steps[state.index] ? state.run.steps[state.index].step : 0;
      const nextCount = state.ekycCancelCount + 1;
      if (nextCount > MAX_EKYC_CANCELS) {
        // Cancelled more than the allowed number of times → abort the process.
        const audit = [
          ...state.audit,
          {
            step: stepNo,
            kind: "block" as const,
            text: `EKYC decision=CANCEL (#${nextCount}) · EKYC_FAILED · cancelled more than ${MAX_EKYC_CANCELS} times · process cancelled`,
          },
        ];
        return {
          ...state,
          status: "blocked",
          ekycCancelCount: nextCount,
          ekycFailed: true,
          blocked: true,
          audit,
        };
      }
      // Within the allowed retries → stay at the gate and ask again.
      const remaining = MAX_EKYC_CANCELS + 1 - nextCount;
      const audit = [
        ...state.audit,
        {
          step: stepNo,
          kind: "sec" as const,
          text: `EKYC decision=CANCEL (#${nextCount}) · ${remaining} attempt(s) left · awaiting confirmation`,
        },
      ];
      return { ...state, status: "awaiting_ekyc", ekycCancelCount: nextCount, audit };
    }

    default:
      return state;
  }
}

export interface RunPlayer {
  run: RunDef | null;
  index: number;
  status: RunStatus;
  current: Step | null;
  steps: Step[];
  tokens: TokenTotals;
  records: TokenRecord[];
  audit: AuditEntry[];
  handoff?: HandoffObject;
  blocked: boolean;
  approved: boolean;
  hitlDecision: "approved" | "rejected" | null;
  hitlReason: string;
  ekycCancelCount: number;
  ekycConfirmed: boolean;
  ekycFailed: boolean;
  /** agentId/stage → status, for pure flow-graph rendering. */
  nodeStatus: (nodeId: string) => AgentStatus;
  play(): void;
  pause(): void;
  step(): void;
  reset(): void;
  approve(reason?: string): void;
  reject(reason: string): void;
  ekycConfirm(): void;
  ekycCancel(): void;
}

/**
 * Resolve which flow-node a given step targets. UC1: plan→parent banner,
 * hitl→hitl node, final→final node, else the sub-agent. UC2: the stage id.
 */
export function nodeForStep(s: Step): string {
  if (s.zone || s.stage) return s.stage ?? s.agent; // UC2 stages keyed by stage id
  if (s.phase === "plan") return s.agent; // memo_orchestrator (parent)
  if (s.phase === "hitl") return "hitl";
  if (s.phase === "final") return "final";
  return s.agent;
}

export function useRunPlayer(run: RunDef | null): RunPlayer {
  const [state, dispatch] = useReducer(reducer, run, initialState);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  // Reload when a new run definition arrives.
  useEffect(() => {
    if (run) dispatch({ type: "load", run });
  }, [run?.run_id]); // eslint-disable-line react-hooks/exhaustive-deps

  // Drive the timer while playing.
  useEffect(() => {
    if (state.status === "playing") {
      timer.current = setInterval(() => dispatch({ type: "advance" }), TICK_MS);
      // advance immediately so the first node lights up without delay
      dispatch({ type: "advance" });
      return () => {
        if (timer.current) clearInterval(timer.current);
        timer.current = null;
      };
    }
    if (timer.current) {
      clearInterval(timer.current);
      timer.current = null;
    }
    return undefined;
  }, [state.status]);

  const play = useCallback(() => dispatch({ type: "play" }), []);
  const pause = useCallback(() => dispatch({ type: "pause" }), []);
  const step = useCallback(() => dispatch({ type: "advance" }), []);
  const reset = useCallback(() => dispatch({ type: "reset" }), []);
  const approve = useCallback((reason?: string) => dispatch({ type: "approve", reason }), []);
  const reject = useCallback((reason: string) => dispatch({ type: "reject", reason }), []);
  const ekycConfirm = useCallback(() => dispatch({ type: "ekyc_confirm" }), []);
  const ekycCancel = useCallback(() => dispatch({ type: "ekyc_cancel" }), []);

  const steps = state.run?.steps ?? [];
  const current = state.index >= 0 && state.index < steps.length ? steps[state.index] : null;

  const nodeStatus = useCallback(
    (nodeId: string): AgentStatus => {
      if (!state.run) return "pending";
      // Build the set of nodes that have already executed (<= index).
      let lastNodeOfActive: string | null = null;
      let executed = new Set<string>();
      for (let i = 0; i <= state.index && i < steps.length; i++) {
        const nid = nodeForStep(steps[i]);
        executed.add(nid);
        if (i === state.index) lastNodeOfActive = nid;
      }
      const activeStep = current;
      const isActiveNode = lastNodeOfActive === nodeId;

      if (isActiveNode) {
        if (activeStep?.blocked || state.status === "blocked") return "blocked";
        if (state.status === "done") return "done";
        // working while playing/paused/awaiting; the active node holds focus
        return state.status === "awaiting_approval" ||
          state.status === "awaiting_ekyc" ||
          state.status === "paused" ||
          state.status === "playing"
          ? "working"
          : "done";
      }
      if (executed.has(nodeId)) return "done";
      return "pending";
    },
    [state.run, state.index, state.status, steps, current],
  );

  return useMemo(
    () => ({
      run: state.run,
      index: state.index,
      status: state.status,
      current,
      steps,
      tokens: state.tokens,
      records: state.records,
      audit: state.audit,
      handoff: state.handoff,
      blocked: state.blocked,
      approved: state.approved,
      hitlDecision: state.hitlDecision,
      hitlReason: state.hitlReason,
      ekycCancelCount: state.ekycCancelCount,
      ekycConfirmed: state.ekycConfirmed,
      ekycFailed: state.ekycFailed,
      nodeStatus,
      play,
      pause,
      step,
      reset,
      approve,
      reject,
      ekycConfirm,
      ekycCancel,
    }),
    [state, current, steps, nodeStatus, play, pause, step, reset, approve, reject, ekycConfirm, ekycCancel],
  );
}
