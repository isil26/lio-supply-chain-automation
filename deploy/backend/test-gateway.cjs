const assert = require('node:assert/strict');
const demoUsers = require('../vercel/demo-users.json');
const { createServer } = require('node:http');
const test = require('node:test');
const control = require('../vercel/control.cjs');

async function listener(handler, context) {
  const server = createServer(handler);
  context.after(() => server.close());
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  return 'http://127.0.0.1:' + server.address().port;
}

test('live gateway requires team sign-in and forwards authorized JSON', async (t) => {
  let received = 0;
  const backend = await listener((request, response) => {
    received += 1;
    response.end(JSON.stringify({ path: request.url, user: Buffer.from(request.headers['x-soony-user'] || '', 'base64url').toString() }));
  }, t);
  Object.assign(process.env, {
    SOONY_USERS_JSON: JSON.stringify(demoUsers),
    SOONY_REPLAY_KEY: 'a'.repeat(64),
    SOONY_LIVE_UPSTREAM: backend,
    SOONY_LIVE_GATEWAY_TOKEN: 'test-preview-token',
  });
  const gateway = await listener(control, t);
  assert.equal((await fetch(gateway + '/api/dashboard')).status, 401);
  assert.equal(received, 0);
  const origin = gateway.replace('http:', 'https:');
  const login = await fetch(gateway + '/login', {
    method: 'POST', headers: { origin },
    body: new URLSearchParams({ username: 'isil', password: '12345', next: '/?mail=1&thread=AB12' }),
    redirect: 'manual',
  });
  assert.equal(login.status, 303);
  assert.equal(login.headers.get('location'), '/?mail=1&thread=AB12');
  const cookie = login.headers.get('set-cookie').split(';')[0];
  const headers = { cookie, 'content-type': 'application/json', 'x-soony-user': Buffer.from('leo').toString('base64url') };
  const read = await fetch(gateway + '/api/dashboard', { headers });
  assert.equal(read.status, 200);
  assert.deepEqual(await read.json(), { path: '/api/dashboard', user: 'isil' });
  const invalid = await fetch(gateway + '/api/sync', {
    method: 'POST', headers: { ...headers, origin: 'https://unrelated.invalid' }, body: '{}',
  });
  assert.equal(invalid.status, 403);
  const valid = await fetch(gateway + '/api/sync', {
    method: 'POST', headers: { ...headers, origin }, body: '{}',
  });
  assert.equal(valid.status, 200);
  assert.equal((await fetch(gateway + '/control?live=%2Fapi%2Fagents%2Ftrace&run=42', {
    headers: { authorization: 'Bearer test-preview-token' },
  })).status, 200);
  assert.equal((await fetch(gateway + '/snapshot/agent_run.json', { headers })).status, 404);
  assert.equal(received, 3);
});

test('demo accounts, session isolation, audit records and revocation', async (t) => {
  delete process.env.SOONY_LIVE_UPSTREAM;
  delete process.env.SOONY_USERS_JSON;
  process.env.SOONY_REPLAY_KEY = 'b'.repeat(64);
  const records = [];
  t.mock.method(console, 'info', line => records.push(JSON.parse(line)));
  const site = await listener(control, t);
  const login = (username, password) => fetch(site + '/login', {
    method: 'POST', headers: { origin: site }, redirect: 'manual',
    body: new URLSearchParams({ username, password }),
  });
  assert.equal((await fetch(site + '/api/session')).status, 401);
  assert.equal((await login('unknown', '12345')).status, 401);
  assert.equal((await login('murat', 'wrong-password')).status, 401);
  const cookies = new Map();
  for (const username of ['isil', 'murat', 'nick', 'leo', 'gulsah']) {
    const signedIn = await login(username, '12345');
    assert.equal(signedIn.status, 303);
    const cookie = signedIn.headers.get('set-cookie').split(';')[0];
    cookies.set(username, cookie);
    const headers = { cookie, origin: site };
    assert.deepEqual(await (await fetch(site + '/api/session', { headers })).json(), { user: username });
    assert.equal((await fetch(site + '/api/sync', { method: 'POST', headers })).status, 200);
  }
  assert.deepEqual(records.filter(row => row.action === '/api/sync').map(row => row.user), [...cookies.keys()]);
  assert.equal(records.filter(row => row.action === '/login' && row.status === 401 && row.user === null).length, 2);
  assert.ok(records.every(row => Object.keys(row).sort().join() === 'action,at,event,status,user'));
  const cookie = cookies.get('isil');
  const forged = cookie.replace(Buffer.from('isil').toString('base64url'), Buffer.from('nick').toString('base64url'));
  assert.equal((await fetch(site + '/api/session', { headers: { cookie: forged } })).status, 401);
  const logout = await fetch(site + '/logout', { method: 'POST', headers: { cookie, origin: site }, redirect: 'manual' });
  assert.match(logout.headers.get('set-cookie'), /Max-Age=0/);
  assert.equal(records.at(-1).user, 'isil');
  process.env.SOONY_USERS_JSON = JSON.stringify({ nick: demoUsers.nick });
  assert.equal((await fetch(site + '/api/session', { headers: { cookie } })).status, 401);
  assert.equal((await fetch(site + '/api/session', { headers: { cookie: cookies.get('nick') } })).status, 200);
  process.env.SOONY_USERS_JSON = 'invalid';
  assert.equal((await login('nick', '12345')).status, 503);
});

test('the live relay requires a provisioned account to forward a write', async (t) => {
  let actor;
  const backend = await listener((req, res) => {
    actor = Buffer.from(req.headers['x-soony-user'], 'base64url').toString();
    res.end('{}');
  }, t);
  Object.assign(process.env, {
    SOONY_LIVE_UPSTREAM: backend, SOONY_REPLAY_KEY: 'd'.repeat(64),
    SOONY_USERS_JSON: JSON.stringify(demoUsers), SOONY_LIVE_GATEWAY_TOKEN: 'test-relay',
  });
  const site = await listener(control, t);
  const headers = { authorization: 'Bearer test-relay', 'content-type': 'application/json' };
  const send = () => fetch(site + '/api/sync', { method: 'POST', headers, body: '{}' });
  assert.equal((await send()).status, 401);
  headers['x-soony-user'] = Buffer.from('murat').toString('base64url');
  assert.equal((await send()).status, 200);
  assert.equal(actor, 'murat');
  // The password-only production edge maps only an authenticated, unnamed
  // request to its dedicated shared principal. Named accounts keep their identity.
  process.env.SOONY_USERS_JSON = JSON.stringify({ ...demoUsers, 'Shared team login': demoUsers.nick });
  process.env.SOONY_SHARED_EDGE_ACCOUNT = 'Shared team login';
  assert.equal((await send()).status, 200);
  assert.equal(actor, 'murat');
  delete headers['x-soony-user'];
  assert.equal((await send()).status, 200);
  assert.equal(actor, 'Shared team login');
  delete process.env.SOONY_SHARED_EDGE_ACCOUNT;
  delete process.env.SOONY_USERS_JSON;
  delete process.env.SOONY_DEMO_ACCOUNTS;
  assert.equal((await send()).status, 503);
});
