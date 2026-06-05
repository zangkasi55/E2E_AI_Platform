// =============================================================================
// components/primitives.tsx — small shared leaf components used across pages:
// Badge, StatusChip, AnimatedNumber (token tick-up), JsonBlock (dark code).
// =============================================================================
import { useEffect, useRef, useState } from "react";
import type { AgentStatus } from "../types";

type BadgeVariant = "tool" | "apim" | "model" | "data" | "none" | "hitl" | "blocked";

export function Badge({ variant, children }: { variant: BadgeVariant; children: React.ReactNode }) {
  return <span className={`badge b-${variant}`}>{children}</span>;
}

const CHIP_TEXT: Record<AgentStatus, string> = {
  pending: "pending",
  working: "working…",
  done: "done",
  blocked: "blocked",
};

export function StatusChip({ status }: { status: AgentStatus }) {
  return (
    <span className={`chip ${status}`} aria-label={`status: ${CHIP_TEXT[status]}`}>
      {status === "working" && <span className="dt" aria-hidden />}
      {status === "done" && <span aria-hidden>✓</span>}
      {status === "blocked" && <span aria-hidden>⛔</span>}
      {CHIP_TEXT[status]}
    </span>
  );
}

/** Eases an integer value up to `value` for the live token counters. */
export function AnimatedNumber({ value, className }: { value: number; className?: string }) {
  const [shown, setShown] = useState(value);
  const from = useRef(value);
  const raf = useRef<number | null>(null);

  useEffect(() => {
    const start = performance.now();
    const a = from.current;
    const b = value;
    const dur = 550;
    if (raf.current) cancelAnimationFrame(raf.current);
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / dur);
      const eased = 1 - Math.pow(1 - t, 3);
      setShown(Math.round(a + (b - a) * eased));
      if (t < 1) raf.current = requestAnimationFrame(tick);
      else from.current = b;
    };
    raf.current = requestAnimationFrame(tick);
    return () => {
      if (raf.current) cancelAnimationFrame(raf.current);
    };
  }, [value]);

  return <span className={`tnum ${className ?? ""}`}>{shown.toLocaleString()}</span>;
}

/** Syntax-highlighted dark JSON panel for params / handoff objects. */
export function JsonBlock({ data }: { data: unknown }) {
  const json = JSON.stringify(data, null, 2);
  const html = json
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/"(\\.|[^"\\])*"(\s*:)?/g, (m, _g, colon) =>
      colon ? `<span class="k">${m}</span>` : `<span class="s">${m}</span>`,
    )
    .replace(/\b(-?\d+(?:\.\d+)?)\b/g, '<span class="n">$1</span>')
    .replace(/\b(true|false|null)\b/g, '<span class="b">$1</span>');
  return <pre className="jsonblock" dangerouslySetInnerHTML={{ __html: html }} />;
}
