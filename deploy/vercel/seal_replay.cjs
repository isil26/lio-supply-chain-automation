const { createCipheriv, randomBytes } = require('node:crypto');
const { readFileSync, writeFileSync } = require('node:fs');

const [, , keyPath, outputPath] = process.argv;
const key = Buffer.from(readFileSync(keyPath, 'utf8').trim(), 'hex');
if (key.length !== 32) throw new Error('A 32-byte replay encryption key is required');
const nonce = randomBytes(12);
const cipher = createCipheriv('aes-256-gcm', key, nonce);
const ciphertext = Buffer.concat([cipher.update(readFileSync(0)), cipher.final()]);
writeFileSync(outputPath, Buffer.concat([nonce, cipher.getAuthTag(), ciphertext]), { mode: 0o600 });
