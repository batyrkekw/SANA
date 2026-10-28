import { test } from 'node:test';
import assert from 'node:assert/strict';
import worker from '../cloudflare/pages/_worker.js';

test('edge caches public plans only; authenticated responses always reach the API', async (t) => {
  const cache = new Map(), calls = [], retained = [];
  globalThis.caches = { default: {
    async match(key) { return cache.get(key.url)?.clone(); },
    async put(key, value) { cache.set(key.url, value); },
  } };
  t.after(() => { delete globalThis.caches; });
  const env = { API: { async fetch(request) {
    calls.push(request);
    return Response.json({ path: new URL(request.url).pathname }, {
      headers: { 'Cache-Control': 'no-store' },
    });
  } }, ASSETS: { async fetch(request) { return Response.json({ asset: new URL(request.url).pathname }); } } };
  const ctx = { waitUntil(promise) { retained.push(promise); } };
  const request = (path, user) => new Request(`https://sana.example${path}`, {
    headers: { Authorization: `Bearer ${user}` },
  });
  const first = await worker.fetch(request('/api/v1/plans', 'alice'), env, ctx);
  await Promise.all(retained);
  const second = await worker.fetch(request('/api/v1/plans', 'bob'), env, ctx);
  assert.equal(first.headers.get('X-SANA-Cache'), 'MISS');
  assert.equal(second.headers.get('X-SANA-Cache'), 'HIT');
  assert.equal(calls.length, 1);
  assert.equal(calls[0].headers.get('Authorization'), null);
  for (const user of ['alice', 'bob']) {
    const result = await worker.fetch(request('/api/v1/dashboard', user), env, ctx);
    assert.equal(result.headers.get('Cache-Control'), 'no-store');
    assert.equal(calls.at(-1).headers.get('Authorization'), `Bearer ${user}`);
  }
  assert.equal(calls.length, 3);
  const config = await worker.fetch(request('/api/v1/config', 'alice'), env, ctx);
  assert.equal((await config.json()).asset, '/sana-config.json');
  assert.equal(calls.length, 3);
});
