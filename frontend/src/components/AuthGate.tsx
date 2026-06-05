// =============================================================================
// AuthGate.tsx — lightweight shared-password gate for the PoC demo.
//
// ⚠️ SECURITY NOTE: This is a DEMO gate only. The password check happens in the
// browser (SHA-256 compare against a stored digest). A determined user can
// bypass it by reading the bundle. It is NOT production-grade authentication.
// For real protection, validate server-side (e.g. an SWA managed Functions API).
// =============================================================================
import { FormEvent, ReactNode, useState } from "react";

// SHA-256 hex digest of the demo password "@!PoCS4BX".
const PASSWORD_HASH =
  "d5d67c8142e7d8c74fe1ece6cce15bae0dfaa496260b87ed8a95e45e9ae34363";
const SESSION_KEY = "agpoc-auth";

async function sha256Hex(value: string): Promise<string> {
  const bytes = new TextEncoder().encode(value);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

export function AuthGate({ children }: { children: ReactNode }) {
  const [authed, setAuthed] = useState(
    () => sessionStorage.getItem(SESSION_KEY) === "ok",
  );
  const [pw, setPw] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  if (authed) return <>{children}</>;

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const hash = await sha256Hex(pw);
      if (hash === PASSWORD_HASH) {
        sessionStorage.setItem(SESSION_KEY, "ok");
        setAuthed(true);
      } else {
        setError("Incorrect password. Please try again.");
        setPw("");
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-shell">
      <form className="login-card" onSubmit={onSubmit}>
        <div className="login-brand">TechX · DataX · SCBX · MS</div>
        <h1 className="login-title">Agentic AI Platform PoC</h1>
        <p className="login-sub">Enter the access password to continue.</p>
        <label className="login-label" htmlFor="pw">
          Password
        </label>
        <input
          id="pw"
          className="login-input"
          type="password"
          autoComplete="current-password"
          value={pw}
          onChange={(e) => setPw(e.target.value)}
          autoFocus
        />
        {error ? <div className="login-error">{error}</div> : null}
        <button className="login-btn" type="submit" disabled={busy || !pw}>
          {busy ? "Checking…" : "Sign in"}
        </button>
        <p className="login-note">
          Demo access gate — for evaluation purposes only.
        </p>
      </form>
    </div>
  );
}
