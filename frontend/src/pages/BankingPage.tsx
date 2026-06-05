// =============================================================================
// pages/BankingPage.tsx (UC2) — owns useRunPlayer with a safe/unsafe toggle.
// Left column: mock chat thread + Send/Reset/Unsafe toggle, then the
// ProbabilisticZone, DeterministicBoundary, DeterministicZone, current
// ToolCallCard, and the terminal HandoffObjectCard (or GuardrailBlockBanner on
// the unsafe path). Right rail: audit trail + token counter.
// The agent moves NO money — the terminal artifact is a handoff object.
// =============================================================================
import { useEffect, useRef, useState } from "react";
import type { RunDef } from "../types";
import { backend } from "../lib";
import { recordPromptRiskEvent } from "../lib/dspmEvents";
import type { GovernancePayload } from "../lib/backend";
import { useRunPlayer } from "../hooks/useRunPlayer";
import { AppShell } from "../components/AppShell";
import { DspmEventsPanel } from "../components/DspmEventsPanel";
import {
  DeterministicBoundary,
  DeterministicZone,
  GuardrailBlockBanner,
  HandoffObjectCard,
  ProbabilisticZone,
} from "../components/banking";
import { AuditTrailPanel, RunControls, TokenCounter, ToolCallCard } from "../components/panels";
import {
  BANK_ACCOUNTS,
  INITIAL_BALANCES,
  buildBankingRun,
  defaultBankingMessage,
  formatTHB,
  randomUnsafeMessage,
} from "../data/bankingAccounts";
import type { TransferPlan } from "../data/bankingAccounts";

interface LedgerTxn {
  id: string;
  ts: string;
  fromAlias: string;
  toAlias: string;
  amount: number;
  status: "executed" | "denied" | "blocked";
  note: string;
}

export function BankingPage() {
  const [unsafe, setUnsafe] = useState(false);
  const [run, setRun] = useState<RunDef | null>(null);
  const [plan, setPlan] = useState<TransferPlan | null>(null);
  const [governance, setGovernance] = useState<GovernancePayload | null>(null);
  const [fromUserId, setFromUserId] = useState(BANK_ACCOUNTS[0].user_id);
  const [draftMessage, setDraftMessage] = useState(defaultBankingMessage());
  const [submittedMessage, setSubmittedMessage] = useState(defaultBankingMessage());

  // Simulated core-banking ledger: balances + transaction activity.
  const [balances, setBalances] = useState<Record<string, number>>({ ...INITIAL_BALANCES });
  const [txns, setTxns] = useState<LedgerTxn[]>([]);
  const balancesRef = useRef(balances);
  balancesRef.current = balances;
  const appliedRuns = useRef<Set<string>>(new Set());
  // Set when Play should auto-start playback after a freshly built run loads.
  const pendingPlay = useRef(false);

  const loadRun = (message: string, useUnsafe: boolean) => {
    setRun(null);
    const { run: built, plan: builtPlan } = buildBankingRun({
      message,
      fromUserId,
      unsafe: useUnsafe,
      balances: balancesRef.current,
    });
    setPlan(builtPlan);
    setRun(built);
  };

  // Build the default run once on mount.
  useEffect(() => {
    loadRun(defaultBankingMessage(), false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    let live = true;
    backend.getGovernance().then((g) => live && setGovernance(g));
    return () => {
      live = false;
    };
  }, []);

  const player = useRunPlayer(run);
  const c = player.current;

  // After Play rebuilds the run from the typed message, start playback once the
  // new run definition has loaded into the player.
  useEffect(() => {
    if (pendingPlay.current && run) {
      pendingPlay.current = false;
      player.play();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run?.run_id]);

  // When a run completes, post its outcome to the simulated ledger exactly once.
  useEffect(() => {
    if (!run || !plan) return;
    if (player.status !== "done" && player.status !== "blocked") return;
    if (appliedRuns.current.has(run.run_id)) return;
    appliedRuns.current.add(run.run_id);

    const ts = new Date().toISOString();
    const fromAlias = plan.sender.alias;
    const toAlias = plan.recipient?.alias ?? plan.recipientName ?? "—";
    const amt = plan.amount ?? 0;

    if (plan.outcome === "permit" && plan.recipient) {
      const recipient = plan.recipient;
      setBalances((prev) => ({
        ...prev,
        [plan.sender.user_id]: (prev[plan.sender.user_id] ?? 0) - amt,
        [recipient.user_id]: (prev[recipient.user_id] ?? 0) + amt,
      }));
      setTxns((prev) => [
        {
          id: plan.handoffId,
          ts,
          fromAlias,
          toAlias,
          amount: amt,
          status: "executed",
          note: "Transfer executed after step-up confirmation.",
        },
        ...prev,
      ]);
    } else if (plan.outcome === "deny_insufficient") {
      setTxns((prev) => [
        { id: plan.handoffId, ts, fromAlias, toAlias, amount: amt, status: "denied", note: "Denied — insufficient funds." },
        ...prev,
      ]);
    } else if (plan.outcome === "condition_failed") {
      setTxns((prev) => [
        { id: plan.handoffId, ts, fromAlias, toAlias, amount: amt, status: "denied", note: "Skipped — balance condition not met." },
        ...prev,
      ]);
    } else if (plan.outcome === "blocked") {
      // Record a Microsoft Purview DSPM-for-AI risky-prompt event so the blocked
      // injection attempt is auditable on the Governance page (same in-memory
      // store the Governance DSPM panel reads, and mirrors the live FastAPI path).
      recordPromptRiskEvent({
        run_id: run.run_id,
        prompt: submittedMessage,
        user: `${plan.sender.alias}@scbx.local`,
      });
      setTxns((prev) => [
        { id: plan.handoffId, ts, fromAlias, toAlias, amount: amt, status: "blocked", note: "Blocked — unsafe instruction rejected by guardrails." },
        ...prev,
      ]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [player.status, run?.run_id]);

  // Play now drives the run: it builds the run from the currently typed message
  // and starts playback. A paused run with an unchanged message simply resumes.
  const handlePlay = () => {
    const text = draftMessage.trim() || defaultBankingMessage();
    if (player.status === "paused" && text === submittedMessage) {
      player.play();
      return;
    }
    setSubmittedMessage(text);
    pendingPlay.current = true;
    loadRun(text, unsafe);
  };

  const onToggleUnsafe = (checked: boolean) => {
    setUnsafe(checked);
    if (checked) {
      // Generate a random unsafe prompt for the user to test the guardrails.
      const injected = randomUnsafeMessage();
      setDraftMessage(injected);
      loadRun(injected, true);
    } else {
      const restored = defaultBankingMessage();
      setDraftMessage(restored);
      loadRun(restored, false);
    }
  };

  const resetLedger = () => {
    setBalances({ ...INITIAL_BALANCES });
    setTxns([]);
    appliedRuns.current.clear();
  };

  return (
    <AppShell
      hero={{
        uc: "banking",
        ucLabel: "UC2 · Conversational Banking",
        crumb: "Banking",
        title: "Conversational Banking Control",
        subtitle:
          "Natural-language intents are reasoned about in a probabilistic zone, but every action crosses a deterministic boundary: tools run through APIM with scope enforcement and a Policy Decision Point. The agent never moves money — it produces an auditable handoff object that still requires confirmation and step-up auth.",
        tags: run ? [`run ${run.run_id}`, unsafe ? "unsafe path" : "happy path"] : [],
      }}
    >
      <main className="page">
        <div className="layout">
          <div className="col">
            <div className="panel">
              <h2>Customer conversation</h2>
              <p className="sub">A mock banking chat. Pick the account you are speaking as, type a request, then press Play to run it. Toggle the unsafe instruction to see deterministic guardrails block it.</p>
              <div className="chat">
                <div className="bubble user">{submittedMessage || defaultBankingMessage()}</div>
                {c && <div className="bubble agent">{c.result}</div>}
              </div>
              <div className="acctpick">
                <label htmlFor="fromAcct">From account</label>
                <select
                  id="fromAcct"
                  value={fromUserId}
                  onChange={(e) => setFromUserId(e.target.value)}
                  aria-label="From account"
                >
                  {BANK_ACCOUNTS.map((a) => (
                    <option key={a.user_id} value={a.user_id}>
                      {a.alias} · {a.display_name} ({formatTHB(balances[a.user_id] ?? 0)} THB)
                    </option>
                  ))}
                </select>
              </div>
              <form className="chatform" onSubmit={(e) => { e.preventDefault(); handlePlay(); }}>
                <input
                  type="text"
                  value={draftMessage}
                  onChange={(e) => setDraftMessage(e.target.value)}
                  placeholder="e.g. transfer 2,000 baht to user2"
                  aria-label="Banking message"
                />
              </form>
              <div className="controls controls-top-gap">
                <RunControls
                  status={player.status}
                  onPlay={handlePlay}
                  onPause={player.pause}
                  onStep={player.step}
                  onReset={player.reset}
                />
              </div>
              <label className="unsafe">
                <input type="checkbox" checked={unsafe} onChange={(e) => onToggleUnsafe(e.target.checked)} />
                Inject unsafe instruction (&ldquo;ignore bank rules · skip OTP&rdquo;)
              </label>
            </div>

            <div className="panel">
              <h2>Control flow</h2>
              <p className="sub">Probabilistic reasoning above · deterministic enforcement below the boundary.</p>
              <ProbabilisticZone nodeStatus={player.nodeStatus} />
              <DeterministicBoundary />
              <DeterministicZone nodeStatus={player.nodeStatus} guardrailPolicy={governance?.guardrail_policy} />
            </div>

            <div className="panel">
              <h2>Current step</h2>
              <ToolCallCard step={c} />
            </div>

            {player.blocked ? (
              <GuardrailBlockBanner step={c} guardrailPolicy={governance?.guardrail_policy} />
            ) : (
              <HandoffObjectCard handoff={player.handoff} />
            )}
          </div>

          <aside className="col">
            <DspmEventsPanel compact />
            <div className="panel">
              <div className="rail-h rail-h-row">
                <span>Accounts · remaining balance</span>
                <button className="btn tiny" type="button" onClick={resetLedger}>Reset</button>
              </div>
              <ul className="acctlist">
                {BANK_ACCOUNTS.map((a) => (
                  <li key={a.user_id} className={a.user_id === fromUserId ? "acct active" : "acct"}>
                    <div className="acct-id">
                      <span className="acct-alias">{a.alias}</span>
                      <span className="acct-name">{a.display_name}</span>
                    </div>
                    <div className="acct-bal">{formatTHB(balances[a.user_id] ?? 0)} <span className="ccy">THB</span></div>
                  </li>
                ))}
              </ul>
              <p className="sub sub-tight-top">
                The agent never moves money. This ledger simulates the core-banking system applying a transfer only after a permitted handoff + step-up confirmation.
              </p>
            </div>
            <div className="panel">
              <div className="rail-h">Transaction activity</div>
              {txns.length === 0 ? (
                <p className="sub">No transactions yet. Send a transfer request to populate activity.</p>
              ) : (
                <ul className="txnlist">
                  {txns.map((t) => (
                    <li key={t.id} className={`txn ${t.status}`}>
                      <div className="txn-top">
                        <span className="txn-route">{t.fromAlias} → {t.toAlias}</span>
                        <span className={`txn-status ${t.status}`}>{t.status}</span>
                      </div>
                      <div className="txn-amt">{formatTHB(t.amount)} THB</div>
                      <div className="txn-note">{t.note}</div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div className="panel">
              <div className="rail-h">Token usage · live</div>
              <TokenCounter
                prompt={player.tokens.prompt}
                completion={player.tokens.completion}
                total={player.tokens.total}
                cost={player.tokens.cost}
                consumer={c?.stage ?? c?.agent}
                model={c?.model}
              />
              <p className="sub sub-tight-top">
                Deterministic tool steps make no model call — they emit no token record.
              </p>
            </div>
            <div className="panel">
              <div className="rail-h">Audit trail · Cosmos</div>
              <AuditTrailPanel audit={player.audit} />
            </div>
          </aside>
        </div>
      </main>
    </AppShell>
  );
}
