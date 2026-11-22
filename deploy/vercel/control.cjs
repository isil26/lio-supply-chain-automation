const { createDecipheriv, createHash, createHmac, randomBytes, timingSafeEqual } = require('node:crypto');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { liveTarget, forwardLive } = require('./live.cjs');

const { accounts, verifyPassword } = require('./accounts.cjs');

const COOKIE = '__Host-soony-replay';
const SHARED_ACCOUNT = 'Shared team login';
const SESSION_SECONDS = 8 * 60 * 60;
const operations = new Map([
  ['/', 'home'], ['/login', 'login'], ['/logout', 'logout'],
  ['/api/dashboard', 'dashboard'], ['/api/sync', 'sync'], ['/api/replay/reset', 'reset'],
  ['/api/session', 'session'],
  ['/api/uploads', 'uploads'],
]);
let replay;

function equal(left, right) {
  const a = Buffer.from(left);
  const b = Buffer.from(right);
  return a.length === b.length && timingSafeEqual(a, b);
}

function signature(body, key, verifier) {
  return createHmac('sha256', key).update(`soony-session-v2:${verifier}:${body}`).digest('base64url');
}

function sharedSignature(body, key) {
  return createHmac('sha256', key).update(`soony-replay-session-v1:${body}`).digest('base64url');
}

function sessionFrom(request, key, users, sharedLogin) {
  const cookie = (request.headers.cookie || '').split(';').map(part => part.trim())
    .find(part => part.startsWith(`${COOKIE}=`));
  const token = cookie?.slice(COOKIE.length + 1) || '';
  if (sharedLogin) {
    const parts = /^(\d{10})\.(before|after)\.([\w-]{22})\.([\w-]{43})$/.exec(token);
    if (!parts) return null;
    const [, expiration, phase, nonce, provided] = parts;
    const body = `${expiration}.${phase}.${nonce}`;
    if (Number(expiration) <= Date.now() / 1000 || !equal(provided, sharedSignature(body, key))) return null;
    return { expiration: Number(expiration), phase, nonce, user: SHARED_ACCOUNT };
  }
  const match = /^(\d{10})\.(before|after)\.([\w-]{22})\.([\w-]{1,430})\.([\w-]{43})$/.exec(token);
  if (!match) return null;
  const [, expiration, phase, nonce, encodedUser, provided] = match;
  const user = Buffer.from(encodedUser, 'base64url').toString('utf8');
  const verifier = users.get(user);
  if (!verifier || Number(expiration) <= Date.now() / 1000 ||
      !equal(provided, signature(token.slice(0, token.lastIndexOf('.')), key, verifier))) return null;
  return { expiration: Number(expiration), phase, nonce, user };
}

function setSession(response, key, session, users, sharedLogin) {
  let token = '';
  if (session && sharedLogin) {
    const body = `${session.expiration}.${session.phase}.${session.nonce}`;
    token = `${body}.${sharedSignature(body, key)}`;
  } else if (session) {
    const encodedUser = Buffer.from(session.user).toString('base64url');
    const body = `${session.expiration}.${session.phase}.${session.nonce}.${encodedUser}`;
    token = `${body}.${signature(body, key, users.get(session.user))}`;
  }
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

function loginReturn(query) {
  const params = new URLSearchParams();
  if (query.get("mail") === "1") params.set("mail", "1");
  const thread = query.get("thread") || "";
  if (/^[A-F0-9]{1,32}$/.test(thread)) params.set("thread", thread);
  return params.size ? "/?" + params.toString() : "/";
}

function safeReturn(path) {
  if (["/live", "/react", "/game-cards"].includes(path)) return path;
  if (typeof path !== "string" || !/^\/(?:\?(?:mail=1(?:&thread=[A-F0-9]{1,32})?|thread=[A-F0-9]{1,32}))?$/.test(path)) return "/";
  return path;
}

function loginPage(response, failed = false, next = "/", allowShared = false) {
  const template = readFileSync(join(__dirname, 'login.html'), 'utf8');
  const page = process.env.SOONY_LIVE_UPSTREAM
    ? template.replace('private supplier-drop replay', 'private live control room') : template;
  respond(response, failed ? 401 : 200, page
    .replace(/<!-- SHARED_LOGIN_START -->[\s\S]*?<!-- SHARED_LOGIN_END -->/, block => allowShared ? block : '')
    .replaceAll('<!-- LOGIN_RETURN -->', '<input type="hidden" name="next" value="' + next.replace(/&/g, "&amp;") + '">')
    .replace('<!-- LOGIN_ERROR -->', failed ? '<p role="alert">The username or password is incorrect.</p>' : ''), 'text/html; charset=utf-8');
}

async function getLogin(request) {
  if (Number(request.headers['content-length']) > 4096 || !request.headers['content-type']?.startsWith('application/x-www-form-urlencoded')) {
    return new URLSearchParams();
  }
  if (typeof request.body === 'object' && request.body !== null && !Buffer.isBuffer(request.body)) {
    return new URLSearchParams(['username', 'password', 'next'].map(name =>
      [name, typeof request.body[name] === 'string' ? request.body[name] : '']));
  }
  let body = request.body || '';
  if (!body) {
    const chunks = [];
    let length = 0;
    for await (const chunk of request) {
      length += Buffer.byteLength(chunk);
      if (length > 4096) return new URLSearchParams();
      chunks.push(Buffer.from(chunk));
    }
    body = Buffer.concat(chunks);
  }
  if (Buffer.byteLength(body) > 4096) return new URLSearchParams();
  return new URLSearchParams(String(body));
}

module.exports = async function control(request, response, mode) {
  const sharedLogin = mode === "production-team-password";
  response.setHeader('Cache-Control', 'private, no-store');
  response.setHeader('Vercel-CDN-Cache-Control', 'no-store');
  response.setHeader('X-Content-Type-Options', 'nosniff');
  // Native form submissions need the same-origin Origin header checked below.
  response.setHeader('Referrer-Policy', 'same-origin');
  response.setHeader('X-Robots-Tag', 'noindex, nofollow');
  response.setHeader('Content-Security-Policy', "default-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'");

  const teamHash = process.env.SOONY_TEAM_PASSWORD_HASH;
  const allowShared = mode === "production-team-accounts" && /^[a-f0-9]{64}$/.test(teamHash || '');
  const users = sharedLogin
    ? (/^[a-f0-9]{64}$/.test(teamHash || '') ? new Map([[SHARED_ACCOUNT, teamHash]]) : null)
    : accounts();
  const hexKey = process.env.SOONY_REPLAY_KEY;
  if (!users || !/^[a-f0-9]{64}$/.test(hexKey || '')) {
    return respond(response, 503, { error: 'Team dashboard is unavailable' });
  }
  const key = Buffer.from(hexKey, 'hex');
  const url = new URL(request.url, `https://${request.headers.host}`);
  const rewritten = url.pathname === '/control';
  const livePath = rewritten ? url.searchParams.get('live') : null;
  const op = operations.get(livePath || url.pathname) ?? (rewritten && !livePath ? url.searchParams.get('op') : null);
  const method = request.method;
  const upstream = process.env.SOONY_LIVE_UPSTREAM;
  const target = upstream ? (op === 'home' ? '/' : liveTarget(url, process.env.SOONY_LOCAL_DASHBOARD === '1')) : null;
  const gatewayToken = process.env.SOONY_LIVE_GATEWAY_TOKEN;
  const trustedGateway = Boolean(!sharedLogin && target && gatewayToken &&
    equal(request.headers.authorization || '', 'Bearer ' + gatewayToken));
  const session = sessionFrom(request, key, users, sharedLogin) ||
    (allowShared ? sessionFrom(request, key, users, true) : null);
  let user = session?.user ?? null;
  if (trustedGateway) {
    // Only a credentialed relay can assert an account. Browser headers are ignored.
    const forwarded = request.headers['x-soony-user'] || '';
    const name = Buffer.from(forwarded, 'base64url').toString('utf8');
    // A password-only front gateway authenticates the whole team. Attribute
    // its requests to one provisioned account, never to a named signer.
    const shared = process.env.SOONY_SHARED_EDGE_ACCOUNT;
    user = !forwarded && shared && users.has(shared) ? shared : users.has(name) ? name : null;
  }
  if (method === 'POST') {
    const route = target?.split('?')[0] ||
      [...operations].find(([, operation]) => operation === op)?.[0];
    // Never log arbitrary paths, query strings, input bodies, session IDs or credentials.
    const action = route?.startsWith('/api/source/') ? '/api/source' : route || 'unknown';
    response.once('finish', () => console.info(JSON.stringify({
      event: 'control_room.activity', at: new Date().toISOString(), user, action, status: response.statusCode,
    })));
    const localOrigin = ['127.0.0.1', 'localhost'].includes(url.hostname) && request.headers.origin === 'http://' + url.host;
    if (!trustedGateway && request.headers.origin !== url.origin && !localOrigin) {
      return respond(response, 403, { error: 'Use the team dashboard to submit this request' });
    }
  }
  if (op === 'login' && method === 'POST') {
    user = null;
    const credentials = await getLogin(request);
    const next = upstream ? safeReturn(credentials.get("next")) : "/";
    const passwordOnly = sharedLogin || (allowShared && !credentials.get('username'));
    const name = passwordOnly ? SHARED_ACCOUNT : credentials.get('username');
    const password = credentials.get('password') || '';
    const verified = passwordOnly
      ? Boolean(password) && equal(createHash('sha256').update(password).digest('hex'), teamHash)
      : await verifyPassword(users.get(name), password);
    if (verified === null) return respond(response, 429, { error: 'Login is busy. Try again shortly.' });
    if (!verified) return loginPage(response, true, next, allowShared);
    user = name;
    setSession(response, key, {
      expiration: Math.floor(Date.now() / 1000) + SESSION_SECONDS,
      phase: 'before',
      nonce: randomBytes(16).toString('base64url'),
      user,
    }, users, passwordOnly);
    response.setHeader('Location', next);
    return respond(response, 303, '');
  }

  if ((op === 'home' || op === 'login' || target === '/live' || target === '/react' || target === '/game-cards') && method === 'GET' && !user && !trustedGateway) {
    return loginPage(response, false, upstream ? (["/live", "/react", "/game-cards"].includes(target) ? target : loginReturn(url.searchParams)) : "/", allowShared);
  }
  const serviceRead = trustedGateway && method === 'GET' && process.env.SOONY_DEMO_ACCOUNTS !== '0';
  if (!user && !serviceRead) return respond(response, 401, { error: 'Team login required' });
  if (op === 'session' && method === 'GET') return respond(response, 200, { user });
  if (op === 'uploads') {
    if (!user) return respond(response, 401, { error: 'Team login required' });
    const uploadUpstream = upstream || process.env.SOONY_UPLOAD_UPSTREAM;
    if (!uploadUpstream) {
      return method === 'GET' ? respond(response, 200, { status: 'unavailable' }) :
        respond(response, 503, { error: 'Upload processing is unavailable.' });
    }
    const nonce = trustedGateway ? request.headers['x-soony-upload-session'] : session?.nonce;
    if (typeof nonce !== 'string' || !/^[A-Za-z0-9_-]{22,64}$/.test(nonce)) {
      return respond(response, 403, { error: 'Upload session required.' });
    }
    const token = upstream ? process.env.SOONY_LIVE_UPSTREAM_TOKEN : process.env.SOONY_UPLOAD_UPSTREAM_TOKEN;
    return forwardLive(request, response, uploadUpstream, '/api/uploads', token, user, nonce);
  }
  if (target) return forwardLive(request, response, upstream, target, process.env.SOONY_LIVE_UPSTREAM_TOKEN, user);
  if (op === 'home' && method === 'GET') {
    return respond(response, 200, readFileSync(join(__dirname, 'app.html')), 'text/html; charset=utf-8');
  }
  if (op === 'logout' && method === 'POST') {
    setSession(response, key, null);
    response.setHeader('Location', '/');
    return respond(response, 303, '');
  }
  if (op === 'dashboard' && method === 'GET') {
    return respond(response, 200, { ...dashboard(session.phase, key), currentUser: session.user });
  }
  if ((op === 'sync' || op === 'reset') && method === 'POST') {
    const phase = op === 'sync' ? 'after' : 'before';
    setSession(response, key, { ...session, phase }, users, sharedLogin);
    return respond(response, 200, { ok: true });
  }
  return respond(response, 404, { error: 'Route unavailable' });
};
