import { useCallback, useEffect, useState } from "react";

import type { AgentBinding, GovernancePayload } from "../lib/backend";
import type { DspmEvent } from "../lib/dspmEvents";
import { backend, USE_MOCK } from "../lib";
import { AppShell } from "../components/AppShell";
import { DspmEventsPanel } from "../components/DspmEventsPanel";

/** The nine governance / observability pillars wired to every agent. */
const PILLARS: ReadonlyArray<{ key: keyof Omit<AgentBinding, "agent" | "use_case">; label: string }> = [
  { key: "entra", label: "EntraID" },
  { key: "apim", label: "APIM" },
  { key: "guardrail", label: "Guardrail" },
  { key: "agent_workflow", label: "Agent workflow" },
  { key: "ai_foundry", label: "AI Foundry" },
  { key: "dspm", label: "DSPM" },
  { key: "purview", label: "Purview" },
  { key: "app_insights", label: "AppInsight" },
  { key: "foundry_observability", label: "Foundry Observability" },
];

function AgentWiringMatrix({ bindings }: { bindings: AgentBinding[] }) {
  if (!bindings || bindings.length === 0) return null;
  const totalCells = bindings.length * PILLARS.length;
  const wiredCells = bindings.reduce(
    (sum, b) => sum + PILLARS.filter((p) => b[p.key]?.configured).length,
    0,
  );
  return (
    <div className="panel">
      <h2>Per-agent wiring · {PILLARS.length} pillars</h2>
      <p className="sub">
        Every agent is bound to all {PILLARS.length} governance/observability pillars ·{" "}
        {wiredCells}/{totalCells} bindings configured.
      </p>
      <div className="matrix-scroll">
        <table className="table matrix-table">
          <thead>
            <tr>
              <th>Agent</th>
              <th>Use case</th>
              {PILLARS.map((p) => (
                <th key={p.key} className="matrix-col">{p.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {bindings.map((b) => (
              <tr key={b.agent}>
                <td className="matrix-agent">{b.agent}</td>
                <td><span className="sub">{b.use_case}</span></td>
                {PILLARS.map((p) => {
                  const ok = !!b[p.key]?.configured;
                  return (
                    <td key={p.key} className="matrix-cell">
                      <span
                        className={`matrix-dot ${ok ? "ok" : "off"}`}
                        title={`${b.agent} → ${p.label}: ${ok ? "configured" : "not configured"}`}
                      >
                        {ok ? "●" : "○"}
                      </span>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return iso;
  }
}

function PolicyCard({
  title,
  policy,
}: {
  title: string;
  policy: GovernancePayload["data_policy"] | GovernancePayload["security_policy"];
}) {
  const scope = Array.isArray(policy.scope) ? policy.scope : [];
  const controls = Array.isArray(policy.controls) ? policy.controls : [];

  return (
    <div className="panel">
      <h2>{title}</h2>
      <p className="sub">
        {(policy.name || "Unnamed policy")} · {(policy.platform || "unknown platform")}
      </p>
      <p className="sub">Owner: {policy.owner || "unassigned"}</p>
      <p className="sub">Scope: {scope.length > 0 ? scope.join(", ") : "not specified"}</p>
      <table className="table">
        <thead>
          <tr>
            <th>ID</th>
            <th>Control</th>
            <th>Requirement</th>
            <th>Capability</th>
          </tr>
        </thead>
        <tbody>
          {controls.map((control) => (
            <tr key={control.id}>
              <td>{control.id}</td>
              <td>{control.title}</td>
              <td>{control.requirement}</td>
              <td>{control.purview_capability ?? control.entra_capability ?? "-"}</td>
            </tr>
          ))}
          {controls.length === 0 ? (
            <tr>
              <td colSpan={4}>No controls reported by backend.</td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </div>
  );
}

export function GovernancePage() {
  const [data, setData] = useState<GovernancePayload | null>(null);
  const [events, setEvents] = useState<DspmEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [checkedAt, setCheckedAt] = useState<string | null>(null);

  const refresh = useCallback(() => {
    setLoading(true);
    setError(null);
    Promise.all([backend.getGovernance(), backend.getDspmEvents(50)])
      .then(([result, dspm]) => {
        setData(result);
        setEvents(dspm);
        setCheckedAt(new Date().toISOString());
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    refresh();
    const id = window.setInterval(refresh, 15000);
    return () => window.clearInterval(id);
  }, [refresh]);

  const configured = data ? data.component_wiring.filter((c) => c.configured).length : 0;
  const total = data ? data.component_wiring.length : 0;
  const source = USE_MOCK ? "mock backend" : "live FastAPI";

  return (
    <AppShell
      hero={{
        ucLabel: "Governance",
        crumb: "Governance",
        title: "Purview + EntraID Governance",
        subtitle:
          "Showcase data governance policy (Purview) and security policy (EntraID/APIM), plus live component wiring status from backend configuration.",
        tags: data ? [`${total} components`, `${configured}/${total} configured`, `source: ${source}`] : [],
      }}
    >
      <main className="page">
        <div className="panel statusbar">
          <div className="statusbar-meta">
            <span className="statusbar-title">Governance status</span>
            <span className="sub statusbar-when">
              {error
                ? `Refresh failed: ${error}`
                : checkedAt
                  ? `Last refreshed ${formatTime(checkedAt)} · source ${source}`
                  : "Loading…"}
            </span>
          </div>
          <button className="btn primary" type="button" onClick={refresh} disabled={loading}>
            {loading ? "Refreshing…" : "↻ Refresh"}
          </button>
        </div>

        <DspmEventsPanel events={events} />

        {!data ? (
          <div className="panel">
            <p className="sub">{error ? `Unable to load governance: ${error}` : "Loading governance policies…"}</p>
          </div>
        ) : (
          <>
            <div className="panel">
              <h2>Live wiring status</h2>
              <p className="sub">
                {configured}/{total} components configured · guardrail policy {data.guardrail_policy?.configured ? "active" : "not configured"}.
              </p>
              <div className="statuschips">
                {data.component_wiring.map((entry) => (
                  <span
                    key={entry.component}
                    className={`expect-pill ${entry.configured ? "demonstrated" : "unavailable"}`}
                  >
                    {entry.configured ? "● " : "○ "}
                    {entry.component}
                  </span>
                ))}
                <span className={`expect-pill ${data.guardrail_policy?.configured ? "demonstrated" : "unavailable"}`}>
                  {data.guardrail_policy?.configured ? "● " : "○ "}
                  {(data.guardrail_policy?.provider || "Guardrail")} · {(data.guardrail_policy?.mode || "unknown")}
                </span>
              </div>
            </div>

            {data.agent_bindings && data.agent_bindings.length > 0 ? (
              <AgentWiringMatrix bindings={data.agent_bindings} />
            ) : null}

            <PolicyCard title="Data Policy" policy={data.data_policy} />
            <PolicyCard title="Security Policy" policy={data.security_policy} />

            <div className="panel">
              <h2>Component Wiring Status</h2>
              <p className="sub">Backend-reported connectivity/configuration snapshot.</p>
              <table className="table">
                <thead>
                  <tr>
                    <th>Component</th>
                    <th>Status</th>
                    <th>Details</th>
                  </tr>
                </thead>
                <tbody>
                  {data.component_wiring.map((entry) => (
                    <tr key={entry.component}>
                      <td>{entry.component}</td>
                      <td>
                        <span className={`expect-pill ${entry.configured ? "demonstrated" : "unavailable"}`}>
                          {entry.configured ? "configured" : "missing config"}
                        </span>
                      </td>
                      <td>
                        {Object.entries(entry.details)
                          .filter(([, value]) => !!value)
                          .map(([key, value]) => `${key}: ${value}`)
                          .join(" | ") || "-"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </main>
    </AppShell>
  );
}
