// =============================================================================
// components/charts.tsx — dependency-free inline-SVG charts for the token
// dashboard: horizontal bar chart (tokens by agent) + donut (tokens by model).
// role="img" + aria-label per POC_SPEC §6 accessibility.
// =============================================================================
import { colors, modelColor } from "../theme";
import type { ModelId } from "../types";

const AGENT_COLORS: Record<string, string> = {
  memo_orchestrator: colors.agent,
  doc_retrieval: colors.agent2,
  financial_ratio: colors.model,
  bureau_summary: colors.tool,
  memo_assembler: colors.gov,
  intent_decomposition: colors.agent,
  slot_filling: colors.agent2,
  conditional_eval: colors.sec,
  handoff: colors.tool,
};

function colorFor(key: string, i: number): string {
  return AGENT_COLORS[key] ?? [colors.agent, colors.agent2, colors.model, colors.tool, colors.gov, colors.obs][i % 6];
}

export function TokensByAgentChart({ data }: { data: Record<string, number> }) {
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]);
  const max = Math.max(1, ...entries.map(([, v]) => v));
  const rowH = 30;
  const w = 520;
  const labelW = 150;
  const h = entries.length * rowH + 8;
  const summary = entries.map(([k, v]) => `${k}: ${v.toLocaleString()} tokens`).join("; ");
  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      width="100%"
      role="img"
      aria-label={`Tokens by agent. ${summary}`}
      style={{ display: "block" }}
    >
      {entries.map(([k, v], i) => {
        const y = i * rowH + 4;
        const barW = ((w - labelW - 70) * v) / max;
        return (
          <g key={k}>
            <text x={0} y={y + 16} fontSize={11.5} fill={colors.ink} fontFamily="Segoe UI, sans-serif">
              {k}
            </text>
            <rect x={labelW} y={y + 5} width={w - labelW - 70} height={14} rx={4} fill="#eef2f7" />
            <rect x={labelW} y={y + 5} width={Math.max(2, barW)} height={14} rx={4} fill={colorFor(k, i)} />
            <text
              x={labelW + Math.max(2, barW) + 6}
              y={y + 16}
              fontSize={11}
              fill={colors.muted}
              fontFamily="Segoe UI, sans-serif"
            >
              {v.toLocaleString()}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

export function TokensByModelDonut({ data }: { data: Record<string, number> }) {
  const entries = Object.entries(data) as [ModelId, number][];
  const total = entries.reduce((s, [, v]) => s + v, 0) || 1;
  const R = 60;
  const C = 2 * Math.PI * R;
  let offset = 0;
  const summary = entries.map(([k, v]) => `${k}: ${((v / total) * 100).toFixed(0)}%`).join("; ");
  return (
    <div>
      <svg viewBox="0 0 160 160" width="160" height="160" role="img" aria-label={`Tokens by model. ${summary}`}>
        <g transform="translate(80,80) rotate(-90)">
          <circle r={R} fill="none" stroke="#eef2f7" strokeWidth={22} />
          {entries.map(([k, v]) => {
            const frac = v / total;
            const dash = frac * C;
            const el = (
              <circle
                key={k}
                r={R}
                fill="none"
                stroke={modelColor(k)}
                strokeWidth={22}
                strokeDasharray={`${dash} ${C - dash}`}
                strokeDashoffset={-offset}
              />
            );
            offset += dash;
            return el;
          })}
        </g>
        <text x="80" y="78" textAnchor="middle" fontSize="13" fontWeight={800} fill={colors.ink}>
          {total.toLocaleString()}
        </text>
        <text x="80" y="94" textAnchor="middle" fontSize="9.5" fill={colors.muted}>
          total tokens
        </text>
      </svg>
      <div className="legend">
        {entries.map(([k, v]) => (
          <div className="li" key={k}>
            <span className="sw" style={{ background: modelColor(k) }} />
            <span>
              {k} · {v.toLocaleString()} ({((v / total) * 100).toFixed(0)}%)
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
