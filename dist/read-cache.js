// Per-tab, per-user snapshots. HTTP responses and credentials are never cached here.
const STORAGE_KEY = 'sana-reads-v1';
const MAX_AGE = 30 * 60 * 1000;
const MAX_ENTRIES = 40;
const MAX_CHARACTERS = 500_000;
export class ReadCache {
  constructor({ storage, now = () => Date.now(), onUpdate = () => {}, onError = () => {} } = {}) {
    this.storage = storage;
    this.now = now;
    this.onUpdate = onUpdate;
    this.onError = onError;
    this.entries = new Map();
    this.pending = new Map();
    this.epoch = 0;
  }
  identify(owner) {
    if (owner === this.owner) return;
    let saved;
    try {
      saved = JSON.parse(this.storage?.getItem(STORAGE_KEY) || 'null');
    } catch {
      /* Optional storage. */
    }
    this.clear();
    this.owner = owner;
    if (owner && saved?.owner === owner && Array.isArray(saved.entries)) {
      for (const pair of saved.entries.slice(-MAX_ENTRIES)) {
        if (!Array.isArray(pair)) continue;
        const [path, entry] = pair;
        if (
          typeof path === 'string' &&
          entry &&
          Number.isFinite(entry.at) &&
          entry.at <= this.now() &&
          this.now() - entry.at < MAX_AGE
        )
          this.entries.set(path, entry);
      }
      this.persist();
    }
  }
  clear(prefixes) {
    this.epoch++;
    this.pending.clear();
    if (prefixes) {
      for (const path of this.entries.keys())
        if (prefixes.some((prefix) => path.startsWith(prefix))) this.entries.delete(path);
    } else this.entries.clear();
    this.persist();
  }
  peek(path) {
    const entry = this.entries.get(path);
    if (!entry || this.now() - entry.at >= MAX_AGE) return undefined;
    return structuredClone(entry.data);
  }
  persist() {
    try {
      const entries = [...this.entries].filter(([, entry]) => this.now() - entry.at < MAX_AGE);
      let value = JSON.stringify({ owner: this.owner, entries });
      while (value.length > MAX_CHARACTERS && entries.length) {
        entries.shift();
        value = JSON.stringify({ owner: this.owner, entries });
      }
      if (entries.length) this.storage?.setItem(STORAGE_KEY, value);
      else this.storage?.removeItem(STORAGE_KEY);
    } catch {
      /* Full or disabled storage must not prevent navigation. */
    }
  }
  async read(path, loader, { freshFor = 15000, force = false, waitForFresh = false } = {}) {
    const data = this.peek(path);
    const fresh = data !== undefined && this.now() - this.entries.get(path).at < freshFor;
    if (!force && data !== undefined && (fresh || !waitForFresh)) {
      if (!fresh)
        void this.fill(path, loader).catch((error) => {
          if (error.name !== 'AbortError') this.onError({ path, error });
        });
      return data;
    }
    return structuredClone(await this.fill(path, loader));
  }
  fill(path, loader) {
    if (this.pending.has(path)) return this.pending.get(path);
    const epoch = this.epoch;
    const work = Promise.resolve()
      .then(loader)
      .then((data) => {
        // A read started before a write/sign-out must never restore obsolete data.
        if (epoch !== this.epoch) throw new DOMException('Cache invalidated', 'AbortError');
        const previous = this.peek(path);
        this.entries.delete(path);
        this.entries.set(path, { data: structuredClone(data), at: this.now() });
        while (this.entries.size > MAX_ENTRIES)
          this.entries.delete(this.entries.keys().next().value);
        this.persist();
        this.onUpdate({ path, data: structuredClone(data), previous });
        return data;
      })
      .catch((error) => {
        if (epoch === this.epoch && [401, 403, 404].includes(error.status)) {
          this.entries.delete(path);
          this.persist();
        }
        throw error;
      })
      .finally(() => {
        if (this.pending.get(path) === work) this.pending.delete(path);
      });
    this.pending.set(path, work);
    return work;
  }
}

// Cancel a view's subscription, not the shared request used by prefetch/another view.
export function forConsumer(promise, signal) {
  if (!signal) return promise;
  signal.throwIfAborted();
  return new Promise((resolve, reject) => {
    const abort = () => reject(signal.reason);
    signal.addEventListener('abort', abort, { once: true });
    promise.then(resolve, reject).finally(() => signal.removeEventListener('abort', abort));
  });
}
