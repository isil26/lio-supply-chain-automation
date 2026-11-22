const fs = require('node:fs');
const net = require('node:net');
const path = require('node:path');
const { Client } = require('ssh2');
const control = require('./control.cjs');

const [host, , publicKey] = fs.readFileSync(path.join(__dirname, 'vm_known_hosts'), 'utf8').trim().split(/\s+/);
const hostKey = Buffer.from(publicKey, 'base64');
let listening;

function forward(socket) {
  const client = new Client();
  socket.on('error', () => client.end());
  socket.once('close', () => client.end());
  client.on('error', () => socket.destroy());
  client.once('close', () => socket.destroy());
  client.once('ready', () => {
    client.forwardOut('127.0.0.1', 0, '127.0.0.1', 8890, (error, stream) => {
      if (error) return socket.destroy();
      stream.on('error', () => socket.destroy());
      socket.pipe(stream).pipe(socket);
    });
  });
  client.connect({
    host, username: 'lio-vercel', privateKey: process.env.LIO_VM_FORWARD_KEY,
    algorithms: { serverHostKey: ['ssh-ed25519'] },
    hostVerifier: key => key.equals(hostKey), readyTimeout: 8000,
  });
}

async function openTransport() {
  if (!process.env.LIO_VM_FORWARD_KEY) throw new Error('Missing VM transport credential');
  const server = net.createServer(forward);
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  server.unref();
  process.env.SOONY_LIVE_UPSTREAM = 'http://127.0.0.1:' + server.address().port;
}

module.exports = async function vmControl(request, response) {
  try {
    listening ||= openTransport().catch(error => { listening = undefined; throw error; });
    await listening;
  } catch {
    response.statusCode = 503;
    return response.end('VM transport unavailable');
  }
  return control(request, response);
};
