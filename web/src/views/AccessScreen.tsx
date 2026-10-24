// What shows before the bench: the access code field when the public backend asks for one,
// or a short offline note while the backend does not answer (it retries on its own).
import { useState, type FormEvent } from "react";
import { Logo } from "../components/TopBar";
import { StatusDot } from "../components/ui/primitives";
import { useSource } from "../events/source";

export function AccessScreen() {
  const access = useSource((s) => s.access);
  const unlock = useSource((s) => s.unlock);
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // While the first health check runs, the page stays quiet instead of flashing a screen.
  if (access === "checking") return <div className="h-full bg-page" />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!code.trim() || busy) return;
    setBusy(true);
    setError(await unlock(code));
    setBusy(false);
  };

  return (
    <div className="flex h-full items-center justify-center bg-page px-4">
      <div className="w-full max-w-[400px] animate-rise rounded-[var(--radius-card)] bg-card p-8 shadow-[var(--shadow-float)]">
        <div className="flex items-center gap-3">
          <Logo size={44} />
          <h1 className="text-[22px] font-semibold tracking-tight text-ink">AnyBuild</h1>
        </div>
        {access === "offline" ? (
          <p role="status" className="mt-6 flex items-center gap-2.5 text-[15px] font-semibold text-ink-2">
            <StatusDot tone="agent" pulse />
            Live backend offline, try again shortly.
          </p>
        ) : (
          <form onSubmit={submit} className="mt-6">
            <label htmlFor="access-code" className="text-[15px] font-semibold text-ink-2">
              Enter access code
            </label>
            <div className="mt-2 flex gap-2">
              <input
                id="access-code"
                type="password"
                autoComplete="off"
                autoFocus
                value={code}
                onChange={(e) => {
                  setCode(e.target.value);
                  setError(null);
                }}
                aria-invalid={error ? true : undefined}
                aria-describedby={error ? "access-error" : undefined}
                className="min-w-0 flex-1 rounded-[var(--radius-tile)] bg-tile px-4 py-3 text-[16px] text-ink outline-none placeholder:text-faint focus:ring-2 focus:ring-accent/40"
              />
              <button
                type="submit"
                disabled={!code.trim() || busy}
                className="shrink-0 rounded-[var(--radius-tile)] bg-ink px-5 text-[15px] font-semibold text-white transition hover:brightness-125 disabled:opacity-40"
              >
                {busy ? "…" : "Enter"}
              </button>
            </div>
            {error && (
              <p id="access-error" role="alert" className="mt-3 text-[14px] font-medium text-fail-ink">
                {error}
              </p>
            )}
          </form>
        )}
      </div>
    </div>
  );
}
