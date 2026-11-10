"use client";

import {
  isValidElement,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { useRouter } from "next/navigation";
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";
import RemoteDesktop, { type RemoteDesktopHandle } from "@/components/remote-desktop";

type LabSession = {
  id: string;
  labId: string;
  labTitle: string;
  courseId: string;
  courseTitle: string;
  status: string;
  expiresAt: string;
};

type Guide = {
  lab: { id: string; title: string; courseId: string; courseTitle: string };
  content: string;
  taskProgress: Record<string, boolean>;
  completed: boolean;
};

type Resources = {
  vm: { username: string | null; password: string | null };
  azure: {
    username: string | null;
    password: string | null;
    subscriptionId: string | null;
    resourceGroup: string | null;
  };
};

type CourseProgress = {
  courseId: string;
  percent: number;
  completed: number;
  total: number;
};

type ValidationCheck = { name: string; passed: boolean; message: string };
type WorkspaceSnapshot = {
  session: LabSession;
  guide: Guide;
  progress: CourseProgress | null;
};

function extractText(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(extractText).join("");
  if (isValidElement<{ children?: ReactNode }>(node)) return extractText(node.props.children);
  return "";
}

function formatTime(seconds: number): string {
  const safe = Math.max(0, seconds);
  return `${Math.floor(safe / 60)
    .toString()
    .padStart(2, "0")}:${(safe % 60).toString().padStart(2, "0")}`;
}

export default function LabWorkspace({ sessionId }: { sessionId: string }) {
  const router = useRouter();
  const remoteRef = useRef<RemoteDesktopHandle>(null);
  const [session, setSession] = useState<LabSession | null>(null);
  const [guide, setGuide] = useState<Guide | null>(null);
  const [resources, setResources] = useState<Resources | null>(null);
  const [progress, setProgress] = useState<CourseProgress | null>(null);
  const [activeTab, setActiveTab] = useState<"instructions" | "resources" | "help">(
    "instructions",
  );
  const [page, setPage] = useState(0);
  const [remainingSeconds, setRemainingSeconds] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [validationChecks, setValidationChecks] = useState<ValidationCheck[]>([]);
  const [visibleSecrets, setVisibleSecrets] = useState<Record<string, boolean>>({});
  const sessionStatus = session?.status;

  const fetchWorkspace = useCallback(async (): Promise<WorkspaceSnapshot> => {
    const [sessionResponse, progressResponse] = await Promise.all([
      fetch(`/api/backend/sessions/${encodeURIComponent(sessionId)}`, { cache: "no-store" }),
      fetch("/api/backend/me/progress", { cache: "no-store" }),
    ]);
    if (!sessionResponse.ok) {
      throw new Error(`Could not load lab session (HTTP ${sessionResponse.status}).`);
    }
    if (!progressResponse.ok) {
      throw new Error(`Could not load course progress (HTTP ${progressResponse.status}).`);
    }
    const sessionData = (await sessionResponse.json()) as LabSession;
    const progressData = (await progressResponse.json()) as { courses: CourseProgress[] };
    const guideResponse = await fetch(
      `/api/backend/labs/${encodeURIComponent(sessionData.labId)}/guide?session_id=${encodeURIComponent(sessionId)}`,
      { cache: "no-store" },
    );
    if (!guideResponse.ok) {
      throw new Error(`Could not load the lab guide (HTTP ${guideResponse.status}).`);
    }
    return {
      session: sessionData,
      guide: (await guideResponse.json()) as Guide,
      progress:
        progressData.courses.find((item) => item.courseId === sessionData.courseId) ?? null,
    };
  }, [sessionId]);

  const applyWorkspace = useCallback(({ session, guide, progress }: WorkspaceSnapshot) => {
    setSession(session);
    setGuide(guide);
    setProgress(progress);
    setRemainingSeconds(
      Math.max(0, Math.floor((Date.parse(session.expiresAt) - Date.now()) / 1000)),
    );
  }, []);

  const loadWorkspace = useCallback(async () => {
    applyWorkspace(await fetchWorkspace());
  }, [applyWorkspace, fetchWorkspace]);

  useEffect(() => {
    let active = true;
    void fetchWorkspace()
      .then((workspace) => {
        if (active) applyWorkspace(workspace);
      })
      .catch((cause: unknown) => {
        if (active) setError(cause instanceof Error ? cause.message : "Could not load lab workspace.");
      });
    return () => {
      active = false;
    };
  }, [applyWorkspace, fetchWorkspace]);

  useEffect(() => {
    if (!session) return;
    const timer = setInterval(() => {
      setRemainingSeconds(
        Math.max(0, Math.floor((Date.parse(session.expiresAt) - Date.now()) / 1000)),
      );
    }, 1000);
    return () => clearInterval(timer);
  }, [session]);

  useEffect(() => {
    if (session?.status !== "ready") return;
    const heartbeat = setInterval(() => {
      void fetch(
        `/api/backend/sessions/${encodeURIComponent(sessionId)}/activity`,
        { method: "POST", cache: "no-store" },
      ).catch(() => undefined);
    }, 60_000);
    return () => clearInterval(heartbeat);
  }, [session?.status, sessionId]);

  useEffect(() => {
    if (!sessionStatus || ["ready", "ending", "ended", "failed"].includes(sessionStatus)) return;
    const timer = setInterval(() => {
      fetch(`/api/backend/sessions/${encodeURIComponent(sessionId)}`, { cache: "no-store" })
        .then(async (response) => {
          if (!response.ok) {
            throw new Error(`Could not refresh lab session (HTTP ${response.status}).`);
          }
          const updated = (await response.json()) as LabSession;
          setSession(updated);
          if (updated.status === "ready") {
            void loadWorkspace().catch((cause: unknown) =>
              setError(cause instanceof Error ? cause.message : "Could not load lab workspace."),
            );
          }
        })
        .catch((cause: unknown) =>
          setError(cause instanceof Error ? cause.message : "Could not refresh lab session."),
        );
    }, 3000);
    return () => clearInterval(timer);
  }, [loadWorkspace, sessionId, sessionStatus]);

  const pages = useMemo(() => guide?.content.split(/\r?\n---page---\r?\n/) ?? [], [guide]);
  const taskOffset = useMemo(
    () =>
      pages
        .slice(0, page)
        .reduce((count, content) => count + (content.match(/^\s*[-*]\s+\[[ xX]\]\s+/gm) ?? []).length, 0),
    [page, pages],
  );
  const loadResources = async () => {
    const response = await fetch(
      `/api/backend/sessions/${encodeURIComponent(sessionId)}/resources`,
      { cache: "no-store" },
    );
    if (!response.ok) throw new Error(`Could not load session resources (HTTP ${response.status}).`);
    setResources((await response.json()) as Resources);
  };

  const toggleTask = async (taskIndex: number, completed: boolean) => {
    if (!guide) return;
    try {
      const response = await fetch(
        `/api/backend/labs/${encodeURIComponent(guide.lab.id)}/tasks/${taskIndex}`,
        {
          method: "PUT",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ completed }),
        },
      );
      if (!response.ok) {
        setError(`Could not save task progress (HTTP ${response.status}).`);
        return;
      }
      setGuide({
        ...guide,
        taskProgress: { ...guide.taskProgress, [taskIndex]: completed },
      });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not save task progress.");
    }
  };

  const markComplete = async () => {
    if (!guide) return;
    try {
      const response = await fetch(
        `/api/backend/labs/${encodeURIComponent(guide.lab.id)}/complete`,
        { method: "POST" },
      );
      if (!response.ok) {
        setError(`Could not mark the lab complete (HTTP ${response.status}).`);
        return;
      }
      setGuide({ ...guide, completed: true });
      await loadWorkspace();
      setNotice("Lab completed. Your course progress has been saved.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not mark the lab complete.");
    }
  };

  const extendSession = async () => {
    try {
      const response = await fetch(
        `/api/backend/sessions/${encodeURIComponent(sessionId)}/extend`,
        { method: "POST" },
      );
      if (!response.ok) {
        setError(`Could not extend the lab session (HTTP ${response.status}).`);
        return;
      }
      await loadWorkspace();
      setNotice("Lab session extended.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not extend the lab session.");
    }
  };

  const endSession = async () => {
    if (!session || !window.confirm("End this lab session? Session resources will be cleaned up.")) {
      return;
    }
    try {
      const response = await fetch(
        `/api/backend/sessions/${encodeURIComponent(sessionId)}/end`,
        { method: "POST" },
      );
      if (!response.ok) {
        setError(`Could not end the lab session (HTTP ${response.status}).`);
        return;
      }
      router.push(`/courses/${encodeURIComponent(session.courseId)}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not end the lab session.");
    }
  };

  const validateLab = async () => {
    if (!guide) return;
    setValidationChecks([]);
    try {
      const response = await fetch(
        `/api/backend/labs/${encodeURIComponent(guide.lab.id)}/validate?session_id=${encodeURIComponent(sessionId)}`,
        { method: "POST" },
      );
      const data = (await response.json()) as {
        passed?: boolean;
        checks?: ValidationCheck[];
        detail?: string;
      };
      if (!response.ok) {
        setError(data.detail ?? `Validation failed to run (HTTP ${response.status}).`);
        return;
      }
      setValidationChecks(data.checks ?? []);
      setNotice(data.passed ? "Validation passed." : "Validation ran, but some requirements are not met.");
      if (data.passed) await loadWorkspace();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Validation failed to run.");
    }
  };

  const copyValue = async (label: string, value: string | null) => {
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
      setNotice(`${label} copied to clipboard.`);
    } catch {
      setError("The browser blocked clipboard access. Check clipboard permissions.");
    }
  };

  let checkboxCounter = 0;
  const markdownComponents: Components = {
    input: ({ checked }) => {
      const taskIndex = taskOffset + checkboxCounter++;
      const isChecked = guide?.taskProgress[String(taskIndex)] ?? checked ?? false;
      return (
        <input
          aria-label={`Mark task ${taskIndex + 1} complete`}
          checked={isChecked}
          className="mr-2 align-middle accent-blue-700"
          onChange={(event) => void toggleTask(taskIndex, event.currentTarget.checked)}
          type="checkbox"
        />
      );
    },
    pre: ({ children }) => {
      const text = extractText(children).replace(/\n$/, "");
      return (
        <div className="my-4 overflow-hidden rounded-lg border border-slate-700">
          <div className="flex justify-end bg-slate-800 px-3 py-2">
            <button
              className="rounded bg-blue-600 px-2 py-1 text-xs font-medium text-white hover:bg-blue-500"
              onClick={() => {
                if (!remoteRef.current?.sendText(text)) {
                  setError("Only printable ASCII can currently be typed into the VM.");
                }
              }}
              type="button"
            >
              Type into VM
            </button>
          </div>
          <pre className="overflow-x-auto bg-slate-950 p-4 text-sm text-slate-100">{children}</pre>
        </div>
      );
    },
    h1: ({ children }) => <h1 className="mb-4 text-2xl font-bold">{children}</h1>,
    h2: ({ children }) => <h2 className="mb-3 mt-6 text-xl font-semibold">{children}</h2>,
    p: ({ children }) => <p className="my-3 leading-7 text-slate-700">{children}</p>,
    ul: ({ children }) => <ul className="my-3 list-disc space-y-2 pl-6">{children}</ul>,
    ol: ({ children }) => <ol className="my-3 list-decimal space-y-2 pl-6">{children}</ol>,
    blockquote: ({ children }) => (
      <blockquote className="my-4 border-l-4 border-amber-400 bg-amber-50 px-4 py-2">
        {children}
      </blockquote>
    ),
  };

  if (error && !session) {
    return <main className="p-8 text-red-700">{error}</main>;
  }
  if (!session || !guide) {
    return (
      <main className="grid min-h-screen place-items-center bg-slate-100">
        <div className="rounded-xl bg-white p-8 text-center shadow">
          <h1 className="text-xl font-semibold">Preparing your lab workspace…</h1>
          <p className="mt-2 text-sm text-slate-600">
            Loading session, course progress, and lab instructions.
          </p>
        </div>
      </main>
    );
  }

  const pageContent = pages[page] ?? "";
  const isReady = session.status === "ready";

  return (
    <main className="flex h-screen min-h-[600px] flex-col overflow-hidden bg-slate-100 text-slate-900">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b bg-white px-4 py-3">
        <div className="min-w-0">
          <p className="truncate text-xs font-medium text-slate-500">{session.courseTitle}</p>
          <h1 className="truncate font-semibold">{session.labTitle}</h1>
        </div>
        <div className="flex items-center gap-3">
          {progress ? (
            <div className="hidden min-w-32 sm:block">
              <div className="flex justify-between text-xs">
                <span>Progress</span>
                <span>{progress.percent}%</span>
              </div>
              <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-200">
                <div className="h-full bg-blue-700" style={{ width: `${progress.percent}%` }} />
              </div>
            </div>
          ) : null}
          <span className="rounded bg-slate-100 px-2 py-1 font-mono text-sm" aria-label="Time remaining">
            {formatTime(remainingSeconds)}
          </span>
          <button
            className="rounded border px-3 py-1.5 text-sm disabled:opacity-50"
            disabled={!isReady}
            onClick={() => void extendSession()}
            type="button"
          >
            Extend
          </button>
          <button
            className="rounded bg-red-700 px-3 py-1.5 text-sm text-white hover:bg-red-800"
            onClick={() => void endSession()}
            type="button"
          >
            End lab
          </button>
        </div>
      </header>

      {error || notice ? (
        <div
          className={`flex items-center justify-between px-4 py-2 text-sm ${
            error ? "bg-red-50 text-red-800" : "bg-emerald-50 text-emerald-800"
          }`}
          role="status"
        >
          <div>
            <p>{error ?? notice}</p>
            {validationChecks.length ? (
              <ul className="mt-1 space-y-1">
                {validationChecks.map((check) => (
                  <li key={check.name} className={check.passed ? "text-emerald-800" : "text-red-800"}>
                    {check.passed ? "Passed" : "Not yet"} — {check.name}: {check.message}
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
          <button
            aria-label="Dismiss message"
            onClick={() => {
              setError(null);
              setNotice(null);
            }}
            type="button"
          >
            ×
          </button>
        </div>
      ) : null}

      <PanelGroup className="min-h-0 flex-1" direction="horizontal">
        <Panel
          className="flex min-h-0 flex-col border-r bg-white"
          collapsible
          collapsedSize={0}
          defaultSize={40}
          minSize={25}
        >
          <nav className="flex border-b" aria-label="Workspace tabs">
            {(["instructions", "resources", "help"] as const).map((tab) => (
              <button
                aria-current={activeTab === tab ? "page" : undefined}
                className={`flex-1 border-b-2 px-3 py-3 text-sm font-medium capitalize ${
                  activeTab === tab
                    ? "border-blue-700 text-blue-700"
                    : "border-transparent text-slate-500"
                }`}
                key={tab}
                onClick={() => {
                  setActiveTab(tab);
                  if (tab === "resources" && !resources) {
                    loadResources().catch((cause: unknown) =>
                      setError(cause instanceof Error ? cause.message : "Could not load resources."),
                    );
                  }
                }}
                type="button"
              >
                {tab}
              </button>
            ))}
          </nav>

          {activeTab === "instructions" ? (
            <>
              <div className="min-h-0 flex-1 overflow-y-auto p-5">
                <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                  {pageContent}
                </ReactMarkdown>
              </div>
              <footer className="flex flex-wrap items-center justify-between gap-2 border-t p-3">
                <button
                  className="rounded border px-3 py-2 text-sm disabled:opacity-40"
                  disabled={page === 0}
                  onClick={() => setPage((current) => Math.max(0, current - 1))}
                  type="button"
                >
                  Previous
                </button>
                <span className="text-sm text-slate-500">
                  Page {page + 1} of {pages.length}
                </span>
                {page < pages.length - 1 ? (
                  <button
                    className="rounded border px-3 py-2 text-sm"
                    onClick={() => setPage((current) => Math.min(pages.length - 1, current + 1))}
                    type="button"
                  >
                    Next
                  </button>
                ) : (
                  <div className="flex gap-2">
                    <button
                      className="rounded border border-blue-700 px-3 py-2 text-sm text-blue-700"
                      onClick={() => void validateLab()}
                      type="button"
                    >
                      Validate
                    </button>
                    <button
                      className="rounded bg-blue-700 px-3 py-2 text-sm text-white disabled:opacity-50"
                      disabled={guide.completed}
                      onClick={() => void markComplete()}
                      type="button"
                    >
                      {guide.completed ? "Completed" : "Mark complete"}
                    </button>
                  </div>
                )}
              </footer>
            </>
          ) : null}

          {activeTab === "resources" ? (
            <div className="min-h-0 flex-1 space-y-6 overflow-y-auto p-5">
              {!resources ? <p className="text-sm text-slate-500">Loading session resources…</p> : null}
              {resources ? (
                <>
                  <ResourceField
                    label="VM username"
                    value={resources.vm.username}
                    onCopy={copyValue}
                  />
                  <ResourceField
                    label="VM password"
                    value={resources.vm.password}
                    visible={visibleSecrets.vm}
                    onCopy={copyValue}
                    onToggle={() =>
                      setVisibleSecrets((current) => ({ ...current, vm: !current.vm }))
                    }
                  />
                  <ResourceField
                    label="Azure username"
                    value={resources.azure.username}
                    onCopy={copyValue}
                  />
                  <ResourceField
                    label="Azure password"
                    value={resources.azure.password}
                    visible={visibleSecrets.azure}
                    onCopy={copyValue}
                    onToggle={() =>
                      setVisibleSecrets((current) => ({ ...current, azure: !current.azure }))
                    }
                  />
                  <ResourceField
                    label="Azure subscription"
                    value={resources.azure.subscriptionId}
                    onCopy={copyValue}
                  />
                  <ResourceField
                    label="Azure resource group"
                    value={resources.azure.resourceGroup}
                    onCopy={copyValue}
                  />
                </>
              ) : null}
            </div>
          ) : null}

          {activeTab === "help" ? (
            <div className="min-h-0 flex-1 overflow-y-auto p-5 text-sm leading-6 text-slate-700">
              <h2 className="text-lg font-semibold text-slate-950">Need help?</h2>
              <p className="mt-3">
                Wait for the desktop to connect, then click inside it before typing. Use the
                clipboard button above the desktop to paste text from your browser.
              </p>
              <p className="mt-3">
                If the desktop disconnects, LabForge attempts to reconnect. Use the course support
                channel if it does not recover.
              </p>
            </div>
          ) : null}
        </Panel>

        <PanelResizeHandle
          aria-label="Resize instructions and desktop panels"
          className="w-1 cursor-col-resize bg-slate-200 hover:bg-blue-500"
        />
        <Panel className="min-h-0 min-w-0" defaultSize={60} minSize={30}>
          {isReady ? (
            <RemoteDesktop ref={remoteRef} sessionId={sessionId} />
          ) : (
            <div className="grid h-full place-items-center bg-slate-900 p-8 text-center text-white">
              <div>
                <h2 className="text-xl font-semibold">Preparing your environment</h2>
                <p className="mt-2 text-sm text-slate-300">Current session status: {session.status}</p>
                <ol className="mt-5 space-y-2 text-left text-sm text-slate-300">
                  <li>1. Allocating VM</li>
                  <li>2. Starting Windows</li>
                  <li>3. Connecting to desktop</li>
                </ol>
              </div>
            </div>
          )}
        </Panel>
      </PanelGroup>
    </main>
  );
}

function ResourceField({
  label,
  value,
  visible = true,
  onCopy,
  onToggle,
}: {
  label: string;
  value: string | null;
  visible?: boolean;
  onCopy: (label: string, value: string | null) => Promise<void>;
  onToggle?: () => void;
}) {
  return (
    <div>
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</p>
      <div className="mt-1 flex gap-2">
        <input
          className="min-w-0 flex-1 rounded border bg-slate-50 px-3 py-2 text-sm"
          readOnly
          type={onToggle && !visible ? "password" : "text"}
          value={value ?? ""}
        />
        {onToggle ? (
          <button className="rounded border px-2 text-sm" onClick={onToggle} type="button">
            {visible ? "Hide" : "Show"}
          </button>
        ) : null}
        <button
          className="rounded border px-2 text-sm disabled:opacity-40"
          disabled={!value}
          onClick={() => void onCopy(label, value)}
          type="button"
        >
          Copy
        </button>
      </div>
    </div>
  );
}
