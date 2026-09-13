import { useState, useEffect, useRef } from "react";
import { Lock, ArrowRight, Loader2, KeyRound, X } from "lucide-react";
import { api, setApiToken, getApiToken, ApiError } from "@/lib/api";
import { useGraphStore } from "@/store/graphStore";
import { isPreviewMode } from "@/lib/previewFixtures";

type Diagnosis = {
  message: string;
  /** Only a 401 means the credential is actually wrong. */
  tokenAtFault: boolean;
};

const BACKEND_UNREACHABLE = "Cannot reach the backend. Check that the API is running.";

/**
 * Work out what actually went wrong before blaming the user's token.
 *
 * The previous version caught every failure, said "Invalid API token", and
 * erased the token — so a Neo4j outage, a backend with no API_TOKEN
 * configured, and a genuinely wrong credential were indistinguishable, and
 * the only escape was a page reload. `/health` is public and unauthenticated,
 * which makes it the right probe for telling these apart.
 */
async function diagnose(err: unknown): Promise<Diagnosis> {
  const status = (err as ApiError)?.status;

  if (status === 401) {
    return { message: "That token was rejected. Check the API_TOKEN value.", tokenAtFault: true };
  }
  if (status === 503) {
    return {
      message:
        "The server has no API_TOKEN configured, so it cannot accept any token. " +
        "This is a deployment setting, not something you can fix here.",
      tokenAtFault: false,
    };
  }
  if (status === 429) {
    return { message: "Rate limited. Wait a minute and try again.", tokenAtFault: false };
  }

  // No status means fetch itself failed — the backend is unreachable.
  if (status === undefined) {
    return { message: BACKEND_UNREACHABLE, tokenAtFault: false };
  }

  try {
    const health = await api.health();
    if (health.neo4j !== "ok") {
      return {
        message: "The backend is up but cannot reach Neo4j, so no query can succeed yet.",
        tokenAtFault: false,
      };
    }
  } catch {
    return { message: BACKEND_UNREACHABLE, tokenAtFault: false };
  }

  return { message: `The server returned an error (${status}).`, tokenAtFault: false };
}

export default function AuthModal() {
  const [isOpen, setIsOpen] = useState(false);
  const [token, setToken] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dismissible, setDismissible] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    // Fixture mode renders mock data and makes no API calls, so the gate
    // would only be in the way.
    if (isPreviewMode()) return;
    const handleAuthReq = () => setIsOpen(true);
    window.addEventListener("auth-required", handleAuthReq);

    let cancelled = false;
    let probeFailed = false;
    (async () => {
      // Ask the backend whether a credential is even required before deciding
      // to prompt. /health is public, so this works with no token, and it
      // reports only whether auth is needed -- never a secret. Doing this
      // first (rather than opening the modal and closing it later) avoids the
      // gate flashing on screen for a deployment that does not need one.
      try {
        const health = await api.health();
        if (cancelled) return;
        if ((health as { anonymous_reads?: boolean }).anonymous_reads) {
          // Reads are open: browsing needs nothing. A write will raise
          // `auth-required` and the modal opens then.
          try {
            const data = await api.listRepos();
            if (!cancelled) useGraphStore.getState().setRepos(data.repos);
          } catch { /* surfaced by the views themselves */ }
          return;
        }
      } catch {
        // The probe itself failed, so whether auth is required is unknown.
        // Prompting for a token without saying so blames the reader for an
        // outage: /health is public, so its failure is never about credentials.
        probeFailed = true;
      }
      if (cancelled) return;

      if (!getApiToken()) {
        if (probeFailed) {
          setError(BACKEND_UNREACHABLE);
          setDismissible(true);
        }
        setIsOpen(true);
        return;
      }
      try {
        const data = await api.listRepos();
        if (!cancelled) useGraphStore.getState().setRepos(data.repos);
      } catch (err) {
        if (cancelled) return;
        const { message, tokenAtFault } = await diagnose(err);
        // A stored token stays stored unless the server actually rejected it.
        // A backend outage must not cost the user their credential.
        if (tokenAtFault) setApiToken("");
        setError(message);
        setDismissible(!tokenAtFault);
        setIsOpen(true);
      }
    })();

    return () => {
      cancelled = true;
      window.removeEventListener("auth-required", handleAuthReq);
    };
  }, []);

  useEffect(() => {
    if (isOpen) inputRef.current?.focus();
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen || !dismissible) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setIsOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [isOpen, dismissible]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token.trim()) return;
    setLoading(true);
    setError(null);
    const attempted = token.trim();
    try {
      setApiToken(attempted);
      const data = await api.listRepos();
      useGraphStore.getState().setRepos(data.repos);
      setIsOpen(false);
      setToken("");
    } catch (err) {
      const { message, tokenAtFault } = await diagnose(err);
      setError(message);
      setDismissible(!tokenAtFault);
      // Keep what they typed unless the server said it was wrong, so a
      // transient outage does not make them dig the token out again.
      if (tokenAtFault) {
        setApiToken("");
      } else {
        setApiToken(attempted);
      }
    } finally {
      setLoading(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center px-4"
      style={{ background: "var(--scrim)", backdropFilter: "blur(8px)", animation: "fadeIn 0.2s ease-out" }}
      role="dialog"
      aria-modal="true"
      aria-labelledby="auth-modal-title"
    >
      <div className="bg-surface-raised border border-default rounded-xl p-8 w-full max-w-md space-y-6 relative"
           style={{ boxShadow: "var(--elev-3)" }}>
        {dismissible && (
          <button
            type="button"
            onClick={() => setIsOpen(false)}
            aria-label="Dismiss"
            className="absolute top-4 right-4 p-1.5 rounded-md text-tertiary hover:text-primary hover:bg-slate-100 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        )}

        <div className="w-12 h-12 rounded-lg bg-accent-bg border border-accent-border flex items-center justify-center">
          <KeyRound className="w-6 h-6 text-accent-text" />
        </div>

        <div>
          <h2 id="auth-modal-title" className="text-xl font-semibold text-primary">Authorization needed</h2>
          <p className="text-base text-secondary mt-2 leading-relaxed">
            {/* Reads may be open while writes are not, so this copy has to
                cover both cases rather than claiming reading needs a token. */}
            This action needs an authorization token. Paste your{" "}
            <code className="bg-slate-100 px-1 py-0.5 rounded-xs text-accent-text font-mono text-sm">API_TOKEN</code>.
            Ingesting, deleting and rebuilding always require one.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="api-token" className="sr-only">API token</label>
            <input
              id="api-token"
              ref={inputRef}
              type="password"
              placeholder="Paste token…"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              aria-invalid={Boolean(error)}
              aria-describedby={error ? "auth-modal-error" : undefined}
              className="w-full bg-surface-overlay border border-interactive rounded-md px-4 py-3 text-base text-primary font-mono placeholder:text-disabled"
            />
            {error && (
              <p id="auth-modal-error" role="alert" className="text-sm text-danger-text mt-2 leading-relaxed">
                {error}
              </p>
            )}
          </div>

          <button
            type="submit"
            disabled={!token.trim() || loading}
            className="w-full flex items-center justify-center gap-2 bg-accent-solid hover:bg-accent-hover disabled:opacity-50 text-white font-medium px-4 py-3 rounded-md transition-colors"
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Lock className="w-4 h-4" />}
            <span>Connect</span>
            {!loading && <ArrowRight className="w-4 h-4 ml-1 opacity-70" />}
          </button>
        </form>
      </div>
    </div>
  );
}
