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
  EkycGate,
  GuardrailBlockBanner,
  HandoffObjectCard,
  ProbabilisticZone,
  TransferApprovalGate,
} from "../components/banking";
import { AuditTrailPanel, RunControls, TokenCounter, ToolCallCard } from "../components/panels";
import {
  BANK_ACCOUNTS,
  BANK_CURRENCY,
  BANK_TRANSFER_LIMIT_THB,
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
  // Adjustable per-transaction transfer-limit gate (THB). Seeded from the bank
  // policy default; the user can change it to demo the deterministic gate.
  const [transferLimit, setTransferLimit] = useState(BANK_TRANSFER_LIMIT_THB);
  const transferLimitRef = useRef(transferLimit);
  transferLimitRef.current = transferLimit;

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
      transferLimit: transferLimitRef.current,
    });
    setPlan(builtPlan);
    setRun(built);
  };

  // Build the default run once on mount.
  useEffect(() => {
    loadRun(defaultBankingMessage(), false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Rebuild the current run whenever the limit gate changes so the policy
  // strip, eligibility step, and outcome reflect the new threshold live.
  const didMountLimit = useRef(false);
  useEffect(() => {
    if (!didMountLimit.current) {
      didMountLimit.current = true;
      return;
    }
    loadRun(submittedMessage, unsafe);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [transferLimit]);

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

    // EKYC identity gate failed (cancelled more than the allowed times). The run
    // aborts before any account access — log a blocked activity, no money moves.
    if (player.ekycFailed) {
      setTxns((prev) => [
        { id: plan.handoffId, ts, fromAlias, toAlias, amount: amt, status: "blocked", note: "EKYC failed — identity not confirmed; process cancelled." },
        ...prev,
      ]);
      return;
    }

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
    } else if (plan.outcome === "escalate_approval") {
      // Over-limit transfer was escalated to a human banker. The downstream
      // ledger only executes when the banker approved; a rejection is a
      // logged decline. No money moves until a human decided.
      if (player.hitlDecision === "approved" && plan.recipient) {
        const recipient = plan.recipient;
        setBalances((prev) => ({
          ...prev,
          [plan.sender.user_id]: (prev[plan.sender.user_id] ?? 0) - amt,
          [recipient.user_id]: (prev[recipient.user_id] ?? 0) + amt,
        }));
        setTxns((prev) => [
          { id: plan.handoffId, ts, fromAlias, toAlias, amount: amt, status: "executed", note: "Approved by banker — over-limit transfer executed after step-up confirmation." },
          ...prev,
        ]);
      } else {
        setTxns((prev) => [
          { id: plan.handoffId, ts, fromAlias, toAlias, amount: amt, status: "denied", note: `Rejected by banker — over-limit transfer declined (exceeds ${formatTHB(transferLimitRef.current)} ${BANK_CURRENCY}/txn).` },
          ...prev,
        ]);
      }
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
      // In live mode, also execute the backend guardrail path so the DSPM
      // panel (which polls /api/governance/dspm-events) receives the risky
      // prompt event from the server-side Purview audit sink.
      void backend
        .getRun("banking_blocked", { bankingMessage: submittedMessage })
        .catch(() => {
          // Keep UI playback resilient even if backend telemetry write fails.
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
        tags: run
          ? [
              `run ${run.run_id}`,
              unsafe ? "unsafe path" : plan?.outcome === "escalate_approval" ? "human approval" : "happy path",
            ]
          : [],
      }}
    >
      <main className="page">
        <div className="layout">
          <div className="col">
            <div className="panel">
              <h2>Customer conversation</h2>
              <p className="sub">A mock banking chat. Pick the account you are speaking as, type a request, then press Play to run it. Toggle the unsafe instruction to see deterministic guardrails block it.</p>
              <div className="policystrip" aria-label="Active transfer policy">
                <span className="flag limit">Transfer limit · {formatTHB(transferLimit)} {BANK_CURRENCY}/txn</span>
                <span className="flag ekyc">EKYC required</span>
              </div>
              <div className="limitgate">
                <label htmlFor="limitInput">Adjust transfer-limit gate</label>
                <div className="limitgate-field">
                  <input
                    id="limitInput"
                    type="number"
                    min={0}
                    step={100}
                    value={transferLimit}
                    onChange={(e) => setTransferLimit(Math.max(0, Number(e.target.value) || 0))}
                    aria-label="Transfer limit per transaction in THB"
                  />
                  <span className="ccy">{BANK_CURRENCY}/txn</span>
                </div>
                <div className="limitgate-presets">
                  {[1000, 1500, 5000, 20000].map((v) => (
                    <button
                      key={v}
                      type="button"
                      className={`btn tiny${transferLimit === v ? " active" : ""}`}
                      onClick={() => setTransferLimit(v)}
                    >
                      {formatTHB(v).replace(".00", "")}
                    </button>
                  ))}
                </div>
              </div>
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
                  placeholder="e.g. transfer 1,200 baht to user2"
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
                  allowReplayTerminal
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

            <EkycGate
              active={player.status === "awaiting_ekyc"}
              confirmed={player.ekycConfirmed}
              failed={player.ekycFailed}
              cancelCount={player.ekycCancelCount}
              maxCancels={2}
              userId={plan?.sender.user_id}
              onConfirm={player.ekycConfirm}
              onCancel={player.ekycCancel}
            />

            {plan?.outcome === "escalate_approval" ? (
              <TransferApprovalGate
                active={player.status === "awaiting_approval"}
                resolved={!!player.hitlDecision && (player.status === "done" || player.status === "blocked")}
                decision={player.hitlDecision}
                reason={player.hitlReason}
                amount={plan.amount ?? 0}
                limit={transferLimit}
                currency={BANK_CURRENCY}
                payeeName={plan.recipient ? `${plan.recipient.display_name} (${plan.recipient.alias})` : plan.recipientName}
                onApprove={player.approve}
                onReject={player.reject}
              />
            ) : null}

            {player.blocked && !player.ekycFailed ? (
              <GuardrailBlockBanner step={c} guardrailPolicy={governance?.guardrail_policy} />
            ) : player.hitlDecision === "rejected" ? null : (
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
