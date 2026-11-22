const http = require('node:http');
const { accounts } = require('../vercel/accounts.cjs');
const control = require('../vercel/control.cjs');

if (!process.env.SOONY_LIVE_UPSTREAM) {
  throw new Error('SOONY_LIVE_UPSTREAM must point to the loopback Python service.');
}
if (!accounts() ||
    !/^[0-9a-f]{64}$/.test(process.env.SOONY_REPLAY_KEY || '')) {
  throw new Error('Configure SOONY_USERS_JSON and session key before exposing this listener.');
}
const port = Number(process.env.SOONY_GATEWAY_PORT || '8790');
http.createServer((request, response) => {
  Promise.resolve(control(request, response)).catch(() => {
    if (!response.headersSent) response.statusCode = 502;
    response.end('The gateway could not handle the request.');
  });
}).listen(port, '127.0.0.1');
