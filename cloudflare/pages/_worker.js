// Keep browser requests same-origin; the Python Worker validates every private request.
export default {
  async fetch(request, env) {
    const { pathname } = new URL(request.url);
    if (pathname.startsWith('/api/') || pathname.startsWith('/health/')) {
      try {
        return await env.API.fetch(request);
      } catch {
        return Response.json(
          { error: { code: 'service_unavailable' } },
          { status: 503, headers: { 'Cache-Control': 'no-store' } },
        );
      }
    }
    return env.ASSETS.fetch(request);
  },
};
