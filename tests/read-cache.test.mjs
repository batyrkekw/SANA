import test from 'node:test';
import assert from 'node:assert/strict';
import { ReadCache, forConsumer } from '../dist/read-cache.js';
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
};
function fixture() {
  let time = 1000;
  const values = new Map(),
    updates = [],
    errors = [];
  const options = {
    now: () => time,
    storage: {
      getItem: (key) => values.get(key),
      setItem: (key, value) => values.set(key, value),
      removeItem: (key) => values.delete(key),
    },
    onUpdate: (event) => updates.push(event),
    onError: (event) => errors.push(event),
  };
  const cache = new ReadCache(options);
  cache.identify('alice');
  return {
    cache,
    options,
    values,
    updates,
    errors,
    advance: (ms) => {
      time += ms;
    },
  };
}
test('stale snapshots return before a blocked refresh, with one deduplicated request', async () => {
  const { cache, advance, updates } = fixture();
  await cache.read('/dashboard', async () => ({ tokens: 100 }));
  advance(16000);
  const next = deferred();
  let calls = 0;
  const loader = () => {
    calls++;
    return next.promise;
  };
  const first = await cache.read('/dashboard', loader);
  first.tokens = -1;
  assert.deepEqual(await cache.read('/dashboard', loader), { tokens: 100 });
  const fresh = cache.read('/dashboard', loader, { waitForFresh: true });
  assert.equal(calls, 1);
  next.resolve({ tokens: 94 });
  assert.deepEqual(await fresh, { tokens: 94 });
  assert.equal(updates.at(-1).previous.tokens, 100);
});
test('a reload restores only the same owner and bounded-age snapshots', async () => {
  const { cache, advance, options, values } = fixture();
  await cache.read('/materials', async () => ({ items: ['private lesson'] }));
  const reloaded = new ReadCache(options);
  reloaded.identify('alice');
  assert.deepEqual(reloaded.peek('/materials').items, ['private lesson']);
  reloaded.identify('bob');
  assert.equal(reloaded.peek('/materials'), undefined);
  assert.equal(values.size, 0);
  await reloaded.read('/materials', async () => ({ items: ['bob lesson'] }));
  advance(30 * 60 * 1000);
  const expired = new ReadCache(options);
  expired.identify('bob');
  assert.equal(expired.peek('/materials'), undefined);
});
test('writes and logout discard late reads, including requests shared by multiple consumers', async () => {
  for (const invalidate of [(cache) => cache.clear(), (cache) => cache.identify(null)]) {
    const { cache, values } = fixture();
    const old = deferred();
    const pending = cache.read('/materials', () => old.promise);
    await Promise.resolve();
    invalidate(cache);
    old.resolve({ items: ['deleted'] });
    await assert.rejects(pending, { name: 'AbortError' });
    assert.equal(cache.peek('/materials'), undefined);
    assert.equal(values.size, 0);
  }
});
test('aborting navigation does not abort a shared prefetch or its next consumer', async () => {
  const { cache } = fixture();
  const next = deferred(),
    controller = new AbortController();
  const request = cache.read('/materials', () => next.promise);
  const first = forConsumer(request, controller.signal);
  const second = cache.read('/materials', () => {
    throw new Error('duplicate fetch');
  });
  controller.abort();
  await assert.rejects(first, { name: 'AbortError' });
  next.resolve({ items: [1] });
  assert.deepEqual(await second, { items: [1] });
});
test('offline revalidation keeps a snapshot and reports a background error', async () => {
  const { cache, advance, errors } = fixture();
  await cache.read('/materials', async () => ({ items: [1] }));
  advance(16000);
  assert.deepEqual(
    await cache.read('/materials', async () => {
      throw new Error('offline');
    }),
    { items: [1] }
  );
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(errors.length, 1);
  assert.deepEqual(cache.peek('/materials'), { items: [1] });
});
test('disabled or corrupt storage cannot break a normal read', async () => {
  for (const storage of [
    { getItem: () => '{bad json', removeItem() {} },
    {
      getItem: () => JSON.stringify({ owner: 'alice', entries: [null, 42, ['bad', null]] }),
      removeItem() {},
    },
    {
      getItem() {
        throw new Error('disabled');
      },
      removeItem() {
        throw new Error('disabled');
      },
    },
  ]) {
    const cache = new ReadCache({ storage });
    cache.identify('alice');
    assert.equal(await cache.read('/plans', async () => 1), 1);
  }
});
test('permission or deletion errors remove snapshots instead of serving them indefinitely', async () => {
  const { cache, advance, errors } = fixture();
  await cache.read('/materials/one', async () => ({ title: 'Private lesson' }));
  advance(16000);
  await cache.read('/materials/one', async () => {
    throw Object.assign(new Error('not found'), { status: 404 });
  });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(cache.peek('/materials/one'), undefined);
  assert.equal(errors[0].error.status, 404);
});
