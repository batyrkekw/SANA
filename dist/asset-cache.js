// Private, immutable images live only in this tab's memory, never shared HTTP storage.
export class AssetCache {
  constructor({ maxBytes = 16 * 1024 * 1024, maxEntries = 48, concurrency = 2 } = {}) {
    Object.assign(this, { maxBytes, maxEntries, concurrency });
    this.entries = new Map();
    this.pending = new Map();
    this.queue = [];
    this.bytes = 0;
    this.active = 0;
    this.epoch = 0;
  }
  identify(owner) {
    if (owner === this.owner) return;
    this.owner = owner;
    this.clear();
  }
  clear() {
    this.epoch++;
    this.entries.clear();
    this.pending.clear();
    this.bytes = 0;
    // Wake queued work so it can reject against its old identity before fetching.
    this.drain();
  }
  drain() {
    // A newly opened lesson takes priority over covers queued by an old view.
    this.queue.sort((a, b) => b.priority - a.priority);
    while (this.active < this.concurrency && this.queue.length) this.queue.shift().start();
  }
  read(path, loader, priority = 0) {
    const cached = this.entries.get(path);
    if (cached) {
      this.entries.delete(path);
      this.entries.set(path, cached);
      return Promise.resolve(cached);
    }
    if (this.pending.has(path)) {
      const queued = this.queue.find((item) => item.path === path);
      if (queued) queued.priority = Math.max(queued.priority, priority);
      return this.pending.get(path);
    }
    const epoch = this.epoch;
    const valid = () => {
      if (epoch !== this.epoch) throw new DOMException('Account changed', 'AbortError');
    };
    const work = new Promise((resolve, reject) => {
      this.queue.push({
        path,
        priority,
        start: () => {
          this.active++;
          Promise.resolve()
            .then(() => {
              valid();
              return loader();
            })
            .then((blob) => {
              valid();
              if (
                !this.owner ||
                !(blob instanceof Blob) ||
                !/^image\/(png|jpeg|webp)$/.test(blob.type)
              )
                throw new Error('Invalid private image');
              if (blob.size <= this.maxBytes) {
                while (
                  this.entries.size &&
                  (this.bytes + blob.size > this.maxBytes || this.entries.size >= this.maxEntries)
                ) {
                  const oldest = this.entries.keys().next().value;
                  this.bytes -= this.entries.get(oldest).size;
                  this.entries.delete(oldest);
                }
                this.entries.set(path, blob);
                this.bytes += blob.size;
              }
              resolve(blob);
            })
            .catch(reject)
            .finally(() => {
              this.active--;
              this.drain();
            });
        },
      });
    }).finally(() => {
      if (this.pending.get(path) === work) this.pending.delete(path);
    });
    this.pending.set(path, work);
    this.drain();
    return work;
  }
}
