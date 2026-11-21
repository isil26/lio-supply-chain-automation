const assert = require('node:assert/strict');
const { createHash } = require('node:crypto');
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
    response.end(JSON.stringify({ path: request.url }));
  }, t);
  Object.assign(process.env, {
    SOONY_TEAM_PASSWORD_HASH: createHash('sha256').update('test-team-password').digest('hex'),
    SOONY_REPLAY_KEY: 'a'.repeat(64),
    SOONY_LIVE_UPSTREAM: backend,
    SOONY_LIVE_GATEWAY_TOKEN: 'test-preview-token',
  });
  const gateway = await listener(control, t);
  assert.equal((await fetch(gateway + '/api/dashboard')).status, 401);
  assert.equal(received, 0);
  const origin = gateway.replace('http:', 'https:');
  const login = await fetch(gateway + '/login', {
    method: 'POST', headers: { origin }, body: new URLSearchParams({ password: 'test-team-password' }),
    redirect: 'manual',
  });
  assert.equal(login.status, 303);
  const cookie = login.headers.get('set-cookie').split(';')[0];
  const headers = { cookie, 'content-type': 'application/json' };
  const read = await fetch(gateway + '/api/dashboard', { headers });
  assert.equal(read.status, 200);
  assert.deepEqual(await read.json(), { path: '/api/dashboard' });
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
