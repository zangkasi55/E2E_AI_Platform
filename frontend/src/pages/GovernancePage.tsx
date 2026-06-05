import { useCallback, useEffect, useState } from "react";

import type { GovernancePayload } from "../lib/backend";
import type { DspmEvent } from "../lib/dspmEvents";
import { backend, USE_MOCK } from "../lib";
import { AppShell } from "../components/AppShell";
import { DspmEventsPanel } from "../components/DspmEventsPanel";

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
  return (
    <div className="panel">
      <h2>{title}</h2>
      <p className="sub">
        {policy.name} · {policy.platform}
      </p>
      <p className="sub">Owner: {policy.owner}</p>
      <p className="sub">Scope: {policy.scope.join(", ")}</p>
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
          {policy.controls.map((control) => (
            <tr key={control.id}>
              <td>{control.id}</td>
              <td>{control.title}</td>
              <td>{control.requirement}</td>
              <td>{control.purview_capability ?? control.entra_capability ?? "-"}</td>
            </tr>
          ))}
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
                {configured}/{total} components configured · guardrail policy {data.guardrail_policy.configured ? "active" : "not configured"}.
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
                <span className={`expect-pill ${data.guardrail_policy.configured ? "demonstrated" : "unavailable"}`}>
                  {data.guardrail_policy.configured ? "● " : "○ "}
                  {data.guardrail_policy.provider} guardrail · {data.guardrail_policy.mode}
                </span>
              </div>
            </div>

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
