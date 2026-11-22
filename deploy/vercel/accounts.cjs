const { scrypt, timingSafeEqual } = require('node:crypto');
const { promisify } = require('node:util');

const deriveKey = promisify(scrypt);
const options = { N: 32768, r: 8, p: 3, maxmem: 64 * 1024 * 1024 };
const usernamePattern = /^[\p{L}\p{N}][\p{L}\p{M}\p{N} .@_'-]{0,79}$/u;
const verifierPattern = /^scrypt-v1:([a-f0-9]{32}):([a-f0-9]{64})$/;
const dummy = 'scrypt-v1:' + '0'.repeat(32) + ':' + '0'.repeat(64);
let pending = 0;

function accounts() {
  try {
    const useDemo = process.env.SOONY_DEMO_ACCOUNTS === '1' || !process.env.SOONY_LIVE_UPSTREAM;
    const data = process.env.SOONY_USERS_JSON !== undefined ? JSON.parse(process.env.SOONY_USERS_JSON) :
      useDemo ? require('./demo-users.json') : null;
    if (!data || typeof data !== 'object' || Array.isArray(data)) return null;
    const entries = Object.entries(data);
    if (!entries.length || entries.some(([name, verifier]) =>
      !usernamePattern.test(name) || name.trim() !== name ||
      typeof verifier !== 'string' || !verifierPattern.test(verifier))) return null;
    return new Map(entries);
  } catch {
    return null;
  }
}

async function verifyPassword(verifier, password) {
  if (!password || [...password].length > 128) return false;
  // Bound concurrent memory-hard password checks per gateway instance.
  if (pending >= 4) return null;
  pending++;
  try {
    const [, salt, hash] = verifierPattern.exec(verifier || dummy);
    const computed = await deriveKey(password, Buffer.from(salt, 'hex'), 32, options);
    return timingSafeEqual(computed, Buffer.from(hash, 'hex')) && Boolean(verifier);
  } finally {
    pending--;
  }
}

module.exports = { accounts, verifyPassword };
