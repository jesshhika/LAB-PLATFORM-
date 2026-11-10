"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { getLaunchErrorMessage } from "@/lib/launch-error.js";

type Lab = {
  id: string;
  number: number;
  title: string;
  completed: boolean;
};

type ActiveSession = {
  id: string;
  labId: string;
  status: string;
  expiresAt: string;
};

type Course = {
  id: string;
  learnerName: string;
  title: string;
  description: string;
  completed: number;
  total: number;
  percent: number;
  labs: Lab[];
  sessions: ActiveSession[];
};

export default function CoursePage() {
  const { courseId } = useParams<{ courseId: string }>();
  const router = useRouter();
  const [course, setCourse] = useState<Course | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [launchingLabId, setLaunchingLabId] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    fetch(`/api/backend/courses/${encodeURIComponent(courseId)}`, { cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) throw new Error(`Could not load course (HTTP ${response.status}).`);
        return (await response.json()) as Course;
      })
      .then((data) => {
        if (active) setCourse(data);
      })
      .catch((cause: unknown) => {
        if (active) setError(cause instanceof Error ? cause.message : "Could not load course.");
      });
    return () => {
      active = false;
    };
  }, [courseId]);

  const downloadCertificate = async () => {
    if (!course) return;
    setDownloading(true);
    setError(null);
    try {
      const { PDFDocument, StandardFonts } = await import("pdf-lib");
      const document = await PDFDocument.create();
      const page = document.addPage([612, 792]);
      const font = await document.embedFont(StandardFonts.Helvetica);
      page.drawText("Certificate of Completion", {
        x: 90,
        y: 625,
        size: 28,
        font,
      });
      page.drawText(course.learnerName, { x: 90, y: 540, size: 24, font });
      page.drawText("has successfully completed", { x: 90, y: 495, size: 16, font });
      page.drawText(course.title, { x: 90, y: 465, size: 18, font });
      page.drawText(`Completed ${new Date().toLocaleDateString()}`, {
        x: 90,
        y: 390,
        size: 14,
        font,
      });
      const dataUri = await document.saveAsBase64({ dataUri: true });
      const link = window.document.createElement("a");
      link.href = dataUri;
      link.download = `${course.id}-certificate.pdf`;
      window.document.body.append(link);
      link.click();
      link.remove();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not generate the certificate.");
    } finally {
      setDownloading(false);
    }
  };

  const launchLab = async (labId: string) => {
    setLaunchingLabId(labId);
    setError(null);
    try {
      const response = await fetch("/api/backend/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ labId }),
      });
      if (!response.ok) {
        throw new Error(getLaunchErrorMessage(response.status));
      }
      const session = (await response.json()) as ActiveSession;
      router.push(`/lab/${encodeURIComponent(session.id)}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not launch lab.");
      setLaunchingLabId(null);
    }
  };

  if (error) return <main className="mx-auto max-w-4xl p-8 text-red-700">{error}</main>;
  if (!course) return <main className="mx-auto max-w-4xl p-8">Loading course…</main>;

  return (
    <main className="mx-auto max-w-4xl space-y-8 px-6 py-10">
      <Link className="text-sm font-medium text-blue-700 hover:underline" href="/">
        ← LabForge
      </Link>
      <header className="space-y-3">
        <p className="text-sm font-semibold uppercase tracking-widest text-blue-700">Course</p>
        <h1 className="text-4xl font-bold text-slate-950">{course.title}</h1>
        <p className="text-slate-600">{course.description}</p>
        <div className="space-y-2 pt-2">
          <div className="flex justify-between text-sm font-medium">
            <span>Course progress</span>
            <span>{course.percent}%</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-slate-200">
            <div className="h-full bg-blue-700" style={{ width: `${course.percent}%` }} />
          </div>
          <p className="text-sm text-slate-500">
            {course.completed} of {course.total} labs complete
          </p>
        </div>
      </header>

      {course.percent === 100 ? (
        <section
          aria-label="Course completion certificate"
          className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-emerald-300 bg-emerald-50 p-6"
          role="status"
        >
          <div>
            <p aria-hidden="true" className="text-2xl">🎉</p>
            <h2 className="mt-1 text-xl font-bold text-emerald-900">Course complete!</h2>
            <p className="mt-1 text-sm text-emerald-800">You completed every lab in this course.</p>
          </div>
          <button
            className="rounded-lg bg-emerald-800 px-4 py-2 font-semibold text-white hover:bg-emerald-900 disabled:opacity-50"
            disabled={downloading}
            onClick={() => void downloadCertificate()}
            type="button"
          >
            {downloading ? "Creating certificate…" : "Download PDF certificate"}
          </button>
        </section>
      ) : null}

      <section className="space-y-3" aria-label="Course labs">
        {course.labs.map((lab) => {
          const activeSession = course.sessions.find((session) => session.labId === lab.id);
          return (
            <article
              className="flex items-center justify-between gap-4 rounded-xl border border-slate-200 bg-white p-5"
              key={lab.id}
            >
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                  Lab {lab.number}
                </p>
                <h2 className="mt-1 text-lg font-semibold text-slate-900">{lab.title}</h2>
              </div>
              <div className="flex items-center gap-3">
                <span
                  className={`rounded-full px-3 py-1 text-sm font-medium ${
                    lab.completed ? "bg-emerald-100 text-emerald-800" : "bg-slate-100 text-slate-600"
                  }`}
                >
                  {lab.completed ? "Completed" : "Not started"}
                </span>
                {activeSession ? (
                  <Link
                    className="rounded-lg bg-blue-700 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-800"
                    href={`/lab/${encodeURIComponent(activeSession.id)}`}
                  >
                    Open workspace
                  </Link>
                ) : (
                  <button
                    className="rounded-lg bg-blue-700 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-800 disabled:opacity-50"
                    disabled={launchingLabId === lab.id}
                    onClick={() => void launchLab(lab.id)}
                    type="button"
                  >
                    {launchingLabId === lab.id ? "Launching…" : "Launch lab"}
                  </button>
                )}
              </div>
            </article>
          );
        })}
      </section>

      <p className="rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950">
        Local launch opens the lab guide and workspace for screenshots. Live Azure VM provisioning and
        remote desktop connection require Azure credentials and a built golden image.
      </p>
    </main>
  );
}
