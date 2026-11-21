const API_PATH = /^\/api\/(?:dashboard|health|truth|documents|sync|agents\/(?:runs|trace|run|stop)|threads\/[A-F0-9]+\/(?:send|demo-reply)|reply-decisions\/[0-9]{1,12}\/approve|decisions\/[a-f0-9]+\/(?:approve|review)|source\/.+)$/;
const VIEWS = /^\/(?:live|react|assets\/[\w.-]+)?$/;

function liveTarget(url) {
  const rewritten = url.pathname === '/control' ? url.searchParams.get('live') : null;
  const path = rewritten ?? url.pathname;
  let decoded;
  try { decoded = decodeURIComponent(path); } catch { return null; }
  if (decoded.includes('\\') || decoded.split('/').some((segment) => segment === '.' || segment === '..')) return null;
  if (!API_PATH.test(path) && !VIEWS.test(path)) return null;
  if (path === '/api/agents/trace' && url.searchParams.has('run')) {
    return path + '?' + new URLSearchParams({ run: url.searchParams.get('run') });
  }
  return path;
}

async function jsonBody(request) {
  if (!request.headers['content-type']?.startsWith('application/json')) return null;
  if (Number(request.headers['content-length']) > 4096) return null;
  if (request.body !== undefined && request.body !== null) {
    const input = Buffer.isBuffer(request.body) || typeof request.body === 'string'
      ? request.body : JSON.stringify(request.body);
    return Buffer.byteLength(input) <= 4096 ? input : null;
  }
  const parts = [];
  let bytes = 0;
  for await (const chunk of request) {
    bytes += Buffer.byteLength(chunk);
    if (bytes > 4096) return null;
    parts.push(Buffer.from(chunk));
  }
  return Buffer.concat(parts);
}

async function forwardLive(request, response, base, target, token) {
  const method = request.method;
  if (method !== 'GET' && (method !== 'POST' || !target.startsWith('/api/'))) {
    response.statusCode = 405;
    return response.end();
  }
  const headers = {};
  if (token) headers.Authorization = 'Bearer ' + token;
  const body = method === 'POST' ? await jsonBody(request) : undefined;
  if (body === null) {
    response.statusCode = 400;
    return response.end(JSON.stringify({ error: 'Send a JSON request of 4 KB or less.' }));
  }
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  try {
    const origin = new URL(base);
    if (origin.protocol !== 'https:' && !(origin.protocol === 'http:' && origin.hostname === '127.0.0.1')) {
      throw new Error('Invalid upstream URL');
    }
    const upstream = await fetch(new URL(target, origin), {
      method, headers, body, redirect: 'manual', signal: AbortSignal.timeout(25000),
    });
    for (const key of ['Content-Type', 'Content-Security-Policy', 'Content-Disposition']) {
      if (upstream.headers.has(key)) response.setHeader(key, upstream.headers.get(key));
    }
    response.statusCode = upstream.status;
    return response.end(Buffer.from(await upstream.arrayBuffer()));
  } catch {
    response.statusCode = 503;
    response.setHeader('Content-Type', 'application/json; charset=utf-8');
    return response.end(JSON.stringify({ error: 'The live backend is unavailable.' }));
  }
}

module.exports = { liveTarget, forwardLive };
