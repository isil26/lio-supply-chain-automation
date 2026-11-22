const http = require('node:http');
const { createReadStream } = require('node:fs');
const { join } = require('node:path');
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
  const pathname = request.url.split('?')[0];
  if (request.method === 'GET' && /^\/demo\/(index\.html|brand\/manti-logo\.png|assets\/[\w-]+\.(?:js|css))$/.test(pathname)) {
    const asset = createReadStream(join(__dirname, '../../web/dist', pathname));
    asset.on('error', error => {
      if (error.code === 'ENOENT' && pathname === '/demo/index.html') {
        // The Python-only local demo can still open the hosted public dashboard.
        response.writeHead(302, { Location: 'https://soony-manti-live.vercel.app/demo/index.html' });
      } else {
        response.statusCode = 404;
      }
      response.end();
    });
    const types = { html: 'text/html; charset=utf-8', js: 'text/javascript', css: 'text/css', png: 'image/png' };
    response.setHeader('Content-Type', types[pathname.split('.').pop()]);
    response.setHeader('Content-Security-Policy', "default-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'none'; form-action 'none'; frame-ancestors 'none'; base-uri 'none'");
    asset.pipe(response);
    return;
  }
  // Vercel serves this same public logo from its static directory.
  if (request.method === 'GET' && request.url === '/brand/manti-logo.png') {
    const logo = createReadStream(join(__dirname, '../../web/src/desk/manti-logo.png'));
    logo.on('error', () => { response.statusCode = 404; response.end(); });
    response.setHeader('Content-Type', 'image/png');
    response.setHeader('Cache-Control', 'no-cache');
    logo.pipe(response);
    return;
  }
  Promise.resolve(control(request, response)).catch(() => {
    if (!response.headersSent) response.statusCode = 502;
    response.end('The gateway could not handle the request.');
  });
}).listen(port, '127.0.0.1');
