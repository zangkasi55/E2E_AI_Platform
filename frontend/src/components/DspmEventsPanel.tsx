// =============================================================================
// components/DspmEventsPanel.tsx — shared Microsoft Purview DSPM-for-AI activity
// panel. Renders sensitivity-label / DLP events from the credit-memo upload gate
// plus risky-prompt / prompt-injection blocks from the conversational-banking
// guardrail. Used on the Governance page (full table) and on the Credit Memo /
// Banking right rails (compact list). When `events` is not supplied the panel
// self-fetches from the backend and polls every 15s.
// =============================================================================
import { useCallback, useEffect, useRef, useState } from "react";

import { backend } from "../lib";
import type { DspmEvent } from "../lib/dspmEvents";

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return iso;
  }
}

function eventLabel(ev: DspmEvent): string {
  if (ev.event_type === "prompt_injection_block") return "Risky prompt";
  if (ev.event_type === "dlp_block") return "DLP block";
  return "Label scan";
}

function classificationOf(ev: DspmEvent): string {
  return ev.risk_category || ev.label_full_name || ev.label || "—";
}

function sourceOf(ev: DspmEvent): string {
  const isPrompt = ev.event_type === "prompt_injection_block";
  return (isPrompt ? ev.prompt_preview : ev.file_name) || ev.use_case;
}

function promptDetectorOf(ev: DspmEvent): string {
  if (ev.event_type !== "prompt_injection_block") return "";
  if (ev.detection_source === "azure_ai_foundry_guardrail") {
    const name = ev.guardrail_policy_name || ev.guardrail_policy_id || "Foundry policy";
    return `Detected by ${ev.guardrail_provider || "Azure AI Foundry"} (${name})`;
  }
  return "Detected by deterministic guardrail";
}

interface DspmEventsPanelProps {
  /** When provided, the panel renders these and does not self-fetch. */
  events?: DspmEvent[];
  /** Compact list layout for narrow right rails. Defaults to false (table). */
  compact?: boolean;
  /** Max events to fetch when self-fetching. */
  limit?: number;
}

export function DspmEventsPanel({ events: provided, compact = false, limit = 50 }: DspmEventsPanelProps) {
  const [fetched, setFetched] = useState<DspmEvent[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const selfFetch = provided === undefined;
  const liveRef = useRef(true);

  const load = useCallback(async () => {
    if (!selfFetch) return;
    setRefreshing(true);
    try {
      const evs = await backend.getDspmEvents(limit);
      if (liveRef.current) setFetched(evs);
    } finally {
      if (liveRef.current) setRefreshing(false);
    }
  }, [selfFetch, limit]);

  useEffect(() => {
    if (!selfFetch) return;
    liveRef.current = true;
    load();
    const id = window.setInterval(load, 15000);
    return () => {
      liveRef.current = false;
      window.clearInterval(id);
    };
  }, [selfFetch, load]);

  const events = provided ?? fetched;

  if (compact) {
    return (
      <div className="panel">
        <div className="dspm-head">
          <div className="rail-h">DSPM for AI · security events</div>
          {selfFetch ? (
            <button
              type="button"
              className="btn ghost dspm-refresh"
              onClick={() => load()}
              disabled={refreshing}
              title="Refresh DSPM events now"
            >
              {refreshing ? "⟳ Refreshing…" : "⟳ Refresh"}
            </button>
          ) : null}
        </div>
        <p className="sub sub-tight-top">
          Live Microsoft Purview DSPM-for-AI log: document label/DLP scans and risky-prompt guardrail blocks.
        </p>
        {events.length === 0 ? (
          <p className="sub">No data-security events recorded yet.</p>
        ) : (
          <ul className="dspm-compact">
            {events.map((ev) => {
              const isPrompt = ev.event_type === "prompt_injection_block";
              return (
                <li key={ev.id} className={`dspm-c-item ${ev.decision}`}>
                  <div className="dspm-c-top">
                    <span className={`expect-pill ${isPrompt ? "unavailable" : "demonstrated"}`}>{eventLabel(ev)}</span>
                    <span className={`dspm-sev ${ev.severity}`}>{ev.severity}</span>
                    <span className="dspm-c-time">{formatTime(ev.ts)}</span>
                  </div>
                  <div className="dspm-c-class">{classificationOf(ev)}</div>
                  <div className={isPrompt ? "dspm-c-src dspm-prompt" : "dspm-c-src"}>{sourceOf(ev)}</div>
                  {isPrompt ? <div className="dspm-c-class">{promptDetectorOf(ev)}</div> : null}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    );
  }

  return (
    <div className="panel">
      <div className="dspm-head">
        <h2>DSPM for AI · data security events</h2>
        {selfFetch ? (
          <button
            type="button"
            className="btn ghost dspm-refresh"
            onClick={() => load()}
            disabled={refreshing}
            title="Refresh DSPM events now"
          >
            {refreshing ? "⟳ Refreshing…" : "⟳ Refresh"}
          </button>
        ) : null}
      </div>
      <p className="sub">
        Microsoft Purview DSPM for AI activity log (latest 10 events · scroll for more). Captures
        sensitivity-label scans and DLP blocks from the credit-memo upload gate, plus{" "}
        <strong>risky-prompt / prompt-injection attempts</strong> rejected by the conversational-banking
        guardrail before any tool call. Blocked events are also logged to Microsoft Defender for Cloud
        (AI workloads).
      </p>
      {events.length === 0 ? (
        <p className="sub">No data-security events recorded yet.</p>
      ) : (
        <div className="dspm-table-scroll">
          <table className="table">
            <thead>
              <tr>
                <th>Time</th>
                <th>Event</th>
                <th>Decision</th>
                <th>Severity</th>
                <th>Risk / classification</th>
                <th>Source</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {events.slice(0, 10).map((ev) => {
                const isPrompt = ev.event_type === "prompt_injection_block";
                return (
                  <tr key={ev.id}>
                    <td>{formatTime(ev.ts)}</td>
                    <td>
                      <span className={`expect-pill ${isPrompt ? "unavailable" : "demonstrated"}`}>{eventLabel(ev)}</span>
                    </td>
                    <td>
                      <span className={`expect-pill ${ev.decision === "blocked" ? "unavailable" : "demonstrated"}`}>
                        {ev.decision === "blocked" ? "● blocked" : "● allowed"}
                      </span>
                    </td>
                    <td>
                      <span className={`dspm-sev ${ev.severity}`}>{ev.severity}</span>
                    </td>
                    <td>{classificationOf(ev)}</td>
                    <td className={isPrompt ? "dspm-prompt" : undefined}>{sourceOf(ev)}</td>
                    <td>
                      {ev.detail}
                      {isPrompt ? <div className="sub">{promptDetectorOf(ev)}</div> : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
