import test from 'node:test';
import assert from 'node:assert/strict';
import { AssetCache } from '../dist/asset-cache.js';

const panel = (size = 4) => new Blob(['x'.repeat(size)], { type: 'image/png' });
const deferred = () => {
  let resolve;
  const promise = new Promise((r) => {
    resolve = r;
  });
  return { promise, resolve };
};

test('cover and reader share one image fetch and reuse its blob', async () => {
  const cache = new AssetCache();
  cache.identify('alice');
  let calls = 0;
  const loader = async () => {
    calls++;
    return panel();
  };
  const [a, b] = await Promise.all([cache.read('/one', loader), cache.read('/one', loader)]);
  assert.equal(a, b);
  assert.equal(await cache.read('/one', loader), a);
  assert.equal(calls, 1);
});

test('account switch rejects in-flight and queued images without fetching for the old user', async () => {
  const cache = new AssetCache({ concurrency: 1 });
  cache.identify('alice');
  const slow = deferred();
  const first = cache.read('/one', () => slow.promise);
  let oldQueuedCalled = false;
  const queued = cache.read('/two', () => {
    oldQueuedCalled = true;
    return panel();
  });
  const checks = [
    assert.rejects(first, { name: 'AbortError' }),
    assert.rejects(queued, { name: 'AbortError' }),
  ];
  await Promise.resolve();
  cache.identify('bob');
  slow.resolve(panel());
  await Promise.all(checks);
  assert.equal(oldQueuedCalled, false);
  assert.equal(cache.entries.size, 0);
  let calls = 0;
  await cache.read('/one', () => {
    calls++;
    return panel();
  });
  assert.equal(calls, 1);
});

test('bounded image concurrency and memory; failed loads can be retried', async () => {
  const cache = new AssetCache({ concurrency: 2, maxBytes: 8 });
  cache.identify('alice');
  let active = 0,
    peak = 0,
    calls = 0;
  const loader = async () => {
    active++;
    calls++;
    peak = Math.max(peak, active);
    await new Promise((r) => setTimeout(r, 5));
    active--;
    return panel();
  };
  await Promise.all([1, 2, 3, 4].map((id) => cache.read(`/${id}`, loader)));
  assert.equal(peak, 2);
  assert.equal(cache.bytes, 8);
  await cache.read('/1', loader);
  assert.equal(calls, 5);
  await assert.rejects(
    cache.read('/error', () => {
      throw new Error('network');
    })
  );
  assert.equal((await cache.read('/error', loader)).size, 4);
  cache.identify(null);
  assert.equal(cache.bytes, 0);
});

test('non-image responses are never cached as private images', async () => {
  const cache = new AssetCache();
  cache.identify('alice');
  await assert.rejects(cache.read('/one', () => new Blob(['login'], { type: 'text/html' })));
  assert.equal(cache.entries.size, 0);
});

test('new lesson images run before old queued covers, and shared work can be promoted', async () => {
  const cache = new AssetCache({ concurrency: 1 });
  cache.identify('alice');
  const gate = deferred(),
    order = [];
  const first = cache.read('/first', () => gate.promise, 1);
  const cover = cache.read(
    '/cover',
    () => {
      order.push('cover');
      return panel();
    },
    1
  );
  const promoted = cache.read(
    '/lesson',
    () => {
      order.push('lesson');
      return panel();
    },
    1
  );
  const reader = cache.read(
    '/lesson',
    () => {
      throw new Error('duplicate');
    },
    2
  );
  gate.resolve(panel());
  await Promise.all([first, cover, promoted, reader]);
  assert.deepEqual(order, ['lesson', 'cover']);
});
