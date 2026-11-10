"use client";

import { useEffect, useState } from "react";

type LiveSession = {
  id: string;
  userId: string;
  courseId: string;
  labTitle: string;
  status: string;
  timeLeftSeconds: number;
};

type GuardrailMetrics = {
  dailyVmHoursUsed: number;
  dailyVmHoursCommitted: number;
  dailyVmHoursCap: number;
  activeVms: number;
  maxConcurrentVms: number;
  refusedLaunchesToday: number;
  values: {
    sessionMaxMinutes: number;
    maxExtensions: number;
    idleTimeoutMinutes: number;
    allowedVmSizes: string[];
    warmPoolSize: number;
    vmAutoshutdownTime: string;
    vmAutoshutdownTimezone: string;
  };
};

async function fetchSessions(): Promise<{ sessions: LiveSession[] }> {
  const response = await fetch("/api/backend/api/admin/sessions", { cache: "no-store" });
  if (response.status === 401 || response.status === 403) {
    throw new Error("Admin access is required.");
  }
  if (!response.ok) {
    throw new Error("Could not load live sessions.");
  }
  return (await response.json()) as { sessions: LiveSession[] };
}

async function fetchGuardrails(): Promise<GuardrailMetrics> {
  const response = await fetch("/api/backend/api/admin/guardrails", { cache: "no-store" });
  if (response.status === 401 || response.status === 403) {
    throw new Error("Guardrail metrics are available to admins only.");
  }
  if (!response.ok) {
    throw new Error("Could not load staging guardrail metrics.");
  }
  return (await response.json()) as GuardrailMetrics;
}

export default function AdminPage() {
  const [sessions, setSessions] = useState<LiveSession[]>([]);
  const [error, setError] = useState("");
  const [guardrails, setGuardrails] = useState<GuardrailMetrics | null>(null);
  const [guardrailError, setGuardrailError] = useState("");

  async function loadSessions() {
    try {
      const data = await fetchSessions();
      setSessions(data.sessions);
      setError("");
    } catch (error) {
      setError(error instanceof Error ? error.message : "Could not load live sessions.");
    }
  }

  useEffect(() => {
    let active = true;
    const refresh = () => {
      void fetchSessions()
        .then((data) => {
          if (active) {
            setSessions(data.sessions);
            setError("");
          }
        })
        .catch((error: unknown) => {
          if (active) {
            setError(error instanceof Error ? error.message : "Could not load live sessions.");
          }
        });
    };
    const refreshGuardrails = () => {
        void fetchGuardrails()
          .then((data) => {
            if (active) {
              setGuardrails(data);
              setGuardrailError("");
            }
          })
          .catch((error: unknown) => {
            if (active) {
              setGuardrails(null);
              setGuardrailError(
                error instanceof Error
                  ? error.message
                  : "Could not load staging guardrail metrics.",
              );
            }
          });
    };
    refresh();
    refreshGuardrails();
    const timer = window.setInterval(() => {
        refresh();
        refreshGuardrails();
    }, 10000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  async function endSession(sessionId: string) {
    const response = await fetch(`/api/backend/api/admin/sessions/${sessionId}/end`, {
      method: "POST",
    });
    if (!response.ok) {
      setError("Could not end the session.");
      return;
    }
    await loadSessions();
  }

  async function extendSession(sessionId: string) {
    const response = await fetch(`/api/backend/api/admin/sessions/${sessionId}/extend`, {
      method: "POST",
    });
    if (!response.ok) {
      setError("Could not extend the session.");
      return;
    }
    await loadSessions();
  }

  return (
    <main className="mx-auto max-w-6xl p-6">
      <h1 className="text-2xl font-bold">LabForge Administration</h1>
      <p className="mt-1 text-sm text-slate-600">Live sessions and operational controls</p>
      {error ? <p className="mt-4 text-sm text-red-700">{error}</p> : null}
      <section
        aria-label="Staging cost guardrails"
        className="mt-6 rounded-lg border border-slate-200 bg-white p-4"
      >
        <h2 className="text-lg font-semibold">Staging cost guardrails</h2>
        {guardrails ? (
          <>
            <dl className="mt-3 grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
              <div>
                <dt className="text-slate-500">VM-hours used / committed / cap</dt>
                <dd className="font-semibold">
                  {guardrails.dailyVmHoursUsed} / {guardrails.dailyVmHoursCommitted} / {guardrails.dailyVmHoursCap}
                </dd>
              </div>
              <div>
                <dt className="text-slate-500">Active VMs</dt>
                <dd className="font-semibold">
                  {guardrails.activeVms} / {guardrails.maxConcurrentVms}
                </dd>
              </div>
              <div>
                <dt className="text-slate-500">Refused launches today</dt>
                <dd className="font-semibold">{guardrails.refusedLaunchesToday}</dd>
              </div>
              <div>
                <dt className="text-slate-500">Allowed VM sizes</dt>
                <dd className="font-semibold">{guardrails.values.allowedVmSizes.join(", ")}</dd>
              </div>
              <div>
                <dt className="text-slate-500">Maximum session length</dt>
                <dd className="font-semibold">{guardrails.values.sessionMaxMinutes} minutes</dd>
              </div>
              <div>
                <dt className="text-slate-500">Maximum extensions</dt>
                <dd className="font-semibold">{guardrails.values.maxExtensions}</dd>
              </div>
              <div>
                <dt className="text-slate-500">Idle timeout</dt>
                <dd className="font-semibold">{guardrails.values.idleTimeoutMinutes} minutes</dd>
              </div>
              <div>
                <dt className="text-slate-500">VM auto-shutdown</dt>
                <dd className="font-semibold">
                  {guardrails.values.vmAutoshutdownTime} ({guardrails.values.vmAutoshutdownTimezone})
                </dd>
              </div>
              <div>
                <dt className="text-slate-500">Warm pool</dt>
                <dd className="font-semibold">{guardrails.values.warmPoolSize}</dd>
              </div>
            </dl>
            <p className="mt-3 text-xs text-slate-500">Read-only configuration and usage.</p>
          </>
        ) : (
          <p className="mt-3 text-sm text-slate-600" role="status">
            {guardrailError || "Loading staging guardrails…"}
          </p>
        )}
      </section>
      <div className="mt-6 overflow-x-auto rounded-lg border border-slate-200">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-50">
            <tr>
              <th className="p-3">Learner</th>
              <th className="p-3">Lab</th>
              <th className="p-3">Status</th>
              <th className="p-3">Time left</th>
              <th className="p-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {sessions.map((session) => (
              <tr key={session.id} className="border-t border-slate-200">
                <td className="p-3">{session.userId}</td>
                <td className="p-3">{session.labTitle}</td>
                <td className="p-3">{session.status}</td>
                <td className="p-3">{Math.floor(session.timeLeftSeconds / 60)} min</td>
                <td className="p-3">
                  <button className="mr-2 rounded bg-blue-700 px-3 py-1 text-white" onClick={() => void extendSession(session.id)}>
                    Extend
                  </button>
                  <button className="mr-2 rounded bg-red-700 px-3 py-1 text-white" onClick={() => void endSession(session.id)}>
                    End
                  </button>
                  <a className="rounded border border-slate-300 px-3 py-1" href={`/lab/${session.id}?shadow=true`}>
                    Shadow
                  </a>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <a className="mt-4 inline-block rounded border border-slate-300 px-4 py-2 text-sm" href="/api/backend/api/admin/reports/foundry.csv">
        Export Foundry progress CSV
      </a>
    </main>
  );
}
