// =============================================================================
// pages/TokenMonitorDashboard.tsx (/tokens) — reads the same TokenRecord[] the
// orchestrator writes to Cosmos `tokens`. 4 KPI cards + tokens-by-agent bar
// chart + tokens-by-model donut + per-run aggregation table. Stateless given
// the records (aggregate() is a pure function). POC_SPEC §Token monitoring.
// =============================================================================
import { useEffect, useMemo, useState } from "react";
import type { TokenRecord } from "../types";
import { backend } from "../lib";
import { aggregate } from "../data/mockData";
import { AppShell } from "../components/AppShell";
import { TokensByAgentChart, TokensByModelDonut } from "../components/charts";

export function TokenMonitorDashboard() {
  const [records, setRecords] = useState<TokenRecord[]>([]);
  useEffect(() => {
    let live = true;
    backend.getTokens().then((r) => live && setRecords(r));
    return () => {
      live = false;
    };
  }, []);

  const agg = useMemo(() => aggregate(records), [records]);
  const runs = useMemo(
    () => Object.values(agg.byRun).sort((a, b) => Date.parse(b.ts) - Date.parse(a.ts)),
    [agg],
  );

  return (
    <AppShell
      hero={{
        uc: "tokens",
        ucLabel: "Observability",
        crumb: "Token Monitor",
        title: "Token Usage Monitor",
        subtitle:
          "Every model call emits the App Insights metric gen_ai.token.usage and a record in Cosmos `tokens`. This dashboard aggregates prompt/completion/total tokens and estimated cost by agent, model, and run — the cost-governance view for the platform.",
        tags: [`${records.length} records`],
      }}
    >
      <main className="page">
        <div className="kpis">
          <div className="kpi total">
            <div className="klab">Total tokens</div>
            <div className="kval tnum">{agg.total.total.toLocaleString()}</div>
          </div>
          <div className="kpi cost">
            <div className="klab">Est. cost (USD)</div>
            <div className="kval tnum">${agg.total.cost.toFixed(4)}</div>
          </div>
          <div className="kpi">
            <div className="klab">Prompt tokens</div>
            <div className="kval tnum">{agg.total.prompt.toLocaleString()}</div>
          </div>
          <div className="kpi">
            <div className="klab">Completion tokens</div>
            <div className="kval tnum">{agg.total.completion.toLocaleString()}</div>
          </div>
        </div>

        <div className="charts">
          <div className="panel">
            <h2>Tokens by agent</h2>
            <p className="sub">Which agent/stage consumes the most — the per-consumer breakdown.</p>
            <TokensByAgentChart data={agg.byAgent} />
          </div>
          <div className="panel">
            <h2>Tokens by model</h2>
            <p className="sub">gpt-4o vs gpt-4o-mini share of total usage.</p>
            <TokensByModelDonut data={agg.byModel} />
          </div>
        </div>

        <div className="panel">
          <h2>Runs</h2>
          <p className="sub">Per-run aggregation. Newest first.</p>
          <table className="table">
            <thead>
              <tr>
                <th>Run</th>
                <th>Use case</th>
                <th>When</th>
                <th className="num">Calls</th>
                <th className="num">Tokens</th>
                <th className="num">Est. cost</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.run_id}>
                  <td style={{ fontFamily: "ui-monospace, Consolas, monospace" }}>{r.run_id}</td>
                  <td>
                    <span className={`pill ${r.use_case}`}>{r.use_case}</span>
                  </td>
                  <td>{new Date(r.ts).toLocaleString()}</td>
                  <td className="num">{r.calls}</td>
                  <td className="num">{r.tokens.toLocaleString()}</td>
                  <td className="num">${r.cost.toFixed(4)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </main>
    </AppShell>
  );
}
