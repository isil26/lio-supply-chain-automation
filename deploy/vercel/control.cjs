const { createDecipheriv, createHash, createHmac, randomBytes, timingSafeEqual } = require('node:crypto');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { liveTarget, forwardLive } = require('./live.cjs');

const COOKIE = '__Host-soony-replay';
const SESSION_SECONDS = 8 * 60 * 60;
const operations = new Map([
  ['/', 'home'], ['/login', 'login'], ['/logout', 'logout'],
  ['/api/dashboard', 'dashboard'], ['/api/sync', 'sync'], ['/api/replay/reset', 'reset'],
]);
let replay;

function equal(left, right) {
  const a = Buffer.from(left);
  const b = Buffer.from(right);
  return a.length === b.length && timingSafeEqual(a, b);
}

function signature(body, key) {
  return createHmac('sha256', key).update(`soony-replay-session-v1:${body}`).digest('base64url');
}

function sessionFrom(request, key) {
  const cookie = (request.headers.cookie || '').split(';').map(part => part.trim())
    .find(part => part.startsWith(`${COOKIE}=`));
  const token = cookie?.slice(COOKIE.length + 1) || '';
  const match = /^(\d{10})\.(before|after)\.([\w-]{22})\.([\w-]{43})$/.exec(token);
  if (!match) return null;
  const [, expiration, phase, nonce, provided] = match;
  if (Number(expiration) <= Date.now() / 1000 || !equal(provided, signature(`${expiration}.${phase}.${nonce}`, key))) {
    return null;
  }
  return { expiration: Number(expiration), phase, nonce };
}

function setSession(response, key, session) {
  const body = session ? `${session.expiration}.${session.phase}.${session.nonce}` : '';
  const token = session ? `${body}.${signature(body, key)}` : '';
  const age = session ? Math.max(0, session.expiration - Math.floor(Date.now() / 1000)) : 0;
  response.setHeader('Set-Cookie', `${COOKIE}=${token}; Path=/; Max-Age=${age}; Secure; HttpOnly; SameSite=Strict`);
}

function dashboard(phase, key) {
  if (!replay) {
    const bundle = readFileSync(join(__dirname, 'replay.enc'));
    const decipher = createDecipheriv('aes-256-gcm', key, bundle.subarray(0, 12));
    decipher.setAuthTag(bundle.subarray(12, 28));
    replay = JSON.parse(Buffer.concat([decipher.update(bundle.subarray(28)), decipher.final()]).toString('utf8'));
  }
  return replay[phase];
}

function respond(response, status, body, type = 'application/json; charset=utf-8') {
  response.statusCode = status;
  response.setHeader('Content-Type', type);
  response.end(typeof body === 'string' || Buffer.isBuffer(body) ? body : JSON.stringify(body));
}

function loginPage(response, failed = false) {
  const template = readFileSync(join(__dirname, 'login.html'), 'utf8');
  const page = process.env.SOONY_LIVE_UPSTREAM
    ? template.replace('private supplier-drop replay', 'private live control room') : template;
  respond(response, failed ? 401 : 200, page.replace('<!-- LOGIN_ERROR -->', failed ? '<p role="alert">The team password is incorrect.</p>' : ''), 'text/html; charset=utf-8');
}

async function getPassword(request) {
  if (Number(request.headers['content-length']) > 1024 || !request.headers['content-type']?.startsWith('application/x-www-form-urlencoded')) {
    return '';
  }
  if (typeof request.body === 'object' && request.body !== null) {
    return typeof request.body.password === 'string' ? request.body.password : '';
  }
  let body = request.body || '';
  if (!body) {
    for await (const chunk of request) {
      body += chunk;
      if (body.length > 1024) return '';
    }
  }
  return new URLSearchParams(body).get('password') || '';
}

module.exports = async function control(request, response) {
  response.setHeader('Cache-Control', 'private, no-store');
  response.setHeader('Vercel-CDN-Cache-Control', 'no-store');
  response.setHeader('X-Content-Type-Options', 'nosniff');
  // Native form submissions need the same-origin Origin header checked below.
  response.setHeader('Referrer-Policy', 'same-origin');
  response.setHeader('X-Robots-Tag', 'noindex, nofollow');
  response.setHeader('Content-Security-Policy', "default-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'");

  const { SOONY_TEAM_PASSWORD_HASH: passwordHash, SOONY_REPLAY_KEY: hexKey } = process.env;
  if (!/^[a-f0-9]{64}$/.test(passwordHash || '') || !/^[a-f0-9]{64}$/.test(hexKey || '')) {
    return respond(response, 503, { error: 'Team dashboard is unavailable' });
  }
  const key = Buffer.from(hexKey, 'hex');
  const url = new URL(request.url, `https://${request.headers.host}`);
  const op = operations.get(url.pathname) ?? (url.pathname === '/control' ? url.searchParams.get('op') : null);
  const method = request.method;

  const upstream = process.env.SOONY_LIVE_UPSTREAM;
  const target = upstream ? liveTarget(url) : null;
  const gatewayToken = process.env.SOONY_LIVE_GATEWAY_TOKEN;
  const trustedGateway = Boolean(target && gatewayToken && equal(request.headers.authorization || '', 'Bearer ' + gatewayToken));
  if (method === 'POST' && !trustedGateway && request.headers.origin !== url.origin) {
    return respond(response, 403, { error: 'Use the team dashboard to submit this request' });
  }
  if (op === 'login' && method === 'POST') {
    const password = await getPassword(request);
    const candidate = createHash('sha256').update(password).digest('hex');
    if (!equal(candidate, passwordHash)) return loginPage(response, true);
    setSession(response, key, {
      expiration: Math.floor(Date.now() / 1000) + SESSION_SECONDS,
      phase: 'before',
      nonce: randomBytes(16).toString('base64url'),
    });
    response.setHeader('Location', '/');
    return respond(response, 303, '');
  }

  const session = sessionFrom(request, key);
  if (op === 'home' && method === 'GET' && !session && !trustedGateway) {
    return loginPage(response);
  }
  if (!session && !trustedGateway) return respond(response, 401, { error: 'Team login required' });
  if (target) return forwardLive(request, response, upstream, target, process.env.SOONY_LIVE_UPSTREAM_TOKEN);
  if (op === 'home' && method === 'GET') {
    return respond(response, 200, readFileSync(join(__dirname, 'app.html')), 'text/html; charset=utf-8');
  }
  if (op === 'logout' && method === 'POST') {
    setSession(response, key, null);
    response.setHeader('Location', '/');
    return respond(response, 303, '');
  }
  if (op === 'dashboard' && method === 'GET') {
    return respond(response, 200, dashboard(session.phase, key));
  }
  if ((op === 'sync' || op === 'reset') && method === 'POST') {
    const phase = op === 'sync' ? 'after' : 'before';
    setSession(response, key, { ...session, phase });
    return respond(response, 200, { ok: true });
  }
  return respond(response, 404, { error: 'Route unavailable' });
};
