import { createClient } from './vendor/supabase.js';
let connection;
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
  const headers = new Headers(options.headers);
  headers.set('Authorization', `Bearer ${session.access_token}`);
  if (options.body) headers.set('Content-Type', 'application/json');
  let response;
  try {
    response = await fetch(`/api/v1${path}`, {
      ...options,
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
  return response.status === 204 ? null : response.json();
}
