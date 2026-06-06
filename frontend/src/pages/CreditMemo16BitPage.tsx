// =============================================================================
// pages/CreditMemo16BitPage.tsx (/credit-memo-16bit) — a 16-bit RPG re-skin of
// UC1. Same real run-player, token, audit and DSPM data as CreditMemoPage, but
// every agent is an animated pixel sprite in a throne room ("DSPM ORCHESTRATOR").
// The orchestrator (MO) sits on the throne and narrates; the party (DR, FR, BS,
// MA, HITL, FINAL) stand on platforms and "work" (type), celebrate, or shake
// when blocked — all driven by player.nodeStatus(). Functionally identical to
// the Credit Memo tab; only the presentation changes.
// =============================================================================
import { useCallback, useEffect, useRef, useState, type ChangeEvent, type DragEvent } from "react";
import { Link } from "react-router-dom";
import type { RunDef } from "../types";
import { backend } from "../lib";
import type { DspmEvent } from "../lib/dspmEvents";
import {
  SAMPLE_DR_DOCUMENT,
  SAMPLE_DR_FILE_NAME,
  SAMPLE_HC_DOCUMENT,
  SAMPLE_HC_FILE_NAME,
} from "../data/sampleDrDocument";
import { useRunPlayer } from "../hooks/useRunPlayer";
import { PixelHero, type HeroAccessory, type HeroPalette } from "../components/pixel/PixelHero";
import "./creditMemo16bit.css";

// ---- pre-built test files (same two the Credit Memo tab uses) ---------------
const DEFAULT_DR_FILE = new File([SAMPLE_DR_DOCUMENT], SAMPLE_DR_FILE_NAME, {
  type: "text/plain",
  lastModified: Date.now(),
});
const HC_DR_FILE = new File([SAMPLE_HC_DOCUMENT], SAMPLE_HC_FILE_NAME, {
  type: "text/plain",
  lastModified: Date.now(),
});
const SAMPLE_CONTENT: Record<string, string> = {
  [SAMPLE_DR_FILE_NAME]: SAMPLE_DR_DOCUMENT,
  [SAMPLE_HC_FILE_NAME]: SAMPLE_HC_DOCUMENT,
};

// ---- character roster (maps 1:1 to useRunPlayer nodeStatus ids) -------------
interface GameChar {
  id: string;
  code: string;
  name: string;
  role: string;
  accessory: HeroAccessory;
  palette: HeroPalette;
}

const P = (suit: string, suitDark: string, accent: string, hair = "#3a2a1a"): HeroPalette => ({
  skin: "#f1c9a5",
  hair,
  suit,
  suitDark,
  shirt: "#f4f6ff",
  accent,
});

const MO_CHAR: GameChar = {
  id: "memo_orchestrator",
  code: "MO",
  name: "Memo Orchestrator",
  role: "Parent orchestrator",
  accessory: "crown",
  palette: P("#0b5cab", "#063a6e", "#ffcf3f", "#2a1a0e"),
};

const PARTY: GameChar[] = [
  { id: "doc_retrieval", code: "DR", name: "Doc Retrieval", role: "Sub-agent · retrieval", accessory: "glasses", palette: P("#0e7c7b", "#08504f", "#46e2ff") },
  { id: "financial_ratio", code: "FR", name: "Financial Ratio", role: "Sub-agent · ratios", accessory: "none", palette: P("#c25e00", "#7d3c00", "#ffd23f") },
  { id: "bureau_summary", code: "BS", name: "Bureau Summary", role: "Sub-agent · bureau", accessory: "none", palette: P("#5b2d8e", "#3a1c5c", "#c69bff", "#1c1030") },
  { id: "memo_assembler", code: "MA", name: "Memo Assembler", role: "Sub-agent · assembly", accessory: "none", palette: P("#2e7d32", "#1c4d20", "#9dff8a") },
  { id: "hitl", code: "HITL", name: "Human Gate", role: "Human-in-the-loop", accessory: "helmet", palette: P("#7a5b12", "#4a3608", "#ffcf3f", "#1a1208") },
  { id: "final", code: "FINAL", name: "Final Memo", role: "Approved & audited", accessory: "sword", palette: P("#1a4e8a", "#0e2f57", "#5cff9d") },
];

const STATUS_TEXT: Record<string, string> = {
  pending: "PENDING",
  working: "WORKING",
  done: "DONE",
  blocked: "BLOCKED",
};

function fmt(n: number): string {
  return n.toLocaleString("en-US");
}

function eventLabel(e: DspmEvent): string {
  if (e.event_type === "prompt_injection_block") return "RISKY PROMPT";
  if (e.event_type === "dlp_block") return "DLP BLOCK";
  return "LABEL SCAN";
}

function eventDetail(e: DspmEvent): string {
  return e.label_full_name || e.label || e.detail || e.risk_category || "—";
}

export function CreditMemo16BitPage() {
  const [file, setFile] = useState<File>(DEFAULT_DR_FILE);
  const [run, setRun] = useState<RunDef | null>(null);
  const [loading, setLoading] = useState(false);
  const [events, setEvents] = useState<DspmEvent[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [showDoc, setShowDoc] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const [attachError, setAttachError] = useState<string | null>(null);
  const [docPreview, setDocPreview] = useState<string | null>(null);
  const pendingPlay = useRef(false);
  const seq = useRef(0);

  // ---- document intake: sample switch + real file upload (parity w/ Credit Memo) ----
  const selectSample = (f: File) => {
    setAttachError(null);
    setDocPreview(null);
    setShowDoc(false);
    setFile(f);
  };
  const attachFromFile = (f?: File) => {
    if (!f) return;
    if (!/\.(pdf|doc|docx|txt)$/i.test(f.name)) {
      setAttachError("Attach a supported file (.pdf, .doc, .docx, .txt)");
      return;
    }
    setAttachError(null);
    setDocPreview(null);
    setShowDoc(false);
    setFile(f);
  };
  const onPickFile = (e: ChangeEvent<HTMLInputElement>) => attachFromFile(e.target.files?.[0]);
  const onDropFile = (e: DragEvent<HTMLLabelElement>) => {
    e.preventDefault();
    setDragActive(false);
    attachFromFile(e.dataTransfer.files?.[0]);
  };
  const openPicker = () => (document.getElementById("dr16-file-input") as HTMLInputElement | null)?.click();
  const togglePreview = async () => {
    if (showDoc) {
      setShowDoc(false);
      return;
    }
    if (docPreview === null) {
      const text = SAMPLE_CONTENT[file.name] ?? (await file.text());
      setDocPreview(text);
    }
    setShowDoc(true);
  };

  const fetchRun = useCallback((f: File) => {
    const id = ++seq.current;
    setLoading(true);
    return backend
      .getRun("credit_memo", {
        drDocument: {
          file_name: f.name,
          size_bytes: f.size,
          mime_type: f.type || undefined,
          last_modified_epoch_ms: f.lastModified,
          uploaded_at: new Date().toISOString(),
        },
      })
      .then((r) => {
        if (id !== seq.current) return null;
        setRun(r);
        setLoading(false);
        return r;
      })
      .catch(() => {
        if (id !== seq.current) return null;
        setRun(null);
        setLoading(false);
        return null;
      });
  }, []);

  useEffect(() => {
    void fetchRun(file);
  }, [file, fetchRun]);

  const player = useRunPlayer(run);

  // Queue play() until the reducer has consumed a freshly fetched run.
  useEffect(() => {
    if (!pendingPlay.current || !run) return;
    if (player.run?.run_id !== run.run_id) return;
    pendingPlay.current = false;
    player.play();
  }, [run?.run_id, player.run?.run_id]); // eslint-disable-line react-hooks/exhaustive-deps

  const refreshEvents = useCallback(() => {
    void backend.getDspmEvents(8).then(setEvents).catch(() => undefined);
  }, []);

  useEffect(() => {
    refreshEvents();
  }, [refreshEvents]);

  // Re-pull security events when a run terminates (a block surfaces a Purview event).
  useEffect(() => {
    if (player.status === "blocked" || player.status === "done") refreshEvents();
  }, [player.status, refreshEvents]);

  const handlePlay = () => {
    if (loading) return;
    // Purview sensitivity-label gate: a blocked file must never reach the agents.
    if (run?.policyBlock) return;
    if (run && !player.run) {
      pendingPlay.current = true;
      return;
    }
    if (!run) {
      pendingPlay.current = true;
      void fetchRun(file);
      return;
    }
    if (player.status === "done" || player.status === "blocked") {
      player.reset();
      window.setTimeout(() => player.play(), 0);
      return;
    }
    player.play();
  };

  const isHC = file.name === SAMPLE_HC_FILE_NAME;
  const blocked = !!run?.policyBlock;
  const moStatus = player.nodeStatus(MO_CHAR.id);
  const completed = [MO_CHAR, ...PARTY].filter((c) => player.nodeStatus(c.id) === "done").length;
  const statusLabel = blocked ? "BLOCKED" : player.status.replace("_", " ").toUpperCase();
  const statusClass = blocked ? "blocked" : player.status;

  // ---- MO speech bubble ----
  let bubble = "Attach a document and start the run.";
  let tone = "";
  if (blocked) {
    bubble = `Purview blocked: ${run!.policyBlock!.label_full_name}. Pick the General file.`;
    tone = "bad";
  } else if (player.status === "blocked") {
    bubble = "A policy gate blocked this run.";
    tone = "bad";
  } else if (player.status === "awaiting_approval") {
    bubble = "Human review needed — approve or reject the draft.";
    tone = "warn";
  } else if (player.status === "done") {
    bubble = "Memo draft assembled, approved & fully audited!";
    tone = "good";
  } else if (player.current) {
    bubble = player.current.title;
  } else if (loading) {
    bubble = "Loading the quest...";
  }

  const selectedChar = selected ? [MO_CHAR, ...PARTY].find((c) => c.id === selected) : null;

  return (
    <div className="cm16">
      <div className="cm16-frame">
        {/* ---- HUD ---- */}
        <div className="cm16-hud">
          <span className="title">DSPM ORCHESTRATOR</span>
          <span className="level">{isHC ? "LEVEL 1 · BLOCKED ZONE" : "LEVEL 1 · INTERNAL BUSINESS"}</span>
          <span className="spacer" />
          <span className="stat"><span className="ico">⬥</span>{fmt(player.tokens.total)}</span>
          <span className="stat"><span className="ico">★</span>{completed}/{PARTY.length + 1}</span>
          <Link className="back" to="/credit-memo">EXIT ▸</Link>
        </div>

        <div className="cm16-stage">
          {/* ===================== LEFT (main) ===================== */}
          <div className="cm16-main">
            {/* ---- throne-room scene ---- */}
            <div className="cm16-scene">
              <div className="cm16-throne">
                <div className={`cm16-bubble ${tone}`}>{bubble}</div>
                <button
                  type="button"
                  className={`cm16-slot ${selected === MO_CHAR.id ? "is-selected" : ""} is-${moStatus}`}
                  onClick={() => setSelected(selected === MO_CHAR.id ? null : MO_CHAR.id)}
                  title={MO_CHAR.name}
                >
                  <div className="cm16-hero">
                    <PixelHero palette={MO_CHAR.palette} accessory={MO_CHAR.accessory} state={moStatus} />
                  </div>
                  <div className="chair" />
                  <span className="cm16-tag">{MO_CHAR.code}</span>
                </button>
              </div>

              <div className="cm16-party">
                {PARTY.map((ch) => {
                  const st = player.nodeStatus(ch.id);
                  return (
                    <button
                      type="button"
                      key={ch.id}
                      className={`cm16-slot is-${st} ${selected === ch.id ? "is-selected" : ""}`}
                      onClick={() => setSelected(selected === ch.id ? null : ch.id)}
                      title={ch.name}
                    >
                      {st !== "pending" && <span className={`cm16-stchip ${st}`}>{STATUS_TEXT[st]}</span>}
                      <div className="cm16-hero">
                        <PixelHero palette={ch.palette} accessory={ch.accessory} state={st} />
                      </div>
                      <div className="cm16-platform" />
                      <span className="cm16-tag">{ch.code}</span>
                    </button>
                  );
                })}
              </div>

              {selectedChar && (
                <div className="cm16-bubble cm16-inspect">
                  <b className="pixel">{selectedChar.code}</b> — {selectedChar.name} · {selectedChar.role}
                  {" · "}
                  {STATUS_TEXT[player.nodeStatus(selectedChar.id)]}
                </div>
              )}
            </div>

            {/* ---- document intake + pipeline ---- */}
            <div className="cm16-cols">
              <div className="cm16-box">
                <h3>📜 Document Intake · DR</h3>
                <div className="pad">
                  <div className="cm16-filebtns">
                    <button
                      type="button"
                      className={`cm16-fb gen ${file.name === SAMPLE_DR_FILE_NAME ? "active" : ""}`}
                      onClick={() => selectSample(DEFAULT_DR_FILE)}
                    >
                      <b>GENERAL</b>
                      <small>Credit file · passes Purview gate</small>
                    </button>
                    <button
                      type="button"
                      className={`cm16-fb hc ${isHC ? "active" : ""}`}
                      onClick={() => selectSample(HC_DR_FILE)}
                    >
                      <b>HIGHLY CONFIDENTIAL</b>
                      <small>Board doc · blocked by Purview</small>
                    </button>
                  </div>

                  {/* real file upload — drag & drop or click to browse */}
                  <label
                    className={`cm16-drop ${dragActive ? "drag" : ""}`}
                    onClick={openPicker}
                    onDragEnter={(e) => { e.preventDefault(); setDragActive(true); }}
                    onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
                    onDragLeave={(e) => { e.preventDefault(); setDragActive(false); }}
                    onDrop={onDropFile}
                  >
                    <input id="dr16-file-input" type="file" accept=".pdf,.doc,.docx,.txt" onChange={onPickFile} hidden />
                    <b>⬆ ATTACH FILE</b>
                    Drop a credit file here or click to upload · PDF / DOC / DOCX / TXT
                  </label>
                  {attachError && <div className="cm16-attach-err">⚠ {attachError}</div>}

                  {run?.policyBlock && (
                    <div className="cm16-block" role="alert">
                      <b className="pixel">⛔ PURVIEW BLOCK · {run.policyBlock.label}</b>
                      <span>Sensitivity label <b>{run.policyBlock.label_full_name}</b> — blocked from agent ingestion.</span>
                      <small>{run.policyBlock.justification}</small>
                    </div>
                  )}

                  <div className="cm16-file">
                    <span className="doc">🗎</span>
                    <span>
                      <span className="nm">{file.name}</span>
                      <br />
                      <span className="meta">{fmt(file.size)} bytes · {file.type || "file"}</span>
                    </span>
                    <button type="button" className="cm16-btn ghost push" onClick={() => void togglePreview()}>
                      {showDoc ? "HIDE" : "VIEW"}
                    </button>
                  </div>
                  {showDoc && docPreview && <pre className="cm16-docpre">{docPreview.slice(0, 1600)}</pre>}
                </div>
              </div>

              <div className="cm16-box">
                <h3>⚔ Agent Pipeline<span className="r">{completed}/{PARTY.length + 1}</span></h3>
                <div className="pad">
                  <div className="cm16-steps">
                    {[MO_CHAR, ...PARTY].map((ch) => {
                      const st = player.nodeStatus(ch.id);
                      const cls = st === "working" ? "on" : st === "done" ? "ok" : st === "blocked" ? "bad" : "";
                      return (
                        <div className={`cm16-srow ${cls}`} key={ch.id}>
                          <div className="mini">
                            <PixelHero palette={ch.palette} accessory={ch.accessory} state={st} />
                          </div>
                          <span className="nm">
                            {ch.name}
                            <small>{ch.role}</small>
                          </span>
                          <span className="pip">{STATUS_TEXT[st]}</span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* ===================== RIGHT (rail) ===================== */}
          <div className="cm16-rail">
            {/* ---- run controls ---- */}
            <div className="cm16-box">
              <h3>🎮 Run Controls<span className={`cm16-badge ${statusClass} r`}>{statusLabel}</span></h3>
              <div className="pad">
                <div className="cm16-btnrow">
                  <button type="button" className="cm16-btn play" onClick={handlePlay} disabled={loading || blocked}>
                    {player.status === "playing" ? "❚❚ PAUSE" : "▶ PLAY"}
                  </button>
                  <button type="button" className="cm16-btn step" onClick={() => player.step()} disabled={loading || !player.run || blocked}>⏭ STEP</button>
                  <button type="button" className="cm16-btn reset" onClick={() => player.reset()} disabled={!player.run}>↺ RESET</button>
                </div>
                {blocked && (
                  <div className="cm16-btnrow mt8">
                    <span className="cm16-block-note">⛔ Run disabled — Purview blocked this file. Pick the General file to continue.</span>
                  </div>
                )}
                {player.status === "playing" && (
                  <div className="cm16-btnrow mt8">
                    <button type="button" className="cm16-btn ghost" onClick={() => player.pause()}>❚❚ PAUSE</button>
                  </div>
                )}
                {player.status === "awaiting_approval" && (
                  <div className="cm16-btnrow mt10">
                    <button type="button" className="cm16-btn approve" onClick={() => player.approve("Approved in 16-bit review")}>✔ APPROVE</button>
                    <button type="button" className="cm16-btn reject" onClick={() => player.reject("Rejected in 16-bit review")}>✖ REJECT</button>
                  </div>
                )}
              </div>
            </div>

            {/* ---- live security events ---- */}
            <div className="cm16-box">
              <h3>🛡 Live Security Events
                <button type="button" className="cm16-btn ghost r cm16-refresh" onClick={refreshEvents}>↻ REFRESH</button>
              </h3>
              <div className="pad">
                <div className="cm16-ev">
                  {events.length === 0 && <div className="cm16-empty">No events yet — press PLAY.</div>}
                  {events.map((e) => (
                    <div className={`cm16-evrow ${e.decision}`} key={e.id}>
                      <span>
                        <span className="et">{eventLabel(e)}</span>{" "}
                        <span className={`sev ${e.severity}`}>{(e.severity || "informational").toUpperCase()}</span>
                        <span className="dt">{eventDetail(e)}</span>
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* ---- token usage ---- */}
            <div className="cm16-box">
              <h3>⬥ Token Usage · Live</h3>
              <div className="pad">
                <div className="cm16-tok">
                  <div className="cm16-tcell"><div className="k">PROMPT</div><div className="v tnum">{fmt(player.tokens.prompt)}</div></div>
                  <div className="cm16-tcell"><div className="k">COMPL</div><div className="v tnum">{fmt(player.tokens.completion)}</div></div>
                  <div className="cm16-tcell total"><div className="k">TOTAL</div><div className="v tnum">{fmt(player.tokens.total)}</div></div>
                </div>
                <div className="cm16-cost">EST COST  ${player.tokens.cost.toFixed(4)}</div>
              </div>
            </div>

            {/* ---- audit trail ---- */}
            <div className="cm16-box">
              <h3>📦 Audit Trail · Cosmos</h3>
              <div className="pad">
                <div className="cm16-audit">
                  {player.audit.length === 0 && <div className="cm16-empty">Audit log is empty.</div>}
                  {player.audit.map((a, i) => (
                    <div className="cm16-arow" key={`${a.step}-${i}`}>
                      <span className="ak">{a.kind.toUpperCase()}</span>
                      <span className="ax">{a.text}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* ---- footer hint bar ---- */}
        <div className="cm16-footer">
          <span className="hint"><span className="key">CLICK</span> Inspect hero</span>
          <span className="hint"><span className="key">▶</span> Play run</span>
          <span className="hint"><span className="key">⏭</span> Step</span>
          <span className="hint"><span className="key">↻</span> Refresh events</span>
          <span className="start">{player.status === "ready" ? "PRESS PLAY TO RUN" : player.status === "done" ? "QUEST COMPLETE!" : "● RUNNING"}</span>
        </div>
      </div>
    </div>
  );
}
