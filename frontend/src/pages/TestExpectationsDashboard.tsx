import { useCallback, useEffect, useState } from "react";

import { AppShell } from "../components/AppShell";
import { pendingLiveStatus, probeLiveStatus } from "../lib/liveStatus";
import type { LiveExpectation, LiveStatus, LiveStatusReport } from "../lib/liveStatus";

function statusClass(status: LiveStatus): string {
  if (status === "Demonstrated") return "expect-pill demonstrated";
  if (status === "Mocked") return "expect-pill mocked";
  if (status === "Documented") return "expect-pill documented";
  if (status === "Probing") return "expect-pill probing";
  return "expect-pill unavailable";
}

function countStatus(items: LiveExpectation[], status: LiveStatus): number {
  return items.filter((item) => item.status === status).length;
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return iso;
  }
}

function ExpectationTable({
  title,
  sub,
  head,
  items,
  prefix,
}: {
  title: string;
  sub: string;
  head: string;
  items: LiveExpectation[];
  prefix: string;
}) {
  return (
    <div className="panel">
      <h2>{title}</h2>
      <p className="sub">{sub}</p>
      <table className="table">
        <thead>
          <tr>
            <th>#</th>
            <th>{head}</th>
            <th>Status</th>
            <th>Live evidence</th>
          </tr>
        </thead>
        <tbody>
          {items.length === 0 ? (
            <tr>
              <td colSpan={4} className="sub">No data yet — press Refresh to probe the backend.</td>
            </tr>
          ) : (
            items.map((item) => (
              <tr key={`${prefix}-${item.id}`}>
                <td className="num">{item.id}</td>
                <td>{item.item}</td>
                <td>
                  <span className={statusClass(item.status)}>{item.status}</span>
                </td>
                <td>{item.where}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

export function TestExpectationsDashboard() {
  const [report, setReport] = useState<LiveStatusReport>(() => pendingLiveStatus());
  const [probed, setProbed] = useState(false);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(() => {
    setLoading(true);
    probeLiveStatus()
      .then((r) => {
        setReport(r);
        setProbed(true);
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const minExpected = report?.minExpected ?? [];
  const assessment = report?.assessment ?? [];
  const minDemonstrated = countStatus(minExpected, "Demonstrated");
  const assDemonstrated = countStatus(assessment, "Demonstrated");
  const unavailableTotal = countStatus(minExpected, "Unavailable") + countStatus(assessment, "Unavailable");
  const mockedTotal = countStatus(minExpected, "Mocked") + countStatus(assessment, "Mocked");
  const documentedTotal = countStatus(minExpected, "Documented") + countStatus(assessment, "Documented");

  return (
    <AppShell
      hero={{
        crumb: "Test Expectations",
        title: "Test Expectations Dashboard",
        subtitle:
          "Live conformance view. Each customer minimum expectation and assessment criterion is checked against real backend payloads (governance, UC1/UC2 runs, token records) and refreshed on demand.",
        tags: report ? [`source: ${report.source}`, report.error ? "probe error" : "live probe"] : ["live probe"],
      }}
    >
      <main className="page">
        <div className="panel statusbar">
          <div className="statusbar-meta">
            <span className="statusbar-title">Conformance status</span>
            <span className="sub statusbar-when">
              {report?.error
                ? `Probe failed: ${report.error}`
                : loading
                  ? "Probing backend…"
                  : probed
                    ? `Last checked ${formatTime(report.checkedAt)} · source ${report.source}`
                    : "Probing backend…"}
            </span>
          </div>
          <button className="btn primary" type="button" onClick={refresh} disabled={loading}>
            {loading ? "Refreshing…" : "↻ Refresh"}
          </button>
        </div>

        <div className="kpis">
          <div className="kpi total">
            <div className="klab">Minimum Items Demonstrated</div>
            <div className="kval tnum">{minDemonstrated}/{minExpected.length || 0}</div>
          </div>
          <div className="kpi">
            <div className="klab">Assessment Demonstrated</div>
            <div className="kval tnum">{assDemonstrated}/{assessment.length || 0}</div>
          </div>
          <div className="kpi cost">
            <div className="klab">Unavailable / Mocked</div>
            <div className="kval tnum">{unavailableTotal + mockedTotal}</div>
          </div>
          <div className="kpi">
            <div className="klab">Documented Items</div>
            <div className="kval tnum">{documentedTotal}</div>
          </div>
        </div>

        <ExpectationTable
          title="Minimum Expected Implementation"
          sub="Customer minimum items checked against live PoC evidence."
          head="Expectation"
          items={minExpected}
          prefix="min"
        />

        <ExpectationTable
          title="Assessment Criteria"
          sub="How this PoC should be evaluated in demos and reviews — verified live."
          head="Criterion"
          items={assessment}
          prefix="ass"
        />
      </main>
    </AppShell>
  );
}
