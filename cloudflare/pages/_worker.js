// Keep browser requests same-origin; the Python Worker validates every private request.
export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const { pathname } = url;
    // Public configuration needs no database or Python startup.
    if (request.method === 'GET' && pathname === '/api/v1/config') {
      return env.ASSETS.fetch(new Request(new URL('/sana-config.json', url), { method: 'GET' }));
    }
    // Only the public plan catalogue may enter a shared cache. Account data never does.
    if (request.method === 'GET' && pathname === '/api/v1/plans') {
      const key = new Request(new URL('/api/v1/plans', url), { method: 'GET' });
      const cached = await caches.default.match(key);
      if (cached) {
        const hit = new Response(cached.body, cached);
        hit.headers.set('X-SANA-Cache', 'HIT');
        return hit;
      }
      const response = await env.API.fetch(key);
      if (!response.ok) return response;
      const result = new Response(response.body, response);
      result.headers.set('Cache-Control', 'public, max-age=60');
      result.headers.set('X-SANA-Cache', 'MISS');
      ctx.waitUntil(caches.default.put(key, result.clone()));
      return result;
    }
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
