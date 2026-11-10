import { NextRequest, NextResponse } from "next/server";

type RouteContext = {
  params: Promise<{ path: string[] }>;
};

async function forward(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  const safePath = path.map((segment) => encodeURIComponent(segment)).join("/");
  const apiUrl = process.env.API_INTERNAL_URL ?? "http://localhost:8000";
  const target = new URL(`/api/${safePath}${request.nextUrl.search}`, apiUrl);
  const headers = new Headers();
  const contentType = request.headers.get("content-type");
  const authorization = request.headers.get("authorization");

  if (contentType) headers.set("content-type", contentType);
  if (authorization) headers.set("authorization", authorization);
  if (process.env.APP_ENV === "development" && process.env.DEV_USER_ID) {
    headers.set("x-user-id", process.env.DEV_USER_ID);
  }

  let body: string | undefined;
  if (request.method !== "GET" && request.method !== "HEAD") {
    body = await request.text();
  }

  try {
    const response = await fetch(target, {
      method: request.method,
      headers,
      body,
      cache: "no-store",
    });
    return new NextResponse(response.body, {
      status: response.status,
      headers: {
        "content-type": response.headers.get("content-type") ?? "application/json",
        "cache-control": "no-store",
      },
    });
  } catch (error) {
    console.error("LabForge API proxy request failed.", error);
    return NextResponse.json({ detail: "The LabForge API is unavailable." }, { status: 502 });
  }
}

export const GET = forward;
export const POST = forward;
export const PUT = forward;
