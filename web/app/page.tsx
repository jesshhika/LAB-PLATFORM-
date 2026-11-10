import Link from "next/link";

type HealthResponse = {
  status: string;
  service: string;
};

async function getApiHealth(): Promise<HealthResponse | null> {
  const apiUrl = process.env.API_INTERNAL_URL ?? "http://localhost:8000";
  const response = await fetch(`${apiUrl}/api/health`, { cache: "no-store" });

  if (!response.ok) {
    return null;
  }

  return (await response.json()) as HealthResponse;
}

export default async function Home() {
  let health: HealthResponse | null = null;
  let error: string | null = null;

  try {
    health = await getApiHealth();
  } catch (cause) {
    error = cause instanceof Error ? cause.message : "The API health check failed.";
  }

  return (
    <main className="mx-auto my-[10vh] max-w-[720px] p-8">
      <p className="text-sm font-semibold uppercase tracking-widest text-blue-700">
        LabForge
      </p>
      <h1 className="mt-3 text-4xl font-bold">Hands-on learning starts here.</h1>
      <p className="mt-4 text-slate-600">
        Your lab platform foundation is running.
      </p>
      <p className="status mt-8" role="status" aria-live="polite">
        {health?.status === "healthy" ? "API healthy" : "API unavailable"}
      </p>
      <Link
        className="mt-6 inline-flex rounded-lg bg-blue-700 px-4 py-2 font-semibold text-white hover:bg-blue-800"
        href="/courses/foundry"
      >
        Open Microsoft Foundry Bootcamp
      </Link>
      {error ? <p className="mt-3 text-sm text-red-700">{error}</p> : null}
    </main>
  );
}
