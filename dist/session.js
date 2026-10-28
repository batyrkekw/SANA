import { createClient } from './vendor/supabase.js';
let connection;
// Private data lives only in this page's memory, never in a shared HTTP cache.
const reads = new Map();
let readOwner, readEpoch = 0;
export function clearReads() {
  reads.clear();
  readEpoch++;
}
export class APIError extends Error {
  constructor(code, status = 0) {
    super(code);
    this.code = code;
    this.status = status;
  }
}
export function connect() {
  connection ??= (async () => {
    let response;
    try {
      response = await fetch('/api/v1/config', {
        signal: AbortSignal.timeout(10000),
        cache: 'no-store',
      });
    } catch {
      throw new APIError('network');
    }
    if (!response.ok) throw new APIError('network');
    const config = await response.json();
    if (!config.auth_configured) return { client: null, config };
    const client = createClient(config.supabase_url, config.supabase_publishable_key, {
      auth: {
        flowType: 'pkce',
        autoRefreshToken: true,
        persistSession: true,
        detectSessionInUrl: true,
      },
    });
    client.auth.onAuthStateChange((event) => {
      if (event === 'SIGNED_OUT') clearReads();
    });
    return { client, config };
  })();
  return connection;
}
export async function api(path, options = {}, retry = true) {
  options.signal?.throwIfAborted();
  const { client } = await connect();
  const {
    data: { session },
  } = client ? await client.auth.getSession() : { data: { session: null } };
  options.signal?.throwIfAborted();
  if (!session) throw new APIError('authentication_required', 401);
  if (readOwner !== session.user.id) {
    clearReads();
    readOwner = session.user.id;
  }
  const { cacheFor = 0, ...fetchOptions } = options;
  const isRead = !options.method || options.method === 'GET';
  if (!isRead) clearReads();
  const epoch = readEpoch;
  const cached = reads.get(path);
  if (isRead && cacheFor && cached?.expires > Date.now()) return structuredClone(cached.data);
  const headers = new Headers(options.headers);
  headers.set('Authorization', `Bearer ${session.access_token}`);
  if (options.body) headers.set('Content-Type', 'application/json');
  let response;
  try {
    response = await fetch(`/api/v1${path}`, {
      ...fetchOptions,
      headers,
      cache: 'no-store',
      signal: options.signal
        ? AbortSignal.any([options.signal, AbortSignal.timeout(20000)])
        : AbortSignal.timeout(20000),
    });
  } catch {
    options.signal?.throwIfAborted();
    throw new APIError('network');
  }
  if (response.status === 401 && retry) {
    const { data, error } = await client.auth.refreshSession();
    if (!error && data.session) return api(path, options, false);
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    if (response.status === 401) window.dispatchEvent(new Event('sana:expired'));
    throw new APIError(body.error?.code || 'internal_error', response.status);
  }
  if (options.blob) return response.blob();
  const data = response.status === 204 ? null : await response.json();
  options.signal?.throwIfAborted();
  if (!isRead) clearReads();
  // Active jobs need fresh balances/lists on each poll and section change.
  if (isRead && cacheFor && epoch === readEpoch && !data?.tokens?.reserved) {
    if (reads.size >= 40) reads.delete(reads.keys().next().value);
    reads.set(path, { data: structuredClone(data), expires: Date.now() + cacheFor });
  }
  return data;
}
