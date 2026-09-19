const REQUEST_TIMEOUT_MS = 20_000;

export async function GET(request: Request) {
  const cronSecret = process.env.CRON_SECRET?.trim();
  if (!cronSecret) {
    return Response.json({ error: "Cron keepalive is not configured" }, { status: 503 });
  }

  const expectedAuthorization = `Bearer ${cronSecret}`;
  if (request.headers.get("authorization") !== expectedAuthorization) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }

  const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL?.trim().replace(/\/$/, "");
  if (!apiBaseUrl) {
    return Response.json({ error: "API base URL is not configured" }, { status: 503 });
  }

  try {
    const response = await fetch(`${apiBaseUrl}/api/system/database-keepalive`, {
      headers: { authorization: expectedAuthorization },
      cache: "no-store",
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });

    if (!response.ok) {
      return Response.json(
        { error: "Database keepalive failed", upstreamStatus: response.status },
        { status: 502 },
      );
    }

    return Response.json({ status: "ok" });
  } catch {
    return Response.json({ error: "Database keepalive failed" }, { status: 502 });
  }
}
