// =============================================================================
// pages/CreditMemoPage.tsx (UC1) — owns useRunPlayer("credit_memo"). Left column:
// run controls + live AgentFlowGraph + current ToolCallCard + HITL approval bar.
// Right rail: audit trail + live token counter. Read-only workflow; the memo is
// never final without human approval (POC_SPEC §UC1 hard rule).
// =============================================================================
import { useEffect, useRef, useState, type ChangeEvent, type DragEvent } from "react";
import type { RunDef } from "../types";
import { backend } from "../lib";
import { UC1_AGENTS } from "../data/mockData";
import {
  SAMPLE_DR_DOCUMENT,
  SAMPLE_DR_FILE_NAME,
  SAMPLE_HC_DOCUMENT,
  SAMPLE_HC_FILE_NAME,
  SAMPLE_REJECT_DOCUMENT,
  SAMPLE_REJECT_FILE_NAME,
} from "../data/sampleDrDocument";
import { useRunPlayer } from "../hooks/useRunPlayer";
import { AppShell } from "../components/AppShell";
import { AgentFlowGraph } from "../components/flow";
import { DspmEventsPanel } from "../components/DspmEventsPanel";
import {
  AuditTrailPanel,
  HITLApprovalBar,
  RunControls,
  TokenCounter,
  ToolCallCard,
} from "../components/panels";

const DEFAULT_DR_FILE = new File(
  [SAMPLE_DR_DOCUMENT],
  SAMPLE_DR_FILE_NAME,
  { type: "text/plain", lastModified: Date.now() },
);

const HC_DR_FILE = new File(
  [SAMPLE_HC_DOCUMENT],
  SAMPLE_HC_FILE_NAME,
  { type: "text/plain", lastModified: Date.now() },
);

const REJECT_DR_FILE = new File(
  [SAMPLE_REJECT_DOCUMENT],
  SAMPLE_REJECT_FILE_NAME,
  { type: "text/plain", lastModified: Date.now() },
);

// Pre-built test files the reviewer can switch between: a General-labeled credit
// file that passes policy (APP-1001 → approve), a General-labeled credit file
// that breaches policy (APP-1003 → reject), and a Highly Confidential board
// document the Purview gate blocks before any agent runs.
const SAMPLE_CONTENT: Record<string, string> = {
  [SAMPLE_DR_FILE_NAME]: SAMPLE_DR_DOCUMENT,
  [SAMPLE_REJECT_FILE_NAME]: SAMPLE_REJECT_DOCUMENT,
  [SAMPLE_HC_FILE_NAME]: SAMPLE_HC_DOCUMENT,
};

export function CreditMemoPage() {
  const [run, setRun] = useState<RunDef | null>(null);
  const [attachedFile, setAttachedFile] = useState<File>(DEFAULT_DR_FILE);
  const [dragActive, setDragActive] = useState(false);
  const [attachError, setAttachError] = useState<string | null>(null);
  const [runLoadState, setRunLoadState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [runLoadMessage, setRunLoadMessage] = useState<string>("Sample document attached. Click Play to run.");
  const [docPreview, setDocPreview] = useState<string | null>(null);
  const [showPreview, setShowPreview] = useState(false);
  // Set when Play should begin once a freshly fetched run is loaded.
  const pendingPlay = useRef(false);
  // Monotonic request id so stale run responses cannot overwrite newer intent.
  const runLoadSeq = useRef(0);

  const sampleContent = SAMPLE_CONTENT[attachedFile.name];
  const isSampleDoc = sampleContent !== undefined;

  // Swap the attached file to one of the two pre-built test documents. Resets the
  // preview so it re-reads the newly selected sample's content.
  const selectSample = (file: File) => {
    setAttachError(null);
    setDocPreview(null);
    setShowPreview(false);
    setAttachedFile(file);
  };

  const attachFromFile = (file: File | undefined) => {
    if (!file) return;
    const allowed = /\.(pdf|doc|docx|txt)$/i.test(file.name);
    if (!allowed) {
      setAttachError("Attach a supported file (.pdf, .doc, .docx, .txt)");
      return;
    }
    setAttachError(null);
    setAttachedFile(file);
  };

  const onPickFile = (ev: ChangeEvent<HTMLInputElement>) => {
    setDocPreview(null);
    setShowPreview(false);
    attachFromFile(ev.target.files?.[0]);
  };

  const onDropFile = (ev: DragEvent<HTMLLabelElement>) => {
    ev.preventDefault();
    setDragActive(false);
    setDocPreview(null);
    setShowPreview(false);
    attachFromFile(ev.dataTransfer.files?.[0]);
  };

  const openDrPicker = () => {
    const input = document.getElementById("dr-file-input") as HTMLInputElement | null;
    input?.click();
  };

  const togglePreview = async () => {
    if (showPreview) {
      setShowPreview(false);
      return;
    }
    if (docPreview === null && attachedFile) {
      const text = sampleContent ?? (await attachedFile.text());
      setDocPreview(text);
    }
    setShowPreview(true);
  };

  const fetchRun = async (file: File, reason: "init" | "file-change" | "play" | "play-fallback" | "reset") => {
    const seq = ++runLoadSeq.current;
    const source = reason === "play-fallback" ? "sample" : file === DEFAULT_DR_FILE ? "sample" : "uploaded";
    setRunLoadState("loading");
    setRunLoadMessage(
      source === "sample"
        ? "Preparing sample run..."
        : `Preparing run from uploaded file (${file.name})...`,
    );
    // Read the document text so the backend agent can analyse the actual case
    // content. Samples use their canned text; uploads read the file (best
    // effort — binary formats may not yield clean text). Capped to keep the
    // request small.
    let content: string | undefined;
    try {
      const raw = SAMPLE_CONTENT[file.name] ?? (await file.text());
      content = raw ? raw.slice(0, 20000) : undefined;
    } catch {
      content = undefined;
    }
    if (seq !== runLoadSeq.current) return null;
    return backend
      .getRun("credit_memo", {
        drDocument: {
          file_name: file.name,
          size_bytes: file.size,
          mime_type: file.type || undefined,
          last_modified_epoch_ms: file.lastModified,
          uploaded_at: new Date().toISOString(),
          content,
        },
      })
      .then((r) => {
        if (seq !== runLoadSeq.current) return null;
        setAttachError(null);
        setRunLoadState("ready");
        setRunLoadMessage(
          source === "sample"
            ? "Sample run is ready."
            : `Run ready from uploaded file (${file.name}).`,
        );
        setRun(r);
        return r;
      })
      .catch((err: unknown) => {
        if (seq !== runLoadSeq.current) return null;
        const detail = err instanceof Error && err.message ? ` (${err.message})` : "";
        setRunLoadState("error");
        setRunLoadMessage(
          source === "sample"
            ? `Sample run preload failed. Please try again${detail}.`
            : `Uploaded file run preload failed (${file.name})${detail}.`,
        );
        setRun(null);
        return null;
      });
  };

  useEffect(() => {
    void fetchRun(attachedFile, "file-change");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attachedFile]);

  const player = useRunPlayer(run);
  const c = player.current;
  const approvalGuidance = (c?.params as { approval_guidance?: { recommendation?: string; should_approve?: string[]; should_not_approve?: string[] } } | undefined)?.approval_guidance;

  useEffect(() => {
    // Avoid a race: run state may be set before useRunPlayer has consumed it.
    if (!pendingPlay.current || !run) return;
    if (player.run?.run_id !== run.run_id) return;
    pendingPlay.current = false;
    player.play();
  }, [run?.run_id, player.run?.run_id, player.status]);

  const handlePlay = () => {
    if (runLoadState === "loading") return;
    // If run is present but reducer state has not consumed it yet, queue play.
    if (run && !player.run) {
      pendingPlay.current = true;
      return;
    }
    if (!run) {
      pendingPlay.current = true;
      setAttachError(null);
      void fetchRun(attachedFile, "play")
        .then((r) => {
          if (!r) {
            // If uploaded file preload fails, automatically fall back to sample.
            if (attachedFile !== DEFAULT_DR_FILE) {
              setAttachedFile(DEFAULT_DR_FILE);
              setRunLoadMessage("Uploaded file failed. Falling back to sample document...");
              void fetchRun(DEFAULT_DR_FILE, "play-fallback").then((sampleRun) => {
                if (!sampleRun) {
                  pendingPlay.current = false;
                  setAttachError("Run preload failed for both uploaded and sample files.");
                  return;
                }
                setAttachError(null);
              });
              return;
            }
            pendingPlay.current = false;
            setAttachError("Run preload failed. Please try again.");
          }
        })
        .catch(() => {
          pendingPlay.current = false;
          setAttachError("Run preload failed. Please try again.");
        });
      return;
    }
    if (player.status === "done" || player.status === "blocked") {
      player.reset();
      window.setTimeout(() => player.play(), 0);
      return;
    }
    player.play();
  };

  // Reset clears the run player AND any page-level Purview policy block. The
  // block lives on the run object (not the player), so player.reset() alone
  // would leave the controls disabled and the block banner up — making Reset
  // look like a no-op. Re-fetching a clean run for the attached file unblocks.
  const handleReset = () => {
    player.reset();
    setAttachError(null);
    if (run?.policyBlock) void fetchRun(attachedFile, "reset");
  };

  return (
    <AppShell
      hero={{
        uc: "credit_memo",
        ucLabel: "UC1 · Credit Memo",
        crumb: "Credit Memo",
        title: "Credit Memo Drafting Agent",
        subtitle:
          "A parent orchestrator plans a read-only, multi-step workflow and dispatches sub-agents to retrieve documents, compute ratios, summarize the bureau report, and assemble a memo draft. A human approves before anything is final.",
        tags: run ? [`run ${run.run_id}`, run.applicant ?? ""] : [],
      }}
    >
      <main className="page">
        <div className="layout">
          <div className="col">
            <div className="panel">
              <h2>Run controls</h2>
              <p className="sub">Walk the orchestration step-by-step or play it through. The working agent is highlighted.</p>
              <RunControls
                status={player.status}
                onPlay={handlePlay}
                onPause={player.pause}
                onStep={player.step}
                onReset={handleReset}
                disabled={!!run?.policyBlock}
                allowReplayTerminal
              />
              <p className="sub" style={{ marginTop: 10, marginBottom: 0 }}>
                Attach a supporting document in the DR node first, then start the run.
              </p>
              <p className={`sub ${runLoadState === "error" ? "dr-error" : ""}`} style={{ marginTop: 6, marginBottom: 0 }}>
                {runLoadMessage}
              </p>
            </div>

            <div className="panel">
              <h2>Document intake (DR)</h2>
              <p className="sub">Click the DR node or drop a file here. The workflow starts only after a document is attached.</p>
              <div className="dr-samples">
                <span className="dr-samples-label">Test file:</span>
                <button
                  type="button"
                  className={`dr-sample-btn${attachedFile?.name === SAMPLE_DR_FILE_NAME ? " active" : ""}`}
                  onClick={() => selectSample(DEFAULT_DR_FILE)}
                  aria-pressed={attachedFile?.name === SAMPLE_DR_FILE_NAME ? "true" : "false"}
                >
                  <span className="dr-sample-dot general" aria-hidden />
                  General
                  <small>passes — agent runs</small>
                </button>
                <button
                  type="button"
                  className={`dr-sample-btn${attachedFile?.name === SAMPLE_REJECT_FILE_NAME ? " active" : ""}`}
                  onClick={() => selectSample(REJECT_DR_FILE)}
                  aria-pressed={attachedFile?.name === SAMPLE_REJECT_FILE_NAME ? "true" : "false"}
                >
                  <span className="dr-sample-dot reject" aria-hidden />
                  Reject case
                  <small>agent recommends reject</small>
                </button>
                <button
                  type="button"
                  className={`dr-sample-btn${attachedFile?.name === SAMPLE_HC_FILE_NAME ? " active" : ""}`}
                  onClick={() => selectSample(HC_DR_FILE)}
                  aria-pressed={attachedFile?.name === SAMPLE_HC_FILE_NAME ? "true" : "false"}
                >
                  <span className="dr-sample-dot hc" aria-hidden />
                  Highly Confidential
                  <small>blocked by Purview</small>
                </button>
              </div>
              <label
                className={`dr-dropzone${dragActive ? " active" : ""}`}
                onDragEnter={(e) => {
                  e.preventDefault();
                  setDragActive(true);
                }}
                onDragOver={(e) => {
                  e.preventDefault();
                  setDragActive(true);
                }}
                onDragLeave={(e) => {
                  e.preventDefault();
                  setDragActive(false);
                }}
                onDrop={onDropFile}
              >
                <input id="dr-file-input" type="file" accept=".pdf,.doc,.docx,.txt" onChange={onPickFile} hidden />
                <strong>{attachedFile ? attachedFile.name : "Drop credit file here or click to upload"}</strong>
                <span>{attachedFile ? `${Math.ceil(attachedFile.size / 1024)} KB attached` : "Supported formats: PDF, DOC, DOCX, TXT"}</span>
              </label>
              {attachError ? <p className="dr-error">{attachError}</p> : null}
              {runLoadState === "loading" ? <p className="sub">Upload status: preparing run...</p> : null}
              {run?.policyBlock ? (
                <div className="policy-block-alert" role="alert">
                  <div className="policy-block-head">
                    <span className="policy-block-icon" aria-hidden>⛔</span>
                    <div>
                      <strong>Upload rejected · Microsoft Purview</strong>
                      <span className="policy-block-sub">
                        Sensitivity label <b>{run.policyBlock.label_full_name}</b> — blocked from agent ingestion.
                      </span>
                    </div>
                    <span className="policy-block-pill">{run.policyBlock.label}</span>
                  </div>
                  <p className="policy-block-body">{run.policyBlock.justification}</p>
                  <p className="policy-block-meta">
                    File: {run.policyBlock.file_name} · Logged to Microsoft Purview audit + DSPM for AI
                    {run.policyBlock.dspm_event_id ? ` · event ${run.policyBlock.dspm_event_id}` : ""}. Attach a
                    General/Internal-labeled document to continue.
                  </p>
                </div>
              ) : null}
              {isSampleDoc || attachedFile.type === "text/plain" ? (
                <div className="dr-preview-controls">
                  <button type="button" className="btn ghost" onClick={togglePreview}>
                    {showPreview ? "Hide document" : "View sample document"}
                  </button>
                  {attachedFile?.name === SAMPLE_DR_FILE_NAME ? (
                    <span className="dr-sample-tag">APP-1001 · General · credit file</span>
                  ) : attachedFile?.name === SAMPLE_REJECT_FILE_NAME ? (
                    <span className="dr-sample-tag reject">APP-1003 · General · reject case</span>
                  ) : attachedFile?.name === SAMPLE_HC_FILE_NAME ? (
                    <span className="dr-sample-tag hc">APP-1001 · Highly Confidential · board resolution</span>
                  ) : null}
                </div>
              ) : null}
              {showPreview && docPreview ? (
                <pre className="dr-doc-view">{docPreview}</pre>
              ) : null}
            </div>

            <div className="panel">
              <h2>Agent pipeline</h2>
              <p className="sub">memo_orchestrator (parent) → 4 sub-agents → HITL gate → final audited memo.</p>
              <AgentFlowGraph agents={UC1_AGENTS} nodeStatus={player.nodeStatus} onNodeClick={(id) => id === "doc_retrieval" && openDrPicker()} />
            </div>

            <div className="panel">
              <h2>Current step</h2>
              <ToolCallCard step={c} />
            </div>
          </div>

          <aside className="col">
            <HITLApprovalBar
              active={player.status === "awaiting_approval"}
              resolved={!!player.hitlDecision && (player.status === "done" || player.status === "blocked")}
              decision={player.hitlDecision}
              reason={player.hitlReason}
              guidance={approvalGuidance}
              onApprove={player.approve}
              onReject={player.reject}
            />
            <DspmEventsPanel compact />
            <div className="panel">
              <div className="rail-h">Token usage · live</div>
              <TokenCounter
                prompt={player.tokens.prompt}
                completion={player.tokens.completion}
                total={player.tokens.total}
                cost={player.tokens.cost}
                consumer={c?.agent}
                model={c?.model}
              />
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
